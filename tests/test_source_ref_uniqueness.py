"""A source reference is a link, and a link is stored once (#23).

`elementary_flow_sources` is what `docs/reference/limitations.md` points readers
at, because the published export strips `source_refs`.  It held 197,836 rows for
103,843 links on the 2026-08-06 build: every one of the 93,993 base-list flows
appeared twice, every one of the 9,850 merged rows once.

Two independent causes, each sufficient on its own, so both are pinned here:

- The table had no constraint on its natural key, only an autoincrementing `id`.
  Both of the merge's `INSERT OR IGNORE` statements therefore had no conflict to
  detect and degraded to plain inserts, writing a second copy of every reference
  the transform had already written.
- `sync_merge_results` selected the flows to re-sync by removing the ids this
  merge generated from `accumulator.merged_elementary` -- which is the whole
  working list, so what was left was every pre-existing flow rather than the
  ones this merge matched.  7,441 flows were matched; 93,993 were re-synced.

The invariant is one line and belongs where a test can see it: a row count that
exceeds the distinct-link count means something wrote a link twice.
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
from brightway_flows.merge.datastores import _sync_existing_flow_source_refs
from brightway_flows.merge.report import AlgorithmMatch, PreparedMatch
from brightway_flows.pipeline.sqlite import _write_consensus_sqlite

_NATURAL_KEY = "elementary_flow_uuid, list_name, list_version, source_flow_uuid"


#: Air of unstated height.  These fixtures said `["Air"]` back when the
#: field held anything; the context they meant is this one.
_AIR = context_from_dict(
    {"dimension": "Environmental", "media": "Air", "strata": "Unknown"}
)

def _source_ref(source_flow_uuid: str, name: str = "carbon dioxide") -> dict:
    return {
        "list_name": "EF",
        "list_version": "3.1",
        "source_flow_uuid": source_flow_uuid,
        "source_flow_name": name,
        "source_metadata": {"input_dataset": "EF 3.1"},
    }


#: The reference a matched flow gains from the merge, alongside the base list's.
_ECOINVENT_REF = {
    "list_name": "ecoinvent",
    "list_version": "3.12",
    "source_flow_uuid": "ei-1",
    "source_flow_name": "Carbon dioxide",
    "source_metadata": {},
}


def _flow(
    source_refs: list[dict],
    *,
    elementary_flow_id: str = "flow-1",
    source: str = "EF 3.1",
) -> ElementaryFlow:
    """One row of the merge's working list, carrying the references given."""
    return ElementaryFlow(
        elementary_flow_id=elementary_flow_id,
        flow_object_id="fo-1",
        source=source,
        context=_AIR,
        context_iri="",
        unit="kg",
        unit_iri="",
        lcia_methods=[],
        general_comment=None,
        source_refs=source_refs,
    )


