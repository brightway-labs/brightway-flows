"""The review tables have to hold what the JSON files held.

Phase 0 of `plans/webapp-consolidation.md` moves six side-car files into
`consensus-flows.sqlite3`.  The claim being made is narrow and checkable: the
tables either carry the data the files carried, or they do not.

Three things are pinned here, because each is a way the move could go wrong
without any test noticing:

- **Round trip.** Every record written comes back equal.  A column that silently
  drops a field would otherwise only show up on a page nobody reads.
- **Both access paths on `changelog`.** The reason it replaces
  `consensus_changes` is that it answers "what happened to this substance" as
  well as "what happened to this flow".
- **Derivation, not duplication.** `provenance_activities` stores a version
  number and mints its IRIs; the values live once, on the change with the same
  index.
"""

import sqlite3
import tempfile
import unittest
from pathlib import Path

import orjson

from brightway_flows.domain.vocabulary import MintedNamespace
from brightway_flows.pipeline.provenance import build_provenance_activities
from brightway_flows.pipeline.review_records import (
    EF_PREFIX,
    PROV_CONTEXT,
    ChangeEvent,
    RunStat,
    ContextDefaultMapping,
    ElementCoverage,
    ElementStatus,
    FormulaMismatch,
    PipelineRun,
    ReviewQueue,
    ReviewQueueItem,
    ReviewQueueProvider,
    Severity,
)
from brightway_flows.pipeline.review_tables import (
    REVIEW_SCHEMA_VERSION,
    build_element_coverage,
    collect_review_queue_items,
    load_context_default_mappings,
    number_change_events,
    read_changelog,
    read_pipeline_run,
    read_provenance_activities,
    read_review_queue,
    read_run_stats,
    write_review_tables,
)
from brightway_flows.transformers.consensus_match import (
    CasVoteConflict,
    ConsensusDecision,
    ConsensusMatchReviewItem,
)


def _run(**kwargs) -> PipelineRun:
    return PipelineRun(
        run_id="run-1",
        timestamp="2026-08-06T00:00:00+00:00",
        schema_version=REVIEW_SCHEMA_VERSION,
        **kwargs,
    )


def _change(uuid, field, old, new, transformer, **kwargs) -> ChangeEvent:
    return ChangeEvent(
        uuid=uuid, field_name=field, old_value=old, new_value=new,
        transformer=transformer, **kwargs,
    )


class WriteAndReadTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = Path(self._tmp.name) / "consensus-flows.sqlite3"

    def _write(self, **kwargs):
        defaults = dict(
            run=_run(), stats=[], changes=[], queue_items=[],
            formula_mismatches=[], element_coverage=[], context_mappings=[],
        )
        defaults.update(kwargs)
        write_review_tables(self.path, **defaults)

    def _rows(self, table):
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        try:
            return [dict(row) for row in connection.execute(f"SELECT * FROM {table}")]
        finally:
            connection.close()

    def test_the_run_header_round_trips(self):
        """`transform-log.json` carried this above its changes; nothing else does."""
        self._write(run=_run(
            dry_run=True, max_flows=400, input_files=["a.json", "b.json"],
            transformer_names=["first", "second"], flow_count=400, change_count=3,
        ))
        run = read_pipeline_run(self.path)
        self.assertEqual(run.run_id, "run-1")
        self.assertTrue(run.dry_run)
        self.assertEqual(run.max_flows, 400)
        self.assertEqual(run.input_files, ["a.json", "b.json"])
        self.assertEqual(run.transformer_names, ["first", "second"])
        self.assertEqual(run.flow_count, 400)
        self.assertEqual(run.change_count, 3)

    def test_a_database_with_no_review_tables_has_no_run(self):
        """A stale database must answer, not raise: the app shows an empty state."""
        sqlite3.connect(self.path).close()
        self.assertIsNone(read_pipeline_run(self.path))

    def test_a_stage_tally_round_trips(self):
        """#232: every producer already returned a `Counter`; they were logged
        and dropped, so a regression in any of them was invisible between
        runs."""
        self._write(stats=[
            RunStat(stage="assign_semantic_types", key="typed_from_formula",
                    value=386),
            RunStat(stage="assign_semantic_types", key="untyped_no_structure",
                    value=1),
            RunStat(stage="build_correspondences", key="skipped_unknown_scheme",
                    value=0),
        ])
        rows = read_run_stats(self.path)
        self.assertEqual(
            [(row.stage, row.key, row.value) for row in rows],
            [
                ("assign_semantic_types", "typed_from_formula", 386),
                ("assign_semantic_types", "untyped_no_structure", 1),
                ("build_correspondences", "skipped_unknown_scheme", 0),
            ],
        )

    def test_a_zero_is_stored_rather_than_omitted(self):
        """A zero is a finding: "0 skipped" says the check ran and found none.

        The writer stores what it is given. Whether a *producer* emits the zero
        is the producer's business, and a `Counter` has no key for a case it
        never saw -- so an absent row means "this stage did not count that",
        which is not the same as zero. See `RunStat`.
        """
        self._write(stats=[
            RunStat(stage="build_correspondences", key="skipped_unknown_scheme",
                    value=0),
        ])
        [row] = read_run_stats(self.path)
        self.assertEqual(row.value, 0)

    def test_one_stage_cannot_report_a_key_twice(self):
        """The key is `(stage, key)`, so a producer emitting a duplicate is an
        error rather than a silently doubled or halved number."""
        with self.assertRaises(sqlite3.IntegrityError):
            self._write(stats=[
                RunStat(stage="resolve_flow_layers", key="flow_objects", value=1),
                RunStat(stage="resolve_flow_layers", key="flow_objects", value=2),
            ])

    def test_a_database_without_the_table_has_no_tallies(self):
        sqlite3.connect(self.path).close()
        self.assertEqual(read_run_stats(self.path), [])

    def test_a_change_round_trips_including_structured_values(self):
        """Old and new values are arbitrary JSON -- a label list, a context dict."""
        changes = number_change_events(
            [_change("u-1", "prefLabel", [{"@value": "Old"}], [{"@value": "New"}],
                     "consensus_match", flow_name="Old", comment="why")],
            flow_object_id_by_uuid={"u-1": "fo-1"},
        )
        self._write(changes=changes)
        [read] = read_changelog(self.path)
        self.assertEqual(read, changes[0])

    def test_the_change_log_is_reachable_by_flow_and_by_substance(self):
        """The reason `changelog` replaces `consensus_changes`: two access paths,
        neither needing a join."""
        changes = number_change_events(
            [
                _change("u-1", "unit", "kg", "m3", "unit_normalization"),
                _change("u-2", "unit", "kg", "m3", "unit_normalization"),
            ],
            flow_object_id_by_uuid={"u-1": "fo-1", "u-2": "fo-1"},
        )
        self._write(changes=changes)
        self.assertEqual([c.uuid for c in read_changelog(self.path, uuid="u-2")], ["u-2"])
        self.assertEqual(
            [c.uuid for c in read_changelog(self.path, flow_object_id="fo-1")],
            ["u-1", "u-2"],
        )

    def test_a_flow_with_no_substance_still_gets_a_row(self):
        """Layering does not resolve every flow to a flow object, and a change
        that vanished from the log because of that would be a change the run
        made and cannot account for."""
        changes = number_change_events(
            [_change("u-1", "unit", "kg", "m3", "unit_normalization")],
            flow_object_id_by_uuid={},
        )
        self._write(changes=changes)
        [read] = read_changelog(self.path)
        self.assertEqual(read.flow_object_id, "")
        self.assertEqual(read.change_index, 1)

    def test_a_queue_item_round_trips(self):
        item = ReviewQueueItem(
            queue_name=ReviewQueue.CAS_AMBIGUOUS,
            item_key="u-1",
            title="Ammonium chloride",
            severity=Severity.BLOCKING,
            uuid="u-1",
            flow_object_id="fo-1",
            cas="12125-02-9",
            item_index=1,
            payload={"possible_corrected_cas_values": ["12125-02-9"]},
        )
        self._write(queue_items=[item])
        self.assertEqual(read_review_queue(self.path), [item])

    def test_queues_are_read_one_at_a_time(self):
        """Six queues share one table; a page asks for one of them."""
        self._write(queue_items=[
            ReviewQueueItem(queue_name=ReviewQueue.EC_MALFORMED, item_key="a"),
            ReviewQueueItem(queue_name=ReviewQueue.CAS_AMBIGUOUS, item_key="b"),
        ])
        read = read_review_queue(self.path, ReviewQueue.EC_MALFORMED)
        self.assertEqual([item.item_key for item in read], ["a"])

    def test_two_items_cannot_share_a_key_within_a_queue(self):
        """The key is what a stored ruling would hang off, so it has to be one."""
        with self.assertRaises(sqlite3.IntegrityError):
            self._write(queue_items=[
                ReviewQueueItem(queue_name=ReviewQueue.EC_MALFORMED, item_key="a"),
                ReviewQueueItem(queue_name=ReviewQueue.EC_MALFORMED, item_key="a"),
            ])

    def test_a_formula_mismatch_round_trips(self):
        mismatch = FormulaMismatch(
            flow_object_id="fo-1",
            chebi_id="http://purl.obolibrary.org/obo/CHEBI_1234",
            similarity_score=0.5,
            threshold=0.55,
            pref_label="Lithium",
            flow_formula="Li",
            chebi_label="lithium hydride",
            chebi_formula="HLi",
            chebi_cas_numbers=["7580-67-8"],
        )
        self._write(formula_mismatches=[mismatch])
        [row] = self._rows("formula_mismatches")
        self.assertEqual(row["flow_object_id"], "fo-1")
        self.assertEqual(row["similarity_score"], 0.5)
        self.assertEqual(row["threshold"], 0.55)
        self.assertEqual(row["chebi_cas_numbers_json"], '["7580-67-8"]')

    def test_element_coverage_keeps_the_covered_elements_too(self):
        """"118 of 118 covered" is only sayable if the covered ones are rows."""
        self._write(element_coverage=[
            ElementCoverage(atomic_number=1, symbol="H", name="Hydrogen",
                            status=ElementStatus.LINKED, flow_object_id="fo-h"),
            ElementCoverage(atomic_number=118, symbol="Og", name="Oganesson"),
        ])
        rows = {row["atomic_number"]: row for row in self._rows("element_coverage")}
        self.assertEqual(rows[1]["status"], "linked")
        self.assertEqual(rows[118]["status"], "missing-flow-object")

    def test_a_context_mapping_round_trips(self):
        self._write(context_mappings=[ContextDefaultMapping(
            source="ecoinvent-3.12",
            source_context=["air", "low population density, long-term"],
            context_iri="https://vocab.brightway.one/flow-contexts/envi-air",
            context_display="Environment → Air",
            comment="Temporal differentiation is done by LCIA.",
        )])
        [row] = self._rows("context_default_mappings")
        self.assertEqual(row["source"], "ecoinvent-3.12")
        self.assertEqual(
            row["source_context_json"],
            '["air","low population density, long-term"]',
        )

    def test_rewriting_replaces_rather_than_appends(self):
        """The database is written fresh per run; two runs' rows in one table
        would be two runs claiming to be the state of the world."""
        self._write(changes=number_change_events(
            [_change("u-1", "unit", "kg", "m3", "first")], flow_object_id_by_uuid={},
        ))
        self._write(changes=number_change_events(
            [_change("u-2", "unit", "kg", "m3", "second")], flow_object_id_by_uuid={},
        ))
        self.assertEqual([c.uuid for c in read_changelog(self.path)], ["u-2"])
        self.assertEqual(len(self._rows("pipeline_runs")), 1)


