"""All seven of ecoinvent's `Carbon` rows are curated onto elemental carbon.

#180.  ecoinvent registers its soot measure `Carbon`, 7440-44-0, on seven
emission rows.  Four were in the vendor's correspondence table and #141 sent
them to EF's `Elemental carbon` with signed curated rows; the three soil rows
the table omitted were matched on the number and landed on EF's own `Carbon`
instead, so one name and one number were two substances.  The three now carry
the same curated target, signed the same way.

Two halves.  Every one of the seven is a curated row onto the elemental-carbon
substance, and the two soil-stock rows that share the number -- the #258
family, which are a different substance -- are not swept in.
"""

from __future__ import annotations

import unittest

from brightway_flows.filesystem import PACKAGE_DATA_DIR
from brightway_flows.match_overrides import apply_match_overrides, load_match_overrides

OVERRIDES = PACKAGE_DATA_DIR / "ecoinvent-match-overrides.json"

#: EF's two `Elemental carbon` emission flows, the only targets the family takes.
ELEMENTAL_CARBON = {
    "9fe66e05-5e89-4245-acfc-bb035a982360",  # soil, unspecified
    "d47abacb-4b57-48ef-b2c9-477a6e79f2d3",  # urban air close to ground
}

#: The seven, by uuid: the four #141 curated and the three this change adds.
CARBON = {
    "57af157e-2054-407d-949b-8cc9c2aa4655": ["air", "urban air close to ground"],
    "14ea575b-5caa-4958-acf7-0bcc47f9cadf": ["soil", "unspecified"],
    "36609913-7c42-457a-89cc-00e2d9f0f867": ["water", "ground-"],
    "3ff3231e-3c38-5a47-a6fd-821d11c599e0": ["water", "unspecified"],
    "62859da4-f3c5-417b-a575-8b00d8d658b1": ["soil", "agricultural"],
    "b72e46aa-9034-4dd2-856d-a43241d3b1f4": ["soil", "forestry"],
    "7f8fd1ca-0412-4b2e-90fd-a9d294d947a3": ["soil", "industrial"],
}

#: The soil-carbon ledger rows, which carry 7440-44-0 too and are not soot.
SOIL_STOCK = {
    "9c77a9ae-fcb2-48ed-ae10-4dda59dd6c61",
    "8c2fe757-6866-4ed2-9f89-81012ad774a0",
}


def _by_source():
    return {o.source_uuid: o for o in load_match_overrides(OVERRIDES)}


class EveryCarbonRowIsCuratedTestCase(unittest.TestCase):
    def test_all_seven_target_elemental_carbon(self):
        rows = _by_source()
        for uuid in CARBON:
            with self.subTest(uuid=uuid):
                self.assertIn(uuid, rows)
                self.assertIn(rows[uuid].target_uuid, ELEMENTAL_CARBON)

    def test_all_seven_sign_the_contradiction(self):
        """7440-44-0 names the element and the target is deliberately not it;
        the audit refuses an unsigned contradiction, and a row that forgot to
        sign would be read as a leftover."""
        rows = _by_source()
        for uuid in CARBON:
            with self.subTest(uuid=uuid):
                self.assertTrue(rows[uuid].not_the_stated_substance)

    def test_the_soil_stock_rows_are_not_soot(self):
        rows = _by_source()
        for uuid in SOIL_STOCK:
            with self.subTest(uuid=uuid):
                self.assertNotIn(rows[uuid].target_uuid, ELEMENTAL_CARBON)

    def test_the_three_soil_rows_are_appended_to_an_empty_table(self):
        """Every manifest declares an empty table since #141, so what the
        overrides append is the whole prepared correspondence."""
        result = apply_match_overrides([], OVERRIDES)
        appended = {
            str(row["source"]["uuid"]): str(row["target"]["uuid"]) for row in result
        }
        for uuid in (
            "62859da4-f3c5-417b-a575-8b00d8d658b1",
            "b72e46aa-9034-4dd2-856d-a43241d3b1f4",
            "7f8fd1ca-0412-4b2e-90fd-a9d294d947a3",
        ):
            with self.subTest(uuid=uuid):
                self.assertEqual(appended.get(uuid), "9fe66e05-5e89-4245-acfc-bb035a982360")


if __name__ == "__main__":
    unittest.main()
