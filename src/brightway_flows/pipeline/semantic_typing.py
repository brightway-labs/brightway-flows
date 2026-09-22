"""What kind of thing is this flow object?

98.6% of flow objects carried no ``@type``, and the two classes that were
assigned came from a regex over the preferred label: ``MonoatomicIon`` needed
``_extract_ion_base_and_charge`` to parse the name *and* the base element object
to already exist under the title-cased name.  So ``Chloride``, ``Sodium ion``
and ``Tin(2+)`` -- monoatomic, charged, unmistakable -- went untyped, while the
class was assigned to five objects carrying no charge at all.

This module types from the chemistry instead: formula, charge, structure,
registry identifiers, and the contexts the substance is emitted to.  Every class
it can assign is verified present and *concrete* in the ChemROF LinkML source
(``chemkg/chemrof``, ``src/chemrof/schema/chemrof.yaml``).

Only the **most specific** class is emitted.  ``MolecularCation`` implies
``PolyatomicIon`` implies ``Molecule`` in the ontology and a reasoner derives the
chain; writing all three is noise that can drift out of step with ChemROF.

The rules are ordered and the first match wins.  Every object gets an outcome --
a class, or a recorded reason for having none -- so "untyped" is a decision with
a name rather than a silence, and the run reports the tally of both.

What this deliberately does not do
----------------------------------

**Half-life is published against its declared range.**  ChemROF gives
``half_life`` the range ``NumberOfYears``, which the schema defines as
``xsd:int``.  Americium-241's half-life is 432.6 years and Krypton-85's is 10.7;
no integer is either value.  The three options were a wrong number, no number,
or a float that the range does not permit -- and a float is the only one that
tells the truth, so that is what is published.  Reported upstream.

**What is not chemistry, and the flow layer itself.**  246 flow objects occur
only in contexts that count something other than a substance -- land use
(``Arable, Irrigated``), money (``Labour Cost``), an inventory indicator
(``Exported Energy - Heat``) -- and every elementary flow is an occurrence
rather than a substance.  None is a chemical entity and ChemROF has no class for
any of them, so all stay untyped with a reason naming which it is.  The
alternative is minting a class IRI, which is a publishing commitment rather than
a code change.

The context that decides this is read as ``(dimension, media)`` and not as the
dimension alone, because one medium of an otherwise chemical dimension counts
something other than a substance: ``Environmental / Other``.  BAFU files traffic
noise there, under a compartment it calls ``non material emissions``, measured
per person-kilometre and per tonne-kilometre (#70).  Noise is a real burden and
methods characterise it, but it has no formula, no mass and no registry number,
because it is not matter -- and while the rule asked only about dimensions, the
six noise objects fell through to ``no_structure_and_no_registry_identifier``,
"we could not tell what this is", which is as untrue of them as it was of
``Labour Cost``.

**Aggregate measurements are the exception, and they are curated.**
``Chemical Oxygen Demand``, ``Benzene (as BTEX)`` and ``Particles (PM2.5)`` are
quantities defined by the method that measures them.  They get a class --
``brightway:AggregateMeasurement``, the one this project mints -- because
leaving them untyped publishes nothing a consumer can filter on, and being
excluded from a query for substances is the whole point of saying what they
are.  Which names are such a quantity is read from
``data/aggregate-measurements.json`` and never from a pattern; see
:mod:`brightway_flows.domain.aggregate_measurements` for why.
"""

from __future__ import annotations

import functools
import re
from collections import Counter
from dataclasses import dataclass
from typing import Any

import structlog

from brightway_flows.chem import graph_only_smiles, mol_from_smiles
from brightway_flows.domain.aggregate_measurements import (
    AggregateMeasurement,
    measurement_for_name,
)
from brightway_flows.domain.common import Provenance
from brightway_flows.domain.structure_corrections import correction_for
from brightway_flows.domain.context import (
    Dimension,
    counts_a_non_material_intervention,
)
from brightway_flows.domain.flow_object import FlowObject
from brightway_flows.domain.labels import (
    canonical_label_value,
    coerce_alt_labels,
    flow_label_value,
)
from brightway_flows.domain.materials import (
    concept_by_flow_object,
    material_concepts,
)
from brightway_flows.domain.nuclides import half_life_years
from brightway_flows.domain.vocabulary import (
    CHEMINF_CAS_REGISTRY_NUMBER,
    MintedNamespace,
    Namespace,
    SKOS_BROADER_IRI,
    SKOS_BROAD_MATCH_CURIE,
    SKOS_BROAD_MATCH_IRI,
    SKOS_CLOSE_MATCH_CURIE,
    SKOS_CLOSE_MATCH_IRI,
    SKOS_EXACT_MATCH_CURIE,
    SKOS_EXACT_MATCH_IRI,
    SKOS_IN_SCHEME_IRI,
    SKOS_RELATED_IRI,
    SKOS_RELATED_MATCH_CURIE,
    SKOS_RELATED_MATCH_IRI,
    CHEMINF_EC_NUMBER,
    CHEMROF_DECAY_MODE,
    CHEMROF_ELEMENTAL_CHARGE,
    CHEMROF_CHEMICAL_ELEMENT,
    CHEMROF_HALF_LIFE,
    CHEMROF_HAS_ELEMENT,
    CHEMROF_INCHI2D_KEY_STRING,
    CHEMROF_INCHI2D_STRING,
    CHEMROF_ISOMERIC_SMILES_STRING,
    CHEMROF_IUPAC_NAME,
    CHEMROF_MOLECULAR_FORMULA,
    CHEMROF_MOLECULAR_MASS,
    CHEMROF_MONOISOTOPIC_MASS,
    CHEMROF_NUCLEON_NUMBER,
    CHEMROF_SMILES_STRING,
    CHEMROF_SYMBOL,
    BRIGHTWAY_EXPRESSED_AS,
    BRIGHTWAY_SUMS_OVER,
    IRIS,
    QUDT_HAS_UNIT,
    RDFS_LABEL_CURIE,
    UNIT_IRI_NUM,
    UNIT_IRI_YEAR,
    Term,
    flow_object_iri,
)
from brightway_flows.domain.land_flow_classes import published_land_classes
from brightway_flows.domain.land_use import LandUse
from brightway_flows.domain.land_use_anchors import anchors_for
from brightway_flows.flow_layers.land_hierarchy import land_object_id
from brightway_flows.pipeline.layer_writes import LayerWriteLog
from brightway_flows.qualifiers import (
    ALPHA_EMITTERS,
    is_delayed_emission_correction,
)

logger = structlog.get_logger(__name__)

#: Recorded as `prov:wasGeneratedBy` on everything this module writes.
ACTIVITY = "semantic_typing.classify"

#: The pass name on a flow-layer withdrawal in the changelog, spelled as the
#: function rather than the module: `assign_semantic_types` writes to flow
#: objects from here too, and those writes are not this pass.
_WITHDRAW_PASS_NAME = "withdraw_single_substance_properties"

_ATTRIBUTED_TO = "brightway-flows"

#: An element symbol in Hill notation: a capital, optionally a lower-case.
_ELEMENT_SYMBOL = re.compile(r"[A-Z][a-z]?")

#: Exactly one element symbol and nothing else -- `Ni`, `Cl`.  `O3` and `Cl2`
#: are several atoms of one element and do not match.
_SINGLE_ATOM_FORMULA = re.compile(r"[A-Z][a-z]?")

#: A charged atom in SMILES bracket notation: `[Na+]`, `[O-]`, `[Fe+3]`.
_SMILES_CATION = re.compile(r"\[[^\]]*\+\d*\]")
_SMILES_ANION = re.compile(r"\[[^\]]*-\d*\]")

#: Labels naming a *class* of substance rather than a substance.  Deliberately
#: narrow: a false positive says a real substance is a grouping class, which is
#: worse than leaving it untyped.
#:
#: `(unspecified)` is the parenthesised form of the suffix beside it, and a
#: singular `Compound` the singular of the plural: `Hydrocarbons (unspecified)`
#: and `Volatile Organic Compound` say exactly what `Aldehydes, Unspecified`
#: says.  These hold whatever else is known about the object, because a label
#: that says "unspecified" is settling the question itself.
_GROUPING_LABEL = re.compile(
    r",\s*unspecified\s*$"
    r"|\(\s*unspecified\b[^)]*\)"
    r"|\bcompounds?\s*$"
    r"|\bunspecified\b[^,]*\bcompounds\b"
    r"|^radioactive species\b",
    re.IGNORECASE,
)

