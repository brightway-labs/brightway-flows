"""A substance's name counts its atoms, and a structure may not disagree.

#129.  A name-to-structure parser cannot tell `antimonous sulfide` -- which is
Sb2S3 -- from `antimony monosulfide`, because the name it is given does not say
how many sulfur atoms there are.  It returns the same one-to-one structure for
both, and that structure was published as antimony trisulfide's.

The half worth testing hardest is where the rule must **decline**, because it
withdraws a published structure and a rule that over-fires deletes correct
chemistry.  The first draft did exactly that: it read a missing multiplicative
prefix as "one" and condemned eleven correct formulas, `hydrogen sulfide` and
`lanthanum oxide` among them.  Those cases are the second class below.
"""

from __future__ import annotations

import unittest

from brightway_flows.domain.composition import (
    corroborates_name,
    contradicts_name,
    formula_composition,
    stated_composition,
)


class ANameStatesHowManyAtoms(unittest.TestCase):
    """The half #129 is about."""

    def test_a_prefix_on_the_anion(self):
        self.assertEqual(
            stated_composition("antimony trisulfide"), {"Sb": None, "S": 3}
        )

    def test_a_prefix_on_both(self):
        self.assertEqual(
            stated_composition("dibismuth trisulphide"), {"Bi": 2, "S": 3}
        )

    def test_the_other_spelling_of_sulfur(self):
        self.assertEqual(
            stated_composition("diphosphorus pentasulphide"), {"P": 2, "S": 5}
        )

    def test_an_element_named_by_a_stem_that_is_not_its_name(self):
        # `antimonide` is not `antimony` with a suffix, which is why the stems
        # are listed rather than truncated.
        self.assertEqual(
            stated_composition("trisodium antimonide"), {"Na": 3, "Sb": None}
        )

    def test_a_longer_prefix_is_not_read_as_a_shorter_one(self):
        # `hexa` must not be read as `he`, which names nothing anyway, nor
        # `deca` as `de`.
        self.assertEqual(stated_composition("tungsten hexafluoride"), {"W": None, "F": 6})


class AnElidedOxideNameIsStillRead(unittest.TestCase):
    """`monoxide` shares its `o` with the prefix, and these lists carry it.

    Without spelling them out, `carbon monoxide` reads as a prefix `mono`
    followed by `xide`, which names nothing -- so the whole name would say
    nothing and never be checked.
    """

    def test_monoxide(self):
        self.assertEqual(
            stated_composition("carbon monoxide"), {"C": None, "O": 1}
        )
        self.assertFalse(contradicts_name("CO", "carbon monoxide"))

    def test_pentoxide_as_the_dimer_it_is_published_as(self):
        self.assertFalse(contradicts_name("P4O10", "diphosphorus pentoxide"))

    def test_tetroxide(self):
        self.assertEqual(
            stated_composition("osmium tetroxide"), {"Os": None, "O": 4}
        )

    def test_dioxide_needs_no_elision_and_is_unchanged(self):
        self.assertEqual(
            stated_composition("nitrogen dioxide"), {"N": None, "O": 2}
        )


class AMissingPrefixStatesNothing(unittest.TestCase):
    """The distinction the first draft got wrong, and the reason for this file.

    Every name here is a correct traditional name for a compound whose formula
    has more atoms than the name mentions.  None of them states a count for its
    first element, and reading one as "one" makes each substance contradict its
    own true formula.
    """

    def test_hydrogen_sulfide(self):
        self.assertIsNone(stated_composition("hydrogen sulfide"))
        self.assertFalse(contradicts_name("H2S", "hydrogen sulfide"))

    def test_lanthanum_oxide(self):
        self.assertIsNone(stated_composition("lanthanum oxide"))
        self.assertFalse(contradicts_name("La2O3", "lanthanum oxide"))

    def test_silicon_nitride(self):
        self.assertFalse(contradicts_name("N4Si3", "silicon nitride"))

    def test_magnesium_chloride(self):
        self.assertFalse(contradicts_name("Cl2Mg", "magnesium chloride"))

    def test_an_unstated_count_beside_a_stated_one_is_not_checked(self):
        # `arsenic trioxide` is As2O3.  Its three oxygens are stated and agree;
        # its two arsenics are not stated at all, so nothing is asked of them.
        self.assertFalse(contradicts_name("As2O3", "arsenic trioxide"))


class AStructureThatMiscountsIsCaught(unittest.TestCase):
    """The three the parser got wrong, as they were published."""

    def test_antimony_trisulfide(self):
        self.assertTrue(contradicts_name("SSb+", "Antimony Trisulfide"))

    def test_dibismuth_trisulphide(self):
        self.assertTrue(contradicts_name("BiS+", "Dibismuth Trisulphide"))

    def test_bismuth_trioxide(self):
        self.assertTrue(contradicts_name("BiO+", "Bismuth Trioxide"))

    def test_the_charge_does_not_stop_the_count(self):
        # RDKit writes these formulas charged, so a rule that refused to count
        # a charged formula would never fire on the case it exists for.
        self.assertEqual(formula_composition("SSb+"), {"S": 1, "Sb": 1})


