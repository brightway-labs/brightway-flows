"""The pass carries a number the convention names, and nothing else.

Ammonium is characterised in surface water and has a river flow nobody
characterised; the convention says a river takes surface water's number, so the
river gets 2,493.2 as `carried`, from that flow.  What the pass declines to do
is the half that matters: it never fills a context an implementation speaks
about, never publishes onto a withdrawn flow, never carries from a carried
factor, and a root takes its children's number only where they agree.
"""

from __future__ import annotations

import unittest
from dataclasses import dataclass

from brightway_flows.lcia.context_carry import (
    CARRIED,
    CarryDirection,
    CarryRule,
    ContextCarryRules,
    carry_across_contexts,
)

CTX = "https://vocab.brightway.one/flow-contexts/"
SURFACE = CTX + "envi-wate-suwa"
UNKNOWN = CTX + "envi-wate-unkn"
RIVER = CTX + "envi-wate-rive"
LAKE = CTX + "envi-wate-lake"
AQUIFER = CTX + "envi-wate-unaq"
SUBSTANCE = "fo-ammonium"
SLUG = "ecotoxicity-freshwater"


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


def _rule(direction, recipient, *donors):
    return CarryRule(
        direction=direction,
        recipient_iri=recipient,
        recipient=recipient,
        donor_iris=tuple(donors),
        donors=tuple(donors),
        comment="because",
    )


DOWN_RIVER = _rule(CarryDirection.DOWNWARD, RIVER, SURFACE, UNKNOWN)
DOWN_LAKE = _rule(CarryDirection.DOWNWARD, LAKE, SURFACE, UNKNOWN)
DOWN_SURFACE = _rule(CarryDirection.DOWNWARD, SURFACE, UNKNOWN)
UP_UNKNOWN = _rule(CarryDirection.UPWARD, UNKNOWN, SURFACE, AQUIFER)
RULES = ContextCarryRules(
    walls=(),
    downward=(DOWN_RIVER, DOWN_LAKE, DOWN_SURFACE),
    upward=(UP_UNKNOWN,),
)


def _flows(*pairs, deprecated=()):
    return {
        uuid: {
            "flow_object_id": SUBSTANCE,
            "context_iri": context,
            "deprecated": uuid in deprecated,
        }
        for uuid, context in pairs
    }


def _carry(published, flows, rules=RULES, stated=None):
    return carry_across_contexts(
        published,
        rules=rules,
        slug_of=lambda row: SLUG,
        flows=flows,
        stated=stated or {},
    )


def _carried(rows):
    return {row.elementary_flow_uuid: row for row in rows if row.derivation == CARRIED}


