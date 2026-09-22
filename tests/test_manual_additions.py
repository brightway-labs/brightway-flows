"""Tests for the manual-additions merge helpers."""

from __future__ import annotations

import ast
import json
import tempfile
import unittest
from pathlib import Path

from brightway_flows.domain.elementary_flow import minted_elementary_flow_id
from brightway_flows.merge.additions import (
    _build_manual_additions_indexes,
    _load_manual_additions,
)
from brightway_flows.sources import known_source_lists, resolve_source_list

#: The list the bundled groupings file was composed for.  Named once, so the
#: tests read the path from its manifest rather than rebuilding the filename.
GROUPINGS_OWNER = "ecoinvent-3.12"

MINIMAL_ADDITIONS = {
    "schema_version": 2,
    "description": "Test fixture",
    "mappings": [
        {
            "source_name": "Testicide A",
            "pesticide_type": "herbicide",
            "flow_object_id": "fo-aabbccdd11223344",
            "flow_object_label": "Herbicides, Unspecified",
            "notes": "A test herbicide.",
            "source_uuids": ["aaaa-1111", "bbbb-2222"],
        },
        {
            "source_name": "Testicide B",
            "flow_object_id": "fo-99887766554433aa",
            "flow_object_label": "Fungicides, Unspecified",
            "notes": "A test fungicide.",
            "source_uuids": ["cccc-3333"],
        },
        {
            "source_name": "NotAPesticide",
            "flow_object_id": None,
            "flow_object_label": None,
            "notes": "Industrial chemical; not a pesticide.",
        },
    ],
}


def _rules(payload: dict) -> tuple:
    """*payload* written to a file and read back as the rules it states."""
    with tempfile.NamedTemporaryFile(suffix=".json", mode="w", delete=False) as handle:
        json.dump(payload, handle)
        path = Path(handle.name)
    try:
        return _load_manual_additions(path)
    finally:
        path.unlink(missing_ok=True)


class LoadManualAdditionsTestCase(unittest.TestCase):
    def test_loads_from_file(self):
        rules = _rules(MINIMAL_ADDITIONS)
        # Two of the three: the row naming no flow object decides nothing.
        self.assertEqual(
            [rule.source_name for rule in rules], ["Testicide A", "Testicide B"]
        )
        self.assertEqual(rules[0].source_uuids, ("aaaa-1111", "bbbb-2222"))

    def test_missing_file_returns_no_rules(self):
        self.assertEqual(
            _load_manual_additions(Path("/nonexistent/path/additions.json")), ()
        )

    def test_declared_path_loads_without_error(self):
        # A manifest that names a groupings file names one that is loadable.
        #
        # It used to assert the file yielded rules, and that stopped being true
        # with #76: the thirty positive mappings that sent named pesticides to
        # `Herbicides, Unspecified` and its siblings were removed, and the
        # twelve `not_pesticide` rows that remain name no flow object, so the
        # loader drops every one of them.  The file is still declared by every
        # ecoinvent manifest and still has to load; what it no longer does is
        # place anything.  `tests/test_pesticide_catch_alls.py` states that as
        # the claim rather than as a side effect of this one.
        rules = _load_manual_additions(
            resolve_source_list(GROUPINGS_OWNER).manual_additions_path
        )
        self.assertEqual(rules, ())

    def test_no_declared_file_returns_no_rules(self):
        """A list with no groupings merges without them rather than with
        another list's (#240).  There is no default file any more."""
        self.assertEqual(_load_manual_additions(None), ())


class BuildManualAdditionsIndexesTestCase(unittest.TestCase):
    def setUp(self):
        self.uuid_index, self.name_index = _build_manual_additions_indexes(
            _rules(MINIMAL_ADDITIONS)
        )

    def test_uuid_index_covers_all_listed_uuids(self):
        self.assertIn("aaaa-1111", self.uuid_index)
        self.assertIn("bbbb-2222", self.uuid_index)
        self.assertIn("cccc-3333", self.uuid_index)

    def test_uuid_index_maps_to_correct_flow_object(self):
        self.assertEqual(self.uuid_index["aaaa-1111"].flow_object_id, "fo-aabbccdd11223344")
        self.assertEqual(self.uuid_index["cccc-3333"].flow_object_id, "fo-99887766554433aa")

    def test_name_index_covers_entries_with_non_null_flow_object_id(self):
        self.assertIn("testicide a", self.name_index)
        self.assertIn("testicide b", self.name_index)

    def test_name_index_excludes_entries_with_null_flow_object_id(self):
        self.assertNotIn("notapesticide", self.name_index)

    def test_name_lookup_is_case_insensitive(self):
        self.assertEqual(self.name_index["testicide a"].flow_object_id, "fo-aabbccdd11223344")

    def test_what_the_created_flow_carries_beyond_the_core_fields(self):
        """`pesticide_type` and the uuids the rule was written against are
        published in the new flow's `source_metadata`."""
        self.assertEqual(
            self.uuid_index["aaaa-1111"].extra_fields,
            {"pesticide_type": "herbicide", "source_uuids": ["aaaa-1111", "bbbb-2222"]},
        )

    def test_no_rules_returns_empty_dicts(self):
        u, n = _build_manual_additions_indexes(())
        self.assertEqual(u, {})
        self.assertEqual(n, {})
        u2, n2 = _build_manual_additions_indexes(_rules({"mappings": []}))
        self.assertEqual(u2, {})
        self.assertEqual(n2, {})

    def test_invalid_entries_skipped(self):
        rules = _rules(
            {"mappings": [None, 42, {"source_name": "X"}, {"flow_object_id": "fo-abc"}]}
        )
        # The row with a flow object and no name is a rule; it just cannot be
        # reached by name.
        u, n = _build_manual_additions_indexes(rules)
        self.assertEqual(u, {})
        self.assertEqual(n, {})


