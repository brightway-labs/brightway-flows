"""The acceptance test: every question a build has answered, asked again.

`plans/lookup-api.md` §5.1. The lookup's claim is that an answer from it is the
answer the build would have given. `merge_outcomes` holds 16,953 rows of "these
inputs produced this answer", so the claim is checkable rather than arguable:
rebuild a `FlowQuery` from each recorded row, ask, and count.

Measured on the unbounded three-list build of 21 August 2026 at `8be43a3` -- EF
3.1 with ecoinvent 3.12, ecoinvent 3.8 and BAFU 2026-v1 merged:

| bucket | rows | same flow | other flow | declined |
|---|---|---|---|---|
| evidence | 2,519 | 2,490 | **0** | 29 |
| material | 288 | 188 | 0 | 100 |
| land_class | 98 | 19 | 0 | 79 |
| prepared | 11,974 | 11,115 | 252 | 607 |
| prepared-mapping | 1,232 | 1,153 | 2 | 77 |
| created | 842 | 840 | 0 | 2 |

**Zero other-flow in every bucket the algorithm owns.** Where the lookup differs
from the build it declines to place the row; it never puts one somewhere else.
That is the property worth having, and it is the one this file asserts most
firmly: a wrong match is silent, an unmatched row is reviewable.

The tests are skipped where there is no build, because most runs of this suite
have none. The exact counts live in `expectations/0641-a-row-without-a-build.json`
and are graded by `assess`, which is where a number that moves shows up in a
pull request's diff; here the *shapes* are asserted, so a change that reverses
the safety property fails whether or not anybody re-recorded a baseline.
"""

from __future__ import annotations

import logging
import unittest

import structlog

from brightway_flows.filesystem import CONSENSUS_DB_FILEPATH
from brightway_flows.lookup import FlowMatcher, UnusableBuildError
from brightway_flows.lookup.replay import (
    CREATED,
    EVIDENCE,
    LAND_CLASS,
    MATERIAL,
    PREPARED,
    PREPARED_MAPPING,
    bucket_of,
    replay,
)
from brightway_flows.merge.store import latest_run_id, read_outcomes

#: What the evidence bucket has to reproduce. Not 100%: a handful of rows
#: matched on names `merge_outcomes` does not carry -- a synonym, an alternative
#: label enrichment found, a catalogue code -- and those cannot be reconstructed
#: from what was stored. 98.85% on the 21 August 2026 build; the floor is set
#: below it with room for one build's worth of drift, and the count is pinned
#: exactly in `expectations/`.
EVIDENCE_FLOOR = 0.97

#: A row the merge had to create a flow for should now find that flow, because
#: the replay runs against the finished build. 99.8% on the same build.
CREATED_FLOOR = 0.99


