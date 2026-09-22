"""A run merges several versions of one list, and they must not erase each other.

The 2026-08-07 build merged ecoinvent 3.12 and then ecoinvent 3.8.  Of 4,421
ecoinvent 3.8 source flows, 4,420 were matched and linked in
`elementary_flow_sources`, but only 4,378 reached the published export -- and
ecoinvent 3.12 came out worse, losing 4,121 of its 9,850.  Two defects, each
pinned below:

- `sync_merge_results` asked whether a flow was created by *this* pass by
  comparing its `source` to `SourceList.algorithm_addition_source`, which is
  `f"{list_name} algorithm addition"` and names no version.  Every flow the
  3.12 pass created answered to it, so the 3.8 pass sent 42 already-stored rows
  to `_sync_new_flows_to_datastores`, whose `INSERT OR IGNORE` wrote nothing.
- `_sync_existing_flow_concept_associations` assigned `flow_json` alone.  The
  next pass's working set is read from `elementary_flow_json`, so it came back
  without the associations the previous pass had added and overwrote them.
"""

from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import orjson

from dataclasses import replace

from brightway_flows.domain.vocabulary import (
    XKOS_SOURCE_CONCEPT_CURIE,
    XKOS_TARGET_CONCEPT_CURIE,
)
from brightway_flows.merge.datastores import (
    _sync_existing_flow_concept_associations,
)
from brightway_flows.merge.report import AlgorithmMatch
from brightway_flows.merge.state import MergeAccumulator
from brightway_flows.domain.context_registry import context_from_dict
from brightway_flows.domain.elementary_flow import ElementaryFlow
from brightway_flows.domain.flow import Flow
from brightway_flows.pipeline.sqlite import _write_consensus_sqlite

_FLOW_ID = "flow-1"
_TARGET_IRI = f"https://vocab.brightway.dev/elementary-flows/{_FLOW_ID}"


#: Air of unstated height.  These fixtures said `["Air"]` back when the
#: field held anything; the context they meant is this one.
_AIR = context_from_dict(
    {"dimension": "Environmental", "media": "Air", "strata": "Unknown"}
)

def _association(version: str, source_uuid: str) -> dict:
    return {
        "@type": "xkos:ConceptAssociation",
        XKOS_SOURCE_CONCEPT_CURIE: {
            "@id": f"https://vocab.brightway.one/ecoinvent/{version}/flow/{source_uuid}",
            "skos:prefLabel": "Carbon dioxide",
        },
        XKOS_TARGET_CONCEPT_CURIE: {"@id": _TARGET_IRI},
    }


_FROM_312 = _association("3.12", "ei-312")
_FROM_38 = _association("3.8", "ei-38")


def _source_ref(version: str, source_uuid: str) -> dict:
    return {
        "list_name": "ecoinvent",
        "list_version": version,
        "source_flow_uuid": source_uuid,
        "source_flow_name": "Carbon dioxide",
        "source_metadata": {},
    }


def _flow(
    *,
    source: str = "ecoinvent manual addition",
    source_refs: list | None = None,
    concept_associations: list | None = None,
) -> ElementaryFlow:
    """The row a merge pass builds for the substance, as the record it is."""
    return ElementaryFlow(
        elementary_flow_id=_FLOW_ID,
        flow_object_id="fo-1",
        source=source,
        context=_AIR,
        context_iri="",
        unit="kg",
        unit_iri="",
        lcia_methods=[],
        general_comment="",
        source_refs=source_refs,
        concept_associations=concept_associations,
    )