class BundledPesticideGroupingsRegressionTestCase(unittest.TestCase):
    """What the bundled groupings file is for, now that it places nothing.

    It used to assert that Laminarin's `soil/forestry` flow was catalogued by
    uuid, because that flow has no EF 3.1 equivalent in that context and the
    grouping was the only thing that reached it -- the regression for #204 and
    #205.  #76 retired the thirty positive mappings, so the assertion is
    inverted here rather than deleted: the *route* changed and the outcome the
    two issues wanted did not.  The flow is still reached, by the merge's own
    addition path, and it is now reached as `Laminarin` instead of as
    `Fungicides, Unspecified`, which is what #206 asked for on top.
    """

    def test_laminarin_soil_forestry_is_no_longer_a_manual_addition(self):
        uuid_index, _ = _build_manual_additions_indexes(_load_manual_additions(
            resolve_source_list(GROUPINGS_OWNER).manual_additions_path
        ))
        self.assertEqual(uuid_index, {})

    def test_laminarin_soil_forestry_consensus_flow_id(self):
        """The consensus flow id for the soil/forestry Laminarin.

        It was `a1a190e1775b734a38bf598934c15d35b8c021a8` -- sha1 of the
        grouping's own source row, `2c062d6a-f9af-58b8-92b8-6144f688f54c`, with
        the substance and the context.  #102 retired that name along with the
        other 2,560, because the row it carried was not a property of the flow;
        `retired-minted-flow-ids.json` is where the old one is written down and
        the export redirects it here.  Kept as a literal rather than recomputed
        from the same call the code makes, which would assert nothing.
        """
        self.assertEqual(
            minted_elementary_flow_id(
                "fo-08d9dd2d1d8a87d5",
                "https://vocab.brightway.one/flow-contexts/envi-grou-silv",
            ),
            "b3bf7797f3f78597a4cd5a221f009dd2a5e046d9",
        )


class ManualAdditionsAreScopedToOneListTestCase(unittest.TestCase):
    """#240: groupings composed for one list must not reach another.

    `merge_source_list` called `_load_manual_additions()` with no argument and
    got ecoinvent's pesticide groupings whatever was being merged.  The name
    index is a deliberate fallback *within* a list -- it catches flows a new
    release adds before they are catalogued by UUID -- so across lists any
    normalised name collision attached a row to ecoinvent's chosen flow object
    and removed it from the unmatched queue, where no curator would see it.
    """

    def test_the_merge_reads_the_path_from_the_source_list(self):
        """No call site may rely on a default.  Pinned structurally because the
        defect was an omitted argument: it imports, runs, and produces wrong
        output without raising."""
        merge_dir = (
            Path(__file__).resolve().parent.parent
            / "src" / "brightway_flows" / "merge"
        )
        bare_calls = []
        for path in sorted(merge_dir.glob("*.py")):
            for node in ast.walk(ast.parse(path.read_text())):
                if not isinstance(node, ast.Call):
                    continue
                func = node.func
                name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", "")
                if name == "_load_manual_additions" and not node.args and not node.keywords:
                    bare_calls.append(f"{path.name}:{node.lineno}")
        self.assertEqual(bare_calls, [])

    def test_a_declared_additions_file_belongs_to_the_list_that_names_it(self):
        for key, source in sorted(known_source_lists().items()):
            with self.subTest(source=key):
                path = source.manual_additions_path
                if path is None:
                    continue
                self.assertTrue(
                    path.exists(),
                    f"{key} declares manual additions at {path}, which is missing.",
                )
                self.assertTrue(
                    path.name.startswith(source.list_name),
                    f"{key} reads {path.name}, which was composed for another list.",
                )


if __name__ == "__main__":
    unittest.main()
