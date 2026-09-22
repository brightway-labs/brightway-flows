"""A run's outcomes, keyed so that one source flow has one outcome.

The JSON report had no key, so nothing stated -- let alone enforced -- that a
source flow gets exactly one outcome, and the shape could not express a second
source list without a second file. It was also redundant: `unmatched` and the
two enriched lists held the same 9,614 rows, differing only in a boolean.

Measured on a real run before the primary key was asserted: 9,850 distinct
source flows, each in exactly one of the four outcomes; the enriched pair an
exact partition of `unmatched`; and every prepared-context inconsistency also a
prepared match. These tests hold that shape in place.
"""

import sqlite3
import tempfile
import unittest
from pathlib import Path

from brightway_flows.merge.report import (
    AlgorithmMatch,
    CreatedFlow,
    PreparedMatch,
    UnmatchedRow,
)
from brightway_flows.sources import known_source_lists, resolve_source_list
from brightway_flows.merge.store import (
    MergeOutcome,
    create_merge_tables,
    MergeRunInput,
    Outcome,
    latest_run_id,
    read_outcomes,
    ConflictKind,
    detect_conflicts,
    read_conflicts,
    run_stats,
    start_run,
    write_merge_run,
    write_source_outcomes,
)

SOURCE = resolve_source_list("ecoinvent-3.12")


def unmatched_row(uuid, reason="no-flow-object-candidate"):
    return UnmatchedRow(
        source_uuid=uuid, source_name=f"name-{uuid}", source_context=["air"],
        source_unit="kg", source_cas="", source_ec="", reason=reason,
    )


def prepared_row(uuid):
    return PreparedMatch(
        source_uuid=uuid, source_name=f"name-{uuid}", source_context=["air"],
        source_context_iri="https://example.org/context/envi-air-unkn",
        source_unit="kg", source_cas="", target_elementary_flow_id="ef-1",
        prepared_target_elementary_flow_id="ef-1", target_flow_object_id="fo-1",
        target_name="target", target_context=["air"], target_unit="kg",
        prepared_target_resolution="direct", prepared_target_trace=[],
        prepared_context_decision="", provenance={},
    )


def created_row(uuid):
    return CreatedFlow(
        source_uuid=uuid, source_name=f"name-{uuid}", source_context=["air"],
        source_context_iri="ctx-1", source_unit="kg", source_cas="7803-63-6",
        source_ec="", flow_object_id="fo-3", flow_object_label="target",
        flow_object_cas=["7803-63-6"], flow_object_ec=[],
        new_elementary_flow_id="ef-3", minted_flow_object=True,
        identity_is_name_only=False, provenance={},
    )


def algorithm_row(uuid):
    return AlgorithmMatch(
        source_uuid=uuid, source_name=f"name-{uuid}", source_context=["air"],
        source_context_normalized=(), source_context_iri="", source_unit="kg",
        source_cas="7732-18-5", source_ec="", flow_object_id="fo-2",
        target_name="target", target_elementary_flow_id="ef-2",
        target_context=["air"], target_unit="kg", basis="cas",
        basis_value="7732-18-5", selector_reason="", matching_method="cas",
        algorithm_details={}, provenance={},
    )


class CreatedFlowIsItsOwnOutcomeTestCase(unittest.TestCase):
    """A created flow is neither an addition nor a row that stayed unmatched.

    It carries the same `source` string as the two additions, because the sync
    selects the flows to write by comparing against that constant. The outcome
    is where the three are told apart, so it has to be a value of its own.
    """

    def test_the_outcome_is_created(self):
        outcome = MergeOutcome.from_created("run-1", SOURCE, created_row("u-1"))
        self.assertEqual(outcome.outcome, Outcome.CREATED)
        self.assertEqual(outcome.flow_object_id, "fo-3")
        self.assertEqual(outcome.target_elementary_flow_id, "ef-3")
        self.assertEqual(outcome.matching_method, "flow_object_creation")

    def test_reason_stays_empty_because_the_row_was_placed(self):
        """`reason` is why a row could not be placed.  This one was."""
        outcome = MergeOutcome.from_created("run-1", SOURCE, created_row("u-1"))
        self.assertEqual(outcome.reason, "")

    def test_the_record_is_kept_whole_in_detail(self):
        outcome = MergeOutcome.from_created("run-1", SOURCE, created_row("u-1"))
        self.assertEqual(outcome.detail["flow_object_cas"], ["7803-63-6"])
        self.assertIs(outcome.detail["identity_is_name_only"], False)
        self.assertIs(outcome.detail["minted_flow_object"], True)


class StoreTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db = Path(self._tmp.name) / "consensus.sqlite3"
        self.addCleanup(self._tmp.cleanup)

    def write(self, outcomes, run_id="run-1", row_count=0):
        write_merge_run(
            self.db, run_id=run_id,
            started_at="2026-01-01T00:00:00Z", finished_at="2026-01-01T00:01:00Z",
            inputs=[MergeRunInput(
                run_id=run_id, list_name=SOURCE.list_name,
                list_version=SOURCE.list_version, sequence=0,
                row_count=row_count or len(outcomes),
            )],
            outcomes=outcomes, stats={},
        )


class OneOutcomePerSourceFlowTestCase(StoreTestCase):
    def test_the_same_source_flow_twice_in_one_run_is_rejected(self):
        """The invariant the JSON report could not state."""
        rows = [
            MergeOutcome.from_unmatched(
                "run-1", SOURCE, unmatched_row("u-1"), has_candidates=False),
            MergeOutcome.from_algorithm("run-1", SOURCE, algorithm_row("u-1")),
        ]
        with self.assertRaises(sqlite3.IntegrityError):
            self.write(rows)

    def test_the_same_source_flow_in_two_runs_is_fine(self):
        row = unmatched_row("u-1")
        self.write([MergeOutcome.from_unmatched("run-1", SOURCE, row,
                                                has_candidates=False)], run_id="run-1")
        self.write([MergeOutcome.from_unmatched("run-2", SOURCE, row,
                                                has_candidates=True)], run_id="run-2")
        self.assertEqual(len(read_outcomes(self.db, run_id="run-1")), 1)
        self.assertEqual(len(read_outcomes(self.db, run_id="run-2")), 1)

    def test_the_same_source_uuid_from_two_lists_is_fine(self):
        """Two source lists may legitimately use the same uuid.

        Two ecoinvent releases share most of their flow uuids, so this is the
        normal case rather than an edge one.
        """
        other = known_source_lists()["ecoinvent-3.11"]
        write_merge_run(
            self.db, run_id="run-1", started_at="t", finished_at="t",
            inputs=[
                MergeRunInput(run_id="run-1", list_name=SOURCE.list_name,
                              list_version=SOURCE.list_version, sequence=0),
                MergeRunInput(run_id="run-1", list_name=other.list_name,
                              list_version=other.list_version, sequence=1),
            ],
            outcomes=[
                MergeOutcome.from_unmatched("run-1", SOURCE, unmatched_row("u-1"),
                                            has_candidates=False),
                MergeOutcome.from_unmatched("run-1", other, unmatched_row("u-1"),
                                            has_candidates=False),
            ],
            stats={},
        )
        self.assertEqual(len(read_outcomes(self.db)), 2)

    def test_outcomes_for_an_undeclared_source_list_are_refused(self):
        """Silently dropping them is how data goes missing without a trace."""
        other = known_source_lists()["ecoinvent-3.11"]
        with self.assertRaises(ValueError) as ctx:
            self.write([MergeOutcome.from_unmatched(
                "run-1", other, unmatched_row("u-1"), has_candidates=False)])
        self.assertIn("3.11", str(ctx.exception))


