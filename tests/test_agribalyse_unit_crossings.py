"""AGRIBALYSE's 26 rows that cross a unit, each converted or accepted (#370).

On the first five-list build every one of these reached a flow measured in
another unit with nothing on the mapping between the two: `Gas, natural/m3` on
EF 3.1's megajoule `Natural Gas`, `Water` released by the kilogram on a
cubic-metre flow.  Each now either carries its factor in
`agribalyse-3.2-match-overrides.json` and is accepted in
`unit-change-allowlist.json`, or -- argon-40 and manganese-55, stable isotopes
with no activity -- is accepted with no number at all.

The heating values are AGRIBALYSE's own, the net values its export's substance
block states, which is the user's decision on #370; whether every list should
convert by its own value is #407.  The coal-mine off-gas rows reach natural gas
only because the vendor writes natural gas's registry number on them, so the
number comes off in the manual fixes, as #80 did for every other list.
"""

from __future__ import annotations

import copy
import unittest

import orjson

from brightway_flows.filesystem import PACKAGE_DATA_DIR
from brightway_flows.integrations.agribalyse import _flow_uuid
from brightway_flows.manual_fixes import apply_manual_fixes
from brightway_flows.match_overrides import load_match_overrides

OVERRIDES_PATH = PACKAGE_DATA_DIR / "agribalyse-3.2-match-overrides.json"
FIXES_PATH = PACKAGE_DATA_DIR / "agribalyse-3.2-manual-fixes.json"
ALLOWLIST_PATH = PACKAGE_DATA_DIR / "unit-change-allowlist.json"

NATURAL_GAS = "fe0acd60-3ddc-11dd-a6fa-0050c2490048"
OFF_GAS = "00fdc4bc-724b-4993-ad43-c70df533b092"
NATURAL_GAS_CAS = "8006-14-2"

