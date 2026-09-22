"""`elementary_flow_sources` is the only home for a flow's references (#30).

A flow's `source_refs` had three homes: the table, `flow_json`, and the
`elementary_flow_json` projected from it.  The transform wrote all three from
one record, so at build time they agreed.  The merge then appended a matched
flow's new reference to the table alone -- `_sync_existing_flow_source_refs`
touches no payload -- and the two JSON copies were the pre-merge answer from
that point on.

On the 2026-08-07 build that was 7,794 of 94,433 flows carrying a stored
`source_refs` shorter than the table's: the payload named the base list's single
source where the table named two to 38.  The direction never reversed -- no
payload held a reference the table lacked, and no flow was missing from the
table.  So the table was never the incomplete copy, and the fix is to stop
storing the other two rather than to write three places.

What is pinned here is that no payload writer puts the field back.
"""

from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import orjson

from brightway_flows.domain.context_registry import context_from_dict
from brightway_flows.domain.elementary_flow import ElementaryFlow
from brightway_flows.domain.flow import Flow
from brightway_flows.merge.datastores import _sync_new_flows_to_datastores
from brightway_flows.pipeline.sqlite import (
    _write_consensus_sqlite,
    _without_source_refs,
    elementary_flow_record,
)

_EF_REF = {
    "list_name": "EF",
    "list_version": "3.1",
    "source_flow_uuid": "ef-1",
    "source_flow_name": "carbon dioxide",
    "source_metadata": {"input_dataset": "EF 3.1"},
}

#: The reference the merge adds to a flow the base list already had.  It reaches
#: the table and nothing else, which is what made the stored copies short.
_ECOINVENT_REF = {
    "list_name": "ecoinvent",
    "list_version": "3.12",
    "source_flow_uuid": "ei-1",
    "source_flow_name": "Carbon dioxide",
    "source_metadata": {},
}


#: Air of unstated height.  These fixtures said `["Air"]` back when the
#: field held anything; the context they meant is this one.
_AIR = context_from_dict(
    {"dimension": "Environmental", "media": "Air", "strata": "Unknown"}
)

class _RealSchemaTestCase(unittest.TestCase):
    """A database built by the transform's own writer.

    The schema is not restated here, for the reason `test_source_ref_uniqueness`
    gives: a hand-copied `CREATE TABLE` in a test carries whatever the test
    author assumed and passes while production differs.
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = Path(self.tmp.name) / "consensus-flows.sqlite3"
        for module in (
            "brightway_flows.pipeline.sqlite",
            "brightway_flows.merge.datastores",
        ):
            patch = mock.patch(f"{module}.CONSENSUS_DB_FILEPATH", self.db)
            patch.start()
            self.addCleanup(patch.stop)

    def build(self, refs: list[dict], uuid: str = "flow-1") -> None:
        """One base-list flow, its references on both records the writer reads."""
        flow = Flow(
            uuid=uuid,
            flow_object_id="fo-1",
            source="EF 3.1",
            unit="kg",
            context=_AIR,
            source_refs=refs,
        )
        layered = ElementaryFlow(
            elementary_flow_id=uuid,
            flow_object_id="fo-1",
            source="EF 3.1",
            context=_AIR,
            context_iri="",
            unit="kg",
            unit_iri="",
            lcia_methods=[],
            general_comment=None,
            source_refs=refs,
        )
        _write_consensus_sqlite([flow], [], [], [layered])

    def payload(self, uuid: str = "flow-1") -> dict:
        conn = sqlite3.connect(self.db)
        try:
            row = conn.execute(
                "SELECT flow_json FROM elementary_flows WHERE uuid = ?", (uuid,)
            ).fetchone()
        finally:
            conn.close()
        self.assertIsNotNone(row, f"no elementary_flows row for {uuid}")
        return orjson.loads(row[0])

    def table_refs(self, uuid: str = "flow-1") -> list[tuple[str, str, str]]:
        conn = sqlite3.connect(self.db)
        try:
            return conn.execute(
                "SELECT list_name, list_version, source_flow_uuid "
                "FROM elementary_flow_sources WHERE elementary_flow_uuid = ? "
                "ORDER BY list_name, list_version",
                (uuid,),
            ).fetchall()
        finally:
            conn.close()


class TransformWriteTestCase(_RealSchemaTestCase):
    """The transform writes the table and not the payload."""

    def test_the_stored_payload_carries_no_references(self):
        self.build([_EF_REF])
        self.assertNotIn("source_refs", self.payload())

    def test_the_table_still_carries_them(self):
        """The point is one home, not none."""
        self.build([_EF_REF])
        self.assertEqual(self.table_refs(), [("EF", "3.1", "ef-1")])


class MergeWriteTestCase(_RealSchemaTestCase):
    """A flow the merge creates is stored the same way."""

    def test_a_created_flow_is_stored_without_its_references(self):
        """It would otherwise keep the one reference it was minted from and
        never gain the ones a later pass matches to it -- the same staleness,
        starting one build earlier."""
        self.build([_EF_REF])
        _sync_new_flows_to_datastores(
            [ElementaryFlow(
                elementary_flow_id="flow-2",
                flow_object_id="fo-1",
                source="ecoinvent algorithm addition",
                # A consensus context, not the compartment a source list
                # ships: the writer reads the context's attributes by name.
                context=context_from_dict({
                    "dimension": "Environmental", "media": "Air",
                    "strata": "Unknown",
                }),
                context_iri="",
                unit="kg",
                unit_iri="",
                lcia_methods=[],
                general_comment="",
                source_refs=[_ECOINVENT_REF],
            )],
            {"fo-1": "Carbon dioxide"},
        )
        self.assertNotIn("source_refs", self.payload("flow-2"))
        self.assertEqual(
            self.table_refs("flow-2"), [("ecoinvent", "3.12", "ei-1")]
        )


class ProjectionTestCase(unittest.TestCase):
    """`elementary_flow_json` is projected from `flow_json`, so it inherits the
    absence -- but the projection names its keys, so this is worth stating."""

    def test_the_merges_record_is_not_given_references(self):
        record = elementary_flow_record({
            "uuid": "flow-1",
            "flow_object_id": "fo-1",
            "unit": "kg",
            "source_refs": [_EF_REF],
        })
        self.assertNotIn("source_refs", record)
        self.assertEqual(record["elementary_flow_id"], "flow-1")


class HelperTestCase(unittest.TestCase):
    def test_the_input_record_is_left_alone(self):
        """The transform's writers still read the record after storing it, and
        the merge builds the table rows from the same dict."""
        flow = {"uuid": "flow-1", "source_refs": [_EF_REF]}
        stripped = _without_source_refs(flow)
        self.assertNotIn("source_refs", stripped)
        self.assertEqual(flow["source_refs"], [_EF_REF])

    def test_every_other_key_survives(self):
        self.assertEqual(
            _without_source_refs({"uuid": "flow-1", "unit": "kg"}),
            {"uuid": "flow-1", "unit": "kg"},
        )


if __name__ == "__main__":
    unittest.main()
