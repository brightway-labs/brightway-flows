"""An acid and its ion, published as one substance and filed as a shape dispute.

`(2R,3R)-2,3-dihydroxybutanedioic acid` publishes two keys::

    FEWJPZIEWOKRBE-JCYAYHJZSA-N   tartaric acid, and CAS's own answer for 87-69-4
    FEWJPZIEWOKRBE-JCYAYHJZSA-L   tartrate, with both acid hydrogens removed

The middle block -- the stereochemistry -- is identical in both, and identical to
the registry's.  Only the last block, the protonation state, differs.  The queue
nonetheless carried this at `blocking` as *"same skeleton, different
stereochemistry, both specific"*, because the classifier read
`compare_structures` reporting a *difference* as reporting a difference in shape:
the charge is tested before the stereochemistry hash is, so the answer was
already decided by the time the shape was looked at (#54).

What is pinned here:

- **Charge is classified before shape**, under its own kind, so a curator sent to
  settle a shape question is not sent to settle one that does not exist.
- **A charge difference is reported even where the shapes cannot be compared.**
  The third block is not touched by the InChI options the second block's hash
  depends on, so the comparison that *is* valid is the one reported.
- **A flat registration is no exception.**  CAS registering the number without a
  stereochemistry says nothing about its charge, and those cases were reported
  nowhere before.
- **The key is withdrawn where the registry's own answer sits beside it**, on
  exactly the reasoning of #278: one of the object's own keys was independently
  reproduced by the registry, so the other describes something the registry does
  not call by this number.
- **Where the registry's answer is absent, nothing is touched** and the row
  stays open.
- **The withdrawal closes the open row it answers**, so one finding is not two
  rows.
"""

import unittest

from brightway_flows.integrations.commonchemistry import build_commonchemistry_index
from brightway_flows.pipeline.review_records import Severity
from brightway_flows.transformers.enrich_references import (
    EnrichReferencesTransformer,
    StructureCandidate,
)

KEY_IRI = EnrichReferencesTransformer.CHEMROF_INCHI2D_KEY_STRING

#: (+)-Tartaric acid, 87-69-4.  The registry publishes the neutral acid only.
ACID_CAS = "87-69-4"
ACID = "FEWJPZIEWOKRBE-JCYAYHJZSA-N"
DIANION = "FEWJPZIEWOKRBE-JCYAYHJZSA-L"
ACID_INCHI = (
    "InChI=1S/C4H6O6/c5-1(3(7)8)2(6)4(9)10/h1-2,5-6H,(H,7,8)(H,9,10)/t1-,2-/m1/s1"
)

#: 6-Aminohexanoic acid, 60-32-2: registered *flat*, and published beside its
#: anion.  Nothing about the shape is in dispute -- there is no shape -- so this
#: pair was reported nowhere at all before.
FLAT_CAS = "60-32-2"
FLAT_ACID = "SLXKOJJOQWFEFD-UHFFFAOYSA-N"
FLAT_ANION = "SLXKOJJOQWFEFD-UHFFFAOYSA-M"
FLAT_INCHI = "InChI=1S/C6H13NO2/c7-5-3-1-2-4-6(8)9/h1-5,7H2,(H,8,9)"

#: (2RS,4SR)-2-methyl-4-propyl-1,3-oxathiane, 59323-76-1: a relative
#: stereochemistry, so no standard key can ever be compared with the registry's.
#: The *charge* still can be.
RELATIVE_CAS = "59323-76-1"
RELATIVE_INCHI = (
    "InChI=1/C8H16OS/c1-3-4-8-5-6-9-7(2)10-8/h7-8H,3-6H2,1-2H3/t7-,8+/s2"
)
RELATIVE_THEIRS = "GKGOLPMYJJXRGD-HGXVMFPFNA-N"
RELATIVE_ANION = "GKGOLPMYJJXRGD-SFYZADRCSA-M"

#: Bornyl acetate, 5655-61-8: a genuine shape disagreement, and the row this
#: change must not disturb.
CONFLICT_CAS = "5655-61-8"
CONFLICT_OURS = "KGEKLUUHTZCSIP-SQLBVSGCSA-N"
CONFLICT_INCHI = (
    "InChI=1S/C12H20O2/c1-8(13)14-10-7-9-5-6-12(10,4)11(9,2)3/h9-10H,5-7H2,"
    "1-4H3/t9-,10+,12+/m0/s1"
)

DIFFERENT_SKELETON = "SCYULBFZEHDVBN-UHFFFAOYSA-M"
UNCACHED_CAS = "999999-99-9"

