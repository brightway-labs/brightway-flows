"""Tag IUPAC-conformant names and set authoritative name/structure data via OPSIN.

All preferred and alternative labels for every eligible flow are collected and
batched into a single OPSIN subprocess call (one JVM startup for the whole run).
A flow qualifies when exactly one unique label (across pref + alt, compared
case-insensitively) can be parsed by OPSIN.  When that condition holds:

- ``properties[CHEMROF_IUPAC_NAME]`` is set to that label value (replacing any
  existing entry, e.g. one seeded from PubChem).
- SMILES and InChI are replaced with values derived from the OPSIN output via
  RDKit.

InChIKey, formula, and masses are intentionally left to
:class:`RDKitAuthoritativeTransformer`, which runs next and derives them from
the now-authoritative InChI.

Any mismatch between the OPSIN InChIKey and pre-existing InChIKey values is
logged as a warning but does not block the update.

Flows with an ``origin_qualifier`` are skipped (consistent with the rest of the
RDKit pipeline).
"""

from __future__ import annotations

import copy
import warnings
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import structlog

from brightway_flows.domain.flow import Flow
from brightway_flows.chem import (
    StructureValues,
    structure_values_from_smiles,
)
from brightway_flows.domain.common import Provenance
from brightway_flows.domain.composition import contradicts_name
from brightway_flows.filesystem import OPSIN_LOG_FILEPATH
from brightway_flows.domain.labels import (
    canonical_label_value,
    coerce_alt_labels,
    coerce_pref_labels,
)
from brightway_flows.pipeline import Change, Transformer
from brightway_flows.domain.vocabulary import (
    CHEMROF_INCHI2D_KEY_STRING,
    CHEMROF_INCHI2D_STRING,
    CHEMROF_IUPAC_NAME,
    CHEMROF_SMILES_STRING,
)
from brightway_flows.transformers.rdkit_enrichment import (
    _get_values,
    _set_definitive,
    _should_skip,
)

logger = structlog.get_logger(__name__)

# py2opsin prefixes each line of the OPSIN subprocess's stderr with this.
_OPSIN_WARNING_LINE_PREFIX = " > "

_opsin_log_path: Path | None = None


def configure_opsin_logging(log_path: Path) -> None:
    """Set the file OPSIN parse errors are written to, clearing it first.

    Until this is called, they are discarded rather than printed.
    """
    global _opsin_log_path
    _opsin_log_path = log_path
    log_path.write_text("", encoding="utf-8")


def _log_opsin_warnings(caught: list[warnings.WarningMessage]) -> None:
    """Write captured OPSIN parse errors to the log file, re-raising the rest.

    py2opsin re-emits the whole of the OPSIN subprocess's stderr as a single
    ``RuntimeWarning`` whose body is one indented line per unparseable name —
    tens of thousands of lines on a full run.  Anything else that warned inside
    the block is not ours to swallow, so it is re-issued.
    """
    lines: list[str] = []
    for entry in caught:
        text = str(entry.message)
        if entry.category is not RuntimeWarning or "OPSIN raised the following" not in text:
            warnings.warn_explicit(
                entry.message, entry.category, entry.filename, entry.lineno
            )
            continue
        # Drop the "OPSIN raised the following error(s)..." header line.
        for line in text.splitlines()[1:]:
            line = line.removeprefix(_OPSIN_WARNING_LINE_PREFIX).strip()
            if line:
                lines.append(line)

    if not lines:
        return
    logger.info(
        "opsin_parse_errors_logged",
        count=len(lines),
        path=str(_opsin_log_path) if _opsin_log_path else None,
    )
    if _opsin_log_path is None:
        return
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    with open(_opsin_log_path, "a", encoding="utf-8") as fh:
        for line in lines:
            fh.write(f"{ts}\t{line}\n")


def _opsin_batch(names: list[str]) -> list[str | None]:
    """Return SMILES for each name; None where OPSIN cannot parse.

    Names OPSIN cannot parse are expected and handled by the caller, so its
    complaints go to the log file rather than the terminal.
    """
    from py2opsin import py2opsin  # deferred so the package is optional at import time

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        results = py2opsin(chemical_name=names, output_format="SMILES")
    _log_opsin_warnings(caught)
    if isinstance(results, str):
        results = [results]
    return [r.strip() or None for r in results]


def _distinct_labels(label_values: list[str]) -> list[str]:
    """*label_values*, preferred first, with case variants of one name collapsed.

    `Trichloroethene`, `trichloroethene` and `TRICHLOROETHENE` are one name
    written three ways and have always counted once here.  Kept as its own
    function because what is counted below is now structures, and the two
    dedupes answer different questions: this one is about spelling, that one is
    about substance.
    """
    seen: set[str] = set()
    out: list[str] = []
    for value in label_values:
        key = canonical_label_value(value)
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(value)
    return out


