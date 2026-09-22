"""Label, definition and text helpers shared across the layering modules.

A label or definition is a list of `{"@value", "@language", "provenance"}` rows
rather than a string, and every module here writes them the same way: build a
row with `_label_entry`, merge two lists with `_merge_label_rows`, read one back
with `_object_pref_label_value`.  The normalisation helpers (`_norm_text`,
`_canonical_name`) are the keys those merges and the enrichment lookups are
indexed by.
"""

from __future__ import annotations

from typing import Any

import orjson

from brightway_flows.domain.common import Provenance
from brightway_flows.domain.flow_object import FlowObject
from brightway_flows.domain.labels import (
    coerce_alt_labels,
    coerce_pref_label,
    strip_markup,
)
from brightway_flows.domain.vocabulary import (
    PROV_HAD_PRIMARY_SOURCE_CURIE,
    PROV_WAS_DERIVED_FROM_CURIE,
    PROV_WAS_GENERATED_BY_CURIE,
)


def _norm_text(value: str) -> str:
    return " ".join(value.lower().split())


def _canonical_name(value: str) -> str:
    return "".join(ch.lower() for ch in value if ch.isalnum())


def _reference_key(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, dict):
        raw = value.get("@id")
        if isinstance(raw, str) and raw.strip():
            return raw.strip()
    return ""


def _provenance_rows(value: Any) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if isinstance(value, dict):
        rows.append(value)
    elif isinstance(value, list):
        rows.extend([x for x in value if isinstance(x, dict)])
    return rows


def _merge_provenance(existing: Any, incoming: Any) -> dict[str, Any] | list[dict[str, Any]] | None:
    rows = _provenance_rows(existing) + _provenance_rows(incoming)
    deduped: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in rows:
        marker = orjson.dumps(row, option=orjson.OPT_SORT_KEYS).decode("utf-8")
        if marker in seen:
            continue
        seen.add(marker)
        deduped.append(row)
    if not deduped:
        return None
    if len(deduped) == 1:
        return deduped[0]
    return deduped


def _label_entry(
    *,
    value: str,
    language: str,
    resolver_name: str,
    seed_source: str,
    was_derived_from: str,
    extra_primary_sources: list[str] | None = None,
    label_source: Any = None,
) -> dict[str, Any]:
    """One `{"@value", "@language", "provenance"}` row for a label.

    `label_source` is the provenance the label already carries on the flow it
    is being copied from, and it wins over the layering's own attribution
    (#247).  A label written by an enricher -- a Common Chemistry trade name,
    a ChEBI synonym -- was not produced by the resolver that built the object
    and did not come from the list the object was seeded from, so publishing
    `wasGeneratedBy: hybrid_name_cas_v1` and `hadPrimarySource: ["EF 3.1"]`
    over it named the wrong origin for ~99.5% of published labels.  The
    generating activity and `wasDerivedFrom` are taken from the label, and the
    seed source joins the label's own primary sources rather than replacing
    them: it still records which member list put this label on this object,
    which matters once several lists merge into one.
    """
    own = label_source if isinstance(label_source, dict) else None
    primary_sources = [seed_source] if seed_source else []
    if isinstance(extra_primary_sources, list):
        primary_sources.extend([x for x in extra_primary_sources if isinstance(x, str) and x.strip()])
    if isinstance(label_source, str) and label_source.strip():
        primary_sources.append(label_source.strip())

    generated_by = resolver_name
    derived_from = was_derived_from
    if own is not None:
        own_generated_by = own.get(PROV_WAS_GENERATED_BY_CURIE)
        if isinstance(own_generated_by, str) and own_generated_by.strip():
            generated_by = own_generated_by.strip()
        own_derived_from = own.get(PROV_WAS_DERIVED_FROM_CURIE)
        if isinstance(own_derived_from, str) and own_derived_from.strip():
            derived_from = own_derived_from.strip()
        own_sources = own.get(PROV_HAD_PRIMARY_SOURCE_CURIE)
        if isinstance(own_sources, str):
            own_sources = [own_sources]
        if isinstance(own_sources, list):
            primary_sources.extend([x for x in own_sources if isinstance(x, str) and x.strip()])

    primary_sources = sorted({x.strip() for x in primary_sources if x.strip()})
    provenance = Provenance(
        was_generated_by=generated_by,
        was_attributed_to="brightway-flows",
        had_primary_source=primary_sources,
        was_derived_from=derived_from,
    ).to_dict()
    return {
        "@value": value,
        "@language": language,
        "@lang": language,
        "provenance": provenance,
    }


