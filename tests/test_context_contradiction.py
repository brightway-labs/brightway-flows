"""
A row is never published in a place that contradicts the place it named.

Matching a row is a search for a flow that already exists, and the search is
allowed to settle for less than the row said: a release to a lake published as a
release to water, unspecified, loses detail and says nothing false.  That is a
coarsening, and it is usually the only thing to do, because the base list often
has no lake.

What the selector used to do when no such flow existed was different in kind.
It widened to every flow of the same substance in the same medium and scored
them by how many words their contexts shared -- so BAFU's release of lead-210 to
a lake was published as a release to groundwater, which scored best because it
agreed on "an environmental release to water" and on the unit (#85).
Groundwater is not a vaguer way of saying lake.  It is a different place.

The rule is structural.  A context is a record of axes -- media, water body,
vertical strata, geography -- and each either names a value or says `Unknown`,
which is the absence of a claim rather than a claim.  A target contradicts a
source when it names a *different* value on an axis the source also named.
Pairs allowed to disagree anyway are the ones written down in
`correspondence-context-routing.json`, where the correspondence tables' own
permitted coarsenings already live.
"""

import unittest

from brightway_flows.domain.context_registry import context_from_dict
from brightway_flows.domain.elementary_flow import ElementaryFlow
from brightway_flows.merge.contexts import context_contradicts
from brightway_flows.merge.matching import _select_elementary_flow
from brightway_flows.merge.report import UnmatchedReason
from brightway_flows.merge.rows import _CREATABLE_SELECTOR_REASONS

NS = "https://vocab.brightway.one/flow-contexts/"

LAKE = NS + "envi-wate-lake"
RIVER = NS + "envi-wate-rive"
AQUIFER = NS + "envi-wate-unaq"
WATER_UNSPECIFIED = NS + "envi-wate-unkn"
SURFACE_WATER = NS + "envi-wate-suwa"
FORESTRY_SOIL = NS + "envi-grou-silv"
INDUSTRIAL_SOIL = NS + "envi-grou-indu"
FARM_SOIL = NS + "envi-grou-agri"
NON_AGRICULTURAL_SOIL = NS + "envi-grou-noag"
SOIL_UNSPECIFIED = NS + "envi-grou-unkn"
AIR_UNSPECIFIED = NS + "envi-air-unkn"
HIGH_STACK = NS + "envi-air-hist15me"


def _candidate(flow_id, context, context_iri, unit="kg"):
    """One elementary flow as the selector sees it.

    The context is spelled out as a dict and built into the `Context` the record
    carries, rather than resolved from the IRI: it keeps the `Unknown` values
    that `to_list()` drops, and it says here what each candidate's context is
    rather than making a reader look the IRI up.  Both halves of the comparison
    are still read from the IRI rather than from these strings.
    """
    return ElementaryFlow(
        elementary_flow_id=flow_id,
        flow_object_id="fo-1",
        source="EF 3.1",
        context=context_from_dict(context),
        context_iri=context_iri,
        unit=unit,
        unit_iri="",
        lcia_methods=[],
        general_comment=None,
    )


# Prefixes, not contexts: neither is one the vocabulary would accept on its own
# -- water needs a body and ground needs a geography -- and each is only ever
# spread into a complete context below.  Named `_PREFIX` so that is legible, and
# so `test_context_fixtures` is not the only thing that knows it.
WATER_PREFIX = {"dimension": "Environmental", "media": "Water"}
GROUND_PREFIX = {"dimension": "Environmental", "media": "Ground"}

AQUIFER_FLOW = _candidate("aquifer", {**WATER_PREFIX, "water_body": "Unconfined aquifer"}, AQUIFER)
LAKE_FLOW = _candidate("lake", {**WATER_PREFIX, "water_body": "Lake"}, LAKE)
SURFACE_FLOW = _candidate("surface", {**WATER_PREFIX, "water_body": "Surface water"}, SURFACE_WATER, unit="m3")
WATER_UNSPECIFIED_FLOW = _candidate("water-unspec", {**WATER_PREFIX, "water_body": "Unknown"}, WATER_UNSPECIFIED, unit="m3")
FARM_FLOW = _candidate("farm", {**GROUND_PREFIX, "geography": "Agricultural"}, FARM_SOIL)
NON_AGRICULTURAL_FLOW = _candidate("non-ag", {**GROUND_PREFIX, "geography": "Non-agricultural"}, NON_AGRICULTURAL_SOIL)
SOIL_UNSPECIFIED_FLOW = _candidate("soil-unspec", {**GROUND_PREFIX, "geography": "Unknown"}, SOIL_UNSPECIFIED)


