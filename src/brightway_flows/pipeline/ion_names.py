"""Apply the ion naming standard to the substances a build publishes.

`domain.ion_names` says what an ion is called and which synonyms it carries.
This pass makes every ion substance say it, last of the substance-name writers,
so that whichever route a name took -- EF's `arsenic (v)` parsed by
`flow_layers.ions`, a curated name copied from the merge's lookup spelling
(`Copper, Ion`), a vendor's `X, ion` title-cased and minted by the merge
(`Chromium, Ion`), PubChem's `Cesium(1+)` -- the published list spells it one
way and answers to the others.

What it does **not** decide is whether an ion's charge is known.  That is
`IonPrefLabelPass`'s question, gated by `preferred-label-decisions.json` and by
the disambiguation rule of #143: `Titanium, ion` stays generic though PubChem
says Ti+4.  This pass reads the charge the name already states and spells it,
so it changes how a name is written and never which ion it names.  A
monatomic anion is the one case where the charge is read from the object
rather than the name, because `Chloride` states it by being an anion name.

Deliberately not a `Transformer`: it reads semantic types and the stated
charge, which exist only once the substances are built.  Returns a `Counter`
and leaves its trace in the provenance it stamps on each label, because a
`LayerWriteLog` records writes to flows and this writes to flow objects --
`SubstancePrefLabelPass`, which runs after it, is what carries the new names
onto the flows, and logs that.
"""

from __future__ import annotations

from collections import Counter
from typing import Any

import structlog

from brightway_flows.domain.common import Provenance
from brightway_flows.domain.flow import Flow
from brightway_flows.domain.flow_object import FlowObject
from brightway_flows.domain.ion_names import (
    ION_NAMING_STANDARD,
    REPLACED_LABEL_DERIVED_FROM,
    STANDARD_SYNONYM_DERIVED_FROM,
    is_anion_name,
    is_replaced_label_row,
    is_standard_label_row,
    standard_ion_label,
    standard_ion_synonyms,
)
from brightway_flows.domain.labels import canonical_label_value, flow_label_value
from brightway_flows.domain.vocabulary import (
    CHEMROF_ELEMENTAL_CHARGE,
    IRIS,
    Term,
)
from brightway_flows.flow_layers.ions import _extract_ion_base_and_charge
from brightway_flows.flow_layers.labels import _label_entry, _set_pref_label
from brightway_flows.pipeline.layer_writes import LayerWriteLog
from brightway_flows.sources import base_source_label

logger = structlog.get_logger(__name__)

PASS_NAME = ION_NAMING_STANDARD

#: One atom with a charge: these take the whole standard.
_MONATOMIC_ION_TYPES = frozenset(
    IRIS[term] for term in (Term.MONOATOMIC_ION, Term.ATOM_CATION, Term.ATOM_ANION)
)
#: Several atoms with a charge: only the generic `X, ion` spelling applies,
#: because a numeral would state an oxidation number no one atom has.
_POLYATOMIC_ION_TYPES = frozenset(
    IRIS[term]
    for term in (Term.POLYATOMIC_ION, Term.MOLECULAR_ANION, Term.MOLECULAR_CATION)
)

_GENERIC_SUFFIXES = (", ion", " ion")

_WAS_DERIVED_FROM = STANDARD_SYNONYM_DERIVED_FROM


def _types(obj: FlowObject) -> set[str]:
    raw = obj.types
    if isinstance(raw, str):
        return {raw}
    if isinstance(raw, list):
        return {str(x) for x in raw if isinstance(x, str)}
    return set()


