"""What has to hold inside `units.json` for the code that reads three of its fields.

`domain/units.py` decides whether a correspondence table's factor says anything
new by dividing two `conversion_multiplier`s, and it only does that division
when the two rows agree on `quantity_kind_iri` and on `reference_unit_iri`.
`merge/conversions.py` reads `quantity_kind_iri` alone to decide whether a pair
crosses a time dimension, which is the guard that refuses to inherit somebody
else's assumed duration.  Neither reads the file's prose, so a row that points
its `reference_unit_iri` at a quantity kind, or names a day where it means a
year, does not fail -- it quietly answers "the table says nothing" and a second
copy of a fact that already has a home on the unit gets published (#274).

Four things are asserted, all of them properties of the file rather than of any
one run:

- the two IRI fields are not interchanged, which is how `kg.s` shipped for a
  while: its own unit IRI as its quantity kind and `MassTime` as its reference;
- every `reference_unit_iri` names a unit the file defines, and that unit is the
  base of its own scale.  There is no exception left: `Nm3` was the one, and it
  is now an alias of `sm3` rather than a row of its own (#292), so a two-hop
  reference appearing again is a failure rather than a precedent;
- a unit and its reference measure the same kind of quantity;
- a time-denominated unit is its own untimed scale times seconds, days or the
  Julian year -- never the Julian year for `m2.a` and a day for `m.a`, which is
  invisible from `km.a -> m.a` because both were wrong by the same factor.
"""

import unittest

import orjson

from brightway_flows.domain.units import UNITS_FILEPATH, unit_table_factor
from brightway_flows.merge.conversions import crosses_a_time_dimension

UNIT_PREFIX = "https://vocab.brightway.one/units/unit/"
QUANTITY_KIND_PREFIX = "https://vocab.brightway.one/units/quantity-kind/"

#: Seconds in a day, and in the Julian year the file uses everywhere it says
#: "year" -- 365.25 days, the astronomers' year rather than the calendar's.
SECONDS = {"s": 1.0, "d": 86400.0, "a": 31557600.0}

#: Empty, and meant to stay that way.  `Nm3` was the only entry -- stated against
#: `sm3` rather than against `mol` -- and it is an alias now, not a row (#292).
#: `unit_table_factor` keeps its branch for one quantity kind reached through two
#: reference units, because the branch is what makes a new one safe rather than
#: silently divided through.
TWO_HOP_REFERENCES: set[str] = set()


def _rows():
    return orjson.loads(UNITS_FILEPATH.read_bytes())


class UnitTableShapeTestCase(unittest.TestCase):
    """The file's internal references, read the way the code reads them."""

    def setUp(self):
        self.rows = _rows()
        self.by_iri = {row["iri"]: row for row in self.rows}

    def test_the_iri_fields_name_the_kind_of_thing_they_are_named_for(self):
        """A quantity kind in `reference_unit_iri` is not a resolvable unit."""
        for row in self.rows:
            with self.subTest(notation=row["notation"]):
                self.assertTrue(
                    row["reference_unit_iri"].startswith(UNIT_PREFIX),
                    f"{row['notation']} references {row['reference_unit_iri']}",
                )
                self.assertTrue(
                    row["quantity_kind_iri"].startswith(QUANTITY_KIND_PREFIX),
                    f"{row['notation']} is kind {row['quantity_kind_iri']}",
                )

    def test_every_reference_unit_is_a_unit_the_file_defines(self):
        for row in self.rows:
            with self.subTest(notation=row["notation"]):
                self.assertIn(row["reference_unit_iri"], self.by_iri)

    def test_a_reference_unit_is_the_base_of_its_own_scale(self):
        """Otherwise two rows on one scale disagree about where its zero is."""
        for row in self.rows:
            if row["notation"] in TWO_HOP_REFERENCES:
                continue
            reference = self.by_iri.get(row["reference_unit_iri"])
            if reference is None:
                continue
            with self.subTest(notation=row["notation"]):
                self.assertEqual(
                    reference["reference_unit_iri"],
                    reference["iri"],
                    f"{row['notation']} references {reference['notation']}, "
                    f"which is itself stated against "
                    f"{reference['reference_unit_iri'].rsplit('/', 1)[-1]}",
                )

    def test_a_unit_measures_what_its_reference_unit_measures(self):
        for row in self.rows:
            reference = self.by_iri.get(row["reference_unit_iri"])
            if reference is None:
                continue
            with self.subTest(notation=row["notation"]):
                self.assertEqual(
                    row["quantity_kind_iri"],
                    reference["quantity_kind_iri"],
                    f"{row['notation']} is {row['quantity_kind_iri']} against "
                    f"{reference['notation']}, which is "
                    f"{reference['quantity_kind_iri']}",
                )

    def test_a_year_is_the_julian_year_wherever_the_file_says_year(self):
        """`X.a` is `X` times 365.25 days, for every `X` the file also carries."""
        by_notation = {row["notation"]: row for row in self.rows}
        checked = 0
        for row in self.rows:
            base, _, suffix = row["notation"].rpartition(".")
            if suffix not in SECONDS or base not in by_notation:
                continue
            checked += 1
            with self.subTest(notation=row["notation"]):
                self.assertAlmostEqual(
                    row["conversion_multiplier"],
                    by_notation[base]["conversion_multiplier"] * SECONDS[suffix],
                    msg=f"{row['notation']} is not {base} times {suffix}",
                )
        self.assertGreaterEqual(checked, 8, "the time-denominated rows went missing")


class WhatTheCodeReadsOffTheTableTestCase(unittest.TestCase):
    """The three answers #274 changed, pinned as answers rather than as rows."""

    def test_the_mass_time_units_convert_into_each_other(self):
        """No table factor here means every stated one looks substance-specific."""
        self.assertAlmostEqual(unit_table_factor("kg.d", "kg.a"), 86400 / 31557600)
        self.assertAlmostEqual(unit_table_factor("kg.s", "kg.d"), 1 / 86400)
        self.assertAlmostEqual(unit_table_factor("kg.s", "kg.a"), 1 / 31557600)

    def test_seconds_to_a_year_is_a_year(self):
        self.assertAlmostEqual(unit_table_factor("m.a", "m.s"), 31557600.0)
        self.assertAlmostEqual(unit_table_factor("km.a", "m.a"), 1000.0)

    def test_a_standard_cubic_metre_is_moles(self):
        """42.38 mol/m3 -- an ideal gas at 1 atm and 15 degrees C."""
        self.assertAlmostEqual(unit_table_factor("sm3", "mole"), 42.38)

    def test_kilograms_to_kilogram_seconds_crosses_a_time_dimension(self):
        """The guard that refuses to inherit an assumed duration."""
        for untimed, timed in (("kg", "kg.s"), ("kg", "kg.a"), ("m2", "m2.a")):
            with self.subTest(pair=(untimed, timed)):
                self.assertTrue(crosses_a_time_dimension(untimed, timed))


if __name__ == "__main__":
    unittest.main()
