"""The curated water and land tables, consulted by name instead of uuid (#358).

`water-flow-materials.json` and `land-flow-classes.json` are keyed on the
vendor's row uuid, and a query has none -- so until #358 the lookup told a
caller that which kind of water and which land class were things it could not
work out, while the answer sat in a table whose rows also record the vendor's
spelling.  These tests hold the name-keyed reading to the same discipline the
uuid-keyed one has: a name two rows disagree about declines rather than being
arbitrated, and a compartment the caller did resolve is never crossed.

The index tests run off package data alone.  The matcher tests need a build,
and skip without one, like every other real-build lookup test.
"""

from __future__ import annotations

import logging
import unittest

import structlog

from brightway_flows.filesystem import CONSENSUS_DB_FILEPATH
from brightway_flows.lookup import FlowMatcher, FlowQuery, UnusableBuildError
from brightway_flows.lookup.curated_names import (
    land_class_for_name,
    material_for_name,
)
from brightway_flows.lookup.query import resolve_context
from test_lookup_matcher import _quiet_logs


def _context(*parts: str):
    """The caller's compartment, resolved the way the matcher resolves it."""
    return resolve_context(FlowQuery(name="", context=list(parts)))


class _Quiet(unittest.TestCase):
    def setUp(self) -> None:
        super().setUp()
        _quiet_logs(self)


class WaterByNameTestCase(_Quiet):
    """Which kind of water, read off the table's own spellings."""

    def test_a_name_the_table_spells_once_answers_in_its_compartment(self):
        """BAFU and five ecoinvent releases all call `Water, lake` lake water,
        so a caller writing that name in a water resource compartment gets the
        material without stating it."""
        context = _context("Raw", "in water")
        self.assertEqual(material_for_name("Water, lake", context), "lake_water")

    def test_the_compartment_splits_a_name_the_table_reads_two_ways(self):
        """`Water, unspecified natural origin` is three different materials in
        three compartments -- fossil groundwater at a fossil well, groundwater
        in the ground, water in surface water -- and the compartment is what
        tells them apart, exactly as it does in the table itself."""
        self.assertEqual(
            material_for_name(
                "Water, unspecified natural origin", _context("Raw", "in water")
            ),
            "water",
        )
        self.assertEqual(
            material_for_name(
                "Water, unspecified natural origin", _context("Raw", "in ground")
            ),
            "groundwater",
        )

    def test_a_disagreement_the_compartment_cannot_settle_declines(self):
        """A caller who writes `Raw` and refuses to name a medium has not said
        whether their unspecified water came from the ground or the surface,
        and the table disagrees across that dimension -- so no material, which
        leaves the row on the CAS route and its honest twelve candidates."""
        context = _context("Raw", "(unspecified)")
        self.assertEqual(
            material_for_name("Water, unspecified natural origin", context), ""
        )

    def test_a_name_no_row_spells_stays_empty(self):
        self.assertEqual(
            material_for_name("Benzene", _context("Raw", "in water")), ""
        )

    def test_a_resolved_compartment_outside_the_table_is_not_answered(self):
        """`Water, lake` is a resource-side curation -- every row of it sits in
        a water resource compartment -- and a caller who resolved to an
        *emission* compartment must not be answered from it.  Falling through
        to the whole-table rung is how a discharge into a river was nearly
        typed as lake water drawn from one."""
        context = _context("Emissions to water", "river")
        self.assertTrue(context.context_iri)
        self.assertEqual(material_for_name("Water, lake", context), "")


class LandByNameTestCase(_Quiet):
    """Which land class -- where no two of the table's rows disagree about a
    name, so the name alone answers a caller with no readable compartment."""

    def test_an_occupation_name_answers_with_no_compartment_at_all(self):
        context = _context("nowhere anybody has mapped")
        self.assertEqual(
            land_class_for_name("Occupation, arable", context),
            "occupation/cropland",
        )

    def test_a_transformation_name_answers_too(self):
        context = _context("Raw", "land")
        self.assertEqual(
            land_class_for_name("Transformation, from forest, unspecified", context),
            "transformation-from/forest",
        )

    def test_a_name_outside_the_table_stays_empty(self):
        self.assertEqual(land_class_for_name("Occupation, the moon", _context()), "")


