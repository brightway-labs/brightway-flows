"""The denormalised SQLite database backing the review application.

Written fresh on every run. Tables are indexed after bulk insert rather than
during, and FTS5 tables carry the search columns, because the application needs
sub-second queries over ~94k flows.
"""

from __future__ import annotations

import sqlite3
import time
from collections import Counter
from pathlib import Path
from typing import Any

import orjson
import structlog

from brightway_flows.domain.context_registry import (
    CONTEXT_FIELDS,
    context_attributes,
    context_display_parts,
)
from brightway_flows.domain.elementary_flow import ElementaryFlow
from brightway_flows.domain.flow import Flow
from brightway_flows.domain.flow_object import FlowObject
from brightway_flows.domain.vocabulary import (
    CHEMINF_CAS_REGISTRY_NUMBER,
    CHEMINF_EC_NUMBER,
    CHEMROF_CHEMICAL_ELEMENT,
    DCTERMS_IS_REPLACED_BY,
    OWL_DEPRECATED,
    RO_HAS_ROLE_IRI,
    SKOS_DEFINITION_IRI,
)
from brightway_flows.filesystem import CONSENSUS_DB_FILEPATH
from brightway_flows.domain.labels import coerce_alt_labels, flow_label_value
from brightway_flows.domain.lcia.records import (
    non_zero_factor_count_of_entries,
)
from brightway_flows.pipeline.match_strength import cardinality_of, weaken
from brightway_flows.pipeline.review_records import ChangeEvent
from brightway_flows.pipeline.sqlite_schema import (
    insert_statement,
    recreate,
)

logger = structlog.get_logger(__name__)

_UNCLASSIFIED = "unclassified"

def _compute_flow_type(row: dict[str, Any]) -> str:
    """The webapp's filter facet for one flow object.

    This is a *display* facet, not RDF: one value per object, so the review apps
    can group by it.  It reads `@type` and reports the most specific class,
    which is now assigned by `pipeline.semantic_typing` from the chemistry --
    before that, only two classes existed and 98.6% of objects fell through to
    `"consensus"`, which named nothing.

    One value is still not a ChemROF class, and is marked as such by not being
    an IRI: `unclassified`, for an object the typing rules could not place.  The
    reason is on the object, in `created_from.semantic_typing.reason`.

    One value is an IRI and is not ChemROF's: `brightway:AggregateMeasurement`,
    for a quantity defined by the procedure that measures it.  That it sorts
    beside the chemistry here is the point -- a facet that only offered chemical
    classes could not express "this row is not chemistry" (#68).

    `OriginQualifiedSubstance` used to be a second such value, returned for a
    qualified object that no rule had typed.  It fires on nothing in the current
    build -- every one of the 14 qualified objects carries a class -- and if it
    did fire it would answer the wrong question: an object is not typed *either*
    by its chemistry *or* by where it came from, and a facet that collapses the
    two hides the fact that the typing failed.  The qualifier is its own filter
    now, so `unclassified` and `biogenic` can both be said.
    """
    types = row.get("@type", [])
    if isinstance(types, str):
        types = [types]
    class_iris = [str(t) for t in types if isinstance(t, str) and t.strip()]
    if class_iris:
        # Most specific first: the typing pass emits leaves, and where it emits
        # two (a charged element) the ion class is the informative one.
        for iri in class_iris:
            if iri != CHEMROF_CHEMICAL_ELEMENT:
                return iri
        return class_iris[0]
    return _UNCLASSIFIED

#: Keys of `flow_json` that describe the *substance* rather than the occurrence.
#: Every one of them is identical across the flows of an object -- except where
#: it is not, which is the whole reason `_hoist_shared_object_payloads` checks
#: rather than assumes.
_OBJECT_DERIVED_KEYS = (
    "altLabel",
    "properties",
    "references",
    "prefLabel",
    "@type",
    SKOS_DEFINITION_IRI,
    # A role is the substance's, not the occurrence's, so every flow of one
    # object carries the same set and one copy is enough.
    RO_HAS_ROLE_IRI,
)


def _hoist_shared_object_payloads(
    ef_rows: list[tuple],
) -> tuple[list[tuple], list[tuple[str, str]]]:
    """Move each object's shared payload out of its flows and store it once.

    `flow_json` embedded the flow object's body -- labels, properties,
    references -- in every elementary flow.  94,433 flows share 7,730 objects,
    so those keys came to 1,267.5 MiB across the table where one copy each is
    98.6 MiB: 12.4x, and 1.57 GiB of an 8.13 GiB file (#253).

    Hoisted per (object, key), and only where **every** flow of that object
    agrees byte for byte.  They usually do, but not always: on the 2026-08-07
    build 233 objects disagree on `prefLabel`, 72 on `altLabel`, 17 on
    `properties` and 2 on `references`.  A flow that disagrees keeps its own
    copy, and rehydration lets it win -- so the rule is "a key absent from
    `flow_json` is the object's", which needs no notion of an override and
    cannot lose a value.

    `properties` no longer disagrees: since #53 a flow's properties *are* its
    object's, deep-copied onto it by `_link_flows_to_their_substance`, so that
    key now hoists for every object with flows here.  Still checked rather than
    assumed -- the other five keys can disagree, and a check that holds for
    everything costs one comparison to keep saying so.

    Deliberately *not* re-derived from `flow_objects` at read time, which is
    what #254 proposed.  That table holds the same information in a different
    serialisation -- a label there carries `@lang` and `provenance` where the
    flow's carries `source` -- so reading it back would have rewritten 93,993
    of 94,433 `prefLabel` values in the published export.  What is stored here
    is the flow-shaped bytes, verbatim.

    Returns the rewritten rows and the payload rows to insert.
    """
    canonical = lambda value: orjson.dumps(value, option=orjson.OPT_SORT_KEYS)

    # Per object, per key: the distinct canonical forms its flows carry, and
    # how many of its flows carry the key at all.
    seen: dict[str, dict[str, set[bytes]]] = {}
    present: dict[str, dict[str, int]] = {}
    flows_per_object: dict[str, int] = {}
    for row in ef_rows:
        object_id = row[_EF_FLOW_OBJECT_ID]
        flow = row[_EF_FLOW_JSON]
        flows_per_object[object_id] = flows_per_object.get(object_id, 0) + 1
        for key in _OBJECT_DERIVED_KEYS:
            if key not in flow:
                continue
            seen.setdefault(object_id, {}).setdefault(key, set()).add(
                canonical(flow[key])
            )
            present.setdefault(object_id, {})[key] = (
                present.setdefault(object_id, {}).get(key, 0) + 1
            )

    # A key is the object's only if every one of its flows carries it and they
    # all agree.  "Every one" matters: a key some flows lack is not shared, and
    # hoisting it would hand it to flows that never had it.
    shared: dict[str, set[str]] = {}
    for object_id, by_key in seen.items():
        for key, forms in by_key.items():
            if len(forms) == 1 and present[object_id][key] == flows_per_object[object_id]:
                shared.setdefault(object_id, set()).add(key)

    payloads: dict[str, dict[str, Any]] = {}
    rewritten: list[tuple] = []
    for row in ef_rows:
        object_id = row[_EF_FLOW_OBJECT_ID]
        flow = row[_EF_FLOW_JSON]
        keys = shared.get(object_id, set())
        if keys:
            if object_id not in payloads:
                # Written in the declared order, not the order the set hands
                # them over.  Python randomises the iteration order of a set of
                # strings per process, so every rebuild wrote all 7,683 payload
                # rows -- 94.8 MiB -- with their keys shuffled differently, and
                # two runs of one revision could not be compared byte for byte
                # (#293).  The set stays a set; it answers *which* keys, and
                # `_OBJECT_DERIVED_KEYS` answers in what order.
                payloads[object_id] = {
                    key: flow[key] for key in _OBJECT_DERIVED_KEYS if key in keys
                }
            flow = {key: value for key, value in flow.items() if key not in keys}
        rewritten.append(
            row[:_EF_FLOW_JSON]
            + (orjson.dumps(flow).decode("utf-8"),)
            + row[_EF_FLOW_JSON + 1:]
        )

    payload_rows = [
        (object_id, orjson.dumps(body).decode("utf-8"))
        for object_id, body in payloads.items()
    ]
    return rewritten, payload_rows


