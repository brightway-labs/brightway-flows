"""The code table that reads a refrigerant's identity out of its own factor.

EF 3.1 names a family of refrigerants, blowing agents and heat-transfer fluids
by their industry code and gives them no identifier of any kind.  #19's first
pass cleared most of them by asking PubChem whether any record listed the code
among its own synonyms; twenty-one were left, and every one of them was left for
the same reason -- PubChem holds no record carrying the code, so there was
nothing to cite.

What identifies them is the characterisation factor.  EF 3.1's `Climate change`
category is a transcription of IPCC AR6 WGI Table 7.SM.7, and that table prints
the industry designation, the chemical structure and the GWP100 on one line, so
a flow EF names only `HFE-143a` still carries the number 616 -- and AR6's
`HFE-143a` row is CH3OCF3 at 616.

This file is about that table as *data*: what is in it, what is deliberately
not, and the property every entry has to have.  What the fixes then do to a row
is `test_manual_fixes.py`'s job, and what the build publishes is
`expectations/0202-refrigerants-from-their-factors.json`'s.
"""

from __future__ import annotations

import re
import tempfile
import unittest
from pathlib import Path

import orjson

from brightway_flows.filesystem import PACKAGE_DATA_DIR
from brightway_flows.manual_fixes import apply_manual_fixes

FIXES = PACKAGE_DATA_DIR / "ef-3.1-manual-fixes.json"

#: A well-formed registry number, with the check digit's position fixed.  Not
#: the check digit itself: a typo that survives the arithmetic is caught by the
#: comment naming a PubChem record, which a reader can open.
CAS = re.compile(r"^\d{2,7}-\d{2}-\d$")

#: The twenty identifications the factor made possible, and the GWP100 that
#: made each one.  The number is AR6 Table 7.SM.7's for the row named beside it
#: and EF 3.1's for the flow named by the key; the identification is that the
#: two are the same number.  Written here rather than parsed out of the comments
#: so that a change to either side has to be made twice, deliberately.
FROM_THE_FACTOR = {
    "HFE-143a": ("421-14-7", "616"),
    "HFE-216": ("1187-93-5", "0.01"),
    "Halon-2301": ("421-06-7", "177"),
    "HCFC-132c": ("1842-05-3", "342"),
    "HFC-227ca": ("2252-84-8", "2980"),
    "HFC-263fb": ("421-07-8", "74.8"),
    "HFC-1243zf": ("677-21-4", "0.261"),
    "HFE-263m1": ("690-22-2", "29.2"),
    "PFC-61-16": ("335-57-9", "8410"),
    "PFC-71-18": ("307-34-6", "8260"),
    "n-HFE-7100": ("163702-07-6", "544"),
    "i-HFE-7100": ("163702-08-7", "437"),
    "n-HFE-7200": ("163702-05-4", "60.7"),
    "(E)-HFC-1234ze": ("29118-24-9", "1.37"),
    "(Z)-HFC-1234ze": ("29118-25-0", "0.315"),
    "(Z)-HFC-1225ye": ("5528-43-8", "0.344"),
    "(Z)-HFC-1336": ("692-49-9", "2.08"),
    "1,1′-Oxybis[2-(difluoromethoxy)-1,1,2,2-tetrafluoroethane]": (
        "205367-61-9", "5730",
    ),
    "Perfluorodecalin (cis)": ("60433-11-6", "7800"),
    "Perfluorodecalin (trans)": ("60433-12-7", "7120"),
}

#: Left unidentified on purpose, and why.  A later change that gives one of
#: these a number is a regression unless it also answers the reason.
HELD_BACK = {
    "i-HFE-7200": (
        "163702-06-5 is already on EF's `HFE-7200`, the commercial mixture of "
        "the n- and i- ethers; asserting it merges a mixture with a component"
    ),
    "HG-10": "no characterisation factor, so no fingerprint",
    "HG-30": "no characterisation factor, so no fingerprint",
    "H-Galden 1040x": "no characterisation factor, so no fingerprint",
    "Halon-2404": "no characterisation factor, so no fingerprint",
    "PFC-c216": "no characterisation factor, so no fingerprint",
    "HFE-236ca": "no characterisation factor, so no fingerprint",
}

#: Pairs that a synonym search collapses onto one record and the factor keeps
#: apart.  Each is two EF flows with two GWP100s, so a table that gave them one
#: number would be publishing one substance where the list characterises two.
KEPT_APART = (
    ("(E)-HFC-1234ze", "(Z)-HFC-1234ze"),
    ("Perfluorodecalin (cis)", "Perfluorodecalin (trans)"),
)


def _fixes() -> list[dict]:
    return orjson.loads(FIXES.read_bytes())["fixes"]


def _by_name() -> dict[str, dict]:
    """The `cas_numbers` fixes of this file, keyed on the name each matches."""
    found = {}
    for fix in _fixes():
        if fix.get("field") != "cas_numbers" or "new_value" not in fix:
            continue
        name = (fix.get("match") or {}).get("name")
        if name is not None:
            found[name] = fix
    return found


