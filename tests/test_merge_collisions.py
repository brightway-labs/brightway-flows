"""The collision check asked of what the merge writes, not of what precedes it.

#60. `report_collisions` was called once, from the transform, immediately after
the duplicate deprecations. The merge then added flows and nothing looked again,
so on the 2026-08-12 build the queue described 116 groups and the published
database held 145 -- the 29 it never saw holding 190 flows the merge had minted
onto a substance, context and unit a flow already occupied, none of them
carrying a single characterisation factor.

What is pinned here:

- **The check reads records.** `find_collisions` reads every field by
  attribute, so handing it the working list as dicts reports a clean database
  however many collisions are in it.  The working list has been
  `ElementaryFlow` records since #93; `MergedFlow` narrows one to the six
  fields the check names.
- **Minted is read from the source label.** Not from the accumulator's
  `added_flow_ids`, which names what *this pass* added: a build merges several
  lists in sequence and the last pass has to be able to report the first's.
- **The counters and the queue are written where a reader finds them**, scoped
  so that merging a second list replaces the first list's rows instead of
  doubling them.
- **The report runs after the additions and the creations.** That is the whole
  of the defect: the check itself was right and ran in the wrong place.
"""

import inspect
import sqlite3
import tempfile
import unittest
from pathlib import Path

from brightway_flows.domain.context_registry import context_for_iri
from brightway_flows.domain.elementary_flow import ElementaryFlow
from brightway_flows.domain.lcia.records import StatedFactor, stated_category
from brightway_flows.merge.collisions import (
    MERGE_COLLISION_STAGE,
    MergedFlow,
    minted_flow_ids,
    report_merged_collisions,
)
from brightway_flows.merge.state import MergeAccumulator
from brightway_flows.pipeline.collisions import STAGE_MERGE, STAGE_TRANSFORM
from brightway_flows.pipeline.review_records import (
    PipelineRun,
    ReviewQueue,
    ReviewQueueItem,
    Severity,
)
from brightway_flows.pipeline.review_tables import (
    replace_queue_items,
    replace_stage_stats,
    write_review_tables,
)
from brightway_flows.domain.vocabulary import OWL_DEPRECATED
from brightway_flows.sources import base_source_label

#: A real context IRI; which one does not matter, that it is one does.
AIR = "https://vocab.brightway.one/flow-contexts/envi-air-unkn"

def record(
    elementary_flow_id: str,
    *,
    flow_object_id: str = "fo-herbicides",
    context_iri: str = AIR,
    unit: str = "kg",
    source: str | None = None,
    factors: int = 0,
    deprecated: bool = False,
    general_comment: str | None = None,
    concept_associations: list | None = None,
) -> ElementaryFlow:
    """One row of the working list, in the shape the accumulator holds."""
    return ElementaryFlow(
        elementary_flow_id=elementary_flow_id,
        flow_object_id=flow_object_id,
        source=base_source_label() if source is None else source,
        # Resolved from the IRI, so the record cannot say one context and its
        # `context_iri` another.
        context=context_for_iri(context_iri),
        context_iri=context_iri,
        unit=unit,
        unit_iri="",
        lcia_methods=[
            StatedFactor(
                category=stated_category(uuid=f"m{i}", name=f"m{i}"),
                flow_uuid=elementary_flow_id,
                amount=1.0,
            )
            for i in range(factors)
        ],
        general_comment=general_comment,
        concept_associations=concept_associations or [],
        owl_deprecated=True if deprecated else None,
    )


def accumulator_of(*rows: ElementaryFlow) -> MergeAccumulator:
    accumulator = MergeAccumulator()
    for row in rows:
        accumulator.merged_elementary.append(row)
    return accumulator