def merge_object_payload(
    flow: dict[str, Any], payload_json: str | bytes | None
) -> dict[str, Any]:
    """Put an object's shared payload back under one of its flows.

    The flow's own keys win, always.  `_hoist_shared_object_payloads` only
    removes a key when every flow of the object agreed on it, so a key that
    survived on a flow is one that disagreed -- or one a later writer put back,
    which the merge does when it rewrites a payload it has just read.

    Mutating nothing and returning a new dict: callers hand this straight to
    the export, which must not see two flows sharing one label list object.
    """
    if not payload_json:
        return flow
    try:
        shared = orjson.loads(payload_json)
    except orjson.JSONDecodeError:
        return flow
    if not isinstance(shared, dict):
        return flow
    return {**shared, **flow}


def _without_source_refs(flow: dict[str, Any]) -> dict[str, Any]:
    """*flow* without `source_refs`, which no stored payload keeps.

    `elementary_flow_sources` is the single home for a flow's references, and
    the only one the merge maintains: `_sync_existing_flow_source_refs` appends
    a matched flow's new reference to that table and to no payload.  So a
    payload written at build time answers for the base list alone.  On the
    2026-08-07 build that made 7,794 of 94,433 stored `source_refs` short: the
    payload held the base list's single reference where the table held two to
    38.  None was wrong the other way -- no payload held a reference the table
    lacked, and no flow was missing from the table (#30).

    Nothing downstream loses a field.  The one published artifact cannot carry
    it -- `SimpleFlow` has no such attribute, so `_strip_lcia_from_flows` never
    reads one -- and every reader that wants references reads the table.
    """
    return {key: value for key, value in flow.items() if key != "source_refs"}


#: The `ElementaryFlow` record's occurrence-level keys -- what a flow is, as
#: opposed to what substance it is an occurrence of.
#:
#: `source_refs` is not among them: see `_without_source_refs`.  The merge's
#: working set is projected from a stored payload, so a reference carried here
#: would be the pre-merge one.
_OCCURRENCE_KEYS = (
    "elementary_flow_id",
    "flow_object_id",
    "source",
    "context",
    "context_iri",
    "unit",
    "unit_iri",
    "lcia_methods",
    "general_comment",
    "cas_match_labels",
    "concept_associations",
    OWL_DEPRECATED,
    DCTERMS_IS_REPLACED_BY,
    "is_replaced_by_uuid",
)

#: The substance keys the merge's own flows carry on their record as well.
#: `elementary_flow_json` is documented as having exactly one shape and has two:
#: 93,993 base-list flows carry only the keys above, and the 440 the merge
#: created -- 251 `ecoinvent algorithm addition`, 189 `ecoinvent manual
#: addition` -- carry these too.  Reproduced rather than tidied away, because
#: making both shapes one is a change to what the merge reads and belongs with
#: someone who can say which shape is right.
_MERGE_RECORD_SUBSTANCE_KEYS = (
    "name",
    "prefLabel",
    "altLabel",
    "properties",
    "references",
    "cas_numbers",
    "ec_numbers",
    SKOS_DEFINITION_IRI,
)


def elementary_flow_record(flow: dict[str, Any]) -> dict[str, Any]:
    """The `ElementaryFlow` record for a flow, projected from its `Flow` record.

    There were two stored payloads per flow: `flow_json`, which the export and
    the webapps read, and `elementary_flow_json`, which `_load_working_set`
    hands the merge.  Where they carried the same key they carried the same
    bytes -- `lcia_methods`, `source_refs`, `context`, `context_iri`,
    `unit_iri`, `cas_match_labels` and the rest are identical in 94,433 of
    94,433 rows, and no key differs anywhere.  The second was 221.3 MiB of a
    file this series is trying to shrink (#255).

    So one is stored and this projects the other.  Three keys are defaulted
    rather than copied, because the `Flow` record omits them when they are
    empty and the `ElementaryFlow` record spells them out:

    * `elementary_flow_id` falls back to `uuid` -- the same value under the
      other layer's name for it.
    * `general_comment` to `None`.
    * `cas_match_labels` to `{}`.

    And a deprecated flow's record carries no `concept_associations`: 14,602
    flows are deprecated and exactly 14,602 lack the key.

    `source_refs` is projected by neither, because it is stored by neither: the
    references live in `elementary_flow_sources`, which is the copy the merge
    keeps current (#30).  The merge builds its own reference for a flow it
    matches or creates and hands that to the table, so it needs nothing here.

    *flow* must be the whole `Flow` record -- rehydrated with
    `merge_object_payload` if it came from `flow_json`, which no longer holds
    the substance body.  Verified against every row of the 2026-08-07 build:
    94,433 projections identical to the column they replace, none differing.
    """
    keys = _OCCURRENCE_KEYS
    if "name" in flow:
        keys = keys + _MERGE_RECORD_SUBSTANCE_KEYS
    record = {key: flow[key] for key in keys if key in flow}
    record.setdefault("elementary_flow_id", flow.get("uuid"))
    record.setdefault("general_comment", None)
    record.setdefault("cas_match_labels", {})
    if flow.get(OWL_DEPRECATED) is True:
        record.pop("concept_associations", None)
    return record


