"""The whitelist that stops 70 substances being published under a part number.

EF 3.1 names 118 refrigerants, blowing agents and fire suppressants by their
industry designation -- `HFC-134a`, `CFC-12`, `Halon-1301`, counted on the
2026-08-17 build at commit 87a5918 -- and this project has ruled twice that a
part number is a worse published name than the chemistry.  The rule that would
propose the rename asks Common Chemistry and ChEBI the same question and acts
only when both answer, and ChEBI answers for six of the 118, so it never fires
for any of them (#104).

Rather than trust one database where the other is silent, the renames a curator
is confident of are written into `ef-3.1-manual-fixes.json` one at a time.  This
file is about that whitelist as *data*: what is in it, what is deliberately not,
and the property every entry has to have.  What the fixes then do to a row is
`test_manual_fixes.py`'s job, and what the build publishes is
`expectations/0521-designations-are-not-names.json`'s.
"""

from __future__ import annotations

import re
import unittest

import orjson

from brightway_flows.filesystem import PACKAGE_DATA_DIR
from brightway_flows.manual_fixes import RETAIN_ORIGINAL_KEY

FIXES = PACKAGE_DATA_DIR / "ef-3.1-manual-fixes.json"

#: A name that is itself an industry designation rather than chemistry.  Broader
#: than the one in `strip_catalogue_altlabels`, because here a false positive
#: costs a test failure somebody reads and a false negative costs a substance
#: published under the name the whitelist exists to replace.
DESIGNATION = re.compile(
    r"^(?:HFC|HCFC|CFC|HFO|HFE|PFC|FC|R|Halon|Freon)[ -]?\d", re.IGNORECASE
)

#: The renames the issue turns on, and the two it turns on *not* making.
NAMED_IN_THE_ISSUE = {
    "811-97-2": "1,1,1,2-Tetrafluoroethane",   # HFC-134a, 78 factors
    "306-83-2": "2,2-Dichloro-1,1,1-trifluoroethane",  # HCFC-123, 83 factors
    "75-71-8": "Dichlorodifluoromethane",      # CFC-12
    "74-83-9": "Bromomethane",                 # Halon-1001, 121 factors
    "354-33-6": "Pentafluoroethane",           # HFC-125
    "75-37-6": "1,1-Difluoroethane",           # HFC-152a
    "75-46-7": "Trifluoromethane",             # Hfc-23, the opening example
    "75-43-4": "Dichlorofluoromethane",        # HCFC-21
    "151-67-7": "Halothane",                   # Halon-2311, the stereo prefix
}

#: Registry numbers deliberately left alone, and why. Each is a substance whose
#: part number is a better published name than anything available, so a later
#: change that renames it is a regression and not an improvement.
HELD_BACK = {
    "26523-64-8": "CFC-113: `Trichlorotrifluoroethane` names either isomer",
    "29255-31-0": "CFC-214: `Tetrachlorotetrafluoropropane` names any of them",
    "25497-29-4": "HCFC-142: `Chlorodifluoroethane` names any of 142/142a/142b",
    "134190-50-4": "HCFC-244: `Chlorotetrafluoropropane` names any of them",
    "76-14-2": "CFC-114: Common Chemistry's name for it is `CFC 114`",
    "2837-89-0": "HCFC-124: Common Chemistry's name for it is `HCFC 124`",
    "762-49-2": "FC-151B1: `Ethane, 1-bromo-2-fluoro-` is the CAS index form",
    "430-55-7": "HCFC-271: `Propane, 1-chloro-1-fluoro-` is the index form",
    "420-45-1": "HFC-272ca: `Propane, 2,2-difluoro-` is the index form",
    "382-34-3": "four HFE-356 isomers share this number; one name for four",
    "406-78-0": "three HFE-347 isomers share this number",
    "1885-48-9": "three HFE-245 isomers share this number",
    "84011-06-3": "two HFE-236 isomers share this number",
    "163702-06-5": "HFE-7200 is a mixture; the CC name is one of its isomers",
}


def _name_fixes() -> list[dict]:
    payload = orjson.loads(FIXES.read_bytes())
    return [fix for fix in payload["fixes"] if fix.get("field") == "name"]