CACHE_RECORDS = {
    ACID_CAS: (ACID, ACID_INCHI, "C<sub>4</sub>H<sub>6</sub>O<sub>6</sub>"),
    FLAT_CAS: (FLAT_ACID, FLAT_INCHI, "C<sub>6</sub>H<sub>13</sub>NO<sub>2</sub>"),
    RELATIVE_CAS: (RELATIVE_THEIRS, RELATIVE_INCHI, "C<sub>8</sub>H<sub>16</sub>OS"),
    CONFLICT_CAS: (
        "KGEKLUUHTZCSIP-HOSYDEDBSA-N",
        CONFLICT_INCHI,
        "C<sub>12</sub>H<sub>20</sub>O<sub>2</sub>",
    ),
}


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


def semantic(values: list[str]) -> dict:
    return {KEY_IRI: {"@id": KEY_IRI, "@value": list(values), "provenance": []}}


def drop(instance, values: list[str], cas_numbers: list[str]) -> list[str]:
    payload = semantic(values)
    instance._drop_foreign_protonation_inchikeys(
        semantic=payload, cas_numbers=cas_numbers
    )
    return payload[KEY_IRI]["@value"]


class ClassificationTestCase(unittest.TestCase):
    def test_a_missing_hydrogen_ion_is_not_a_different_shape(self):
        self.assertEqual(
            transformer()._stereo_disagreement(
                cas=ACID_CAS, candidate=StructureCandidate(DIANION)
            ),
            "protonation",
        )

    def test_an_added_hydrogen_ion_is_the_same_finding(self):
        cation = "FEWJPZIEWOKRBE-JCYAYHJZSA-O"
        self.assertEqual(
            transformer()._stereo_disagreement(
                cas=ACID_CAS, candidate=StructureCandidate(cation)
            ),
            "protonation",
        )

    def test_a_flat_registration_still_answers_about_charge(self):
        """The gate that owns flat registrations is about shape, and says
        nothing about how many hydrogen ions a candidate carries."""
        self.assertEqual(
            transformer()._stereo_disagreement(
                cas=FLAT_CAS, candidate=StructureCandidate(FLAT_ANION)
            ),
            "protonation",
        )

    def test_charge_is_answered_where_shape_cannot_be(self):
        """The last block is not touched by the InChI options the stereo hash
        was computed under, so this comparison is valid where none other is."""
        self.assertEqual(
            transformer()._stereo_disagreement(
                cas=RELATIVE_CAS, candidate=StructureCandidate(RELATIVE_ANION)
            ),
            "protonation",
        )

    def test_the_same_charge_is_still_a_shape_question(self):
        self.assertEqual(
            transformer()._stereo_disagreement(
                cas=CONFLICT_CAS, candidate=StructureCandidate(CONFLICT_OURS)
            ),
            "conflict",
        )

    def test_a_different_skeleton_is_a_different_substance(self):
        self.assertIsNone(
            transformer()._stereo_disagreement(
                cas=ACID_CAS, candidate=StructureCandidate(DIFFERENT_SKELETON)
            )
        )

    def test_the_registrys_own_answer_disagrees_about_nothing(self):
        self.assertIsNone(
            transformer()._stereo_disagreement(
                cas=ACID_CAS, candidate=StructureCandidate(ACID)
            )
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
            if item.item_key == f"{cas}:protonation"
        )

    def test_the_row_no_longer_claims_a_stereochemistry_difference(self):
        title = self.row(ACID_CAS, DIANION).title
        self.assertNotIn("different stereochemistry", title)
        self.assertIn("different protonation state", title)
        self.assertIn(DIANION, title)
        self.assertIn(ACID, title)

    def test_an_unsettled_charge_difference_blocks(self):
        self.assertEqual(self.row(ACID_CAS, DIANION).severity, Severity.BLOCKING)

    def test_no_correction_is_offered(self):
        """The registry's neutral form is not the corrected key of an ion; which
        substance the object is for is the curator's question."""
        self.assertEqual(self.row(ACID_CAS, DIANION).payload["corrected_inchikey"], "")


class WithdrawalTestCase(unittest.TestCase):
    def test_the_ion_goes_and_the_registrys_answer_stays(self):
        self.assertEqual(drop(transformer(), [ACID, DIANION], [ACID_CAS]), [ACID])

    def test_order_does_not_matter(self):
        self.assertEqual(drop(transformer(), [DIANION, ACID], [ACID_CAS]), [ACID])

    def test_a_flat_pair_is_withdrawn_too(self):
        """Neither key states a shape, and they are still two substances."""
        self.assertEqual(
            drop(transformer(), [FLAT_ACID, FLAT_ANION], [FLAT_CAS]), [FLAT_ACID]
        )

    def test_every_ion_of_the_group_goes(self):
        cation = "FEWJPZIEWOKRBE-JCYAYHJZSA-O"
        self.assertEqual(
            drop(transformer(), [ACID, DIANION, cation], [ACID_CAS]), [ACID]
        )


