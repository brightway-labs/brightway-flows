"""The quantities that are not substances, and what typing them takes off.

Six BAFU names in #68 turned out to be measurements rather than compounds, and
two of them had already been typed as substances by rules that read a registry
number: `COD, Chemical Oxygen Demand` as an `ImpreciseChemicalMixture` off a
CAS that names no compound, and EF's `Acid (as H+)` as a `NeutralMolecule`
carrying the hydron's structure over 12 elementary flows.

These pin the three things that has to mean: the curated decision beats the
chemistry the row arrived with, the identity that made the row look like a
substance is withdrawn rather than left beside a class contradicting it, and
what the number *is* expressed as survives as a link instead of as the row's
identity.
"""

import unittest
from typing import Any

from brightway_flows.domain.aggregate_measurements import (
    aggregate_measurements,
    measurement_for_name,
)
from brightway_flows.domain.flow import Flow
from brightway_flows.domain.flow_object import FlowObject
from brightway_flows.domain.vocabulary import (
    BRIGHTWAY_EXPRESSED_AS,
    BRIGHTWAY_SUMS_OVER,
    CHEMINF_CAS_REGISTRY_NUMBER,
    CHEMINF_EC_NUMBER,
    CHEMROF_MOLECULAR_FORMULA,
    CHEMROF_SMILES_STRING,
    CLASS_TERMS,
    IRIS,
    Term,
    flow_object_iri,
)
from brightway_flows.pipeline.semantic_typing import (
    assign_semantic_types,
    withdraw_single_substance_properties,
)


def make_object(
    label: str,
    *,
    alt_labels: tuple[str, ...] = (),
    cas: str = "",
    ec: str = "",
    formula: str = "",
    smiles: str = "",
) -> FlowObject:
    properties: dict[str, Any] = {}
    if formula:
        properties[CHEMROF_MOLECULAR_FORMULA] = {"@value": [formula]}
    if smiles:
        properties[CHEMROF_SMILES_STRING] = {"@value": [smiles]}
    classifications: dict[str, Any] = {}
    if cas:
        classifications[CHEMINF_CAS_REGISTRY_NUMBER] = {"@value": [cas]}
    if ec:
        classifications[CHEMINF_EC_NUMBER] = {"@value": [ec]}
    return FlowObject(
        flow_object_id="fo-" + label.lower().replace(" ", "-")[:28],
        prefLabel=[{"@value": label, "@language": "en"}],
        altLabel=[{"@value": alt, "@language": "en"} for alt in alt_labels],
        properties=properties,
        references=[],
        created_from={},
        classifications=classifications,
    )


def typed(objects: list[FlowObject]) -> dict[str, FlowObject]:
    """Run the typing pass and return the objects by preferred label."""
    assign_semantic_types(objects)
    return {obj.prefLabel[0]["@value"]: obj for obj in objects}


class CuratedFileTestCase(unittest.TestCase):
    """The file is data a curator edits, so its shape is checked rather than
    assumed."""

    def test_every_entry_states_what_it_is_and_why(self):
        for measurement in aggregate_measurements():
            with self.subTest(id=measurement.id):
                self.assertTrue(measurement.id)
                self.assertTrue(measurement.label)
                self.assertTrue(measurement.names)
                # The definition and the comment are what make this file
                # reviewable rather than a list of strings someone once agreed
                # with.  An entry without them is a decision with no record.
                self.assertTrue(measurement.definition)
                self.assertTrue(measurement.comment)

    def test_ids_are_unique(self):
        ids = [m.id for m in aggregate_measurements()]
        self.assertEqual(len(ids), len(set(ids)))

    def test_a_name_claimed_twice_is_an_error_and_not_a_race(self):
        """Two quantities cannot both be what a source meant by one name.

        The index raises where the file is read rather than letting whichever
        entry happens to be last silently win -- which would make the answer
        depend on file order, and file order is not a decision anyone made.
        """
        from brightway_flows.domain import aggregate_measurements as module

        module._by_canonical_name.cache_clear()
        original = module.aggregate_measurements
        duplicated = (*original(), original()[0])
        try:
            module.aggregate_measurements = lambda: (
                duplicated[0],
                module.AggregateMeasurement(
                    id="other", label="Other", definition="d",
                    names=duplicated[0].names, expressed_as=None,
                    sums_over=None, comment="c",
                ),
            )
            with self.assertRaises(ValueError):
                module._by_canonical_name()
        finally:
            module.aggregate_measurements = original
            module._by_canonical_name.cache_clear()

    def test_the_class_is_offered_as_a_filter(self):
        """`CLASS_TERMS` generates the review apps' type facet.

        A class nothing can filter on is most of the reason these rows were a
        problem, so leaving the minted one out of the registry would reproduce
        it one layer up.
        """
        self.assertIn(Term.AGGREGATE_MEASUREMENT, CLASS_TERMS)

    def test_lookup_is_exact_after_normalisation(self):
        self.assertIsNotNone(measurement_for_name("Benzene (as BTEX)"))
        self.assertIsNotNone(measurement_for_name("  benzene   (AS btex) "))
        # The pair this file exists to keep apart: containment in either
        # direction is how the BTEX total gets benzene's identity.
        self.assertIsNone(measurement_for_name("Benzene"))
        self.assertIsNone(measurement_for_name("Benzene (as BTEX) and toluene"))


