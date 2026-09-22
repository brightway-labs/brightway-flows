"""Two InChIKeys that differ only in the standard flag are the same structure.

The 14th character of an InChIKey's second block records whether the key came
from a standard or a non-standard InChI.  It describes the calculation, not the
substance.  CAS Common Chemistry publishes non-standard keys freely and every
other source we read publishes standard ones, so a literal string comparison
between them reports differences that do not exist.

The cost was measured before this module existed: 22 flow objects in the
2026-08-07 build agree with Common Chemistry only once the flag is disregarded,
and comparing the raw strings inflated the count of genuine stereochemistry
mismatches from 89 to 111 (#42).  Both β- and δ-hexachlorocyclohexane are in
that group -- the same molecule, written `…-CDRYSYESSA-N` by RDKit and
`…-CDRYSYESNA-N` by CAS.

Ignoring the flag is right for *equality* and wrong for *inequality*, and the
second half is what this file was extended for.  A non-standard InChI is
computed under options the key does not record, so its stereo hash and ours are
hashes of different things.  CAS reaches for those options exactly when standard
InChI cannot say what it needs -- `/s2`, relative stereochemistry, on 40 of the
75 non-standard keys in the cache:

    Trans-4-tert-butylcyclohexanol   CCOQPGVQAWPUPE-KYZUINATNA-N
                                     InChI=1/C10H20O/…/t8-,9-
    (2RS,4SR)-2-methyl-4-propyl-     GKGOLPMYJJXRGD-HGXVMFPFNA-N
      1,3-oxathiane                  InChI=1/C8H16OS/…/t7-,8+/s2

No standard key can equal those, so calling the difference a disagreement
convicts a correct structure on a comparison that never ran.  That mistake is
45 of the 91 flow objects #42 reported: 9 of 10 "stereo lost" and 36 of 48
"stereo conflict".

What is pinned here:

- **The flag is ignored for equality, and nothing else is.** Skeleton, stereo
  hash, version and protonation all still have to match.
- **The flag decides comparability for inequality.** Unequal stereo hashes are
  a disagreement only when both keys are standard.
- **A different skeleton is a different substance whatever the flags say.**
  That check finds the wrong-hit structures of #35 and #38, and no InChI
  option moves the connectivity hash.
- **An unparseable key never compares equal**, including to another unparseable
  key.  Callers use these to decide whether to keep data, so garbage must not
  read as agreement.
- **`same_skeleton` is looser on purpose**, so a stereochemistry disagreement
  can be told from a different substance.
"""

import unittest

from brightway_flows.domain.inchikey import (
    FLAT_STEREO_HASH,
    StructureComparison,
    compare_structures,
    parse_inchikey,
    same_skeleton,
    same_structure,
    structure_identity,
)

#: β-hexachlorocyclohexane as RDKit writes it and as CAS publishes it.
BETA_HCH_STANDARD = "JLYXXMFPNIAWKQ-CDRYSYESSA-N"
BETA_HCH_NONSTANDARD = "JLYXXMFPNIAWKQ-CDRYSYESNA-N"
#: α-hexachlorocyclohexane: same skeleton, genuinely different stereo hash.
ALPHA_HCH = "JLYXXMFPNIAWKQ-SHFUYGGZSA-N"
#: L-tryptophan, and the flat key it was wrongly given (#42).
L_TRYPTOPHAN = "QIVBCDIJIAJPQS-VIFPVBQESA-N"
TRYPTOPHAN_FLAT = "QIVBCDIJIAJPQS-UHFFFAOYSA-N"
DICHLOROMETHANE = "YMWUJEATGCHHMB-UHFFFAOYSA-N"
#: trans-4-tert-butylcyclohexanol: the flat key we publish, and the
#: non-standard key CAS publishes for 21862-63-5.  Not a stereo hash our key
#: could ever have matched.
TRANS_TBCH_FLAT = "CCOQPGVQAWPUPE-UHFFFAOYSA-N"
TRANS_TBCH_CAS = "CCOQPGVQAWPUPE-KYZUINATNA-N"
#: (2RS,4SR)-2-methyl-4-propyl-1,3-oxathiane, CAS 59323-76-1: one enantiomer as
#: we hold it, and CAS's `/s2` relative-stereo key.
OXATHIANE_ABSOLUTE = "GKGOLPMYJJXRGD-SFYZADRCSA-N"
OXATHIANE_CAS_RELATIVE = "GKGOLPMYJJXRGD-HGXVMFPFNA-N"