class QueriesReplaceTheOldListsTestCase(StoreTestCase):
    """The report's three unmatched lists are one table and three queries."""

    def setUp(self):
        super().setUp()
        self.write([
            MergeOutcome.from_prepared("run-1", SOURCE, prepared_row("p-1"),
                                       inconsistent=True),
            MergeOutcome.from_prepared("run-1", SOURCE, prepared_row("p-2")),
            MergeOutcome.from_algorithm("run-1", SOURCE, algorithm_row("a-1")),
            MergeOutcome.from_unmatched("run-1", SOURCE, unmatched_row("w-1"),
                                        has_candidates=True),
            MergeOutcome.from_unmatched("run-1", SOURCE, unmatched_row("n-1"),
                                        has_candidates=False),
            MergeOutcome.from_unmatched("run-1", SOURCE, unmatched_row("n-2"),
                                        has_candidates=False),
        ])

    def test_all_unmatched(self):
        rows = read_outcomes(self.db, outcome=Outcome.UNMATCHED)
        self.assertEqual([r.source_uuid for r in rows], ["w-1", "n-1", "n-2"])

    def test_unmatched_with_candidates(self):
        rows = read_outcomes(self.db, outcome=Outcome.UNMATCHED,
                             has_flow_object_candidates=True)
        self.assertEqual([r.source_uuid for r in rows], ["w-1"])

    def test_unmatched_without_candidates(self):
        rows = read_outcomes(self.db, outcome=Outcome.UNMATCHED,
                             has_flow_object_candidates=False)
        self.assertEqual([r.source_uuid for r in rows], ["n-1", "n-2"])

    def test_the_two_queries_partition_the_unmatched_rows(self):
        """As they did in the report, where it cost 9,614 duplicated rows."""
        every = {r.source_uuid for r in read_outcomes(self.db, outcome=Outcome.UNMATCHED)}
        with_ = {r.source_uuid for r in read_outcomes(
            self.db, outcome=Outcome.UNMATCHED, has_flow_object_candidates=True)}
        without = {r.source_uuid for r in read_outcomes(
            self.db, outcome=Outcome.UNMATCHED, has_flow_object_candidates=False)}
        self.assertEqual(with_ | without, every)
        self.assertEqual(with_ & without, set())

    def test_context_inconsistency_annotates_a_prepared_match(self):
        """It is not a fifth outcome: every one is also a prepared match."""
        prepared = read_outcomes(self.db, outcome=Outcome.PREPARED)
        flagged = [r for r in prepared if r.has_context_inconsistency]
        self.assertEqual([r.source_uuid for r in flagged], ["p-1"])

    def test_stats_are_counted_from_the_rows(self):
        """Counts cannot disagree with the rows beside them, as they could when
        they were a stored `stats` block."""
        stats = run_stats(self.db)
        self.assertEqual(stats["source_row_count"], 6)
        self.assertEqual(stats["prepared_match_count"], 2)
        self.assertEqual(stats["algorithm_match_count"], 1)
        self.assertEqual(stats["unmatched_count"], 3)
        self.assertEqual(stats["unmatched_with_flow_object_candidates_count"], 1)
        self.assertEqual(stats["unmatched_without_flow_object_candidates_count"], 2)
        self.assertEqual(stats["prepared_context_inconsistency_count"], 1)
        self.assertEqual(stats["matched_count"], 3)


class RunLifecycleTestCase(StoreTestCase):
    def test_rewriting_a_run_replaces_it_rather_than_accumulating(self):
        self.write([MergeOutcome.from_unmatched(
            "run-1", SOURCE, unmatched_row("u-1"), has_candidates=False)])
        self.write([MergeOutcome.from_unmatched(
            "run-1", SOURCE, unmatched_row("u-2"), has_candidates=False)])
        rows = read_outcomes(self.db, run_id="run-1")
        self.assertEqual([r.source_uuid for r in rows], ["u-2"])

    def test_reads_default_to_the_latest_run(self):
        self.write([MergeOutcome.from_unmatched(
            "old", SOURCE, unmatched_row("u-1"), has_candidates=False)], run_id="old")
        write_merge_run(
            self.db, run_id="new", started_at="2026-06-01T00:00:00Z",
            finished_at="2026-06-01T00:01:00Z",
            inputs=[MergeRunInput(run_id="new", list_name="ecoinvent",
                                  list_version="3.12", sequence=0)],
            outcomes=[MergeOutcome.from_unmatched(
                "new", SOURCE, unmatched_row("u-2"), has_candidates=False)],
            stats={},
        )
        self.assertEqual(latest_run_id(self.db), "new")
        self.assertEqual([r.source_uuid for r in read_outcomes(self.db)], ["u-2"])

    def test_reading_a_database_with_no_runs_is_empty_not_an_error(self):
        sqlite3.connect(self.db).close()
        self.assertIsNone(latest_run_id(self.db))
        self.assertEqual(read_outcomes(self.db), [])
        self.assertEqual(run_stats(self.db), {})

    def test_merge_order_is_recorded(self):
        """With several lists, which went first is part of what happened."""
        write_merge_run(
            self.db, run_id="run-1", started_at="t", finished_at="t",
            inputs=[
                MergeRunInput(run_id="run-1", list_name="ecoinvent",
                              list_version="3.12", sequence=0, row_count=10),
                MergeRunInput(run_id="run-1", list_name="bafu",
                              list_version="2025", sequence=1, row_count=5),
            ],
            outcomes=[], stats={},
        )
        conn = sqlite3.connect(self.db)
        rows = conn.execute(
            "SELECT list_name, sequence FROM merge_run_inputs "
            "WHERE run_id = 'run-1' ORDER BY sequence"
        ).fetchall()
        conn.close()
        self.assertEqual(rows, [("ecoinvent", 0), ("bafu", 1)])


