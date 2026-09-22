"""Reading the ratio a registry writes into a salt's formula, and acting on it.

CAS registers nickel acetate as `C2H4O2 . 1/2 Ni` -- two acetic acids to one
nickel, which is the salt.  Neither SMILES nor InChI can hold half an atom, so
the structure CAS derives from its own formula loses the ratio and comes out
one-to-one, and both end up published side by side (#310).

The tests come in pairs throughout.  Every one that asks a value to be withdrawn
has a partner asking that the same rule leaves a value alone -- a rule that
withdraws data is cheapest to make pass by withdrawing more, and the partner is
what stops it.
"""

from __future__ import annotations

import unittest
from collections import Counter

from brightway_flows.domain.attestation import ATTESTED_BY, attest, attested_by, prune
from brightway_flows.domain.flow import Flow
from brightway_flows.domain.formula import (
    heavy_atom_composition,
    parse_formula,
    published_heavy_atoms,
    registered_composition,
)
from brightway_flows.domain.vocabulary import (
    CHEMROF_INCHI2D_KEY_STRING,
    CHEMROF_MOLECULAR_FORMULA,
    CHEMROF_SMILES_STRING,
)
from brightway_flows.integrations.commonchemistry import (
    build_commonchemistry_index,
    normalise_formula,
)
from brightway_flows.transformers.withhold_contradicted_composition import (
    WithholdContradictedCompositionTransformer,
)

#: Nickel acetate, the substance #310 is written about.
_NICKEL_CAS = "373-02-4"
_NICKEL_REGISTERED = "C<sub>2</sub>H<sub>4</sub>O<sub>2</sub>.<sup>1</sup>/<sub>2</sub>Ni"
_SALT_FORMULA = "C4H6NiO4"
_SALT_KEY = "AIYYMMQIMJOTBM-UHFFFAOYSA-L"
_RATIOLESS_FORMULA = "C2H4NiO2"
_RATIOLESS_KEY = "XMOKRCSXICGIDD-UHFFFAOYSA-N"

#: DABCO, where the same test points the other way: the registry is right and
#: the name-derived structure is wrong.
_DABCO_CAS = "280-57-9"
_DABCO_REGISTERED = "C<sub>6</sub>H<sub>12</sub>N<sub>2</sub>"
_DABCO_FORMULA = "C6H12N2"
_DABCO_KEY = "IMNIMPAHZVJRPE-UHFFFAOYSA-N"
_MISREAD_FORMULA = "C14H28N2"
_MISREAD_KEY = "KKCOQCVPBASEDD-UHFFFAOYSA-N"

_PUBCHEM = "enrich_references.pubchem_semantic"
_CHEBI = "enrich_references.chebi_semantic"
_RDKIT = "rdkit_post_consensus"


def _composition(formula: str) -> tuple[tuple[str, int], ...] | None:
    return published_heavy_atoms(formula)


class ReadingARegisteredFormulaTestCase(unittest.TestCase):
    """`C2H4O2 . 1/2 Ni` is two acetic acids and one nickel, not one of each."""

    def test_a_plain_formula_reads_as_itself(self):
        self.assertEqual(registered_composition("C6H12N2"), Counter(C=6, H=12, N=2))

    def test_a_half_metal_doubles_the_acid(self):
        self.assertEqual(
            registered_composition("C2H4O2.1/2Ni"), Counter(C=4, H=8, O=4, Ni=1)
        )

    def test_a_whole_number_multiplier_multiplies_that_component_only(self):
        self.assertEqual(
            registered_composition("H4O7P2.2Na"), Counter(H=4, O=7, P=2, Na=2)
        )

    def test_a_three_quarter_ratio_scales_both_components(self):
        # Talc, 14807-96-6: `H2O3Si . 3/4 Mg` is four silicate units to three
        # magnesium, which is the Mg3(Si4O10) the mineral's own name says.
        self.assertEqual(
            registered_composition("H2O3Si.3/4Mg"), Counter(H=8, O=12, Si=4, Mg=3)
        )

    def test_unspecified_is_no_opinion_rather_than_a_parse_failure(self):
        self.assertIsNone(registered_composition("Unspecified"))

    def test_an_unreadable_component_says_nothing_rather_than_half_an_answer(self):
        # A half-read formula compares as a different substance, so nothing is
        # worse than a partial answer here.
        self.assertIsNone(registered_composition("C6H12N2.what"))
        self.assertIsNone(parse_formula("C4H6NiO4-2"))

    def test_a_blank_says_nothing(self):
        self.assertIsNone(registered_composition(""))
        self.assertIsNone(registered_composition(None))


