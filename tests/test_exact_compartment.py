"""
A row that names its compartment exactly outranks the neighbours of it (#90).

BAFU reports water vapour to the air, compartment unspecified. The list holds
water vapour in air with the height left unstated -- the same compartment, the
same substance -- measured in kilograms, and also in air at aircraft cruise
height and in air, long-term. All three are kilograms, and all three used to
score 3, so the merge reported a tie and placed the row nowhere.

The score counts words. The compartment the row names is written
`Environmental / Air / Unknown`, because a context lists its answers and the
height's answer is "unstated"; the row arrives as `Environmental / Air`, because
the source side is read from `consensus-flows-as-strings.json`, which drops the
answers that state nothing. So the flow the row *means* shares two words with it
and differs by one, exactly like the two flows in other places.

There is a rule that takes a flow in the row's own compartment and stops, but it
requires that exactly one flow sit there, and EF holds water vapour in air,
unspecified twice: once in kilograms and once in cubic metres (§8 of
`water-taxonomy-overview.md` records that doubling as an open item). So the
short-circuit declines, scoring takes over, and scoring could not see the
difference the short-circuit was looking at.

What is pinned here:

- **An exact compartment beats a sibling of it.** The context IRI is the
  identity the words describe, and it is worth a point.
- **A unit weighs more than an exact compartment.** Two points against one, so
  the point tells the two flows in the row's own compartment apart by unit and
  never carries a kilogram row onto a cubic-metre flow.
- **A near miss is still found.** A row whose compartment the list does not hold
  gives the point to nobody, so nothing about how it is placed changes -- that
  includes the ties that send a row to a flow of its own, which
  `test_context_contradiction.py` pins for ecoinvent's forestry soil.
"""

import unittest

from brightway_flows.domain.context_registry import context_from_dict
from brightway_flows.domain.elementary_flow import ElementaryFlow
from brightway_flows.merge.matching import _select_elementary_flow
from brightway_flows.merge.report import UnmatchedReason

NS = "https://vocab.brightway.one/flow-contexts/"

AIR_UNSPECIFIED = NS + "envi-air-unkn"
CRUISE_HEIGHT = NS + "envi-air-aicrhe"
LONG_TERM = NS + "envi-air-lote"
GROUND_LEVEL_URBAN = NS + "envi-air-grle-ur10pesq"
FORESTRY_SOIL = NS + "envi-grou-silv"
FARM_SOIL = NS + "envi-grou-agri"

AIR = {"dimension": "Environmental", "media": "Air"}

#: What the merge hands the selector for a row in air, unspecified: the strings
#: of the context it was harmonised to, which state the height nowhere because
#: the row states it nowhere.
UNSPECIFIED_AIR_ROW = {
    "source_context": ["Environmental", "Air"],
    "source_unit": "kg",
    "source_context_iri": AIR_UNSPECIFIED,
}


def _candidate(flow_id, context, context_iri, unit="kg"):
    """One elementary flow as the selector sees it.

    The context is spelled out as a dict and built into the `Context` the record
    carries, because what this is about is a field the source strings do not
    state: the `Unknown` the printed context shows and `Context.to_list()`
    drops. Writing it here rather than resolving the IRI is what makes that
    visible to a reader of the fixture.
    """
    return ElementaryFlow(
        elementary_flow_id=flow_id,
        flow_object_id="fo-water-vapour",
        source="EF 3.1",
        context=context_from_dict(context),
        context_iri=context_iri,
        unit=unit,
        unit_iri="",
        lcia_methods=[],
        general_comment=None,
    )


