"""Stepwise 2006's factors: what is read, what is rescaled, what is kept.

The rescaling is the part with a wrong answer that looks ordinary.  A factor
stated per gram and published against a flow inventoried in kilograms is a
thousandfold error that no downstream check can see, because a published factor
carries no unit of its own -- the category's unit is the indicator's, not the
flow's.  So the conversion is asserted in both directions here: that it happens
where the two units differ, and that it does not happen where they agree.
"""

from __future__ import annotations

import unittest
from pathlib import Path

import orjson

from brightway_flows.domain.lcia.crosswalk import (
    STEPWISE_IMPACT_CATEGORIES_FILEPATH,
    lcia_method,
    lcia_methods,
)
from brightway_flows.domain.units import unit_table_factor
from brightway_flows.integrations.stepwise_lcia import (
    FACTORS_SCHEMA_VERSION,
    FLOW_UNIT_KEY,
    StepwiseLciaError,
    _rescale,
    load_factors,
)
from brightway_flows.sources import known_source_lists

STEPWISE_KEY = "stepwise-2006-1.09"
METHOD_SLUG = "stepwise-2006"
STATED_METHOD = "Stepwise_2006_IPCC2021_CorrectedNatureOccupation"


class TheMethodFileTestCase(unittest.TestCase):
    """What the second method file has to be, checked without a build."""

    def setUp(self):
        self.method = lcia_method(METHOD_SLUG)

    def test_it_is_registered_beside_the_first(self):
        slugs = [method.slug for method in lcia_methods()]
        self.assertIn(METHOD_SLUG, slugs)
        self.assertIn("ef", slugs)

    def test_it_declares_nineteen_categories(self):
        # 19 is the whole of the export.  A file with 18 would publish a method
        # with a category missing and nothing saying which.
        self.assertEqual(len(self.method.categories), 19)

    def test_one_publisher_decides_and_ours_does_not(self):
        self.assertEqual(self.method.reference.name, "2.-0 LCA consultants")
        self.assertTrue(self.method.reference.decides)
        self.assertFalse(self.method.consensus.decides)

    def test_every_category_states_a_unit_the_vocabulary_defines(self):
        from brightway_flows.domain.units import known_unit_iris

        known = known_unit_iris()
        for category in self.method.categories:
            with self.subTest(category.slug):
                self.assertIn(category.unit_iri, known)

    def test_the_damage_units_are_the_endpoint_categories(self):
        # The reading #346 settled: a category counted in an equivalence unit is
        # a midpoint, and one counted in a damage unit -- an unprotected
        # ecosystem area, a disappeared fraction, a fatal injury, a euro -- is an
        # endpoint.  Named rather than counted, because the point is which.
        endpoint = {
            category.slug
            for category in self.method.categories
            if str(category.midpoint_endpoint) == "Endpoint"
        }
        self.assertEqual(
            endpoint,
            {
                "acidification",
                "economic-costs",
                "eutrophication-terrestrial",
                "injuries-road-or-work",
                "nature-occupation",
            },
        )

    def test_the_stated_names_are_the_export_s_own(self):
        # The crosswalk matches a factor to a category by this name, so a row
        # rewritten into our house style would file every factor under nothing.
        stated = {
            category.stated_by("twenty-zero-lca").name
            for category in self.method.categories
        }
        self.assertIn("Human toxicity, non-carc.", stated)
        self.assertIn("Photochemical ozone, vegetat.", stated)

    def test_the_file_the_repository_ships_is_the_one_that_is_read(self):
        payload = orjson.loads(STEPWISE_IMPACT_CATEGORIES_FILEPATH.read_bytes())
        self.assertEqual(payload["method"]["slug"], METHOD_SLUG)
        self.assertEqual(len(payload["categories"]), 19)


class TheManifestAndTheMethodFileAgreeTestCase(unittest.TestCase):
    """Two files naming each other, held to it without fetching anything."""

    def test_the_list_declares_the_method_the_file_reads(self):
        source = known_source_lists()[STEPWISE_KEY]
        self.assertIsNotNone(source.lcia)
        self.assertEqual(
            [method.name for method in source.lcia.methods], [STATED_METHOD]
        )
        self.assertEqual(source.lcia.implemented_by, "2.-0 LCA consultants")

    def test_the_reference_implementation_reads_that_list(self):
        reference = lcia_method(METHOD_SLUG).reference
        self.assertEqual(reference.factors.source_list, STEPWISE_KEY)
        self.assertEqual(reference.factors.stated_method, STATED_METHOD)

    def test_a_reader_is_registered_for_the_publisher(self):
        # An implementation reading a list with no reader for its file format
        # raises at characterisation; this is the same claim, one import earlier.
        from brightway_flows.lcia.sources import _READERS

        self.assertIn("2.-0 LCA consultants", _READERS)