class HeavyAtomsTestCase(unittest.TestCase):
    """The acid and its salt differ by hydrogen and by nothing else."""

    def test_the_registry_and_the_salt_agree_once_hydrogen_is_ignored(self):
        registered = heavy_atom_composition(
            registered_composition(normalise_formula(_NICKEL_REGISTERED))
        )
        self.assertEqual(registered, _composition(_SALT_FORMULA))

    def test_the_ratioless_structure_does_not_agree(self):
        self.assertNotEqual(_composition(_SALT_FORMULA), _composition(_RATIOLESS_FORMULA))

    def test_a_formula_of_nothing_but_hydrogen_says_nothing(self):
        # Otherwise two substances would compare equal by both having no heavy
        # atoms at all.
        self.assertIsNone(heavy_atom_composition(Counter(H=2)))

    def test_a_source_may_spell_a_salt_the_registry_way_too(self):
        # The build carries `H4B4O9.2Na` for disodium tetraborate.
        self.assertEqual(
            published_heavy_atoms("H4B4O9.2Na"), published_heavy_atoms("B4Na2O9")
        )


class AttestationTestCase(unittest.TestCase):
    """Which stage stands behind which value, keyed on the value."""

    def _entry(self) -> dict:
        entry = {"@value": [_SALT_FORMULA, _RATIOLESS_FORMULA]}
        attest(entry, [_SALT_FORMULA], _RDKIT)
        attest(entry, [_RATIOLESS_FORMULA], _PUBCHEM)
        return entry

    def test_each_value_names_its_own_source(self):
        entry = self._entry()
        self.assertEqual(attested_by(entry, _SALT_FORMULA), (_RDKIT,))
        self.assertEqual(attested_by(entry, _RATIOLESS_FORMULA), (_PUBCHEM,))

    def test_two_sources_agreeing_on_one_value_both_stand_behind_it(self):
        entry = self._entry()
        attest(entry, [_SALT_FORMULA], _CHEBI)
        self.assertEqual(attested_by(entry, _SALT_FORMULA), (_CHEBI, _RDKIT))

    def test_attesting_twice_records_once(self):
        entry = self._entry()
        attest(entry, [_SALT_FORMULA], _RDKIT)
        self.assertEqual(attested_by(entry, _SALT_FORMULA), (_RDKIT,))

    def test_a_value_nobody_attested_reads_as_unknown_not_as_unsupported(self):
        entry = self._entry()
        self.assertEqual(attested_by(entry, "C99H99"), ())

    def test_sorting_the_values_does_not_disturb_the_attribution(self):
        # The point of keying on the value: `_merge_semantic_property` sorts
        # `@value` and knows nothing about this key.
        entry = self._entry()
        entry["@value"] = sorted(entry["@value"], reverse=True)
        self.assertEqual(attested_by(entry, _SALT_FORMULA), (_RDKIT,))

    def test_pruning_clears_what_a_gate_withdrew(self):
        entry = self._entry()
        entry["@value"] = [_SALT_FORMULA]
        prune(entry)
        self.assertEqual(entry[ATTESTED_BY], {_SALT_FORMULA: [_RDKIT]})

    def test_pruning_everything_removes_the_key_rather_than_leaving_it_empty(self):
        entry = self._entry()
        entry["@value"] = []
        prune(entry)
        self.assertNotIn(ATTESTED_BY, entry)


def _index(**registered: str):
    """A Common Chemistry index holding the formulas named, and nothing else."""
    return build_commonchemistry_index({
        "detail_by_cas": {
            cas: {"rn": cas, "name": cas, "molecularFormula": formula, "inchiKey": ""}
            for cas, formula in registered.items()
        }
    })


def _flow(*, cas: list[str], properties: dict) -> Flow:
    return Flow(uuid="flow-1", name="test", cas_numbers=cas, properties=properties)


def _properties(rows: list[tuple[str, list[tuple[str, str]]]]) -> dict:
    """`[(iri, [(value, generator), ...])]` as a properties dict."""
    out: dict = {}
    for iri, values in rows:
        entry: dict = {"@id": iri, "@value": [value for value, _ in values]}
        for value, generator in values:
            attest(entry, [value], generator)
        out[iri] = entry
    return out


def _run(transformer, flow):
    changes = transformer.transform([flow])
    return changes[0].new_value if changes else None


