"""ecoinvent's thirteen `Molybdenum VI` rows take the ion's registry number.

#181.  ecoinvent names the rows for the hexavalent ion, writes `Mo+6` on them,
and from 3.10.1 registers them 7439-98-7, the metal; 3.9.1 registered the same
uuids 16065-87-5, the ion.  The fix restores the ion's number in the three
release files that ship the metal's.

Three things are tested.  The fix renumbers the ion rows and leaves the plain
`Molybdenum` resource row alone.  The three releases state the same correction.
And the canonical-identities derivation reads a release *with its fixes
applied*: an identity derived from the raw file would carry the metal's number
as the vendor's newest opinion and substitute it back over the correction at
matching, which is the failure this tool used to have.
"""

from __future__ import annotations

import copy
import importlib.util
import tempfile
import unittest
from pathlib import Path

import orjson

from brightway_flows.filesystem import PACKAGE_DATA_DIR
from brightway_flows.manual_fixes import apply_manual_fixes

METAL = "7439-98-7"
ION = "16065-87-5"
RELEASES_WITH_THE_METALS_NUMBER = ("3.10.1", "3.11", "3.12")

ROWS = [
    {
        "uuid": "c26d4716-ce1e-43da-a662-cd9498b1e8bc", "name": "Molybdenum VI",
        "cas_number": METAL, "context": ["air", "urban air close to ground"], "unit": "kg",
        "synonyms": ["Molybdenum", "Molybdenum (+6)", "Molybdenum ion"],
    },
    {
        "uuid": "9cf3a683-ed3d-40e9-b039-7653e4fc9e20", "name": "Molybdenum VI",
        "cas_number": METAL, "context": ["soil", "agricultural"], "unit": "kg",
        "synonyms": ["Molybdenum (+6)", "Molybdenum ion", "Molybdenum"],
    },
    {
        "uuid": "e5a3dff5-72dc-5287-893c-597dd4a19566", "name": "Molybdenum",
        "cas_number": METAL, "context": ["natural resource", "in ground"], "unit": "kg",
    },
]


def _fixed(version):
    rows = copy.deepcopy(ROWS)
    path = PACKAGE_DATA_DIR / f"ecoinvent-{version}-manual-fixes.json"
    apply_manual_fixes(rows, path, label=f"ecoinvent-{version}", quiet=True)
    return {row["uuid"]: row for row in rows}


def _tool(name):
    """`tools/` is not a package; a tool is a script, loaded here by path."""
    path = Path(__file__).resolve().parent.parent / "tools" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class MolybdenumVINumberTestCase(unittest.TestCase):
    def test_the_ion_rows_take_the_ions_number_in_every_release_that_ships_the_metals(self):
        for version in RELEASES_WITH_THE_METALS_NUMBER:
            fixed = _fixed(version)
            for uuid in (
                "c26d4716-ce1e-43da-a662-cd9498b1e8bc",
                "9cf3a683-ed3d-40e9-b039-7653e4fc9e20",
            ):
                with self.subTest(version=version, uuid=uuid):
                    self.assertEqual(fixed[uuid]["cas_number"], ION)

    def test_the_resource_row_keeps_the_metals_number(self):
        for version in RELEASES_WITH_THE_METALS_NUMBER:
            with self.subTest(version=version):
                row = _fixed(version)["e5a3dff5-72dc-5287-893c-597dd4a19566"]
                self.assertEqual(row["cas_number"], METAL)
                self.assertEqual(row["name"], "Molybdenum")

    def test_applying_twice_changes_nothing_further(self):
        rows = copy.deepcopy(ROWS)
        path = PACKAGE_DATA_DIR / "ecoinvent-3.12-manual-fixes.json"
        apply_manual_fixes(rows, path, label="ecoinvent-3.12", quiet=True)
        once = copy.deepcopy(rows)
        apply_manual_fixes(rows, path, label="ecoinvent-3.12", quiet=True)
        self.assertEqual(rows, once)


class TheDerivationReadsCorrectedRowsTestCase(unittest.TestCase):
    """Two tiny releases: 3.9.1 registers the ion, 3.12 the metal, and a 3.12
    fixes file that restores the ion.  Derived from the fixed rows the two
    releases agree and there is nothing to decide; derived from the raw rows
    the tool would call the metal the vendor's newest opinion."""

    UUID = "c26d4716-ce1e-43da-a662-cd9498b1e8bc"

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)
        self.derive = _tool("derive_ecoinvent_canonical_identities").derive
        self._release("3.9.1", ION)
        self._release("3.12", METAL)
        # A 3.8 that names the flow plain `Molybdenum`, so the newest identity
        # has something to replace and an entry is written either way.
        self._release("3.8", METAL, name="Molybdenum")
        self.fixes = self.dir / "fixes-3.12.json"
        self.fixes.write_bytes(orjson.dumps({
            "fixes": [{
                "match": {"name": "Molybdenum VI"},
                "field": "cas_number",
                "original_value": METAL,
                "new_value": ION,
                "comment": "test",
            }]
        }))

    def _release(self, version, cas, *, name="Molybdenum VI"):
        (self.dir / f"ecoinvent-biosphere-flows-{version}.json").write_bytes(
            orjson.dumps([{
                "uuid": self.UUID, "name": name, "cas_number": cas,
                "context": ["air", "unspecified"], "unit": "kg",
            }])
        )

    def _entry(self, payload):
        return next(e for e in payload["identities"] if e["uuid"] == self.UUID)

    def test_a_fix_on_the_newest_release_is_what_the_identity_carries(self):
        entry = self._entry(self.derive(self.dir, fixes={"3.12": self.fixes}))
        self.assertEqual(entry["cas_number"], ION)
        self.assertEqual(entry["decided_by"], "3.12")
        # 3.9.1 now agrees with the corrected 3.12 and replaces nothing.
        self.assertEqual(
            [r["version"] for r in entry["replaces"]], ["3.8"]
        )

    def test_without_the_fix_the_raw_number_is_derived(self):
        """The contrast, so the test above cannot pass by accident."""
        entry = self._entry(self.derive(self.dir, fixes={}))
        self.assertEqual(entry["cas_number"], METAL)
        self.assertEqual(
            [r["version"] for r in entry["replaces"]], ["3.8", "3.9.1"]
        )

    def test_the_checked_in_file_carries_the_ions_number_for_the_thirteen(self):
        """The regenerated file, read as data: 3.12 decides the thirteen rows,
        with the ion's number, replacing 3.8's plain `Molybdenum` only."""
        payload = orjson.loads(
            (PACKAGE_DATA_DIR / "ecoinvent-canonical-identities.json").read_bytes()
        )
        thirteen = [
            e for e in payload["identities"]
            if e["name"] == "Molybdenum VI" and e["decided_by"] == "3.12"
        ]
        self.assertEqual(len(thirteen), 13)
        for entry in thirteen:
            with self.subTest(uuid=entry["uuid"]):
                self.assertEqual(entry["cas_number"], ION)
                self.assertEqual([r["version"] for r in entry["replaces"]], ["3.8"])


if __name__ == "__main__":
    unittest.main()
