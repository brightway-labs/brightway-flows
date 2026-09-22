"""BAFU's numberless `Carbon monoxide, biogenic` row takes carbon monoxide's number.

#177.  BAFU ships the name three times, once per air subcompartment, and the
`low. pop.` row alone carries no registry number.  Its two siblings carry
630-08-0 and reach `Carbon Monoxide (biogenic)` on `cas+qualifier`; the third
reached nothing and minted a second biogenic carbon monoxide with no factor.
The fix is #134's, one substance over: the number is written on the name in
`bafu-2026-v1-manual-fixes.json`.

Both halves are tested.  The numberless row gets the number, and the two rows
that already carry it are not touched -- which is what a name-keyed fix has to
guarantee, since it matches all three.
"""

from __future__ import annotations

import copy
import unittest

from brightway_flows.filesystem import PACKAGE_DATA_DIR
from brightway_flows.manual_fixes import apply_manual_fixes

FIXES = PACKAGE_DATA_DIR / "bafu-2026-v1-manual-fixes.json"

CARBON_MONOXIDE = "630-08-0"

#: The three rows as the extraction ships them (`bafu-2026-v1.json`): the two
#: numbered ones carry the number, the `low. pop.` row has no `cas_numbers`
#: key at all.
ROWS = [
    {
        "uuid": "5602a0ca-7176-5593-928a-62dc45952387",
        "name": "Carbon monoxide, biogenic",
        "source": "bafu-2026-v1",
        "context": ["emissions to air", "high. pop."],
        "unit": "kg",
        "cas_numbers": [CARBON_MONOXIDE],
    },
    {
        "uuid": "da1ef05f-a84c-515a-b252-6c60b0baae8f",
        "name": "Carbon monoxide, biogenic",
        "source": "bafu-2026-v1",
        "context": ["emissions to air", "unspecified"],
        "unit": "kg",
        "cas_numbers": [CARBON_MONOXIDE],
    },
    {
        "uuid": "4469c7c9-c330-575e-94f4-ce731c9fa524",
        "name": "Carbon monoxide, biogenic",
        "source": "bafu-2026-v1",
        "context": ["emissions to air", "low. pop."],
        "unit": "kg",
    },
    # A neighbour the fix must not reach: fossil carbon monoxide, numberless.
    {
        "uuid": "00000000-0000-0000-0000-000000000001",
        "name": "Carbon monoxide, fossil",
        "source": "bafu-2026-v1",
        "context": ["emissions to air", "low. pop."],
        "unit": "kg",
    },
]


def _fixed():
    rows = copy.deepcopy(ROWS)
    apply_manual_fixes(rows, FIXES, label="bafu-2026-v1", quiet=True)
    return {row["uuid"]: row for row in rows}


class BiogenicCarbonMonoxideTestCase(unittest.TestCase):
    def test_the_low_pop_row_gets_the_number(self):
        row = _fixed()["4469c7c9-c330-575e-94f4-ce731c9fa524"]
        self.assertEqual(row["cas_numbers"], [CARBON_MONOXIDE])

    def test_the_two_numbered_siblings_are_left_as_shipped(self):
        fixed = _fixed()
        for uuid in (
            "5602a0ca-7176-5593-928a-62dc45952387",
            "da1ef05f-a84c-515a-b252-6c60b0baae8f",
        ):
            with self.subTest(uuid=uuid):
                self.assertEqual(fixed[uuid]["cas_numbers"], [CARBON_MONOXIDE])

    def test_a_differently_qualified_neighbour_is_not_touched(self):
        row = _fixed()["00000000-0000-0000-0000-000000000001"]
        self.assertNotIn("cas_numbers", row)

    def test_applying_twice_changes_nothing_further(self):
        rows = copy.deepcopy(ROWS)
        apply_manual_fixes(rows, FIXES, label="bafu-2026-v1", quiet=True)
        once = copy.deepcopy(rows)
        apply_manual_fixes(rows, FIXES, label="bafu-2026-v1", quiet=True)
        self.assertEqual(rows, once)


if __name__ == "__main__":
    unittest.main()