def _ion_of_an_element(obj: FlowObject) -> bool:
    """Whether `flow_layers.ions` recorded *obj* as an ion of an element.

    A second way of knowing an object is one charged atom, because the typing
    can say otherwise: on the build of `43403ac` (run
    `20261019T0759116033000000`) `Palladium(2+)`, `Rhodium(3+)`, `Rhenium(2+)`
    and `Chromium IV` are each typed an imprecise mixture (#403), and each is
    recorded as the ion of its element with one stated charge.  The record is
    written only where the name resolved to an element, so `Pyrethrin I` --
    a name ending in a numeral -- is never read as one.
    """
    properties = obj.properties
    if not isinstance(properties, dict):
        return False
    relationships = properties.get("relationships")
    return (
        isinstance(relationships, dict)
        and relationships.get("relationship_type") == "ion_of"
        and bool(relationships.get("parent_element_flow_object_id"))
    )


def _stated_charge(obj: FlowObject) -> int | None:
    """The one non-zero charge *obj* states, or ``None``."""
    properties = obj.properties
    if not isinstance(properties, dict):
        return None
    entry = properties.get(CHEMROF_ELEMENTAL_CHARGE)
    if not isinstance(entry, dict):
        return None
    values = entry.get("@value")
    if not isinstance(values, list):
        values = [values]
    charges = {int(v) for v in values if isinstance(v, (int, float))}
    if len(charges) != 1:
        return None
    return charges.pop() or None


def _generic_base(label: str) -> str:
    lower = label.lower()
    for suffix in _GENERIC_SUFFIXES:
        if lower.endswith(suffix):
            return label[: -len(suffix)].strip().rstrip(",").strip()
    return ""


def ion_reading(obj: FlowObject) -> tuple[str, int | None] | None:
    """What *obj*'s name says it is, as ``(base, charge)``, or ``None``.

    ``None`` where the standard is not about *obj*: not an ion, or an ion whose
    name this cannot read.  A charge of ``None`` in the pair is the generic
    reading, `Copper, ion`.
    """
    types = _types(obj)
    monatomic = bool(types & _MONATOMIC_ION_TYPES) or _ion_of_an_element(obj)
    if not monatomic and not types & _POLYATOMIC_ION_TYPES:
        return None
    label = flow_label_value(obj).strip()
    if not label:
        return None
    generic = _generic_base(label)
    if generic:
        return generic, None
    if not monatomic:
        return None
    base, charge = _extract_ion_base_and_charge(label)
    if base and charge:
        return base, charge
    stated = _stated_charge(obj)
    if stated is not None and stated < 0 and is_anion_name(label):
        return label, stated
    return None


def _label_row(value: str, *, replaced: bool = False) -> dict[str, Any]:
    return _label_entry(
        value=value,
        language="en",
        resolver_name=PASS_NAME,
        seed_source=base_source_label(),
        was_derived_from=REPLACED_LABEL_DERIVED_FROM if replaced else _WAS_DERIVED_FROM,
    )


def _row_value(row: Any) -> str:
    value = row.get("@value") if isinstance(row, dict) else row
    return value.strip() if isinstance(value, str) else ""


