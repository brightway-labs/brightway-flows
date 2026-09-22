"""A curated target has to reach every version of a list, not just one.

ecoinvent 3.8's correspondence table is composed here, so a target this project
disagrees with could be stated in the composition and nowhere else.  3.9.1
onwards read theirs from `randonneur_data` verbatim: there was no hook at all,
and a decision made for 3.8 silently did not apply to the other four versions
(#37).

Overriding what a table *loads* is that hook, and one override set covers every
version because ecoinvent's flow uuids are stable across releases.  These are
the properties that make that safe: that an override cannot half-apply to a
source flow the table names twice, that it does not quietly do nothing when the
table names the flow not at all, that applying it twice is applying it once, and
that a row naming a flow a version does not ship is inert rather than an error.

The particulate and trivalent-chromium cases are checked against the real
files, in every registered ecoinvent version, because those are the decisions
the file exists for.
"""

import tempfile
import unittest
from pathlib import Path

import orjson

from brightway_flows.match_overrides import (
    apply_match_overrides,
    load_match_overrides,
    admitted_prepared_rows,
)
from brightway_flows.sources import (
    PACKAGE_DATA_DIR,
    known_source_lists,
    load_prepared_match_table,
    resolve_source_list,
)

OVERRIDES_FILE = "ecoinvent-match-overrides.json"
OVERRIDES_PATH = PACKAGE_DATA_DIR / OVERRIDES_FILE

#: ecoinvent's coarse particulate fraction, by context, and the EF 3.1
#: `particles (PM10)` flow of the matching context it now maps to.  The source
#: uuids are stable from 3.8 to 3.12; the name gains and loses a comma.
COARSE_PARTICULATES = {
    "b967e1bf-f09b-4c89-8740-ace21db47bba": "08a91e70-3ddc-11dd-91be-0050c2490048",
    "5716c728-bd33-414d-8691-16e5534f5d37": "08a91e70-3ddc-11dd-91bf-0050c2490048",
    "ccb169c3-8aae-4727-89bb-a7dd122946f3": "08a91e70-3ddc-11dd-91c0-0050c2490048",
    "295c9740-6fdb-4676-9eb8-15e3786f713d": "08a91e70-3ddc-11dd-91c1-0050c2490048",
    "604f9273-f26b-46be-83a7-3a65280011d1": "64b1f56e-6556-11dd-ad8b-0800200c9a66",
}


#: ecoinvent's trivalent chromium emissions to air and soil, by context, and the
#: EF 3.1 `chromium (iii)` flow of the matching context each now maps to.  The
#: source uuids are stable from 3.8 to 3.12; the name changes from `Chromium` to
#: `Chromium III` at 3.9.1, along with the CAS number.
TRIVALENT_CHROMIUM = {
    "e142b577-e934-4085-9a07-3983d4d92afb": "08a91e70-3ddc-11dd-9f7b-0050c2490048",
    "7705f0e1-5b14-44f4-b330-1245b5c7fc08": "4d9a8790-3ddd-11dd-8fce-0050c2490048",
    "4d40d8e3-9bc7-4ab1-ac5c-4f4a76fda8e5": "4d9a8790-3ddd-11dd-8fcf-0050c2490048",
    "2a5ed451-12a2-47db-b4dc-fa0bfbc01d79": "3e4c8d2d-6556-11dd-ad8b-0800200c9a66",
    "6b29d83a-c43c-484c-8e73-474a8a22d71e": "08a91e70-3ddc-11dd-9f7c-0050c2490048",
    "e7881581-21b3-4f5c-bd63-6b0684b5e712": "08a91e70-3ddc-11dd-9f79-0050c2490048",
    "591de726-f2c7-43ba-8e22-15fd08acc8dc": "4d9a8790-3ddd-11dd-8fd3-0050c2490048",
    "e65a9c58-21f1-48b6-b738-d05a8f10e5f3": "4d9a8790-3ddd-11dd-8fd3-0050c2490048",
    "e0336c9b-a0ff-4ae3-b8bb-ca1e46bbbc11": "08a91e70-3ddc-11dd-9f7a-0050c2490048",
}

#: The same substance in water, which ecoinvent 3.8 already called
#: `Chromium, ion` and every published table already maps to `chromium (iii)`.
#: Named here to state the scope of the decision: these are the rows the
#: overrides deliberately leave alone.
TRIVALENT_CHROMIUM_IN_WATER = (
    "1c87de06-e58f-4684-a54c-d29f1a251a87",
    "d9c23a8d-e7bf-4f70-8d22-b9ad8a653204",
    "d98f0ec0-bf19-4c90-a457-a8593dec497f",
    "e34d3da4-a3d5-41be-84b5-458afe32c990",
    "30f484ee-dec4-47ae-8e92-d00d4b93fe05",
)


#: ecoinvent's trivalent chromium emissions to air and soil, by context, and the
#: EF 3.1 `chromium (iii)` flow of the matching context each now maps to.  The
#: source uuids are stable from 3.8 to 3.12; the name changes from `Chromium` to
#: `Chromium III` at 3.9.1, along with the CAS number.
TRIVALENT_CHROMIUM = {
    "e142b577-e934-4085-9a07-3983d4d92afb": "08a91e70-3ddc-11dd-9f7b-0050c2490048",
    "7705f0e1-5b14-44f4-b330-1245b5c7fc08": "4d9a8790-3ddd-11dd-8fce-0050c2490048",
    "4d40d8e3-9bc7-4ab1-ac5c-4f4a76fda8e5": "4d9a8790-3ddd-11dd-8fcf-0050c2490048",
    "2a5ed451-12a2-47db-b4dc-fa0bfbc01d79": "3e4c8d2d-6556-11dd-ad8b-0800200c9a66",
    "6b29d83a-c43c-484c-8e73-474a8a22d71e": "08a91e70-3ddc-11dd-9f7c-0050c2490048",
    "e7881581-21b3-4f5c-bd63-6b0684b5e712": "08a91e70-3ddc-11dd-9f79-0050c2490048",
    "591de726-f2c7-43ba-8e22-15fd08acc8dc": "4d9a8790-3ddd-11dd-8fd3-0050c2490048",
    "e65a9c58-21f1-48b6-b738-d05a8f10e5f3": "4d9a8790-3ddd-11dd-8fd3-0050c2490048",
    "e0336c9b-a0ff-4ae3-b8bb-ca1e46bbbc11": "08a91e70-3ddc-11dd-9f7a-0050c2490048",
}

#: The same substance in water, which ecoinvent 3.8 already called
#: `Chromium, ion` and every published table already maps to `chromium (iii)`.
#: Named here to state the scope of the decision: these are the rows the
#: overrides deliberately leave alone.
TRIVALENT_CHROMIUM_IN_WATER = (
    "1c87de06-e58f-4684-a54c-d29f1a251a87",
    "d9c23a8d-e7bf-4f70-8d22-b9ad8a653204",
    "d98f0ec0-bf19-4c90-a457-a8593dec497f",
    "e34d3da4-a3d5-41be-84b5-458afe32c990",
    "30f484ee-dec4-47ae-8e92-d00d4b93fe05",
)


#: ecoinvent's 1,4-butanediol, by context, and the EF 3.1 `butylene glycol`
#: flow of the matching compartment each now maps to (#140).  The registration
#: is 110-63-4 in every release; the published table routed the whole family
#: onto the epichlorohydrin adduct 2425-79-8, a different substance.
BUTANEDIOL = {
    "09db39be-d9a6-4fc3-8d25-1f80b23e9131": "fe0acd60-3ddc-11dd-a8a7-0050c2490048",
    "38a622c6-f086-4763-a952-7c6b3b1c42ba": "fe0acd60-3ddc-11dd-a8a9-0050c2490048",
    "83bafcf1-2f2e-4a32-89a0-f1f16ca10626": "fe0acd60-3ddc-11dd-a8aa-0050c2490048",
    "d21da01e-f96f-4db5-9746-7b70db8a1f2c": "fe0acd60-3ddc-11dd-a8a8-0050c2490048",
    "90653a29-2f53-4b1b-88bd-9ae2fe64a8d6": "f214fc47-6555-11dd-ad8b-0800200c9a66",
    "d835b7aa-288b-4b3a-966b-3f64f36ed220": "fe0acd60-3ddc-11dd-a8ad-0050c2490048",
    "d6911d36-3fec-41fe-8ef9-540f6543a240": "fe0acd60-3ddc-11dd-a8ab-0050c2490048",
    "aae8aac7-b81d-41e4-b356-912b369d1c55": "fe0acd60-3ddc-11dd-ae2e-0050c2490048",
    "c5de5e4d-85cf-4102-9ff1-5248d8928ba1": "fe0acd60-3ddc-11dd-a8ad-0050c2490048",
    "564dde7f-e713-4baf-84aa-7a11ffa7e2cd": "fe0acd60-3ddc-11dd-a8ac-0050c2490048",
}

