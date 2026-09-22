"""A build records where its time went, without becoming a difference itself.

Nothing in the pipeline measured its own stages, so the question "what should
we make faster" was answered from outside with a stopwatch: extraction 61 s, a
400-flow base-only build 42 s, a whole verification build 135 s.  A stopwatch
outside the process cannot say which of twenty-odd transformers spent those
135 seconds -- and on the first run that could, the largest stages were the
merge's enrichment at 21.7 s and one transformer's `setup()` at 8.4 s.

The awkward part is that a duration is the one number a build produces that
*must* differ between two runs of identical code, while `tools/verify_run.py`
verifies a change by requiring every artifact to be identical.  The two are
reconciled by where the durations are put: their own table, whose value column
is called `duration_seconds`, which is a name the harness already masks.  That
coupling is invisible from either side, so it is asserted here.
"""

from __future__ import annotations

import importlib.util
import sqlite3
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from brightway_flows.domain.flow import Flow
from brightway_flows.pipeline.engine import apply_transformers
from brightway_flows.pipeline.review_records import StageTiming
from brightway_flows.pipeline.review_tables import (
    TABLES,
    create_review_tables,
    write_run_timings,
)
from brightway_flows.pipeline.timings import RunTimings
from brightway_flows.sources import base_source_list

REPO_ROOT = Path(__file__).resolve().parent.parent