class ContradictionRuleTestCase(unittest.TestCase):
    """The rule itself, on pairs of contexts."""

    def test_a_context_never_contradicts_itself(self):
        self.assertFalse(context_contradicts(LAKE, LAKE))

    def test_dropping_the_water_body_is_a_coarsening(self):
        """A lake release published as a release to water says nothing false."""
        self.assertFalse(context_contradicts(LAKE, WATER_UNSPECIFIED))

    def test_naming_another_water_body_is_a_contradiction(self):
        """The defect: groundwater is not a vaguer way of saying lake."""
        self.assertTrue(context_contradicts(LAKE, AQUIFER))
        self.assertTrue(context_contradicts(RIVER, LAKE))

    def test_naming_another_soil_is_a_contradiction(self):
        """Forest soil and farm soil differ by one word and are not the same place."""
        self.assertTrue(context_contradicts(FORESTRY_SOIL, FARM_SOIL))

    def test_naming_a_place_the_row_left_open_is_a_contradiction(self):
        """The other half of the same failure, and the same rule catches it.

        A row that said only "to water" did not say which water, and publishing
        it in a lake makes a claim the row never made.  It is not a coarsening:
        detail is being invented rather than dropped.
        """
        self.assertTrue(context_contradicts(WATER_UNSPECIFIED, LAKE))
        self.assertTrue(context_contradicts(AIR_UNSPECIFIED, HIGH_STACK))

    def test_a_disagreement_written_down_for_the_table_alone_is_not_allowed(self):
        """Forestry and industrial soil onto non-agricultural: permitted, unpublished.

        A correspondence table pointing either there is naming the nearest flow
        EF has, and the routing file goes on permitting that.  Publishing the
        emission there is the other question, and its answer is no: taking the
        target's compartment made where a forestry emission lands depend on
        whether EF happens to ship the substance (#84).
        """
        self.assertTrue(context_contradicts(FORESTRY_SOIL, NON_AGRICULTURAL_SOIL))
        self.assertTrue(context_contradicts(INDUSTRIAL_SOIL, NON_AGRICULTURAL_SOIL))

    def test_groundwater_onto_fresh_water_is_not_allowed_either(self):
        """The third entry of that kind, and the one that used to be published.

        EF 3.1 has no groundwater emission compartment, so a correspondence
        table pointing ecoinvent's `water / ground-` rows at EF's fresh water is
        naming the nearest flow EF has, and the routing file goes on permitting
        that.  Publishing them there was allowed on the grounds that ecoinvent's
        own `EF v3.1` implementation reads the freshwater factor for these
        flows -- a fact about characterisation, not about where the release
        happened.  The row said groundwater, and that is the stronger claim, so
        the target's compartment is no longer read off it: ecoinvent's rows join
        BAFU's `emissions to water / groundwater` on the aquifer instead of
        splitting from them onto surface water (#77).
        """
        self.assertTrue(context_contradicts(AQUIFER, SURFACE_WATER))

    def test_those_three_may_still_be_coarsened_onto_the_unspecified_context(self):
        """Refusing one target is not refusing every target above the row.

        `Unknown` on the water body and geography axes is the absence of a
        claim, so it stays a coarsening whatever the routing file says about
        non-agricultural soil or surface water.  This is the half that stops the
        refusal growing into a rule that strands a row with nowhere to go.
        """
        self.assertFalse(context_contradicts(FORESTRY_SOIL, SOIL_UNSPECIFIED))
        self.assertFalse(context_contradicts(INDUSTRIAL_SOIL, SOIL_UNSPECIFIED))
        self.assertFalse(context_contradicts(AQUIFER, WATER_UNSPECIFIED))

    def test_a_context_this_project_does_not_know_is_not_a_contradiction(self):
        """A different defect with a different fix; reporting it here buries these."""
        self.assertFalse(context_contradicts("", LAKE))
        self.assertFalse(context_contradicts(LAKE, ""))
        self.assertFalse(context_contradicts(NS + "not-a-context", LAKE))


