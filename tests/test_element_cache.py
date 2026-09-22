"""Reading PubChem's and ChemLIN's answers without losing their shape.

Both sources hand this project a table it has to reassemble, and both
reassemblies were losing information in a way that produced plausible wrong
numbers rather than obvious missing ones.

PubChem serves the decay table as **parallel columns**, zipped back into rows by
position. Blank cells were dropped before the zip, so a missing value pulled
every later value in that column one row out of step and 18 of the 118 elements
published a decay mode belonging to a different nuclide -- 138 ground states
came out decaying by isomeric transition, which a ground state cannot do. It is
the same defect as the positional context reconstruction in the merge, one layer
down, and it is why blanks are load-bearing here.

ChemLIN writes a power of ten as markup, and the scrape stopped at the first
tag: uranium-235's `7.04(1) &times; 10<sup>8</sup> a` came back as
`7.04(1) &times; 10`.
"""

from __future__ import annotations

import unittest

from brightway_flows.domain.nuclides import Nuclide, half_life_years
from brightway_flows.flow_layers.element_cache import (
    _fold_scientific_notation,
    _parse_isotope_decay_annotation,
    _resolve_chemlin_isotope_data,
)


def _annotation(**columns: list[str]) -> dict:
    """PubChem's annotation payload: one entry per column, not per row."""
    names = {
        "nuclide": "Nuclide",
        "half_life": "Half Life and Uncertainty",
        "discovery_year": "Discovery Year",
        "decay_modes": "Decay Modes, Intensities and Uncertainties [%]",
    }
    return {
        "Data": [
            {
                "Name": names[key],
                "Value": {"StringWithMarkup": [{"String": value} for value in values]},
            }
            for key, values in columns.items()
        ]
    }


class DecayTableAlignmentTestCase(unittest.TestCase):
    def test_a_blank_cell_holds_its_row(self):
        """Curium is the real case: PubChem has no discovery year for four of
        its nuclides. Skipping the blanks moved every later year up one, so
        curium-242 was given curium-242m's decay mode."""
        rows = _parse_isotope_decay_annotation(
            _annotation(
                nuclide=["242Cm", "242Cmm", "243Cm"],
                decay_modes=["α=100%", "", "α=100%"],
                discovery_year=["1947", "", "1947"],
            )
        )
        self.assertEqual(len(rows), 3)
        by_nuclide = {row["nuclide"]: row for row in rows}
        self.assertEqual(
            by_nuclide["242Cm"]["decay_modes_intensities_and_uncertainties_%"],
            "α=100%",
        )
        self.assertNotIn(
            "decay_modes_intensities_and_uncertainties_%", by_nuclide["242Cmm"]
        )
        self.assertEqual(
            by_nuclide["243Cm"]["decay_modes_intensities_and_uncertainties_%"],
            "α=100%",
        )

    def test_a_column_that_does_not_line_up_is_refused(self):
        """Zipping it short is what silently mis-assigns. The caller keeps the
        section-parsed table, which is keyed by nuclide and cannot slip."""
        self.assertEqual(
            _parse_isotope_decay_annotation(
                _annotation(
                    nuclide=["242Cm", "242Cmm", "243Cm"],
                    decay_modes=["α=100%", "IT=100%"],
                )
            ),
            [],
        )

    def test_a_payload_with_no_nuclide_column_yields_nothing(self):
        self.assertEqual(
            _parse_isotope_decay_annotation(_annotation(decay_modes=["α=100%"])), []
        )


class ScientificNotationTestCase(unittest.TestCase):
    def test_the_exponent_survives_the_markup(self):
        self.assertEqual(
            _fold_scientific_notation("7.04(1) &times; 10<sup>8</sup> a"),
            "7.04(1)e8 a",
        )

    def test_and_reaches_the_parser_as_a_number(self):
        folded = _fold_scientific_notation("4.468(6) &times; 10<sup>9</sup> a")
        self.assertAlmostEqual(half_life_years(folded), 4.468e9, places=3)

    def test_a_negative_exponent(self):
        self.assertEqual(
            _fold_scientific_notation("1.5 &times; 10<sup>-3</sup> s"), "1.5e-3 s"
        )

    def test_a_plain_value_is_left_alone(self):
        self.assertEqual(_fold_scientific_notation("22.20(22) a"), "22.20(22) a")


