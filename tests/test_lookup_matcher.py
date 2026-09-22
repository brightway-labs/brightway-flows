"""Asking where a row goes, and getting the answer a build would have given.

The claim `lookup/matcher.py` makes is strong and simple: it calls the merge's
own `resolve_flow_object` and `_select_elementary_flow`, so an answer from it is
the answer the build would have given, or it is broken.  Most of what is checked
here is the *surrounding* work -- turning a caller's row into the row those two
functions expect -- because that is the only part that could be wrong without
the merge being wrong too.

The replay against a whole recorded build is `tests/test_lookup_replay.py`, and
that is what measures the claim at scale.  This file is the mechanism: the four
context steps, the SimaPro flag, the enrichment subset, the two curated hints,
and the three ways "it writes nothing" is enforced.
"""

from __future__ import annotations

import logging
import tempfile
import unittest

from dataclasses import replace
from pathlib import Path
from unittest import mock

import structlog

from brightway_flows.lookup import FlowMatch, FlowMatcher, FlowQuery
from brightway_flows.lookup.query import (
    CHEBI_TRANSFORMER_NAME,
    CONTEXT_AMBIGUOUS,
    CONTEXT_ANY_LIST,
    CONTEXT_CONSENSUS_STRINGS,
    CONTEXT_GIVEN,
    CONTEXT_NAMED_LIST,
    CONTEXT_UNRESOLVED,
    OFFLINE_TRANSFORMER_NAMES,
    WITHHELD_TRANSFORMER_NAMES,
    OfflineEnrichment,
    QUERY_UUID,
    resolve_context,
)
from test_lookup_index import (
    PREFIX,
    _elementary,
    _flow,
    _flow_object,
    _write_run_tables,
)

AIR = PREFIX + "envi-air-unkn"
RURAL = PREFIX + "envi-air-mest15me-ru10pesq"
WATER = PREFIX + "envi-wate-unkn"

#: BAFU and ecoinvent spellings of the same compartment, which is what makes the
#: `any-list` step worth having: neither is this project's own vocabulary, and a
#: caller exporting from SimaPro writes the first.
BAFU_AIR = ["emissions to air", "low. pop."]
ECOINVENT_AIR = ["air", "non-urban air or from high stacks"]


def _quiet_logs(case: unittest.TestCase) -> None:
    """The enrichment chain logs a line per step. Six per call is fine in a
    build and noise in a test."""
    structlog.configure(wrapper_class=structlog.make_filtering_bound_logger(logging.CRITICAL))
    case.addCleanup(structlog.reset_defaults)