class AgainstARealBuildTestCase(_Quiet):
    """The join inside the matcher, asked the questions #358 was opened about."""

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        structlog.configure(
            wrapper_class=structlog.make_filtering_bound_logger(logging.CRITICAL)
        )
        # Registered before anything can skip: a `SkipTest` below must not
        # leave the CRITICAL filter on for the rest of the run, where it would
        # silence events later suites assert with `capture_logs`.
        cls.addClassCleanup(structlog.reset_defaults)
        if not CONSENSUS_DB_FILEPATH.exists():
            raise unittest.SkipTest(f"no build at {CONSENSUS_DB_FILEPATH}")
        try:
            cls.matcher = FlowMatcher.from_results(CONSENSUS_DB_FILEPATH)
        except UnusableBuildError as error:
            raise unittest.SkipTest(str(error))

    def test_a_land_row_is_placed_without_the_caller_stating_the_class(self):
        result = self.matcher.match(
            FlowQuery(
                name="Occupation, arable",
                context=["Raw", "land"],
                unit="m2a",
                simapro_origin=True,
            )
        )
        self.assertTrue(result.matched)
        self.assertEqual(result.basis, "land_class")
        self.assertEqual(result.basis_value, "occupation/cropland")
        self.assertEqual(
            result.selector_details.get("curated_name_table"), "land-flow-classes"
        )

    def test_a_water_row_is_placed_under_the_prepared_name(self):
        """The name arrives spelled `Water, unspecified natural origin/kg` --
        SimaPro's habit of writing the unit into the name -- and the table is
        keyed on the plain spelling, so the join has to happen after
        preparation or the entry is missed.  The issue's own case."""
        result = self.matcher.match(
            FlowQuery(
                name="Water, unspecified natural origin/kg",
                context=["Raw", "in water"],
                unit="kg",
                cas="7732-18-5",
                simapro_origin=True,
            )
        )
        self.assertTrue(result.matched)
        self.assertEqual(result.basis, "material")
        self.assertEqual(result.basis_value, "water")
        self.assertEqual(
            result.selector_details.get("curated_name_table"), "water-flow-materials"
        )

    def test_a_stated_cas_is_not_overridden_across_a_compartment(self):
        """A lead discharge whose row happens to be named `Water, lake` -- the
        regression the boundary rule exists for.  The table's entry lives in a
        resource compartment; the caller resolved to an emission compartment;
        before the rule, the whole-table rung filled `lake_water`, the material
        branch found no lake water among river emissions, and the row came back
        unmatched with the stated CAS never consulted."""
        result = self.matcher.match(
            FlowQuery(
                name="Water, lake",
                context=["Emissions to water", "river"],
                unit="kg",
                cas="7439-92-1",
                simapro_origin=True,
            )
        )
        self.assertTrue(result.matched)
        self.assertEqual(result.basis, "cas")
        self.assertNotIn("curated_name_table", result.selector_details)

    def test_an_explicit_value_from_the_caller_wins(self):
        """A caller who says `material="lake_water"` knows something the table
        does not, and the table's `water` for this name must not overrule
        them."""
        result = self.matcher.match(
            FlowQuery(
                name="Water, unspecified natural origin",
                context=["Raw", "in water"],
                unit="m3",
                material="lake_water",
            )
        )
        self.assertTrue(result.matched)
        self.assertEqual(result.basis, "material")
        self.assertEqual(result.basis_value, "lake_water")
        self.assertNotIn("curated_name_table", result.selector_details)


if __name__ == "__main__":
    unittest.main()
