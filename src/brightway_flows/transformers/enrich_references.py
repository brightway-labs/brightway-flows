"""Add ChEBI/PubChem properties and external references to flows."""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass
from enum import StrEnum
from typing import Any
from urllib.parse import parse_qs, urlparse

import orjson
import structlog
from chemformula import ChemFormula

from brightway_flows.domain.flow import Flow
from brightway_flows.flow_layers.contested_cas import Verdict as ContestedVerdict
from brightway_flows.flow_layers.contested_cas import (
    load_decisions as load_contested_cas_decisions,
)
from brightway_flows.chem import ConversionRefusal
from brightway_flows.domain.attestation import attest, prune
from brightway_flows.domain.common import Provenance
from brightway_flows.domain import vocabulary
from brightway_flows.domain.vocabulary import (
    CHEMROF_ELEMENTAL_CHARGE,
    CHEMROF_MOLECULAR_MASS,
    CHEMROF_MONOISOTOPIC_MASS,
    PROV_WAS_GENERATED_BY_CURIE,
    QUDT_HAS_UNIT,
    RDFS_LABEL_CURIE,
    UNIT_IRI_GM_PER_MOL,
    UNIT_IRI_NUM,
)
from brightway_flows.filesystem import (
    PUBCHEM_DATA_FILEPATH,
    PUBCHEM_ELEMENTS_CACHE_FILEPATH,
)
from brightway_flows.chem import (
    standard_inchikey_from_inchi,
    states_more_stereochemistry,
)
from brightway_flows.domain.inchikey import (
    StructureComparison,
    compare_structures,
    parse_inchikey,
    same_skeleton,
    structure_identity,
    without_redundant_flat_keys,
)
from brightway_flows.integrations.chebi import load_chebi_index
from brightway_flows.integrations.commonchemistry import (
    CommonChemistryIndex,
    StructureRuling,
    StructureRulingVerdict,
    load_commonchemistry_index,
    load_structure_decisions,
)
from brightway_flows.domain.labels import flow_label_value, strip_markup
from brightway_flows.pipeline import Change, Transformer
from brightway_flows.pipeline.review_records import (
    ReviewQueue,
    ReviewQueueItem,
    Severity,
)

logger = structlog.get_logger(__name__)

#: The heading PubChem files a compound's registry CAS numbers under, in the
#: "Other Identifiers" section of its PUG View record.
CURATED_CAS_HEADING = "CAS"

#: What each kind of surviving structure disagreement is asking.  Written out
#: per kind rather than assembled from fragments, because they want different
#: things from a curator and a title that blurs them is the whole failure #42
#: was reported with -- and the whole of #54, where a difference in charge was
#: put to a curator as a question about shape.
_STEREO_DISAGREEMENT_TITLES = {
    "lost": (
        "{cas}: CAS gives this number a stereochemistry ({theirs}) and the "
        "structure published for it is flat ({ours}){fix}"
    ),
    "conflict": (
        "{cas}: CAS publishes {theirs} and the structure published for it is "
        "{ours} -- same skeleton, different stereochemistry, both specific, "
        "and each states an arrangement the other contradicts"
    ),
    "cas-undetermined": (
        "{cas}: CAS leaves undetermined an arrangement the structure published "
        "for it states ({ours} against {theirs}), and the two agree on every "
        "one both state -- a gap in the registry's record, not a disagreement"
    ),
    "ours-undetermined": (
        "{cas}: the structure published for it leaves undetermined an "
        "arrangement CAS states ({ours} against {theirs}), and the two agree on "
        "every one both state, so the published key names a broader substance "
        "than the number does{fix}"
    ),
    "incomparable": (
        "{cas}: CAS's structure for this number ({theirs}) {because}, so it "
        "cannot be compared with {ours}.  Not known to be a disagreement"
    ),
    "restored": (
        "{cas}: no source held the stereochemistry CAS states ({theirs}), so "
        "the structure published for it was flat ({ours}); the registry's "
        "structure has been read and published in its place{fix}"
    ),
    "superseded": (
        "{cas}: {ours} withdrawn -- another key on the same skeleton is the "
        "structure CAS registers for this number, so the two were one "
        "substance published under two identities{fix}"
    ),
    "protonation": (
        "{cas}: CAS publishes {theirs} and the structure published for it is "
        "{ours} -- the same skeleton in a different protonation state, an acid "
        "and its ion.  A difference in the substance, not in its "
        "stereochemistry"
    ),
    "protonation-withdrawn": (
        "{cas}: {ours} withdrawn -- it is the structure CAS registers for this "
        "number with hydrogen ions added or taken away, so the object was "
        "publishing an acid and its ion in one identity field{fix}"
    ),
}

#: What each kind asks of a reader.  `BLOCKING` where the pipeline will not act
#: and says so; `REVIEW` where it acted by *withdrawing* a structure, which is
#: what every other exclusion queue here reports at; `INFO` where there is
#: nothing to do -- `incomparable` is not a disagreement, `restored` is one the
#: pipeline has already settled, and `cas-undetermined` is settled by a rule
#: rather than by a curator: a record that assigns every centre is not
#: contradicted by one that leaves some undetermined, when the two agree on
#: every centre both assign.  All of them are reported anyway so the next reader
#: does not rediscover them as defects.
_STEREO_DISAGREEMENT_SEVERITIES = {
    "incomparable": Severity.INFO,
    "restored": Severity.INFO,
    "cas-undetermined": Severity.INFO,
    "superseded": Severity.REVIEW,
    "protonation-withdrawn": Severity.REVIEW,
}

#: Why an `incomparable` row could not be answered, in the reader's terms.  Read
#: from the refusal rather than assumed: `RELATIVE` is the usual cause and was
#: being printed for every refusal, including the isotope-labelled single atoms
#: whose keys agreed with ours exactly (#55).
_STEREO_CONVERSION_REASONS = {
    ConversionRefusal.RELATIVE: (
        "states a relative or racemic stereochemistry, which no standard "
        "InChIKey can express"
    ),
    ConversionRefusal.ALTERED: (
        "cannot be read back without altering it -- the isotopic layer of a "
        "lone labelled atom is lost on the round trip"
    ),
    ConversionRefusal.UNREADABLE: "could not be read",
}

#: When the reason was not recorded at all, which should not happen and is not
#: worth crashing over.
_STEREO_CONVERSION_REASON_UNKNOWN = "has no comparable standard form"

#: Appended to a `lost` title when the corrected structure is available.  Put in
#: the title rather than left to the payload because it turns the row from a
#: complaint into an instruction, and that is what decides whether it gets read.
_STEREO_DISAGREEMENT_FIX = " -- the corrected key is {corrected}"

#: The same clause where the row reports a *removal* rather than a defect:
#: what survived, not what should replace it.
_STEREO_DISAGREEMENT_KEPT = " -- the surviving key is {corrected}"

#: Which of the two each kind uses.  A row that says "this is wrong" and one
#: that says "this was taken out" want opposite sentences for the same field.
_STEREO_DISAGREEMENT_SUFFIXES = {
    "superseded": _STEREO_DISAGREEMENT_KEPT,
    "protonation-withdrawn": _STEREO_DISAGREEMENT_KEPT,
}


@dataclass(frozen=True)
class StructureCandidate:
    """One structure a source offered for a CAS number.

    The key and the InChI travel together because half the questions asked of a
    candidate cannot be answered by either alone.  "Is this the same substance"
    is a key question -- that is what a key is for.  "Does the registry's record
    state everything this one does" is not: a key hashes the stereo layers as a
    block, so it can say the two records differ and never which way (#56).

    `inchi` is allowed to be empty.  A source that published a key and no
    structure has still offered a candidate, and the gates that only compare
    keys work on it unchanged; only the questions needing a structure go
    unanswered, and each of those refuses rather than guesses.
    """

    inchikey: str
    inchi: str = ""


class CasAttestation(StrEnum):
    """What PubChem's own curated record says about a CAS ↔ CID link.

    `by_cas` is built from PubChem's `xref/RN` index, which aggregates the CAS
    numbers of every *substance* record standardised onto a compound -- vendor
    catalogue entries included, wrong numbers included.  CAS 686-31-7 reaches
    CID 106206, magnesium bis(quinolin-8-olate), through two vendor listings and
    nothing else, and so pulled that compound's formula, InChI, SMILES and names
    onto a peroxyester (#249).

    The curated "CAS" heading of the compound's own record is the corrective:
    it admits only numbers a registry or regulator attests, with a reference per
    source.  It does not list 686-31-7 for CID 106206.

    Three values rather than a boolean, because the third is the one that keeps
    this safe.  A candidate is dropped only when PubChem was asked and answered
    otherwise -- never because the cache has no entry for it.
    """

    #: The compound's curated record lists the CAS that was searched on.
    ATTESTED = "attested"
    #: The compound has a curated record, and this CAS is not in it.
    CONTRADICTED = "contradicted"
    #: No curated record cached for this CID: not asked, or the request failed.
    UNKNOWN = "unknown"


class StructureVerdict(StrEnum):
    """What CAS Common Chemistry says about a structure offered for a CAS.

    `CasAttestation` above asks whether PubChem's *own* curated record backs a
    CAS-to-compound link.  This asks a different and blunter question: does the
    CAS registry publish a structure for that number at all, and if so, is it
    this one.

    The two are complementary, and neither subsumes the other.  The curated-CAS
    gate cannot fire when a CAS returns a single compound, because there is no
    better candidate to prefer -- and a single uncontested compound for a
    non-specific CAS is exactly the shape that produced #35.  1300-21-6,
    "dichloroethane" with no isomer stated, returns CID 6365 alone, so
    1,1-dichloroethane's structure was attached with nothing to weigh it
    against, and the flow then collided under InChIKey with the real
    1,1-dichloroethane at 75-34-3.

    `NO_STRUCTURE` is the value that does the work, and it is a positive
    statement rather than an absence: Common Chemistry answered for this
    number, named the substance, and published no InChIKey, because a UVCB or
    an unspecified isomer has no single structure to publish.
    """

    #: Common Chemistry's structure for this CAS is the one offered.
    CONFIRMED = "confirmed"
    #: Common Chemistry publishes a structure for this CAS, and it is a
    #: different one.  Same skeleton or not -- the caller decides what to make
    #: of that, because a stereo disagreement (#42) is not a wrong substance.
    CONTRADICTED = "contradicted"
    #: Common Chemistry publishes a structure for this CAS and the two keys
    #: cannot be weighed against each other, because CAS computed its key from a
    #: non-standard InChI.  Distinct from `CONTRADICTED` and from `UNKNOWN`:
    #: there *is* an answer on both sides, and comparing them would be comparing
    #: hashes of different things.  36 of the 48 "stereo conflict" flow objects
    #: #42 reported are this and not a conflict at all.
    INCOMPARABLE = "incomparable"
    #: Common Chemistry publishes a flat structure for this CAS -- the number is
    #: registered with its stereochemistry unstated -- and the structure offered
    #: is a stereoisomer of it.  Unlike `CONTRADICTED`, this is acted on without
    #: a better candidate to prefer, because every candidate is wrong in the
    #: same direction and waiting for one to disagree is waiting forever (#42).
    STEREO_UNSPECIFIED = "stereo-unspecified"
    #: Common Chemistry holds a record for this CAS with no structure in it.
    NO_STRUCTURE = "no-structure"
    #: Common Chemistry has no cached record for this CAS: not asked, or the
    #: request failed.  Never treated as either of the answers above.
    UNKNOWN = "unknown"


def normalize_formula_for_parse(formula: str) -> str:
    text = str(formula or "").strip()
    if not text:
        return ""
    text = text.replace(" ", "")
    text = re.sub(r"\(?\s*\d+\s*[+-]\s*\)?$", "", text)
    text = re.sub(r"\(?\s*[+-]\s*\d+\s*\)?$", "", text)
    text = re.sub(r"\(?\s*[+-]+\s*\)?$", "", text)
    return text.strip()


def formula_element_counts(formula: str) -> dict[str, int] | None:
    normalized = normalize_formula_for_parse(formula)
    if not normalized:
        return None
    try:
        parsed = ChemFormula(normalized)
    except Exception:
        return None
    elements = getattr(parsed, "element", None)
    if not isinstance(elements, dict):
        return None
    out: dict[str, int] = {}
    for key, value in elements.items():
        if not isinstance(key, str):
            continue
        try:
            count = int(value)
        except Exception:
            continue
        if count > 0:
            out[key] = count
    return out or None


def formula_similarity_score(left: str, right: str) -> float:
    left_counts = formula_element_counts(left)
    right_counts = formula_element_counts(right)
    if not left_counts or not right_counts:
        return 0.0
    keys = set(left_counts) | set(right_counts)
    left_total = sum(left_counts.values())
    right_total = sum(right_counts.values())
    if left_total <= 0 or right_total <= 0:
        return 0.0
    left_ratio = {k: left_counts.get(k, 0) / left_total for k in keys}
    right_ratio = {k: right_counts.get(k, 0) / right_total for k in keys}
    l1_distance = sum(abs(left_ratio.get(k, 0.0) - right_ratio.get(k, 0.0)) for k in keys)
    return max(0.0, 1.0 - (0.5 * l1_distance))


# Formula similarity threshold used when filtering multiple ChEBI-direct
# matches for the same CAS.  Records below this threshold are rejected as
# likely ChEBI data errors.  Li vs HLi scores ≈ 0.5; 0.55 is safely above
# that without affecting genuinely related entries (e.g. stereoisomers share
# the same formula and score 1.0).
_CHEBI_DIRECT_FORMULA_THRESHOLD = 0.55


# Mapping from ChemROF property IRI → QUDT unit IRI for numeric properties.
#
# The charge PubChem and ChEBI report is the net charge of the whole entity, so
# it is `elemental_charge` ("number of protons minus number of electrons",
# declared on `ChemicalEntity`) and not `formal_charge`, which ChemROF scopes to
# `AtomOccurrence` -- one atom's charge inside a molecule.  This wrote
# `formal_charge` for 3,235 flow objects before #9.
_PROPERTY_UNIT_IRIS: dict[str, str] = {
    CHEMROF_MOLECULAR_MASS: UNIT_IRI_GM_PER_MOL,
    CHEMROF_MONOISOTOPIC_MASS: UNIT_IRI_GM_PER_MOL,
    CHEMROF_ELEMENTAL_CHARGE: UNIT_IRI_NUM,
}


