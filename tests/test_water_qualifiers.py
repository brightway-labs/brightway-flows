"""Tests for origin-qualifier detection, synonym cleaning, and flow object separation.

All origin-qualified flows (biogenic CO2, fossil methane, green water, …) must
produce separate flow objects even when they share a CAS number with the base
substance.  Generic synonyms enriched from ChEBI/PubChem must be stripped so
that label-based matching cannot confuse variants with one another.
"""

from __future__ import annotations

import unittest

from brightway_flows.domain.flow import Flow
from brightway_flows.qualifiers import ORIGIN_QUALIFIERS, detect_origin_qualifier
from brightway_flows.sources import base_source_list

#: `resolve_flow_layers` asks which list its flows came from rather than
#: reading it off `flow.source`, and these are the base list's rows (#13).
BASE = base_source_list()


def _as_flows(rows):
    """resolve_flow_layers takes Flow records; tests still author dicts."""
    return [Flow.from_dict(r) for r in rows]



class TestWaterQualifierDetection(unittest.TestCase):

    # ── green water ──────────────────────────────────────────────────────────

    def test_green_water_comma_style(self):
        self.assertEqual(detect_origin_qualifier("Water, green"), "green_water")

    def test_green_water_prefix_style(self):
        self.assertEqual(detect_origin_qualifier("Green water"), "green_water")

    def test_green_water_case_insensitive(self):
        self.assertEqual(detect_origin_qualifier("GREEN WATER"), "green_water")
        self.assertEqual(detect_origin_qualifier("water, Green"), "green_water")

    # ── blue water ───────────────────────────────────────────────────────────

    def test_blue_water_comma_style(self):
        self.assertEqual(detect_origin_qualifier("Water, blue"), "blue_water")

    def test_blue_water_prefix_style(self):
        self.assertEqual(detect_origin_qualifier("Blue water"), "blue_water")

    def test_blue_water_case_insensitive(self):
        self.assertEqual(detect_origin_qualifier("BLUE WATER"), "blue_water")

    # ── grey / gray water ────────────────────────────────────────────────────

    def test_grey_water_comma_style(self):
        self.assertEqual(detect_origin_qualifier("Water, grey"), "grey_water")

    def test_gray_water_alternate_spelling(self):
        self.assertEqual(detect_origin_qualifier("Water, gray"), "grey_water")

    def test_grey_water_prefix_style(self):
        self.assertEqual(detect_origin_qualifier("Grey water"), "grey_water")

    def test_gray_water_prefix_style(self):
        self.assertEqual(detect_origin_qualifier("Gray water"), "grey_water")

    def test_grey_water_case_insensitive(self):
        self.assertEqual(detect_origin_qualifier("GREY WATER"), "grey_water")

    # ── plain water returns None ─────────────────────────────────────────────

    def test_plain_water_no_qualifier(self):
        self.assertIsNone(detect_origin_qualifier("Water"))

    def test_plain_water_with_context_no_qualifier(self):
        self.assertIsNone(detect_origin_qualifier("Water, river"))
        self.assertIsNone(detect_origin_qualifier("Water, lake"))
        self.assertIsNone(detect_origin_qualifier("Water, well, in ground"))

    # ── carbon-origin qualifiers ─────────────────────────────────────────────

    def test_biogenic(self):
        self.assertEqual(detect_origin_qualifier("Carbon dioxide, biogenic"), "biogenic")

    def test_non_fossil_maps_to_biogenic(self):
        self.assertEqual(detect_origin_qualifier("Oils, non-fossil"), "biogenic")

    def test_fossil(self):
        self.assertEqual(detect_origin_qualifier("Methane, fossil"), "fossil")

    def test_land_use_change(self):
        self.assertEqual(detect_origin_qualifier("Carbon dioxide, land use change"), "land_use_change")

    def test_land_use_change_hyphen(self):
        self.assertEqual(detect_origin_qualifier("Carbon dioxide, land-use change"), "land_use_change")

    # ── biogenic_resource_correction ─────────────────────────────────────────

    def test_resource_correction_comma_style(self):
        self.assertEqual(
            detect_origin_qualifier("Carbon dioxide, non-fossil, resource correction"),
            "biogenic_resource_correction",
        )

    def test_resource_correction_hyphen(self):
        self.assertEqual(
            detect_origin_qualifier("Carbon dioxide, non-fossil, resource-correction"),
            "biogenic_resource_correction",
        )

    def test_resource_correction_case_insensitive(self):
        self.assertEqual(
            detect_origin_qualifier("CARBON DIOXIDE, NON-FOSSIL, RESOURCE CORRECTION"),
            "biogenic_resource_correction",
        )

    def test_resource_correction_takes_precedence_over_biogenic(self):
        """biogenic_resource_correction must win over plain biogenic."""
        q = detect_origin_qualifier("Carbon dioxide, non-fossil, resource correction")
        self.assertEqual(q, "biogenic_resource_correction")
        self.assertNotEqual(q, "biogenic")

    # ── ORIGIN_QUALIFIERS tuple ───────────────────────────────────────────────

    def test_all_qualifiers_present(self):
        for q in (
            "biogenic",
            "biogenic_resource_correction",
            "fossil",
            "land_use_change",
            "green_water",
            "blue_water",
            "grey_water",
        ):
            with self.subTest(qualifier=q):
                self.assertIn(q, ORIGIN_QUALIFIERS)

    def test_resource_correction_before_biogenic_in_tuple(self):
        """Ordering in ORIGIN_QUALIFIERS must mirror precedence."""
        idx = {q: i for i, q in enumerate(ORIGIN_QUALIFIERS)}
        self.assertLess(idx["biogenic_resource_correction"], idx["biogenic"])


