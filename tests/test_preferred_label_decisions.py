"""A preferred label is replaced only when a curator has approved it (#219).

`consensus_match` derives better names from Common Chemistry, ChEBI and PubChem
and rewrites the preferred label of every member of a flow object with them. In
one full run that produced `Systhane` -> `Myclobutanil` alongside
`Xylene (all isomers)` -> `Xylene`, and the two are not separable by rule: a
heuristic over locants, designations and scope qualifiers took three iterations
to stop misfiring on real names and still blocked good renames.

So the rules propose and `preferred-label-decisions.json` decides. What these
pin is the property that makes that safe -- an undecided pair is *not* applied --
and the fact that one ruling covers every spelling of the same pair.
"""

import tempfile
import unittest
from pathlib import Path

import orjson

from brightway_flows.domain.preferred_label_decisions import (
    APPROVE,
    DEFAULT_APPROVED_RULES,
    REJECT,
    LabelRuling,
    UndecidedLabelReplacement,
    decision_key,
    load_preferred_label_decisions,
    rule_on_replacement,
)
from brightway_flows.flow_layers.provenance import ELEMENT_ENRICHMENT_GENERATED_BY
from brightway_flows.transformers.consensus_match import ConsensusMatchTransformer


class DecisionKeyTestCase(unittest.TestCase):
    def test_case_and_spacing_do_not_make_a_second_pair(self):
        """One ruling has to cover `HCFC-140` and `Hcfc-140` -- the pair whose
        two spellings made #219's "same input, different output" look like
        non-determinism in the caser."""
        self.assertEqual(
            decision_key("1,1,1-Trichloroethane", "HCFC-140"),
            decision_key("1,1,1-trichloroethane", "Hcfc-140"),
        )

    def test_markup_does_not_make_a_second_pair(self):
        self.assertEqual(
            decision_key("Hydrocarbons, C<sub>4-6</sub>", "Hexane"),
            decision_key("Hydrocarbons, C4-6", "Hexane"),
        )

    def test_direction_matters(self):
        """Approving A -> B must not approve B -> A."""
        self.assertNotEqual(decision_key("Xylene", "Xylene (all isomers)"),
                            decision_key("Xylene (all isomers)", "Xylene"))


class LoadingTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)

    def _write(self, rows) -> Path:
        path = Path(self._tmp.name) / "decisions.json"
        path.write_bytes(orjson.dumps({"schema_version": 1, "decisions": rows}))
        return path

    def test_approvals_and_rejections_are_both_recorded(self):
        index = load_preferred_label_decisions(self._write([
            {"current": "Systhane", "replacement": "Myclobutanil", "decision": APPROVE},
            {"current": "Xylene (all isomers)", "replacement": "Xylene", "decision": REJECT},
        ]))
        self.assertTrue(index[decision_key("Systhane", "Myclobutanil")].approved)
        self.assertFalse(index[decision_key("Xylene (all isomers)", "Xylene")].approved)

    def test_an_unrecognised_decision_is_dropped_rather_than_guessed(self):
        """A typo must not read as "approve".  Dropping the row leaves the pair
        undecided, which refuses the rename -- the safe direction."""
        index = load_preferred_label_decisions(self._write([
            {"current": "A", "replacement": "B", "decision": "aprove"},
        ]))
        self.assertEqual(index, {})

    def test_a_row_missing_a_side_is_dropped(self):
        index = load_preferred_label_decisions(self._write([
            {"current": "", "replacement": "B", "decision": APPROVE},
            {"current": "A", "replacement": "", "decision": APPROVE},
        ]))
        self.assertEqual(index, {})

    def test_a_missing_file_yields_no_decisions(self):
        """Which, with default-refuse, replaces no label at all.  That is the
        safe direction to fail in."""
        self.assertEqual(
            load_preferred_label_decisions(Path("/nonexistent/decisions.json")), {}
        )