class EnrichReferencesTransformer(Transformer):
    """Populate ``properties`` and ``references`` from ChEBI and PubChem."""

    name = "enrich_references"
    answers_per_flow = True
    # Class attributes so instance code can use `self.<TERM>`; the values come
    # from the registry so they cannot drift from the rest of the project.
    CHEMROF_ELEMENTAL_CHARGE = vocabulary.CHEMROF_ELEMENTAL_CHARGE
    CHEMROF_INCHI2D_KEY_STRING = vocabulary.CHEMROF_INCHI2D_KEY_STRING
    CHEMROF_INCHI2D_STRING = vocabulary.CHEMROF_INCHI2D_STRING
    CHEMROF_IUPAC_NAME = vocabulary.CHEMROF_IUPAC_NAME
    CHEMROF_MOLECULAR_FORMULA = vocabulary.CHEMROF_MOLECULAR_FORMULA
    CHEMROF_MOLECULAR_MASS = vocabulary.CHEMROF_MOLECULAR_MASS
    CHEMROF_MONOISOTOPIC_MASS = vocabulary.CHEMROF_MONOISOTOPIC_MASS
    CHEMROF_SMILES_STRING = vocabulary.CHEMROF_SMILES_STRING
    SKOS_DEFINITION = vocabulary.SKOS_DEFINITION_IRI
    FORMULA_SIMILARITY_MIN_SCORE = 0.55
    FORMULA_SIMILARITY_KEEP_WINDOW = 0.15

    def __init__(self) -> None:
        self._chebi_records: dict[str, dict[str, Any]] = {}
        self._chebi_by_cas: dict[str, list[str]] = {}
        self._pubchem_by_cas: dict[str, list[dict[str, Any]]] = {}
        self._pubchem_identifiers_by_cid: dict[str, dict[str, Any]] = {}
        self._pubchem_chebi_ids_by_cas: dict[str, set[str]] = defaultdict(set)
        self._cas_by_pubchem_cid: dict[int, set[str]] = defaultdict(set)
        self._element_symbol_by_name: dict[str, str] = {}
        self._chebi_key_aliases: dict[str, str] = {}
        #: One entry per CAS the curated-CAS gate excluded a compound for.  Keyed
        #: by CAS rather than by flow: the decision is a property of the CAS
        #: lookup, and every flow carrying that number gets the same answer.
        self._curated_cas_exclusions: dict[str, dict[str, Any]] = {}
        #: CAS Common Chemistry's structure index, empty until `setup()`.
        self._commonchemistry: CommonChemistryIndex = CommonChemistryIndex({}, set(), set())
        #: What a curator ruled about a registry number's structure, by CAS:
        #: an unspecified isomer family, or specific despite Common Chemistry
        #: giving no composition.
        self._structure_rulings: dict[str, StructureRuling] = {}
        #: CAS ruled contested -- two substances in one source list carry it.
        self._contested_rulings: set[str] = set()
        #: One entry per CAS whose structure lookup Common Chemistry blocked or
        #: narrowed.  Keyed by CAS for the same reason as above.
        self._structure_exclusions: dict[str, dict[str, Any]] = {}
        #: One entry per CAS registered without stereochemistry that a source
        #: offered a stereoisomer for.  Separate from `_structure_exclusions`
        #: because the two answer different questions -- that one is "is this
        #: the right substance", this one is "is this the right isomer of it" --
        #: and a curator triaging #42 should not have to read them apart.
        self._stereo_exclusions: dict[str, dict[str, Any]] = {}
        #: One entry per (CAS, kind of disagreement) that survived every gate.
        #: Keyed on the pair rather than the CAS alone because one number can
        #: hold candidates that disagree with the registry in two ways at once,
        #: and a queue that merged them would report neither.
        self._stereo_disagreements: dict[str, dict[str, Any]] = {}
        #: One entry per CAS whose lost stereochemistry was restored from the
        #: structure Common Chemistry publishes, mapped to the standard key that
        #: replaced the flat one.  Keyed by CAS for the same reason as the rest:
        #: the repair is a property of the number, not of a flow.
        self._stereo_repairs: dict[str, str] = {}
        #: The keys withdrawn from a CAS because they are the structure the
        #: registry publishes for it in another protonation state.  Kept so a
        #: later flow reaching the same number does not report as an open
        #: question a key this run has already taken out (#54).
        self._protonation_withdrawals: dict[str, set[str]] = {}

    def setup(self) -> None:
        chebi = load_chebi_index()
        self._chebi_records = chebi["records"]
        self._chebi_by_cas = chebi["by_cas"]
        self._pubchem_by_cas = {}
        self._pubchem_identifiers_by_cid = {}
        self._pubchem_chebi_ids_by_cas = defaultdict(set)
        self._cas_by_pubchem_cid = defaultdict(set)
        self._element_symbol_by_name = {}
        self._chebi_key_aliases = {}
        self._curated_cas_exclusions = {}
        self._structure_exclusions = {}
        # Read from disk rather than from `CommonchemCasReviewTransformer`, which
        # runs two transformers earlier: the engine calls every `setup()` before
        # any `transform()`, so that run's additions are not in memory yet.  The
        # cache is persistent and keyed by CAS, so what is on disk is the
        # previous build's answers -- which is enough, and an empty cache on a
        # first build correctly makes every gate below a no-op.
        self._commonchemistry = load_commonchemistry_index()
        self._structure_rulings = load_structure_decisions()
        #: Registry numbers a curator has ruled contested -- carried by two
        #: names the layering must not fuse (#34).  A number that does not
        #: identify one substance cannot lend one a structure either, so the
        #: same ruling gates both.  Only the *ruled* separations are read, not
        #: the ones the factor signal derives: withholding chemistry is the
        #: stronger action of the two, and this file follows the same principle
        #: as `commonchemistry-structure-decisions.json` above it -- the default
        #: is to do nothing, and a number is withheld only where a curator says.
        self._contested_rulings = {
            cas for cas, ruling in load_contested_cas_decisions().items()
            if ruling.verdict is ContestedVerdict.SEPARATE
        }
        for key in self._chebi_records:
            if not isinstance(key, str):
                continue
            canonical = self._to_chebi_record_key(key)
            if canonical:
                self._chebi_key_aliases[canonical] = key

        if PUBCHEM_ELEMENTS_CACHE_FILEPATH.exists():
            try:
                payload = orjson.loads(PUBCHEM_ELEMENTS_CACHE_FILEPATH.read_bytes())
            except Exception:
                payload = {}
            elements = payload.get("elements", [])
            if isinstance(elements, list):
                for element in elements:
                    if not isinstance(element, dict):
                        continue
                    name = str(element.get("name") or "").strip().lower()
                    symbol = str(element.get("symbol") or "").strip()
                    if name and symbol:
                        self._element_symbol_by_name[name] = symbol

        if not PUBCHEM_DATA_FILEPATH.exists():
            return

        payload = orjson.loads(PUBCHEM_DATA_FILEPATH.read_bytes())
        self._pubchem_by_cas = payload.get("by_cas", {})
        self._pubchem_identifiers_by_cid = payload.get("identifiers", {})

        cid_to_chebi_ids: dict[int, set[str]] = defaultdict(set)
        for cid_key, id_map in self._pubchem_identifiers_by_cid.items():
            if not isinstance(id_map, dict):
                continue
            try:
                cid = int(cid_key)
            except (TypeError, ValueError):
                continue
            for item in id_map.get("ChEBI ID", []):
                value = item.get("value") if isinstance(item, dict) else None
                if isinstance(value, str) and value.strip():
                    normalized = self._to_chebi_record_key(value)
                    if normalized:
                        cid_to_chebi_ids[cid].add(normalized)

        for cas, compounds in self._pubchem_by_cas.items():
            if not isinstance(cas, str) or not isinstance(compounds, list):
                continue
            for compound in compounds:
                if not isinstance(compound, dict):
                    continue
                cid = compound.get("cid")
                if isinstance(cid, int):
                    self._pubchem_chebi_ids_by_cas[cas].update(cid_to_chebi_ids.get(cid, set()))
                    self._cas_by_pubchem_cid[cid].add(cas)

    def transform(self, flows: list[Flow]) -> list[Change]:
        changes: list[Change] = []

        for flow in flows:
            cas_numbers = [
                cas for cas in flow.cas_numbers
                if isinstance(cas, str) and cas.strip()
            ]
            if not cas_numbers:
                continue

            expected_formulas = self._expected_formulas_for_flow(flow)
            candidate_pubchem_cids = sorted({
                c.get("cid")
                for cas in cas_numbers
                for c in self._pubchem_by_cas.get(cas, [])
                if isinstance(c, dict) and isinstance(c.get("cid"), int)
            })
            # Both structure lookups are by CAS and nothing else, so a number
            # that denotes no structure has to be withheld from both.  The full
            # list still goes to `_build_references` below: the Common Chemistry
            # and ECHA pages for 1300-21-6 describe that registry entry, and are
            # correct references for a flow that carries the number.
            structure_cas = self._structure_bearing_cas(cas_numbers)
            chebi_ids = self._matched_chebi_ids(structure_cas, expected_formulas=expected_formulas)
            pubchem_compounds = self._matched_pubchem_compounds(
                flow=flow,
                cas_numbers=structure_cas,
                chebi_ids=chebi_ids,
            )
            has_single_consensus_cas = len({cas.strip() for cas in cas_numbers}) == 1
            # Only where the stereochemistry gate actually refused something.
            # 5,726 of the 6,300 keyed numbers are registered flat, and
            # publishing the registry's structure for all of them would be a
            # different and much larger change; here it is the replacement for
            # what was just taken away.
            stereo_unspecified_cas = [
                cas for cas in structure_cas if cas in self._stereo_exclusions
            ]
            # The other direction: the number states a stereochemistry no source
            # we look a structure up in can supply, so the flow object publishes
            # the shape-free key and collides with the substance that key really
            # belongs to.  Asked of every surviving candidate at once, because
            # "is there a hole here" is a question about the whole record rather
            # than about the number a candidate happened to arrive through.
            stereo_restored_cas = self._restore_lost_stereochemistry(
                cas_numbers=structure_cas,
                chebi_ids=chebi_ids,
                pubchem_compounds=pubchem_compounds,
            )

            if (
                not chebi_ids
                and not pubchem_compounds
                and not stereo_unspecified_cas
                and not stereo_restored_cas
                and not has_single_consensus_cas
            ):
                continue

            new_properties = self._build_properties(
                existing=flow.properties,
                chebi_ids=chebi_ids,
                pubchem_compounds=pubchem_compounds,
                stereo_unspecified_cas=stereo_unspecified_cas,
                stereo_restored_cas=stereo_restored_cas,
                structure_cas=structure_cas,
            )
            if new_properties and flow.properties != new_properties:
                changes.append(Change(
                    flow.uuid,
                    "properties",
                    new_properties,
                    comment=(
                        f"Added ChEBI/PubChem properties (chebi_ids={len(chebi_ids)}, "
                        f"pubchem_cids={len({c.get('cid') for c in pubchem_compounds if isinstance(c.get('cid'), int)})}"
                        + (
                            f", commonchemistry_cas={stereo_unspecified_cas}"
                            if stereo_unspecified_cas
                            else ""
                        )
                        + (
                            f", stereochemistry_restored_cas={stereo_restored_cas}"
                            if stereo_restored_cas
                            else ""
                        )
                        + ")"
                    ),
                ))

            new_definitions = self._build_definitions(
                existing=flow.skos_definition,
                chebi_ids=chebi_ids,
                pubchem_compounds=pubchem_compounds,
            )
            if flow.skos_definition != new_definitions:
                changes.append(Change(
                    flow.uuid,
                    self.SKOS_DEFINITION,
                    new_definitions,
                    comment="Merged ChEBI/PubChem definitions into skos:definition",
                ))

            new_references = self._build_references(
                existing=flow.references,
                chebi_ids=chebi_ids,
                pubchem_compounds=pubchem_compounds,
                cas_numbers=cas_numbers,
            )
            if flow.references != new_references:
                unique_cas = sorted({cas.strip() for cas in cas_numbers if isinstance(cas, str) and cas.strip()})
                pubchem_cids = sorted({
                    c.get("cid")
                    for c in pubchem_compounds
                    if isinstance(c, dict) and isinstance(c.get("cid"), int)
                })
                changes.append(Change(
                    flow.uuid,
                    "references",
                    new_references,
                    comment=(
                        "Added references with provenance; "
                        f"cas_numbers={unique_cas}; "
                        f"matched_chebi_ids={sorted(chebi_ids)}; "
                        f"candidate_pubchem_cids={candidate_pubchem_cids}; "
                        f"selected_pubchem_cids={pubchem_cids}; "
                        f"formula_similarity_expected={expected_formulas}; "
                        "pubchem_selection_rule=curated_cas_then_formula_similarity_then_prefer_chebi_aligned_when_unambiguous_else_keep_all_cas_matches; "
                        f"single_cas_commonchem_link={'yes' if len(unique_cas) == 1 else 'no'}"
                    ),
                ))

        if self._curated_cas_exclusions:
            logger.info(
                "curated_cas_gate_completed",
                cas_numbers_filtered=len(self._curated_cas_exclusions),
                cids_dropped=sum(
                    len(entry["dropped_cids"])
                    for entry in self._curated_cas_exclusions.values()
                ),
            )

        return changes

    def review_queue_items(self) -> list[ReviewQueueItem]:
        """Every CAS whose candidate compounds the curated-CAS gate narrowed.

        Recorded even though the pipeline acted, because acting is the part
        worth checking: PubChem's curated section is the better evidence, not
        infallible evidence, and a dropped CID is a structure this list now
        does not publish.  `INFO` rather than `BLOCKING` -- the run resolved it,
        and the queue is here so a curator can disagree.
        """
        items = [
            ReviewQueueItem(
                queue_name=ReviewQueue.CURATED_CAS_EXCLUSION,
                item_key=cas,
                title=f"{cas}: {len(entry['dropped_cids'])} compound(s) dropped",
                severity=Severity.INFO,
                cas=cas,
                payload=entry,
            )
            for cas, entry in sorted(self._curated_cas_exclusions.items())
        ]
        # `REVIEW` rather than `INFO`, unlike the gate above, because the two
        # ask different things of a curator.  That one narrowed a choice between
        # candidates and left a structure in place; this one can leave a flow
        # with *no* structure at all, and whether that is right depends on
        # whether the CAS really is non-specific.  Somebody should look.
        items.extend(
            ReviewQueueItem(
                queue_name=ReviewQueue.COMMONCHEM_STRUCTURE_EXCLUSION,
                item_key=cas,
                title=(
                    f"{cas}: CAS publishes no structure, "
                    f"{len(entry['dropped_cids'])} PubChem compound(s) and "
                    f"{len(entry.get('dropped_chebi_ids', []))} ChEBI record(s) withheld"
                    if entry["reason"] == StructureVerdict.NO_STRUCTURE.value
                    else f"{cas}: {len(entry['dropped_cids'])} compound(s) dropped, "
                         f"CAS publishes {entry['commonchemistry_inchikey']}"
                ),
                severity=Severity.REVIEW,
                cas=cas,
                payload=entry,
            )
            for cas, entry in sorted(self._structure_exclusions.items())
        )
        # `REVIEW` again, and for the sharper version of the same reason.  This
        # gate acts on Common Chemistry alone, with no second candidate agreeing
        # with it, so the registry's flat key is the whole of the evidence.  It
        # is good evidence -- 542-75-6 is registered flat beside cis-1,3-
        # dichloropropene at 10061-01-5, and 4170-30-3 beside trans-crotonaldehyde
        # at 123-73-9 -- and where the isomers are not separately registered a
        # curator should be able to say the flat key is a gap rather than a
        # statement.
        items.extend(
            ReviewQueueItem(
                queue_name=ReviewQueue.COMMONCHEM_STRUCTURE_EXCLUSION,
                item_key=f"{cas}:stereo",
                title=(
                    f"{cas}: CAS registers this number without stereochemistry, "
                    f"{len(entry['dropped_cids'])} PubChem compound(s) and "
                    f"{len(entry['dropped_chebi_ids'])} ChEBI record(s) withheld"
                ),
                severity=Severity.REVIEW,
                cas=cas,
                payload=entry,
            )
            for cas, entry in sorted(self._stereo_exclusions.items())
        )
        # Everything #42 found, whether or not the pipeline could settle it,
        # in one queue because a curator triaging that issue should not have to
        # read four apart.  The severity is what separates them: see
        # `_STEREO_DISAGREEMENT_SEVERITIES`.  It began as the one queue here
        # that reported without having acted, and two of its five kinds now do
        # act -- the rows are still written, because a fix nobody can see is
        # indistinguishable from a defect nobody found.
        items.extend(
            ReviewQueueItem(
                queue_name=ReviewQueue.STEREO_DISAGREEMENT,
                item_key=item_key,
                title=_STEREO_DISAGREEMENT_TITLES[entry["kind"]].format(
                    cas=entry["cas"],
                    ours=", ".join(entry["published_inchikeys"]),
                    theirs=entry["commonchemistry_inchikey"],
                    fix=(
                        _STEREO_DISAGREEMENT_SUFFIXES.get(
                            entry["kind"], _STEREO_DISAGREEMENT_FIX
                        ).format(corrected=entry["corrected_inchikey"])
                        if entry.get("corrected_inchikey")
                        else ""
                    ),
                    because=_STEREO_CONVERSION_REASONS.get(
                        entry.get("conversion_refusal"),
                        _STEREO_CONVERSION_REASON_UNKNOWN,
                    ),
                ),
                severity=_STEREO_DISAGREEMENT_SEVERITIES.get(
                    entry["kind"], Severity.BLOCKING
                ),
                cas=entry["cas"],
                payload=entry,
            )
            for item_key, entry in sorted(self._stereo_disagreements.items())
        )
        return items

    def _matched_chebi_ids(
        self,
        cas_numbers: list[str],
        expected_formulas: list[str] | None = None,
    ) -> list[str]:
        queried_cas = {c.strip() for c in cas_numbers if c.strip()}
        matched: set[str] = set()
        #: Which numbers each record was reached through, so the stereochemistry
        #: gate below can ask its question of the right one.  A record matched
        #: through two numbers is only refused if *both* register flat.
        reached_through: dict[str, set[str]] = defaultdict(set)
        for cas in queried_cas:
            for chebi_id in self._chebi_by_cas.get(cas, []):
                normalized = self._to_chebi_record_key(chebi_id)
                if normalized:
                    matched.add(normalized)
                    reached_through[normalized].add(cas)
            for chebi_id in self._pubchem_chebi_ids_by_cas.get(cas, set()):
                normalized = self._to_chebi_record_key(chebi_id)
                if not normalized:
                    continue
                # Only accept a PubChem-derived ChEBI ID if the ChEBI record
                # itself also lists one of the queried CAS numbers. PubChem's
                # ChEBI cross-reference table occasionally maps a CAS to an
                # unrelated ChEBI entry (e.g. CAS 25013-16-5 → CHEBI:17688
                # nicotine), which the ChEBI record's own CAS list does not
                # confirm.
                record = self._chebi_records.get(normalized, {})
                record_cas = set(record.get("cas_numbers", []))
                if record_cas & queried_cas:
                    matched.add(normalized)
                    reached_through[normalized].add(cas)

        # Secondary guard: ChEBI's own data can contain errors where a compound
        # record incorrectly claims a CAS number belonging to a different
        # substance (e.g. CHEBI:30146 / lithium hydride lists CAS 7439-93-2
        # which is the lithium element).  When multiple ChEBI-direct IDs are
        # matched and the flow has a known expected formula, filter out records
        # whose formula is clearly incompatible using formula similarity.  A
        # record with no formula is kept (absence of data is not a rejection
        # reason).  The set is only narrowed if at least one record survives the
        # filter.
        if len(matched) > 1 and expected_formulas:
            formula_filtered: set[str] = set()
            for chebi_id in matched:
                record = self._chebi_records.get(chebi_id, {})
                record_formula = record.get("formula")
                if isinstance(record_formula, str) and record_formula.strip():
                    best = max(
                        formula_similarity_score(record_formula, ef)
                        for ef in expected_formulas
                    )
                    if best >= _CHEBI_DIRECT_FORMULA_THRESHOLD:
                        formula_filtered.add(chebi_id)
                else:
                    formula_filtered.add(chebi_id)
            if formula_filtered:
                matched = formula_filtered

        # Last, and ungated on the count, for the reason given in
        # `_filter_compounds_by_stereo_specificity`: this is where #42's
        # invented stereochemistry mostly comes from.  32 of the 33 flow objects
        # carry `chebi_semantic` in the provenance of the offending key, because
        # ChEBI's entry for a common name is usually the stereo-defined natural
        # isomer and nothing above this line asks the registry whether the
        # number has a stereochemistry at all.
        surviving: set[str] = set()
        for chebi_id in matched:
            candidate = self._chebi_record_candidate(chebi_id)
            sources = sorted(reached_through.get(chebi_id, set()))
            inventing = [
                cas for cas in sources
                if self._invents_stereochemistry(cas=cas, candidate=candidate.inchikey)
            ]
            if inventing and len(inventing) == len(sources):
                for cas in inventing:
                    self._record_stereo_exclusion(cas=cas, chebi_ids=[chebi_id])
                continue
            surviving.add(chebi_id)
            for cas in sources:
                self._record_stereo_disagreement(
                    cas=cas, source=chebi_id, candidate=candidate
                )

        return sorted(surviving)

    def _chebi_basic_property(self, chebi_id: str, name: str) -> str:
        """The first value a ChEBI record holds under *name*, or `""`.

        A record holds at most one structure -- 182,605 of ChEBI's 224,523 CLASS
        records have exactly one InChIKey and the rest have none -- so there is
        no choice to make here, and a record with none is simply not gated on
        its structure.
        """
        record = self._chebi_records.get(chebi_id, {})
        values = (record.get("basic_property_values") or {}).get(name)
        if not isinstance(values, list):
            return ""
        for value in values:
            if isinstance(value, str) and value.strip():
                return value.strip()
        return ""

    def _chebi_record_candidate(self, chebi_id: str) -> StructureCandidate:
        """The structure a ChEBI record offers: its key and the InChI behind it."""
        return StructureCandidate(
            inchikey=self._chebi_basic_property(chebi_id, "inchi_key_string"),
            inchi=self._chebi_basic_property(chebi_id, "inchi_string"),
        )

    def _to_chebi_record_key(self, value: Any) -> str:
        text = str(value or "").strip()
        if not text:
            return ""
        if text in self._chebi_records:
            return text
        aliased = self._chebi_key_aliases.get(text)
        if aliased:
            return aliased
        match = re.search(r"CHEBI[_:](\d+)", text, flags=re.IGNORECASE)
        if match:
            suffix = match.group(1)
            uri = f"http://purl.obolibrary.org/obo/CHEBI_{suffix}"
            if uri in self._chebi_records:
                self._chebi_key_aliases[text] = uri
                return uri
            compact = f"CHEBI:{suffix}"
            aliased = self._chebi_key_aliases.get(compact)
            if aliased:
                self._chebi_key_aliases[text] = aliased
                return aliased
        if text.isdigit():
            uri = f"http://purl.obolibrary.org/obo/CHEBI_{text}"
            if uri in self._chebi_records:
                self._chebi_key_aliases[text] = uri
                return uri
        return ""

    def _normalize_chebi_id(self, value: str) -> str:
        text = value.strip()
        if not text:
            return ""
        lowered = text.lower()
        if "chebi:" in lowered:
            suffix = text.split(":", 1)[1].strip()
            return f"CHEBI:{suffix}"
        if "chebi_" in lowered:
            suffix = text.rsplit("_", 1)[1].strip()
            return f"CHEBI:{suffix}"
        if text.isdigit():
            return f"CHEBI:{text}"
        return text.upper()

    def _compound_chebi_ids(self, cid: int) -> set[str]:
        out: set[str] = set()
        id_map = self._pubchem_identifiers_by_cid.get(str(cid), {})
        if not isinstance(id_map, dict):
            return out
        for item in id_map.get("ChEBI ID", []):
            if not isinstance(item, dict):
                continue
            value = item.get("value")
            if isinstance(value, str):
                normalized = self._normalize_chebi_id(value)
                if normalized:
                    out.add(normalized)
        return out

    def _matched_pubchem_compounds(
        self,
        *,
        flow: dict[str, Any],
        cas_numbers: list[str],
        chebi_ids: list[str],
    ) -> list[dict[str, Any]]:
        wanted_chebi = {
            self._normalize_chebi_id(x)
            for x in chebi_ids
            if isinstance(x, str) and x.strip()
        }
        expected_formulas = self._expected_formulas_for_flow(flow)
        compounds: list[dict[str, Any]] = []
        seen_cids: set[int] = set()
        for cas in cas_numbers:
            cas_compounds = [
                c for c in self._pubchem_by_cas.get(cas, [])
                if isinstance(c, dict) and isinstance(c.get("cid"), int)
            ]
            # First, because it is the only filter here that consults PubChem's
            # own judgement rather than inferring one.  The formula and ChEBI
            # filters below need the flow to already carry a formula or a ChEBI
            # id, and a flow whose structure has not been enriched yet carries
            # neither -- which is exactly the case this was written for.
            #
            # It narrows `selected` and deliberately leaves `cas_compounds`
            # alone, because `len(cas_compounds) > 1` below is not a count of
            # what survives -- it is the test for whether the CAS was ambiguous
            # at all, and the ChEBI branch rejects every candidate for an
            # ambiguous CAS with no ChEBI support.  Narrowing the list that test
            # reads would let this gate *admit* compounds the ChEBI guard had
            # rejected: dinitrophenol went from no structure to phenol with two
            # nitrous acids stuck to it, C6H8N2O5 for a C6H4N2O5 substance.  A
            # gate that only ever removes candidates must not be able to add
            # one.
            selected = self._filter_compounds_by_curated_cas(
                cas=cas, compounds=cas_compounds
            )
            if len(cas_compounds) > 1 and expected_formulas:
                selected = self._filter_compounds_by_formula_similarity(
                    cas=cas,
                    compounds=selected,
                    expected_formulas=expected_formulas,
                )
            if len(cas_compounds) > 1 and wanted_chebi:
                chebi_matched = [
                    c for c in selected
                    if self._compound_chebi_ids(c["cid"]).intersection(wanted_chebi)
                ]
                if len(chebi_matched) == 1:
                    selected = chebi_matched
                elif len(chebi_matched) > 1:
                    selected = chebi_matched
                else:
                    # Ambiguous CAS without supporting ChEBI linkage: skip instead of adding similar compounds.
                    selected = []
            # Last, and ungated on `len(cas_compounds)`, unlike the two filters
            # above.  Those read the count as "was this CAS ambiguous", which is
            # the wrong question for a non-specific number: 68475-60-5, alkanes
            # C4-5, is not ambiguous in PubChem's index -- it returns n-pentane
            # and only n-pentane -- and that unanimity is what let a UVCB
            # inherit a single molecule's structure unopposed.
            selected = self._filter_compounds_by_commonchemistry(
                cas=cas, compounds=selected
            )
            # After the narrowing gate, and ungated on the count for the same
            # reason: the invented stereochemistry of #42 arrives unopposed.
            # In 20 of the 33 cases PubChem and ChEBI hand back the *same*
            # stereo-specific compound, so there is no candidate to prefer over
            # it and nothing above this line can fire.
            selected = self._filter_compounds_by_stereo_specificity(
                cas=cas, compounds=selected
            )
            # What survived every gate is what the list will publish, so this is
            # the point at which a remaining stereochemistry disagreement is
            # worth reporting rather than a passing state of the filtering.
            for compound in selected:
                self._record_stereo_disagreement(
                    cas=cas,
                    source=f"CID:{compound['cid']}",
                    candidate=self._compound_candidate(compound),
                )
            for compound in selected:
                if not isinstance(compound, dict):
                    continue
                cid = compound.get("cid")
                if not isinstance(cid, int) or cid in seen_cids:
                    continue
                seen_cids.add(cid)
                compounds.append(compound)
        return compounds

    def _lends_no_structure(self, cas: str) -> str | None:
        """Why *cas* may not be used to look a structure up, or `None`.

        Two grounds, and only the first is the pipeline's own judgement.

        **Common Chemistry gives the number no composition.**
        ``molecularFormula: "Unspecified"`` is CAS stating that the number
        denotes nothing with a definite formula -- ``Alkanes, C4-5``,
        ``Turpentine oil``, ``Naphtha``, ``Kieselguhr``.  Nothing reachable
        through such a number can be the substance's structure, so this is
        acted on directly.  517 cached records.

        **A curator has ruled the number an unspecified isomer.**  Where Common
        Chemistry gives a real formula and no key, the record cannot say
        whether the number is an isomer family or a specific molecule it simply
        holds no key for.  Both are in there, and the second includes ozone::

            1300-21-6    Dichloroethane   C2H4Cl2      isomer family
            25264-93-1   Hexene           C6H12        isomer family
            10028-15-6   Ozone            O3           one molecule
            10102-44-0   Nitrogen dioxide NO2          one molecule
            117704-25-3  Doramectin       C50H74O14    one molecule

        Guessing here is not available: 319 records have this shape and reading
        them as non-specific would strip ozone's structure. So the default is
        to do nothing, and a number is withheld only where
        `commonchemistry-structure-decisions.json` says so.
        """
        if cas in self._contested_rulings:
            return (
                "ruled a contested registry number: more than one substance in the "
                "source list carries it, so no structure reached through it belongs "
                "to any one of them"
            )
        ruling = self._structure_rulings.get(cas)
        if ruling is not None:
            if ruling.verdict is StructureRulingVerdict.ISOMER_AMBIGUOUS:
                return f"ruled an unspecified isomer: {ruling.comment}"
            return None
        if self._commonchemistry.holds_no_composition(cas):
            return "CAS Common Chemistry gives this number no molecular formula"
        return None

    def _structure_bearing_cas(self, cas_numbers: list[str]) -> list[str]:
        """The CAS numbers of *cas_numbers* a structure may be looked up from.

        A number is dropped not because it is wrong -- 1300-21-6 really is
        dichloroethane and 8006-64-2 really is turpentine -- but because it
        names a substance with no single structure, so every structure
        reachable *through* it belongs to something else.  PubChem answers such
        a number with one component of the mixture, or with an unrelated
        compound its `xref/RN` index aggregated: gum turpentine returns triethyl
        citrate, and `Isononanoic acid, C16-18-alkyl esters` returns water.

        An uncached number is kept, and so is one Common Chemistry gives a
        formula for with no ruling against it.  The gate must never let a gap in
        the cache, or an ambiguity it cannot resolve, decide identity -- the
        same rule `_filter_compounds_by_curated_cas` follows for `UNKNOWN`.
        """
        kept: list[str] = []
        for cas in cas_numbers:
            reason = self._lends_no_structure(cas)
            if reason is None:
                kept.append(cas)
                continue
            self._structure_exclusions.setdefault(cas, {
                "cas": cas,
                "reason": StructureVerdict.NO_STRUCTURE.value,
                "why": reason,
                "dropped_cids": sorted({
                    c["cid"] for c in self._pubchem_by_cas.get(cas, [])
                    if isinstance(c, dict) and isinstance(c.get("cid"), int)
                }),
                # The raw ids the CAS index holds, not the record keys
                # `_to_chebi_record_key` would resolve them to: an id with
                # no loaded record resolves to `""`, and a report of what
                # was withheld must not quietly drop the ones it cannot
                # resolve.
                "dropped_chebi_ids": sorted(
                    str(x).strip()
                    for x in self._chebi_by_cas.get(cas, [])
                    if str(x or "").strip()
                ),
            })
        return kept

    def _compound_property(self, compound: dict[str, Any], label: str) -> str:
        for prop in compound.get("props", []):
            if not isinstance(prop, dict):
                continue
            if prop.get("urn", {}).get("label") != label:
                continue
            value = prop.get("value", {}).get("sval")
            if isinstance(value, str) and value.strip():
                return value.strip()
        return ""

    def _compound_inchikey(self, compound: dict[str, Any]) -> str:
        return self._compound_property(compound, "InChIKey")

    def _compound_candidate(self, compound: dict[str, Any]) -> StructureCandidate:
        """The structure a PubChem compound offers: its key and its InChI."""
        return StructureCandidate(
            inchikey=self._compound_property(compound, "InChIKey"),
            inchi=self._compound_property(compound, "InChI"),
        )

    def _structure_verdict(self, *, cas: str, compound: dict[str, Any]) -> StructureVerdict:
        """What Common Chemistry says about *compound* being the structure of *cas*.

        A key that does not match is not automatically a contradiction.  CAS
        often computes its key a different way from every source here, and two
        keys computed differently cannot be weighed against each other -- so
        reading a mismatch as "CAS says this is the wrong structure" convicts a
        candidate on a comparison that never ran.

        The way out is to stop comparing keys and compare *structures*.  CAS
        publishes the InChI behind its key, and where that describes something
        standard InChI can express, `comparable_inchikey_for` re-expresses it as
        a key that can be compared.  Only where it cannot -- relative or racemic
        stereochemistry -- is the answer `INCOMPARABLE`, and then it is
        `INCOMPARABLE` for a reason about the substance rather than about the
        cache.
        """
        if self._lends_no_structure(cas) is not None:
            return StructureVerdict.NO_STRUCTURE
        published = self._commonchemistry.inchikey_for(cas)
        if not published:
            return StructureVerdict.UNKNOWN
        candidate = self._compound_inchikey(compound)
        if not candidate:
            return StructureVerdict.UNKNOWN
        comparable = self._commonchemistry.comparable_inchikey_for(cas) or published
        match compare_structures(candidate, comparable):
            case StructureComparison.SAME:
                return StructureVerdict.CONFIRMED
            case StructureComparison.INCOMPARABLE:
                return StructureVerdict.INCOMPARABLE
            case _:
                return StructureVerdict.CONTRADICTED

    def _stereo_disagreement(
        self, *, cas: str, candidate: StructureCandidate
    ) -> str | None:
        """How *candidate* disagrees with CAS about its structure, or `None`.

        Asked of structures that survived every gate, so what it finds is what
        the list is about to publish.  Six answers, and they want different
        things from a curator:

        - **`protonation`** -- the same skeleton carrying a different number of
          hydrogen ions: an acid and its ion, or a salt against the free acid.
          Not a shape question at all, and reporting it as one is #54.
        - **`lost`** -- CAS gives the number a stereochemistry and the candidate
          is flat.  Where CAS's structure can be re-expressed as a standard key,
          the corrected value comes with the finding: this is a defect with its
          own fix attached, and `_corrected_inchikey_for` hands it over.
        - **`cas-undetermined`** -- both records specific, and the registry's
          leaves undetermined an arrangement ours states, agreeing on every one
          both state.  Settled here rather than by a curator: a record that
          assigns every centre is not contradicted by one that leaves some
          undetermined, so ours stands and the row is `INFO`.
        - **`ours-undetermined`** -- the same the other way round, and not
          settled the same way, because the published key then names a broader
          substance than the number does.  `_restored_stereochemistry_for` fills
          the gap from the registry where every candidate has it; where one does
          not, this survives as an open defect with the fuller key named in it.
        - **`conflict`** -- both records specific, and each states an
          arrangement the other contradicts.  Neither source can be trusted
          silently; this is the band #42 asked to send to a curator, and #56
          measured as three of the fifteen rows wearing its label.
        - **`incomparable`** -- CAS states a *relative* or *racemic*
          stereochemistry, which standard InChI has no way to write down.  No
          key will ever be comparable with it, so this is not a disagreement and
          is reported at `INFO`.  It is reported at all because it looks exactly
          like `conflict` from the key strings, and reading it as one is how
          #42 came to count 91 defects where there are 45.

        **Charge is tested before shape**, and both parts of that are load
        bearing.  `compare_structures` reports a protonation difference as a
        difference -- correctly, because it is one -- and the shape bands used
        to read that answer as being about shape, so `(+)-tartaric acid` and its
        tartrate were filed as *"same skeleton, different stereochemistry, both
        specific"* over two keys whose stereochemistry hashes are identical
        (#54).  Testing charge first also gets the question a curator is asked
        right where *both* differ: the third block is not touched by the InChI
        options the second block's hash depends on, so the charge comparison is
        valid on a pair the shape comparison could only shrug at.

        `None` for agreement, for a different skeleton -- a different substance
        is not a stereochemistry question -- and for a number Common Chemistry
        has no key for.
        """
        published = self._commonchemistry.inchikey_for(cas)
        if not published:
            return None
        theirs = parse_inchikey(published)
        ours = parse_inchikey(candidate.inchikey)
        if ours is None or theirs is None or ours.skeleton != theirs.skeleton:
            return None
        if ours.protonation != theirs.protonation:
            # Withdrawn already, on this flow or an earlier one reaching the
            # same number: a key the pipeline has taken out is not an open
            # question, and `_record_withdrawn_protonation` files it as a
            # removal instead.
            if candidate.inchikey in self._protonation_withdrawals.get(
                cas, frozenset()
            ):
                return None
            return "protonation"
        if theirs.is_flat:
            # `_filter_compounds_by_stereo_specificity` owns that direction.
            return None
        # Agreement first, against the key CAS actually published.  Two keys
        # with the same stereo hash are the same structure whatever computed
        # them -- that half of #42's warning about the standard flag was always
        # right -- so a conversion cannot change this answer and there is no
        # reason to reach for one.  Asking it second is how `Zinc-65` came to be
        # reported as an impossible comparison against a key identical to its
        # own (#55).
        if (
            compare_structures(candidate.inchikey, published)
            is StructureComparison.SAME
        ):
            return None
        # Only a *difference* needs a key that can be compared: without this the
        # answer would rest on how CAS happened to compute its key rather than
        # on what the substance is.
        comparable = self._commonchemistry.comparable_inchikey_for(cas)
        if comparable is None:
            return "incomparable"
        if (
            compare_structures(candidate.inchikey, comparable)
            is StructureComparison.SAME
        ):
            return None
        if not ours.is_flat:
            return self._specific_stereo_disagreement(cas=cas, candidate=candidate)
        # Repaired earlier in this run, on a flow that reached the number with
        # the same hole.  Reported once and fixed once; a second flow finding
        # the same flat candidate is not a second open question.
        return None if cas in self._stereo_repairs else "lost"

    def _specific_stereo_disagreement(
        self, *, cas: str, candidate: StructureCandidate
    ) -> str | None:
        """Which of #56's three kinds a both-specific disagreement is.

        The keys have already said the two records are not the same structure.
        What they cannot say is whether that is an argument about chemistry or
        one record simply not stating something the other did -- a key hashes
        every stereo layer at once, so one undetermined corner out of thirty
        moves it as thoroughly as inverting all thirty would.  All fifteen rows
        #56 reports arrived wearing the same label for exactly that reason, and
        ten of them turned out to be a gap rather than a disagreement.

        So the structures are asked instead, through
        :func:`states_more_stereochemistry`, and `conflict` is what remains when
        neither record is the other with corners unstated.  That includes the
        case where a structure could not be read at all: `conflict` is the
        status quo and the answer that sends a person to look.
        """
        theirs = self._commonchemistry.comparable_inchi_for(cas) or ""
        ours = self._candidate_inchi(candidate)
        if ours and theirs:
            if states_more_stereochemistry(ours, theirs):
                return "cas-undetermined"
            if states_more_stereochemistry(theirs, ours):
                # Filled earlier in this run, from the registry, on a flow that
                # reached the number with the same gap -- as for `lost` above.
                return None if cas in self._stereo_repairs else "ours-undetermined"
        return "conflict"

    def _candidate_inchi(self, candidate: StructureCandidate) -> str:
        """*candidate*'s InChI, where it really is the structure its key names.

        The two arrive from one record and are meant to describe one substance,
        and nothing has checked that they do.  Reading a stereochemistry off a
        string that belongs to a different structure from the key beside it
        would put the answer on the wrong molecule, so the InChI is converted to
        a key and the two are required to agree before either is believed.

        `""` where they do not, and where there is no InChI at all -- both mean
        "no structure to read here", and every caller treats that as a question
        it cannot answer rather than as an answer.
        """
        text = str(candidate.inchi or "").strip()
        if not text:
            return ""
        derived = standard_inchikey_from_inchi(text)
        if derived is None or structure_identity(derived) != structure_identity(
            candidate.inchikey
        ):
            return ""
        return text

    def _corrected_inchikey_for(
        self, *, cas: str, candidate: StructureCandidate
    ) -> str:
        """The key this substance should carry instead of *candidate*, or `""`.

        Only where the finding is a gap in the published record -- `lost`, the
        whole shape missing, or `ours-undetermined`, part of it -- and only
        where CAS's structure survives being re-expressed as a standard key.  A
        queue row that says "this is wrong" is worth less than one that also
        says what the right answer is, and for most of these the right answer is
        available and was being thrown away: the earlier reading of this defect
        concluded CAS's key "cannot be copied in as the corrected value", which
        is true of the key and false of the structure behind it.
        """
        if self._stereo_disagreement(cas=cas, candidate=candidate) not in (
            "lost",
            "ours-undetermined",
        ):
            return ""
        return self._commonchemistry.comparable_inchikey_for(cas) or ""

    def _registry_fills_the_gap(
        self, *, cas: str, candidate: StructureCandidate
    ) -> bool:
        """Whether CAS's structure states everything *candidate* does, and more.

        The partial form of "the candidate is shape-free": the record is not
        missing its whole shape, it is missing part of it, and the registry
        supplies the rest without contradicting any of it.  `β-Endosulfan`
        leaves three of its five centres undetermined where the registry assigns
        all five and agrees on the other two, so the key published for it names
        a set of stereoisomers rather than the substance the number denotes
        (#56).

        Reads the structures, because the keys cannot answer this: see
        :func:`states_more_stereochemistry`.
        """
        ours = self._candidate_inchi(candidate)
        theirs = self._commonchemistry.comparable_inchi_for(cas)
        return bool(ours and theirs) and states_more_stereochemistry(theirs, ours)

    def _restored_stereochemistry_for(
        self, *, cas: str, candidates: list[StructureCandidate]
    ) -> str:
        """The key that restores *cas*'s stereochemistry to *candidates*, or `""`.

        The one place this project *adds* a stereochemistry rather than refusing
        one, so the conditions are stated in full and each is load-bearing.

        A number like `21862-63-5` is `trans-4-tert-butylcyclohexanol`.  The name
        says which isomer it is and CAS's structure says the same, but PubChem
        and ChEBI answer with the shape-free compound -- the trans form is not a
        record either of them holds -- so the flow object publishes
        `CCOQPGVQAWPUPE-UHFFFAOYSA-N`, which is also plain
        `4-tert-butylcyclohexanol`'s key, and the two collide (#50, #42).

        The registry is the only source that holds the answer, exactly as in
        `_merge_commonchemistry_semantic_properties`, and here it is used to fill
        a hole rather than to replace something taken away.  Five conditions:

        - **CAS's structure re-expresses as a standard key.**
          `comparable_inchikey_for` returns `None` for a relative or racemic
          registration, where reading the structure would invent an absolute
          arrangement -- the defect #42 exists to stop.
        - **CAS's structure states a shape at all**, asked of the InChI and not
          the key, because the key's second block hashes isotopes too and
          `Zinc-65` would otherwise read as stereo-specific (#55).
        - **Every candidate for the number has a gap the registry fills** --
          either shape-free, or shape-*incomplete* in the sense of
          `_registry_fills_the_gap`.  Where a source has already supplied the
          specific key there is no hole to fill, and the redundant flat one is
          `without_redundant_flat_keys`' business.
        - **Same skeleton.**  A different one is a different substance and a
          question for #35 and #38, not for this.
        - **Same protonation.**  An acid and its ion differ in the last block,
          and copying a shape across that boundary would answer a question
          nobody asked (#54).

        The partial case was added by #56 and is the *safer* of the two, which
        is worth saying because it looks like the bolder one.  Filling a wholly
        shape-free record rests on the registry alone: there is nothing in the
        candidate to agree or disagree with.  Filling a partial one rests on the
        registry having been checked against the candidate first and found to
        state the same arrangement at every centre the candidate assigns -- a
        record that contradicts ours at one centre and completes it at another
        fails the test and stays a `conflict` for a curator.

        Returns the key rather than a bool because the caller publishes it, and
        because "which key" is the part worth asserting in a test.
        """
        comparable = self._commonchemistry.comparable_inchikey_for(cas)
        if not comparable or not self._commonchemistry.registers_stereochemistry(cas):
            return ""
        theirs = parse_inchikey(comparable)
        if theirs is None or theirs.is_flat:
            return ""
        usable = [
            (candidate, parse_inchikey(candidate.inchikey))
            for candidate in candidates
            if candidate.inchikey
        ]
        usable = [
            (candidate, parts)
            for candidate, parts in usable
            if parts is not None and parts.skeleton == theirs.skeleton
        ]
        if not usable:
            return ""
        if any(
            parts.protonation != theirs.protonation
            or not (
                parts.is_flat
                or self._registry_fills_the_gap(cas=cas, candidate=candidate)
            )
            for candidate, parts in usable
        ):
            return ""
        return comparable

    def _restore_lost_stereochemistry(
        self,
        *,
        cas_numbers: list[str],
        chebi_ids: list[str],
        pubchem_compounds: list[dict[str, Any]],
    ) -> list[str]:
        """Which of *cas_numbers* have a stereochemistry to restore, and file it.

        Also withdraws the matching open row from the review queue -- `lost`
        where the whole shape was missing, `ours-undetermined` where part of it
        was.  A defect the pipeline has just repaired is not an open question,
        and leaving the row would ask a curator to fix what is already fixed --
        which is how the queue came to hold seven rows for objects that already
        published the right key.
        """
        candidates = [
            self._chebi_record_candidate(chebi_id) for chebi_id in chebi_ids
        ]
        candidates += [
            self._compound_candidate(compound)
            for compound in pubchem_compounds
            if isinstance(compound, dict)
        ]
        restored: list[str] = []
        for cas in cas_numbers:
            key = self._restored_stereochemistry_for(cas=cas, candidates=candidates)
            if not key:
                continue
            restored.append(cas)
            self._stereo_repairs[cas] = key
            replaced = [
                self._stereo_disagreements.pop(f"{cas}:{kind}", None)
                for kind in ("lost", "ours-undetermined")
            ]
            entry = self._stereo_disagreements.setdefault(f"{cas}:restored", {
                "cas": cas,
                "kind": "restored",
                "commonchemistry_inchikey": self._commonchemistry.inchikey_for(cas),
                "corrected_inchikey": key,
                "published_inchikeys": [],
                "sources": [],
            })
            # The keys this replaced, carried over from the row it supersedes so
            # the row still says what was there before.
            entry["published_inchikeys"] = sorted(
                set(entry["published_inchikeys"]).union(
                    *((row or {}).get("published_inchikeys", []) for row in replaced)
                )
            )
            entry["sources"] = sorted(
                set(entry["sources"]).union(
                    *((row or {}).get("sources", []) for row in replaced)
                )
            )
        return restored

    def _record_stereo_disagreement(
        self, *, cas: str, source: str, candidate: StructureCandidate
    ) -> None:
        """File a surviving structure's stereochemistry disagreement, if any."""
        kind = self._stereo_disagreement(cas=cas, candidate=candidate)
        if kind is None:
            return
        entry = self._stereo_disagreements.setdefault(f"{cas}:{kind}", {
            "cas": cas,
            "kind": kind,
            "commonchemistry_inchikey": self._commonchemistry.inchikey_for(cas),
            # What the substance should carry instead, where CAS's structure can
            # be re-expressed as a comparable key.  Empty when it cannot, which
            # is the honest answer for a relative or racemic registration.
            "corrected_inchikey": self._corrected_inchikey_for(
                cas=cas, candidate=candidate
            ),
            # Why there is no comparable key, for the rows that have none.  The
            # row has to describe the absence, and describing it as the wrong
            # one of three causes is the defect #55 reported.
            "conversion_refusal": self._commonchemistry.comparable_refusal_for(cas),
            "published_inchikeys": [],
            "sources": [],
        })
        entry["published_inchikeys"] = sorted(
            set(entry["published_inchikeys"]) | {candidate.inchikey}
        )
        entry["sources"] = sorted(set(entry["sources"]) | {source})

    def _filter_compounds_by_commonchemistry(
        self,
        *,
        cas: str,
        compounds: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Prefer the compound whose structure CAS publishes for this number.

        One-sided, exactly like the curated-CAS gate: a candidate is dropped
        only when another candidate is `CONFIRMED`.  If none is confirmed, every
        candidate survives.

        That restraint is deliberate, because Common Chemistry is strong
        evidence and not an oracle.  For metaldehyde, CAS 9002-91-9, it
        publishes acetaldehyde's key `IKHGUXGNUITLKF-…` where our tetramer
        `GKKDCARASOJPNG-…` is the better answer.  A gate that discarded every
        contradicted structure would have thrown that one away.  Contradictions
        with nothing better to replace them go to the review queue instead.

        `INCOMPARABLE` is kept for the same reason `UNKNOWN` is: it is the
        absence of a usable comparison, not the result of one.  A candidate
        whose only offence is that CAS published a non-standard key for the
        number has had nothing said against it.
        """
        if len(compounds) < 2:
            return compounds
        published = self._commonchemistry.inchikey_for(cas)
        if not published:
            return compounds

        verdicts = {
            compound["cid"]: self._structure_verdict(cas=cas, compound=compound)
            for compound in compounds
        }
        if StructureVerdict.CONFIRMED not in verdicts.values():
            return compounds

        kept = [
            compound for compound in compounds
            if verdicts[compound["cid"]] is not StructureVerdict.CONTRADICTED
        ]
        dropped = sorted(
            cid for cid, verdict in verdicts.items()
            if verdict is StructureVerdict.CONTRADICTED
        )
        if dropped:
            by_cid = {compound["cid"]: compound for compound in compounds}
            self._structure_exclusions.setdefault(cas, {
                "cas": cas,
                "reason": StructureVerdict.CONTRADICTED.value,
                "commonchemistry_inchikey": published,
                "kept_cids": sorted(compound["cid"] for compound in kept),
                "dropped_cids": dropped,
                # Which of the dropped compounds are the same molecule under a
                # different stereo descriptor rather than a different substance.
                # A curator reading this queue needs to tell #42 from #35, and
                # the two are indistinguishable from the CID alone.
                "stereo_only_cids": [
                    cid for cid in dropped
                    if same_skeleton(self._compound_inchikey(by_cid[cid]), published)
                ],
                # Kept, and worth naming: these are the candidates the gate
                # could not weigh because CAS's key for the number is
                # non-standard.  Without the field they read as agreeing.
                "incomparable_cids": sorted(
                    cid for cid, verdict in verdicts.items()
                    if verdict is StructureVerdict.INCOMPARABLE
                ),
            })
        return kept

    def _invents_stereochemistry(self, *, cas: str, candidate: str) -> bool:
        """Whether *candidate* gives *cas* stereochemistry the registry withholds.

        Three conditions, and each of them is load-bearing:

        - **CAS registers the number flat**, from a standard key.  See
          `CommonChemistryIndex.registers_without_stereochemistry`.
        - **The candidate is the same skeleton.**  A different skeleton is a
          different substance and a different bug -- #35 and #38 own that,
          and reading it here would let a stereochemistry rule delete a
          wrong-hit structure without saying so.
        - **The candidate carries stereochemistry.**  A flat candidate for a
          flat number agrees, which is the overwhelming majority: 5,726 of the
          6,300 keyed numbers in the cache are flat and 5,765 flow objects
          already agree with Common Chemistry outright.

        Only the conjunction is a defect, and only 33 flow objects meet it.
        """
        if not self._commonchemistry.registers_without_stereochemistry(cas):
            return False
        parts = parse_inchikey(candidate)
        if parts is None or parts.is_flat:
            return False
        return same_skeleton(candidate, self._commonchemistry.inchikey_for(cas) or "")

    def _filter_compounds_by_stereo_specificity(
        self,
        *,
        cas: str,
        compounds: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Drop compounds that give a stereo-unspecified CAS a stereochemistry.

        The gates above this one are comparative: they weigh candidates against
        each other and act only when one is better.  That is the right shape
        when the question is *which* of several structures a number means, and
        the wrong shape for #42's "stereo invented", where every candidate is
        wrong in the same direction.  Crotonaldehyde, CAS 4170-30-3, is
        registered flat and PubChem and ChEBI both answer with the *trans*
        isomer -- so nothing is contradicted, nothing is confirmed, and the
        narrowing gate returns early by design.  The result collides under
        InChIKey with `trans-2-butenal` at 123-73-9, which is a separately
        registered substance (#35).

        So this gate is not comparative.  Common Chemistry's flat key is read as
        a statement in its own right: *this number denotes the substance with
        its stereochemistry unstated*, and a stereo-specific structure reached
        through it describes a different substance, however many sources agree
        on it.

        It can empty the candidate list -- that is the same trade
        `_structure_bearing_cas` makes, and the reason both file to
        `commonchem-structure-exclusion` for review -- so the structure CAS
        *does* publish is put back in its place by
        `_merge_commonchemistry_semantic_properties`.

        On the 2026-08-12 build that replacement turns out to be confirmatory
        rather than load-bearing.  The gate acts on 90 numbers across 100 flow
        objects, and every one of them still gets the same flat key from a
        surviving PubChem or ChEBI candidate, or from RDKit deriving it from the
        source list's own structure; none publishes a key that only Common
        Chemistry supplied.  It is kept because it makes the outcome guaranteed
        rather than lucky -- nothing obliges PubChem to hold a flat compound for
        a number CAS registers flat -- but a reader should not be told it is
        doing more work than it is.
        """
        kept: list[dict[str, Any]] = []
        dropped: list[int] = []
        for compound in compounds:
            if self._invents_stereochemistry(
                cas=cas, candidate=self._compound_inchikey(compound)
            ):
                dropped.append(compound["cid"])
            else:
                kept.append(compound)
        if dropped:
            self._record_stereo_exclusion(cas=cas, cids=dropped)
        return kept

    def _record_stereo_exclusion(
        self,
        *,
        cas: str,
        cids: list[int] | None = None,
        chebi_ids: list[str] | None = None,
    ) -> None:
        """Note what this number's flat registration withheld.

        Merged rather than `setdefault`, unlike the exclusions above, because
        both lookup paths reach the same number and are gated separately --
        ChEBI in `_matched_chebi_ids` and PubChem in
        `_filter_compounds_by_stereo_specificity`.  Whichever ran first would
        otherwise be the only one reported, and for the 20 objects where both
        sources hand back the same stereo-specific structure the report would
        name half the cause.
        """
        entry = self._stereo_exclusions.setdefault(cas, {
            "cas": cas,
            "reason": StructureVerdict.STEREO_UNSPECIFIED.value,
            "commonchemistry_inchikey": self._commonchemistry.inchikey_for(cas),
            "dropped_cids": [],
            "dropped_chebi_ids": [],
        })
        entry["dropped_cids"] = sorted(set(entry["dropped_cids"]) | set(cids or []))
        entry["dropped_chebi_ids"] = sorted(
            set(entry["dropped_chebi_ids"]) | set(chebi_ids or [])
        )

    def _curated_cas_for_cid(self, cid: int) -> set[str] | None:
        """The CAS numbers PubChem's curated record lists for *cid*.

        `None` when no record is cached, which is not the same as an empty set:
        an empty set is PubChem saying it holds no registry CAS for the
        compound, and `None` is us not having asked.  `fetch_and_store_pubchem`
        caches `{}` for a compound whose PUG View record has no "Other
        Identifiers" section, so that distinction survives a run.
        """
        entry = self._pubchem_identifiers_by_cid.get(str(cid))
        if not isinstance(entry, dict):
            return None
        values: set[str] = set()
        for item in entry.get(CURATED_CAS_HEADING, []):
            if not isinstance(item, dict):
                continue
            value = item.get("value")
            if isinstance(value, str) and value.strip():
                values.add(value.strip())
        return values

    def _cas_attestation(self, *, cas: str, cid: int) -> CasAttestation:
        """Whether PubChem's curated record for *cid* backs the *cas* link."""
        curated = self._curated_cas_for_cid(cid)
        if curated is None:
            return CasAttestation.UNKNOWN
        if cas.strip() in curated:
            return CasAttestation.ATTESTED
        return CasAttestation.CONTRADICTED

    def _filter_compounds_by_curated_cas(
        self,
        *,
        cas: str,
        compounds: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Drop compounds whose own curated record denies the CAS.

        The rule is deliberately one-sided.  A compound is removed only when
        *another* candidate is attested -- there has to be a better answer
        before a worse one is discarded, so a CAS whose candidates are all
        unattested keeps every one of them and stays as ambiguous as it was.

        `UNKNOWN` is kept alongside `ATTESTED` for the same reason.  Dropping it
        would let a gap in the identifier cache decide identity, and the gap is
        large: 4,172 of the CIDs reachable from `by_cas` had no cached record
        before #249 backfilled them.
        """
        if len(compounds) < 2:
            return compounds

        verdicts = {
            compound["cid"]: self._cas_attestation(cas=cas, cid=compound["cid"])
            for compound in compounds
        }
        if CasAttestation.ATTESTED not in verdicts.values():
            return compounds

        kept = [
            compound for compound in compounds
            if verdicts[compound["cid"]] is not CasAttestation.CONTRADICTED
        ]
        dropped = sorted(
            cid for cid, verdict in verdicts.items()
            if verdict is CasAttestation.CONTRADICTED
        )
        if dropped:
            self._curated_cas_exclusions[cas] = {
                "cas": cas,
                "kept_cids": sorted(compound["cid"] for compound in kept),
                "dropped_cids": dropped,
                "unknown_cids": sorted(
                    cid for cid, verdict in verdicts.items()
                    if verdict is CasAttestation.UNKNOWN
                ),
            }
        return kept

    def _expected_formulas_for_flow(self, flow: dict[str, Any]) -> list[str]:
        expected: set[str] = set()
        properties = flow.properties
        if isinstance(properties, dict):
            row = properties.get(self.CHEMROF_MOLECULAR_FORMULA)
            if isinstance(row, dict):
                raw = row.get("@value")
                if isinstance(raw, list):
                    for value in raw:
                        if isinstance(value, str) and value.strip():
                            expected.add(value.strip())
                elif isinstance(raw, str) and raw.strip():
                    expected.add(raw.strip())

        # A loop over flow-level "formula"/"molecular_formula" keys used to sit
        # here.  Neither is a field of Flow, and neither appears in any input, so
        # it never contributed; formulas come from `properties` above.

        name = flow_label_value(flow) or ""
        if isinstance(name, str) and name.strip():
            base = name.strip()
            for pattern in (
                r",\s*ion\s*$",
                r"\(\s*[0-9IVXivx]+\s*[+-]?\s*\)\s*$",
                r"\(\s*[+-]?\s*[0-9]+\s*\)\s*$",
                r"\(\s*[0-9]+\s*[+-]\s*\)\s*$",
            ):
                base = re.sub(pattern, "", base).strip()
            symbol = self._element_symbol_by_name.get(base.lower())
            if symbol:
                expected.add(symbol)

        return sorted(expected)

    def _normalize_formula_for_parse(self, formula: str) -> str:
        return normalize_formula_for_parse(formula)

    def _formula_element_counts(self, formula: str) -> dict[str, int] | None:
        return formula_element_counts(formula)

    def _formula_similarity_score(self, left: str, right: str) -> float:
        return formula_similarity_score(left, right)

    def _compound_formula(self, compound: dict[str, Any]) -> str:
        for prop in compound.get("props", []):
            if not isinstance(prop, dict):
                continue
            urn = prop.get("urn", {})
            if not isinstance(urn, dict) or urn.get("label") != "Molecular Formula":
                continue
            value = prop.get("value", {})
            if not isinstance(value, dict):
                continue
            sval = value.get("sval")
            if isinstance(sval, str) and sval.strip():
                return sval.strip()
        return ""

    def _filter_compounds_by_formula_similarity(
        self,
        *,
        cas: str,
        compounds: list[dict[str, Any]],
        expected_formulas: list[str],
    ) -> list[dict[str, Any]]:
        if len(compounds) < 2 or not expected_formulas:
            return compounds
        scored: list[tuple[float, dict[str, Any]]] = []
        for compound in compounds:
            formula = self._compound_formula(compound)
            if not formula:
                scored.append((0.0, compound))
                continue
            score = max(
                self._formula_similarity_score(formula, expected)
                for expected in expected_formulas
            )
            scored.append((score, compound))
        best_score = max(score for score, _ in scored) if scored else 0.0
        if best_score < self.FORMULA_SIMILARITY_MIN_SCORE:
            return compounds
        kept = [
            compound
            for score, compound in scored
            if score >= self.FORMULA_SIMILARITY_MIN_SCORE
            and score >= best_score - self.FORMULA_SIMILARITY_KEEP_WINDOW
        ]
        if not kept:
            return compounds
        return kept

    def _build_properties(
        self,
        *,
        existing: Any,
        chebi_ids: list[str],
        pubchem_compounds: list[dict[str, Any]],
        stereo_unspecified_cas: list[str] | None = None,
        stereo_restored_cas: list[str] | None = None,
        structure_cas: list[str] | None = None,
    ) -> dict[str, Any]:
        out: dict[str, Any] = {}
        if isinstance(existing, dict):
            # Keep pre-existing non-source-grouped properties as-is.
            for key, value in existing.items():
                if key in {"chebi", "pubchem", "consensus"}:
                    continue
                out[key] = value

        chebi_formulas = []
        chebi_basic_props: dict[str, set[str]] = defaultdict(set)
        for chebi_id in chebi_ids:
            rec = self._chebi_records.get(chebi_id, {})
            formula = rec.get("formula")
            if isinstance(formula, str) and formula.strip():
                chebi_formulas.append(formula.strip())
            basic_values = rec.get("basic_property_values", {})
            if isinstance(basic_values, dict):
                for key, values in basic_values.items():
                    if not isinstance(key, str) or not key.strip():
                        continue
                    if not isinstance(values, list):
                        continue
                    for value in values:
                        if isinstance(value, str) and value.strip():
                            chebi_basic_props[key.strip()].add(value.strip())

        pubchem_cids: list[int] = []
        pubchem_formulas: list[str] = []
        pubchem_inchikeys: list[str] = []
        pubchem_molecular_mass: list[str] = []
        pubchem_monoisotopic_mass: list[str] = []
        pubchem_iupac_names: list[str] = []
        pubchem_smiles: list[str] = []
        pubchem_inchi: list[str] = []
        pubchem_charge: list[str] = []
        for compound in pubchem_compounds:
            cid = compound.get("cid")
            if isinstance(cid, int):
                pubchem_cids.append(cid)
                id_map = self._pubchem_identifiers_by_cid.get(str(cid), {})
                if isinstance(id_map, dict):
                    for item in id_map.get("IUPAC Name", []):
                        if not isinstance(item, dict):
                            continue
                        value = item.get("value")
                        if isinstance(value, str) and value.strip():
                            pubchem_iupac_names.append(value.strip())
            for prop in compound.get("props", []):
                urn = prop.get("urn", {})
                label = urn.get("label")
                name = urn.get("name")
                value = prop.get("value", {})
                sval = value.get("sval")
                fval = value.get("fval")
                if not isinstance(sval, str) or not sval.strip():
                    text = ""
                else:
                    text = sval.strip()
                if label == "Molecular Formula" and text:
                    pubchem_formulas.append(text)
                elif label == "InChIKey" and text:
                    pubchem_inchikeys.append(text)
                elif label == "SMILES" and text:
                    pubchem_smiles.append(text)
                elif label == "InChI" and text:
                    pubchem_inchi.append(text)
                elif label == "Molecular Weight":
                    if isinstance(fval, (int, float)):
                        pubchem_molecular_mass.append(str(fval))
                elif label == "Mass" and name == "Monoisotopic":
                    if isinstance(fval, (int, float)):
                        pubchem_monoisotopic_mass.append(str(fval))
                elif label == "IUPAC Name" and text:
                    # Skip markup variants with inline HTML tags.
                    if name != "Markup":
                        pubchem_iupac_names.append(text)
                elif label == "Charge":
                    if isinstance(fval, (int, float)):
                        pubchem_charge.append(str(int(fval) if float(fval).is_integer() else fval))

        semantic = self._merge_existing_semantic_properties(out)
        chebi_semantic = self._build_chebi_semantic_properties(
            chebi_ids=chebi_ids,
            chebi_formulas=chebi_formulas,
            chebi_basic_props=chebi_basic_props,
        )
        for iri, entry in chebi_semantic.items():
            self._merge_semantic_property(
                semantic=semantic,
                iri=iri,
                label=entry.get(RDFS_LABEL_CURIE, ""),
                values=entry.get("@value", []),
                provenance=entry.get("provenance"),
                unit_iri=_PROPERTY_UNIT_IRIS.get(iri),
            )

        pubchem_source = [f"CID:{cid}" for cid in sorted(set(pubchem_cids))]
        self._merge_semantic_property(
            semantic=semantic,
            iri=self.CHEMROF_MOLECULAR_FORMULA,
            label="Molecular formula",
            values=sorted(set(pubchem_formulas)),
            provenance=Provenance(
                was_generated_by="enrich_references.pubchem_semantic",
                was_attributed_to="brightway-flows",
                had_primary_source=pubchem_source,
                was_derived_from="pubchem.props.Molecular Formula",
            ).to_dict(),
        )
        self._merge_semantic_property(
            semantic=semantic,
            iri=self.CHEMROF_INCHI2D_KEY_STRING,
            label="InChIKey",
            values=sorted(set(pubchem_inchikeys)),
            provenance=Provenance(
                was_generated_by="enrich_references.pubchem_semantic",
                was_attributed_to="brightway-flows",
                had_primary_source=pubchem_source,
                was_derived_from="pubchem.props.InChIKey",
            ).to_dict(),
        )
        self._merge_semantic_property(
            semantic=semantic,
            iri=self.CHEMROF_SMILES_STRING,
            label="SMILES",
            values=sorted(set(pubchem_smiles)),
            provenance=Provenance(
                was_generated_by="enrich_references.pubchem_semantic",
                was_attributed_to="brightway-flows",
                had_primary_source=pubchem_source,
                was_derived_from="pubchem.props.SMILES",
            ).to_dict(),
        )
        self._merge_semantic_property(
            semantic=semantic,
            iri=self.CHEMROF_INCHI2D_STRING,
            label="InChI",
            values=sorted(set(pubchem_inchi)),
            provenance=Provenance(
                was_generated_by="enrich_references.pubchem_semantic",
                was_attributed_to="brightway-flows",
                had_primary_source=pubchem_source,
                was_derived_from="pubchem.props.InChI",
            ).to_dict(),
        )
        self._merge_semantic_property(
            semantic=semantic,
            iri=self.CHEMROF_MOLECULAR_MASS,
            label="Molecular mass",
            values=sorted(set(pubchem_molecular_mass)),
            provenance=Provenance(
                was_generated_by="enrich_references.pubchem_semantic",
                was_attributed_to="brightway-flows",
                had_primary_source=pubchem_source,
                was_derived_from="pubchem.props.Molecular Weight",
            ).to_dict(),
            unit_iri=UNIT_IRI_GM_PER_MOL,
        )
        self._merge_semantic_property(
            semantic=semantic,
            iri=self.CHEMROF_MONOISOTOPIC_MASS,
            label="Monoisotopic mass",
            values=sorted(set(pubchem_monoisotopic_mass)),
            provenance=Provenance(
                was_generated_by="enrich_references.pubchem_semantic",
                was_attributed_to="brightway-flows",
                had_primary_source=pubchem_source,
                was_derived_from="pubchem.props.Mass.Monoisotopic",
            ).to_dict(),
            unit_iri=UNIT_IRI_GM_PER_MOL,
        )
        self._merge_semantic_property(
            semantic=semantic,
            iri=self.CHEMROF_IUPAC_NAME,
            label="IUPAC name",
            values=sorted(set(pubchem_iupac_names)),
            provenance=Provenance(
                was_generated_by="enrich_references.pubchem_semantic",
                was_attributed_to="brightway-flows",
                had_primary_source=pubchem_source,
                was_derived_from="pubchem.identifiers.IUPAC Name",
            ).to_dict(),
        )
        self._merge_semantic_property(
            semantic=semantic,
            iri=self.CHEMROF_ELEMENTAL_CHARGE,
            label="Elemental charge",
            values=sorted(set(pubchem_charge)),
            provenance=Provenance(
                was_generated_by="enrich_references.pubchem_semantic",
                was_attributed_to="brightway-flows",
                had_primary_source=pubchem_source,
                was_derived_from="pubchem.props.Charge",
            ).to_dict(),
            unit_iri=UNIT_IRI_NUM,
        )

        self._merge_commonchemistry_semantic_properties(
            semantic=semantic, cas_numbers=stereo_unspecified_cas or []
        )
        self._merge_restored_stereochemistry(
            semantic=semantic, cas_numbers=stereo_restored_cas or []
        )
        self._drop_redundant_flat_inchikeys(semantic)
        self._drop_superseded_stereo_inchikeys(
            semantic=semantic, cas_numbers=structure_cas or []
        )
        self._drop_foreign_protonation_inchikeys(
            semantic=semantic, cas_numbers=structure_cas or []
        )
        # The three gates above rewrite `@value` in place and know nothing about
        # per-value attribution, which is the point of keying it on the value
        # rather than on the position.  Clearing what they withdrew is one pass
        # here rather than three obligations they could each forget.
        for entry in semantic.values():
            prune(entry)

        out.update(semantic)
        cleaned_out = self._prune_empty(out)
        return cleaned_out if isinstance(cleaned_out, dict) else {}

    def _drop_redundant_flat_inchikeys(
        self, semantic: dict[str, dict[str, Any]]
    ) -> None:
        """Take out any key the record's own specific key already covers.

        Here rather than in `_merge_semantic_property`, because the question is
        about the slot as a whole and every source has had its say by this
        point: ChEBI, PubChem and -- for a number Common Chemistry registers
        without stereochemistry -- the registry, plus whatever the record
        arrived with.  A flat key from any of them beside a specific one for the
        same skeleton is the same substance stated twice, and the flat string is
        another substance's real key (#50).

        This stage supplies the flat key on its own for 59 of the 419 flow
        objects where the redundancy appears in the 2026-08-12 build; the rest
        come from the RDKit stages, which refuse it at their own write.

        Provenance is left alone.  It is recorded per property rather than per
        value, so every source that attested to the structure is still named on
        the slot -- the same treatment `collapse_smiles_spellings` gives the
        spellings it collapses.
        """
        entry = semantic.get(self.CHEMROF_INCHI2D_KEY_STRING)
        if not isinstance(entry, dict):
            return
        raw = entry.get("@value")
        if not isinstance(raw, list) or len(raw) < 2:
            return
        kept = without_redundant_flat_keys(str(v) for v in raw)
        if len(kept) == len(raw):
            return
        entry["@value"] = kept

    def _drop_superseded_stereo_inchikeys(
        self,
        *,
        semantic: dict[str, dict[str, Any]],
        cas_numbers: list[str],
    ) -> None:
        """Take out a stereoisomer the registry's own answer supersedes.

        `_drop_redundant_flat_inchikeys` handles a *flat* key beside a specific
        one.  This handles the other way an object ends up with two identities
        for one substance: **two specific keys on the same skeleton**, one from
        ChEBI and one from PubChem, with nothing in the pipeline reconciling the
        two paths against each other.  `Pyrethrin I` publishes both
        `ROVGZAWFACYCSP-VUMXUWRFSA-N` and `ROVGZAWFACYCSP-NEWSRXKRSA-N`, and
        anything using an InChIKey as an identity sees two substances.

        The tie is only broken where the registry breaks it, and only when one
        of the keys *is* the registry's answer -- re-expressed as a standard key
        by `comparable_inchikey_for`, since CAS often writes its own in a
        notation nothing here can compare with.  That is a stronger position
        than the structure gate's: it does not weigh candidates against Common
        Chemistry and pick a winner, it observes that one of the object's own
        keys was independently reproduced by the registry and that the others
        therefore describe something else.

        Withdrawing rather than choosing.  A group where **no** key matches the
        registry is left entirely alone -- that is the `conflict` band, which
        wants a curator (#56) -- and so is a group where the registry has no
        comparable answer at all.

        Only stereochemistry-bearing keys are taken.  A flat key in the group
        states nothing the specific one contradicts, and belongs to #50 and to
        the method above.

        And only a *stereochemistry*, asked of the registry's structure rather
        than of its key.  Block 2 of an InChIKey hashes isotopic labelling too,
        so `HCWPIIXVSYCSAN-IGMARMGPSA-N` and `HCWPIIXVSYCSAN-YPZZEJLDSA-N` look
        like two stereoisomers of radium and are radium-226 and radium-224.
        Withdrawing one of those would delete a substance rather than a second
        identity for one, which is the opposite of what this method is for
        (#55).  Nothing is currently offered that this refuses: each of the 37
        flow objects carrying a number CAS registers as an isotope holds a
        single key for the skeleton.

        On the 2026-08-12 build this fires on 8 flow objects across 106
        elementary flows, six of which are the pyrethrin esters, where the
        withdrawn key is missing the double-bond geometry the registry and the
        surviving key both state.  Provenance is left alone, for the same reason
        as above.
        """
        entry = semantic.get(self.CHEMROF_INCHI2D_KEY_STRING)
        if not isinstance(entry, dict):
            return
        raw = entry.get("@value")
        if not isinstance(raw, list) or len(raw) < 2:
            return
        values = [str(v) for v in raw]
        superseded: set[str] = set()
        for cas in cas_numbers:
            if not self._commonchemistry.registers_stereochemistry(cas):
                continue
            comparable = self._commonchemistry.comparable_inchikey_for(cas)
            theirs = parse_inchikey(comparable or "")
            if theirs is None or theirs.is_flat:
                continue
            group = [(v, parse_inchikey(v)) for v in values]
            group = [
                (v, p) for v, p in group
                if p is not None
                and p.skeleton == theirs.skeleton
                and p.protonation == theirs.protonation
            ]
            if not any(p.stereo == theirs.stereo for _, p in group):
                continue
            dropped = {
                v for v, p in group if p.stereo != theirs.stereo and not p.is_flat
            }
            if not dropped:
                continue
            superseded |= dropped
            self._record_superseded_stereochemistry(
                cas=cas, kept=comparable or "", dropped=sorted(dropped)
            )
        if not superseded:
            return
        entry["@value"] = [v for v in values if v not in superseded]

    def _record_superseded_stereochemistry(
        self, *, cas: str, kept: str, dropped: list[str]
    ) -> None:
        """File a withdrawn stereoisomer, so the removal is not silent.

        Onto the `restored` row where this run put the surviving key there
        itself.  The `superseded` row exists to say a structure claim was
        discarded and that somebody should check it, and that is the wrong thing
        to say about a key the same run replaced with one stating everything it
        stated and more: nothing was discarded but a gap, and the `restored` row
        already reports the repair.  Two rows for one event would also read as
        two defects (#56).
        """
        kind = "restored" if self._stereo_repairs.get(cas) == kept else "superseded"
        entry = self._stereo_disagreements.setdefault(f"{cas}:{kind}", {
            "cas": cas,
            "kind": kind,
            "commonchemistry_inchikey": self._commonchemistry.inchikey_for(cas),
            "corrected_inchikey": kept,
            "published_inchikeys": [],
            "sources": [],
        })
        entry["published_inchikeys"] = sorted(
            set(entry["published_inchikeys"]) | set(dropped)
        )

    def _drop_foreign_protonation_inchikeys(
        self,
        *,
        semantic: dict[str, dict[str, Any]],
        cas_numbers: list[str],
    ) -> None:
        """Take out a key that is the registry's structure with its charge changed.

        The third way one object ends up publishing two identities, after the
        flat key beside a specific one (#50) and the two stereoisomers of
        `_drop_superseded_stereo_inchikeys` (#42).  Here the two keys agree
        about the skeleton *and* about the shape, and differ in the last block
        alone::

            (2R,3R)-2,3-dihydroxybutanedioic acid, 87-69-4
                FEWJPZIEWOKRBE-JCYAYHJZSA-N   tartaric acid, and CAS's own answer
                FEWJPZIEWOKRBE-JCYAYHJZSA-L   tartrate, two hydrogen ions gone

        That is not a simplification of the other, as a flat key is.  It is a
        second substance: a different formula, a different charge, and a
        different mass.  One came through ChEBI and one through PubChem, and
        nothing reconciled the two paths, so both were kept.

        The tie is broken exactly where `_drop_superseded_stereo_inchikeys`
        breaks it, and on the same reasoning: only where one of the object's own
        keys *is* the structure the registry publishes for the number.  Nothing
        is chosen on the registry's authority -- one key has been independently
        reproduced by it, and the other therefore describes something the
        registry does not call by this number.

        The restraints, and what each refuses:

        - **The registry's answer must be present.**  Where it is not -- 11 of
          the 15 objects publishing a charge clash on the 2026-08-13 build,
          most of them salts the registry answers with a different skeleton
          altogether -- nothing is touched and the row stays open.
        - **Same shape.**  A key differing in the second block as well is not
          this substance with its charge changed, and belongs to the band above.
        - **Same InChI version**, because two hashing schemes are not two
          substances.

        The same-shape requirement is also why this needs no isotope guard,
        unlike the method above: block 2 hashes isotopic labelling too, so
        radium-226 and radium-224 differ in it and are never in one group here.
        Two keys reaching this point carry the same label as well as the same
        arrangement, and differ only in how many hydrogen ions came off (#55).

        Unlike the stereochemistry sibling this does *not* require either key to
        carry a shape: the flat pair `SLXKOJJOQWFEFD-UHFFFAOYSA-N` and `-M`,
        6-aminohexanoic acid and its anion, are two identities for the same
        reason the tartaric ones are.

        4 flow objects across 52 elementary flows on the 2026-08-13 build.
        Provenance is left alone, for the same reason as the two methods above:
        the values that stay came from the sources the provenance names.
        """
        entry = semantic.get(self.CHEMROF_INCHI2D_KEY_STRING)
        if not isinstance(entry, dict):
            return
        raw = entry.get("@value")
        if not isinstance(raw, list) or len(raw) < 2:
            return
        values = [str(v) for v in raw]
        withdrawn: set[str] = set()
        for cas in cas_numbers:
            comparable = self._commonchemistry.comparable_inchikey_for(cas)
            theirs = parse_inchikey(comparable or "")
            if theirs is None:
                continue
            group = [(v, parse_inchikey(v)) for v in values]
            group = [
                (v, p) for v, p in group
                if p is not None
                and p.skeleton == theirs.skeleton
                and p.stereo == theirs.stereo
                and p.version == theirs.version
            ]
            if not any(p.protonation == theirs.protonation for _, p in group):
                continue
            dropped = {v for v, p in group if p.protonation != theirs.protonation}
            if not dropped:
                continue
            withdrawn |= dropped
            self._record_withdrawn_protonation(
                cas=cas, kept=comparable or "", dropped=sorted(dropped)
            )
        if not withdrawn:
            return
        entry["@value"] = [v for v in values if v not in withdrawn]

    def _record_withdrawn_protonation(
        self, *, cas: str, kept: str, dropped: list[str]
    ) -> None:
        """File a withdrawn ion, and close the open row it answers.

        The classifier files a `protonation` row for the same key when the
        candidate arrives, and the two are one finding: leaving both would ask a
        curator to settle what the pipeline has already settled, which is the
        mistake `_restore_lost_stereochemistry` had to undo for the `lost` rows.
        The open row keeps whichever of its keys survived, and goes when none
        did.
        """
        gone = self._protonation_withdrawals.setdefault(cas, set())
        gone |= set(dropped)
        entry = self._stereo_disagreements.setdefault(f"{cas}:protonation-withdrawn", {
            "cas": cas,
            "kind": "protonation-withdrawn",
            "commonchemistry_inchikey": self._commonchemistry.inchikey_for(cas),
            "corrected_inchikey": kept,
            "published_inchikeys": [],
            "sources": [],
        })
        entry["published_inchikeys"] = sorted(
            set(entry["published_inchikeys"]) | set(dropped)
        )
        reported = self._stereo_disagreements.get(f"{cas}:protonation")
        if reported is None:
            return
        remaining = [
            value for value in reported["published_inchikeys"] if value not in gone
        ]
        if remaining:
            reported["published_inchikeys"] = remaining
            return
        entry["sources"] = sorted(set(entry["sources"]) | set(reported["sources"]))
        del self._stereo_disagreements[f"{cas}:protonation"]

    def _merge_commonchemistry_semantic_properties(
        self,
        *,
        semantic: dict[str, dict[str, Any]],
        cas_numbers: list[str],
    ) -> None:
        """Publish the structure CAS registers for a number, where it was needed.

        The only place Common Chemistry is a *source* of structure rather than a
        referee of other sources' structures.  It earns that here because it is
        the only source that holds the answer: PubChem and ChEBI index compounds,
        and a substance registered with its stereochemistry unstated is not a
        compound either of them has a record for.  Crotonaldehyde's flat key
        exists in exactly one place we read, and dropping the *trans* isomer
        without putting it back would leave the flow with no identity at all --
        trading #42 for #223.

        Three values and no more.  The key, the InChI and the formula are what
        Common Chemistry states; a SMILES would have to be computed from the
        InChI, and a derived value belongs to the stage that derives it, under
        its own provenance, not smuggled in under the registry's name.
        """
        keys: list[str] = []
        inchis: list[str] = []
        formulae: list[str] = []
        sources: list[str] = []
        for cas in cas_numbers:
            key = self._commonchemistry.inchikey_for(cas)
            if not key:
                continue
            sources.append(f"CAS:{cas}")
            keys.append(key)
            inchi = self._commonchemistry.inchi_for(cas)
            if inchi:
                inchis.append(inchi)
            formula = self._commonchemistry.formula_for(cas)
            if formula:
                formulae.append(formula)
        if not sources:
            return

        for iri, label, values, derived_from in (
            (self.CHEMROF_INCHI2D_KEY_STRING, "InChIKey", keys, "commonchemistry.inchiKey"),
            (self.CHEMROF_INCHI2D_STRING, "InChI", inchis, "commonchemistry.inchi"),
            (
                self.CHEMROF_MOLECULAR_FORMULA,
                "Molecular formula",
                formulae,
                "commonchemistry.molecularFormula",
            ),
        ):
            self._merge_semantic_property(
                semantic=semantic,
                iri=iri,
                label=label,
                values=sorted(set(values)),
                provenance=Provenance(
                    was_generated_by="enrich_references.commonchemistry_semantic",
                    was_attributed_to="brightway-flows",
                    had_primary_source=sorted(set(sources)),
                    was_derived_from=derived_from,
                ).to_dict(),
            )

    def _merge_restored_stereochemistry(
        self,
        *,
        semantic: dict[str, dict[str, Any]],
        cas_numbers: list[str],
    ) -> None:
        """Publish the stereochemistry CAS states and no other source could.

        The counterpart of `_merge_commonchemistry_semantic_properties`, and the
        one place the registry's structure is used to *add* a claim rather than
        to replace one the pipeline has just withdrawn.  It is a separate method
        under a separate provenance name for exactly that reason: the gates in
        this class can only ever refuse a candidate, and a step that can add one
        should be visible as itself in the change log rather than folded into a
        gate's write.

        The **converted** key and InChI, not the ones CAS published.  Six of the
        seven numbers this fires on are registered with a non-standard InChI, so
        CAS's own key cannot be compared with anything else in the list and
        publishing it would put a string in the slot that no consumer can join
        on.  `comparable_inchikey_for` re-expresses the same structure as a
        standard key; `comparable_inchi_for` hands over the string it came from,
        so the two agree with each other.

        No formula.  Stereochemistry does not change one, so the formula already
        on the object is the same formula, and adding CAS's spelling of it would
        put a second value in the slot to no purpose.

        The flat key this supersedes is not removed here.  It goes in
        `_drop_redundant_flat_inchikeys`, which runs next and already withdraws
        a flat key that a specific key of the same skeleton covers (#50) --
        this only has to supply the specific one.
        """
        keys: list[str] = []
        inchis: list[str] = []
        sources: list[str] = []
        for cas in cas_numbers:
            key = self._commonchemistry.comparable_inchikey_for(cas)
            if not key:
                continue
            sources.append(f"CAS:{cas}")
            keys.append(key)
            inchi = self._commonchemistry.comparable_inchi_for(cas)
            if inchi:
                inchis.append(inchi)
        if not sources:
            return

        for iri, label, values, derived_from in (
            (
                self.CHEMROF_INCHI2D_KEY_STRING,
                "InChIKey",
                keys,
                "commonchemistry.inchi",
            ),
            (self.CHEMROF_INCHI2D_STRING, "InChI", inchis, "commonchemistry.inchi"),
        ):
            self._merge_semantic_property(
                semantic=semantic,
                iri=iri,
                label=label,
                values=sorted(set(values)),
                provenance=Provenance(
                    was_generated_by="enrich_references.commonchemistry_stereochemistry",
                    was_attributed_to="brightway-flows",
                    had_primary_source=sorted(set(sources)),
                    was_derived_from=derived_from,
                ).to_dict(),
            )

    def _build_definitions(
        self,
        *,
        existing: Any,
        chebi_ids: list[str],
        pubchem_compounds: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        merged: dict[tuple[str, str], dict[str, Any]] = {}

        def _insert(
            *,
            text: str,
            language: str,
            provenance: dict[str, Any],
        ) -> None:
            # ChEBI writes definitions with markup -- `<i>trans</i>`,
            # `<small>D</small>`, `<sub>2</sub>` -- in 29,660 of its records.
            # Definitions never passed through `coerce_label`, so unlike labels
            # they were published raw.  Stripping here, where every definition
            # is created, also means two sources that differ only in markup
            # collapse to one entry instead of two.
            value = strip_markup(text).strip()
            lang = (language or "en").strip() or "en"
            if not value:
                return
            key = (lang.lower(), value)
            entry = merged.get(key)
            if entry is None:
                merged[key] = {
                    "@value": value,
                    "@language": lang,
                    "provenance": provenance,
                }
                return
            existing_prov = entry.get("provenance")
            rows: list[dict[str, Any]] = []
            if isinstance(existing_prov, dict):
                rows = [existing_prov]
            elif isinstance(existing_prov, list):
                rows = [x for x in existing_prov if isinstance(x, dict)]
            marker = orjson.dumps(provenance, option=orjson.OPT_SORT_KEYS).decode("utf-8")
            seen = {
                orjson.dumps(row, option=orjson.OPT_SORT_KEYS).decode("utf-8")
                for row in rows
            }
            if marker not in seen:
                rows.append(provenance)
            entry["provenance"] = rows[0] if len(rows) == 1 else rows

        if isinstance(existing, list):
            for row in existing:
                if not isinstance(row, dict):
                    continue
                value = row.get("@value")
                if not isinstance(value, str) or not value.strip():
                    continue
                language = row.get("@language")
                lang = language if isinstance(language, str) and language.strip() else "en"
                prov = row.get("provenance")
                _insert(
                    text=value,
                    language=lang,
                    provenance=prov if isinstance(prov, dict) else Provenance(
                        was_generated_by="legacy_definition_import",
                        was_attributed_to="brightway-flows",
                    ).to_dict(),
                )

        for chebi_id in chebi_ids:
            rec = self._chebi_records.get(chebi_id, {})
            for text in rec.get("definitions", []):
                if not isinstance(text, str) or not text.strip():
                    continue
                _insert(
                    text=text,
                    language="en",
                    provenance=Provenance(
                        was_generated_by="enrich_references.chebi_definition",
                        was_attributed_to="brightway-flows",
                        had_primary_source=[chebi_id],
                        was_derived_from="chebi.definition",
                    ).to_dict(),
                )

        for compound in pubchem_compounds:
            cid = compound.get("cid")
            if not isinstance(cid, int):
                continue
            id_map = self._pubchem_identifiers_by_cid.get(str(cid), {})
            if not isinstance(id_map, dict):
                continue
            for item in id_map.get("Record Description", []):
                if not isinstance(item, dict):
                    continue
                text = item.get("value")
                if not isinstance(text, str) or not text.strip():
                    continue
                _insert(
                    text=text,
                    language="en",
                    provenance=Provenance(
                        was_generated_by="enrich_references.pubchem_definition",
                        was_attributed_to="brightway-flows",
                        had_primary_source=[f"CID:{cid}"],
                        was_derived_from="pubchem.identifiers.Record Description",
                    ).to_dict(),
                )

        return [
            merged[key]
            for key in sorted(merged.keys(), key=lambda x: (x[0], x[1].lower()))
        ]

    def _merge_existing_semantic_properties(self, out: dict[str, Any]) -> dict[str, dict[str, Any]]:
        semantic: dict[str, dict[str, Any]] = {}
        for key, value in out.items():
            if not isinstance(key, str) or not key.startswith("http"):
                continue
            if not isinstance(value, dict):
                continue
            semantic[key] = dict(value)
        return semantic

    def _merge_semantic_property(
        self,
        *,
        semantic: dict[str, dict[str, Any]],
        iri: str,
        label: str,
        values: Any,
        provenance: Any,
        unit_iri: str | None = None,
    ) -> None:
        if not isinstance(iri, str) or not iri.strip():
            return
        clean_values = sorted({
            str(v).strip()
            for v in (values if isinstance(values, list) else [])
            if str(v).strip()
        })
        if not clean_values:
            return
        entry = semantic.get(iri, {"@id": iri})
        existing_values = entry.get("@value", [])
        merged_values = sorted({
            str(v).strip()
            for v in ([*existing_values, *clean_values] if isinstance(existing_values, list) else clean_values)
            if str(v).strip()
        })
        entry["@value"] = merged_values
        # `clean_values`, not `merged_values`: this source stands behind what it
        # just gave, and appending to a slot is not an attestation of what was
        # already in it (#310).
        if isinstance(provenance, dict):
            attest(entry, clean_values, str(provenance.get(PROV_WAS_GENERATED_BY_CURIE) or ""))
        if isinstance(label, str) and label.strip() and not entry.get(RDFS_LABEL_CURIE):
            entry[RDFS_LABEL_CURIE] = label.strip()
        if isinstance(unit_iri, str) and unit_iri.strip() and not entry.get(QUDT_HAS_UNIT):
            entry[QUDT_HAS_UNIT] = unit_iri
        existing_prov = entry.get("provenance")
        prov_rows: list[dict[str, Any]] = []
        if isinstance(existing_prov, list):
            prov_rows.extend([x for x in existing_prov if isinstance(x, dict)])
        elif isinstance(existing_prov, dict):
            prov_rows.append(existing_prov)
        if isinstance(provenance, dict):
            marker = orjson.dumps(provenance, option=orjson.OPT_SORT_KEYS).decode("utf-8")
            seen = {
                orjson.dumps(row, option=orjson.OPT_SORT_KEYS).decode("utf-8")
                for row in prov_rows
            }
            if marker not in seen:
                prov_rows.append(provenance)
        if len(prov_rows) == 1:
            entry["provenance"] = prov_rows[0]
        elif prov_rows:
            entry["provenance"] = prov_rows
        semantic[iri] = entry

    def _build_semantic_entry(
        self,
        *,
        iri: str,
        label: str,
        values: list[str],
        chebi_ids: list[str],
        derived_from: str,
    ) -> dict[str, Any]:
        return {
            RDFS_LABEL_CURIE: label,
            "@value": values,
            "provenance": Provenance(
                was_generated_by="enrich_references.chebi_semantic",
                was_attributed_to="brightway-flows",
                had_primary_source=chebi_ids,
                was_derived_from=derived_from,
            ).to_dict(),
            "@id": iri,
        }

    def _build_chebi_semantic_properties(
        self,
        *,
        chebi_ids: list[str],
        chebi_formulas: list[str],
        chebi_basic_props: dict[str, set[str]],
    ) -> dict[str, dict[str, Any]]:
        key_to_predicate = {
            "generalized_empirical_formula": (
                self.CHEMROF_MOLECULAR_FORMULA,
                "Molecular formula",
                "chebi.basic_property_values.generalized_empirical_formula",
            ),
            "smiles_string": (
                self.CHEMROF_SMILES_STRING,
                "SMILES",
                "chebi.basic_property_values.smiles_string",
            ),
            "inchi_string": (
                self.CHEMROF_INCHI2D_STRING,
                "InChI",
                "chebi.basic_property_values.inchi_string",
            ),
            "inchi_key_string": (
                self.CHEMROF_INCHI2D_KEY_STRING,
                "InChIKey",
                "chebi.basic_property_values.inchi_key_string",
            ),
            "mass": (
                self.CHEMROF_MOLECULAR_MASS,
                "Molecular mass",
                "chebi.basic_property_values.mass",
            ),
            "monoisotopic_mass": (
                self.CHEMROF_MONOISOTOPIC_MASS,
                "Monoisotopic mass",
                "chebi.basic_property_values.monoisotopic_mass",
            ),
            "charge": (
                self.CHEMROF_ELEMENTAL_CHARGE,
                "Elemental charge",
                "chebi.basic_property_values.charge",
            ),
        }
        semantic: dict[str, dict[str, Any]] = {}

        formula_values = sorted(set(chebi_formulas))
        if formula_values:
            iri, label, derived_from = key_to_predicate["generalized_empirical_formula"]
            semantic[iri] = self._build_semantic_entry(
                iri=iri,
                label=label,
                values=formula_values,
                chebi_ids=chebi_ids,
                derived_from=derived_from,
            )

        for key, (iri, label, derived_from) in key_to_predicate.items():
            raw = chebi_basic_props.get(key, set())
            values = sorted({x for x in raw if isinstance(x, str) and x.strip()})
            if not values:
                continue
            semantic[iri] = self._build_semantic_entry(
                iri=iri,
                label=label,
                values=values,
                chebi_ids=chebi_ids,
                derived_from=derived_from,
            )

        return semantic

    def _reference_entry(
        self,
        *,
        url: str,
        generated_by: str,
        source_hint: str,
        derived_from: str,
    ) -> dict[str, Any]:
        return {
            "@id": url,
            "provenance": Provenance(
                was_generated_by=generated_by,
                was_attributed_to="brightway-flows",
                had_primary_source=[source_hint] if source_hint else [],
                was_derived_from=derived_from,
            ).to_dict(),
        }

    def _build_references(
        self,
        *,
        existing: Any,
        chebi_ids: list[str],
        pubchem_compounds: list[dict[str, Any]],
        cas_numbers: list[str],
    ) -> list[dict[str, Any]]:
        refs: dict[str, dict[str, Any]] = {}
        source_hint = ",".join(sorted(set(chebi_ids))) if chebi_ids else "CAS-aligned-record"
        if isinstance(existing, list):
            for value in existing:
                if isinstance(value, str) and value.strip():
                    url = value.strip()
                    refs[url] = refs.get(url) or self._reference_entry(
                        url=url,
                        generated_by="legacy_reference_import",
                        source_hint=source_hint,
                        derived_from="references",
                    )
                elif isinstance(value, dict):
                    url = value.get("@id")
                    if isinstance(url, str) and url.strip():
                        refs[url.strip()] = value

        for chebi_id in chebi_ids:
            rec = self._chebi_records.get(chebi_id, {})
            for url in rec.get("xrefs_urls", []):
                if isinstance(url, str) and url.strip():
                    clean = url.strip()
                    if not self._allow_chebi_xref_url_for_cas(url=clean, cas_numbers=cas_numbers):
                        continue
                    refs[clean] = refs.get(clean) or self._reference_entry(
                        url=clean,
                        generated_by="enrich_references.chebi_xrefs",
                        source_hint=chebi_id,
                        derived_from="chebi.xrefs_urls",
                    )
            term = self._chebi_term_for_id(chebi_id)
            chebi_url = f"https://www.ebi.ac.uk/chebi/searchId.do?chebiId={term}"
            refs[chebi_url] = refs.get(chebi_url) or self._reference_entry(
                url=chebi_url,
                generated_by="enrich_references.chebi_id_link",
                source_hint=chebi_id,
                derived_from="chebi.id",
            )

        for compound in pubchem_compounds:
            cid = compound.get("cid")
            if isinstance(cid, int):
                matched_cas = self._matched_cas_for_cid(cas_numbers=cas_numbers, cid=cid)
                cas_hint = f";CAS:{'|'.join(matched_cas)}" if matched_cas else ""
                pubchem_url = f"https://pubchem.ncbi.nlm.nih.gov/compound/{cid}"
                refs[pubchem_url] = refs.get(pubchem_url) or self._reference_entry(
                    url=pubchem_url,
                    generated_by="enrich_references.pubchem_compound",
                    source_hint=f"CID:{cid}{cas_hint}",
                    derived_from=(
                        f"pubchem.by_cas[{','.join(matched_cas)}]"
                        if matched_cas
                        else "pubchem.by_cas"
                    ),
                )
                id_map = self._pubchem_identifiers_by_cid.get(str(cid), {})
                for entries in id_map.values():
                    if not isinstance(entries, list):
                        continue
                    for item in entries:
                        if not isinstance(item, dict):
                            continue
                        url = item.get("url")
                        if isinstance(url, str) and url.strip():
                            clean = url.strip()
                            refs[clean] = refs.get(clean) or self._reference_entry(
                                url=clean,
                                generated_by="enrich_references.pubchem_identifier_url",
                                source_hint=f"CID:{cid}{cas_hint}",
                                derived_from=(
                                    f"pubchem.identifiers[{','.join(matched_cas)}]"
                                    if matched_cas
                                    else "pubchem.identifiers"
                                ),
                            )

        unique_cas = sorted({x.strip() for x in cas_numbers if isinstance(x, str) and x.strip()})
        if len(unique_cas) == 1:
            cas = unique_cas[0]
            commonchem_url = f"https://commonchemistry.cas.org/detail?cas_rn={cas}"
            refs[commonchem_url] = refs.get(commonchem_url) or self._reference_entry(
                url=commonchem_url,
                generated_by="enrich_references.consensus_cas_link",
                source_hint=cas,
                derived_from="cas_numbers",
            )

        return [refs[key] for key in sorted(refs)]

    def _matched_cas_for_cid(self, *, cas_numbers: list[str], cid: int) -> list[str]:
        matched: list[str] = []
        for cas in sorted({x.strip() for x in cas_numbers if isinstance(x, str) and x.strip()}):
            compounds = self._pubchem_by_cas.get(cas, [])
            if not isinstance(compounds, list):
                continue
            if any(isinstance(row, dict) and row.get("cid") == cid for row in compounds):
                matched.append(cas)
        return matched

    def _allow_chebi_xref_url_for_cas(self, *, url: str, cas_numbers: list[str]) -> bool:
        unique_cas = sorted({x for x in cas_numbers if isinstance(x, str) and x.strip()})
        if len(unique_cas) != 1:
            return True
        target_cas = unique_cas[0]
        try:
            parsed = urlparse(url)
        except Exception:
            return True
        host = (parsed.netloc or "").lower()
        path = parsed.path or ""
        query = parse_qs(parsed.query or "")
        if "commonchemistry.cas.org" in host:
            cas_vals = query.get("cas_rn", [])
            if cas_vals and any(str(v).strip() and str(v).strip() != target_cas for v in cas_vals):
                return False
            return True
        if "pubchem.ncbi.nlm.nih.gov" in host:
            # Only gate clear compound links; keep other URL shapes.
            marker = "/compound/"
            if marker in path:
                try:
                    cid_text = path.split(marker, 1)[1].split("/", 1)[0]
                    cid = int(cid_text)
                except Exception:
                    return True
                mapped = self._cas_by_pubchem_cid.get(cid, set())
                if mapped and target_cas not in mapped:
                    return False
            return True
        return True

    def _chebi_term_for_id(self, chebi_id: str) -> str:
        if "CHEBI:" in chebi_id:
            suffix = chebi_id.split("CHEBI:", 1)[1]
            return f"CHEBI:{suffix}"
        if "CHEBI_" in chebi_id:
            suffix = chebi_id.rsplit("CHEBI_", 1)[1]
            return f"CHEBI:{suffix}"
        return chebi_id

    def _prune_empty(self, value: Any) -> Any:
        if isinstance(value, dict):
            cleaned: dict[str, Any] = {}
            for key, item in value.items():
                pruned = self._prune_empty(item)
                if pruned in (None, "", [], {}):
                    continue
                cleaned[key] = pruned
            return cleaned
        if isinstance(value, list):
            cleaned_list = [self._prune_empty(item) for item in value]
            return [item for item in cleaned_list if item not in (None, "", [], {})]
        return value
