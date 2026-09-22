"""The substance's body is stored once, not once per flow (#253).

`flow_json` embedded the flow object's labels, properties and references in
every elementary flow.  94,433 flows share 7,730 objects, so those keys came to
1,267.5 MiB across the table where one copy each is 98.6 MiB -- 1.57 GiB of an
8.13 GiB file.

Two things make this safe, and both are pinned here.

**It is not re-derived from `flow_objects`.**  That was the obvious design and
it is wrong: the same information is serialised differently there -- a label
carries `@lang` and `provenance` where the flow's carries `source` -- so reading
it back would have rewritten 93,993 of 94,433 `prefLabel` values in the
published export.  What is stored is the flow-shaped bytes, verbatim.

**A key is hoisted only where every flow of the object agreed.**  They usually
do, but on the 2026-08-07 build 233 objects disagree on `prefLabel`, 72 on
`altLabel`, 17 on `properties` and 2 on `references`.  A flow that disagrees
keeps its own copy and wins on the way back, so the rule is "a key absent from
`flow_json` is the object's" -- no overrides, and nothing can be lost.
"""

from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import orjson

from brightway_flows.domain.context_registry import context_from_dict
from brightway_flows.domain.elementary_flow import ElementaryFlow
from brightway_flows.domain.flow import Flow
from brightway_flows.domain.flow_object import FlowObject
from brightway_flows.pipeline.sqlite import (
    _EF_FLOW_JSON,
    _EF_FLOW_OBJECT_ID,
    _OBJECT_DERIVED_KEYS,
    _hoist_shared_object_payloads,
    _write_consensus_sqlite,
    merge_object_payload,
    read_published_flow_payloads,
)

REPO_ROOT = Path(__file__).resolve().parents[1]


#: Air of unstated height.  These fixtures said `["Air"]` back when the
#: field held anything; the context they meant is this one.
_AIR = context_from_dict(
    {"dimension": "Environmental", "media": "Air", "strata": "Unknown"}
)

def _flow(uuid: str, **fields) -> Flow:
    return Flow(uuid=uuid, source="EF 3.1", unit="kg", context=_AIR, **fields)


def _elementary(uuid: str, object_id: str) -> ElementaryFlow:
    return ElementaryFlow(
        elementary_flow_id=uuid,
        flow_object_id=object_id,
        source="EF 3.1",
        context=_AIR,
        context_iri="",
        unit="kg",
        unit_iri="",
        lcia_methods=[],
        general_comment=None,
        source_refs=[],
    )


LABELS = [{"@value": f"synonym {n}", "@language": "en"} for n in range(40)]


class HoistTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = Path(self.tmp.name) / "consensus-flows.sqlite3"
        patch = mock.patch(
            "brightway_flows.pipeline.sqlite.CONSENSUS_DB_FILEPATH", self.db
        )
        patch.start()
        self.addCleanup(patch.stop)

    def write(self, flows: list[Flow], objects: dict[str, str]) -> None:
        flow_objects = [
            FlowObject(
                flow_object_id=oid, prefLabel=[], altLabel=[], classifications={},
                properties={}, references=[], created_from={},
            )
            for oid in sorted(set(objects.values()))
        ]
        _write_consensus_sqlite(
            flows,
            [],
            flow_objects,
            [_elementary(flow.uuid, objects[flow.uuid]) for flow in flows],
        )

    def stored(self) -> dict[str, dict]:
        connection = sqlite3.connect(self.db)
        try:
            return {
                row[0]: orjson.loads(row[1])
                for row in connection.execute(
                    "SELECT uuid, flow_json FROM elementary_flows"
                )
            }
        finally:
            connection.close()

    def payloads(self) -> dict[str, dict]:
        connection = sqlite3.connect(self.db)
        try:
            return {
                row[0]: orjson.loads(row[1])
                for row in connection.execute(
                    "SELECT flow_object_id, payload_json FROM flow_object_payloads"
                )
            }
        finally:
            connection.close()

    def test_an_agreed_key_leaves_the_flows_and_is_stored_once(self):
        self.write(
            [_flow("u-1", altLabel=LABELS), _flow("u-2", altLabel=LABELS)],
            {"u-1": "fo-1", "u-2": "fo-1"},
        )
        for flow in self.stored().values():
            self.assertNotIn("altLabel", flow)
        self.assertEqual(self.payloads()["fo-1"]["altLabel"], LABELS)

    def test_the_flows_read_back_whole(self):
        self.write(
            [_flow("u-1", altLabel=LABELS), _flow("u-2", altLabel=LABELS)],
            {"u-1": "fo-1", "u-2": "fo-1"},
        )
        restored = {f["uuid"]: f for f in read_published_flow_payloads(self.db)}
        self.assertEqual(restored["u-1"]["altLabel"], LABELS)
        self.assertEqual(restored["u-2"]["altLabel"], LABELS)

    def test_a_disagreeing_flow_keeps_its_own_copy(self):
        """233 objects disagree on `prefLabel` on the real build."""
        mine = [{"@value": "Only mine", "@language": "en"}]
        self.write(
            [_flow("u-1", altLabel=LABELS), _flow("u-2", altLabel=mine)],
            {"u-1": "fo-1", "u-2": "fo-1"},
        )
        # The object still has a payload row -- `properties` and `references`
        # are empty on both flows, and two flows that agree on a key share it
        # however dull the value.  What must not be there is the key they
        # disagree about.
        self.assertNotIn("altLabel", self.payloads().get("fo-1", {}))
        restored = {f["uuid"]: f for f in read_published_flow_payloads(self.db)}
        self.assertEqual(restored["u-1"]["altLabel"], LABELS)
        self.assertEqual(restored["u-2"]["altLabel"], mine)

    def test_a_key_only_some_flows_carry_is_not_hoisted(self):
        """Hoisting it would hand it to a flow that never had it.

        `prefLabel` rather than `altLabel`, which every other case here uses:
        the two are hoisted alike, and `prefLabel` is the one of them a `Flow`
        can be without -- it is omitted from the payload when it is None, where
        `altLabel` defaults to an empty list and is always written.
        """
        self.write(
            [_flow("u-1", prefLabel=LABELS), _flow("u-2")],
            {"u-1": "fo-1", "u-2": "fo-1"},
        )
        restored = {f["uuid"]: f for f in read_published_flow_payloads(self.db)}
        self.assertEqual(restored["u-1"]["prefLabel"], LABELS)
        self.assertNotIn("prefLabel", restored["u-2"])

    def test_flow_specific_keys_are_never_hoisted(self):
        """`concept_associations` is per flow, and #252 was it going missing."""
        self.write(
            [
                _flow("u-1", altLabel=LABELS,
                      concept_associations=[{"target": "a"}]),
                _flow("u-2", altLabel=LABELS,
                      concept_associations=[{"target": "b"}]),
            ],
            {"u-1": "fo-1", "u-2": "fo-1"},
        )
        for flow in self.stored().values():
            self.assertIn("concept_associations", flow)
        restored = {f["uuid"]: f for f in read_published_flow_payloads(self.db)}
        self.assertEqual(restored["u-1"]["concept_associations"], [{"target": "a"}])
        self.assertEqual(restored["u-2"]["concept_associations"], [{"target": "b"}])

    def test_two_objects_do_not_share_a_payload(self):
        other = [{"@value": "Different", "@language": "en"}]
        self.write(
            [_flow("u-1", altLabel=LABELS), _flow("u-2", altLabel=other)],
            {"u-1": "fo-1", "u-2": "fo-2"},
        )
        payloads = self.payloads()
        self.assertEqual(payloads["fo-1"]["altLabel"], LABELS)
        self.assertEqual(payloads["fo-2"]["altLabel"], other)

    def test_export_order_survives_the_join(self):
        """The export preserves flow order and a join does not guarantee it."""
        flows = [_flow(f"u-{n}", altLabel=LABELS) for n in range(12)]
        self.write(flows, {flow.uuid: "fo-1" for flow in flows})
        self.assertEqual(
            [f["uuid"] for f in read_published_flow_payloads(self.db)],
            [flow.uuid for flow in flows],
        )


