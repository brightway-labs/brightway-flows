"""Two specific keys for one substance, and the registry breaking the tie.

`_drop_redundant_flat_inchikeys` handles a *flat* key beside a specific one
(#50). This is the other way one flow object ends up publishing two identities:
**two stereochemistry-bearing keys on the same skeleton**, one from ChEBI and one
from PubChem, with nothing reconciling the two lookup paths against each other.

`Pyrethrin I` publishes `ROVGZAWFACYCSP-VUMXUWRFSA-N` and
`ROVGZAWFACYCSP-NEWSRXKRSA-N`. The second is the first with the double-bond
geometry left out, and anything using an InChIKey as an identity sees two
substances.

What is pinned here:

- **The tie is broken only where the registry breaks it**, and only when one of
  the object's own keys *is* the registry's answer. Nothing is chosen; the
  others are observed to describe something else.
- **A group where nothing matches the registry is left alone.** That is the
  `conflict` band, and it wants a curator (#56).
- **A flat key in the group survives**, because it states nothing the specific
  one contradicts -- #50 owns it.
- **A different skeleton and a different protonation are different questions**
  (#35, #38, #54).
- **The removal is reported**, at `REVIEW`, because a structure claim is being
  discarded.
"""

import unittest

from brightway_flows.integrations.commonchemistry import build_commonchemistry_index
from brightway_flows.pipeline.review_records import Severity
from brightway_flows.transformers.enrich_references import (
    EnrichReferencesTransformer,
)

KEY_IRI = EnrichReferencesTransformer.CHEMROF_INCHI2D_KEY_STRING

#: Pyrethrin I.  CAS states the double-bond geometry; one of our two sources
#: does not, and its key differs completely as a result.
CAS = "121-21-1"
KEPT = "ROVGZAWFACYCSP-VUMXUWRFSA-N"
RIVAL = "ROVGZAWFACYCSP-NEWSRXKRSA-N"
FLAT = "ROVGZAWFACYCSP-UHFFFAOYSA-N"
CAS_INCHI = (
    "InChI=1S/C21H28O3/c1-7-8-9-10-15-14(4)18(12-17(15)22)24-20(23)19-"
    "16(11-13(2)3)21(19,5)6/h7-9,11,16,18-19H,1,10,12H2,2-6H3/b9-8-/t16-"
    ",18+,19+/m1/s1"
)

#: A number whose structure states a relative arrangement: no comparable answer
#: exists, so nothing may be withdrawn on its authority.
RELATIVE_CAS = "59323-76-1"
RELATIVE_INCHI = (
    "InChI=1/C8H16OS/c1-3-4-8-5-6-9-7(2)10-8/h7-8H,3-6H2,1-2H3/t7-,8+/s2"
)
RELATIVE_A = "GKGOLPMYJJXRGD-SFYZADRCSA-N"
RELATIVE_B = "GKGOLPMYJJXRGD-JGVFFNPUSA-N"

#: A number where neither of our keys is the registry's: the conflict band.
CONFLICT_CAS = "16118-49-3"
CONFLICT_INCHI = (
    "InChI=1S/C12H16N2O3/c1-3-13-11(15)9(2)17-12(16)14-10-7-5-4-6-8-"
    "10/h4-9H,3H2,1-2H3,(H,13,15)(H,14,16)/t9-/m1/s1"
)
CONFLICT_A = "AMRQXHFXNZFDCH-VIFPVBQESA-N"
CONFLICT_B = "AMRQXHFXNZFDCH-QGZVFWFLSA-N"

CACHE_RECORDS = {
    CAS: (KEPT, CAS_INCHI, "C<sub>21</sub>H<sub>28</sub>O<sub>3</sub>"),
    RELATIVE_CAS: (
        "GKGOLPMYJJXRGD-HGXVMFPFNA-N",
        RELATIVE_INCHI,
        "C<sub>8</sub>H<sub>16</sub>OS",
    ),
    CONFLICT_CAS: (
        "AMRQXHFXNZFDCH-SECBINFHSA-N",
        CONFLICT_INCHI,
        "C<sub>12</sub>H<sub>16</sub>N<sub>2</sub>O<sub>3</sub>",
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
    instance._drop_superseded_stereo_inchikeys(
        semantic=payload, cas_numbers=cas_numbers
    )
    return payload[KEY_IRI]["@value"]


class WithdrawalTestCase(unittest.TestCase):
    def test_the_rival_goes_and_the_registrys_answer_stays(self):
        self.assertEqual(drop(transformer(), [KEPT, RIVAL], [CAS]), [KEPT])

    def test_order_does_not_matter(self):
        self.assertEqual(drop(transformer(), [RIVAL, KEPT], [CAS]), [KEPT])

    def test_a_flat_key_in_the_group_is_left_for_334(self):
        """It states nothing the specific key contradicts."""
        self.assertEqual(
            drop(transformer(), [KEPT, RIVAL, FLAT], [CAS]), [KEPT, FLAT]
        )


class RestraintTestCase(unittest.TestCase):
    def test_nothing_goes_when_the_registrys_answer_is_absent(self):
        """The conflict band: both specific, neither confirmed, curator's call."""
        self.assertEqual(
            drop(transformer(), [CONFLICT_A, CONFLICT_B], [CONFLICT_CAS]),
            [CONFLICT_A, CONFLICT_B],
        )

    def test_nothing_goes_on_a_relative_registration(self):
        """No comparable answer exists, so the registry breaks no ties here."""
        self.assertEqual(
            drop(transformer(), [RELATIVE_A, RELATIVE_B], [RELATIVE_CAS]),
            [RELATIVE_A, RELATIVE_B],
        )

    def test_a_different_skeleton_is_untouched(self):
        other = "SCYULBFZEHDVBN-UHFFFAOYSA-N"
        self.assertEqual(
            drop(transformer(), [KEPT, RIVAL, other], [CAS]), [KEPT, other]
        )

    def test_a_different_protonation_is_untouched(self):
        anion = "ROVGZAWFACYCSP-NEWSRXKRSA-M"
        self.assertEqual(
            drop(transformer(), [KEPT, anion], [CAS]), [KEPT, anion]
        )

    def test_a_single_key_is_never_touched(self):
        self.assertEqual(drop(transformer(), [RIVAL], [CAS]), [RIVAL])

    def test_an_uncached_number_breaks_no_ties(self):
        self.assertEqual(
            drop(transformer(), [KEPT, RIVAL], ["999999-99-9"]), [KEPT, RIVAL]
        )


class ReportingTestCase(unittest.TestCase):
    def instance_after_drop(self) -> EnrichReferencesTransformer:
        instance = transformer()
        drop(instance, [KEPT, RIVAL], [CAS])
        return instance

    def test_the_removal_is_reported(self):
        entry = self.instance_after_drop()._stereo_disagreements[f"{CAS}:superseded"]
        self.assertEqual(entry["published_inchikeys"], [RIVAL])
        self.assertEqual(entry["corrected_inchikey"], KEPT)

    def test_a_discarded_structure_asks_for_review(self):
        items = [
            item
            for item in self.instance_after_drop().review_queue_items()
            if item.item_key == f"{CAS}:superseded"
        ]
        self.assertEqual([item.severity for item in items], [Severity.REVIEW])

    def test_the_row_names_what_survived_not_what_should_replace_it(self):
        item = next(
            item
            for item in self.instance_after_drop().review_queue_items()
            if item.item_key == f"{CAS}:superseded"
        )
        self.assertIn(f"the surviving key is {KEPT}", item.title)
        self.assertIn(RIVAL, item.title)


if __name__ == "__main__":
    unittest.main()