class RestraintTestCase(unittest.TestCase):
    def test_nothing_goes_when_the_registrys_answer_is_absent(self):
        """Only the ion is published, and choosing a substance for the object is
        not this rule's to make."""
        self.assertEqual(drop(transformer(), [DIANION], [ACID_CAS]), [DIANION])

    def test_a_key_with_another_shape_is_left_to_the_shape_bands(self):
        other_shape = "FEWJPZIEWOKRBE-UHFFFAOYSA-L"
        self.assertEqual(
            drop(transformer(), [ACID, other_shape], [ACID_CAS]), [ACID, other_shape]
        )

    def test_a_different_skeleton_is_untouched(self):
        self.assertEqual(
            drop(transformer(), [ACID, DIFFERENT_SKELETON], [ACID_CAS]),
            [ACID, DIFFERENT_SKELETON],
        )

    def test_nothing_goes_on_a_relative_registration(self):
        """No comparable answer exists, so the registry breaks no ties here --
        the row stays open even though the charge difference is reportable."""
        self.assertEqual(
            drop(transformer(), [RELATIVE_THEIRS, RELATIVE_ANION], [RELATIVE_CAS]),
            [RELATIVE_THEIRS, RELATIVE_ANION],
        )

    def test_an_uncached_number_breaks_no_ties(self):
        self.assertEqual(
            drop(transformer(), [ACID, DIANION], [UNCACHED_CAS]), [ACID, DIANION]
        )

    def test_a_single_key_is_never_touched(self):
        self.assertEqual(drop(transformer(), [ACID], [ACID_CAS]), [ACID])


class ReportingTestCase(unittest.TestCase):
    def instance_after_drop(self) -> EnrichReferencesTransformer:
        instance = transformer()
        instance._record_stereo_disagreement(
            cas=ACID_CAS, source="CID:1", candidate=StructureCandidate(DIANION)
        )
        drop(instance, [ACID, DIANION], [ACID_CAS])
        return instance

    def test_the_removal_is_reported(self):
        entry = self.instance_after_drop()._stereo_disagreements[
            f"{ACID_CAS}:protonation-withdrawn"
        ]
        self.assertEqual(entry["published_inchikeys"], [DIANION])
        self.assertEqual(entry["corrected_inchikey"], ACID)

    def test_the_open_row_it_answers_is_closed(self):
        """One finding, one row: the curator is not asked to settle what the
        pipeline settled."""
        keys = sorted(self.instance_after_drop()._stereo_disagreements)
        self.assertEqual(keys, [f"{ACID_CAS}:protonation-withdrawn"])

    def test_the_source_of_the_closed_row_is_carried_over(self):
        entry = self.instance_after_drop()._stereo_disagreements[
            f"{ACID_CAS}:protonation-withdrawn"
        ]
        self.assertEqual(entry["sources"], ["CID:1"])

    def test_a_key_that_survived_keeps_its_open_row(self):
        instance = transformer()
        other_shape = "FEWJPZIEWOKRBE-UHFFFAOYSA-L"
        for candidate in (DIANION, other_shape):
            instance._record_stereo_disagreement(
                cas=ACID_CAS, source="CID:1", candidate=StructureCandidate(candidate)
            )
        drop(instance, [ACID, DIANION, other_shape], [ACID_CAS])
        self.assertEqual(
            instance._stereo_disagreements[f"{ACID_CAS}:protonation"][
                "published_inchikeys"
            ],
            [other_shape],
        )

    def test_a_withdrawn_key_is_not_reopened_by_a_later_flow(self):
        instance = self.instance_after_drop()
        self.assertIsNone(
            instance._stereo_disagreement(
                cas=ACID_CAS, candidate=StructureCandidate(DIANION)
            )
        )

    def test_a_discarded_structure_asks_for_review(self):
        item = next(
            item
            for item in self.instance_after_drop().review_queue_items()
            if item.item_key == f"{ACID_CAS}:protonation-withdrawn"
        )
        self.assertEqual(item.severity, Severity.REVIEW)

    def test_the_row_names_what_survived(self):
        item = next(
            item
            for item in self.instance_after_drop().review_queue_items()
            if item.item_key == f"{ACID_CAS}:protonation-withdrawn"
        )
        self.assertIn(f"the surviving key is {ACID}", item.title)
        self.assertIn(DIANION, item.title)


if __name__ == "__main__":
    unittest.main()
