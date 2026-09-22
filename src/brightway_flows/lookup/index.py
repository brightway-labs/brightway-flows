"""The lookups a query is answered from, read out of a build that has happened.

The merge starts by loading its working set -- every flow object and every
elementary flow, as records, deep-copied -- because it is about to mutate them.

None of it is matching's.  The selector reads four fields off a candidate --
``elementary_flow_id``, ``unit``, ``context`` and ``context_iri`` -- and the
indexes need five off a flow object -- ``flow_object_id``, its preferred label,
its alternative labels, its classifications and its origin qualifier.  Every one
of those is a *column*, so this module reads the columns and skips both the JSON
parse and the copy: the copy exists to protect a mutation a lookup does not
perform.

Measured against the 21 August 2026 build of revision ``8be43a3`` -- EF 3.1 with
ecoinvent 3.12, ecoinvent 3.8 and BAFU 2026-v1 merged on, 7,984 flow objects and
96,277 active flows:

============================== ======= =========
what                            time    memory
============================== ======= =========
``_load_working_set``           7.96 s  +976 MB
``build_merge_accumulator``     6.45 s  +967 MB
this module, indexes included   1.44 s  +307 MB
============================== ======= =========

**Five and a half times faster and a third of the memory**, for indexes that
compare equal key for key -- not the sixteen-fold that ``plans/lookup-api.md``
§1.2 estimated, which appears to have counted neither building the indexes
themselves nor grouping the flows by object.  Both of those are done here.

The records this builds are **partial by construction**.  They carry the fields
matching reads and no more, which is correct for the selector and wrong for
anything else, so they do not leave this package: the answer a caller is handed
is read from ``flow_json`` for the one winning row.  One row, not 96,277.

What it must *not* be is a second implementation of matching.  The indexes are
built by :func:`merge.matching.build_merge_indexes`, the same function the merge
calls, from records assembled a cheaper way -- so the guarantee the lookup can
then make is that an answer from it is the answer the build would have given, or
it is broken.  :mod:`tests.test_lookup_index` holds the two loads to producing
equal indexes, key for key, so a field moving out of a column and into the JSON
fails there rather than quietly matching less.

See ``plans/lookup-api.md`` §1.2 and §3.4.
"""

from __future__ import annotations

import sqlite3

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import orjson

from brightway_flows.domain.context_registry import context_field_from_serialised
from brightway_flows.domain.elementary_flow import ElementaryFlow
from brightway_flows.domain.flow_object import FlowObject
from brightway_flows.merge.contexts import ContextExpectations
from brightway_flows.merge.matching import build_merge_indexes
from brightway_flows.merge.state import MergeIndexes
from brightway_flows.context_mapping import consensus_context_strings
from brightway_flows.sources import SourceList

#: The list a query is treated as coming from.  Not registered, and
#: :func:`sources.resolve_source_list` must not find it: it exists so that
#: `MergeIndexes` -- which is frozen and requires a list -- can be built, and a
#: build must never be able to name it as a ``--source``.
LOOKUP_LIST_NAME = "lookup"
LOOKUP_LIST_VERSION = "query"


class UnusableBuildError(RuntimeError):
    """The database cannot answer for the whole consensus list.

    Refused before a flow is read, on signals the build already records.  A
    lookup is a statement about one build, so a build that is half-written or
    is a slice somebody chose for a smoke run cannot make it.
    """


@dataclass(frozen=True)
class BuildStamp:
    """Which build answered, so a caller can tell when their answer expires.

    A match is not a fact about a substance; it is a fact about one consensus
    list on one day.  The list moves -- flows are deprecated, substances are
    split, a new source list mints objects the algorithm then matches against --
    so an ``elementary_flow_id`` a caller stores and never re-asks about drifts.
    Naming the run and the revision is what lets them ask again.
    """

    #: ``pipeline_runs.run_id`` of the transform that wrote the flows.
    run_id: str
    #: The git revision that ran, and whether its tree had uncommitted changes.
    #: A dirty revision cannot be checked out again, so an answer from one is
    #: not reproducible and says so.
    revision: str
    revision_dirty: bool
    #: When the transform ran, ISO-8601 as stored.
    timestamp: str
    #: ``merge_runs.run_id`` of the merge that placed the source lists, and when
    #: it finished.  Absent on a build nothing has been merged into, which is a
    #: base list on its own and a perfectly answerable one.
    merge_run_id: str = ""
    merge_finished_at: str = ""
    #: The source lists merged in, as ``name-version``, in merge order.  Which
    #: lists a build holds decides what there was to match against, so it is
    #: part of naming the build rather than a detail about it.
    merged_lists: tuple[str, ...] = ()
    #: What was there to be matched.
    flow_object_count: int = 0
    elementary_flow_count: int = 0


