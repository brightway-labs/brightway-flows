"""A match whose two sides measure different quantities.

A correspondence table says which target a source flow maps to; it does not say
the two are measured in the same unit. ecoinvent 3.8's `Manganese-55` becomes
`Manganese` under an unchanged UUID while its unit goes from kBq to kg, and no
table records it.

The guard reports and never converts, because a dimension change is usually an
error but not always: EF 3.1 accounts fossil carriers by energy content on
purpose. What it must never do is withhold the match or report it as unmatched
-- `accumulator.unmatched` feeds the manual-additions pass, which creates
elementary flows, so an already-matched flow reported there would be duplicated.
"""

import unittest
from dataclasses import dataclass

import orjson

from brightway_flows.merge.unit_changes import (
    ALLOWLIST_FILEPATH,
    canonical_unit,
    crosses_quantity_kinds,
    find_unit_mismatches,
    load_unit_change_allowlist,
    report_unrecorded_crossings,
)
from brightway_flows.transformers.unit_normalization import build_units_index

UNITS = build_units_index()


@dataclass
class Match:
    """The fields the guard reads; `PreparedMatch` and `AlgorithmMatch` share them."""

    source_uuid: str = "s-1"
    source_name: str = "a flow"
    source_unit: str = "kg"
    target_unit: str = "kg"
    target_elementary_flow_id: str = "t-1"


def _find(matches, allowed=frozenset()):
    return find_unit_mismatches(matches, units_index=UNITS, allowed=set(allowed))


class DisagreementIsReportedTestCase(unittest.TestCase):
    def test_a_dimension_change_is_reported(self):
        self.assertEqual(_find([Match(source_unit="kBq", target_unit="kg")]), {"s-1"})

    def test_matching_units_are_not_reported(self):
        self.assertEqual(_find([Match(source_unit="kg", target_unit="kg")]), set())

    def test_an_allowlisted_pair_is_not_reported(self):
        matches = [Match(source_unit="kg", target_unit="MJ")]
        self.assertEqual(_find(matches, allowed={("s-1", "t-1")}), set())

    def test_the_allowlist_is_keyed_on_the_pair_not_the_source(self):
        """The same flow can be accepted against one target and wrong against
        another. `Gas, mine, off-gas` is both: sm3 to MJ against EF 3.1's
        natural gas, and m3 to Sm3 within ecoinvent."""
        matches = [Match(source_unit="kg", target_unit="MJ", target_elementary_flow_id="t-2")]
        self.assertEqual(_find(matches, allowed={("s-1", "t-1")}), {"s-1"})


class BothSidesAreCanonicalisedTestCase(unittest.TestCase):
    """The source side is canonical by the time it reaches the merge; the
    target side is whatever the flow record stores."""

    def test_notation_differences_are_not_disagreements(self):
        self.assertEqual(_find([Match(source_unit="m2.a", target_unit="m2*a")]), set())

    def test_canonical_unit_resolves_known_notations(self):
        self.assertEqual(canonical_unit("m2*a", UNITS), canonical_unit("m2.a", UNITS))

    def test_an_unknown_unit_is_compared_as_it_arrived(self):
        """Not an error: the merge already refuses a source unit it cannot
        normalise, and an unknown target unit is a reason to report the pair."""
        self.assertEqual(canonical_unit("widgets", UNITS), "widgets")
        self.assertEqual(_find([Match(source_unit="widgets", target_unit="kg")]), {"s-1"})


class AMissingUnitIsNotADisagreementTestCase(unittest.TestCase):
    def test_no_source_unit_is_not_reported(self):
        self.assertEqual(_find([Match(source_unit="", target_unit="kg")]), set())

    def test_no_target_unit_is_not_reported(self):
        self.assertEqual(_find([Match(source_unit="kg", target_unit="")]), set())