class ParseTestCase(unittest.TestCase):
    def test_the_blocks_are_split_by_meaning(self):
        parts = parse_inchikey(BETA_HCH_STANDARD)
        self.assertEqual(parts.skeleton, "JLYXXMFPNIAWKQ")
        self.assertEqual(parts.stereo, "CDRYSYES")
        self.assertEqual(parts.standard_flag, "S")
        self.assertEqual(parts.version, "A")
        self.assertEqual(parts.protonation, "N")

    def test_the_commonchemistry_prefix_is_tolerated(self):
        """Common Chemistry stores the value as `InChIKey=…` in its cache."""
        self.assertEqual(
            parse_inchikey("InChIKey=" + BETA_HCH_NONSTANDARD).standard_flag, "N"
        )

    def test_a_flat_key_is_recognised(self):
        self.assertTrue(parse_inchikey(DICHLOROMETHANE).is_flat)
        self.assertFalse(parse_inchikey(BETA_HCH_STANDARD).is_flat)
        self.assertEqual(parse_inchikey(DICHLOROMETHANE).stereo, FLAT_STEREO_HASH)

    def test_malformed_values_do_not_parse(self):
        for value in (
            "",
            None,
            "not-a-key",
            "JLYXXMFPNIAWKQ-CDRYSYESSA",           # two blocks
            "JLYXXMFPNIAW-CDRYSYESSA-N",           # short first block
            "JLYXXMFPNIAWKQ-CDRYSYESS-N",          # short second block
            "JLYXXMFPNIAWKQ-CDRYSYESSA-NN",        # long third block
            "jlyxxmfpniawkq-cdrysyessa-n",         # lower case
            "JLYXXMFPNIAWK1-CDRYSYESSA-N",         # digit in the hash
        ):
            with self.subTest(value=value):
                self.assertIsNone(parse_inchikey(value))


class SameStructureTestCase(unittest.TestCase):
    def test_the_standard_flag_is_disregarded(self):
        self.assertTrue(same_structure(BETA_HCH_STANDARD, BETA_HCH_NONSTANDARD))
        self.assertEqual(
            structure_identity(BETA_HCH_STANDARD),
            structure_identity(BETA_HCH_NONSTANDARD),
        )

    def test_a_different_stereo_hash_is_a_different_structure(self):
        """β- and α-hexachlorocyclohexane are separate flows and must stay so."""
        self.assertFalse(same_structure(BETA_HCH_STANDARD, ALPHA_HCH))
        self.assertTrue(same_skeleton(BETA_HCH_STANDARD, ALPHA_HCH))

    def test_losing_the_stereo_layer_is_a_different_structure(self):
        """The L-tryptophan case: same skeleton, and not the same substance."""
        self.assertFalse(same_structure(L_TRYPTOPHAN, TRYPTOPHAN_FLAT))
        self.assertTrue(same_skeleton(L_TRYPTOPHAN, TRYPTOPHAN_FLAT))

    def test_an_unparseable_key_never_matches(self):
        self.assertFalse(same_structure("", ""))
        self.assertFalse(same_structure("rubbish", "rubbish"))
        self.assertFalse(same_structure(BETA_HCH_STANDARD, ""))
        self.assertFalse(same_structure("", BETA_HCH_STANDARD))
        self.assertFalse(same_skeleton("rubbish", "rubbish"))

    def test_protonation_and_version_still_count(self):
        self.assertFalse(same_structure(BETA_HCH_STANDARD, "JLYXXMFPNIAWKQ-CDRYSYESSA-M"))
        self.assertFalse(same_structure(BETA_HCH_STANDARD, "JLYXXMFPNIAWKQ-CDRYSYESSB-N"))

    def test_unrelated_substances_share_nothing(self):
        self.assertFalse(same_skeleton(DICHLOROMETHANE, BETA_HCH_STANDARD))


