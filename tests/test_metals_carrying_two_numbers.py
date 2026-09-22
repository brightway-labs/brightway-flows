"""A BAFU row carrying an element's number and an ion's is read as the element.

#168.  Eleven BAFU rows -- six metals in `unspecified` air or water -- carry two
registry numbers rather than one, because the extraction unions what BAFU's own
processes wrote and BAFU's processes disagree.  For `Chromium` to unspecified
water, 122 exchanges write 7440-47-3, one writes 18540-29-9, and nine write no
number.  The merge reads `cas_numbers[0]`, the five-digit ion numbers sort before
7439- and 7440-, and the one stray exchange decided the substance for all 123.

This is the mirror of #146 and settled by the same argument.  There BAFU wrote
the metal's number beside `Cadmium II`, a name that states the ion, and the name
was the half that was right.  Here BAFU writes the ion's number beside
`Cadmium`, a name that states the element -- and unlike #146 the row also
carries the number the name implies, so reading it is a choice *between the
row's own two numbers* rather than a name overruling a number.

The two halves this file tests are the correction and its bounds: `Cadmium II`
keeps #146's ion, and a plain metal row that carries one number is not touched
by anything here.
"""

from __future__ import annotations

import unittest

import orjson
from structlog.testing import capture_logs

from brightway_flows.filesystem import PACKAGE_DATA_DIR
from brightway_flows.manual_fixes import apply_manual_fixes

FIXES = PACKAGE_DATA_DIR / "bafu-2026-v1-manual-fixes.json"

#: The eleven rows, by the uuid the extraction gives them.  Value is (name, the
#: compartment BAFU writes, the ion's number BAFU's stray exchanges wrote, the
#: element's number the rest of them wrote).  The pair is in the order the
#: extraction sorts them into, which is what the fix has to state as
#: `original_value`.
TWO_NUMBERS = {
    "af44881b-cae7-59b4-b73c-a4b647409e8e": (
        "Cadmium", ["emissions to air", "unspecified"], "22537-48-0", "7440-43-9"),
    "da9f3e9a-6c1e-50b2-87e2-b8b58face58d": (
        "Cadmium", ["emissions to water", "unspecified"], "22537-48-0", "7440-43-9"),
    "2516d6e7-cccb-5d0e-bd0e-4d9e9e1fb644": (
        "Chromium", ["emissions to water", "unspecified"], "18540-29-9", "7440-47-3"),
    "c43b26cb-6d32-531a-8fa9-8326b7fb3769": (
        "Lead", ["emissions to air", "unspecified"], "14280-50-3", "7439-92-1"),
    "f1c672b2-8985-5284-a33e-31cf848d6c92": (
        "Lead", ["emissions to water", "unspecified"], "14280-50-3", "7439-92-1"),
    "4a154714-6351-5214-911b-86f0b14651cb": (
        "Mercury", ["emissions to air", "unspecified"], "14302-87-5", "7439-97-6"),
    "13950d9f-3a5a-5c3b-a06e-6bb5c4d3773b": (
        "Mercury", ["emissions to water", "unspecified"], "14302-87-5", "7439-97-6"),
    "3594cf14-d0b1-501e-85eb-e68edd947d38": (
        "Nickel", ["emissions to air", "unspecified"], "14701-22-5", "7440-02-0"),
    "bfc2cd90-0167-577d-baf7-e50dc7406b61": (
        "Nickel", ["emissions to water", "unspecified"], "14701-22-5", "7440-02-0"),
    "298fecf8-66c5-51e8-b119-cc827975d0af": (
        "Zinc", ["emissions to air", "unspecified"], "23713-49-7", "7440-66-6"),
    "2697f2ad-7044-587c-90a8-d5e47f84e1f1": (
        "Zinc", ["emissions to water", "unspecified"], "23713-49-7", "7440-66-6"),
}

