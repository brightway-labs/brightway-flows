"""A substance's property entry reaches every record that publishes it (#407, phase C).

`merge_object_payload` lets a flow's own keys win over its object's shared
payload, so a flow that still carries its own `properties` -- one whose
object's flows disagreed at build time, or one the merge minted with its whole
body and no payload row -- would publish a record without the quantity entry
its substance gained.  The write-back after the property pass writes the entry
onto those flows as well as onto the object and its payload.
"""

import sqlite3
import tempfile
import unittest
from pathlib import Path

import orjson

from brightway_flows.domain.context_registry import context_from_dict
from brightway_flows.domain.elementary_flow import ElementaryFlow
from brightway_flows.domain.flow import Flow
from brightway_flows.domain.flow_object import FlowObject
from brightway_flows.merge.datastores import sync_flow_object_properties
from brightway_flows.pipeline.sqlite import _write_consensus_sqlite, merge_object_payload

_AIR = context_from_dict(
    {"dimension": "Environmental", "media": "Air", "strata": "Unknown"}
)


def _flow(uuid: str, **fields) -> Flow:
    return Flow(uuid=uuid, source="EF 3.1", unit="kg", context=_AIR, **fields)


def _elementary(uuid: str, object_id: str) -> ElementaryFlow:
    return ElementaryFlow(
        elementary_flow_id=uuid, flow_object_id=object_id, source="EF 3.1",
        context=_AIR, context_iri="", unit="kg", unit_iri="", lcia_methods=[],
        general_comment=None, source_refs=[],
    )


ENTRY = {"https://vocab.brightway.one/quantity/net-calorific-value": {"rdfs:label": "Net calorific value"}}


class SyncTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = Path(self.tmp.name) / "consensus-flows.sqlite3"

    def _object(self, object_id, properties):
        return FlowObject(
            flow_object_id=object_id, prefLabel=[], altLabel=[], classifications={},
            properties=properties, references=[], created_from={},
        )

    def _stored(self):
        connection = sqlite3.connect(self.db)
        try:
            payloads = dict(connection.execute(
                "SELECT flow_object_id, payload_json FROM flow_object_payloads"
            ).fetchall())
            flows = {
                uuid: merge_object_payload(orjson.loads(flow_json), payloads.get(object_id))
                for uuid, object_id, flow_json in connection.execute(
                    "SELECT uuid, flow_object_id, flow_json FROM elementary_flows"
                )
            }
            own = {
                uuid: orjson.loads(flow_json).get("properties")
                for uuid, flow_json in connection.execute(
                    "SELECT uuid, flow_json FROM elementary_flows"
                )
            }
            return flows, own
        finally:
            connection.close()

    def test_a_flow_that_keeps_its_own_properties_receives_the_entry(self):
        # `fo-1`'s two flows agree on `properties`, so the key hoists to the
        # payload and the flows read it from there; `fo-2`'s two disagree, so
        # each keeps its own copy and the payload has nothing to give them.
        _write_consensus_sqlite(
            [
                _flow("u-1", properties={"x": 1}),
                _flow("u-2", properties={"x": 1}),
                _flow("u-3", properties={"x": 2}),
                _flow("u-4", properties={"x": 3}),
                _flow("u-5", properties={"y": 4}),
            ],
            [],
            [
                self._object("fo-1", {"x": 1}),
                self._object("fo-2", {"x": 2}),
                self._object("fo-3", {"y": 4}),
            ],
            [
                _elementary("u-1", "fo-1"), _elementary("u-2", "fo-1"),
                _elementary("u-3", "fo-2"), _elementary("u-4", "fo-2"),
                _elementary("u-5", "fo-3"),
            ],
            db_path=self.db,
        )
        flows, own = self._stored()
        self.assertIsNone(own["u-1"], "the agreed key hoisted to the payload")
        self.assertEqual(own["u-3"], {"x": 2}, "a disagreeing flow keeps its own")

        written = sync_flow_object_properties(
            [
                self._object("fo-1", {"x": 1, **ENTRY}),
                self._object("fo-2", {"x": 2, **ENTRY}),
                self._object("fo-3", {"y": 4}),
            ],
            {"fo-1", "fo-2"},
            self.db,
        )
        self.assertEqual(written, 2)
        flows, own = self._stored()
        for uuid in ("u-1", "u-2"):
            with self.subTest(flow=uuid):
                self.assertEqual(flows[uuid]["properties"], {"x": 1, **ENTRY})
                self.assertIsNone(own[uuid], "read from the payload, not given a copy")
        for uuid in ("u-3", "u-4"):
            with self.subTest(flow=uuid):
                self.assertEqual(flows[uuid]["properties"], {"x": 2, **ENTRY})
                self.assertEqual(own[uuid], {"x": 2, **ENTRY}, "written onto the flow's own copy")
        self.assertEqual(flows["u-5"]["properties"], {"y": 4}, "another object's flow is untouched")

    def test_a_flow_with_no_payload_row_receives_the_entry_on_its_own_record(self):
        """A minted flow is written with its whole body and no payload row."""
        _write_consensus_sqlite(
            [_flow("u-1", properties={"x": 1})],
            [],
            [self._object("fo-1", {"x": 1})],
            [_elementary("u-1", "fo-1")],
            db_path=self.db,
        )
        connection = sqlite3.connect(self.db)
        connection.execute("DELETE FROM flow_object_payloads")
        connection.execute(
            "UPDATE elementary_flows SET flow_json = json_set(flow_json, '$.properties', json(?))",
            (orjson.dumps({"x": 1}).decode(),),
        )
        connection.commit()
        connection.close()
        sync_flow_object_properties([self._object("fo-1", {"x": 1, **ENTRY})], {"fo-1"}, self.db)
        flows, _own = self._stored()
        self.assertEqual(flows["u-1"]["properties"], {"x": 1, **ENTRY})


if __name__ == "__main__":
    unittest.main()