def _verify_run():
    spec = importlib.util.spec_from_file_location(
        "_verify_run", REPO_ROOT / "tools" / "verify_run.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules["_verify_run"] = module
    spec.loader.exec_module(module)
    return module


def _timings_in(db: Path) -> list[tuple]:
    connection = sqlite3.connect(db)
    try:
        return list(
            connection.execute(
                "SELECT stage, detail, duration_seconds FROM run_timings "
                "ORDER BY stage, detail"
            )
        )
    finally:
        connection.close()


class RecordingAStageTestCase(unittest.TestCase):
    def test_a_stage_that_runs_twice_is_one_row(self):
        """`merge` over three lists is three merges of one stage, and a reader
        summing rows to get the total would be doing the recorder's job."""
        timings = RunTimings()
        timings.record("merge", 1.0, detail="ecoinvent-3.12")
        timings.record("merge", 2.0, detail="ecoinvent-3.12")
        self.assertEqual(
            timings.records(),
            [StageTiming(stage="merge", detail="ecoinvent-3.12", duration_seconds=3.0)],
        )

    def test_detail_is_what_keeps_two_lists_apart(self):
        timings = RunTimings()
        timings.record("merge", 1.0, detail="ecoinvent-3.12")
        timings.record("merge", 2.0, detail="bafu-2026-v1")
        self.assertEqual(
            [(row.detail, row.duration_seconds) for row in timings.records()],
            [("ecoinvent-3.12", 1.0), ("bafu-2026-v1", 2.0)],
        )

    def test_a_stage_that_raises_is_still_recorded(self):
        """The stage that dies is the one whose cost is most worth knowing."""
        timings = RunTimings()
        with self.assertRaises(ValueError):
            with timings.stage("resolve_flow_layers"):
                raise ValueError("boom")
        self.assertEqual([row.stage for row in timings.records()], ["resolve_flow_layers"])

    def test_the_slowest_come_first(self):
        timings = RunTimings()
        timings.record("cheap", 0.5)
        timings.record("dear", 30.0)
        timings.record("middling", 4.0)
        self.assertEqual(
            [row.stage for row in timings.slowest(2)], ["dear", "middling"]
        )

    def test_the_total_is_of_what_was_measured(self):
        timings = RunTimings()
        timings.record("one", 1.5)
        timings.record("two", 2.25)
        self.assertEqual(timings.total_seconds(), 3.75)


class _CountingTransformer:
    """A transformer that proposes nothing, so only its own cost is timed."""

    answers_per_flow = True

    def __init__(self, name: str) -> None:
        self.name = name

    def setup(self) -> None:  # pragma: no cover - nothing to load
        ...

    def transform(self, flows):
        return []


class EveryTransformerIsAStageTestCase(unittest.TestCase):
    """Per transformer, because "the transform took 26 minutes" names no step."""

    def test_each_transformer_gets_a_row_under_the_stage_it_ran_in(self):
        timings = RunTimings()
        apply_transformers(
            [_CountingTransformer("first"), _CountingTransformer("second")],
            [Flow.from_dict({"uuid": "u-1", "source": "EF 3.1", "unit": "kg"})],
            source_list=base_source_list(),
            timings=timings,
        )
        self.assertEqual(
            [(row.stage, row.detail) for row in timings.records()],
            [("transform", "first"), ("transform", "second")],
        )

    def test_the_merge_enrichment_is_a_stage_of_its_own(self):
        """The same transformer costs different amounts over the base list and
        over a source list, and one row for both would describe neither."""
        timings = RunTimings()
        apply_transformers(
            [_CountingTransformer("first")],
            [Flow.from_dict({"uuid": "u-1", "source": "EF 3.1", "unit": "kg"})],
            source_list=base_source_list(),
            timings=timings,
            timing_stage="merge_enrich_transformer",
        )
        self.assertEqual(
            [row.stage for row in timings.records()], ["merge_enrich_transformer"]
        )

    def test_a_caller_with_no_recorder_still_runs(self):
        """Every existing call site passes nothing, and gets a recorder that
        logs and keeps nothing rather than a branch around the timing."""
        changes = apply_transformers(
            [_CountingTransformer("first")],
            [Flow.from_dict({"uuid": "u-1", "source": "EF 3.1", "unit": "kg"})],
            source_list=base_source_list(),
        )
        self.assertEqual(changes, [])


class WritingTheTableTestCase(unittest.TestCase):
    def setUp(self):
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.db = Path(self.directory.name) / "consensus-flows.sqlite3"
        connection = sqlite3.connect(self.db)
        create_review_tables(connection)
        connection.commit()
        connection.close()

    def test_the_rows_are_written(self):
        write_run_timings(
            self.db,
            timings=[
                StageTiming(stage="merge", detail="ecoinvent-3.12", duration_seconds=12.5),
                StageTiming(stage="transform", detail="chebi", duration_seconds=3.25),
            ],
        )
        self.assertEqual(
            _timings_in(self.db),
            [("merge", "ecoinvent-3.12", 12.5), ("transform", "chebi", 3.25)],
        )

    def test_writing_again_replaces_the_table(self):
        """`build` writes once at the end over what the transform wrote partway
        through, so the second write is the whole account and not an addition
        to a stale one."""
        write_run_timings(
            self.db, timings=[StageTiming(stage="transform", duration_seconds=1.0)]
        )
        write_run_timings(
            self.db,
            timings=[
                StageTiming(stage="transform", duration_seconds=2.0),
                StageTiming(stage="merge", duration_seconds=5.0),
            ],
        )
        self.assertEqual(
            _timings_in(self.db), [("merge", "", 5.0), ("transform", "", 2.0)]
        )

    def test_a_database_without_the_table_is_reported_not_crashed(self):
        with TemporaryDirectory() as directory:
            empty = Path(directory) / "empty.sqlite3"
            sqlite3.connect(empty).close()
            write_run_timings(
                empty, timings=[StageTiming(stage="merge", duration_seconds=1.0)]
            )

    def test_the_table_is_one_a_build_recreates(self):
        """In `TABLES`, so it is dropped and rewritten with the rest rather than
        accumulating one run's stages under the next run's."""
        self.assertIn("run_timings", TABLES)


class ItCannotBecomeAnArtifactDifferenceTestCase(unittest.TestCase):
    """The coupling that makes the whole thing safe, asserted from both ends.

    `verify_run.dump_table` masks a cell whose *column name* is in
    `VOLATILE_KEYS`.  So the timing column has to be called one of those names,
    and if either side is renamed without the other, every comparison starts
    reporting a difference for a clock tick -- which is the quickest way to
    make a verification harness stop being run.
    """

    def test_the_duration_column_is_one_the_harness_masks(self):
        tool = _verify_run()
        self.assertIn("duration_seconds", tool.VOLATILE_KEYS)

    def test_the_table_writes_that_column(self):
        from brightway_flows.pipeline.review_tables import _TIMING_COLUMNS

        self.assertIn("duration_seconds", _TIMING_COLUMNS)

    def test_two_runs_of_the_same_code_dump_the_same_rows(self):
        """The stages are compared and the durations are not, so a table that
        differs says a stage appeared or disappeared."""
        tool = _verify_run()
        dumps = []
        for seconds in (1.0, 99.0):
            with TemporaryDirectory() as directory:
                db = Path(directory) / "consensus-flows.sqlite3"
                connection = sqlite3.connect(db)
                create_review_tables(connection)
                connection.commit()
                connection.close()
                write_run_timings(
                    db,
                    timings=[
                        StageTiming(
                            stage="merge",
                            detail="ecoinvent-3.12",
                            duration_seconds=seconds,
                        )
                    ],
                )
                connection = sqlite3.connect(db)
                try:
                    dumps.append(tool.dump_table(connection, "run_timings", str(db)))
                finally:
                    connection.close()
        self.assertEqual(dumps[0], dumps[1])
        self.assertIn(b"ecoinvent-3.12", dumps[0])


if __name__ == "__main__":
    unittest.main()
