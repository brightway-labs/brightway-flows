"""Three rows that ship no number are given the one their name means.

#471.  BAFU's `P-cyanophenol` and Stepwise's `Amylene, beta-cis-` and
`Amylene, trans-beta-` each name, under an ordinary second name, a substance
EF 3.1 ships with its registry number.  None of the three rows ships one, so
each minted a second copy.  The fix writes the number on the row.

Two halves, as for every fix that fills in what a source left out.  The number
goes on, and a row beside it that the fix does not name keeps what it shipped:
Stepwise's `1-Pentene` is a pentene that is neither of these, and a spelling
BAFU does not ship is left alone.
"""

from __future__ import annotations

import copy
import unittest

from brightway_flows.filesystem import PACKAGE_DATA_DIR
from brightway_flows.manual_fixes import apply_manual_fixes

BAFU_FIXES = PACKAGE_DATA_DIR / "bafu-2026-v1-manual-fixes.json"
STEPWISE_FIXES = PACKAGE_DATA_DIR / "stepwise-2006-manual-fixes.json"

P_CYANOPHENOL = "64eae87e-9ee8-5893-b1c0-96702b46d2c1"
CIS = "81b5295d-e6d5-5c36-9d51-73b49371f703"
TRANS = "5b715bff-fcca-5f9e-b516-ceab73e7257e"
ONE_PENTENE = "4d075748-1edf-53e5-a863-a2c96f56ff2d"

#: The row as `bafu-2026-v1.json` ships it.
BAFU_ROWS = [
    {
        "uuid": P_CYANOPHENOL,
        "name": "P-cyanophenol",
        "source": "bafu-2026-v1",
        "context": ["emissions to soil", "industrial"],
        "unit": "kg",
    },
]

#: The rows as `stepwise-2006-1.09.json` ships them.
STEPWISE_ROWS = [
    {
        "uuid": CIS,
        "name": "Amylene, beta-cis-",
        "source": "stepwise-2006-1.09",
        "context": ["Air", "(unspecified)"],
        "unit": "kg",
    },
    {
        "uuid": TRANS,
        "name": "Amylene, trans-beta-",
        "source": "stepwise-2006-1.09",
        "context": ["Air", "(unspecified)"],
        "unit": "kg",
    },
    {
        "uuid": ONE_PENTENE,
        "name": "1-Pentene",
        "source": "stepwise-2006-1.09",
        "context": ["Air", "(unspecified)"],
        "unit": "kg",
        "cas_numbers": ["109-67-1"],
    },
]


def _fixed(rows, fixes, label):
    rows = copy.deepcopy(rows)
    apply_manual_fixes(rows, fixes, label=label, quiet=True)
    return {row["uuid"]: row for row in rows}


class RowsThatNameAHeldSubstanceTestCase(unittest.TestCase):
    def test_p_cyanophenol_is_given_the_number_of_4_cyanophenol(self):
        fixed = _fixed(BAFU_ROWS, BAFU_FIXES, "bafu-2026-v1")
        self.assertEqual(fixed[P_CYANOPHENOL]["cas_numbers"], ["767-00-0"])

    def test_the_two_beta_amylenes_are_given_the_two_2_pentenes(self):
        fixed = _fixed(STEPWISE_ROWS, STEPWISE_FIXES, "stepwise-2006-1.09")
        self.assertEqual(fixed[CIS]["cas_numbers"], ["627-20-3"])
        self.assertEqual(fixed[TRANS]["cas_numbers"], ["646-04-8"])

    def test_a_pentene_the_fix_does_not_name_keeps_its_own_number(self):
        fixed = _fixed(STEPWISE_ROWS, STEPWISE_FIXES, "stepwise-2006-1.09")
        self.assertEqual(fixed[ONE_PENTENE]["cas_numbers"], ["109-67-1"])

    def test_the_name_is_matched_as_shipped_and_not_in_another_case(self):
        """`P-cyanophenol` is BAFU's capitalisation; `p-Cyanophenol` is not a row."""
        rows = [{**BAFU_ROWS[0], "name": "p-Cyanophenol"}]
        fixed = _fixed(rows, BAFU_FIXES, "bafu-2026-v1")
        self.assertNotIn("cas_numbers", fixed[P_CYANOPHENOL])

    def test_applying_twice_changes_nothing_further(self):
        rows = copy.deepcopy(STEPWISE_ROWS)
        apply_manual_fixes(rows, STEPWISE_FIXES, label="stepwise-2006-1.09", quiet=True)
        once = copy.deepcopy(rows)
        apply_manual_fixes(rows, STEPWISE_FIXES, label="stepwise-2006-1.09", quiet=True)
        self.assertEqual(rows, once)


if __name__ == "__main__":
    unittest.main()