_FILTER_OPTION_COUNTS_DDL = """
    CREATE TABLE IF NOT EXISTS filter_option_counts (
        option_group TEXT NOT NULL,
        option_key TEXT NOT NULL,
        option_value TEXT NOT NULL,
        item_count INTEGER NOT NULL,
        PRIMARY KEY (option_group, option_key, option_value)
    )
"""


def _fill_filter_option_counts(cur: sqlite3.Cursor) -> None:
    """Rebuild `filter_option_counts` from whatever the database now holds.

    Every option the flows page offers before anything is filtered is read from
    here, counted in flows.  Deriving the same options live costs 198ms against
    the 0.8ms this table costs to read -- ten `GROUP BY`s over 94,429 rows, of
    which the `flow_type` join alone is 103ms -- so the precomputation earns its
    keep on the page a reader opens first.

    What did not earn its keep was *where* it happened.  These were three inline
    blocks in the middle of the transform's writer, run once against the base
    list and never again, so the 436 flows the ecoinvent merge adds afterwards
    were in the database, in the export and in no filter: two source labels that
    selected 247 and 189 flows were not offered at all, and `EUR` was a unit the
    dropdown had never heard of (#248).  One idempotent function instead, run by
    the writer and again by `build` once every stage has written.

    Deletes first, so a second run replaces the previous answer rather than
    colliding with it on the primary key.  The caller commits.
    """
    cur.execute(_FILTER_OPTION_COUNTS_DDL)
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_filter_option_counts_group_key "
        "ON filter_option_counts(option_group, option_key)"
    )
    cur.execute("DELETE FROM filter_option_counts")

    def store(group: str, key: str, rows: list[sqlite3.Row]) -> None:
        for row in rows:
            value = row["option_value"]
            if not isinstance(value, str) or not value.strip():
                continue
            cur.execute(
                """
                INSERT INTO filter_option_counts (
                    option_group, option_key, option_value, item_count
                ) VALUES (?, ?, ?, ?)
                """,
                (group, key, value, int(row["n"] or 0)),
            )

    for column in ("source", "unit"):
        store(
            column,
            "",
            cur.execute(
                f"""
                SELECT {column} AS option_value, COUNT(*) AS n
                FROM elementary_flows
                WHERE coalesce({column}, '') <> ''
                GROUP BY {column}
                """
            ).fetchall(),
        )

    # The two substance-layer facets, counted in *flows* like every other
    # option on that page.  Grouping `flow_objects` directly would be
    # cheaper and would count substances, which is what the page used to
    # offer: `biogenic (4)` above a result of 28.
    for facet_column in ("flow_type", "origin_qualifier"):
        store(
            "type" if facet_column == "flow_type" else "qualifier",
            "",
            cur.execute(
                f"""
                SELECT fo.{facet_column} AS option_value, COUNT(*) AS n
                FROM elementary_flows ef
                JOIN flow_objects fo ON fo.flow_object_id = ef.flow_object_id
                WHERE coalesce(fo.{facet_column}, '') <> ''
                GROUP BY fo.{facet_column}
                """
            ).fetchall(),
        )

    # Every context axis the model declares, so a new one is a filter without
    # a second list to remember: `CONTEXT_FIELDS` is where the axes live.
    for context_key in CONTEXT_FIELDS:
        store(
            "context",
            context_key,
            cur.execute(
                f"""
                SELECT context_{context_key} AS option_value, COUNT(*) AS n
                FROM elementary_flows
                WHERE coalesce(context_{context_key}, '') <> ''
                GROUP BY context_{context_key}
                """
            ).fetchall(),
        )


def check_filter_option_counts(db_path: Path = CONSENSUS_DB_FILEPATH) -> None:
    """Fail if the published facets do not describe the published flows.

    One equality, over the one facet every flow has a value for: the source
    options must add up to `elementary_flows`.  It says nothing about the writer,
    which satisfies it by construction -- it is a check on the *ordering*, which
    is what broke.  A stage that adds flows after the facets are computed fails
    here rather than shipping a landing page that cannot select them, which is
    the guard the ecoinvent merge went without for as long as it existed (#248).
    """
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        facet_total = conn.execute(
            "SELECT coalesce(sum(item_count), 0) FROM filter_option_counts "
            "WHERE option_group = 'source'"
        ).fetchone()[0]
        flow_total = conn.execute("SELECT count(*) FROM elementary_flows").fetchone()[0]
    finally:
        conn.close()
    if facet_total != flow_total:
        raise ValueError(
            "filter_option_counts is stale: the source facet totals "
            f"{facet_total:,} against {flow_total:,} elementary flows. "
            "Something wrote flows after the facets were computed; recompute "
            "them with `recompute_filter_option_counts` once it has finished."
        )


