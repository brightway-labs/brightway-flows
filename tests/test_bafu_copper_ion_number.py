"""BAFU's one numbered `Copper ion` row loses the metal's number.

#183.  BAFU ships `Copper ion` three times and writes 7440-50-8 -- copper the
metal -- on the `high. pop.` air row alone.  The name says ion, the number says
metal, and BAFU ships plain `Copper` under the same number in the same
compartment, so the number is the half that is wrong.  The other two rows carry
no number and land by name on `Copper, Ion`; with the number removed this one
joins them.

Two halves.  The number comes off the one row, and BAFU's plain `Copper` rows,
which carry the same number and mean the metal, are not touched -- the fix is
keyed on the uuid, and this is what says so if it is ever loosened to the name.
"""

from __future__ import annotations

import copy
import unittest

from brightway_flows.filesystem import PACKAGE_DATA_DIR
from brightway_flows.manual_fixes import apply_manual_fixes

FIXES = PACKAGE_DATA_DIR / "bafu-2026-v1-manual-fixes.json"

COPPER_METAL = "7440-50-8"
COPPER_ION_HIGH_POP = "32892430-739d-5fde-9a96-441ecc8153f0"
COPPER_HIGH_POP = "275c37d7-dcb8-538a-899c-6c30dfebc6cc"

#: The rows as `bafu-2026-v1.json` ships them.
ROWS = [
    {
        "uuid": COPPER_ION_HIGH_POP,
        "name": "Copper ion",
        "source": "bafu-2026-v1",
        "context": ["emissions to air", "high. pop."],
        "unit": "kg",
        "cas_numbers": [COPPER_METAL],
        "formula": "Cu",
    },
    {
        "uuid": "6460e06e-892e-515c-a09f-302830a12739",
        "name": "Copper ion",
        "source": "bafu-2026-v1",
        "context": ["emissions to air", "unspecified"],
        "unit": "kg",
    },
    {
        "uuid": COPPER_HIGH_POP,
        "name": "Copper",
        "source": "bafu-2026-v1",
        "context": ["emissions to air", "high. pop."],
        "unit": "kg",
        "cas_numbers": [COPPER_METAL],
    },
]


def _fixed():
    rows = copy.deepcopy(ROWS)
    apply_manual_fixes(rows, FIXES, label="bafu-2026-v1", quiet=True)
    return {row["uuid"]: row for row in rows}


class CopperIonNumberTestCase(unittest.TestCase):
    def test_the_metal_number_comes_off_the_ion_row(self):
        self.assertEqual(_fixed()[COPPER_ION_HIGH_POP]["cas_numbers"], [])

    def test_the_row_then_reads_as_carrying_no_number(self):
        """`merge/rows.py` reads `cas_numbers[0]`; an empty list is no number,
        which is what its two siblings ship and what puts it on the name."""
        self.assertFalse(_fixed()[COPPER_ION_HIGH_POP]["cas_numbers"])

    def test_the_plain_copper_row_keeps_the_metal_number(self):
        self.assertEqual(_fixed()[COPPER_HIGH_POP]["cas_numbers"], [COPPER_METAL])

    def test_the_numberless_sibling_is_not_touched(self):
        self.assertNotIn("cas_numbers", _fixed()["6460e06e-892e-515c-a09f-302830a12739"])

    def test_applying_twice_changes_nothing_further(self):
        rows = copy.deepcopy(ROWS)
        apply_manual_fixes(rows, FIXES, label="bafu-2026-v1", quiet=True)
        once = copy.deepcopy(rows)
        apply_manual_fixes(rows, FIXES, label="bafu-2026-v1", quiet=True)
        self.assertEqual(rows, once)


if __name__ == "__main__":
    unittest.main()
