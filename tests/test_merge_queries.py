"""The reads behind the merge section.

These were `tests/test_run_report_app.py`, driving the same behaviour through a
Flask test client.  The app is gone; the reads moved to
`webapps/app/queries/merge.py`, and so did the tests, because what they pin is
not how the page looks:

- **No run at all.** The state before the first build, and after a build that
  merged nothing. It must be an answer, not an exception.
- **The three unmatched views are one query with arguments.** `merge_review`
  shipped `unmatched`, `unmatched_with_flow_object_candidates` and
  `unmatched_without_flow_object_candidates` -- the same 9,614 rows stored
  twice and split on a boolean.
- **More than one source list.** The case the JSON report could not describe at
  all, because it was one file per version.

The `/merge` views arrive in Phase 2 and get their own smoke tests. Losing the
route-level assertions is the cost of deleting the app; losing these would have
been the cost of deleting the query layer with it.
"""

import sqlite3
import tempfile
import unittest
from pathlib import Path

from brightway_flows.merge.report import AlgorithmMatch, UnmatchedRow
from brightway_flows.sources import known_source_lists, resolve_source_list
from brightway_flows.merge.store import (
    MergeOutcome,
    MergeRunInput,
    Outcome,
    detect_conflicts,
    write_merge_run,
)
from brightway_flows.webapps.app import db
from brightway_flows.webapps.app.queries import merge as queries

PRIMARY = resolve_source_list("ecoinvent-3.12")
SECONDARY = known_source_lists()["ecoinvent-3.11"]


def unmatched(uuid, *, candidates, reason="no-flow-object-candidate"):
    return UnmatchedRow(
        source_uuid=uuid, source_name=f"Flow {uuid}", source_context=["air"],
        source_unit="kg", source_cas="", source_ec="", reason=reason,
    ), candidates


def matched(uuid, target, unit="kg"):
    return AlgorithmMatch(
        source_uuid=uuid, source_name=f"Flow {uuid}", source_context=["air"],
        source_context_normalized=(), source_context_iri="", source_unit=unit,
        source_cas="124-38-9", source_ec="", flow_object_id="fo-1",
        target_name="target", target_elementary_flow_id=target,
        target_context=["air"], target_unit="kg", basis="cas",
        basis_value="124-38-9", selector_reason="", matching_method="cas",
        algorithm_details={}, provenance={},
    )


class MergeQueryTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.db = Path(self._tmp.name) / "consensus-flows.sqlite3"

    def connection(self):
        """A read-only connection, as a request would hold.

        These functions took a path and opened one per call until the `/merge`
        views were written against them; four calls on the summary page meant
        four file opens.
        """
        connection = db.connect(self.db)
        self.addCleanup(connection.close)
        return connection

    def write(self, inputs, outcomes):
        write_merge_run(
            self.db, run_id="run-1", started_at="2026-01-01T00:00:00Z",
            finished_at="2026-01-01T00:05:00Z", inputs=inputs,
            outcomes=outcomes, stats={},
        )

    def one_source(self):
        rows = [
            MergeOutcome.from_unmatched("run-1", PRIMARY, row, has_candidates=candidates)
            for row, candidates in (unmatched("u-1", candidates=True),
                                    unmatched("u-2", candidates=False))
        ]
        rows.append(MergeOutcome.from_algorithm("run-1", PRIMARY, matched("m-1", "ef-1")))
        self.write(
            [MergeRunInput(run_id="run-1", list_name="ecoinvent",
                           list_version="3.12", sequence=0, row_count=3)],
            rows,
        )


class NoRunTestCase(MergeQueryTestCase):
    """The state before the first build, which must not be an error."""

    def test_a_missing_database_is_refused_at_the_connection(self):
        """Where "no database" is handled changed with the move.

        These functions used to take a path and return an empty summary for a
        file that was not there. The connection is now opened once per request,
        before any query runs, so a missing file is caught in one place and
        renders the app's single empty state.
        """
        with self.assertRaises(db.DatabaseMissingError):
            db.connect(self.db)

    def test_an_empty_database_is_also_no_run(self):
        sqlite3.connect(self.db).close()
        self.assertFalse(queries.load_run(self.connection()).exists)