def _write(tmp: str, fixes: list[dict]) -> Path:
    path = Path(tmp) / "fixes.json"
    path.write_bytes(orjson.dumps({"schema_version": 1, "fixes": fixes}))
    return path


class TheTableIsCompleteTestCase(unittest.TestCase):
    """Every designation the factor identified is in the file, once."""

    def setUp(self):
        self.by_name = _by_name()

    def test_every_identification_is_stated(self):
        for name, (cas, _) in FROM_THE_FACTOR.items():
            with self.subTest(name):
                fix = self.by_name.get(name)
                self.assertIsNotNone(fix, f"{name} has no entry")
                self.assertEqual(fix["new_value"], [cas])

    def test_each_entry_asserts_exactly_one_number(self):
        for name in FROM_THE_FACTOR:
            with self.subTest(name):
                self.assertEqual(len(self.by_name[name]["new_value"]), 1)

    def test_every_number_is_well_formed(self):
        for name, (cas, _) in FROM_THE_FACTOR.items():
            with self.subTest(name):
                self.assertRegex(cas, CAS)

    def test_no_two_designations_take_the_same_number(self):
        """Two codes on one number would publish two substances as one.

        They may share a number with a flow EF 3.1 already names by its
        chemistry -- six of them do, and that sharing is the point, because it
        says the source entered one substance twice.  Sharing with each other
        is the failure.
        """
        numbers = [cas for cas, _ in FROM_THE_FACTOR.values()]
        self.assertEqual(len(numbers), len(set(numbers)))

    def test_the_pairs_a_synonym_search_would_merge_stay_apart(self):
        for first, second in KEPT_APART:
            with self.subTest(f"{first} / {second}"):
                self.assertNotEqual(
                    self.by_name[first]["new_value"],
                    self.by_name[second]["new_value"],
                )


class TheDamagedLabelIsRepairedBeforeItIsIdentifiedTestCase(unittest.TestCase):
    """The fifth damaged label, and the ordering the repair depends on.

    Deduplication keeps the designation-side flows and deprecates EF's own
    `HG-02` rows onto them, so the corrupted string becomes the published name
    of four live flows the moment the two share a substance.  The repair is not
    cosmetic, and it has to be applied before the registry number is, because
    the number's fix matches on the name.
    """

    DAMAGED = "1,1-Oxybis[2-(difluoromethoxy)-1,1,2,2-tetrafluoroethane"
    REPAIRED = "1,1′-Oxybis[2-(difluoromethoxy)-1,1,2,2-tetrafluoroethane]"
    UUIDS = frozenset({
        "7d11f8ca-e251-11e6-bf01-fe55135034f3",
        "7d11fab4-e251-11e6-bf01-fe55135034f3",
        "7d11fc58-e251-11e6-bf01-fe55135034f3",
        "7d11fdfc-e251-11e6-bf01-fe55135034f3",
    })

    def setUp(self):
        self.fixes = _fixes()
        self.renames = [
            fix for fix in self.fixes
            if fix.get("field") == "name" and fix.get("uuid") in self.UUIDS
        ]

    def test_all_four_compartments_are_repaired(self):
        self.assertEqual({fix["uuid"] for fix in self.renames}, self.UUIDS)

    def test_each_repair_states_the_string_it_replaces(self):
        for fix in self.renames:
            with self.subTest(fix["uuid"]):
                self.assertEqual(fix["original_value"], self.DAMAGED)
                self.assertEqual(fix["new_value"], self.REPAIRED)

    def test_the_corrupted_string_is_not_kept_as_a_synonym(self):
        """A corrupted spelling is not a name the substance has."""
        for fix in self.renames:
            with self.subTest(fix["uuid"]):
                self.assertNotIn("retain_original_as_synonym", fix)

    def test_the_repair_is_applied_before_the_number(self):
        """Otherwise the CAS fix, which matches on the name, matches nothing."""
        rename_positions = [
            index for index, fix in enumerate(self.fixes)
            if fix.get("uuid") in self.UUIDS and fix.get("field") == "name"
        ]
        cas_position = next(
            index for index, fix in enumerate(self.fixes)
            if (fix.get("match") or {}).get("name") == self.REPAIRED
        )
        self.assertLess(max(rename_positions), cas_position)

    def test_the_number_matches_on_the_repaired_name(self):
        names = {(fix.get("match") or {}).get("name") for fix in self.fixes}
        self.assertIn(self.REPAIRED, names)
        self.assertNotIn(self.DAMAGED, names)

    def test_the_two_fixes_applied_in_order_leave_one_repaired_row(self):
        flow = {
            "uuid": "7d11fdfc-e251-11e6-bf01-fe55135034f3",
            "name": self.DAMAGED,
            "cas_numbers": [],
        }
        table = [
            fix for fix in self.fixes
            if fix.get("uuid") in self.UUIDS
            or (fix.get("match") or {}).get("name") == self.REPAIRED
        ]
        with tempfile.TemporaryDirectory() as tmp:
            apply_manual_fixes([flow], _write(tmp, table))
        self.assertEqual(flow["name"], self.REPAIRED)
        self.assertEqual(flow["cas_numbers"], ["205367-61-9"])


