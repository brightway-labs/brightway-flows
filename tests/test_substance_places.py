"""One substance in two places, and the two rows that put it there (#87).

The collision check asks whether one place holds two flows. Nothing asked the
other half: whether one substance holds two *places*. It is the harder half to
notice, because there is no moment at which anything goes wrong. Two source
lists agree about what a substance is, disagree about where it comes from, and
the merge does exactly what it is asked -- matches the substance, then writes a
flow in the context the row named, because the substance had none there. The
result is two identifiers that can never meet: an inventory using one and a
method characterising the other simply do not connect, and both sides look fine
from the inside.

**Releases are excluded, and that is the whole of the rule.** Where a substance
goes is a fact about the process, so zinc to air and zinc to a river are two
ordinary flows and a list shipping one of them contradicts nothing. Where a
substance comes from is a fact about the substance: peat is dug out of the
ground and no process chooses otherwise. So the comparison is over the contexts
that are not releases, and two of those on one substance are two answers to a
question that has one.

**A coarsening is not a second place.** `Water -> River` and `Water -> Unknown`
are one place at two levels of detail, and BAFU names rivers where EF 3.1 has
only unspecified water. `context_contradicts` already draws that line for the
merge and this reads it in both directions, which is what keeps those rows out.

**A split inside the base list is nobody's disagreement.** EF 3.1 publishes
magnesium as a ground resource and as a water resource on purpose. It takes a
flow the merge wrote for the pair to be two lists answering differently, which
is also the only case nothing already reported: a *matched* row whose context
disagrees with its target's is recorded as a context inconsistency, 1,756 of
them on the 2026-08-14 build, and a row that creates a flow in a second context
raised nothing at all.

The two the issue names are fixed here as well, in data rather than in code:

- **Geothermal energy** is not biotic. BAFU files `Energy, geothermal,
  converted` in `resources / in ground` in 57 datasets and in
  `resources / biotic` in 5, and the compartment rule believed both, so the
  energy carrier EF 3.1, ecoinvent 3.8 and ecoinvent 3.12 all share was
  published twice. A flow-specific context rule sends the biotic row to ground.
- **Peat** is two substances in this list, because EF 3.1 ships it twice, and
  the two vendor lists were sending their kilogram of it to different ones of
  them. ecoinvent's biotic kilogram reaches `Peat, in ground`; BAFU's matched
  the megajoule energy carrier on its label and minted a second kilogram of peat
  there. A match override sends it where ecoinvent's goes. Whether the two peats
  are one substance is #266 and is untouched.
"""

import json
import unittest

from brightway_flows.domain.context_registry import context_for_iri
from brightway_flows.domain.elementary_flow import ElementaryFlow
from brightway_flows.domain.lcia.records import StatedFactor, stated_category
from brightway_flows.match_overrides import load_match_overrides
from brightway_flows.merge.collisions import MergedFlow
from brightway_flows.merge.places import (
    display_context,
    find_split_substances,
    is_a_release,
    places_of,
    report_substance_places,
    two_places,
)
from brightway_flows.merge.state import MergeAccumulator
from brightway_flows.pipeline.review_records import ReviewQueue, Severity
from brightway_flows.sources import PACKAGE_DATA_DIR, base_source_label

PREFIX = "https://vocab.brightway.one/flow-contexts/"
GROUND = PREFIX + "reso-grou"
BIOTIC = PREFIX + "reso-biot"
RESOURCE_AIR = PREFIX + "reso-air"
RESOURCE_WATER = PREFIX + "reso-wate"
RESOURCE_RIVER = PREFIX + "reso-wate-rive"
OCCUPATION = PREFIX + "laus-occu"
TO_AIR = PREFIX + "envi-air-unkn"
TO_RIVER = PREFIX + "envi-wate-rive"

BASE = base_source_label()
MINTED_SOURCE = "bafu algorithm addition"


def flow(
    flow_id,
    context_iri=GROUND,
    flow_object_id="fo-1",
    unit="MJ",
    source=BASE,
    factors=0,
    deprecated=False,
):
    """One merged flow, as the record the accumulator holds."""
    return ElementaryFlow(
        elementary_flow_id=flow_id,
        flow_object_id=flow_object_id,
        source=source,
        # Resolved from the IRI, so the record cannot say one context and its
        # `context_iri` another.  A flow the mapping placed nowhere has neither.
        context=context_for_iri(context_iri) if context_iri else None,
        context_iri=context_iri,
        unit=unit,
        unit_iri="",
        lcia_methods=[
            StatedFactor(
                category=stated_category(uuid=f"m{i}", name=f"m{i}"),
                flow_uuid=flow_id,
                amount=1.0,
            )
            for i in range(factors)
        ],
        general_comment=None,
        owl_deprecated=deprecated or None,
    )


