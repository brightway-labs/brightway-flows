"""Propagating merge results into the artifacts the review application reads.

The merge runs after the main transform, so the elementary-flow file and the
SQLite database already exist. These functions update them in place rather than
rebuilding, which keeps the merge independent of the transform.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

import orjson
import structlog

from brightway_flows.domain.context_registry import (
    context_display_parts,
    context_to_dict,
)
from brightway_flows.domain.elementary_flow import ElementaryFlow
from brightway_flows.domain.labels import coerce_alt_labels, flow_label_value
from brightway_flows.domain.flow import Flow
from brightway_flows.domain.flow_object import FlowObject
from brightway_flows.domain.vocabulary import (
    CHEMINF_CAS_REGISTRY_NUMBER,
    CHEMINF_EC_NUMBER,
)
from brightway_flows.filesystem import (
    CONSENSUS_DB_FILEPATH,
)
from brightway_flows.merge.state import (
    MergeAccumulator,
    MergeIndexes,
    _association_key,
    _extend_unique,
)
from brightway_flows.pipeline.sqlite import (
    _compute_flow_type,
    _without_source_refs,
)

logger = structlog.get_logger(__name__)


def _as_harmonised(
    flow: ElementaryFlow, types_by_object_id: dict[str, list[str]] | None = None
) -> dict[str, Any]:
    """An elementary-flow record as the harmonised flow the export projects from.

    The two differ in how the flow is identified: a harmonised flow carries
    `uuid` and `identifier`, an elementary flow carries `elementary_flow_id`.
    Routing through `Flow` gives a merge-created row the same field set as every
    other row in the column, instead of an elementary flow's -- and it is what
    makes the working list's key order a matter of no consequence downstream:
    whatever order the elementary record serialises in, `Flow.to_dict()` writes
    this column in `Flow`'s (#93).

    `@type` is copied from the flow object here for the same reason the transform
    engine copies it: identity is a property of the substance, and a merge-created
    flow points at a flow object that already has one.  Without this the merge's
    rows publish untyped -- 196 of 596 in a bounded run, a third of the export.
    """
    harmonised = Flow.from_dict(
        {**flow.to_dict(), "uuid": flow.elementary_flow_id}
    ).to_dict()
    object_types = (types_by_object_id or {}).get(flow.flow_object_id)
    if object_types:
        harmonised["@type"] = list(object_types)
    # `source_refs` is not stored on a payload -- the row's references go to
    # `elementary_flow_sources`, the copy the merge keeps current (#30).  A
    # created flow would otherwise be written with the reference it was minted
    # from and never gain the ones a later pass matches to it.
    return _without_source_refs(harmonised)


def _flow_object_types(
    cursor: sqlite3.Cursor, flow_object_ids: set[str]
) -> dict[str, list[str]]:
    """The `@type` of each named flow object, read from the database.

    Read here rather than threaded through the merge: the flow objects were
    written by the transform run that preceded this merge, and the database is
    where they are.  A row whose object is missing or untyped is simply absent.
    """
    types: dict[str, list[str]] = {}
    identifiers = sorted(x for x in flow_object_ids if x)
    if not identifiers:
        return types
    for start in range(0, len(identifiers), 500):
        chunk = identifiers[start:start + 500]
        placeholders = ",".join("?" * len(chunk))
        for object_id, blob in cursor.execute(
            "SELECT flow_object_id, flow_object_json FROM flow_objects "
            f"WHERE flow_object_id IN ({placeholders})",
            chunk,
        ):
            raw = (orjson.loads(blob) if blob else {}).get("@type")
            if isinstance(raw, str):
                raw = [raw]
            if isinstance(raw, list):
                values = [
                    str(x) for x in raw if isinstance(x, str) and x.strip()
                ]
                if values:
                    types[str(object_id)] = values
    return types


def _classification_text(classifications: dict[str, Any], predicate: str) -> str:
    """A flow object's values for one classification predicate, as FTS text."""
    entry = classifications.get(predicate)
    values = entry.get("@value", []) if isinstance(entry, dict) else []
    return " ".join(str(x) for x in values if isinstance(x, str) and x.strip())