class MergeObjectPayloadTestCase(unittest.TestCase):
    def test_the_flow_wins(self):
        merged = merge_object_payload({"altLabel": ["mine"]},
                                      orjson.dumps({"altLabel": ["shared"]}))
        self.assertEqual(merged["altLabel"], ["mine"])

    def test_a_missing_payload_is_the_flow_unchanged(self):
        flow = {"uuid": "u-1"}
        self.assertEqual(merge_object_payload(flow, None), flow)
        self.assertEqual(merge_object_payload(flow, ""), flow)

    def test_a_corrupt_payload_does_not_take_the_flow_with_it(self):
        flow = {"uuid": "u-1"}
        self.assertEqual(merge_object_payload(flow, "{not json"), flow)
        self.assertEqual(merge_object_payload(flow, orjson.dumps([1, 2])), flow)

    def test_it_does_not_mutate_either_side(self):
        flow = {"uuid": "u-1"}
        payload = orjson.dumps({"altLabel": ["shared"]})
        merged = merge_object_payload(flow, payload)
        self.assertNotIn("altLabel", flow)
        merged["altLabel"].append("scribble")
        self.assertEqual(
            merge_object_payload({"uuid": "u-2"}, payload)["altLabel"], ["shared"]
        )


class KeyOrderTestCase(unittest.TestCase):
    """Two runs of one revision write the same bytes (#293).

    The keys of a payload were written in the order a `set` handed them over,
    and Python randomises that per process for strings.  So every build wrote
    all 7,683 rows -- 94.8 MiB -- with their keys shuffled differently from the
    last, and comparing two databases byte for byte reported everything as
    changed.  Nothing published ever moved: a reader puts these keys back on the
    flow by name, and the export writes its own fields in its own order.  What
    it cost was the ability to say two runs produced the same artifact.
    """

    def test_the_keys_are_written_in_the_declared_order(self):
        rows = [
            _hoist_row("u-1", "fo-1", _SHARED_BODY),
            _hoist_row("u-2", "fo-1", _SHARED_BODY),
        ]
        _rewritten, payloads = _hoist_shared_object_payloads(rows)
        self.assertEqual(
            list(orjson.loads(payloads[0][1])),
            [key for key in _OBJECT_DERIVED_KEYS if key in _SHARED_BODY],
        )

    def test_two_processes_hoist_the_same_bytes(self):
        """The property itself, which one process cannot show.

        A set's iteration order is fixed for the life of a process and drawn
        afresh at the next start, so this is asked of two interpreters started
        under different hash seeds -- which is what two builds are.
        """
        payloads = [
            subprocess.run(
                [sys.executable, "-c", _HOIST_ONE_PAYLOAD],
                capture_output=True, text=True, check=True,
                env={**os.environ, "PYTHONHASHSEED": seed},
                cwd=REPO_ROOT,
            ).stdout
            for seed in ("1", "2")
        ]
        self.assertEqual(payloads[0], payloads[1])


#: A substance body carrying several of the hoistable keys, so there is an order
#: for the two runs to disagree about.
_SHARED_BODY = {
    "@type": ["chemrof:ChemicalEntity"],
    "altLabel": [{"@value": "a synonym", "@language": "en"}],
    "prefLabel": [{"@value": "a substance", "@language": "en"}],
    "properties": {"molecular_mass": 44.0},
    "references": [{"@id": "https://example.org/ref"}],
}

#: Run in a fresh interpreter, twice, under different hash seeds.
_HOIST_ONE_PAYLOAD = """
import sys
sys.path.insert(0, "src")
from tests.test_flow_object_payloads import _SHARED_BODY, _hoist_row
from brightway_flows.pipeline.sqlite import _hoist_shared_object_payloads

rows = [_hoist_row("u-1", "fo-1", _SHARED_BODY), _hoist_row("u-2", "fo-1", _SHARED_BODY)]
print(_hoist_shared_object_payloads(rows)[1][0][1])
"""


def _hoist_row(uuid: str, object_id: str, body: dict) -> tuple:
    """One `elementary_flows` insert tuple, shaped as the writer builds it."""
    width = max(_EF_FLOW_JSON, _EF_FLOW_OBJECT_ID) + 1
    row = [None] * width
    row[_EF_FLOW_OBJECT_ID] = object_id
    row[_EF_FLOW_JSON] = {"uuid": uuid, **body}
    return tuple(row)


if __name__ == "__main__":
    unittest.main()