#: The same judgement from a weaker signal, and therefore only for an object
#: that nothing else identifies.
#:
#: A plural family noun is a grouping class in `Hydrocarbons, Aromatic` and part
#: of a substance name in `Fatty Acids, Tallow, Zinc Salts`.  Matching it
#: unconditionally takes 39 EC-registered UVCBs away from
#: `ImpreciseChemicalMixture` and calls them classes -- measured, not feared.
#: What separates the two is the registry identifier: an authority registered a
#: substance, however variable its composition, and nobody registers "aromatic
#: hydrocarbons".  So this applies only where rule 10 would find nothing, which
#: is what makes the wider net safe.
_UNREGISTERED_GROUPING_LABEL = re.compile(
    r"^hydrocarbons\b"
    r"|\bsalts\b"
    r"|\boxides\s*$"
    r"|^solids,"
    r"|^oils,",
    re.IGNORECASE,
)

#: Groups of *elements* rather than of molecules -- "Actinides, radioactive,
#: unspecified" groups atoms, so `MoleculeGroupingClass` would be a category
#: error one level down from the one this module exists to fix.  `Radioactive
#: Species, Alpha Emitters` groups nuclides, which is the same thing rule 0
#: gives the alpha-emitter aggregates.
#:
#: `radioactive` is here on its own, and it is what makes the seven radiological
#: groupings agree.  Six were `AtomGroupingClass` and `Aerosols, Radioactive,
#: Unspecified` was `MoleculeGroupingClass`, which says its members are
#: molecules: a radioactive aerosol is particles carrying nuclides, grouped by
#: what they emit rather than by what they are made of, and it is the same kind
#: of thing as the other six.  Anything in either list that is *radioactive* and
#: has already been judged a grouping class by rule 8 is a grouping over
#: nuclides.  The four radioactive-waste labels are not counter-examples --
#: `High-level Radioactive Waste Disposed` and the repository volumes are
#: inventory indicators, and rule 7 answers for them several rules earlier.
_ELEMENT_GROUP_LABEL = re.compile(
    r"\b(actinides|lanthanides|noble gases|halogens|alkali metals"
    r"|alkaline earth metals|rare earth (metals|elements)|heavy metals"
    r"|radioactive)\b",
    re.IGNORECASE,
)

#: The context dimensions where the thing being counted is not a substance.
#:
#: `Land Use` was the only one named.  The two others the list actually uses
#: fell through to `no_structure_and_no_registry_identifier` -- "the identity
#: is too thin to classify", which is untrue of `Labour Cost` and `Exported
#: Energy - Heat`.  Their identity is perfectly clear; they are not
#: chemistry.  `Social` and `Impact Assessment Score` have no flows today and
#: are here so that gaining one is not a silent reclassification.  Taken from
#: :class:`~brightway_flows.domain.context.Dimension` so a dimension added
#: there has to be placed on one side of this line or the other.
#:
#: `Environmental` and `Resource` are deliberately absent: those are where a
#: substance is what is being counted, and `Resource` has rule 9.  One medium of
#: `Environmental` is the exception -- see
#: `context.counts_a_non_material_intervention`.
_NON_CHEMICAL_DIMENSIONS: frozenset[str] = frozenset({
    Dimension.LAND_USE,
    Dimension.ECONOMIC,
    Dimension.SOCIAL,
    Dimension.INVENTORY,
    Dimension.IMPACT,
})

#: One context an object occurs in, reduced to the two fields that decide
#: whether a substance is the thing being counted.  `media` is `""` for a
#: dimension that has none, which is every dimension outside `Environmental`
#: and `Resource`.
ContextSlot = tuple[str, str]

#: The reason a non-material context earns, kept apart from the dimension slugs
#: because it names what the flow *is* rather than which dimension excluded it.
#:
#: A slot rather than a whole dimension, because the dimension is right and only
#: the medium is outside chemistry -- see
#: `context.counts_a_non_material_intervention`, which both this module and the
#: flow layering ask.  Moving these flows to `Social` would have typed them with
#: no code at all -- it is already above -- at the cost of filing an
#: environmental burden under the heading LCA keeps for labour and human rights,
#: where a consumer filtering for environmental effects would never find it.
_NON_MATERIAL_REASON = "non_material_intervention_not_a_chemical_entity"


def _counts_something_other_than_a_substance(slot: ContextSlot) -> bool:
    """Whether the thing counted in *slot* is anything but a substance."""
    dimension, media = slot
    return dimension in _NON_CHEMICAL_DIMENSIONS or (
        counts_a_non_material_intervention(dimension, media)
    )


def _slot_reason(slot: ContextSlot) -> str:
    """Name what puts one context outside chemistry."""
    if counts_a_non_material_intervention(*slot):
        return _NON_MATERIAL_REASON
    slug = str(slot[0]).lower().replace(" ", "_")
    return f"{slug}_not_a_chemical_entity"


def _not_a_chemical_entity_reason(slots: frozenset[ContextSlot]) -> str:
    """Name what put *slots* outside chemistry.

    One answer names itself -- `land_use_not_a_chemical_entity`, unchanged from
    when land use was the only case.  A flow whose contexts give two different
    answers has no one of them to blame, so the reason drops the qualifier
    rather than picking arbitrarily.
    """
    reasons = {_slot_reason(slot) for slot in slots}
    if len(reasons) != 1:
        return "not_a_chemical_entity"
    return reasons.pop()


@dataclass(frozen=True)
class Classification:
    """One typing decision, and what drove it."""

    types: tuple[str, ...]
    rule: str
    #: Set only when no class could be assigned; names what stopped it.
    reason: str = ""


# ── reading a flow object ────────────────────────────────────────────────────


def _values(properties: Any, iri: str) -> list[Any]:
    entry = properties.get(iri) if isinstance(properties, dict) else None
    if not isinstance(entry, dict):
        return []
    raw = entry.get("@value")
    values = raw if isinstance(raw, list) else [raw]
    return [value for value in values if value not in ("", None)]


def _first_str(properties: Any, iri: str) -> str:
    for value in _values(properties, iri):
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


#: A trailing charge on a formula: `BO3-3`, `Ti+4`, `CNS-`.
_FORMULA_CHARGE = re.compile(r"([+-])(\d*)$")


def _charge_from_formulas(properties: Any) -> int | None:
    """The net charge every stated formula agrees on, or ``None``.

    The fallback for :func:`_charge`, which reads `elemental_charge` -- a
    property most objects do not carry.  Seven substances stated a formula that
    plainly carries a charge, `BO3-3` and `Ti+4` among them, and were published
    as neutral molecules because nothing looked at it (#326).

    **Agreement across every stated formula is required, and that is the guard
    rather than a detail.**  `Phosphonic Acid, Dibutyl Ester` states
    `C8H18O3P+` *and* `C8H18O3P-`: two readings of one substance, opposite in
    sign, and neither is evidence of a charge.  Taking the first would publish
    whichever the enrichment happened to write down first.

    An unsigned formula among signed ones is a disagreement too -- a neutral
    reading against a charged one -- so it also yields ``None``.
    """
    charges: set[int] = set()
    for value in _values(properties, CHEMROF_MOLECULAR_FORMULA):
        if not isinstance(value, str) or not value.strip():
            continue
        match = _FORMULA_CHARGE.search(value.strip())
        if match is None:
            return None
        magnitude = int(match.group(2) or "1")
        charges.add(magnitude if match.group(1) == "+" else -magnitude)
    if len(charges) != 1:
        return None
    charge = charges.pop()
    return charge or None


def _charge(properties: Any) -> int | None:
    """The whole-entity charge, or None when absent or unusable.

    Reads ``elemental_charge``: ``formal_charge`` is an ``AtomOccurrence``
    property in ChemROF, not an entity's net charge (#9).
    """
    for value in _values(properties, CHEMROF_ELEMENTAL_CHARGE):
        if isinstance(value, bool):
            continue
        if isinstance(value, int):
            return value
        try:
            return int(str(value).strip())
        except (TypeError, ValueError):
            continue
    return None


def _strip_charge(formula: str) -> str:
    """Drop a trailing charge from a formula: `Pb+2` -> `Pb`, `Cr2O7-2` -> `Cr2O7`.

    PubChem and ChEBI both write the charge into the formula of an ion, so
    `Lead(2+)` arrives as `Pb+2` and a plain `[A-Z][a-z]?` test says it is not
    one atom -- which sent lead and silver down the polyatomic branch.
    """
    return re.sub(r"(?:[+-]\d*|\d*[+-])$", "", (formula or "").strip())


def _is_single_atom(formula: str) -> bool:
    return bool(re.fullmatch(_SINGLE_ATOM_FORMULA, _strip_charge(formula)))


def _distinct_elements(formula: str) -> int:
    return len(set(_ELEMENT_SYMBOL.findall(_strip_charge(formula))))