class SingleSourceTestCase(MergeQueryTestCase):
    def setUp(self):
        super().setUp()
        self.one_source()

    def test_the_run_names_its_source_list(self):
        run = queries.load_run(self.connection())
        self.assertTrue(run.exists)
        self.assertEqual(
            [(row["list_name"], row["list_version"]) for row in run.inputs],
            [("ecoinvent", "3.12")],
        )

    def test_the_three_old_unmatched_views_are_one_query_with_arguments(self):
        def uuids(**kwargs):
            page = queries.outcome_page(self.connection(), run_id="run-1", outcome=Outcome.UNMATCHED, **kwargs
            )
            return sorted(row.source_uuid for row in page.rows)

        self.assertEqual(uuids(), ["u-1", "u-2"])
        self.assertEqual(uuids(has_flow_object_candidates=True), ["u-1"])
        self.assertEqual(uuids(has_flow_object_candidates=False), ["u-2"])

    def test_search_narrows_by_name_uuid_and_cas(self):
        page = queries.outcome_page(self.connection(), run_id="run-1", query="124-38-9")
        self.assertEqual([row.source_uuid for row in page.rows], ["m-1"])

    def test_a_page_beyond_the_end_is_the_last_page(self):
        """Also changed with the move, and for the better.

        This used to return an empty list under a pager that said "page 9999 of
        1". The shared page type clamps instead, so an out-of-range page number
        lands somewhere that exists.
        """
        page = queries.outcome_page(self.connection(), run_id="run-1", page=9999)
        self.assertEqual(page.number, 1)
        self.assertEqual(page.pages, 1)
        self.assertEqual(page.total, 3)
        self.assertEqual(len(page.rows), 3)

    def test_one_source_list_can_have_no_conflicts(self):
        """Empty because there is one list, not because nothing was checked."""
        self.assertEqual(queries.conflicts(self.connection(), "run-1"), [])
        self.assertEqual(queries.source_lists(self.connection(), "run-1"), ["ecoinvent-3.12"])

    def test_detail_returns_one_record_per_source_list(self):
        [outcome] = queries.outcome_detail(self.connection(), "run-1", "u-1")
        self.assertEqual(outcome.list_version, "3.12")
        self.assertEqual(outcome.reason, "no-flow-object-candidate")

    def test_detail_for_an_unknown_flow_is_empty_not_an_error(self):
        self.assertEqual(
            queries.outcome_detail(self.connection(), "run-1", "never-heard-of-it"), []
        )

    def test_the_reason_breakdown_groups_by_category(self):
        [row] = queries.reason_breakdown(self.connection(), "run-1")
        self.assertEqual(row, {"reason": "no-flow-object-candidate", "count": 2})


def tied(uuid, name, *, flow_ids, scores):
    """An unmatched row the selector scored but could not choose between."""
    return UnmatchedRow(
        source_uuid=uuid, source_name=name, source_context=["air"],
        source_unit="kg", source_cas="", source_ec="",
        reason="tied-elementary-candidates",
        candidate_flow_object_ids=["fo-1"],
        candidate_elementary_flow_ids=list(flow_ids),
        candidate_elementary_flows=[
            {"elementary_flow_id": flow_id, "score": score, "unit": "kg",
             "context": ["Environmental", "Air", "Unknown"]}
            for flow_id, score in zip(flow_ids, scores, strict=True)
        ],
        algorithm_details={
            "elementary_candidate_count": len(flow_ids),
            "eligible_candidate_count": len(flow_ids),
            "filtered_out_context_mismatch_count": 2,
        },
    )