#: uuid -> (vendor name, compartment, subcompartment, unit, target, factor,
#:          target unit)
CONVERTED = {
    "a7e4ae42-ba96-5583-87df-7b5e1a95ba89": ("Coal, hard", "Resources", "", "kg", "fe0acd60-3ddc-11dd-a6fc-0050c2490048", 18.2, "MJ"),
    "73592c08-9e10-5388-91ea-2e90c3de5bc3": ("Coal, hard", "Resources", "in ground", "kg", "fe0acd60-3ddc-11dd-a6fc-0050c2490048", 18.2, "MJ"),
    "c93d8b25-7b26-526d-96c4-417ab385f38a": ("Coal, brown", "Resources", "", "kg", "fe0acd60-3ddc-11dd-a6f9-0050c2490048", 8.75, "MJ"),
    "b958fc8c-ff3d-5499-af0d-897d4cc569e9": ("Coal, brown", "Resources", "in ground", "kg", "fe0acd60-3ddc-11dd-a6f9-0050c2490048", 8.75, "MJ"),
    "966368b2-34db-55ba-a84a-beb4533aaeb9": ("Oil, crude", "Resources", "", "kg", "fe0acd60-3ddc-11dd-a6f8-0050c2490048", 43.2, "MJ"),
    "92052d5f-40db-5440-b75f-6d86ea1ccfd5": ("Oil, crude", "Resources", "in ground", "kg", "fe0acd60-3ddc-11dd-a6f8-0050c2490048", 43.2, "MJ"),
    "99a20ba5-1e0c-5e9b-8c23-18c6a935a905": ("Uranium", "Resources", "", "kg", "3e4d2966-6556-11dd-ad8b-0800200c9a66", 560000.0, "MJ"),
    "4328482b-3230-5bad-b039-2a40af37e3a5": ("Uranium", "Resources", "in ground", "kg", "3e4d2966-6556-11dd-ad8b-0800200c9a66", 560000.0, "MJ"),
    "4e0fae84-bad2-5378-9a09-0d5b6ff09550": ("Gas, natural/m3", "Resources", "in ground", "m3", NATURAL_GAS, 34.5, "MJ"),
    "b71f49da-94c5-5015-a636-f03630a348af": ("Gas, natural/kg", "Resources", "", "kg", NATURAL_GAS, 43.1, "MJ"),
    "e87519c1-c32b-5d7b-9595-d29db06904e7": ("Gas, natural, 30.3 MJ per kg", "Resources", "in ground", "kg", NATURAL_GAS, 30.3, "MJ"),
    "9fdd888b-ae2b-54a1-a659-f6b1c5e5a2ac": ("Gas, natural, 46.8 MJ per kg", "Resources", "in ground", "kg", NATURAL_GAS, 46.8, "MJ"),
    "06156935-5f89-5754-968c-a068a2265517": ("Gas, natural, 35 MJ per m3", "Resources", "in ground", "m3", NATURAL_GAS, 35.0, "MJ"),
    "bf468574-1d70-522c-9077-637beb24f28f": ("Gas, natural, 36.6 MJ per m3", "Resources", "in ground", "m3", NATURAL_GAS, 36.6, "MJ"),
    "2e888763-5042-5f1f-af32-b0252d7584bf": ("Gas, mine, off-gas, process, coal mining/m3", "Resources", "in ground", "m3", OFF_GAS, 1.0, "sm3"),
    "6be68aec-e88a-51a6-a22a-b8e26d1c6947": ("Gas, mine, off-gas, process, coal mining/kg", "Resources", "in ground", "kg", OFF_GAS, 1.254, "sm3"),
    "3448032e-95f6-5eb3-a7a8-04141c3b95d1": ("Gas, mine, off-gas, process, coal mining/kg", "Resources", "", "kg", OFF_GAS, 1.254, "sm3"),
    "b5bffb1f-1e13-56b7-a45f-eb5c262078e4": ("Lead-210/kg", "Emissions to water", "", "kg", "4d9a8790-3ddd-11dd-9812-0050c2490048", 2.84e12, "kBq"),
    "345c7fd9-afa8-5a1a-a079-46274e660f01": ("Radium-226/kg", "Emissions to water", "", "kg", "08a91e70-3ddc-11dd-98c1-0050c2490048", 3.66e10, "kBq"),
    "8e15efc9-89ae-5dc2-afd1-2c53658144fd": ("Radium-228/kg", "Emissions to water", "", "kg", "fe0acd60-3ddc-11dd-aba9-0050c2490048", 1.01e13, "kBq"),
    "846692b1-2270-5a4d-92db-b1b078af8326": ("Water", "Emissions to water", "", "kg", "a3876d9b-a3e8-4680-861a-4e08642f1392", 0.001, "m3"),
}

#: Released by mass onto a flow the merge creates rather than one EF 3.1 ships,
#: which a curated target cannot name -- the row comes out unmatched,
#: `prepared-target-not-found` -- so the row's own unit is rebased in the manual
#: fixes instead.  uuid -> (vendor name, compartment, subcompartment)
REBASED = {
    "65724528-8bc6-52e4-a77a-4d530d34caaf": ("Water", "Emissions to water", "river"),
    "f91a9f9a-cc75-509f-aa74-ea0f1845d80d": ("Waste water", "Emissions to water", ""),
}

#: Accepted with no number: a stable isotope has no activity to convert to.
#: uuid -> (vendor name, compartment, subcompartment, unit, target)
INERT = {
    "46d00281-f7f8-5401-be25-55f750f2edc6": ("Argon-40/kg", "Resources", "in air", "kg", "e8d5b530-d495-4f79-8c34-ca8ec4852bfa"),
    "eb761cc9-c9ad-52ba-84e1-4f292d8cc77f": ("Argon-40/kg", "Emissions to air", "", "kg", "3f5f02ed-d820-47b1-b319-505ab06b9bc0"),
    "eb3ff946-cc3e-554d-850b-33064a00bcfd": ("Manganese-55", "Emissions to water", "", "kBq", "08a91e70-3ddc-11dd-9bcc-0050c2490048"),
}


