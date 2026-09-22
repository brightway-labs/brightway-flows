"""The two qualifiers that tell a land carbon transfer from a land conversion.

Both patterns were added for #139 and neither had a test, which is the wrong way
round for a rule whose whole job is to keep two substances apart: the build-level
expectations pin where today's rows land, but nothing pinned *why*, so a widened
pattern would move rows and only the expectations would notice -- after a
thirteen-minute build, and without saying which pattern did it.

What the two rules say:

`sequestration_from_land_management` claims ecoinvent's `Carbon dioxide, to soil
or biomass stock` -- carbon leaving the atmosphere for a long-lived land pool.
It is not land *use change* (102 of the 269 ecoinvent 3.12 datasets that emit it
are `land already in use`, where no conversion happens) and it is not biogenic
(the fast cycle EF calls neutral is the one whose other half falls inside the
study period).

`land_use_change` claims EF 3.1's `(land use change)` names and the one flow that
spells the same idea `land transformation`.

The direction word is load-bearing, and it is the only thing in the vendor's name
that carries it: `from soil or biomass stock` is the release side, it reaches EF's
own `carbon dioxide (land use change)` where both implementations state +1, and
matching it here would move a flow two publishers agree about.
"""

from __future__ import annotations

import unittest

from brightway_flows.qualifiers import ORIGIN_QUALIFIERS, detect_origin_qualifier


class SequestrationFromLandManagementTestCase(unittest.TestCase):
    """`to soil or biomass stock`, and the three phrases that look like it."""

    def test_the_one_name_it_exists_for(self):
        self.assertEqual(
            detect_origin_qualifier("Carbon dioxide, to soil or biomass stock"),
            "sequestration_from_land_management",
        )

    def test_it_is_case_insensitive(self):
        """merge_outcomes records this name title-cased."""
        self.assertEqual(
            detect_origin_qualifier("Carbon Dioxide, To Soil Or Biomass Stock"),
            "sequestration_from_land_management",
        )

    def test_the_release_side_is_not_claimed(self):
        """`from` is the emission, and it has a flow of its own that means it."""
        for name in (
            "Carbon dioxide, from soil or biomass stock",
            "Carbon monoxide, from soil or biomass stock",
            "Methane, from soil or biomass stock",
        ):
            with self.subTest(name=name):
                self.assertNotEqual(
                    detect_origin_qualifier(name),
                    "sequestration_from_land_management",
                )

    def test_the_balancing_flows_are_not_claimed(self):
        """`in`/`increase in`/`decrease in` are the organic carbon stock balance."""
        for name in (
            "Carbon, organic, in soil or biomass stock",
            "Carbon, organic, increase in soil or biomass stock",
            "Carbon, organic, decrease in soil or biomass stock",
        ):
            with self.subTest(name=name):
                self.assertIsNone(detect_origin_qualifier(name))

    def test_it_wins_over_land_use_change(self):
        """Ordering, stated as a test rather than as a comment.

        The two patterns do not overlap today.  This pins the ordering anyway, so
        that a future `land use` spelling of a stock flow cannot quietly become a
        land-use-change row -- which is the one way these two can collide.
        """
        self.assertEqual(
            detect_origin_qualifier(
                "Carbon dioxide, land use, to soil or biomass stock"
            ),
            "sequestration_from_land_management",
        )

    def test_it_is_a_known_qualifier(self):
        self.assertIn("sequestration_from_land_management", ORIGIN_QUALIFIERS)


class LandUseChangeTestCase(unittest.TestCase):
    """`land use`, `land-use`, and the `land transformation` spelling."""

    def test_ef_spells_it_land_use_change(self):
        for name in (
            "Carbon dioxide (land use change)",
            "methane (land use change)",
            "carbon monoxide (land use change)",
        ):
            with self.subTest(name=name):
                self.assertEqual(detect_origin_qualifier(name), "land_use_change")

    def test_bafu_spells_it_land_transformation(self):
        self.assertEqual(
            detect_origin_qualifier("Carbon dioxide, land transformation"),
            "land_use_change",
        )

    def test_the_hyphenated_spellings(self):
        for name in (
            "Carbon dioxide (land-use change)",
            "Carbon dioxide, land-transformation",
        ):
            with self.subTest(name=name):
                self.assertEqual(detect_origin_qualifier(name), "land_use_change")

    def test_the_land_flows_are_not_claimed(self):
        """The reason the pattern is two alternatives and not the word `land`.

        ecoinvent and BAFU both name their land flows `Transformation, from ...`
        and `Occupation, ...`; none of them contains `land use` or `land
        transformation`, and a pattern on `land` alone would have taken all of
        them.
        """
        for name in (
            "Transformation, from forest, primary (non-use)",
            "Transformation, to arable land, unspecified use",
            "Occupation, forest, intensive",
            "Occupation, arable land, unspecified use",
        ):
            with self.subTest(name=name):
                self.assertIsNone(detect_origin_qualifier(name))

    def test_a_word_that_merely_starts_with_land_is_not_claimed(self):
        self.assertIsNone(detect_origin_qualifier("Landfill gas"))


class PeatOxidationTestCase(unittest.TestCase):
    """AGRIBALYSE's third spelling of a land conversion (#194).

    Draining a peatland and letting the peat oxidise is a change of land use,
    and AGRIBALYSE books it as one: its `Peat degradation emissions on
    grassland, per kg CO2 {GLO}` ships the release as `Carbon dioxide, land
    transformation`, and its soil carbon datasets say their land-transformation
    row is "excluding peat degradation" -- the same accounting split out.
    """

    def test_the_three_names_it_exists_for(self):
        """Every name carrying the phrase across the nine lists read here, and
        all three are AGRIBALYSE's."""
        for name in (
            "Carbon dioxide, peat oxidation",
            "Methane, peat oxidation",
            "Dinitrogen monoxide, peat oxidation",
        ):
            with self.subTest(name=name):
                self.assertEqual(detect_origin_qualifier(name), "land_use_change")

    def test_it_is_case_insensitive_and_takes_the_hyphen(self):
        for name in ("CARBON DIOXIDE, PEAT OXIDATION", "Carbon dioxide, peat-oxidation"):
            with self.subTest(name=name):
                self.assertEqual(detect_origin_qualifier(name), "land_use_change")

    def test_the_peat_rows_that_are_not_a_conversion_are_not_claimed(self):
        """The reason the pattern is the two words together.

        AGRIBALYSE ships peat as a growing medium and as an energy carrier, and
        #354 ruled on both.  Neither is a land conversion, and a pattern on
        `peat` alone would have taken them and every `Peat, horticulture` row in
        the list with them.
        """
        for name in (
            "Peat",
            "Peat, horticulture",
            "Energy, from peat",
            "Peat degradation emissions on grassland",
        ):
            with self.subTest(name=name):
                self.assertIsNone(detect_origin_qualifier(name))

    def test_the_phrase_is_read_as_a_phrase(self):
        """`oxidation` on its own says nothing about where carbon came from."""
        for name in ("Methane, oxidation of peat", "Carbon dioxide, oxidation"):
            with self.subTest(name=name):
                self.assertIsNone(detect_origin_qualifier(name))


if __name__ == "__main__":
    unittest.main()