class SelectorVetoTestCase(unittest.TestCase):
    """The rule where it bites: choosing a flow for a row no table covers."""

    LAKE_ROW = {
        "source_context": ["Environmental", "Water", "Lake"],
        "source_unit": "kg",
        "source_context_iri": LAKE,
    }

    def test_a_lake_row_is_not_published_in_groundwater(self):
        """BAFU's lead-210, which is what #85 was written about.

        The aquifer flow wins on score -- it agrees on the medium and on the
        unit -- and is refused anyway.
        """
        selected, reason, details = _select_elementary_flow(
            [AQUIFER_FLOW, SURFACE_FLOW], **self.LAKE_ROW
        )
        self.assertIsNone(selected)
        self.assertEqual(reason, UnmatchedReason.CONTEXT_CONTRADICTION)
        self.assertEqual(details["rejected_contradicting_context_iri"], AQUIFER)
        self.assertEqual(details["non_contradicting_candidate_count"], 0)

    def test_a_refused_row_gets_a_flow_of_its_own(self):
        """Not the review queue: the row's own place is known, so it can be made.

        It is what the disagreement was measured against, so creating a flow
        there is not a guess.
        """
        self.assertIn(
            UnmatchedReason.CONTEXT_CONTRADICTION, _CREATABLE_SELECTOR_REASONS
        )

    def test_a_coarsening_is_preferred_to_a_contradiction(self):
        """Scoring is re-run on what is left, and unspecified water is left.

        The aquifer flow scores higher, because it is the one that also
        agrees on the unit -- which is exactly how BAFU's lake row came to be
        published in groundwater.  Preferring the lower-scoring honest answer is
        the whole of #85's change; the score itself is untouched.

        **Rewritten for #112.**  This used to end by asserting the row was
        published on `water-unspec`.  It is not any more: the row names a
        compartment this list holds, nothing offered is in it, and #112 gives it
        a flow of its own rather than the nearest coarser one.  What #85 put
        here is unchanged and is what is still asserted -- the aquifer flow is
        rejected for contradicting the row, and the re-scoring finds exactly one
        honest candidate.  The two refusals stack, in that order, which is why
        both are visible in the details.
        """
        selected, reason, details = _select_elementary_flow(
            [AQUIFER_FLOW, WATER_UNSPECIFIED_FLOW], **self.LAKE_ROW
        )
        self.assertEqual(details["rejected_contradicting_context_iri"], AQUIFER)
        self.assertEqual(details["non_contradicting_candidate_count"], 1)
        self.assertEqual(details["rejected_coarser_context_iri"], WATER_UNSPECIFIED)
        self.assertIsNone(selected)
        self.assertEqual(reason, UnmatchedReason.NO_CANDIDATE_IN_STATED_CONTEXT)

    def test_an_honest_coarsening_is_not_a_contradiction(self):
        """The veto does not fire on a candidate that merely says less.

        **Rewritten for #112**, which changed the outcome but not the finding.
        The assertion that matters to #85 is the last one: `water-unspec` says
        nothing this row denies, so the veto leaves it alone and no
        contradiction is recorded.  What has changed is what happens next --
        the row named a lake, no candidate is in a lake, and #112 makes it a
        lake flow instead of publishing it as water, unspecified.
        """
        selected, reason, details = _select_elementary_flow(
            [WATER_UNSPECIFIED_FLOW], **self.LAKE_ROW
        )
        self.assertIsNone(selected)
        self.assertEqual(reason, UnmatchedReason.NO_CANDIDATE_IN_STATED_CONTEXT)
        self.assertNotIn("rejected_contradicting_context_iri", details)

    def test_an_exact_match_is_never_second_guessed(self):
        """A flow in the row's own context short-circuits before any scoring."""
        selected, reason, _details = _select_elementary_flow(
            [LAKE_FLOW, AQUIFER_FLOW], **self.LAKE_ROW
        )
        self.assertEqual(selected.elementary_flow_id, "lake")
        self.assertEqual(reason, "exact-context-iri-match")

    def test_a_tie_is_still_a_tie(self):
        """The veto judges a winner, so it cannot break a tie -- deliberately.

        Filtering the candidates before scoring would be simpler and would turn
        113 rows on the 2026-08-13 build from "gets a flow in its own context"
        into "coarsened onto an existing one", most of them ecoinvent's forestry
        soil.  That question has since been answered the other way -- a forestry
        row keeps its compartment (#84) -- and this is still not where it was
        answered: the row below has no honest candidate to be re-decided among,
        and a tie among the dishonest ones is a tie.
        """
        selected, reason, _details = _select_elementary_flow(
            [FARM_FLOW, NON_AGRICULTURAL_FLOW, SOIL_UNSPECIFIED_FLOW],
            source_context=["Environmental", "Ground", "Silvicultural"],
            source_unit="kg",
            source_context_iri=FORESTRY_SOIL,
        )
        self.assertIsNone(selected)
        self.assertEqual(reason, UnmatchedReason.TIED_ELEMENTARY_CANDIDATES)


