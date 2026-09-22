"""The size-window convention is read whole, checked against the scheme, and
carries a number across windows inside one compartment and nowhere else.

The file says which broader window's number a blank particle flow takes.  What
these tests hold it to is the part a reader cannot see: every window it names
is one of the seven, a downward donor list is the recipient's own chain in
``particulate-size-classes.json`` and nothing else, the upward donor list is the
root's direct children, and the decisions of 2 September 2026 are the ones
written down -- the coarse band from PM10, the two windows finer than PM2.5
from PM2.5, the above-ten fraction from the unsized total.

The pass is held to what `carry_across_contexts` is held to: it fills a window
only where nobody spoke, never publishes onto a withdrawn flow, never carries
from a carried factor, and the root takes its children's number only where they
agree.
"""

from __future__ import annotations

import json
import unittest
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory

from brightway_flows.domain.particulate_size import size_classes
from brightway_flows.lcia.context_carry import CarryDirection
from brightway_flows.lcia.size_class_carry import (
    CARRIED,
    SIZE_CLASS_CARRY_RULES_FILEPATH,
    SizeClassCarryRuleError,
    carry_across_size_classes,
    load_size_class_carry_rules,
)

AIR = "https://vocab.brightway.one/flow-contexts/envi-air-unkn"
URBAN = "https://vocab.brightway.one/flow-contexts/envi-air-grle-ur10pesq"
SLUG = "particulate-matter"

OBJECT = {identifier: value.flow_object_id for identifier, value in size_classes().items()}


def _rule(recipient, *donors, comment="because"):
    return {"recipient": recipient, "donors": list(donors), "comment": comment}


def _document(**overrides):
    document = {
        "schema_version": 1,
        "downward": [_rule("pm2_5_to_pm10", "pm10", "unsized")],
        "upward": [_rule("unsized", "pm10", "above_pm10")],
    }
    document.update(overrides)
    return document


class LoadingTest(unittest.TestCase):
    def _load(self, document):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "rules.json"
            path.write_text(json.dumps(document))
            return load_size_class_carry_rules(path)

    def test_a_well_formed_file_reads_as_records(self):
        rules = self._load(_document())
        (down,) = rules.downward
        self.assertEqual(down.direction, CarryDirection.DOWNWARD)
        self.assertEqual(down.recipient.id, "pm2_5_to_pm10")
        self.assertEqual([donor.id for donor in down.donors], ["pm10", "unsized"])
        self.assertEqual(down.rule_id, "downward:pm2_5_to_pm10")
        self.assertEqual(
            [rule.direction for rule in rules.rules],
            [CarryDirection.DOWNWARD, CarryDirection.UPWARD],
        )

    def test_an_unknown_window_is_refused(self):
        with self.assertRaises(SizeClassCarryRuleError):
            self._load(_document(downward=[_rule("pm1", "pm2_5")]))
        with self.assertRaises(SizeClassCarryRuleError):
            self._load(_document(downward=[_rule("pm0_2", "pm1")]))

    def test_a_downward_donor_list_must_be_the_recipients_own_chain(self):
        """The scheme says what contains what; the file may only say how far
        up a blank looks.  PM0.2 hung off PM10 skips PM2.5, and the coarse band
        pointed at PM2.5 is a containment the bounds deny."""
        with self.assertRaises(SizeClassCarryRuleError) as caught:
            self._load(_document(downward=[_rule("pm0_2", "pm10")]))
        self.assertIn("broader windows nearest first", str(caught.exception))
        with self.assertRaises(SizeClassCarryRuleError):
            self._load(_document(downward=[_rule("pm2_5_to_pm10", "pm2_5")]))
        # A prefix of the chain is fine: a blank may look one step up only.
        rules = self._load(_document(downward=[_rule("pm0_2", "pm2_5")]))
        self.assertEqual([d.id for d in rules.downward[0].donors], ["pm2_5"])

    def test_an_upward_donor_list_must_be_the_direct_children(self):
        with self.assertRaises(SizeClassCarryRuleError) as caught:
            self._load(_document(upward=[_rule("unsized", "pm10")]))
        self.assertIn("direct children", str(caught.exception))

    def test_a_recipient_is_not_its_own_donor_and_has_one_rule(self):
        with self.assertRaises(SizeClassCarryRuleError):
            self._load(_document(downward=[_rule("pm10", "pm10")]))
        with self.assertRaises(SizeClassCarryRuleError):
            self._load(_document(downward=[_rule("pm10", "unsized"), _rule("pm10", "unsized")]))

    def test_a_comment_is_required(self):
        with self.assertRaises(SizeClassCarryRuleError):
            self._load(_document(downward=[_rule("pm10", "unsized", comment="")]))

    def test_the_schema_version_is_read(self):
        with self.assertRaises(SizeClassCarryRuleError):
            self._load(_document(schema_version=2))


