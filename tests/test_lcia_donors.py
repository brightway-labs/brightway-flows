"""A signed ion takes its element's published number in the same context, and
nothing else happens.

Zinc is characterised in water and air by Stepwise; the zinc ion has flows in
both and nobody states anything for it.  The signed entry puts zinc's water
number on the ion's water flow and zinc's air number on its air flow, as
`adopted`, each naming zinc's flow.  What the pass declines to do is the half
that matters: it never overwrites, never copies a carried or adopted number,
never touches a recipient the publisher characterised, never crosses a unit,
and reads only the entries that say the number is the donor's (#197).
"""

from __future__ import annotations

import unittest
from dataclasses import dataclass

from brightway_flows.lcia.adoptions import (
    Donor,
    FactorAdoption,
    NumberFrom,
    Relationship,
    Verdict,
)
from brightway_flows.lcia.donors import ADOPTED, adopt_donor_numbers

CTX = "https://vocab.brightway.one/flow-contexts/"
WATER = CTX + "envi-wate-unkn"
AIR = CTX + "envi-air-unkn"
RIVER = CTX + "envi-wate-rive"
ZINC = "fo-zinc"
ION = "fo-zinc-ion"
SLUG = "human-toxicity-non-carcinogens"
OTHER_SLUG = "ecotoxicity-aquatic"
PUBLISHER = "2.-0 LCA consultants"


@dataclass(frozen=True)
class FakeFactor:
    amount: float
    geography: str | None = None


@dataclass
class FakeRow:
    elementary_flow_uuid: str
    factor: FakeFactor
    derivation: str | None = "sole"
    source_flow_uuid: str | None = None
    also_stated: float | None = None


@dataclass(frozen=True)
class FakeImplementation:
    name: str


def _entry(**overrides) -> FactorAdoption:
    fields = dict(
        flow_object_id=ION,
        substance="Zinc(2+)",
        relationship=Relationship.ION_OF,
        verdict=Verdict.ADOPT,
        categories=frozenset({SLUG}),
        donor=Donor(flow_object_id=ZINC, substance="Zinc"),
        comment="signed",
        implemented_by=frozenset({PUBLISHER}),
        number_from=NumberFrom.DONOR,
    )
    fields.update(overrides)
    return FactorAdoption(**fields)


def _flows(*rows, deprecated=(), units=None):
    """(uuid, substance, context) rows, all in kilograms unless *units* says."""
    units = units or {}
    return {
        uuid: {
            "flow_object_id": substance,
            "context_iri": context,
            "unit": units.get(uuid, "kg"),
            "deprecated": uuid in deprecated,
        }
        for uuid, substance, context in rows
    }


FLOWS = _flows(
    ("zn-water", ZINC, WATER),
    ("zn-air", ZINC, AIR),
    ("ion-water", ION, WATER),
    ("ion-air", ION, AIR),
    ("ion-river", ION, RIVER),
)


def _stated(*keys):
    """What the one publisher states, keyed the way `derive` keys it."""
    return {FakeImplementation(PUBLISHER): {key: object() for key in keys}}


def _adopt(published, *, entries=None, flows=FLOWS, stated=None, slug=SLUG):
    entries = [_entry()] if entries is None else entries
    return adopt_donor_numbers(
        published,
        adoptions={entry.flow_object_id: entry for entry in entries},
        slug_of=lambda row: slug,
        flows=flows,
        stated=stated if stated is not None else _stated(("zn-water", slug, ""), ("zn-air", slug, "")),
    )


def _adopted(rows):
    """The rows the pass added, by recipient flow.  A donor row that arrived
    already marked `adopted` is a fixture, not an outcome."""
    return {
        row.elementary_flow_uuid: row
        for row in rows
        if row.derivation == ADOPTED and row.source_flow_uuid is not None
    }


class AdoptingTest(unittest.TestCase):
    def test_the_donors_number_lands_in_the_same_context(self):
        published = [FakeRow("zn-water", FakeFactor(133.39)), FakeRow("zn-air", FakeFactor(92.75))]
        out, counts = _adopt(published)
        adopted = _adopted(out)
        self.assertEqual(set(adopted), {"ion-water", "ion-air"})
        self.assertEqual(adopted["ion-water"].factor.amount, 133.39)
        self.assertEqual(adopted["ion-water"].source_flow_uuid, "zn-water")
        self.assertEqual(adopted["ion-air"].factor.amount, 92.75)
        self.assertEqual(adopted["ion-air"].source_flow_uuid, "zn-air")
        self.assertEqual(counts["adopted"], 2)
        self.assertEqual(counts["adopted_ion-of"], 2)
        # The two donor rows are still there, untouched.
        self.assertEqual(len(out), 4)

    def test_the_river_is_left_to_the_convention(self):
        """Zinc has no river flow; the ion's river is a context question, asked
        of the ion's own adopted water row by the pass that runs next."""
        out, _ = _adopt([FakeRow("zn-water", FakeFactor(133.39))])
        self.assertNotIn("ion-river", _adopted(out))

    def test_a_stated_zero_is_a_number(self):
        out, counts = _adopt([FakeRow("zn-water", FakeFactor(0.0))])
        self.assertEqual(_adopted(out)["ion-water"].factor.amount, 0.0)
        self.assertEqual(counts["adopted"], 1)

    def test_geography_travels_with_the_number(self):
        published = [FakeRow("zn-water", FakeFactor(1.0)), FakeRow("zn-water", FakeFactor(2.0, "CH"))]
        out, _ = _adopt(published, stated=_stated(("zn-water", SLUG, ""), ("zn-water", SLUG, "CH")))
        landed = [
            (row.factor.geography, row.factor.amount)
            for row in out
            if row.elementary_flow_uuid == "ion-water" and row.derivation == ADOPTED
        ]
        self.assertEqual(set(landed), {(None, 1.0), ("CH", 2.0)})

    def test_nothing_the_donor_said_about_others_travels(self):
        out, _ = _adopt([FakeRow("zn-water", FakeFactor(1.0), also_stated=1.0)])
        self.assertIsNone(_adopted(out)["ion-water"].also_stated)


