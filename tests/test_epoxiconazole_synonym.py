"""ecoinvent's two synonym-less `Epoxiconazole` rows get the synonym their siblings carry.

#179.  ecoinvent registers the fungicide 135319-73-2 and EF 3.1 carries it as
`Bas 480f` under 106325-08-0, so the only bridge between the lists is the
synonym `BAS 480F`, which ecoinvent writes on six of its eight rows.  The two
without it -- soil, unspecified and surface water, both shipped from 3.11 on --
minted a second substance.  The fix restores the synonym in the 3.11 and 3.12
fixes files.

Both halves: the two rows get the synonym, and a sibling that already carries
it -- and any other row -- is not touched.  The two files are checked to agree,
since #26 is what a correction in one release and not the other costs.
"""

from __future__ import annotations

import copy
import unittest

from brightway_flows.filesystem import PACKAGE_DATA_DIR
from brightway_flows.manual_fixes import apply_manual_fixes

SYNONYM = "BAS 480F"
STEREO_UNSPECIFIED = "135319-73-2"
SOIL = "3bd32b7c-53b2-5302-a82a-61206e93c1de"
SURFACE_WATER = "a9870af8-ee86-51a8-8068-9d2250dea9cf"
AGRICULTURAL_SOIL = "1afedfb8-dfbd-4722-a5fc-f678c593d907"

#: As the 3.12 extraction ships them: the two rows have no `synonyms` key.
ROWS = [
    {
        "uuid": SOIL, "name": "Epoxiconazole", "cas_number": STEREO_UNSPECIFIED,
        "context": ["soil", "unspecified"], "unit": "kg",
    },
    {
        "uuid": SURFACE_WATER, "name": "Epoxiconazole", "cas_number": STEREO_UNSPECIFIED,
        "context": ["water", "surface water"], "unit": "kg",
    },
    {
        "uuid": AGRICULTURAL_SOIL, "name": "Epoxiconazole", "cas_number": STEREO_UNSPECIFIED,
        "context": ["soil", "agricultural"], "unit": "kg", "synonyms": [SYNONYM],
    },
    {
        "uuid": "00000000-0000-0000-0000-000000000001", "name": "Epoxiconazole-like",
        "cas_number": "1-2-3", "context": ["soil", "unspecified"], "unit": "kg",
    },
]


def _fixed(version):
    rows = copy.deepcopy(ROWS)
    path = PACKAGE_DATA_DIR / f"ecoinvent-{version}-manual-fixes.json"
    apply_manual_fixes(rows, path, label=f"ecoinvent-{version}", quiet=True)
    return {row["uuid"]: row for row in rows}


class EpoxiconazoleSynonymTestCase(unittest.TestCase):
    def test_both_rows_get_the_synonym_in_both_releases(self):
        for version in ("3.11", "3.12"):
            fixed = _fixed(version)
            for uuid in (SOIL, SURFACE_WATER):
                with self.subTest(version=version, uuid=uuid):
                    self.assertEqual(fixed[uuid]["synonyms"], [SYNONYM])

    def test_the_sibling_that_already_carries_it_is_left_alone(self):
        for version in ("3.11", "3.12"):
            with self.subTest(version=version):
                self.assertEqual(_fixed(version)[AGRICULTURAL_SOIL]["synonyms"], [SYNONYM])

    def test_a_row_with_another_uuid_is_not_touched(self):
        for version in ("3.11", "3.12"):
            with self.subTest(version=version):
                row = _fixed(version)["00000000-0000-0000-0000-000000000001"]
                self.assertNotIn("synonyms", row)

    def test_the_number_is_not_what_changes(self):
        """The registry number is ecoinvent's and it is right for what it
        names; the fix is about the name, not the number."""
        for uuid in (SOIL, SURFACE_WATER):
            with self.subTest(uuid=uuid):
                self.assertEqual(_fixed("3.12")[uuid]["cas_number"], STEREO_UNSPECIFIED)

    def test_applying_twice_changes_nothing_further(self):
        rows = copy.deepcopy(ROWS)
        path = PACKAGE_DATA_DIR / "ecoinvent-3.12-manual-fixes.json"
        apply_manual_fixes(rows, path, label="ecoinvent-3.12", quiet=True)
        once = copy.deepcopy(rows)
        apply_manual_fixes(rows, path, label="ecoinvent-3.12", quiet=True)
        self.assertEqual(rows, once)


if __name__ == "__main__":
    unittest.main()