class RoundTripTestCase(StoreTestCase):
    def test_outcomes_survive_the_database(self):
        original = MergeOutcome.from_algorithm("run-1", SOURCE, algorithm_row("a-1"))
        self.write([original])
        restored = read_outcomes(self.db)[0]
        self.assertEqual(restored, original)

    def test_detail_keeps_what_the_indexed_columns_do_not(self):
        original = MergeOutcome.from_prepared("run-1", SOURCE, prepared_row("p-1"))
        self.write([original])
        detail = read_outcomes(self.db)[0].detail
        self.assertEqual(detail["prepared_target_resolution"], "direct")
        self.assertEqual(detail["target_unit"], "kg")
        # The place the build resolved, kept for the recorded-by-name reader
        # so it never has to re-derive the compartment outside the build (#361).
        self.assertEqual(
            detail["source_context_iri"],
            "https://example.org/context/envi-air-unkn",
        )


if __name__ == "__main__":
    unittest.main()


class MultipleSourceListsInOneRunTestCase(StoreTestCase):
    """A run may consume several source lists; each writes its own rows.

    The writer originally deleted a run's rows wholesale before inserting, which
    is correct when a run has one source list and destroys the earlier lists'
    outcomes when it has several. `build` grew the loop before the writer grew
    the scope.
    """

    OTHER = known_source_lists()["ecoinvent-3.11"]

    def write_source(self, source, outcomes, sequence, run_id="run-1"):
        write_source_outcomes(
            self.db,
            run_id=run_id,
            source_input=MergeRunInput(
                run_id=run_id, list_name=source.list_name,
                list_version=source.list_version, sequence=sequence,
                row_count=len(outcomes),
            ),
            outcomes=outcomes,
        )

    def test_a_second_source_list_does_not_erase_the_first(self):
        start_run(self.db, run_id="run-1", started_at="t0")
        self.write_source(
            SOURCE,
            [MergeOutcome.from_unmatched("run-1", SOURCE, unmatched_row("a-1"),
                                         has_candidates=False)],
            sequence=0,
        )
        self.write_source(
            self.OTHER,
            [MergeOutcome.from_unmatched("run-1", self.OTHER, unmatched_row("b-1"),
                                         has_candidates=False)],
            sequence=1,
        )
        rows = read_outcomes(self.db, run_id="run-1")
        self.assertEqual(
            sorted((r.list_version, r.source_uuid) for r in rows),
            [("3.11", "b-1"), ("3.12", "a-1")],
        )

    def test_rewriting_one_source_list_leaves_the_others_alone(self):
        start_run(self.db, run_id="run-1", started_at="t0")
        self.write_source(SOURCE, [MergeOutcome.from_unmatched(
            "run-1", SOURCE, unmatched_row("a-1"), has_candidates=False)], 0)
        self.write_source(self.OTHER, [MergeOutcome.from_unmatched(
            "run-1", self.OTHER, unmatched_row("b-1"), has_candidates=False)], 1)
        # Re-merge only the first list.
        self.write_source(SOURCE, [MergeOutcome.from_unmatched(
            "run-1", SOURCE, unmatched_row("a-2"), has_candidates=False)], 0)
        rows = read_outcomes(self.db, run_id="run-1")
        self.assertEqual(
            sorted((r.list_version, r.source_uuid) for r in rows),
            [("3.11", "b-1"), ("3.12", "a-2")],
        )

    def test_every_source_list_is_recorded_with_its_order(self):
        start_run(self.db, run_id="run-1", started_at="t0")
        self.write_source(SOURCE, [], 0)
        self.write_source(self.OTHER, [], 1)
        conn = sqlite3.connect(self.db)
        rows = conn.execute(
            "SELECT list_version, sequence FROM merge_run_inputs ORDER BY sequence"
        ).fetchall()
        conn.close()
        self.assertEqual(rows, [("3.12", 0), ("3.11", 1)])


