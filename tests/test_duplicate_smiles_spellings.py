"""One molecule, spelled twice, is one candidate structure -- not two (#22).

A canonical SMILES is canonical only per toolkit.  PubChem's OEChem writes
camphor `CC1(C2CCC1(C(=O)C2)C)C` and RDKit writes `CC12CCC(CC1=O)C2(C)C`, and
both RDKit stages asked "is this value new?" by comparing strings -- so RDKit's
spelling of a molecule PubChem had already supplied took the "new value" branch
and was appended.  5,708 of 17,170 stored SMILES were a duplicate spelling of a
structure the same flow object already carried, on 5,270 objects; for 3,285 the
record had exactly one structure once the spellings were collapsed.

Two things are pinned here, in the two places they happen:

- the RDKit stages do not add a spelling of a structure the flow already has,
  and record themselves as a further source on the value that is there;
- the property normalisation collapses what reaches a record anyway -- two
  sources spelling it differently, or the stereochemistry-stripped form of one
  landing on a flat string another supplied.

InChI, InChIKey, the formula and the masses are canonical across toolkits, so
they never had this problem and must keep matching on the string.
"""

import unittest
from typing import Any

from brightway_flows.domain.flow import Flow
from brightway_flows.domain.flow_object import FlowObject
from brightway_flows.domain.property_values import (
    normalise_records,
    redundant_smiles_slots,
)
from brightway_flows.domain.vocabulary import (
    CHEMROF_INCHI2D_STRING,
    CHEMROF_ISOMERIC_SMILES_STRING,
    CHEMROF_SMILES_STRING,
)
from brightway_flows.pipeline.semantic_typing import assign_semantic_types
from brightway_flows.transformers.rdkit_enrichment import (
    RDKitPreConsensusTransformer,
)
from brightway_flows.transformers.rdkit_post_consensus import (
    RDKitPostConsensusTransformer,
)

#: PubChem's OEChem spelling of camphor, RDKit's, and a third that is neither.
PUBCHEM_CAMPHOR = "CC1(C2CCC1(C(=O)C2)C)C"
RDKIT_CAMPHOR = "CC12CCC(CC1=O)C2(C)C"
OTHER_CAMPHOR = "O=C1CC2CCC1(C)C2(C)C"
CHIRAL_CAMPHOR = "CC1(C)[C@@H]2CC[C@@]1(C)C(=O)C2"


def _smiles_property(values: list[str], iri: str = CHEMROF_SMILES_STRING) -> dict[str, Any]:
    return {
        iri: {
            "@id": iri,
            "rdfs:label": "SMILES",
            "@value": list(values),
            "provenance": {
                "prov:wasGeneratedBy": "enrich_references.pubchem_semantic"
            },
        }
    }


def _flow(properties: dict[str, Any]) -> Flow:
    return Flow(
        uuid="u-1",
        source="EF 3.1",
        unit="kg",
        prefLabel=[{"@value": "Camphor", "@language": "en"}],
        properties=properties,
    )


def _flow_object(properties: dict[str, Any]) -> FlowObject:
    return FlowObject(
        flow_object_id="fo-camphor",
        prefLabel=[{"@value": "Camphor", "@language": "en"}],
        altLabel=[],
        properties=properties,
        references=[],
        created_from={},
        classifications={},
    )


def _applied(transformer: Any, flow: Flow) -> dict[str, Any]:
    """The properties the transformer proposes, or the ones it left alone."""
    for change in transformer.transform([flow]):
        if change.field == "properties":
            return change.new_value
    return flow.properties


class PreConsensusTestCase(unittest.TestCase):
    def setUp(self):
        self.transformer = RDKitPreConsensusTransformer()

    def test_a_respelled_structure_is_not_added_again(self):
        flow = _flow(_smiles_property([PUBCHEM_CAMPHOR]))
        properties = _applied(self.transformer, flow)
        self.assertEqual(
            properties[CHEMROF_SMILES_STRING]["@value"], [PUBCHEM_CAMPHOR]
        )

    def test_the_stored_spelling_is_not_rewritten(self):
        """Nothing is removed or replaced here -- ChEBI's and PubChem's strings
        stay as they wrote them."""
        flow = _flow(_smiles_property([PUBCHEM_CAMPHOR]))
        properties = _applied(self.transformer, flow)
        self.assertNotIn(RDKIT_CAMPHOR, properties[CHEMROF_SMILES_STRING]["@value"])

    def test_a_property_the_flow_does_not_have_is_still_added(self):
        flow = _flow(_smiles_property(["O=C=O"]))
        properties = _applied(self.transformer, flow)
        self.assertEqual(
            properties[CHEMROF_INCHI2D_STRING]["@value"], ["InChI=1S/CO2/c2-1-3"]
        )

    def test_an_unparseable_stored_string_never_matches(self):
        """It has no canonical form, and that is not the same as being this
        structure -- so the computed value is a new one and is added."""
        flow = _flow(_smiles_property(["not/a/smiles[", "O=C=O"]))
        properties = _applied(self.transformer, flow)
        self.assertEqual(
            sorted(properties[CHEMROF_SMILES_STRING]["@value"]),
            ["O=C=O", "not/a/smiles["],
        )


