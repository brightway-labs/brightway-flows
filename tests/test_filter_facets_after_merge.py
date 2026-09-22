"""The published filter facets describe the database, not the base list (#248).

`filter_option_counts` was written once, inside the transform's SQLite writer,
and never recomputed. The merge runs afterwards and inserts flows through
`merge/datastores.py`, which touches no facet table -- so on the 2026-08-06 run
the source filter totalled 93,993 against 94,429 flows, the two ecoinvent labels
that select 247 and 189 flows were offered nowhere, and `EUR` was a unit in the
database, in the export, and in no dropdown.

The failure lands on the landing page and only there: applying any filter falls
through to the live query, where the merged flows reappear.
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
    check_filter_option_counts,
    recompute_filter_option_counts,
)
from brightway_flows.webapps.app.queries import flows as flow_queries

_BASE_UNIT = "kg"
_MERGED_UNIT = "EUR"
_BASE_SOURCE = "EF 3.1"
_MERGED_SOURCE = "ecoinvent algorithm addition"


#: Air of unstated height.  `Air` alone is not a context the vocabulary accepts:
#: the medium requires either a vertical stratum or an indoor air class.
_AIR = context_from_dict(
    {"dimension": "Environmental", "media": "Air", "strata": "Unknown"}
)


def _flow(uuid: str, *, unit: str = _BASE_UNIT, source: str = _BASE_SOURCE) -> Flow:
    return Flow(
        uuid=uuid,
        source=source,
        unit=unit,
        prefLabel=[{"@value": f"Flow {uuid}", "@language": "en"}],
        context=_AIR,
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


def _elementary(
    uuid: str, object_id: str, *, unit: str = _BASE_UNIT, source: str = _BASE_SOURCE
) -> ElementaryFlow:
    return ElementaryFlow(
        elementary_flow_id=uuid,
        flow_object_id=object_id,
        source=source,
        context=_AIR,
        context_iri="",
        unit=unit,
        unit_iri="",
        lcia_methods=[],
        general_comment=None,
        source_refs=[],
    )


class FacetsAfterMergeTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.db = Path(self._tmp.name) / "consensus-flows.sqlite3"

        flows = [_flow("base-1"), _flow("base-2")]
        flow_objects = [_flow_object("obj-1"), _flow_object("obj-2")]
        elementary = [_elementary("base-1", "obj-1"), _elementary("base-2", "obj-2")]

        with mock.patch(
            "brightway_flows.pipeline.sqlite.CONSENSUS_DB_FILEPATH", self.db
        ):
            _write_consensus_sqlite(
                flows,
                number_change_events([], flow_object_id_by_uuid={}),
                flow_objects,
                elementary,
            )

    def merge_a_flow(self) -> None:
        """What the merge does after the transform has written: add flows.

        Through the merge's own writer, so a change to how it inserts is a
        change this test sees.
        """
        with mock.patch(
            "brightway_flows.merge.datastores.CONSENSUS_DB_FILEPATH", self.db
        ):
            _sync_new_flows_to_datastores(
                [
                    ElementaryFlow(
                        elementary_flow_id="merged-1",
                        flow_object_id="obj-1",
                        source=_MERGED_SOURCE,
                        context=context_from_dict({"dimension": "Economic"}),
                        context_iri="",
                        unit=_MERGED_UNIT,
                        unit_iri="",
                        lcia_methods=[],
                        general_comment="",
                        source_refs=[],
                    )
                ],
                {"obj-1": "Substance obj-1"},
            )

    def facets(self, group: str, key: str = "") -> dict[str, int]:
        conn = sqlite3.connect(self.db)
        try:
            return dict(
                conn.execute(
                    "SELECT option_value, item_count FROM filter_option_counts "
                    "WHERE option_group = ? AND option_key = ?",
                    (group, key),
                )
            )
        finally:
            conn.close()

    def read_only(self) -> sqlite3.Connection:
        conn = sqlite3.connect(f"file:{self.db}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        return conn

    def test_the_transform_alone_leaves_facets_that_add_up(self):
        check_filter_option_counts(self.db)
        self.assertEqual(self.facets("source"), {_BASE_SOURCE: 2})

    def test_a_merged_flow_leaves_the_facets_behind(self):
        """The state that shipped: the flow is in the database and in no filter."""
        self.merge_a_flow()
        self.assertEqual(self.facets("source"), {_BASE_SOURCE: 2})
        with self.assertRaises(ValueError) as caught:
            check_filter_option_counts(self.db)
        self.assertIn("stale", str(caught.exception))

    def test_recomputing_offers_every_merged_value(self):
        self.merge_a_flow()
        recompute_filter_option_counts(self.db)

        check_filter_option_counts(self.db)
        self.assertEqual(self.facets("source"), {_BASE_SOURCE: 2, _MERGED_SOURCE: 1})
        self.assertEqual(self.facets("unit"), {_BASE_UNIT: 2, _MERGED_UNIT: 1})
        self.assertEqual(
            self.facets("context", "dimension"), {"Environmental": 2, "Economic": 1}
        )

    def test_the_reader_can_select_the_merged_flows(self):
        """End to end, on the page a reader opens first: nothing filtered."""
        self.merge_a_flow()
        recompute_filter_option_counts(self.db)

        connection = self.read_only()
        try:
            options = flow_queries.filter_options(connection, flow_queries.FlowFilters())
            self.assertIn(_MERGED_SOURCE, dict(options["source"]))
            self.assertIn(_MERGED_UNIT, dict(options["unit"]))

            page = flow_queries.flow_page(
                connection, flow_queries.FlowFilters(source=_MERGED_SOURCE)
            )
            self.assertEqual([row.uuid for row in page.rows], ["merged-1"])
        finally:
            connection.close()

    def test_recomputing_twice_is_the_same_answer(self):
        """`build` runs it over a database the transform already wrote one into."""
        self.merge_a_flow()
        recompute_filter_option_counts(self.db)
        first = self.facets("source")
        recompute_filter_option_counts(self.db)
        self.assertEqual(self.facets("source"), first)


if __name__ == "__main__":
    unittest.main()
