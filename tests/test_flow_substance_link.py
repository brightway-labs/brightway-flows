"""What travels from a substance onto the flows that reference it.

A flow and its substance are different things — that is what the two layers are
for — but the published export is flow-shaped, so the classes, the origin
qualifier, the substance that qualifier is relative to, and the substance's
chemistry have to travel with the flow or every reader re-derives them.

The chemistry is the one that used not to travel, because the flow already had
a copy of it — the one its sources wrote, from before the layering. Every
correction the pipeline makes runs over the substance, so the flow published the
uncorrected answer: 8,542 flows stating a stereochemistry in the field defined
as carrying none (#53), 85 objects' flows claiming a charge their substance had
withdrawn, and none of them carrying the element and isotope statements written
onto the object afterwards. It is derived now, so there is one home for a
substance's chemistry and no rule about which parts of it are inherited.

This is tested apart from `run_pipeline` because a copy that silently does
nothing is invisible inside it. `origin_qualifier` is set on 11 flow objects out
of 7,660 and on none at all in a bounded run, so a build proves nothing about
it: the first real check that it reached the export would have been a user not
finding it.
"""

import unittest
from typing import Any

from brightway_flows.domain.flow import Flow
from brightway_flows.domain.flow_object import FlowObject
from brightway_flows.domain.vocabulary import (
    CHEMROF_ELEMENTAL_CHARGE,
    CHEMROF_ISOMERIC_SMILES_STRING,
    CHEMROF_MOLECULAR_FORMULA,
    CHEMROF_SMILES_STRING,
    IRIS,
    Term,
)
from brightway_flows.pipeline.engine import _link_flows_to_their_substance
from brightway_flows.pipeline.semantic_typing import (
    _split_isomeric_smiles,
    _withdraw_single_substance_properties,
    isomeric_values_in_graph_slot,
    withdraw_single_substance_properties,
)


class _LayerRow:
    """Stands in for the `ElementaryFlow` the resolver produced."""

    def __init__(self, flow_object_id: str, source_refs: list[Any] | None = None):
        self.flow_object_id = flow_object_id
        self.source_refs = source_refs or []


def make_object(object_id: str, **kwargs) -> FlowObject:
    return FlowObject(
        flow_object_id=object_id,
        prefLabel=[],
        altLabel=[],
        properties={},
        references=[],
        created_from={},
        **kwargs,
    )


