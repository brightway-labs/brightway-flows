"""Agreement is agreement, whatever a conversion would have said about it.

`Zinc-65` is a single atom. It has no three-dimensional shape to disagree about,
and the key this list publishes for it is character-for-character the key CAS
Common Chemistry publishes. It was reported as a comparison that could not be
made, under the explanation "CAS states a relative or racemic stereochemistry":

    13982-39-3: CAS states a relative or racemic stereochemistry
    (HCHKCACWOHOZIP-IGMARMGPSA-N), which no standard InChIKey can express, so it
    cannot be compared with HCHKCACWOHOZIP-IGMARMGPSA-N

Two separate faults, both fixed here.

**The comparison was never needed.** To compare a key CAS wrote in its own
notation, the pipeline re-reads CAS's structure and takes a fresh fingerprint.
That was being done *before* asking whether the two keys already agreed. Equal
stereo hashes are the same structure whatever computed them -- the half of
#42's warning about the standard flag that was always right -- so a conversion
cannot change the answer when they are equal.

**The refusal did not record its reason, so one was assumed.** The conversion
declines for three different reasons and returned a bare `None` for all of them.
The isotope case is the third: RDKit's InChI reader drops the isotopic layer of a
lone labelled atom, so the round-trip guard fires and correctly refuses -- it is
the guard working, not a relative stereochemistry.

See `<https://github.com/brightway-labs/brightway-flows/issues/55>`_.
"""

import unittest

from brightway_flows.chem import (
    ConversionRefusal,
    standard_structure_from_inchi,
)
from brightway_flows.integrations.commonchemistry import build_commonchemistry_index
from brightway_flows.pipeline.review_records import Severity
from brightway_flows.transformers.enrich_references import (
    EnrichReferencesTransformer,
    StructureCandidate,
)

#: The three radionuclides of #55.  Each is one atom, written as a shift of
#: zero from the element's standard atomic weight -- zinc's rounds to 65, radium
#: to 226, radon to 222 -- and `IGMARMGP` is the signature of that shift rather
#: than of any shape.
ISOTOPES = {
    "13982-39-3": ("HCHKCACWOHOZIP-IGMARMGPSA-N", "InChI=1S/Zn/i1+0", "Zn"),
    "13982-63-3": ("HCWPIIXVSYCSAN-IGMARMGPSA-N", "InChI=1S/Ra/i1+0", "Ra"),
    "14859-67-7": ("SYUHGPGVQRZVTB-IGMARMGPSA-N", "InChI=1S/Rn/i1+0", "Rn"),
}

#: (2RS,4SR)-2-methyl-4-propyl-1,3-oxathiane: a genuine relative registration,
#: which must keep reporting as one.
RELATIVE_CAS = "59323-76-1"
RELATIVE_THEIRS = "GKGOLPMYJJXRGD-HGXVMFPFNA-N"
RELATIVE_OURS = "GKGOLPMYJJXRGD-SFYZADRCSA-N"
RELATIVE_INCHI = (
    "InChI=1/C8H16OS/c1-3-4-8-5-6-9-7(2)10-8/h7-8H,3-6H2,1-2H3/t7-,8+/s2"
)

#: trans-4-tert-butylcyclohexanol: a shape standard InChI can express, so the
#: registry's structure re-expresses as a key that can settle a tie.  The
#: positive control for the guard in `SupersededTieTestCase`.
SETTLED_CAS = "21862-63-5"
SETTLED_THEIRS = "CCOQPGVQAWPUPE-KYZUINATNA-N"
SETTLED_COMPARABLE = "CCOQPGVQAWPUPE-KYZUINATSA-N"
SETTLED_OTHER = "CCOQPGVQAWPUPE-QMMMGPOBSA-N"
SETTLED_INCHI = (
    "InChI=1/C10H20O/c1-10(2,3)8-4-6-9(11)7-5-8/h8-9,11H,4-7H2,1-3H3/t8-,9-"
)