class RefusingTest(unittest.TestCase):
    def test_a_recipient_the_publisher_characterised_is_refused_whole(self):
        """Chromium: Stepwise names the trivalent ion and gives it no ecotoxicity
        number.  An entry for it publishes nothing, in every category."""
        stated = _stated(("zn-water", SLUG, ""), ("ion-air", OTHER_SLUG, ""))
        out, counts = _adopt([FakeRow("zn-water", FakeFactor(1.0))], stated=stated)
        self.assertEqual(_adopted(out), {})
        self.assertEqual(counts["recipient_stated_by_a_publisher"], 1)

    def test_a_published_triple_is_never_overwritten(self):
        published = [FakeRow("zn-water", FakeFactor(1.0)), FakeRow("ion-water", FakeFactor(99.0), derivation="ruled")]
        out, counts = _adopt(published)
        self.assertEqual(_adopted(out), {})
        self.assertEqual(counts["already_published"], 1)
        self.assertEqual(next(r for r in out if r.elementary_flow_uuid == "ion-water").factor.amount, 99.0)

    def test_a_carried_or_adopted_donor_row_is_not_copied(self):
        for derivation in ("carried", "adopted"):
            with self.subTest(derivation):
                out, counts = _adopt([FakeRow("zn-water", FakeFactor(1.0), derivation=derivation)])
                self.assertEqual(_adopted(out), {})
                self.assertEqual(counts.get("adopted", 0), 0)

    def test_a_restated_or_refined_donor_row_is_a_statement(self):
        for derivation in ("restated", "refined", "moved", "agreed", "ruled"):
            with self.subTest(derivation):
                out, _ = _adopt([FakeRow("zn-water", FakeFactor(1.0), derivation=derivation)])
                self.assertIn("ion-water", _adopted(out))

    def test_a_category_the_entry_does_not_name_is_not_copied(self):
        out, counts = _adopt([FakeRow("zn-water", FakeFactor(1.0))], slug=OTHER_SLUG,
                             stated=_stated(("zn-water", OTHER_SLUG, "")))
        self.assertEqual(_adopted(out), {})
        self.assertEqual(counts.get("adopted", 0), 0)

    def test_a_donor_row_somebody_else_stated_is_not_copied(self):
        stated = {FakeImplementation("Somebody else"): {("zn-water", SLUG, ""): object()}}
        out, _ = _adopt([FakeRow("zn-water", FakeFactor(1.0))], stated=stated)
        self.assertEqual(_adopted(out), {})

    def test_a_unit_crossing_is_refused(self):
        flows = _flows(("zn-water", ZINC, WATER), ("ion-water", ION, WATER), units={"ion-water": "g"})
        out, counts = _adopt([FakeRow("zn-water", FakeFactor(1.0))], flows=flows)
        self.assertEqual(_adopted(out), {})
        self.assertEqual(counts["unit_differs"], 1)

    def test_a_withdrawn_recipient_flow_is_not_filled(self):
        flows = _flows(("zn-water", ZINC, WATER), ("ion-water", ION, WATER), deprecated={"ion-water"})
        out, _ = _adopt([FakeRow("zn-water", FakeFactor(1.0))], flows=flows)
        self.assertEqual(_adopted(out), {})

    def test_a_decline_publishes_nothing_and_is_counted(self):
        out, counts = _adopt([FakeRow("zn-water", FakeFactor(1.0))], entries=[_entry(verdict=Verdict.DECLINE)])
        self.assertEqual(_adopted(out), {})
        self.assertEqual(counts["declined"], 1)

    def test_an_entry_answering_stated_rows_is_not_read_here(self):
        out, counts = _adopt([FakeRow("zn-water", FakeFactor(1.0))],
                             entries=[_entry(number_from=NumberFrom.TRANSCRIPTION)])
        self.assertEqual(_adopted(out), {})
        self.assertEqual(counts, {})

    def test_no_entries_means_nothing_happens(self):
        published = [FakeRow("zn-water", FakeFactor(1.0))]
        out, counts = _adopt(published, entries=[])
        self.assertIs(out, published)
        self.assertEqual(counts, {})


if __name__ == "__main__":
    unittest.main()
