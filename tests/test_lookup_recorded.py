"""Tier one: the decision a build already made, rather than one derived again.

`plans/lookup-api.md` §3.3. The algorithm is a re-derivation, and where a build
has already decided a row the decision itself is better evidence: exact, instant,
and inclusive of the curated decisions the algorithm would not reproduce.

Two ways in, and the difference between them is the whole of §8's first open
question.

**By identifier** is not a guess of any kind. The caller says which list their
row came from and what its identifier is there; `elementary_flow_sources` is the
join, and the row is the row. On by default.

**By name and medium** is a judgement that a row of the caller's list *is* a row
of a list already merged, because the two are spelled the same and are in the
same resolved place (#357). Off by default: it is the one place this design
could produce a confident wrong answer.

What can be measured now that could not be argued before: over the 23,005
recorded outcomes of the 30 August 2026 build, 15,756 distinct `(name,
resolved context)` keys hold one recorded flow and 43 hold two. The 43 decline
rather than being arbitrated -- unless the caller's `source_label` names a
merged list that ruled there (#359), which settles 34 of them -- so the tier
can decline but not be quietly wrong about a disagreement this build contains.
"""

from __future__ import annotations

import logging
import sqlite3
import tempfile
import unittest

from pathlib import Path

import orjson
import structlog

from brightway_flows.filesystem import CONSENSUS_DB_FILEPATH
from brightway_flows.lookup import (
    TIER_ALGORITHM,
    TIER_RECORDED,
    TIER_RECORDED_BY_NAME,
    FlowMatcher,
    FlowQuery,
    UnusableBuildError,
)
from brightway_flows.lookup.recorded import (
    RecordedDecision,
    RecordedDecisions,
    split_list_key,
)
from test_lookup_index import (
    PREFIX,
    _elementary,
    _flow,
    _flow_object,
    _write_run_tables,
)

AIR = PREFIX + "envi-air-unkn"
WATER = PREFIX + "envi-wate-unkn"


def _fixture(tmp: Path) -> Path:
    """A build with two source rows recorded against two consensus flows.

    `_write_consensus_sqlite` writes `elementary_flow_sources` from the flows'
    own `source_refs`, so the links are stated the way a build states them
    rather than inserted behind its back.
    """
    from brightway_flows.pipeline.sqlite import _write_consensus_sqlite

    db_path = tmp / "consensus-flows.sqlite3"
    flow_objects = [
        _flow_object("fo-benzene", "Benzene", cas=("71-43-2",)),
        _flow_object("fo-water", "Water", cas=("7732-18-5",)),
    ]
    elementary = [
        _elementary("ef-benzene-air", "fo-benzene", context_iri=AIR),
        _elementary("ef-water-water", "fo-water", context_iri=WATER, unit="m3"),
    ]
    flows = [
        _flow(
            row.elementary_flow_id,
            "fixture",
            flow_object_id=row.flow_object_id,
            context_iri=row.context_iri,
            unit=row.unit or "kg",
        )
        for row in elementary
    ]
    # On the `ElementaryFlow`, not the `Flow`: the writer reads `source_refs`
    # off the layered record, which is the copy the merge keeps current (#30).
    elementary[0].source_refs = [
        {
            "list_name": "somelist",
            "list_version": "1.0",
            "source_flow_uuid": "vendor-benzene",
            "source_flow_name": "Benzene as they call it",
        }
    ]
    elementary[1].source_refs = [
        {
            "list_name": "somelist",
            "list_version": "1.0",
            "source_flow_uuid": "vendor-water",
            "source_flow_name": "Water as they call it",
        }
    ]
    _write_consensus_sqlite(flows, [], flow_objects, elementary, db_path=db_path)
    _write_run_tables(db_path)
    _record_outcomes(db_path)
    return db_path


