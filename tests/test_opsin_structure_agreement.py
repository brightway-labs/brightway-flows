"""The name-to-structure step counts structures, not spellings (#71).

`Sulfur Dichloride` is eight names for one molecule: `Dichlorosulfane`,
`Sulfur chloride (SCl2)`, `Monosulfur dichloride` and five more. Five of them
the parser reads, and it reads all five as `ClSCl`. The flow object the merge
created for it publishes no structure at all.

The reason was a guard meant to protect against ambiguity: update a flow only
when exactly one of its labels is a name the parser can read, and leave it alone
when several are, since several readable names might mean several substances.
The intent is right. What it counted was wrong -- it grouped the readable labels
by the *name*, so two spellings of one molecule counted as two answers, and a
substance whose synonyms the enrichment had just filled in could never have one.
Nothing in the list had exactly one: on the build of 5f77d7b4de1f the guard let
through 378 flows out of tens of thousands, and of the 261 empty substances a
merge created it let through none.

Grouping by the structure the names resolve to is what the guard meant to say.
Where the structures genuinely disagree it still refuses -- `Zoxamide`'s
spellings are two against two, and `Copper Chloride Oxide, Hydrate` gives five
answers from six names.

OPSIN itself is stubbed. It is a Java subprocess and it is not what is being
tested: what is being tested is what the rule does with what it returns.
"""

from __future__ import annotations

import unittest
from unittest import mock

from brightway_flows.domain.flow import Flow
from brightway_flows.domain.vocabulary import (
    CHEMROF_INCHI2D_STRING,
    CHEMROF_IUPAC_NAME,
    CHEMROF_SMILES_STRING,
)
from brightway_flows.transformers.opsin_iupac import OPSINTransformer

#: Two spellings of sulfur dichloride, and one of carbon dioxide to disagree
#: with. Written as SMILES the parser would return, not as canonical ones: the
#: rule has to reach the same structure from either.
SULFUR_DICHLORIDE = "ClSCl"
SULFUR_DICHLORIDE_OTHER_SPELLING = "S(Cl)Cl"
CARBON_DIOXIDE = "O=C=O"
TRICHLOROETHENE = "ClC=C(Cl)Cl"


def _flow(uuid: str, pref: str, *alt: str) -> Flow:
    return Flow.from_dict({
        "uuid": uuid,
        "identifier": uuid,
        "source": "test",
        "unit": "kg",
        "prefLabel": [{"@value": pref, "@language": "en"}],
        "altLabel": [{"@value": value, "@language": "en"} for value in alt],
    })


class _RunsTheTransformer:
    """Running the transformer against a stubbed parser, for both cases below."""

    def run_transformer(self, flows, smiles_by_name):
        """Run the transformer with OPSIN answering out of *smiles_by_name*."""
        transformer = OPSINTransformer()

        def batch(names):
            return [smiles_by_name.get(name) for name in names]

        with mock.patch(
            "brightway_flows.transformers.opsin_iupac._opsin_batch",
            side_effect=batch,
        ):
            return transformer.transform(flows)

    def structure_written(self, changes, uuid):
        for change in changes:
            if change.uuid == uuid and change.field == "properties":
                return change.new_value
        return None


