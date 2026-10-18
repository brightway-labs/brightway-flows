"""The factor `units.json` gives between two units is published, and says so.

A BAFU row in becquerels lands on a flow this list publishes in
kilobecquerels.  The mapping states 0.001 beside it, with `conversion_basis`
`unit-table` and a `conversion_provenance` naming both units and `units.json`,
so a reader can tell it from a density or a heating value somebody stated for
that row (#393).  Characterisation and lookup convert the same pair by the
same rule, `domain.units.quantity_factor`.
"""

from __future__ import annotations

import unittest

from brightway_flows.domain.units import ConversionBasis, quantity_factor
from brightway_flows.lcia.conversion import UnitCrossing
from brightway_flows.merge.conversions import UnitConversion, conversion_to_publish

UNIT = "https://vocab.brightway.one/units/unit/"


def _publish(conversion=None, *, source_unit, target_unit):
    return conversion_to_publish(
        conversion,
        source_unit=source_unit,
        target_unit=target_unit,
        generated_by="merge_bafu",
        correspondence_file="table.json",
        overrides_file="overrides.json",
    )


class TheUnitTablesFactorIsPublishedTestCase(unittest.TestCase):
    def test_becquerels_onto_kilobecquerels(self):
        published = _publish(source_unit="Bq", target_unit="kBq")
        self.assertAlmostEqual(published.factor, 0.001)
        self.assertIs(published.basis, ConversionBasis.UNIT_TABLE)

    def test_it_cites_both_units_and_the_table(self):
        metadata = _publish(source_unit="Bq", target_unit="kBq").to_metadata()
        self.assertEqual(metadata["conversion_basis"], "unit-table")
        self.assertEqual(
            metadata["conversion_provenance"],
            {
                "prov:wasGeneratedBy": "merge_bafu",
                "prov:wasAttributedTo": "brightway-flows",
                "prov:hadPrimarySource": [UNIT + "BQ", UNIT + "KiloBQ", "units.json"],
                "prov:wasDerivedFrom": "units.json",
            },
        )

    def test_one_unit_publishes_nothing(self):
        self.assertIsNone(_publish(source_unit="kg", target_unit="kg"))

    def test_two_spellings_of_one_unit_publish_nothing(self):
        self.assertIsNone(_publish(source_unit="m2*a", target_unit="m2.a"))

    def test_a_crossing_of_quantity_kinds_publishes_nothing(self):
        """A mass onto an energy needs a heating value, which no unit table
        has."""
        self.assertIsNone(_publish(source_unit="kg", target_unit="MJ"))

    def test_an_unknown_unit_publishes_nothing(self):
        self.assertIsNone(_publish(source_unit="widgets", target_unit="kg"))


class AStatedFactorComesFirstTestCase(unittest.TestCase):
    def test_a_correspondence_tables_factor_cites_the_table(self):
        published = _publish(
            UnitConversion(9.41, "kg", "MJ"), source_unit="kg", target_unit="MJ"
        )
        self.assertEqual(published.factor, 9.41)
        self.assertIs(published.basis, ConversionBasis.CORRESPONDENCE_TABLE)
        self.assertEqual(published.provenance.was_derived_from, "table.json")

    def test_a_curated_factor_cites_the_file_that_states_it(self):
        published = _publish(
            UnitConversion(
                0.00204, "kg", "m3",
                basis=ConversionBasis.CURATED, stated_in="bafu-manual-fixes.json",
            ),
            source_unit="kg",
            target_unit="m3",
        )
        self.assertIs(published.basis, ConversionBasis.CURATED)
        self.assertEqual(published.provenance.was_derived_from, "bafu-manual-fixes.json")

    def test_a_curated_prepared_row_cites_the_overrides(self):
        published = _publish(
            UnitConversion(0.599, "kg", "kg", basis=ConversionBasis.CURATED),
            source_unit="kg",
            target_unit="kg",
        )
        self.assertEqual(published.factor, 0.599)
        self.assertEqual(published.provenance.was_derived_from, "overrides.json")

    def test_a_stated_factor_the_unit_table_implies_is_the_unit_tables(self):
        """Litres to cubic metres at 0.001 is what `units.json` says, so the
        table stating it is not a statement of its own."""
        published = _publish(
            UnitConversion(0.001, "L", "m3"), source_unit="L", target_unit="m3"
        )
        self.assertIs(published.basis, ConversionBasis.UNIT_TABLE)

    def test_a_stated_factor_that_no_longer_holds_falls_back(self):
        """A kg -> MJ heating value on a pair that is kWh -> MJ is not that
        pair's; the unit table's 3.6 is."""
        published = _publish(
            UnitConversion(9.41, "kg", "MJ"), source_unit="kWh", target_unit="MJ"
        )
        self.assertAlmostEqual(published.factor, 3.6)
        self.assertIs(published.basis, ConversionBasis.UNIT_TABLE)


class OneRuleForLookupAndCharacterisationTestCase(unittest.TestCase):
    def test_the_rule(self):
        cases = [
            ("kg", "MJ", 9.41, 9.41),
            ("kg", "kg", None, 1.0),
            ("m2*a", "m2.a", None, 1.0),
            ("Bq", "kBq", None, 0.001),
            ("kWh", "MJ", None, 3.6),
            ("kg", "MJ", None, None),
            ("widgets", "kg", None, None),
        ]
        for source, target, stated, expected in cases:
            with self.subTest(source=source, target=target, stated=stated):
                factor = quantity_factor(source, target, stated)
                if expected is None:
                    self.assertIsNone(factor)
                else:
                    self.assertAlmostEqual(factor, expected)

    def test_a_factor_per_becquerel_is_published_per_kilobecquerel(self):
        """Characterisation used to refuse this pair for want of a recorded
        multiplier; 2.0 per Bq is 2,000 per kBq."""
        crossing = UnitCrossing("Bq", "kBq")
        self.assertTrue(crossing.convertible)
        self.assertAlmostEqual(crossing.convert(2.0), 2000.0)

    def test_a_mass_onto_an_energy_is_still_refused(self):
        crossing = UnitCrossing("kg", "MJ")
        self.assertFalse(crossing.convertible)
        with self.assertRaises(ValueError):
            crossing.convert(1.0)


if __name__ == "__main__":
    unittest.main()