CACHE_RECORDS = dict(ISOTOPES)
CACHE_RECORDS[RELATIVE_CAS] = (
    RELATIVE_THEIRS,
    RELATIVE_INCHI,
    "C<sub>8</sub>H<sub>16</sub>OS",
)
CACHE_RECORDS[SETTLED_CAS] = (
    SETTLED_THEIRS,
    SETTLED_INCHI,
    "C<sub>10</sub>H<sub>20</sub>O",
)


def transformer() -> EnrichReferencesTransformer:
    instance = EnrichReferencesTransformer()
    instance._commonchemistry = build_commonchemistry_index({
        "detail_by_cas": {
            cas: {
                "rn": cas,
                "name": cas,
                "molecularFormula": formula,
                "inchi": inchi,
                "inchiKey": f"InChIKey={key}",
            }
            for cas, (key, inchi, formula) in CACHE_RECORDS.items()
        }
    })
    instance._structure_rulings = {}
    return instance


class ConversionRefusalTestCase(unittest.TestCase):
    def test_an_isotope_label_is_lost_on_the_round_trip(self):
        """Pins RDKit's behaviour, so removing the guard fails loudly."""
        from rdkit.Chem.inchi import MolFromInchi, MolToInchi

        self.assertEqual(MolToInchi(MolFromInchi("InChI=1S/Zn/i1+0")), "InChI=1S/Zn")

    def test_the_refusal_says_the_structure_was_altered(self):
        for cas, (_, inchi, _) in ISOTOPES.items():
            with self.subTest(cas=cas):
                self.assertEqual(
                    standard_structure_from_inchi(inchi).refusal,
                    ConversionRefusal.ALTERED,
                )

    def test_a_relative_registration_still_says_relative(self):
        self.assertEqual(
            standard_structure_from_inchi(RELATIVE_INCHI).refusal,
            ConversionRefusal.RELATIVE,
        )

    def test_an_unreadable_string_says_unreadable(self):
        for value in ("", "   ", "not an InChI"):
            with self.subTest(value=value):
                self.assertEqual(
                    standard_structure_from_inchi(value).refusal,
                    ConversionRefusal.UNREADABLE,
                )

    def test_a_conversion_that_works_refuses_nothing(self):
        converted = standard_structure_from_inchi(
            "InChI=1/C10H20O/c1-10(2,3)8-4-6-9(11)7-5-8/h8-9,11H,4-7H2,1-3H3/t8-,9-"
        )
        self.assertIsNone(converted.refusal)
        self.assertEqual(converted.inchikey, "CCOQPGVQAWPUPE-KYZUINATSA-N")


class AgreementTestCase(unittest.TestCase):
    def test_an_identical_key_is_not_an_impossible_comparison(self):
        instance = transformer()
        for cas, (key, _, _) in ISOTOPES.items():
            with self.subTest(cas=cas):
                self.assertIsNone(
                    instance._stereo_disagreement(
                        cas=cas, candidate=StructureCandidate(key)
                    )
                )

    def test_this_is_not_about_isotopes(self):
        """The same fix, on a relative registration whose key we happen to hold.

        Nothing here reasons about isotopes: it reasons about asking the cheap
        question first.
        """
        self.assertIsNone(
            transformer()._stereo_disagreement(
                cas=RELATIVE_CAS, candidate=StructureCandidate(RELATIVE_THEIRS)
            )
        )

    def test_nothing_is_reported_for_a_number_that_agrees(self):
        instance = transformer()
        for cas, (key, _, _) in ISOTOPES.items():
            instance._record_stereo_disagreement(
                cas=cas, source="CID:1", candidate=StructureCandidate(key)
            )
        self.assertEqual(instance._stereo_disagreements, {})

    def test_a_real_disagreement_still_reports(self):
        self.assertEqual(
            transformer()._stereo_disagreement(
                cas=RELATIVE_CAS, candidate=StructureCandidate(RELATIVE_OURS)
            ),
            "incomparable",
        )