class ConflictDetectionTestCase(StoreTestCase):
    """Disagreements between source lists, which one list cannot produce."""

    OTHER = known_source_lists()["ecoinvent-3.11"]

    def outcome(self, source, uuid, target, unit="kg"):
        row = algorithm_row(uuid)
        row.target_elementary_flow_id = target
        row.source_unit = unit
        return MergeOutcome.from_algorithm("run-1", source, row)

    def write_two(self, first, second):
        write_merge_run(
            self.db, run_id="run-1", started_at="t", finished_at="t",
            inputs=[
                MergeRunInput(run_id="run-1", list_name=SOURCE.list_name,
                              list_version=SOURCE.list_version, sequence=0),
                MergeRunInput(run_id="run-1", list_name=self.OTHER.list_name,
                              list_version=self.OTHER.list_version, sequence=1),
            ],
            outcomes=first + second, stats={},
        )

    def test_one_source_list_can_never_conflict(self):
        """With nothing to disagree with, there is nothing to find."""
        self.write([self.outcome(SOURCE, "a-1", "ef-1", unit="kg"),
                    self.outcome(SOURCE, "a-2", "ef-1", unit="m3")])
        self.assertEqual(detect_conflicts(self.db, "run-1"), [])

    def test_two_lists_with_different_units_on_one_target(self):
        self.write_two(
            [self.outcome(SOURCE, "a-1", "ef-1", unit="kg")],
            [self.outcome(self.OTHER, "b-1", "ef-1", unit="m3")],
        )
        conflicts = detect_conflicts(self.db, "run-1")
        self.assertEqual(len(conflicts), 1)
        self.assertEqual(conflicts[0]["kind"], str(ConflictKind.UNIT_DISAGREEMENT))
        self.assertEqual(conflicts[0]["target_elementary_flow_id"], "ef-1")
        self.assertEqual(
            sorted(c["source_unit"] for c in conflicts[0]["claimants"]), ["kg", "m3"]
        )

    def test_two_lists_agreeing_on_a_target_is_not_a_conflict(self):
        """Many-to-one is the normal case, not a problem."""
        self.write_two(
            [self.outcome(SOURCE, "a-1", "ef-1", unit="kg")],
            [self.outcome(self.OTHER, "b-1", "ef-1", unit="kg")],
        )
        self.assertEqual(detect_conflicts(self.db, "run-1"), [])

    def test_the_same_source_flow_placed_differently_by_two_lists(self):
        """Two releases of one list share most uuids; a moved mapping shows up
        here whether it was deliberate or not."""
        self.write_two(
            [self.outcome(SOURCE, "shared-uuid", "ef-1")],
            [self.outcome(self.OTHER, "shared-uuid", "ef-2")],
        )
        conflicts = detect_conflicts(self.db, "run-1")
        kinds = [c["kind"] for c in conflicts]
        self.assertIn(str(ConflictKind.DIVERGENT_TARGET), kinds)

    def test_the_same_source_flow_placed_identically_is_not_a_conflict(self):
        self.write_two(
            [self.outcome(SOURCE, "shared-uuid", "ef-1")],
            [self.outcome(self.OTHER, "shared-uuid", "ef-1")],
        )
        self.assertEqual(detect_conflicts(self.db, "run-1"), [])

    def test_unmatched_rows_are_not_claimants(self):
        """A row with no target cannot contend for one."""
        self.write_two(
            [self.outcome(SOURCE, "a-1", "ef-1", unit="kg")],
            [MergeOutcome.from_unmatched("run-1", self.OTHER, unmatched_row("b-1"),
                                         has_candidates=False)],
        )
        self.assertEqual(detect_conflicts(self.db, "run-1"), [])

    def test_conflicts_are_readable_and_replaced_on_rerun(self):
        self.write_two(
            [self.outcome(SOURCE, "a-1", "ef-1", unit="kg")],
            [self.outcome(self.OTHER, "b-1", "ef-1", unit="m3")],
        )
        detect_conflicts(self.db, "run-1")
        detect_conflicts(self.db, "run-1")
        stored = read_conflicts(self.db, "run-1")
        self.assertEqual(len(stored), 1)
        self.assertEqual(stored[0]["kind"], ConflictKind.UNIT_DISAGREEMENT)


