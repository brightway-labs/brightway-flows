"""EF's thirteen `cerium(3+)` rows take the ion's registry number.

#184.  EF 3.1 writes 7440-45-1 -- cerium the element -- on every `cerium(3+)`
row, and publishes the element separately under the same number as its
`cerium` resource row.  A number outranks a name, so the thirteen emission rows
were published as the element and the charge EF wrote was dropped.  The fix is
#49's for `vanadium (v)`: the ion's own number, 18923-26-7, replaces the
element's on the rows whose name states the charge.

Both halves: the ion rows are renumbered and lose the element's EC number,
and the element's own row, which carries the same number under a bare name,
is left exactly as EF shipped it.
"""

from __future__ import annotations

import copy
import unittest

from brightway_flows.filesystem import PACKAGE_DATA_DIR
from brightway_flows.manual_fixes import apply_manual_fixes

FIXES = PACKAGE_DATA_DIR / "ef-3.1-manual-fixes.json"

ELEMENT = "7440-45-1"
ION = "18923-26-7"
ELEMENT_EC = "231-154-9"

ROWS = [
    {
        "uuid": "ef6d6805-f188-4e31-8d34-a7ddc69aac48",
        "name": "cerium(3+)",
        "cas_numbers": [ELEMENT],
        "ec_numbers": [ELEMENT_EC],
        "synonyms": ["element", "cerium"],
        "context": ["Emissions", "Emissions to air", "Emissions to urban air close to ground"],
        "unit": "kg",
    },
    {
        "uuid": "5953f432-7c43-41ae-b4a3-23f8be3641fc",
        "name": "cerium(3+)",
        "cas_numbers": [ELEMENT],
        "ec_numbers": [ELEMENT_EC],
        "synonyms": ["element", "cerium"],
        "context": ["Emissions", "Emissions to soil", "Emissions to agricultural soil"],
        "unit": "kg",
    },
    {
        "uuid": "08a91e70-3ddc-11dd-925f-0050c2490048",
        "name": "cerium",
        "cas_numbers": [ELEMENT],
        "ec_numbers": [],
        "synonyms": ["cerio"],
        "context": ["Resources", "Resources from ground", "Non-renewable element resources from ground"],
        "unit": "kg",
    },
]


def _fixed():
    rows = copy.deepcopy(ROWS)
    apply_manual_fixes(rows, FIXES, label="ef-3.1", quiet=True)
    return {row["uuid"]: row for row in rows}


class CeriumIonNumberTestCase(unittest.TestCase):
    def test_every_ion_row_takes_the_ions_number(self):
        fixed = _fixed()
        for uuid in (
            "ef6d6805-f188-4e31-8d34-a7ddc69aac48",
            "5953f432-7c43-41ae-b4a3-23f8be3641fc",
        ):
            with self.subTest(uuid=uuid):
                self.assertEqual(fixed[uuid]["cas_numbers"], [ION])

    def test_the_ion_rows_lose_the_elements_ec_number(self):
        """231-154-9 is the element's EC number, and the ion has none; left on
        the rows it is the element's identity by a second route, and the EC
        cross-check queues every row whose EC and CAS disagree."""
        fixed = _fixed()
        for uuid in (
            "ef6d6805-f188-4e31-8d34-a7ddc69aac48",
            "5953f432-7c43-41ae-b4a3-23f8be3641fc",
        ):
            with self.subTest(uuid=uuid):
                self.assertEqual(fixed[uuid]["ec_numbers"], [])

    def test_the_element_row_keeps_the_elements_number(self):
        row = _fixed()["08a91e70-3ddc-11dd-925f-0050c2490048"]
        self.assertEqual(row["cas_numbers"], [ELEMENT])
        self.assertEqual(row["name"], "cerium")

    def test_applying_twice_changes_nothing_further(self):
        rows = copy.deepcopy(ROWS)
        apply_manual_fixes(rows, FIXES, label="ef-3.1", quiet=True)
        once = copy.deepcopy(rows)
        apply_manual_fixes(rows, FIXES, label="ef-3.1", quiet=True)
        self.assertEqual(rows, once)


if __name__ == "__main__":
    unittest.main()
