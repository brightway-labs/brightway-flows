"""The shortlist has to find the narrowings without swallowing the population.

`curation.qualifier_loss` answers the question the CC/ChEBI identity audit
cannot: does the replacement drop a qualifier the current name carries?  It
shortlists for a chemist and decides nothing, so both directions matter here --
the archetypal scope losses have to be reported, and the systematic-to-common
improvements the rule exists to make have to stay off the list, or the shortlist
is the whole population again and nobody reads it.

The misfires #220 hit while trying to use this kind of pattern as a *gate* are
pinned too: `C4-6` read as an isotope, `beta-1,2,3,4,5,6-` read as one as well.
"""

import unittest

from brightway_flows.curation.qualifier_loss import (
    assess,
    is_reduction,
    qualifier_losses,
)


def _detected(current, replacement):
    return {loss.detector: set(loss.tokens) for loss in qualifier_losses(current, replacement)}


class ScopeLossTestCase(unittest.TestCase):
    def test_the_archetype_is_reported(self):
        """`Xylene (all isomers)` -> `Xylene`: the case the gate exists for."""
        detected = _detected("Xylene (all isomers)", "Xylene")
        self.assertEqual(detected["scope"], {"all isomers"})
        self.assertEqual(detected["parenthetical"], {"all isomers"})

    def test_a_scope_phrase_is_reported_once(self):
        """`all isomers` and `isomers` are one loss, not two.

        Both phrases match, and a row that says the same thing twice reads as
        two findings to the chemist working through it.
        """
        self.assertEqual(_detected("Xylene (all isomers)", "Xylene")["scope"], {"all isomers"})

    def test_a_kept_qualifier_is_not_a_loss(self):
        self.assertEqual(_detected("Xylene (all isomers)", "Xylenes (all isomers)"), {})

    def test_a_locant_is_reported(self):
        self.assertEqual(_detected("3-Methylpentane", "Methyl Pentane")["locant"], {"3"})
        self.assertEqual(
            _detected("1,1,1-Trichloroethane", "HCFC-140")["locant"], {"1,1,1"}
        )

    def test_an_allotrope_prefix_is_reported(self):
        self.assertEqual(_detected("Plutonium-alpha", "Plutonium")["stereo"], {"alpha"})

    def test_a_hydrate_word_is_reported(self):
        self.assertEqual(
            _detected("Sodium chloride dihydrate", "Sodium chloride")["salt_hydrate_ion"],
            {"dihydrate"},
        )

    def test_a_comma_clause_is_reported_but_a_locant_comma_is_not(self):
        """`, ` separates clauses; the commas in `1,1,1-` separate locants."""
        self.assertEqual(
            _detected("Sodium metaborate, anhydrous", "Sodium metaborate")["comma_clause"],
            {"anhydrous"},
        )
        self.assertNotIn("comma_clause", _detected("1,1,1-Trichloroethane", "Trichloroethane"))

    def test_a_pure_spelling_change_reports_nothing(self):
        self.assertEqual(_detected("Acryolonitrile", "Acrylonitrile"), {})
        self.assertEqual(_detected("Systhane", "Myclobutanil"), {})
        self.assertEqual(_detected("Kresoxim Methyl", "Kresoxim-methyl"), {})


class MisfiresOfTheAbandonedHeuristicTestCase(unittest.TestCase):
    """#220 abandoned this pattern as a gate after it misread these names.

    They are pinned because the pattern is back -- as a shortlist -- and the
    reason it is allowed back is that its misfires now cost a chemist a glance
    instead of blocking a correct rename.  A misfire that changes what is
    *published* would be the old defect returning.
    """

    def test_a_carbon_range_is_a_carbon_range_and_not_an_isotope(self):
        detected = _detected("Fatty acids, C13-15", "Fatty acids")
        self.assertEqual(detected["carbon_range"], {"c13-15"})
        self.assertNotIn("locant", detected)

    def test_a_greek_stereo_prefix_respelt_in_ascii_is_not_a_loss(self):
        """`alpha-` and `α-` are the same descriptor, and the rename rule
        compares them that way, so respelling one as the other drops nothing."""
        self.assertEqual(_detected("alpha-Pinene", "α-Pinene"), {})

    def test_the_locants_of_a_hexachlorocyclohexane_are_still_locants(self):
        detected = _detected(
            "beta-1,2,3,4,5,6-Hexachlorocyclohexane", "beta-Hexachlorocyclohexane"
        )
        self.assertEqual(detected["locant"], {"1,2,3,4,5,6"})
        self.assertNotIn("carbon_range", detected)


class ReductionTestCase(unittest.TestCase):
    """What separates a dropped locant that matters from one that does not."""

    def test_the_same_name_minus_a_locant_is_a_reduction(self):
        self.assertTrue(is_reduction("3-Methylpentane", "Methyl Pentane"))

    def test_the_same_name_minus_a_scope_qualifier_is_a_reduction(self):
        self.assertTrue(is_reduction("Xylene (all isomers)", "Xylene"))

    def test_a_common_name_replacing_a_systematic_one_is_not(self):
        """The improvement the rule exists to make. It drops eleven locants."""
        self.assertFalse(is_reduction(
            "(+/-) 2-(2,4-dichlorophenyl)-3-(1h-1,2,4-triazole-1-yl)propyl-"
            "1,1,2,2-tetrafluoroethylether",
            "Tetraconazole",
        ))

    def test_a_designation_replacing_a_systematic_name_is_not(self):
        self.assertFalse(is_reduction("1,1,1-Trichloroethane", "HCFC-140"))


class ShortlistTestCase(unittest.TestCase):
    def test_a_reduction_that_drops_anything_is_shortlisted(self):
        self.assertTrue(assess("3-Methylpentane", "Methyl Pentane").shortlisted)

    def test_a_systematic_to_common_rename_is_not_shortlisted_for_its_locants(self):
        """Otherwise the shortlist is 63% of the population and reads as noise."""
        assessment = assess(
            "(+/-) 2-(2,4-dichlorophenyl)-3-(1h-1,2,4-triazole-1-yl)propyl-"
            "1,1,2,2-tetrafluoroethylether",
            "Tetraconazole",
        )
        self.assertTrue(assessment.losses)
        self.assertFalse(assessment.shortlisted)

    def test_a_scope_word_shortlists_whatever_the_names_share(self):
        """`, mixed Isomers` says what the flow covers, and a replacement that
        drops it narrows the flow even when it is otherwise a different name."""
        assessment = assess("3,7,11-trimethyldodeca-1,6,10-trien-3-ol, mixed Isomers", "Nerolidol")
        self.assertFalse(assessment.reduction)
        self.assertTrue(assessment.shortlisted)

    def test_a_salt_or_ion_word_shortlists_the_same_way(self):
        self.assertTrue(assess("Acrylate, Ion", "Acrylic acid").shortlisted)

    def test_a_pair_that_loses_nothing_is_not_shortlisted(self):
        assessment = assess("Systhane", "Myclobutanil")
        self.assertEqual(assessment.losses, ())
        self.assertFalse(assessment.shortlisted)


if __name__ == "__main__":
    unittest.main()
