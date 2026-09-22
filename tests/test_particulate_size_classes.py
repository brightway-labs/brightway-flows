"""The particle size vocabulary: its windows and its nesting.

A size class is a pair of aerodynamic-diameter bounds, and the pair is the
identity — which is the whole of #153. These tests are what keep that true:
that no two classes state one window, that every parent really does contain its
child, and that the six classes EF 3.1 already publishes keep the flow object
identifiers they have.

This vocabulary is ours and cites nothing, so there are no anchors to check —
see `plans/particulate-taxonomy.md` §2 for why. What replaces an authority is
the arithmetic: `check_nesting` runs on every load, and the cases below are its
failure modes stated as tests.
"""

import unittest
from dataclasses import replace

from brightway_flows.domain.particulate_size import (
    ParticulateSizeError,
    SizeClass,
    broader_chain,
    check_labels,
    check_nesting,
    class_by_flow_object,
    flow_object_basis_for,
    size_class,
    size_classes,
)


class TheSevenWindowsTestCase(unittest.TestCase):
    """Seventeen spellings across five source lists, seven windows."""

    #: id -> (lower, upper) in micrometres, `None` meaning open on that side.
    #: Spelled out rather than derived, because deriving them from the file
    #: would make this assert that the file equals itself.
    WINDOWS = {
        "unsized": (None, None),
        "pm10": (None, 10.0),
        "pm2_5": (None, 2.5),
        "pm0_2": (None, 0.2),
        "pm0_2_to_pm2_5": (0.2, 2.5),
        "pm2_5_to_pm10": (2.5, 10.0),
        "above_pm10": (10.0, None),
    }

    def test_the_scheme_is_exactly_these_seven(self):
        self.assertEqual(sorted(size_classes()), sorted(self.WINDOWS))

    def test_each_states_the_window_it_should(self):
        for identifier, (lower, upper) in self.WINDOWS.items():
            with self.subTest(identifier):
                found = size_class(identifier)
                assert found is not None
                self.assertEqual((found.lower_um, found.upper_um), (lower, upper))

    def test_only_the_root_states_no_cut(self):
        """`unsized` is the absence of a statement, and nothing else is.

        A row that did not say where the sample was cut has not said the cut was
        everywhere, so this class is not a superset of PM10 and `window()`
        returns None rather than `(0, inf)` — a caller has to decide what to do
        about a row that said nothing instead of being handed a number.
        """
        unstated = [v.id for v in size_classes().values() if not v.states_a_cut]
        self.assertEqual(unstated, ["unsized"])
        self.assertIsNone(size_classes()["unsized"].window())

    def test_the_windows_read_as_closed_pairs(self):
        self.assertEqual(size_classes()["pm10"].window(), (0.0, 10.0))
        self.assertEqual(size_classes()["pm2_5_to_pm10"].window(), (2.5, 10.0))
        self.assertEqual(size_classes()["above_pm10"].window(), (10.0, float("inf")))

    def test_the_selection_is_derived_from_the_bounds(self):
        selections = {v.id: v.selection for v in size_classes().values()}
        self.assertEqual(
            selections,
            {
                "unsized": "unstated",
                "pm10": "below",
                "pm2_5": "below",
                "pm0_2": "below",
                "pm0_2_to_pm2_5": "between",
                "pm2_5_to_pm10": "between",
                "above_pm10": "above",
            },
        )