class TitleTestCase(unittest.TestCase):
    def row(self, cas: str, candidate: str):
        instance = transformer()
        instance._record_stereo_disagreement(
            cas=cas, source="CID:1", candidate=StructureCandidate(candidate)
        )
        return next(
            item
            for item in instance.review_queue_items()
            if item.item_key.startswith(cas)
        )

    def test_a_relative_registration_is_described_as_one(self):
        item = self.row(RELATIVE_CAS, RELATIVE_OURS)
        self.assertIn("relative or racemic stereochemistry", item.title)
        self.assertEqual(item.severity, Severity.INFO)

    def test_the_reason_is_carried_on_the_row(self):
        item = self.row(RELATIVE_CAS, RELATIVE_OURS)
        self.assertEqual(
            item.payload["conversion_refusal"], ConversionRefusal.RELATIVE
        )

    def test_an_altered_conversion_is_not_called_a_stereochemistry(self):
        """The sentence #55 was filed about.

        Reached by giving one of the isotope numbers a key that genuinely
        differs, so the row exists at all -- what is pinned is the wording, not
        that this substance produces a row.
        """
        item = self.row("13982-39-3", "HCHKCACWOHOZIP-BJUDXGSMSA-N")
        self.assertNotIn("stereochemistry", item.title)
        self.assertIn("isotopic layer", item.title)


class SupersededTieTestCase(unittest.TestCase):
    """The registry breaks a tie between two shapes, and not between two nuclei.

    `_drop_superseded_stereo_inchikeys` withdraws a key on the grounds that
    another on the same skeleton is the one the registry reproduces, so the two
    were one substance published under two identities. Block 2 of an InChIKey
    hashes isotopic labelling as well, so zinc-64 and zinc-65 present to that
    rule exactly as two stereoisomers of zinc do -- and withdrawing one would
    delete a substance rather than a duplicate identity.

    Nothing in the list offers such a pair today, so this refuses nothing that
    is currently published. It is the guard that keeps it that way.
    """

    #: Zinc-65, as CAS registers it, and zinc-64: one skeleton, two nuclides.
    ZINC_CAS = "13982-39-3"
    ZINC_65 = "HCHKCACWOHOZIP-IGMARMGPSA-N"
    ZINC_64 = "HCHKCACWOHOZIP-BJUDXGSMSA-N"

    def slot(self, instance: EnrichReferencesTransformer, values: list[str]) -> dict:
        return {instance.CHEMROF_INCHI2D_KEY_STRING: {"@value": list(values)}}

    def test_two_nuclides_both_survive(self):
        instance = transformer()
        semantic = self.slot(instance, [self.ZINC_65, self.ZINC_64])
        instance._drop_superseded_stereo_inchikeys(
            semantic=semantic, cas_numbers=[self.ZINC_CAS]
        )
        self.assertEqual(
            semantic[instance.CHEMROF_INCHI2D_KEY_STRING]["@value"],
            [self.ZINC_65, self.ZINC_64],
        )

    def test_no_withdrawal_is_reported_either(self):
        """A queue row for a removal that did not happen is its own defect."""
        instance = transformer()
        instance._drop_superseded_stereo_inchikeys(
            semantic=self.slot(instance, [self.ZINC_65, self.ZINC_64]),
            cas_numbers=[self.ZINC_CAS],
        )
        self.assertEqual(instance._stereo_disagreements, {})

    def test_a_shape_the_registry_settles_is_still_withdrawn(self):
        """The guard must not switch the rule off for everything else."""
        instance = transformer()
        semantic = self.slot(instance, [SETTLED_COMPARABLE, SETTLED_OTHER])
        instance._drop_superseded_stereo_inchikeys(
            semantic=semantic, cas_numbers=[SETTLED_CAS]
        )
        self.assertEqual(
            semantic[instance.CHEMROF_INCHI2D_KEY_STRING]["@value"],
            [SETTLED_COMPARABLE],
        )
        self.assertIn(f"{SETTLED_CAS}:superseded", instance._stereo_disagreements)


if __name__ == "__main__":
    unittest.main()
