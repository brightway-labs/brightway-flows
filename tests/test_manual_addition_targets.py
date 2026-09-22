"""A grouping names a flow object that exists, or the row is not placed (#228).

`apply_manual_additions` looked its target flow object up only to copy fields
off it, under `if fo:`, and wrote the elementary flow whether or not it found
one.  A row grouped onto a missing object therefore became a flow pointing at
nothing: no label, no properties, no `@type`, unreachable from the object side
and invisible to the deduplication invariant, which is stated over objects that
exist.  A bounded 400-flow run produced 189 of them.

Two rules are pinned here, and the pipeline-level check that backs them up:

- an unresolvable target on a complete consensus list is a stale curated
  decision, and it raises;
- on a bounded slice it is the bound, so the rows stay unmatched and the run
  goes on.
"""

from __future__ import annotations

import dataclasses
import json
import tempfile
import unittest
from pathlib import Path

from brightway_flows.merge.contexts import ContextExpectations
from brightway_flows.domain.context_registry import context_for_iri
from brightway_flows.domain.elementary_flow import ElementaryFlow
from brightway_flows.domain.flow import Flow
from brightway_flows.merge.additions import apply_manual_additions
from brightway_flows.domain.flow_object import FlowObject
from brightway_flows.merge.pipeline import _refuse_dangling_flow_objects
from brightway_flows.merge.report import UnmatchedReason, UnmatchedRow
from brightway_flows.merge.state import MergeAccumulator, MergeIndexes
from brightway_flows.sources import resolve_source_list
from brightway_flows.transformers.unit_normalization import build_units_index

AIR = "https://vocab.brightway.one/flow-contexts/envi-air-unkn"
CONTEXTS = ContextExpectations(
    _by_source_context={("air",): AIR}, _source_label="test"
)
CONTEXT_STRINGS = {AIR: ["Environmental", "Air"]}

GROUP_ID = "fo-601ee65225568e0a"
MISSING_ID = "fo-deadbeefdeadbeef"


def _pointing_at(flow_object_id: str) -> ElementaryFlow:
    """A merged flow naming *flow_object_id* as its substance, and nothing else.

    The dangling check reads that one pointer; the rest is what any flow needs
    to be a record.
    """
    return ElementaryFlow(
        elementary_flow_id="ef-1",
        flow_object_id=flow_object_id,
        source="EF 3.1",
        context=context_for_iri(AIR),
        context_iri=AIR,
        unit="kg",
        unit_iri="",
        lcia_methods=[],
        general_comment=None,
    )


def _groupings_file(flow_object_id: str) -> Path:
    payload = {
        "schema_version": 2,
        "source_file": "test-groupings.json",
        "mappings": [
            {
                "source_name": "Testicide A",
                "flow_object_id": flow_object_id,
                "flow_object_label": "Herbicides, Unspecified",
                "notes": "A test herbicide.",
                "source_uuids": ["u-1"],
            }
        ],
    }
    handle = tempfile.NamedTemporaryFile(
        suffix=".json", mode="w", delete=False, prefix="ecoinvent-"
    )
    with handle as f:
        json.dump(payload, f)
    return Path(handle.name)


def _source_flow(uuid: str, name: str) -> Flow:
    return Flow.from_dict({
        "uuid": uuid,
        "identifier": uuid,
        "source": "ecoinvent-3.12",
        "unit": "kg",
        "cas_numbers": [],
        "ec_numbers": [],
        "prefLabel": [{"@value": name, "@language": "en"}],
        "altLabel": [],
    })


def _unmatched(uuid: str, name: str) -> UnmatchedRow:
    return UnmatchedRow(
        source_uuid=uuid,
        source_name=name,
        source_context=["air"],
        source_unit="kg",
        source_cas="",
        source_ec="",
        reason=UnmatchedReason.NO_FLOW_OBJECT_CANDIDATE,
        matching_method="algorithm",
    )


