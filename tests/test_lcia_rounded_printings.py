"""A rounded printing is refined, and only where the document says it is one.

#342: AR6 states CFC-11's hundred-year global warming potential as 6226 in
Chapter 7's Table 7.15 and as 6230 in the supplementary Table 7.SM.7, which
rounds it.  The JRC's EF 3.1 carries the supplement's number and ecoinvent's
implementation carries the chapter's; where both speak the merge already keeps
the precise one, and where only the JRC has a flow the rounded one went out
unopposed, leaving one substance with two numbers.

Both halves are tested, and the second is the one that matters.  Rewriting a
number is easy; what stops this growing into "publish whichever number is
prettier" is the set of cases where it declines to fire -- a row publishing some
other amount, a build whose implementations have moved, and an implementation
arriving or going silent since the row was written.
"""

from __future__ import annotations

import json
import unittest
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory

from brightway_flows.domain.lcia.crosswalk import ef_method
from brightway_flows.lcia.misattributions import stated_by_substance
from brightway_flows.lcia.precision import (
    REFINED,
    RoundedPrinting,
    RoundedPrintingError,
    load_rounded_printings,
    refine_factors,
)

SUBSTANCE = "fo-the-halocarbon"
SLUG = "climate-change"
JRC = "European Commission — JRC"
ECOINVENT = "ecoinvent Centre"


@dataclass(frozen=True)
class FakeFactor:
    amount: float


@dataclass(frozen=True)
class FakeRow:
    """Enough of a `MatchedFactor` for the refiner: a flow, a number, a derivation."""

    elementary_flow_uuid: str
    factor: FakeFactor
    derivation: str | None = None


FLOWS = {
    "cruise-height": {"flow_object_id": SUBSTANCE},
    "unspecified-air": {"flow_object_id": SUBSTANCE},
    "another-substance": {"flow_object_id": "fo-something-else"},
}


def printing(**overrides) -> RoundedPrinting:
    fields = {
        "category_slug": SLUG,
        "flow_object_id": SUBSTANCE,
        "implemented_by": JRC,
        "prints": 6230.0,
        "states": 6226.0,
        "primary_source": "AR6 Table 7.15",
        "stated_about": {JRC: (6230.0,), ECOINVENT: (6226.0,)},
        "comment": "why",
    }
    fields.update(overrides)
    return RoundedPrinting(**fields)


def refine(rows, *, printings=None, stated=None):
    one = printings if printings is not None else [printing()]
    return refine_factors(
        list(rows),
        printings={row.key: row for row in one},
        slug_of=lambda _row: SLUG,
        flows=FLOWS,
        stated=stated
        if stated is not None
        else {(SLUG, SUBSTANCE): {JRC: (6230.0,), ECOINVENT: (6226.0,)}},
    )


class TheNumberIsRefined(unittest.TestCase):
    """The published row carries the value the source states."""

    def test_the_rounded_amount_becomes_the_precise_one(self):
        rows, counts = refine(
            [FakeRow("cruise-height", FakeFactor(6230.0), "sole")]
        )
        self.assertEqual(rows[0].factor.amount, 6226.0)
        self.assertEqual(counts, {"refined": 1})

    def test_a_refined_factor_says_it_was_refined(self):
        rows, _ = refine([FakeRow("cruise-height", FakeFactor(6230.0), "sole")])
        self.assertEqual(rows[0].derivation, REFINED)

    def test_the_flow_it_is_on_does_not_move(self):
        rows, _ = refine([FakeRow("cruise-height", FakeFactor(6230.0), "sole")])
        self.assertEqual(rows[0].elementary_flow_uuid, "cruise-height")

    def test_every_compartment_publishing_the_rounded_number_is_refined(self):
        rows, counts = refine([
            FakeRow("cruise-height", FakeFactor(6230.0), "sole"),
            FakeRow("unspecified-air", FakeFactor(6230.0), "sole"),
        ])
        self.assertEqual([row.factor.amount for row in rows], [6226.0, 6226.0])
        self.assertEqual(counts, {"refined": 2})