class ReadingTheWorkingListTestCase(unittest.TestCase):
    def test_a_row_becomes_the_fields_the_check_reads(self):
        flow = MergedFlow.from_record(record("a", factors=4))
        self.assertEqual(flow.elementary_flow_id, "a")
        self.assertEqual(flow.flow_object_id, "fo-herbicides")
        self.assertEqual(flow.context_iri, AIR)
        self.assertEqual(flow.unit, "kg")
        self.assertEqual(len(flow.lcia_methods), 4)

    def test_deprecation_reads_off_the_field_that_carries_it(self):
        """The record aliases `owl_deprecated` to the expanded IRI a stored row
        spells it with, so one read answers for both. Read under the wrong name,
        every resolved collision comes back as an outstanding one."""
        flow = MergedFlow.from_record(record("a", deprecated=True))
        self.assertTrue(flow.owl_deprecated)
        self.assertIs(
            record("a", deprecated=True).to_dict()[OWL_DEPRECATED], True
        )

    def test_a_row_the_record_cannot_represent_stops_at_the_read_boundary(self):
        """Not here. `_load_working_set` builds the records, so a stored row
        missing a field the record requires fails there, where a stored row that
        cannot be read is a fact worth stopping the build for -- rather than
        reaching this check as six defaulted fields."""
        with self.assertRaises(TypeError):
            ElementaryFlow.from_dict({"elementary_flow_id": "a"})


class WhatHoldsThemApartTestCase(unittest.TestCase):
    """The report asks deduplication which of *its* fields still differ (#58).

    It answers `[]` for a row it cannot read as a record, and `[]` is a legal
    answer — a group nothing holds apart is one that would collapse. So a
    `MergedFlow` that named its six fields and stopped would have reported every
    group in the published database that way, including the 116 the transform
    describes correctly, and nothing would have failed.
    """

    def test_a_merged_row_answers_the_question_the_transforms_rows_answer(self):
        _counts, items = report_merged_collisions(
            accumulator=accumulator_of(
                record("a", general_comment="from EF 3.1"), record("b")
            ),
            labels_by_object={},
        )
        self.assertEqual(items[0].payload["differing_fields"], ["general_comment"])

    def test_a_field_attached_after_deduplication_holds_nothing_apart(self):
        """Concept associations are attached after the transform has both
        deduplicated and reported, so no pass that could collapse a pair has
        ever seen one. By the time the merge reports, every flow carries its
        own — and counting them would name a field as holding all 145 groups
        apart that holds none of them apart."""
        _counts, items = report_merged_collisions(
            accumulator=accumulator_of(
                record("a", concept_associations=[{"@id": "ef:a"}]),
                record("b", concept_associations=[{"@id": "ef:b"}]),
            ),
            labels_by_object={},
        )
        self.assertEqual(items[0].payload["differing_fields"], [])

    def test_the_flow_holding_the_factors_is_the_one_that_would_be_kept(self):
        """Deduplication's own ranking, over rows the merge read rather than
        rows the transform built."""
        _counts, items = report_merged_collisions(
            accumulator=accumulator_of(
                record("zzz", factors=4),
                record("aaa", source="ecoinvent manual addition"),
            ),
            labels_by_object={},
        )
        self.assertEqual(items[0].payload["deduplication_would_keep"], "zzz")


class WhatCountsAsMintedTestCase(unittest.TestCase):
    def test_a_flow_the_base_list_published_is_not_minted(self):
        flows = [MergedFlow.from_record(record("ef"))]
        self.assertEqual(minted_flow_ids(flows), frozenset())

    def test_any_other_source_label_is(self):
        """A match leaves the label alone -- it becomes a source reference on
        the flow it landed on. So a label that is not the base list's is a flow
        an addition or a creation minted, in this pass or an earlier one."""
        flows = [
            MergedFlow.from_record(record("ef")),
            MergedFlow.from_record(record("m", source="ecoinvent manual addition")),
        ]
        self.assertEqual(minted_flow_ids(flows), frozenset({"m"}))