#: The adduct's own EF flow in unspecified air.  Named to state the scope of
#: the #140 decision: EF 3.1 genuinely carries the reaction product as a
#: substance of its own, and nothing about that entry or its rows changes --
#: only ecoinvent's butanediol stops being mapped onto it.
BUTANEDIOL_ADDUCT_TARGET = "88dc464b-4d23-48c5-861e-bf0a1fbcdb7c"

#: ecoinvent's hardwood and unspecified standing wood, which every published
#: table routes onto EF 3.1's `Wood, primary forest, standing` because EF ships
#: nothing else they could go to.  The uuids are stable from 3.8 to 3.12.
STANDING_WOOD_DECLINED = {
    "bac875f4-75fb-4dde-841a-b07d3a41bcd1": "Wood, hard, standing",
    "23e83c1f-07c9-4b5f-a898-0f4f09a6691f": "Wood, unspecified, standing",
}

#: The other two of ecoinvent's four, and the EF 3.1 flow each reaches.  Named
#: to state the scope of the decision: these are the rows it leaves alone, and
#: they are the reason `Wood, primary forest, standing` is still a target at
#: all.
STANDING_WOOD_KEPT = {
    "28528881-7154-48d5-9cc3-5c13ddcdc47a": "c70982c9-e239-4642-8162-33d985c517fe",
    "b073ec00-a5bf-4b64-bda0-ef366a3ac9bb": "34724ae6-a108-4f17-8b12-5b188a0c4200",
}


def _override(**fields):
    row = {
        "source_uuid": "s-1",
        "source_name": "Something",
        "target_uuid": "t-new",
        "target_name": "something else",
        "comment": "Because the published table is wrong about this one.",
    }
    row.update(fields)
    if "conversion_factor" in row and "conversion_checked_against" not in row:
        # A factor has to say which releases it was checked against (#162).
        # Defaulted here so a test about something else does not have to
        # restate it; a test *about* the scope states its own, and one about
        # the scope being missing passes an empty list.
        row["conversion_checked_against"] = ["1.0"]
    return row


def _target_uuid(row):
    return str((row.get("target") or {}).get("uuid") or "")


def _source_uuid(row):
    side = row.get("source") or {}
    return str(side.get("uuid") or side.get("identifier") or "")


class ApplicationTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)

    def _file(self, *overrides):
        path = self.dir / "overrides.json"
        path.write_bytes(orjson.dumps({"overrides": list(overrides)}))
        return path

    def test_the_target_is_rewritten(self):
        rows = [{"source": {"uuid": "s-1"}, "target": {"uuid": "t-old"}}]
        result = apply_match_overrides(rows, self._file(_override()))
        self.assertEqual([_target_uuid(r) for r in result], ["t-new"])
        self.assertEqual(result[0]["target"]["name"], "something else")

    def test_the_table_is_not_mutated(self):
        rows = [{"source": {"uuid": "s-1"}, "target": {"uuid": "t-old"}}]
        apply_match_overrides(rows, self._file(_override()))
        self.assertEqual(_target_uuid(rows[0]), "t-old")

    def test_the_reasoning_travels_with_the_row(self):
        rows = [{"source": {"uuid": "s-1"}, "target": {"uuid": "t-old"}}]
        result = apply_match_overrides(rows, self._file(_override()))
        self.assertEqual(result[0]["comment"], _override()["comment"])
        self.assertEqual(result[0]["route"], "override")

    def test_the_tables_own_target_context_does_not_travel(self):
        """It describes the flow the table chose, not the one the override does.

        Carrying it over would publish a context nobody checked against the
        flow it now sits on.
        """
        rows = [{
            "source": {"uuid": "s-1"},
            "target": {"uuid": "t-old", "context": ["Emissions", "Emissions to air"]},
        }]
        result = apply_match_overrides(rows, self._file(_override()))
        self.assertNotIn("context", result[0]["target"])

    def test_the_overrides_own_target_context_does_travel(self):
        """A row that states its target's context keeps it, so a curated row in
        a composed table reads like the routed rows beside it -- and so this
        pass over that table leaves it as it found it."""
        context = ["Emissions", "Emissions to soil", "Emissions to soil, unspecified"]
        rows = [{"source": {"uuid": "s-1"}, "target": {"uuid": "t-old"}}]
        result = apply_match_overrides(
            rows, self._file(_override(target_context=context))
        )
        self.assertEqual(result[0]["target"]["context"], context)

    def test_every_row_for_the_flow_is_rewritten(self):
        """Not the first.

        The merge refuses a source flow whose prepared rows disagree on a
        target, so a row left behind would turn a curated decision into an
        unmatched row.
        """
        rows = [
            {"source": {"uuid": "s-1"}, "target": {"uuid": "t-old"}},
            {"source": {"uuid": "s-1"}, "target": {"uuid": "t-other"}},
        ]
        result = apply_match_overrides(rows, self._file(_override()))
        self.assertEqual({_target_uuid(r) for r in result}, {"t-new"})

    def test_an_update_verb_row_is_matched_too(self):
        """`replace` rows spell the source uuid `uuid`; `update` rows spell it
        `identifier`.  Reading one matches nothing on half the tables."""
        rows = [{"source": {"identifier": "s-1"}, "target": {"uuid": "t-old"}}]
        result = apply_match_overrides(rows, self._file(_override()))
        self.assertEqual([_target_uuid(r) for r in result], ["t-new"])

    def test_a_flow_the_table_omits_gets_a_row(self):
        """A table can simply not name a flow -- 3.8's composed one omits every
        flow no route reaches.  An override that silently did nothing there
        would leave the flow to algorithmic matching while the file said
        otherwise."""
        result = apply_match_overrides([], self._file(_override()))
        self.assertEqual(len(result), 1)
        self.assertEqual(_source_uuid(result[0]), "s-1")
        self.assertEqual(_target_uuid(result[0]), "t-new")

    def test_other_rows_are_left_alone(self):
        rows = [{"source": {"uuid": "s-2"}, "target": {"uuid": "t-2"}}]
        result = apply_match_overrides(rows, self._file(_override()))
        self.assertEqual(_target_uuid(result[0]), "t-2")
        self.assertNotIn("route", result[0])

    def test_applying_twice_is_applying_once(self):
        """The 3.8 table is composed with these applied and then loaded through
        them again; that second pass has to be a no-op."""
        path = self._file(_override())
        once = apply_match_overrides(
            [{"source": {"uuid": "s-1"}, "target": {"uuid": "t-old"}}], path
        )
        twice = apply_match_overrides(once, path)
        self.assertEqual(twice, once)

    def test_no_overrides_file_leaves_the_table_alone(self):
        rows = [{"source": {"uuid": "s-1"}, "target": {"uuid": "t-old"}}]
        self.assertEqual(apply_match_overrides(rows, None), rows)
        self.assertEqual(apply_match_overrides(rows, self.dir / "absent.json"), rows)