class DefaultByRuleTestCase(unittest.TestCase):
    """Where there is no ruling, the fallback depends on the proposing rule.

    Auditing one full run against Common Chemistry and ChEBI -- is each name a
    name the cited CAS actually has? -- put `cc_chebi_agreement` at 0 identity
    errors in 724 pairs and the PubChem-backed `entropy` rule at 80 in 114.  One
    default for both either publishes `'Sodium Chloride' -> 'sea water'` or
    discards 9,375 correct names to prevent it.

    `entropy` was removed outright in #222 rather than left to the gate, so the
    untrusted rule exercised here is `multi_source_consensus`.  The pairs are
    still the audit's, because they are what the split was measured on.
    """

    def setUp(self):
        self.transformer = ConsensusMatchTransformer()
        self.transformer.gate.decisions = {}
        self.transformer.gate.undecided = []

    def _approved(self, current, replacement, rule):
        return self.transformer.gate.approves(
            "uuid-1", current, replacement, rule=rule,
        )

    def test_an_undecided_pair_from_a_trusted_rule_is_applied(self):
        self.assertTrue(self._approved("Systhane", "Myclobutanil", "cc_chebi_agreement"))
        self.assertEqual(self.transformer.gate.undecided, [])

    def test_an_undecided_pair_from_an_untrusted_rule_is_deferred(self):
        self.assertFalse(
            self._approved("Sodium Chloride", "sea water", "multi_source_consensus")
        )
        self.assertEqual(len(self.transformer.gate.undecided), 1)
        self.assertEqual(
            self.transformer.gate.undecided[0].replacement, "sea water"
        )

    def test_every_rule_is_untrusted_unless_named(self):
        self.assertFalse(self._approved("A", "B", "multi_source_consensus"))

    def test_a_rejection_beats_the_trusted_default(self):
        """A curator's `reject` has to win, or the rulings stop meaning anything."""
        self.transformer.gate.decisions = load_preferred_label_decisions()
        self.assertFalse(
            self._approved("Xylene (all isomers)", "Xylene", "cc_chebi_agreement")
        )
        self.assertEqual(self.transformer.gate.undecided, [])

    def test_a_case_only_difference_needs_no_ruling_from_any_rule(self):
        self.assertTrue(self._approved("Benzene", "benzene", "multi_source_consensus"))
        self.assertEqual(self.transformer.gate.undecided, [])

    def test_only_the_audited_rule_is_trusted(self):
        """Adding a rule here is a claim about that rule's error rate, and wants
        the same measurement behind it.  Pinned so it has to be deliberate."""
        self.assertEqual(DEFAULT_APPROVED_RULES, frozenset({"cc_chebi_agreement"}))

    def test_a_queued_pair_carries_the_cas_it_was_keyed_on(self):
        """Ruling on a rename means asking whether the replacement is a name
        this substance has.  Without the CAS the file states the decision and
        withholds the evidence."""
        self.transformer.gate.approves(
            "uuid-1", "Sodium Chloride", "sea water",
            rule="multi_source_consensus", cas="7647-14-5",
        )
        self.assertEqual(
            self.transformer.gate.undecided[0].cas, "7647-14-5"
        )


class UndecidedPairTestCase(unittest.TestCase):
    """The queue is deduplicated by pair, so its evidence has to survive that."""

    def setUp(self):
        self.transformer = ConsensusMatchTransformer()
        self.transformer.gate.decisions = {}
        self.transformer.review = []

    def _pairs(self, queued):
        self.transformer.gate.undecided = queued
        return self.transformer.undecided_label_pairs()

    def _row(self, uuid, current, replacement, cas):
        return UndecidedLabelReplacement(
            uuid=uuid, rule="multi_source_consensus", current=current,
            replacement=replacement, cas=cas,
        )

    def test_one_pair_from_several_flows_collapses_to_one_row(self):
        pairs = self._pairs([
            self._row("u1", "Sodium Chloride", "sea water", "7647-14-5"),
            self._row("u2", "Sodium Chloride", "sea water", "7647-14-5"),
        ])
        self.assertEqual(len(pairs), 1)
        self.assertEqual(pairs[0].flow_count, 2)
        self.assertEqual(pairs[0].cas_numbers, ["7647-14-5"])
        self.assertEqual(pairs[0].example_uuid, "u1")

    def test_a_pair_spanning_several_cas_keeps_all_of_them(self):
        """A ruling is keyed on the pair, so it binds every CAS that produced
        it.  Showing one would hide the case where the pair means different
        things for different substances."""
        pairs = self._pairs([
            self._row("u1", "Butene", "1-butene", "25167-67-3"),
            self._row("u2", "Butene", "1-butene", "106-98-9"),
        ])
        self.assertEqual(pairs[0].cas_numbers, ["106-98-9", "25167-67-3"])
        # The pair carries every CAS, not the one flow's; a single `cas` field
        # would be the bug this collapse could introduce.
        self.assertNotIn("cas", pairs[0].to_dict())


