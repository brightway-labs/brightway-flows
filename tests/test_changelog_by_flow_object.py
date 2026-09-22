"""One row per edit, not per affected flow (#253).

`altLabel` and `properties` are 87% of the change log's bytes and both belong to
the flow object.  94,433 elementary flows share 7,730 objects, so a row per
affected flow stored the same payload a dozen times: stripping the catalogue
labels off `Silicon Dioxide` wrote its 2.9 MiB before-and-after thirteen times,
37.6 MiB to record one edit.  The table was 4.63 GiB of an 8.13 GiB file and
91.5% of that was duplicate.

What is pinned here is that collapsing is *lossless*, which is the only reason
it is allowed:

- Changes that agree on substance, field, transformer, both values and comment
  are one row, and `changelog_flows` names every flow they landed on.
- Changes that disagree on any of those stay separate -- in particular two flows
  of one substance whose `context` went to different places.
- `read_changelog` still returns one record per (edit, flow), so every caller
  that asked "what happened to this flow" sees what it saw before.
"""

from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from brightway_flows.pipeline.review_records import ChangeEvent, PipelineRun
from brightway_flows.pipeline.review_tables import (
    number_change_events,
    read_changelog,
    write_review_tables,
)


def _change(uuid, field, old, new, transformer, **kwargs) -> ChangeEvent:
    return ChangeEvent(
        uuid=uuid,
        field_name=field,
        old_value=old,
        new_value=new,
        transformer=transformer,
        **kwargs,
    )


class CollapseTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "review.sqlite3"

    def write(self, changes: list[ChangeEvent], objects: dict[str, str]) -> None:
        numbered = number_change_events(changes, flow_object_id_by_uuid=objects)
        write_review_tables(
            self.path,
            run=PipelineRun(run_id="run-1", timestamp="2026-08-08T00:00:00+00:00",
                            schema_version=1),
            stats=[], changes=numbered, queue_items=[],
            formula_mismatches=[], element_coverage=[], context_mappings=[],
        )

    def rows(self, table: str) -> int:
        connection = sqlite3.connect(self.path)
        try:
            return int(connection.execute(f"SELECT count(*) FROM {table}").fetchone()[0])
        finally:
            connection.close()

    def test_one_edit_to_a_shared_substance_is_one_row(self):
        """Fourteen flows, one synonym list, one row."""
        labels = [{"@value": f"synonym {n}"} for n in range(50)]
        flows = [f"u-{n}" for n in range(14)]
        self.write(
            [
                _change(uuid, "altLabel", [], labels, "strip_catalogue_altlabels",
                        flow_name="Silicon Dioxide", comment="catalogue codes")
                for uuid in flows
            ],
            {uuid: "fo-sio2" for uuid in flows},
        )
        self.assertEqual(self.rows("changelog"), 1)
        self.assertEqual(self.rows("changelog_flows"), 14)

    def test_the_flows_of_one_edit_all_come_back(self):
        flows = [f"u-{n}" for n in range(14)]
        self.write(
            [
                _change(uuid, "altLabel", [], [{"@value": "a"}], "chebi_altlabels")
                for uuid in flows
            ],
            {uuid: "fo-sio2" for uuid in flows},
        )
        restored = read_changelog(self.path)
        self.assertEqual(len(restored), 14)
        self.assertEqual({c.uuid for c in restored}, set(flows))
        self.assertEqual({c.change_index for c in restored}, {1})

    def test_flows_that_changed_differently_stay_separate(self):
        """Two flows of one substance whose context went to different places.

        This is why the group key carries both values, not just the field: on
        the field alone these would merge and one flow's history would be a
        lie.
        """
        self.write(
            [
                _change("u-1", "context", ["Air"], ["Air", "urban"],
                        "default_context_mapping"),
                _change("u-2", "context", ["Air"], ["Air", "rural"],
                        "default_context_mapping"),
            ],
            {"u-1": "fo-co2", "u-2": "fo-co2"},
        )
        self.assertEqual(self.rows("changelog"), 2)
        self.assertEqual(self.rows("changelog_flows"), 2)
        [one] = read_changelog(self.path, uuid="u-1")
        self.assertEqual(one.new_value, ["Air", "urban"])

    def test_a_different_comment_is_a_different_edit(self):
        """The comment is the reason, and two reasons are two edits."""
        self.write(
            [
                _change("u-1", "unit", "kg", "m3", "unit_normalization",
                        comment="declared in m3"),
                _change("u-2", "unit", "kg", "m3", "unit_normalization",
                        comment="inferred from the property"),
            ],
            {"u-1": "fo-1", "u-2": "fo-1"},
        )
        self.assertEqual(self.rows("changelog"), 2)

    def test_a_change_without_a_substance_is_not_grouped_with_another(self):
        """No row on the 2026-08-07 build has an empty `flow_object_id`, but a
        flow the layering dropped would -- and merging those would be wrong."""
        self.write(
            [
                _change("u-1", "unit", "kg", "m3", "unit_normalization"),
                _change("u-2", "unit", "kg", "m3", "unit_normalization"),
            ],
            {},
        )
        self.assertEqual(self.rows("changelog"), 2)
        self.assertEqual(
            {c.uuid for c in read_changelog(self.path)}, {"u-1", "u-2"}
        )

    def test_the_same_edit_to_two_substances_is_two_rows(self):
        self.write(
            [
                _change("u-1", "unit", "kg", "m3", "unit_normalization"),
                _change("u-2", "unit", "kg", "m3", "unit_normalization"),
            ],
            {"u-1": "fo-1", "u-2": "fo-2"},
        )
        self.assertEqual(self.rows("changelog"), 2)

    def test_the_index_is_dense_and_ordered_by_first_application(self):
        """`change_index` still reads as "later steps win"."""
        self.write(
            [
                _change("u-1", "prefLabel", "a", "b", "bootstrap_labels"),
                _change("u-2", "prefLabel", "a", "b", "bootstrap_labels"),
                _change("u-1", "prefLabel", "b", "c", "normalize_name_case"),
            ],
            {"u-1": "fo-1", "u-2": "fo-1"},
        )
        connection = sqlite3.connect(self.path)
        try:
            indices = [
                row[0]
                for row in connection.execute(
                    "SELECT change_index FROM changelog ORDER BY change_index"
                )
            ]
        finally:
            connection.close()
        self.assertEqual(indices, [1, 2])
        restored = read_changelog(self.path, uuid="u-1")
        self.assertEqual([c.transformer for c in restored],
                         ["bootstrap_labels", "normalize_name_case"])

    def test_read_changelog_filters_by_flow_through_the_link_table(self):
        flows = [f"u-{n}" for n in range(5)]
        self.write(
            [
                _change(uuid, "altLabel", [], [{"@value": "a"}], "chebi_altlabels")
                for uuid in flows
            ]
            + [_change("u-9", "unit", "kg", "m3", "unit_normalization")],
            {**{uuid: "fo-1" for uuid in flows}, "u-9": "fo-2"},
        )
        self.assertEqual([c.uuid for c in read_changelog(self.path, uuid="u-3")], ["u-3"])
        self.assertEqual(len(read_changelog(self.path, flow_object_id="fo-1")), 5)


if __name__ == "__main__":
    unittest.main()