class TheCuratedFileTest(unittest.TestCase):
    """The decisions of 2 September 2026, as data."""

    @classmethod
    def setUpClass(cls):
        cls.rules = load_size_class_carry_rules()

    def test_it_is_the_shipped_file(self):
        self.assertTrue(SIZE_CLASS_CARRY_RULES_FILEPATH.exists())

    def test_every_sized_window_takes_its_chain_downward(self):
        """Six downward rules -- one per window below the root -- each looking
        all the way up its chain."""
        by_recipient = {rule.recipient.id: [d.id for d in rule.donors] for rule in self.rules.downward}
        self.assertEqual(
            by_recipient,
            {
                "pm0_2": ["pm2_5", "pm10", "unsized"],
                "pm0_2_to_pm2_5": ["pm2_5", "pm10", "unsized"],
                "pm2_5": ["pm10", "unsized"],
                "pm2_5_to_pm10": ["pm10", "unsized"],
                "pm10": ["unsized"],
                "above_pm10": ["unsized"],
            },
        )

    def test_the_root_takes_its_children_upward(self):
        (up,) = self.rules.upward
        self.assertEqual(up.recipient.id, "unsized")
        self.assertEqual(sorted(d.id for d in up.donors), ["above_pm10", "pm10"])


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


def _flows(*triples, deprecated=()):
    """(uuid, window id, context IRI) -> the description the pass reads."""
    return {
        uuid: {
            "flow_object_id": OBJECT[window],
            "context_iri": context,
            "deprecated": uuid in deprecated,
        }
        for uuid, window, context in triples
    }


def _carry(published, flows, stated=None):
    return carry_across_size_classes(
        published,
        rules=load_size_class_carry_rules(),
        slug_of=lambda row: SLUG,
        flows=flows,
        stated=stated or {},
    )


def _carried(rows):
    return {row.elementary_flow_uuid: row for row in rows if row.derivation == CARRIED}