class WhatIsDeliberatelyAbsentTestCase(unittest.TestCase):
    """The counterweight, and the reason this is a table rather than a rule."""

    def setUp(self):
        self.by_name = _by_name()

    def test_the_held_back_designations_have_no_entry(self):
        for name, reason in HELD_BACK.items():
            with self.subTest(name):
                self.assertNotIn(name, self.by_name, reason)

    def test_the_mixtures_number_is_not_asserted_on_a_component(self):
        """`i-HFE-7200` is the one where identifying it would do damage.

        163702-06-5 is the right number for ethyl perfluoroisobutyl ether and
        also the number EF 3.1 carries on `HFE-7200`, the commercial mixture of
        the n- and i- ethers.  Nothing in this file may put it on a second flow.
        """
        for name, fix in self.by_name.items():
            with self.subTest(name):
                self.assertNotIn("163702-06-5", fix["new_value"])


class EveryEntryCarriesItsEvidenceTestCase(unittest.TestCase):
    """A number without its evidence is indistinguishable from a guess.

    These entries are unusual in this file: they were arrived at from a
    published table of factors rather than from a database lookup, so a reader
    who cannot see the chain has no way to check the answer.
    """

    def setUp(self):
        self.by_name = _by_name()

    def test_each_comment_quotes_the_factor_that_identified_it(self):
        for name, (_, gwp) in FROM_THE_FACTOR.items():
            with self.subTest(name):
                self.assertIn(gwp, self.by_name[name]["comment"])

    def test_each_comment_names_the_table_the_factor_came_from(self):
        for name in FROM_THE_FACTOR:
            with self.subTest(name):
                self.assertIn("7.SM.7", self.by_name[name]["comment"])

    def test_each_comment_names_the_record_the_number_came_from(self):
        for name in FROM_THE_FACTOR:
            with self.subTest(name):
                self.assertIn("PubChem CID", self.by_name[name]["comment"])

    def test_each_entry_says_which_issue_it_answers(self):
        for name in FROM_THE_FACTOR:
            with self.subTest(name):
                self.assertIn("#19", self.by_name[name]["comment"])


class TheFixFillsABlankAndNothingElseTestCase(unittest.TestCase):
    """Both halves of a rule that refines an unstated value.

    The whole table is guarded by `original_value: []`, which is what makes it
    a fill-in rather than an override.  A later edit dropping that guard would
    turn twenty entries into twenty rewrites of whatever the source ships, and
    only the second test here notices.
    """

    def setUp(self):
        self.by_name = _by_name()

    def test_every_entry_declares_the_blank_it_fills(self):
        for name in FROM_THE_FACTOR:
            with self.subTest(name):
                self.assertEqual(self.by_name[name].get("original_value"), [])

    def test_a_row_with_no_number_gets_one(self):
        flow = {"uuid": "u-1", "name": "HFE-143a", "cas_numbers": []}
        with tempfile.TemporaryDirectory() as tmp:
            apply_manual_fixes([flow], _write(tmp, [self.by_name["HFE-143a"]]))
        self.assertEqual(flow["cas_numbers"], ["421-14-7"])

    def test_a_row_that_already_states_one_is_left_alone(self):
        """The half that stops the table growing into an override.

        If EF 3.1 ever ships `HFE-143a` with a registry number of its own, that
        number is the source's and this file has no business replacing it
        silently -- the disagreement is what somebody should be shown.
        """
        flow = {"uuid": "u-1", "name": "HFE-143a", "cas_numbers": ["420-46-2"]}
        with tempfile.TemporaryDirectory() as tmp:
            apply_manual_fixes([flow], _write(tmp, [self.by_name["HFE-143a"]]))
        self.assertEqual(flow["cas_numbers"], ["420-46-2"])

    def test_applying_the_whole_table_twice_changes_nothing_further(self):
        """The base list applies its own fixes twice (#237)."""
        flows = [
            {"uuid": f"u-{index}", "name": name, "cas_numbers": []}
            for index, name in enumerate(FROM_THE_FACTOR)
        ]
        table = [self.by_name[name] for name in FROM_THE_FACTOR]
        with tempfile.TemporaryDirectory() as tmp:
            path = _write(tmp, table)
            apply_manual_fixes(flows, path)
            once = [dict(flow) for flow in flows]
            apply_manual_fixes(flows, path)
        self.assertEqual(flows, once)

    def test_a_row_of_another_name_is_untouched(self):
        """`HFC-143a` shares the number in the code and nothing else.

        It is 1,1,1-trifluoroethane, CAS 420-46-2, and AR6 gives it 5810
        against the ether's 616.  A fix matching loosely on the digits would
        reach it.
        """
        flow = {"uuid": "u-1", "name": "HFC-143a", "cas_numbers": []}
        with tempfile.TemporaryDirectory() as tmp:
            apply_manual_fixes([flow], _write(tmp, [self.by_name["HFE-143a"]]))
        self.assertEqual(flow["cas_numbers"], [])


if __name__ == "__main__":
    unittest.main()