class NameGuardTestCase(unittest.TestCase):
    """A decision written about one release must not reach a release where the
    vendor gave the same uuid to a different substance.

    The file's premise is that a flow uuid names the same flow in every release,
    which is what lets one row decide for all of them.  ecoinvent's vanadium
    flows are the counter-example measured on 2026-08-18: thirteen uuids ship as
    `Vanadium` (7440-62-2) and `Vanadium, ion` (22541-77-1) in 3.8 and as
    `Vanadium V` (22537-31-1) in 3.12.  Rewriting them to EF 3.1's
    `vanadium (v)` is right for 3.12 and moves nine elemental-vanadium rows and
    four trivalent-ion rows onto the wrong substance in 3.8.

    Opt-in, and the second test is why: `Particulates, > 2.5 um, and < 10um`
    became `Particulate Matter, > 2.5 um and < 10um` between the same two
    releases, and the four overrides about it are as true after the comma moved
    as before.  A guard enforced on every row would have cost those.
    """

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)

    def _file(self, *overrides):
        path = self.dir / "overrides.json"
        path.write_bytes(orjson.dumps({"overrides": list(overrides)}))
        return path

    def test_it_applies_where_the_table_uses_the_stated_name(self):
        rows = [{"source": {"uuid": "s-1", "name": "Vanadium V"}, "target": {"uuid": "t-old"}}]
        result = apply_match_overrides(
            rows, self._file(_override(only_when_named="Vanadium V"))
        )
        self.assertEqual([_target_uuid(r) for r in result], ["t-new"])

    def test_it_leaves_the_row_alone_where_the_table_uses_another_name(self):
        rows = [{"source": {"uuid": "s-1", "name": "Vanadium"}, "target": {"uuid": "t-old"}}]
        result = apply_match_overrides(
            rows, self._file(_override(only_when_named="Vanadium V"))
        )
        self.assertEqual([_target_uuid(r) for r in result], ["t-old"])
        self.assertNotIn("route", result[0])

    def test_an_unguarded_row_survives_a_rename(self):
        rows = [{
            "source": {"uuid": "s-1", "name": "Particulate Matter, > 2.5 um and < 10um"},
            "target": {"uuid": "t-old"},
        }]
        result = apply_match_overrides(rows, self._file(_override()))
        self.assertEqual([_target_uuid(r) for r in result], ["t-new"])

    def test_a_guarded_row_is_not_appended_instead(self):
        """The guard has to close the other door too.

        An override whose flow the table has no row for is *appended*, so a
        guard that only skipped the rewrite would let the decision arrive as a
        new row -- with the same wrong target, on a release the decision was
        never about.
        """
        rows = [{"source": {"uuid": "s-1", "name": "Vanadium"}, "target": {"uuid": "t-old"}}]
        result = apply_match_overrides(
            rows, self._file(_override(only_when_named="Vanadium V"))
        )
        self.assertEqual(len(result), 1)

    def test_the_name_guard_travels_on_an_appended_row(self):
        """With no table row to check it against, the guard rides to the merge.

        The two tests above check the guard against a *table row's* stated
        name -- and with every prepared table retired there is no such row,
        so the append loop appends unconditionally and the guard is emitted
        on the row instead, for `admitted_prepared_rows` to check against
        the release's own flow.  Found by review on #336, when every guarded
        override was reaching every release unchecked.
        """
        result = apply_match_overrides(
            [], self._file(_override(only_when_named="Vanadium V"))
        )
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].get("only_when_named"), ["Vanadium V"])
        # An unguarded override appends without the field: nothing for the
        # merge to check, exactly as before.
        result = apply_match_overrides([], self._file(_override()))
        self.assertEqual(len(result), 1)
        self.assertNotIn("only_when_named", result[0])

    def test_admitted_prepared_rows_checks_the_guard(self):
        """The merge-side half of the guard, on the rows the append emits."""
        guarded = {"only_when_named": ["Vanadium V"], "source": {}, "target": {}}
        plain = {"source": {}, "target": {}}
        self.assertEqual(
            admitted_prepared_rows([guarded, plain], row_name="Vanadium V"),
            [guarded, plain],
        )
        # Case never decides, exactly as `applies_to` never let it.
        self.assertEqual(
            admitted_prepared_rows([guarded], row_name="vanadium v"),
            [guarded],
        )
        # A release whose flow answers to another name is a release the
        # decision was not written about: withheld, not redirected -- the
        # flow falls through to ordinary matching.
        self.assertEqual(
            admitted_prepared_rows([guarded, plain], row_name="Vanadium"),
            [plain],
        )

    def test_several_spellings_may_be_named(self):
        rows = [{"source": {"uuid": "s-1", "name": "vanadium v"}, "target": {"uuid": "t-old"}}]
        result = apply_match_overrides(
            rows, self._file(_override(only_when_named=["Vanadium V", "Vanadium (V)"]))
        )
        # Compared without regard to case: that part of a vendor's spelling
        # varies between releases without meaning anything.
        self.assertEqual([_target_uuid(r) for r in result], ["t-new"])

    def test_a_table_row_with_no_name_does_not_satisfy_a_guard(self):
        rows = [{"source": {"uuid": "s-1"}, "target": {"uuid": "t-old"}}]
        result = apply_match_overrides(
            rows, self._file(_override(only_when_named="Vanadium V"))
        )
        self.assertEqual([_target_uuid(r) for r in result], ["t-old"])

    def test_the_thirteen_vanadium_rows_are_guarded(self):
        """The checked-in file, not a fixture: this is the population the guard
        was added for, and an unguarded one would be the defect back."""
        guarded = [
            override for override in load_match_overrides(OVERRIDES_PATH)
            if override.target_name == "vanadium (v)"
        ]
        self.assertEqual(len(guarded), 13)
        for override in guarded:
            with self.subTest(override.source_uuid):
                self.assertEqual(override.only_when_named, ("Vanadium V",))

    def test_the_fosetyl_row_is_guarded_by_the_retired_spelling(self):
        """#144, against the checked-in file: 3.8 ships `4c44e04f` CAS-less as
        `Fosetyl-aluminium`, the spelling every later release retired, and the
        row minted a duplicate of EF's characterised `fosetyl-aluminum`.  The
        override sends it there -- and only under that spelling, because
        3.9.1 onwards name the same uuid `Fosetyl-Al` and register it
        39148-24-8, evidence the matcher already lands on by itself.
        """
        rows = [
            override for override in load_match_overrides(OVERRIDES_PATH)
            if override.source_uuid == "4c44e04f-9b3d-4389-bf08-1bddf9dfa9e7"
        ]
        self.assertEqual(len(rows), 1)
        override = rows[0]
        self.assertEqual(
            override.target_uuid, "08a91e70-3ddc-11dd-9433-0050c2490048"
        )
        self.assertEqual(override.only_when_named, ("Fosetyl-aluminium",))

    def test_the_fosetyl_guard_admits_only_the_retired_spelling(self):
        """Both halves of the guard, on the row the append emits: the release
        that spells the flow the retired way is decided, and the release that
        states its own registry number is left to the evidence."""
        emitted = [
            row for row in apply_match_overrides([], OVERRIDES_PATH)
            if _source_uuid(row) == "4c44e04f-9b3d-4389-bf08-1bddf9dfa9e7"
        ]
        self.assertEqual(len(emitted), 1)
        self.assertEqual(
            admitted_prepared_rows(emitted, row_name="Fosetyl-aluminium"),
            emitted,
        )
        self.assertEqual(
            admitted_prepared_rows(emitted, row_name="Fosetyl-Al"), []
        )


