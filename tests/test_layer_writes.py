"""Writes made after the transformer chain reach the changelog (#92).

`ChangeEvent` used to be constructed in one place, `apply_transformers`, and
`pipeline_sources` written in the line below it. Everything the run did *after*
`resolve_flow_layers` was therefore absent from `changelog` -- including the two
largest things that can happen to a published flow: its preferred label being
replaced outright by the element pass, and its being deprecated.

`review_records.ChangeEvent` says the table makes "everything that happened to
this substance answerable without a join". These tests are what makes that true
of the run rather than of the transformer chain.

Four passes were connected then and three were not, so the deprecation a
*curator* decided still left no trace while the derived one five lines away in
`run_pipeline` was recorded (#94). The last three classes here are those
passes.
"""

from __future__ import annotations

import unittest

from brightway_flows.domain.flow import Flow
from brightway_flows.domain.flow_object import FlowObject
from brightway_flows.domain.vocabulary import (
    CHEMROF_CHEMICAL_ELEMENT,
    CHEMROF_ELEMENTAL_CHARGE,
    CHEMROF_FORMAL_CHARGE,
    CHEMROF_MOLECULAR_FORMULA,
    RDFS_LABEL_CURIE,
)
from brightway_flows.domain.records import UnknownRecordFieldError
from brightway_flows.pipeline.collision_decisions import (
    CollisionRuling,
    apply_collision_rulings,
)
from brightway_flows.pipeline.element_labels import ElementPrefLabelPass
from brightway_flows.pipeline.engine import _normalise_flow_properties
from brightway_flows.pipeline.layer_writes import LayerWriteLog
from brightway_flows.pipeline.semantic_typing import (
    withdraw_single_substance_properties,
)

#: An object-level property, written by `flow_layers/elements.py` and not an
#: IRI: it describes the record rather than the substance, so the withdrawal
#: leaves it alone.
_ISOTOPE_LOOKUP = "isotope_lookup"


def _flow(uuid: str = "u-1", **kwargs) -> Flow:
    return Flow(uuid=uuid, **kwargs)


class _Row:
    """An elementary flow, in the fields a collision ruling reads and writes."""

    def __init__(self, elementary_flow_id: str):
        self.elementary_flow_id = elementary_flow_id
        self.flow_object_id = "fo-1"
        self.context_iri = "ctx-1"
        self.unit = "kg"
        self.lcia_methods = []
        self.source_refs = None
        self.owl_deprecated = None
        self.dcterms_is_replaced_by = None
        self.is_replaced_by_uuid = None


_RULING = {
    ("fo-1", "ctx-1", "kg"): CollisionRuling(
        flow_object_id="fo-1",
        context_iri="ctx-1",
        unit="kg",
        survivor="rich",
        merged=("poor",),
        names=("designation", "chemical name"),
        comment="one substance published twice",
    )
}


class TheLogAppliesAndRecordsTestCase(unittest.TestCase):
    def test_a_write_lands_on_the_flow(self):
        flow = _flow(unit="kg")
        log = LayerWriteLog()

        self.assertTrue(log.write(flow, "unit", "m", pass_name="p"))
        self.assertEqual(flow.unit, "m")

    def test_the_write_is_recorded_with_the_value_it_replaced(self):
        flow = _flow(unit="kg")
        log = LayerWriteLog()
        log.write(flow, "unit", "m", pass_name="p", comment="why")

        [write] = log.writes
        self.assertEqual(write.uuid, "u-1")
        self.assertEqual(write.field_name, "unit")
        self.assertEqual(write.old_value, "kg")
        self.assertEqual(write.new_value, "m")
        self.assertEqual(write.pass_name, "p")
        self.assertEqual(write.comment, "why")

    def test_the_pass_is_named_as_the_source_of_the_field(self):
        """`pipeline_sources` answers 'who last wrote this', and a layer pass
        writing a published field without answering it is the gap."""
        flow = _flow(unit="kg")
        LayerWriteLog().write(flow, "unit", "m", pass_name="link_pass")
        self.assertEqual(flow.pipeline_sources["unit"], "link_pass")

    def test_a_write_that_changes_nothing_is_not_recorded(self):
        """`_link_flows_to_their_substance` assigns `properties` onto every
        flow in the run.  On the 2026-08-12 build 815 of 7,674 objects differed
        from the flow carrying them; logging the other 6,859 would be hundreds
        of thousands of rows saying nothing happened."""
        flow = _flow(unit="kg")
        log = LayerWriteLog()

        self.assertFalse(log.write(flow, "unit", "kg", pass_name="p"))
        self.assertEqual(log.writes, [])
        self.assertNotIn("unit", flow.pipeline_sources)

    def test_a_misspelled_field_raises_where_it_is_written(self):
        """The same guarantee `Change` gives, for the same reason."""
        with self.assertRaises(UnknownRecordFieldError):
            LayerWriteLog().write(_flow(), "untis", "m", pass_name="p")

    def test_a_serialised_key_resolves_to_its_attribute(self):
        flow = _flow()
        log = LayerWriteLog()
        log.write(flow, "@type", ["chemrof:ChemicalElement"], pass_name="p")

        self.assertEqual(flow.types, ["chemrof:ChemicalElement"])
        self.assertEqual(log.writes[0].field_name, "types")

    def test_the_changelog_rows_carry_the_pass_as_the_transformer(self):
        flow = _flow(unit="kg")
        log = LayerWriteLog()
        log.write(flow, "unit", "m", pass_name="element_pref_labels")

        [event] = log.change_events()
        self.assertEqual(event.transformer, "element_pref_labels")
        self.assertEqual(event.field_name, "unit")
        self.assertEqual(event.old_value, "kg")
        self.assertEqual(event.new_value, "m")
        # Filled in by the writer, not by the pass.
        self.assertEqual(event.change_index, 0)
        self.assertEqual(event.flow_object_id, "")


