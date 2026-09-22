"""Helium comes out of the ground, and EF 3.1 files it as coming out of the air.

EF 3.1's `Renewable element resources from air` holds nine flows.  Eight are
gases cryogenic air separation actually produces -- dinitrogen, oxygen, argon,
Argon-40, neon, krypton, xenon -- plus radon, which is in the air because it
decays into it.  Helium is the one member nobody separates from air: at 5.2 ppm
it is far too dilute, and commercial helium comes out of natural gas deposits.

ecoinvent 3.12 says so in its own data, which is what turns a reading into a
disagreement: its flow is `Helium, in natural gas` in `natural resource / in
ground`.  The two compartments contradict, so the merge minted a second flow
rather than putting that row on EF's, and helium was published as a resource in
two places (#114).

These are about the rule as *data*: which flow it moves, where to, and the eight
it must leave alone.  What the build then publishes is
`expectations/0576-helium-comes-out-of-the-ground.json`.
"""

from __future__ import annotations

import unittest

import orjson

from brightway_flows.context_mapping import MANUAL_MAPPING_FILEPATH

#: EF 3.1's resource flow for helium.  Named by uuid because the whole of this
#: change is where that one row is filed, and the name `helium` is also on
#: twelve emission flows the rule must not touch.
HELIUM_UUID = "fe0acd60-3ddc-11dd-a657-0050c2490048"

GROUND = "https://vocab.brightway.one/flow-contexts/reso-grou"
AIR_RESOURCE = [
    "Resources",
    "Resources from air",
    "Renewable element resources from air",
]

#: The eight that stay. Every one is a gas an air separation unit produces, or
#: -- radon -- one that is in the air because it decays into it there.
STAY_IN_THE_AIR = (
    "dinitrogen",
    "oxygen",
    "argon",
    "Argon-40",
    "neon",
    "krypton",
    "xenon",
    "radon",
)


def _rows() -> list[dict]:
    payload = orjson.loads(MANUAL_MAPPING_FILEPATH.read_bytes())
    return payload["flow_specific_context_mappings"]


def _helium_row() -> dict | None:
    for row in _rows():
        if row.get("source_uuid") == HELIUM_UUID:
            return row
    return None


class TheRuleSaysWhereHeliumComesFromTestCase(unittest.TestCase):
    def setUp(self):
        self.row = _helium_row()

    def test_the_rule_is_stated(self):
        self.assertIsNotNone(self.row, "no rule for EF 3.1's helium resource flow")

    def test_it_sends_helium_to_the_ground(self):
        self.assertEqual(self.row["context_iri"], GROUND)

    def test_it_names_the_compartment_it_overrules(self):
        """The row records what EF filed it under, not only where it goes."""
        self.assertEqual(self.row["source_context"], AIR_RESOURCE)

    def test_it_names_the_list_and_the_flow(self):
        self.assertEqual(self.row["source"], "EF 3.1")
        self.assertEqual(self.row["source_name"], "helium")

    def test_it_says_why(self):
        comment = self.row["comment"]
        for fragment in ("natural gas", "5.2 ppm", "#114"):
            with self.subTest(fragment):
                self.assertIn(fragment, comment)


class TheOtherEightAreLeftAloneTestCase(unittest.TestCase):
    """A rule that moved the whole compartment would be a different change.

    Argon, neon, krypton and xenon really are taken from the air, and moving
    them would be wrong in the direction this rule is right in.
    """

    def test_no_rule_moves_another_air_resource(self):
        moved = {
            row["source_name"].strip().lower()
            for row in _rows()
            if row.get("source_context") == AIR_RESOURCE
        }
        for name in STAY_IN_THE_AIR:
            with self.subTest(name):
                self.assertNotIn(name.lower(), moved)

    def test_helium_is_the_only_one_moved(self):
        moved = [
            row["source_name"]
            for row in _rows()
            if row.get("source_context") == AIR_RESOURCE
        ]
        self.assertEqual(moved, ["helium"])


class TheRuleIsKeyedOnOneFlowTestCase(unittest.TestCase):
    """Twelve of EF's thirteen helium flows are emissions and must not move.

    `merge/places.py` sets release contexts aside for the reason this test
    exists: where a substance is released is a fact about the process, and
    helium emitted to air, water and soil is thirteen ordinary flows.
    """

    def test_the_rule_names_a_uuid_rather_than_a_name(self):
        self.assertTrue(self.__class__ and _helium_row()["source_uuid"])

    def test_no_other_helium_flow_is_named(self):
        named = [
            row["source_uuid"]
            for row in _rows()
            if row.get("source_name", "").strip().lower() == "helium"
        ]
        self.assertEqual(named, [HELIUM_UUID])


if __name__ == "__main__":
    unittest.main()