class ShippedDecisionsTestCase(unittest.TestCase):
    """The checked-in file, which is data rather than code."""

    def setUp(self):
        self.index = load_preferred_label_decisions()

    def test_the_renames_that_lose_specificity_are_rejected(self):
        for current, replacement in (
            ("3-Methylpentane", "Methyl Pentane"),
            ("Xylene (all isomers)", "Xylene"),
            # A range of C4-C6 dicarboxylic acids is not the C5 one.  Same error
            # as Xylene (all isomers) -> Xylene, and from the same rule that
            # produced 'Sodium Chloride' -> 'sea water'.
            ("Carboxylic Acids, Di-, C4-6", "Pentanedioic acid"),
        ):
            with self.subTest(f"{current} -> {replacement}"):
                decision = self.index.get(decision_key(current, replacement))
                self.assertIsNotNone(decision)
                self.assertFalse(decision.approved)

    def test_the_plutonium_alpha_ruling_is_retired(self):
        """#238 removed it, and it must not come back as a fix for the label.

        `Plutonium-alpha` no longer resolves to a `ChemicalElement`-typed flow
        object, so the element pass never proposes the rename and there is
        nothing left to rule on.  Re-adding the row would hide a regression in
        the split rather than guard against one: with no ruling the element
        pass defers and files a review item, which is the visible failure.
        """
        self.assertIsNone(
            self.index.get(decision_key("Plutonium-alpha", "Plutonium"))
        )

    def test_the_titanium_ion_rename_is_rejected_and_the_tin_one_is_not(self):
        """#143: a stated charge does not rename a label that disambiguates nothing.

        The #128 approval of `Titanium, ion` -> `Titanium(4+)` never applied:
        the ion pass reads the charge from `elemental_charge`, which only ChEBI
        enrichment writes, and ChEBI has no entry for 22541-75-9 -- so the row
        sat inert, waiting to fire the moment a later change made the charge
        visible.  #143 reversed it to a rejection under the disambiguation
        rule: a fallback ion name is corrected only where the element has one
        possible ionic form, or where the generic name sits beside a published
        charged sibling.  Tin is the sibling case -- `Tin, ion` was published
        beside `Tin(2+)` -- and its approval must stand beside titanium's
        rejection, because the pair is what states the rule rather than a
        preference about one element.
        """
        rejected = self.index.get(decision_key("Titanium, ion", "Titanium(4+)"))
        self.assertIsNotNone(rejected)
        self.assertFalse(rejected.approved)
        approved = self.index.get(decision_key("Tin, ion", "Tin(4+)"))
        self.assertIsNotNone(approved)
        self.assertTrue(approved.approved)

    def test_the_renames_that_correct_a_name_are_approved(self):
        for current, replacement in (
            ("Acryolonitrile", "Acrylonitrile"),
            ("Systhane", "Myclobutanil"),
            ("Sulphuric Acid", "Sulfuric acid"),
            ("beta-1,2,3,4,5,6-hexachlorocyclohexane", "β-hexachlorocyclohexane"),
        ):
            with self.subTest(f"{current} -> {replacement}"):
                decision = self.index.get(decision_key(current, replacement))
                self.assertIsNotNone(decision)
                self.assertTrue(decision.approved)

    def test_both_spellings_of_the_hcfc_pair_resolve_to_one_ruling(self):
        for replacement in ("HCFC-140", "Hcfc-140"):
            with self.subTest(replacement):
                decision = self.index.get(
                    decision_key("1,1,1-Trichloroethane", replacement)
                )
                self.assertIsNotNone(decision)
                self.assertFalse(decision.approved)

    def test_every_decision_carries_a_reason(self):
        """The file is the record of why a published name is what it is."""
        for decision in self.index.values():
            with self.subTest(f"{decision.current} -> {decision.replacement}"):
                self.assertTrue(decision.notes.strip())


