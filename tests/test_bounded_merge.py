"""`--max-rows` bounds the merge, and cannot do it quietly.

`--max-flows` bounds the transform and the merge went on matching every row of
every source list against the bounded consensus list -- all 9,850 ecoinvent
3.12 rows against a 400-flow list, which was 25.9 s of a 135 s verification run
on 2026-08-15 and the largest single stage in it.  Under `--max-rows 1000` the
same merge took 7.4 s.

The bound is the same rule the transform uses -- a prefix, plus any row named
with `--include-source-uuid`, because a prefix alone is a sample nobody chose.

The other half of this file is the half that matters more.  A bounded merge
produces smaller numbers for every merge measure there is, and a reader who
does not know the run was bounded reads those numbers as a regression.  So the
run records the limit and the rows the list ships beside the rows it read, and
`assess` refuses to record a baseline from it.
"""

from __future__ import annotations

import inspect
import sqlite3
import unittest
from functools import cache
from pathlib import Path
from tempfile import TemporaryDirectory

from brightway_flows.assessment.baseline import (
    Baseline,
    BaselineError,
    compare_to_baseline,
    write_baseline,
)
from brightway_flows.assessment.evaluate import Assessment
from brightway_flows.assessment.measures import RunIdentity, run_identity
from brightway_flows.assessment.report import terminal_lines
from brightway_flows.domain.flow import Flow
from brightway_flows.merge.store import (
    MergeRunInput,
    create_merge_tables,
    write_source_outcomes,
)
from brightway_flows.pipeline.engine import bounded_sample

from test_new_source_list_is_data import (
    FIXTURE_KEY,
    _consensus_flow,
    _flow_object,
    fixture_world,
    merge_fixture_list,
    outcomes,
    seed_consensus_database,
)

#: Three rows of one fixture list, in file order.  Distinct substances, so
#: nothing about which of them the merge reads depends on what the others are.
ROWS = [
    {
        "uuid": "fx-1",
        "name": "Carbon dioxide",
        "unit": "kg",
        "context": ["atmosphere"],
        "cas_number": "124-38-9",
        "source": FIXTURE_KEY,
    },
    {
        "uuid": "fx-2",
        "name": "Methane",
        "unit": "kg",
        "context": ["atmosphere"],
        "cas_number": "74-82-8",
        "source": FIXTURE_KEY,
    },
    {
        "uuid": "fx-3",
        "name": "Dinitrogen monoxide",
        "unit": "kg",
        "context": ["atmosphere"],
        "cas_number": "10024-97-2",
        "source": FIXTURE_KEY,
    },
]


def _run_inputs(db: Path, run_id: str) -> list[sqlite3.Row]:
    connection = sqlite3.connect(db)
    connection.row_factory = sqlite3.Row
    try:
        return list(
            connection.execute(
                "SELECT * FROM merge_run_inputs WHERE run_id = ?", (run_id,)
            )
        )
    finally:
        connection.close()


@cache
def _merged(max_rows: int | None = None, keep: tuple[str, ...] = ()) -> dict:
    """Merge the three fixture rows under one bound, and keep what it wrote.

    Cached, and read by both classes below: an end-to-end merge is the only
    way to state what the bound does to a run, and it costs about a second and
    a half.  Six tests asking the same three questions of the same three runs
    would pay for it six times.
    """
    bounds: dict = {}
    if max_rows is not None:
        bounds["max_rows"] = max_rows
    if keep:
        bounds["keep_uuids"] = list(keep)
    with fixture_world() as (_, db):
        _seeded_consensus()
        run_id, _ = merge_fixture_list(ROWS, **bounds)
        return {
            "uuids": [row["source_uuid"] for row in outcomes(db, run_id)],
            "inputs": [dict(row) for row in _run_inputs(db, run_id)],
        }


