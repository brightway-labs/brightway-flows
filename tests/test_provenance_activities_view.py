"""`provenance_activities` is a view, and it agrees with the builder (#253).

The table held 1,407,835 rows and 0.17 GiB with its index, and every column but
`entity_version` was a copy of a `changelog` column.  `entity_version` is "the
nth edit to reach this flow", which `row_number()` computes.

There are now two statements of what an entity version is: the SQL in `SCHEMA`
and `build_provenance_activities`, which the in-memory pipeline still uses.  Two
statements of one rule drift, so the first test here is that they agree -- and
the ordering rule they share is not obvious, because `change_index` is assigned
by an edit's *first* appearance, so a later element of the log can carry an
earlier index.  Both sides order by the index, not by list position.
"""

from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from brightway_flows.pipeline.provenance import build_provenance_activities
from brightway_flows.pipeline.review_records import ChangeEvent, PipelineRun
from brightway_flows.pipeline.review_tables import (
    number_change_events,
    read_provenance_activities,
    write_review_tables,
)


def _change(uuid, field, old, new, transformer, **kwargs) -> ChangeEvent:
    return ChangeEvent(
        uuid=uuid, field_name=field, old_value=old, new_value=new,
        transformer=transformer, **kwargs,
    )


class ProvenanceViewTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "review.sqlite3"

    def write(self, changes: list[ChangeEvent], objects: dict[str, str]):
        numbered = number_change_events(changes, flow_object_id_by_uuid=objects)
        write_review_tables(
            self.path,
            run=PipelineRun(run_id="run-1", timestamp="2026-08-08T00:00:00+00:00",
                            schema_version=1),
            stats=[], changes=numbered, queue_items=[],
            formula_mismatches=[], element_coverage=[], context_mappings=[],
        )
        return numbered

    def test_the_view_agrees_with_the_builder(self):
        """Two statements of one rule, pinned against each other."""
        numbered = self.write(
            [
                _change("u-1", "prefLabel", "a", "b", "bootstrap_labels"),
                _change("u-2", "prefLabel", "a", "b", "bootstrap_labels"),
                _change("u-1", "altLabel", [], [{"@value": "x"}], "chebi_altlabels"),
                _change("u-2", "unit", "kg", "m3", "unit_normalization"),
                _change("u-1", "prefLabel", "b", "c", "normalize_name_case"),
            ],
            {"u-1": "fo-1", "u-2": "fo-1"},
        )
        expected = {
            (a.change_index, a.uuid): a.entity_version
            for a in build_provenance_activities(numbered)
        }
        actual = {
            (a.change_index, a.uuid): a.entity_version
            for a in read_provenance_activities(self.path)
        }
        self.assertEqual(actual, expected)

    def test_versions_follow_application_order_not_change_index(self):
        """The reason `entity_version` is stored rather than derived.

        `u-2` gets `synonyms` first, so that edit's group is numbered before
        `u-1`'s `prefLabel`.  When the identical `synonyms` edit later reaches
        `u-1` it carries the earlier index -- but it happened to `u-1` *third*,
        and the version chain has to say so.  Ordering by `change_index` here
        would report v1, and assert that `u-1` went from its loaded state
        straight to having synonyms.
        """
        numbered = self.write(
            [
                _change("u-2", "synonyms", [], ["s"], "bootstrap_labels"),
                _change("u-1", "prefLabel", "a", "b", "bootstrap_labels"),
                _change("u-1", "name", "a", "b", "bootstrap_labels"),
                _change("u-1", "synonyms", [], ["s"], "bootstrap_labels"),
            ],
            {"u-1": "fo-1", "u-2": "fo-1"},
        )
        # The shared `synonyms` edit really is numbered first.
        by_field = {c.field_name: c.change_index for c in numbered if c.uuid == "u-1"}
        self.assertLess(by_field["synonyms"], by_field["prefLabel"])

        trail = read_provenance_activities(self.path, uuid="u-1")
        self.assertEqual(
            [(a.field_name, a.entity_version) for a in trail],
            [("prefLabel", 1), ("name", 2), ("synonyms", 3)],
        )
        # And the chain is intact: each consumes what the last produced.
        for earlier, later in zip(trail, trail[1:]):
            self.assertEqual(later.used_entity_id, earlier.generated_entity_id)

    def test_it_is_a_view_not_a_table(self):
        self.write([_change("u-1", "unit", "kg", "m3", "first")], {"u-1": "fo-1"})
        connection = sqlite3.connect(self.path)
        try:
            kind = connection.execute(
                "SELECT type FROM sqlite_master WHERE name = 'provenance_activities'"
            ).fetchone()
        finally:
            connection.close()
        self.assertEqual(kind[0], "view")

    def test_versions_count_from_one_per_flow(self):
        self.write(
            [
                _change("u-1", "prefLabel", "a", "b", "first"),
                _change("u-1", "unit", "kg", "m3", "second"),
                _change("u-2", "unit", "kg", "m3", "second"),
            ],
            {"u-1": "fo-1", "u-2": "fo-2"},
        )
        versions = [
            a.entity_version for a in read_provenance_activities(self.path, uuid="u-1")
        ]
        self.assertEqual(versions, [1, 2])
        [only] = read_provenance_activities(self.path, uuid="u-2")
        self.assertEqual(only.entity_version, 1)
        self.assertEqual(only.used_entity_id, "ef:flow/u-2/v0")

    def test_one_edit_on_many_flows_is_one_activity_per_flow(self):
        """Sharing a `change_index` -- and so an activity IRI -- is what PROV-O
        means by one activity generating several entities."""
        flows = [f"u-{n}" for n in range(5)]
        self.write(
            [
                _change(uuid, "altLabel", [], [{"@value": "x"}], "chebi_altlabels")
                for uuid in flows
            ],
            {uuid: "fo-1" for uuid in flows},
        )
        trail = read_provenance_activities(self.path)
        self.assertEqual(len(trail), 5)
        self.assertEqual({a.change_index for a in trail}, {1})
        self.assertEqual({a.entity_version for a in trail}, {1})

    def test_a_rebuild_replaces_a_table_left_by_an_earlier_version(self):
        """`DROP VIEW` will not remove a table. Left in place it would shadow
        the view and serve stale rows forever."""
        connection = sqlite3.connect(self.path)
        try:
            connection.execute(
                "CREATE TABLE provenance_activities (change_index INTEGER, "
                "elementary_flow_uuid TEXT, field TEXT, transformer TEXT, "
                "entity_version INTEGER)"
            )
            connection.execute(
                "INSERT INTO provenance_activities VALUES (99, 'stale', 'x', 'y', 7)"
            )
            connection.commit()
        finally:
            connection.close()

        self.write([_change("u-1", "unit", "kg", "m3", "first")], {"u-1": "fo-1"})

        connection = sqlite3.connect(self.path)
        try:
            kind = connection.execute(
                "SELECT type FROM sqlite_master WHERE name = 'provenance_activities'"
            ).fetchone()[0]
        finally:
            connection.close()
        self.assertEqual(kind, "view")
        self.assertEqual(
            [a.uuid for a in read_provenance_activities(self.path)], ["u-1"]
        )


if __name__ == "__main__":
    unittest.main()