class TheLabelIsCapturedBeforeTheWriteTestCase(unittest.TestCase):
    """A rename has to report the name it replaced.

    `ChangeEvent.flow_name` is read off the flow, and the element pass changes
    exactly that field.  Read afterwards, every rename in the changelog would
    say it renamed the new name to itself.
    """

    def test_a_rename_reports_the_old_name(self):
        flow = _flow(prefLabel=[{"@value": "americium", "@language": "en"}])
        log = LayerWriteLog()
        log.write(
            flow, "prefLabel",
            [{"@value": "Americium", "@language": "en"}],
            pass_name="element_pref_labels",
        )

        self.assertEqual(log.writes[0].flow_name, "americium")
        self.assertEqual(log.change_events()[0].flow_name, "americium")


class TheElementPassIsVisibleTestCase(unittest.TestCase):
    """#16 gated this pass on a curator's ruling.  It still left no record of
    the renames the ruling allowed."""

    def _run(self, current: str, element: str, decisions=None):
        flow = _flow(
            prefLabel=[{"@value": current, "@language": "en"}],
            flow_object_id="fo-1",
        )
        obj = FlowObject(
            flow_object_id="fo-1",
            prefLabel=[{"@value": element, "@language": "en"}],
            altLabel=[],
            properties={},
            references=[],
            created_from={},
            types=[CHEMROF_CHEMICAL_ELEMENT],
        )
        log = LayerWriteLog()
        pass_ = ElementPrefLabelPass(decisions=decisions or {}, writes=log)
        stats = pass_.apply([flow], [obj])
        return flow, log, stats

    def test_a_titlecase_rename_reaches_the_changelog(self):
        flow, log, stats = self._run("americium", "Americium")

        self.assertEqual(stats["titlecased"], 1)
        self.assertEqual(len(log.writes), 1)
        self.assertEqual(log.writes[0].field_name, "prefLabel")
        self.assertEqual(log.writes[0].flow_name, "americium")
        self.assertEqual(flow.pipeline_sources["prefLabel"], pass_name(log))

    def test_a_pass_that_writes_nothing_records_nothing(self):
        """An unruled rename is refused, and a refusal is not a change."""
        _flow_, log, stats = self._run("Curium chloride", "Americium")

        self.assertEqual(stats["undecided"], 1)
        self.assertEqual(log.writes, [])


class TheCuratedDeprecationIsVisibleTestCase(unittest.TestCase):
    """#94: the two passes that deprecate a flow run five lines apart.

    One derives the deprecation from a signature and recorded it from #92
    onwards; the other applies a ruling a curator wrote down, and recorded
    nothing -- so the deprecations a curator is most likely to come looking for
    were the ones with no row to find.
    """

    def setUp(self):
        self.rows = [_Row("rich"), _Row("poor")]
        self.flows = [_flow("rich"), _flow("poor")]

    def _apply(self, writes=None):
        return apply_collision_rulings(
            flows=self.flows,
            elementary_flows=self.rows,
            rulings=_RULING,
            writes=writes,
        )

    def test_all_three_fields_of_the_deprecation_are_recorded(self):
        log = LayerWriteLog()
        self._apply(writes=log)

        self.assertEqual(
            [(w.uuid, w.field_name, w.new_value) for w in log.writes],
            [
                ("poor", "owl_deprecated", True),
                ("poor", "dcterms_is_replaced_by", "urn:uuid:rich"),
                ("poor", "is_replaced_by_uuid", "rich"),
            ],
        )

    def test_the_row_carries_the_curator_s_reason(self):
        """The changelog is where a curator asks why a flow disappeared, and a
        ruling is the one deprecation that has an answer written down."""
        log = LayerWriteLog()
        self._apply(writes=log)

        [event, *_] = log.change_events()
        self.assertEqual(event.transformer, "pipeline.collision_decisions")
        self.assertIn("merged onto rich", event.comment)
        self.assertIn("one substance published twice", event.comment)

    def test_the_deprecation_lands_whether_or_not_it_is_recorded(self):
        """Nothing branches on recording: the merge reuses these passes with no
        log, and must get the same writes."""
        self._apply()

        [deprecated] = [f for f in self.flows if f.owl_deprecated]
        self.assertEqual(deprecated.uuid, "poor")
        self.assertEqual(deprecated.is_replaced_by_uuid, "rich")
        self.assertEqual(
            deprecated.pipeline_sources["owl_deprecated"],
            "pipeline.collision_decisions",
        )