class TheNumberIsLeftAlone(unittest.TestCase):
    """Where the row was not written about what is there."""

    def test_a_row_already_carrying_the_precise_value_is_untouched(self):
        """The compartments where both implementations spoke.

        They carry 6226 as `agreed`, which is a record of two publishers
        agreeing; rewriting it would trade that for a record of this file
        acting, and the number would not change.
        """
        rows, counts = refine(
            [FakeRow("unspecified-air", FakeFactor(6226.0), "agreed")]
        )
        self.assertEqual(rows[0].derivation, "agreed")
        self.assertEqual(counts, {})

    def test_some_other_amount_is_untouched(self):
        rows, counts = refine([FakeRow("cruise-height", FakeFactor(9999.0), "sole")])
        self.assertEqual(rows[0].factor.amount, 9999.0)
        self.assertEqual(counts, {})

    def test_another_substance_is_untouched(self):
        rows, counts = refine(
            [FakeRow("another-substance", FakeFactor(6230.0), "sole")]
        )
        self.assertEqual(rows[0].derivation, "sole")
        self.assertEqual(counts, {})

    def test_an_implementation_stating_a_number_the_row_never_saw_stops_it(self):
        rows, counts = refine(
            [FakeRow("cruise-height", FakeFactor(6230.0), "sole")],
            stated={(SLUG, SUBSTANCE): {JRC: (6230.0,), ECOINVENT: (6100.0,)}},
        )
        self.assertEqual(rows[0].factor.amount, 6230.0)
        self.assertEqual(counts, {"not_about_this_build": 1})

    def test_an_implementation_the_row_never_heard_from_stops_it(self):
        rows, counts = refine(
            [FakeRow("cruise-height", FakeFactor(6230.0), "sole")],
            stated={
                (SLUG, SUBSTANCE): {
                    JRC: (6230.0,),
                    ECOINVENT: (6226.0,),
                    "A third implementation": (6226.0,),
                }
            },
        )
        self.assertEqual(rows[0].factor.amount, 6230.0)
        self.assertEqual(counts, {"not_about_this_build": 1})

    def test_an_implementation_that_has_gone_silent_stops_it(self):
        rows, counts = refine(
            [FakeRow("cruise-height", FakeFactor(6230.0), "sole")],
            stated={(SLUG, SUBSTANCE): {JRC: (6230.0,)}},
        )
        self.assertEqual(rows[0].factor.amount, 6230.0)
        self.assertEqual(counts, {"not_about_this_build": 1})

    def test_no_printings_leaves_the_list_identical(self):
        rows = [FakeRow("cruise-height", FakeFactor(6230.0), "sole")]
        out, counts = refine_factors(
            rows, printings={}, slug_of=lambda _row: SLUG, flows=FLOWS, stated={}
        )
        self.assertIs(out, rows)
        self.assertEqual(counts, {})


class TheFileIsRead(unittest.TestCase):
    """A malformed row is refused rather than skipped."""

    def _write(self, payload) -> Path:
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        path = Path(directory.name) / "printings.json"
        path.write_text(json.dumps(payload))
        return path

    def _one(self, **overrides):
        row = {
            "category_slug": SLUG,
            "flow_object_id": SUBSTANCE,
            "implemented_by": JRC,
            "prints": 6230.0,
            "states": 6226.0,
            "primary_source": "AR6 Table 7.15",
            "stated_about": {JRC: [6230.0], ECOINVENT: [6226.0]},
            "comment": "why",
        }
        row.update(overrides)
        return {"schema_version": 1, "method": "ef", "printings": [row]}

    def test_a_well_formed_file_loads(self):
        printings = load_rounded_printings(self._write(self._one()))
        self.assertEqual(list(printings), [(SLUG, SUBSTANCE)])
        self.assertEqual(printings[(SLUG, SUBSTANCE)].states, 6226.0)

    def test_a_row_with_no_comment_is_refused(self):
        with self.assertRaises(RoundedPrintingError):
            load_rounded_printings(self._write(self._one(comment="")))

    def test_a_row_with_no_source_is_refused(self):
        """The citation is the whole evidence, so a row without one is not one."""
        with self.assertRaises(RoundedPrintingError):
            load_rounded_printings(self._write(self._one(primary_source="")))

    def test_a_row_refining_a_number_to_itself_is_refused(self):
        with self.assertRaises(RoundedPrintingError):
            load_rounded_printings(self._write(self._one(states=6230.0)))

    def test_a_row_with_no_stated_about_is_refused(self):
        with self.assertRaises(RoundedPrintingError):
            load_rounded_printings(self._write(self._one(stated_about={})))

    def test_a_row_whose_own_implementation_is_unrecorded_is_refused(self):
        with self.assertRaises(RoundedPrintingError):
            load_rounded_printings(
                self._write(self._one(stated_about={ECOINVENT: [6226.0]}))
            )

    def test_a_row_refining_a_number_its_implementation_does_not_state_is_refused(self):
        with self.assertRaises(RoundedPrintingError):
            load_rounded_printings(
                self._write(
                    self._one(stated_about={JRC: [1.0], ECOINVENT: [6226.0]})
                )
            )

    def test_two_rows_about_one_substance_and_category_are_refused(self):
        payload = self._one()
        payload["printings"].append(dict(payload["printings"][0]))
        with self.assertRaises(RoundedPrintingError):
            load_rounded_printings(self._write(payload))

    def test_a_wrong_schema_version_is_refused(self):
        payload = self._one()
        payload["schema_version"] = 2
        with self.assertRaises(RoundedPrintingError):
            load_rounded_printings(self._write(payload))

    def test_a_missing_file_is_no_printings_rather_than_an_error(self):
        self.assertEqual(load_rounded_printings(Path("/nowhere.json")), {})