class StructuresNotSpellingsTestCase(_RunsTheTransformer, unittest.TestCase):
    def test_several_spellings_of_one_molecule_are_one_answer(self):
        """The `Sulfur Dichloride` case: five names, one structure."""
        flow = _flow(
            "u-1", "Sulfur Dichloride", "Dichlorosulfane", "Sulfur chloride (SCl2)"
        )
        changes = self.run_transformer([flow], {
            "Sulfur Dichloride": SULFUR_DICHLORIDE,
            "Dichlorosulfane": SULFUR_DICHLORIDE_OTHER_SPELLING,
            "Sulfur chloride (SCl2)": SULFUR_DICHLORIDE,
        })

        written = self.structure_written(changes, "u-1")
        self.assertIsNotNone(written, "three spellings of one molecule wrote nothing")
        self.assertIn(CHEMROF_SMILES_STRING, written)
        self.assertIn(CHEMROF_INCHI2D_STRING, written)

    def test_the_preferred_label_is_the_name_recorded(self):
        """Which of the agreeing spellings is published as the IUPAC name.

        The labels arrive preferred-first, and that order is the preference: a
        substance's own name is a better answer than the fourth synonym ChEBI
        supplied, even where both mean the same molecule.
        """
        flow = _flow("u-1", "Sulfur Dichloride", "Dichlorosulfane")
        changes = self.run_transformer([flow], {
            "Sulfur Dichloride": SULFUR_DICHLORIDE,
            "Dichlorosulfane": SULFUR_DICHLORIDE_OTHER_SPELLING,
        })

        written = self.structure_written(changes, "u-1")
        self.assertEqual(written[CHEMROF_IUPAC_NAME]["@value"], ["Sulfur Dichloride"])

    def test_one_readable_name_still_answers(self):
        """The case the guard was already letting through, unchanged."""
        flow = _flow("u-1", "Trichloroethene", "Trade Name 7")
        changes = self.run_transformer(
            [flow], {"Trichloroethene": TRICHLOROETHENE}
        )

        self.assertIsNotNone(self.structure_written(changes, "u-1"))

    def test_no_readable_name_answers_nothing(self):
        flow = _flow("u-1", "Kerosene", "Petrol")
        changes = self.run_transformer([flow], {})

        self.assertEqual(changes, [])

    def test_an_even_disagreement_is_refused(self):
        """The half the guard exists for, and it has to keep working.

        `Zoxamide` is this case in the real list: two of its readable spellings
        say one molecule and two say another, and nothing here can say which is
        the substance. A rule that answered anyway would be guessing.
        """
        flow = _flow("u-1", "Zoxamide", "(RS)-zoxamide", "rac-zoxamide")
        changes = self.run_transformer([flow], {
            "Zoxamide": SULFUR_DICHLORIDE,
            "(RS)-zoxamide": CARBON_DIOXIDE,
        })

        self.assertEqual(changes, [])

    def test_a_lopsided_disagreement_takes_the_majority(self):
        """`Trioctyltin`: four spellings say one thing and the bare name another.

        A tin with three octyls on it and nothing said about the fourth bond is
        not a complete molecule, and `Trioctyltin` is what the parser makes of
        it. `Stannane, trioctyl-`, `Trioctylstannane`, `Trioctyltin hydride` and
        `Tris(n-octyl)stannane` all say the same complete one. Four against one
        is not a disagreement about what the substance is.
        """
        flow = _flow(
            "u-1", "Trioctyltin", "Stannane, trioctyl-", "Trioctylstannane",
            "Trioctyltin hydride", "Tris(n-octyl)stannane",
        )
        changes = self.run_transformer([flow], {
            "Trioctyltin": CARBON_DIOXIDE,
            "Stannane, trioctyl-": SULFUR_DICHLORIDE,
            "Trioctylstannane": SULFUR_DICHLORIDE,
            "Trioctyltin hydride": SULFUR_DICHLORIDE,
            "Tris(n-octyl)stannane": SULFUR_DICHLORIDE,
        })

        written = self.structure_written(changes, "u-1")
        self.assertIsNotNone(written)
        self.assertEqual(
            written[CHEMROF_IUPAC_NAME]["@value"], ["Stannane, trioctyl-"],
            "the name cited has to be one of the agreeing spellings, not the outvoted one",
        )

    def test_a_narrow_majority_is_refused(self):
        """Three against two is a disagreement, not a lopsided one.

        `Disodium Phosphonate` is this case, and what its spellings disagree
        about is real: whether the substance is written as the phosphonate or as
        the hydrogen phosphite, which are two tautomers with different InChIKeys
        and different registry numbers. Three names against two is not evidence
        about which of the two the vendor meant, and settling it by counting
        synonyms would be deciding a chemical question by vote.
        """
        flow = _flow(
            "u-1", "Disodium Phosphonate", "Phosphonic acid, disodium salt",
            "Phosphonic acid, sodium salt (1:2)", "Disodium hydrogen phosphite",
            "Disodium orthophosphite",
        )
        changes = self.run_transformer([flow], {
            "Disodium Phosphonate": SULFUR_DICHLORIDE,
            "Phosphonic acid, disodium salt": SULFUR_DICHLORIDE,
            "Phosphonic acid, sodium salt (1:2)": SULFUR_DICHLORIDE,
            "Disodium hydrogen phosphite": CARBON_DIOXIDE,
            "Disodium orthophosphite": CARBON_DIOXIDE,
        })

        self.assertEqual(changes, [])

    def test_a_plurality_that_is_not_a_majority_is_refused(self):
        """`Copper Chloride Oxide, Hydrate`: six names, five answers.

        Two of them agree, which is more than any other answer gets and is still
        two names out of six. A rule that took the largest group whatever its
        size would answer here, and a substance whose names scatter across five
        structures is one nobody has a structure for.
        """
        flow = _flow(
            "u-1", "Copper Chloride Oxide, Hydrate",
            "Copper chloride oxide, hydrate (1:?)", "Copper (II) oxychloride",
            "Copper chloride oxide", "Copper oxychloride", "Cupric oxide chloride",
        )
        changes = self.run_transformer([flow], {
            "Copper Chloride Oxide, Hydrate": SULFUR_DICHLORIDE,
            "Copper chloride oxide, hydrate (1:?)": SULFUR_DICHLORIDE,
            "Copper (II) oxychloride": CARBON_DIOXIDE,
            "Copper chloride oxide": TRICHLOROETHENE,
            "Copper oxychloride": "ClCl",
            "Cupric oxide chloride": "BrBr",
        })

        self.assertEqual(changes, [])

    def test_case_variants_of_one_name_are_still_one_name(self):
        """The dedupe the guard already did, which grouping must not lose."""
        flow = _flow("u-1", "Trichloroethene", "trichloroethene", "TRICHLOROETHENE")
        changes = self.run_transformer([flow], {
            "Trichloroethene": TRICHLOROETHENE,
            "trichloroethene": TRICHLOROETHENE,
            "TRICHLOROETHENE": TRICHLOROETHENE,
        })

        self.assertIsNotNone(self.structure_written(changes, "u-1"))

    def test_a_name_the_parser_misreads_does_not_outvote_the_rest(self):
        """Two flows, one batch: the grouping is per flow, not per run."""
        flows = [
            _flow("u-1", "Sulfur Dichloride", "Dichlorosulfane"),
            _flow("u-2", "Zoxamide", "(RS)-zoxamide"),
        ]
        changes = self.run_transformer(flows, {
            "Sulfur Dichloride": SULFUR_DICHLORIDE,
            "Dichlorosulfane": SULFUR_DICHLORIDE,
            "Zoxamide": SULFUR_DICHLORIDE,
            "(RS)-zoxamide": CARBON_DIOXIDE,
        })

        self.assertIsNotNone(self.structure_written(changes, "u-1"))
        self.assertIsNone(self.structure_written(changes, "u-2"))