def _is_zwitterion(smiles: str) -> bool:
    """True when the molecule has a free cationic *and* a free anionic centre.

    A nitro group is written `[N+](=O)[O-]` -- a charge-separated *resonance
    form*, not a zwitterion -- and nitroaromatics are everywhere in these lists,
    so a plain "contains both signs" test called ten nitro compounds zwitterions
    in a 400-flow run.

    "The charges are not bonded to each other" is not enough either: 2,5-
    dinitrotoluene has two nitro groups, and the nitrogen of one is not bonded
    to the oxygen of the other.  What distinguishes a zwitterion is that a
    charge stands *alone* -- betaine's ammonium has no anionic neighbour and its
    carboxylate has no cationic one, while in a nitro group every charge is
    paired off against the one next to it.  So: a free centre of each sign.

    Falls back to False when the structure will not parse.  Claiming nothing is
    better than claiming a class from a structure we could not read.
    """
    mol = mol_from_smiles(smiles)
    if mol is None:
        return False
    free_cation = False
    free_anion = False
    for atom in mol.GetAtoms():
        charge = atom.GetFormalCharge()
        if charge == 0:
            continue
        neighbour_charges = [n.GetFormalCharge() for n in atom.GetNeighbors()]
        if charge > 0 and not any(c < 0 for c in neighbour_charges):
            free_cation = True
        elif charge < 0 and not any(c > 0 for c in neighbour_charges):
            free_anion = True
    return free_cation and free_anion


def _existing_types(obj: FlowObject) -> list[str]:
    raw = obj.types
    if isinstance(raw, str):
        return [raw.strip()] if raw.strip() else []
    if isinstance(raw, list):
        return [str(x).strip() for x in raw if isinstance(x, str) and x.strip()]
    return []


def _has_registry_identifier(obj: FlowObject) -> bool:
    classifications = obj.classifications
    if not isinstance(classifications, dict):
        return False
    return any(
        classifications.get(iri)
        for iri in (CHEMINF_CAS_REGISTRY_NUMBER, CHEMINF_EC_NUMBER)
    )


def _registry_numbers(obj: FlowObject) -> list[str]:
    """The CAS numbers *obj* publishes, for looking a curated entry up by."""
    classifications = obj.classifications
    if not isinstance(classifications, dict):
        return []
    entry = classifications.get(CHEMINF_CAS_REGISTRY_NUMBER)
    if not isinstance(entry, dict):
        return []
    raw = entry.get("@value")
    values = raw if isinstance(raw, list) else [raw]
    return [str(v).strip() for v in values if str(v or "").strip()]


def _measurement_for(
    record: Any, label: str = ""
) -> tuple[AggregateMeasurement, str] | None:
    """The curated quantity *record* names, and the label that named it.

    The preferred label first, then the alternative labels.  Both, because the
    two answer different questions: the preferred label is what this project
    decided to call the row and an alternative label is what a source called
    it, and a curator writing `aggregate-measurements.json` is working from the
    source lists.  `Acid (as H+)` is the case -- its preferred label is EF's
    name and its alternative labels are the hydron synonyms a CAS lookup
    attached, so a future rename of the row must not be able to hide it.

    Which label matched is returned rather than discarded, and recorded on the
    object.  A match through an alternative label is worth a second look: it
    means the row is published under a name the file does not list.
    """
    text = label or flow_label_value(record)
    measurement = measurement_for_name(text)
    if measurement is not None:
        return measurement, text
    for alt in coerce_alt_labels(getattr(record, "altLabel", None)):
        measurement = measurement_for_name(alt.value)
        if measurement is not None:
            return measurement, alt.value
    return None


# ── classification ───────────────────────────────────────────────────────────


def _ion_types(charge: int | None, *, monoatomic: bool) -> tuple[str, ...]:
    """The most specific ion class for *charge*.

    A charge whose sign is unknown falls back to the parent class, which is all
    that can honestly be said about it.
    """
    if charge is None or charge == 0:
        return (
            (IRIS[Term.MONOATOMIC_ION],) if monoatomic
            else (IRIS[Term.POLYATOMIC_ION],)
        )
    if monoatomic:
        return (IRIS[Term.ATOM_CATION],) if charge > 0 else (IRIS[Term.ATOM_ANION],)
    return (
        (IRIS[Term.MOLECULAR_CATION],) if charge > 0
        else (IRIS[Term.MOLECULAR_ANION],)
    )


def classify(
    obj: FlowObject,
    *,
    label: str = "",
    context_slots: frozenset[ContextSlot] = frozenset(),
) -> Classification:
    """Decide what *obj* is.  Ordered rules; the first match wins.

    *context_slots* are the `(dimension, media)` pairs of every context the
    object occurs in.  The pair rather than the dimension, because
    `Environmental / Other` counts something other than a substance while the
    rest of `Environmental` counts substances -- see `_NON_MATERIAL_SLOT`.
    """
    properties = obj.properties if isinstance(obj.properties, dict) else {}
    formula = _first_str(properties, CHEMROF_MOLECULAR_FORMULA)
    smiles = _first_str(properties, CHEMROF_SMILES_STRING)
    charge = _charge(properties)
    if charge is None:
        # An ion is an atom or molecule carrying a charge, and a formula that
        # states one is saying so.  `elemental_charge` is the preferred
        # evidence and most objects do not carry it, which is how `BO3-3` came
        # to be published as a neutral molecule (#326).
        charge = _charge_from_formulas(properties)
    charged = charge is not None and charge != 0

    # 0. A radiological aggregate: the alpha-emitting isotopes of one element,
    #    reported together as activity.  It is not one substance, so no rule
    #    below can place it -- and it arrives carrying the element's structural
    #    properties, which would send it down the molecule branches and have it
    #    published as the element itself (#238).  `AtomGroupingClass` is what
    #    rule 8 already gives "Actinides, radioactive, unspecified": a named
    #    class over atoms rather than one of them.  First, because the
    #    properties this outranks are exactly the ones that are wrong here, and
    #    `_withdraw_single_substance_properties` takes them off afterwards.
    if obj.origin_qualifier == ALPHA_EMITTERS:
        return Classification(
            (IRIS[Term.ATOM_GROUPING_CLASS],), "alpha_emitter_aggregate"
        )

    # 0b. A delayed-emission correction: EF's accounting device for an emission
    #     that happens later, measured in kg*a -- a mass held for a time, which
    #     is not a substance and not a quantity of one.  Here for the same
    #     reason as rule 0 and one rule further: it arrives carrying the base
    #     substance's structure through the CAS it shares with it, so every
    #     molecule branch below would place it, and place it wrongly (#43).
    #
    #     Untyped, unlike rule 0.  `AtomGroupingClass` fits a set of isotopes;
    #     nothing in ChemROF fits an accounting flow, and this module mints no
    #     IRI for what it cannot name -- so the outcome is a named reason, as
    #     it is for land use and for an aggregate measurement.
    if is_delayed_emission_correction(obj.origin_qualifier):
        return Classification(
            (), "", reason="delayed_emission_correction_not_a_substance"
        )

    # 0c. A quantity someone curated as not being a substance: chemical oxygen
    #     demand, BTEX reported as benzene, particles below a size.  Here for
    #     the third time for the same reason -- these arrive holding a
    #     substance's identity and every rule below would honour it.  `Acid (as
    #     H+)` reached rule 6 through the hydron's CAS and was published as a
    #     `NeutralMolecule` with that ion's structure, formula and two masses;
    #     `COD, Chemical Oxygen Demand` reached rule 10 through a number that
    #     names no compound and was published as a mixture (#68).
    #
    #     Unlike 0 and 0b this assigns a class, and the class is ours.  ChemROF
    #     has nothing for a quantity defined by its own procedure -- the nearest
    #     term, `ImpreciseChemicalMixture`, is a portion of matter -- and
    #     leaving it untyped is what let two of these be typed by accident.
    if _measurement_for(obj, label) is not None:
        return Classification(
            (IRIS[Term.AGGREGATE_MEASUREMENT],), "aggregate_measurement"
        )

    # 0d. A class a curator states, in `structure-corrections.json`, for a
    #     substance whose structure this pipeline cannot work out.  Antimony
    #     trisulfide is the one: every route to its structure is blocked or
    #     wrong, so it reached rule 10 through a registry number with no
    #     structure on file and was published `ImpreciseChemicalMixture` -- a
    #     substance of variable composition, which Sb2S3 is not (#129).
    #
    #     Here rather than earlier because the three rules above decide a row is
    #     not a substance at all, and a curated structure must never be able to
    #     turn an aggregate measurement or a land-use flow into a compound.
    #     Here rather than later because the point of stating a class is that it
    #     does not depend on the chemistry rules happening to agree -- today
    #     they do, since the same file gives the substance a SMILES that types
    #     it the same way, and a correction that is only right while that holds
    #     is not a correction.
    correction = correction_for(_registry_numbers(obj))
    if correction is not None:
        return Classification((correction.flow_type,), "curated_structure")

    # 1. A nuclide.  The isotope record is the only reliable signal: the label
    #    form "Americium-241" also matches refrigerant codes like "HCFC-123a".
    isotope = properties.get("isotope")
    if isinstance(isotope, dict) and isotope:
        types = [IRIS[Term.ISOTOPE]]
        if isotope.get("decay_modes") or isotope.get("half_life_and_uncertainty"):
            types.append(IRIS[Term.RADIONUCLIDE])
        return Classification(tuple(types), "isotope_record")

    # 2. An element, already typed from the periodic table.  A charged one is
    #    *only* an ion: `ChemicalElement` is the generic form, with charge
    #    unspecified, so it and a charge state are mutually exclusive -- unlike
    #    `FullySpecifiedAtom`, which this used to emit alongside the ion class.
    if CHEMROF_CHEMICAL_ELEMENT in _existing_types(obj):
        if charged:
            return Classification(
                _ion_types(charge, monoatomic=True), "element_with_charge"
            )
        return Classification((CHEMROF_CHEMICAL_ELEMENT,), "element")

    # 3. One atom, charged: a monoatomic ion, whatever the label says.
    if charged and _is_single_atom(formula):
        return Classification(_ion_types(charge, monoatomic=True), "monoatomic_ion")

    # 4. Several components: held together by something weaker than a covalent
    #    bond.  A charged component makes it a salt rather than a complex.
    if "." in smiles:
        parts = smiles.split(".")
        ionic = any(
            _SMILES_CATION.search(part) or _SMILES_ANION.search(part)
            for part in parts
        )
        if ionic:
            return Classification(
                (IRIS[Term.CHEMICAL_SALT],), "multi_component_ionic"
            )
        return Classification(
            (IRIS[Term.MOLECULAR_COMPLEX],), "multi_component_neutral"
        )

    # 5. Several atoms with a net charge: a polyatomic ion.
    if charged and formula:
        return Classification(_ion_types(charge, monoatomic=False), "polyatomic_ion")

    # 6. One covalently bonded structure, no net charge.
    if smiles:
        # Allotrope before zwitterion, deliberately.  Ozone's canonical SMILES
        # is `[O-][O+]=O` -- separated formal charges that net to zero -- so the
        # zwitterion test matches it, and "a zwitterion of oxygen" is not a
        # thing.  One element means the allotrope answer is the right one.
        if formula and _distinct_elements(formula) == 1 and not _is_single_atom(formula):
            return Classification((IRIS[Term.ALLOTROPE],), "allotrope")
        # The cheap string test first: it is wrong often enough to need the
        # structural check, but it keeps RDKit off the other 97% of the list.
        if (
            _SMILES_CATION.search(smiles)
            and _SMILES_ANION.search(smiles)
            and _is_zwitterion(smiles)
        ):
            return Classification((IRIS[Term.ZWITTERION],), "zwitterion")
        return Classification((IRIS[Term.NEUTRAL_MOLECULE],), "neutral_molecule")

    # ── Everything below has no usable structure. ──

    # 7. Not a substance: every context it occurs in counts something other
    #    than chemistry -- land use, money, an inventory indicator, or a
    #    non-material environmental burden such as noise.  Untyped by decision,
    #    not by omission: ChemROF has no class for any of them, and this project
    #    mints no IRIs for what it cannot name.
    if context_slots and all(
        _counts_something_other_than_a_substance(slot) for slot in context_slots
    ):
        return Classification(
            (), "", reason=_not_a_chemical_entity_reason(context_slots)
        )

    # 8. A named class of substance rather than one substance.
    if _GROUPING_LABEL.search(label or "") or (
        not _has_registry_identifier(obj)
        and _UNREGISTERED_GROUPING_LABEL.search(label or "")
    ):
        if _ELEMENT_GROUP_LABEL.search(label or ""):
            return Classification(
                (IRIS[Term.ATOM_GROUPING_CLASS],), "element_grouping_label"
            )
        return Classification(
            (IRIS[Term.MOLECULE_GROUPING_CLASS],), "molecule_grouping_label"
        )

    # 9. Extracted as a resource and structureless: a material, not a compound.
    if context_slots and {dimension for dimension, _ in context_slots} <= {"Resource"}:
        return Classification((IRIS[Term.MATERIAL],), "structureless_resource")

    # 10. Registered with an authority but with no structure on file.  That is
    #     what a UVCB is: variable composition, unknown stoichiometry.
    if _has_registry_identifier(obj):
        return Classification(
            (IRIS[Term.IMPRECISE_CHEMICAL_MIXTURE],), "registered_without_structure"
        )

    return Classification((), "", reason="no_structure_and_no_registry_identifier")