class LinkFlowsTestCase(unittest.TestCase):
    def link(self, flows, objects, rows):
        _link_flows_to_their_substance(flows, objects, rows)
        return flows

    def test_the_flow_learns_which_substance_it_is(self):
        flow = Flow(uuid="u-1", source="EF 3.1", unit="kg")
        self.link([flow], [make_object("fo-1")], {"u-1": _LayerRow("fo-1")})
        self.assertEqual(flow.flow_object_id, "fo-1")

    def test_the_classes_travel(self):
        flow = Flow(uuid="u-1", source="EF 3.1", unit="kg")
        obj = make_object("fo-1", types=[IRIS[Term.NEUTRAL_MOLECULE]])
        self.link([flow], [obj], {"u-1": _LayerRow("fo-1")})
        self.assertEqual(flow.types, [IRIS[Term.NEUTRAL_MOLECULE]])

    def test_the_origin_qualifier_travels(self):
        """The one this file exists for: 11 objects in 7,660 carry it."""
        flow = Flow(uuid="u-1", source="EF 3.1", unit="kg")
        obj = make_object("fo-1", origin_qualifier="fossil")
        self.link([flow], [obj], {"u-1": _LayerRow("fo-1")})
        self.assertEqual(flow.origin_qualifier, "fossil")

    def test_the_base_substance_travels(self):
        """The other half of the qualifier, and as invisible in a bounded run."""
        flow = Flow(uuid="u-1", source="EF 3.1", unit="kg")
        obj = make_object(
            "fo-1", origin_qualifier="biogenic", parent_flow_object_id="fo-base"
        )
        self.link([flow], [obj], {"u-1": _LayerRow("fo-1")})
        self.assertEqual(flow.parent_flow_object_id, "fo-base")

    def test_a_qualified_substance_with_no_parent_says_nothing(self):
        """`Oils, Non-fossil` has no CAS for the parent resolution to run through."""
        flow = Flow(uuid="u-1", source="EF 3.1", unit="kg")
        obj = make_object("fo-1", origin_qualifier="biogenic")
        self.link([flow], [obj], {"u-1": _LayerRow("fo-1")})
        self.assertEqual(flow.origin_qualifier, "biogenic")
        self.assertIsNone(flow.parent_flow_object_id)
        self.assertNotIn("parent_flow_object_id", flow.to_dict())

    def test_every_flow_of_one_substance_gets_the_same_facts(self):
        """Many flows to one object is the relationship; all of them learn it."""
        flows = [Flow(uuid=f"u-{n}", source="EF 3.1", unit="kg") for n in (1, 2, 3)]
        obj = make_object(
            "fo-1",
            types=[IRIS[Term.ATOM_CATION]],
            origin_qualifier="biogenic",
            parent_flow_object_id="fo-base",
        )
        rows = {f"u-{n}": _LayerRow("fo-1") for n in (1, 2, 3)}
        self.link(flows, [obj], rows)
        for flow in flows:
            with self.subTest(flow=flow.uuid):
                self.assertEqual(flow.types, [IRIS[Term.ATOM_CATION]])
                self.assertEqual(flow.origin_qualifier, "biogenic")
                self.assertEqual(flow.parent_flow_object_id, "fo-base")

    def test_an_unqualified_substance_leaves_the_field_absent(self):
        """None, not "", so `_OMIT_IF_NONE` keeps the key out of the export."""
        flow = Flow(uuid="u-1", source="EF 3.1", unit="kg")
        self.link([flow], [make_object("fo-1")], {"u-1": _LayerRow("fo-1")})
        self.assertIsNone(flow.origin_qualifier)
        self.assertIsNone(flow.parent_flow_object_id)
        self.assertIsNone(flow.types)
        self.assertNotIn("origin_qualifier", flow.to_dict())
        self.assertNotIn("parent_flow_object_id", flow.to_dict())
        self.assertNotIn("@type", flow.to_dict())

    def test_a_flow_the_resolver_did_not_place_is_left_alone(self):
        """It has no substance to learn from, and must not be given one."""
        flow = Flow(uuid="u-missing", source="EF 3.1", unit="kg")
        obj = make_object(
            "fo-1", origin_qualifier="fossil", parent_flow_object_id="fo-base"
        )
        self.link([flow], [obj], {})
        self.assertEqual(flow.flow_object_id, "")
        self.assertIsNone(flow.origin_qualifier)
        self.assertIsNone(flow.parent_flow_object_id)

    def test_a_stale_value_is_cleared_rather_than_kept(self):
        """The merge shows the transformers flows read back from the database.

        One already carrying a qualifier, whose object no longer has one, must
        not keep the old answer.
        """
        flow = Flow(uuid="u-1", source="EF 3.1", unit="kg")
        flow.origin_qualifier = "fossil"
        flow.parent_flow_object_id = "fo-base"
        flow.types = [IRIS[Term.NEUTRAL_MOLECULE]]
        self.link([flow], [make_object("fo-1")], {"u-1": _LayerRow("fo-1")})
        self.assertIsNone(flow.origin_qualifier)
        self.assertIsNone(flow.parent_flow_object_id)
        self.assertIsNone(flow.types)

    def test_the_classes_are_copied_not_shared(self):
        """A later edit to one flow's list must not reach the substance."""
        flow = Flow(uuid="u-1", source="EF 3.1", unit="kg")
        obj = make_object("fo-1", types=[IRIS[Term.NEUTRAL_MOLECULE]])
        self.link([flow], [obj], {"u-1": _LayerRow("fo-1")})
        flow.types.append("https://example.org/not-a-class")
        self.assertEqual(obj.types, [IRIS[Term.NEUTRAL_MOLECULE]])


def smiles_entry(*values: str, iri: str = CHEMROF_SMILES_STRING) -> dict:
    """A structure slot in the shape the pipeline's writers leave it."""
    return {"@id": iri, "rdfs:label": "SMILES", "@value": list(values)}