class CountingTestCase(MergeQueryTestCase):
    """Rows are not substances, and substances are not flows.

    A source list carries one row per substance per context, and two lists can
    send a row each to the same consensus flow, so a page that counts only rows
    overstates every question a curator asks of it: how much is left to decide,
    and how much of the consensus list a run touched.
    """

    def setUp(self):
        super().setUp()
        rows = [
            MergeOutcome.from_algorithm("run-1", PRIMARY, matched("a-1", "ef-1")),
            MergeOutcome.from_algorithm("run-1", PRIMARY, matched("a-2", "ef-2")),
            MergeOutcome.from_algorithm("run-1", PRIMARY, matched("a-3", "ef-3")),
            # The same substance, in a second list, on a flow the first list
            # already claimed.
            MergeOutcome.from_algorithm("run-1", SECONDARY, matched("b-1", "ef-1")),
            MergeOutcome.from_unmatched(
                "run-1", PRIMARY, unmatched("u-1", candidates=False)[0],
                has_candidates=False),
        ]
        # `matched` names a row after its uuid, so the two rows that are meant
        # to be one substance are renamed here rather than in the helper, which
        # every other test relies on for distinct names.
        for row, name in zip(rows, ["Carbon dioxide", "Carbon dioxide", "Methane",
                                    "Carbon dioxide", "Krypton-85"], strict=True):
            row.source_name = name
        self.write(
            [
                MergeRunInput(run_id="run-1", list_name="ecoinvent",
                              list_version="3.12", sequence=0, row_count=4),
                MergeRunInput(run_id="run-1", list_name="ecoinvent",
                              list_version="3.11", sequence=1, row_count=1),
            ],
            rows,
        )

    def test_an_outcome_is_counted_three_ways(self):
        counts = {row.outcome: row for row in
                  queries.outcome_counts(self.connection(), "run-1")}
        self.assertEqual(counts["algorithm"].rows, 4)
        self.assertEqual(counts["algorithm"].flow_objects, 2)
        self.assertEqual(counts["algorithm"].elementary_flows, 3)

    def test_an_unmatched_row_landed_on_no_flow(self):
        """`''` is what the column holds, and it is not a flow.

        Without `nullif` the distinct count reads that empty string as one more
        elementary flow, so every unmatched group would report exactly one.
        """
        counts = {row.outcome: row for row in
                  queries.outcome_counts(self.connection(), "run-1")}
        self.assertEqual(counts["unmatched"].rows, 1)
        self.assertEqual(counts["unmatched"].elementary_flows, 0)

    def test_the_outcomes_come_back_in_the_merge_order(self):
        self.assertEqual(
            [row.outcome for row in queries.outcome_counts(self.connection(), "run-1")],
            ["algorithm", "unmatched"],
        )

    def test_the_total_is_not_the_columns_added_up(self):
        totals = queries.run_totals(self.connection(), "run-1")
        self.assertEqual(totals.rows, 5)
        # Carbon dioxide, Methane, Krypton-85 -- not 2 + 1.
        self.assertEqual(totals.flow_objects, 3)
        self.assertEqual(totals.elementary_flows, 3)

    def test_each_source_list_reports_its_substances(self):
        run = queries.load_run(self.connection())
        self.assertEqual(
            [(row["list_version"], row["row_count"], row["flow_object_count"])
             for row in run.inputs],
            # Four rows naming three substances: carbon dioxide twice, methane,
            # and the krypton isotope nothing could place.
            [("3.12", 4, 3), ("3.11", 1, 1)],
        )