class ReportingTheMergedListTestCase(unittest.TestCase):
    def test_the_group_the_merge_produced_is_reported_and_attributed(self):
        """The shape of all 29: one EF flow holding the factors, and the merge's
        rows beside it under the same name, in the same place, holding none."""
        counts, items = report_merged_collisions(
            accumulator=accumulator_of(
                record("ef", factors=4),
                record("m-1", source="ecoinvent manual addition"),
                record("m-2", source="ecoinvent manual addition"),
            ),
            labels_by_object={"fo-herbicides": "Herbicides, Unspecified"},
        )
        self.assertEqual(counts["collision_groups"], 1)
        self.assertEqual(counts["collision_flows"], 3)
        self.assertEqual(counts["collision_groups_from_merge"], 1)
        self.assertEqual(counts["collision_flows_minted_by_merge"], 2)
        self.assertEqual(counts["collision_minted_flows_without_factors"], 2)
        self.assertEqual(items[0].payload["stage"], STAGE_MERGE)
        self.assertEqual(items[0].severity, Severity.REVIEW)
        self.assertIn("Herbicides, Unspecified", items[0].title)

    def test_a_group_the_transform_already_had_is_still_the_transforms(self):
        counts, items = report_merged_collisions(
            accumulator=accumulator_of(record("ef-1"), record("ef-2")),
            labels_by_object={},
        )
        self.assertEqual(counts["collision_groups"], 1)
        self.assertEqual(counts["collision_groups_from_merge"], 0)
        self.assertEqual(items[0].payload["stage"], STAGE_TRANSFORM)
        self.assertEqual(items[0].severity, Severity.INFO)

    def test_the_merge_reports_the_transforms_groups_too(self):
        """It replaces the queue rather than adding to it, so its report has to
        be the whole picture -- 145 groups, not the 29 the transform missed."""
        counts, items = report_merged_collisions(
            accumulator=accumulator_of(
                record("ef-1"),
                record("ef-2"),
                record("m", flow_object_id="fo-fungicides",
                        source="ecoinvent manual addition"),
                record("m-2", flow_object_id="fo-fungicides",
                        source="ecoinvent manual addition"),
            ),
            labels_by_object={},
        )
        self.assertEqual(counts["collision_groups"], 2)
        self.assertEqual(
            sorted(item.payload["stage"] for item in items),
            [STAGE_MERGE, STAGE_TRANSFORM],
        )

    def test_a_deprecated_flow_is_not_a_collision(self):
        """A deprecated flow is a collision already resolved; the merge reads
        the working list including those, and has to skip them as the transform
        does."""
        counts, _items = report_merged_collisions(
            accumulator=accumulator_of(
                record("ef"),
                record("gone", source="ecoinvent manual addition", deprecated=True),
            ),
            labels_by_object={},
        )
        self.assertEqual(counts["collision_groups"], 0)