class TheRescalingTestCase(unittest.TestCase):
    """A factor per gram is not a factor per kilogram."""

    def test_a_factor_per_gram_is_a_thousand_times_as_much_per_kilogram(self):
        self.assertAlmostEqual(
            _rescale(3.8e-05, factor_unit="g", flow_unit="kg", name="Methane"),
            0.038,
        )

    def test_a_factor_per_becquerel_is_a_thousand_times_as_much_per_kilobecquerel(self):
        # The case #164 found: every radionuclide is inventoried in kBq and
        # every one of `Ionizing radiation`'s 36 rows is stated per Bq.
        self.assertAlmostEqual(
            _rescale(2.0, factor_unit="Bq", flow_unit="kBq", name="Radon-222"),
            2000.0,
        )

    def test_the_four_pairs_the_export_states_are_all_conversions_this_file_knows(self):
        # If `units.json` stopped converting one of them the fetch would raise,
        # which is the right failure -- but it would raise after a download, and
        # this says so in a second.
        for flow_unit, factor_unit, expected in (
            ("kg", "g", 1000.0),
            ("kBq", "Bq", 1000.0),
            ("ton", "kg", 1000.0),
            ("ha a", "m2a", 10000.0),
        ):
            with self.subTest(f"{factor_unit} -> {flow_unit}"):
                self.assertEqual(unit_table_factor(flow_unit, factor_unit), expected)

    def test_a_pair_the_unit_table_cannot_convert_raises(self):
        # Publishing it unscaled would state a number per a unit nobody asked
        # for, and silently: a published factor carries no unit of its own.
        with self.assertRaises(StepwiseLciaError) as caught:
            _rescale(1.0, factor_unit="kg", flow_unit="m3", name="Something")
        self.assertIn("does not convert", str(caught.exception))


class TheWrittenFileTestCase(unittest.TestCase):
    """`load_factors` on a file this test writes: the shape, not the data."""

    def setUp(self):
        import tempfile

        self.directory = Path(tempfile.mkdtemp())
        self.path = self.directory / "stepwise-2006-lcia-factors.json"

    def _write(self, factors):
        self.path.write_bytes(
            orjson.dumps(
                {
                    "schema_version": FACTORS_SCHEMA_VERSION,
                    "source": STEPWISE_KEY,
                    "list_version": "2006-1.09",
                    "export": "Stepwise2006_v1.09.csv",
                    "methods": [
                        {
                            "method": STATED_METHOD,
                            "categories": [
                                {
                                    "category": "Respiratory organics",
                                    "unit": "pers*ppm*h",
                                    "factor_count": len(factors),
                                    "zero_count": 0,
                                }
                            ],
                            "factor_count": len(factors),
                            "flow_count": len(factors),
                            "rescaled_count": 1,
                            "factors": factors,
                        }
                    ],
                }
            )
        )

    def test_a_rescaled_row_keeps_the_publisher_s_own_unit(self):
        self._write(
            [
                {
                    "flow_uuid": "abc",
                    "category": "Respiratory organics",
                    "amount": 0.038,
                    FLOW_UNIT_KEY: "g",
                }
            ]
        )
        (factors,) = load_factors(self.path).values()
        self.assertEqual(factors[0].amount, 0.038)
        self.assertEqual(factors[0].extra, {FLOW_UNIT_KEY: "g"})

    def test_a_row_that_needed_no_rescaling_carries_no_extra_key(self):
        # Rule 3 the other way: a key the publisher did not state must not be
        # invented, or every row grows a unit it never had.
        self._write(
            [{"flow_uuid": "abc", "category": "Respiratory organics", "amount": 1.0}]
        )
        (factors,) = load_factors(self.path).values()
        self.assertEqual(factors[0].extra, {})

    def test_the_category_name_is_what_the_crosswalk_matches_on(self):
        self._write(
            [{"flow_uuid": "abc", "category": "Respiratory organics", "amount": 1.0}]
        )
        (factors,) = load_factors(self.path).values()
        self.assertEqual(factors[0].category.name, "Respiratory organics")
        # The export states none, and a record that filled it in would publish a
        # value the file does not have.
        self.assertIsNone(factors[0].category.methodology)

    def test_a_file_from_another_schema_is_refused(self):
        self.path.write_bytes(orjson.dumps({"schema_version": 99, "methods": []}))
        with self.assertRaises(StepwiseLciaError):
            load_factors(self.path)


if __name__ == "__main__":
    unittest.main()