class CompareStructuresTestCase(unittest.TestCase):
    """The third verdict, and where it does and does not apply."""

    def test_equal_hashes_are_the_same_whatever_computed_them(self):
        self.assertIs(
            compare_structures(BETA_HCH_STANDARD, BETA_HCH_NONSTANDARD),
            StructureComparison.SAME,
        )

    def test_two_standard_keys_can_disagree(self):
        for left, right in (
            (BETA_HCH_STANDARD, ALPHA_HCH),
            (L_TRYPTOPHAN, TRYPTOPHAN_FLAT),
        ):
            with self.subTest(left=left, right=right):
                self.assertIs(
                    compare_structures(left, right), StructureComparison.DIFFERENT
                )

    def test_a_non_standard_key_cannot_disagree_about_stereochemistry(self):
        """The 45 of #42's 91 that are not defects.

        Our standard key and CAS's `/s2` key hash different things.  Neither
        `SAME` nor `DIFFERENT` is supportable, and `DIFFERENT` is the one that
        would drop a correct structure.
        """
        for left, right in (
            (TRANS_TBCH_FLAT, TRANS_TBCH_CAS),
            (OXATHIANE_ABSOLUTE, OXATHIANE_CAS_RELATIVE),
            (BETA_HCH_STANDARD, "JLYXXMFPNIAWKQ-SHFUYGGZNA-N"),
        ):
            with self.subTest(left=left, right=right):
                self.assertIs(
                    compare_structures(left, right), StructureComparison.INCOMPARABLE
                )
                self.assertIs(
                    compare_structures(right, left), StructureComparison.INCOMPARABLE
                )

    def test_two_non_standard_keys_are_incomparable_too(self):
        """Different options on both sides is still different options."""
        self.assertIs(
            compare_structures(
                "JLYXXMFPNIAWKQ-CDRYSYESNA-N", "JLYXXMFPNIAWKQ-SHFUYGGZNA-N"
            ),
            StructureComparison.INCOMPARABLE,
        )

    def test_an_unrecognised_flag_is_not_standard(self):
        """A flag this module has never seen is a calculation we cannot account
        for, which argues for caution rather than against it."""
        self.assertIs(
            compare_structures(BETA_HCH_STANDARD, "JLYXXMFPNIAWKQ-SHFUYGGZQA-N"),
            StructureComparison.INCOMPARABLE,
        )

    def test_a_different_skeleton_is_different_whatever_the_flag(self):
        """The check #35 and #38 rest on.  No InChI option moves block 1."""
        self.assertIs(
            compare_structures(DICHLOROMETHANE, "JLYXXMFPNIAWKQ-CDRYSYESNA-N"),
            StructureComparison.DIFFERENT,
        )

    def test_a_different_protonation_is_different_whatever_the_flag(self):
        self.assertIs(
            compare_structures(BETA_HCH_STANDARD, "JLYXXMFPNIAWKQ-CDRYSYESNA-M"),
            StructureComparison.DIFFERENT,
        )

    def test_a_different_version_is_incomparable(self):
        """Two hashing schemes, not two substances."""
        self.assertIs(
            compare_structures(BETA_HCH_STANDARD, "JLYXXMFPNIAWKQ-SHFUYGGZSB-N"),
            StructureComparison.INCOMPARABLE,
        )

    def test_an_unreadable_key_is_incomparable_not_different(self):
        for left, right in (
            ("", ""),
            ("rubbish", "rubbish"),
            (BETA_HCH_STANDARD, ""),
            ("", BETA_HCH_STANDARD),
        ):
            with self.subTest(left=left, right=right):
                self.assertIs(
                    compare_structures(left, right), StructureComparison.INCOMPARABLE
                )

    def test_same_structure_is_the_same_answer_narrowed(self):
        """`same_structure` stays a boolean, and stays true only for `SAME`."""
        for left, right in (
            (BETA_HCH_STANDARD, BETA_HCH_NONSTANDARD),
            (BETA_HCH_STANDARD, ALPHA_HCH),
            (TRANS_TBCH_FLAT, TRANS_TBCH_CAS),
            ("rubbish", "rubbish"),
        ):
            with self.subTest(left=left, right=right):
                self.assertEqual(
                    same_structure(left, right),
                    compare_structures(left, right) is StructureComparison.SAME,
                )