class WritingItWhereAReaderLooksTestCase(unittest.TestCase):
    """The rows the merge writes into tables the transform wrote first."""

    def setUp(self):
        self.directory = Path(
            self.enterContext(tempfile.TemporaryDirectory())
        )
        self.db = self.directory / "consensus-flows.sqlite3"

    def write_review_tables(self, queue_items=()):
        write_review_tables(
            self.db,
            run=PipelineRun(run_id="run-1", timestamp="2026-08-13", schema_version=1),
            stats=[],
            changes=[],
            queue_items=list(queue_items),
            formula_mismatches=[],
            element_coverage=[],
            context_mappings=[],
        )

    def rows(self, sql, *params):
        connection = sqlite3.connect(self.db)
        try:
            return list(connection.execute(sql, params))
        finally:
            connection.close()

    def item(self, key: str) -> ReviewQueueItem:
        return ReviewQueueItem(
            queue_name=ReviewQueue.ELEMENTARY_FLOW_COLLISION,
            item_key=key,
            title=key,
            severity=Severity.REVIEW,
        )

    def test_the_stage_files_its_counts_beside_the_transforms(self):
        """Not over them: two numbers under two stage names is the comparison
        that was missing while only one of them existed."""
        self.write_review_tables()
        replace_stage_stats(
            self.db,
            stage="elementary_flow_collisions",
            counts={"collision_groups": 116},
        )
        replace_stage_stats(
            self.db, stage=MERGE_COLLISION_STAGE, counts={"collision_groups": 145}
        )
        self.assertEqual(
            self.rows(
                "SELECT stage, value FROM run_stats WHERE key = 'collision_groups' "
                "ORDER BY stage"
            ),
            [("elementary_flow_collisions", 116), (MERGE_COLLISION_STAGE, 145)],
        )

    def test_writing_twice_replaces_rather_than_doubles(self):
        """One build merges several source lists, each running this."""
        self.write_review_tables()
        for value in (100, 145):
            replace_stage_stats(
                self.db,
                stage=MERGE_COLLISION_STAGE,
                counts={"collision_groups": value},
            )
        self.assertEqual(
            self.rows("SELECT stage, key, value FROM run_stats"),
            [(MERGE_COLLISION_STAGE, "collision_groups", 145)],
        )

    def test_the_queue_is_replaced_and_other_queues_are_left_alone(self):
        self.write_review_tables([
            ReviewQueueItem(
                queue_name=ReviewQueue.EC_MALFORMED, item_key="ec-1", title="ec"
            ),
            self.item("fo-1|ctx|kg"),
        ])
        replace_queue_items(
            self.db,
            queue=ReviewQueue.ELEMENTARY_FLOW_COLLISION,
            items=[self.item("fo-1|ctx|kg"), self.item("fo-2|ctx|kg")],
        )
        self.assertEqual(
            self.rows(
                "SELECT queue_name, item_key FROM review_queue ORDER BY item_key"
            ),
            [
                ("ec-malformed", "ec-1"),
                ("elementary-flow-collision", "fo-1|ctx|kg"),
                ("elementary-flow-collision", "fo-2|ctx|kg"),
            ],
        )

    def test_an_item_of_another_queue_is_refused(self):
        """The delete is scoped to one queue name, so an item of another would
        be inserted beside rows this call did not clear and would double."""
        self.write_review_tables()
        with self.assertRaises(ValueError):
            replace_queue_items(
                self.db,
                queue=ReviewQueue.ELEMENTARY_FLOW_COLLISION,
                items=[
                    ReviewQueueItem(
                        queue_name=ReviewQueue.EC_MALFORMED, item_key="ec-1"
                    )
                ],
            )

    def test_a_database_with_no_review_tables_is_skipped_not_failed(self):
        """A fixture seeded without a transform run is what several tests hand
        the merge. The report was computed and logged either way."""
        sqlite3.connect(self.db).close()
        replace_stage_stats(
            self.db, stage=MERGE_COLLISION_STAGE, counts={"collision_groups": 1}
        )
        replace_queue_items(
            self.db,
            queue=ReviewQueue.ELEMENTARY_FLOW_COLLISION,
            items=[self.item("fo-1|ctx|kg")],
        )
        self.assertEqual(
            self.rows("SELECT name FROM sqlite_master WHERE type = 'table'"), []
        )


class WhereItRunsTestCase(unittest.TestCase):
    """The defect was the ordering, so the ordering is what is pinned."""

    def test_the_report_runs_after_everything_the_merge_adds(self):
        from brightway_flows.merge.pipeline import merge_source_list

        source = inspect.getsource(merge_source_list)
        report = source.index("report_merged_collisions")
        for step in (
            "apply_manual_additions",
            "create_flows_for_unmatched_rows",
            "sync_merge_results",
        ):
            with self.subTest(step):
                self.assertLess(source.index(step), report)

    def test_the_merge_writes_both_the_counts_and_the_queue(self):
        from brightway_flows.merge.pipeline import merge_source_list

        source = inspect.getsource(merge_source_list)
        self.assertIn("replace_stage_stats", source)
        self.assertIn("replace_queue_items", source)


if __name__ == "__main__":
    unittest.main()