class TheNestingFollowsTheBoundsTestCase(unittest.TestCase):
    """The check runs on every load, so these are its cases stated as tests."""

    def test_the_shipped_scheme_passes(self):
        check_nesting(size_classes())

    def test_the_coarse_band_is_under_pm10_and_not_under_pm2_5(self):
        """Both readings mention 2.5, and only the bounds tell them apart.

        This is the mapping #153 is about: 2.5–10 µm is inside 0–10 and is not
        inside 0–2.5, so the coarse fraction cannot reach PM2.5 — nor, once the
        window is the identity, PM10.
        """
        self.assertEqual(size_classes()["pm2_5_to_pm10"].broader, "pm10")

    def test_above_pm10_is_not_inside_pm10(self):
        """Spelled out of PM10, and therefore not part of it."""
        self.assertEqual(size_classes()["above_pm10"].broader, "unsized")

    def test_the_chain_from_the_finest_cut_reaches_the_root(self):
        self.assertEqual(
            broader_chain("pm0_2"), ["pm0_2", "pm2_5", "pm10", "unsized"]
        )

    def _scheme(self, **edits: SizeClass) -> dict[str, SizeClass]:
        scheme = dict(size_classes())
        scheme.update(edits)
        return scheme

    def test_two_classes_stating_one_window_is_refused(self):
        """A second PM10 under another name is the collapse this scheme stops."""
        twin = replace(size_classes()["pm2_5_to_pm10"], lower_um=None, upper_um=10.0)
        with self.assertRaises(ParticulateSizeError) as caught:
            check_nesting(self._scheme(pm2_5_to_pm10=twin))
        self.assertIn("both state the window", str(caught.exception))

    def test_a_parent_that_does_not_contain_the_child_is_refused(self):
        misfiled = replace(size_classes()["pm2_5_to_pm10"], broader="pm2_5")
        with self.assertRaises(ParticulateSizeError) as caught:
            check_nesting(self._scheme(pm2_5_to_pm10=misfiled))
        self.assertIn("smallest class containing", str(caught.exception))

    def test_a_parent_that_is_not_the_nearest_container_is_refused(self):
        """PM0.2 hung off PM10 skips PM2.5, which also contains it."""
        skipped = replace(size_classes()["pm0_2"], broader="pm10")
        with self.assertRaises(ParticulateSizeError) as caught:
            check_nesting(self._scheme(pm0_2=skipped))
        self.assertIn("'pm2_5'", str(caught.exception))

    def test_a_contained_class_may_not_hang_off_the_root(self):
        detached = replace(size_classes()["pm2_5"], broader="unsized")
        with self.assertRaises(ParticulateSizeError):
            check_nesting(self._scheme(pm2_5=detached))


class NothingThatExistsChurnsTestCase(unittest.TestCase):
    """The six published classes keep the identifiers they already have.

    Measured off the build of 25 August 2026, run `20260825T0605411116990000`,
    revision `b03c940b`. Every one of the six is minted today from its
    lowercased name, so the scheme declares that basis rather than a new one:
    giving the window a field is not a reason for the largest particulate flow
    objects in the list to change identity.

    Only `unsized` is new, and it takes a basis of its own because it is not any
    of the four flow objects it replaces — it is the class those four were
    spellings of.
    """

    PUBLISHED = {
        "pm0_2": ("name:particles (pm0.2)", "fo-bc028c1c45f2ada6"),
        "pm0_2_to_pm2_5": ("name:particles (pm0.2 - pm2.5)", "fo-23325a14efc92ca6"),
        "pm2_5": ("name:particles (pm2.5)", "fo-68bfa13f441778cb"),
        "pm2_5_to_pm10": ("name:particles (pm2.5 - pm10)", "fo-ae1315a262379c68"),
        "pm10": ("name:particles (pm10)", "fo-4619792929f057e6"),
        "above_pm10": ("name:particles (> pm10)", "fo-a30bea921eacba3f"),
    }

    def test_each_keeps_its_basis_and_its_identifier(self):
        for identifier, (basis, object_id) in self.PUBLISHED.items():
            with self.subTest(identifier):
                found = size_class(identifier)
                assert found is not None
                self.assertEqual(found.flow_object_basis, basis)
                self.assertEqual(found.flow_object_id, object_id)
                self.assertEqual(flow_object_basis_for(identifier), basis)

    def test_the_unsized_total_is_the_only_new_object(self):
        unsized = size_classes()["unsized"]
        self.assertEqual(unsized.flow_object_basis, "particulate:unsized")
        self.assertNotIn(
            unsized.flow_object_id, {oid for _, oid in self.PUBLISHED.values()}
        )

    def test_every_class_mints_an_object_and_the_reverse_index_is_whole(self):
        """Unlike the material taxonomy, no concept here exists only to group."""
        self.assertEqual(len(class_by_flow_object()), len(size_classes()))
        for identifier, size in size_classes().items():
            with self.subTest(identifier):
                self.assertIs(class_by_flow_object()[size.flow_object_id], size)