def _seeded_consensus() -> None:
    """A consensus flow for every fixture row.

    All three deliberately, so that no row of any bound reaches
    `create_flows_for_unmatched_rows`: creating a flow looks a substance up,
    and a test whose cost depends on whether a registry number happens to be
    in the cache is a test that sometimes goes to the network.  What is under
    test here is which rows the merge reads, which every row can show by being
    matched.
    """
    seed_consensus_database(
        [
            _flow_object("fo-co2", "Carbon dioxide", cas="124-38-9"),
            _flow_object("fo-ch4", "Methane", cas="74-82-8"),
            _flow_object("fo-n2o", "Dinitrogen monoxide", cas="10024-97-2"),
        ],
        [
            _consensus_flow("ef-co2", "fo-co2", "Carbon dioxide"),
            _consensus_flow("ef-ch4", "fo-ch4", "Methane"),
            _consensus_flow("ef-n2o", "fo-n2o", "Dinitrogen monoxide"),
        ],
    )


class BoundingTheMergeTestCase(unittest.TestCase):
    """End to end, because the claim is about what the merge reads."""

    def test_only_the_first_rows_are_merged(self):
        self.assertEqual(_merged(max_rows=1)["uuids"], ["fx-1"])

    def test_a_named_row_outside_the_prefix_is_merged_too(self):
        """The same rule as `--include-uuid`: named rows are added to the
        prefix rather than replacing it, so two runs stay comparable."""
        self.assertEqual(
            _merged(max_rows=1, keep=("fx-3",))["uuids"], ["fx-1", "fx-3"]
        )

    def test_naming_a_row_the_list_does_not_ship_raises(self):
        """A typo'd uuid that sampled silently would have the run report on the
        wrong rows, which is the defect the option exists to prevent."""
        with fixture_world():
            _seeded_consensus()
            with self.assertRaises(ValueError) as raised:
                merge_fixture_list(ROWS, max_rows=1, keep_uuids=["fx-404"])
        message = str(raised.exception)
        self.assertIn("--include-source-uuid", message)
        self.assertIn(FIXTURE_KEY, message)

    def test_an_unbounded_merge_reads_every_row(self):
        self.assertEqual(_merged()["uuids"], ["fx-1", "fx-2", "fx-3"])


class TheRunSaysItWasBoundedTestCase(unittest.TestCase):
    """Two numbers, not one flag: `1 of 3 rows` is the claim being made."""

    def test_the_limit_and_the_rows_available_are_recorded(self):
        inputs = _merged(max_rows=1)["inputs"]
        self.assertEqual(len(inputs), 1)
        self.assertEqual(inputs[0]["row_count"], 1)
        self.assertEqual(inputs[0]["available_row_count"], 3)
        self.assertEqual(inputs[0]["max_rows"], 1)

    def test_an_unbounded_merge_records_no_limit(self):
        """`max_rows` is null and the two counts agree, which is what makes a
        bounded run distinguishable rather than merely smaller."""
        inputs = _merged()["inputs"]
        self.assertIsNone(inputs[0]["max_rows"])
        self.assertEqual(inputs[0]["row_count"], 3)
        self.assertEqual(inputs[0]["available_row_count"], 3)

    def test_a_writer_that_says_nothing_about_the_bound_records_a_whole_list(self):
        """`MergeRunInput` is written by tests and by one caller.  A caller that
        knows nothing of bounding must not produce a row reading `3 of 0`."""
        with TemporaryDirectory() as directory:
            db = Path(directory) / "consensus-flows.sqlite3"
            connection = sqlite3.connect(db)
            create_merge_tables(connection)
            connection.commit()
            connection.close()
            write_source_outcomes(
                db,
                run_id="run-1",
                source_input=MergeRunInput(
                    run_id="run-1",
                    list_name="fixturelist",
                    list_version="1",
                    sequence=0,
                    row_count=3,
                ),
                outcomes=[],
            )
            inputs = _run_inputs(db, "run-1")
        self.assertEqual(inputs[0]["available_row_count"], 3)
        self.assertIsNone(inputs[0]["max_rows"])


class WhereTheBoundIsAppliedTestCase(unittest.TestCase):
    """Before the enrichment, not after.

    Enriching a row this run will not match is the same wasted derivation #88
    removed on the consensus side: the transformers run over every row handed
    to them, so a bound applied after them would save the matching and pay for
    the expensive half anyway.
    """

    def test_the_rows_are_bounded_before_they_are_enriched(self):
        from brightway_flows.merge.pipeline import merge_source_list

        source = inspect.getsource(merge_source_list)
        self.assertLess(
            source.index("bounded_sample"), source.index("_enrich_against_consensus")
        )