def _renames_by_cas() -> dict[str, dict]:
    """The #104 whitelist, keyed on the registry number each entry matches.

    Selected by the issue number in the comment rather than by the shape of the
    fix, because the file holds two other registry-keyed name fixes -- the
    thirteen `basic violet` rows and fluorescein's disodium salt -- and neither
    is a designation being replaced by chemistry.
    """
    out: dict[str, dict] = {}
    for fix in _name_fixes():
        cas = (fix.get("match") or {}).get("cas_numbers")
        if isinstance(cas, str) and "(#104)" in str(fix.get("comment") or ""):
            out[cas] = fix
    return out


class TheWhitelistTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.renames = _renames_by_cas()

    def test_the_substances_the_issue_names_are_renamed(self):
        for cas, expected in NAMED_IN_THE_ISSUE.items():
            with self.subTest(cas=cas):
                self.assertIn(cas, self.renames)
                self.assertEqual(self.renames[cas]["new_value"], expected)

    def test_none_of_them_is_renamed_to_another_designation(self):
        """The rename has to be an improvement, and `CFC-114` -> `CFC 114` is
        not one.  Two of the 118 fail this and are held back for it."""
        for cas, fix in self.renames.items():
            with self.subTest(cas=cas):
                self.assertIsNone(DESIGNATION.match(fix["new_value"]))

    def test_every_rename_keeps_the_part_number_searchable(self):
        """The designation is the only string an inventory written against
        EF 3.1 holds for the substance.  A rename that drops it makes the flow
        unfindable by the one name its user has, which is a worse outcome than
        publishing a part number."""
        for cas, fix in self.renames.items():
            with self.subTest(cas=cas):
                self.assertTrue(fix.get(RETAIN_ORIGINAL_KEY))

    def test_no_two_substances_are_renamed_to_one_name(self):
        """The failure the shared-registry-number exclusion exists to prevent:
        four HFE-356 isomers on one number would become four flows called
        `1,1,2,3,3,3-Hexafluoropropyl methyl ether`."""
        names = [fix["new_value"] for fix in self.renames.values()]
        self.assertEqual(len(names), len(set(names)))

    def test_the_substances_held_back_are_left_alone(self):
        """The other half, and the reason this is a whitelist rather than a
        rule: for each of these the chemical name available says less than the
        part number does, or is a part number itself."""
        for cas, why in HELD_BACK.items():
            with self.subTest(cas=cas, why=why):
                self.assertNotIn(cas, self.renames)

    def test_every_rename_says_what_it_is_for(self):
        """A curated rename is a claim about a substance, and a claim with no
        evidence attached is one nobody can check or revisit."""
        for cas, fix in self.renames.items():
            with self.subTest(cas=cas):
                self.assertIn(cas, fix["comment"])
                self.assertGreater(len(fix["comment"]), 200)

    def test_the_whitelist_is_the_size_it_says_it_is(self):
        """70 of the 118, counted on the 2026-08-17 build at commit 87a5918.
        Here so that adding one is a deliberate act with this file's five
        criteria re-read, rather than a line nobody notices."""
        self.assertEqual(len(self.renames), 70)

    def test_ef_s_second_name_for_the_fumigant_is_renamed_too(self):
        """The one entry keyed on a name rather than on a number.

        EF 3.1 ships CAS 74-83-9 twice, and gives the thirteen rows it calls
        `Methyl bromide` no registry number at all -- the number they carry is
        this project's identification (#19).  A fix keyed on 74-83-9 therefore
        reaches only half the rows, which leaves eleven live flows publishing
        `Methyl Bromide` under a substance published as `Bromomethane`: the
        member-stranded-on-another-name defect #221 and #245 each fixed once,
        reintroduced by a curated rename that stopped halfway.
        """
        by_name = {
            (fix.get("match") or {}).get("name"): fix
            for fix in _name_fixes()
            if "(#104)" in str(fix.get("comment") or "")
        }
        fix = by_name.get("Methyl bromide")
        self.assertIsNotNone(fix, "EF's second name for 74-83-9 is not renamed")
        self.assertEqual(fix["new_value"], "Bromomethane")
        self.assertTrue(fix.get(RETAIN_ORIGINAL_KEY))


if __name__ == "__main__":
    unittest.main()