# The five flows of `Water vapour` this is about, as the 2026-08-15 build holds
# them: the object carries 19 flows, 12 of them in air.
VAPOUR_UNSPECIFIED_KG = _candidate("vapour-kg", {**AIR, "strata": "Unknown"}, AIR_UNSPECIFIED)
VAPOUR_UNSPECIFIED_M3 = _candidate("vapour-m3", {**AIR, "strata": "Unknown"}, AIR_UNSPECIFIED, unit="m3")
VAPOUR_UNSPECIFIED_M3_AGAIN = _candidate("vapour-m3-2", {**AIR, "strata": "Unknown"}, AIR_UNSPECIFIED, unit="m3")
VAPOUR_CRUISE = _candidate("vapour-cruise", {**AIR, "strata": "Aircraft cruise height"}, CRUISE_HEIGHT)
VAPOUR_LONG_TERM = _candidate("vapour-long-term", {**AIR, "strata": "Long-term"}, LONG_TERM)

WATER_VAPOUR_IN_AIR = [
    VAPOUR_CRUISE,
    VAPOUR_UNSPECIFIED_KG,
    VAPOUR_LONG_TERM,
    VAPOUR_UNSPECIFIED_M3,
    VAPOUR_UNSPECIFIED_M3_AGAIN,
]


class WaterVapourTestCase(unittest.TestCase):
    """The 50 BAFU rows the issue was written about."""

    def test_the_row_lands_in_the_compartment_it_named(self):
        selected, reason, _details = _select_elementary_flow(
            WATER_VAPOUR_IN_AIR, **UNSPECIFIED_AIR_ROW
        )
        self.assertEqual(selected.elementary_flow_id, "vapour-kg")
        self.assertEqual(reason, "best-score")

    def test_the_short_circuit_still_declines(self):
        """The premise: three flows sit in the compartment, so it cannot fire.

        Were it firing, this file would be pinning a rule that never runs.
        """
        _selected, reason, _details = _select_elementary_flow(
            WATER_VAPOUR_IN_AIR, **UNSPECIFIED_AIR_ROW
        )
        self.assertNotEqual(reason, "exact-context-iri-match")

    def test_the_neighbours_are_left_a_point_behind(self):
        """4 against 3: two shared words and the unit for both, and the
        compartment itself for one."""
        _selected, _reason, details = _select_elementary_flow(
            WATER_VAPOUR_IN_AIR, **UNSPECIFIED_AIR_ROW
        )
        by_id = {c["elementary_flow_id"]: c for c in details["scored_candidates"]}
        self.assertEqual(by_id["vapour-kg"]["score"], 4)
        self.assertTrue(by_id["vapour-kg"]["context_iri_exact"])
        self.assertEqual(by_id["vapour-cruise"]["score"], 3)
        self.assertEqual(by_id["vapour-long-term"]["score"], 3)
        self.assertFalse(by_id["vapour-cruise"]["context_iri_exact"])

    def test_the_unit_still_decides_between_two_flows_in_that_compartment(self):
        """The doubled EF flow: both are in the row's own compartment, and the
        row is measured in kilograms."""
        selected, reason, _details = _select_elementary_flow(
            [VAPOUR_UNSPECIFIED_M3, VAPOUR_UNSPECIFIED_KG], **UNSPECIFIED_AIR_ROW
        )
        self.assertEqual(selected.elementary_flow_id, "vapour-kg")
        self.assertEqual(reason, "best-score")

    def test_the_unit_outweighs_the_compartment(self):
        """A point against two.  The cubic-metre flows sit in the row's own
        compartment and still rank below a kilogram flow in a neighbouring one,
        so the point cannot carry a row across a unit boundary -- publishing a
        kilogram row on a cubic-metre flow is #78's defect and this must not
        add to it.
        """
        _selected, _reason, details = _select_elementary_flow(
            WATER_VAPOUR_IN_AIR, **UNSPECIFIED_AIR_ROW
        )
        by_id = {c["elementary_flow_id"]: c for c in details["scored_candidates"]}
        self.assertEqual(by_id["vapour-m3"]["score"], 2)
        self.assertTrue(by_id["vapour-m3"]["context_iri_exact"])
        self.assertLess(by_id["vapour-m3"]["score"], by_id["vapour-cruise"]["score"])

    def test_two_flows_in_one_compartment_are_still_a_tie(self):
        """The list holds the same emission twice, in the same compartment and
        the same unit.  Both earn the point, neither is the answer, and the row
        is reported rather than placed."""
        selected, reason, _details = _select_elementary_flow(
            [VAPOUR_UNSPECIFIED_M3, VAPOUR_UNSPECIFIED_M3_AGAIN],
            source_context=["Environmental", "Air"],
            source_unit="m3",
            source_context_iri=AIR_UNSPECIFIED,
        )
        self.assertIsNone(selected)
        self.assertEqual(reason, UnmatchedReason.TIED_ELEMENTARY_CANDIDATES)