class TheSampleRuleIsTheOneTheTransformUsesTestCase(unittest.TestCase):
    """One function, told which option and which list to name.

    The message is half of what the option is for: a run that sampled without
    the row it was about would report on the wrong thing, and the report would
    look clean.
    """

    def setUp(self):
        self.flows = [
            Flow.from_dict({"uuid": f"u-{i}", "source": "fixturelist", "unit": "kg"})
            for i in range(5)
        ]

    def test_it_names_the_source_option_and_the_list(self):
        with self.assertRaises(ValueError) as raised:
            bounded_sample(
                self.flows,
                2,
                ["u-404"],
                option="--include-source-uuid",
                list_name="ecoinvent-3.12",
            )
        self.assertIn("--include-source-uuid", str(raised.exception))
        self.assertIn("ecoinvent-3.12", str(raised.exception))

    def test_the_transform_still_names_its_own(self):
        """The default is the wording the base list had before this was shared,
        so the message a `--max-flows` run prints did not change."""
        with self.assertRaises(ValueError) as raised:
            bounded_sample(self.flows, 2, ["u-404"])
        self.assertIn("--include-uuid", str(raised.exception))
        self.assertIn("the base list", str(raised.exception))


#: A database with the two tables `run_identity` reads, at the shape a build
#: writes them.  Hand-written rather than built by a run: what is under test is
#: how the columns are read, and a real run would take half an hour to produce
#: two rows of them.
_IDENTITY_SCHEMA = (
    """CREATE TABLE pipeline_runs (run_id TEXT PRIMARY KEY, timestamp TEXT NOT NULL,
       schema_version INTEGER NOT NULL, max_flows INTEGER)""",
    """CREATE TABLE merge_runs (run_id TEXT PRIMARY KEY, started_at TEXT NOT NULL,
       finished_at TEXT, schema_version INTEGER NOT NULL, stats_json TEXT)""",
    """CREATE TABLE merge_run_inputs (run_id TEXT NOT NULL, list_name TEXT NOT NULL,
       list_version TEXT NOT NULL, sequence INTEGER NOT NULL,
       row_count INTEGER NOT NULL DEFAULT 0,
       available_row_count INTEGER NOT NULL DEFAULT 0, max_rows INTEGER,
       PRIMARY KEY (run_id, list_name, list_version))""",
    # Empty, but present: the overview counts outcomes and conflicts for the
    # run it is describing, and a missing table there is a different question
    # from a bounded one.
    """CREATE TABLE merge_outcomes (run_id TEXT NOT NULL, list_name TEXT NOT NULL,
       list_version TEXT NOT NULL, source_uuid TEXT NOT NULL, outcome TEXT NOT NULL)""",
    """CREATE TABLE merge_conflicts (run_id TEXT NOT NULL,
       target_elementary_flow_id TEXT NOT NULL, kind TEXT NOT NULL,
       claimants_json TEXT NOT NULL)""",
)


def _identity_connection(max_rows: int | None, merged: int, available: int):
    connection = sqlite3.connect(":memory:")
    for statement in _IDENTITY_SCHEMA:
        connection.execute(statement)
    connection.execute(
        "INSERT INTO pipeline_runs (run_id, timestamp, schema_version) "
        "VALUES ('pipe-1', '2026-08-15T00:00:00+00:00', 1)"
    )
    connection.execute(
        "INSERT INTO merge_runs (run_id, started_at, schema_version) "
        "VALUES ('merge-1', '2026-08-15T00:00:00+00:00', 2)"
    )
    connection.execute(
        "INSERT INTO merge_run_inputs (run_id, list_name, list_version, sequence, "
        "row_count, available_row_count, max_rows) VALUES "
        "('merge-1', 'ecoinvent', '3.12', 0, ?, ?, ?)",
        (merged, available, max_rows),
    )
    return connection