def lookup_source_list(*, simapro_origin: bool) -> SourceList:
    """The synthetic list a query is merged as, for the one thing it decides.

    Four of matching's inputs are keyed on which list is being merged, and three
    of them -- the prepared match table, the manual fixes and the additional
    flows -- are simply absent for a list nobody has seen, which costs nothing:
    there are no curated decisions about a row nobody has looked at.

    The fourth is ``simapro_origin``, and it is not absent, it is *stated by the
    caller*.  It is what entitles :func:`simapro_names.simapro_name_aliases` to
    rewrite `Benzene, chloro-` into chlorobenzene, and it reaches matching only
    through the list, so this is where "is this a SimaPro-shaped list" enters.

    ``flows_path`` is never read: nothing in the lookup path loads flows from a
    file, and pointing it at one would be inviting something to.
    """
    return SourceList(
        list_name=LOOKUP_LIST_NAME,
        list_version=LOOKUP_LIST_VERSION,
        flows_path=Path("/nonexistent/lookup-query-has-no-flows-file.json"),
        simapro_origin=simapro_origin,
    )


def _flow_object_from_columns(row: tuple[Any, ...]) -> FlowObject:
    """A `FlowObject` carrying only what :func:`build_merge_indexes` reads.

    ``pref_label_value`` is the column the writer fills with
    :func:`flow_label_value` of the object, which is the same function the index
    then calls on this record -- so passing the scalar back through ``prefLabel``
    returns it unchanged, and the index gets the label it would have got from
    the full payload.  ``alt_label_json`` and ``classifications_json`` are the
    verbatim fields, so there is nothing to reconstruct.

    Every other field is left at its default, and that is the point: this record
    is an argument to the index builder, not a substance.
    """
    flow_object_id, pref_label_value, alt_label_json, classifications_json, origin_qualifier = row
    return FlowObject(
        flow_object_id=str(flow_object_id or ""),
        prefLabel=[{"@value": str(pref_label_value or ""), "@language": "en"}]
        if pref_label_value
        else [],
        altLabel=orjson.loads(alt_label_json) if alt_label_json else [],
        properties={},
        references=[],
        created_from={},
        classifications=orjson.loads(classifications_json) if classifications_json else {},
        origin_qualifier=str(origin_qualifier) if origin_qualifier else None,
    )


def _elementary_flow_from_columns(row: tuple[Any, ...]) -> ElementaryFlow:
    """An `ElementaryFlow` carrying only what the selector scores on.

    ``unit`` and ``context_iri`` are read straight off their columns; ``context``
    is parsed from ``context_json`` into the `Context` the selector renders with
    :func:`context_display_parts`.

    ``source``, ``lcia_methods`` and ``general_comment`` are declared fields with
    no default, so they are filled with empties rather than omitted.  The
    selector reads none of them.
    """
    uuid, flow_object_id, unit, context_iri, context_json = row
    return ElementaryFlow(
        elementary_flow_id=str(uuid or ""),
        flow_object_id=str(flow_object_id or ""),
        source="",
        context=context_field_from_serialised(
            orjson.loads(context_json) if context_json else None
        ),
        context_iri=str(context_iri or ""),
        unit=str(unit or ""),
        unit_iri="",
        lcia_methods=[],
        general_comment=None,
    )


def _table_exists(connection: sqlite3.Connection, name: str) -> bool:
    """Whether this database has *name*.

    Asked rather than assumed, because the three tables the guards read are
    written by three different stages.  ``pipeline_runs`` comes from the
    transform and is not optional -- without it nothing says which build this
    is.  ``merge_runs`` and ``merge_run_inputs`` come from the merge, and a
    build with no ``--source`` never runs one: that is the base list on its own,
    which is a smaller consensus list and not a broken one.
    """
    return bool(
        connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (name,)
        ).fetchone()
    )


def _column_exists(connection: sqlite3.Connection, table: str, column: str) -> bool:
    """Whether *table* carries *column* yet.

    The merge's tables are ``CREATE TABLE IF NOT EXISTS`` and gain columns
    through ``_add_missing_columns``, so a database written before a column
    existed still has the table without it.  ``max_rows`` is one: a build older
    than the bound cannot say whether it was bounded, and the honest reading of
    that is "it does not say" rather than an error about a column.
    """
    if not _table_exists(connection, table):
        return False
    return any(
        row[1] == column
        for row in connection.execute(f"PRAGMA table_info({table})")
    )