def _sync_new_flow_objects_to_datastores(
    flow_objects: list[FlowObject],
    db_path: Path | None = None,
) -> None:
    """Insert merge-created flow objects into ``flow_objects`` and its FTS table.

    The merge did not mint flow objects until #215, which is why this is the
    only writer of these two tables outside the transform.  Both are needed: the
    ``consensus_flows`` view reads a flow's name, classifications and properties
    off the object, and `_load_working_set` is how the *next* source list in the
    same run sees what this one created.

    ``flow_type`` is computed the same way the transform computes it, from the
    object's `@type`.  The column is NOT NULL, and an object written without it
    would publish as `unclassified` for no reason other than having arrived
    through the merge.
    """
    # Resolved here rather than as a default argument: a default binds at
    # import time, and the tests for this module patch
    # `datastores.CONSENSUS_DB_FILEPATH`.  Both routes work this way (#92).
    db_path = CONSENSUS_DB_FILEPATH if db_path is None else db_path
    if not flow_objects:
        return
    if not db_path.exists():
        logger.warning("consensus_db_not_found_skipping_sync", path=str(db_path))
        return

    fo_rows: list[tuple] = []
    fo_fts_rows: list[tuple] = []
    for obj in flow_objects:
        flow_object_id = obj.flow_object_id
        if not flow_object_id:
            continue
        classifications = obj.classifications
        if not isinstance(classifications, dict):
            classifications = {}
        pref_value = flow_label_value(obj) or ""
        alt_text = " ".join(
            item.value
            for item in coerce_alt_labels(obj.altLabel)
            if isinstance(item.value, str) and item.value.strip()
        )
        # `flow_object_json` must hold exactly what the transform writes there,
        # which is `FlowObject.to_dict()` -- and `_compute_flow_type` reads the
        # serialised `@type` key.  Serialised once and used for both.
        payload = obj.to_dict()
        fo_rows.append((
            flow_object_id,
            pref_value,
            orjson.dumps(obj.prefLabel).decode("utf-8"),
            orjson.dumps(obj.altLabel).decode("utf-8"),
            orjson.dumps(classifications).decode("utf-8"),
            orjson.dumps(obj.properties).decode("utf-8"),
            orjson.dumps(obj.references).decode("utf-8"),
            orjson.dumps(payload).decode("utf-8"),
            obj.origin_qualifier or None,
            obj.parent_flow_object_id or None,
            obj.parent_intervention_id or None,
            _compute_flow_type(payload),
        ))
        fo_fts_rows.append((
            flow_object_id,
            pref_value,
            alt_text,
            _classification_text(classifications, CHEMINF_CAS_REGISTRY_NUMBER),
            _classification_text(classifications, CHEMINF_EC_NUMBER),
        ))

    conn = sqlite3.connect(db_path)
    try:
        conn.executemany(
            """
            INSERT OR IGNORE INTO flow_objects (
                flow_object_id, pref_label_value, pref_label_json, alt_label_json,
                classifications_json, properties_json, references_json,
                flow_object_json, origin_qualifier, parent_flow_object_id,
                parent_intervention_id, flow_type
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            fo_rows,
        )
        conn.executemany(
            """
            INSERT INTO flow_objects_fts (
                flow_object_id, pref_label, alt_labels, cas_numbers, ec_numbers
            ) VALUES (?, ?, ?, ?, ?)
            """,
            fo_fts_rows,
        )
        conn.commit()
        logger.info(
            "synced_new_flow_objects_to_sqlite",
            count=len(fo_rows),
            path=str(db_path),
        )
    finally:
        conn.close()


def sync_flow_object_synonyms(
    flow_objects: list[FlowObject],
    object_ids: set[str],
    db_path: Path | None = None,
) -> int:
    """Write back the synonyms `carry_member_names` moved on existing objects.

    `_sync_new_flow_objects_to_datastores` writes the objects the merge minted,
    which is all it ever had to: nothing else changed a pre-existing object's
    labels.  The synonym pass does -- it withdraws a name that has come to
    answer for two substances, and the second substance is usually one an
    earlier stage wrote -- so a write-back is needed or the withdrawal lives in
    memory and the published row still holds the name (#113).

    `flow_objects_fts` is rewritten for the same rows, because it is what a
    name search reads and a stale index would answer with the name that was
    just withdrawn.  Returns how many rows were written.
    """
    # Resolved here rather than as a default argument, as every other writer in
    # this module resolves it (#92).
    db_path = CONSENSUS_DB_FILEPATH if db_path is None else db_path
    if not object_ids:
        return 0
    if not db_path.exists():
        logger.warning("consensus_db_not_found_skipping_sync", path=str(db_path))
        return 0

    rows: list[tuple] = []
    fts_rows: list[tuple] = []
    for obj in flow_objects:
        flow_object_id = obj.flow_object_id
        if not flow_object_id or flow_object_id not in object_ids:
            continue
        classifications = obj.classifications
        if not isinstance(classifications, dict):
            classifications = {}
        alt_text = " ".join(
            item.value
            for item in coerce_alt_labels(obj.altLabel)
            if isinstance(item.value, str) and item.value.strip()
        )
        payload = obj.to_dict()
        rows.append((
            orjson.dumps(obj.altLabel).decode("utf-8"),
            orjson.dumps(payload).decode("utf-8"),
            flow_object_id,
        ))
        fts_rows.append((
            flow_object_id,
            flow_label_value(obj) or "",
            alt_text,
            _classification_text(classifications, CHEMINF_CAS_REGISTRY_NUMBER),
            _classification_text(classifications, CHEMINF_EC_NUMBER),
        ))

    conn = sqlite3.connect(db_path)
    try:
        conn.executemany(
            "UPDATE flow_objects SET alt_label_json = ?, flow_object_json = ? "
            "WHERE flow_object_id = ?",
            rows,
        )
        conn.executemany(
            "DELETE FROM flow_objects_fts WHERE flow_object_id = ?",
            [(row[0],) for row in fts_rows],
        )
        conn.executemany(
            """
            INSERT INTO flow_objects_fts (
                flow_object_id, pref_label, alt_labels, cas_numbers, ec_numbers
            ) VALUES (?, ?, ?, ?, ?)
            """,
            fts_rows,
        )
        conn.commit()
        logger.info(
            "synced_flow_object_synonyms", count=len(rows), path=str(db_path)
        )
    finally:
        conn.close()
    return len(rows)


def _sync_new_flows_to_datastores(
    new_flows: list[ElementaryFlow],
    flow_object_label_by_id: dict[str, str],
    db_path: Path | None = None,
) -> None:
    """Append algorithm-created elementary flows to the transform data stores.

    Updates ``elementary-flows.json`` and inserts rows into the SQLite
    database (``elementary_flows``, ``elementary_flow_sources``, and
    ``elementary_flows_fts`` tables).  Skips any flow whose
    ``elementary_flow_id`` is already present in the database.
    """
    # Resolved here rather than as a default argument: a default binds at
    # import time, and the tests for this module patch
    # `datastores.CONSENSUS_DB_FILEPATH`.  Both routes work this way (#92).
    db_path = CONSENSUS_DB_FILEPATH if db_path is None else db_path
    if not new_flows:
        return

    # --- SQLite ---
    if not db_path.exists():
        logger.warning("consensus_db_not_found_skipping_sync", path=str(db_path))
        return

    conn = sqlite3.connect(db_path)
    try:
        cur = conn.cursor()
        types_by_object_id = _flow_object_types(
            cur, {flow.flow_object_id for flow in new_flows}
        )
        ef_rows: list[tuple] = []
        ef_fts_rows: list[tuple] = []
        efs_rows: list[tuple] = []
        # Every new flow: the JSON write-back that used to filter these
        # is gone, and the inserts below are INSERT OR IGNORE.
        for flow in new_flows:
            elem_id = flow.elementary_flow_id
            if not elem_id:
                continue
            flow_object_id = flow.flow_object_id
            pref_label = flow_object_label_by_id.get(flow_object_id, "")
            source = flow.source
            unit = flow.unit or ""
            # Serialised once, here at the write boundary: the row states the
            # context as a rendering, an IRI, a payload and eight columns, and
            # all four come off the one `Context` the record holds.
            context_value = context_to_dict(flow.context) if flow.context else {}
            # The shared renderer, not a third copy of it.  This writes
            # `context_display` for the flows the merge adds and
            # `pipeline/sqlite.py` writes it for the rest, so a copy here is two
            # writers of one published column disagreeing about what a context
            # is called -- which for indoor air they did: this listed the fields
            # in order and printed `indoor`'s `Unknown`, where the other applies
            # the #284 rule and prints `Indoor` (#97).
            context_parts = context_display_parts(context_value)
            context_display = " → ".join(context_parts) if context_parts else "(none)"
            ef_rows.append((
                elem_id,
                flow_object_id,
                pref_label,
                source,
                unit,
                0,   # lcia_factor_count
                0,   # is_deprecated
                "",  # replaced_by_uuid
                context_display,
                # The context's address, beside its rendering and its parts.
                # The row carried the printed name and an empty `context_iri`
                # for all 1,200 flows the merge wrote, so every query asking
                # "same context?" the proper way -- the collision check, the
                # duplicate check, the review app's context filter -- was blind
                # to everything ecoinvent and BAFU brought in (#295).  The flow
                # has known the address all along: `flow_json` gets it in the
                # same breath.
                flow.context_iri,
                orjson.dumps(context_value).decode("utf-8"),
                str(context_value.get("dimension", "")),
                str(context_value.get("media", "")),
                str(context_value.get("strata", "")),
                str(context_value.get("indoor", "")),
                str(context_value.get("population_density", "")),
                str(context_value.get("geography", "")),
                str(context_value.get("water_body", "")),
                str(context_value.get("land_use", "")),
                0,   # consensus_change_count
                # `flow` is an ElementaryFlow record, and `flow_json` holds the
                # denormalised harmonised flow the export projects from --
                # writing an elementary flow into it is what once made that
                # column hold two record types.  There is no second column to
                # write now: `elementary_flow_json` is projected back out of
                # this one by `elementary_flow_record` (#255).
                orjson.dumps(_as_harmonised(flow, types_by_object_id)).decode("utf-8"),
            ))
            # Both are substance keys, which `ElementaryFlow` does not declare
            # -- see `_inherited_flow_object_fields` -- so they are read from
            # the passthrough bag by name, which is AGENTS.md rule 3.
            cas_text = " ".join(
                str(x) for x in (flow.extra.get("cas_numbers") or [])
                if isinstance(x, str) and x
            )
            alt_text = " ".join(
                item.value
                for item in coerce_alt_labels(flow.extra.get("altLabel"))
                if isinstance(item.value, str) and item.value.strip()
            )
            ef_fts_rows.append((
                elem_id, flow_object_id, pref_label, source, unit, context_display, cas_text, alt_text,
            ))
            for ref in (flow.source_refs or []):
                if not isinstance(ref, dict):
                    continue
                efs_rows.append((
                    elem_id,
                    str(ref.get("list_name") or ""),
                    str(ref.get("list_version") or ""),
                    str(ref.get("source_flow_uuid") or ""),
                    str(ref.get("source_flow_name") or ""),
                    orjson.dumps(ref.get("source_metadata", {})).decode("utf-8"),
                ))

        cur.executemany(
            """
            INSERT OR IGNORE INTO elementary_flows (
                uuid, flow_object_id, pref_label_value, source, unit, lcia_factor_count,
                is_deprecated, replaced_by_uuid, context_display, context_iri, context_json,
                context_dimension, context_media, context_strata, context_indoor,
                context_population_density, context_geography,
                context_water_body, context_land_use, consensus_change_count, flow_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ef_rows,
        )
        cur.executemany(
            "INSERT OR IGNORE INTO elementary_flows_fts "
            "(uuid, flow_object_id, name, source, unit, context_display, cas_numbers, alt_labels) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ef_fts_rows,
        )
        cur.executemany(
            """
            INSERT OR IGNORE INTO elementary_flow_sources (
                elementary_flow_uuid, list_name, list_version,
                source_flow_uuid, source_flow_name, source_metadata_json
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            efs_rows,
        )
        conn.commit()
        logger.info(
            "synced_new_flows_to_sqlite",
            count=len(ef_rows),
            path=str(db_path),
        )
    finally:
        conn.close()

def _sync_existing_flow_concept_associations(
    flows: list[ElementaryFlow], db_path: Path | None = None
) -> None:
    """Merge this pass's concept associations into a pre-existing flow's record.

    Merged, not assigned.  #252 was the other half of this: associations lived
    in two payload columns and only `flow_json` was written, so the *next*
    source list in the run loaded a working row from `elementary_flow_json`
    without them, appended its own, and wrote that short list back -- the
    ecoinvent 3.8 pass erased 4,084 of ecoinvent 3.12's correspondences that
    way.  The fix wrote both columns.

    There is one column now (#255), and `_load_working_set` projects the
    merge's record out of it, so the divergence that caused #252 has nowhere to
    happen: a pass cannot read a record that is missing what another pass
    wrote, because there is only one record.  Merging rather than assigning
    stays -- it is the half of the fix that does not depend on how many columns
    there are, and it is what stops a re-run losing an association already
    stored.
    """
    # Resolved here rather than as a default argument: a default binds at
    # import time, and the tests for this module patch
    # `datastores.CONSENSUS_DB_FILEPATH`.  Both routes work this way (#92).
    db_path = CONSENSUS_DB_FILEPATH if db_path is None else db_path
    if not flows or not db_path.exists():
        return

    updates: list[tuple[list[Any], str]] = []
    for flow in flows:
        elem_id = flow.elementary_flow_id
        assocs = flow.concept_associations
        if not elem_id or not isinstance(assocs, list) or not assocs:
            continue
        updates.append((assocs, elem_id))

    if not updates:
        return

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        updated = 0
        appended = 0
        for assocs, elem_id in updates:
            row = conn.execute(
                "SELECT flow_json FROM elementary_flows WHERE uuid = ?",
                (elem_id,),
            ).fetchone()
            if row is None or not row["flow_json"]:
                continue
            try:
                payload = orjson.loads(row["flow_json"])
            except Exception:
                continue
            if not isinstance(payload, dict):
                continue
            stored = payload.get("concept_associations")
            merged = (
                [a for a in stored if isinstance(a, dict)]
                if isinstance(stored, list)
                else []
            )
            before = len(merged)
            _extend_unique(merged, assocs, _association_key)
            appended += len(merged) - before
            payload["concept_associations"] = merged
            conn.execute(
                "UPDATE elementary_flows SET flow_json = ? WHERE uuid = ?",
                (orjson.dumps(payload).decode("utf-8"), elem_id),
            )
            updated += 1
        conn.commit()
        logger.info(
            "synced_existing_flow_concept_associations_to_sqlite",
            updated_count=updated,
            appended_association_count=appended,
            path=str(db_path),
        )
    finally:
        conn.close()

def _sync_existing_flow_source_refs(
    flows: list[ElementaryFlow], db_path: Path | None = None
) -> None:
    """Insert source_refs for pre-existing elementary flows into the SQLite DB.

    A matched flow's `source_refs` holds the reference the transform already
    wrote for the base list as well as the one it gained from this merge, so
    re-inserting the first is expected rather than exceptional: `INSERT OR
    IGNORE` against the table's UNIQUE key is what makes that a no-op.  The key
    did not exist until #23, so `OR IGNORE` had nothing to ignore against and
    this was writing a second copy of every reference it was handed.
    """
    # Resolved here rather than as a default argument: a default binds at
    # import time, and the tests for this module patch
    # `datastores.CONSENSUS_DB_FILEPATH`.  Both routes work this way (#92).
    db_path = CONSENSUS_DB_FILEPATH if db_path is None else db_path
    if not flows or not db_path.exists():
        return

    efs_rows: list[tuple] = []
    for flow in flows:
        elem_id = flow.elementary_flow_id
        if not elem_id:
            continue
        for ref in (flow.source_refs or []):
            if not isinstance(ref, dict):
                continue
            efs_rows.append((
                elem_id,
                str(ref.get("list_name") or ""),
                str(ref.get("list_version") or ""),
                str(ref.get("source_flow_uuid") or ""),
                str(ref.get("source_flow_name") or ""),
                orjson.dumps(ref.get("source_metadata", {})).decode("utf-8"),
            ))

    if not efs_rows:
        return

    conn = sqlite3.connect(db_path)
    try:
        conn.executemany(
            """
            INSERT OR IGNORE INTO elementary_flow_sources (
                elementary_flow_uuid, list_name, list_version,
                source_flow_uuid, source_flow_name, source_metadata_json
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            efs_rows,
        )
        conn.commit()
        logger.info(
            "synced_existing_flow_source_refs_to_sqlite",
            ref_count=len(efs_rows),
            path=str(db_path),
        )
    finally:
        conn.close()


def sync_merge_results(
    *,
    new_flow_objects: list[FlowObject],
    indexes: MergeIndexes,
    accumulator: MergeAccumulator,
    db_path: Path | None = None,
) -> None:
    """Write everything the merge changed into the database and the datastores.

    Three kinds of change, told apart by what produced them: the flow objects the
    merge minted, the elementary flows it created for this source list -- both
    the algorithmic additions and the manual ones -- and the flows that already
    existed and gained a source ref or a concept association by being matched.

    Which flows this pass created is read from `preexisting_flow_ids`, not from
    the `source` string those flows carry.  The string names the list and not
    the version, so on a run that merges ecoinvent 3.12 and then 3.8 every flow
    the 3.12 pass created answered to the 3.8 pass's
    `algorithm_addition_source` as well.  The 3.8 pass therefore sent 42 of them
    to `_sync_new_flows_to_datastores`, whose `INSERT OR IGNORE` is a no-op on a
    row that is already there: the `elementary_flow_sources` link was written,
    and the `source_refs` and `concept_associations` that go with it were not,
    so the export published no ecoinvent 3.8 correspondence for any of them.
    """
    # Resolved here rather than as a default argument: a default binds at
    # import time, and the tests for this module patch
    # `datastores.CONSENSUS_DB_FILEPATH`.  Both routes work this way (#92).
    db_path = CONSENSUS_DB_FILEPATH if db_path is None else db_path
    created_flows = [
        f for f in accumulator.merged_elementary
        if f.elementary_flow_id
        and f.elementary_flow_id not in accumulator.preexisting_flow_ids
    ]
    # Objects first: a created flow's row carries its object's label, read from
    # `flow_object_label_by_id`, and the foreign key points the same way.
    _sync_new_flow_objects_to_datastores(new_flow_objects, db_path)
    _sync_new_flows_to_datastores(
        created_flows, indexes.flow_object_label_by_id, db_path
    )

    # `merged_elementary` is the whole working list, so which of its rows this
    # pass actually touched has to come from what the pass recorded.  Two
    # things touch a pre-existing flow: a match, which names its target (#23),
    # and an addition whose minted id collides with a flow an earlier version's
    # pass minted from the same source uuid, which `add_flow` merged into.
    matched_target_ids = {
        str(match.target_elementary_flow_id or "")
        for match in (*accumulator.prepared_matches, *accumulator.algorithm_matches)
    }
    touched_ids = (
        matched_target_ids | accumulator.added_flow_ids
    ) & accumulator.preexisting_flow_ids
    existing_matched_flows = [
        f for f in accumulator.merged_elementary
        if f.elementary_flow_id in touched_ids
        and (f.source_refs or f.concept_associations)
    ]
    _sync_existing_flow_source_refs(existing_matched_flows, db_path)
    _sync_existing_flow_concept_associations(existing_matched_flows, db_path)