class RenumberingCheckTestCase(unittest.TestCase):
    """A row that records having been checked is re-asked by the next release.

    A rename is cosmetic often enough that the name guard has to be opt-in.  A
    renumbering is ecoinvent saying the flow is a different substance, and the
    nine chromium rows and the thirteen vanadium rows have the same shape and
    the opposite answer -- so what a row records is which registrations the
    answer was checked against, and a release registering the flow as something
    else is refused rather than inheriting it.

    Both halves, because the way this rule goes wrong is by growing: it must
    fire for a release nobody checked, and it must leave alone every row that
    records no check and every release that states no number at all.
    """

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)

    def _file(self, *overrides):
        path = self.dir / "overrides.json"
        path.write_bytes(orjson.dumps({"overrides": list(overrides)}))
        return path

    def _checked(self, **fields):
        return _override(
            carries_when_registered_as=["7440-47-3", "16065-83-1"], **fields
        )

    def test_it_applies_where_the_release_registers_a_number_it_was_checked_for(self):
        rows = [{"source": {"uuid": "s-1"}, "target": {"uuid": "t-old"}}]
        result = apply_match_overrides(
            rows, self._file(self._checked()), registered_as={"s-1": ["7440-47-3"]}
        )
        self.assertEqual([_target_uuid(r) for r in result], ["t-new"])

    def test_a_release_registering_it_as_something_else_is_refused(self):
        """Refused, not skipped, and the difference is what a person can act on.

        A name guard is a decision -- this correction is not about that release
        -- so skipping carries the decision out.  A registry number nobody has
        seen is an unanswered question: applying the row asserts an identity
        nobody checked, and skipping it publishes the vendor's table, equally
        unchecked.
        """
        rows = [{"source": {"uuid": "s-1"}, "target": {"uuid": "t-old"}}]
        with self.assertRaises(ValueError) as raised:
            apply_match_overrides(
                rows,
                self._file(self._checked()),
                label="ecoinvent-3.13",
                registered_as={"s-1": ["7440-62-2"]},
            )
        message = str(raised.exception)
        self.assertIn("ecoinvent-3.13", message)
        self.assertIn("s-1", message)
        self.assertIn("7440-62-2", message)

    def test_a_row_that_records_no_check_is_left_alone(self):
        """The 361 rows the question was never about.

        Most corrections really do carry across releases, and a rule that made
        every row answer for its registry number would refuse the four coarse
        particulate rows -- which carry no registry number in any release -- and
        every land occupation and water flow beside them.
        """
        rows = [{"source": {"uuid": "s-1"}, "target": {"uuid": "t-old"}}]
        result = apply_match_overrides(
            rows, self._file(_override()), registered_as={"s-1": ["7440-62-2"]}
        )
        self.assertEqual([_target_uuid(r) for r in result], ["t-new"])

    def test_a_release_that_states_no_number_has_renumbered_nothing(self):
        """The opposite reading from the name guard's, and deliberately.

        A correspondence row always names the flow, so a missing name is an
        anomaly.  A missing registry number is ordinary -- ecoinvent's
        `Gas, mine, off-gas, process, coal mining` states 8006-14-2 in 3.8 and
        3.9.1 and nothing from 3.10.1 on -- and a release that has stopped
        saying has said nothing about what the substance is.
        """
        rows = [{"source": {"uuid": "s-1"}, "target": {"uuid": "t-old"}}]
        for absent in ({}, {"s-1": []}, {"s-1": [""]}):
            with self.subTest(registered_as=absent):
                result = apply_match_overrides(
                    rows, self._file(self._checked()), registered_as=absent
                )
                self.assertEqual([_target_uuid(r) for r in result], ["t-new"])

    def test_the_old_number_kept_beside_the_new_one_still_counts(self):
        """Any one of the registrations being checked is enough: a release that
        renumbers a flow and keeps the old number still registers it as
        something this row was checked against."""
        rows = [{"source": {"uuid": "s-1"}, "target": {"uuid": "t-old"}}]
        result = apply_match_overrides(
            rows,
            self._file(self._checked()),
            registered_as={"s-1": ["16065-83-1", "18540-29-9"]},
        )
        self.assertEqual([_target_uuid(r) for r in result], ["t-new"])

    def test_a_caller_with_no_flows_in_hand_asks_nothing(self):
        """The 3.8 composition applies this file with no release to ask about,
        and a check it cannot make must not become a check it fails."""
        rows = [{"source": {"uuid": "s-1"}, "target": {"uuid": "t-old"}}]
        result = apply_match_overrides(rows, self._file(self._checked()))
        self.assertEqual([_target_uuid(r) for r in result], ["t-new"])

    def test_a_flow_the_table_omits_is_refused_too(self):
        """The guard has to close the other door.

        An override whose flow the table has no row for is appended, so a check
        that only looked at rewrites would let an unchecked decision arrive as
        a new row instead.
        """
        with self.assertRaises(ValueError):
            apply_match_overrides(
                [], self._file(self._checked()), registered_as={"s-1": ["7440-62-2"]}
            )

    def test_the_nine_chromium_rows_record_the_two_numbers(self):
        """The checked-in file, not a fixture: these are the rows whose answer
        was right by argument and recorded nowhere a machine could read it."""
        recorded = [
            override for override in load_match_overrides(OVERRIDES_PATH)
            if override.source_uuid in TRIVALENT_CHROMIUM
        ]
        self.assertEqual(len(recorded), 9)
        for override in recorded:
            with self.subTest(override.source_uuid):
                self.assertEqual(
                    override.carries_when_registered_as,
                    ("7440-47-3", "16065-83-1"),
                )


class ValidationTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)

    def _load(self, payload):
        path = self.dir / "overrides.json"
        path.write_bytes(orjson.dumps(payload))
        return load_match_overrides(path)

    def test_a_row_without_reasoning_is_refused(self):
        """Every row asserts something the published table does not, and an
        assertion with no stated reasoning cannot be re-checked against the
        vendor's next release."""
        with self.assertRaises(ValueError):
            self._load({"overrides": [_override(comment="")]})

    def test_a_row_without_a_target_is_refused(self):
        """Refused rather than skipped: an override with no target is a
        decision nobody has made yet."""
        with self.assertRaises(ValueError):
            self._load({"overrides": [_override(target_uuid="")]})

    def test_a_placeholder_is_refused(self):
        with self.assertRaises(ValueError):
            self._load({"overrides": [_override(source_uuid="PLACEHOLDER-1")]})

    def test_two_rows_for_one_flow_are_refused(self):
        """One flow, one decision. Two rows mean the last one read wins, which
        is not a decision anyone made."""
        with self.assertRaises(ValueError):
            self._load({
                "overrides": [_override(), _override(target_uuid="t-other")],
            })

    def test_a_payload_without_overrides_is_refused(self):
        with self.assertRaises(ValueError):
            self._load({"rows": []})

    def test_a_conversion_without_its_units_is_refused(self):
        """A bare factor cannot be checked against the pair the merge builds,
        so the merge would decline to carry it and the row would do nothing."""
        for missing in ("source_unit", "target_unit"):
            with self.subTest(missing=missing):
                fields = {
                    "conversion_factor": 0.599,
                    "source_unit": "kg",
                    "target_unit": "kg",
                }
                fields[missing] = ""
                with self.assertRaises(ValueError):
                    self._load({"overrides": [_override(**fields)]})

    def test_a_conversion_of_one_is_refused(self):
        """It converts nothing, and would assert that the two units were
        compared and found equal."""
        with self.assertRaises(ValueError):
            self._load({"overrides": [_override(
                conversion_factor=1.0, source_unit="kg", target_unit="kg",
            )]})

    def test_a_signed_contradiction_loads_and_a_signing_decline_is_refused(self):
        """`not_the_stated_substance` is a signature on a rewrite's target.

        A decline names no substance, so there is nothing for it to be
        deliberately different from -- signing one is the authoring mistake
        the loader refuses.
        """
        loaded = self._load({"overrides": [_override(
            not_the_stated_substance=True,
        )]})
        self.assertTrue(loaded[0].not_the_stated_substance)
        loaded = self._load({"overrides": [_override()]})
        self.assertFalse(loaded[0].not_the_stated_substance)
        with self.assertRaises(ValueError):
            self._load({"overrides": [_override(
                not_the_stated_substance="yes",
            )]})
        with self.assertRaises(ValueError):
            self._load({"overrides": [
                {**_override(not_the_stated_substance=True, target_uuid=""),
                 "decline": True},
            ]})

    def test_a_respelled_unit_validates_every_spelling(self):
        """`source_unit` as a list is one unit under two vendor spellings.

        Each spelling is checked exactly as a single one would be: an empty
        entry can never be checked against a release, and a spelling
        `units.json` already converts is a second copy of a stated fact.
        """
        loaded = self._load({"overrides": [_override(
            conversion_factor=36.0,
            source_unit=["sm3", "m3"],
            target_unit="MJ",
        )]})
        self.assertEqual(loaded[0].source_unit, "sm3")
        self.assertEqual(loaded[0].source_unit_alternates, ("m3",))
        with self.assertRaises(ValueError):
            self._load({"overrides": [_override(
                conversion_factor=36.0,
                source_unit=["sm3", ""],
                target_unit="MJ",
            )]})
        with self.assertRaises(ValueError):
            # kg -> kg at 1.0 hides inside a list as easily as alone.
            self._load({"overrides": [_override(
                conversion_factor=1.0,
                source_unit=["sm3", "kg"],
                target_unit="kg",
            )]})

    def test_a_non_numeric_conversion_is_refused(self):
        with self.assertRaises(ValueError):
            self._load({"overrides": [_override(
                conversion_factor="0.599", source_unit="kg", target_unit="kg",
            )]})

    def test_a_renumbering_check_naming_one_number_is_refused(self):
        """One number spans no renumbering.

        A row that means to reach only the releases spelling the flow one way
        is guarded by name; a row recording a check has to say what the check
        spanned, or the next release cannot re-ask it.
        """
        with self.assertRaises(ValueError):
            self._load({"overrides": [
                _override(carries_when_registered_as=["7440-47-3"])
            ]})

    def test_a_renumbering_check_that_is_not_a_registry_number_is_refused(self):
        """These are read off the releases, so a name here means the wrong
        field was copied."""
        with self.assertRaises(ValueError):
            self._load({"overrides": [
                _override(carries_when_registered_as=["Chromium", "Chromium III"])
            ]})
        with self.assertRaises(ValueError):
            self._load({"overrides": [
                _override(carries_when_registered_as="7440-47-3")
            ]})

    def test_a_row_that_is_both_guarded_and_checked_is_refused(self):
        """Both answer whether the decision reaches a release, and the guard
        has already answered no."""
        with self.assertRaises(ValueError):
            self._load({"overrides": [_override(
                only_when_named="Vanadium V",
                carries_when_registered_as=["7440-62-2", "22537-31-1"],
            )]})