def _refuse_an_unanswerable_build(connection: sqlite3.Connection, db_path: Path) -> None:
    """Refuse a build that is half-written, or is a slice of one.

    **A build in flight.**  ``merge_runs.finished_at`` is null between
    ``start_run`` and ``finish_run``, and half a merge is not a consensus list:
    the flows one source list created are there and the next list's are not, so
    a row would be told it has no consensus flow when the build it is reading is
    about to make one.  Not hypothetical -- the shared data directory was
    mid-build while ``plans/lookup-api.md`` was being measured.

    **A bounded build.**  ``pipeline_runs.max_flows`` bounds the transform to a
    prefix of the base list and ``merge_run_inputs.max_rows`` bounds a source
    list to a prefix of its rows.  Either one makes the database a slice
    somebody chose for a smoke run, and an answer from it is a statement about
    the slice rather than about the list.  ``assess`` already refuses to record
    a baseline from one, for this reason.

    A build nothing has been merged into is *not* refused: a base list on its
    own is a smaller consensus list, not a broken one, and the stamp says which
    lists it holds.
    """
    if not _table_exists(connection, "pipeline_runs"):
        raise UnusableBuildError(
            f"{db_path}: no `pipeline_runs` table, so nothing says which build "
            "this is or which revision produced it. A match is a statement "
            "about one build and cannot be made without naming it. This is a "
            "fixture or a partial file rather than the output of "
            "`brightway-flows build`."
        )

    unfinished = [
        run_id
        for (run_id,) in connection.execute(
            "SELECT run_id FROM merge_runs WHERE finished_at IS NULL OR finished_at = ''"
        )
    ] if _column_exists(connection, "merge_runs", "finished_at") else []
    if unfinished:
        raise UnusableBuildError(
            f"{db_path}: merge run {unfinished[0]} has not finished. Half a "
            "merge is not a consensus list -- the flows one source list created "
            "are there and the next list's are not -- so a row would be told it "
            "has no consensus flow when the build is about to make one. Wait "
            "for the build to finish, or point at a database that is not being "
            "written."
        )

    bounded_flows = [
        (run_id, max_flows)
        for run_id, max_flows in connection.execute(
            "SELECT run_id, max_flows FROM pipeline_runs WHERE max_flows IS NOT NULL"
        )
    ] if _column_exists(connection, "pipeline_runs", "max_flows") else []
    if bounded_flows:
        run_id, max_flows = bounded_flows[0]
        raise UnusableBuildError(
            f"{db_path}: run {run_id} built only {max_flows} flows of the base "
            "list. That is a slice somebody chose for a smoke run, so an answer "
            "from it is a statement about the slice and not about the consensus "
            "list. Build without --max-flows."
        )

    bounded_rows = [
        (list_name, list_version, max_rows)
        for list_name, list_version, max_rows in connection.execute(
            "SELECT list_name, list_version, max_rows FROM merge_run_inputs "
            "WHERE max_rows IS NOT NULL"
        )
    ] if _column_exists(connection, "merge_run_inputs", "max_rows") else []
    if bounded_rows:
        list_name, list_version, max_rows = bounded_rows[0]
        raise UnusableBuildError(
            f"{db_path}: only {max_rows} rows of {list_name}-{list_version} were "
            "merged. The flows the rest of that list would have created are "
            "missing, so a row can be told no consensus flow exists for it when "
            "an unbounded build would have made one. Build without --max-rows."
        )


def _read_build_stamp(
    connection: sqlite3.Connection,
    db_path: Path,
    *,
    flow_object_count: int,
    elementary_flow_count: int,
) -> BuildStamp:
    """Which run wrote this database, from the two tables that record it.

    ``run_id`` and ``timestamp`` are required, because they are what names the
    build.  The revision is read only where the column is there: `pipeline_runs`
    gained ``git_commit`` and ``git_dirty`` after it was first written, so a
    database older than those columns can still say *which run* it was, and an
    answer from it is still a statement about a build -- one whose revision is
    unknown, which the empty string says.
    """
    optional = {
        name: _column_exists(connection, "pipeline_runs", name)
        for name in ("git_commit", "git_dirty")
    }
    columns = ["run_id", "timestamp"] + [name for name, present in optional.items() if present]
    runs = list(
        connection.execute(
            f"SELECT {', '.join(columns)} FROM pipeline_runs ORDER BY timestamp DESC"
        )
    )
    if not runs:
        raise UnusableBuildError(
            f"{db_path}: no row in `pipeline_runs`, so nothing says which build "
            "this is. A match is a statement about one build and cannot be made "
            "without naming it."
        )
    row = dict(zip(columns, runs[0]))
    run_id, timestamp = row["run_id"], row["timestamp"]
    git_commit, git_dirty = row.get("git_commit", ""), row.get("git_dirty", 0)

    merge_runs = list(
        connection.execute(
            "SELECT run_id, finished_at FROM merge_runs ORDER BY finished_at DESC"
        )
    ) if _column_exists(connection, "merge_runs", "finished_at") else []
    merge_run_id, merge_finished_at = merge_runs[0] if merge_runs else ("", "")
    merged = tuple(
        f"{list_name}-{list_version}"
        for list_name, list_version in connection.execute(
            "SELECT list_name, list_version FROM merge_run_inputs "
            "WHERE run_id = ? ORDER BY sequence",
            (merge_run_id,),
        )
    ) if merge_run_id and _column_exists(connection, "merge_run_inputs", "sequence") else ()

    return BuildStamp(
        run_id=str(run_id or ""),
        revision=str(git_commit or ""),
        revision_dirty=bool(git_dirty),
        timestamp=str(timestamp or ""),
        merge_run_id=str(merge_run_id or ""),
        merge_finished_at=str(merge_finished_at or ""),
        merged_lists=merged,
        flow_object_count=flow_object_count,
        elementary_flow_count=elementary_flow_count,
    )


