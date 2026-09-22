"""The registry's composition fills a hole, and only where a name confirms it.

#129 withdrew `Antimony Trisulfide`'s only molecular formula, because it was a
misreading describing antimony *mono*sulfide.  That left the substance with no
composition at all -- which this project's own rule, written in
`withhold_contradicted_composition`, calls worse than a disputed one.

Common Chemistry has registered 1345-04-6 as `S3Sb2` throughout.  Nothing asked
it, because the registry's composition was only ever used to *judge* a derived
formula, never to supply one.

The half worth testing hardest is the corroboration gate.  Without it the rule
fires on two dozen substances, and several of those would publish something
false -- see `AName_MustConfirmTheRegistry` for the three shapes.
"""

from __future__ import annotations

import unittest
from unittest import mock

from brightway_flows.domain.flow import Flow
from brightway_flows.domain.vocabulary import (
    CHEMROF_INCHI2D_KEY_STRING,
    CHEMROF_MOLECULAR_FORMULA,
    CHEMROF_SMILES_STRING,
)
from brightway_flows.transformers.supply_registered_composition import (
    SupplyRegisteredCompositionTransformer,
)

#: What Common Chemistry really registers for each of these numbers.
REGISTERED = {
    "1345-04-6": "S3Sb2",  # antimony trisulfide
    "7440-15-5": "Re",  # rhenium, the element
    "7440-61-1": "U",  # uranium, the element
    "124-38-9": "CO2",
    "1314-84-7": "P2Zn3",  # zinc phosphide
}


def _flow(uuid, pref, *cas, properties=None):
    return Flow.from_dict({
        "uuid": uuid,
        "identifier": uuid,
        "source": "test",
        "unit": "kg",
        "prefLabel": [{"@value": pref, "@language": "en"}],
        "cas_numbers": list(cas),
        "properties": properties or {},
    })


class _Runs:
    def run_transformer(self, flows, registered=None):
        transformer = SupplyRegisteredCompositionTransformer()
        index = mock.Mock()
        index.registered_formula_for.side_effect = (
            registered if registered is not None else REGISTERED
        ).get
        with mock.patch(
            "brightway_flows.transformers.supply_registered_composition"
            ".load_commonchemistry_index",
            return_value=index,
        ):
            transformer.setup()
            return transformer.transform(flows)

    def written(self, changes, uuid):
        for change in changes:
            if change.uuid == uuid and change.field == "properties":
                return change.new_value
        return None

    def formula(self, changes, uuid):
        properties = self.written(changes, uuid)
        if properties is None:
            return None
        raw = properties[CHEMROF_MOLECULAR_FORMULA]["@value"]
        return raw[0] if isinstance(raw, list) else raw


class TheHoleIsFilled(_Runs, unittest.TestCase):
    """The case #129 created."""

    def test_the_trisulfide_gets_its_composition(self):
        flow = _flow("u-1", "Antimony Trisulfide", "1345-04-6")
        self.assertEqual(self.formula(self.run_transformer([flow]), "u-1"), "S3Sb2")

    def test_only_the_composition_is_written(self):
        """No structure, because the registry publishes none for this number.

        Inventing one from a composition would be the very mistake #129 is
        about: a confident structure standing in for an absent one.
        """
        flow = _flow("u-2", "Antimony Trisulfide", "1345-04-6")
        properties = self.written(self.run_transformer([flow]), "u-2")
        self.assertIn(CHEMROF_MOLECULAR_FORMULA, properties)
        self.assertNotIn(CHEMROF_SMILES_STRING, properties)
        self.assertNotIn(CHEMROF_INCHI2D_KEY_STRING, properties)

    def test_it_is_attributed_to_the_registry(self):
        flow = _flow("u-3", "Antimony Trisulfide", "1345-04-6")
        entry = self.written(self.run_transformer([flow]), "u-3")[CHEMROF_MOLECULAR_FORMULA]
        provenance = entry.get("provenance")
        blob = str(provenance)
        self.assertIn("1345-04-6", blob)
        self.assertIn("CAS Common Chemistry", blob)


class AName_MustConfirmTheRegistry(_Runs, unittest.TestCase):
    """The gate, and the three shapes that showed why it is needed.

    All three are real rows measured on the build: without corroboration the
    rule fires on 24 substances, and these publish something false.
    """

    def test_an_ion_does_not_take_its_element_s_composition(self):
        # `Rhenium(2+)` carries 7440-15-5, which is rhenium metal.  `Re` is the
        # neutral element and the substance is its cation.
        flow = _flow("u-4", "Rhenium(2+)", "7440-15-5")
        self.assertIsNone(self.formula(self.run_transformer([flow]), "u-4"))

    def test_a_radiological_aggregate_is_not_the_element(self):
        # `Uranium Alpha` is the alpha-emitting isotopes of uranium reported
        # together as activity -- not one substance at all (#68).
        flow = _flow("u-5", "Uranium Alpha", "7440-61-1")
        self.assertIsNone(self.formula(self.run_transformer([flow]), "u-5"))

    def test_an_accounting_construct_is_not_the_gas(self):
        flow = _flow(
            "u-6", "Correction Flow For Delayed Emission Of Fossil Carbon Dioxide",
            "124-38-9",
        )
        self.assertIsNone(self.formula(self.run_transformer([flow]), "u-6"))

    def test_a_name_that_states_no_count_corroborates_nothing(self):
        # `zinc phosphide` is P2Zn3 and the name says so nowhere: it carries no
        # multiplicative prefix, so there is no second source.
        flow = _flow("u-7", "Zinc phosphide", "1314-84-7")
        self.assertIsNone(self.formula(self.run_transformer([flow]), "u-7"))


class ItFillsNothingItShouldNot(_Runs, unittest.TestCase):
    def test_a_flow_already_publishing_a_formula_is_left_alone(self):
        flow = _flow(
            "u-8", "Antimony Trisulfide", "1345-04-6",
            properties={CHEMROF_MOLECULAR_FORMULA: {"@value": ["Sb2S3"]}},
        )
        self.assertIsNone(self.written(self.run_transformer([flow]), "u-8"))

    def test_a_flow_with_no_registry_number_is_left_alone(self):
        flow = _flow("u-9", "Antimony Trisulfide")
        self.assertIsNone(self.written(self.run_transformer([flow]), "u-9"))

    def test_a_number_the_registry_cannot_answer_for_is_left_alone(self):
        flow = _flow("u-10", "Antimony Trisulfide", "9999-99-9")
        self.assertIsNone(self.written(self.run_transformer([flow]), "u-10"))

    def test_two_numbers_stating_different_compositions_are_left_alone(self):
        # Two numbers made of different things is two substances wearing one
        # flow, and picking one would hide that.
        flow = _flow("u-11", "Antimony Trisulfide", "1345-04-6", "124-38-9")
        self.assertIsNone(self.written(self.run_transformer([flow]), "u-11"))

    def test_two_numbers_agreeing_still_answer(self):
        flow = _flow("u-12", "Antimony Trisulfide", "1345-04-6", "1345-04-7")
        registered = dict(REGISTERED, **{"1345-04-7": "S3Sb2"})
        self.assertEqual(
            self.formula(self.run_transformer([flow], registered), "u-12"), "S3Sb2"
        )


if __name__ == "__main__":
    unittest.main()