class AStructureMayNotMiscountTheNameTestCase(_RunsTheTransformer, unittest.TestCase):
    """#129.  Agreement among the names is not enough if they all miscount.

    The rule above asks whether a substance's names agree about what it is.
    These names do agree -- there is only one the parser can read -- and the
    structure is still wrong, because the name it read does not say how many
    atoms there are and the parser assumed one of each.
    """

    #: What OPSIN really returns for these names, and the point of the issue:
    #: the trisulfide's synonym and the monosulfide's name give the same answer.
    ANTIMONY_MONOSULFIDE = "[Sb+]=S"
    BISMUTH_MONOXIDE = "[O]=[Bi+]"
    SULFUR_DIOXIDE = "O=S=O"

    def test_the_trisulfide_does_not_take_a_monosulfide_structure(self):
        # As published: EF's flow is named for the trisulfide, and the only
        # name OPSIN can read is `Antimonous sulfide`.
        flow = _flow("u-1", "Antimony Trisulfide", "Antimonous sulfide")
        changes = self.run_transformer(
            [flow], {"Antimonous sulfide": self.ANTIMONY_MONOSULFIDE}
        )
        self.assertIsNone(
            self.structure_written(changes, "u-1"),
            "a one-sulfur structure was written onto a trisulfide",
        )

    def test_the_trioxide_does_not_take_a_monoxide_structure(self):
        flow = _flow("u-2", "Bismuth Trioxide", "Bismuth(III) oxide")
        changes = self.run_transformer(
            [flow], {"Bismuth(III) oxide": self.BISMUTH_MONOXIDE}
        )
        self.assertIsNone(self.structure_written(changes, "u-2"))

    def test_a_structure_that_counts_correctly_is_still_written(self):
        # The half that matters: this must not become a rule that refuses
        # binary compounds.  `Sulfur Dioxide` states two oxygens and has two.
        flow = _flow("u-3", "Sulfur Dioxide", "Sulphur dioxide")
        changes = self.run_transformer(
            [flow],
            {
                "Sulfur Dioxide": self.SULFUR_DIOXIDE,
                "Sulphur dioxide": self.SULFUR_DIOXIDE,
            },
        )
        self.assertIsNotNone(self.structure_written(changes, "u-3"))

    def test_a_name_that_states_no_count_is_left_alone(self):
        # `Hydrogen Sulfide` says nothing about how many hydrogens, and H2S is
        # right.  Reading the missing prefix as "one" would refuse this.
        flow = _flow("u-4", "Hydrogen Sulfide", "Dihydrogen sulfide")
        changes = self.run_transformer(
            [flow], {"Hydrogen Sulfide": "S", "Dihydrogen sulfide": "S"}
        )
        self.assertIsNotNone(self.structure_written(changes, "u-4"))

    #: What OPSIN really returns for the systematic name of Sb2S3.
    ANTIMONY_TRISULFIDE = "S=[Sb]S[Sb]=S"

    def test_a_correct_reading_beside_a_miscounting_one_still_answers(self):
        """Why the miscount is dropped rather than disqualifying the flow.

        Refusing the whole flow would throw away a right answer for having a
        wrong one next to it -- and worse, it would leave the substance with no
        structure at all, which the typing rules read as a substance of
        variable composition.
        """
        flow = _flow(
            "u-7",
            "Antimony Trisulfide",
            "Antimonous sulfide",
            "sulfanylidene(sulfanylidenestibanylsulfanyl)stibane",
        )
        changes = self.run_transformer([flow], {
            "Antimonous sulfide": self.ANTIMONY_MONOSULFIDE,
            "sulfanylidene(sulfanylidenestibanylsulfanyl)stibane": (
                self.ANTIMONY_TRISULFIDE
            ),
        })

        written = self.structure_written(changes, "u-7")
        self.assertIsNotNone(written, "the correct reading was thrown away")
        smiles = written[CHEMROF_SMILES_STRING]["@value"]
        self.assertNotIn(
            self.ANTIMONY_MONOSULFIDE,
            smiles if isinstance(smiles, list) else [smiles],
        )

    def test_a_miscount_does_not_outvote_a_correct_reading(self):
        """Two miscounting names against one correct one: the correct one wins.

        Without the drop this is a 2-1 majority for the wrong structure, which
        `_agreed_structure` would take.
        """
        flow = _flow(
            "u-8",
            "Antimony Trisulfide",
            "Antimonous sulfide",
            "antimony(III) sulfide",
            "sulfanylidene(sulfanylidenestibanylsulfanyl)stibane",
        )
        changes = self.run_transformer([flow], {
            "Antimonous sulfide": self.ANTIMONY_MONOSULFIDE,
            "antimony(III) sulfide": self.ANTIMONY_MONOSULFIDE,
            "sulfanylidene(sulfanylidenestibanylsulfanyl)stibane": (
                self.ANTIMONY_TRISULFIDE
            ),
        })
        self.assertIsNotNone(self.structure_written(changes, "u-8"))

    def test_the_refusal_is_per_flow(self):
        flows = [
            _flow("u-5", "Antimony Trisulfide", "Antimonous sulfide"),
            _flow("u-6", "Sulfur Dichloride", "Dichlorosulfane"),
        ]
        changes = self.run_transformer(flows, {
            "Antimonous sulfide": self.ANTIMONY_MONOSULFIDE,
            "Sulfur Dichloride": SULFUR_DICHLORIDE,
            "Dichlorosulfane": SULFUR_DICHLORIDE,
        })
        self.assertIsNone(self.structure_written(changes, "u-5"))
        self.assertIsNotNone(self.structure_written(changes, "u-6"))


if __name__ == "__main__":
    unittest.main()