class TheAllowlistTestCase(unittest.TestCase):
    def test_every_entry_states_its_reason(self):
        payload = orjson.loads(ALLOWLIST_FILEPATH.read_bytes())
        entries = payload["accepted"]
        self.assertTrue(entries)
        for entry in entries:
            with self.subTest(source=entry.get("source_name")):
                self.assertTrue(str(entry.get("comment") or "").strip())

    def test_an_entry_without_a_comment_does_not_silence_the_guard(self):
        """The comment is the entry's whole justification. Silencing the guard
        while asserting nothing is the one thing the file must not allow."""
        import tempfile
        from pathlib import Path

        bad = {"accepted": [{"source_uuid": "s-1", "target_elementary_flow_id": "t-1"}]}
        # Through the loader's own `path` rather than by patching
        # `Path.read_bytes` for the whole process: the loader is injectable and
        # uncached precisely so a fixture can be pointed at it (#92).
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "unit-change-allowlist.json"
            path.write_bytes(orjson.dumps(bad))
            self.assertEqual(load_unit_change_allowlist(path), set())

    def test_the_checked_in_entries_load(self):
        allowed = load_unit_change_allowlist()
        # It was 25 from #89, which accepted BAFU's biotic peat kilogram
        # against EF's megajoule peat: the row is the fuel, so it takes the
        # same 9.76 MJ/kg its `in ground` sibling already had.
        #
        # 40 since #171 answered the fifteen crossings that had no entry at
        # all: Stepwise 2006's twelve energy carriers, which are the same
        # assertion already accepted for ecoinvent and BAFU; two ecoinvent
        # `Manganese-55` rows whose entries named a target the water-context
        # work moved them off; and BAFU's coal-mine off-gas in cubic metres
        # against the same flow in standard cubic metres, which this file's own
        # description had named as needing its own answer.
        #
        # 53 with AGRIBALYSE's water curation (#352): thirteen density
        # crossings the material table created by placing kilogram intakes on
        # cubic-metre flows and cubic-metre rows on kilogram flows -- fresh
        # water at 1000 kg/m3 and ocean water at the 1025 kg/m3 ecoinvent's
        # own `Water, salt, ocean` entry already records -- each carrying its
        # factor on the mapping in `agribalyse-3.2-match-overrides.json`.
        #
        # 55 since #354 rebased the two AGRIBALYSE rows whose names state
        # their own energy content -- wood and wood waste at 9.5 MJ/kg, ore-
        # bound uranium oxide at 332 GJ/kg -- onto the megajoule `Wood` and
        # `Uranium` flows, the vendor's own numbers carried as the factors.
        self.assertEqual(len(allowed), 55)
        self.assertIn(
            ("024c9722-1e88-412b-8c4b-10c532be8dca",
             "fe0acd60-3ddc-11dd-a6f9-0050c2490048"),
            allowed,
            "Coal, brown -> Brown Coal, kg to MJ",
        )
        self.assertIn(
            ("44360b86-a3d8-5623-b211-44ec41853fcd",
             "172a3db9-6556-11dd-ad8b-0800200c9a66"),
            allowed,
            "BAFU's Water, salt, ocean -> EF 3.1's sea water, m3 to kg, the "
            "24th and the second list to ship that vendor row (#78)",
        )

    def test_coal_mine_off_gas_needs_no_entry(self):
        """It had one, and #80 took the disagreement away rather than allowing it.

        The entry accepted ecoinvent's standard cubic metres landing on EF 3.1's
        natural gas in megajoules.  That pairing is gone -- the flow goes to EF's
        own coal-mine flow now -- and every list's copy of that flow is in `sm3`,
        so the two sides agree and there is nothing for the guard to report.  An
        entry surviving here would be silencing a guard that no longer fires,
        which reads as a reviewed disagreement rather than a resolved one.
        """
        allowed = load_unit_change_allowlist()
        self.assertEqual(
            [pair for pair in allowed
             if pair[0] == "3ed5f377-344f-423a-b5ec-9a9a1162b944"],
            [],
        )

    def test_bafu_reaches_the_same_targets_as_ecoinvent(self):
        """BAFU states the fossil carriers in kilograms too, so the same
        crossing has to be accepted for its flows as for ecoinvent's -- the file
        is keyed by source flow, so one list's acceptance says nothing about
        another's. Eleven entries: hard coal, brown coal, crude oil, peat,
        uranium in each of the three compartments BAFU files it under, and the
        two gas flows in each of the two unit spellings BAFU uses (#69)."""
        allowed = load_unit_change_allowlist()
        self.assertIn(
            ("80922cad-30bf-5248-ae0a-656cae92b95c",
             "fe0acd60-3ddc-11dd-a6f9-0050c2490048"),
            allowed,
            "BAFU Coal, brown -> Brown Coal, kg to MJ, beside ecoinvent's",
        )
        self.assertIn(
            ("25d290ab-0e08-5963-9141-cbcbb998c559",
             "e2fba107-6555-11dd-ad8b-0800200c9a66"),
            allowed,
            "BAFU Peat -> Peat, kg to MJ; no ecoinvent counterpart exists",
        )

    def test_the_coal_mine_off_gas_needs_no_bafu_entry_either(self):
        """#291 asked for one, reading BAFU's `Nm3` against the flow's `sm3` as a
        5% physical difference.  It is not one: for gas both are 15.00 C at
        101.325 kPa, so `Nm3` normalises to `sm3` and the guard has nothing to
        report (#292).  An entry here would record a reviewed disagreement where
        there is none, which is what this file must not contain."""
        allowed = load_unit_change_allowlist()
        self.assertEqual(
            [pair for pair in allowed
             if pair[0] == "8fd7095d-f33f-580a-8018-2d24479170ca"],
            [],
        )

    def test_manganese_55_is_accepted_as_an_inert_defect(self):
        """kBq onto elemental manganese in kg, with nothing to convert by: 55Mn
        is manganese's stable isotope and has no activity. Accepted rather than
        removed because no ecoinvent 3.8 dataset uses the flow at all, so the
        pairing mischaracterises nothing and dropping it would leave five
        permanent rows in the unmatched report."""
        allowed = load_unit_change_allowlist()
        self.assertIn(
            ("583eec00-1480-4cd7-8670-31eaf94053ad",
             "08a91e70-3ddc-11dd-9bcc-0050c2490048"),
            allowed,
        )

    def test_actinium_is_fixed_at_the_source_rather_than_allowlisted(self):
        """The guard's first real finding, and the one it was right about.

        EF 3.1 pointed the flow at 'Net calorific value' while labelling the
        reference 'Radioactivity', so it published in MJ; ecoinvent gives
        actinium in kg. Allowlisting would have recorded a mistyped pointer as
        a decision, so the unit is corrected in `ef-3.1-manual-fixes.json` and
        the mismatch stops existing rather than being accepted.
        """
        import orjson

        from brightway_flows.sources import PACKAGE_DATA_DIR

        self.assertNotIn(
            ("7781bd84-0ca4-5bf1-8fc5-15cdc1fb0796",
             "08a91e70-3ddc-11dd-91b3-0050c2490048"),
            load_unit_change_allowlist(),
        )
        fixes = orjson.loads(
            (PACKAGE_DATA_DIR / "ef-3.1-manual-fixes.json").read_bytes()
        )["fixes"]
        actinium = [
            fix for fix in fixes
            if (fix.get("match") or {}).get("uuid")
            == "08a91e70-3ddc-11dd-91b3-0050c2490048"
        ]
        self.assertEqual(len(actinium), 1)
        self.assertEqual(actinium[0]["field"], "unit")
        self.assertEqual(actinium[0]["original_value"], "MJ")
        self.assertEqual(actinium[0]["new_value"], "kg")