def split(*records):
    merged = [MergedFlow.from_record(record) for record in records]
    minted = frozenset(
        f.elementary_flow_id for f in merged if f.source != BASE
    )
    return find_split_substances(merged, minted)


class WhatCountsAsAPlaceTestCase(unittest.TestCase):
    def test_a_resource_context_is_not_a_release(self):
        self.assertFalse(is_a_release(GROUND))
        self.assertFalse(is_a_release(OCCUPATION))

    def test_an_emission_context_is(self):
        self.assertTrue(is_a_release(TO_AIR))
        self.assertTrue(is_a_release(TO_RIVER))

    def test_an_unregistered_iri_is_neither(self):
        """It answers False, and `two_places` then calls it no place at all, so
        a context nobody can resolve can only quieten this report rather than
        populate it. None reaches the report: `_refuse_invalid_contexts` stops
        the build over the same list first, and that is a different defect with
        a different fix.
        """
        self.assertFalse(is_a_release("https://example.invalid/nope"))
        self.assertFalse(two_places("https://example.invalid/nope", GROUND))


class TwoPlacesOrOneTestCase(unittest.TestCase):
    def test_two_media_are_two_places(self):
        self.assertTrue(two_places(GROUND, BIOTIC))

    def test_two_dimensions_are_two_places(self):
        self.assertTrue(two_places(GROUND, OCCUPATION))

    def test_a_coarsening_is_one_place(self):
        """The direction that matters: unspecified water makes no claim about
        the body, so a river is that place described better."""
        self.assertFalse(two_places(RESOURCE_RIVER, RESOURCE_WATER))
        self.assertFalse(two_places(RESOURCE_WATER, RESOURCE_RIVER))

    def test_one_context_is_not_two_places(self):
        self.assertFalse(two_places(GROUND, GROUND))