def _record_outcomes(db_path: Path) -> None:
    """The `merge_outcomes` rows the name index is built from.

    Four shapes, one per claim: a name recorded once (benzene), a name recorded
    in two places with a different flow in each (the solvent -- #357's ordinary
    case, a decision that depends on the compartment), a place two lists ruled
    on differently (the water rows -- the genuine disagreement, which declines
    unless a `source_label` names a ruling list, #359), and the resolved
    context written into `detail_json` the way a build writes it.  Three edge
    rows follow, one per boundary of what the index reads (#361's review).
    """
    from brightway_flows.merge.store import create_merge_tables

    connection = sqlite3.connect(db_path)
    try:
        create_merge_tables(connection)
        rows = [
            ("somelist", "1.0", "vendor-benzene", "Benzene as they call it",
             ["their air"], AIR, "ef-benzene-air"),
            # A second list agreeing with the first: the rung stays unanimous,
            # and what it exercises is attribution -- whose row reports an
            # answer both lists gave.
            ("thirdlist", "1.0", "third-benzene", "Benzene as they call it",
             ["their air"], AIR, "ef-benzene-air"),
            ("somelist", "1.0", "vendor-solvent-a", "Solvent as they call it",
             ["their air"], AIR, "ef-benzene-air"),
            ("somelist", "1.0", "vendor-solvent-w", "Solvent as they call it",
             ["their water"], WATER, "ef-water-water"),
            ("somelist", "1.0", "vendor-water", "Water as they call it",
             ["their water"], WATER, "ef-water-water"),
            # The same name in the same resolved place as the row above it,
            # decided differently by another list: a genuine disagreement,
            # answered for nobody except a caller who names a ruling list.
            ("otherlist", "1.0", "other-water", "Water as they call it",
             ["their water"], WATER, "ef-benzene-air"),
        ]
        for list_name, list_version, uuid, name, context, iri, target in rows:
            connection.execute(
                "INSERT INTO merge_outcomes (run_id, list_name, list_version, "
                "source_uuid, outcome, source_name, source_context_json, "
                "target_elementary_flow_id, basis, matching_method, detail_json) "
                "VALUES ('merge-1', ?, ?, ?, 'algorithm', ?, ?, ?, 'cas', 'algorithm', ?)",
                (list_name, list_version, uuid, name,
                 orjson.dumps(context).decode(), target,
                 orjson.dumps({"source_context_iri": iri}).decode()),
            )
        # Three more shapes, one per boundary of what the index reads: a row
        # the merge *refused* but stored with the refused target filled in
        # (two real refusal paths do that), a record from before #361 whose
        # detail has no place field at all, and a record whose field is
        # present but empty because the build resolved no place.
        edge_rows = [
            ("unmatched", "vendor-refused", "Refused as they call it",
             orjson.dumps({"source_context_iri": AIR}).decode()),
            ("algorithm", "vendor-orphan", "Orphan as they call it",
             orjson.dumps({}).decode()),
            ("algorithm", "vendor-blank", "Blank as they call it",
             orjson.dumps({"source_context_iri": ""}).decode()),
        ]
        for outcome, uuid, name, detail in edge_rows:
            connection.execute(
                "INSERT INTO merge_outcomes (run_id, list_name, list_version, "
                "source_uuid, outcome, source_name, source_context_json, "
                "target_elementary_flow_id, basis, matching_method, detail_json) "
                "VALUES ('merge-1', 'somelist', '1.0', ?, ?, ?, ?, "
                "'ef-benzene-air', 'cas', 'algorithm', ?)",
                (uuid, outcome, name,
                 orjson.dumps(["their air"]).decode(), detail),
            )
        connection.commit()
    finally:
        connection.close()