def check_context_iris_are_written(db_path: Path = CONSENSUS_DB_FILEPATH) -> None:
    """Fail if any flow has a printed context and no address for it.

    `context_display` and `context_iri` are written from one context object, so
    there is no state in which only one of them is known.  The merge's writer
    filled the name and the seven axis columns and left the address empty, on
    all 1,200 flows ecoinvent and BAFU brought in -- and an empty string
    compares equal to an empty string, so those flows shared a context with each
    other and with nothing else (#295).

    Nothing was published wrong: the export reads `flow_json`, which had the
    address all along.  This guards the database that the collision check,
    the duplicate check and the review app's context filter query.
    """
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        missing = conn.execute(
            "SELECT count(*) FROM elementary_flows "
            "WHERE coalesce(context_display, '') <> '' "
            "AND coalesce(context_iri, '') = ''"
        ).fetchone()[0]
        sources = conn.execute(
            "SELECT source, count(*) AS n FROM elementary_flows "
            "WHERE coalesce(context_display, '') <> '' "
            "AND coalesce(context_iri, '') = '' "
            "GROUP BY source ORDER BY n DESC LIMIT 5"
        ).fetchall()
    finally:
        conn.close()
    if missing:
        named = ", ".join(f"{source or '(no source)'}: {n:,}" for source, n in sources)
        raise ValueError(
            f"{missing:,} elementary flows carry a context_display and no "
            f"context_iri ({named}). The two are written from one context "
            "object; a writer that fills the rendering must fill the identity."
        )


def recompute_filter_option_counts(db_path: Path = CONSENSUS_DB_FILEPATH) -> None:
    """Rebuild the filter facets against the finished database, and check them.

    Called by `build` after the merge, because the merge adds flows and the
    transform's copy of these counts describes only the base list.
    """
    _t0 = time.monotonic()
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        _fill_filter_option_counts(conn.cursor())
        conn.commit()
    finally:
        conn.close()
    check_filter_option_counts(db_path)
    logger.info(
        "filter_option_counts.recomputed",
        path=str(db_path),
        ms=round((time.monotonic() - _t0) * 1000),
    )


def recompute_match_strengths(db_path: Path = CONSENSUS_DB_FILEPATH) -> Counter:
    """Settle how strong every stored mapping is, against the whole database.

    Called by the merge after it has written its flows, because the strength of
    a mapping is not a property of the row that made it: `skos:exactMatch`
    chains, so two of one list's flows landing on one consensus flow assert that
    those two source flows are each other.  The merge decides one row at a time
    and cannot see the second one coming, and `merge/state.py` folds a stored
    association back in unchanged -- so a strength written by an earlier run
    survives until something recounts.  This is that something (#76).

    Over the database rather than the merge's own records, for the same reason:
    the flows a previous run wrote carry mappings this run never touched, and
    they are published all the same.

    Two passes, because the answer for any one mapping depends on mappings on
    other flows entirely.  The first reads only the `concept_associations` of
    each row -- `json_extract` in SQLite, so the multi-gigabyte payloads around
    them stay in the database -- and the second rewrites the few rows whose
    claims were too strong.
    """
    _t0 = time.monotonic()
    conn = sqlite3.connect(db_path)
    counts: Counter = Counter()
    try:
        by_uuid: dict[str, list[dict[str, Any]]] = {}
        for uuid, fragment in conn.execute(
            "SELECT uuid, json_extract(flow_json, '$.concept_associations') "
            "FROM elementary_flows WHERE flow_json IS NOT NULL"
        ):
            if not fragment:
                continue
            associations = orjson.loads(fragment)
            if isinstance(associations, list) and associations:
                by_uuid[str(uuid)] = associations

        cardinality = cardinality_of(by_uuid.values())
        rewritten = 0
        for uuid, associations in by_uuid.items():
            changed = weaken(associations, cardinality)
            counts.update(changed)
            if not any(key.startswith("weakened_") for key in changed):
                continue
            row = conn.execute(
                "SELECT flow_json FROM elementary_flows WHERE uuid = ?", (uuid,)
            ).fetchone()
            if row is None or not row[0]:
                continue
            payload = orjson.loads(row[0])
            if not isinstance(payload, dict):
                continue
            payload["concept_associations"] = associations
            conn.execute(
                "UPDATE elementary_flows SET flow_json = ? WHERE uuid = ?",
                (orjson.dumps(payload).decode("utf-8"), uuid),
            )
            rewritten += 1
        conn.commit()
    finally:
        conn.close()
    logger.info(
        "match_strengths.recomputed",
        path=str(db_path),
        flows_with_associations=len(by_uuid),
        flows_rewritten=rewritten,
        ms=round((time.monotonic() - _t0) * 1000),
        **dict(counts),
    )
    return counts


#: The columns each `INSERT` below fills, in the order the row tuples are built.
#:
#: Declared once and turned into the statement by `insert_statement`, rather
#: than restated inside it: a hand-written column list is a second copy of the
#: `CREATE TABLE` above, and the two disagree in silence -- the row is written
#: with the forgotten column left at its default.
#: `tests/test_sqlite_columns.py` fails if a list here and the table it names
#: part company.
#:
#: `elementary_flow_sources.id` is the one column no list mentions: SQLite
#: fills it.
_FLOW_OBJECT_COLUMNS = (
    "flow_object_id", "pref_label_value", "pref_label_json", "alt_label_json",
    "classifications_json", "properties_json", "references_json",
    "flow_object_json", "origin_qualifier", "parent_flow_object_id",
    "parent_intervention_id", "flow_type",
)
_FLOW_OBJECT_FTS_COLUMNS = (
    "flow_object_id", "pref_label", "alt_labels", "cas_numbers", "ec_numbers",
)
_FLOW_OBJECT_PAYLOAD_COLUMNS = ("flow_object_id", "payload_json")
_ELEMENTARY_FLOW_COLUMNS = (
    "uuid", "flow_object_id", "pref_label_value", "source", "unit",
    "lcia_factor_count", "is_deprecated", "replaced_by_uuid", "context_display",
    "context_iri", "context_json", "context_dimension", "context_media",
    "context_strata", "context_indoor", "context_population_density",
    "context_geography", "context_water_body", "context_land_use",
    "consensus_change_count", "flow_json",
)
_ELEMENTARY_FLOW_FTS_COLUMNS = (
    "uuid", "flow_object_id", "name", "source", "unit", "context_display",
    "cas_numbers", "alt_labels",
)
_ELEMENTARY_FLOW_SOURCE_COLUMNS = (
    "elementary_flow_uuid", "list_name", "list_version", "source_flow_uuid",
    "source_flow_name", "source_metadata_json",
)

