"""A row's curated land class decides its context, not the vendor's filing.

#193: AGRIBALYSE files seven land rows under `Resources / in ground` and
`Resources / in water`, and on the build of 1 September 2026 the compartment
decided -- rows placed on the right substance by `basis=land_class` were
published as ground and water resources, six of them a factor-less second
flow for a substance whose Land Use flow carries 213 factors.  The class is
now the most specific context rule, ahead of the per-flow and name-prefix
rules, so the context and the class derive from one statement -- which is
what `LandUse.land_use_class`'s own docstring always demanded.

Real rows against the real curated tables, because the defect lived in the
join between them: every uuid here is in `land-flow-classes.json` and every
compartment is one the vendor genuinely used.
"""

from __future__ import annotations

import unittest

from brightway_flows.domain.context import Context, Dimension, LandUseClass
from brightway_flows.domain.context_registry import iri_for_context
from brightway_flows.merge.contexts import _load_context_expectation_indexes
from brightway_flows.sources import resolve_source_list

OCCUPATION_IRI = iri_for_context(
    Context(dimension=Dimension.LAND_USE, land_use=LandUseClass.OCCUPATION)
)
TRANSFORMATION_IRI = iri_for_context(
    Context(dimension=Dimension.LAND_USE, land_use=LandUseClass.TRANSFORMATION)
)

#: The seven misfiled rows of #193: uuid -> (name, vendor compartment, the
#: direction's IRI).  uuids from the extracted list; each is a curated row of
#: `land-flow-classes.json`, which is what entitles the rule to speak.
MISFILED = {
    "57b50b48-817e-589c-bb16-cbac987d1bc8": (
        "Occupation, mineral extraction site", ["Resources", "in water"], OCCUPATION_IRI,
    ),
    "58cec0b2-317e-5ed3-ab52-03c8087163a4": (
        "Occupation, sea and ocean", ["Resources", "in water"], OCCUPATION_IRI,
    ),
    "bf354371-40d2-5f4d-87ca-6e5c5f49facc": (
        "Transformation, from agriculture", ["Resources", "in ground"], TRANSFORMATION_IRI,
    ),
    "cbc63f21-df8c-5388-82f7-c6cbb15a3400": (
        "Transformation, from forest, unspecified", ["Resources", "in water"], TRANSFORMATION_IRI,
    ),
    "02c1c36c-eaef-56b0-9b46-9ed0b276838b": (
        "Transformation, to annual crop", ["Resources", "in ground"], TRANSFORMATION_IRI,
    ),
    "8dab19f5-c588-5403-85bc-e3493087561d": (
        "Transformation, to mineral extraction site", ["Resources", "in water"], TRANSFORMATION_IRI,
    ),
    "31b7cffb-46e5-51d9-be84-a8f9a7314da1": (
        "Transformation, to permanent crop", ["Resources", "in ground"], TRANSFORMATION_IRI,
    ),
}


def _expectations():
    source = resolve_source_list("agribalyse-3.2")
    expectations, _renderings = _load_context_expectation_indexes(source)
    return expectations


class LandClassDecidesTestCase(unittest.TestCase):
    def setUp(self) -> None:
        try:
            self.expectations = _expectations()
        except Exception as error:  # noqa: BLE001 - a missing vocabulary skips
            raise unittest.SkipTest(str(error))

    def test_a_misfiled_land_row_lands_in_its_direction(self):
        for uuid, (name, compartment, iri) in sorted(MISFILED.items()):
            with self.subTest(name=name, compartment=compartment):
                self.assertEqual(
                    self.expectations.resolve(uuid, compartment, name), iri
                )

    def test_the_correctly_filed_twin_agrees(self):
        """The same rows under `Resources / land` resolve identically, so the
        rule changes nothing for the 194 rows that were already right."""
        for uuid, (name, _compartment, iri) in sorted(MISFILED.items()):
            with self.subTest(name=name):
                self.assertEqual(
                    self.expectations.resolve(uuid, ["Resources", "land"], name), iri
                )

    def test_a_row_with_no_land_class_is_untouched(self):
        """The other half: a water intake filed beside the land rows resolves
        by the rules that always placed it, because the class table has no
        row for it and the rule asks the table, never the name."""
        resolved = self.expectations.resolve(
            "no-such-uuid", ["Resources", "in water"], "Water, river"
        )
        self.assertIsNotNone(resolved)
        self.assertNotIn("land", str(resolved).rsplit("/", 1)[-1])


class GuardTestCase(unittest.TestCase):
    """`report_land_classes_out_of_place` says what it looked at, even when
    it finds nothing -- an absent stat reads as a stage that did not run."""

    def test_an_empty_merge_reports_zeroes_and_no_items(self):
        from brightway_flows.merge.places import (
            report_land_classes_out_of_place,
        )
        from brightway_flows.merge.state import MergeAccumulator

        counts, items = report_land_classes_out_of_place(
            accumulator=MergeAccumulator(), labels_by_object={}
        )
        self.assertEqual(counts["land_class_flows"], 0)
        self.assertEqual(counts["land_classes_out_of_place"], 0)
        self.assertEqual(items, [])


if __name__ == "__main__":
    unittest.main()