class AdditiveColumnMigrationTestCase(unittest.TestCase):
    """`merge_outcomes` outlives a build, so its DDL has to be able to move.

    The transform drops and recreates the flow tables on every build, so those
    need no migration.  The merge tables are `CREATE TABLE IF NOT EXISTS` and
    hold every previous run, so a column added to the DDL alone would be absent
    from every existing database and every insert would fail against it -- on a
    database that is several gigabytes and not cheap to rebuild.
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = Path(self.tmp.name) / "consensus.sqlite3"
        self.connection = sqlite3.connect(self.db)
        self.addCleanup(self.connection.close)

    def columns(self):
        return {row[1] for row in self.connection.execute("PRAGMA table_info(merge_outcomes)")}

    def test_a_database_predating_the_column_gains_it(self):
        # The table as it shipped, without the added column.
        self.connection.execute("""
            CREATE TABLE merge_outcomes (
                run_id TEXT NOT NULL, list_name TEXT NOT NULL,
                list_version TEXT NOT NULL, source_uuid TEXT NOT NULL,
                outcome TEXT NOT NULL, source_name TEXT, source_context_json TEXT,
                source_unit TEXT, source_cas TEXT, source_ec TEXT, reason TEXT,
                flow_object_id TEXT, target_elementary_flow_id TEXT, basis TEXT,
                basis_value TEXT, matching_method TEXT,
                has_flow_object_candidates INTEGER,
                has_context_inconsistency INTEGER NOT NULL DEFAULT 0,
                detail_json TEXT,
                PRIMARY KEY (run_id, list_name, list_version, source_uuid)
            )
        """)
        self.assertNotIn("has_unit_mismatch", self.columns())
        create_merge_tables(self.connection)
        self.assertIn("has_unit_mismatch", self.columns())

    def test_migrating_twice_is_harmless(self):
        create_merge_tables(self.connection)
        create_merge_tables(self.connection)
        self.assertIn("has_unit_mismatch", self.columns())

    def test_a_row_written_before_the_guard_is_not_flagged(self):
        """A run recorded before the guard existed observed no mismatch, and
        must not read back as though it had."""
        create_merge_tables(self.connection)
        self.connection.execute(
            "INSERT INTO merge_outcomes (run_id, list_name, list_version, "
            "source_uuid, outcome) VALUES ('r', 'ecoinvent', '3.12', 's-1', 'prepared')"
        )
        self.connection.commit()
        value = self.connection.execute(
            "SELECT has_unit_mismatch FROM merge_outcomes").fetchone()[0]
        self.assertEqual(value, 0)


class UnitMismatchAnnotatesAMatchTestCase(unittest.TestCase):
    """Like a context inconsistency, and for the same reason: a note on an
    outcome, not an outcome of its own.  The match still stands."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = Path(self.tmp.name) / "consensus.sqlite3"
        start_run(self.db, run_id="run-1", started_at="t0")
        write_source_outcomes(
            self.db, run_id="run-1",
            source_input=MergeRunInput(run_id="run-1", list_name="ecoinvent",
                                       list_version="3.12", sequence=0),
            outcomes=[
                MergeOutcome.from_prepared("run-1", SOURCE, prepared_row("p-1"),
                                           unit_mismatch=True),
                MergeOutcome.from_prepared("run-1", SOURCE, prepared_row("p-2")),
                MergeOutcome.from_algorithm("run-1", SOURCE, algorithm_row("a-1"),
                                            unit_mismatch=True),
            ],
        )

    def test_a_flagged_row_keeps_its_outcome(self):
        prepared = read_outcomes(self.db, outcome=Outcome.PREPARED)
        self.assertEqual({r.source_uuid for r in prepared}, {"p-1", "p-2"})

    def test_only_the_flagged_rows_carry_the_flag(self):
        every = read_outcomes(self.db)
        flagged = sorted(r.source_uuid for r in every if r.has_unit_mismatch)
        self.assertEqual(flagged, ["a-1", "p-1"])

    def test_an_algorithmic_match_can_be_flagged_too(self):
        """The path that needs it most: nobody has reviewed those pairings."""
        algorithmic = read_outcomes(self.db, outcome=Outcome.ALGORITHM)
        self.assertTrue(all(r.has_unit_mismatch for r in algorithmic))
