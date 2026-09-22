"""What the last build did, and what it is waiting on a curator for.

Pure functions over a connection, returning dataclasses.  No Flask import here
deliberately: the applications this replaces are testable only through a Flask
test client, which is why `run_report` is the only one with tests.

Every count is a `SELECT count(*)`, not a fetch-and-len.  The page is the first
thing a curator opens and the database is 3.5 GB.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field

import orjson

from brightway_flows.merge.store import Outcome
from brightway_flows.pipeline.review_records import ElementStatus, Severity
from brightway_flows.webapps.app.db import column_exists, count, table_exists


@dataclass
class TransformRun:
    """The `pipeline_runs` row, or the absence of one.

    `exists` is False for a database written before Phase 0 added the table, as
    well as for one no build has filled.  Both mean the same thing to a reader --
    this database cannot say what produced it -- and neither is an error.
    """

    exists: bool = False
    run_id: str = ""
    timestamp: str = ""
    flow_count: int = 0
    change_count: int = 0
    input_files: list[str] = field(default_factory=list)
    transformer_names: list[str] = field(default_factory=list)
    max_flows: int | None = None
    dry_run: bool = False

    @property
    def input_names(self) -> list[str]:
        """The inputs by file name, without the directory they were read from.

        `ef-31-flows.json` rather than `/home/somebody/.local/share/...`: which
        list went into the run is a fact about the run and belongs on the page;
        where that machine keeps its data directory is a fact about the machine
        and belongs to whoever administers it.  The whole path was printed on
        the front page of a site published to the internet.
        """
        return [str(path).rsplit("/", 1)[-1] for path in self.input_files if path]

    @property
    def is_bounded(self) -> bool:
        """Whether the run processed only part of the input.

        Worth saying on the page: every count below is a count over a partial
        build, and a curator reading "203 blocked decisions" off a 400-flow
        smoke run would be reading a number that means nothing.
        """
        return self.max_flows is not None


@dataclass
class QueueSummary:
    """One decision queue, and how much of it is blocking."""

    name: str
    total: int
    blocking: int


@dataclass
class MergeSummary:
    """What the merge did, per source list and per outcome."""

    exists: bool = False
    run_id: str = ""
    started_at: str = ""
    finished_at: str = ""
    #: `(list name, version, rows)`, in the order the run consumed them.
    inputs: list[tuple[str, str, int]] = field(default_factory=list)
    outcomes: dict[str, int] = field(default_factory=dict)
    conflicts: int = 0
    #: `(list name, version, rows read, rows the list ships)` for each list the
    #: run was asked to bound with `--max-rows`.  Said on the page for the same
    #: reason `RunRecord.is_bounded` is: every outcome count below is a count
    #: over the rows that were read, and a curator reading "9,614 unmatched"
    #: off a thousand-row sample is reading a number that means nothing.
    bounded_lists: list[tuple[str, str, int, int]] = field(default_factory=list)

    @property
    def unmatched(self) -> int:
        return self.outcomes.get(str(Outcome.UNMATCHED), 0)

    @property
    def total(self) -> int:
        return sum(self.outcomes.values())


@dataclass
class ContentCounts:
    """How much is in the published layer.

    None where the table is absent, so the template can say "not in this
    database" rather than "0" -- which would read as an empty consensus list.
    """

    flow_objects: int | None = None
    elementary_flows: int | None = None
    changes: int | None = None
    provenance_activities: int | None = None


@dataclass
class CheckSummary:
    """The quality checks that are precomputed, and what they found."""

    formula_mismatches: int | None = None
    uncovered_elements: int | None = None
    covered_elements: int | None = None

    @property
    def total_elements(self) -> int | None:
        if self.uncovered_elements is None or self.covered_elements is None:
            return None
        return self.uncovered_elements + self.covered_elements


@dataclass
class StageTally:
    """One stage of the run, and what it counted.

    These were logged and dropped (#232). A run-over-run comparison of them is
    the cheapest regression detector this project has: "386 of 387 objects
    typed" falling to 340 is a bug in the typing rules that nothing else would
    notice, and `tools/verify_run.py` -- which diffs whole artifacts -- is a
    much blunter instrument for the same question.
    """

    stage: str
    counts: list[tuple[str, int]] = field(default_factory=list)

    @property
    def total(self) -> int:
        return sum(value for _, value in self.counts)


@dataclass
class Overview:
    """Everything the front page shows, in one object.

    One object rather than six template arguments, so that adding a number to
    the page is a field here and a line in the template, and the view stays a
    single call.
    """

    run: TransformRun
    content: ContentCounts
    queues: list[QueueSummary]
    checks: CheckSummary
    merge: MergeSummary
    stages: list[StageTally] = field(default_factory=list)

    @property
    def blocking_total(self) -> int:
        return sum(queue.blocking for queue in self.queues)

    @property
    def needs_a_curator(self) -> bool:
        """Whether anything is waiting on a decision.

        The merge's unmatched rows count: a source flow nothing could place is
        a decision someone has to make, the same as a blocked rename.
        """
        return bool(self.blocking_total or self.merge.unmatched)


def load_stage_tallies(connection: sqlite3.Connection) -> list[StageTally]:
    """What each stage of the run counted, in the order the run ran them.

    Order is stored, not alphabetical: the reader is following the run, and
    `assign_semantic_types` before `resolve_flow_layers` would describe a
    pipeline that does not exist.
    """
    if not table_exists(connection, "run_stats"):
        return []
    tallies: dict[str, StageTally] = {}
    for row in connection.execute(
        "SELECT stage, key, value FROM run_stats ORDER BY rowid"
    ):
        tally = tallies.setdefault(row["stage"], StageTally(stage=row["stage"]))
        tally.counts.append((row["key"], int(row["value"])))
    return list(tallies.values())


def load_transform_run(connection: sqlite3.Connection) -> TransformRun:
    if not table_exists(connection, "pipeline_runs"):
        return TransformRun()
    row = connection.execute("SELECT * FROM pipeline_runs LIMIT 1").fetchone()
    if row is None:
        return TransformRun()
    return TransformRun(
        exists=True,
        run_id=row["run_id"],
        timestamp=row["timestamp"],
        flow_count=row["flow_count"],
        change_count=row["change_count"],
        input_files=orjson.loads(row["input_files_json"]),
        transformer_names=orjson.loads(row["transformer_names_json"]),
        max_flows=row["max_flows"],
        dry_run=bool(row["dry_run"]),
    )


def load_content_counts(connection: sqlite3.Connection) -> ContentCounts:
    return ContentCounts(
        flow_objects=count(connection, "flow_objects"),
        elementary_flows=count(connection, "elementary_flows"),
        changes=count(connection, "changelog"),
        provenance_activities=count(connection, "provenance_activities"),
    )


def load_queues(connection: sqlite3.Connection) -> list[QueueSummary]:
    """Every queue with at least one item, most-blocking first.

    Queues with nothing in them are left out rather than listed as zero. A
    curator opens this page to find work; a list of empty queues is chrome.
    """
    if not table_exists(connection, "review_queue"):
        return []
    rows = connection.execute(
        "SELECT queue_name, count(*) AS total, "
        "sum(CASE WHEN severity = ? THEN 1 ELSE 0 END) AS blocking "
        "FROM review_queue GROUP BY queue_name",
        (str(Severity.BLOCKING),),
    ).fetchall()
    summaries = [
        QueueSummary(
            name=row["queue_name"],
            total=int(row["total"]),
            blocking=int(row["blocking"] or 0),
        )
        for row in rows
    ]
    summaries.sort(key=lambda queue: (-queue.blocking, -queue.total, queue.name))
    return summaries


def load_checks(connection: sqlite3.Connection) -> CheckSummary:
    summary = CheckSummary(
        formula_mismatches=count(connection, "formula_mismatches"),
    )
    if table_exists(connection, "element_coverage"):
        rows = connection.execute(
            "SELECT status, count(*) AS n FROM element_coverage GROUP BY status"
        ).fetchall()
        by_status = {row["status"]: int(row["n"]) for row in rows}
        summary.covered_elements = by_status.pop(str(ElementStatus.LINKED), 0)
        summary.uncovered_elements = sum(by_status.values())
    return summary


def load_merge(connection: sqlite3.Connection) -> MergeSummary:
    """The most recent merge run.

    Most recent rather than "the" run because `merge_runs` accumulates: the
    transform rewrites the database, but a merge opened against an existing one
    adds a row. In practice `build` produces one, and this shows that one.
    """
    if not table_exists(connection, "merge_runs"):
        return MergeSummary()
    row = connection.execute(
        "SELECT * FROM merge_runs ORDER BY started_at DESC, rowid DESC LIMIT 1"
    ).fetchone()
    if row is None:
        return MergeSummary()

    run_id = row["run_id"]
    inputs = [
        (source["list_name"], source["list_version"], int(source["row_count"] or 0))
        for source in connection.execute(
            "SELECT list_name, list_version, row_count FROM merge_run_inputs "
            "WHERE run_id = ? ORDER BY sequence",
            (run_id,),
        )
    ]
    # Guarded on the column, not the table: these rows outlive the run that
    # wrote them, so a database holding a merge from before the merge could be
    # bounded is still read here.
    bounded_lists = [
        (
            source["list_name"],
            source["list_version"],
            int(source["row_count"] or 0),
            int(source["available_row_count"] or 0),
        )
        for source in connection.execute(
            "SELECT list_name, list_version, row_count, available_row_count "
            "FROM merge_run_inputs WHERE run_id = ? AND max_rows IS NOT NULL "
            "ORDER BY sequence",
            (run_id,),
        )
    ] if column_exists(connection, "merge_run_inputs", "max_rows") else []
    outcomes = {
        outcome["outcome"]: int(outcome["n"])
        for outcome in connection.execute(
            "SELECT outcome, count(*) AS n FROM merge_outcomes WHERE run_id = ? "
            "GROUP BY outcome",
            (run_id,),
        )
    }
    conflicts = int(
        connection.execute(
            "SELECT count(*) FROM merge_conflicts WHERE run_id = ?", (run_id,)
        ).fetchone()[0]
    )
    return MergeSummary(
        exists=True,
        run_id=run_id,
        bounded_lists=bounded_lists,
        started_at=row["started_at"] or "",
        finished_at=row["finished_at"] or "",
        inputs=inputs,
        outcomes=outcomes,
        conflicts=conflicts,
    )


def load_overview(connection: sqlite3.Connection) -> Overview:
    """The whole front page in one call."""
    return Overview(
        run=load_transform_run(connection),
        content=load_content_counts(connection),
        queues=load_queues(connection),
        checks=load_checks(connection),
        merge=load_merge(connection),
        stages=load_stage_tallies(connection),
    )