#: Position of the flow payload in an `elementary_flows` row tuple, and of the
#: flow object id it is grouped by.  Named because the tuple is built in one
#: place and rewritten in another.
#:
#: Read off the column list rather than written down: they were literals, and a
#: column added in the middle moved them silently -- `context_iri` did, and the
#: payload position then pointed at an integer (#284).
_EF_FLOW_OBJECT_ID = _ELEMENTARY_FLOW_COLUMNS.index("flow_object_id")
_EF_FLOW_JSON = _ELEMENTARY_FLOW_COLUMNS.index("flow_json")

#: The relations this writer owns, dropped and recreated on every build.
#:
#: One of them is a view and the rest are tables; `recreate` reads which from
#: the database rather than being told, so this is one list and not two.
_RELATIONS = (
    "consensus_flows",
    "flow_objects",
    "flow_objects_fts",
    "elementary_flows",
    "elementary_flows_fts",
    "elementary_flow_sources",
    "flow_object_payloads",
    # On the list like the rest.  It was the one table this writer created
    # without dropping first, so writing twice into one file raised "table
    # already exists" -- invisible in a build, which deletes the database before
    # it starts, and immediate for anything that writes a fixture.
    "filter_option_counts",
    # Still dropped, though nothing creates it any more: a database written by
    # an earlier version has the table, and a rebuild in place would otherwise
    # leave 0.83 GiB of orphaned rows behind.
    "consensus_changes",
)

#: In creation order, which matters once: `consensus_flows` is a view over two
#: of the tables above it.  No `CREATE INDEX` among them -- the indices are
#: built after the inserts, so that a bulk load does not pay per-row index
#: maintenance.
_SCHEMA = (
    """
    CREATE TABLE flow_objects (
        flow_object_id TEXT PRIMARY KEY,
        pref_label_value TEXT,
        pref_label_json TEXT,
        alt_label_json TEXT,
        classifications_json TEXT,
        properties_json TEXT,
        references_json TEXT,
        flow_object_json TEXT,
        origin_qualifier TEXT,
        parent_flow_object_id TEXT,
        parent_intervention_id TEXT,
        flow_type TEXT NOT NULL DEFAULT 'unclassified'
    )
    """,
    """
    CREATE VIRTUAL TABLE flow_objects_fts USING fts5(
        flow_object_id,
        pref_label,
        alt_labels,
        cas_numbers,
        ec_numbers
    )
    """,
    """
    CREATE VIRTUAL TABLE elementary_flows_fts USING fts5(
        uuid,
        flow_object_id,
        name,
        source,
        unit,
        context_display,
        cas_numbers,
        alt_labels
    )
    """,
    """
    CREATE TABLE elementary_flows (
        uuid TEXT PRIMARY KEY,
        flow_object_id TEXT NOT NULL,
        pref_label_value TEXT NOT NULL DEFAULT '',
        source TEXT,
        unit TEXT,
        lcia_factor_count INTEGER NOT NULL DEFAULT 0,
        is_deprecated INTEGER NOT NULL DEFAULT 0,
        replaced_by_uuid TEXT,
        context_display TEXT,
        -- The context's identity, beside its rendering and its parts.
        -- Every other facet had a column and this one did not, so a
        -- query needing "the same context" had to reach for the printed
        -- name -- which is a rendering, and two contexts can share one
        -- (#284).
        context_iri TEXT NOT NULL DEFAULT '',
        context_json TEXT,
        context_dimension TEXT,
        context_media TEXT,
        context_strata TEXT,
        context_indoor TEXT,
        context_population_density TEXT,
        context_geography TEXT,
        context_water_body TEXT,
        context_land_use TEXT,
        consensus_change_count INTEGER,
        -- One payload, one shape: the denormalised harmonised flow the
        -- published export and the webapps project from, minus the
        -- substance body, which `flow_object_payloads` holds once per
        -- object.
        --
        -- There was a second, `elementary_flow_json`, holding the
        -- `ElementaryFlow` record the merge reads.  It said nothing
        -- this column did not: every key the two shared was byte
        -- identical in all 94,433 rows and none differed anywhere, for
        -- 221.3 MiB (#255).  `elementary_flow_record` projects it.
        flow_json TEXT
    )
    """,
    """
    CREATE TABLE elementary_flow_sources (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        elementary_flow_uuid TEXT NOT NULL,
        list_name TEXT,
        list_version TEXT,
        source_flow_uuid TEXT,
        source_flow_name TEXT,
        source_metadata_json TEXT,
        -- A row is the link between one elementary flow and one source
        -- flow, so the link is the key.  Without this the merge's
        -- `INSERT OR IGNORE` had no conflict to detect and wrote a
        -- second copy of every reference the transform had already
        -- written -- 197,836 rows for 103,843 links (#23).
        UNIQUE (elementary_flow_uuid, list_name, list_version, source_flow_uuid)
    )
    """,
    # Compatibility view for any old tooling still querying consensus_flows.
    """
    CREATE VIEW consensus_flows AS
    SELECT
        ef.uuid AS uuid,
        fo.pref_label_value AS name,
        ef.source AS source,
        ef.unit AS unit,
        ef.lcia_factor_count AS lcia_factor_count,
        ef.is_deprecated AS is_deprecated,
        ef.replaced_by_uuid AS replaced_by_uuid,
        ef.context_display AS context_display,
        ef.context_json AS context_json,
        ef.context_dimension AS context_major,
        ef.context_media AS context_environment,
        '' AS context_resource,
        ef.context_land_use AS context_land_use,
        ef.context_geography AS context_urbanity,
        ef.context_strata AS context_vertical,
        ef.context_population_density AS context_high_pop_density,
        ef.context_indoor AS context_indoor,
        ef.context_water_body AS context_water_location,
        '' AS context_water_usage,
        ef.consensus_change_count AS consensus_change_count,
        fo.pref_label_value AS pref_label_value,
        json_array_length(fo.alt_label_json) AS alt_label_count,
        fo.classifications_json AS classifications_json,
        ef.flow_json AS flow_json,
        fo.properties_json AS properties_json
    FROM elementary_flows ef
    LEFT JOIN flow_objects fo ON fo.flow_object_id = ef.flow_object_id
    """,
    # One row per flow object, holding the keys every one of its flows
    # agreed on, in the shape the flows use.  See
    # `_hoist_shared_object_payloads`.
    """
    CREATE TABLE flow_object_payloads (
        flow_object_id TEXT PRIMARY KEY,
        payload_json TEXT NOT NULL
    )
    """,
    _FILTER_OPTION_COUNTS_DDL,
)