class _StructureCache:
    """The structure each readable name resolves to, derived once per SMILES.

    OPSIN returns a SMILES per name and RDKit turns that into the InChI, the
    InChIKey and the formula.  Many names share a SMILES -- a substance's
    synonyms usually all do, which is the whole point of the rule below -- so
    the derivation is keyed on the SMILES rather than on the name.
    """

    def __init__(self, smiles_by_name: dict[str, str]) -> None:
        self._smiles_by_name = smiles_by_name
        self._by_smiles: dict[str, StructureValues | None] = {}

    def for_name(self, name: str) -> StructureValues | None:
        smiles = self._smiles_by_name.get(name)
        if smiles is None:
            return None
        if smiles not in self._by_smiles:
            self._by_smiles[smiles] = structure_values_from_smiles(smiles)
        return self._by_smiles[smiles]


def _agreed_structure(
    readable: list[tuple[str, StructureValues]],
) -> tuple[str, StructureValues] | None:
    """The structure a substance's readable names agree on, and the name to cite.

    A flow is updated only when its names agree about what the substance is.
    That was the intent of the rule this replaces; what that rule counted was
    the *names*, so `Sulfur Dichloride` and `Dichlorosulfane` -- one molecule,
    two spellings -- read as two answers and the flow was skipped.  Since
    `chebi_altlabels` and `consensus_match` fill in synonyms for everything, a
    substance with exactly one readable name barely exists: 378 flows of the
    whole list on the build of 5f77d7b4de1f, and none at all of the 261 empty
    substances a merge created (#71).

    Agreement is asked of the InChIKey, so the question is whether the names
    mean one molecule rather than whether they are one string.

    Unanimity is not required, because one bad spelling among five good ones is
    not a substance in doubt.  `Trioctyltin`'s four systematic names all say one
    molecule and its bare name says another, since a tin with three octyls and
    nothing said about its fourth bond is not a complete molecule.  A group
    wins when it is **more than half** of the readable names and **at least
    twice** the next largest, which is the difference between an outlier and a
    dispute:

      - `Trioctyltin`, 4 against 1 -- taken;
      - `Disodium Phosphonate`, 3 against 2 -- refused.  What those spellings
        disagree about is whether the substance is the phosphonate or the
        hydrogen phosphite, two tautomers with different registry numbers, and
        counting synonyms is not evidence about which the vendor meant;
      - `Zoxamide`, 2 against 2 -- refused, the case the original guard exists
        for;
      - `Copper Chloride Oxide, Hydrate`, 2 against 1 against 1 against 1
        against 1 -- refused.  Two is the largest group and is two names out of
        six; a substance whose names scatter over five structures is one nobody
        has a structure for.

    The name returned is the first of the winning group in label order, which is
    preferred label before alternative: the substance's own name is a better
    thing to publish as its IUPAC name than the fourth synonym ChEBI supplied.
    It is never the outvoted spelling.
    """
    keyed = [(name, values) for name, values in readable if values.inchikey]
    if not keyed:
        return None
    counts = Counter(values.inchikey for _name, values in keyed)
    (winner, top), *rest = counts.most_common()
    runner_up = rest[0][1] if rest else 0
    if not (top * 2 > len(keyed) and top >= 2 * runner_up):
        return None
    return next((name, values) for name, values in keyed if values.inchikey == winner)