class AWholeMultipleOfTheStatedCountsAgrees(unittest.TestCase):
    """Why the comparison is on the ratio and not the raw number.

    A correct formula is often written as a multiple of what the name states.
    Refusing those would withdraw structures that are right.
    """

    def test_a_dimer_of_what_the_name_states(self):
        self.assertFalse(contradicts_name("P4S10", "diphosphorus pentasulphide"))

    def test_the_same_substance_written_plainly(self):
        self.assertFalse(contradicts_name("P2S5", "diphosphorus pentasulphide"))

    def test_a_dimer_where_only_the_anion_is_counted(self):
        self.assertFalse(contradicts_name("Bi4S6", "dibismuth trisulphide"))

    def test_a_multiple_of_one_element_only_is_not_a_multiple(self):
        # Six sulfurs against two bismuths is not two Bi2S3 units; the two
        # stated counts have to scale together or they disagree.
        self.assertTrue(contradicts_name("Bi2S6", "dibismuth trisulphide"))


class CorroborationIsStrongerThanNotContradicting(unittest.TestCase):
    """The gate on publishing a registry's composition as a formula (#129).

    "Does not contradict" is nearly always true and is therefore nearly no
    evidence: a name that says nothing about composition contradicts nothing.
    Corroboration asks the name to *state* a count that agrees.
    """

    def test_a_name_that_states_the_count_corroborates(self):
        # CAS registers 1345-04-6 as `S3Sb2`; the name says three sulfurs.
        self.assertTrue(corroborates_name("S3Sb2", "Antimony Trisulfide"))

    def test_a_name_that_states_nothing_corroborates_nothing(self):
        # `Zn3P2` is right and `zinc phosphide` says so nowhere.  Not a
        # contradiction, and not evidence either.
        self.assertFalse(corroborates_name("P2Zn3", "Zinc phosphide"))
        self.assertFalse(contradicts_name("P2Zn3", "Zinc phosphide"))

    def test_an_ion_is_not_corroborated_by_its_element(self):
        # `Rhenium(2+)` carries rhenium metal's registry number.
        self.assertFalse(corroborates_name("Re", "Rhenium(2+)"))

    def test_an_aggregate_is_not_corroborated_by_its_element(self):
        self.assertFalse(corroborates_name("U", "Uranium Alpha"))

    def test_a_disagreeing_count_does_not_corroborate(self):
        self.assertFalse(corroborates_name("SSb", "Antimony Trisulfide"))

    def test_a_formula_naming_other_elements_does_not_corroborate(self):
        self.assertFalse(corroborates_name("H3AsO3", "Arsenic Trioxide"))


class TheRuleDeclinesWhereItCannotJudge(unittest.TestCase):
    """A name or formula this cannot read is not a name or formula it refutes."""

    def test_a_name_that_is_not_a_binary_compound(self):
        # Two words, a multiplicative prefix, and not one of these: `thiuram`
        # is not an element, and its "monosulphide" counts a bridging atom
        # rather than the molecule's three sulfurs.
        self.assertIsNone(stated_composition("tetramethylthiuram monosulphide"))
        self.assertFalse(
            contradicts_name("C6H12N2S3", "tetramethylthiuram monosulphide")
        )

    def test_a_name_of_one_word(self):
        self.assertIsNone(stated_composition("glucose"))

    def test_a_name_of_three_words(self):
        self.assertIsNone(stated_composition("sodium hydrogen carbonate"))

    def test_a_word_that_is_only_a_prefix(self):
        # `tri` alone leaves nothing to name an element.
        self.assertIsNone(stated_composition("tri trisulfide"))

    def test_an_element_paired_with_itself(self):
        self.assertIsNone(stated_composition("disulfur disulfide"))

    def test_a_formula_naming_other_elements_is_not_judged(self):
        # `H3AsO3` is arsenous acid, not a reading of arsenic trioxide.  A
        # formula about different elements is a question this cannot answer.
        self.assertFalse(contradicts_name("H3AsO3", "arsenic trioxide"))

    def test_a_mixture_written_as_one_string(self):
        self.assertIsNone(formula_composition("2Cu.S"))
        self.assertIsNone(formula_composition("C39H41N3O6S2.Na"))

    def test_a_bracketed_formula(self):
        self.assertIsNone(formula_composition("Ca(OH)2"))

    def test_an_empty_formula(self):
        self.assertIsNone(formula_composition(""))

    def test_an_empty_name(self):
        self.assertIsNone(stated_composition(""))


if __name__ == "__main__":
    unittest.main()
