"""One substance, one flow object, where EF 3.1 gave one of its names no number.

EF 3.1 ships four substances under two names each, and on one of the two names
it ships no identifier at all: `Methylene chloride` beside `dichloromethane`,
`Methyl chloroform` beside `HCFC-140`, `2,2,3,3,3-Pentafluoropropan-1-ol` beside
`pentafluoro-1-propanol`, `perfluoro-2-methyl-3-pentanone` beside
`1,1,1,2,2,4,5,5,5-nonafluoro-4-(trifluoromethyl )-3-pentanone`.  The layering
consults CAS and name and never the structure it has already derived, so the
name-only side keys on `name:` and a second flow object is minted for a
substance the list already has (#35).

The correction is the registry number the rows are missing, stated once per
substance in `ef-3.1-manual-fixes.json`, and these assert what it buys: the
name-only rows join the object the identified rows already mint, and that object
is the one derived from the CAS -- so the identifier a consumer has mapped
survives the merge and the name-derived one is what retires.

The pairing is not asserted from the names.  Each `expected` id below is
`stable_flow_object_id("fo", "cas:<number>")`, which is what the layering mints
for the identified rows, and the test fails if the corrected rows land anywhere
else.
"""

from __future__ import annotations

import unittest

from brightway_flows.domain.flow import Flow
from brightway_flows.domain.flow_object import stable_flow_object_id
from brightway_flows.flow_layers import resolve_flow_layers
from brightway_flows.integrations.ef31 import MANUAL_FIXES_FILEPATH
from brightway_flows.manual_fixes import apply_manual_fixes
from brightway_flows.sources import base_source_list

BASE = base_source_list()

_AIR_CTX = {"dimension": "Environmental", "media": "Air", "strata": "Ground level",
             "population_density": "Urban (>1000 people/square mile)"}

#: The four pairs, as EF 3.1 spells them: the name that carries the registry
#: number, the name that carries nothing, and the number itself.
PAIRS = [
    ("dichloromethane", "75-09-2", "Methylene chloride"),
    ("HCFC-140", "71-55-6", "Methyl chloroform"),
    ("pentafluoro-1-propanol", "422-05-9", "2,2,3,3,3-Pentafluoropropan-1-ol"),
    (
        "1,1,1,2,2,4,5,5,5-nonafluoro-4-(trifluoromethyl )-3-pentanone",
        "756-13-8",
        "perfluoro-2-methyl-3-pentanone",
    ),
]


def _row(uuid: str, name: str, cas: list[str]) -> dict:
    return {
        "uuid": uuid,
        "name": name,
        "prefLabel": [{"@value": name, "@language": "en"}],
        "source": "EF 3.1",
        "context": _AIR_CTX,
        "cas_numbers": list(cas),
        "ec_numbers": [],
    }


def _rows_for(identified: str, cas: str, name_only: str) -> list[dict]:
    return [
        _row("11111111-1111-1111-1111-111111111111", identified, [cas]),
        _row("22222222-2222-2222-2222-222222222222", name_only, []),
    ]


def _object_ids(rows: list[dict]) -> dict[str, str]:
    """Which flow object each row's uuid resolves to."""
    _, elementary_flows, _ = resolve_flow_layers(
        [Flow.from_dict(row) for row in rows], source_list=BASE
    )
    return {flow.elementary_flow_id: flow.flow_object_id for flow in elementary_flows}


class TheCorrectionIsStatedTestCase(unittest.TestCase):
    """The fixes file supplies the number, once per substance."""

    def test_each_name_only_side_is_given_its_registry_number(self):
        for identified, cas, name_only in PAIRS:
            with self.subTest(substance=name_only):
                rows = _rows_for(identified, cas, name_only)
                apply_manual_fixes(rows, MANUAL_FIXES_FILEPATH, label="EF 3.1")
                self.assertEqual(rows[1]["cas_numbers"], [cas])

    def test_the_identified_side_is_left_alone(self):
        """The fix matches on the name that has no number, not on the substance."""
        for identified, cas, name_only in PAIRS:
            with self.subTest(substance=identified):
                rows = _rows_for(identified, cas, name_only)
                apply_manual_fixes(rows, MANUAL_FIXES_FILEPATH, label="EF 3.1")
                self.assertEqual(rows[0]["cas_numbers"], [cas])

    def test_applying_twice_changes_nothing_further(self):
        """The base list has its fixes applied twice, at extract and at read (#237)."""
        for identified, cas, name_only in PAIRS:
            with self.subTest(substance=name_only):
                rows = _rows_for(identified, cas, name_only)
                apply_manual_fixes(rows, MANUAL_FIXES_FILEPATH, label="EF 3.1")
                once = [dict(row) for row in rows]
                apply_manual_fixes(rows, MANUAL_FIXES_FILEPATH, label="EF 3.1")
                self.assertEqual(rows, once)


class TheTwoNamesResolveToOneObjectTestCase(unittest.TestCase):
    """What the number buys, asserted against the published identifier."""

    def test_uncorrected_rows_mint_two_objects(self):
        """The defect, so a passing test below cannot be passing vacuously."""
        for identified, cas, name_only in PAIRS:
            with self.subTest(substance=name_only):
                resolved = _object_ids(_rows_for(identified, cas, name_only))
                self.assertEqual(len(set(resolved.values())), 2)

    def test_corrected_rows_share_the_cas_derived_object(self):
        for identified, cas, name_only in PAIRS:
            with self.subTest(substance=name_only):
                rows = _rows_for(identified, cas, name_only)
                apply_manual_fixes(rows, MANUAL_FIXES_FILEPATH, label="EF 3.1")
                resolved = _object_ids(rows)
                expected = stable_flow_object_id("fo", f"cas:{cas}")
                self.assertEqual(set(resolved.values()), {expected})


if __name__ == "__main__":
    unittest.main()