class CompartmentTheListDoesNotHoldTestCase(unittest.TestCase):
    """Where the near miss is the right answer, it is still the answer."""

    def test_the_point_goes_to_nobody(self):
        """A row at ground level in an urban area, where the list holds only
        the two flows above and below it: the search is unchanged."""
        _selected, _reason, details = _select_elementary_flow(
            [VAPOUR_CRUISE, VAPOUR_LONG_TERM],
            source_context=["Environmental", "Air", "Ground level", "Urban (>1000 people/square mile)"],
            source_unit="kg",
            source_context_iri=GROUND_LEVEL_URBAN,
        )
        self.assertFalse(
            any(c["context_iri_exact"] for c in details["scored_candidates"])
        )

    def test_a_coarsening_is_still_scored(self):
        """The row named a height; the list states none.  Nothing here stops
        the flow that leaves it open from being found and scored.

        **Rewritten for #112.**  It used to end by asserting that flow was the
        answer.  It is not any more -- the row names a compartment this list
        holds, nothing offered is in it, so the row gets a flow of its own
        rather than the one that leaves the height open.  What this test is
        for is unchanged and is what is still asserted: #90's exact-IRI term
        goes to nobody here, and the coarser flow is scored on its merits
        rather than filtered out before the selector sees it.
        """
        selected, reason, details = _select_elementary_flow(
            [VAPOUR_UNSPECIFIED_KG],
            source_context=["Environmental", "Air", "Long-term"],
            source_unit="kg",
            source_context_iri=LONG_TERM,
        )
        self.assertEqual(
            [c["elementary_flow_id"] for c in details["scored_candidates"]],
            ["vapour-kg"],
        )
        self.assertFalse(details["scored_candidates"][0]["context_iri_exact"])
        self.assertIsNone(selected)
        self.assertEqual(reason, UnmatchedReason.NO_CANDIDATE_IN_STATED_CONTEXT)

    def test_a_row_with_no_compartment_of_its_own_is_unaffected(self):
        """A row the mapping could not place carries no IRI, so the term is not
        merely zero for every candidate -- it is never reached."""
        _selected, _reason, details = _select_elementary_flow(
            [VAPOUR_CRUISE, VAPOUR_LONG_TERM],
            source_context=["Environmental", "Air"],
            source_unit="kg",
            source_context_iri="",
        )
        self.assertFalse(
            any(c["context_iri_exact"] for c in details["scored_candidates"])
        )

    def test_forestry_soil_still_gets_a_flow_of_its_own(self):
        """ecoinvent's `soil / forestry`, which EF does not hold at all.  The
        farm and unspecified soils tie, the row is refused, and a flow is made
        in the context it named.  420 rows are placed that way on the
        2026-08-15 build -- 341 of BAFU's releases to a named water body, 25
        ecoinvent forestry soil rows, and the rest ones and twos -- and none of
        them is this issue's to move."""
        selected, reason, _details = _select_elementary_flow(
            [
                _candidate("farm", {"dimension": "Environmental", "media": "Ground", "geography": "Agricultural"}, FARM_SOIL),
                _candidate("soil-unspec", {"dimension": "Environmental", "media": "Ground", "geography": "Unknown"}, NS + "envi-grou-unkn"),
            ],
            source_context=["Environmental", "Ground", "Silvicultural"],
            source_unit="kg",
            source_context_iri=FORESTRY_SOIL,
        )
        self.assertIsNone(selected)
        self.assertEqual(reason, UnmatchedReason.TIED_ELEMENTARY_CANDIDATES)