class FindingThemTestCase(unittest.TestCase):
    def test_one_substance_in_two_resource_media_is_reported(self):
        found = split(
            flow("a", GROUND),
            flow("b", BIOTIC, source=MINTED_SOURCE),
        )
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0].flow_object_id, "fo-1")
        self.assertEqual(found[0].stranded, (BIOTIC,))

    def test_a_substance_released_in_two_media_is_not(self):
        """The asymmetry the rule rests on: an emission goes where the process
        sends it, so two media are two flows rather than two answers."""
        self.assertEqual(
            split(flow("a", TO_AIR), flow("b", TO_RIVER, source=MINTED_SOURCE)),
            [],
        )

    def test_nor_is_a_resource_beside_a_release_of_the_same_substance(self):
        """Barite is dug out of the ground and discharged to the sea, and both
        are true of it."""
        self.assertEqual(
            split(flow("a", GROUND), flow("b", TO_RIVER, source=MINTED_SOURCE)),
            [],
        )

    def test_a_coarsening_is_not_reported(self):
        self.assertEqual(
            split(
                flow("a", RESOURCE_WATER),
                flow("b", RESOURCE_RIVER, source=MINTED_SOURCE),
            ),
            [],
        )

    def test_a_split_the_base_list_made_alone_is_not_reported(self):
        """EF 3.1 ships magnesium in ground and in water on purpose, and nobody
        contradicted it."""
        self.assertEqual(
            split(flow("a", GROUND), flow("b", RESOURCE_WATER)),
            [],
        )

    def test_the_same_split_is_reported_once_a_merge_writes_into_it(self):
        found = split(
            flow("a", GROUND),
            flow("b", RESOURCE_WATER),
            flow("c", BIOTIC, source=MINTED_SOURCE),
        )
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0].stranded, (BIOTIC,))

    def test_a_minted_place_one_of_the_others_describes_is_not_stranded(self):
        """The reason the question is asked of a place rather than of a pair.

        BAFU's river withdrawal beside EF 3.1's unspecified water is the flow
        finding the place it wanted; the ground resource sitting next to them is
        the base list's own business, and pairing the river with it would report
        a row that did nothing wrong.
        """
        self.assertEqual(
            split(
                flow("a", GROUND),
                flow("b", RESOURCE_WATER),
                flow("c", RESOURCE_RIVER, source=MINTED_SOURCE),
            ),
            [],
        )

    def test_and_every_place_is_listed_beside_the_stranded_one(self):
        """A place is only stranded relative to the others, so the others are
        what makes the finding readable."""
        found = split(
            flow("a", GROUND),
            flow("b", RESOURCE_WATER),
            flow("c", BIOTIC, source=MINTED_SOURCE),
        )
        self.assertEqual(
            [place.context_iri for place in found[0].places],
            [BIOTIC, GROUND, RESOURCE_WATER],
        )

    def test_two_substances_are_two_findings(self):
        found = split(
            flow("a", GROUND, flow_object_id="fo-1"),
            flow("b", BIOTIC, flow_object_id="fo-1", source=MINTED_SOURCE),
            flow("c", GROUND, flow_object_id="fo-2"),
            flow("d", OCCUPATION, flow_object_id="fo-2", source=MINTED_SOURCE),
        )
        self.assertEqual([f.flow_object_id for f in found], ["fo-1", "fo-2"])

    def test_a_deprecated_flow_holds_no_place(self):
        """A deprecated flow is a place the list has already left."""
        self.assertEqual(
            split(
                flow("a", GROUND),
                flow("b", BIOTIC, source=MINTED_SOURCE, deprecated=True),
            ),
            [],
        )

    def test_an_unplaced_flow_is_not_a_second_place(self):
        self.assertEqual(
            split(flow("a", GROUND), flow("b", "", source=MINTED_SOURCE)),
            [],
        )

    def test_two_flows_in_one_place_are_a_collision_rather_than_a_split(self):
        """The other check's finding, and this one says nothing about it."""
        self.assertEqual(
            split(flow("a", GROUND), flow("b", GROUND, source=MINTED_SOURCE)),
            [],
        )

    def test_a_place_gathers_every_flow_in_it(self):
        places = places_of(
            [
                MergedFlow.from_record(record)
                for record in (
                    flow("a", GROUND, unit="MJ"),
                    flow("b", GROUND, unit="kg", source=MINTED_SOURCE),
                )
            ],
            frozenset({"b"}),
        )
        self.assertEqual(len(places["fo-1"]), 1)
        place = places["fo-1"][0]
        self.assertEqual(place.elementary_flow_ids, ("a", "b"))
        self.assertEqual(place.units, ("MJ", "kg"))
        self.assertEqual(place.minted, ("b",))


