"""8006-14-2 names natural gas, and in this list it names nothing else.

Three of the four lists put natural gas's registry number on gas drawn off a
coal seam while the coal is being mined, which is a different substance: it
comes out of a mine rather than a gas field, and EF 3.1 says as much in words on
its neighbouring `Pit Methane` flow -- "Pit methane is a different substance
than natural gas (impurities, heating value etc.)".  EF 3.1 puts the number on
coal-mine gas and gives natural gas none at all; ecoinvent 3.8 and 3.9.1 put it
on both, and took it off coal-mine gas at 3.10.1 under the same UUID; BAFU puts
it on one of its two coal-mine rows.

Nothing failed loudly.  Synonym enrichment looked the number up and wrote down
what the chemical registry calls it, so coal-mine gas came to answer to `Natural
gas`, `Gas, natural`, `Sweet natural gas` and five more.  Two flow objects
answering to one name is why a source row saying only `Gas, natural` was
reported as `multiple-flow-object-candidates` and dropped, and BAFU ships two of
those (#80).

The corrections state the move rather than its consequences.  The eight synonyms
are named nowhere: they are derived from the number, and enrichment would write
them back if they were removed one at a time.

The last case is the one that needs saying out loud.  Ambiguity was protecting
BAFU's coal-mine row: while two objects answered to the number it was dropped,
which is visible.  Correcting the other three lists without correcting BAFU
would have let it match confidently onto natural gas instead, so the four
corrections are one correction and this asserts them together.
"""

from __future__ import annotations

import json
import unittest

from brightway_flows.integrations.ef31 import MANUAL_FIXES_FILEPATH
from brightway_flows.manual_fixes import apply_manual_fixes
from brightway_flows.sources import base_source_list, known_source_lists

NATURAL_GAS_CAS = "8006-14-2"

#: EF 3.1's uuids.  Both substances appear once, in one context each.
EF_MINE_GAS_UUID = "00fdc4bc-724b-4993-ad43-c70df533b092"
EF_NATURAL_GAS_UUID = "fe0acd60-3ddc-11dd-a6fa-0050c2490048"

#: ecoinvent's, stable across every release that ships them.
EI_MINE_GAS_UUID = "3ed5f377-344f-423a-b5ec-9a9a1162b944"
EI_NATURAL_GAS_UUID = "7c337428-fb1b-45c7-bbb2-2ee4d29e17ba"

#: BAFU has no identifier of its own and repeats a substance per unit, so its
#: rows are named rather than keyed.  The `/m3` is the spelling the rows still
#: have when fixes run: the general rule that takes a unit back out of a name
#: (#67) is downstream of them.
BAFU_MINE_GAS_NAME = "Gas, mine, off-gas, process, coal mining/m3"
BAFU_NATURAL_GAS_NAME = "Gas, natural/m3"

#: What every list's copy of coal-mine off-gas is measured in.  A cubic metre of
#: gas is not a quantity until the temperature and pressure are stated, and
#: ecoinvent stated them at 3.9 by relabelling this flow from `m3` to `Sm3`.  EF
#: 3.1 and ecoinvent 3.8 are brought to the same spelling here, which is what
#: lets the correspondence between them carry no conversion at all.
MINE_GAS_UNIT = "sm3"


def _ef_rows() -> list[dict]:
    """The pair as EF 3.1 ships it: the number on the wrong one of the two."""
    return [
        {
            "uuid": EF_MINE_GAS_UUID,
            "name": "Gas, mine, off-gas, process, coal mining",
            "cas_numbers": [NATURAL_GAS_CAS],
            "ec_numbers": [],
            "unit": "m3",
        },
        {
            "uuid": EF_NATURAL_GAS_UUID,
            "name": "natural gas",
            "cas_numbers": [],
            "ec_numbers": [],
            "unit": "MJ",
        },
    ]


def _fetched(list_name: str):
    """The registered sources of *list_name* whose flows are on disk."""
    for key, source in known_source_lists().items():
        if source.list_name == list_name and source.flows_path.exists():
            yield key, source


def _corrected(source, key: str) -> list[dict]:
    flows = json.loads(source.flows_path.read_text())
    if source.manual_fixes_path is not None:
        apply_manual_fixes(flows, source.manual_fixes_path, label=key)
    return flows


