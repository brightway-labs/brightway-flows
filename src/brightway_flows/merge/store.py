"""What a merge run did, stored in SQLite.

The report used to be `ecoinvent-merge-report-{version}.json`: a bag of seven
parallel lists, one file per source version.  Two things were wrong with it.

It had no key.  Nothing stated that a source flow gets exactly one outcome, so
nothing enforced it, and the shape could not express a second source list at all
without a second file.  Measured on a real run, the invariant does hold -- 9,850
distinct source flows, each in exactly one of prepared / algorithm /
manual-addition / unmatched -- so it can be a primary key rather than a hope.

It was also redundant.  `unmatched` and the two enriched lists described the
same 9,614 rows: the enriched pair is exactly a partition of `unmatched`, with
no overlap, split on whether the row had flow-object candidates.  That is one
boolean, stored as 9,614 duplicated rows.  Likewise the nine
`prepared_context_inconsistencies` rows are all rows that also appear in
`prepared_matches`; an inconsistency is an annotation on an outcome, not an
outcome of its own.

So: one row per source flow per run, with the type-specific remainder in
`detail`.  The three-way split of unmatched rows survives as a query, which is
where a view belongs.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any, ClassVar

import orjson
import structlog

from brightway_flows.domain.records import SerialisableRecord
from brightway_flows.merge.report import (
    AlgorithmMatch,
    CreatedFlow,
    EnrichedUnmatchedRow,
    ManualAddition,
    PreparedContextInconsistency,
    PreparedMatch,
    UnmatchedRow,
)
from brightway_flows.pipeline.sqlite_schema import insert_statement
from brightway_flows.sources import SourceList

logger = structlog.get_logger(__name__)

#: Bumped when the merge tables change shape.  2 adds `available_row_count`
#: and `max_rows` to `merge_run_inputs`, which is what a bounded merge
#: (`build --max-rows`) records about itself.
MERGE_SCHEMA_VERSION = 2


def _json_safe(value: Any) -> Any:
    """Convert tuples to lists, recursively.

    `detail` is stored as JSON, which has no tuple type, so a tuple written in
    comes back as a list -- `AlgorithmMatch.source_context_normalized` is one.
    Normalising on the way in means an outcome equals what reading it back
    produces, instead of differing in a way nothing would notice until something
    compared them.
    """
    if isinstance(value, tuple | list):
        return [_json_safe(item) for item in value]
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    return value


class Outcome(StrEnum):
    """How the merge resolved a source flow.  Exactly one applies."""

    PREPARED = "prepared"
    ALGORITHM = "algorithm"
    MANUAL_ADDITION = "manual-addition"
    #: The substance was not in the consensus list, so the merge added it.
    #: Separate from `manual-addition`, which groups source flows onto a flow
    #: object a curator chose: nothing was chosen here because there was
    #: nothing to choose from.  The published flow carries the same `source`
    #: string as both additions, so this is the only place they differ.
    CREATED = "created"
    UNMATCHED = "unmatched"


@dataclass
class MergeOutcome(SerialisableRecord):
    """What became of one source flow in one run.

    The indexed fields are the ones a curator filters and sorts on; everything
    else specific to how the row was resolved goes in `detail`, which is stored
    as JSON.  Splitting it that way keeps the table narrow without discarding
    anything the old report carried.
    """

    run_id: str
    list_name: str
    list_version: str
    source_uuid: str
    outcome: Outcome

    source_name: str = ""
    source_context: list[str] = field(default_factory=list)
    source_unit: str = ""
    source_cas: str = ""
    source_ec: str = ""

    #: Why a row could not be placed, as an
    #: :class:`~brightway_flows.merge.report.UnmatchedReason` value.  Empty
    #: for a row that was placed.  Typed `str` rather than the enum because a
    #: row read back from the table is whatever text the table holds, including
    #: a category written by an older version of this code.
    reason: str = ""
    flow_object_id: str = ""
    target_elementary_flow_id: str = ""
    basis: str = ""
    basis_value: str = ""
    matching_method: str = ""

    #: Only meaningful when unmatched: whether the row has candidate flow
    #: objects, and so whether a curator picks one or creates one.  This is the
    #: whole content of the old two-list split.
    has_flow_object_candidates: bool | None = None
    #: Only meaningful when prepared: the stored decision no longer agrees with
    #: the contexts its target covers.
    has_context_inconsistency: bool = False
    #: The source flow and the flow it landed on are measured in different
    #: units, and the pair is not on the reviewed allow-list.  An annotation on
    #: a match that stands, like the flag above: the mapping may still be right
    #: -- EF 3.1 accounts fossil carriers by energy content on purpose -- so
    #: this reports rather than withholds.  See `merge.unit_changes`.
    has_unit_mismatch: bool = False

    detail: dict[str, Any] = field(default_factory=dict)

    _OMIT_IF_NONE: ClassVar[frozenset[str]] = frozenset({"has_flow_object_candidates"})

    @classmethod
    def from_prepared(cls, run_id: str, source: SourceList, row: PreparedMatch,
                      *, inconsistent: bool = False,
                      unit_mismatch: bool = False) -> MergeOutcome:
        return cls(
            run_id=run_id, list_name=source.list_name,
            list_version=source.list_version, source_uuid=row.source_uuid,
            outcome=Outcome.PREPARED, source_name=row.source_name,
            source_context=list(row.source_context), source_unit=row.source_unit,
            source_cas=row.source_cas,
            flow_object_id=row.target_flow_object_id,
            target_elementary_flow_id=row.target_elementary_flow_id,
            matching_method="prepared",
            has_context_inconsistency=inconsistent,
            has_unit_mismatch=unit_mismatch,
            detail=_json_safe(row.to_dict()),
        )

    @classmethod
    def from_algorithm(cls, run_id: str, source: SourceList,
                       row: AlgorithmMatch, *,
                       unit_mismatch: bool = False) -> MergeOutcome:
        return cls(
            run_id=run_id, list_name=source.list_name,
            list_version=source.list_version, source_uuid=row.source_uuid,
            outcome=Outcome.ALGORITHM, source_name=row.source_name,
            source_context=list(row.source_context), source_unit=row.source_unit,
            source_cas=row.source_cas, source_ec=row.source_ec,
            flow_object_id=row.flow_object_id,
            target_elementary_flow_id=row.target_elementary_flow_id,
            basis=row.basis, basis_value=row.basis_value,
            matching_method=row.matching_method,
            has_unit_mismatch=unit_mismatch,
            detail=_json_safe(row.to_dict()),
        )

    @classmethod
    def from_manual_addition(cls, run_id: str, source: SourceList,
                             row: ManualAddition) -> MergeOutcome:
        return cls(
            run_id=run_id, list_name=source.list_name,
            list_version=source.list_version, source_uuid=row.source_uuid,
            outcome=Outcome.MANUAL_ADDITION, source_name=row.source_name,
            source_context=list(row.source_context), source_unit=row.source_unit,
            source_cas=row.source_cas, source_ec=row.source_ec,
            flow_object_id=row.flow_object_id,
            target_elementary_flow_id=row.new_elementary_flow_id,
            matching_method="manual_addition",
            detail=_json_safe(row.to_dict()),
        )

    @classmethod
    def from_created(cls, run_id: str, source: SourceList,
                     row: CreatedFlow) -> MergeOutcome:
        return cls(
            run_id=run_id, list_name=source.list_name,
            list_version=source.list_version, source_uuid=row.source_uuid,
            outcome=Outcome.CREATED, source_name=row.source_name,
            source_context=list(row.source_context), source_unit=row.source_unit,
            source_cas=row.source_cas, source_ec=row.source_ec,
            flow_object_id=row.flow_object_id,
            target_elementary_flow_id=row.new_elementary_flow_id,
            # `reason` stays empty: it is why a row could *not* be placed, and
            # this one was.  Only `no-flow-object-candidate` ever reaches
            # creation, so recording it here would be a constant column.
            matching_method="flow_object_creation",
            # On a creation this says the row's own unit is not the one the
            # flow it made states, because two rows landed together and
            # disagreed.  On a match it says the row disagrees with a flow that
            # already existed.  One field, one meaning -- "this row is measured
            # in something other than the flow it landed on" -- and `outcome`
            # is what tells the two situations apart (#78).
            has_unit_mismatch=row.has_unit_mismatch,
            detail=_json_safe(row.to_dict()),
        )

    @classmethod
    def from_unmatched(cls, run_id: str, source: SourceList, row: UnmatchedRow,
                       *, has_candidates: bool, enrichment: dict[str, Any] | None = None
                       ) -> MergeOutcome:
        detail = _json_safe(row.to_dict())
        if enrichment:
            detail = {**detail, **_json_safe(enrichment)}
        return cls(
            run_id=run_id, list_name=source.list_name,
            list_version=source.list_version, source_uuid=row.source_uuid,
            outcome=Outcome.UNMATCHED, source_name=row.source_name,
            source_context=list(row.source_context), source_unit=row.source_unit,
            source_cas=row.source_cas, source_ec=row.source_ec,
            reason=row.reason,
            target_elementary_flow_id=row.target_elementary_flow_id or "",
            matching_method=row.matching_method or "",
            has_flow_object_candidates=has_candidates,
            detail=detail,
        )


@dataclass
class MergeRunInput(SerialisableRecord):
    """One source list consumed by a run, and where it came in the order.

    `sequence` is why this table exists rather than a column on the run: with
    more than one list, a later list can match a flow an earlier one created,
    so which went first is part of what happened and has to be recoverable.
    """

    run_id: str
    list_name: str
    list_version: str
    sequence: int
    source_path: str = ""
    prepared_match_table: str = ""
    row_count: int = 0
    #: How many rows the list ships, against `row_count`'s how many this run
    #: read.  Equal unless `build --max-rows` bounded the merge, and recorded
    #: as two numbers rather than one flag because "3,412 rows merged" and
    #: "3,412 of 21,088" are different claims.
    available_row_count: int = 0
    #: The limit that produced the difference, or `None` on a whole run.  A
    #: reader could infer "bounded" from the two counts above; this says by
    #: what, and it is what `assess` refuses to record a baseline from.
    max_rows: int | None = None


#: `IF NOT EXISTS`, unlike the flow and review tables, which are dropped and
#: recreated by every build (`pipeline.sqlite_schema.recreate`).  These rows
#: outlive the run that wrote them -- every previous run's outcomes are still
#: here, and `write_source_outcomes` deletes only the scope it is about to
#: rewrite -- so dropping the table would throw away the history the merge
#: pages read.  A column added here needs `_ADDED_OUTCOME_COLUMNS` below.
SCHEMA = (
    """
    CREATE TABLE IF NOT EXISTS merge_runs (
        run_id TEXT PRIMARY KEY,
        started_at TEXT NOT NULL,
        finished_at TEXT,
        schema_version INTEGER NOT NULL,
        stats_json TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS merge_run_inputs (
        run_id TEXT NOT NULL,
        list_name TEXT NOT NULL,
        list_version TEXT NOT NULL,
        sequence INTEGER NOT NULL,
        source_path TEXT,
        prepared_match_table TEXT,
        row_count INTEGER NOT NULL DEFAULT 0,
        available_row_count INTEGER NOT NULL DEFAULT 0,
        max_rows INTEGER,
        PRIMARY KEY (run_id, list_name, list_version)
    )
    """,
    # The primary key is the invariant: one outcome per source flow per list per
    # run.  Verified on a real run before being asserted here.
    """
    CREATE TABLE IF NOT EXISTS merge_outcomes (
        run_id TEXT NOT NULL,
        list_name TEXT NOT NULL,
        list_version TEXT NOT NULL,
        source_uuid TEXT NOT NULL,
        outcome TEXT NOT NULL,
        source_name TEXT,
        source_context_json TEXT,
        source_unit TEXT,
        source_cas TEXT,
        source_ec TEXT,
        reason TEXT,
        flow_object_id TEXT,
        target_elementary_flow_id TEXT,
        basis TEXT,
        basis_value TEXT,
        matching_method TEXT,
        has_flow_object_candidates INTEGER,
        has_context_inconsistency INTEGER NOT NULL DEFAULT 0,
        has_unit_mismatch INTEGER NOT NULL DEFAULT 0,
        detail_json TEXT,
        PRIMARY KEY (run_id, list_name, list_version, source_uuid)
    )
    """,
    # Only reachable with more than one source list: two lists claiming the same
    # target, or disagreeing about its unit or context.  Created here so the
    # shape is settled before anything writes to it.
    """
    CREATE TABLE IF NOT EXISTS merge_conflicts (
        run_id TEXT NOT NULL,
        target_elementary_flow_id TEXT NOT NULL,
        kind TEXT NOT NULL,
        claimants_json TEXT NOT NULL
    )
    """,
)

INDEXES = (
    "CREATE INDEX IF NOT EXISTS idx_merge_outcomes_outcome "
    "ON merge_outcomes(run_id, outcome)",
    "CREATE INDEX IF NOT EXISTS idx_merge_outcomes_candidates "
    "ON merge_outcomes(run_id, outcome, has_flow_object_candidates)",
    "CREATE INDEX IF NOT EXISTS idx_merge_outcomes_target "
    "ON merge_outcomes(target_elementary_flow_id)",
    "CREATE INDEX IF NOT EXISTS idx_merge_outcomes_reason "
    "ON merge_outcomes(run_id, reason)",
)

#: The columns each `INSERT` below fills.  The convention the other two writers
#: into this file now follow as well (#96): one declaration per table, turned
#: into the statement by `insert_statement`, rather than a column list restated
#: inside it where it can drift from the `CREATE TABLE` above without anything
#: saying so.
_RUN_COLUMNS = ("run_id", "started_at", "schema_version")

_RUN_INPUT_COLUMNS = (
    "run_id", "list_name", "list_version", "sequence", "source_path",
    "prepared_match_table", "row_count", "available_row_count", "max_rows",
)

_CONFLICT_COLUMNS = (
    "run_id", "target_elementary_flow_id", "kind", "claimants_json",
)

_OUTCOME_COLUMNS = (
    "run_id", "list_name", "list_version", "source_uuid", "outcome",
    "source_name", "source_context_json", "source_unit", "source_cas",
    "source_ec", "reason", "flow_object_id", "target_elementary_flow_id",
    "basis", "basis_value", "matching_method", "has_flow_object_candidates",
    "has_context_inconsistency", "has_unit_mismatch", "detail_json",
)


def build_outcomes(
    *,
    run_id: str,
    source: SourceList,
    prepared_matches: list[PreparedMatch],
    algorithm_matches: list[AlgorithmMatch],
    manual_additions: list[ManualAddition],
    created_flows: list[CreatedFlow],
    unmatched: list[UnmatchedRow],
    inconsistencies: list[PreparedContextInconsistency],
    unit_mismatch_uuids: set[str],
    enriched_with_candidates: list[EnrichedUnmatchedRow],
    enriched_without_candidates: list[EnrichedUnmatchedRow],
) -> list[MergeOutcome]:
    """One outcome row per source flow, from what the merge concluded about it.

    The module docstring above says why this is one list rather than seven: a
    source flow gets exactly one outcome, and the two things that used to be
    lists of their own are annotations on it.  A prepared-context inconsistency
    is a row that also appears in *prepared_matches*, so it sets a flag on that
    outcome; the two enriched unmatched lists are exactly a partition of
    *unmatched*, so the split becomes a boolean and the enrichment goes into
    `detail` rather than duplicating the row.
    """
    inconsistent_uuids = {row.source_uuid for row in inconsistencies}
    enrichment_by_uuid: dict[str, dict[str, Any]] = {}
    with_candidates: set[str] = set()
    for enriched in enriched_with_candidates:
        enrichment_by_uuid[enriched.source_uuid] = enriched.to_dict()
        with_candidates.add(enriched.source_uuid)
    for enriched in enriched_without_candidates:
        enrichment_by_uuid[enriched.source_uuid] = enriched.to_dict()

    outcomes: list[MergeOutcome] = []
    outcomes.extend(
        MergeOutcome.from_prepared(
            run_id, source, row,
            inconsistent=row.source_uuid in inconsistent_uuids,
            unit_mismatch=row.source_uuid in unit_mismatch_uuids,
        )
        for row in prepared_matches
    )
    outcomes.extend(
        MergeOutcome.from_algorithm(
            run_id, source, row,
            unit_mismatch=row.source_uuid in unit_mismatch_uuids,
        )
        for row in algorithm_matches
    )
    outcomes.extend(
        MergeOutcome.from_manual_addition(run_id, source, row)
        for row in manual_additions
    )
    outcomes.extend(
        MergeOutcome.from_created(run_id, source, row)
        for row in created_flows
    )
    outcomes.extend(
        MergeOutcome.from_unmatched(
            run_id, source, row,
            has_candidates=row.source_uuid in with_candidates,
            enrichment=enrichment_by_uuid.get(row.source_uuid),
        )
        for row in unmatched
    )
    return outcomes


#: Columns added to `merge_outcomes` after it first shipped.  The flow tables
#: are dropped and recreated by the transform on every build, so they need no
#: migration; the merge tables are not -- they are `CREATE TABLE IF NOT EXISTS`
#: and hold every previous run -- so a column added to the DDL alone would be
#: absent from every existing database and every insert would fail.
#:
#: Additive only, and each must be nullable or defaulted, which is the subset
#: of schema change SQLite's `ADD COLUMN` does cheaply and without rewriting
#: the table.  A change that is not additive needs more than this.
_ADDED_OUTCOME_COLUMNS: dict[str, str] = {
    "has_unit_mismatch": "INTEGER NOT NULL DEFAULT 0",
}

#: The same for `merge_run_inputs`, whose rows outlive the run that wrote them:
#: a database built before the merge could be bounded still has its old runs in
#: it, and they are read by the merge pages.
_ADDED_RUN_INPUT_COLUMNS: dict[str, str] = {
    "available_row_count": "INTEGER NOT NULL DEFAULT 0",
    "max_rows": "INTEGER",
}


def _add_missing_columns(
    connection: sqlite3.Connection, table: str, columns: dict[str, str]
) -> None:
    """Bring *table* up to date with columns added since it was created."""
    existing = {row[1] for row in connection.execute(f"PRAGMA table_info({table})")}
    for name, declaration in columns.items():
        if name not in existing:
            connection.execute(f"ALTER TABLE {table} ADD COLUMN {name} {declaration}")
            logger.info("merge_table_column_added", table=table, column=name)


def create_merge_tables(connection: sqlite3.Connection) -> None:
    for statement in SCHEMA:
        connection.execute(statement)
    _add_missing_columns(connection, "merge_outcomes", _ADDED_OUTCOME_COLUMNS)
    _add_missing_columns(connection, "merge_run_inputs", _ADDED_RUN_INPUT_COLUMNS)
    for statement in INDEXES:
        connection.execute(statement)


def _outcome_row(outcome: MergeOutcome) -> tuple[Any, ...]:
    return (
        outcome.run_id, outcome.list_name, outcome.list_version,
        outcome.source_uuid, str(outcome.outcome), outcome.source_name,
        orjson.dumps(outcome.source_context).decode(), outcome.source_unit,
        outcome.source_cas, outcome.source_ec, str(outcome.reason),
        outcome.flow_object_id, outcome.target_elementary_flow_id,
        outcome.basis, outcome.basis_value, outcome.matching_method,
        None if outcome.has_flow_object_candidates is None
        else int(outcome.has_flow_object_candidates),
        int(outcome.has_context_inconsistency),
        int(outcome.has_unit_mismatch),
        orjson.dumps(outcome.detail).decode(),
    )


def start_run(db_path: Path, *, run_id: str, started_at: str) -> None:
    """Open a run, clearing anything a previous attempt at the same id left."""
    connection = sqlite3.connect(db_path)
    try:
        create_merge_tables(connection)
        for table in ("merge_outcomes", "merge_run_inputs", "merge_conflicts",
                      "merge_runs"):
            connection.execute(f"DELETE FROM {table} WHERE run_id = ?", (run_id,))
        connection.execute(
            insert_statement("merge_runs", _RUN_COLUMNS),
            (run_id, started_at, MERGE_SCHEMA_VERSION),
        )
        connection.commit()
    finally:
        connection.close()


def write_source_outcomes(
    db_path: Path,
    *,
    run_id: str,
    source_input: MergeRunInput,
    outcomes: list[MergeOutcome],
) -> None:
    """Record what one source list decided, replacing only that list's rows.

    Scoped to the source list, not the run.  Deleting by `run_id` alone is
    correct when a run has one source list and destroys the earlier lists'
    outcomes when it has several -- which is what `build` does now.
    """
    connection = sqlite3.connect(db_path)
    try:
        create_merge_tables(connection)
        scope = (run_id, source_input.list_name, source_input.list_version)
        for table in ("merge_outcomes", "merge_run_inputs"):
            connection.execute(
                f"DELETE FROM {table} WHERE run_id = ? AND list_name = ? "
                "AND list_version = ?",
                scope,
            )
        connection.execute(
            insert_statement("merge_run_inputs", _RUN_INPUT_COLUMNS),
            (run_id, source_input.list_name, source_input.list_version,
             source_input.sequence, source_input.source_path,
             source_input.prepared_match_table, source_input.row_count,
             source_input.available_row_count or source_input.row_count,
             source_input.max_rows),
        )
        connection.executemany(
            insert_statement("merge_outcomes", _OUTCOME_COLUMNS),
            [_outcome_row(o) for o in outcomes],
        )
        connection.commit()
    finally:
        connection.close()
    logger.info(
        "wrote_source_outcomes", run_id=run_id,
        source=f"{source_input.list_name}-{source_input.list_version}",
        sequence=source_input.sequence, outcomes=len(outcomes),
    )


def finish_run(
    db_path: Path, *, run_id: str, finished_at: str, stats: dict[str, Any]
) -> None:
    """Close a run, after every source list has been merged."""
    connection = sqlite3.connect(db_path)
    try:
        connection.execute(
            "UPDATE merge_runs SET finished_at = ?, stats_json = ? WHERE run_id = ?",
            (finished_at, orjson.dumps(stats).decode(), run_id),
        )
        connection.commit()
    finally:
        connection.close()


def write_merge_run(
    db_path: Path,
    *,
    run_id: str,
    started_at: str,
    finished_at: str,
    inputs: list[MergeRunInput],
    outcomes: list[MergeOutcome],
    stats: dict[str, Any],
) -> None:
    """Record a whole run in one call.  A convenience over the three above."""
    start_run(db_path, run_id=run_id, started_at=started_at)
    by_source: dict[tuple[str, str], list[MergeOutcome]] = {}
    for outcome in outcomes:
        by_source.setdefault((outcome.list_name, outcome.list_version), []).append(outcome)
    declared = {(i.list_name, i.list_version) for i in inputs}
    undeclared = sorted(set(by_source) - declared)
    if undeclared:
        # Writing these would put outcomes in the table for a source list the
        # run does not say it consumed; dropping them silently would lose them.
        raise ValueError(
            f"outcomes for source list(s) not among the run's inputs: {undeclared}"
        )
    for source_input in inputs:
        write_source_outcomes(
            db_path,
            run_id=run_id,
            source_input=source_input,
            outcomes=by_source.get((source_input.list_name, source_input.list_version), []),
        )
    finish_run(db_path, run_id=run_id, finished_at=finished_at, stats=stats)


def latest_run_id(db_path: Path) -> str | None:
    connection = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        row = connection.execute(
            "SELECT run_id FROM merge_runs ORDER BY started_at DESC, rowid DESC LIMIT 1"
        ).fetchone()
    except sqlite3.OperationalError:
        return None
    finally:
        connection.close()
    return row[0] if row else None


def read_outcomes(
    db_path: Path,
    *,
    run_id: str | None = None,
    outcome: Outcome | None = None,
    has_flow_object_candidates: bool | None = None,
) -> list[MergeOutcome]:
    """Outcomes of a run, optionally narrowed.

    The old report's three unmatched lists are this function with different
    arguments: all of them, those with candidates, those without.
    """
    run = run_id or latest_run_id(db_path)
    if run is None:
        return []
    clauses = ["run_id = ?"]
    params: list[Any] = [run]
    if outcome is not None:
        clauses.append("outcome = ?")
        params.append(str(outcome))
    if has_flow_object_candidates is not None:
        clauses.append("has_flow_object_candidates = ?")
        params.append(int(has_flow_object_candidates))

    connection = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        rows = connection.execute(
            f"SELECT * FROM merge_outcomes WHERE {' AND '.join(clauses)} "
            "ORDER BY rowid",
            params,
        ).fetchall()
    finally:
        connection.close()
    return [_outcome_from_row(row) for row in rows]


def _outcome_from_row(row: sqlite3.Row) -> MergeOutcome:
    candidates = row["has_flow_object_candidates"]
    return MergeOutcome(
        run_id=row["run_id"],
        list_name=row["list_name"],
        list_version=row["list_version"],
        source_uuid=row["source_uuid"],
        outcome=Outcome(row["outcome"]),
        source_name=row["source_name"] or "",
        source_context=orjson.loads(row["source_context_json"] or b"[]"),
        source_unit=row["source_unit"] or "",
        source_cas=row["source_cas"] or "",
        source_ec=row["source_ec"] or "",
        reason=row["reason"] or "",
        flow_object_id=row["flow_object_id"] or "",
        target_elementary_flow_id=row["target_elementary_flow_id"] or "",
        basis=row["basis"] or "",
        basis_value=row["basis_value"] or "",
        matching_method=row["matching_method"] or "",
        has_flow_object_candidates=None if candidates is None else bool(candidates),
        has_context_inconsistency=bool(row["has_context_inconsistency"]),
        has_unit_mismatch=bool(row["has_unit_mismatch"]),
        detail=orjson.loads(row["detail_json"] or b"{}"),
    )


def run_stats(db_path: Path, run_id: str | None = None) -> dict[str, Any]:
    """Counts by outcome for a run, computed rather than stored."""
    run = run_id or latest_run_id(db_path)
    if run is None:
        return {}
    connection = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        by_outcome = dict(connection.execute(
            "SELECT outcome, count(*) FROM merge_outcomes WHERE run_id = ? "
            "GROUP BY outcome", (run,),
        ).fetchall())
        with_candidates = connection.execute(
            "SELECT count(*) FROM merge_outcomes WHERE run_id = ? AND outcome = ? "
            "AND has_flow_object_candidates = 1", (run, str(Outcome.UNMATCHED)),
        ).fetchone()[0]
        inconsistent = connection.execute(
            "SELECT count(*) FROM merge_outcomes WHERE run_id = ? "
            "AND has_context_inconsistency = 1", (run,),
        ).fetchone()[0]
    finally:
        connection.close()
    total = sum(by_outcome.values())
    unmatched = by_outcome.get(str(Outcome.UNMATCHED), 0)
    return {
        "run_id": run,
        "source_row_count": total,
        "prepared_match_count": by_outcome.get(str(Outcome.PREPARED), 0),
        "algorithm_match_count": by_outcome.get(str(Outcome.ALGORITHM), 0),
        "manual_addition_count": by_outcome.get(str(Outcome.MANUAL_ADDITION), 0),
        "created_flow_count": by_outcome.get(str(Outcome.CREATED), 0),
        "matched_count": total - unmatched,
        "unmatched_count": unmatched,
        "unmatched_with_flow_object_candidates_count": with_candidates,
        "unmatched_without_flow_object_candidates_count": unmatched - with_candidates,
        "prepared_context_inconsistency_count": inconsistent,
    }


class ConflictKind(StrEnum):
    """A disagreement between source lists about the same consensus flow."""

    #: Two lists mapped flows with different units onto one consensus flow.
    #: The consensus flow has one unit, so at least one mapping needs a
    #: conversion factor or is wrong.
    UNIT_DISAGREEMENT = "unit-disagreement"
    #: The same source flow uuid, present in two lists, was placed on different
    #: consensus flows.  Two releases of one list share most uuids, so this
    #: says the mapping moved -- deliberately or not.
    DIVERGENT_TARGET = "divergent-target"


def detect_conflicts(db_path: Path, run_id: str) -> list[dict[str, Any]]:
    """Find and record disagreements between the source lists of a run.

    Unreachable with a single source list, which is why the merge has never
    looked for these: with one list there is nothing to disagree with. Called
    once after every list has been merged, because a conflict is a property of
    the set rather than of any one list.
    """
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    try:
        create_merge_tables(connection)
        connection.execute("DELETE FROM merge_conflicts WHERE run_id = ?", (run_id,))
        rows = connection.execute(
            "SELECT list_name, list_version, source_uuid, source_name, source_unit, "
            "target_elementary_flow_id FROM merge_outcomes "
            "WHERE run_id = ? AND target_elementary_flow_id != '' ORDER BY rowid",
            (run_id,),
        ).fetchall()

        by_target: dict[str, list[sqlite3.Row]] = {}
        by_source_uuid: dict[str, list[sqlite3.Row]] = {}
        for row in rows:
            by_target.setdefault(row["target_elementary_flow_id"], []).append(row)
            by_source_uuid.setdefault(row["source_uuid"], []).append(row)

        conflicts: list[dict[str, Any]] = []

        for target, claimants in by_target.items():
            lists = {(r["list_name"], r["list_version"]) for r in claimants}
            if len(lists) < 2:
                continue
            units = {r["source_unit"] for r in claimants if r["source_unit"]}
            if len(units) > 1:
                conflicts.append({
                    "target_elementary_flow_id": target,
                    "kind": str(ConflictKind.UNIT_DISAGREEMENT),
                    "claimants": [_claimant(r) for r in claimants],
                })

        for source_uuid, appearances in by_source_uuid.items():
            lists = {(r["list_name"], r["list_version"]) for r in appearances}
            targets = {r["target_elementary_flow_id"] for r in appearances}
            if len(lists) > 1 and len(targets) > 1:
                conflicts.append({
                    "source_uuid": source_uuid,
                    "target_elementary_flow_id": sorted(targets)[0],
                    "kind": str(ConflictKind.DIVERGENT_TARGET),
                    "claimants": [_claimant(r) for r in appearances],
                })

        connection.executemany(
            insert_statement("merge_conflicts", _CONFLICT_COLUMNS),
            [(run_id, c["target_elementary_flow_id"], c["kind"],
              orjson.dumps(c["claimants"]).decode()) for c in conflicts],
        )
        connection.commit()
    finally:
        connection.close()
    if conflicts:
        logger.warning("merge_conflicts_detected", run_id=run_id, count=len(conflicts))
    return conflicts


def _claimant(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "list_name": row["list_name"],
        "list_version": row["list_version"],
        "source_uuid": row["source_uuid"],
        "source_name": row["source_name"],
        "source_unit": row["source_unit"],
        "target_elementary_flow_id": row["target_elementary_flow_id"],
    }


def read_conflicts(db_path: Path, run_id: str | None = None) -> list[dict[str, Any]]:
    run = run_id or latest_run_id(db_path)
    if run is None:
        return []
    connection = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        rows = connection.execute(
            "SELECT * FROM merge_conflicts WHERE run_id = ? ORDER BY rowid", (run,)
        ).fetchall()
    except sqlite3.OperationalError:
        return []
    finally:
        connection.close()
    return [
        {
            "target_elementary_flow_id": row["target_elementary_flow_id"],
            "kind": ConflictKind(row["kind"]),
            "claimants": orjson.loads(row["claimants_json"]),
        }
        for row in rows
    ]