def _write_consensus_sqlite(
    flows: list[Flow],
    changelog: list[ChangeEvent],
    flow_objects: list[FlowObject],
    elementary_flows: list[ElementaryFlow],
    db_path: Path | None = None,
) -> None:
    """Write normalized consensus tables for webapp performance.

    There was a `consensus_changes` table here: the `consensus_match` slice of
    the change log, kept for one release so the old consensus webapp kept
    working while the consolidated app was built on `changelog`.  That release
    has been and gone.  Every one of its 200,484 rows duplicated
    `changelog WHERE transformer = 'consensus_match'` exactly -- on `uuid`,
    `field`, both value payloads and `comment` -- differing only in renumbering
    `change_index` from 1 rather than carrying the log's own index.  Nothing
    read it: the consolidated app reads `changelog`, which is keyed by substance
    as well as by flow and so answers both questions without a join.  It was
    0.83 GiB of the 8.13 GiB output (#253).

    The `consensus_match` slice is still computed, because
    `elementary_flows.consensus_change_count` is a per-flow count of it.  That
    is a count, not a copy.
    """
    consensus_changes = [
        change for change in changelog if change.transformer == "consensus_match"
    ]
    counts: dict[str, int] = {}
    for change in consensus_changes:
        counts[change.uuid] = counts.get(change.uuid, 0) + 1

    # The boundary is this line, not the caller's.  Everything above works in
    # records; this function serialises whole records -- into columns, into
    # `flow_json`, into the FTS text -- so it converts them itself rather than
    # taking three parallel lists of dictionaries the caller built only to hand
    # over (#96).
    #
    # `changelog` stays records because nothing here serialises a change: the
    # only thing this database keeps of the log is `consensus_change_count`,
    # counted above.
    flow_payloads = [flow.to_dict() for flow in flows]
    flow_object_payloads = [obj.to_dict() for obj in flow_objects]
    layered_payloads = [row.to_dict() for row in elementary_flows]

    _t0 = time.monotonic()

    # The only writer of this database that could not be pointed at a temp copy,
    # while `write_review_tables` and `write_source_outcomes` both take a path
    # (#92).  Resolved here rather than as a default argument, so patching the
    # module constant keeps working.
    db_path = CONSENSUS_DB_FILEPATH if db_path is None else db_path
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        cur = conn.cursor()
        # WAL mode + relaxed sync dramatically reduce fsync overhead on macOS.
        cur.execute("PRAGMA journal_mode = WAL")
        cur.execute("PRAGMA synchronous = NORMAL")
        cur.execute("PRAGMA cache_size = -65536")  # 64 MB page cache
        recreate(conn, relations=_RELATIONS, schema=_SCHEMA)

        # No `isinstance(..., dict)` guard here any more: these payloads were
        # built by `to_dict()` twenty lines up, so a guard against a record
        # reaching them guards against nothing.  `flow_by_uuid` went with them
        # -- it was read once, to look up the flow the loop already held.
        layered_by_uuid = {
            row["elementary_flow_id"]: row for row in layered_payloads
        }

        object_search_terms: dict[str, dict[str, str]] = {}
        fo_rows: list[tuple] = []
        fo_fts_rows: list[tuple] = []
        for row in flow_object_payloads:
            classifications = row.get("classifications", {}) if isinstance(row.get("classifications"), dict) else {}
            cas_numbers = (
                classifications.get(CHEMINF_CAS_REGISTRY_NUMBER, {}).get("@value", [])
                if isinstance(classifications.get(CHEMINF_CAS_REGISTRY_NUMBER), dict)
                else []
            )
            ec_numbers = (
                classifications.get(CHEMINF_EC_NUMBER, {}).get("@value", [])
                if isinstance(classifications.get(CHEMINF_EC_NUMBER), dict)
                else []
            )
            cas_text = " ".join(str(x) for x in cas_numbers if isinstance(x, str) and x.strip())
            ec_text = " ".join(str(x) for x in ec_numbers if isinstance(x, str) and x.strip())
            alt_values = [x.value for x in coerce_alt_labels(row.get("altLabel"))]
            alt_text = " ".join(v for v in alt_values if isinstance(v, str) and v.strip())
            pref_value = flow_label_value(row) or ""
            flow_object_id = str(row.get("flow_object_id") or "")
            origin_qualifier = row.get("origin_qualifier") or None
            parent_flow_object_id = row.get("parent_flow_object_id") or None
            parent_intervention_id = row.get("parent_intervention_id") or None
            flow_type = _compute_flow_type(row)
            fo_rows.append((
                flow_object_id,
                pref_value,
                orjson.dumps(row.get("prefLabel", [])).decode("utf-8"),
                orjson.dumps(row.get("altLabel", [])).decode("utf-8"),
                orjson.dumps(row.get("classifications", {})).decode("utf-8"),
                orjson.dumps(row.get("properties", {})).decode("utf-8"),
                orjson.dumps(row.get("references", [])).decode("utf-8"),
                orjson.dumps(row).decode("utf-8"),
                origin_qualifier,
                parent_flow_object_id,
                parent_intervention_id,
                flow_type,
            ))
            fo_fts_rows.append((flow_object_id, pref_value, alt_text, cas_text, ec_text))
            object_search_terms[flow_object_id] = {
                "name": pref_value,
                "alt_labels": alt_text,
                "cas_numbers": cas_text,
            }
        cur.executemany(
            insert_statement("flow_objects", _FLOW_OBJECT_COLUMNS), fo_rows
        )
        cur.executemany(
            insert_statement("flow_objects_fts", _FLOW_OBJECT_FTS_COLUMNS),
            fo_fts_rows,
        )
        _t_fo = time.monotonic()

        ef_rows: list[tuple] = []
        ef_fts_rows: list[tuple] = []
        efs_rows: list[tuple] = []
        for flow in flow_payloads:
            uuid = flow["uuid"]
            count = counts.get(uuid, 0)
            context_value = flow.get("context")
            context_parts = context_display_parts(context_value)
            if not context_parts:
                context_parts = context_display_parts(flow.get("elementary_flow_categorization"))
            attrs = context_attributes(context_value)
            layered = layered_by_uuid.get(uuid, {})
            flow_object_id = (
                layered.get("flow_object_id")
                or flow.get("flow_object_id")
                or ""
            )
            context_display = " → ".join(context_parts) if context_parts else "(none)"
            search_terms = object_search_terms.get(flow_object_id, {})
            unit_val = layered.get("unit") or flow.get("unit") or ""
            ef_rows.append((
                uuid,
                flow_object_id,
                search_terms.get("name", ""),
                flow.get("source") or "",
                unit_val,
                non_zero_factor_count_of_entries(
                    layered.get("lcia_methods", flow.get("lcia_methods"))
                ),
                1 if flow.get(OWL_DEPRECATED) is True else 0,
                str(flow.get("is_replaced_by_uuid") or ""),
                context_display,
                str(layered.get("context_iri") or flow.get("context_iri") or ""),
                orjson.dumps(context_value).decode("utf-8") if context_value is not None else "null",
                attrs.get("dimension", ""),
                attrs.get("media", ""),
                attrs.get("strata", ""),
                attrs.get("indoor", ""),
                attrs.get("population_density", ""),
                attrs.get("geography", ""),
                attrs.get("water_body", ""),
                attrs.get("land_use", ""),
                count,
                # The dict, not its JSON: `_hoist_shared_object_payloads` runs
                # over the whole list below and needs to compare flows of one
                # object before any of them is serialised.
                #
                # A copy without `source_refs`, and a copy because *flow* is the
                # harmonised record other writers in this loop still read.  The
                # references go to `elementary_flow_sources` below, out of
                # `layered`, and that table is the only home that stays current:
                # the merge appends to it and to no payload, so a stored
                # `source_refs` is the pre-merge answer and was short on 7,794
                # of 94,433 flows (#30).
                _without_source_refs(flow),
            ))
            ef_fts_rows.append((
                uuid,
                flow_object_id,
                search_terms.get("name", ""),
                flow.get("source") or "",
                unit_val,
                context_display,
                search_terms.get("cas_numbers", ""),
                search_terms.get("alt_labels", ""),
            ))

            refs = layered.get("source_refs", [])
            if not isinstance(refs, list):
                refs = []
            for ref in refs:
                if not isinstance(ref, dict):
                    continue
                efs_rows.append((
                    uuid,
                    ref.get("list_name") or "",
                    ref.get("list_version") or "",
                    ref.get("source_flow_uuid") or "",
                    ref.get("source_flow_name") or "",
                    orjson.dumps(ref.get("source_metadata", {})).decode("utf-8"),
                ))

        ef_rows, payload_rows = _hoist_shared_object_payloads(ef_rows)
        cur.executemany(
            insert_statement("flow_object_payloads", _FLOW_OBJECT_PAYLOAD_COLUMNS),
            payload_rows,
        )
        cur.executemany(
            insert_statement("elementary_flows", _ELEMENTARY_FLOW_COLUMNS), ef_rows
        )
        cur.executemany(
            insert_statement("elementary_flows_fts", _ELEMENTARY_FLOW_FTS_COLUMNS),
            ef_fts_rows,
        )
        cur.executemany(
            insert_statement(
                "elementary_flow_sources", _ELEMENTARY_FLOW_SOURCE_COLUMNS
            ),
            efs_rows,
        )
        _t_ef = time.monotonic()

        # The same facets `build` recomputes after the merge, written here
        # too so a database is never without them.  One definition:
        # `_fill_filter_option_counts` is idempotent and re-derives them
        # from the tables above, which are, at this point, the base list.
        _fill_filter_option_counts(cur)

        _t_facets = time.monotonic()

        # Build all indices after all inserts to avoid per-row index maintenance.
        cur.execute("CREATE INDEX idx_flow_objects_pref_label_value ON flow_objects(lower(pref_label_value))")
        cur.execute("CREATE INDEX idx_flow_objects_flow_object_id ON flow_objects(lower(flow_object_id))")
        # Covering, and that is the whole point.  `flow_type` and
        # `origin_qualifier` are declared *after* `flow_object_json`, so reading
        # either one off a row means stepping over a multi-kilobyte JSON blob --
        # and the filtered flows page groups 94,429 joined rows by one of them.
        # Held in an index the query never leaves, that GROUP BY goes from 663ms
        # to 121ms; the index costs 0.5 MB.  Measured on the full build.
        cur.execute(
            "CREATE INDEX idx_flow_objects_facets "
            "ON flow_objects(flow_object_id, flow_type, origin_qualifier)"
        )
        cur.execute("CREATE INDEX idx_elementary_flows_deprecated_name ON elementary_flows(is_deprecated, lower(pref_label_value))")
        cur.execute("CREATE INDEX idx_elementary_flows_source ON elementary_flows(source)")
        cur.execute("CREATE INDEX idx_elementary_flows_unit ON elementary_flows(unit)")
        cur.execute("CREATE INDEX idx_elementary_flows_object_id ON elementary_flows(flow_object_id)")
        cur.execute("CREATE INDEX idx_elementary_flows_lcia_count ON elementary_flows(lcia_factor_count)")
        cur.execute("CREATE INDEX idx_elementary_flows_deprecated ON elementary_flows(is_deprecated)")
        cur.execute("CREATE INDEX idx_elementary_flows_context_dimension ON elementary_flows(context_dimension)")
        # "Which flows share a substance and a context" is the duplicate check,
        # and it groups on this pair.
        cur.execute(
            "CREATE INDEX idx_elementary_flows_object_context "
            "ON elementary_flows(flow_object_id, context_iri)"
        )
        cur.execute("CREATE INDEX idx_elementary_flows_context_media ON elementary_flows(context_media)")
        cur.execute("CREATE INDEX idx_elementary_flows_context_strata ON elementary_flows(context_strata)")
        cur.execute("CREATE INDEX idx_elementary_flows_context_indoor ON elementary_flows(context_indoor)")
        cur.execute("CREATE INDEX idx_elementary_flows_context_population_density ON elementary_flows(context_population_density)")
        cur.execute("CREATE INDEX idx_elementary_flows_context_geography ON elementary_flows(context_geography)")
        cur.execute("CREATE INDEX idx_elementary_flows_context_water_body ON elementary_flows(context_water_body)")
        cur.execute("CREATE INDEX idx_elementary_flows_context_land_use ON elementary_flows(context_land_use)")
        # `idx_filter_option_counts_group_key` is created by
        # `_fill_filter_option_counts`, which owns that table start to finish.
        #
        # No index for `elementary_flow_sources`: the UNIQUE constraint above
        # leads with `elementary_flow_uuid`, which is the app's only lookup
        # (`webapps/app/queries/flows.py`), so a second index on the same
        # column would be maintained for nothing.
        conn.commit()
        _t_end = time.monotonic()
        logger.info(
            "write_consensus_sqlite.timing",
            ms_flow_objects=round((_t_fo - _t0) * 1000),
            ms_elementary_flows=round((_t_ef - _t_fo) * 1000),
            ms_facets=round((_t_facets - _t_ef) * 1000),
            ms_indexes=round((_t_end - _t_facets) * 1000),
            ms_total=round((_t_end - _t0) * 1000),
            n_flow_objects=len(fo_rows),
            n_elementary_flows=len(ef_rows),
            n_sources=len(efs_rows),
            # The `consensus_match` changes counted into
            # `consensus_change_count`, not rows written -- this function no
            # longer writes a change table.
            n_consensus_match_changes=len(consensus_changes),
        )
    finally:
        conn.close()


