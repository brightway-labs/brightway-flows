"""Which corrections are about a flow ecoinvent has renumbered, and were they checked.

`ecoinvent-match-overrides.json` writes a correction against a flow's code,
once, and it then applies to every release that ships that flow.  The premise is
that a code names the same flow in every release, and it is right about renames:
the coarse dust flow is `Particulates, > 2.5 um, and < 10um` in 3.8 and
`Particulate Matter, > 2.5 um and < 10um` in 3.12, and the four corrections about
it are as true after the comma moved as before.

It is not right about renumbering.  Thirteen codes ship as `Vanadium`, 7440-62-2,
and `Vanadium, ion`, 22541-77-1, in release 3.8 and as a single `Vanadium V`,
22537-31-1, in 3.12: three substances under one set of codes, and a decision
about pentavalent vanadium is not a decision about the metal.  Nine codes have
exactly that shape -- `Chromium`, 7440-47-3, in 3.8; `Chromium III`, 16065-83-1,
from 3.9.1 -- and the opposite answer, because 3.8 shipped a separate
`Chromium VI` flow in those same nine places, so its unspeciated chromium already
meant trivalent.

Whether a correction carries across a renumbering is a chemist's question and no
test can answer it.  What a test can do is *ask* it, of every correction, and
refuse the ones nobody has answered.  That is this file: the twenty-seven rows a
renumbering touches must each either be guarded by name, which says the decision
was written about one release, or record the registrations it was checked
against, which says it was written about the substance behind them.

It reads the releases on disk, so it skips where they have not been fetched.
The five extracted on 2026-08-18 are the answer's lower bound: a release nobody
here has extracted may renumber a flow this passes on today, which is what
`apply_match_overrides` refuses at build time (#109).
"""

from __future__ import annotations

import json
import unittest
from collections import defaultdict

from brightway_flows.match_overrides import MatchOverride, load_match_overrides
from brightway_flows.sources import (
    PACKAGE_DATA_DIR,
    SourceList,
    known_source_lists,
)

ECOINVENT = "ecoinvent"
OVERRIDES_PATH = PACKAGE_DATA_DIR / "ecoinvent-match-overrides.json"


def _ecoinvent_sources() -> dict[str, SourceList]:
    return {
        key: source
        for key, source in known_source_lists().items()
        if source.list_name == ECOINVENT
    }


class EveryRenumberedCorrectionIsAccountedForTestCase(unittest.TestCase):
    """The question asked of the shipped files, release by release.

    Not of the two releases a build merges: the disagreement that made this
    issue is not always visible there.  ecoinvent registers `Copper oxychloride`
    as 1332-40-7 in 3.9.1 and 3.10.1 and as 1332-65-6 in 3.11 and 3.12, under
    the same name in all four, and 3.8 does not ship the flow at all -- so a
    build merging 3.12 and 3.8 shows one number and nothing to compare it with.
    """

    @classmethod
    def setUpClass(cls):
        cls.sources = _ecoinvent_sources()
        missing = sorted(
            key for key, source in cls.sources.items() if not source.flows_path.exists()
        )
        if missing:
            raise unittest.SkipTest(f"flows not fetched for {', '.join(missing)}")
        cls.overrides = {
            override.source_uuid: override
            for override in load_match_overrides(OVERRIDES_PATH)
        }
        # uuid -> registry number -> the releases stating it.  Built over every
        # flow rather than only the corrected ones, because the file is edited
        # far more often than a release is added and the cost is one pass.
        cls.registered: dict[str, dict[str, set[str]]] = defaultdict(
            lambda: defaultdict(set)
        )
        for key, source in cls.sources.items():
            for flow in json.loads(source.flows_path.read_text()):
                number = str(flow.get("cas_number") or "").strip()
                if number:
                    cls.registered[str(flow.get("uuid") or "").strip()][number].add(key)

    def _renumbered(self) -> dict[str, dict[str, set[str]]]:
        """The corrected flows the extracted releases disagree about.

        Disagree, not "differ from one release": a flow that states a number in
        one release and nothing in another has renumbered nothing.  Whole
        families here carry no registry number at all -- the coarse particulate
        rows, the standing wood, the land occupations -- and one that stops
        stating a number it used to state, as
        `Gas, mine, off-gas, process, coal mining` does after 3.9.1, has said
        nothing about what the substance is.
        """
        return {
            uuid: dict(numbers)
            for uuid, numbers in self.registered.items()
            if uuid in self.overrides and len(numbers) > 1
        }

    def _describe(self, uuid: str, override: MatchOverride) -> str:
        stated = "; ".join(
            f"{number} in {', '.join(sorted(keys))}"
            for number, keys in sorted(self.registered[uuid].items())
        )
        return f"{override.source_name or uuid} ({uuid}): {stated}"

    def test_every_renumbered_correction_is_guarded_or_records_its_check(self):
        """The question this file exists to ask.

        A row that fails it is not necessarily wrong -- the chromium rows would
        have failed it and are right.  It is a row whose rightness lives only in
        prose, which is what let thirteen vanadium rows look exactly like nine
        chromium ones.
        """
        renumbered = self._renumbered()
        self.assertTrue(renumbered, "no corrected flow is renumbered; check the fetch")
        for uuid, numbers in sorted(renumbered.items()):
            override = self.overrides[uuid]
            with self.subTest(flow=override.source_name or uuid):
                self.assertTrue(
                    override.only_when_named or override.carries_when_registered_as,
                    f"{self._describe(uuid, override)} -- ecoinvent registers this "
                    f"flow differently in different releases, and the correction "
                    f"about it says nothing about which of them it was written "
                    f"for. Guard it with 'only_when_named' if the decision is "
                    f"about one release, or record the registrations it was "
                    f"checked against with 'carries_when_registered_as': "
                    f"{sorted(numbers)}.",
                )

    def test_a_recorded_check_covers_every_registration_on_disk(self):
        """The other half: a record that has fallen behind the releases.

        A row recording two of the three numbers its flow now carries would
        still pass the first test, and the build would refuse it -- correctly,
        and only on the machine that has the release. Asked here as well so the
        row is named before a build stops.
        """
        for uuid, numbers in sorted(self._renumbered().items()):
            override = self.overrides[uuid]
            if not override.carries_when_registered_as:
                continue
            with self.subTest(flow=override.source_name or uuid):
                self.assertLessEqual(
                    set(numbers),
                    set(override.carries_when_registered_as),
                    f"{self._describe(uuid, override)} -- the correction records "
                    f"having been checked against "
                    f"{list(override.carries_when_registered_as)}, which does not "
                    f"cover every registration the extracted releases ship.",
                )

    def test_a_recorded_check_is_about_a_flow_that_is_renumbered(self):
        """A record of a check nobody needed reads like one somebody made.

        Every number recorded has to be one some extracted release states for
        that flow, or the row is answering a question about a release nobody
        here has -- which is a claim, but not this one, and it belongs in the
        comment where a reader can weigh it.
        """
        for uuid, override in sorted(self.overrides.items()):
            if not override.carries_when_registered_as:
                continue
            with self.subTest(flow=override.source_name or uuid):
                self.assertGreater(
                    len(self.registered.get(uuid, {})), 1,
                    f"{override.source_name or uuid} ({uuid}) records having been "
                    f"checked against "
                    f"{list(override.carries_when_registered_as)}, but the "
                    f"extracted releases register it as "
                    f"{sorted(self.registered.get(uuid, {}))}.",
                )