class ChemistryTravelsTestCase(unittest.TestCase):
    """#53: the substance's `properties`, onto every flow that is an occurrence of it."""

    def link(self, flows, objects, rows):
        _link_flows_to_their_substance(flows, objects, rows)
        return flows

    def test_the_chemistry_travels(self):
        flow = Flow(uuid="u-1", source="EF 3.1", unit="kg")
        obj = make_object("fo-1")
        obj.properties = {CHEMROF_MOLECULAR_FORMULA: {"@value": ["C6H8O"]}}
        self.link([flow], [obj], {"u-1": _LayerRow("fo-1")})
        self.assertEqual(flow.properties[CHEMROF_MOLECULAR_FORMULA]["@value"], ["C6H8O"])

    def test_the_shape_reaches_the_field_that_says_it_carries_one(self):
        """Hexa-2,4-dienal, the substance #53 was written about.

        Its `/` marks say which side of each double bond the ends are on, and
        the substance record moves them to `isomeric_smiles_string` where the
        field name admits them. The flow published them in `smiles_string`,
        which is defined as the structure with the shape taken off, and carried
        no isomeric slot at all — the correction runs over substances, and this
        is a flow.
        """
        flow = Flow(uuid="u-1", source="EF 3.1", unit="kg")
        flow.properties = {CHEMROF_SMILES_STRING: smiles_entry("C/C=C/C=C/C=O")}
        obj = make_object("fo-1")
        obj.properties = {CHEMROF_SMILES_STRING: smiles_entry("C/C=C/C=C/C=O")}
        _split_isomeric_smiles(obj)

        self.link([flow], [obj], {"u-1": _LayerRow("fo-1")})

        self.assertEqual(
            flow.properties[CHEMROF_SMILES_STRING]["@value"], ["CC=CC=CC=O"]
        )
        self.assertEqual(
            flow.properties[CHEMROF_ISOMERIC_SMILES_STRING]["@value"],
            ["C/C=C/C=C/C=O"],
        )
        self.assertEqual(isomeric_values_in_graph_slot(flow.properties), 0)

    def test_a_statement_the_substance_withdrew_does_not_survive_on_the_flow(self):
        """The charge on an element: withdrawn on 85 objects, kept on their flows.

        `ChemicalElement` is the generic form of an atom, and PubChem's zero is
        the neutral one — a different class, which nothing here asserts. The
        object stopped saying it; the flow went on saying it.
        """
        flow = Flow(uuid="u-1", source="EF 3.1", unit="kg")
        flow.properties = {CHEMROF_ELEMENTAL_CHARGE: {"@value": [0]}}
        obj = make_object("fo-1")
        obj.properties = {CHEMROF_MOLECULAR_FORMULA: {"@value": ["Ni"]}}
        self.link([flow], [obj], {"u-1": _LayerRow("fo-1")})
        self.assertNotIn(CHEMROF_ELEMENTAL_CHARGE, flow.properties)

    def test_a_substance_with_no_chemistry_leaves_the_flow_with_none(self):
        """An empty bag is the substance's answer, not a reason to keep the flow's."""
        flow = Flow(uuid="u-1", source="EF 3.1", unit="kg")
        flow.properties = {CHEMROF_MOLECULAR_FORMULA: {"@value": ["CO2"]}}
        self.link([flow], [make_object("fo-1")], {"u-1": _LayerRow("fo-1")})
        self.assertEqual(flow.properties, {})
        self.assertEqual(flow.to_dict()["properties"], {})

    def test_a_flow_the_resolver_did_not_place_keeps_its_own(self):
        """There is no substance to read from, and its own copy is all there is."""
        flow = Flow(uuid="u-missing", source="EF 3.1", unit="kg")
        flow.properties = {CHEMROF_MOLECULAR_FORMULA: {"@value": ["CO2"]}}
        self.link([flow], [make_object("fo-1")], {})
        self.assertEqual(flow.properties[CHEMROF_MOLECULAR_FORMULA]["@value"], ["CO2"])

    def test_every_flow_of_one_substance_states_the_same_chemistry(self):
        """What makes the copy hoistable: 94,409 flows over 7,760 substances."""
        flows = [Flow(uuid=f"u-{n}", source="EF 3.1", unit="kg") for n in (1, 2, 3)]
        flows[0].properties = {CHEMROF_SMILES_STRING: smiles_entry("C/C=C/C=O")}
        obj = make_object("fo-1")
        obj.properties = {CHEMROF_SMILES_STRING: smiles_entry("CC=CC=O")}
        rows = {f"u-{n}": _LayerRow("fo-1") for n in (1, 2, 3)}
        self.link(flows, [obj], rows)
        for flow in flows:
            with self.subTest(flow=flow.uuid):
                self.assertEqual(
                    flow.properties[CHEMROF_SMILES_STRING]["@value"], ["CC=CC=O"]
                )

    def test_the_flow_layer_withdrawal_has_nothing_left_to_do(self):
        """A delayed-emission correction is a quantity in kg*a, not a substance.

        `assign_semantic_types` takes the formula, masses and structures off its
        object; the flow layer then ran the same withdrawal over the flow's own
        copy (#43). Reading from the object, the copy arrives already stripped
        — so the pass reports nothing withdrawn, and that zero is what says the
        derivation reached the flow.
        """
        obj = make_object("fo-1", origin_qualifier="delayed_emission_correction")
        obj.properties = {CHEMROF_MOLECULAR_FORMULA: {"@value": ["CO2"]}}
        _withdraw_single_substance_properties(obj)

        flow = Flow(uuid="u-1", source="EF 3.1", unit="kg")
        flow.properties = {CHEMROF_MOLECULAR_FORMULA: {"@value": ["CO2"]}}
        self.link([flow], [obj], {"u-1": _LayerRow("fo-1")})

        counts = withdraw_single_substance_properties([flow])
        self.assertEqual(counts["records"], 1)
        self.assertEqual(counts["properties_withdrawn"], 0)
        self.assertNotIn(CHEMROF_MOLECULAR_FORMULA, flow.properties)

    def test_the_chemistry_is_copied_not_shared(self):
        """Deeply: a property entry nests its values and its provenance.

        A shallow copy would leave every flow of a substance editing one bag,
        and an edit to a flow is not an edit to the substance.
        """
        flows = [Flow(uuid=f"u-{n}", source="EF 3.1", unit="kg") for n in (1, 2)]
        obj = make_object("fo-1")
        obj.properties = {CHEMROF_SMILES_STRING: smiles_entry("CC=CC=O")}
        rows = {f"u-{n}": _LayerRow("fo-1") for n in (1, 2)}
        self.link(flows, [obj], rows)

        flows[0].properties[CHEMROF_SMILES_STRING]["@value"].append("not a structure")

        self.assertEqual(obj.properties[CHEMROF_SMILES_STRING]["@value"], ["CC=CC=O"])
        self.assertEqual(
            flows[1].properties[CHEMROF_SMILES_STRING]["@value"], ["CC=CC=O"]
        )


if __name__ == "__main__":
    unittest.main()