# ── applying it ──────────────────────────────────────────────────────────────


def _provenance(derived_from: str, primary: list[str] | None = None) -> dict[str, Any]:
    return Provenance(
        was_generated_by=ACTIVITY,
        was_attributed_to=_ATTRIBUTED_TO,
        had_primary_source=primary or [],
        was_derived_from=derived_from,
    ).to_dict()


def _semantic_entry(
    *, label: str, values: list[Any], derived_from: str, unit: str | None = None
) -> dict[str, Any]:
    entry: dict[str, Any] = {RDFS_LABEL_CURIE: label, "@value": values}
    if unit:
        entry[QUDT_HAS_UNIT] = unit
    entry["provenance"] = _provenance(derived_from)
    return entry


def _nuclide_properties(obj: FlowObject) -> int:
    """Move what the isotope record already knows onto ChemROF slots.

    The data was collected long ago and has sat in an untyped bag: ``symbol``,
    ``mass_number`` and ``decay_modes`` all have declared ChemROF slots.  The
    bag is left in place -- it holds specific activity, discovery year and the
    ChemLIN URL, which have no slot, and the half-life, whose slot cannot
    represent it.

    Returns the number of properties written.
    """
    properties = obj.properties if isinstance(obj.properties, dict) else {}
    isotope = properties.get("isotope")
    if not isinstance(isotope, dict) or not isotope:
        return 0
    written = 0

    mass_number = isotope.get("mass_number")
    try:
        nucleon_number = int(str(mass_number).strip())
    except (TypeError, ValueError):
        nucleon_number = None
    if nucleon_number is not None:
        properties[CHEMROF_NUCLEON_NUMBER] = _semantic_entry(
            label="nucleon number",
            values=[nucleon_number],
            derived_from="isotope.mass_number",
            unit=UNIT_IRI_NUM,
        )
        written += 1

    symbol = str(isotope.get("symbol") or "").strip()
    if symbol:
        properties[CHEMROF_SYMBOL] = _semantic_entry(
            label="symbol", values=[symbol], derived_from="isotope.symbol"
        )
        written += 1

    years = half_life_years(str(isotope.get("half_life_and_uncertainty") or ""))
    if years is not None:
        properties[CHEMROF_HALF_LIFE] = _semantic_entry(
            label="half life",
            values=[years],
            derived_from="isotope.half_life_and_uncertainty",
            unit=UNIT_IRI_YEAR,
        )
        written += 1

    decay_modes = isotope.get("decay_modes")
    modes = [
        str(mode).strip()
        for mode in (decay_modes if isinstance(decay_modes, list) else [decay_modes])
        if str(mode or "").strip()
    ]
    if modes:
        properties[CHEMROF_DECAY_MODE] = _semantic_entry(
            label="decay mode", values=sorted(set(modes)),
            derived_from="isotope.decay_modes",
        )
        written += 1

    obj.properties = properties
    return written


#: Stereochemistry in SMILES: `@`/`@@` for a tetrahedral centre, `/` and `\`
#: for a double-bond configuration.
_STEREO_SMILES = re.compile(r"[@/\\]")

#: An isotopic label: the mass number inside the bracket, `[13C]`, `[2H]`.
#: Anchored on the bracket so a ring-closure digit cannot match.
_ISOTOPE_SMILES = re.compile(r"\[\d+[A-Z]")


def _is_isomeric_smiles(smiles: str) -> bool:
    """True when *smiles* carries what `smiles_string` says it does not."""
    return bool(_STEREO_SMILES.search(smiles) or _ISOTOPE_SMILES.search(smiles))


def isomeric_values_in_graph_slot(properties: Any) -> int:
    """How many `smiles_string` values carry the stereochemistry it excludes.

    The acceptance measure for #51, and asked of the finished record rather
    than of the step that does the splitting: what makes a value wrong is that
    it is published under a name that says it carries no shape, so the question
    can only be answered where it is published.  A run that reports anything but
    zero here is publishing a structure under a field name that denies it.
    """
    if not isinstance(properties, dict):
        return 0
    entry = properties.get(CHEMROF_SMILES_STRING)
    if not isinstance(entry, dict):
        return 0
    raw = entry.get("@value")
    values = raw if isinstance(raw, list) else [raw]
    return sum(
        1 for v in values if isinstance(v, str) and v.strip() and _is_isomeric_smiles(v)
    )


def _merged_provenance(existing: Any, added: dict[str, Any]) -> Any:
    """*added* appended to whatever provenance *existing* already had."""
    if isinstance(existing, list):
        return [*existing, added]
    if isinstance(existing, dict):
        return [existing, added]
    return added