class CandidateTestCase(MergeQueryTestCase):
    """What an unmatched row had to choose from.

    Without the published tables beside them -- which is a database
    `write_merge_run` will happily produce -- the candidates are identifiers
    and scores. That is what the run recorded, and the summary reports it
    rather than refusing to render.
    """

    def setUp(self):
        super().setUp()
        self.write(
            [MergeRunInput(run_id="run-1", list_name="ecoinvent",
                           list_version="3.12", sequence=0, row_count=2)],
            [
                MergeOutcome.from_unmatched(
                    "run-1", PRIMARY,
                    tied("t-1", "Carbon dioxide",
                         flow_ids=["ef-a", "ef-b", "ef-c"], scores=[4, 4, 2]),
                    has_candidates=True),
                MergeOutcome.from_algorithm("run-1", PRIMARY, matched("m-1", "ef-1")),
            ],
        )

    def summaries(self, **kwargs):
        page = queries.outcome_page(self.connection(), run_id="run-1")
        return page.rows, queries.candidate_summaries(
            self.connection(), page.rows, **kwargs)

    def test_the_summary_names_the_tie(self):
        rows, summaries = self.summaries()
        summary = summaries[[row.source_uuid for row in rows].index("t-1")]
        self.assertEqual(summary.flow_count, 3)
        self.assertEqual(summary.winning_score, 4)
        self.assertEqual(summary.tied_count, 2)
        self.assertEqual(
            [flow.tied_at_top for flow in summary.flows], [True, True, False]
        )

    def test_the_candidates_are_best_first(self):
        """The ids-only fallback has no order, and a shortlist is not sorted."""
        rows, summaries = self.summaries()
        summary = summaries[[row.source_uuid for row in rows].index("t-1")]
        self.assertEqual([flow.score for flow in summary.flows], [4, 4, 2])

    def test_the_selector_counts_come_through(self):
        rows, summaries = self.summaries()
        summary = summaries[[row.source_uuid for row in rows].index("t-1")]
        self.assertEqual(summary.candidate_count, 3)
        self.assertEqual(summary.eligible_count, 3)
        self.assertEqual(summary.filtered_out_count, 2)

    def test_a_cap_shortens_the_list_and_not_the_count(self):
        """The list page shows three; "18 flows" is still what it says."""
        rows, summaries = self.summaries(limit=2)
        summary = summaries[[row.source_uuid for row in rows].index("t-1")]
        self.assertEqual(len(summary.flows), 2)
        self.assertEqual(summary.flow_count, 3)

    def test_a_placed_row_has_nothing_to_choose_between(self):
        rows, summaries = self.summaries()
        summary = summaries[[row.source_uuid for row in rows].index("m-1")]
        self.assertEqual(summary.flows, [])
        self.assertEqual(summary.objects, [])

    def test_the_summaries_line_up_with_the_rows(self):
        """A list, not a mapping: a source uuid appears once per source list."""
        rows, summaries = self.summaries()
        self.assertEqual(len(rows), len(summaries))

    def test_a_database_without_the_published_tables_still_reports(self):
        rows, summaries = self.summaries()
        summary = summaries[[row.source_uuid for row in rows].index("t-1")]
        self.assertEqual(
            [flow.elementary_flow_id for flow in summary.flows],
            ["ef-a", "ef-b", "ef-c"],
        )
        self.assertEqual([flow.name for flow in summary.flows], ["", "", ""])
        self.assertFalse(any(flow.resolved for flow in summary.flows))


class MultipleSourceListsTestCase(MergeQueryTestCase):
    """The case `merge_review` could not display at all."""

    def setUp(self):
        super().setUp()
        self.write(
            [
                MergeRunInput(run_id="run-1", list_name="ecoinvent",
                              list_version="3.12", sequence=0, row_count=1),
                MergeRunInput(run_id="run-1", list_name="ecoinvent",
                              list_version="3.11", sequence=1, row_count=1),
            ],
            [
                MergeOutcome.from_algorithm(
                    "run-1", PRIMARY, matched("shared", "ef-1", unit="kg")),
                MergeOutcome.from_algorithm(
                    "run-1", SECONDARY, matched("shared", "ef-1", unit="m3")),
            ],
        )
        detect_conflicts(self.db, "run-1")

    def test_every_source_list_is_listed_in_merge_order(self):
        """Order matters: a later list can match a flow an earlier one created."""
        self.assertEqual(
            queries.source_lists(self.connection(), "run-1"),
            ["ecoinvent-3.12", "ecoinvent-3.11"],
        )

    def test_conflicts_carry_their_claimants(self):
        [conflict] = queries.conflicts(self.connection(), "run-1")
        self.assertEqual(conflict["kind"], "unit-disagreement")
        claimants = str(conflict["claimants"])
        self.assertIn("3.12", claimants)
        self.assertIn("3.11", claimants)

    def test_a_source_flow_in_two_lists_has_two_outcomes(self):
        outcomes = queries.outcome_detail(self.connection(), "run-1", "shared")
        self.assertEqual(
            sorted(row.list_version for row in outcomes), ["3.11", "3.12"]
        )

    def test_outcomes_can_be_filtered_to_one_source_list(self):
        page = queries.outcome_page(self.connection(), run_id="run-1", source_list="ecoinvent-3.11"
        )
        self.assertEqual(page.total, 1)
        self.assertEqual([row.list_version for row in page.rows], ["3.11"])


if __name__ == "__main__":
    unittest.main()