def _accepted() -> set[tuple[str, str]]:
    return {
        (row["source_uuid"], row["target_elementary_flow_id"])
        for row in orjson.loads(ALLOWLIST_PATH.read_bytes())["accepted"]
        if str(row.get("comment") or "").strip()
    }


class TheRowsTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.by_uuid = {
            override.source_uuid: override
            for override in load_match_overrides(OVERRIDES_PATH)
        }

    def test_there_are_the_twenty_six_the_issue_counted(self) -> None:
        self.assertEqual(len(CONVERTED) + len(REBASED) + len(INERT), 26)

    def test_every_row_names_the_flow_its_vendor_fields_derive(self) -> None:
        """An override naming a uuid AGRIBALYSE does not ship overrides
        nothing and raises nothing, so the uuid is recomputed from the fields."""
        for uuid, (name, compartment, sub, unit, *_rest) in {**CONVERTED, **INERT}.items():
            with self.subTest(name=name, sub=sub or "(bare)"):
                self.assertEqual(_flow_uuid(name, compartment, sub, unit), uuid)
        for uuid, (name, compartment, sub) in REBASED.items():
            with self.subTest(name=name, sub=sub or "(bare)"):
                self.assertEqual(_flow_uuid(name, compartment, sub, "kg"), uuid)

    def test_every_converted_row_states_its_target_factor_and_units(self) -> None:
        for uuid, (name, _, _, unit, target, factor, target_unit) in CONVERTED.items():
            with self.subTest(name=name, uuid=uuid):
                override = self.by_uuid[uuid]
                self.assertEqual(override.target_uuid, target)
                self.assertEqual(override.conversion_factor, factor)
                self.assertEqual(override.source_unit, unit)
                self.assertEqual(override.target_unit, target_unit)
                self.assertTrue(override.comment.strip())

    def test_every_row_is_accepted_against_its_target(self) -> None:
        accepted = _accepted()
        for uuid, (name, *_rest) in CONVERTED.items():
            with self.subTest(name=name, uuid=uuid):
                self.assertIn((uuid, CONVERTED[uuid][4]), accepted)
        for uuid, (name, _, _, _, target) in INERT.items():
            with self.subTest(name=name, uuid=uuid):
                self.assertIn((uuid, target), accepted)

    def test_a_stable_isotope_is_given_no_number(self) -> None:
        """The other half: accepting argon-40 and manganese-55 must not grow a
        factor, because there is no activity for one to convert to."""
        for uuid, (name, *_rest) in INERT.items():
            with self.subTest(name=name):
                self.assertNotIn(uuid, self.by_uuid)

    def test_the_kilobecquerel_twins_are_left_alone(self) -> None:
        """AGRIBALYSE ships each converted isotope in kBq as well, and those
        rows already reach the same flows in the right unit."""
        for name in ("Lead-210", "Radium-226", "Radium-228"):
            with self.subTest(name):
                uuid = _flow_uuid(name, "Emissions to water", "", "kBq")
                self.assertNotIn(uuid, self.by_uuid)

    def test_no_coal_mine_row_is_sent_to_natural_gas(self) -> None:
        for override in self.by_uuid.values():
            if override.source_name.startswith("Gas, mine, off-gas"):
                with self.subTest(override.source_uuid):
                    self.assertEqual(override.target_uuid, OFF_GAS)