class DownwardTest(unittest.TestCase):
    def test_the_first_published_donor_gives_its_number(self):
        flows = _flows(("surface", SURFACE), ("unknown", UNKNOWN), ("river", RIVER))
        published = [FakeRow("surface", FakeFactor(2493.2)), FakeRow("unknown", FakeFactor(2493.2))]
        out, counts = _carry(published, flows)
        river = _carried(out)["river"]
        self.assertEqual(river.factor.amount, 2493.2)
        self.assertEqual(river.source_flow_uuid, "surface")
        self.assertIsNone(river.also_stated)
        self.assertEqual(counts["carried"], 1)
        self.assertEqual(counts["carried_downward"], 1)
        self.assertEqual(counts["rule_downward:envi-wate-rive"], 1)
        self.assertEqual(len(out), 3)

    def test_the_second_donor_is_used_where_the_first_is_not_published(self):
        flows = _flows(("unknown", UNKNOWN), ("river", RIVER))
        out, _ = _carry([FakeRow("unknown", FakeFactor(7.0))], flows)
        self.assertEqual(_carried(out)["river"].source_flow_uuid, "unknown")

    def test_nothing_is_carried_from_a_carried_factor(self):
        # Surface water is itself blank and is filled from unspecified water; the
        # river then takes unspecified water directly rather than the carried row.
        flows = _flows(("unknown", UNKNOWN), ("surface", SURFACE), ("river", RIVER))
        out, counts = _carry([FakeRow("unknown", FakeFactor(7.0))], flows)
        carried = _carried(out)
        self.assertEqual(carried["surface"].source_flow_uuid, "unknown")
        self.assertEqual(carried["river"].source_flow_uuid, "unknown")
        self.assertEqual(counts["carried"], 2)

    def test_a_context_somebody_speaks_about_is_left_to_the_queue(self):
        flows = _flows(("surface", SURFACE), ("river", RIVER))
        stated = {"ecoinvent": {("river", SLUG, ""): object()}}
        out, counts = _carry([FakeRow("surface", FakeFactor(1.0))], flows, stated=stated)
        self.assertEqual(_carried(out), {})
        self.assertEqual(counts["held_by_a_queue"], 1)

    def test_a_withdrawn_flow_is_neither_filled_nor_a_donor(self):
        flows = _flows(("surface", SURFACE), ("river", RIVER), ("old-river", RIVER), deprecated={"old-river"})
        out, _ = _carry([FakeRow("surface", FakeFactor(1.0))], flows)
        self.assertEqual(set(_carried(out)), {"river"})
        flows = _flows(("surface", SURFACE), ("river", RIVER), deprecated={"surface"})
        out, _ = _carry([FakeRow("surface", FakeFactor(1.0))], flows)
        self.assertEqual(_carried(out), {})

    def test_every_empty_flow_of_the_context_is_filled(self):
        flows = _flows(("surface", SURFACE), ("river-kg", RIVER), ("river-m3", RIVER))
        out, counts = _carry([FakeRow("surface", FakeFactor(1.0))], flows)
        self.assertEqual(set(_carried(out)), {"river-kg", "river-m3"})
        self.assertEqual(counts["carried"], 2)

    def test_geography_is_part_of_the_key(self):
        flows = _flows(("surface", SURFACE), ("river", RIVER))
        published = [
            FakeRow("surface", FakeFactor(42.95, "")),
            FakeRow("surface", FakeFactor(18.6, "CH")),
            FakeRow("river", FakeFactor(18.6, "CH")),
        ]
        out, counts = _carry(published, flows)
        carried = [row for row in out if row.derivation == CARRIED]
        self.assertEqual([(row.factor.geography, row.factor.amount) for row in carried], [("", 42.95)])

    def test_a_stated_zero_carries(self):
        flows = _flows(("surface", SURFACE), ("river", RIVER))
        out, _ = _carry([FakeRow("surface", FakeFactor(0.0))], flows)
        self.assertEqual(_carried(out)["river"].factor.amount, 0.0)

    def test_a_context_no_rule_names_stays_blank(self):
        flows = _flows(("surface", SURFACE), ("aquifer", AQUIFER))
        out, counts = _carry([FakeRow("surface", FakeFactor(1.0))], flows)
        self.assertEqual(_carried(out), {})
        self.assertEqual(counts, {})


class UpwardTest(unittest.TestCase):
    def test_a_root_takes_its_only_published_child(self):
        flows = _flows(("surface", SURFACE), ("unknown", UNKNOWN))
        out, counts = _carry([FakeRow("surface", FakeFactor(1.5))], flows)
        self.assertEqual(_carried(out)["unknown"].source_flow_uuid, "surface")
        self.assertEqual(counts["carried_upward"], 1)

    def test_a_root_takes_agreeing_children_at_the_most_precise_printing(self):
        flows = _flows(("surface", SURFACE), ("aquifer", AQUIFER), ("unknown", UNKNOWN))
        published = [FakeRow("surface", FakeFactor(1787.5)), FakeRow("aquifer", FakeFactor(1787.5000000001))]
        out, _ = _carry(published, flows)
        self.assertEqual(_carried(out)["unknown"].factor.amount, 1787.5000000001)

    def test_a_root_refuses_children_that_differ(self):
        flows = _flows(("surface", SURFACE), ("aquifer", AQUIFER), ("unknown", UNKNOWN))
        published = [FakeRow("surface", FakeFactor(100.0)), FakeRow("aquifer", FakeFactor(101.0))]
        out, counts = _carry(published, flows)
        self.assertEqual(_carried(out), {})
        self.assertEqual(counts["children_disagree"], 1)

    def test_upward_runs_after_downward_and_reads_only_stated_children(self):
        # Unspecified water is blank; surface water is blank too and would be
        # filled downward only from unspecified water, which is not published,
        # so it stays blank; the aquifer is stated, and the root takes it.
        flows = _flows(("surface", SURFACE), ("aquifer", AQUIFER), ("unknown", UNKNOWN), ("river", RIVER))
        out, counts = _carry([FakeRow("aquifer", FakeFactor(3.0))], flows)
        carried = _carried(out)
        self.assertEqual(set(carried), {"unknown"})
        self.assertEqual(counts["carried_upward"], 1)


class NothingToDoTest(unittest.TestCase):
    def test_no_rules_no_rows(self):
        flows = _flows(("surface", SURFACE), ("river", RIVER))
        empty = ContextCarryRules(walls=(), downward=(), upward=())
        out, counts = _carry([FakeRow("surface", FakeFactor(1.0))], flows, rules=empty)
        self.assertEqual(len(out), 1)
        self.assertEqual(counts, {})


if __name__ == "__main__":
    unittest.main()
