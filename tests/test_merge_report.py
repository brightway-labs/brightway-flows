"""The merge report is built from records, and says so.

`MergeAccumulator` annotated its three row lists as `list[dict[str, Any]]`
while every append site built a record.  A wrong annotation is not merely
untidy here: `MergeReport.to_dict` carried a `hasattr(row, "to_dict")` fallback
because of it, so a dict that reached the report would have been serialised
unchanged -- with whatever keys it happened to have -- rather than rejected.

These tests pin the invariant the fallback was hiding.
"""

import unittest
from dataclasses import fields

from brightway_flows.merge.contexts import ContextExpectations
from brightway_flows.merge.report import (
    AlgorithmMatch,
    MergeReport,
    PreparedMatch,
    UnmatchedReason,
    UnmatchedRow,
)
from brightway_flows.merge.rows import apply_prepared_decision
from brightway_flows.sources import resolve_source_list
from brightway_flows.merge.state import (
    MergeAccumulator,
    MergeIndexes,
    SourceRow,
)


def _unmatched(uuid="u-1", reason=UnmatchedReason.NO_FLOW_OBJECT_CANDIDATE):
    return UnmatchedRow(
        source_uuid=uuid,
        source_name="Carbon dioxide",
        source_context=["air"],
        source_unit="kg",
        source_cas="124-38-9",
        source_ec="",
        reason=reason,
    )


def _report(**kwargs):
    return MergeReport(
        schema_version=1,
        generated_at="2026-01-01T00:00:00Z",
        source_list="ecoinvent",
        source_version="3.12",
        input_paths={},
        stats={},
        **kwargs,
    )


class AccumulatorHoldsRecordsTestCase(unittest.TestCase):
    def test_row_lists_are_annotated_as_records(self):
        annotations = {f.name: f.type for f in fields(MergeAccumulator)}
        self.assertEqual(annotations["prepared_matches"], "list[PreparedMatch]")
        self.assertEqual(annotations["algorithm_matches"], "list[AlgorithmMatch]")
        self.assertEqual(annotations["unmatched"], "list[UnmatchedRow]")

    def test_a_fresh_accumulator_has_empty_row_lists(self):
        accumulator = MergeAccumulator()
        for name in ("prepared_matches", "algorithm_matches", "unmatched"):
            self.assertEqual(getattr(accumulator, name), [])


class ReportSerialisationTestCase(unittest.TestCase):
    def test_records_serialise_through_their_own_type(self):
        report = _report(unmatched=[_unmatched()])
        row = report.to_dict()["unmatched"][0]
        self.assertEqual(row["source_uuid"], "u-1")
        self.assertEqual(row["reason"], "no-flow-object-candidate")
        # Optional fields stay absent rather than becoming null.
        self.assertNotIn("target_elementary_flow_id", row)

    def test_a_dict_row_raises_rather_than_passing_through(self):
        """The case the removed `hasattr` fallback would have serialised.

        A stray dict is a bug in whatever built it; emitting it unchanged puts
        arbitrary keys into the report and defers the problem to a reader.
        """
        report = _report(unmatched=[{"source_uuid": "u-1", "typo_key": 1}])
        with self.assertRaises(AttributeError):
            report.to_dict()

    def test_every_row_list_is_converted(self):
        """A row list left out of ROW_KEYS would serialise as record objects."""
        declared = {f.name for f in fields(MergeReport)}
        self.assertEqual(set(MergeReport.ROW_KEYS) - declared, set())
        non_rows = {"schema_version", "generated_at", "source_list",
                    "source_version", "input_paths", "stats"}
        self.assertEqual(declared - non_rows, set(MergeReport.ROW_KEYS))

    def test_row_order_within_a_list_is_preserved(self):
        report = _report(unmatched=[_unmatched("u-1"), _unmatched("u-2")])
        self.assertEqual(
            [row["source_uuid"] for row in report.to_dict()["unmatched"]],
            ["u-1", "u-2"],
        )

    def test_report_keys_follow_declaration_order(self):
        """`to_dict()` output is the artifact; its key order must not drift."""
        report = _report()
        self.assertEqual(
            list(report.to_dict()),
            [f.name for f in fields(MergeReport)],
        )