def load_lookup_index(
    db_path: Path,
) -> tuple[MergeIndexes, dict[str, list[ElementaryFlow]], BuildStamp]:
    """Everything a query is answered against, from the columns.

    Returns the indexes matching reads, the object-to-flows map the selector
    picks candidates out of, and the stamp naming the build that answered.

    The indexes carry the *unqualified* list -- ``simapro_origin=False``.  A
    caller who states otherwise gets a copy of this record with the other list
    on it, which shares every dict underneath because the record is frozen and
    ``dataclasses.replace`` copies the reference.  Two records, one set of
    indexes; building them twice would cost the whole load again for one boolean.

    ``elementary_by_object`` excludes deprecated flows, exactly as
    :func:`merge.matching.build_merge_accumulator` does when it builds the same
    map: a deprecated flow is neither a candidate nor a match target.  Where the
    merge then needs the deprecated ones to follow a replacement chain, the
    lookup does not -- it never follows a prepared decision -- so they are left
    out here rather than carried in a second map nothing reads.

    Opened ``mode=ro``.  A build writes the shared data directory for the better
    part of an hour, so a lookup will sometimes be reading a database that is
    mid-run; read-only is what stops this path from being able to make that
    worse, and :func:`_refuse_an_unanswerable_build` is what stops it answering
    from it.
    """
    if not db_path.exists():
        raise FileNotFoundError(
            f"No consensus database at {db_path}. Run `brightway-flows build` "
            "first, or point at the database of a build that has already run."
        )
    connection = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        _refuse_an_unanswerable_build(connection, db_path)

        flow_objects = [
            _flow_object_from_columns(row)
            for row in connection.execute(
                "SELECT flow_object_id, pref_label_value, alt_label_json, "
                "classifications_json, origin_qualifier FROM flow_objects "
                "ORDER BY rowid"
            )
        ]
        elementary_by_object: dict[str, list[ElementaryFlow]] = {}
        elementary_flow_count = 0
        for row in connection.execute(
            "SELECT uuid, flow_object_id, unit, context_iri, context_json "
            "FROM elementary_flows WHERE is_deprecated = 0 ORDER BY rowid"
        ):
            elementary_flow_count += 1
            flow = _elementary_flow_from_columns(row)
            if flow.flow_object_id:
                elementary_by_object.setdefault(flow.flow_object_id, []).append(flow)

        stamp = _read_build_stamp(
            connection,
            db_path,
            flow_object_count=len(flow_objects),
            elementary_flow_count=elementary_flow_count,
        )
    finally:
        connection.close()

    indexes = build_merge_indexes(
        flow_objects,
        # **Deliberately empty, and nothing in the lookup path reads it.**
        #
        # `ContextExpectations` resolves a row's context by asking three rules
        # in order, and all three key on the list's own `source` string -- which
        # for a query is a synthetic label no rule is written under.  Filling
        # this with the compartment rules read across every list would look like
        # an improvement and would be a defect: four of those 90 compartments
        # are ones a list has already ruled its flows' *names* have to decide,
        # so `natural resource / land` would answer `laus-occu` and file a
        # caller's land transformation as an occupation, silently. That is #52.
        #
        # `lookup/query.py` resolves context instead, through
        # `context_iri_for_any_source_context`, which reads the name rules
        # beside the compartment rules -- and reports which of its four steps
        # answered, which this record has no field for.
        #
        # Neither `resolve_flow_object` nor `_select_elementary_flow` reads this
        # field; `tests/test_lookup_index.py` holds them to that.
        context_expectations=ContextExpectations(
            _by_source_context={},
            _source_label=lookup_source_list(simapro_origin=False).source_label,
        ),
        consensus_context_strings={
            iri: list(strings) for iri, strings in consensus_context_strings().items()
        },
        # A query has no curated decisions about it, by definition: these are
        # rulings about pairings a curator has looked at, and nobody has looked
        # at a row nobody has seen.
        prepared_context_decisions={},
        mapping_file=None,
        source=lookup_source_list(simapro_origin=False),
    )
    return indexes, elementary_by_object, stamp