class QuantityKindCrossingTestCase(unittest.TestCase):
    """#171: which unit disagreements are the ones a curator has to answer.

    `find_unit_mismatches` reports every disagreement, and most of them need
    nobody: a becquerel against a kilobecquerel is one quantity at two scales
    and `units.json` converts it by itself.  What needs a written reason is a
    mapping whose two units measure *different kinds of quantity*, because no
    table converts a mass into an energy -- how many megajoules a kilogram is
    depends on the substance.
    """

    def test_a_scale_change_does_not_cross(self):
        self.assertFalse(crosses_quantity_kinds("Bq", "kBq"))
        self.assertFalse(crosses_quantity_kinds("km", "m"))

    def test_a_mass_onto_an_energy_crosses(self):
        self.assertTrue(crosses_quantity_kinds("kg", "MJ"))

    def test_an_activity_onto_a_mass_crosses(self):
        self.assertTrue(crosses_quantity_kinds("kBq", "kg"))

    def test_a_volume_onto_a_standard_volume_crosses(self):
        """The pair `units.json` deliberately keeps apart: a standard cubic
        metre is an amount of substance and a cubic metre is a volume."""
        self.assertTrue(crosses_quantity_kinds("m3", "sm3"))

    def test_two_spellings_of_one_unit_do_not_cross(self):
        self.assertFalse(crosses_quantity_kinds("m2.a", "m2*a"))

    def test_a_unit_the_table_does_not_know_does_not_cross(self):
        """Both halves of it.  An unreadable unit is its own problem, and
        reporting it here would assert something about the pair that has not
        been established."""
        self.assertFalse(crosses_quantity_kinds("kg", "not-a-unit"))
        self.assertFalse(crosses_quantity_kinds("not-a-unit", "kg"))
        self.assertFalse(crosses_quantity_kinds("", ""))