def standardise_ion_names(flow_objects: list[FlowObject]) -> Counter[str]:
    """Give every ion in *flow_objects* the standard name and synonyms.

    Mutates the objects.  A name the standard replaces stays as a synonym, so
    nothing a source list called the substance stops finding it.  The
    standard's synonyms lead the list, ahead of what enrichment gathered, and
    are stamped `ion_naming_standard`: the export keeps the first of two
    spellings that differ only in case, and `carry_member_names` never
    withdraws a label the standard promised.
    """
    stats: Counter[str] = Counter()
    for obj in flow_objects:
        reading = ion_reading(obj)
        if reading is None:
            continue
        base, charge = reading
        stats["ions"] += 1
        stats["generic" if charge is None else "charged"] += 1

        current = flow_label_value(obj).strip()
        label = standard_ion_label(base, charge)
        synonyms = standard_ion_synonyms(base, charge)
        # Labels replaced on an earlier pass -- the transform's, read back by
        # the merge -- stay marked as such, and so does this pass's own.
        replaced = {
            _row_value(row) for row in obj.altLabel or [] if is_replaced_label_row(row)
        }
        if current != label:
            replaced.add(current)
            _set_pref_label(
                obj=obj,
                value=label,
                resolver_name=PASS_NAME,
                seed_source=base_source_label(),
                was_derived_from=_WAS_DERIVED_FROM,
            )
            stats["renamed"] += 1
            logger.debug(
                "ion_name_standardised",
                flow_object_id=obj.flow_object_id,
                was=current,
                now=label,
            )

        synonyms = [*synonyms, *sorted(replaced - set(synonyms) - {label})]
        promised = set(synonyms)
        label_key = canonical_label_value(label)
        kept = []
        for row in obj.altLabel or []:
            value = _row_value(row)
            if value in promised:
                # Re-stamped below rather than kept under the provenance it
                # came with: an unprotected copy is one `carry_member_names`
                # could withdraw.
                continue
            if value and canonical_label_value(value) == label_key:
                # The label itself in another case -- `caesium(1+)` beside
                # `Caesium(1+)` -- which the export would publish as a synonym.
                stats["synonyms_equal_to_the_label_dropped"] += 1
                continue
            kept.append(row)
        before = {_row_value(row) for row in obj.altLabel or []}
        stats["synonyms_added"] += sum(1 for value in synonyms if value not in before)
        obj.altLabel = [
            _label_row(value, replaced=value in replaced) for value in synonyms
        ] + kept

    logger.info("ion_names_standardised", **dict(stats))
    return stats


def _published_synonyms(obj: FlowObject) -> list[str]:
    """The standard's synonyms *obj* carries, in the order it carries them."""
    return [
        _row_value(row) for row in obj.altLabel or []
        if is_standard_label_row(row) and _row_value(row)
    ]


def _flow_label_row(value: str, object_id: str) -> dict[str, Any]:
    """A synonym in the shape a flow's labels take, which is `source` where a
    flow object's take `provenance` (`pipeline.sqlite`)."""
    return {
        "@value": value,
        "@language": "en",
        "@lang": "en",
        "source": Provenance(
            was_generated_by=PASS_NAME,
            was_attributed_to="brightway-flows",
            had_primary_source=[],
            was_derived_from=f"flow_object.altLabel ({object_id})",
        ).to_dict(),
    }


def carry_ion_synonyms_onto_flows(
    flows: list[Flow],
    flow_objects: list[FlowObject],
    *,
    writes: LayerWriteLog,
) -> Counter[str]:
    """Give every flow of an ion the synonyms the standard gave its substance.

    The published list takes a flow's synonyms from the flow, and in the
    transform a flow's synonyms are its own, gathered by the chain before any
    substance existed: on the first build of #401, 13 of `Lead(2+)`'s 18
    published flows -- EF 3.1's -- lacked `Lead II` while the substance had
    it, and the 5 the merge minted, which copy their substance's synonyms when
    they are made, had it.  So the standard's synonyms are written onto the
    flows as well, first, as on the substance, and through `writes`, so each
    write reaches the change log.
    """
    stats: Counter[str] = Counter()
    synonyms_by_object = {
        obj.flow_object_id: names
        for obj in flow_objects
        if (names := _published_synonyms(obj))
    }
    for flow in flows:
        object_id = flow.flow_object_id.strip()
        synonyms = synonyms_by_object.get(object_id)
        if not synonyms:
            continue
        promised = set(synonyms)
        kept = [row for row in flow.altLabel or [] if _row_value(row) not in promised]
        rows = [_flow_label_row(value, object_id) for value in synonyms] + kept
        if writes.write(
            flow, "altLabel", rows, pass_name=PASS_NAME,
            comment="the ion naming standard's synonyms, from the substance",
        ):
            stats["flows_given_synonyms"] += 1
    logger.info("ion_synonyms_carried_onto_flows", **dict(stats))
    return stats


__all__ = [
    "PASS_NAME",
    "carry_ion_synonyms_onto_flows",
    "ion_reading",
    "standardise_ion_names",
]