class TheRebasedWaterTestCase(unittest.TestCase):
    """The two water releases whose flow the merge creates are measured in
    cubic metres before they are matched, with the density stated on the
    rebase, so they cross nothing and need no target or acceptance."""

    def _fixed(self) -> dict[str, dict]:
        rows = [
            {
                "uuid": uuid,
                "name": name,
                "context": [compartment, sub] if sub else [compartment],
                "unit": "kg",
            }
            for uuid, (name, compartment, sub) in REBASED.items()
        ]
        apply_manual_fixes(rows, FIXES_PATH, label="agribalyse-3.2", quiet=True)
        return {row["uuid"]: row for row in rows}

    def test_each_release_is_rebased_to_cubic_metres(self) -> None:
        fixed = self._fixed()
        for uuid, (name, *_rest) in REBASED.items():
            with self.subTest(name):
                self.assertEqual(fixed[uuid]["unit"], "m3")

    def test_each_rebase_states_fresh_waters_density(self) -> None:
        fixes = {
            fix["uuid"]: fix
            for fix in orjson.loads(FIXES_PATH.read_bytes())["fixes"]
            if fix.get("field") == "unit" and "uuid" in fix
        }
        for uuid, (name, *_rest) in REBASED.items():
            with self.subTest(name):
                self.assertEqual(fixes[uuid]["original_value"], "kg")
                self.assertEqual(fixes[uuid]["conversion_factor"], 0.001)

    def test_neither_is_also_given_a_target_or_an_acceptance(self) -> None:
        targeted = {o.source_uuid for o in load_match_overrides(OVERRIDES_PATH)}
        accepted = {source for source, _ in _accepted()}
        for uuid, (name, *_rest) in REBASED.items():
            with self.subTest(name):
                self.assertNotIn(uuid, targeted)
                self.assertNotIn(uuid, accepted)


class TheCoalMineNumberTestCase(unittest.TestCase):
    """Natural gas's number comes off AGRIBALYSE's coal-mine gas, and stays on
    AGRIBALYSE's natural gas."""

    ROWS = [
        {"uuid": "6be68aec-e88a-51a6-a22a-b8e26d1c6947", "name": "Gas, mine, off-gas, process, coal mining/kg",
         "context": ["Resources", "in ground"], "unit": "kg", "cas_numbers": [NATURAL_GAS_CAS]},
        {"uuid": "3448032e-95f6-5eb3-a7a8-04141c3b95d1", "name": "Gas, mine, off-gas, process, coal mining/kg",
         "context": ["Resources"], "unit": "kg", "cas_numbers": [NATURAL_GAS_CAS]},
        {"uuid": "2e888763-5042-5f1f-af32-b0252d7584bf", "name": "Gas, mine, off-gas, process, coal mining/m3",
         "context": ["Resources", "in ground"], "unit": "m3", "cas_numbers": [NATURAL_GAS_CAS]},
        {"uuid": "4e0fae84-bad2-5378-9a09-0d5b6ff09550", "name": "Gas, natural/m3",
         "context": ["Resources", "in ground"], "unit": "m3", "cas_numbers": [NATURAL_GAS_CAS]},
        {"uuid": "b71f49da-94c5-5015-a636-f03630a348af", "name": "Gas, natural/kg",
         "context": ["Resources"], "unit": "kg", "cas_numbers": [NATURAL_GAS_CAS]},
    ]

    def _fixed(self) -> dict[str, dict]:
        rows = copy.deepcopy(self.ROWS)
        apply_manual_fixes(rows, FIXES_PATH, label="agribalyse-3.2", quiet=True)
        return {row["uuid"]: row for row in rows}

    def test_the_number_comes_off_all_three_coal_mine_rows(self) -> None:
        fixed = self._fixed()
        for row in self.ROWS[:3]:
            with self.subTest(row["name"], context=row["context"]):
                self.assertNotIn(NATURAL_GAS_CAS, fixed[row["uuid"]].get("cas_numbers") or [])

    def test_natural_gas_keeps_its_own_number(self) -> None:
        fixed = self._fixed()
        for row in self.ROWS[3:]:
            with self.subTest(row["name"]):
                self.assertEqual(fixed[row["uuid"]]["cas_numbers"], [NATURAL_GAS_CAS])


if __name__ == "__main__":
    unittest.main()