class TheCuratedFileHoldsWhatIssue724Says(unittest.TestCase):
    """The rows shipped in `data/`, which are a claim about two IPCC tables."""

    @classmethod
    def setUpClass(cls):
        cls.printings = load_rounded_printings()

    def test_it_carries_both_substances_in_both_climate_categories(self):
        self.assertEqual(
            {(key[1], key[0]) for key in self.printings},
            {
                ("fo-a40881b1029ff99c", "climate-change"),
                ("fo-a40881b1029ff99c", "climate-change-fossil"),
                ("fo-9a8a2ec4f7948ae5", "climate-change"),
                ("fo-9a8a2ec4f7948ae5", "climate-change-fossil"),
            },
        )

    def test_every_row_refines_the_jrcs_printing(self):
        """Which direction the refinement runs is the claim, not an accident.

        The JRC transcribed the supplement and ecoinvent the chapter; a row
        pointing the other way would be publishing a rounding.
        """
        self.assertEqual(
            {row.implemented_by for row in self.printings.values()}, {JRC}
        )

    def test_the_numbers_are_ar6s_two_printings(self):
        pairs = {(row.prints, row.states) for row in self.printings.values()}
        self.assertEqual(pairs, {(6230.0, 6226.0), (1530.0, 1526.0)})

    def test_every_row_cites_where_the_precise_value_is_printed(self):
        for row in self.printings.values():
            with self.subTest(substance=row.substance, category=row.category):
                self.assertIn("7.15", row.primary_source)

    def test_every_row_states_its_reasoning(self):
        for row in self.printings.values():
            with self.subTest(substance=row.substance, category=row.category):
                self.assertGreater(len(row.comment), 200)

    def test_sulfur_hexafluoride_is_not_here(self):
        """Its two numbers are two lifetimes, not two printings, and it was
        answered by a ruling instead (#342)."""
        self.assertNotIn(
            "fo-21903c3421b5c942",
            {row.flow_object_id for row in self.printings.values()},
        )


class TheStatedIndexIsShared(unittest.TestCase):
    """The refiner reads the same index the mover does, so a row is compared
    against every compartment of a substance rather than one flow's number."""

    def test_it_groups_every_compartment_under_one_substance(self):
        class Matched:
            def __init__(self, amount):
                self.factor = FakeFactor(amount)

        index = stated_by_substance(
            {
                ef_method().reference: {
                    ("cruise-height", SLUG, ""): Matched(6230.0),
                    ("unspecified-air", SLUG, ""): Matched(6230.0),
                }
            },
            flows=FLOWS,
        )
        self.assertEqual(
            index[(SLUG, SUBSTANCE)],
            {ef_method().reference.name: (6230.0, 6230.0)},
        )
        self.assertTrue(printing().covers(stated={JRC: (6230.0, 6230.0),
                                                  ECOINVENT: (6226.0,)}))


if __name__ == "__main__":
    unittest.main()
