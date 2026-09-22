"""A substance whose formula carries a charge is an ion, not a neutral molecule.

#326. An ion is an atom or molecule carrying an electric charge; a neutral
molecule, by definition, is not.  Seven substances stated a formula that plainly
carries one -- `BO3-3` is borate, `Ti+4` is the titanium(4+) cation -- and every
one was typed `NeutralMolecule`, because the typing rules read the charge from
`elemental_charge` and most objects do not carry that property.

The type is published *and used*: the ion layer finds an ion by resolving its
base name against an object typed `ChemicalElement`, and the catch-all guard from
#76/#604 keys on whether a target is typed as a grouping class.  A wrong type is
an input to later decisions as well as a wrong statement.

The half worth testing is where the rule declines to fire, because the evidence
it reads is sometimes wrong or self-contradictory and a charge asserted from that
is worse than none.
"""

from __future__ import annotations

import unittest

from brightway_flows.domain.vocabulary import CHEMROF_MOLECULAR_FORMULA
from brightway_flows.pipeline.semantic_typing import _charge_from_formulas


def _props(*formulas):
    return {CHEMROF_MOLECULAR_FORMULA: {"@value": list(formulas)}}


class ACharge_IsReadOffTheFormula(unittest.TestCase):
    """The half #326 is about."""

    def test_an_anion(self):
        self.assertEqual(_charge_from_formulas(_props("BO3-3")), -3)

    def test_a_cation(self):
        self.assertEqual(_charge_from_formulas(_props("Ti+4")), 4)

    def test_a_bare_sign_means_one(self):
        # `CNS-` is thiocyanate at -1: the magnitude is implied, not absent.
        self.assertEqual(_charge_from_formulas(_props("CNS-")), -1)

    def test_a_polyatomic_anion(self):
        self.assertEqual(_charge_from_formulas(_props("CH3BO3-2")), -2)

    def test_every_stated_formula_may_agree(self):
        self.assertEqual(_charge_from_formulas(_props("Ti+4", "Ti+4")), 4)


class TheRuleDeclinesOnBadEvidence(unittest.TestCase):
    """The half that stops a charge being asserted from evidence that is wrong."""

    def test_two_formulas_of_opposite_sign_are_not_a_charge(self):
        # `Phosphonic Acid, Dibutyl Ester` states `C8H18O3P+` *and*
        # `C8H18O3P-`: two readings of one substance, and neither is evidence.
        # Taking the first would publish whichever the enrichment happened to
        # write down first.
        self.assertIsNone(
            _charge_from_formulas(_props("C8H18O3P+", "C8H18O3P-"))
        )

    def test_two_formulas_of_different_magnitude_are_not_a_charge(self):
        self.assertIsNone(_charge_from_formulas(_props("Fe+2", "Fe+3")))

    def test_an_unsigned_formula_beside_a_signed_one_is_a_disagreement(self):
        # A neutral reading against a charged one.  The element `Aluminium`
        # states `Al`; its ion states `Al+3`; an object stating both is not
        # saying it has a charge.
        self.assertIsNone(_charge_from_formulas(_props("Al", "Al+3")))

    def test_a_neutral_formula_yields_nothing(self):
        self.assertIsNone(_charge_from_formulas(_props("C6H12O6")))

    def test_no_formula_yields_nothing(self):
        self.assertIsNone(_charge_from_formulas({}))

    def test_a_charge_of_zero_is_not_a_charge(self):
        self.assertIsNone(_charge_from_formulas(_props("Na+0")))


class AWrongStructureIsWithdrawnRatherThanExcepted(unittest.TestCase):
    """Why this rule needs no list of substances to skip.

    It briefly had one.  `Antimony Trisulfide` stated the formula `SSb+`, which
    reads as a cation and is wrong: Sb2S3 is neutral, and the structure was a
    misreading of a synonym that describes antimony *mono*sulfide.  Naming the
    substance here would have been a rule about a name rather than about
    chemistry, and it would have left the wrong structure published.

    #129 withdraws the structure instead, at the parser that produced it, so
    there is nothing left here to except.  This rule stays as it should be:
    a formula that states a charge means the substance carries one.
    """

    def test_such_a_formula_still_reads_as_a_cation(self):
        # Unchanged and correct.  Anything stating `SSb+` *is* saying it is a
        # cation -- the defect was never the reading, it was the formula.
        self.assertEqual(_charge_from_formulas(_props("SSb+")), 1)


if __name__ == "__main__":
    unittest.main()
