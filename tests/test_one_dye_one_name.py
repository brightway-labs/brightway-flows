"""One dye, one name, where EF 3.1 gave it thirteen dyes' names.

EF 3.1 repeats methyl violet once per environmental compartment and calls each
copy something different -- `basic violet 1` through `basic violet 13`, all on
registry number 8004-87-3, all with the same synonyms and the same structure.
`Basic Violet` is a Colour Index catalogue position rather than a chemical
family, so twelve of those thirteen names belong to twelve other dyes, and the
registry says so: asked for each name in turn, Common Chemistry answers with
thirteen different numbers -- Crystal violet for `basic violet 3`, Ethyl violet
for `basic violet 4`, Rhodamine B for `basic violet 10` (#280).

Nothing had caught it.  The thirteen sit in thirteen compartments, so no two are
ever in one place and #271's duplicate check has nothing to report; and the
contested-registry-number queue could list the number but not settle it, because
the names *are* one substance and a `merge` ruling would change nothing.

The correction is the name, stated once against the number in
`ef-3.1-manual-fixes.json`.  These assert what it buys:

* the thirteen rows read as one substance, under the name the registry gives
  8004-87-3 and in the spelling EF itself uses for the other dye;
* crystal violet, which EF publishes correctly as `C.I. Basic Violet 3`, keeps
  its name and its rows;
* the contested-number queue stops carrying an item it could not decide;
* and the thirteen still resolve to the one flow object they always did -- the
  grouping was never the defect.

The uncorrected shape is asserted first in each case, so a passing test cannot
be passing because the rows went away.
"""

from __future__ import annotations

import json
import unittest

from brightway_flows.domain.flow import Flow
from brightway_flows.domain.flow_object import stable_flow_object_id
from brightway_flows.flow_layers import resolve_flow_layers
from brightway_flows.flow_layers.contested_cas import contested_cas_index
from brightway_flows.integrations.ef31 import MANUAL_FIXES_FILEPATH
from brightway_flows.manual_fixes import apply_manual_fixes
from brightway_flows.sources import base_source_list

BASE = base_source_list()

METHYL_VIOLET = "8004-87-3"
CRYSTAL_VIOLET = "548-62-9"

#: What the correction writes.  The registry's own name for 8004-87-3, in the
#: spelling EF 3.1 already uses for crystal violet, so the two dyes read alike.
CORRECTED = "C.I. Basic Violet 1"

#: The thirteen names EF 3.1 gives the one dye, with the compartment each sits
#: in.  Thirteen compartments is why no duplicate check ever fired on them.
MISNAMED = [
    ("basic violet 1", {"dimension": "Environmental", "media": "Air", "strata": "High stack, >150 meters",
             "population_density": "Urban (>1000 people/square mile)"}),
    ("basic violet 2", {"dimension": "Environmental", "media": "Air", "strata": "Ground level",
             "population_density": "Urban (>1000 people/square mile)"}),
    ("basic violet 3", {"dimension": "Environmental", "media": "Air", "indoor": "Unknown"}),
    ("basic violet 4", {"dimension": "Environmental", "media": "Ground", "geography": "Agricultural"}),
    ("basic violet 5", {"dimension": "Environmental", "media": "Water", "water_body": "Ocean"}),
    ("basic violet 6", {"dimension": "Environmental", "media": "Air", "strata": "Unknown"}),
    ("basic violet 7", {"dimension": "Environmental", "media": "Water", "water_body": "Unknown"}),
    ("basic violet 8", {"dimension": "Environmental", "media": "Air", "strata": "Aircraft cruise height"}),
    ("basic violet 9", {"dimension": "Environmental", "media": "Water", "water_body": "Long-term"}),
    ("basic violet 10", {"dimension": "Environmental", "media": "Water", "water_body": "Surface water"}),
    ("basic violet 11", {"dimension": "Environmental", "media": "Ground", "geography": "Non-agricultural"}),
    ("basic violet 12", {"dimension": "Environmental", "media": "Ground", "geography": "Unknown"}),
    ("basic violet 13", {"dimension": "Environmental", "media": "Air", "strata": "Long-term"}),
]


def _row(index: int, name: str, cas: str, context: dict) -> dict:
    """A row as extraction hands it over: a name, and no label yet.

    Deliberately without `prefLabel`.  The fixes are applied while the rows are
    still source-shaped and `bootstrap_labels` writes the label from the `name`
    field afterwards, so a fixture carrying a label would be carrying the one
    the correction is about to replace -- and every question below would be
    answered against the uncorrected name.
    """
    return {
        "uuid": f"{index:08d}-0000-0000-0000-000000000000",
        "name": name,
        "source": "EF 3.1",
        "context": context,
        "cas_numbers": [cas],
        "ec_numbers": [],
    }


def _misnamed_rows() -> list[dict]:
    return [
        _row(index, name, METHYL_VIOLET, context)
        for index, (name, context) in enumerate(MISNAMED)
    ]


def _crystal_violet_rows() -> list[dict]:
    """EF's other dye, correctly named, in the compartments it shares."""
    return [
        _row(100 + index, "C.I. Basic Violet 3", CRYSTAL_VIOLET, context)
        for index, (_, context) in enumerate(MISNAMED)
    ]


def _corrected(rows: list[dict]) -> list[dict]:
    apply_manual_fixes(rows, MANUAL_FIXES_FILEPATH, label="EF 3.1")
    return rows