class TypingTestCase(unittest.TestCase):

    def test_a_registry_number_is_withdrawn_rather_than_corrected(self):
        """#57's answer, applied where the number arrives (#68).

        17612-50-9 rides on BAFU's COD row.  It names no compound, so there is
        no right number to put in its place -- and left there it is a merge
        waiting for a substance to claim it, exactly as dinitrogen's number
        fused organic-bound nitrogen with the nitrogen-gas rows.
        """
        objects = typed([
            make_object("COD, Chemical Oxygen Demand", cas="17612-50-9"),
            make_object("Oxygen"),
        ])
        cod = objects["COD, Chemical Oxygen Demand"]

        self.assertEqual(cod.types, [IRIS[Term.AGGREGATE_MEASUREMENT]])
        self.assertNotIn(CHEMINF_CAS_REGISTRY_NUMBER, cod.classifications)
        record = cod.created_from["aggregate_measurement"]
        self.assertEqual(record["registry_identifiers_withdrawn"], ["17612-50-9"])
        self.assertEqual(record["id"], "chemical_oxygen_demand")

    def test_the_withdrawn_number_is_named_and_not_merely_counted(self):
        """A number nobody can see was removed is one nobody can check."""
        objects = typed([
            make_object("Acid (as H+)", cas="12408-02-5", ec="235-186-4"),
        ])
        record = objects["Acid (as H+)"].created_from["aggregate_measurement"]
        self.assertEqual(
            sorted(record["registry_identifiers_withdrawn"]),
            ["12408-02-5", "235-186-4"],
        )

    def test_the_structure_a_wrong_number_pulled_in_goes_too(self):
        """`Acid (as H+)` published the hydron's formula and SMILES.

        Sulfuric acid's mass counted at the proton's weight is not the proton.
        The class alone would leave the row typed as a measurement while still
        carrying the values that made it look like a substance, which is a
        record contradicting itself.
        """
        objects = typed([
            make_object(
                "Acid (as H+)", cas="12408-02-5", formula="H", smiles="[H+]",
            ),
        ])
        acid = objects["Acid (as H+)"]
        self.assertNotIn(CHEMROF_MOLECULAR_FORMULA, acid.properties)
        self.assertNotIn(CHEMROF_SMILES_STRING, acid.properties)

    def test_what_the_number_is_expressed_as_is_a_link_not_an_identity(self):
        """The distinction the whole issue turns on.

        `Benzene (as BTEX)` relates to benzene and is not benzene.  A link says
        the first; a match would say the second, and BAFU carries plain benzene
        in the same compartment of all 8 datasets that hold the BTEX row, so
        saying the second would also double-count.
        """
        benzene = make_object("Benzene", formula="C6H6", smiles="c1ccccc1")
        objects = typed([make_object("Benzene (as BTEX)"), benzene])
        btex = objects["Benzene (as BTEX)"]

        self.assertEqual(btex.types, [IRIS[Term.AGGREGATE_MEASUREMENT]])
        self.assertEqual(
            btex.properties[BRIGHTWAY_EXPRESSED_AS]["@value"],
            [{"@id": flow_object_iri(benzene.flow_object_id)}],
        )
        # Not the same object, and not carrying benzene's chemistry.
        self.assertNotIn(CHEMROF_SMILES_STRING, btex.properties)
        self.assertEqual(
            objects["Benzene"].types, [IRIS[Term.NEUTRAL_MOLECULE]]
        )

    def test_a_measurement_can_name_both_what_it_counts_and_what_it_weighs(self):
        """AOX is the case with both links, and they are different objects.

        EF's `Adsorbable Organic Halogen Compounds` is a class of molecules;
        BAFU's `AOX ... as Cl` is those molecules weighed as chlorine.  Nothing
        in the published list said how the two relate.
        """
        compounds = make_object("Adsorbable Organic Halogen Compounds")
        chlorine = make_object("Chlorine")
        objects = typed([
            make_object("AOX, Adsorbable Organic Halogen As Cl"),
            compounds,
            chlorine,
        ])
        aox = objects["AOX, Adsorbable Organic Halogen As Cl"]

        self.assertEqual(
            aox.properties[BRIGHTWAY_SUMS_OVER]["@value"],
            [{"@id": flow_object_iri(compounds.flow_object_id)}],
        )
        self.assertEqual(
            aox.properties[BRIGHTWAY_EXPRESSED_AS]["@value"],
            [{"@id": flow_object_iri(chlorine.flow_object_id)}],
        )

    def test_an_unstated_link_and_an_unresolved_one_are_different_facts(self):
        """Only one of them is a defect.

        Acidity states no `expressed_as` -- a proton is not the element
        hydrogen, and naming the wrong thing is worse than naming nothing.
        Total nitrogen states one the list cannot answer: it carries
        `Dinitrogen` and no elemental `Nitrogen`.  Collapsing the two would
        hide the second behind the first.
        """
        objects = typed([
            make_object("Acidity, Unspecified"),
            make_object("Nitrogen, Total (excluding N2)"),
            make_object("Dinitrogen"),
        ])
        acidity = objects["Acidity, Unspecified"].created_from["aggregate_measurement"]
        nitrogen = objects[
            "Nitrogen, Total (excluding N2)"
        ].created_from["aggregate_measurement"]

        self.assertEqual(acidity["expressed_as"], "unstated")
        self.assertEqual(nitrogen["expressed_as"], "unresolved:Nitrogen")
        self.assertNotIn(
            BRIGHTWAY_EXPRESSED_AS,
            objects["Nitrogen, Total (excluding N2)"].properties,
        )

    def test_a_label_two_objects_share_resolves_to_neither(self):
        """Eleven preferred labels are duplicated in the current build.

        Picking whichever came first would publish a link to an arbitrary one
        of two substances, and nothing downstream could tell.
        """
        objects = [
            make_object("Benzene (as BTEX)"),
            make_object("Benzene", formula="C6H6"),
            make_object("Benzene", smiles="c1ccccc1"),
        ]
        objects[2].flow_object_id = "fo-benzene-second"
        assign_semantic_types(objects)
        record = objects[0].created_from["aggregate_measurement"]

        self.assertEqual(record["expressed_as"], "unresolved:Benzene")
        self.assertNotIn(BRIGHTWAY_EXPRESSED_AS, objects[0].properties)

    def test_a_source_name_matches_through_an_alternative_label(self):
        """A curator writes the name the source list uses.

        The preferred label is this project's decision and can change; the
        source's name survives as an alternative label.  Which label matched is
        recorded, because a match through an alternative one means the row is
        published under a name the file does not list.
        """
        objects = typed([
            make_object(
                "Oxygen Demand, Chemical",
                alt_labels=("COD, Chemical Oxygen Demand",),
            ),
        ])
        record = objects[
            "Oxygen Demand, Chemical"
        ].created_from["aggregate_measurement"]

        self.assertEqual(record["id"], "chemical_oxygen_demand")
        self.assertEqual(record["matched_on"], "COD, Chemical Oxygen Demand")

    def test_the_run_reports_what_it_did(self):
        counts = assign_semantic_types([
            make_object("COD, Chemical Oxygen Demand", cas="17612-50-9"),
            make_object("Benzene (as BTEX)"),
            make_object("Benzene", formula="C6H6", smiles="c1ccccc1"),
        ])
        self.assertEqual(counts["aggregate_measurement"], 2)
        self.assertEqual(
            counts["aggregate_measurement_registry_identifiers_withdrawn"], 1
        )
        self.assertEqual(counts["aggregate_measurement_expressed_as_links"], 1)
        self.assertEqual(counts["aggregate_measurement_expressed_as_unresolved"], 1)


class FlowLayerTestCase(unittest.TestCase):

    def test_the_flow_layer_sweep_recognises_a_measurement_by_its_name(self):
        """The other two families are recognised by their origin qualifier.

        An aggregate measurement has none, and should not: a qualifier says why
        a substance is held apart from another one, and there is no substance
        this is held apart from.  So the sweep asks the name, which is the same
        question the typing asked one layer up.
        """
        flow = Flow(
            uuid="uuid-1",
            prefLabel=[{"@value": "Acid (as H+)", "@language": "en"}],
            properties={
                CHEMROF_MOLECULAR_FORMULA: {"@value": ["H"]},
                CHEMROF_SMILES_STRING: {"@value": ["[H+]"]},
            },
        )
        counts = withdraw_single_substance_properties([flow])

        self.assertEqual(counts["records"], 1)
        self.assertEqual(counts["properties_withdrawn"], 2)
        self.assertEqual(flow.properties, {})


if __name__ == "__main__":
    unittest.main()
