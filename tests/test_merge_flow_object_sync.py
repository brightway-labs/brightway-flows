"""Flow objects the merge created reach the database (#215).

Until #215 nothing in `merge/` minted a flow object, so `_sync_new_flows_to_datastores`
wrote elementary flows and nothing else. Two consumers need the object row: the
`consensus_flows` view reads a flow's name, classifications and properties off it
through a LEFT JOIN — so a missing object publishes a flow with a null name
rather than no flow — and `_load_working_set` is how the next source list in the
same run sees what this one created.
"""

from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import orjson

from brightway_flows.domain.vocabulary import (
    CHEMINF_CAS_REGISTRY_NUMBER,
    CHEMROF_MONOATOMIC_ION,
)
from brightway_flows.domain.flow_object import FlowObject
from brightway_flows.merge.datastores import _sync_new_flow_objects_to_datastores

SCHEMA = """
CREATE TABLE flow_objects (
    flow_object_id TEXT PRIMARY KEY,
    pref_label_value TEXT,
    pref_label_json TEXT,
    alt_label_json TEXT,
    classifications_json TEXT,
    properties_json TEXT,
    references_json TEXT,
    flow_object_json TEXT,
    origin_qualifier TEXT,
    parent_flow_object_id TEXT,
    parent_intervention_id TEXT,
    flow_type TEXT NOT NULL DEFAULT 'unclassified'
);
CREATE VIRTUAL TABLE flow_objects_fts USING fts5(
    flow_object_id, pref_label, alt_labels, cas_numbers, ec_numbers
);
"""


def _flow_object(
    object_id: str, label: str, cas: str = "", types=None
) -> FlowObject:
    payload: dict = {
        "flow_object_id": object_id,
        "prefLabel": [{"@value": label, "@language": "en"}],
        "altLabel": [{"@value": f"{label} synonym", "@language": "en"}],
        "properties": {},
        "references": [],
        "classifications": (
            {CHEMINF_CAS_REGISTRY_NUMBER: {"@value": [cas]}} if cas else {}
        ),
        "created_from": {"resolver": "hybrid_name_cas_v1"},
    }
    if types:
        payload["@type"] = list(types)
    # Built from the payload rather than the constructor so `@type` goes in
    # through the alias, which is the route `_load_working_set` uses.
    return FlowObject.from_dict(payload)


class SyncNewFlowObjectsTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.db = Path(self._tmp.name) / "consensus-flows.sqlite3"
        conn = sqlite3.connect(self.db)
        conn.executescript(SCHEMA)
        conn.commit()
        conn.close()
        patch = mock.patch(
            "brightway_flows.merge.datastores.CONSENSUS_DB_FILEPATH", self.db
        )
        patch.start()
        self.addCleanup(patch.stop)

    def rows(self, query: str) -> list[tuple]:
        conn = sqlite3.connect(self.db)
        try:
            return conn.execute(query).fetchall()
        finally:
            conn.close()

    def test_the_object_reaches_the_table_with_its_label(self):
        _sync_new_flow_objects_to_datastores([
            _flow_object("fo-1", "Ammonium Bisulfate", cas="7803-63-6")
        ])
        rows = self.rows(
            "SELECT flow_object_id, pref_label_value, classifications_json FROM flow_objects"
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][0], "fo-1")
        self.assertEqual(rows[0][1], "Ammonium Bisulfate")
        self.assertEqual(
            orjson.loads(rows[0][2])[CHEMINF_CAS_REGISTRY_NUMBER]["@value"],
            ["7803-63-6"],
        )

    def test_the_object_is_searchable_by_its_label_not_the_empty_string(self):
        _sync_new_flow_objects_to_datastores([
            _flow_object("fo-1", "Ammonium Bisulfate", cas="7803-63-6")
        ])
        rows = self.rows(
            "SELECT flow_object_id, pref_label, cas_numbers FROM flow_objects_fts"
        )
        self.assertEqual(rows, [("fo-1", "Ammonium Bisulfate", "7803-63-6")])

    def test_flow_type_is_computed_rather_than_left_at_its_default(self):
        _sync_new_flow_objects_to_datastores([
            _flow_object("fo-1", "Butatriene", types=[CHEMROF_MONOATOMIC_ION])
        ])
        self.assertEqual(
            self.rows("SELECT flow_type FROM flow_objects")[0][0],
            CHEMROF_MONOATOMIC_ION,
        )

    def test_an_untyped_object_is_unclassified_not_a_write_failure(self):
        """The column is NOT NULL, so the fallback has to be a value."""
        _sync_new_flow_objects_to_datastores([_flow_object("fo-1", "Alkylbenzene")])
        self.assertEqual(
            self.rows("SELECT flow_type FROM flow_objects")[0][0], "unclassified"
        )

    def test_an_id_already_present_is_left_alone(self):
        _sync_new_flow_objects_to_datastores([_flow_object("fo-1", "First")])
        _sync_new_flow_objects_to_datastores([_flow_object("fo-1", "Second")])
        self.assertEqual(
            self.rows("SELECT pref_label_value FROM flow_objects"), [("First",)]
        )

    def test_nothing_to_write_touches_nothing(self):
        _sync_new_flow_objects_to_datastores([])
        self.assertEqual(self.rows("SELECT count(*) FROM flow_objects"), [(0,)])


if __name__ == "__main__":
    unittest.main()