class TheNumberMovesInEFTestCase(unittest.TestCase):
    """EF 3.1 is the only list where the correction is a move, not a removal.

    It is the one list that gives natural gas no number at all, so taking the
    number off coal-mine gas without putting it back would leave 8006-14-2
    naming nothing in the base list.
    """

    def test_coal_mine_gas_stops_carrying_it(self):
        rows = _ef_rows()
        apply_manual_fixes(rows, MANUAL_FIXES_FILEPATH, label="EF 3.1")
        self.assertEqual(rows[0]["cas_numbers"], [])

    def test_natural_gas_starts_carrying_it(self):
        rows = _ef_rows()
        apply_manual_fixes(rows, MANUAL_FIXES_FILEPATH, label="EF 3.1")
        self.assertEqual(rows[1]["cas_numbers"], [NATURAL_GAS_CAS])

    def test_exactly_one_of_the_two_holds_it_afterwards(self):
        rows = _ef_rows()
        apply_manual_fixes(rows, MANUAL_FIXES_FILEPATH, label="EF 3.1")
        holders = [row["name"] for row in rows if NATURAL_GAS_CAS in row["cas_numbers"]]
        self.assertEqual(holders, ["natural gas"])

    def test_applying_twice_changes_nothing_further(self):
        """The base list has its fixes applied twice, at extract and at read (#237)."""
        rows = _ef_rows()
        apply_manual_fixes(rows, MANUAL_FIXES_FILEPATH, label="EF 3.1")
        once = [dict(row) for row in rows]
        apply_manual_fixes(rows, MANUAL_FIXES_FILEPATH, label="EF 3.1")
        self.assertEqual(rows, once)


class NoListShipsItOnCoalMineGasTestCase(unittest.TestCase):
    """The same statement asked of each list's own flows.

    A list that has not been fetched is skipped rather than assumed innocent;
    the fixes files themselves are checked either way, by
    `tests/test_cross_version_manual_fixes.py`.
    """

    def test_no_ecoinvent_version_holds_it_on_coal_mine_gas(self):
        checked = 0
        for key, source in _fetched("ecoinvent"):
            flows = _corrected(source, key)
            holders = {
                flow["uuid"] for flow in flows
                if flow.get("cas_number") == NATURAL_GAS_CAS
            }
            with self.subTest(source=key):
                self.assertNotIn(EI_MINE_GAS_UUID, holders)
                self.assertIn(EI_NATURAL_GAS_UUID, holders)
            checked += 1
        if not checked:
            self.skipTest("no ecoinvent version has been fetched")

    def test_bafu_does_not_hold_it_on_coal_mine_gas(self):
        checked = 0
        for key, source in _fetched("bafu"):
            flows = _corrected(source, key)
            holding = {
                flow["name"] for flow in flows
                if NATURAL_GAS_CAS in (flow.get("cas_numbers") or [])
            }
            with self.subTest(source=key):
                self.assertNotIn(BAFU_MINE_GAS_NAME, holding)
                self.assertIn(BAFU_NATURAL_GAS_NAME, holding)
            checked += 1
        if not checked:
            self.skipTest("BAFU has not been fetched")

    def test_every_list_measures_coal_mine_gas_the_same_way(self):
        """One substance, one measure, so the mapping between them states none.

        ecoinvent relabelled this flow from `m3` to `Sm3` at 3.9 under an
        unchanged UUID; 3.8 and EF 3.1 are brought to that spelling by their
        fixes files.  If any of them drifted back to a bare `m3` the units would
        disagree again, and the correspondence would need a factor it does not
        have -- silently, because a missing conversion looks like agreement.
        """
        checked = 0
        for key, source in _fetched("ecoinvent"):
            flows = _corrected(source, key)
            row = next(f for f in flows if f["uuid"] == EI_MINE_GAS_UUID)
            with self.subTest(source=key):
                self.assertEqual(str(row["unit"]).lower(), MINE_GAS_UNIT)
            checked += 1
        base = base_source_list()
        if base.flows_path.exists():
            flows = _corrected(base, base.key)
            row = next(f for f in flows if f["uuid"] == EF_MINE_GAS_UUID)
            self.assertEqual(str(row["unit"]).lower(), MINE_GAS_UNIT)
            checked += 1
        if not checked:
            self.skipTest("no list holding this flow has been fetched")

    def test_ef_holds_it_on_natural_gas_only(self):
        """Over the whole extracted list, not the two rows above.

        EF 3.1 is the base list rather than one of the merged sources, so it is
        reached through `base_source_list` and not the registry.
        """
        source = base_source_list()
        if not source.flows_path.exists():
            self.skipTest("EF 3.1 has not been extracted")
        flows = _corrected(source, source.key)
        holders = {
            flow["uuid"] for flow in flows
            if NATURAL_GAS_CAS in (flow.get("cas_numbers") or [])
        }
        self.assertEqual(holders, {EF_NATURAL_GAS_UUID})


if __name__ == "__main__":
    unittest.main()