class TheSaltKeepsTheNameDerivedAnswerTestCase(unittest.TestCase):
    """Nickel acetate: the registry's formula backs the salt, so the
    ratio-less structure goes."""

    def setUp(self):
        self.transformer = WithholdContradictedCompositionTransformer()
        self.transformer._registry = _index(**{_NICKEL_CAS: _NICKEL_REGISTERED})
        self.flow = _flow(
            cas=[_NICKEL_CAS],
            properties=_properties([
                (CHEMROF_MOLECULAR_FORMULA,
                 [(_SALT_FORMULA, _RDKIT), (_RATIOLESS_FORMULA, _PUBCHEM)]),
                (CHEMROF_INCHI2D_KEY_STRING,
                 [(_SALT_KEY, _RDKIT), (_RATIOLESS_KEY, _PUBCHEM)]),
            ]),
        )
        self.result = _run(self.transformer, self.flow)

    def test_the_salt_formula_survives_alone(self):
        self.assertEqual(
            self.result[CHEMROF_MOLECULAR_FORMULA]["@value"], [_SALT_FORMULA]
        )

    def test_the_key_that_came_with_the_withdrawn_formula_goes_too(self):
        self.assertEqual(
            self.result[CHEMROF_INCHI2D_KEY_STRING]["@value"], [_SALT_KEY]
        )

    def test_the_withdrawal_is_recorded_in_the_attribution(self):
        entry = self.result[CHEMROF_INCHI2D_KEY_STRING]
        self.assertEqual(attested_by(entry, _SALT_KEY), (_RDKIT,))
        self.assertEqual(attested_by(entry, _RATIOLESS_KEY), ())


class DabcoLosesTheNameDerivedAnswerTestCase(unittest.TestCase):
    """The same test, pointing the other way.

    The half that stops this becoming "the name always wins".  If it ever
    passes for the same reason as the salt case, the rule has started reading
    which stage produced a value rather than what the registry registered.
    """

    def setUp(self):
        self.transformer = WithholdContradictedCompositionTransformer()
        self.transformer._registry = _index(**{_DABCO_CAS: _DABCO_REGISTERED})
        self.flow = _flow(
            cas=[_DABCO_CAS],
            properties=_properties([
                (CHEMROF_MOLECULAR_FORMULA,
                 [(_DABCO_FORMULA, _CHEBI), (_MISREAD_FORMULA, _RDKIT)]),
                (CHEMROF_INCHI2D_KEY_STRING,
                 [(_DABCO_KEY, _CHEBI), (_MISREAD_KEY, _RDKIT)]),
            ]),
        )
        self.result = _run(self.transformer, self.flow)

    def test_the_registry_formula_survives_alone(self):
        self.assertEqual(
            self.result[CHEMROF_MOLECULAR_FORMULA]["@value"], [_DABCO_FORMULA]
        )

    def test_the_name_derived_key_goes(self):
        self.assertEqual(
            self.result[CHEMROF_INCHI2D_KEY_STRING]["@value"], [_DABCO_KEY]
        )