class PostConsensusTestCase(unittest.TestCase):
    def setUp(self):
        self.transformer = RDKitPostConsensusTransformer()

    def test_a_respelled_structure_is_not_added_again(self):
        flow = _flow(_smiles_property([PUBCHEM_CAMPHOR]))
        properties = _applied(self.transformer, flow)
        self.assertEqual(
            properties[CHEMROF_SMILES_STRING]["@value"], [PUBCHEM_CAMPHOR]
        )

    def test_rdkit_is_recorded_as_a_further_source_on_the_value(self):
        """The confirmation is the point of the branch: two toolkits read the
        same structure out of that string, and the audit trail should say so."""
        flow = _flow(_smiles_property([PUBCHEM_CAMPHOR]))
        properties = _applied(self.transformer, flow)
        self.assertIn(
            "rdkit_post_consensus",
            [
                row.get("prov:wasGeneratedBy")
                for row in properties[CHEMROF_SMILES_STRING]["provenance"]
            ],
        )

    def test_the_change_reports_the_structure_as_confirmed_not_added(self):
        flow = _flow(_smiles_property([PUBCHEM_CAMPHOR]))
        (change,) = self.transformer.transform([flow])
        self.assertIn("confirmed: smiles_string", change.comment)
        self.assertNotIn("added: smiles_string", change.comment)