#: The twelfth row the extraction reports as ambiguous, and the one deliberately
#: left alone.  `2025884` is not a registry number in any format -- no check
#: digit, no hyphens -- and the row reaches `Sulfur Dioxide` on its EC number
#: either way, so nothing about the substance is in doubt and there is nothing
#: for a correction to decide.
SULFUR_DIOXIDE = "11423c5b-6002-549f-8bab-ecebaaf50287"


def _fixes():
    return orjson.loads(FIXES.read_bytes())["fixes"]


def _by_uuid():
    out = {}
    for fix in _fixes():
        uuid = (fix.get("match") or {}).get("uuid") or fix.get("uuid")
        if uuid:
            out.setdefault(uuid, []).append(fix)
    return out


def _rows():
    """The eleven rows as the extraction ships them, plus the ones nearby."""
    rows = [
        {"uuid": uuid, "name": name, "source": "bafu-2026-v1", "context": context,
         "unit": "kg", "cas_numbers": sorted({ion, element})}
        for uuid, (name, context, ion, element) in TWO_NUMBERS.items()
    ]
    rows.append({
        # #146's row: the ion named as an ion, and given the ion's number there.
        "uuid": "16d4462f-0000-0000-0000-000000000000", "name": "Cadmium II",
        "source": "bafu-2026-v1", "context": ["emissions to air", "high. pop."],
        "unit": "kg", "cas_numbers": ["22537-48-0"],
    })
    rows.append({
        # A plain metal row in another compartment: one number, and right.
        "uuid": "f74c6254-621f-5410-92e7-89136f8df81d", "name": "Chromium",
        "source": "bafu-2026-v1", "context": ["emissions to water", "river"],
        "unit": "kg", "cas_numbers": ["7440-47-3"],
    })
    rows.append({
        "uuid": SULFUR_DIOXIDE, "name": "Sulfur dioxide", "source": "bafu-2026-v1",
        "context": ["emissions to air", "unspecified"], "unit": "kg",
        "cas_numbers": ["2025884", "7446-09-5"],
    })
    return rows


class EachRowIsGivenTheNumberItsNameStates(unittest.TestCase):
    """The half the issue is about."""

    def setUp(self):
        self.fixes = _by_uuid()

    def test_each_of_the_eleven_has_exactly_one_fix(self):
        for uuid, (name, context, _, _) in TWO_NUMBERS.items():
            with self.subTest(name=name, context=context[0]):
                self.assertEqual(
                    len(self.fixes.get(uuid, [])), 1,
                    f"{name} in {context} needs one registry-number fix and no more",
                )

    def test_the_fix_records_both_numbers_and_keeps_the_element(self):
        # `original_value` is the pair, not the ion alone: what is being
        # corrected is an ambiguity BAFU shipped, and a fix that named one
        # number would read as though BAFU had stated only that one.
        for uuid, (name, _, ion, element) in TWO_NUMBERS.items():
            with self.subTest(name=name, uuid=uuid):
                fix = self.fixes[uuid][0]
                self.assertEqual(fix["field"], "cas_numbers")
                self.assertEqual(fix["original_value"], sorted({ion, element}))
                self.assertEqual(fix["new_value"], [element])

    def test_the_element_number_is_the_one_bafu_writes_elsewhere(self):
        # The number kept is not chosen from the pair by shape -- it is the one
        # BAFU's other twelve or thirteen rows for the same name carry, in every
        # other compartment.  Six metals, six numbers, and no two the same.
        elements = {name: element for name, _, _, element in TWO_NUMBERS.values()}
        self.assertEqual(elements, {
            "Cadmium": "7440-43-9", "Chromium": "7440-47-3", "Lead": "7439-92-1",
            "Mercury": "7439-97-6", "Nickel": "7440-02-0", "Zinc": "7440-66-6",
        })
        self.assertEqual(len(set(elements.values())), 6)

    def test_each_states_its_reasoning(self):
        for uuid, (name, _, _, _) in TWO_NUMBERS.items():
            with self.subTest(name=name):
                self.assertTrue(self.fixes[uuid][0].get("comment", "").strip())

    def test_applying_the_file_leaves_one_number_on_each_row(self):
        rows = {row["uuid"]: row for row in apply_manual_fixes(_rows(), FIXES)}
        for uuid, (name, _, ion, element) in TWO_NUMBERS.items():
            with self.subTest(name=name, uuid=uuid):
                self.assertEqual(rows[uuid]["cas_numbers"], [element])
                self.assertNotIn(ion, rows[uuid]["cas_numbers"])

    def test_applying_it_twice_changes_nothing_and_says_nothing(self):
        # The base list applies its fixes at extract and again when the
        # transform reads the derived file back (#237).  Keyed on the uuid
        # rather than on the number being rewritten, the second pass matches the
        # same rows and finds them already correct -- so no fix here can produce
        # the `manual_fix_matched_nothing` warning, which is the one signal a
        # curator has that a fix has gone stale.
        once = apply_manual_fixes(_rows(), FIXES)
        with capture_logs() as logs:
            twice = apply_manual_fixes(once, FIXES)
        rows = {row["uuid"]: row for row in twice}
        for uuid, (_, _, _, element) in TWO_NUMBERS.items():
            self.assertEqual(rows[uuid]["cas_numbers"], [element])
        stale = [
            entry for entry in logs
            if entry.get("event") == "manual_fix_matched_nothing"
            and (entry.get("criteria") or {}).get("uuid") in TWO_NUMBERS
        ]
        self.assertEqual(stale, [])