class ConversionVintageTestCase(unittest.TestCase):
    """A factor states which releases it was checked against, and for which it
    is a different number.

    A target reaches every release because a uuid names one flow in all of
    them, which is a statement about identity.  A heating value is a quantity
    somebody measured, and ecoinvent remeasures: crude oil went from 42.3 to
    43.4 MJ/kg at 3.9, natural gas from 34.5 per cubic metre to 36.0 per
    standard cubic metre, and the oil and gas datasets were rebuilt on the new
    numbers.  Converting a 3.8 inventory with the later figure uses a heating
    value that release never had (#162).

    Three halves, because this rule goes wrong in three directions: it has to
    give a named release its own number, leave every other release the default,
    and refuse a release nobody has checked rather than defaulting it.
    """

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)

    def _file(self, *overrides):
        path = self.dir / "overrides.json"
        path.write_bytes(orjson.dumps({"overrides": list(overrides)}))
        return path

    def _oil(self, **fields):
        row = {
            "conversion_factor": 43.4,
            "source_unit": "kg",
            "target_unit": "MJ",
            "conversion_checked_against": ["3.9.1", "3.12"],
            "conversion_by_release": {"3.8": 42.3},
        }
        row.update(fields)
        return _override(**row)

    def test_a_release_with_its_own_number_takes_it(self):
        result = apply_match_overrides([], self._file(self._oil()), release="3.8")
        self.assertEqual(result[0]["conversion_factor"], 42.3)

    def test_every_other_checked_release_takes_the_default(self):
        for release in ("3.9.1", "3.12"):
            with self.subTest(release=release):
                result = apply_match_overrides(
                    [], self._file(self._oil()), release=release
                )
                self.assertEqual(result[0]["conversion_factor"], 43.4)

    def test_a_rewritten_row_is_stamped_with_the_releases_number_too(self):
        """Appending and rewriting are two doors into the same table.

        The factor is resolved in `override_row_extras`, which both paths go
        through; a resolver wired into only one would leave whichever door the
        next list came through publishing the default.
        """
        rows = [{"source": {"uuid": "s-1", "unit": "kg"}, "target": {"uuid": "t-old"}}]
        result = apply_match_overrides(rows, self._file(self._oil()), release="3.8")
        self.assertEqual(result[0]["conversion_factor"], 42.3)

    def test_a_release_nobody_checked_is_refused(self):
        """Refused, not defaulted, and that is the whole of the issue.

        Defaulting is exactly what published 43.4 against ecoinvent 3.8 and
        scored its oil chains 2.6% high. There is no safe silent answer: the
        default is a number nobody compared against this release, so the only
        useful thing to do is name the row that has to be re-read.
        """
        with self.assertRaises(ValueError) as caught:
            apply_match_overrides([], self._file(self._oil()), release="3.13")
        message = str(caught.exception)
        self.assertIn("3.13", message)
        self.assertIn("Something", message)

    def test_a_caller_naming_no_release_asks_nothing(self):
        """The 3.8 composition and every test reading the table's shape hold no
        list, exactly as they hold no flows for the renumbering check."""
        result = apply_match_overrides([], self._file(self._oil()))
        self.assertEqual(result[0]["conversion_factor"], 43.4)

    def test_a_row_stating_no_factor_is_never_asked(self):
        result = apply_match_overrides([], self._file(_override()), release="3.13")
        self.assertNotIn("conversion_factor", result[0])

    def test_a_factor_with_no_releases_is_refused(self):
        with self.assertRaises(ValueError):
            apply_match_overrides([], self._file(_override(
                conversion_factor=43.4,
                source_unit="kg",
                target_unit="MJ",
                conversion_checked_against=[],
            )))

    def test_a_release_on_both_sides_is_refused(self):
        """One question, one answer: the default and an override cannot both
        claim a release without the row failing to say which it converts by."""
        with self.assertRaises(ValueError):
            apply_match_overrides([], self._file(self._oil(
                conversion_checked_against=["3.8", "3.9.1"],
            )))

    def test_a_per_release_factor_the_unit_table_implies_is_refused(self):
        """A release's own number is the same kind of assertion as the default
        and is checked the same way."""
        with self.assertRaises(ValueError):
            apply_match_overrides([], self._file(_override(
                conversion_factor=0.599,
                source_unit="kg",
                target_unit="kg",
                conversion_checked_against=["3.9.1"],
                conversion_by_release={"3.8": 1.0},
            )))

    def test_a_release_scope_without_a_factor_is_refused(self):
        """Most likely the factor was removed and its scope left behind, which
        reads like a decision and is not one."""
        with self.assertRaises(ValueError):
            apply_match_overrides([], self._file(_override(
                conversion_checked_against=["3.8"],
            )))

    def test_the_two_revised_carriers_state_their_releases(self):
        """The real file, not a fixture: crude oil and natural gas each name
        3.8's number, and no other ecoinvent conversion does."""
        from brightway_flows.filesystem import PACKAGE_DATA_DIR
        from brightway_flows.match_overrides import load_match_overrides

        overrides = load_match_overrides(
            PACKAGE_DATA_DIR / "ecoinvent-match-overrides.json"
        )
        by_release = {
            o.source_name: dict(o.conversion_by_release)
            for o in overrides
            if o.converts and o.conversion_by_release
        }
        self.assertEqual(by_release, {
            "Oil, crude, in ground": {"3.8": 42.3},
            "Gas, natural, in ground": {"3.8": 34.5},
        })
        for override in overrides:
            if override.converts:
                with self.subTest(flow=override.source_name):
                    self.assertTrue(override.covers_release("3.8"))
                    self.assertTrue(override.covers_release("3.12"))
                    self.assertFalse(override.covers_release("3.13"))


