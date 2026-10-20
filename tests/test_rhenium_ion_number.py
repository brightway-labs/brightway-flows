"""EF's thirteen `rhenium(2+)` rows lose rhenium the element's registry number.

#404.  EF 3.1 writes 7440-15-5 -- rhenium the element -- and its EC companion
231-124-5 on every `rhenium(2+)` row, and publishes the element separately
under the same number as its `rhenium` resource row.  The name states a
charge, as `cerium(3+)` does (#184), but no registry holds a number for the
cation, so there is nothing to put in the element's place: the number comes
off, as it does for AGRIBALYSE's `Copper, ion` (#198), because a number is
published on a substance only where it names that substance.

Both halves: the ion rows lose both numbers, and the element's own row and
EF's perrhenic acid row, which carry rhenium numbers of their own, are left
exactly as EF shipped them.
"""

from __future__ import annotations

import copy
import unittest

from brightway_flows.filesystem import PACKAGE_DATA_DIR
from brightway_flows.manual_fixes import apply_manual_fixes

FIXES = PACKAGE_DATA_DIR / "ef-3.1-manual-fixes.json"

ELEMENT = "7440-15-5"
ELEMENT_EC = "231-124-5"

ION_ROWS = (
    "0fc5ac7a-59be-4bbc-8a23-5bc150f8c7ca",
    "ad8e0952-2bca-4592-9594-df6ef9e6d939",
)
ELEMENT_ROW = "1729c87c-6556-11dd-ad8b-0800200c9a66"
PERRHENIC_ACID_ROW = "0a460eb6-3385-494e-8a51-3a0972bb3578"

ROWS = [
    {
        "uuid": ION_ROWS[0],
        "name": "rhenium(2+)",
        "cas_numbers": [ELEMENT],
        "ec_numbers": [ELEMENT_EC],
        "synonyms": ["element", "rhenium"],
        "context": ["Emissions", "Emissions to water", "Emissions to sea water"],
        "unit": "kg",
    },
    {
        "uuid": ION_ROWS[1],
        "name": "rhenium(2+)",
        "cas_numbers": [ELEMENT],
        "ec_numbers": [ELEMENT_EC],
        "synonyms": ["element", "rhenium"],
        "context": ["Emissions", "Emissions to water", "Emissions to fresh water"],
        "unit": "kg",
    },
    {
        "uuid": ELEMENT_ROW,
        "name": "rhenium",
        "cas_numbers": [ELEMENT],
        "ec_numbers": [],
        "synonyms": ["RE", "Rhenium, elementar"],
        "context": [
            "Resources",
            "Resources from ground",
            "Non-renewable element resources from ground",
        ],
        "unit": "kg",
    },
    {
        "uuid": PERRHENIC_ACID_ROW,
        "name": "hydroxy(trioxo)rhenium",
        "cas_numbers": ["13768-11-1"],
        "ec_numbers": ["237-380-4"],
        "synonyms": ["inorganic", "perrhenicacid"],
        "context": [
            "Emissions",
            "Emissions to water",
            "Emissions to water, unspecified (long-term)",
        ],
        "unit": "kg",
    },
]


def _fixed(passes: int = 1):
    rows = copy.deepcopy(ROWS)
    for _ in range(passes):
        apply_manual_fixes(rows, FIXES, label="ef-3.1", quiet=True)
    return {row["uuid"]: row for row in rows}


class RheniumIonNumberTestCase(unittest.TestCase):
    def test_every_ion_row_loses_the_elements_number(self):
        fixed = _fixed()
        for uuid in ION_ROWS:
            with self.subTest(uuid=uuid):
                self.assertEqual(fixed[uuid]["cas_numbers"], [])

    def test_every_ion_row_loses_the_elements_ec_number(self):
        """231-124-5 is the element's EC number and the ion has none; left on
        the rows it is the element's identity by a second route."""
        fixed = _fixed()
        for uuid in ION_ROWS:
            with self.subTest(uuid=uuid):
                self.assertEqual(fixed[uuid]["ec_numbers"], [])

    def test_the_ion_rows_are_not_given_a_number_in_its_place(self):
        """Removed, not replaced: no registry holds a number for Re2+, and a
        number written here would be one nobody can look up."""
        fixed = _fixed()
        for uuid in ION_ROWS:
            with self.subTest(uuid=uuid):
                self.assertFalse(fixed[uuid]["cas_numbers"])
                self.assertFalse(fixed[uuid]["ec_numbers"])

    def test_the_elements_own_row_keeps_its_number(self):
        """The resource row *is* the metal, and 7440-15-5 names it."""
        fixed = _fixed()
        self.assertEqual(fixed[ELEMENT_ROW]["cas_numbers"], [ELEMENT])
        self.assertEqual(fixed[ELEMENT_ROW]["name"], "rhenium")

    def test_perrhenic_acid_is_left_alone(self):
        """EF's other rhenium emission, with numbers of its own."""
        fixed = _fixed()
        row = fixed[PERRHENIC_ACID_ROW]
        self.assertEqual(row["cas_numbers"], ["13768-11-1"])
        self.assertEqual(row["ec_numbers"], ["237-380-4"])

    def test_a_second_pass_changes_nothing_more(self):
        """The base list applies its fixes at extract and again when the
        transform reads the file back (#237); the second pass must find the
        numbers already gone and say nothing."""
        self.assertEqual(_fixed(passes=2), _fixed(passes=1))