class UnrecordedCrossingTestCase(unittest.TestCase):
    def _report(self, matches, allowed=frozenset()):
        return report_unrecorded_crossings(
            matches, units_index=UNITS, allowed=set(allowed)
        )

    def test_a_crossing_with_no_entry_is_reported(self):
        self.assertEqual(
            self._report([Match(source_unit="kg", target_unit="MJ")]),
            [("s-1", "t-1")],
        )

    def test_an_allowlisted_crossing_is_not_reported(self):
        self.assertEqual(
            self._report(
                [Match(source_unit="kg", target_unit="MJ")], allowed={("s-1", "t-1")}
            ),
            [],
        )

    def test_a_scale_change_is_never_reported(self):
        """The half that keeps the count meaningful.  159 of the 177 unit
        disagreements on the four-list build of 2026-08-29 are becquerels
        against kilobecquerels, and a guard asking for a ruling on those would
        be asking for 159 entries that say what `units.json` already says."""
        self.assertEqual(self._report([Match(source_unit="Bq", target_unit="kBq")]), [])

    def test_the_pair_is_what_is_matched_and_not_the_source_flow(self):
        """The same flow can be accepted against one target and unruled against
        another, which is why the allowlist is keyed on the pair."""
        matches = [
            Match(source_uuid="s-1", target_elementary_flow_id="t-1",
                  source_unit="kg", target_unit="MJ"),
            Match(source_uuid="s-1", target_elementary_flow_id="t-2",
                  source_unit="kg", target_unit="MJ"),
        ]
        self.assertEqual(
            self._report(matches, allowed={("s-1", "t-1")}), [("s-1", "t-2")]
        )


