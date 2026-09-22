"""Every particle size window is a measurement, and the two files agree it is.

`particulate-size-classes.json` says *which cut*. `aggregate-measurements.json`
says *not a substance* — a quantity fixed by the procedure that produces it,
typed `brightway:AggregateMeasurement` rather than by the chemistry rules.
Neither is a substitute for the other, and both have to be true of the same
seven flows.

They are two files, so they can drift, and the drift has a direction. Adding a
window means adding a label; forgetting to claim that label in the measurements
file leaves the new object to the chemistry rules, which have nothing to go on —
no CAS, no formula, no structure — and fall through to rule 8, which reads a
label saying `unspecified` and answers `MoleculeGroupingClass`.

That is not a hypothetical. It is what `aggregate-measurements.json` records
having happened to `Particulates, Unspecified` and to `Suspended Solids,
Unspecified` before it existed, and the size-unstated total this taxonomy
publishes is called `Particles (unspecified size)` — so the same rule would
reach for the same wrong answer under a new name.

Hence this test rather than a comment.
"""

import unittest

from brightway_flows.domain.aggregate_measurements import (
    measurement_for_name,
)
from brightway_flows.domain.particulate_size import size_classes


class EverySizeWindowIsClaimedAsAMeasurementTestCase(unittest.TestCase):
    def test_each_published_label_resolves_to_a_measurement(self):
        for identifier, size in size_classes().items():
            with self.subTest(identifier):
                found = measurement_for_name(size.label)
                self.assertIsNotNone(
                    found,
                    f"{size.label!r} is a size window this list publishes and "
                    "no entry in aggregate-measurements.json claims it, so it "
                    "will be typed by the chemistry rules instead",
                )

    def test_they_all_resolve_to_the_same_entry(self):
        """One quantity cut at different sizes, so one entry claims all seven."""
        entries = {
            measurement_for_name(size.label).id  # type: ignore[union-attr]
            for size in size_classes().values()
        }
        self.assertEqual(entries, {"particulate_matter"})

    def test_the_size_unstated_total_is_claimed_by_name(self):
        """The one whose label would otherwise answer rule 8.

        `Particles (unspecified size)` contains the word the label rule reads.
        Being claimed here is what stops it being published as a class of
        molecules, which is what the size-unstated rows were before this
        taxonomy existed.
        """
        found = measurement_for_name(size_classes()["unsized"].label)
        assert found is not None
        self.assertEqual(found.id, "particulate_matter")

    def test_the_measurement_entry_claims_no_label_the_scheme_dropped(self):
        """Drift in the other direction: a name left behind by a rename.

        A label the measurements file claims and the scheme no longer publishes
        is not an error the build would notice — the entry simply never matches
        — so it is caught here instead.
        """
        from brightway_flows.domain.aggregate_measurements import (
            aggregate_measurements,
        )
        from brightway_flows.domain.labels import canonical_label_value

        entry = next(
            m for m in aggregate_measurements() if m.id == "particulate_matter"
        )
        published = {
            canonical_label_value(size.label) for size in size_classes().values()
        }
        orphaned = [
            name
            for name in entry.names
            if canonical_label_value(name) not in published
        ]
        self.assertEqual(
            orphaned, [],
            "aggregate-measurements.json claims these names and "
            "particulate-size-classes.json no longer publishes them",
        )


if __name__ == "__main__":
    unittest.main()