class TestStripQualifierAltLabels(unittest.TestCase):
    """StripQualifierAltLabelsTransformer removes non-qualifier-specific altLabels."""

    def _run(self, flows):
        from brightway_flows.transformers.strip_qualifier_altlabels import (
            StripQualifierAltLabelsTransformer,
        )
        t = StripQualifierAltLabelsTransformer()
        changes = t.transform([Flow.from_dict(f) for f in flows])
        # Apply changes back so we can inspect the result
        by_uuid = {f["uuid"]: f for f in flows}
        for change in changes:
            by_uuid[change.uuid]["altLabel"] = change.new_value
        return changes, flows

    def test_generic_water_synonyms_stripped_from_green_water(self):
        flows = [
            {
                "uuid": "gw",
                "prefLabel": [{"@value": "Green Water", "@language": "en"}],
                "altLabel": [
                    {"@value": "oxidane", "@language": "en"},
                    {"@value": "H2O", "@language": "en"},
                    {"@value": "Green water resource", "@language": "en"},
                ],
            }
        ]
        changes, flows = self._run(flows)
        self.assertEqual(len(changes), 1)
        remaining = [l["@value"] for l in flows[0]["altLabel"]]
        self.assertNotIn("oxidane", remaining)
        self.assertNotIn("H2O", remaining)
        self.assertIn("Green water resource", remaining)

    def test_unqualified_flow_not_touched(self):
        flows = [
            {
                "uuid": "w",
                "prefLabel": [{"@value": "Water", "@language": "en"}],
                "altLabel": [
                    {"@value": "oxidane", "@language": "en"},
                    {"@value": "H2O", "@language": "en"},
                ],
            }
        ]
        changes, _ = self._run(flows)
        self.assertEqual(changes, [])

    def test_generic_co2_synonyms_stripped_from_biogenic_co2(self):
        flows = [
            {
                "uuid": "bio",
                "prefLabel": [{"@value": "Carbon dioxide, biogenic", "@language": "en"}],
                "altLabel": [
                    {"@value": "CO2", "@language": "en"},
                    {"@value": "Carbon dioxide", "@language": "en"},
                    {"@value": "CO2, biogenic", "@language": "en"},
                ],
            }
        ]
        changes, flows = self._run(flows)
        self.assertEqual(len(changes), 1)
        remaining = [l["@value"] for l in flows[0]["altLabel"]]
        self.assertNotIn("CO2", remaining)
        self.assertNotIn("Carbon dioxide", remaining)
        self.assertIn("CO2, biogenic", remaining)

    def test_resource_correction_strips_plain_co2_synonyms(self):
        flows = [
            {
                "uuid": "rc",
                "prefLabel": [
                    {"@value": "Carbon dioxide, non-fossil, resource correction", "@language": "en"}
                ],
                "altLabel": [
                    {"@value": "CO2", "@language": "en"},
                    {"@value": "Carbon dioxide, biogenic", "@language": "en"},
                    {"@value": "CO2, non-fossil, resource correction", "@language": "en"},
                ],
            }
        ]
        changes, flows = self._run(flows)
        self.assertEqual(len(changes), 1)
        remaining = [l["@value"] for l in flows[0]["altLabel"]]
        # plain CO2 and biogenic CO2 don't match biogenic_resource_correction
        self.assertNotIn("CO2", remaining)
        self.assertNotIn("Carbon dioxide, biogenic", remaining)
        self.assertIn("CO2, non-fossil, resource correction", remaining)

    def test_no_changes_when_all_altlabels_share_qualifier(self):
        flows = [
            {
                "uuid": "bw",
                "prefLabel": [{"@value": "Water, blue", "@language": "en"}],
                "altLabel": [
                    {"@value": "Blue water", "@language": "en"},
                ],
            }
        ]
        changes, _ = self._run(flows)
        self.assertEqual(changes, [])