if __name__ == "__main__":
    unittest.main()


class NoCandidateInTheStatedContextTestCase(unittest.TestCase):
    """#112: a row that names a compartment this list holds is published in it.

    The sibling of the veto above, one step weaker.  There, every candidate
    named a place the row denies.  Here they merely say less than the row does
    -- `Water → Unknown` for a release to a lake -- which is a coarsening and
    says nothing false.

    What makes it wrong anyway is not the statement, it is the stability.  The
    flow a coarsening lands on is whichever one scored best among those that
    existed when the row was reached, and the merge creates flows as it runs.
    ecoinvent's `Aerosols, radioactive, unspecified` sits in `air / urban air
    close to ground` in 3.8 and in 3.12 alike; the 3.12 pass matched it onto
    `Air → Unknown` on a score of 3 against 2, and by the 3.8 pass a third flow
    of the substance existed, two tied at 3, and the tie minted a flow in the
    row's own compartment.  Same row, two consensus flows.

    So the answer is made a property of the row.  This narrows #85's
    coarsening rather than contradicting it: coarsening is still what happens
    to a row whose compartment this list does not hold, which is the case that
    reasoning was about.
    """

    URBAN_GROUND_AIR = NS + "envi-air-grle-ur10pesq"
    AIR_PREFIX = {"dimension": "Environmental", "media": "Air"}

    AEROSOLS_ROW = {
        "source_context": [
            "Environmental", "Air", "Ground level",
            "Urban (>1000 people/square mile)",
        ],
        "source_unit": "kBq",
        "source_context_iri": URBAN_GROUND_AIR,
    }
    LAKE_ROW = {
        "source_context": ["Environmental", "Water", "Lake"],
        "source_unit": "kg",
        "source_context_iri": LAKE,
    }

    def _air_unspecified(self):
        return _candidate(
            "air-unspec", {**self.AIR_PREFIX, "strata": "Unknown"},
            AIR_UNSPECIFIED, unit="kBq",
        )

    def _stack(self):
        return _candidate(
            "stack",
            {**self.AIR_PREFIX, "strata": "Medium stack, <150 meters",
             "population_density": "Rural (<1000 people/square mile)"},
            NS + "envi-air-mest15me-ru10pesq", unit="kBq",
        )

    def _long_term(self):
        return _candidate(
            "long-term", {**self.AIR_PREFIX, "strata": "Long-term"},
            NS + "envi-air-lote", unit="kBq",
        )

    def _urban(self, flow_id="urban", unit="kBq"):
        return _candidate(
            flow_id,
            {**self.AIR_PREFIX, "strata": "Ground level",
             "population_density": "Urban (>1000 people/square mile)"},
            self.URBAN_GROUND_AIR, unit=unit,
        )

    def test_the_aerosols_row_is_not_coarsened_onto_unknown_air(self):
        """The row #112 is named for, at the moment it was being coarsened."""
        selected, reason, details = _select_elementary_flow(
            [self._air_unspecified()], **self.AEROSOLS_ROW
        )
        self.assertIsNone(selected)
        self.assertEqual(reason, UnmatchedReason.NO_CANDIDATE_IN_STATED_CONTEXT)
        self.assertEqual(details["rejected_coarser_context_iri"], AIR_UNSPECIFIED)

    def test_the_refused_row_gets_a_flow_of_its_own(self):
        """The compartment to create it in is the one the row named."""
        self.assertIn(
            UnmatchedReason.NO_CANDIDATE_IN_STATED_CONTEXT,
            _CREATABLE_SELECTOR_REASONS,
        )

    def test_the_answer_does_not_depend_on_what_else_exists(self):
        """The whole point, stated as the two passes that disagreed.

        With two candidates the old selector had a clear winner and matched;
        with three it had a tie and created.  Both now refuse, and both refusals
        create, so the row reaches the same flow whichever release is merged
        first.
        """
        two = _select_elementary_flow(
            [self._air_unspecified(), self._stack()], **self.AEROSOLS_ROW
        )
        three = _select_elementary_flow(
            [self._air_unspecified(), self._stack(), self._long_term()],
            **self.AEROSOLS_ROW,
        )
        self.assertIsNone(two[0])
        self.assertIsNone(three[0])
        self.assertIn(two[1], _CREATABLE_SELECTOR_REASONS)
        self.assertIn(three[1], _CREATABLE_SELECTOR_REASONS)

    def test_an_exact_match_is_still_taken(self):
        """The half that stops this becoming "always create".

        A flow in the row's own compartment short-circuits before any of this,
        and must go on doing so or every row would mint a duplicate.
        """
        selected, reason, _details = _select_elementary_flow(
            [self._urban(), self._air_unspecified()], **self.AEROSOLS_ROW
        )
        self.assertEqual(selected.elementary_flow_id, "urban")
        self.assertEqual(reason, "exact-context-iri-match")

    def test_a_row_whose_compartment_the_list_does_not_hold_is_still_coarsened(self):
        """The other half, and the case #85's reasoning was actually about.

        With no IRI for the row there is no compartment to create a flow in, so
        the nearest neighbour is still the only answer available.
        """
        selected, reason, details = _select_elementary_flow(
            [WATER_UNSPECIFIED_FLOW],
            source_context=["Environmental", "Water", "Lake"],
            source_unit="m3",
            source_context_iri="",
        )
        self.assertEqual(selected.elementary_flow_id, "water-unspec")
        self.assertEqual(reason, "best-score")
        self.assertNotIn("rejected_coarser_context_iri", details)

    def test_two_flows_in_the_rows_own_compartment_are_not_turned_into_a_creation(self):
        """The guard reads the candidates, not the winner.

        Where two flows share the compartment the row named, the exact-IRI
        short-circuit declines to choose between them and scoring picks one.
        That row is ambiguous, not missing, and minting a third flow in a
        compartment that already holds two would be the worst answer available.
        """
        selected, reason, details = _select_elementary_flow(
            [self._urban("urban-1"), self._urban("urban-2", unit="MBq")],
            **self.AEROSOLS_ROW,
        )
        self.assertEqual(selected.elementary_flow_id, "urban-1")
        self.assertEqual(reason, "best-score")
        self.assertNotIn("rejected_coarser_context_iri", details)

    def test_a_contradiction_is_still_a_contradiction(self):
        """The veto runs first and keeps its own reason.

        Both refusals end in a flow in the row's compartment, so the outcome is
        the same; the reason stays distinct because the two describe different
        findings about the source list.
        """
        selected, reason, _details = _select_elementary_flow(
            [AQUIFER_FLOW], **self.LAKE_ROW
        )
        self.assertIsNone(selected)
        self.assertEqual(reason, UnmatchedReason.CONTEXT_CONTRADICTION)