def _bootstrapped(rows: list[dict]) -> list[Flow]:
    """Rows as the layering sees them, with the label `bootstrap_labels` writes."""
    return [
        Flow.from_dict(dict(row, prefLabel=[{"@value": row["name"], "@language": "en"}]))
        for row in rows
    ]


class TheCorrectionIsStatedTestCase(unittest.TestCase):
    """The fixes file gives one substance one name."""

    def test_uncorrected_rows_carry_thirteen_names(self):
        """The defect, so nothing below can pass vacuously."""
        self.assertEqual(len({row["name"] for row in _misnamed_rows()}), 13)

    def test_every_row_reads_as_the_same_dye(self):
        self.assertEqual({row["name"] for row in _corrected(_misnamed_rows())}, {CORRECTED})

    def test_no_other_dyes_name_survives(self):
        """`basic violet 3` is crystal violet's name, `basic violet 10` is rhodamine B's.

        The one name that may stay is `basic violet 1`, and only in the `C.I.`
        spelling: it is the catalogue name of the substance actually there.
        """
        others = {name for name, _ in MISNAMED if name != "basic violet 1"}
        surviving = {row["name"].lower() for row in _corrected(_misnamed_rows())}
        self.assertEqual(surviving & others, set())

    def test_the_correction_is_stated_once(self):
        """Against the number, not thirteen times against the names.

        A uuid-keyed rule would state itself once per compartment and go stale
        the moment EF adds one; the claim being made is about the substance.
        """
        fixes = json.loads(MANUAL_FIXES_FILEPATH.read_text())["fixes"]
        ours = [
            fix for fix in fixes
            if fix.get("field") == "name" and fix.get("new_value") == CORRECTED
        ]
        self.assertEqual(len(ours), 1)
        self.assertEqual(ours[0].get("match"), {"cas_numbers": METHYL_VIOLET})

    def test_applying_twice_changes_nothing_further(self):
        """The base list has its fixes applied twice, at extract and at read (#237)."""
        rows = _corrected(_misnamed_rows())
        once = [dict(row) for row in rows]
        apply_manual_fixes(rows, MANUAL_FIXES_FILEPATH, label="EF 3.1")
        self.assertEqual(rows, once)

    def test_the_other_dye_is_left_alone(self):
        """548-62-9 is crystal violet, and EF already names it correctly."""
        rows = _corrected(_crystal_violet_rows())
        self.assertEqual({row["name"] for row in rows}, {"C.I. Basic Violet 3"})
        self.assertEqual({row["cas_numbers"][0] for row in rows}, {CRYSTAL_VIOLET})


class TheContestedNumberIsSettledTestCase(unittest.TestCase):
    """One name means nothing left for the contested-number queue to ask."""

    def _index(self, rows: list[dict]) -> dict:
        return contested_cas_index(
            _bootstrapped(rows), list_name="EF 3.1", list_version="3.1"
        )

    def test_uncorrected_rows_contest_the_number(self):
        contested = self._index(_misnamed_rows())
        self.assertIn(METHYL_VIOLET, contested)
        self.assertEqual(len(contested[METHYL_VIOLET].names), 13)

    def test_corrected_rows_do_not(self):
        self.assertNotIn(METHYL_VIOLET, self._index(_corrected(_misnamed_rows())))


class TheGroupingIsUnchangedTestCase(unittest.TestCase):
    """The thirteen were already one substance; only the name was wrong."""

    def _object_ids(self, rows: list[dict]) -> set[str]:
        _, elementary_flows, _ = resolve_flow_layers(
            _bootstrapped(rows), source_list=BASE
        )
        return {flow.flow_object_id for flow in elementary_flows}

    def test_the_thirteen_share_the_cas_derived_object(self):
        expected = stable_flow_object_id("fo", f"cas:{METHYL_VIOLET}")
        self.assertEqual(self._object_ids(_misnamed_rows()), {expected})
        self.assertEqual(self._object_ids(_corrected(_misnamed_rows())), {expected})

    def test_the_two_dyes_stay_apart(self):
        rows = _corrected(_misnamed_rows() + _crystal_violet_rows())
        self.assertEqual(
            self._object_ids(rows),
            {
                stable_flow_object_id("fo", f"cas:{METHYL_VIOLET}"),
                stable_flow_object_id("fo", f"cas:{CRYSTAL_VIOLET}"),
            },
        )


class TheRealRowsCarryItTestCase(unittest.TestCase):
    """Against the extracted list, when the machine running this has one.

    Skipped rather than synthesised: the claim here is about how many rows EF
    actually ships under this number, and a fixture cannot be wrong about that
    in the way the fixes file can.
    """

    @classmethod
    def setUpClass(cls):
        if not BASE.flows_path.exists():
            raise unittest.SkipTest(f"{BASE.flows_path.name} has not been extracted")
        rows = json.loads(BASE.flows_path.read_text())
        cls.rows = [
            dict(row) for row in rows
            if METHYL_VIOLET in (row.get("cas_numbers") or [])
        ]

    def test_thirteen_rows_carry_the_number(self):
        self.assertEqual(len(self.rows), 13)

    def test_they_end_up_under_one_name(self):
        apply_manual_fixes(self.rows, MANUAL_FIXES_FILEPATH, label="EF 3.1")
        self.assertEqual({row["name"] for row in self.rows}, {CORRECTED})

    def test_each_sits_in_its_own_compartment(self):
        """Why no duplicate check ever reported them (#271)."""
        contexts = [json.dumps(row["context"], sort_keys=True) for row in self.rows]
        self.assertEqual(len(set(contexts)), len(contexts))


if __name__ == "__main__":
    unittest.main()