class TheRealFileAnswersEveryCarrierTestCase(unittest.TestCase):
    """Stepwise's twelve energy carriers, checked against the files not a build.

    Each is listed in `unit-change-allowlist.json`, which accepts the crossing,
    and carries its conversion in `stepwise-2006-match-overrides.json`, which
    supplies the number.  Both halves are pinned because either alone is a
    half-answer: an accepted crossing with no number publishes a mass on an
    energy and leaves the reader to invent the factor, and a number with no
    entry leaves the guard reporting a pair somebody has in fact answered.
    """

    #: Stepwise's energy carriers, and the EF 3.1 flow each reaches.
    CARRIERS = {
        "7d86a5b7-c5d1-549b-aad3-29286a5e5346": "fe0acd60-3ddc-11dd-a6fc-0050c2490048",
        "cede79a3-3e82-562b-ac7c-8f0483604f8b": "fe0acd60-3ddc-11dd-a6f9-0050c2490048",
        "146c61d4-321a-53ef-b58e-35d53bc57de6": "fe0acd60-3ddc-11dd-a6f8-0050c2490048",
        "b28ffb76-dac7-5bdc-9aa9-f3a00f1ce266": "e2fba107-6555-11dd-ad8b-0800200c9a66",
        "2a7ddb41-4644-5f68-a2ac-81cf18772938": "3e4d2966-6556-11dd-ad8b-0800200c9a66",
        "177b2fed-48df-5222-b7a7-be3b71a0e73c": "fe0acd60-3ddc-11dd-a6fa-0050c2490048",
        "bbc7d9ed-0d3a-541b-8ea4-9b80d7c93b66": "fe0acd60-3ddc-11dd-a6fa-0050c2490048",
        "1da85908-9de5-5f8c-ad12-c5c2031a675d": "fe0acd60-3ddc-11dd-a6fa-0050c2490048",
        "00e5682e-99d0-53ca-9142-8ddb8c14325a": "fe0acd60-3ddc-11dd-a6fa-0050c2490048",
        "3e88af6a-0f31-5fb7-a035-7a4577e02c9b": "fe0acd60-3ddc-11dd-a6fa-0050c2490048",
        "01aa0043-f4ce-5461-9eab-6f7725cecbf2": "fe0acd60-3ddc-11dd-a6fa-0050c2490048",
        "26eeeb1c-17c9-539c-a654-3a995495c235": "fe0acd60-3ddc-11dd-a6fa-0050c2490048",
    }

    #: The six whose *name* states what a unit of the gas is worth.  The name is
    #: the vendor's own assertion of the quantity -- the rule
    #: `simapro-lineage-manual-fixes.json` applies to `Uranium, 451 GJ per kg` --
    #: so the factor and the name have to agree or one of them is wrong.
    NAMED_IN_THE_NAME = {
        "bbc7d9ed-0d3a-541b-8ea4-9b80d7c93b66": 30.3,
        "1da85908-9de5-5f8c-ad12-c5c2031a675d": 46.8,
        "00e5682e-99d0-53ca-9142-8ddb8c14325a": 46.8,
        "3e88af6a-0f31-5fb7-a035-7a4577e02c9b": 35.0,
        "01aa0043-f4ce-5461-9eab-6f7725cecbf2": 35.0,
        "26eeeb1c-17c9-539c-a654-3a995495c235": 36.6,
    }

    def setUp(self):
        from brightway_flows.filesystem import PACKAGE_DATA_DIR
        from brightway_flows.match_overrides import load_match_overrides

        self.allowed = load_unit_change_allowlist()
        self.overrides = {
            override.source_uuid: override
            for override in load_match_overrides(
                PACKAGE_DATA_DIR / "stepwise-2006-match-overrides.json"
            )
        }

    def test_every_carrier_crossing_is_accepted(self):
        for source_uuid, target in sorted(self.CARRIERS.items()):
            with self.subTest(flow=source_uuid):
                self.assertIn((source_uuid, target), self.allowed)

    def test_every_carrier_states_its_conversion(self):
        for source_uuid, target in sorted(self.CARRIERS.items()):
            with self.subTest(flow=source_uuid):
                override = self.overrides.get(source_uuid)
                self.assertIsNotNone(override)
                self.assertEqual(override.target_uuid, target)
                self.assertIsNotNone(override.conversion_factor)
                self.assertEqual(override.target_unit, "MJ")
                self.assertTrue(crosses_quantity_kinds(override.source_unit, "MJ"))

    def test_a_factor_the_name_states_is_the_factor_the_row_carries(self):
        for source_uuid, stated in sorted(self.NAMED_IN_THE_NAME.items()):
            override = self.overrides[source_uuid]
            with self.subTest(name=override.source_name):
                printed = f"{stated:g}"
                self.assertIn(printed, override.source_name)
                self.assertEqual(override.conversion_factor, stated)


if __name__ == "__main__":
    unittest.main()