class TheItemTestCase(unittest.TestCase):
    def report(self, *records, labels=None):
        return report_substance_places(
            accumulator=MergeAccumulator(merged_elementary=list(records)),
            labels_by_object=(
                {"fo-1": "Energy, Geothermal, Converted"}
                if labels is None
                else labels
            ),
        )

    def test_a_clean_list_reports_none_and_says_so(self):
        counts, items = self.report(flow("a", GROUND))
        self.assertEqual(items, [])
        # Seeded rather than absent: an absent row in `run_stats` means a stage
        # did not look, and this one looked.
        self.assertEqual(counts["substances_in_two_places"], 0)
        self.assertEqual(counts["places_belonging_nowhere_else"], 0)

    def test_the_geothermal_shape_raises_one_item(self):
        counts, items = self.report(
            flow("a", GROUND),
            flow("b", BIOTIC, source=MINTED_SOURCE),
        )
        self.assertEqual(counts["substances_in_two_places"], 1)
        self.assertEqual(counts["places_belonging_nowhere_else"], 1)
        self.assertEqual(counts["flows_in_a_split_substance"], 2)
        self.assertEqual(counts["flows_minted_into_a_second_place"], 1)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].queue_name, ReviewQueue.SUBSTANCE_IN_TWO_PLACES)

    def test_the_item_is_keyed_on_the_substance(self):
        _, items = self.report(
            flow("a", GROUND), flow("b", BIOTIC, source=MINTED_SOURCE)
        )
        self.assertEqual(items[0].item_key, "fo-1")
        self.assertEqual(items[0].flow_object_id, "fo-1")

    def test_the_item_names_the_substance_and_its_places(self):
        _, items = self.report(
            flow("a", GROUND), flow("b", BIOTIC, source=MINTED_SOURCE)
        )
        self.assertIn("Energy, Geothermal, Converted", items[0].title)
        self.assertEqual(
            items[0].payload["contexts"],
            ["Resource → Biotic", "Resource → Ground"],
        )

    def test_every_item_is_a_review(self):
        """There is no `info` half of this queue: every group here needs a flow
        the merge wrote, so the pipeline acted and what it did wants
        confirming."""
        _, items = self.report(
            flow("a", GROUND), flow("b", BIOTIC, source=MINTED_SOURCE)
        )
        self.assertEqual(items[0].severity, Severity.REVIEW)

    def test_the_payload_says_which_flows_are_where(self):
        _, items = self.report(
            flow("a", GROUND, factors=1),
            flow("b", BIOTIC, unit="kg", source=MINTED_SOURCE),
        )
        by_iri = {p["context_iri"]: p for p in items[0].payload["places"]}
        self.assertEqual(by_iri[GROUND]["elementary_flow_ids"], ["a"])
        self.assertEqual(by_iri[GROUND]["lcia_factor_count"], 1)
        self.assertEqual(by_iri[GROUND]["minted_by_merge"], [])
        self.assertEqual(by_iri[BIOTIC]["units"], ["kg"])
        self.assertEqual(by_iri[BIOTIC]["minted_by_merge"], ["b"])
        self.assertEqual(by_iri[BIOTIC]["sources"], [MINTED_SOURCE])

    def test_the_side_holding_the_characterisation_is_counted(self):
        """The consequence rather than a second description of the cause: one
        place answers for the substance and the other publishes a flow with no
        number on it, so an inventory that picked the wrong one scores zero."""
        counts, _ = self.report(
            flow("a", GROUND, factors=1),
            flow("b", BIOTIC, source=MINTED_SOURCE),
        )
        self.assertEqual(counts["splits_with_the_factors_on_one_side"], 1)

    def test_and_is_not_counted_when_neither_side_holds_any(self):
        counts, _ = self.report(
            flow("a", GROUND), flow("b", BIOTIC, source=MINTED_SOURCE)
        )
        self.assertEqual(counts["splits_with_the_factors_on_one_side"], 0)

    def test_a_minted_flow_that_found_its_place_is_not_counted_as_stranded(self):
        """The river flow again, from the counting side: it is minted, it is on
        a reported substance, and it is not what the report is about."""
        counts, items = self.report(
            flow("a", GROUND),
            flow("b", RESOURCE_WATER),
            flow("c", RESOURCE_RIVER, source=MINTED_SOURCE),
            flow("d", BIOTIC, source=MINTED_SOURCE),
        )
        self.assertEqual(counts["places_belonging_nowhere_else"], 1)
        self.assertEqual(counts["flows_minted_into_a_second_place"], 1)
        self.assertEqual(items[0].payload["minted_by_merge"], ["d"])
        # ...and the place it did find is still listed, because a place is only
        # stranded relative to the others.
        self.assertEqual(len(items[0].payload["places"]), 4)

    def test_the_number_of_places_is_tallied(self):
        counts, _ = self.report(
            flow("a", GROUND),
            flow("b", BIOTIC, source=MINTED_SOURCE),
            flow("c", RESOURCE_AIR, source=MINTED_SOURCE),
        )
        self.assertEqual(counts["substance_in_3_places"], 1)

    def test_an_unlabelled_substance_is_named_by_its_identifier(self):
        _, items = self.report(
            flow("a", GROUND), flow("b", BIOTIC, source=MINTED_SOURCE), labels={}
        )
        self.assertIn("fo-1", items[0].title)


class DisplayTestCase(unittest.TestCase):
    def test_a_place_renders_as_the_database_prints_it(self):
        self.assertEqual(display_context(GROUND), "Resource → Ground")
        self.assertEqual(display_context(OCCUPATION), "Land Use → Occupation")

    def test_an_unregistered_iri_renders_as_itself(self):
        self.assertEqual(display_context("urn:nope"), "urn:nope")