class CollapseTestCase(unittest.TestCase):
    """What the normalisation does with spellings that reach a record anyway."""

    def _normalised(self, values: list[str], iri: str = CHEMROF_SMILES_STRING):
        record = _flow_object(_smiles_property(values, iri))
        counts = normalise_records([record])
        return record.properties[iri]["@value"], counts

    def test_two_spellings_of_one_molecule_leave_one_value(self):
        values, _ = self._normalised([PUBCHEM_CAMPHOR, RDKIT_CAMPHOR])
        self.assertEqual(values, [RDKIT_CAMPHOR])

    def test_the_surviving_spelling_is_the_canonical_one(self):
        """Neither source wrote the canonical form here, so one had to be chosen,
        and the record is already written in RDKit's spelling throughout."""
        values, _ = self._normalised([PUBCHEM_CAMPHOR, OTHER_CAMPHOR])
        self.assertEqual(values, [RDKIT_CAMPHOR])

    def test_a_lone_value_keeps_the_spelling_its_source_gave_it(self):
        """Nothing duplicates it, so rewriting it would change a published string
        with nothing to show for it."""
        values, _ = self._normalised([PUBCHEM_CAMPHOR])
        self.assertEqual(values, [PUBCHEM_CAMPHOR])

    def test_two_different_molecules_both_stay(self):
        """The substances that are genuinely ambiguous must stay that way."""
        values, _ = self._normalised(["O=C=O", "C(=O)=S"])
        self.assertEqual(sorted(values), ["C(=O)=S", "O=C=O"])

    def test_stereoisomers_are_two_structures(self):
        """Flattening one onto the other would lose the stereochemistry, which
        is a loss rather than a collapse -- in either slot."""
        values, _ = self._normalised(["C[C@@H](N)C(=O)O", "C[C@H](N)C(=O)O"])
        self.assertEqual(len(values), 2)

    def test_a_respelled_isomer_collapses(self):
        """`N[C@H](C)C(=O)O` and `C[C@@H](N)C(=O)O` are the same enantiomer: the
        chirality tag is read against the order the neighbours are written in."""
        values, _ = self._normalised(
            ["N[C@H](C)C(=O)O", "C[C@@H](N)C(=O)O"], CHEMROF_ISOMERIC_SMILES_STRING
        )
        self.assertEqual(values, ["C[C@@H](N)C(=O)O"])

    def test_an_unparseable_string_is_left_alone(self):
        """No canonical form is not the same as no structure, and two strings
        RDKit cannot read are not evidence of one molecule."""
        values, _ = self._normalised(["not/a/smiles[", "also]not[one", "O=C=O"])
        self.assertEqual(values, ["not/a/smiles[", "also]not[one", "O=C=O"])

    def test_the_provenance_of_the_dropped_spelling_stays_on_the_property(self):
        """Provenance is recorded per property, not per value, so collapsing must
        not take the record of who attested to the structure with it."""
        record = _flow_object(
            {
                CHEMROF_SMILES_STRING: {
                    "@value": [PUBCHEM_CAMPHOR, RDKIT_CAMPHOR],
                    "provenance": [
                        {"prov:wasGeneratedBy": "enrich_references.pubchem_semantic"},
                        {"prov:wasGeneratedBy": "rdkit_post_consensus"},
                    ],
                }
            }
        )
        normalise_records([record])
        self.assertEqual(
            [
                row["prov:wasGeneratedBy"]
                for row in record.properties[CHEMROF_SMILES_STRING]["provenance"]
            ],
            ["enrich_references.pubchem_semantic", "rdkit_post_consensus"],
        )

    def test_a_flow_is_collapsed_as_well_as_a_flow_object(self):
        """The published export projects the flow and the review apps read the
        object; a fix that reached one and not the other is how they disagree."""
        flow = _flow(_smiles_property([PUBCHEM_CAMPHOR, RDKIT_CAMPHOR]))
        normalise_records([flow])
        self.assertEqual(
            flow.properties[CHEMROF_SMILES_STRING]["@value"], [RDKIT_CAMPHOR]
        )

    def test_the_run_reports_what_it_collapsed(self):
        _, counts = self._normalised([PUBCHEM_CAMPHOR, RDKIT_CAMPHOR])
        self.assertEqual(counts["smiles_string_duplicate_spellings_collapsed"], 1)

    def test_running_it_twice_changes_nothing(self):
        """The merge writes records by a path that runs this again."""
        record = _flow_object(_smiles_property([PUBCHEM_CAMPHOR, RDKIT_CAMPHOR]))
        normalise_records([record])
        once = record.properties
        normalise_records([record])
        self.assertEqual(record.properties, once)


class StereoSplitTestCase(unittest.TestCase):
    """The isomeric split writes a spelling of its own, which can collide."""

    def test_a_flattened_stereo_string_collapses_into_a_flat_source_string(self):
        record = _flow_object(_smiles_property([CHIRAL_CAMPHOR, PUBCHEM_CAMPHOR]))
        assign_semantic_types([record], [])
        normalise_records([record])
        self.assertEqual(
            record.properties[CHEMROF_SMILES_STRING]["@value"], [RDKIT_CAMPHOR]
        )
        self.assertEqual(
            record.properties[CHEMROF_ISOMERIC_SMILES_STRING]["@value"],
            [CHIRAL_CAMPHOR],
        )


class RedundancyMeasureTestCase(unittest.TestCase):
    """The acceptance measure, read off the record rather than asserted."""

    def test_a_record_with_two_spellings_of_one_structure_is_counted(self):
        record = _flow_object(_smiles_property([PUBCHEM_CAMPHOR, RDKIT_CAMPHOR]))
        self.assertEqual(redundant_smiles_slots(record.properties), 1)

    def test_nothing_is_counted_once_the_normalisation_has_run(self):
        record = _flow_object(_smiles_property([PUBCHEM_CAMPHOR, RDKIT_CAMPHOR]))
        normalise_records([record])
        self.assertEqual(redundant_smiles_slots(record.properties), 0)

    def test_both_slots_are_measured(self):
        properties = _smiles_property([PUBCHEM_CAMPHOR, RDKIT_CAMPHOR])
        properties.update(
            _smiles_property(
                ["N[C@H](C)C(=O)O", "C[C@@H](N)C(=O)O"],
                CHEMROF_ISOMERIC_SMILES_STRING,
            )
        )
        self.assertEqual(redundant_smiles_slots(properties), 2)

    def test_two_different_structures_are_not_redundancy(self):
        record = _flow_object(_smiles_property(["O=C=O", "C(=O)=S"]))
        self.assertEqual(redundant_smiles_slots(record.properties), 0)


if __name__ == "__main__":
    unittest.main()
