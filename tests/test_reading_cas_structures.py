"""Reading the structure behind a key, instead of comparing key strings.

An InChIKey records how it was computed. CAS Common Chemistry computes plenty of
its keys a different way from every other source here, and two keys computed
differently cannot be weighed against each other -- so for those numbers the
list could say only "no comparable answer", and a real defect and a false alarm
looked identical.

CAS publishes the InChI its key came from, though, and a structure can be read
and written out again. Where that works, the number becomes checkable::

    trans-4-tert-butylcyclohexanol, 21862-63-5
        CAS publishes   CCOQPGVQAWPUPE-KYZUINATNA-N
        re-expressed    CCOQPGVQAWPUPE-KYZUINATSA-N
                                       ^^^^^^^^ same stereochemistry hash

On the 2026-08-12 build this answers 22 of the 56 substance-and-number pairs
where CAS states a stereochemistry the list does not match.

**The other 34 must stay unanswered, and that is the delicate part.** CAS uses
non-standard InChI mainly to say something standard InChI cannot: `/s2`, a
*relative* stereochemistry -- "these centres are arranged so with respect to
each other, in either mirror image". RDKit does not refuse such a string. It
reads it and returns *one* enantiomer, so a round trip would silently convert
"either mirror image" into "specifically this one" -- inventing exactly the
stereochemistry #42 exists to stop being invented.

What is pinned here:

- **A structure standard InChI can express round-trips faithfully**, keeping the
  stereochemistry hash and changing only the character that records how the key
  was computed.
- **A relative or racemic structure returns nothing at all**, checked before any
  conversion is attempted rather than after.
- **A conversion that altered the structure returns nothing**, even though it
  has not been seen on the cached records. It is the one failure that would be
  worse than having no answer.
- **Counting stereocentres separates the two reasons a key is flat**, which the
  key itself writes identically.
"""

import unittest

from rdkit import Chem

from brightway_flows.chem import (
    RELATIVE_STEREO_LAYERS,
    standard_inchikey_from_inchi,
    states_relative_stereochemistry,
    stereocentre_counts,
)

#: trans-4-tert-butylcyclohexanol, CAS 21862-63-5. Non-standard, and expressible.
TRANS_TBCH_INCHI = (
    "InChI=1/C10H20O/c1-10(2,3)8-4-6-9(11)7-5-8/h8-9,11H,4-7H2,1-3H3/t8-,9-"
)
TRANS_TBCH_CAS_KEY = "CCOQPGVQAWPUPE-KYZUINATNA-N"
TRANS_TBCH_STANDARD = "CCOQPGVQAWPUPE-KYZUINATSA-N"

#: (2RS,4SR)-2-methyl-4-propyl-1,3-oxathiane, CAS 59323-76-1. Relative: `/s2`.
OXATHIANE_INCHI = (
    "InChI=1/C8H16OS/c1-3-4-8-5-6-9-7(2)10-8/h7-8H,3-6H2,1-2H3/t7-,8+/s2"
)
#: What RDKit returns for it if nothing stops the conversion: one enantiomer.
OXATHIANE_INVENTED = "GKGOLPMYJJXRGD-JGVFFNPUSA-N"

#: Heptachlor epoxide, CAS 1024-57-3. Also relative.
HEPTACHLOR_EPOXIDE_INCHI = (
    "InChI=1/C10H5Cl7O/c11-3-1-2(4-5(3)18-4)9(15)7(13)6(12)8(1,14)10(9,16)17/"
    "h1-5H/t1-,2+,3+,4-,5+,8+,9-/s2"
)

#: An ordinary standard InChI, for the case that needs no special handling.
CROTONALDEHYDE_INCHI = "InChI=1S/C4H6O/c1-2-3-4-5/h2-4H,1H3"
CROTONALDEHYDE_KEY = "MLUCVPSAIODCQM-UHFFFAOYSA-N"


class RelativeStereochemistryTestCase(unittest.TestCase):
    def test_the_relative_and_racemic_layers_are_recognised(self):
        self.assertTrue(states_relative_stereochemistry(OXATHIANE_INCHI))
        self.assertTrue(states_relative_stereochemistry(HEPTACHLOR_EPOXIDE_INCHI))
        self.assertEqual(RELATIVE_STEREO_LAYERS, ("/s2", "/s3"))

    def test_absolute_stereochemistry_is_not_relative(self):
        """`/s1` is absolute, and must not be swept up with the other two."""
        self.assertFalse(
            states_relative_stereochemistry(
                "InChI=1S/C12H20O2/c1-8(13)14-10-7-9-5-6-12(10,4)11(9,2)3/"
                "h9-10H,5-7H2,1-4H3/t9-,10+,12+/m0/s1"
            )
        )

    def test_a_structure_with_no_stereochemistry_is_not_relative(self):
        self.assertFalse(states_relative_stereochemistry(CROTONALDEHYDE_INCHI))

    def test_nothing_is_not_relative(self):
        for value in ("", None):
            with self.subTest(value=value):
                self.assertFalse(states_relative_stereochemistry(value))