class _RealSchemaTestCase(unittest.TestCase):
    """A database built by the transform's own writer.

    The schema is not restated here.  A hand-copied `CREATE TABLE` in a test is
    what let this defect survive: it would have carried whatever constraint the
    test author assumed, and passed while production had none.
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = Path(self.tmp.name) / "consensus-flows.sqlite3"
        patch = mock.patch(
            "brightway_flows.pipeline.sqlite.CONSENSUS_DB_FILEPATH", self.db
        )
        patch.start()
        self.addCleanup(patch.stop)

    def write(self, refs: list[dict], elementary_flow_id: str = "flow-1") -> None:
        flow = Flow(
            uuid=elementary_flow_id, source="EF 3.1", unit="kg", context=_AIR,
        )
        elementary = ElementaryFlow(
            elementary_flow_id=elementary_flow_id,
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
        _write_consensus_sqlite([flow], [], [], [elementary])


class TransformWriteTestCase(_RealSchemaTestCase):
    """The table the transform creates carries the constraint."""

    def counts(self) -> tuple[int, int]:
        conn = sqlite3.connect(self.db)
        try:
            rows = conn.execute("SELECT count(*) FROM elementary_flow_sources").fetchone()[0]
            links = conn.execute(
                f"SELECT count(*) FROM (SELECT DISTINCT {_NATURAL_KEY} "
                "FROM elementary_flow_sources)"
            ).fetchone()[0]
        finally:
            conn.close()
        return rows, links

    def test_a_reference_is_stored_once(self):
        self.write([_source_ref("src-1")])
        self.assertEqual(self.counts(), (1, 1))

    def test_two_references_to_different_source_flows_both_land(self):
        self.write([_source_ref("src-1"), _source_ref("src-2")])
        self.assertEqual(self.counts(), (2, 2))

    def test_the_transform_may_not_write_a_link_twice(self):
        """Not `OR IGNORE` here: the transform builds these rows from one
        record's `source_refs`, so a repeat is a defect in that record rather
        than the expected overlap the merge deals with."""
        with self.assertRaises(sqlite3.IntegrityError):
            self.write([_source_ref("src-1"), _source_ref("src-1", name="CO2")])


class MergeResyncTestCase(_RealSchemaTestCase):
    """Re-inserting a reference the transform already wrote is a no-op.

    The transform runs first and writes the base list's reference; the merge
    then re-syncs the flows it matched, handing back that reference alongside
    the one it added.  So this starts from a real transform write rather than an
    empty table -- the overlap is the whole point.
    """

    def setUp(self):
        super().setUp()
        self.write([_source_ref("src-1")])
        patch = mock.patch(
            "brightway_flows.merge.datastores.CONSENSUS_DB_FILEPATH", self.db
        )
        patch.start()
        self.addCleanup(patch.stop)

    def rows(self) -> list[tuple]:
        conn = sqlite3.connect(self.db)
        try:
            return conn.execute(
                f"SELECT {_NATURAL_KEY} FROM elementary_flow_sources ORDER BY id"
            ).fetchall()
        finally:
            conn.close()

    def test_the_base_list_reference_is_not_written_a_second_time(self):
        """This is the 93,993 doubled rows, reduced to one flow."""
        _sync_existing_flow_source_refs([_flow([_source_ref("src-1")])])
        self.assertEqual(self.rows(), [("flow-1", "EF", "3.1", "src-1")])

    def test_the_reference_the_merge_adds_still_lands(self):
        _sync_existing_flow_source_refs(
            [_flow([_source_ref("src-1"), _ECOINVENT_REF])]
        )
        self.assertEqual(
            self.rows(),
            [
                ("flow-1", "EF", "3.1", "src-1"),
                ("flow-1", "ecoinvent", "3.12", "ei-1"),
            ],
        )

    def test_re_running_the_merge_adds_nothing(self):
        flow = _flow([_source_ref("src-1"), _ECOINVENT_REF])
        _sync_existing_flow_source_refs([flow])
        _sync_existing_flow_source_refs([flow])
        self.assertEqual(len(self.rows()), 2)


class ResyncSelectionTestCase(unittest.TestCase):
    """Only the flows this merge matched are handed to the re-sync."""

    def _accumulator(self, matched_target_id: str):
        from brightway_flows.merge.state import MergeAccumulator

        accumulator = MergeAccumulator()
        accumulator.merged_elementary = [
            _flow([_source_ref("src-1")], elementary_flow_id="matched"),
            _flow([_source_ref("src-2")], elementary_flow_id="untouched"),
        ]
        # Both were in the database before this pass; `build_merge_accumulator`
        # is what records that on a real run.
        accumulator.preexisting_flow_ids = frozenset({"matched", "untouched"})
        accumulator.prepared_matches = [
            mock.Mock(spec=PreparedMatch, target_elementary_flow_id=matched_target_id)
        ]
        accumulator.algorithm_matches = []
        return accumulator

    def test_an_unmatched_pre_existing_flow_is_left_alone(self):
        from brightway_flows.merge.datastores import sync_merge_results

        accumulator = self._accumulator("matched")
        indexes = mock.Mock()
        indexes.flow_object_label_by_id = {}

        with mock.patch(
            "brightway_flows.merge.datastores._sync_existing_flow_source_refs"
        ) as refs, mock.patch(
            "brightway_flows.merge.datastores._sync_existing_flow_concept_associations"
        ), mock.patch(
            "brightway_flows.merge.datastores._sync_new_flow_objects_to_datastores"
        ), mock.patch(
            "brightway_flows.merge.datastores._sync_new_flows_to_datastores"
        ):
            sync_merge_results(
                new_flow_objects=[], indexes=indexes, accumulator=accumulator
            )

        handed = [f.elementary_flow_id for f in refs.call_args.args[0]]
        self.assertEqual(handed, ["matched"])

    def test_an_algorithm_match_onto_a_created_flow_is_not_re_synced(self):
        """`_sync_new_flows_to_datastores` has already written it in full."""
        from brightway_flows.merge.datastores import sync_merge_results

        accumulator = self._accumulator("created")
        # Created by *this* pass, so it is absent from `preexisting_flow_ids`.
        accumulator.merged_elementary.append(_flow(
            [_source_ref("src-3")],
            elementary_flow_id="created",
            source="ecoinvent algorithm addition",
        ))
        accumulator.added_flow_ids.add("created")
        accumulator.prepared_matches = []
        accumulator.algorithm_matches = [
            mock.Mock(spec=AlgorithmMatch, target_elementary_flow_id="created")
        ]
        indexes = mock.Mock()
        indexes.flow_object_label_by_id = {}

        with mock.patch(
            "brightway_flows.merge.datastores._sync_existing_flow_source_refs"
        ) as refs, mock.patch(
            "brightway_flows.merge.datastores._sync_existing_flow_concept_associations"
        ), mock.patch(
            "brightway_flows.merge.datastores._sync_new_flow_objects_to_datastores"
        ), mock.patch(
            "brightway_flows.merge.datastores._sync_new_flows_to_datastores"
        ):
            sync_merge_results(
                new_flow_objects=[], indexes=indexes, accumulator=accumulator
            )

        self.assertEqual(refs.call_args.args[0], [])


if __name__ == "__main__":
    unittest.main()