class IsomerResolutionTestCase(unittest.TestCase):
    """Which ChemLIN page is the page for this nuclide.

    ChemLIN numbers the excited states `m`, `m1`, `m2`, `m3` where PubChem
    letters them `m`, `n`, `p`, `q`, and the two orderings are not reliably the
    same nuclide -- so the state cannot be translated. What settles it is that
    PubChem has already stated a half-life: whichever page agrees with it is the
    right page, which makes the selection a cross-check between two independent
    sources rather than a preference.
    """

    def _resolve(self, nuclide: Nuclide, pages: dict[str, float], expected):
        """*pages* maps a slug suffix to the half-life in days ChemLIN gives it."""
        import brightway_flows.flow_layers.element_cache as cache

        def fake_fetch(client, *, element_name, mass_suffix):
            if mass_suffix not in pages:
                return {"url": f"…/{mass_suffix}", "slug": mass_suffix, "found": False}
            return {
                "url": f"…/{mass_suffix}",
                "slug": mass_suffix,
                "found": True,
                "half_life": f"{pages[mass_suffix]} d",
                "half_life_days": pages[mass_suffix],
                "specific_activity_bq_per_g": "",
                "specific_activity_bq_per_g_value": None,
                "source": "ChemLin",
            }

        original = cache._fetch_chemlin_isotope_data
        cache._fetch_chemlin_isotope_data = fake_fetch
        try:
            return _resolve_chemlin_isotope_data(
                None,
                element_name="uranium",
                nuclide=nuclide,
                expected_half_life_days=expected,
            )
        finally:
            cache._fetch_chemlin_isotope_data = original

    def test_the_page_agreeing_with_pubchem_wins(self):
        result = self._resolve(
            Nuclide("U", 238, "m"),
            {"238": 1.63e12, "238m": 3.24e-12},
            expected=3.24e-12,
        )
        self.assertEqual(result["isomer_resolution"]["selected_slug"], "238m")
        self.assertEqual(
            result["isomer_resolution"]["strategy"], "half_life_agrees_with_pubchem"
        )

    def test_the_ground_state_page_is_fetched_for_an_isomer_too(self):
        """Without it the ranking had one candidate and called it the
        longest-lived of the set, and a wrong metastable flag was
        unrecoverable rather than merely mistaken."""
        result = self._resolve(
            Nuclide("U", 238, "m"), {"238": 1.63e12, "238m": 3.24e-12}, expected=3.24e-12
        )
        self.assertIn("238", result["isomer_resolution"]["attempted_slugs"])

    def test_a_ground_state_asks_for_one_page(self):
        result = self._resolve(Nuclide("U", 238), {"238": 1.63e12}, expected=1.63e12)
        self.assertEqual(result["isomer_resolution"]["attempted_slugs"], ["238"])
        self.assertEqual(result["isomer_resolution"]["selected_slug"], "238")

    def test_with_nothing_to_agree_with_the_guess_is_named_as_one(self):
        result = self._resolve(
            Nuclide("U", 238, "m"), {"238": 1.63e12, "238m": 3.24e-12}, expected=None
        )
        self.assertEqual(
            result["isomer_resolution"]["strategy"],
            "longest_half_life_no_expected_value",
        )

    def test_no_page_at_all_is_recorded_rather_than_left_blank(self):
        result = self._resolve(Nuclide("U", 238), {}, expected=1.63e12)
        self.assertFalse(result["found"])
        self.assertEqual(result["isomer_resolution"]["strategy"], "no_page_found")

    def test_a_stable_nuclide_has_no_half_life_to_agree_with(self):
        """`half_life_days("Stable")` is infinity, which is what the ranking in
        the other branch needs and what this comparison cannot take: every
        candidate is infinitely far from it, and the reciprocal of that
        distance divides by zero. Xenon-131, Tellurium-123 and Argon-40 are
        stable, in the list, and reached here on any run with a cold ChemLIN
        cache -- which is why a warm one hid it.
        """
        result = self._resolve(
            Nuclide("Xe", 131), {"131": 1.0}, expected=float("inf")
        )
        self.assertEqual(result["isomer_resolution"]["strategy"], "ground_state_slug")
        self.assertEqual(result["isomer_resolution"]["selected_slug"], "131")

    def test_a_ratio_too_small_to_invert_does_not_divide_by_zero(self):
        """The same failure without the infinity: a candidate far enough from
        the expected value that the ratio underflows."""
        result = self._resolve(
            Nuclide("U", 238), {"238": 1e-300}, expected=1e300
        )
        self.assertEqual(result["isomer_resolution"]["selected_slug"], "238")


if __name__ == "__main__":
    unittest.main()