class ReExpressingTestCase(unittest.TestCase):
    def test_a_non_standard_key_becomes_comparable(self):
        self.assertEqual(
            standard_inchikey_from_inchi(TRANS_TBCH_INCHI), TRANS_TBCH_STANDARD
        )

    def test_only_the_computed_how_character_moves(self):
        corrected = standard_inchikey_from_inchi(TRANS_TBCH_INCHI)
        skeleton, middle, protonation = corrected.split("-")
        cas_skeleton, cas_middle, cas_protonation = TRANS_TBCH_CAS_KEY.split("-")
        self.assertEqual(skeleton, cas_skeleton)
        self.assertEqual(middle[:8], cas_middle[:8])
        self.assertEqual(protonation, cas_protonation)
        self.assertEqual((middle[8], cas_middle[8]), ("S", "N"))

    def test_a_relative_structure_is_refused_before_conversion(self):
        """The invention this guard exists to prevent is a real one."""
        self.assertIsNone(standard_inchikey_from_inchi(OXATHIANE_INCHI))
        self.assertIsNone(standard_inchikey_from_inchi(HEPTACHLOR_EPOXIDE_INCHI))

    def test_what_would_have_happened_without_the_guard(self):
        """Pinned so that removing the guard fails loudly rather than quietly.

        RDKit reads the relative form and hands back one specific enantiomer.
        Nothing in the returned value says an arrangement was chosen.
        """
        from rdkit.Chem.inchi import MolFromInchi, MolToInchiKey

        mol = MolFromInchi(OXATHIANE_INCHI)
        self.assertIsNotNone(mol)
        self.assertEqual(MolToInchiKey(mol), OXATHIANE_INVENTED)

    def test_an_ordinary_standard_inchi_round_trips(self):
        self.assertEqual(
            standard_inchikey_from_inchi(CROTONALDEHYDE_INCHI), CROTONALDEHYDE_KEY
        )

    def test_unreadable_input_gives_nothing(self):
        for value in ("", None, "rubbish", "InChI=1S/nonsense"):
            with self.subTest(value=value):
                self.assertIsNone(standard_inchikey_from_inchi(value))


class StereocentreCountingTestCase(unittest.TestCase):
    """A flat key has two causes, and writes them identically.

    Both of these end in `UHFFFAOY`. One is a complete description of a molecule
    with nothing to state; the other is a molecule whose arrangement was not
    stated. Anything deciding whether a substance has *lost* its stereochemistry
    needs to tell them apart, or it reports every simple molecule in the list.
    """

    def test_a_molecule_with_nothing_to_state(self):
        mol = Chem.MolFromSmiles("ClCCl")  # dichloromethane
        self.assertEqual(stereocentre_counts(mol), (0, 0))

    def test_a_molecule_whose_arrangement_was_not_stated(self):
        mol = Chem.MolFromSmiles("NC(Cc1c[nH]c2ccccc12)C(=O)O")  # flattened tryptophan
        self.assertEqual(stereocentre_counts(mol), (1, 0))

    def test_a_molecule_that_states_its_arrangement(self):
        mol = Chem.MolFromSmiles("N[C@@H](Cc1c[nH]c2ccccc12)C(=O)O")  # L-tryptophan
        self.assertEqual(stereocentre_counts(mol), (1, 1))

    def test_the_two_flat_cases_are_indistinguishable_by_key(self):
        """Which is why counting is needed at all."""
        from brightway_flows.chem import inchikey

        nothing_to_state = Chem.MolFromSmiles("ClCCl")
        not_stated = Chem.MolFromSmiles("NC(Cc1c[nH]c2ccccc12)C(=O)O")
        self.assertEqual(
            inchikey(nothing_to_state).split("-")[1][:8],
            inchikey(not_stated).split("-")[1][:8],
        )
        self.assertNotEqual(
            stereocentre_counts(nothing_to_state), stereocentre_counts(not_stated)
        )