class ManualAdditionTargetTestCase(unittest.TestCase):
    def setUp(self):
        self.paths: list[Path] = []
        self.addCleanup(self._remove_paths)
        self.units_index = build_units_index()
        self.accumulator = MergeAccumulator()

    def _remove_paths(self):
        for path in self.paths:
            path.unlink(missing_ok=True)

    def _indexes(
        self, *, target_id: str, flow_objects: dict[str, FlowObject]
    ) -> MergeIndexes:
        path = _groupings_file(target_id)
        self.paths.append(path)
        source = dataclasses.replace(
            resolve_source_list("ecoinvent-3.12"), manual_additions_path=path
        )
        return MergeIndexes(
            flow_objects_by_id=flow_objects,
            flow_object_label_by_id={
                fo_id: "Herbicides, Unspecified" for fo_id in flow_objects
            },
            cas_index={},
            ec_index={},
            label_index={},
            pref_label_index={},
            qualifier_index={},
            flow_objects_with_cas=set(),
            context_expectations=CONTEXTS,
            consensus_context_strings=CONTEXT_STRINGS,
            prepared_context_decisions={},
            mapping_file=None,
            source=source,
        )

    def apply(self, *, target_id: str, flow_objects: dict, consensus_is_partial: bool):
        rows = [_unmatched("u-1", "Testicide A")]
        return apply_manual_additions(
            unmatched=rows,
            source_flow_by_uuid={"u-1": _source_flow("u-1", "Testicide A")},
            external_names_by_cas={},
            units_index=self.units_index,
            indexes=self._indexes(target_id=target_id, flow_objects=flow_objects),
            accumulator=self.accumulator,
            consensus_is_partial=consensus_is_partial,
        )

    #: The grouping's target, as the merge holds a flow object: a database
    #: payload, not a record.
    GROUP_OBJECT = FlowObject(
        flow_object_id=GROUP_ID,
        prefLabel=[{"@value": "Herbicides, Unspecified", "@language": "en"}],
        altLabel=[],
        properties={},
        references=[],
        created_from={},
        classifications={},
    )

    def test_a_row_grouped_onto_an_existing_object_is_placed(self):
        placed = self.apply(
            target_id=GROUP_ID,
            flow_objects={GROUP_ID: self.GROUP_OBJECT},
            consensus_is_partial=False,
        )

        self.assertEqual([row.source_uuid for row in placed], ["u-1"])
        self.assertEqual(len(self.accumulator.merged_elementary), 1)
        flow = self.accumulator.merged_elementary[0]
        self.assertEqual(flow.flow_object_id, GROUP_ID)
        # Placed means enriched: the fields that only exist on the object.
        # They live in the record's passthrough bag, because `ElementaryFlow`
        # declares none of them -- see `_inherited_flow_object_fields`.
        self.assertEqual(flow.extra["name"], "Herbicides, Unspecified")

    def test_a_missing_target_on_a_complete_list_raises(self):
        with self.assertRaises(ValueError) as caught:
            self.apply(
                target_id=MISSING_ID,
                flow_objects={GROUP_ID: self.GROUP_OBJECT},
                consensus_is_partial=False,
            )

        self.assertIn(MISSING_ID, str(caught.exception))
        self.assertEqual(self.accumulator.merged_elementary, [])

    def test_a_missing_target_on_a_bounded_slice_leaves_the_row_unmatched(self):
        placed = self.apply(
            target_id=MISSING_ID,
            flow_objects={GROUP_ID: self.GROUP_OBJECT},
            consensus_is_partial=True,
        )

        # Nothing placed, nothing written: the caller drops only what comes
        # back, so the row stays in the unmatched queue and reaches the
        # creation step like any other row that matched nothing.
        self.assertEqual(placed, [])
        self.assertEqual(self.accumulator.merged_elementary, [])


class RefuseDanglingFlowObjectsTestCase(unittest.TestCase):
    """The invariant behind both rules, checked over the whole merged list."""

    def test_a_flow_naming_a_known_object_passes(self):
        _refuse_dangling_flow_objects([_pointing_at(GROUP_ID)], {GROUP_ID})

    def test_a_flow_naming_an_unknown_object_raises(self):
        with self.assertRaises(ValueError) as caught:
            _refuse_dangling_flow_objects(
                [_pointing_at(GROUP_ID), _pointing_at(MISSING_ID)],
                {GROUP_ID},
            )

        self.assertIn(MISSING_ID, str(caught.exception))
        self.assertNotIn(GROUP_ID, str(caught.exception))

    def test_a_flow_naming_no_object_raises(self):
        """An empty pointer resolves to nothing exactly as a wrong one does."""
        with self.assertRaises(ValueError):
            _refuse_dangling_flow_objects([_pointing_at("")], {GROUP_ID})


if __name__ == "__main__":
    unittest.main()