class ThePassTest(unittest.TestCase):
    def test_the_coarse_band_takes_pm10s_number_in_its_own_compartment(self):
        flows = _flows(("pm10-air", "pm10", AIR), ("coarse-air", "pm2_5_to_pm10", AIR),
                       ("pm10-urban", "pm10", URBAN), ("coarse-urban", "pm2_5_to_pm10", URBAN))
        published = [FakeRow("pm10-air", FakeFactor(5.48544e-05)), FakeRow("pm10-urban", FakeFactor(1.89153e-05))]
        out, counts = _carry(published, flows)
        carried = _carried(out)
        self.assertEqual(carried["coarse-air"].factor.amount, 5.48544e-05)
        self.assertEqual(carried["coarse-air"].source_flow_uuid, "pm10-air")
        self.assertEqual(carried["coarse-urban"].factor.amount, 1.89153e-05)
        self.assertEqual(carried["coarse-urban"].source_flow_uuid, "pm10-urban")
        self.assertIsNone(carried["coarse-air"].also_stated)
        self.assertEqual(counts["carried"], 2)
        self.assertEqual(counts["rule_downward:pm2_5_to_pm10"], 2)
        self.assertEqual(len(out), 4)

    def test_nothing_crosses_a_compartment(self):
        """PM10 stated in unspecified air says nothing about the coarse band in
        urban air; that is the compartment convention's business, later."""
        flows = _flows(("pm10-air", "pm10", AIR), ("coarse-urban", "pm2_5_to_pm10", URBAN))
        out, counts = _carry([FakeRow("pm10-air", FakeFactor(1.0))], flows)
        self.assertEqual(_carried(out), {})
        self.assertEqual(counts.get("carried", 0), 0)

    def test_the_finer_windows_take_pm2_5_and_the_second_donor_is_used_where_the_first_is_blank(self):
        flows = _flows(("pm2_5", "pm2_5", AIR), ("pm0_2", "pm0_2", AIR),
                       ("pm10", "pm10", AIR), ("band", "pm0_2_to_pm2_5", AIR))
        out, counts = _carry([FakeRow("pm2_5", FakeFactor(1.0)), FakeRow("pm10", FakeFactor(0.536))], flows)
        carried = _carried(out)
        self.assertEqual(carried["pm0_2"].source_flow_uuid, "pm2_5")
        self.assertEqual(carried["band"].source_flow_uuid, "pm2_5")
        # PM2.5 blank, PM10 stated: the ultrafine cut looks one step further up.
        out, _ = _carry([FakeRow("pm10", FakeFactor(0.536))], flows)
        carried = _carried(out)
        self.assertEqual(carried["pm0_2"].source_flow_uuid, "pm10")
        self.assertEqual(carried["pm2_5"].source_flow_uuid, "pm10")

    def test_above_pm10_takes_the_unsized_total_and_nothing_else(self):
        flows = _flows(("total", "unsized", AIR), ("above", "above_pm10", AIR), ("pm10", "pm10", AIR))
        out, _ = _carry([FakeRow("pm10", FakeFactor(0.536))], flows)
        self.assertNotIn("above", _carried(out))
        out, _ = _carry([FakeRow("pm10", FakeFactor(0.536)), FakeRow("total", FakeFactor(0.157))], flows)
        self.assertEqual(_carried(out)["above"].factor.amount, 0.157)

    def test_nothing_is_carried_from_a_carried_factor(self):
        """The coarse band is filled from PM10, and the ultrafine cut then takes
        PM2.5 directly rather than a row the pass itself wrote."""
        flows = _flows(("pm10", "pm10", AIR), ("pm2_5", "pm2_5", AIR), ("pm0_2", "pm0_2", AIR))
        out, counts = _carry([FakeRow("pm10", FakeFactor(0.536))], flows)
        carried = _carried(out)
        self.assertEqual(carried["pm2_5"].source_flow_uuid, "pm10")
        self.assertEqual(carried["pm0_2"].source_flow_uuid, "pm10")
        self.assertEqual(counts["carried"], 2)

    def test_a_window_somebody_speaks_about_is_left_to_the_queue(self):
        flows = _flows(("pm10", "pm10", AIR), ("coarse", "pm2_5_to_pm10", AIR))
        stated = {"ecoinvent": {("coarse", SLUG, ""): object()}}
        out, counts = _carry([FakeRow("pm10", FakeFactor(1.0))], flows, stated=stated)
        self.assertEqual(_carried(out), {})
        self.assertEqual(counts["held_by_a_queue"], 1)

    def test_a_withdrawn_flow_is_neither_filled_nor_a_donor(self):
        flows = _flows(("pm10", "pm10", AIR), ("coarse", "pm2_5_to_pm10", AIR), deprecated=("coarse",))
        out, _ = _carry([FakeRow("pm10", FakeFactor(1.0))], flows)
        self.assertEqual(_carried(out), {})
        flows = _flows(("pm10", "pm10", AIR), ("coarse", "pm2_5_to_pm10", AIR), deprecated=("pm10",))
        out, _ = _carry([FakeRow("pm10", FakeFactor(1.0))], flows)
        self.assertEqual(_carried(out), {})

    def test_the_root_takes_its_children_only_where_all_are_published_and_agree(self):
        flows = _flows(("total", "unsized", AIR), ("pm10", "pm10", AIR), ("above", "above_pm10", AIR))
        out, counts = _carry([FakeRow("pm10", FakeFactor(0.536)), FakeRow("above", FakeFactor(0.157))], flows)
        self.assertNotIn("total", _carried(out))
        self.assertEqual(counts["children_disagree"], 1)
        # PM10 alone is not the total: that is EF everywhere, and the reading
        # the owner declined for Stepwise.
        out, counts = _carry([FakeRow("pm10", FakeFactor(0.536))], flows)
        self.assertNotIn("total", _carried(out))
        self.assertEqual(counts["children_missing"], 1)
        out, counts = _carry([FakeRow("pm10", FakeFactor(0.5)), FakeRow("above", FakeFactor(0.5))], flows)
        self.assertEqual(_carried(out)["total"].factor.amount, 0.5)
        self.assertEqual(counts["carried_upward"], 1)

    def test_a_substance_that_is_not_a_window_is_not_touched(self):
        flows = {"x": {"flow_object_id": "fo-ammonium", "context_iri": AIR, "deprecated": False}}
        out, counts = _carry([FakeRow("x", FakeFactor(2.0))], flows)
        self.assertEqual(len(out), 1)
        self.assertEqual(counts, {})


if __name__ == "__main__":
    unittest.main()