#: Every distinct pair the `undecided-label-replacement` queue held on the
#: 2026-08-16 run, with the ruling #313 gave it.  Written out rather than read
#: back from a database so that the test says what was decided: a queue is what
#: a run happened to produce, and this is the record of what a curator answered.
#:
#: Two of these were proposed twice, once by `multi_source_consensus` and once
#: by the element pass.  They appear once, because a ruling is keyed on the pair.
QUEUE_2026_08_16 = (
    # Names the source list or this build's own caser damaged.  Every
    # replacement is a name Common Chemistry or ChEBI holds for the cited CAS.
    ("2,3,4,5-tetrachlorobenzoylchloride", "2,3,4,5-tetrachlorobenzoyl chloride", APPROVE),
    ("Bis(chloromethyl)ether", "bis(chloromethyl) ether", APPROVE),
    ("Cfc-10", "Carbon tetrachloride", APPROVE),
    ("Copper (i) Chloride", "copper(I) chloride", APPROVE),
    ("Copper (ii) Sulfate", "copper(II) sulfate", APPROVE),
    ("Dihexylphthalate", "Dihexyl phthalate", APPROVE),
    ("Disodium Hydrogen Phosphate", "disodium hydrogenphosphate", APPROVE),
    ("Ethoxycarbonylmethylethyl Phthalate", "Ethoxycarbonylmethyl ethyl phthalate", APPROVE),
    ("Hexamethylene Diamine", "Hexamethylenediamine", APPROVE),
    ("Hydrogen Carbonate", "hydrogencarbonate", APPROVE),
    ("HFC-1141", "Fluoroethylene", APPROVE),
    ("Iodine, 0.03% In Water", "Iodine", APPROVE),
    ("Methyl Acrylonitrile", "Methylacrylonitrile", APPROVE),
    ("O,o,o-triethylphosphorothioate", "O,O,O-triethyl phosphorothioate", APPROVE),
    (
        "Poly[oxy(methyl-1,2-ethanediyl)], Α-butyl-ω-hydroxy-",
        "Poly[oxy(methyl-1,2-ethanediyl)],α-butyl-ω-hydroxy-",
        APPROVE,
    ),
    ("Potassium Hydrogen Carbonate", "potassium hydrogencarbonate", APPROVE),
    ("Potassiumtetrafluoroaluminate", "Potassium tetrafluoroaluminate", APPROVE),
    ("Sodium Dihydrogen Phosphate", "sodium dihydrogenphosphate", APPROVE),
    ("Sodium Hydrogen Carbonate", "sodium hydrogencarbonate", APPROVE),
    ("Terephthaloyldichloride", "Terephthaloyl dichloride", APPROVE),
    ("Tetramethyl Ammonium Hydroxide", "Tetramethylammonium hydroxide", APPROVE),
    ("Tris(2,3-dibromopropyl)phosphate", "tris(2,3-dibromopropyl) phosphate", APPROVE),
    ("2,6-dime-n,n'-dinitrosopiperazine", "2,6-Dimethyl-1,4-dinitrosopiperazine", APPROVE),
    # The three refusals.
    ("Carbon, Organic, In Soil Or Biomass Stock", "Carbon", REJECT),
    ("HC Blue No. 1", "HC Blue No.1", REJECT),
    (
        "Glycerol Octanoate Decanoate",
        "Decanoic acid, ester with 1,2,3-propanetriol octanoate",
        REJECT,
    ),
)

#: The one pair #313 deliberately left for #312, because neither answer was
#: right: approving published an unreadable name and rejecting recorded that
#: `Fluorescein` is a correct name for the disodium salt, which it is not.
DEFERRED_TO_525 = ("Fluorescein", "Disodium 2-(3-oxo-6-oxidoxanthen-9-yl)benzoate")

#: What #312 turned that pair into. The source name was the wrong field: EF 3.1
#: ships all thirteen rows with 518-47-8, EC 208-253-0 and a comment saying the
#: name and a synonym were interchanged, so `ef-3.1-manual-fixes.json` corrects
#: them to `Fluorescein sodium` before a label exists. The pair a curator is
#: then shown is between two names of one substance, and is refused as a
#: readability choice.
ANSWERED_BY_525 = (
    "Fluorescein sodium",
    "Disodium 2-(3-oxo-6-oxidoxanthen-9-yl)benzoate",
)


