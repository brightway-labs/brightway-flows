"""A charged form BAFU spells its own way reaches the substance the list has.

#127: `Arsenic V` and `Arsenic(5+)` are one substance published twice, and seven
charged forms are doubled the same way.  Every one of them comes from BAFU,
carries no registry number, and is minted rather than matched -- while the
substance beside it carries the characterisation factors.

The evidence that this is a missing reading rather than a wrong rule is BAFU's
own `Chromium III`, which is spelled exactly the way `Arsenic V` is and reaches
`Chromium(3+)` correctly, **because it carries a number**.  So the correction
gives each row the number its stated charge already implies, which is what #119
did for `Anhydrite`.

Two rows are deliberately left alone and the last case is what says so: `Iron,
ion` and `Arsenic, Ion` state no charge, and iron II and iron III are different
substances.  Reaching one of them because it is commoner would be inventing a
fact the source list did not state.

#146 adds the third population: five rows -- `Cadmium II`, `Zinc II`, `Mercury
II`, `Lead II`, `Nickel II` -- that state a charge *and* a number, and the two
contradict each other, because BAFU wrote the metal's number beside the ion's
name.  Those fixes replace a stated value, which is a stronger claim, and the
class for them says why it is still the right one.
"""

from __future__ import annotations

import unittest

import orjson

from brightway_flows.filesystem import PACKAGE_DATA_DIR

FIXES = PACKAGE_DATA_DIR / "bafu-2026-v1-manual-fixes.json"

#: The five rows whose charge is stated, and the number that charge implies.
#: Read off the substances this list already publishes rather than typed from
#: memory: each is the registry number on the flow object the row should reach.
CHARGE_IS_STATED = {
    "Arsenic V": "17428-41-0",
    "Vanadium V": "22537-31-1",
    "Tin (II)": "22541-90-8",
    "Calcium II": "14127-61-8",
    "Perchlorate, ion": "14797-73-0",
}

#: The two that state a charged form and not which charge.  `Iron, ion` is iron
#: II or iron III; `Arsenic, Ion` is arsenic III or arsenic V.  Both are real
#: substances with different numbers and different factors, and nothing in the
#: row says which is meant.
CHARGE_IS_NOT_STATED = ("Iron, ion", "Arsenic, ion")

#: #146: the five rows whose stated charge and stated number contradict each
#: other.  Name -> (the metal's number BAFU wrote, the ion's number the name
#: implies).  The second is read off the substance ecoinvent's fourteen
#: same-named rows already reach, not typed from memory.
NUMBER_CONTRADICTS_THE_NAME = {
    "Cadmium II": ("7440-43-9", "22537-48-0"),
    "Zinc II": ("7440-66-6", "23713-49-7"),
    "Mercury II": ("7439-97-6", "14302-87-5"),
    "Lead II": ("7439-92-1", "14280-50-3"),
    "Nickel II": ("7440-02-0", "14701-22-5"),
}


def _fixes():
    return orjson.loads(FIXES.read_bytes())["fixes"]


def _by_name():
    out = {}
    for fix in _fixes():
        name = (fix.get("match") or {}).get("name")
        if name:
            out.setdefault(name, []).append(fix)
    return out


class EveryStatedChargeGetsItsNumber(unittest.TestCase):
    """The half the issue is about."""

    def setUp(self):
        self.fixes = _by_name()

    def test_each_of_the_five_has_exactly_one_fix(self):
        for name in CHARGE_IS_STATED:
            with self.subTest(name=name):
                self.assertEqual(
                    len(self.fixes.get(name, [])), 1,
                    f"{name} needs one registry-number fix and no more",
                )

    def test_the_number_is_the_one_that_charge_implies(self):
        for name, number in CHARGE_IS_STATED.items():
            with self.subTest(name=name):
                fix = self.fixes[name][0]
                self.assertEqual(fix["field"], "cas_numbers")
                self.assertEqual(fix["new_value"], [number])

    def test_each_states_that_the_row_carried_no_number(self):
        # `original_value: null` is the assertion this is filling a gap rather
        # than overruling BAFU.  A fix that replaced a number BAFU stated would
        # be a different claim needing different reasoning, and #127's argument
        # -- that the spelling goes unread *because* the number is missing --
        # would not support it.
        for name in CHARGE_IS_STATED:
            with self.subTest(name=name):
                self.assertIsNone(self.fixes[name][0]["original_value"])

    def test_each_states_its_reasoning(self):
        for name in CHARGE_IS_STATED:
            with self.subTest(name=name):
                self.assertTrue(self.fixes[name][0].get("comment", "").strip())