def _object_pref_label_value(obj: FlowObject | None) -> str:
    """The flow object's prefLabel, or "" when there is no object.

    The `None` check was `not isinstance(obj, dict)`, which is true of every
    flow object, so this returned "" for all of them: the EF name index built
    from it was empty, isotope objects were never matched by label, and the two
    sorts keyed on it ordered nothing.
    """
    if obj is None:
        return ""
    pref = coerce_pref_label(obj.prefLabel)
    if pref is not None and isinstance(pref.value, str) and pref.value.strip():
        return pref.value.strip()
    return ""


def _object_alt_label_values(obj: FlowObject | None) -> list[str]:
    if obj is None:
        return []
    return [
        item.value.strip()
        for item in coerce_alt_labels(obj.altLabel)
        if isinstance(item.value, str) and item.value.strip()
    ]


def _merge_label_rows(existing: Any, incoming: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: dict[tuple[str, str], dict[str, Any]] = {}

    def _iter_rows(raw: Any):
        if isinstance(raw, list):
            for row in raw:
                if isinstance(row, dict):
                    yield row
        elif isinstance(raw, dict):
            yield raw

    for row in [*_iter_rows(existing), *incoming]:
        text = row.get("@value")
        if not isinstance(text, str) or not text.strip():
            continue
        lang = row.get("@language")
        if not isinstance(lang, str) or not lang.strip():
            raw_lang = row.get("@lang")
            lang = raw_lang if isinstance(raw_lang, str) and raw_lang.strip() else "en"
        key = (_norm_text(text), lang.lower().strip())
        normalized = dict(row)
        normalized["@value"] = text.strip()
        normalized["@language"] = lang.strip()
        normalized["@lang"] = lang.strip()
        if key not in merged:
            merged[key] = normalized
            continue
        combined = dict(merged[key])
        prov = _merge_provenance(combined.get("provenance"), normalized.get("provenance"))
        if prov is not None:
            combined["provenance"] = prov
        merged[key] = combined

    return [
        merged[key]
        for key in sorted(merged.keys(), key=lambda x: (x[0], x[1]))
    ]


def _set_pref_label(
    *,
    obj: dict[str, Any],
    value: str,
    resolver_name: str,
    seed_source: str,
    was_derived_from: str,
    extra_primary_sources: list[str] | None = None,
    label_source: Any = None,
) -> None:
    clean = value.strip()
    if not clean:
        return
    row = _label_entry(
        value=clean,
        language="en",
        resolver_name=resolver_name,
        seed_source=seed_source,
        was_derived_from=was_derived_from,
        extra_primary_sources=extra_primary_sources,
        label_source=label_source,
    )
    obj.prefLabel = [row]


def _definition_key(value: Any) -> tuple[str, str]:
    if not isinstance(value, dict):
        return ("", "")
    language = value.get("@language")
    text = value.get("@value")
    lang = language.strip().lower() if isinstance(language, str) and language.strip() else "en"
    val = strip_markup(text).strip() if isinstance(text, str) else ""
    return (lang, val)


def _strip_definition_markup(row: dict[str, Any]) -> dict[str, Any]:
    """Return *row* with markup removed from its ``@value``.

    `enrich_references` strips a definition as it creates it, but a definition
    can also arrive on an input flow, and that one has never been through it.
    Definitions are published in `flow-objects.json` and, flattened, in the
    simple export, so this is the last point at which one can still be raw.
    """
    text = row.get("@value")
    if not isinstance(text, str):
        return row
    stripped = strip_markup(text).strip()
    if stripped == text:
        return row
    return {**row, "@value": stripped}