class LabelQueueRulingsTestCase(unittest.TestCase):
    """The 2026-08-16 queue, ruled on in #313.

    The queue had gone unread since #245 fixed the comparison that had kept
    `multi_source_consensus` from proposing anything at all, so these are the
    first rulings that rule has ever had.  What is pinned is the answer per
    pair, not the count: a count would pass while every answer moved.
    """

    def setUp(self):
        self.index = load_preferred_label_decisions()

    def test_every_queued_pair_is_ruled_on(self):
        for current, replacement, expected in QUEUE_2026_08_16:
            with self.subTest(f"{current} -> {replacement}"):
                decision = self.index.get(decision_key(current, replacement))
                self.assertIsNotNone(
                    decision, "no ruling covers this pair, so it defers and requeues"
                )
                self.assertEqual(decision.decision, expected)

    def test_the_fluorescein_pair_is_still_unruled_in_its_deferred_form(self):
        """#312 was answered at source, so this pair is never proposed again.

        It stays unruled rather than being refused, and that is the point: a
        `reject` here would record that `Fluorescein` is a correct name for the
        disodium salt.  No EF 3.1 row carries that name any more --
        `ef-3.1-manual-fixes.json` corrects all thirteen -- so nothing asks.
        """
        self.assertIsNone(self.index.get(decision_key(*DEFERRED_TO_525)))

    def test_the_pair_525_left_in_its_place_is_refused(self):
        """The question the curator is actually shown, once the name is right.

        Both sides name 518-47-8, so refusing asserts nothing untrue -- it says
        only that three words beat fourteen syllables.  Without this ruling the
        rule would defer and requeue the same thirteen flows every build.
        """
        self.assertIs(
            rule_on_replacement(
                self.index,
                current=ANSWERED_BY_525[0],
                replacement=ANSWERED_BY_525[1],
                rule="multi_source_consensus",
            ),
            LabelRuling.REJECTED,
        )

    def test_the_refusal_survives_the_name_caser(self):
        """`Fluorescein sodium` reaches the rule title-cased or not.

        The ruling is written in Common Chemistry's spelling and the label the
        flows carry is whatever `normalize_name_case` made of it, so a ruling
        that only covered one of the two would defer on the other -- which is
        the `HCFC-140`/`Hcfc-140` failure that made #219 look like
        non-determinism.
        """
        for spelling in ("Fluorescein sodium", "Fluorescein Sodium"):
            with self.subTest(spelling):
                self.assertIs(
                    rule_on_replacement(
                        self.index,
                        current=spelling,
                        replacement=ANSWERED_BY_525[1],
                        rule="multi_source_consensus",
                    ),
                    LabelRuling.REJECTED,
                )

    def test_the_soil_carbon_refusal_binds_both_stages_that_propose_it(self):
        """`multi_source_consensus` and the element pass both want this rename.

        One ruling refuses both, which is what keying on the pair rather than on
        the proposing stage buys -- and is the property whose absence let
        `Plutonium` be published across two runs (#16).
        """
        for rule in ("multi_source_consensus", ELEMENT_ENRICHMENT_GENERATED_BY):
            with self.subTest(rule):
                self.assertIs(
                    rule_on_replacement(
                        self.index,
                        current="Carbon, Organic, In Soil Or Biomass Stock",
                        replacement="Carbon",
                        rule=rule,
                    ),
                    LabelRuling.REJECTED,
                )

    def test_the_iodine_approval_binds_both_stages_too(self):
        """The other pair both stages propose, ruled the other way.

        Written beside the carbon refusal because the two are the same shape --
        a qualified resource name giving way to the bare element -- and are
        ruled differently: ecoinvent 3.12 calls this flow `Iodine` itself, and
        no contributing list calls the soil-carbon stock `Carbon`.
        """
        for rule in ("multi_source_consensus", ELEMENT_ENRICHMENT_GENERATED_BY):
            with self.subTest(rule):
                self.assertIs(
                    rule_on_replacement(
                        self.index,
                        current="Iodine, 0.03% In Water",
                        replacement="Iodine",
                        rule=rule,
                    ),
                    LabelRuling.APPROVED,
                )

    def test_a_refused_pair_is_not_refused_in_the_other_direction(self):
        """Rulings are direction-specific, and these two rely on it.

        `HC Blue No. 1` -> `HC Blue No.1` is refused because it deletes a space
        from the name Common Chemistry holds.  That says nothing about the
        reverse, and must not: were a rule ever to propose the spaced spelling
        for a flow carrying the closed-up one, the refusal recorded here would
        be the wrong answer.
        """
        self.assertIsNone(self.index.get(decision_key("HC Blue No.1", "HC Blue No. 1")))


