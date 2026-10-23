"""BAFU's one numbered `Copper ion` row has the metal's number set aside.

#183.  BAFU ships `Copper ion` three times and writes 7440-50-8 -- copper the
metal -- on the `high. pop.` air row alone.  The name says ion, the number says
metal, and BAFU ships plain `Copper` under the same number in the same
compartment, so the number is the half that is wrong.  The other two rows carry
no number and land by name on `Copper, Ion`; with the number set aside this one
joins them.

This was a manual fix keyed on the row's uuid until the #380 rule, which sets
the bare element's number aside on every list's ion names, made it redundant
(removed 23 October 2026).  Two halves still: the number is set aside on the
one row, and BAFU's plain `Copper` rows, which carry the same number and mean
the metal, are not touched.
"""

from __future__ import annotations

import copy
import unittest

from brightway_flows.filesystem import PACKAGE_DATA_DIR
from brightway_flows.manual_fixes import apply_manual_fixes
from brightway_flows.merge.species import element_number_set_aside
from brightway_flows.merge.state import SourceRow

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


def _matched(row):
    """The row as the merge's ion rule reads it (`merge/rows.py`)."""
    numbers = row.get("cas_numbers") or []
    return element_number_set_aside(SourceRow(
        uuid=row["uuid"], name=row["name"], synonyms=[], labels=[row["name"]],
        context=row["context"], context_iri="", context_normalized=(),
        unit=row["unit"], unit_iri="", cas=numbers[0] if numbers else "", ec="",
    ))


class CopperIonNumberTestCase(unittest.TestCase):
    def test_no_fix_rewrites_the_ion_row(self):
        """The rule decides it now; a fix as well would be two statements of one ruling."""
        self.assertEqual(_fixed()[COPPER_ION_HIGH_POP]["cas_numbers"], [COPPER_METAL])

    def test_the_metal_number_is_set_aside_on_the_ion_row(self):
        row = _matched(_fixed()[COPPER_ION_HIGH_POP])
        self.assertEqual((row.cas, row.number_set_aside), ("", COPPER_METAL))
        self.assertEqual(row.labels[0], "Copper, ion")

    def test_the_plain_copper_row_is_matched_by_the_metal_number(self):
        row = _matched(_fixed()[COPPER_HIGH_POP])
        self.assertEqual((row.cas, row.number_set_aside), (COPPER_METAL, ""))

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