class TheRowsAroundThemAreLeftAlone(unittest.TestCase):
    """The half that stops this becoming a rule that reads every metal as its
    element."""

    def setUp(self):
        self.rows = {row["uuid"]: row for row in apply_manual_fixes(_rows(), FIXES)}

    def test_the_ion_bafu_names_as_an_ion_keeps_the_ions_number(self):
        # #146's row, and the reason the eleven above are safe: BAFU has a
        # spelling for the ion, so reading `Cadmium` as the metal does not cost
        # the list a way to say cadmium(2+).
        self.assertEqual(
            self.rows["16d4462f-0000-0000-0000-000000000000"]["cas_numbers"],
            ["22537-48-0"],
        )

    def test_a_metal_row_carrying_one_number_is_untouched(self):
        # Keyed on the uuid, so the twelve other `Chromium` rows -- which are
        # already right -- cannot be caught by a criterion that named the name.
        self.assertEqual(
            self.rows["f74c6254-621f-5410-92e7-89136f8df81d"]["cas_numbers"],
            ["7440-47-3"],
        )

    def test_sulfur_dioxide_keeps_both_of_its_numbers(self):
        # The twelfth ambiguous row, and not a substance question: `2025884` is
        # not a registry number and the row reaches `Sulfur Dioxide` on its EC
        # number regardless.  Here so that a later sweep of "rows with two
        # numbers" has to decide about this one on its own evidence.
        self.assertEqual(
            self.rows[SULFUR_DIOXIDE]["cas_numbers"], ["2025884", "7446-09-5"],
        )

    def test_no_fix_selects_a_bare_metal_name_without_a_uuid(self):
        # A fix matching `{"name": "Cadmium"}` alone would rewrite all fifteen
        # BAFU cadmium rows, including the thirteen that are already right, and
        # would stop matching on the second pass.  The name is in the criteria
        # of the eleven to say which row each one is about and to fail loudly if
        # an extraction ever moved a uuid; the uuid is what keeps the fix to the
        # one row measured, so the two are only ever written together.
        metals = {name for name, _, _, _ in TWO_NUMBERS.values()}
        for fix in _fixes():
            criteria = fix.get("match") or {}
            if criteria.get("name") in metals:
                with self.subTest(name=criteria["name"]):
                    self.assertIn("uuid", criteria)


if __name__ == "__main__":
    unittest.main()