class _Replay(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        structlog.configure(
            wrapper_class=structlog.make_filtering_bound_logger(logging.CRITICAL)
        )
        # Registered before anything can skip: a `SkipTest` below must not
        # leave the CRITICAL filter on for the rest of the run, where it would
        # silence events later suites assert with `capture_logs`.
        cls.addClassCleanup(structlog.reset_defaults)
        if not CONSENSUS_DB_FILEPATH.exists():
            raise unittest.SkipTest(f"no build at {CONSENSUS_DB_FILEPATH}")
        try:
            cls.matcher = FlowMatcher.from_results(CONSENSUS_DB_FILEPATH)
        except UnusableBuildError as error:
            raise unittest.SkipTest(str(error))
        run = latest_run_id(CONSENSUS_DB_FILEPATH)
        cls.outcomes = read_outcomes(CONSENSUS_DB_FILEPATH, run_id=run)
        if not cls.outcomes:
            raise unittest.SkipTest("this build merged nothing, so there is nothing to replay")
        cls.result = replay(
            CONSENSUS_DB_FILEPATH,
            run_id=run,
            matcher=cls.matcher,
            outcomes=cls.outcomes,
        )

    @classmethod
    def tearDownClass(cls) -> None:
        structlog.reset_defaults()
        super().tearDownClass()


class TheReplayReproducesTheBuildTestCase(_Replay):
    """What must hold, on any build."""

    def test_there_is_something_to_replay(self):
        """Guards every test below: a replay of nothing passes everything."""
        self.assertEqual(self.result.rows, len(self.outcomes))
        self.assertGreater(self.result.rows, 1000)
        for bucket in (EVIDENCE, PREPARED, CREATED):
            with self.subTest(bucket=bucket):
                self.assertGreater(self.result.tallies[bucket].rows, 0)

    def test_the_evidence_rows_reach_the_same_flow(self):
        """The one bucket where a divergence is a defect: these rows matched on
        something the query carries, so the lookup has the same evidence the
        build had."""
        tally = self.result.tallies[EVIDENCE]
        self.assertGreaterEqual(
            tally.agreement,
            EVIDENCE_FLOOR,
            f"{tally.same_target}/{tally.rows} evidence rows reached the recorded "
            f"flow:\n" + "\n".join(d.describe() for d in self.result.divergences[:20]),
        )

    def test_no_evidence_row_is_sent_somewhere_else(self):
        """**The property worth having.** Where the lookup differs from the
        build it declines to place the row -- it never puts one on a different
        flow. A wrong match is silent; an unmatched row is reviewable, and every
        one of these comes back with the substances it could have been."""
        tally = self.result.tallies[EVIDENCE]
        self.assertEqual(
            tally.other_target,
            0,
            "the lookup placed an evidence row on a flow the build did not "
            "choose:\n"
            + "\n".join(
                d.describe()
                for d in self.result.divergences
                if d.result.matched
            ),
        )

    def test_every_divergence_is_a_row_the_lookup_declined(self):
        """The same statement from the other side, and the one a reader can
        check without re-running anything: the divergence list holds only
        unmatched rows."""
        placed = [d for d in self.result.divergences if d.result.matched]
        self.assertEqual([d.describe() for d in placed], [])

    def test_a_declined_row_still_says_what_it_could_have_been(self):
        """§3.2: never a bare `None`. An unmatched row is a question with
        evidence attached."""
        for divergence in self.result.divergences[:20]:
            with self.subTest(name=divergence.outcome.source_name):
                self.assertTrue(divergence.result.selector_reason)
                self.assertIsNotNone(divergence.result.build)

    def test_a_row_the_merge_created_a_flow_for_now_finds_it(self):
        """Replayed against the *finished* build, the flow the merge made is
        there. `plans/lookup-api.md` §5.1 expects `matched=False` for these,
        which is right about the build as it stood before the merge and wrong
        about the one being read -- and the agreement is the strongest single
        piece of evidence that the two place a row the same way."""
        tally = self.result.tallies[CREATED]
        self.assertGreaterEqual(tally.agreement, CREATED_FLOOR)
        self.assertEqual(tally.other_target, 0)

    def test_the_curated_buckets_are_reported_rather_than_asserted(self):
        """A prepared decision is a curator's, not the algorithm's, so the
        algorithm reaching a different flow is not a defect. What it is, is
        worth knowing: it is the measurement tier one is argued from."""
        for bucket in (PREPARED, PREPARED_MAPPING):
            with self.subTest(bucket=bucket):
                tally = self.result.tallies[bucket]
                self.assertGreater(tally.rows, 0)
                self.assertEqual(
                    tally.same_target + tally.other_target + tally.unmatched, tally.rows
                )

    def test_the_two_curated_tables_are_the_documented_limit(self):
        """§6.1: water and land are keyed on a uuid a query has none of, so
        these are the rows a caller has to state a hint for. The claim is that
        they are *not* silently mismatched -- the agreement is partial and the
        rest decline."""
        for bucket in (MATERIAL, LAND_CLASS):
            with self.subTest(bucket=bucket):
                tally = self.result.tallies[bucket]
                self.assertGreater(tally.rows, 0)
                self.assertEqual(tally.other_target, 0)

    def test_the_report_prints_every_bucket(self):
        """The per-bucket counts are the output of this test, so a change that
        moves a row between buckets is visible rather than absorbed."""
        report = self.result.report()
        print("\n" + report)
        for bucket in (EVIDENCE, MATERIAL, LAND_CLASS, PREPARED, PREPARED_MAPPING, CREATED):
            self.assertIn(bucket, report)


class TheBucketsAreWhatTheyClaimTestCase(_Replay):
    """The buckets decide what is asserted, so they have to be right."""

    def test_every_row_lands_in_exactly_one_bucket(self):
        counted = sum(tally.rows for tally in self.result.tallies.values())
        self.assertEqual(counted, self.result.rows)

    def test_an_evidence_row_matched_on_something_a_query_carries(self):
        """The bucket's definition, checked against the rows in it: a CAS
        number, an EC number, or a name -- including the industry designation
        a shared-CAS name ends in, which is the last comma-segment of the
        row's own name (#362). Not a curated table and not a
        correspondence."""
        allowed = {
            "cas", "ec", "label", "cas+label", "cas+qualifier",
            "cas+designation",
            "cas+label+preferred-name", "label+preferred-name",
            "simapro-name-pattern", "historical-name", "preferred-name", "",
        }
        unexpected = sorted(
            {o.basis for o in self.outcomes if bucket_of(o) == EVIDENCE} - allowed
        )
        self.assertEqual(unexpected, [])

    def test_no_curated_decision_is_counted_as_evidence(self):
        for outcome in self.outcomes:
            if outcome.matching_method == "prepared":
                self.assertIn(bucket_of(outcome), (PREPARED, PREPARED_MAPPING))
            if outcome.basis in ("material", "land_class"):
                self.assertIn(bucket_of(outcome), (MATERIAL, LAND_CLASS))


class SupplyingTheNamesTheBuildUsedTestCase(_Replay):
    """What the replay cannot see, made visible.

    `merge_outcomes` records a row's *name*, and matching is done on every name
    the row is known by. A row that matched on a synonym cannot be reconstructed
    from what was stored, and `basis_value` is the one place those names survive.
    Replaying with them is the check that the divergences above are the replay's
    limit rather than the lookup's.
    """

    def _richer(self):
        return replay(
            CONSENSUS_DB_FILEPATH,
            run_id=self.result.run_id,
            matcher=self.matcher,
            outcomes=self.outcomes,
            with_recorded_names=True,
        )

    def test_more_evidence_never_makes_the_answer_worse(self):
        """Agreement goes up, declines go down. 2,495 of 2,519 against 2,490 on
        the 21 August 2026 build, and 23 declines against 29."""
        richer = self._richer()
        bare = self.result.tallies[EVIDENCE]
        rich = richer.tallies[EVIDENCE]
        self.assertGreaterEqual(rich.same_target, bare.same_target)
        self.assertLessEqual(rich.unmatched, bare.unmatched)
        self.assertGreaterEqual(rich.agreement, EVIDENCE_FLOOR)

    def test_a_row_placed_differently_is_placed_in_the_compartment_it_named(self):
        """**The one row in 16,953 where the lookup and the build disagree about
        where an evidence row goes, and the lookup is right.**

        BAFU's `Energy, Gross Calorific Value, In Biomass, Resource Correction`
        is in `resources / unspecified`, which BAFU's own rule maps onto
        `reso-grou`. The lookup finds the `Biomass` flow that sits in exactly
        that compartment. The build did not: at the moment it matched the row,
        that flow did not exist yet -- the merge creates flows as it goes -- so
        it coarsened onto the nearest one that did. #112 is the same effect
        described from inside the merge: the set of flows to be nearest to grows
        as the merge runs, which makes the answer depend on *when* the row was
        asked.

        So the invariant is not "never differs" -- it is that a row the lookup
        places differently is placed in the compartment the row itself named,
        by an exact match on the context IRI. A coarsening the lookup invented
        would fail this; a coarsening the build had to make does not.
        """
        placed = [d for d in self._richer().divergences if d.result.matched]
        for divergence in placed:
            with self.subTest(name=divergence.outcome.source_name):
                self.assertEqual(
                    divergence.result.selector_reason,
                    "exact-context-iri-match",
                    divergence.describe(),
                )
                self.assertEqual(
                    divergence.result.context_iri,
                    divergence.result.resolved_context_iri,
                    divergence.describe(),
                )


if __name__ == "__main__":
    unittest.main()