class TheTetrachlorobenzoylChlorideRefusalTestCase(unittest.TestCase):
    """#110: the one pair the label queue held, refused rather than approved.

    EF 3.1 files this substance twice, thirteen rows spelled
    `2,3,4,5-tetrachlorobenzoyl chloride` and thirteen spelled
    `2,3,4,5-tetrachlorobenzoylchloride`, both carrying 42221-52-3.
    `multi_source_consensus` votes on the names the sources supply, so the
    run-together spelling wins on count and is proposed as the better name.

    It is not one.  Common Chemistry names the number
    `2,3,4,5-Tetrachlorobenzoyl chloride`, and #313 already ruled this pair the
    other way.  What makes the refusal worth a test rather than only an
    expectation is that the two rulings now sit in one file pointing in
    opposite directions, and nothing but the direction of the key keeps them
    apart -- so both halves are asserted here.
    """

    RUN_TOGETHER = "2,3,4,5-tetrachlorobenzoylchloride"
    SPACED = "2,3,4,5-tetrachlorobenzoyl chloride"
    PUBLISHED = "2,3,4,5-tetrachlorobenzoyl Chloride"

    def setUp(self):
        self.index = load_preferred_label_decisions()

    def test_the_run_together_spelling_is_refused(self):
        self.assertIs(
            rule_on_replacement(
                self.index,
                current=self.PUBLISHED,
                replacement=self.RUN_TOGETHER,
                rule="multi_source_consensus",
            ),
            LabelRuling.REJECTED,
        )

    def test_the_spaced_spelling_is_still_approved(self):
        """#313's ruling, which this one must not have overwritten."""
        self.assertIs(
            rule_on_replacement(
                self.index,
                current=self.RUN_TOGETHER,
                replacement=self.SPACED,
                rule="multi_source_consensus",
            ),
            LabelRuling.APPROVED,
        )

    def test_the_two_rulings_are_two_entries(self):
        """The refusal and the approval are the same pair of strings read in
        opposite directions.  Were the key ever to stop being direction-specific
        they would collide, and one of them would silently disappear.
        """
        self.assertNotEqual(
            decision_key(self.PUBLISHED, self.RUN_TOGETHER),
            decision_key(self.RUN_TOGETHER, self.SPACED),
        )

    def test_the_casing_of_the_published_name_does_not_matter(self):
        """The queue reports the name caser's `Chloride`; the file states the
        pair in the source's own lower case.  One ruling has to cover both."""
        self.assertIs(
            rule_on_replacement(
                self.index,
                current=self.SPACED,
                replacement=self.RUN_TOGETHER,
                rule="multi_source_consensus",
            ),
            LabelRuling.REJECTED,
        )


class PenteneMixtureLabelTestCase(unittest.TestCase):
    """#157, on the pair the rename in `ef-3.1-manual-fixes.json` creates.

    EF 3.1 called the isomer mixture 25377-72-4 `1-pentene`, which is
    109-67-1's name, and the rename rule's containment heuristic blocked its
    own proposal of `Pentene` because `pentene` sits inside `1-pentene`.
    Correcting the source name to `Pentylene` lifts that block -- `pentene` is
    not inside `pentylene` -- so the pair reaches this file and has to be
    answered here, or `multi_source_consensus` requeues the same thirteen flows
    every build.
    """

    CURRENT = "Pentylene"
    PROPOSED = "Pentene"

    def setUp(self):
        self.index = load_preferred_label_decisions()

    def test_the_proposal_is_refused(self):
        """Both names are Common Chemistry's for 25377-72-4, so refusing
        asserts nothing untrue: it says only that `Pentene` cannot be told from
        the four other pentenes this list publishes."""
        self.assertIs(
            rule_on_replacement(
                self.index,
                current=self.CURRENT,
                replacement=self.PROPOSED,
                rule="multi_source_consensus",
            ),
            LabelRuling.REJECTED,
        )

    def test_the_refusal_holds_for_the_trusted_rule_too(self):
        """A `reject` ruling wins whichever rule proposed the pair, and this is
        the one substance where a rename would undo the fix that named it."""
        self.assertIs(
            rule_on_replacement(
                self.index,
                current=self.CURRENT,
                replacement=self.PROPOSED,
                rule=sorted(DEFAULT_APPROVED_RULES)[0],
            ),
            LabelRuling.REJECTED,
        )

    def test_the_casing_of_the_published_name_does_not_matter(self):
        """The label reaches the rule as whatever `normalize_name_case` made of
        it, and Common Chemistry writes the synonym `Pentylene`."""
        for spelling in ("Pentylene", "pentylene"):
            with self.subTest(spelling):
                self.assertIs(
                    rule_on_replacement(
                        self.index,
                        current=spelling,
                        replacement=self.PROPOSED,
                        rule="multi_source_consensus",
                    ),
                    LabelRuling.REJECTED,
                )


if __name__ == "__main__":
    unittest.main()
