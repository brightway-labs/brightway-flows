"""A flow the merge writes carries its context's address, not only its name (#295).

Every flow has a context: where in the environment it went, or where it came
from.  A context has two parts -- a printed name a person reads, and an address
that identifies it -- and both are read off one context object, so there is no
state in which only one of them is known.

The merge's writer knew both and stored one.  All 1,200 flows ecoinvent and BAFU
brought in on the 14 August 2026 build had
`context_display = "Environmental → Ground → Silvicultural"` and
`context_iri = ""`, while all 93,993 the transform wrote had both.  Nothing
shipped wrong -- the export reads `flow_json`, which had the address all along
-- but the column exists so that "are these two flows in the same context?" can
be asked by identity rather than by rendering (#284), and an empty string equals
an empty string: the merged flows shared a context with each other and with
nothing else.  The queries that ask are the collision check, the duplicate check
and the review app's context filter.
"""

from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from brightway_flows.domain.context_registry import context_from_dict
from brightway_flows.domain.elementary_flow import ElementaryFlow
from brightway_flows.domain.flow import Flow
from brightway_flows.domain.flow_object import FlowObject
from brightway_flows.merge.datastores import _sync_new_flows_to_datastores
from brightway_flows.pipeline.review_tables import number_change_events
from brightway_flows.pipeline.sqlite import (
    _write_consensus_sqlite,
    check_context_iris_are_written,
)

_GROUND = "https://vocab.brightway.dev/flow-contexts/envi-grou-silv"
#: The payload form, for the merge rows that are still dicts, and the
#: record form for the records.  One definition either way.
_GROUND_CONTEXT = {
    "dimension": "Environmental",
    "media": "Ground",
    "geography": "Silvicultural",
}
_GROUND_CTX = context_from_dict(_GROUND_CONTEXT)


def _flow(uuid: str) -> Flow:
    return Flow(
        uuid=uuid,
        source="EF 3.1",
        unit="kg",
        prefLabel=[{"@value": f"Flow {uuid}", "@language": "en"}],
        context=_GROUND_CTX,
        context_iri=_GROUND,
    )


def _flow_object(object_id: str) -> FlowObject:
    return FlowObject(
        flow_object_id=object_id,
        prefLabel=[{"@value": f"Substance {object_id}", "@language": "en"}],
        altLabel=[],
        classifications={},
        properties={},
        references=[],
        created_from={},
    )


def _elementary(uuid: str, object_id: str) -> ElementaryFlow:
    return ElementaryFlow(
        elementary_flow_id=uuid,
        flow_object_id=object_id,
        source="EF 3.1",
        context=_GROUND_CTX,
        context_iri=_GROUND,
        unit="kg",
        unit_iri="",
        lcia_methods=[],
        general_comment=None,
        source_refs=[],
    )


def _created_flow(
    elem_id: str, object_id: str, *, context_iri: str = _GROUND
) -> ElementaryFlow:
    """What the merge hands its writer: an elementary flow, context and address."""
    return ElementaryFlow(
        elementary_flow_id=elem_id,
        flow_object_id=object_id,
        source="ecoinvent algorithm addition",
        context=_GROUND_CTX,
        context_iri=context_iri,
        unit="kg",
        unit_iri="",
        lcia_methods=[],
        general_comment="",
        source_refs=[],
    )


class MergeWritesContextIRITestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.db = Path(self._tmp.name) / "consensus-flows.sqlite3"

        with mock.patch(
            "brightway_flows.pipeline.sqlite.CONSENSUS_DB_FILEPATH", self.db
        ):
            _write_consensus_sqlite(
                [_flow("base-1")],
                number_change_events([], flow_object_id_by_uuid={}),
                [_flow_object("obj-1")],
                [_elementary("base-1", "obj-1")],
            )

    def merge_flows(self, *flows: ElementaryFlow) -> None:
        """Through the merge's own writer: a change to how it inserts is seen here."""
        with mock.patch(
            "brightway_flows.merge.datastores.CONSENSUS_DB_FILEPATH", self.db
        ):
            _sync_new_flows_to_datastores(list(flows), {"obj-1": "Substance obj-1"})

    def rows(self) -> dict[str, tuple[str, str]]:
        conn = sqlite3.connect(f"file:{self.db}?mode=ro", uri=True)
        try:
            return {
                uuid: (display, iri)
                for uuid, display, iri in conn.execute(
                    "SELECT uuid, context_display, context_iri FROM elementary_flows"
                )
            }
        finally:
            conn.close()

    def test_a_merged_flow_is_stored_with_its_context_address(self):
        self.merge_flows(_created_flow("merged-1", "obj-1"))
        self.assertEqual(
            self.rows()["merged-1"],
            ("Environmental → Ground → Silvicultural", _GROUND),
        )

    def test_a_merged_flow_shares_its_context_with_the_base_list(self):
        """The question the column was added for, asked by identity (#284)."""
        self.merge_flows(_created_flow("merged-1", "obj-1"))
        conn = sqlite3.connect(f"file:{self.db}?mode=ro", uri=True)
        try:
            same = conn.execute(
                "SELECT count(*) FROM elementary_flows WHERE context_iri = ?",
                (_GROUND,),
            ).fetchone()[0]
        finally:
            conn.close()
        self.assertEqual(same, 2)

    def test_the_check_passes_when_every_flow_has_an_address(self):
        self.merge_flows(_created_flow("merged-1", "obj-1"))
        check_context_iris_are_written(self.db)

    def test_the_check_fails_on_a_printed_context_with_no_address(self):
        """The state that shipped, written directly: name filled, address empty."""
        self.merge_flows(_created_flow("merged-1", "obj-1", context_iri=""))
        with self.assertRaises(ValueError) as caught:
            check_context_iris_are_written(self.db)
        message = str(caught.exception)
        self.assertIn("1 elementary flows", message)
        self.assertIn("ecoinvent algorithm addition", message)


if __name__ == "__main__":
    unittest.main()