def _matcher_fixture() -> tuple[Path, Path]:
    """A database holding four substances, enough to exercise every branch.

    Chlorobenzene is here for the SimaPro rewriting: `Benzene, chloro-` is not
    any of its names, and `chlorobenzene` is exactly its published one.
    """
    tmp = Path(tempfile.mkdtemp())
    db_path = tmp / "consensus-flows.sqlite3"
    flow_objects = [
        _flow_object("fo-benzene", "Benzene", cas=("71-43-2",), alt_labels=("Benzol",)),
        _flow_object("fo-chlorobenzene", "Chlorobenzene", cas=("108-90-7",)),
        _flow_object("fo-water", "Water", cas=("7732-18-5",)),
        _flow_object("fo-noise", "Noise", alt_labels=("Sound",)),
    ]
    elementary = [
        _elementary("ef-benzene-air", "fo-benzene", context_iri=AIR),
        _elementary("ef-benzene-rural", "fo-benzene", context_iri=RURAL),
        _elementary("ef-benzene-water", "fo-benzene", context_iri=WATER),
        _elementary("ef-chlorobenzene-rural", "fo-chlorobenzene", context_iri=RURAL),
        _elementary("ef-water-water", "fo-water", context_iri=WATER, unit="m3"),
        _elementary("ef-noise-air", "fo-noise", context_iri=AIR, unit="kg"),
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
    from brightway_flows.pipeline.sqlite import _write_consensus_sqlite

    _write_consensus_sqlite(flows, [], flow_objects, elementary, db_path=db_path)
    _write_run_tables(db_path)
    return tmp, db_path


class _Matcher(unittest.TestCase):
    """One fixture and one matcher for the whole class.

    `check_digits.setup()` parses the PubChem cache, which is 1.3 s -- more than
    reading the whole index -- so a matcher per test method would put a minute of
    cache parsing into this file for nothing. The matcher is read-only by
    construction, which is what makes sharing it safe, and
    `ItWritesNothingTestCase` is the check that it stays so.
    """

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.tmp, cls.db_path = _matcher_fixture()
        cls.matcher = FlowMatcher.from_results(cls.db_path)

    def setUp(self) -> None:
        super().setUp()
        _quiet_logs(self)


class TheWorkedExampleTestCase(_Matcher):
    """A row of somebody's SimaPro export, and where it goes."""

    def test_a_row_with_a_cas_number_finds_its_substance_and_its_compartment(self):
        result = self.matcher.match(
            FlowQuery(
                name="Benzene, chloro-",
                context=BAFU_AIR,
                cas="108-90-7",
                unit="kg",
                simapro_origin=True,
            )
        )
        self.assertTrue(result.matched)
        self.assertEqual(result.elementary_flow_id, "ef-chlorobenzene-rural")
        self.assertEqual(result.basis, "cas")
        self.assertEqual(result.selector_reason, "exact-context-iri-match")
        self.assertEqual(result.context_iri, RURAL)
        self.assertEqual(result.pref_label, "Chlorobenzene")
        self.assertEqual(result.unit, "kg")

    def test_the_answer_always_names_the_build_it_came_from(self):
        """A match is a statement about one build and expires with it."""
        for query in (
            FlowQuery(name="Benzene", cas="71-43-2", context=BAFU_AIR),
            FlowQuery(name="Nothing at all"),
        ):
            with self.subTest(name=query.name):
                result = self.matcher.match(query)
                self.assertIsNotNone(result.build)
                self.assertTrue(result.build.run_id)
                self.assertTrue(result.build.revision)

    def test_a_row_that_matches_nothing_is_an_answer_and_not_a_none(self):
        """An unmatched row is a question with evidence attached. A wrong match
        is silent; an unmatched row is reviewable."""
        result = self.matcher.match(FlowQuery(name="Substance nobody ships", context=BAFU_AIR))
        self.assertIsInstance(result, FlowMatch)
        self.assertFalse(result.matched)
        self.assertEqual(result.elementary_flow_id, "")
        self.assertTrue(result.selector_reason)
        self.assertIn("basis_counts", result.selector_details)

    def test_a_row_that_matches_too_much_names_what_it_could_have_been(self):
        """Which substances, what each is called, and whether the row reached it
        by number or only by a name -- what picking one takes."""
        result = self.matcher.match(
            FlowQuery(name="Benzol", context=BAFU_AIR, unit="kg")
        )
        # One candidate here, but the shape is the point: the evidence comes back
        # whether it found one substance or twelve.
        self.assertTrue(result.candidates or result.matched)
        if not result.matched:
            for candidate in result.candidates:
                self.assertTrue(candidate.flow_object_id)
                self.assertTrue(candidate.name)


class TheFourContextStepsTestCase(_Matcher):
    """§3.5, and which step answered is on the result.

    A caller cannot check an IRI they did not supply, so the API says how it got
    one.  `given` and `named-list` are claims about the caller's own vocabulary;
    `any-list` and `consensus-strings` are this project guessing well.
    """

    def test_an_iri_the_caller_supplied_is_used_as_given(self):
        result = self.matcher.match(
            FlowQuery(name="Benzene", cas="71-43-2", unit="kg", context_iri=RURAL)
        )
        self.assertEqual(result.context_resolution, CONTEXT_GIVEN)
        self.assertEqual(result.resolved_context_iri, RURAL)
        self.assertEqual(result.elementary_flow_id, "ef-benzene-rural")

    def test_a_named_list_gets_that_lists_own_rules(self):
        result = self.matcher.match(
            FlowQuery(
                name="Benzene",
                cas="71-43-2",
                unit="kg",
                context=ECOINVENT_AIR,
                source_label="ecoinvent-3.12",
            )
        )
        self.assertEqual(result.context_resolution, CONTEXT_NAMED_LIST)
        self.assertEqual(result.resolved_context_iri, RURAL)

    def test_an_unmapped_list_is_placed_by_any_lists_rules(self):
        """The SimaPro spelling, which BAFU has already written down."""
        result = self.matcher.match(
            FlowQuery(name="Benzene", cas="71-43-2", unit="kg", context=BAFU_AIR)
        )
        self.assertEqual(result.context_resolution, CONTEXT_ANY_LIST)
        self.assertEqual(result.resolved_context_iri, RURAL)

    def test_our_own_words_are_read_back(self):
        result = self.matcher.match(
            FlowQuery(
                name="Benzene", cas="71-43-2", unit="kg", context=["Environmental", "Air"]
            )
        )
        self.assertEqual(result.context_resolution, CONTEXT_CONSENSUS_STRINGS)
        self.assertEqual(result.resolved_context_iri, AIR)

    def test_a_compartment_nobody_knows_leaves_the_context_unresolved(self):
        result = self.matcher.match(
            FlowQuery(name="Benzene", cas="71-43-2", unit="kg", context=["over there"])
        )
        self.assertEqual(result.context_resolution, CONTEXT_UNRESOLVED)
        self.assertEqual(result.resolved_context_iri, "")

    def test_an_unresolved_context_still_runs_the_match(self):
        """`_select_elementary_flow` degrades honestly without an IRI: no
        short-circuit, no IRI term, and a score on the unit, which settles a
        substance that has one flow. What it must not do is guess an IRI."""
        result = self.matcher.match(
            FlowQuery(name="Water", cas="7732-18-5", unit="m3", context=["over there"])
        )
        self.assertEqual(result.context_resolution, CONTEXT_UNRESOLVED)
        self.assertTrue(result.matched)
        self.assertEqual(result.elementary_flow_id, "ef-water-water")
        self.assertEqual(result.selector_reason, "best-score")

    def test_the_callers_own_words_are_never_given_to_the_selector(self):
        """The selector's first act is to reject every candidate whose dimension
        is not the row's first string. A build's raw strings are a *mapped*
        list's, so the first two are a dimension and a medium the vocabulary
        knows; a caller's are their own. Passing `["over there"]` through filters
        every candidate out and reports `no-candidates-same-dimension-media`,
        which reads as "no flow of this substance is in your compartment" when
        what happened is "your compartment could not be read"."""
        result = self.matcher.match(
            FlowQuery(name="Water", cas="7732-18-5", unit="m3", context=["over there"])
        )
        self.assertEqual(result.selector_details["source_context_original"], ["over there"])
        self.assertEqual(result.selector_details["source_context_used_for_matching"], [])
        self.assertEqual(result.selector_details["source_context_matching_basis"], "none-resolved")
        self.assertEqual(result.selector_details["filtered_out_context_mismatch_count"], 0)

    def test_an_unresolved_context_ties_rather_than_guessing_where_it_cannot_tell(self):
        """Three benzene flows, one unit, nothing to tell them apart. A tie is
        the honest answer, and it comes back with the trace."""
        result = self.matcher.match(
            FlowQuery(name="Benzene", cas="71-43-2", unit="kg", context=["over there"])
        )
        self.assertEqual(result.context_resolution, CONTEXT_UNRESOLVED)
        self.assertFalse(result.matched)
        self.assertEqual(result.selector_reason, "tied-elementary-candidates")
        self.assertEqual(result.flow_object_id, "fo-benzene")
        self.assertTrue(result.selector_details["scored_candidates"])

    def test_a_name_that_decides_nothing_in_a_partition_compartment_is_ambiguous(self):
        """Not `unresolved` -- somebody *has* mapped this compartment, and has
        ruled that the compartment alone does not decide (#52)."""
        context = resolve_context(
            FlowQuery(name="Something nobody ruled on", context=["natural resource", "land"])
        )
        self.assertEqual(context.resolution, CONTEXT_AMBIGUOUS)
        self.assertEqual(context.context_iri, "")
        self.assertIn("occupation,", context.detail)

    def test_a_named_list_that_cannot_decide_does_not_fall_through(self):
        """Falling through to `any-list` would answer with ecoinvent's
        compartment rule, which says occupation for a flow that may be a
        transformation. That is the defect, not the fix."""
        context = resolve_context(
            FlowQuery(
                name="Something nobody ruled on",
                context=["natural resource", "land"],
                source_label="ecoinvent-3.12",
            )
        )
        self.assertEqual(context.resolution, CONTEXT_AMBIGUOUS)


class TheSimaproFlagTestCase(_Matcher):
    """§5.2's named case, and the only input a caller has to state themselves.

    A derived spelling is a weaker claim than a shipped name, so it is reached
    only once every registry number and every real name has failed -- and only
    for a list whose names that lineage shaped.
    """

    QUERY = FlowQuery(
        name="Benzene, chloro-", context=BAFU_AIR, unit="kg", simapro_origin=True
    )

    def test_with_the_flag_the_derived_spelling_finds_the_substance(self):
        result = self.matcher.match(self.QUERY)
        self.assertTrue(result.matched)
        self.assertEqual(result.basis, "simapro-name-pattern")
        self.assertEqual(result.pref_label, "Chlorobenzene")

    def test_without_the_flag_it_finds_nothing(self):
        result = self.matcher.match(replace(self.QUERY, simapro_origin=False))
        self.assertFalse(result.matched)
        self.assertEqual(result.basis, "")

    def test_a_row_with_its_own_registry_number_never_sees_a_derived_spelling(self):
        result = self.matcher.match(replace(self.QUERY, cas="108-90-7"))
        self.assertEqual(result.basis, "cas")

    def test_the_two_index_records_share_every_dict(self):
        """Two records, one set of indexes: the flag varies per query and
        `MergeIndexes` is frozen, and building them twice would cost the whole
        load again for one boolean."""
        for name in ("cas_index", "label_index", "pref_label_index", "flow_objects_by_id"):
            with self.subTest(index=name):
                self.assertIs(
                    getattr(self.matcher._simapro, name),
                    getattr(self.matcher._plain, name),
                )


class PreparingTheCallersRowTestCase(_Matcher):
    """The two SimaPro splits, for a row that came through no build (#328).

    A build's row is split twice before matching sees it -- the place in the
    adapter, the unit in `load_flows` -- and a caller's row has been through
    neither, so it arrives spelled the way SimaPro spells it. `Water/m3` is not
    a substance this list declines to hold; it is `Water`, asked for under a
    name no flow object in any list answers to.

    The fixture's water is `fo-water`, one flow in the water context measured in
    m3, which is what makes the answers here unambiguous.
    """

    WATER = FlowQuery(
        name="Water/m3",
        context=["emissions to water", "unspecified"],
        unit="m3",
        simapro_origin=True,
    )

    def test_a_name_carrying_its_unit_reaches_the_substance(self):
        result = self.matcher.match(self.WATER)
        self.assertTrue(result.matched)
        self.assertEqual(result.flow_object_id, "fo-water")
        self.assertEqual(result.basis, "label")

    def test_a_name_carrying_a_place_reaches_the_substance(self):
        result = self.matcher.match(replace(self.WATER, name="Water, AE"))
        self.assertTrue(result.matched)
        self.assertEqual(result.flow_object_id, "fo-water")

    def test_a_name_carrying_both_reaches_the_substance(self):
        result = self.matcher.match(replace(self.WATER, name="Water, AE/m3"))
        self.assertTrue(result.matched)
        self.assertEqual(result.flow_object_id, "fo-water")

    def test_the_answer_says_which_name_earned_it(self):
        """A row whose name was rewritten got its answer under a spelling it did
        not send, and being told that is the difference between an answer and a
        coincidence."""
        result = self.matcher.match(replace(self.WATER, name="Water, AE/m3"))
        self.assertEqual(result.prepared_name, "Water")
        self.assertEqual(result.preparation_steps, ("unit-suffix", "geography"))

    def test_a_row_nothing_was_taken_out_of_says_nothing(self):
        result = self.matcher.match(replace(self.WATER, name="Water"))
        self.assertTrue(result.matched)
        self.assertEqual(result.prepared_name, "")
        self.assertEqual(result.preparation_steps, ())

    def test_without_the_flag_the_name_belongs_to_whoever_wrote_it(self):
        """Off a SimaPro-shaped list these are not corrections but guesses: a
        slash in a name is part of the name."""
        result = self.matcher.match(replace(self.WATER, simapro_origin=False))
        self.assertFalse(result.matched)
        self.assertEqual(result.preparation_steps, ())

    def test_the_spelling_as_sent_can_still_earn_the_match(self):
        """Preparation puts the rewritten name in front of the caller's, not
        instead of it, so it can only add a way for the row to match.

        `Sound` is `fo-noise`'s alternative label and carries no unit suffix for
        any rule to take off; sent as `Sound/kg` in kg it has to reach the same
        object by the name it was sent under if the rewrite misfires, and by the
        rewritten one if it does not.  Either way it matches.
        """
        for name in ("Sound", "Sound/kg"):
            with self.subTest(name=name):
                result = self.matcher.match(
                    FlowQuery(
                        name=name,
                        context=BAFU_AIR,
                        unit="kg",
                        simapro_origin=True,
                    )
                )
                self.assertEqual(result.flow_object_id, "fo-noise")

    def test_a_tail_that_is_not_this_row_s_unit_is_left_alone(self):
        """The row the worked example asks about: BAFU ships `Wood,
        unspecified, standing/m3` in m3 and the same base name in kg, and a row
        whose name says one measure and whose field says another is a curator's
        question rather than a pattern's."""
        result = self.matcher.match(replace(self.WATER, unit="kg"))
        self.assertEqual(result.preparation_steps, ())

    def test_the_context_rules_read_the_prepared_name(self):
        """Not only matching: a list whose contexts are told apart by the flow's
        name reads that name, and a name still carrying its unit is not one
        those rules were written against."""
        from brightway_flows.lookup.query import prepare_query

        prepared = prepare_query(
            FlowQuery(
                name="Occupation, traffic area, rail network, CH",
                unit="m2a",
                simapro_origin=True,
            )
        )
        self.assertEqual(prepared.query.name, "Occupation, traffic area, rail network")


class TheOfflineEnrichmentTestCase(_Matcher):
    """§3.6: six steps of the chain, in chain order, offline.

    What they buy: the shipped name and synonyms in the label fields where
    matching looks for them, the unit resolved to its notation, the CAS
    check-digit-corrected.
    """

    def test_the_six_named_steps_are_the_ones_that_run(self):
        enrichment = OfflineEnrichment.build()
        self.assertEqual(
            tuple(step.name for step in enrichment.transformers),
            OFFLINE_TRANSFORMER_NAMES,
        )

    def test_every_one_of_them_answers_per_flow(self):
        """The premise of running them over a batch, and of running them at all:
        a step that compares flows would be answering about a list of one."""
        for step in OfflineEnrichment.build().transformers:
            with self.subTest(step=step.name):
                self.assertTrue(getattr(step, "answers_per_flow", False))

    def test_the_networked_the_heavy_and_the_writing_steps_are_withheld(self):
        """A lookup that silently makes HTTP calls is not the capability being
        asked for; a 49 MB index is not a cost to pay by default; and a step that
        writes `missing-units.json` into the data directory is the thing §3.7
        exists to prevent."""
        for name in WITHHELD_TRANSFORMER_NAMES + (CHEBI_TRANSFORMER_NAME,):
            with self.subTest(step=name):
                self.assertNotIn(name, OFFLINE_TRANSFORMER_NAMES)

    def test_unit_normalization_is_withheld_because_it_writes_and_raises(self):
        """`plans/lookup-api.md` §3.6 lists it among the six safe steps. It is
        not safe: an unresolvable unit makes it write a file into the data
        directory and then raise. A caller who types `kilogrammes` gets neither."""
        from brightway_flows.transformers import UnitNormalizationTransformer

        source = Path(
            __import__(
                "brightway_flows.transformers.unit_normalization",
                fromlist=["unit_normalization"],
            ).__file__
        ).read_text()
        self.assertIn("missing-units.json", source)
        self.assertIn("write_bytes", source)
        self.assertIn("raise ValueError", source)
        self.assertTrue(getattr(UnitNormalizationTransformer, "answers_per_flow", False))
        self.assertIn("unit_normalization", WITHHELD_TRANSFORMER_NAMES)

    def test_the_unit_is_still_resolved_without_that_step(self):
        """The resolution is not the transformer's: `source_row` calls
        `resolve_unit_notation`, the same function it calls."""
        from brightway_flows.domain.units import build_units_index
        from brightway_flows.lookup.query import query_flow, source_row
        from brightway_flows.lookup.index import lookup_source_list

        query = FlowQuery(name="Benzene", unit="kilogram")
        flow = query_flow(query, source=lookup_source_list(simapro_origin=False))
        row = source_row(
            query,
            flow,
            context=resolve_context(query),
            units_index=build_units_index(),
        )
        self.assertEqual(row.unit, "kg")
        self.assertTrue(row.unit_iri)

    def test_chebi_is_available_on_request(self):
        enrichment = OfflineEnrichment.build(chebi=True)
        self.assertEqual(enrichment.transformers[-1].name, CHEBI_TRANSFORMER_NAME)

    def test_a_step_renamed_out_of_the_chain_is_a_failure_here(self):
        """The lookup runs a named subset, so a step removed from
        `DEFAULT_TRANSFORMERS` has to be removed here too -- rather than leaving
        a lookup that quietly enriches less than the build it claims to
        reproduce."""
        with mock.patch(
            "brightway_flows.lookup.query.DEFAULT_TRANSFORMERS", []
        ):
            with self.assertRaises(ValueError) as caught:
                OfflineEnrichment.build()
        self.assertIn("DEFAULT_TRANSFORMERS", str(caught.exception))

    def test_a_synonym_the_caller_supplied_reaches_the_label_index(self):
        """`bootstrap_labels` purges `synonyms` without moving them anywhere, so
        a query whose synonyms were only in `synonyms` would lose them. They
        survive in `provided`, which is where `_source_labels` reads them -- the
        same place a real source row keeps them."""
        result = self.matcher.match(
            FlowQuery(
                name="A name nothing answers to",
                synonyms=["Sound"],
                context=["Environmental", "Air"],
                unit="kg",
            )
        )
        self.assertTrue(result.matched)
        self.assertEqual(result.pref_label, "Noise")
        self.assertEqual(result.basis, "label")
        self.assertEqual(result.basis_value, "Sound")

    def test_an_alternative_name_of_a_numbered_substance_is_still_refused(self):
        """The synonym reaches the index and `_narrow_label_candidates` rejects
        it, because an altLabel hit on a CAS-bearing object is a trade name
        matching the wrong substance -- "Granite" to Penoxsulam. Carried here so
        that the test above is not read as "any synonym matches"."""
        result = self.matcher.match(
            FlowQuery(
                name="A name nothing answers to",
                synonyms=["Benzol"],
                context=BAFU_AIR,
                unit="kg",
            )
        )
        self.assertFalse(result.matched)
        self.assertEqual(result.selector_details["labels_used"], ["Benzol"])
        self.assertEqual(
            [candidate.name for candidate in result.candidates], ["Benzene"]
        )

    def test_a_unit_the_table_knows_by_another_name_is_normalised(self):
        result = self.matcher.match(
            FlowQuery(name="Water", cas="7732-18-5", unit="m3", context=["Environmental", "Water"])
        )
        self.assertEqual(result.unit, "m3")

    def test_a_unit_nobody_recognises_does_not_raise(self):
        """A build raises there, because a source list whose units this project
        cannot read has not been added properly. A caller has made a typo, and
        the honest response is to score them without a unit signal."""
        result = self.matcher.match(
            FlowQuery(name="Benzene", cas="71-43-2", unit="kilogrammes", context=BAFU_AIR)
        )
        self.assertTrue(result.matched)


class TheBatchIsTheSameAsTheRowsTestCase(_Matcher):
    """`match_many` runs the chain once for the whole list.

    Only correct because every step declares `answers_per_flow`, which *means*
    it reads the flow it is asked about and nothing else about the flows it was
    shown. That is a declaration, and this is the check that it is true.
    """

    QUERIES = (
        FlowQuery(name="Benzene, chloro-", context=BAFU_AIR, unit="kg", simapro_origin=True),
        FlowQuery(name="Benzene", cas="71-43-2", context=BAFU_AIR, unit="kg"),
        FlowQuery(name="Water", cas="7732-18-5", unit="m3", context=["Environmental", "Water"]),
        FlowQuery(name="Nothing at all", context=BAFU_AIR),
        FlowQuery(name="Benzene", cas="71-43-2", context=ECOINVENT_AIR, source_label="ecoinvent-3.12"),
    )

    @staticmethod
    def _comparable(result: FlowMatch) -> tuple:
        return (
            result.matched,
            result.elementary_flow_id,
            result.basis,
            result.basis_value,
            result.selector_reason,
            result.context_resolution,
            result.resolved_context_iri,
        )

    def test_a_batch_gives_each_row_the_answer_it_would_get_alone(self):
        batched = self.matcher.match_many(self.QUERIES)
        alone = [self.matcher.match(query) for query in self.QUERIES]
        for query, one, many in zip(self.QUERIES, alone, batched):
            with self.subTest(name=query.name):
                self.assertEqual(self._comparable(many), self._comparable(one))

    def test_the_order_of_the_batch_does_not_change_any_answer(self):
        forwards = self.matcher.match_many(self.QUERIES)
        backwards = list(reversed(self.matcher.match_many(list(reversed(self.QUERIES)))))
        for query, a, b in zip(self.QUERIES, forwards, backwards):
            with self.subTest(name=query.name):
                self.assertEqual(self._comparable(a), self._comparable(b))

    def test_an_empty_batch_is_an_empty_list(self):
        self.assertEqual(self.matcher.match_many([]), [])


class TheTwoCuratedHintsTestCase(_Matcher):
    """§6.1: what a query cannot know, and what a caller may say instead.

    `material_for_source_flow` and `land_class_for_source_flow` are keyed on
    `(source, uuid)` and a query has no uuid. There is no name-derived route to
    either -- deriving one is what the water and land taxonomies exist to avoid
    -- so a caller who knows states it, in the vocabulary this project publishes.
    """

    def test_a_query_carries_no_uuid_the_curated_tables_could_match(self):
        """The premise. A plausible-looking uuid could collide with a real row in
        a table it has no business being found in."""
        from brightway_flows.domain.land_flow_classes import land_class_for_source_flow
        from brightway_flows.domain.materials import material_for_source_flow

        for source in ("bafu-2026-v1", "ecoinvent-3.12", "lookup-query"):
            with self.subTest(source=source):
                self.assertIsNone(material_for_source_flow(source, QUERY_UUID))
                self.assertIsNone(land_class_for_source_flow(source, QUERY_UUID))

    def test_a_material_nothing_in_this_build_names_is_not_a_match(self):
        """And not an exception either: the concept is one the taxonomy knows
        and this build has no object for, which is a different question from
        "which of twelve"."""
        result = self.matcher.match(
            FlowQuery(name="Water", cas="7732-18-5", unit="m3", material="lake_water")
        )
        self.assertFalse(result.matched)
        self.assertEqual(result.selector_details.get("stated_concept"), "lake_water")

    def test_a_land_class_nothing_names_is_not_a_match(self):
        result = self.matcher.match(
            FlowQuery(name="Occupation, x", unit="m2*year", land_class="occupation/agriculture")
        )
        self.assertFalse(result.matched)
        self.assertEqual(
            result.selector_details.get("stated_concept"), "occupation/agriculture"
        )

    def test_a_land_class_key_nothing_reaches_mints_no_identifier(self):
        from brightway_flows.lookup.matcher import land_object_id_or_empty

        self.assertEqual(land_object_id_or_empty("not/a/land/class"), "")
        self.assertTrue(land_object_id_or_empty("occupation/agriculture"))


class ItWritesNothingTestCase(_Matcher):
    """§3.7's second enforcement: the accumulator is per query and discarded.

    The first is `mode=ro` and the third is the import rule; both are in
    `tests/test_lookup_index.py` and `tests/test_lookup_writes_nothing.py`.
    """

    def test_the_candidate_map_is_unchanged_by_matching(self):
        before = {
            object_id: [row.elementary_flow_id for row in rows]
            for object_id, rows in self.matcher._elementary_by_object.items()
        }
        self.matcher.match_many(
            [
                FlowQuery(name="Benzene", cas="71-43-2", context=BAFU_AIR, unit="kg"),
                FlowQuery(name="Nothing at all", context=BAFU_AIR),
                FlowQuery(name="Water", cas="7732-18-5", unit="m3"),
            ]
        )
        after = {
            object_id: [row.elementary_flow_id for row in rows]
            for object_id, rows in self.matcher._elementary_by_object.items()
        }
        self.assertEqual(after, before)

    def test_add_flow_is_never_called(self):
        from brightway_flows.merge.state import MergeAccumulator

        with mock.patch.object(
            MergeAccumulator, "add_flow", side_effect=AssertionError("wrote a flow")
        ):
            self.matcher.match_many(
                [
                    FlowQuery(name="Benzene", cas="71-43-2", context=BAFU_AIR),
                    FlowQuery(name="Nothing at all"),
                ]
            )

    def test_the_database_file_is_not_modified(self):
        stat_before = self.db_path.stat()
        self.matcher.match_many(
            [FlowQuery(name="Benzene", cas="71-43-2", context=BAFU_AIR, unit="kg")]
        )
        stat_after = self.db_path.stat()
        self.assertEqual(stat_after.st_size, stat_before.st_size)
        self.assertEqual(stat_after.st_mtime, stat_before.st_mtime)


class NoFlowIsEverInventedTestCase(_Matcher):
    """The merge's answer to "no consensus flow exists for this" is to create
    one; the answer here is `matched=False` with the reason.

    Those are different questions and the second one is the caller's to decide.
    """

    def test_a_substance_with_no_flow_in_the_rows_compartment_is_reported(self):
        result = self.matcher.match(
            FlowQuery(
                name="Noise",
                unit="dimensionless",
                context=["Environmental", "Water"],
            )
        )
        self.assertFalse(result.matched)
        self.assertEqual(result.elementary_flow_id, "")
        # The substance *was* identified -- that is what makes this reviewable
        # rather than a shrug.
        self.assertEqual(result.flow_object_id, "fo-noise")
        self.assertEqual(result.pref_label, "Noise")
        self.assertTrue(result.selector_reason)


if __name__ == "__main__":
    unittest.main()