class WhatIsLeftAloneTestCase(unittest.TestCase):
    """Every refusal, because a rule that withdraws data is cheapest to make
    pass by withdrawing more."""

    def setUp(self):
        self.transformer = WithholdContradictedCompositionTransformer()

    def test_a_substance_with_one_formula_is_untouched_even_if_it_disagrees(self):
        # #310 is about a record answering twice.  Correcting a record that
        # answers once would leave it with no formula at all.
        self.transformer._registry = _index(**{_NICKEL_CAS: _NICKEL_REGISTERED})
        flow = _flow(cas=[_NICKEL_CAS], properties=_properties([
            (CHEMROF_MOLECULAR_FORMULA, [(_RATIOLESS_FORMULA, _PUBCHEM)]),
        ]))
        self.assertIsNone(_run(self.transformer, flow))

    def test_a_substance_the_registry_says_nothing_about_is_untouched(self):
        self.transformer._registry = _index()
        flow = _flow(cas=[_NICKEL_CAS], properties=_properties([
            (CHEMROF_MOLECULAR_FORMULA,
             [(_SALT_FORMULA, _RDKIT), (_RATIOLESS_FORMULA, _PUBCHEM)]),
        ]))
        self.assertIsNone(_run(self.transformer, flow))

    def test_a_flow_with_no_registry_number_is_untouched(self):
        self.transformer._registry = _index(**{_NICKEL_CAS: _NICKEL_REGISTERED})
        flow = _flow(cas=[], properties=_properties([
            (CHEMROF_MOLECULAR_FORMULA,
             [(_SALT_FORMULA, _RDKIT), (_RATIOLESS_FORMULA, _PUBCHEM)]),
        ]))
        self.assertIsNone(_run(self.transformer, flow))

    def test_where_the_registry_backs_nothing_published_the_row_stays_open(self):
        # Disodium tetraborate's shape: the registry agrees with neither value,
        # so the disagreement is real and belongs to a curator.  Nothing is
        # decided on the registry's authority alone.
        self.transformer._registry = _index(**{_NICKEL_CAS: "C99H2O4"})
        flow = _flow(cas=[_NICKEL_CAS], properties=_properties([
            (CHEMROF_MOLECULAR_FORMULA,
             [(_SALT_FORMULA, _RDKIT), (_RATIOLESS_FORMULA, _PUBCHEM)]),
        ]))
        self.assertIsNone(_run(self.transformer, flow))

    def test_a_value_nobody_attested_is_never_withdrawn(self):
        # A record written before per-value attribution existed says nothing
        # about where its values came from, and silence must not read as "no
        # support".
        self.transformer._registry = _index(**{_NICKEL_CAS: _NICKEL_REGISTERED})
        properties = _properties([
            (CHEMROF_MOLECULAR_FORMULA,
             [(_SALT_FORMULA, _RDKIT), (_RATIOLESS_FORMULA, _PUBCHEM)]),
        ])
        properties[CHEMROF_INCHI2D_KEY_STRING] = {
            "@id": CHEMROF_INCHI2D_KEY_STRING,
            "@value": [_SALT_KEY, _RATIOLESS_KEY],
        }
        result = _run(self.transformer, _flow(cas=[_NICKEL_CAS], properties=properties))
        self.assertEqual(
            result[CHEMROF_INCHI2D_KEY_STRING]["@value"], [_SALT_KEY, _RATIOLESS_KEY]
        )

    def test_a_source_that_also_got_something_right_keeps_its_other_values(self):
        # PubChem attests both the contradicted formula and the surviving one,
        # so its disagreement is with itself and this rule cannot settle it.
        self.transformer._registry = _index(**{_NICKEL_CAS: _NICKEL_REGISTERED})
        flow = _flow(cas=[_NICKEL_CAS], properties=_properties([
            (CHEMROF_MOLECULAR_FORMULA,
             [(_SALT_FORMULA, _PUBCHEM), (_RATIOLESS_FORMULA, _PUBCHEM)]),
            (CHEMROF_INCHI2D_KEY_STRING,
             [(_SALT_KEY, _PUBCHEM), (_RATIOLESS_KEY, _PUBCHEM)]),
        ]))
        self.assertIsNone(_run(self.transformer, flow))

    def test_the_last_value_of_a_property_is_never_withdrawn(self):
        # The SMILES here is the withdrawn source's alone, and taking it would
        # leave the substance with no drawing at all.
        self.transformer._registry = _index(**{_NICKEL_CAS: _NICKEL_REGISTERED})
        properties = _properties([
            (CHEMROF_MOLECULAR_FORMULA,
             [(_SALT_FORMULA, _RDKIT), (_RATIOLESS_FORMULA, _PUBCHEM)]),
            (CHEMROF_SMILES_STRING, [("CC(=O)O.[Ni]", _PUBCHEM)]),
        ])
        result = _run(self.transformer, _flow(cas=[_NICKEL_CAS], properties=properties))
        self.assertEqual(result[CHEMROF_SMILES_STRING]["@value"], ["CC(=O)O.[Ni]"])

    def test_two_registry_numbers_that_disagree_keep_both_answers(self):
        # A flow carrying two numbers with different compositions is a
        # disagreement of its own, and not one to settle by withdrawing data.
        self.transformer._registry = _index(**{
            _NICKEL_CAS: _NICKEL_REGISTERED,
            "14998-37-9": "C<sub>2</sub>H<sub>4</sub>NiO<sub>2</sub>",
        })
        flow = _flow(cas=[_NICKEL_CAS, "14998-37-9"], properties=_properties([
            (CHEMROF_MOLECULAR_FORMULA,
             [(_SALT_FORMULA, _RDKIT), (_RATIOLESS_FORMULA, _PUBCHEM)]),
        ]))
        self.assertIsNone(_run(self.transformer, flow))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