class TheTwoAnswersTestCase(unittest.TestCase):
    """The two rows the file gives opposite answers to, named.

    Read from the checked-in file rather than the releases, so it holds without
    a fetch: these are the populations #108 and #45 decided, and a change that
    moved either of them into the other's treatment would be the defect back.
    """

    def setUp(self):
        self.overrides = load_match_overrides(OVERRIDES_PATH)

    def test_the_vanadium_rows_say_the_decision_does_not_carry(self):
        guarded = [
            override for override in self.overrides if override.only_when_named
        ]
        vanadium = [
            override
            for override in guarded
            if override.only_when_named == ("Vanadium V",)
        ]
        self.assertEqual(len(vanadium), 13)
        for override in vanadium:
            with self.subTest(override.source_uuid):
                self.assertEqual(override.carries_when_registered_as, ())
        # Every guarded row is accounted for by name, so a new one has to be
        # added here with its population rather than riding in uncounted.
        # Besides vanadium there is one: #144's fosetyl rewrite, guarded by
        # the spelling 3.8 alone ships, because 3.9.1 onwards register the
        # same uuid 39148-24-8 and match on it without curation.
        self.assertEqual(
            [
                (override.source_uuid, override.only_when_named)
                for override in guarded
                if override not in vanadium
            ],
            [("4c44e04f-9b3d-4389-bf08-1bddf9dfa9e7", ("Fosetyl-aluminium",))],
        )

    def test_the_rows_that_say_it_does_carry_name_their_registrations(self):
        recorded = [
            override
            for override in self.overrides
            if override.carries_when_registered_as
        ]
        by_numbers: dict[tuple[str, ...], int] = defaultdict(int)
        for override in recorded:
            by_numbers[override.carries_when_registered_as] += 1
        self.assertEqual(
            dict(by_numbers),
            {
                # ecoinvent 3.8's `Chromium` and 3.9.1 onwards' `Chromium III`.
                ("7440-47-3", "16065-83-1"): 9,
                # `Lutetium, in ground`: 439-94-3 in 3.8 and 3.9.1 -- a digit
                # short of lutetium's own 7439-94-3, which 3.10.1 onward carry.
                # One element, one typo, one decision (#141).
                ("439-94-3", "7439-94-3"): 1,
                #
                # Three families recorded here until #141 retired the published
                # tables: `Copper oxychloride`'s five rows and
                # `Flupyrsulfuron-methyl`'s one were declines, spent and removed
                # with the tables they declined rows out of, and `Baddeleyite`'s
                # decline the same -- its two registrations now simply mint the
                # ore as one substance through ordinary matching, which is what
                # the decline argued for (#118). Their reasoning lives in this
                # file's git record and in the issues.
            },
        )


if __name__ == "__main__":
    unittest.main()