def _split_isomeric_smiles(obj: FlowObject) -> Counter:
    """Move stereo- and isotope-bearing SMILES to `isomeric_smiles_string`.

    ChemROF is explicit that `smiles_string` encodes "a molecular graph, no
    chiral or isotopic information", and this project stores chiral SMILES in
    it -- `C[C@H]1CO[C@H]2...` -- on 1,167 flow objects, 2,283 values.  The
    slot for those is
    `isomeric_smiles_string`, declared `is_a: smiles_string`, so the fix is a
    move rather than a new claim.

    Nothing is dropped.  The original string goes to the isomeric slot and
    `smiles_string` keeps the same structure with the stereochemistry taken
    off, computed by RDKit rather than by editing the string, so what is
    published there is a graph this project can stand behind.

    **A structure RDKit will not parse moves too, and no flat form is written
    for it.**  Those are two separate questions and this used to answer both
    with one decision: because there is no way to compute the graph-only form
    of a string that does not resolve to a molecule -- and a hand-stripped one
    would be a guess -- the string was left in `smiles_string`, which is the one
    slot that says it carries no stereochemistry.  ChEBI's SMILES for
    L-tryptophan, `N[C@@H](Cc1cnc2ccccc12)C(=O)O`, writes the indole nitrogen
    without its hydrogen and will not kekulise, so it stayed there with its
    `[C@@H]` intact and a reader trusting the field name got the shape it was
    promised was absent -- 7 substances, 91 elementary flows, on the 2026-08-12
    build (#51).  Not being able to compute the graph is a reason to publish no
    graph, never a reason to publish the stereochemistry as one.  Where the
    unparseable string was the slot's only value, `smiles_string` is withdrawn
    rather than left empty.
    """
    counts: Counter = Counter()
    properties = obj.properties if isinstance(obj.properties, dict) else {}
    entry = properties.get(CHEMROF_SMILES_STRING)
    if not isinstance(entry, dict):
        return counts
    raw = entry.get("@value")
    values = raw if isinstance(raw, list) else [raw]

    isomeric: list[str] = []
    flattened: list[str] = []
    graph_only: list[Any] = []
    for value in values:
        text = value.strip() if isinstance(value, str) else ""
        if not text or not _is_isomeric_smiles(text):
            graph_only.append(value)
            continue
        isomeric.append(text)
        mol = mol_from_smiles(text)
        flat = graph_only_smiles(mol) if mol is not None else ""
        if not flat:
            counts["isomeric_smiles_unparseable"] += 1
            continue
        flattened.append(text)
        graph_only.append(flat)
    if not isomeric:
        return counts

    # Two source strings differing only in stereochemistry flatten to the same
    # graph, so the slot would otherwise gain a duplicate for every pair moved.
    seen: set[Any] = set()
    deduped = [v for v in graph_only if not (v in seen or seen.add(v))]

    properties = dict(properties)
    if deduped:
        updated = dict(entry)
        updated["@value"] = deduped if isinstance(raw, list) else deduped[0]
        # Only the strings a graph was actually computed from are named as its
        # source: provenance on a value RDKit could not read would say this run
        # derived something from it, and it did not.
        if flattened:
            updated["provenance"] = _merged_provenance(
                entry.get("provenance"),
                Provenance(
                    was_generated_by=ACTIVITY,
                    was_attributed_to=_ATTRIBUTED_TO,
                    had_primary_source=flattened,
                    was_derived_from="smiles_string.stereochemistry_removed",
                ).to_dict(),
            )
        properties[CHEMROF_SMILES_STRING] = updated
    else:
        # Every value carried stereochemistry and none of them flattened, so
        # this record has no molecular graph to publish.  An absent slot says
        # that; an empty one says it in a way nothing downstream reads.
        properties.pop(CHEMROF_SMILES_STRING, None)
        counts["smiles_string_withdrawn_no_graph"] += 1
    properties[CHEMROF_ISOMERIC_SMILES_STRING] = _isomeric_entry(
        properties.get(CHEMROF_ISOMERIC_SMILES_STRING), isomeric, entry
    )
    obj.properties = properties
    counts["isomeric_smiles_moved"] += len(isomeric)
    counts["isomeric_smiles_objects"] += 1
    return counts


def _isomeric_entry(existing: Any, moved: list[str], source: dict[str, Any]) -> dict:
    """The isomeric slot with *moved* added to whatever it already held.

    Added rather than assigned: a record that reaches here having already been
    split -- the merge writes flows by a path that runs this again -- has its
    stereochemistry in this slot, and replacing it with only what this pass
    moved would drop it.
    """
    held = existing.get("@value") if isinstance(existing, dict) else None
    kept = list(held) if isinstance(held, list) else [held] if held else []
    seen: set[Any] = set()
    values = [v for v in [*kept, *moved] if not (v in seen or seen.add(v))]

    records: list[Any] = []
    for provenance in (
        existing.get("provenance") if isinstance(existing, dict) else None,
        source.get("provenance"),
        _provenance("smiles_string"),
    ):
        listed = provenance if isinstance(provenance, list) else [provenance]
        for record in listed:
            if record and record not in records:
                records.append(record)
    return {
        RDFS_LABEL_CURIE: "isomeric smiles string",
        "@value": values,
        "provenance": records[0] if len(records) == 1 else records,
    }


def _withdraw_element_charge(obj: FlowObject) -> bool:
    """Take the charge statement off an object typed `ChemicalElement`.

    `ChemicalElement` is "generic form of an atom, with unspecified neutron or
    charge".  Saying the charge *is* zero specifies it, and ChemROF has a
    different class for that -- `UnchargedAtom` -- which this project has no
    grounds to claim: the value comes from PubChem's entry for the neutral
    element, not from anything asserting that this flow's substance is the
    uncharged form rather than the generic one.

    The value is not lost.  `flow_layers` writes it into `properties.element`
    alongside the atomic number and the approximated neutron number, which is
    the periodic-table row and where an unasserted default belongs.

    Written here rather than at the two places that produce the charge, because
    it is a consequence of the class and only this module knows the class.
    """
    properties = obj.properties if isinstance(obj.properties, dict) else {}
    if CHEMROF_ELEMENTAL_CHARGE not in properties:
        return False
    properties = dict(properties)
    del properties[CHEMROF_ELEMENTAL_CHARGE]
    obj.properties = properties
    return True


#: Every statement here is a statement about *one* substance.  A formula counts
#: the atoms in it, a SMILES and the InChI pair encode its bonds, the two masses
#: weigh it, an IUPAC name names it, and a charge is a state one atom is in.
#:
#: Three kinds of object hold none of them.  A set of isotopes reported as
#: activity has no stated proportions, so there is nothing to count, weigh, name
#: or charge (#238).  A delayed-emission correction is an accounting quantity in
#: kg*a rather than a substance at all, so a formula and a mass describe
#: something it is not (#43).  An aggregate measurement is a quantity defined
#: by the procedure that produces it, so the same applies -- `Acid (as H+)`
#: published the hydron's formula, SMILES, InChI, InChIKey, two masses and an
#: IUPAC name for a number that is the acidity of a discharge (#68).  All
#: three arrive carrying these values through a CAS they share with, or were
#: mistakenly given by, a substance that does have them.
#:
#: What stays is what describes the object rather than the substance:
#: `isotope_lookup` and `isotope_mix_candidates`, which
#: `flow_layers/elements.py` writes for exactly the first kind of flow.
SINGLE_SUBSTANCE_PROPERTIES: tuple[str, ...] = (
    CHEMROF_MOLECULAR_FORMULA,
    CHEMROF_SMILES_STRING,
    CHEMROF_ISOMERIC_SMILES_STRING,
    CHEMROF_INCHI2D_STRING,
    CHEMROF_INCHI2D_KEY_STRING,
    CHEMROF_MOLECULAR_MASS,
    CHEMROF_MONOISOTOPIC_MASS,
    CHEMROF_IUPAC_NAME,
    # The same withdrawal `_withdraw_element_charge` makes for `ChemicalElement`
    # and for the same reason: the value is PubChem's entry for the neutral
    # element, and nothing asserts it of a grouping class over nuclides.
    CHEMROF_ELEMENTAL_CHARGE,
)


def _is_not_a_substance(record: Any) -> bool:
    """Whether *record* holds a substance's chemistry without being one.

    Three families reach a flow object that way: the alpha-emitter aggregates,
    which are a set of isotopes (#238), the delayed-emission corrections, which
    are an accounting quantity in kg*a (#43), and the curated aggregate
    measurements, which are a quantity defined by a procedure (#68).  Asked in
    two places -- once per layer -- so the answer is given once here.

    The first two are recognised by their origin qualifier and the third by its
    name, which is the difference between a substance held apart from another
    and a row that is not a substance at all.  A qualifier answers "why is this
    separate from that"; there is no substance an aggregate measurement is
    separate *from*, so it has none.
    """
    qualifier = getattr(record, "origin_qualifier", None)
    return (
        qualifier == ALPHA_EMITTERS
        or is_delayed_emission_correction(qualifier)
        or _measurement_for(record) is not None
    )


