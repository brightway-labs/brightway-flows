"""A published mass must belong to the flow it is published on.

`molecular_mass` describes a structure.  A flow carrying several candidate
structures has no single one, so a value written there is one candidate's mass
presented as the flow's, and nothing downstream can tell which candidate won.
In the run that prompted this it was decided by alphabetical order over SMILES
strings: `10-methoxy-5H-dibenzo[b,f]azepine` (C15H13NO, 223.275) published
232.666, the mass of an unrelated chlorobiphenyl carboxylic acid (#217).

What is pinned here is the invariant that replaced it -- a mass is present only
when the candidates name one structure -- and, just as importantly, that the
properties which *state* the ambiguity are left alone.
"""

import unittest

from brightway_flows.domain.flow import Flow
from brightway_flows.domain.vocabulary import (
    CHEMROF_INCHI2D_KEY_STRING,
    CHEMROF_MOLECULAR_FORMULA,
    CHEMROF_MOLECULAR_MASS,
    CHEMROF_MONOISOTOPIC_MASS,
    CHEMROF_SMILES_STRING,
)
from brightway_flows.transformers.withhold_ambiguous_mass import (
    WithholdAmbiguousMassTransformer,
    candidate_structure_count,
    structure_is_ambiguous,
)

_UUID = "7de354b2-88d0-46a4-b0c7-2e6fe0783d5b"


def _prop(iri, values):
    return {"@id": iri, "rdfs:label": iri.rsplit("/", 1)[-1], "@value": list(values)}


def _flow(*, keys=(), formulas=(), mass="232.666", mono="232.029107", smiles=()):
    properties = {}
    if keys:
        properties[CHEMROF_INCHI2D_KEY_STRING] = _prop(CHEMROF_INCHI2D_KEY_STRING, keys)
    if formulas:
        properties[CHEMROF_MOLECULAR_FORMULA] = _prop(CHEMROF_MOLECULAR_FORMULA, formulas)
    if smiles:
        properties[CHEMROF_SMILES_STRING] = _prop(CHEMROF_SMILES_STRING, smiles)
    if mass:
        properties[CHEMROF_MOLECULAR_MASS] = _prop(CHEMROF_MOLECULAR_MASS, [mass])
    if mono:
        properties[CHEMROF_MONOISOTOPIC_MASS] = _prop(CHEMROF_MONOISOTOPIC_MASS, [mono])
    return Flow.from_dict({
        "uuid": _UUID, "prefLabel": [{"@value": "test", "@language": "en"}],
        "properties": properties,
    })


def _apply(flow):
    changes = WithholdAmbiguousMassTransformer().transform([flow])
    if not changes:
        return flow.properties
    return changes[0].new_value


class AmbiguityTestCase(unittest.TestCase):
    def test_stereo_and_protonation_blocks_do_not_make_two_structures(self):
        """Two records of one compound routinely disagree past the first block."""
        self.assertFalse(structure_is_ambiguous(_flow(keys=[
            "BIOGOMUNGWOQHV-UHFFFAOYSA-N", "BIOGOMUNGWOQHV-QGZVFWFLSA-M",
        ]).properties))

    def test_two_skeletons_are_two_structures(self):
        self.assertTrue(structure_is_ambiguous(_flow(keys=[
            "OWFMSKZVCPGDEJ-UHFFFAOYSA-N", "ZKHZWXLOSIGIGZ-UHFFFAOYSA-N",
        ]).properties))

    def test_formula_is_the_fallback_when_there_is_no_inchikey(self):
        self.assertTrue(structure_is_ambiguous(_flow(formulas=["C15H13NO", "C13H9ClO2"]).properties))
        self.assertFalse(structure_is_ambiguous(_flow(formulas=["C15H13NO"]).properties))

    def test_an_inchikey_outranks_the_formula_fallback(self):
        """Formulas can disagree on notation for one structure; the key decides."""
        properties = _flow(
            keys=["BIOGOMUNGWOQHV-UHFFFAOYSA-N"], formulas=["C22H38O6", "C22H38O6.Na"]
        ).properties
        self.assertEqual(candidate_structure_count(properties), 1)

    def test_a_flow_with_no_structure_at_all_is_not_ambiguous(self):
        self.assertFalse(structure_is_ambiguous({}))


class WithholdingTestCase(unittest.TestCase):
    def test_an_ambiguous_flow_loses_both_masses(self):
        properties = _apply(_flow(keys=[
            "OWFMSKZVCPGDEJ-UHFFFAOYSA-N", "ZKHZWXLOSIGIGZ-UHFFFAOYSA-N",
        ]))
        self.assertNotIn(CHEMROF_MOLECULAR_MASS, properties)
        self.assertNotIn(CHEMROF_MONOISOTOPIC_MASS, properties)

    def test_a_settled_flow_keeps_its_mass(self):
        properties = _apply(_flow(keys=["OWFMSKZVCPGDEJ-UHFFFAOYSA-N"]))
        self.assertEqual(properties[CHEMROF_MOLECULAR_MASS]["@value"], ["232.666"])
        self.assertEqual(properties[CHEMROF_MONOISOTOPIC_MASS]["@value"], ["232.029107"])

    def test_the_properties_that_state_the_ambiguity_are_left_alone(self):
        """A list on formula/SMILES/InChIKey is the signal a reader resolves the
        flow by.  Removing it would hide the condition instead of the guess."""
        keys = ["OWFMSKZVCPGDEJ-UHFFFAOYSA-N", "ZKHZWXLOSIGIGZ-UHFFFAOYSA-N"]
        properties = _apply(_flow(
            keys=keys, formulas=["C15H13NO", "C13H9ClO2"], smiles=["COC1=CC2=CC=CC=C2NC3=CC=CC=C31", "OC(=O)c1ccccc1"],
        ))
        self.assertEqual(properties[CHEMROF_INCHI2D_KEY_STRING]["@value"], keys)
        self.assertEqual(len(properties[CHEMROF_MOLECULAR_FORMULA]["@value"]), 2)
        self.assertEqual(len(properties[CHEMROF_SMILES_STRING]["@value"]), 2)

    def test_an_ambiguous_flow_with_no_mass_yields_no_change(self):
        """Nothing to withhold is not a change; the run report should not claim one."""
        flow = _flow(keys=["A-UHFFFAOYSA-N", "B-UHFFFAOYSA-N"], mass="", mono="")
        self.assertEqual(WithholdAmbiguousMassTransformer().transform([flow]), [])

    def test_a_settled_flow_yields_no_change(self):
        self.assertEqual(
            WithholdAmbiguousMassTransformer().transform([_flow(keys=["A-UHFFFAOYSA-N"])]), []
        )

    def test_the_change_says_how_many_candidates_there_were(self):
        changes = WithholdAmbiguousMassTransformer().transform([_flow(keys=[
            "A-UHFFFAOYSA-N", "B-UHFFFAOYSA-N", "C-UHFFFAOYSA-N",
        ])])
        self.assertIn("3 candidate structures", changes[0].comment)
        self.assertIn("molecular_mass", changes[0].comment)


if __name__ == "__main__":
    unittest.main()