class AddFlowCollisionTestCase(unittest.TestCase):
    """An id the working list already holds is merged into, not appended beside.

    A manual addition mints its id from the source flow's uuid, and two versions
    of a list share those uuids, so the later pass rebuilds a row the earlier
    one already wrote.
    """

    def _accumulator(self) -> MergeAccumulator:
        accumulator = MergeAccumulator()
        accumulator.add_flow(_flow(
            source_refs=[_source_ref("3.12", "ei-312")],
            concept_associations=[_FROM_312],
        ))
        return accumulator

    def test_the_rebuilt_row_does_not_become_a_second_flow(self):
        accumulator = self._accumulator()
        accumulator.add_flow(_flow(
            source_refs=[_source_ref("3.8", "ei-38")],
            concept_associations=[_FROM_38],
        ))
        self.assertEqual(len(accumulator.merged_elementary), 1)

    def test_both_versions_links_survive_the_merge(self):
        accumulator = self._accumulator()
        accumulator.add_flow(_flow(
            source_refs=[_source_ref("3.8", "ei-38")],
            concept_associations=[_FROM_38],
        ))
        flow = accumulator.merged_elementary[0]
        self.assertEqual(
            [(r["list_version"], r["source_flow_uuid"]) for r in flow.source_refs],
            [("3.12", "ei-312"), ("3.8", "ei-38")],
        )
        self.assertEqual(flow.concept_associations, [_FROM_312, _FROM_38])

    def test_re_adding_the_same_row_changes_nothing(self):
        accumulator = self._accumulator()
        before = orjson.dumps([f.to_dict() for f in accumulator.merged_elementary])
        accumulator.add_flow(replace(accumulator.merged_elementary[0]))
        self.assertEqual(
            orjson.dumps([f.to_dict() for f in accumulator.merged_elementary]), before
        )

    def test_the_id_is_recorded_as_added_either_way(self):
        """`sync_merge_results` reads this to find the rows the pass touched."""
        accumulator = self._accumulator()
        accumulator.preexisting_flow_ids = frozenset({_FLOW_ID})
        accumulator.add_flow(_flow(source_refs=[_source_ref("3.8", "ei-38")]))
        self.assertEqual(accumulator.added_flow_ids, {_FLOW_ID})


class ResyncSelectionAcrossVersionsTestCase(unittest.TestCase):
    """A flow an earlier version's pass created is not this pass's to create."""

    def _accumulator(self) -> MergeAccumulator:
        accumulator = MergeAccumulator()
        accumulator.merged_elementary = [_flow(
            # Written by the ecoinvent 3.12 pass, and the string says only
            # "ecoinvent" -- which is the whole defect.
            source="ecoinvent algorithm addition",
            source_refs=[_source_ref("3.12", "ei-312"), _source_ref("3.8", "ei-38")],
            concept_associations=[_FROM_312, _FROM_38],
        )]
        accumulator.preexisting_flow_ids = frozenset({_FLOW_ID})
        accumulator.algorithm_matches = [
            mock.Mock(spec=AlgorithmMatch, target_elementary_flow_id=_FLOW_ID)
        ]
        return accumulator

    def _run(self, accumulator: MergeAccumulator):
        from brightway_flows.merge.datastores import sync_merge_results

        indexes = mock.Mock()
        indexes.flow_object_label_by_id = {}
        with mock.patch(
            "brightway_flows.merge.datastores._sync_existing_flow_source_refs"
        ) as refs, mock.patch(
            "brightway_flows.merge.datastores._sync_existing_flow_concept_associations"
        ) as assocs, mock.patch(
            "brightway_flows.merge.datastores._sync_new_flow_objects_to_datastores"
        ), mock.patch(
            "brightway_flows.merge.datastores._sync_new_flows_to_datastores"
        ) as new_flows:
            sync_merge_results(
                new_flow_objects=[], indexes=indexes, accumulator=accumulator
            )
        return refs, assocs, new_flows

    def test_it_is_not_offered_to_the_insert_that_would_ignore_it(self):
        refs, assocs, new_flows = self._run(self._accumulator())
        self.assertEqual(new_flows.call_args.args[0], [])
        self.assertEqual(
            [f.elementary_flow_id for f in refs.call_args.args[0]], [_FLOW_ID]
        )
        self.assertEqual(
            [f.elementary_flow_id for f in assocs.call_args.args[0]], [_FLOW_ID]
        )

    def test_a_manual_addition_onto_it_is_re_synced_too(self):
        """A manual addition is in no match list; `added_flow_ids` is how it counts."""
        accumulator = self._accumulator()
        accumulator.algorithm_matches = []
        accumulator.added_flow_ids.add(_FLOW_ID)
        refs, _assocs, new_flows = self._run(accumulator)
        self.assertEqual(new_flows.call_args.args[0], [])
        self.assertEqual(
            [f.elementary_flow_id for f in refs.call_args.args[0]], [_FLOW_ID]
        )

    def test_a_flow_this_pass_created_still_goes_to_the_insert(self):
        accumulator = self._accumulator()
        accumulator.preexisting_flow_ids = frozenset()
        _refs, _assocs, new_flows = self._run(accumulator)
        self.assertEqual(
            [f.elementary_flow_id for f in new_flows.call_args.args[0]], [_FLOW_ID]
        )