class RowTypesTestCase(unittest.TestCase):
    def test_each_row_type_round_trips(self):
        rows = [
            _unmatched(),
            PreparedMatch(
                source_uuid="u-1", source_name="n", source_context=[],
                source_context_iri="", source_unit="kg",
                source_cas="", target_elementary_flow_id="ef-1",
                prepared_target_elementary_flow_id="ef-1", target_flow_object_id="fo-1",
                target_name="n", target_context=[], target_unit="kg",
                prepared_target_resolution="direct", prepared_target_trace=[],
                prepared_context_decision="", provenance={},
            ),
            AlgorithmMatch(
                source_uuid="u-1", source_name="n", source_context=[],
                source_context_normalized=(), source_context_iri="", source_unit="kg",
                source_cas="", source_ec="", flow_object_id="fo-1", target_name="n",
                target_elementary_flow_id="ef-1", target_context=[], target_unit="kg",
                basis="cas", basis_value="124-38-9", selector_reason="",
                matching_method="", algorithm_details={}, provenance={},
            ),
        ]
        for row in rows:
            with self.subTest(type(row).__name__):
                self.assertEqual(type(row).from_dict(row.to_dict()), row)

    def test_a_prepared_record_from_before_the_place_field_still_loads(self):
        """`source_context_iri` arrived in #361; a payload written before it
        must load with the field empty, which the reader already treats as
        "re-derive"."""
        payload = {
            "source_uuid": "u-1", "source_name": "n", "source_context": [],
            "source_unit": "kg", "source_cas": "",
            "target_elementary_flow_id": "ef-1",
            "prepared_target_elementary_flow_id": "ef-1",
            "target_flow_object_id": "fo-1", "target_name": "n",
            "target_context": [], "target_unit": "kg",
            "prepared_target_resolution": "direct", "prepared_target_trace": [],
            "prepared_context_decision": "", "provenance": {},
        }
        record = PreparedMatch.from_dict(payload)
        self.assertEqual(record.source_context_iri, "")


def _source_row(uuid="u-1"):
    return SourceRow(
        uuid=uuid, name="Carbon dioxide", synonyms=[], labels=["Carbon dioxide"],
        context=["air"],
        context_iri="", context_normalized=("air",), unit="kg", unit_iri="",
        cas="124-38-9", ec="",
    )


def _indexes():
    return MergeIndexes(
        flow_objects_by_id={}, flow_object_label_by_id={}, cas_index={},
        ec_index={}, label_index={}, pref_label_index={}, qualifier_index={},
        flow_objects_with_cas=set(), context_expectations=ContextExpectations(
            _by_source_context={}, _source_label="test"
        ),
        consensus_context_strings={}, prepared_context_decisions={},
        mapping_file=None, source=resolve_source_list("ecoinvent-3.12"),
    )


class UnmatchedReasonIsACategoryTestCase(unittest.TestCase):
    """`reason` names a category of failure, never a particular flow.

    It used to interpolate the unresolvable target UUID, so grouping on it gave
    8,439 distinct values for 9,614 rows and the run report had to split the
    string apart in SQL to summarise anything.
    """

    def test_no_category_embeds_an_instance(self):
        for reason in UnmatchedReason:
            with self.subTest(reason=str(reason)):
                self.assertNotIn(":", str(reason))
                self.assertEqual(str(reason), str(reason).strip())

    def test_an_unresolvable_prepared_target_reports_a_bare_category(self):
        accumulator = MergeAccumulator()
        finished = apply_prepared_decision(
            row=_source_row(),
            # A target no elementary flow has: the case that produced the
            # interpolated reason.
            prepared_rows=[{"target": {"uuid": "d70fd4d7-a6ee-4cef-9ba7-6753b0000000"}}],
            indexes=_indexes(),
            accumulator=accumulator,
        )
        self.assertTrue(finished)
        (row,) = accumulator.unmatched
        self.assertEqual(row.reason, UnmatchedReason.PREPARED_TARGET_NOT_FOUND)

    def test_the_unresolvable_target_is_still_recorded(self):
        """Dropping it from `reason` must not drop it from the row."""
        accumulator = MergeAccumulator()
        apply_prepared_decision(
            row=_source_row(),
            prepared_rows=[{"target": {"uuid": "d70fd4d7-a6ee-4cef-9ba7-6753b0000000"}}],
            indexes=_indexes(),
            accumulator=accumulator,
        )
        (row,) = accumulator.unmatched
        self.assertEqual(
            row.target_elementary_flow_id, "d70fd4d7-a6ee-4cef-9ba7-6753b0000000"
        )
        self.assertTrue(row.prepared_target_resolution)
        self.assertIsNotNone(row.prepared_target_trace)

    def test_two_unresolvable_targets_share_one_category(self):
        """The property the old reason string did not have."""
        accumulator = MergeAccumulator()
        for uuid in ("target-a", "target-b"):
            apply_prepared_decision(
                row=_source_row(uuid=f"src-{uuid}"),
                prepared_rows=[{"target": {"uuid": uuid}}],
                indexes=_indexes(),
                accumulator=accumulator,
            )
        self.assertEqual({row.reason for row in accumulator.unmatched}, {
            UnmatchedReason.PREPARED_TARGET_NOT_FOUND
        })


if __name__ == "__main__":
    unittest.main()