class GeothermalIsNotBioticTestCase(unittest.TestCase):
    """BAFU's biotic geothermal row, sent to ground by a flow-specific rule."""

    BIOTIC_ROW = "764d049d-ba42-5060-9da4-6b6823075eb7"
    GROUND_ROW = "1e393ca8-eb30-58a9-9ccb-c4e8cd8ff618"

    def rows(self):
        payload = json.loads(
            (PACKAGE_DATA_DIR / "context-manual-mapping.json").read_bytes()
        )
        return {
            row["source_uuid"]: row
            for row in payload["flow_specific_context_mappings"]
            if row["source"] == "bafu-2026-v1"
        }

    def test_the_biotic_row_is_read_as_a_ground_resource(self):
        self.assertEqual(self.rows()[self.BIOTIC_ROW]["context_iri"], GROUND)

    def test_it_is_the_row_the_compartment_rule_would_have_filed_as_biotic(self):
        row = self.rows()[self.BIOTIC_ROW]
        self.assertEqual(row["source_context"], ["resources", "biotic"])
        self.assertEqual(row["source_name"], "Energy, geothermal, converted")

    def test_the_other_compartment_needs_no_rule(self):
        """`resources / in ground` already reaches ground resources, and a rule
        restating a compartment rule is a duplicate that goes stale silently."""
        self.assertNotIn(self.GROUND_ROW, self.rows())


class TwoListsMeanTwoDifferentPeatsTestCase(unittest.TestCase):
    """EF 3.1 ships two peats, and each list's rows go to the one it means.

    `peat` is a non-renewable energy resource in megajoules carrying the
    fossil-resource factor; `Peat, in ground` -- published as `Peat,
    horticulture` since #89 -- is a renewable material resource in kilograms
    carrying nothing.  Fuel peat and peat sold as a growing medium.

    **BAFU's kilogram is the fuel.**  #87 sent it to the material, on the
    reasoning that it has the same name, the same `biotic` compartment and the
    same kilogram as ecoinvent 3.12's row, which is the material.  The archive
    says otherwise: BAFU's row is the extraction input to `Peat, at mine`, one
    kilogram per kilogram, and that dataset is filed under `fuels / peat` and
    feeds `Peat, burned in power plant` and `Electricity, peat, at power plant`.
    The 133 other datasets carrying it are ordinary products at 1e-4 to 1e-8 kg,
    which is peat-fired electricity reaching them through the background.  Same
    name and same compartment, different substance: BAFU's flows came out of
    ecoinvent 2, where peat was a fuel, and ecoinvent 3 restructured (#89).
    """

    BAFU_BIOTIC_KG = "0417d728-9c64-5755-9685-e547485968d4"
    BAFU_GROUND_KG = "25d290ab-0e08-5963-9141-cbcbb998c559"
    BAFU_ENERGY_MJ = "b2b18479-42c0-51f4-9da9-27df4541fb8b"
    PEAT_THE_ENERGY_CARRIER = "e2fba107-6555-11dd-ad8b-0800200c9a66"
    PEAT_THE_MATERIAL = "126514fa-415f-454a-8425-aa5d54a1402b"

    #: IPCC 2006 Guidelines Vol. 2 Table 1.2, the default for peat.
    MJ_PER_KG = 9.76

    def overrides(self):
        return {
            row.source_uuid: row
            for row in load_match_overrides(
                PACKAGE_DATA_DIR / "bafu-2026-v1-match-overrides.json"
            )
        }

    def test_every_bafu_peat_row_reaches_the_energy_carrier(self):
        """One peat in this list, reached from all three of its rows."""
        rows = self.overrides()
        for uuid in (self.BAFU_BIOTIC_KG, self.BAFU_GROUND_KG, self.BAFU_ENERGY_MJ):
            with self.subTest(uuid):
                self.assertEqual(rows[uuid].target_uuid, self.PEAT_THE_ENERGY_CARRIER)

    def test_no_bafu_row_reaches_the_horticultural_peat(self):
        """The half that would go wrong silently.

        Nothing in the release uses peat as a growing medium, so a BAFU row on
        the material peat is a row on the wrong substance -- and before #89
        renamed that flow, nothing a reader could see said so.
        """
        for uuid, row in self.overrides().items():
            with self.subTest(uuid):
                self.assertNotEqual(row.target_uuid, self.PEAT_THE_MATERIAL)

    def test_both_kilogram_rows_state_the_same_conversion(self):
        """A mass reaching a flow measured in megajoules needs a number, and
        the two rows are the same substance so it is the same number."""
        rows = self.overrides()
        for uuid in (self.BAFU_BIOTIC_KG, self.BAFU_GROUND_KG):
            with self.subTest(uuid):
                self.assertEqual(rows[uuid].source_unit, "kg")
                self.assertEqual(rows[uuid].target_unit, "MJ")
                self.assertEqual(rows[uuid].conversion_factor, self.MJ_PER_KG)

    def test_the_two_targets_are_two_substances(self):
        self.assertNotEqual(self.PEAT_THE_MATERIAL, self.PEAT_THE_ENERGY_CARRIER)