def read_published_flow_payloads(db_path: Path) -> list[dict[str, Any]]:
    """The flow payloads behind ``harmonised-flows-simple.json.gz``, in order.

    Read from `elementary_flows.flow_json` rather than from a JSON file, so the
    one published artifact depends on the database and nothing else.  Ordered by
    rowid, which is insertion order, because the export preserves flow order.

    These stay dicts: a SQLite row is an external payload, parsed where it is
    read.  The column does hold one record type -- every row is `Flow`-shaped
    and carries a `uuid`, including the 196 of 596 the merge created, which
    `_as_harmonised` routes through `Flow` for exactly that reason.  That is
    what lets the merge read the consensus back as records and show it to the
    transformers alongside each source list (#213).

    Joined to `flow_object_payloads`, which holds the substance-level keys the
    flows of one object agreed on -- `flow_json` stopped carrying a copy each
    when that came to 1.57 GiB of an 8.13 GiB file (#253).  The join is a
    `LEFT JOIN` because an object whose flows disagreed has no payload row, and
    `merge_object_payload` lets the flow's own keys win, so the reconstructed
    dict is what the column used to hold either way.

    `ORDER BY ef.rowid` survives the join, and has to: the export preserves flow
    order, and a join does not guarantee it.
    """
    connection = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        if not _table_exists(connection, "flow_object_payloads"):
            # A database written before the payloads were hoisted still has
            # whole flows, and reads back unchanged.
            return [
                orjson.loads(row[0])
                for row in connection.execute(
                    "SELECT flow_json FROM elementary_flows "
                    "WHERE flow_json IS NOT NULL ORDER BY rowid"
                )
            ]
        return [
            merge_object_payload(orjson.loads(row[0]), row[1])
            for row in connection.execute(
                "SELECT ef.flow_json, p.payload_json FROM elementary_flows ef "
                "LEFT JOIN flow_object_payloads p "
                "ON p.flow_object_id = ef.flow_object_id "
                "WHERE ef.flow_json IS NOT NULL ORDER BY ef.rowid"
            )
        ]
    finally:
        connection.close()