class AnUnstatedChargeIsLeftAlone(unittest.TestCase):
    """The half that stops this becoming a rule that guesses."""

    def setUp(self):
        self.fixes = _by_name()

    def test_neither_is_given_a_number(self):
        # The point of the test: iron II and iron III are different substances,
        # and picking the commoner one would be inventing a fact.  A later
        # change that "finished" #127 by giving these two numbers should fail
        # here and be made to argue for itself.
        for name in CHARGE_IS_NOT_STATED:
            with self.subTest(name=name):
                self.assertNotIn(
                    name, self.fixes,
                    f"{name} states no charge, so no registry number follows "
                    f"from it; giving it one is a decision needing its own "
                    f"reasoning",
                )

    def test_the_two_are_the_only_ones_left_open(self):
        # Stated so that a further doubled form appearing -- a new BAFU release,
        # or one this sweep missed -- is a visible change rather than a quietly
        # longer list of substances published twice.
        self.assertEqual(len(CHARGE_IS_STATED) + len(CHARGE_IS_NOT_STATED), 7)


class AStatedNumberThatContradictsTheNameIsReplaced(unittest.TestCase):
    """#146: the stronger claim the `original_value: null` test above says
    needs its own reasoning.

    These five rows are not missing a number; they carry the wrong one.  BAFU
    writes the metal's registry number beside a name that states the +2 ion,
    while ecoinvent writes the ion's number beside the very same name -- so one
    name reached two substances depending on which list wrote it.  #127's
    argument (the spelling goes unread *because* the number is missing) does
    not cover this; the argument here is that the name and the number
    contradict each other and the name is the half that is right, which is
    the EF `vanadium (v)` precedent (#49).  `original_value` is what makes
    that a recorded replacement rather than a silent one.
    """

    def setUp(self):
        self.fixes = _by_name()

    def test_each_of_the_five_has_exactly_one_fix(self):
        for name in NUMBER_CONTRADICTS_THE_NAME:
            with self.subTest(name=name):
                self.assertEqual(
                    len(self.fixes.get(name, [])), 1,
                    f"{name} needs one registry-number fix and no more",
                )

    def test_the_fix_records_what_bafu_wrote_and_what_the_name_implies(self):
        for name, (metal, ion) in NUMBER_CONTRADICTS_THE_NAME.items():
            with self.subTest(name=name):
                fix = self.fixes[name][0]
                self.assertEqual(fix["field"], "cas_numbers")
                # Not `null`: this overrules a stated number, and says so.
                self.assertEqual(fix["original_value"], [metal])
                self.assertEqual(fix["new_value"], [ion])

    def test_the_replacement_is_a_different_substance_not_a_vintage(self):
        # A vintage correction (borax, mecoprop) swaps two numbers for one
        # substance.  These swap the metal for its ion, and the five ions are
        # five substances -- so no two fixes may share a number on either side.
        metals = [m for m, _ in NUMBER_CONTRADICTS_THE_NAME.values()]
        ions = [i for _, i in NUMBER_CONTRADICTS_THE_NAME.values()]
        self.assertEqual(len(set(metals)), 5)
        self.assertEqual(len(set(ions)), 5)
        self.assertFalse(set(metals) & set(ions))

    def test_each_states_its_reasoning(self):
        for name in NUMBER_CONTRADICTS_THE_NAME:
            with self.subTest(name=name):
                self.assertTrue(self.fixes[name][0].get("comment", "").strip())

    def test_no_plain_element_row_is_moved_onto_the_ion(self):
        # `Cadmium II` is corrected onto the ion; no row named `Cadmium` is.
        # This asked that no fix name a plain metal at all until #168, which
        # corrects eleven plain rows in the other direction: BAFU writes the
        # ion's number *and* the element's on one row per metal per medium, and
        # those fixes keep the element's.  So the claim is narrowed to what it
        # was always guarding -- a key loosened to a prefix, or a later sweep,
        # dragging the thirteen plain rows onto the ion -- rather than dropped.
        for name, (metal, ion) in NUMBER_CONTRADICTS_THE_NAME.items():
            element = name.split()[0]
            for fix in self.fixes.get(element, []):
                with self.subTest(name=element):
                    self.assertEqual(fix["field"], "cas_numbers")
                    self.assertEqual(fix["new_value"], [metal])
                    self.assertNotIn(ion, fix["new_value"])


class TheFixesAreTheShapeThisFileUses(unittest.TestCase):
    """The same shape #119 used for `Anhydrite`, which is the precedent."""

    def test_the_anhydrite_precedent_is_still_there(self):
        # If this ever goes away the five above have lost their argument, and
        # the reader of this file should find that out here.
        anhydrite = _by_name().get("Anhydrite", [])
        self.assertEqual(len(anhydrite), 1)
        self.assertEqual(anhydrite[0]["field"], "cas_numbers")
        self.assertIsNone(anhydrite[0]["original_value"])


if __name__ == "__main__":
    unittest.main()