class _Fixture(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.tmp = Path(tempfile.mkdtemp())
        cls.db_path = _fixture(cls.tmp)

    def setUp(self) -> None:
        super().setUp()
        structlog.configure(
            wrapper_class=structlog.make_filtering_bound_logger(logging.CRITICAL)
        )
        self.addCleanup(structlog.reset_defaults)


class TheRowIsTheRowTestCase(_Fixture):
    """By identifier: not a guess, and so not behind a flag."""

    def setUp(self) -> None:
        super().setUp()
        self.matcher = FlowMatcher.from_results(self.db_path)

    def test_a_row_this_build_merged_is_answered_from_what_it_decided(self):
        result = self.matcher.match(
            FlowQuery(name="anything at all", list_key="somelist-1.0", identifier="vendor-benzene")
        )
        self.assertTrue(result.matched)
        self.assertEqual(result.tier, TIER_RECORDED)
        self.assertEqual(result.elementary_flow_id, "ef-benzene-air")
        self.assertEqual(result.basis, "recorded-source-reference")
        self.assertEqual(result.selector_reason, "recorded-decision")

    def test_the_answer_carries_the_same_fields_the_algorithm_answers_with(self):
        """A caller should not be able to tell the two apart by shape -- only by
        `tier`, which is the field that exists to tell them."""
        result = self.matcher.match(
            FlowQuery(name="anything", list_key="somelist-1.0", identifier="vendor-water")
        )
        self.assertEqual(result.pref_label, "Water")
        self.assertEqual(result.unit, "m3")
        self.assertEqual(result.context_iri, WATER)
        self.assertEqual(result.context_display, ("Environmental", "Water", "Unknown"))
        self.assertIsNotNone(result.build)

    def test_it_says_which_row_of_which_list_answered(self):
        """So a curator can go and look at the decision rather than trust it."""
        result = self.matcher.match(
            FlowQuery(name="anything", list_key="somelist-1.0", identifier="vendor-water")
        )
        self.assertEqual(result.selector_details["recorded_list"], "somelist-1.0")
        self.assertEqual(result.selector_details["recorded_source_uuid"], "vendor-water")
        self.assertEqual(
            result.selector_details["recorded_source_name"], "Water as they call it"
        )

    def test_a_row_this_build_never_merged_falls_through_to_the_algorithm(self):
        """Which is the ordinary case, because the whole point of the API is
        lists nobody has merged."""
        result = self.matcher.match(
            FlowQuery(
                name="Benzene",
                cas="71-43-2",
                unit="kg",
                context=["Environmental", "Air"],
                list_key="a-list-nobody-merged",
                identifier="whatever",
            )
        )
        self.assertEqual(result.tier, TIER_ALGORITHM)
        self.assertTrue(result.matched)
        self.assertEqual(result.basis, "cas")

    def test_an_identifier_without_a_list_is_not_a_lookup(self):
        """Both halves are needed: a uuid means nothing without knowing whose."""
        result = self.matcher.match(
            FlowQuery(
                name="Benzene", cas="71-43-2", unit="kg",
                context=["Environmental", "Air"], identifier="vendor-benzene",
            )
        )
        self.assertEqual(result.tier, TIER_ALGORITHM)


class ANameIsNotARowTestCase(_Fixture):
    """By name and context: off unless asked for, and refusing what it cannot
    tell apart."""

    def test_it_is_off_by_default(self):
        matcher = FlowMatcher.from_results(self.db_path)
        result = matcher.match(
            FlowQuery(name="Benzene as they call it", context=["their air"])
        )
        self.assertEqual(result.tier, TIER_ALGORITHM)
        self.assertFalse(result.matched)

    def test_turning_it_on_answers_from_the_recorded_decision(self):
        matcher = FlowMatcher.from_results(self.db_path, recorded_by_name=True)
        result = matcher.match(
            FlowQuery(name="Benzene as they call it", context=["their air"])
        )
        self.assertEqual(result.tier, TIER_RECORDED_BY_NAME)
        self.assertTrue(result.matched)
        self.assertEqual(result.elementary_flow_id, "ef-benzene-air")
        self.assertEqual(result.basis, "recorded-name-and-context")

    def test_a_key_two_rows_disagree_about_declines_rather_than_arbitrates(self):
        """**The reason this can be allowed at all.** Two lists record different
        flows for `Water as they call it` in the same resolved place; neither
        is served. Picking one would be choosing between two curated decisions
        by row order, which is exactly what a name collision would produce and
        what this project keeps removing."""
        matcher = FlowMatcher.from_results(self.db_path, recorded_by_name=True)
        result = matcher.match(
            FlowQuery(name="Water as they call it", context_iri=WATER)
        )
        self.assertEqual(result.tier, TIER_ALGORITHM)

    def test_the_index_counts_its_keys_and_its_disagreements(self):
        decisions = RecordedDecisions(self.db_path)
        # (benzene, AIR), (solvent, AIR), (solvent, WATER) hold one flow each;
        # (water, WATER) holds two, and one list there is unanimous.
        self.assertEqual(decisions.context_keys, 3)
        self.assertEqual(decisions.conflicted_context_keys, 1)
        self.assertEqual(decisions.arbitrable_context_keys, 1)

    def test_the_flag_does_not_change_a_row_answered_by_identifier(self):
        """Tier one's two halves are ordered, and the specific one wins."""
        for flag in (False, True):
            with self.subTest(recorded_by_name=flag):
                matcher = FlowMatcher.from_results(self.db_path, recorded_by_name=flag)
                result = matcher.match(
                    FlowQuery(
                        name="Water as they call it",
                        context=["their water"],
                        list_key="somelist-1.0",
                        identifier="vendor-water",
                    )
                )
                self.assertEqual(result.tier, TIER_RECORDED)
                self.assertEqual(result.elementary_flow_id, "ef-water-water")


class ANameIsAnsweredWhereTheCallerIsTestCase(_Fixture):
    """The key is the resolved place, not the source's spelling of it (#357).

    `Solvent as they call it` is recorded twice, onto a different flow in air
    and in water. Keyed on the name alone that is a collision to drop; keyed on
    the name and the resolved context it is two answers, each reachable by the
    caller who is actually in that place."""

    def setUp(self) -> None:
        super().setUp()
        self.matcher = FlowMatcher.from_results(self.db_path, recorded_by_name=True)

    def test_the_same_name_answers_differently_per_medium(self):
        in_air = self.matcher.match(
            FlowQuery(name="Solvent as they call it", context_iri=AIR)
        )
        in_water = self.matcher.match(
            FlowQuery(name="Solvent as they call it", context_iri=WATER)
        )
        self.assertEqual(in_air.tier, TIER_RECORDED_BY_NAME)
        self.assertEqual(in_air.elementary_flow_id, "ef-benzene-air")
        self.assertEqual(in_water.tier, TIER_RECORDED_BY_NAME)
        self.assertEqual(in_water.elementary_flow_id, "ef-water-water")

    def test_a_caller_whose_compartment_cannot_be_read_gets_no_split_name(self):
        """With no place resolved the ladder reaches only the whole-name rung,
        where the solvent's two decisions disagree -- so it declines, rather
        than picking a medium the caller never named."""
        result = self.matcher.match(
            FlowQuery(name="Solvent as they call it", context=["somewhere unmapped"])
        )
        self.assertEqual(result.tier, TIER_ALGORITHM)

    def test_a_name_recorded_once_still_answers_with_no_compartment(self):
        """The whole-name rung, for the caller who has nothing else: benzene is
        recorded onto one flow everywhere, so nothing is being guessed."""
        result = self.matcher.match(
            FlowQuery(name="Benzene as they call it", context=["somewhere unmapped"])
        )
        self.assertEqual(result.tier, TIER_RECORDED_BY_NAME)
        self.assertEqual(result.elementary_flow_id, "ef-benzene-air")

    def test_a_place_the_name_was_never_recorded_in_is_not_answered_from_another(self):
        """One rung per caller, and no falling through.  Benzene is recorded
        only as an air emission; a caller who resolved to water must not be
        answered from the air decision via the dimension rung -- which pools
        every emission medium -- or the whole-name rung.  A resolved
        compartment is answered at that compartment or handed to the
        algorithm, whose media filter holds the boundary."""
        result = self.matcher.match(
            FlowQuery(name="Benzene as they call it", context_iri=WATER)
        )
        self.assertEqual(result.tier, TIER_ALGORITHM)


class OnlyPlacedRowsAreDecisionsTestCase(_Fixture):
    """What the index reads, and what its fallback count means (#361).

    `merge_outcomes` stores refusals beside decisions, and two refusal paths
    fill the target column with the flow they refused, so the reader keys on
    the `outcome` column rather than the target column.  And the fallback
    count means "the record predates the place field", not "the build resolved
    nothing": a present-but-empty field is re-derived without being counted,
    so the count reaches zero by remaking the build and stays there.
    """

    def setUp(self) -> None:
        super().setUp()
        self.decisions = RecordedDecisions(self.db_path)

    def test_a_refused_row_is_not_a_decision(self):
        """The refused row stores a target and a resolved place; it must still
        be invisible at every rung, because the merge did not place it."""
        for rung_kwargs in ({"context_iri": AIR}, {"dimension": "Environmental"}, {}):
            with self.subTest(**rung_kwargs):
                self.assertIsNone(
                    self.decisions.for_name_in_context(
                        "Refused as they call it", **rung_kwargs
                    )
                )

    def test_a_record_without_the_place_field_is_counted_and_re_derived(self):
        answer = self.decisions.for_name_in_context("Orphan as they call it")
        self.assertIsNotNone(answer)
        self.assertEqual(answer.decision.elementary_flow_id, "ef-benzene-air")
        self.assertEqual(self.decisions.resolved_without_recorded_context, 1)

    def test_an_empty_place_field_is_re_derived_but_not_counted(self):
        answer = self.decisions.for_name_in_context("Blank as they call it")
        self.assertIsNotNone(answer)
        self.assertEqual(answer.decision.elementary_flow_id, "ef-benzene-air")
        # Still 1 -- the orphan alone.  This row's field was written; the build
        # resolved nothing, and remaking the build would not change that.
        self.assertEqual(self.decisions.resolved_without_recorded_context, 1)


class TheLineageSettlesADisagreementTestCase(_Fixture):
    """`source_label` arbitrates a place two lists ruled on differently (#359).

    A caller saying "my list is somelist-shaped" has supplied the one fact the
    tie is missing, so somelist's own recorded decision answers -- reported as
    such, with the competing flow listed beside it."""

    def setUp(self) -> None:
        super().setUp()
        self.matcher = FlowMatcher.from_results(self.db_path, recorded_by_name=True)

    def test_naming_a_ruling_list_gets_that_lists_decision(self):
        result = self.matcher.match(
            FlowQuery(
                name="Water as they call it",
                context_iri=WATER,
                source_label="somelist-1.0",
            )
        )
        self.assertEqual(result.tier, TIER_RECORDED_BY_NAME)
        self.assertEqual(result.elementary_flow_id, "ef-water-water")
        self.assertEqual(
            result.selector_details["arbitrated_by_source_label"], "somelist-1.0"
        )
        self.assertEqual(
            result.selector_details["recorded_alternatives"], ["ef-benzene-air"]
        )

    def test_the_bare_list_name_is_enough(self):
        result = self.matcher.match(
            FlowQuery(
                name="Water as they call it",
                context_iri=WATER,
                source_label="somelist",
            )
        )
        self.assertEqual(result.tier, TIER_RECORDED_BY_NAME)
        self.assertEqual(result.elementary_flow_id, "ef-water-water")

    def test_a_label_no_list_answers_to_changes_nothing(self):
        result = self.matcher.match(
            FlowQuery(
                name="Water as they call it",
                context_iri=WATER,
                source_label="a-list-nobody-merged",
            )
        )
        self.assertEqual(result.tier, TIER_ALGORITHM)

    def test_a_unanimous_key_is_not_reported_as_arbitrated(self):
        """The label only settles ties.  Where every list already agrees, the
        answer is the ordinary one and says nothing about arbitration."""
        result = self.matcher.match(
            FlowQuery(
                name="Solvent as they call it",
                context_iri=AIR,
                source_label="somelist-1.0",
            )
        )
        self.assertEqual(result.tier, TIER_RECORDED_BY_NAME)
        self.assertNotIn("arbitrated_by_source_label", result.selector_details)

    def test_a_unanimous_answer_is_attributed_to_the_callers_own_list(self):
        """Two lists recorded benzene in air onto the same flow.  The flow is
        the same whichever row reports it; whose row does should be the
        caller's own list where they named one -- an attribution, not an
        arbitration -- rather than whichever row the merge wrote first."""
        unnamed = self.matcher.match(
            FlowQuery(name="Benzene as they call it", context_iri=AIR)
        )
        named = self.matcher.match(
            FlowQuery(
                name="Benzene as they call it",
                context_iri=AIR,
                source_label="thirdlist-1.0",
            )
        )
        self.assertEqual(unnamed.elementary_flow_id, named.elementary_flow_id)
        self.assertEqual(unnamed.selector_details["recorded_list"], "somelist-1.0")
        self.assertEqual(named.selector_details["recorded_list"], "thirdlist-1.0")
        self.assertNotIn("arbitrated_by_source_label", named.selector_details)


class OneRowTwoDecisionsTestCase(_Fixture):
    """A vendor row mapped onto two consensus flows.

    47 of the 110,993 links on the 21 August 2026 build. Returning either would
    be choosing between two recorded decisions by row order.
    """

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        connection = sqlite3.connect(cls.db_path)
        try:
            connection.execute(
                "INSERT INTO elementary_flow_sources (elementary_flow_uuid, list_name, "
                "list_version, source_flow_uuid, source_flow_name) "
                "VALUES ('ef-water-water', 'somelist', '1.0', 'vendor-benzene', 'x')"
            )
            connection.commit()
        finally:
            connection.close()

    def test_it_is_reported_rather_than_chosen_between(self):
        matcher = FlowMatcher.from_results(self.db_path)
        result = matcher.match(
            FlowQuery(name="anything", list_key="somelist-1.0", identifier="vendor-benzene")
        )
        self.assertFalse(result.matched)
        self.assertEqual(result.tier, TIER_RECORDED)
        self.assertEqual(result.selector_reason, "multiple-recorded-decisions")
        self.assertEqual(
            sorted(result.selector_details["recorded_flow_ids"]),
            ["ef-benzene-air", "ef-water-water"],
        )


class TheListKeyIsSplitOnTheLastNameTestCase(unittest.TestCase):
    """`bafu-2026-v1` is a list called `bafu` at version `2026-v1`, so a split on
    the first hyphen is the one that works and a split on the last is not."""

    def test_the_registered_keys_round_trip(self):
        from brightway_flows.sources import known_source_lists

        for source in known_source_lists().values():
            with self.subTest(key=source.key):
                self.assertEqual(
                    split_list_key(source.key), (source.list_name, source.list_version)
                )

    def test_a_key_with_no_version_is_all_name(self):
        self.assertEqual(split_list_key("simapro"), ("simapro", ""))


class TheLabelIsReadFromTheRegistryTestCase(unittest.TestCase):
    """One acceptor of `source_label`, and it is the registry's.

    A caller plausibly holds any of three spellings of a list -- its key
    (`EF-3.1`), its bare name (`stepwise`), or the label its published flows
    carry (`EF 3.1`) -- and all three must reach the recorded `list_key`, the
    same way `resolve_context` reaches the list's compartment rules.  Two
    private recognisers here and there is how `EF 3.1` came to steer
    compartments while failing to settle ties."""

    def test_every_registered_spelling_reaches_the_recorded_key(self):
        from brightway_flows.lookup.recorded import _list_label_matches
        from brightway_flows.sources import base_source_list, known_source_lists

        for source in (base_source_list(), *known_source_lists().values()):
            decision = RecordedDecision(
                elementary_flow_id="whatever",
                list_name=source.list_name,
                list_version=source.list_version,
            )
            for label in {source.key, source.list_name, source.source_label}:
                with self.subTest(key=source.key, label=label):
                    self.assertTrue(_list_label_matches(decision, label))

    def test_a_registered_spelling_does_not_reach_another_list(self):
        from brightway_flows.lookup.recorded import _list_label_matches

        decision = RecordedDecision(
            elementary_flow_id="whatever", list_name="stepwise", list_version="2006-1.09"
        )
        self.assertFalse(_list_label_matches(decision, "bafu"))

    def test_a_list_the_registry_never_heard_of_still_matches_itself(self):
        """A fixture build's lists are nobody's registry entries; the label
        falls back to the decision's own spellings, hyphen/space collapsed."""
        from brightway_flows.lookup.recorded import _list_label_matches

        decision = RecordedDecision(
            elementary_flow_id="whatever", list_name="somelist", list_version="1.0"
        )
        self.assertTrue(_list_label_matches(decision, "somelist"))
        self.assertTrue(_list_label_matches(decision, "somelist 1.0"))
        self.assertFalse(_list_label_matches(decision, "otherlist"))


class AgainstARealBuildTestCase(unittest.TestCase):
    """The fixture is two rows; a build is a hundred thousand links."""

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
        cls.connection = sqlite3.connect(f"file:{CONSENSUS_DB_FILEPATH}?mode=ro", uri=True)

    @classmethod
    def tearDownClass(cls) -> None:
        if hasattr(cls, "connection"):
            cls.connection.close()
        structlog.reset_defaults()
        super().tearDownClass()

    def _sample(self, list_name: str, list_version: str, limit: int = 200):
        return self.connection.execute(
            "SELECT source_flow_uuid, source_flow_name, elementary_flow_uuid "
            "FROM elementary_flow_sources WHERE list_name = ? AND list_version = ? "
            "AND source_flow_uuid != '' LIMIT ?",
            (list_name, list_version, limit),
        ).fetchall()

    def test_every_sampled_row_of_every_merged_list_is_answered_exactly(self):
        """Including EF 3.1 itself, which the plan does not mention and which is
        94,040 of the 110,993 links: a caller holding the base list gets an exact
        answer for all of it."""
        lists = self.connection.execute(
            "SELECT DISTINCT list_name, list_version FROM elementary_flow_sources"
        ).fetchall()
        self.assertGreaterEqual(len(lists), 2)
        for list_name, list_version in lists:
            rows = self._sample(list_name, list_version)
            with self.subTest(list=f"{list_name}-{list_version}", rows=len(rows)):
                self.assertTrue(rows)
                results = self.matcher.match_many(
                    FlowQuery(
                        name=name or "unknown",
                        list_key=f"{list_name}-{list_version}",
                        identifier=uuid,
                    )
                    for uuid, name, _expected in rows
                )
                wrong = [
                    (uuid, expected, result.elementary_flow_id)
                    for (uuid, _name, expected), result in zip(rows, results)
                    if not result.matched or result.elementary_flow_id != expected
                ]
                self.assertEqual(wrong, [])
                self.assertTrue(all(r.tier == TIER_RECORDED for r in results))

    def test_most_name_collisions_are_places_not_disagreements(self):
        """#357's claim, as a measurement.  Resolved to a place, the recorded
        names split into thousands of unanimous keys and a few dozen genuine
        disagreements -- 15,756 against 43 on the 30 August 2026 build -- and
        most of the disagreements are ones a `source_label` could settle."""
        decisions = RecordedDecisions(CONSENSUS_DB_FILEPATH)
        self.assertGreater(decisions.context_keys, 1000)
        self.assertLessEqual(
            decisions.conflicted_context_keys / max(decisions.context_keys, 1), 0.01
        )
        self.assertLessEqual(
            decisions.arbitrable_context_keys, decisions.conflicted_context_keys
        )

    def test_a_decision_three_lists_agree_about_answers_by_name(self):
        """#357's own example: `Oxygen` as a resource from air, recorded onto
        the same flow by BAFU, ecoinvent 3.12 and ecoinvent 3.8, and reachable
        by a caller with nothing but the name and a SimaPro compartment."""
        matcher = FlowMatcher.from_results(CONSENSUS_DB_FILEPATH, recorded_by_name=True)
        result = matcher.match(
            FlowQuery(
                name="Oxygen",
                context=["Raw", "in air"],
                unit="kg",
                simapro_origin=True,
            )
        )
        self.assertEqual(result.tier, TIER_RECORDED_BY_NAME)
        self.assertEqual(
            result.elementary_flow_id, "e2fb04b0-6555-11dd-ad8b-0800200c9a66"
        )

    def test_the_lineage_settles_unqualified_carbon_dioxide(self):
        """#359's own example: `Carbon dioxide` in unspecified air is fossil to
        BAFU and Stepwise and land-use change to ecoinvent, so it declines --
        unless the caller says their list is Stepwise-shaped, in which case
        Stepwise's recorded ruling answers and the answer says so."""
        matcher = FlowMatcher.from_results(CONSENSUS_DB_FILEPATH, recorded_by_name=True)
        undecided = matcher.match(
            FlowQuery(
                name="Carbon dioxide",
                context=["Emissions to air", ""],
                unit="kg",
                cas="124-38-9",
                simapro_origin=True,
            )
        )
        self.assertEqual(undecided.tier, TIER_ALGORITHM)
        ruled = matcher.match(
            FlowQuery(
                name="Carbon dioxide",
                context=["Emissions to air", ""],
                unit="kg",
                cas="124-38-9",
                simapro_origin=True,
                source_label="stepwise-2006-1.09",
            )
        )
        self.assertEqual(ruled.tier, TIER_RECORDED_BY_NAME)
        self.assertEqual(ruled.pref_label, "Carbon Dioxide (fossil)")
        self.assertEqual(
            ruled.selector_details["arbitrated_by_source_label"], "stepwise-2006-1.09"
        )
        self.assertTrue(ruled.selector_details["recorded_alternatives"])


if __name__ == "__main__":
    unittest.main()