class EveryClassIsDocumentedTestCase(unittest.TestCase):
    def test_each_carries_a_definition_and_a_reason(self):
        for identifier, value in size_classes().items():
            with self.subTest(identifier):
                self.assertTrue(value.definition.strip())
                self.assertTrue(value.comment.strip())
                self.assertTrue(value.label.strip())

    def test_no_two_classes_share_a_label(self):
        labels = [v.label for v in size_classes().values()]
        self.assertEqual(len(labels), len(set(labels)))


class EveryWindowHasItsParticulatesSpellingTestCase(unittest.TestCase):
    """The alternative labels are a promise (`plans/particle-family.md` §2):
    a reader searching for the ecoinvent-2 spelling finds the window whichever
    vendor's rows reached it, and no spelling answers for two windows."""

    def _scheme(self, **overrides):
        classes = dict(size_classes())
        classes.update(overrides)
        return classes

    def test_each_window_states_at_least_one(self):
        for identifier, value in size_classes().items():
            with self.subTest(identifier):
                self.assertTrue(value.alt_labels)
                for label in value.alt_labels:
                    self.assertTrue(label.lower().startswith("particulates"))

    def test_the_vendors_own_spellings_are_the_ones_promised(self):
        """The five spellings the lists ship, and the two coined on their
        pattern for the windows nobody ships."""
        by_id = {k: v.alt_labels for k, v in size_classes().items()}
        self.assertEqual(by_id["pm10"], ("Particulates, < 10 um",))
        self.assertEqual(by_id["pm2_5"], ("Particulates, < 2.5 um",))
        self.assertEqual(by_id["pm2_5_to_pm10"], ("Particulates, > 2.5 um, and < 10um",))
        self.assertEqual(by_id["above_pm10"], ("Particulates, > 10 um",))
        self.assertEqual(by_id["unsized"], ("Particulates, unspecified", "Particulates"))
        self.assertEqual(by_id["pm0_2"], ("Particulates, < 0.2 um",))
        self.assertEqual(by_id["pm0_2_to_pm2_5"], ("Particulates, > 0.2 um, and < 2.5 um",))

    def test_a_window_with_no_spelling_is_refused(self):
        bare = replace(size_classes()["pm10"], alt_labels=())
        with self.assertRaises(ParticulateSizeError) as caught:
            check_labels(self._scheme(pm10=bare))
        self.assertIn("no `Particulates` spelling", str(caught.exception))

    def test_a_spelling_two_windows_state_is_refused(self):
        """`Particulates, < 10 um` on the coarse band as well would make a
        search answer twice, which is the collapse the scheme stops."""
        twice = replace(
            size_classes()["pm2_5_to_pm10"], alt_labels=("Particulates, < 10 um",)
        )
        with self.assertRaises(ParticulateSizeError) as caught:
            check_labels(self._scheme(pm2_5_to_pm10=twice))
        self.assertIn("is a name of both", str(caught.exception))

    def test_a_spelling_that_is_another_windows_label_is_refused(self):
        stolen = replace(size_classes()["above_pm10"], alt_labels=("Particles (PM10)",))
        with self.assertRaises(ParticulateSizeError):
            check_labels(self._scheme(above_pm10=stolen))

    def test_the_shipped_scheme_passes(self):
        check_labels(dict(size_classes()))

    def test_every_window_says_where_its_bound_is_read_from(self):
        """A Directive for the two regulated cuts, construction for the
        bands, and `none stated` for the total (plans/particle-family.md §1)."""
        by_id = {k: v.definition_source for k, v in size_classes().items()}
        self.assertIn("2008/50/EC", by_id["pm10"])
        self.assertIn("2008/50/EC", by_id["pm2_5"])
        for identifier in ("pm0_2", "pm0_2_to_pm2_5", "pm2_5_to_pm10", "above_pm10"):
            self.assertIn("By construction", by_id[identifier])
        self.assertIn("None stated", by_id["unsized"])

    def test_a_window_without_a_definition_source_is_refused(self):
        bare = replace(size_classes()["pm10"], definition_source="")
        with self.assertRaises(ParticulateSizeError) as caught:
            check_labels(self._scheme(pm10=bare))
        self.assertIn("definition source", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