class ProvenanceActivityTestCase(unittest.TestCase):
    """The PROV trail is the graph structure; the values stay on the change."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = Path(self._tmp.name) / "consensus-flows.sqlite3"

    def test_each_activity_consumes_what_the_previous_one_produced(self):
        changes = number_change_events(
            [
                _change("u-1", "unit", "kg", "m3", "first"),
                _change("u-2", "unit", "kg", "L", "first"),
                _change("u-1", "unit", "m3", "kBq", "second"),
            ],
            flow_object_id_by_uuid={},
        )
        activities = build_provenance_activities(changes)
        by_index = {a.change_index: a for a in activities}
        self.assertEqual(by_index[1].entity_version, 1)
        self.assertEqual(by_index[2].entity_version, 1)  # a different flow
        self.assertEqual(by_index[3].entity_version, 2)
        self.assertEqual(by_index[3].used_entity_id, by_index[1].generated_entity_id)

    def test_the_first_change_to_a_flow_consumes_the_loaded_version(self):
        [activity] = build_provenance_activities(number_change_events(
            [_change("u-1", "unit", "kg", "m3", "first")], flow_object_id_by_uuid={},
        ))
        self.assertEqual(activity.used_entity_id, "ef:flow/u-1/v0")
        self.assertEqual(activity.generated_entity_id, "ef:flow/u-1/v1")
        self.assertEqual(activity.agent_id, "ef:agent/first")
        self.assertEqual(activity.activity_id("run-1"), "ef:activity/change/run-1/1")

    def test_every_minted_identifier_resolves_through_the_prov_context(self):
        """#233: `ef:` was a prefix that belonged to nobody.

        The identifiers above are CURIEs, and a CURIE whose prefix is undeclared
        expands to nothing -- which is what `ef:runId` and `ef:flowUuid` did in
        the inputs app before #229. `PROV_CONTEXT` is the declaration, and it now
        reads its namespaces from the registry, so this checks the two halves
        still meet.
        """
        [activity] = build_provenance_activities(number_change_events(
            [_change("u-1", "unit", "kg", "m3", "first")], flow_object_id_by_uuid={},
        ))
        minted = [
            activity.used_entity_id,
            activity.generated_entity_id,
            activity.agent_id,
            activity.activity_id("run-1"),
        ]
        for identifier in minted:
            prefix, _, local = identifier.partition(":")
            with self.subTest(identifier=identifier):
                self.assertIn(prefix, PROV_CONTEXT)
                self.assertTrue(local, f"{identifier} has no local name")
        self.assertEqual(
            PROV_CONTEXT[EF_PREFIX], MintedNamespace.REVIEW_PROVENANCE.value,
        )

    def test_an_activity_shares_its_key_with_its_change(self):
        """Which is what lets the values be stored once rather than twice."""
        changes = number_change_events(
            [_change("u-1", "unit", "kg", "m3", "first", comment="why")],
            flow_object_id_by_uuid={},
        )
        write_review_tables(
            self.path, run=_run(), stats=[], changes=changes,
            queue_items=[], formula_mismatches=[], element_coverage=[],
            context_mappings=[],
        )
        [activity] = read_provenance_activities(self.path, uuid="u-1")
        [change] = read_changelog(self.path)
        self.assertEqual(activity.change_index, change.change_index)

        connection = sqlite3.connect(self.path)
        try:
            columns = {
                row[1] for row in connection.execute(
                    "PRAGMA table_info(provenance_activities)"
                )
            }
        finally:
            connection.close()
        self.assertNotIn("old_value_json", columns)
        self.assertNotIn("new_value_json", columns)
        self.assertNotIn("comment", columns)


class BuilderTestCase(unittest.TestCase):
    def test_an_element_with_no_flow_object_is_missing(self):
        coverage = {
            row.atomic_number: row for row in build_element_coverage([])
        }
        # Only meaningful when the PubChem cache is present; when it is not the
        # builder returns nothing rather than claiming full coverage.
        for row in coverage.values():
            self.assertIs(row.status, ElementStatus.MISSING)
            self.assertFalse(row.is_covered)

    def test_an_element_linked_back_to_ef31_is_covered(self):
        flow_objects = [{
            "flow_object_id": "fo-h",
            "properties": {
                "element": {"atomic_number": 1},
                "ef31_references": {"elementary_flow_ids": ["u-1"]},
            },
        }]
        coverage = {row.atomic_number: row for row in build_element_coverage(flow_objects)}
        if 1 not in coverage:
            self.skipTest("PubChem element cache not present in this data directory")
        self.assertIs(coverage[1].status, ElementStatus.LINKED)
        self.assertEqual(coverage[1].flow_object_id, "fo-h")

    def test_an_element_with_a_flow_object_but_no_ef31_reference_is_unlinked(self):
        flow_objects = [{
            "flow_object_id": "fo-h",
            "properties": {"element": {"atomic_number": 1}},
        }]
        coverage = {row.atomic_number: row for row in build_element_coverage(flow_objects)}
        if 1 not in coverage:
            self.skipTest("PubChem element cache not present in this data directory")
        self.assertIs(coverage[1].status, ElementStatus.NOT_LINKED)

    def test_the_context_rules_come_from_the_package_data_file(self):
        """The same file and key the transformer reads, so the page shows what
        the run applied."""
        mappings = load_context_default_mappings()
        self.assertTrue(mappings)
        for mapping in mappings:
            self.assertTrue(mapping.source)
            self.assertTrue(mapping.context_iri)
            self.assertTrue(mapping.source_context)


class QueuePayloadDeterminismTestCase(unittest.TestCase):
    """A queue payload has to serialise the same way twice.

    The vote tallies behind a consensus decision are built by iterating sets, so
    their key order varies between processes.  Two runs over identical inputs
    produced payloads equal as data and different as text -- invisible while
    this only reached a review file written behind a flag, and reported by
    `tools/verify_run.py` on every run once it became a table.
    """

    def _item(self, votes, conflicts, cas_sources):
        return ConsensusMatchReviewItem(
            uuid="fo-1",
            flow_name="Ammonium chloride",
            decision=ConsensusDecision.NO_CONSENSUS_CAS,
            relationship_class="unresolved",
            source_votes=votes,
            conflicts=conflicts,
            group_cas_sources=cas_sources,
        )

    def test_the_same_content_in_a_different_order_serialises_the_same(self):
        first = self._item(
            {"12125-02-9": ["chebi"], "7440-38-2": ["pubchem"]},
            [CasVoteConflict("7440-38-2", ["pubchem"]),
             CasVoteConflict("12125-02-9", ["chebi"])],
            {"12125-02-9": ["chebi"], "7440-38-2": ["pubchem"]},
        )
        second = self._item(
            {"7440-38-2": ["pubchem"], "12125-02-9": ["chebi"]},
            [CasVoteConflict("12125-02-9", ["chebi"]),
             CasVoteConflict("7440-38-2", ["pubchem"])],
            {"7440-38-2": ["pubchem"], "12125-02-9": ["chebi"]},
        )
        self.assertEqual(orjson.dumps(first.to_dict()), orjson.dumps(second.to_dict()))

    def test_losing_candidates_come_out_sorted(self):
        item = self._item(
            {},
            [CasVoteConflict("7440-38-2", ["pubchem"]),
             CasVoteConflict("12125-02-9", ["chebi"])],
            {},
        )
        self.assertEqual(
            [c["candidate"] for c in item.to_dict()["conflicts"]],
            ["12125-02-9", "7440-38-2"],
        )


class _QueueProvider:
    """A transformer that only implements the queue protocol."""

    name = "stub"

    def __init__(self, items):
        self._items = items

    def review_queue_items(self):
        return list(self._items)


class _Plain:
    """A transformer with no queue.  Most of them."""

    name = "plain"


class CollectQueueItemsTestCase(unittest.TestCase):
    def test_a_transformer_without_a_queue_is_skipped(self):
        self.assertEqual(collect_review_queue_items([_Plain()]), [])

    def test_a_provider_is_recognised_by_its_method_not_its_type(self):
        """Which is what stops a new queue needing a new branch in the CLI."""
        self.assertIsInstance(_QueueProvider([]), ReviewQueueProvider)
        self.assertNotIsInstance(_Plain(), ReviewQueueProvider)

    def test_items_are_numbered_within_their_queue(self):
        items = collect_review_queue_items([
            _QueueProvider([
                ReviewQueueItem(queue_name=ReviewQueue.EC_MALFORMED, item_key="a"),
                ReviewQueueItem(queue_name=ReviewQueue.CAS_AMBIGUOUS, item_key="b"),
                ReviewQueueItem(queue_name=ReviewQueue.EC_MALFORMED, item_key="c"),
            ]),
        ])
        self.assertEqual(
            [(str(i.queue_name), i.item_key, i.item_index) for i in items],
            [
                ("ec-malformed", "a", 1),
                ("cas-ambiguous", "b", 1),
                ("ec-malformed", "c", 2),
            ],
        )


if __name__ == "__main__":
    unittest.main()