class OPSINTransformer(Transformer):
    """Set authoritative IUPAC name, SMILES, and InChI via OPSIN.

    Collects all preferred and alternative labels from all eligible flows and
    calls OPSIN once in batch.  A flow is updated when the names OPSIN could
    read agree about which molecule the substance is; see `_agreed_structure`
    for what agreement means and which disagreements are refused.
    """

    name = "opsin_iupac"
    answers_per_flow = True

    def setup(self) -> None:
        configure_opsin_logging(OPSIN_LOG_FILEPATH)
        try:
            result = _opsin_batch(["methane"])
        except FileNotFoundError:
            raise RuntimeError(
                "Java not found on PATH. Install a JDK/JRE and ensure the 'java' "
                "command is available to enable OPSIN name-to-structure conversion."
            )
        except Exception as exc:
            raise RuntimeError(f"OPSIN canary call failed: {exc}") from exc
        if not result or result[0] is None:
            raise RuntimeError(
                "OPSIN returned no SMILES for 'methane'. Check your Java installation."
            )

    def transform(self, flows: list[Flow]) -> list[Change]:
        # Collect all unique label values across all eligible flows in one pass.
        eligible: list[tuple[dict, list[str], str]] = []
        all_label_values: set[str] = set()

        for flow in flows:
            properties = flow.properties or {}
            if _should_skip(flow, properties):
                continue
            pref = [l.value for l in coerce_pref_labels(flow.prefLabel)]
            alt = [l.value for l in coerce_alt_labels(flow.altLabel)]
            label_values = list(dict.fromkeys(pref + alt))  # preserve order, dedupe
            if not label_values:
                continue
            eligible.append((flow, label_values, pref[0] if pref else ""))
            all_label_values.update(label_values)

        if not all_label_values:
            return []

        # Single OPSIN batch call for all unique label values.
        unique_names = sorted(all_label_values)
        smiles_by_name: dict[str, str] = {
            name: smiles
            for name, smiles in zip(unique_names, _opsin_batch(unique_names))
            if smiles is not None
        }

        # One structure per distinct SMILES, shared across every flow below.  A
        # name is read once by OPSIN and its structure derived once by RDKit,
        # however many flows and synonyms arrive at it.
        structures = _StructureCache(smiles_by_name)

        changes: list[Change] = []
        # Why the flows that got nothing got nothing.  A number to watch between
        # runs rather than a queue: `refused_disagreement` is the substances
        # whose own names contradict each other about what they are, and it
        # going up is a signal that something upstream is attaching a synonym
        # belonging to a different substance.
        no_readable_name = 0
        refused_disagreement = 0
        refused_composition = 0
        for flow, label_values, pref_label in eligible:
            # Deduplicate by canonical (case-insensitive) form to avoid counting
            # trivial variants of the same name as two IUPAC-conformant labels.
            readable = [
                (value, structure)
                for value in _distinct_labels(label_values)
                if (structure := structures.for_name(value)) is not None
            ]
            if not readable:
                no_readable_name += 1
                continue
            # Drop the readings that miscount the substance's own name, before
            # the vote rather than after it (#129).  A name that omits the
            # stoichiometry -- `antimonous sulfide`, `bismuth sulfide`,
            # `bismuth(III) oxide` -- is read as the one-to-one compound, and
            # OPSIN returns for it the *same* structure it returns for
            # `antimony monosulfide`.  Nothing downstream can catch that: the
            # formula and the SMILES agree with each other perfectly and are
            # both about a different substance.
            #
            # Dropped rather than disqualifying the whole flow, so that a
            # correct reading standing beside a miscounting one still answers.
            # The preferred label is the authority rather than the whole
            # synonym set, because the synonyms are what went wrong: they
            # arrive from registry lookups, and OPSIN read one of them.
            counting = [
                (value, structure)
                for value, structure in readable
                if not contradicts_name(structure.formula, pref_label)
            ]
            if len(counting) != len(readable):
                refused_composition += 1
            if not counting:
                continue
            answer = _agreed_structure(counting)
            if answer is None:
                refused_disagreement += 1
                continue
            name, values = answer
            change = self._make_change(flow, name, values)
            if change is not None:
                changes.append(change)

        logger.info(
            "opsin_iupac_structures",
            eligible_flow_count=len(eligible),
            distinct_names=len(unique_names),
            names_opsin_read=len(smiles_by_name),
            changed_flow_count=len(changes),
            flows_with_no_readable_name=no_readable_name,
            flows_whose_names_disagree=refused_disagreement,
            flows_whose_structure_miscounts=refused_composition,
        )
        return changes

    def _make_change(
        self, flow: dict[str, Any], name: str, values: StructureValues
    ) -> Change | None:
        uuid = flow.uuid
        properties = flow.properties or {}

        key = values.inchikey

        existing_keys = _get_values(properties, CHEMROF_INCHI2D_KEY_STRING)
        if existing_keys and key and not all(k == key for k in existing_keys):
            logger.warning(
                "opsin_iupac_inchikey_mismatch",
                uuid=uuid,
                name=name,
                opsin_inchikey=key,
                existing_inchikeys=existing_keys,
            )

        prov = Provenance(
            was_generated_by="opsin_iupac",
            was_attributed_to="brightway-flows",
            had_primary_source=[name],
        ).to_dict()

        new_properties = copy.deepcopy(properties)
        _set_definitive(new_properties, CHEMROF_IUPAC_NAME, "IUPAC name", name, None, prov)
        _set_definitive(new_properties, CHEMROF_SMILES_STRING, "SMILES", values.smiles, None, prov)
        _set_definitive(new_properties, CHEMROF_INCHI2D_STRING, "InChI", values.inchi, None, prov)

        return Change(
            uuid,
            "properties",
            new_properties,
            comment=f"opsin_iupac: set authoritative IUPAC name, SMILES, InChI from '{name}'",
        )