class ARiverRowMintsWhereItSaysTestCase(unittest.TestCase):
    """#186: an emission row in a sub-body the list holds mints there.

    AGRIBALYSE's `Cadmium (II)` released to a river resolves its substance by
    registry number and finds no flow of it in the river context -- EF ships
    Surface water, Long-term, Ocean and the rest, and `Long-term` is a sibling
    water-body value, so the coarsenings tie.  The tie is the correct refusal,
    and the refusal creates: the row gets the existing substance's flow in the
    river place it named, the way BAFU's river metals did.

    A scorer preference that promoted Surface water over Long-term -- a water
    body outranking a time bucket -- was built, measured, and declined on #186:
    it would have re-landed 268 BAFU and 5 Stepwise rows and retired their
    published river flows, and it decided a question the vendor already
    answered.  The stated place wins for emissions; the minted flows carry no
    factors until the factor work reaches them deliberately (#138), and that
    is not this decision's problem.  Resources are the other way round -- a
    wrong subcontext there is a data error, re-filed before matching ever runs
    (the #52 guards in test_simapro_contexts.py and the AGRIBALYSE
    re-filings in its manual-fixes file), so no ruling here touches them.
    """

    RIVER_ROW = {
        "source_context": ["Environmental", "Water", "River"],
        "source_unit": "kg",
        "source_context_iri": RIVER,
    }
    LONG_TERM_ROW = {
        "source_context": ["Environmental", "Water", "Long-term"],
        "source_unit": "kg",
        "source_context_iri": NS + "envi-wate-lote",
    }

    def _surface(self):
        return _candidate(
            "surface-kg", {**WATER_PREFIX, "water_body": "Surface water"},
            SURFACE_WATER,
        )

    def _long_term(self):
        return _candidate(
            "long-term", {**WATER_PREFIX, "water_body": "Long-term"},
            NS + "envi-wate-lote",
        )

    def _river(self):
        return _candidate(
            "river", {**WATER_PREFIX, "water_body": "River"}, RIVER
        )

    def test_the_coarsenings_tie_and_the_tie_creates(self):
        """Surface water does not outrank Long-term; the refusal mints."""
        selected, reason, _details = _select_elementary_flow(
            [self._surface(), self._long_term()], **self.RIVER_ROW
        )
        self.assertIsNone(selected)
        self.assertEqual(reason, UnmatchedReason.TIED_ELEMENTARY_CANDIDATES)
        self.assertIn(reason, _CREATABLE_SELECTOR_REASONS)

    def test_another_body_alone_is_a_contradiction_and_still_creates(self):
        """Surface water names a different body, so a lone candidate is vetoed.

        The tie above never reaches the veto because the refusal came first;
        here the veto is the refusal.  Different reason, same creatable end.
        """
        selected, reason, _details = _select_elementary_flow(
            [self._surface()], **self.RIVER_ROW
        )
        self.assertIsNone(selected)
        self.assertEqual(reason, UnmatchedReason.CONTEXT_CONTRADICTION)
        self.assertIn(reason, _CREATABLE_SELECTOR_REASONS)

    def test_an_unspecified_body_alone_is_566s_refusal_and_still_creates(self):
        """`Water -> Unknown` merely says less, which is #112's case exactly."""
        selected, reason, _details = _select_elementary_flow(
            [WATER_UNSPECIFIED_FLOW],
            source_context=["Environmental", "Water", "River"],
            source_unit="m3",
            source_context_iri=RIVER,
        )
        self.assertIsNone(selected)
        self.assertEqual(reason, UnmatchedReason.NO_CANDIDATE_IN_STATED_CONTEXT)
        self.assertIn(reason, _CREATABLE_SELECTOR_REASONS)

    def test_a_flow_in_the_river_itself_ends_the_question(self):
        """Once the river flow exists -- minted or shipped -- rows land on it."""
        selected, reason, _details = _select_elementary_flow(
            [self._surface(), self._long_term(), self._river()],
            **self.RIVER_ROW,
        )
        self.assertEqual(selected.elementary_flow_id, "river")
        self.assertEqual(reason, "exact-context-iri-match")

    def test_a_row_that_says_long_term_lands_on_long_term(self):
        """The stated place wins in both directions."""
        selected, reason, _details = _select_elementary_flow(
            [self._surface(), self._long_term()], **self.LONG_TERM_ROW
        )
        self.assertEqual(selected.elementary_flow_id, "long-term")
        self.assertEqual(reason, "exact-context-iri-match")