class AssociationSyncTestCase(unittest.TestCase):
    """The association sync adds to both payload columns and removes from neither."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = Path(self.tmp.name) / "consensus-flows.sqlite3"
        for module in ("pipeline.sqlite", "merge.datastores"):
            patch = mock.patch(
                f"brightway_flows.{module}.CONSENSUS_DB_FILEPATH", self.db
            )
            patch.start()
            self.addCleanup(patch.stop)
        _write_consensus_sqlite(
            [Flow(
                uuid=_FLOW_ID, source="EF 3.1", unit="kg",
                context=_AIR, concept_associations=[_FROM_312],
            )],
            [],
            [],
            [ElementaryFlow(
                elementary_flow_id=_FLOW_ID, flow_object_id="fo-1",
                source="EF 3.1", context=_AIR, context_iri="",
                unit="kg", unit_iri="", lcia_methods=[], general_comment=None,
                source_refs=[], concept_associations=[_FROM_312],
            )],
        )

    def stored(self, column: str) -> list[dict]:
        conn = sqlite3.connect(self.db)
        try:
            blob = conn.execute(
                f"SELECT {column} FROM elementary_flows WHERE uuid = ?", (_FLOW_ID,)
            ).fetchone()[0]
        finally:
            conn.close()
        return orjson.loads(blob).get("concept_associations") or []

    def test_the_new_association_reaches_the_stored_record(self):
        """There is one record now (#255), so there is one place to check.

        The divergence #252 was about cannot happen when the merge's working
        set is projected from the same column the export reads.
        """
        _sync_existing_flow_concept_associations(
            [_flow(concept_associations=[_FROM_312, _FROM_38])]
        )
        self.assertEqual(self.stored("flow_json"), [_FROM_312, _FROM_38])

    def test_an_association_the_working_row_never_saw_is_not_dropped(self):
        """The 4,084 ecoinvent 3.12 correspondences the 3.8 pass deleted.

        The working row carries only what this pass added, which is what a row
        loaded from a column the previous pass did not update looks like.
        """
        _sync_existing_flow_concept_associations(
            [_flow(concept_associations=[_FROM_38])]
        )
        self.assertEqual(self.stored("flow_json"), [_FROM_312, _FROM_38])

    def test_running_it_twice_does_not_duplicate_an_association(self):
        flow = _flow(concept_associations=[_FROM_312, _FROM_38])
        _sync_existing_flow_concept_associations([flow])
        _sync_existing_flow_concept_associations([flow])
        self.assertEqual(self.stored("flow_json"), [_FROM_312, _FROM_38])

    def test_both_versions_reach_the_published_correspondences(self):
        """The symptom, stated where a reader will recognise it."""
        from brightway_flows.pipeline.correspondences import build_correspondences
        from brightway_flows.pipeline.sqlite import read_published_flow_payloads

        _sync_existing_flow_concept_associations(
            [_flow(concept_associations=[_FROM_38])]
        )
        _schemes, correspondences, _counts = build_correspondences(
            read_published_flow_payloads(self.db)
        )
        self.assertEqual(
            sorted(c.jsonld_id.rsplit("/", 1)[-1] for c in correspondences),
            ["ecoinvent-3.12", "ecoinvent-3.8"],
        )


if __name__ == "__main__":
    unittest.main()