def _single_substance_statements(record: Any) -> set[str]:
    """Which single-substance statements *record* currently holds."""
    properties = record.properties if isinstance(record.properties, dict) else {}
    return {key for key in SINGLE_SUBSTANCE_PROPERTIES if key in properties}


def _properties_without(properties: Any, withdrawn: set[str]) -> dict[str, Any]:
    """*properties* without the keys named in *withdrawn*."""
    entries = properties if isinstance(properties, dict) else {}
    return {key: value for key, value in entries.items() if key not in withdrawn}


def _withdraw_single_substance_properties(record: Any) -> int:
    """Take the single-substance statements off *record*.

    Same shape as `_withdraw_element_charge`: a value the object does not permit
    is removed rather than corrected, because there is no right value to put in
    its place.  Unlike the charge on an element, nothing keeps a copy -- these
    values described the substance, and the substance's own object still carries
    them.

    Takes anything with a `properties` mapping, because both layers still call
    it.  `FlowObject` is what the review apps read and `Flow` is what the
    published export projects; a flow's properties are its object's since #53,
    so by the time the flow layer calls this the withdrawal has already reached
    it and there is nothing to take off.  It is called anyway, and reports what
    it took, because that zero is what says the derivation ran -- a flow it
    missed would publish `Cm` for a record the database types as a grouping
    class, which is the state this once corrected.

    Returns how many properties were withdrawn.

    Writes directly, because the caller left holding a `FlowObject` is
    `assign_semantic_types`, and `LayerWriteLog` records a write to a `Flow`.
    The flow layer's own sweep is `withdraw_single_substance_properties`, which
    does record.
    """
    withdrawn = _single_substance_statements(record)
    if not withdrawn:
        return 0
    record.properties = _properties_without(record.properties, withdrawn)
    return len(withdrawn)


def withdraw_single_substance_properties(
    records: list[Any], *, writes: LayerWriteLog | None = None
) -> Counter:
    """Withdraw the single-substance properties from every such record.

    The flow-layer half of what `assign_semantic_types` does for flow objects.
    Called on `Flow` records once `origin_qualifier` has reached them, which is
    after the layering has resolved and therefore after the typing has run --
    and after the flows have taken their properties from their objects, which is
    why `properties_withdrawn` is now expected to be zero.  See
    `_withdraw_single_substance_properties` for what a non-zero one would mean.

    Through *writes* for that same reason (#94): the figure is zero while the
    derivation holds, and the run that reports a non-zero one is reporting a
    flow that was publishing a molecular formula for a quantity in `kg*a`.  A
    curator reading that flow needs the row saying what was taken off it.
    """
    log = LayerWriteLog() if writes is None else writes
    counts: Counter = Counter()
    for record in records:
        if not _is_not_a_substance(record):
            continue
        counts["records"] += 1
        withdrawn = _single_substance_statements(record)
        if not withdrawn:
            continue
        log.write(
            record,
            "properties",
            _properties_without(record.properties, withdrawn),
            pass_name=_WITHDRAW_PASS_NAME,
            comment="not one substance, so it states no chemistry",
        )
        counts["properties_withdrawn"] += len(withdrawn)
    logger.info("withdrew_single_substance_properties", **dict(counts))
    return counts


def _element_link(obj: FlowObject) -> bool:
    """Express the ion-or-isotope to element link as ``chemrof:has_element``.

    It was ``properties.relationships.parent_element_flow_object_id`` with
    ``relationship_type: "ion_of"`` -- a home-grown pair of strings for a
    relation ChemROF declares on exactly the two classes that need it.  The
    ``relationships`` bag is left in place; the webapps read it.

    The value is a **node reference**, ``{"@id": ...}`` over the minted
    flow-object IRI.  It was the bare ``flow_object_id``, which the export
    flattens to a string, so the one link this project publishes between two of
    its own objects expanded to the literal ``"fo-0bfffb5e4dadc218"`` -- a
    string where the slot's range is a class, and nothing a consumer can
    follow.  Deciding to mint the namespace is what #8 left open; see
    :attr:`~brightway_flows.domain.vocabulary.MintedNamespace.FLOW_OBJECT`
    for why the target being unpublished does not block it.
    """
    properties = obj.properties if isinstance(obj.properties, dict) else {}
    relationships = properties.get("relationships")
    if not isinstance(relationships, dict):
        return False
    parent = str(relationships.get("parent_element_flow_object_id") or "").strip()
    if not parent:
        return False
    properties[CHEMROF_HAS_ELEMENT] = _semantic_entry(
        label="has element",
        values=[{"@id": flow_object_iri(parent)}],
        derived_from="relationships.parent_element_flow_object_id",
    )
    obj.properties = properties
    return True


def _withdraw_registry_identifiers(obj: FlowObject) -> list[str]:
    """Take the CAS and EC numbers off an aggregate measurement.

    A registry identifier names one compound.  A quantity that sums over many
    compounds, or over none, cannot have one -- so a number found here is
    withdrawn rather than corrected, for the reason #57 gave when it took
    dinitrogen's 7727-37-9 off `Nitrogen, Organic Bound`: there is nothing to
    correct it to.

    Withdrawing rather than leaving in place is not tidiness.  A shared registry
    number is this project's proof of shared identity, so a number on one of
    these rows is a merge waiting to happen: it is what fused organic-bound
    nitrogen with the nitrogen-gas rows, and BAFU's 17612-50-9 on
    `COD, Chemical Oxygen Demand` is the same trap with no substance in the
    list to spring it yet.  It is also what typed COD an
    `ImpreciseChemicalMixture`, through a rule that asks only whether a number
    is present.

    Returns the numbers withdrawn, which the caller records on the object.
    Every one is named rather than counted, because a number nobody can see was
    removed is indistinguishable from one that was never there.
    """
    classifications = obj.classifications
    if not isinstance(classifications, dict):
        return []
    withdrawn: list[str] = []
    remaining = dict(classifications)
    for iri_value in (CHEMINF_CAS_REGISTRY_NUMBER, CHEMINF_EC_NUMBER):
        entry = remaining.pop(iri_value, None)
        if not entry:
            continue
        raw = entry.get("@value") if isinstance(entry, dict) else entry
        values = raw if isinstance(raw, list) else [raw]
        withdrawn.extend(str(v).strip() for v in values if str(v or "").strip())
    if len(remaining) != len(classifications):
        obj.classifications = remaining
    return withdrawn


def _label_index(flow_objects: list[FlowObject]) -> dict[str, str]:
    """Preferred labels to flow-object ids, for resolving the curated links.

    A label two objects share resolves to neither.  Eleven preferred labels are
    duplicated in the current build -- `Paraquat`, `Fenoxycarb` and nine others
    -- and picking whichever came first would publish a link to an arbitrary one
    of two substances.  An unresolved link says so; a wrong one does not.
    """
    index: dict[str, str] = {}
    ambiguous: set[str] = set()
    for obj in flow_objects:
        key = canonical_label_value(flow_label_value(obj))
        if not key:
            continue
        if key in index and index[key] != obj.flow_object_id:
            ambiguous.add(key)
        index[key] = obj.flow_object_id
    for key in ambiguous:
        del index[key]
    return index


def _aggregate_link(
    obj: FlowObject, predicate: str, derived_from: str, target: str | None,
    index: dict[str, str],
) -> str:
    """Write one curated link onto *obj*, and say how it went.

    The value is a node reference over the minted flow-object IRI, the shape
    `chemrof:has_element` uses and for the same reason: a bare `flow_object_id`
    flattens to a string a consumer cannot follow.

    Returns the resolution outcome -- the target's id, `"unstated"`, or
    `"unresolved:<label>"`.  Three outcomes and not two, because "the file does
    not name one" and "the file names one that is not in the list" are different
    facts and only the second is a defect.  `Nitrogen, Total (excluding N2)` is
    expressed as nitrogen and the list has `Dinitrogen` but no elemental
    `Nitrogen`, so it reports the second today.
    """
    if target is None:
        return "unstated"
    resolved = index.get(canonical_label_value(target))
    if resolved is None:
        return f"unresolved:{target}"
    properties = obj.properties if isinstance(obj.properties, dict) else {}
    properties[predicate] = _semantic_entry(
        label=derived_from.replace("_", " "),
        values=[{"@id": flow_object_iri(resolved)}],
        derived_from=f"aggregate_measurements.{derived_from}",
    )
    obj.properties = properties
    return resolved