class CuratedConversionTestCase(unittest.TestCase):
    """A conversion travels with the target, for the reason the target does."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)

    def _file(self, *overrides):
        path = self.dir / "overrides.json"
        path.write_bytes(orjson.dumps({"overrides": list(overrides)}))
        return path

    def _converting(self, **fields):
        row = {
            "conversion_factor": 0.599,
            "source_unit": "kg",
            "target_unit": "kg",
        }
        row.update(fields)
        return _override(**row)

    def test_the_factor_and_both_units_reach_a_rewritten_row(self):
        rows = [{"source": {"uuid": "s-1", "unit": "kg"}, "target": {"uuid": "t-old"}}]
        result = apply_match_overrides(rows, self._file(self._converting()))
        self.assertEqual(result[0]["conversion_factor"], 0.599)
        self.assertEqual(result[0]["target"]["unit_name"], "kg")
        self.assertEqual(result[0]["source"]["unit"], "kg")

    def test_the_factor_and_both_units_reach_an_appended_row(self):
        """A table can simply omit the flow -- 3.8's composed one omits every
        flow no route reaches -- and an appended row has to stand on its own."""
        result = apply_match_overrides([], self._file(self._converting()))
        self.assertEqual(result[0]["conversion_factor"], 0.599)
        self.assertEqual(result[0]["target"]["unit_name"], "kg")
        self.assertEqual(result[0]["source"]["unit"], "kg")

    def test_a_row_stating_no_conversion_gains_no_units(self):
        """Inventing a unit on a row that needs none would publish one nobody
        checked."""
        result = apply_match_overrides([], self._file(_override()))
        self.assertNotIn("conversion_factor", result[0])
        self.assertNotIn("unit_name", result[0]["target"])
        self.assertNotIn("unit", result[0]["source"])

    def test_a_rewritten_target_drops_the_factor_it_did_not_ask_for(self):
        """A factor is about a pair, so changing the target ends it.

        The table sent ecoinvent's coal-mine off-gas to EF 3.1's natural gas and
        stated 36 MJ per standard cubic metre for the privilege.  Redirected to
        EF's own coal-mine flow (#80) that number is about nothing: it survived
        the rewrite, beside a target the override gave no unit at all, and
        `conversion_from_prepared_rows` published it.
        """
        rows = [{
            "source": {"uuid": "s-1", "unit": "sm3"},
            "target": {"uuid": "t-old", "unit_name": "MJ"},
            "conversion_factor": 36.0,
        }]
        result = apply_match_overrides(rows, self._file(_override()))
        self.assertNotIn("conversion_factor", result[0])
        self.assertEqual(_target_uuid(result[0]), "t-new")

    def test_an_override_restating_a_factor_keeps_its_own(self):
        """Dropping the inherited one is not refusing to carry any."""
        rows = [{
            "source": {"uuid": "s-1", "unit": "kg"},
            "target": {"uuid": "t-old", "unit_name": "MJ"},
            "conversion_factor": 36.0,
        }]
        result = apply_match_overrides(rows, self._file(self._converting()))
        self.assertEqual(result[0]["conversion_factor"], 0.599)
        self.assertEqual(result[0]["target"]["unit_name"], "kg")


class CoarseParticulateTestCase(unittest.TestCase):
    """The decision the file was generalised for (#37), and its retirement (#196).

    EF 3.1 gives `particles (PM2.5 - PM10)` no characterisation factor in any
    compartment, so mapping ecoinvent's coarse fraction onto it scored that
    fraction at zero and put every EF 3.1 result 14% below what existing tools
    report; five rows sent the fraction to `particles (PM10)` instead.  Since
    the size-window convention gives the coarse band PM10's number, the rows
    score the same on the band they name, and the five rows -- which published
    a `skos:exactMatch` saying the coarse fraction *is* PM10 -- are gone.  The
    check is that no version sends the coarse fraction to PM10 by a curated
    row any more: the size table, not this file, places it.
    """

    def test_every_ecoinvent_version_declares_the_overrides(self):
        ecoinvent = [
            source for source in known_source_lists().values()
            if source.list_name == "ecoinvent"
        ]
        self.assertEqual(len(ecoinvent), 5)
        for source in ecoinvent:
            with self.subTest(source.key):
                self.assertEqual(source.match_overrides_path, OVERRIDES_PATH)
                self.assertEqual(source.missing_curated_inputs(), [])

    def test_no_ecoinvent_version_sends_the_coarse_fraction_to_pm10_by_a_curated_row(self):
        for key in sorted(
            source.key for source in known_source_lists().values()
            if source.list_name == "ecoinvent"
        ):
            rows = load_prepared_match_table(resolve_source_list(key))
            by_source: dict[str, set[str]] = {}
            for row in rows:
                by_source.setdefault(_source_uuid(row), set()).add(_target_uuid(row))
            for source_uuid, pm10_uuid in COARSE_PARTICULATES.items():
                with self.subTest(key=key, flow=source_uuid):
                    self.assertNotIn(pm10_uuid, by_source.get(source_uuid, set()))

    def test_every_ecoinvent_version_maps_butanediol_to_butylene_glycol(self):
        """#140: the family's own registration, 110-63-4 in every release, is
        butane-1,4-diol, and the flows land on EF's `butylene glycol` rather
        than the epichlorohydrin adduct the published table named.  The adduct
        must keep its own EF entry: the decision unmaps ecoinvent's butanediol
        from it, and does not touch the adduct as a substance.
        """
        for key in sorted(
            source.key for source in known_source_lists().values()
            if source.list_name == "ecoinvent"
        ):
            rows = load_prepared_match_table(resolve_source_list(key))
            by_source: dict[str, set[str]] = {}
            for row in rows:
                by_source.setdefault(_source_uuid(row), set()).add(_target_uuid(row))
            for source_uuid, target_uuid in BUTANEDIOL.items():
                with self.subTest(key=key, flow=source_uuid):
                    self.assertEqual(by_source.get(source_uuid), {target_uuid})
                    self.assertNotIn(
                        BUTANEDIOL_ADDUCT_TARGET, by_source.get(source_uuid, set())
                    )

    def test_the_composed_38_table_is_retired_and_decides_nothing(self):
        """The checked-in 3.8 table was composed, reviewed and loaded until
        #141 retired every prepared table: no manifest names it now, so what
        3.8 loads is the override rows alone, onto an empty table.  The file
        itself stays in `data/` as the record of what the composition decided
        and now it has gone to git history with the composing tool, closing
        the follow-up named on #141.  What this test holds is the live
        contract: everything 3.8 loads is an override row."""
        source = resolve_source_list("ecoinvent-3.8")
        self.assertIsNone(source.prepared_match_table)
        loaded = load_prepared_match_table(source)
        self.assertTrue(loaded)
        self.assertTrue(all(row.get("route") == "override" for row in loaded))


class TrivalentChromiumTestCase(unittest.TestCase):
    """One substance cannot answer to two elements by compartment (#45).

    Every published ecoinvent table maps `Chromium III` to EF 3.1's unspeciated
    `chromium` in air and soil and to `chromium (iii)` in water, though the
    source flow is one substance with one CAS.  EF 3.1 gives that unspeciated
    flow exactly the factors it gives `chromium (vi)`, so the air and soil half
    scores trivalent chromium as hexavalent.  The check is that every version
    now sends all nine to the trivalent flow of their own context.
    """

    def test_every_ecoinvent_version_maps_it_to_the_trivalent_flow(self):
        for key in sorted(
            source.key for source in known_source_lists().values()
            if source.list_name == "ecoinvent"
        ):
            rows = load_prepared_match_table(resolve_source_list(key))
            by_source: dict[str, set[str]] = {}
            for row in rows:
                by_source.setdefault(_source_uuid(row), set()).add(_target_uuid(row))
            for source_uuid, target_uuid in TRIVALENT_CHROMIUM.items():
                with self.subTest(key=key, flow=source_uuid):
                    self.assertEqual(by_source.get(source_uuid), {target_uuid})

    def test_the_water_flows_are_left_to_the_published_tables(self):
        """They already land on `chromium (iii)`, and an override that restated
        a target the table agrees with would look like a decision when the next
        release moved it."""
        claimed = {
            override.source_uuid for override in load_match_overrides(OVERRIDES_PATH)
        }
        for source_uuid in TRIVALENT_CHROMIUM_IN_WATER:
            with self.subTest(source_uuid):
                self.assertNotIn(source_uuid, claimed)


class StandingWoodTestCase(unittest.TestCase):
    """Hardwood and unspecified wood are not primary-forest wood (#81).

    EF 3.1 ships two standing-wood flows against ecoinvent's four, so every
    published table puts hardwood and unspecified wood on
    `Wood, primary forest, standing` -- the one target left over, and the
    strongest claim this list can make about timber.  There is no third flow to
    rewrite them onto, so both are declined and mint consensus flows of their
    own.

    What is checked is both halves of the decision: that no version's table
    still routes those two, and that the two rows the tables get right are left
    exactly as they are.  A decline that took the whole family with it would
    pass a test that only looked at the first half.
    """

    def test_no_version_routes_hardwood_or_unspecified_wood(self):
        for key in sorted(
            source.key for source in known_source_lists().values()
            if source.list_name == "ecoinvent"
        ):
            rows = load_prepared_match_table(resolve_source_list(key))
            routed = {_source_uuid(row) for row in rows}
            for source_uuid, name in STANDING_WOOD_DECLINED.items():
                with self.subTest(key=key, flow=name):
                    self.assertNotIn(source_uuid, routed)

    def test_no_wood_row_is_touched_by_an_override_any_more(self):
        """The declines took hard and unspecified standing wood off a table
        that folded them into EF's `Wood, primary forest, standing`; #141
        retired the table, and the two rows the fold *kept* -- primary forest
        and softwood -- now mint or match their own substances by name, which
        is the symmetric outcome the declines argued for.  What must stay true
        is that no override reintroduces a fold: the four wood flows are
        nobody's rows but their own."""
        overrides = {
            override.source_uuid for override in load_match_overrides(OVERRIDES_PATH)
        }
        for source_uuid in list(STANDING_WOOD_DECLINED) + list(STANDING_WOOD_KEPT):
            with self.subTest(flow=source_uuid):
                self.assertNotIn(source_uuid, overrides)


class TrichloroethaneIsomersTestCase(unittest.TestCase):
    """An ozone-depleting solvent must not be published as its isomer (#121).

    EF 3.1 names five flows -- exactly the five air compartments --
    `1,1,1-trichloroethane` while giving them 79-00-5, which is
    1,1,2-trichloroethane's registry number.  Every published table was built
    against EF's names, so all of them send ecoinvent's emissions of
    1,1,1-trichloroethane to air onto those five flows, and this list -- which
    settles the contradiction by trusting the number -- publishes them as the
    carcinogen.  The ten emissions to water are sent to the solvent correctly,
    so one ecoinvent substance was split by compartment across two published
    substances.

    Both halves are checked, because the fix is about which rows move.  The
    five air flows have to reach `hcfc-140` in every version, and the five
    water flows -- which every table already gets right -- have to be left
    exactly where they are.  An override family that took the whole substance
    with it would pass a test that only looked at the first half.
    """

    #: ecoinvent's five emissions of 1,1,1-trichloroethane to air, by
    #: compartment, and the EF 3.1 `hcfc-140` flow of the matching compartment
    #: each now maps to.  The source uuids are stable from 3.8 to 3.12 and
    #: carry 71-55-6 in every one of them; 3.9.1 alone spells the name
    #: `Ethane, 1,1,1-trichloro-, HCFC-140`, which is a rename and not a
    #: renumbering, so no row here is guarded.
    SOLVENT_TO_AIR = {
        "ce6294f5-2ed7-46ee-a967-33e265e34455": "d86cafdf-6555-11dd-ad8b-0800200c9a66",
        "818cee9e-231c-4b53-8ed2-47a0001802d5": "4d9a8790-3ddd-11dd-925b-0050c2490048",
        "99585564-bfce-4845-9aaa-2f24b8f26a41": "4d9a8790-3ddd-11dd-925c-0050c2490048",
        "f8ee4881-a003-4e18-aa2a-d9daf97d76f7": "4d9a8790-3ddd-11dd-925a-0050c2490048",
        "9e7d019f-c8c0-4631-9bbb-ced3e081c90d": "d86cafe1-6555-11dd-ad8b-0800200c9a66",
    }

    def test_every_ecoinvent_version_maps_the_air_rows_to_the_solvent(self):
        for key in sorted(
            source.key for source in known_source_lists().values()
            if source.list_name == "ecoinvent"
        ):
            rows = load_prepared_match_table(resolve_source_list(key))
            by_source: dict[str, set[str]] = {}
            for row in rows:
                by_source.setdefault(_source_uuid(row), set()).add(_target_uuid(row))
            for source_uuid, target_uuid in self.SOLVENT_TO_AIR.items():
                with self.subTest(key=key, flow=source_uuid):
                    self.assertEqual(by_source.get(source_uuid), {target_uuid})

    def test_the_water_rows_are_left_to_the_published_tables(self):
        """The half that stops this widening into a rule about the substance.

        Every table already sends them to the solvent, and an override that
        restated a target the table agrees with would look like a decision the
        next release had moved.  Read off the tables rather than pinned as a
        literal: what is being asserted is that no water row of this substance
        is claimed here, whichever uuids the releases use for them.
        """
        claimed = {
            override.source_uuid for override in load_match_overrides(OVERRIDES_PATH)
        }
        keys = sorted(
            source.key for source in known_source_lists().values()
            if source.list_name == "ecoinvent"
        )
        missing = [k for k in keys if not resolve_source_list(k).flows_path.exists()]
        if missing:
            raise unittest.SkipTest(f"flows not fetched for {', '.join(missing)}")
        for key in keys:
            source_list = resolve_source_list(key)
            flows = orjson.loads(source_list.flows_path.read_bytes())
            water = [
                flow for flow in flows
                if str(flow.get("cas_number") or "") == "71-55-6"
                and (flow.get("context") or [""])[0] == "water"
            ]
            with self.subTest(key=key):
                self.assertTrue(water, f"{key} ships no water rows for the solvent")
            for flow in water:
                with self.subTest(key=key, flow=flow["uuid"]):
                    self.assertNotIn(flow["uuid"], claimed)

    def test_no_air_row_is_left_pointing_at_the_carcinogens_flows(self):
        """Stated against the five EF flows rather than against the five
        targets, so that a target uuid mistyped into the table above cannot
        make this pass by accident."""
        carcinogen_air_flows = {
            "08a91e70-3ddc-11dd-9304-0050c2490048",
            "fe0acd60-3ddc-11dd-a323-0050c2490048",
            "fe0acd60-3ddc-11dd-a324-0050c2490048",
            "fe0acd60-3ddc-11dd-a325-0050c2490048",
            "e2fb04c3-6555-11dd-ad8b-0800200c9a66",
        }
        for key in sorted(
            source.key for source in known_source_lists().values()
            if source.list_name == "ecoinvent"
        ):
            rows = load_prepared_match_table(resolve_source_list(key))
            for row in rows:
                if _source_uuid(row) in self.SOLVENT_TO_AIR:
                    with self.subTest(key=key, flow=_source_uuid(row)):
                        self.assertNotIn(_target_uuid(row), carcinogen_air_flows)


class PesticideCommonNamesTestCase(unittest.TestCase):
    """A pesticide's common name belongs to one chemical (#119).

    EF 3.1 gives five substances' ordinary names to chemical relatives, and the
    correspondence table reads those names.  Three of the five have the right
    substance in EF 3.1 in every compartment, so their rows are rewritten onto
    it; two have nothing right to reach, so their rows are declined and the
    merge mints a consensus flow instead.

    Both halves are checked here.  The table already reaches the right target
    in some compartments -- agricultural soil for all three of the rewritten
    substances -- and those rows carry no override at all: the fix is that the
    remaining compartments agree with them, not that every compartment is
    restated.  A change that started rewriting the rows the table gets right
    would pass a test that only looked at the first half.
    """

    #: ecoinvent's flow, and the EF 3.1 flow carrying its own registry number in
    #: the same compartment.  Paraquat 4685-14-7, MCPA 94-74-6 and mecoprop-P
    #: 16484-77-8; the uuids arrive at 3.11 and are unchanged in 3.12.
    REDIRECTED = {
        "43a76088-d768-4807-b70b-049019c9b3f7": "fafd0232-2d04-483c-b8f4-0d8f76badb6d",
        "3c3c3e04-f98e-5b9e-a0b3-1a26debfe53f": "85c53554-6efb-4fcb-b9de-8b15f2c27da5",
        "ae104158-bdca-5c0f-b1e4-32e34d788df7": "0131c82e-8971-439f-bf4d-3b2ab971b69f",
        "d9f61aec-1979-579a-a558-dd8aca972b81": "29f91915-f685-4315-9f01-5a86385d5a73",
        "d024c3cc-bac9-5010-a2ed-a30f387e9270": "fc80104d-47e2-40ad-8d04-7eccd4121c25",
        "4bdafb88-3306-583f-9b70-56d73a6b34d6": "fe0acd60-3ddc-11dd-af1c-0050c2490048",
        "9e63abd9-8d70-5b02-aa1f-8a71700dd9de": "fe0acd60-3ddc-11dd-9e66-0050c2490048",
        "6f2c2b45-b402-51c8-8086-f6da256fa832": "fe0acd60-3ddc-11dd-af16-0050c2490048",
        "b1736122-ffce-570c-a0a5-162514d3a21b": "fe0acd60-3ddc-11dd-af1d-0050c2490048",
        "2d0edb0e-63e7-58d6-a484-6866a74f2c96": "5892355e-9647-42fe-afd0-00869b37152e",
        "c990d84f-f86f-5a02-86c9-a8de2ba2519a": "11fa7c35-31ac-42d8-89b7-878646fdecd6",
        "f6b617b4-6ebd-5cc2-b2ea-6f91268468ff": "f0aebe1d-986b-4393-8789-5a3891e91cbc",
        "aa8d1b1b-fe70-5bf4-8c63-9309ed2c9e45": "49c930d4-09e5-4759-b33b-529da407d3ad",
        "f7b5512b-d474-5dc1-b7d3-b64bea3a504b": "456652f8-0fa4-43c5-898c-afd832e61a1e",
        "232f0aae-8afd-5769-ad9b-dc4e06b40544": "560cd91d-576e-456d-865b-bd54eff59e44",
    }

    #: The flows with nowhere right to go.  Flupyrsulfuron-methyl's parent acid,
    #: 144740-53-4, which no EF 3.1 flow carries, and gypsum, 13397-24-5, which
    #: no EF 3.1 flow carries either.
    DECLINED = {
        "fd03e7bd-4621-57ce-9172-f2d30cb5443b": "Flupyrsulfuron-methyl, air",
        "3fd67b6a-46ca-540f-959a-108dd7f600f0": "Flupyrsulfuron-methyl, non-urban air",
        "79db116b-7594-53d7-8e33-953263d2bf5c": "Flupyrsulfuron-methyl, soil",
        "7eed2384-c082-57a1-b571-2a9647bea929": "Flupyrsulfuron-methyl, forestry soil",
        "6409177d-4869-59cd-b3a9-09e714e38d64": "Flupyrsulfuron-methyl, water",
        "4c64df7c-e3e2-5cae-abd4-011faa84e3ac": "Flupyrsulfuron-methyl, surface water",
        "0c77f5af-0a0b-4205-acb6-0b031c22029f": "Flupyrsulfuron-methyl, agricultural soil",
        "11a2a7b1-ab2f-47b8-9e29-6f33d5207fa6": "Gypsum, in ground",
    }

    #: The rows the published tables already get right, and must go on getting
    #: right without an override: each substance in agricultural soil, plus
    #: paraquat in non-urban air and MCPA in the two water compartments.
    ALREADY_RIGHT = {
        "e170546d-a672-4840-bd7a-1c7f8b627286": "e1baa14e-3363-4e99-91cb-a93aa8d295a7",
        "a794b444-2b77-4449-8592-0efda101b0c2": "11936eb8-1423-4d79-adab-280cb918aa4d",
        "e5492922-eaf5-4409-aa49-7f2a35cd0336": "fe0acd60-3ddc-11dd-9e65-0050c2490048",
        "fc3c75dc-e39c-463b-8b26-96cfc0ed4b47": "fe0acd60-3ddc-11dd-af1a-0050c2490048",
        "081ea9c3-9cbe-41d7-a962-840833ba98db": "fe0acd60-3ddc-11dd-af1a-0050c2490048",
        "41c97929-4fc4-4c35-bdf8-f999e4b492fd": "fe0acd60-3ddc-11dd-af19-0050c2490048",
        "0f901f59-84bd-42a5-9a4c-04bd8cac7fb9": "5fb3229a-3f82-4bb9-b2cd-fccf9d7be7e5",
    }

    #: ecoinvent's own flows for the relatives EF named after their parents.
    #: These are correctly placed and nothing here may move them.
    THE_RELATIVES_OWN_FLOWS = {
        "0eb6b65c-eb5a-5bd3-b3cf-8bbd6823ba82": "4d9a8790-3ddd-11dd-961a-0050c2490048",
        "36aa0b45-1850-575d-9e40-352d8b95860c": "fe0acd60-3ddc-11dd-9ecd-0050c2490048",
        "fb28e710-f81a-5991-9be3-d6674a5a67a8": "0124ddee-1363-4865-9db9-a062f49ee7a4",
        "ffd4a2ad-2e43-59e8-a575-71dc22e8cca1": "bc79942f-dc4d-4c83-a58c-d9774c508802",
    }

    def _tables(self):
        for key in sorted(
            source.key for source in known_source_lists().values()
            if source.list_name == "ecoinvent"
        ):
            yield key, load_prepared_match_table(resolve_source_list(key))

    def _targets(self, rows):
        by_source: dict[str, set[str]] = {}
        for row in rows:
            by_source.setdefault(_source_uuid(row), set()).add(_target_uuid(row))
        return by_source

    def test_every_version_sends_the_parent_to_its_own_registry_number(self):
        for key, rows in self._tables():
            targets = self._targets(rows)
            for source_uuid, target_uuid in self.REDIRECTED.items():
                if source_uuid not in targets:
                    continue  # a release that does not ship the flow
                with self.subTest(key=key, flow=source_uuid):
                    self.assertEqual(targets[source_uuid], {target_uuid})

    def test_no_version_routes_the_flows_with_nowhere_right_to_go(self):
        for key, rows in self._tables():
            routed = {_source_uuid(row) for row in rows}
            for source_uuid, name in self.DECLINED.items():
                with self.subTest(key=key, flow=name):
                    self.assertNotIn(source_uuid, routed)

    def test_the_rows_the_tables_get_right_carry_no_override(self):
        """The correction is that the other compartments agree with these, not
        that every compartment is restated.  An override on one of these would
        be a decision nobody needed and a row to re-check at the next
        release."""
        overridden = {
            override.source_uuid for override in load_match_overrides(OVERRIDES_PATH)
        }
        for source_uuid in {**self.ALREADY_RIGHT, **self.THE_RELATIVES_OWN_FLOWS}:
            with self.subTest(source_uuid):
                self.assertNotIn(source_uuid, overridden)

    def test_the_rows_the_tables_get_right_still_reach_that_target(self):
        for key, rows in self._tables():
            targets = self._targets(rows)
            expected = {**self.ALREADY_RIGHT, **self.THE_RELATIVES_OWN_FLOWS}
            for source_uuid, target_uuid in expected.items():
                if source_uuid not in targets:
                    continue
                with self.subTest(key=key, flow=source_uuid):
                    self.assertEqual(targets[source_uuid], {target_uuid})

    def test_no_pesticide_decline_lingers(self):
        """The declines this class pinned -- flupyrsulfuron's renumbered rows
        among them -- took pesticide rows off a table that folded them into
        EF's catch-alls or a near relative.  #141 retired the tables and the
        spent declines went with them; the durable guard is in
        `tests/test_pesticide_catch_alls.py`, which holds that nothing routes
        a named substance to a bucket any more.  Here: none of the pinned
        rows may reappear in the override file with any verdict at all --
        matching decides them now, and an override touching one is a new
        decision that owes its own reasoning."""
        overrides = {
            override.source_uuid for override in load_match_overrides(OVERRIDES_PATH)
        }
        pinned = set(self.DECLINED) | {"0c77f5af-0a0b-4205-acb6-0b031c22029f"}
        for source_uuid in sorted(pinned):
            with self.subTest(flow=source_uuid):
                self.assertNotIn(source_uuid, overrides)


if __name__ == "__main__":
    unittest.main()
