"""Applying a curated structure, and the bounds on the class it states.

#129.  The transformer writes the whole structural record from the one SMILES a
curator states, replacing whatever the derivations reached.  The typing rule
honours the class stated beside it.

The bound that matters is the typing one: a stated class overrules the chemistry
rules, and it must not be able to overrule the rules above it, which decide that
a row is not a substance at all.  A curated structure turning an aggregate
measurement into a compound is exactly the failure `aggregate-measurements.json`
exists to prevent.
"""

from __future__ import annotations

import unittest
from unittest import mock

from brightway_flows.domain.flow import Flow
from brightway_flows.domain.flow_object import FlowObject
from brightway_flows.domain.vocabulary import (
    CHEMINF_CAS_REGISTRY_NUMBER,
    CHEMROF_INCHI2D_KEY_STRING,
    CHEMROF_MOLECULAR_FORMULA,
    CHEMROF_MOLECULAR_MASS,
    CHEMROF_SMILES_STRING,
    IRIS,
    Term,
)
from brightway_flows.pipeline.semantic_typing import classify
from brightway_flows.transformers.apply_structure_corrections import (
    ApplyStructureCorrectionsTransformer,
)

SB2S3 = "[S]=[Sb][S][Sb]=[S]"
MONOSULFIDE = "[S]=[Sb+]"


def _flow(uuid, *cas, properties=None):
    return Flow.from_dict({
        "uuid": uuid,
        "identifier": uuid,
        "source": "test",
        "unit": "kg",
        "prefLabel": [{"@value": "Antimony Trisulfide", "@language": "en"}],
        "cas_numbers": list(cas),
        "properties": properties or {},
    })


def _run(flows):
    transformer = ApplyStructureCorrectionsTransformer()
    transformer.setup()
    return transformer.transform(flows)


def _written(changes, uuid):
    for change in changes:
        if change.uuid == uuid and change.field == "properties":
            return change.new_value
    return None


def _value(properties, iri):
    raw = properties[iri]["@value"]
    return raw[0] if isinstance(raw, list) else raw


class TheStructureIsWritten(unittest.TestCase):
    def test_the_whole_record_comes_from_the_one_smiles(self):
        properties = _written(_run([_flow("u-1", "1345-04-6")]), "u-1")
        self.assertEqual(_value(properties, CHEMROF_SMILES_STRING), SB2S3)
        self.assertEqual(_value(properties, CHEMROF_MOLECULAR_FORMULA), "S3Sb2")
        self.assertEqual(
            _value(properties, CHEMROF_INCHI2D_KEY_STRING),
            "IHBMMJGTJFPEQY-UHFFFAOYSA-N",
        )
        self.assertEqual(_value(properties, CHEMROF_MOLECULAR_MASS), "339.721")

    def test_it_replaces_a_wrong_structure_rather_than_joining_it(self):
        # Leaving the monosulfide beside the correction would publish two
        # answers and settle nothing.
        flow = _flow(
            "u-2", "1345-04-6",
            properties={
                CHEMROF_SMILES_STRING: {"@value": [MONOSULFIDE]},
                CHEMROF_MOLECULAR_FORMULA: {"@value": ["SSb+"]},
            },
        )
        properties = _written(_run([flow]), "u-2")
        smiles = properties[CHEMROF_SMILES_STRING]["@value"]
        self.assertEqual(
            smiles if isinstance(smiles, list) else [smiles], [SB2S3]
        )

    def test_a_flow_with_another_number_is_untouched(self):
        self.assertIsNone(_written(_run([_flow("u-3", "7732-18-5")]), "u-3"))

    def test_a_flow_with_no_number_is_untouched(self):
        self.assertIsNone(_written(_run([_flow("u-4")]), "u-4"))


def _object(label, cas, properties=None, **kwargs):
    return FlowObject.from_dict({
        "flow_object_id": "fo-test",
        "prefLabel": [{"@value": label, "@language": "en"}],
        "classifications": {
            CHEMINF_CAS_REGISTRY_NUMBER: {"@value": [cas]}
        } if cas else {},
        "properties": properties or {},
        "altLabel": [],
        "references": [],
        "created_from": {},
        **kwargs,
    })


class TheStatedClassIsPublished(unittest.TestCase):
    def test_the_correction_decides_the_class(self):
        obj = _object("Antimony Trisulfide", "1345-04-6")
        classification = classify(obj, label="Antimony Trisulfide")
        self.assertEqual(classification.types, (IRIS[Term.NEUTRAL_MOLECULE],))
        self.assertEqual(classification.rule, "curated_structure")

    def test_it_answers_even_with_no_structure_on_the_object(self):
        # The case #129 left behind: no structure at all, which rule 10 read as
        # a substance of variable composition.
        obj = _object("Antimony Trisulfide", "1345-04-6")
        self.assertNotEqual(
            classify(obj, label="Antimony Trisulfide").types,
            (IRIS[Term.IMPRECISE_CHEMICAL_MIXTURE],),
        )

    def test_an_uncorrected_substance_is_unaffected(self):
        obj = _object("Water", "7732-18-5")
        self.assertNotEqual(
            classify(obj, label="Water").rule, "curated_structure"
        )


class ACuratedClassCannotOverruleNotASubstance(unittest.TestCase):
    """The bound.  Rules 0–0c decide a row is not a substance at all."""

    def test_an_aggregate_measurement_still_wins(self):
        # If a number under correction were ever also a curated quantity, the
        # quantity has to win: it is the statement that there is no one
        # substance here to have a structure.
        obj = _object("Chemical Oxygen Demand", "1345-04-6")
        with mock.patch(
            "brightway_flows.pipeline.semantic_typing._measurement_for",
            return_value=("stub", "Chemical Oxygen Demand"),
        ):
            classification = classify(obj, label="Chemical Oxygen Demand")
        self.assertEqual(classification.rule, "aggregate_measurement")


if __name__ == "__main__":
    unittest.main()