class ThePropertyNormalisationIsVisibleTestCase(unittest.TestCase):
    """A published statement moving from one predicate to another is a change
    to what the flow says about the world, and said nothing in the log."""

    def _normalise(self, writes=None):
        flow = _flow(properties={
            CHEMROF_FORMAL_CHARGE: {
                "@value": [-1],
                RDFS_LABEL_CURIE: "formal charge",
            },
        })
        counts = _normalise_flow_properties([flow], writes=writes)
        return flow, counts

    def test_the_corrected_properties_reach_the_changelog(self):
        log = LayerWriteLog()
        flow, counts = self._normalise(writes=log)

        self.assertEqual(counts["charge_migrated"], 1)
        [write] = log.writes
        self.assertEqual(write.field_name, "properties")
        self.assertEqual(write.pass_name, "normalise_property_values")
        self.assertIn(CHEMROF_FORMAL_CHARGE, write.old_value)
        self.assertIn(CHEMROF_ELEMENTAL_CHARGE, write.new_value)
        self.assertEqual(flow.properties, write.new_value)

    def test_a_flow_the_correction_leaves_alone_is_not_recorded(self):
        """Almost every flow is one of these."""
        flow = _flow(properties={
            CHEMROF_ELEMENTAL_CHARGE: {"@value": [-1]},
        })
        log = LayerWriteLog()
        _normalise_flow_properties([flow], writes=log)

        self.assertEqual(log.writes, [])

    def test_the_correction_lands_without_a_log(self):
        flow, counts = self._normalise()

        self.assertEqual(counts["charge_migrated"], 1)
        self.assertNotIn(CHEMROF_FORMAL_CHARGE, flow.properties)


class TheFlowLayerWithdrawalIsVisibleTestCase(unittest.TestCase):
    """`properties_withdrawn` reads zero while the chemistry reaches the flow
    from its substance.  A run reporting a non-zero one is reporting a flow
    that published a molecular formula for a quantity in `kg*a`, and that is
    exactly the flow a curator will open the changelog for."""

    def _withdraw(self, writes=None):
        flow = _flow(
            prefLabel=[{"@value": "Acid (as H+)", "@language": "en"}],
            properties={
                CHEMROF_MOLECULAR_FORMULA: {"@value": ["H"]},
                _ISOTOPE_LOOKUP: {"@value": ["H-1"]},
            },
        )
        counts = withdraw_single_substance_properties([flow], writes=writes)
        return flow, counts

    def test_what_was_taken_off_the_flow_is_recorded(self):
        log = LayerWriteLog()
        flow, counts = self._withdraw(writes=log)

        self.assertEqual(counts["properties_withdrawn"], 1)
        [write] = log.writes
        self.assertEqual(write.field_name, "properties")
        self.assertEqual(write.pass_name, "withdraw_single_substance_properties")
        self.assertIn(CHEMROF_MOLECULAR_FORMULA, write.old_value)
        self.assertNotIn(CHEMROF_MOLECULAR_FORMULA, write.new_value)
        # What describes the object rather than the substance stays.
        self.assertIn(_ISOTOPE_LOOKUP, write.new_value)
        self.assertEqual(flow.properties, write.new_value)

    def test_the_expected_zero_records_nothing(self):
        """The flows have taken their properties from their objects, so the
        withdrawal has already happened one layer up."""
        flow = _flow(prefLabel=[{"@value": "Acid (as H+)", "@language": "en"}])
        log = LayerWriteLog()
        counts = withdraw_single_substance_properties([flow], writes=log)

        self.assertEqual(counts["records"], 1)
        self.assertEqual(counts["properties_withdrawn"], 0)
        self.assertEqual(log.writes, [])

    def test_the_withdrawal_lands_without_a_log(self):
        flow, counts = self._withdraw()

        self.assertEqual(counts["properties_withdrawn"], 1)
        self.assertNotIn(CHEMROF_MOLECULAR_FORMULA, flow.properties)


def pass_name(log: LayerWriteLog) -> str:
    return log.writes[0].pass_name


if __name__ == "__main__":
    unittest.main()