def _apply_aggregate_measurement(
    obj: FlowObject,
    measurement: AggregateMeasurement,
    matched_on: str,
    index: dict[str, str],
) -> dict[str, Any]:
    """Record what *obj* measures, and take off what said it was a substance.

    The class alone would leave the row typed correctly and still carrying a
    compound's registry number and structure, which is how it came to be typed
    wrongly in the first place.  So the same pass states the decision, names the
    quantity, links what the number is expressed as and what it sums over, and
    withdraws the identifiers and single-substance properties that only made
    sense while the row was mistaken for a substance.

    Returns the block written to ``created_from.aggregate_measurement``.
    """
    return {
        "id": measurement.id,
        "label": measurement.label,
        "definition": measurement.definition,
        "matched_on": matched_on,
        "expressed_as": _aggregate_link(
            obj, BRIGHTWAY_EXPRESSED_AS, "expressed_as",
            measurement.expressed_as, index,
        ),
        "sums_over": _aggregate_link(
            obj, BRIGHTWAY_SUMS_OVER, "sums_over", measurement.sums_over, index,
        ),
        "registry_identifiers_withdrawn": _withdraw_registry_identifiers(obj),
        "provenance": _provenance("aggregate_measurements.curated"),
    }


#: The scheme this project's own material concepts live in, from the minted
#: namespace registry rather than spelled here -- the same string builds
#: `turbine_water`'s anchor in `tools/build_environmental_materials.py`, and
#: two literals would let the concept IRI drift from its own `@type`.
MATERIAL_SCHEME = MintedNamespace.ENVIRONMENTAL_MATERIAL.value
#: The scheme itself, which the namespace names without being: the trailing
#: separator is what makes that string a prefix for concepts rather than an IRI
#: of its own.  `skos:inScheme` needs a `skos:ConceptScheme` for an object, and
#: this is the one every concept below belongs to.
MATERIAL_SCHEME_IRI = MATERIAL_SCHEME.rstrip("/")
#: Where the material block sits among the classifications, beside the CHEMINF
#: registry numbers.
MATERIAL_CLASSIFICATION = f"{MATERIAL_SCHEME}concept"

#: Which SKOS mapping property each stated predicate publishes as.  A closed
#: map rather than a lookup by name, so a predicate the taxonomy invents fails
#: here rather than being published as whatever string it happened to hold.
_ANCHOR_PREDICATES = {
    SKOS_EXACT_MATCH_CURIE: SKOS_EXACT_MATCH_IRI,
    SKOS_CLOSE_MATCH_CURIE: SKOS_CLOSE_MATCH_IRI,
    # The taxonomy writes the CURIE; the bare local names are accepted because
    # a curator reading the file will reach for them.
    Term.EXACT_MATCH.value: SKOS_EXACT_MATCH_IRI,
    Term.CLOSE_MATCH.value: SKOS_CLOSE_MATCH_IRI,
}


def _concept_iri(concept_id: str) -> str:
    """This scheme's IRI for one of its own concepts."""
    return f"{MATERIAL_SCHEME}{concept_id.replace('_', '-')}"


def _named(concept: dict[str, Any]) -> dict[str, Any]:
    """*concept* as a node reference, labelled only if the taxonomy labels it.

    `rdfs:label` is omitted rather than falling back to the id.  `saline_water`
    showed why: it was the one node of the sixteen the taxonomy left unlabelled
    -- it groups sea water and brine and no flow lands on it -- and the fallback
    published its snake_case id in the one place every other value is a display
    string, where a reader cannot tell it from something a curator typed (#273).
    It is labelled now, so nothing takes this branch today; the branch is what
    keeps the next unlabelled concept saying nothing instead of saying its id.
    """
    node: dict[str, Any] = {"@id": _concept_iri(concept["id"])}
    if concept["label"]:
        node[RDFS_LABEL_CURIE] = concept["label"]
    return node


def _attach_material(obj: FlowObject) -> Counter:
    """Say which environmental material *obj* is, if it is one.

    Q2 of `plans/water-taxonomy.md`, answered *as a type*: the ENVO or AGROVOC
    class goes in ``@type`` beside whatever the chemistry rules concluded, and
    the concept's place in our own scheme goes in ``classifications``.

    **Appended rather than substituted, and deliberately.**  An object typed both
    `chemrof:NeutralMolecule` and `ENVO:00002149` looks at first like two
    incompatible claims, and it is not: ENVO defines `liquid water` as *an
    environmental material primarily composed of dihydrogen oxide*, so the
    chemistry describes what the material is made of.  The axes are orthogonal
    by construction -- ChemROF says what the molecule is, ENVO says what the
    stuff is -- and dropping either would lose a true statement.

    A concept may also state a `chemrof_type`, which is **read, not derived**.
    `brine` carries one because it is a mixture rather than the molecule and the
    chemistry rules leave it structureless -- but "has no CAS" does not imply
    "is a mixture", so the class is a curated fact in the taxonomy rather than a
    rule applied here.  Water is not a domain with generic rules of that kind.
    """
    counts: Counter = Counter()
    concept = concept_by_flow_object().get(obj.flow_object_id)
    if concept is None:
        return counts

    external = [a for a in concept["anchors"] if a["authority"] != "brightway"]
    minted = [a for a in concept["anchors"] if a["authority"] == "brightway"]
    types = list(obj.types or [])

    stated = concept.get("chemrof_type")
    if stated:
        # Replaces the chemistry conclusion rather than joining it.  Stating a
        # `chemrof_type` is precisely saying the chemistry rules cannot reach
        # this concept, and brine shows why joining would be wrong: it arrived
        # carrying water's CAS -- EF's error, now dropped -- and was typed
        # `NeutralMolecule` from it.  A thing cannot be both a neutral molecule
        # and a mixture, and the published object said it was.
        #
        # Substituted in place rather than appended, because `_compute_flow_type`
        # reads the *first* class and the review apps' `flow_type` facet is
        # documented as the most specific ChemROF one.  Appending put brine's
        # ENVO IRI first and made that facet display `ENVO_00003044`.
        types = [t for t in types if not t.startswith(Namespace.CHEMROF.value)]
        types.insert(0, IRIS[Term(stated)])
        counts["material_chemrof_type"] += 1

    for anchor in external + minted:
        if anchor["iri"] not in types:
            types.append(anchor["iri"])
    obj.types = types

    classifications = (
        obj.classifications if isinstance(obj.classifications, dict) else {}
    )
    # `@id` beside `@value`: the block names a concept, and the concept has an
    # IRI.  It was written without one because a JSON-LD value object may not
    # carry `@id` and every other classification block is a value object -- but
    # none of them is one either.  `{"@value": ["7732-18-5"]}` is already
    # invalid, a value object's `@value` may not be an array, and the sibling
    # `rdfs:label` every block carries is a second violation; expanding one
    # raises rather than producing a literal.  These blocks live on the
    # flow-object layer, which is not part of the published JSON-LD document, so
    # no processor ever reads them and the rule was never in force here.  What
    # the shape cost was real: the concept's own IRI went under `skos:inScheme`,
    # which asserted that every concept is its own scheme (#273).  `inScheme`
    # names the scheme now, and identity is `@id`, which is what it is for.
    entry: dict[str, Any] = {
        **_named(concept),
        "@value": [concept["id"]],
        SKOS_IN_SCHEME_IRI: [{"@id": MATERIAL_SCHEME_IRI}],
        "provenance": _provenance("material_taxonomy"),
    }
    # The predicate is per anchor because the data models it that way: every
    # concept says `exactMatch` today, and publishing a future `closeMatch` as
    # an exact equivalence to an ENVO class would be a false assertion nothing
    # would catch.
    for anchor in external:
        predicate = _ANCHOR_PREDICATES[anchor["predicate"]]
        entry.setdefault(predicate, []).append({"@id": anchor["iri"]})
    if concept.get("broader"):
        parent = material_concepts()[concept["broader"]]
        entry[SKOS_BROADER_IRI] = [
            {
                **_named(parent),
                # Whose edge it is, carried onto the published object: the
                # scheme adds two ENVO does not make, and a consumer must be
                # able to tell them from the ones it does.  `provenance` rather
                # than `source`, which would shadow the declared `dcterms:source`.
                "provenance": {"edge_source": concept["broader_source"]},
            }
        ]
    if concept.get("related"):
        # `related`, not `relatedMatch`: both ends are ours.  Using the mapping
        # property between two concepts of one scheme is the mistake `broader`
        # was declared to avoid.
        entry[SKOS_RELATED_IRI] = [
            {"@id": _concept_iri(r)} for r in concept["related"]
        ]
    classifications[MATERIAL_CLASSIFICATION] = entry
    obj.classifications = classifications
    counts["material_taxonomy"] += 1
    return counts


#: The scheme this project's own land classes live in.  Beside the materials,
#: from the registry rather than spelled here, for the same reason: two literals
#: would let a concept's IRI drift from the `@type` that names its scheme.
LAND_SCHEME = MintedNamespace.LAND_CLASS.value
LAND_SCHEME_IRI = LAND_SCHEME.rstrip("/")
#: Where the land block sits among the classifications, beside the material one.
LAND_CLASSIFICATION = f"{LAND_SCHEME}concept"