def read_source_contexts(
    db_path: Path,
) -> dict[str, dict[str, frozenset[tuple[str, ...]]]]:
    """Each flow's source-list contexts, as they were *before* mapping.

    Keyed by elementary flow UUID, then by source list -- `"EF 3.1"`,
    `"ecoinvent 3.12"` -- with the set of ``original_context`` paths that list's
    rows carried as the value, one tuple per distinct path.

    Kept per list rather than pooled into one set per flow, because pooling is
    what made all 46 of the 2026-08-12 build's context collapses spurious
    (#59): a survivor attested by a second list has a context the deprecated
    flow's set does not, and pooled that is indistinguishable from a survivor
    whose identity moved.  `pipeline/redirects.py` compares the lists both
    flows are in and ignores the rest.

    Keyed by list *and* version, so a context one list renamed between two
    releases becomes two keys rather than two paths under one.  A key only one
    flow has is no evidence and leaves the pair `unclassified`, which a consumer
    refuses; the two spellings pooled under one key would instead read as a
    distinction that list never drew.

    Read from `elementary_flow_sources` rather than from the payload, because
    since #30 the payload does not carry `source_refs` at all -- and before
    that it carried a copy that was short on 7,794 of 94,433 flows.  Short is
    the dangerous direction here: a survivor missing one of its contexts makes a
    context collapse look like a merge of a flow with itself, which is exactly
    the redirect a consumer would then follow when it should refuse.

    Returns an empty mapping when the table is absent, as it is in a database
    written by a bounded run.  The caller publishes `unclassified` for every
    redirect in that case, which is what is actually known.
    """
    connection = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        if not _table_exists(connection, "elementary_flow_sources"):
            logger.warning("source_contexts_table_missing", path=str(db_path))
            return {}
        out: dict[str, dict[str, set[tuple[str, ...]]]] = {}
        for flow_uuid, list_name, list_version, metadata_json in connection.execute(
            "SELECT elementary_flow_uuid, list_name, list_version, "
            "source_metadata_json "
            "FROM elementary_flow_sources WHERE source_metadata_json IS NOT NULL"
        ):
            metadata = orjson.loads(metadata_json)
            if not isinstance(metadata, dict):
                continue
            context = metadata.get("original_context")
            if isinstance(context, list) and context:
                source_list = " ".join(
                    part for part in (list_name, list_version) if part
                )
                out.setdefault(flow_uuid, {}).setdefault(source_list, set()).add(
                    tuple(str(part) for part in context)
                )
        return {
            flow_uuid: {
                source_list: frozenset(paths)
                for source_list, paths in by_list.items()
            }
            for flow_uuid, by_list in out.items()
        }
    finally:
        connection.close()


def _table_exists(connection: sqlite3.Connection, name: str) -> bool:
    return (
        connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (name,)
        ).fetchone()
        is not None
    )
