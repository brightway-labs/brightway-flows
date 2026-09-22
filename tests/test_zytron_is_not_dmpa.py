"""`DMPA` is an abbreviation three unrelated substances answer to.

EF 3.1 publishes one of them -- the herbicide Zytron, CAS 299-85-4 -- under the
abbreviation alone, over 13 flows.  The others are 3,4-dimethoxy-L-phenylalanine
and medroxyprogesterone acetate, and a fourth reading is a coatings monomer.  The
registry number the list carries was already right; the name was what nobody
could resolve, including the pipeline: `commonchem_cas_review` raised a blocking
`cas-ambiguous` item because `dmpa` matches two ChEBI records and neither of them
carries 299-85-4 (#320).

This is about the rename as *data*.  What the build publishes is
`expectations/0577-zytron-is-not-dmpa.json`.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import orjson

from brightway_flows.filesystem import PACKAGE_DATA_DIR
from brightway_flows.manual_fixes import RETAIN_ORIGINAL_KEY, apply_manual_fixes

FIXES = PACKAGE_DATA_DIR / "ef-3.1-manual-fixes.json"

#: What EF 3.1 ships as the name, before the title-caser makes it `Dmpa`.
SHIPPED = "dmpa"
PUBLISHED = "Zytron"
CAS = "299-85-4"


def _fixes() -> list[dict]:
    return orjson.loads(FIXES.read_bytes())["fixes"]


def _rename() -> dict | None:
    for fix in _fixes():
        if fix.get("field") == "name" and (fix.get("match") or {}).get("name") == SHIPPED:
            return fix
    return None


def _write(tmp: str, fixes: list[dict]) -> Path:
    path = Path(tmp) / "fixes.json"
    path.write_bytes(orjson.dumps({"schema_version": 1, "fixes": fixes}))
    return path


class TheRenameIsStatedTestCase(unittest.TestCase):
    def setUp(self):
        self.fix = _rename()

    def test_there_is_a_rename(self):
        self.assertIsNotNone(self.fix, "no rename for EF 3.1's `dmpa` flows")

    def test_it_publishes_the_substance_name(self):
        self.assertEqual(self.fix["new_value"], PUBLISHED)

    def test_it_matches_the_name_the_source_ships(self):
        """EF ships `dmpa`; `Dmpa` is what the name caser makes of it later."""
        self.assertEqual(self.fix["match"]["name"], SHIPPED)

    def test_the_abbreviation_is_not_retained_as_a_synonym(self):
        """Three substances in this list answer to `DMPA`.

        The flag asserts that the replaced string is a name the substance
        genuinely has and only the preferred one was wrong.  `DMPA` is not
        that: dimethylolpropionic acid (4767-03-7) and the photoinitiator
        2,2-dimethoxy-2-phenylacetophenone (24650-42-8) carry it too, thirteen
        flows each.  Publishing it as a synonym for the herbicide would assert
        exactly what the rename denies, and #113's rule would withdraw it in
        any case.
        """
        self.assertNotIn(RETAIN_ORIGINAL_KEY, self.fix)

    def test_it_says_the_abbreviation_is_shared(self):
        comment = self.fix["comment"]
        for fragment in ("4767-03-7", "24650-42-8"):
            with self.subTest(fragment):
                self.assertIn(fragment, comment)

    def test_it_says_why_the_abbreviation_is_not_a_name(self):
        comment = self.fix["comment"]
        for fragment in ("medroxyprogesterone", "3,4-dimethoxy", "#320"):
            with self.subTest(fragment):
                self.assertIn(fragment, comment)

    def test_it_records_that_the_number_was_already_right(self):
        self.assertIn(CAS, self.fix["comment"])


class TheRenameOnlyTouchesThisSubstanceTestCase(unittest.TestCase):
    def setUp(self):
        self.fix = _rename()

    def test_a_dmpa_flow_is_renamed_and_does_not_keep_the_abbreviation(self):
        flow = {"uuid": "u-1", "name": SHIPPED, "cas_numbers": [CAS]}
        with tempfile.TemporaryDirectory() as tmp:
            apply_manual_fixes([flow], _write(tmp, [self.fix]))
        self.assertEqual(flow["name"], PUBLISHED)
        retained = [
            entry.get("@value") if isinstance(entry, dict) else entry
            for entry in flow.get("altLabel") or []
        ]
        self.assertNotIn(SHIPPED, retained)

    def test_a_flow_whose_name_merely_contains_dmpa_is_untouched(self):
        """The match is the whole name, not a substring of one."""
        flow = {"uuid": "u-1", "name": "dmpa-related thing", "cas_numbers": []}
        with tempfile.TemporaryDirectory() as tmp:
            apply_manual_fixes([flow], _write(tmp, [self.fix]))
        self.assertEqual(flow["name"], "dmpa-related thing")

    def test_applying_it_twice_changes_nothing_further(self):
        """The base list applies its own fixes twice (#237)."""
        flow = {"uuid": "u-1", "name": SHIPPED, "cas_numbers": [CAS]}
        with tempfile.TemporaryDirectory() as tmp:
            path = _write(tmp, [self.fix])
            apply_manual_fixes([flow], path)
            once = dict(flow)
            apply_manual_fixes([flow], path)
        self.assertEqual(flow, once)

    def test_the_registry_number_is_not_touched(self):
        """The number was already right; only the name was ambiguous."""
        self.assertEqual(self.fix["field"], "name")
        flow = {"uuid": "u-1", "name": SHIPPED, "cas_numbers": [CAS]}
        with tempfile.TemporaryDirectory() as tmp:
            apply_manual_fixes([flow], _write(tmp, [self.fix]))
        self.assertEqual(flow["cas_numbers"], [CAS])


if __name__ == "__main__":
    unittest.main()