#: Which SKOS mapping property each anchor's stated predicate publishes as.
#:
#: Four rather than the material scheme's two, and that is the point of §3.7:
#: `exactMatch` is earned here rather than assumed.  Most covers are honestly
#: `closeMatch` or `broadMatch` -- our value is narrower or coarser than the
#: published class -- and most regimes are `relatedMatch`, because the AGROVOC
#: concept is a *practice* and our field says the land is under it.  A closed
#: map, so a predicate the anchors invent fails here rather than being published
#: as whatever string it happened to hold.
_LAND_ANCHOR_PREDICATES = {
    SKOS_EXACT_MATCH_CURIE: SKOS_EXACT_MATCH_IRI,
    SKOS_CLOSE_MATCH_CURIE: SKOS_CLOSE_MATCH_IRI,
    SKOS_BROAD_MATCH_CURIE: SKOS_BROAD_MATCH_IRI,
    SKOS_RELATED_MATCH_CURIE: SKOS_RELATED_MATCH_IRI,
}


def _land_concept_iri(key: str) -> str:
    """This scheme's IRI for one of its own land classes."""
    return f"{LAND_SCHEME}{key}"


@functools.cache
def _land_class_by_object_id() -> dict[str, LandUse]:
    """``flow object id -> land class``, for every class a source flow reaches.

    Recomputed from the class rather than threaded through from the layering.
    Both ends compose the id the same way, through `land_object_id`, so they
    cannot disagree about which object is which class.
    """
    return {land_object_id(value): value for value in published_land_classes().values()}


def _attach_land_class(obj: FlowObject) -> Counter:
    """Say which land class *obj* is, if it is one.

    The answer rule 7 could not give.  Every land flow in the build is typed
    `land_use_not_a_chemical_entity` -- correct, and the end of what the typing
    had to say about a forest.  A land class is not a substance and it is not
    nothing: it is an ENVO or IUCN GET environmental class, held under a set of
    AGROVOC practices, and this states that.

    **Substituted, not appended**, which is the opposite of the material rule
    and for a reason the material rule spells out itself.  ENVO's `liquid water`
    is *an environmental material primarily composed of dihydrogen oxide*, so
    the chemistry and the material describe one thing from two sides and both
    are true.  A land class has no chemistry to describe: rule 7 leaves the
    types empty, and there is nothing here to append to.

    The cover anchor goes first, because `_compute_flow_type` reads the first
    class and the review app's facet should show what the land *is* rather than
    which farming practice it is under.  `anchors_for` returns it first for the
    same reason.
    """
    counts: Counter = Counter()
    land_use = _land_class_by_object_id().get(obj.flow_object_id)
    if land_use is None:
        return counts

    anchors = anchors_for(land_use)
    types = list(obj.types or [])
    for anchor in anchors:
        if anchor.iri not in types:
            types.append(anchor.iri)
    obj.types = types

    classifications = (
        obj.classifications if isinstance(obj.classifications, dict) else {}
    )
    entry: dict[str, Any] = {
        "@id": _land_concept_iri(land_use.key),
        RDFS_LABEL_CURIE: land_use.label,
        "@value": [land_use.key],
        SKOS_IN_SCHEME_IRI: [{"@id": LAND_SCHEME_IRI}],
        "provenance": _provenance("land_use_taxonomy"),
    }
    for anchor in anchors:
        predicate = _LAND_ANCHOR_PREDICATES[anchor.predicate]
        entry.setdefault(predicate, []).append(
            {"@id": anchor.iri, RDFS_LABEL_CURIE: anchor.label}
        )

    parent = land_use.broader()
    if parent is not None and parent.key in published_land_classes():
        # No `edge_source` beside it, unlike the material scheme's.  Every edge
        # here is generated by dropping a field, so the whole edge set is ours
        # by construction and there is nothing to tell apart -- which is why
        # §3.7 states it once in this comment rather than 336 times in the data.
        entry[SKOS_BROADER_IRI] = [
            {
                "@id": _land_concept_iri(parent.key),
                RDFS_LABEL_CURIE: parent.label,
            }
        ]
    classifications[LAND_CLASSIFICATION] = entry
    obj.classifications = classifications
    counts["land_taxonomy"] += 1
    return counts


def assign_semantic_types(
    flow_objects: list[FlowObject],
    elementary_flows: list[Any] | None = None,
) -> Counter:
    """Type every flow object, and record how each decision was reached.

    *elementary_flows* supply the contexts, which are the only way to tell a
    land-use class, a raw material or a non-material burden from a structureless
    chemical -- that information lives on the occurrence, not on the substance.

    Mutates ``types``, ``properties`` and ``created_from`` in place and returns
    a tally: one key per rule that fired, plus ``untyped_<reason>``.
    """
    slots: dict[str, set[ContextSlot]] = {}
    for row in elementary_flows or []:
        object_id = str(getattr(row, "flow_object_id", "") or "").strip()
        if not object_id:
            continue
        context = row.context
        # A merge-created flow whose context IRI resolved to nothing has no
        # context, and contributes no slot rather than an empty one.
        if context is None:
            continue
        slots.setdefault(object_id, set()).add(
            (context.dimension.value, context.media.value if context.media else "")
        )

    # A minted intervention family has no elementary flows of its own: it is a
    # vocabulary entry, as the minted elements are, and nothing is ever emitted
    # as `Noise` in the abstract.  With no contexts it would reach the last rule
    # and be told its identity was unreadable -- the answer #70 exists to stop
    # -- so it inherits its members'.  That is not a convenience: the family
    # *does* occur wherever its members occur, and the same set decides the
    # membership in `flow_layers.non_material`.
    for obj in flow_objects:
        parent = obj.parent_intervention_id
        if parent:
            slots.setdefault(parent, set()).update(
                slots.get(obj.flow_object_id, set())
            )

    # Built once, before any object is typed: the curated links resolve to
    # other flow objects, so the whole layer has to be in hand before the first
    # one can be written.
    label_index = _label_index(flow_objects)

    counts: Counter = Counter()
    for obj in flow_objects:
        classification = classify(
            obj,
            label=flow_label_value(obj),
            context_slots=frozenset(slots.get(obj.flow_object_id, set())),
        )
        if classification.types:
            obj.types = list(classification.types)
            counts[classification.rule] += 1
        else:
            counts[f"untyped_{classification.reason}"] += 1

        material_counts = _attach_material(obj)
        counts.update(material_counts)

        # After the material and never before it: the two write different
        # classification blocks and neither object is ever both, but the rule
        # recorded below has to name whichever of them decided the types, and
        # reading them in one order is how that stays sayable.
        land_counts = _attach_land_class(obj)
        counts.update(land_counts)

        created_from = obj.created_from if isinstance(obj.created_from, dict) else {}
        # `obj.types` rather than `classification.types`: the material step may
        # have replaced the chemistry conclusion, and a provenance trail that
        # records why an object carries a class must not name a class it does
        # not carry.  The rule that actually decided it is named too.
        rule = classification.rule or ""
        if material_counts.get("material_chemrof_type"):
            rule = "material_taxonomy.chemrof_type"
        if land_counts.get("land_taxonomy"):
            # The rule that decided it, replacing the empty one rule 7 left.
            # `land_use_not_a_chemical_entity` stays in the *reason* -- it is
            # still true and it is still why no ChemROF class was reached --
            # but an object that now carries an ENVO class must not record
            # that nothing typed it.
            rule = "land_use_taxonomy"
        created_from["semantic_typing"] = {
            "rule": rule,
            "reason": classification.reason or "",
            "types": list(obj.types or []),
            "provenance": _provenance(
                f"semantic_typing.rule.{classification.rule or classification.reason}"
            ),
        }

        # After the typing block, because the class is what makes this row a
        # measurement, and before the property passes below, which withdraw
        # what a substance's identity brought with it.  The two links this
        # writes are not in `SINGLE_SUBSTANCE_PROPERTIES` and survive that
        # withdrawal, which is the point: they are what the row keeps.
        matched = _measurement_for(obj, flow_label_value(obj))
        if matched is not None:
            measurement, matched_on = matched
            record = _apply_aggregate_measurement(
                obj, measurement, matched_on, label_index
            )
            created_from["aggregate_measurement"] = record
            counts["aggregate_measurement_registry_identifiers_withdrawn"] += len(
                record["registry_identifiers_withdrawn"]
            )
            for key in ("expressed_as", "sums_over"):
                if str(record[key]).startswith("unresolved:"):
                    counts[f"aggregate_measurement_{key}_unresolved"] += 1
                elif record[key] != "unstated":
                    counts[f"aggregate_measurement_{key}_links"] += 1
        obj.created_from = created_from

        counts["nuclide_properties"] += _nuclide_properties(obj)
        counts.update(_split_isomeric_smiles(obj))
        if _is_not_a_substance(obj):
            counts["single_substance_properties_withdrawn"] += (
                _withdraw_single_substance_properties(obj)
            )
        if classification.rule == "element" and _withdraw_element_charge(obj):
            counts["element_charge_withdrawn"] += 1
        if _element_link(obj):
            counts["has_element_links"] += 1

    logger.info("assigned_semantic_types", **dict(counts))
    return counts
