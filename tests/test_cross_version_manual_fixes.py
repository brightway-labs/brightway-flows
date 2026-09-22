"""A correction about a substance holds for every version that ships the row.

The substance-level corrections ecoinvent 3.12 carries -- Uranium-238's CAS,
`Silver-110`'s label, the three lindane isomers' CAS, Mefentrifluconazole's
missing CAS, and the name on 2436-73-9 -- are not statements about 3.12.
`7440-61-1` is uranium's registry number in 3.8 exactly as it is in 3.12, and
every registered version ships the same rows under the same UUIDs.  For five months only 3.12 and EF 3.1 had them,
so a build that merged two ecoinvent versions was handed two lists disagreeing
about what a nuclide's CAS is -- which is the situation those fixes exist to
prevent (#26).

Nothing failed.  The fixes files were each internally consistent, every source
list resolved, and the merge arbitrated silently.  What was missing was anything
that read the *set* of fixes files as one thing, which is what this does.

Two guards, and they catch different mistakes:

- Reading only the checked-in files: no two versions may state contradicting
  corrections for the same criteria.  This is what a copy-paste slip looks like.
- Reading the fetched flows as well: no version may still ship a value another
  version's fixes file calls wrong.  This is what #26 looked like, and it is
  the guard that needs real data, so it skips when a version has not been
  fetched.
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from brightway_flows.manual_fixes import apply_manual_fixes, fix_criteria, matches
from brightway_flows.sources import known_source_lists

ECOINVENT = "ecoinvent"


def _ecoinvent_sources() -> dict[str, object]:
    return {
        key: source
        for key, source in known_source_lists().items()
        if source.list_name == ECOINVENT
    }


def _fixes(path: Path | None) -> list[dict]:
    """A version with no fixes file states no corrections.

    Returned rather than raised so that a version that lost its file fails on
    the correction it is missing, which names the defect, instead of on an
    attribute error three frames down, which does not.
    """
    if path is None or not path.exists():
        return []
    return json.loads(path.read_text())["fixes"]


class EveryVersionIsCorrectedTestCase(unittest.TestCase):
    """The checked-in files, read as one set."""

    def setUp(self):
        self.sources = _ecoinvent_sources()

    def test_every_registered_version_names_a_fixes_file(self):
        """A version with no fixes file cannot be carrying the corrections.

        This is not a rule about lists in general -- a list added today has no
        corrections and should name none.  It is a rule about ecoinvent, where
        four corrections are known to apply to every version.
        """
        for key, source in self.sources.items():
            with self.subTest(source=key):
                self.assertIsNotNone(source.manual_fixes_path)
                self.assertTrue(source.manual_fixes_path.exists())

    def test_no_two_versions_state_a_different_correction(self):
        """Same criteria, same field, same answer -- or the lists disagree.

        A correction stated twice with two answers is worse than one stated
        once: both versions look corrected, and the merge still has to
        arbitrate between them.

        The *answer* is `new_value` / `remove_value`.  `original_value` is not
        part of it: it is a guard saying what the release being corrected
        actually ships, and a vendor may ship one flow under two spellings
        across releases.  ecoinvent's horticultural peat is
        `c5035ce2-5ee5-431f-a287-4b25da42be74` in all five, named `Peat` in
        3.9.1 through 3.12 and `Peat, in ground` in 3.8; every release corrects
        it to `Peat, horticulture`, and each states the string it is actually
        replacing.  Requiring one `original_value` there would force a fix to
        name a value its own release does not carry, which is the failure the
        guard exists to catch (#89).

        The guards are checked, elsewhere and per release:
        `test_no_version_ships_a_value_another_version_calls_wrong` asserts that
        no version still ships the value a fix calls wrong, and exempts
        uuid-keyed fixes from the cross-version sweep for this same reason.
        """
        stated: dict[tuple, dict[str, tuple]] = {}
        for key, source in self.sources.items():
            for fix in _fixes(source.manual_fixes_path):
                signature = (
                    tuple(sorted(fix_criteria(fix).items())),
                    fix["field"],
                )
                answer = (
                    json.dumps(fix.get("new_value"), sort_keys=True),
                    json.dumps(fix.get("remove_value"), sort_keys=True),
                )
                stated.setdefault(signature, {})[key] = answer

        for signature, answers in stated.items():
            with self.subTest(fix=signature):
                self.assertEqual(
                    len(set(answers.values())), 1,
                    f"{signature[0]} / {signature[1]} is corrected differently "
                    f"per version: {answers}",
                )

    def test_the_substance_corrections_are_in_every_version_that_can_hold_them(self):
        """Named, because the generic guard below needs fetched flows.

        Uranium-238, `Silver-110` and MCPA-methyl's name are in all five
        versions; the lindanes arrive at 3.11 and Mefentrifluconazole at
        3.10.1, so the versions before those cannot state a correction about a
        row they do not have.
        """
        everywhere = {
            ("name", "Uranium-238"),
            ("name", "Silver-110"),
            # #46: `Ioxynil methyl ester` renamed `MCPA-methyl`, keyed on the
            # registry number because the number is the half that is right.
            ("cas_number", "2436-73-9"),
        }
        expected = {
            "ecoinvent-3.8": everywhere,
            "ecoinvent-3.9.1": everywhere,
            "ecoinvent-3.10.1": everywhere | {
                ("uuid", "a1f19e68-e0ca-4d2b-a159-38e9036542f3"),
            },
            "ecoinvent-3.11": everywhere | {
                ("name", "Alpha-lindane"), ("name", "Beta-lindane"),
                ("name", "Delta-lindane"),
                ("uuid", "a1f19e68-e0ca-4d2b-a159-38e9036542f3"),
            },
            "ecoinvent-3.12": everywhere | {
                ("name", "Alpha-lindane"), ("name", "Beta-lindane"),
                ("name", "Delta-lindane"),
                ("uuid", "a1f19e68-e0ca-4d2b-a159-38e9036542f3"),
            },
        }
        for key, source in self.sources.items():
            with self.subTest(source=key):
                stated = {
                    item
                    for fix in _fixes(source.manual_fixes_path)
                    for item in fix_criteria(fix).items()
                }
                self.assertLessEqual(expected[key], stated)


class NoVersionStillShipsACorrectedValueTestCase(unittest.TestCase):
    """The same question asked of the data rather than of the files.

    This is the one that would have caught #26 the day 3.9.1, 3.10.1 and 3.11
    were registered: it does not need to be told which corrections matter, only
    that a value one version calls wrong is wrong wherever it appears.
    """

    @classmethod
    def setUpClass(cls):
        cls.sources = _ecoinvent_sources()
        missing = [
            key for key, source in cls.sources.items()
            if not source.flows_path.exists()
        ]
        if missing:
            raise unittest.SkipTest(f"flows not fetched for {', '.join(sorted(missing))}")
        cls.fixed = {}
        for key, source in cls.sources.items():
            flows = json.loads(source.flows_path.read_text())
            if source.manual_fixes_path is not None:
                apply_manual_fixes(flows, source.manual_fixes_path, label=key)
            cls.fixed[key] = flows

    def test_no_version_ships_a_value_another_version_calls_wrong(self):
        """A fix guarded by `original_value` says that value is wrong.

        So no version may still be shipping rows that match the fix's criteria
        *and* hold the value it replaces -- not the version that states it, and
        not any other version either.
        """
        for stating_key, source in self.sources.items():
            for index, fix in enumerate(_fixes(source.manual_fixes_path)):
                if "original_value" not in fix or "new_value" not in fix:
                    continue
                criteria = {**fix_criteria(fix), fix["field"]: fix["original_value"]}
                if "uuid" in criteria:
                    # A uuid-keyed fix is about one row, and a uuid is not
                    # guaranteed to mean the same substance in another export;
                    # only ask the version that states it.
                    versions = {stating_key: self.fixed[stating_key]}
                else:
                    versions = self.fixed
                for key, flows in versions.items():
                    stale = [f["uuid"] for f in flows if matches(f, criteria)]
                    with self.subTest(stated_by=stating_key, found_in=key, fix=index):
                        self.assertEqual(
                            stale, [],
                            f"{key} still ships {len(stale)} row(s) with "
                            f"{fix['field']}={fix['original_value']!r} that "
                            f"{stating_key} corrects to {fix['new_value']!r}",
                        )

    def test_the_corrections_agree_across_every_version_that_ships_the_row(self):
        """The property the corrections buy, stated on the merged view.

        The merge keys a source row on its uuid, so two versions carrying one
        uuid with different names or CAS numbers is what makes it arbitrate.
        ecoinvent renames and re-registers plenty of substances between
        releases legitimately, so this asks only about the rows the fixes are
        about.
        """
        watched = ("Uranium-238", "Silver-110m", "Mefentrifluconazole",
                   "Alpha-lindane", "Beta-lindane", "Delta-lindane")
        by_uuid: dict[str, dict[str, tuple]] = {}
        for key, flows in self.fixed.items():
            for flow in flows:
                if flow["name"] in watched:
                    by_uuid.setdefault(flow["uuid"], {})[key] = (
                        flow["name"], flow.get("cas_number")
                    )
        self.assertTrue(by_uuid)
        for uuid, per_version in by_uuid.items():
            with self.subTest(uuid=uuid):
                self.assertEqual(len(set(per_version.values())), 1, per_version)


if __name__ == "__main__":
    unittest.main()