class TheReviewAppSaysSoBeforeAnyCountTestCase(unittest.TestCase):
    """The overview already refuses to show a `--max-flows` build's counts
    without saying they are part of a list.  A bounded merge is the same claim
    about the merge's counts, so it is said in the same place: a curator
    reading "unmatched: 812" off a thousand-row sample is reading a number
    that means nothing.
    """

    def test_a_bounded_list_is_named_with_both_counts(self):
        from brightway_flows.webapps.app.queries.overview import load_merge

        connection = _identity_connection(max_rows=1000, merged=1000, available=21088)
        connection.row_factory = sqlite3.Row
        try:
            summary = load_merge(connection)
        finally:
            connection.close()
        self.assertEqual(
            summary.bounded_lists, [("ecoinvent", "3.12", 1000, 21088)]
        )

    def test_a_whole_merge_names_nothing(self):
        from brightway_flows.webapps.app.queries.overview import load_merge

        connection = _identity_connection(max_rows=None, merged=21088, available=21088)
        connection.row_factory = sqlite3.Row
        try:
            summary = load_merge(connection)
        finally:
            connection.close()
        self.assertEqual(summary.bounded_lists, [])


class ABoundedMergeCannotBecomeTheBaselineTestCase(unittest.TestCase):
    """`assess --record` from a bounded merge would record a prefix as the list.

    The same objection `--max-flows` already raised, on the axis the merge
    bounds: every `merge.*` measure would be recorded small, and the next full
    build would read as though thousands of rows had appeared from nowhere.
    """

    def test_a_bounded_run_is_named_in_the_identity(self):
        connection = _identity_connection(max_rows=400, merged=400, available=21088)
        try:
            identity = run_identity(connection)
        finally:
            connection.close()
        self.assertEqual(
            identity.bounded_sources, ("ecoinvent-3.12: 400 of 21088 rows",)
        )

    def test_a_whole_run_names_nothing(self):
        connection = _identity_connection(max_rows=None, merged=21088, available=21088)
        try:
            identity = run_identity(connection)
        finally:
            connection.close()
        self.assertEqual(identity.bounded_sources, ())

    def test_a_database_without_the_column_is_read_as_unbounded(self):
        """The merge tables are `IF NOT EXISTS` and outlive the run that wrote
        them, so a database from before this change is still asked."""
        connection = sqlite3.connect(":memory:")
        for statement in _IDENTITY_SCHEMA:
            connection.execute(
                statement.replace(
                    "available_row_count INTEGER NOT NULL DEFAULT 0, max_rows INTEGER,",
                    "",
                )
            )
        connection.execute(
            "INSERT INTO merge_runs (run_id, started_at, schema_version) "
            "VALUES ('merge-1', '2026-08-15T00:00:00+00:00', 1)"
        )
        connection.execute(
            "INSERT INTO merge_run_inputs (run_id, list_name, list_version, "
            "sequence, row_count) VALUES ('merge-1', 'ecoinvent', '3.12', 0, 21088)"
        )
        try:
            identity = run_identity(connection)
        finally:
            connection.close()
        self.assertEqual(identity.bounded_sources, ())

    def test_recording_a_baseline_from_one_raises(self):
        assessment = Assessment(
            database="test.sqlite3",
            run=RunIdentity(bounded_sources=("ecoinvent-3.12: 400 of 21088 rows",)),
        )
        with TemporaryDirectory() as directory:
            with self.assertRaises(BaselineError) as raised:
                write_baseline(assessment, Path(directory))
        self.assertIn("--max-rows", str(raised.exception))

    def test_comparing_one_against_a_full_baseline_says_it_cannot(self):
        assessment = Assessment(
            database="test.sqlite3",
            run=RunIdentity(bounded_sources=("ecoinvent-3.12: 400 of 21088 rows",)),
        )
        comparison = compare_to_baseline(
            assessment,
            Baseline(measures={"merge.matched": 9000}, path="baseline.json"),
        )
        self.assertIn("--max-rows", comparison.incomparable)

    def test_the_report_says_so_where_a_reader_will_see_it(self):
        assessment = Assessment(
            database="test.sqlite3",
            run=RunIdentity(bounded_sources=("ecoinvent-3.12: 400 of 21088 rows",)),
        )
        banner = [line for line in terminal_lines(assessment) if "--max-rows" in line]
        self.assertEqual(len(banner), 1)
        self.assertIn("400 of 21088 rows", banner[0])


if __name__ == "__main__":
    unittest.main()
