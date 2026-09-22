"""Reading a half-life out of the text the nuclear-data sources give it in.

Extracted from `flow_layers` when `semantic_typing` started publishing the
value: it was a private function in a module that pulls in settings, the
filesystem and the integrations, and the only way to test it was through a build.
"""

import unittest

from brightway_flows.domain.nuclides import half_life_days, half_life_years


class HalfLifeTestCase(unittest.TestCase):
    def test_the_forms_the_sources_actually_use(self):
        cases = {
            "432.6 a": 432.6,          # ChemLIN writes years as annum
            "432.6(2) a": 432.6,       # with an uncertainty in brackets
            "10.739 yr": 10.739,
            "2.1 y": 2.1,
        }
        for text, expected in cases.items():
            with self.subTest(text=text):
                self.assertAlmostEqual(half_life_years(text), expected, places=3)

    def test_a_short_lived_nuclide_is_a_small_fraction_of_a_year(self):
        self.assertAlmostEqual(half_life_days("5.7 ms"), 5.7e-3 / 86400, places=12)

    def test_the_units_convert_against_each_other(self):
        self.assertAlmostEqual(half_life_days("1 a") / 365.25, 1.0, places=2)

    def test_annum_is_years_and_not_ares(self):
        """`a` is how these sources spell years, and is an area unit to pint."""
        self.assertAlmostEqual(half_life_years("100 a"), 100.0, places=6)

    def test_a_stable_nuclide_has_no_published_half_life(self):
        """Infinity is not a number JSON carries, and "does not decay" is better
        said by the absence of a value than by one nothing can compare."""
        self.assertIsNone(half_life_years("stable"))

    def test_but_ranking_still_sees_it_as_the_longest_lived(self):
        """`flow_layers` picks a metastable candidate by this, and a stable one
        must win."""
        self.assertEqual(half_life_days("stable"), float("inf"))

    def test_text_that_yields_no_quantity_is_none(self):
        for text in ("", "   ", "unknown", "?", "n/a"):
            with self.subTest(text=text):
                self.assertIsNone(half_life_years(text))

    def test_an_unrecognised_unit_is_none_rather_than_a_guess(self):
        self.assertIsNone(half_life_years("5 fortnights"))

    def test_html_entities_are_decoded_first(self):
        self.assertAlmostEqual(half_life_years("12.3&nbsp;a"), 12.3, places=3)

    def test_scientific_notation(self):
        self.assertAlmostEqual(half_life_years("1.5e3 a"), 1500.0, places=3)


if __name__ == "__main__":
    unittest.main()
