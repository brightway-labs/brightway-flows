"""What one unit of a consensus substance is worth, on the flow object (#407, phase C).

Three lists say three things about a kilogram of hard coal -- 18.01, 18.2 and
19.1 MJ -- and each statement lives on its source flow and converts its own
row.  The substance itself, `Hard Coal`, is the one place a reader looks for
*the* number, and until now it carried none.  This module writes, onto
`FlowObject.properties`, one entry per quantity the substance has statements
of, holding three things that are kept apart because they are three things:

* a **reference value**, curated in `flow-object-property-values.json` with
  its reason -- the number the base list's own implementer counts -- which a
  list stating nothing of its own would borrow (none does today);
* the **source spread**, derived here from the statements the merged lists
  made and never written by hand, so it cannot drift from the mappings;
* a **class range**, curated from a published table (the IPCC's net calorific
  values), which is what the substance can be rather than what the lists
  said.  A statement outside it is counted, not refused.

The shape is QUDT's: each measurement is a `qudt:QuantityValue` with its
`qudt:hasUnit` and the unit it is per, `qudt:value` for the reference, and
`schema:minValue`/`schema:maxValue` for the two ranges, because QUDT's own
`lowerBound`/`upperBound` belong to its datatype schema and bound no quantity
value (checked against qudt.org 3.5.3).  The entry is keyed by the quantity's
IRI and says which QUDT kind it matches or narrows, as `quantities.json` does.

The statements are read from the `flow_property_statements` table
(`merge.property_rows`), which every merged list has written to by the time
this runs, so the spread spans the lists merged so far rather than the one
merging now.  The ruling's loader takes no path and is cached (rule 13).
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

import orjson
import structlog

from brightway_flows.domain.common import Provenance
from brightway_flows.domain.flow_object import FlowObject
from brightway_flows.domain.quantities import load_quantities, quantity
from brightway_flows.domain.units import unit_iri_for, unit_row_for
from brightway_flows.domain.vocabulary import (
    QUDT_HAS_UNIT_CURIE,
    RDFS_LABEL_CURIE,
    Term,
    curie,
)
from brightway_flows.filesystem import PACKAGE_DATA_DIR
from brightway_flows.merge.property_rows import PropertyStatementRow

logger = structlog.get_logger(__name__)

FLOW_OBJECT_PROPERTY_VALUES_FILEPATH = PACKAGE_DATA_DIR / "flow-object-property-values.json"

#: This file's own format version (rule 13).
DECISIONS_SCHEMA_VERSION = 1

PASS_NAME = "write_flow_object_property_values"
#: The stage the merge records this pass's counts under.
MERGE_PROPERTY_VALUE_STAGE = "merge_flow_object_property_values"
_ATTRIBUTED_TO = "brightway-flows"

QUANTITY_VALUE_CURIE = curie(Term.QUANTITY_VALUE)
VALUE_CURIE = curie(Term.VALUE)
PER_UNIT_CURIE = curie(Term.PER_UNIT)
SOURCE_SPREAD_CURIE = curie(Term.SOURCE_SPREAD)
CLASS_RANGE_CURIE = curie(Term.CLASS_RANGE)
MIN_VALUE_CURIE = curie(Term.MIN_VALUE)
MAX_VALUE_CURIE = curie(Term.MAX_VALUE)
MEASUREMENTS_CURIE = curie(Term.MEASUREMENTS)


@dataclass(frozen=True)
class ClassRange:
    """What the class of substance spans, from a published table."""

    min: float
    max: float
    basis: str
    primary_source: tuple[str, ...]


@dataclass(frozen=True)
class FlowObjectPropertyValue:
    """One row of `flow-object-property-values.json`."""

    flow_object_id: str
    label: str
    quantity: str
    value: float
    unit: str
    per_unit: str
    primary_source: tuple[str, ...]
    comment: str
    class_range: ClassRange | None = None


def _kind_of(unit: str) -> str:
    row = unit_row_for(unit)
    return str(row.get("quantity_kind_iri") or "") if row is not None else ""


def _text(entry: Mapping[str, Any], key: str, *, where: str) -> str:
    value = entry.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{where} has no {key!r}.")
    return value.strip()


def _number(entry: Mapping[str, Any], key: str, *, where: str) -> float:
    value = entry.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{where} has no numeric {key!r}.")
    return float(value)


def _sources(entry: Mapping[str, Any], *, where: str) -> tuple[str, ...]:
    raw = entry.get("primary_source")
    if not isinstance(raw, list) or not raw or not all(isinstance(s, str) and s.strip() for s in raw):
        raise ValueError(f"{where} names no 'primary_source' (rule 16).")
    return tuple(s.strip() for s in raw)


def _class_range(entry: Mapping[str, Any], *, where: str, value: float) -> ClassRange | None:
    raw = entry.get("class_range")
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise ValueError(f"{where} has a 'class_range' that is not an object.")
    low, high = _number(raw, "min", where=where), _number(raw, "max", where=where)
    if not low < high:
        raise ValueError(f"{where} states a class range of {low} to {high}, which is no range.")
    if not low <= value <= high:
        raise ValueError(
            f"{where} states a reference value of {value} outside its own class "
            f"range {low} to {high}; one of them is wrong."
        )
    return ClassRange(
        min=low, max=high, basis=_text(raw, "basis", where=where),
        primary_source=_sources(raw, where=f"{where}'s class_range"),
    )


@lru_cache(maxsize=1)
def load_flow_object_property_values() -> dict[tuple[str, str], FlowObjectPropertyValue]:
    """The ruling, by (flow object id, quantity slug).  Cached: the path is fixed.

    :raises ValueError: for a malformed entry, naming it; a malformed ruling
        raises and is never skipped (rule 14).
    """
    payload = orjson.loads(FLOW_OBJECT_PROPERTY_VALUES_FILEPATH.read_bytes())
    if payload.get("schema_version") != DECISIONS_SCHEMA_VERSION:
        raise ValueError(
            f"{FLOW_OBJECT_PROPERTY_VALUES_FILEPATH.name} has schema_version "
            f"{payload.get('schema_version')!r}; this reader expects {DECISIONS_SCHEMA_VERSION}."
        )
    rows = payload.get("values")
    if not isinstance(rows, list):
        raise ValueError(f"{FLOW_OBJECT_PROPERTY_VALUES_FILEPATH.name} has no 'values' list.")
    out: dict[tuple[str, str], FlowObjectPropertyValue] = {}
    for index, entry in enumerate(rows):
        where = f"Value {index} in {FLOW_OBJECT_PROPERTY_VALUES_FILEPATH.name}"
        if not isinstance(entry, dict):
            raise ValueError(f"{where} is not an object.")
        slug = _text(entry, "quantity", where=where)
        if slug not in load_quantities():
            raise ValueError(f"{where} names quantity {slug!r}, which quantities.json does not have.")
        unit, per_unit = _text(entry, "unit", where=where), _text(entry, "per_unit", where=where)
        unit_kind, per_kind = _kind_of(unit), _kind_of(per_unit)
        if not unit_kind or not per_kind:
            raise ValueError(f"{where} states a unit units.json does not know ({unit!r} per {per_unit!r}).")
        if unit_kind != quantity(slug).quantity_kind_iri or unit_kind == per_kind:
            raise ValueError(
                f"{where} states {slug!r} as {unit!r} per {per_unit!r}, which are not "
                f"a unit of that quantity per a unit of another kind."
            )
        value = _number(entry, "value", where=where)
        if not value > 0:
            raise ValueError(f"{where} states a value of {value}, which is no property.")
        record = FlowObjectPropertyValue(
            flow_object_id=_text(entry, "flow_object_id", where=where),
            label=_text(entry, "label", where=where),
            quantity=slug,
            value=value,
            unit=unit,
            per_unit=per_unit,
            primary_source=_sources(entry, where=where),
            comment=_text(entry, "comment", where=where),
            class_range=_class_range(entry, where=where, value=value),
        )
        key = (record.flow_object_id, slug)
        if key in out:
            raise ValueError(f"{where} states {slug!r} for {record.flow_object_id} a second time.")
        out[key] = record
    return out


def _unit(notation: str) -> str:
    return unit_iri_for(notation) or notation


def _provenance(*, derived_from: str, primary: Iterable[str]) -> dict[str, Any]:
    return Provenance(
        was_generated_by=PASS_NAME,
        was_attributed_to=_ATTRIBUTED_TO,
        had_primary_source=list(primary),
        was_derived_from=derived_from,
    ).to_dict()


def _measurement(
    *,
    unit: str,
    per_unit: str,
    rows: list[PropertyStatementRow],
    curated: FlowObjectPropertyValue | None,
    counts: Counter,
) -> dict[str, Any]:
    """One `qudt:QuantityValue` for one (unit, per unit) of one quantity."""
    node: dict[str, Any] = {
        "@type": QUANTITY_VALUE_CURIE,
        QUDT_HAS_UNIT_CURIE: _unit(unit),
        PER_UNIT_CURIE: _unit(per_unit),
    }
    provenance: list[dict[str, Any]] = []
    if curated is not None:
        node[VALUE_CURIE] = curated.value
        provenance.append({
            "role": "reference-value",
            **_provenance(
                derived_from=FLOW_OBJECT_PROPERTY_VALUES_FILEPATH.name,
                primary=curated.primary_source,
            ),
        })
        counts["reference_values"] += 1
    if rows:
        values = [row.value for row in rows]
        node[SOURCE_SPREAD_CURIE] = {
            MIN_VALUE_CURIE: min(values),
            MAX_VALUE_CURIE: max(values),
            "statements": len(rows),
            "lists": sorted({f"{row.list_name} {row.list_version}".strip() for row in rows}),
        }
        counts["source_spreads"] += 1
        for row in rows:
            provenance.append({
                "role": "statement",
                "list": f"{row.list_name} {row.list_version}".strip(),
                "source_flow": row.source_flow_name,
                "source_flow_uuid": row.source_flow_uuid,
                "value": row.value,
                "stated_by": row.stated_by,
                "used_for_conversion": row.used_for_conversion,
                **row.provenance,
            })
    if curated is not None and curated.class_range is not None:
        span = curated.class_range
        node[CLASS_RANGE_CURIE] = {
            MIN_VALUE_CURIE: span.min,
            MAX_VALUE_CURIE: span.max,
            "basis": span.basis,
            "provenance": _provenance(
                derived_from=FLOW_OBJECT_PROPERTY_VALUES_FILEPATH.name,
                primary=span.primary_source,
            ),
        }
        outside = [row for row in rows if not span.min <= row.value <= span.max]
        if outside:
            counts["statements_outside_class_range"] += len(outside)
            logger.warning(
                "property_statement_outside_class_range",
                flow_object_id=curated.flow_object_id,
                label=curated.label,
                quantity=curated.quantity,
                range=(span.min, span.max),
                statements=[
                    (row.list_name, row.source_flow_name, row.value) for row in outside
                ],
            )
    node["provenance"] = provenance
    return node


def property_entries(
    flow_object_id: str,
    *,
    rows: Iterable[PropertyStatementRow],
    curated: Mapping[tuple[str, str], FlowObjectPropertyValue],
    counts: Counter | None = None,
) -> dict[str, dict[str, Any]]:
    """The entries one flow object's `properties` gains, keyed by quantity IRI.

    One entry per quantity the lists state or the ruling names; within it one
    measurement per (unit, per unit) -- natural gas is stated per kilogram, per
    cubic metre and per standard cubic metre, three measurements of one
    quantity.  The curated reference joins the measurement whose units are
    its own, or stands alone where no list states the pair.
    """
    counts = Counter() if counts is None else counts
    groups: dict[tuple[str, str, str], list[PropertyStatementRow]] = {}
    for row in rows:
        groups.setdefault((row.quantity, row.unit, row.per_unit), []).append(row)
    references = {
        slug: value for (object_id, slug), value in curated.items()
        if object_id == flow_object_id
    }
    for slug, reference in references.items():
        groups.setdefault((slug, reference.unit, reference.per_unit), [])
    entries: dict[str, dict[str, Any]] = {}
    for slug in sorted({slug for slug, _, _ in groups}):
        record = quantity(slug)
        measurements = [
            _measurement(
                unit=unit, per_unit=per_unit, rows=groups[(q, unit, per_unit)],
                curated=(
                    references.get(slug)
                    if references.get(slug) is not None
                    and (references[slug].unit, references[slug].per_unit) == (unit, per_unit)
                    else None
                ),
                counts=counts,
            )
            for (q, unit, per_unit) in sorted(groups)
            if q == slug
        ]
        entries[record.iri] = {
            RDFS_LABEL_CURIE: record.label,
            record.qudt_match_relation: record.qudt_match_iri,
            MEASUREMENTS_CURIE: measurements,
            "provenance": _provenance(
                derived_from="flow_property_statements",
                primary=[FLOW_OBJECT_PROPERTY_VALUES_FILEPATH.name] if slug in references else [],
            ),
        }
    return entries


def write_flow_object_property_values(
    flow_objects: Iterable[FlowObject],
    *,
    rows_by_object: Mapping[str, list[PropertyStatementRow]],
    curated: Mapping[tuple[str, str], FlowObjectPropertyValue] | None = None,
    changed: set[str] | None = None,
) -> Counter:
    """Write each flow object's property entries, in place; return the counts.

    *changed* collects the ids of the objects whose `properties` moved, for
    the write-back.  Returns a `Counter` (rule 11); `FlowObject` is not a
    `Flow`, so the write is direct, as every other pass over objects writes.
    """
    curated = load_flow_object_property_values() if curated is None else curated
    counts: Counter = Counter()
    ruled = {object_id for object_id, _ in curated}
    for obj in flow_objects:
        object_id = obj.flow_object_id
        rows = rows_by_object.get(object_id, [])
        if not rows and object_id not in ruled:
            continue
        entries = property_entries(object_id, rows=rows, curated=curated, counts=counts)
        properties = dict(obj.properties or {})
        if all(properties.get(key) == value for key, value in entries.items()):
            continue
        properties.update(entries)
        obj.properties = properties
        counts["objects_written"] += 1
        counts["entries"] += len(entries)
        if changed is not None:
            changed.add(object_id)
    logger.info("wrote_flow_object_property_values", **dict(counts))
    return counts
