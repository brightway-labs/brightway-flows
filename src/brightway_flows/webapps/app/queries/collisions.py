"""The elementary-flow collision queue: an item is a group, not a row.

Eleven of the twelve queues are one row per item, which is why they are one
template and a column list each.  This one is not.  Its item is a *group* of
live flows sharing a substance, a context and a unit, and the question it asks
-- are these two flows or one? -- cannot be answered from the identifiers the
payload lists.  Rendered through the shared template it would be a column of
UUIDs (#61), which is why 116 groups were triaged by querying SQLite by hand
(#44, #279, #281) rather than by opening the page that did not exist.

Two things are read rather than taken from the payload:

* **What each flow carries** -- the name its source list shipped, its source and
  how many characterisation factors it holds -- comes from `elementary_flows`,
  keyed by the identifiers the payload does list.  Not `pref_label_value`,
  which is the *substance's* label and so the same on every flow of a group:
  where the flows have different names, the difference shows up as a field they
  disagree on, which is where a curator wants it.
* **What holds the group apart** is computed here, by comparing the flows'
  stored records field by field.

**The flow deduplication would keep** is marked on the row, from the payload's
`deduplication_would_keep`.  It was not rendered while the payload computed it
from the lowest identifier, which is not how deduplication chooses and named
the flow that would be *dropped* on 27 of the 116 groups in the 2026-08-12
build; #58 replaced that with deduplication's own ranking, so the page can now
show it.  It is a conditional and the page says so: these groups are ones
deduplication has already declined to collapse, and the mark is which flow
would be kept if what holds them apart went away.

**Compared, and merely different.**  Deduplication collapses two flows whose
records agree on every field its signature reads, so the fields it reads *and*
the flows disagree on are the whole reason these groups still have two flows in
them.  Those are marked; the rest are shown because they are the evidence a
curator rules on -- most often the two names -- but they are not what keeps the
flows apart.  That distinction is #31: two water flows differing in name alone
were collapsed, because a name is not a field the signature reads, and the
return's factors were lost to the withdrawal.

A difference the page cannot show is not shown: two `prefLabel` entries
carrying one name under two provenances are a disagreement in the record and
two identical cells in a column headed "these differ", which is 21 of the 116
groups.  Dropped, unless the signature reads the field -- there the two
identical cells are the finding, and the header says as much.

`deduplication.SIGNATURE_EXCLUDED_KEYS` is imported rather than restated, so
the page and the pass cannot drift apart.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from typing import Any

import orjson

from brightway_flows.domain.vocabulary import SKOS_DEFINITION_IRI
from brightway_flows.pipeline.deduplication import SIGNATURE_EXCLUDED_KEYS
from brightway_flows.pipeline.sqlite import elementary_flow_record
from brightway_flows.webapps.app.queries.common import Page, load_json

#: Keys no comparison is made on.  Identity differs by definition; the
#: provenance bags record which transformer wrote what rather than what the
#: flow says; `_provided` is the source list's own row, surfaced per flow as the
#: name it shipped instead of as a diff of nested JSON; and `lcia_methods` is
#: excluded because the factors want reading, not diffing -- the counts are
#: shown per flow, and whether the numbers agree is #58's question.
_NOT_COMPARED = frozenset({
    "uuid",
    "identifier",
    "elementary_flow_id",
    "concept_associations",
    "lcia_methods",
    "source_refs",
    "_sources",
    "_transformed",
    "_provided",
})

#: How a field is named to a reader.  A key with no entry is humanised.
_FIELD_LABELS = {
    "prefLabel": "Preferred label",
    "altLabel": "Alternative labels",
    "general_comment": "General comment",
    "cas_numbers": "CAS numbers",
    "cas_number_sources": "Where the CAS came from",
    "cas_match_labels": "Labels the CAS was matched on",
    "ec_numbers": "EC numbers",
    "input_datasets": "Input datasets",
    "synonyms": "Synonyms",
    "properties": "Properties",
    "references": "References",
    "context": "Context",
    "context_iri": "Context",
    "unit_iri": "Unit",
    "source": "Source list",
    SKOS_DEFINITION_IRI: "Definition",
}


@dataclass
class CollisionField:
    """One field the flows of a group do not agree on."""

    key: str
    label: str
    #: True when deduplication's signature reads this field, and so when this
    #: difference is part of what keeps the flows from being collapsed.
    holds_apart: bool = False
    #: True when the flows' values for it render the same -- they differ in
    #: provenance the page does not show.  Only reachable together with
    #: `holds_apart`: a difference that is invisible and holds nothing apart is
    #: not a column.
    same_text: bool = False
    #: True when the column holds what each flow has and the others do not,
    #: rather than the whole field: two overlapping lists rendered whole are
    #: two cells cut off at the same shared prefix.
    differences_only: bool = False


@dataclass
class CollisionFlow:
    """One live flow of a group, with what it carries."""

    uuid: str
    #: The name the source list shipped, before `bootstrap_labels` moved it
    #: into the label fields.  Two flows whose current labels agree can still
    #: have arrived under different names, and that is the evidence.
    provided_name: str = ""
    source: str = ""
    lcia_factor_count: int = 0
    #: True on the flow deduplication's own ranking would keep -- most factors
    #: first, identifier only to break a tie.  A conditional, not a forecast:
    #: this group is one deduplication has declined to collapse (#58).
    would_be_kept: bool = False
    #: This flow's value for each of the group's fields, in that order, so the
    #: template reads a row against a header rather than a dictionary.
    values: list[str] = field(default_factory=list)


@dataclass
class CollisionGroup:
    """One queue item: every live flow sharing a substance, context and unit."""

    item_key: str
    title: str = ""
    flow_object_id: str = ""
    context_iri: str = ""
    context_display: str = ""
    unit: str = ""
    flows: list[CollisionFlow] = field(default_factory=list)
    #: Every field the flows disagree on, in one order for the whole group.
    fields: list[CollisionField] = field(default_factory=list)
    #: Identifiers the payload lists that no row in `elementary_flows` matches.
    #: A database rebuilt under a newer run than the queue was written by, not
    #: a reason to fail the page.
    missing: list[str] = field(default_factory=list)

    @property
    def holding_apart(self) -> list[CollisionField]:
        """The fields deduplication compares and the flows disagree on.

        Empty means nothing the signature reads separates them, which is a
        group deduplication would have collapsed -- worth saying rather than
        rendering as a blank cell.
        """
        return [entry for entry in self.fields if entry.holds_apart]


def _canonical(value: Any) -> bytes:
    """A value as bytes that compare equal exactly when the value does."""
    try:
        return orjson.dumps(value, option=orjson.OPT_SORT_KEYS)
    except TypeError:
        return str(value).encode("utf-8")


def _label_text(value: Any) -> str:
    """A label list as the labels themselves.

    `prefLabel` and `altLabel` are lists of objects carrying a `@value` and the
    provenance of that value.  Rendered as stored, one label is several hundred
    characters of JSON, and the reader is comparing two names.
    """
    if isinstance(value, dict):
        value = [value]
    if not isinstance(value, list):
        return "" if value is None else str(value)
    texts = []
    for entry in value:
        if isinstance(entry, dict):
            text = entry.get("@value")
        else:
            text = entry
        if text not in (None, ""):
            texts.append(str(text))
    return ", ".join(texts)


def _items(key: str, value: Any) -> list[str] | None:
    """A field as the list of things it holds, or None if it is not one."""
    if key in {"prefLabel", "altLabel"}:
        text = _label_text(value)
        return text.split(", ") if text else []
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        return list(value)
    if value is None:
        return []
    return None


def _difference_texts(values: list[list[str]]) -> list[str] | None:
    """Each flow's items that the others do not have, or None.

    Two alternative-label lists of forty entries differing in one render as two
    identical cells, both cut off at the width of the column -- which is 41 of
    the 116 groups in the 2026-08-12 build.  Where the lists overlap at all,
    the entries they do not share are the answer, and the header says that is
    what the column holds.
    """
    shared = set(values[0]).intersection(*(set(value) for value in values[1:]))
    if not shared:
        return None
    return [
        ", ".join(item for item in value if item not in shared) for value in values
    ]


def _value_text(key: str, value: Any) -> str:
    """One field of one flow, as a string a table cell can hold."""
    if key in {"prefLabel", "altLabel"}:
        return _label_text(value)
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        return ", ".join(value)
    return _canonical(value).decode("utf-8")


def _field_label(key: str) -> str:
    label = _FIELD_LABELS.get(key)
    if label:
        return label
    text = key.rsplit("#", 1)[-1].rsplit("/", 1)[-1].replace("_", " ").strip()
    return text[:1].upper() + text[1:] if text else key


def _compared_keys(record: dict[str, Any]) -> set[str]:
    """The keys deduplication's signature reads on one flow.

    `elementary_flow_record` projects the `ElementaryFlow` the pass ran on out
    of the stored `Flow`, and the signature is that record minus the keys it
    excludes.  The projection is not rehydrated with the substance payload,
    deliberately: it takes the substance keys only for a merge-created flow,
    which is the record the pass saw, and rehydrating would hand every flow
    labels the signature never read.
    """
    return set(elementary_flow_record(record)) - SIGNATURE_EXCLUDED_KEYS


def _differing_keys(records: list[dict[str, Any]]) -> list[str]:
    """Every key the flows of a group do not agree on.

    A key on which every flow of a substance agreed is hoisted out of
    `flow_json` into the shared object payload, so a key missing from all of
    them is a key they agree on -- which is why the diff can be taken over the
    stored flows alone.
    """
    keys: set[str] = set()
    for record in records:
        keys.update(record)
    return sorted(
        key
        for key in keys - _NOT_COMPARED
        if len({_canonical(record.get(key)) for record in records}) > 1
    )


def _group(item: Any, rows: dict[str, sqlite3.Row]) -> CollisionGroup:
    uuids = [
        str(uuid)
        for uuid in (item.payload.get("elementary_flow_ids") or [])
        if str(uuid)
    ]
    present = [uuid for uuid in uuids if uuid in rows]
    records = [load_json(rows[uuid]["flow_json"], {}) for uuid in present]
    compared: set[str] = set()
    for record in records:
        compared.update(_compared_keys(record))
    texts = {
        key: [_value_text(key, record.get(key)) for record in records]
        for key in _differing_keys(records)
    }
    # Where the flows hold overlapping lists, only what they do not share.
    partial: set[str] = set()
    for key in list(texts):
        items = [_items(key, record.get(key)) for record in records]
        if len(records) < 2 or any(entry is None for entry in items):
            continue
        difference = _difference_texts(items)
        if difference is not None:
            texts[key] = difference
            partial.add(key)
    # A field the flows disagree on and this page renders identically differs
    # in provenance, not in what it says: 21 of the 116 groups in the
    # 2026-08-12 build carry two `prefLabel` entries with one name between
    # them, under two `prov:wasGeneratedBy`.  Shown, it is a column of two
    # identical cells labelled as a disagreement.  Dropped -- unless it is what
    # holds the flows apart, where two identical cells are the finding and the
    # header says so.
    differing = [
        key for key, values in texts.items()
        if key in compared or len(set(values)) > 1
    ]

    group = CollisionGroup(
        item_key=item.item_key,
        title=item.title,
        flow_object_id=item.flow_object_id
        or str(item.payload.get("flow_object_id") or ""),
        context_iri=str(item.payload.get("context_iri") or ""),
        context_display=(
            rows[present[0]]["context_display"] or "" if present else ""
        ),
        unit=str(item.payload.get("unit") or ""),
        missing=[uuid for uuid in uuids if uuid not in rows],
        fields=[
            CollisionField(
                key=key,
                label=_field_label(key),
                holds_apart=key in compared,
                same_text=len(set(texts[key])) == 1,
                differences_only=key in partial,
            )
            for key in differing
        ],
    )
    would_keep = str(item.payload.get("deduplication_would_keep") or "")
    for index, (uuid, record) in enumerate(zip(present, records, strict=True)):
        row = rows[uuid]
        provided = record.get("_provided")
        provided_name = (
            str(provided.get("name") or "") if isinstance(provided, dict) else ""
        )
        group.flows.append(CollisionFlow(
            uuid=uuid,
            provided_name=provided_name,
            source=row["source"] or "",
            lcia_factor_count=int(row["lcia_factor_count"] or 0),
            would_be_kept=uuid == would_keep,
            values=[texts[key][index] for key in differing],
        ))
    return group


def groups(
    connection: sqlite3.Connection, page: Page[Any]
) -> Page[CollisionGroup]:
    """One page of queue items, with each item's flows read and compared.

    Takes the page rather than querying for it, so the queue's paging, search
    and severity filter are the same code for all twelve queues and only the
    rendering differs.  One query for every flow on the page, not one per
    group.
    """
    uuids = sorted({
        str(uuid)
        for item in page.rows
        for uuid in (item.payload.get("elementary_flow_ids") or [])
        if str(uuid)
    })
    rows: dict[str, sqlite3.Row] = {}
    if uuids:
        placeholders = ",".join("?" * len(uuids))
        rows = {
            row["uuid"]: row
            for row in connection.execute(
                "SELECT uuid, source, lcia_factor_count, "
                "context_display, flow_json FROM elementary_flows "
                f"WHERE uuid IN ({placeholders})",
                uuids,
            )
        }
    return Page(
        rows=[_group(item, rows) for item in page.rows],
        total=page.total,
        number=page.number,
    )