class TestWaterFlowObjectSeparation(unittest.TestCase):
    """Integration tests: water variants must become separate flow objects
    with parent_flow_object_id pointing to the unqualified water object."""

    def _build_minimal_flows(self) -> list[dict]:
        """Four water flows sharing CAS 7732-18-5."""
        return [
            {
                "uuid": "water-plain",
                "prefLabel": [{"@value": "Water", "@language": "en"}],
                "cas_numbers": ["7732-18-5"],
                "source": "test",
            },
            {
                "uuid": "water-green",
                "prefLabel": [{"@value": "Water, green", "@language": "en"}],
                "cas_numbers": ["7732-18-5"],
                "source": "test",
            },
            {
                "uuid": "water-blue",
                "prefLabel": [{"@value": "Water, blue", "@language": "en"}],
                "cas_numbers": ["7732-18-5"],
                "source": "test",
            },
            {
                "uuid": "water-grey",
                "prefLabel": [{"@value": "Water, grey", "@language": "en"}],
                "cas_numbers": ["7732-18-5"],
                "source": "test",
            },
        ]

    def test_four_separate_flow_objects(self):
        from brightway_flows.flow_layers import resolve_flow_layers

        flows = self._build_minimal_flows()
        flow_objects, elementary_flows, _stats = resolve_flow_layers(_as_flows(flows), source_list=BASE)

        object_ids = {fo.flow_object_id for fo in flow_objects}
        self.assertEqual(len(object_ids), 4, "Expected 4 distinct flow objects for 4 water variants")

    def test_qualified_water_has_parent_link(self):
        from brightway_flows.flow_layers import resolve_flow_layers

        flows = self._build_minimal_flows()
        flow_objects, _elementary, _stats = resolve_flow_layers(_as_flows(flows), source_list=BASE)

        by_qualifier = {fo.origin_qualifier: fo for fo in flow_objects}

        plain_id = by_qualifier[None].flow_object_id
        for qualifier in ("green_water", "blue_water", "grey_water"):
            with self.subTest(qualifier=qualifier):
                fo = by_qualifier.get(qualifier)
                self.assertIsNotNone(fo, f"No flow object found for qualifier {qualifier!r}")
                self.assertEqual(
                    fo.parent_flow_object_id,
                    plain_id,
                    f"{qualifier} flow object should link to plain water",
                )

    def test_elementary_flows_mapped_correctly(self):
        from brightway_flows.flow_layers import resolve_flow_layers

        flows = self._build_minimal_flows()
        flow_objects, elementary_flows, _stats = resolve_flow_layers(_as_flows(flows), source_list=BASE)

        ef_by_uuid = {ef.elementary_flow_id: ef for ef in elementary_flows}
        fo_by_id = {fo.flow_object_id: fo for fo in flow_objects}

        for flow in flows:
            uuid = flow["uuid"]
            ef = ef_by_uuid[uuid]
            fo = fo_by_id[ef.flow_object_id]
            label = flow["prefLabel"][0]["@value"]
            expected_qualifier = detect_origin_qualifier(label)
            self.assertEqual(
                fo.origin_qualifier,
                expected_qualifier,
                f"Elementary flow {uuid!r} mapped to wrong flow object qualifier",
            )


if __name__ == "__main__":
    unittest.main()
