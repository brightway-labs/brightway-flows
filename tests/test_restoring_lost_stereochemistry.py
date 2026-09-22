"""Filling in a stereochemistry the registry states and no other source holds.

`21862-63-5` is `trans-4-tert-butylcyclohexanol`. The name says which isomer it
is and CAS's structure says the same, but PubChem and ChEBI answer the number
with the shape-free compound -- the trans form is not a record either of them
holds -- so the flow object published `CCOQPGVQAWPUPE-UHFFFAOYSA-N`. That string
is also plain `4-tert-butylcyclohexanol`'s key, so the two substances collided on
it (#50), and #42's "stereo lost" band is seven flow objects in that position.

This is the one place the project *adds* a structure claim rather than refusing
one, so what is pinned here is mostly the refusals.

- **The registry is read as a structure, not as a key.** Six of the seven
  numbers are registered with a non-standard InChI whose key cannot be compared
  with anything else in the list, and it is the structure behind it that carries
  the answer.
- **A key is not evidence of a shape.** The second block hashes isotopes as
  well, so `Zinc-65` looks stereo-specific and has none; copying "its
  stereochemistry" across would stamp an isotope label onto ordinary zinc
  (#55).
- **A hole is required.** Where a source already supplied the specific key there
  is nothing to fill, and the redundant flat key is #50's business.
- **Relative and racemic registrations are refused**, because reading one back
  invents an absolute arrangement -- the defect #42 exists to stop.
- **A different skeleton and a different protonation are different questions**
  (#35, #38, #54).
- **What was repaired stops being reported as an open defect.**
"""

import unittest

from brightway_flows.domain.flow import Flow
from brightway_flows.integrations.commonchemistry import build_commonchemistry_index
from brightway_flows.pipeline.review_records import Severity
from brightway_flows.transformers.enrich_references import (
    EnrichReferencesTransformer,
    StructureCandidate,
)

#: trans-4-tert-butylcyclohexanol.  CAS states the trans arrangement in a
#: non-standard InChI; every source we look the number up in answers flat.
LOST_CAS = "21862-63-5"
LOST_FLAT = "CCOQPGVQAWPUPE-UHFFFAOYSA-N"
LOST_CAS_KEY = "CCOQPGVQAWPUPE-KYZUINATNA-N"
#: The same structure re-expressed as a standard key: same stereochemistry hash,
#: differing only in the character that records how the key was computed.
LOST_CORRECTED = "CCOQPGVQAWPUPE-KYZUINATSA-N"
LOST_CORRECTED_INCHI = (
    "InChI=1S/C10H20O/c1-10(2,3)8-4-6-9(11)7-5-8/h8-9,11H,4-7H2,1-3H3/t8-,9-"
)

#: (2RS,4SR)-2-methyl-4-propyl-1,3-oxathiane: `/s2`, relative stereochemistry.
RELATIVE_CAS = "59323-76-1"
RELATIVE_FLAT = "GKGOLPMYJJXRGD-UHFFFAOYSA-N"

#: Zinc-65.  A single atom, so no shape at all -- but `IGMARMGP` is not
#: `UHFFFAOY`, so a rule reading the key alone would call it stereo-specific.
ISOTOPE_CAS = "13982-39-3"
ISOTOPE_FLAT = "HCHKCACWOHOZIP-UHFFFAOYSA-N"

#: Crotonaldehyde: registered flat, and owned by the stereochemistry gate.
FLAT_CAS = "4170-30-3"

CACHE_RECORDS = {
    LOST_CAS: (
        LOST_CAS_KEY,
        "InChI=1/C10H20O/c1-10(2,3)8-4-6-9(11)7-5-8/h8-9,11H,4-7H2,1-3H3/t8-,9-",
        "C<sub>10</sub>H<sub>20</sub>O",
    ),
    RELATIVE_CAS: (
        "GKGOLPMYJJXRGD-HGXVMFPFNA-N",
        "InChI=1/C8H16OS/c1-3-4-8-5-6-9-7(2)10-8/h7-8H,3-6H2,1-2H3/t7-,8+/s2",
        "C<sub>8</sub>H<sub>16</sub>OS",
    ),
    ISOTOPE_CAS: (
        "HCHKCACWOHOZIP-IGMARMGPSA-N",
        "InChI=1S/Zn/i1+0",
        "Zn",
    ),
    FLAT_CAS: (
        "MLUCVPSAIODCQM-UHFFFAOYSA-N",
        "InChI=1S/C4H6O/c1-2-3-4-5/h2-4H,1H3",
        "C<sub>4</sub>H<sub>6</sub>O",
    ),
}


def cache_payload() -> dict:
    return {
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
    }


def transformer() -> EnrichReferencesTransformer:
    instance = EnrichReferencesTransformer()
    instance._commonchemistry = build_commonchemistry_index(cache_payload())
    instance._structure_rulings = {}
    return instance


def compound(cid: int, inchikey: str) -> dict:
    return {
        "cid": cid,
        "charge": 0,
        "props": [{"urn": {"label": "InChIKey"}, "value": {"sval": inchikey}}],
    }


class RestoringTestCase(unittest.TestCase):
    def test_the_registrys_structure_fills_the_hole(self):
        self.assertEqual(
            transformer()._restored_stereochemistry_for(
                cas=LOST_CAS, candidates=[StructureCandidate(LOST_FLAT)]
            ),
            LOST_CORRECTED,
        )

    def test_the_key_published_is_standard_not_the_registrys_own(self):
        """CAS's key is `…NA-N`, which no standard key can ever equal."""
        self.assertNotEqual(
            transformer()._restored_stereochemistry_for(
                cas=LOST_CAS, candidates=[StructureCandidate(LOST_FLAT)]
            ),
            LOST_CAS_KEY,
        )

    def test_the_inchi_published_matches_the_key_published(self):
        instance = transformer()
        self.assertEqual(
            instance._commonchemistry.comparable_inchi_for(LOST_CAS),
            LOST_CORRECTED_INCHI,
        )


class RefusalTestCase(unittest.TestCase):
    def test_an_isotope_label_is_not_a_stereochemistry(self):
        """Without this, plain zinc is handed zinc-65's key (#55)."""
        self.assertEqual(
            transformer()._restored_stereochemistry_for(
                cas=ISOTOPE_CAS, candidates=[StructureCandidate(ISOTOPE_FLAT)]
            ),
            "",
        )

    def test_a_relative_registration_is_refused(self):
        """Reading it back would invent an absolute arrangement."""
        self.assertEqual(
            transformer()._restored_stereochemistry_for(
                cas=RELATIVE_CAS, candidates=[StructureCandidate(RELATIVE_FLAT)]
            ),
            "",
        )

    def test_nothing_is_added_where_a_source_already_answered(self):
        """No hole to fill; the redundant flat key is #50's business."""
        self.assertEqual(
            transformer()._restored_stereochemistry_for(
                cas=LOST_CAS,
                candidates=[
                    StructureCandidate(LOST_FLAT),
                    StructureCandidate(LOST_CORRECTED),
                ],
            ),
            "",
        )

    def test_a_specific_candidate_that_disagrees_is_left_alone(self):
        """That is a conflict for a curator, not a hole to fill."""
        self.assertEqual(
            transformer()._restored_stereochemistry_for(
                cas=LOST_CAS, candidates=[StructureCandidate("CCOQPGVQAWPUPE-QMMMGPOBSA-N")]
            ),
            "",
        )

    def test_a_different_protonation_is_a_different_question(self):
        self.assertEqual(
            transformer()._restored_stereochemistry_for(
                cas=LOST_CAS, candidates=[StructureCandidate("CCOQPGVQAWPUPE-UHFFFAOYSA-M")]
            ),
            "",
        )

    def test_a_different_skeleton_is_a_different_substance(self):
        self.assertEqual(
            transformer()._restored_stereochemistry_for(
                cas=LOST_CAS, candidates=[StructureCandidate("SCYULBFZEHDVBN-UHFFFAOYSA-N")]
            ),
            "",
        )

    def test_a_flat_registration_belongs_to_the_gate(self):
        self.assertEqual(
            transformer()._restored_stereochemistry_for(
                cas=FLAT_CAS, candidates=[StructureCandidate("MLUCVPSAIODCQM-UHFFFAOYSA-N")]
            ),
            "",
        )

    def test_an_uncached_number_says_nothing(self):
        self.assertEqual(
            transformer()._restored_stereochemistry_for(
                cas="999999-99-9", candidates=[StructureCandidate(LOST_FLAT)]
            ),
            "",
        )

    def test_no_candidate_on_the_skeleton_is_not_a_hole(self):
        """An object that never had this structure is not missing a shape."""
        self.assertEqual(
            transformer()._restored_stereochemistry_for(cas=LOST_CAS, candidates=[]),
            "",
        )


class PublishedStructureTestCase(unittest.TestCase):
    def properties(self) -> dict:
        instance = transformer()
        restored = instance._restore_lost_stereochemistry(
            cas_numbers=[LOST_CAS],
            chebi_ids=[],
            pubchem_compounds=[compound(1, LOST_FLAT)],
        )
        self.assertEqual(restored, [LOST_CAS])
        return instance._build_properties(
            existing={},
            chebi_ids=[],
            pubchem_compounds=[compound(1, LOST_FLAT)],
            stereo_restored_cas=restored,
        )

    def test_the_corrected_key_is_published(self):
        entry = self.properties()[
            EnrichReferencesTransformer.CHEMROF_INCHI2D_KEY_STRING
        ]
        self.assertIn(LOST_CORRECTED, entry["@value"])

    def test_the_flat_key_it_supersedes_is_withdrawn(self):
        """`_drop_redundant_flat_inchikeys` takes it once the specific one lands."""
        entry = self.properties()[
            EnrichReferencesTransformer.CHEMROF_INCHI2D_KEY_STRING
        ]
        self.assertNotIn(LOST_FLAT, entry["@value"])

    def test_the_addition_is_attributed_to_itself(self):
        """A step that can add a claim is not folded into a gate's write."""
        entry = self.properties()[
            EnrichReferencesTransformer.CHEMROF_INCHI2D_KEY_STRING
        ]
        self.assertIn(
            "enrich_references.commonchemistry_stereochemistry",
            [p.get("prov:wasGeneratedBy") for p in entry["provenance"]],
        )


class ReportingTestCase(unittest.TestCase):
    def instance_after_repair(self) -> EnrichReferencesTransformer:
        instance = transformer()
        instance._pubchem_by_cas = {LOST_CAS: [compound(1, LOST_FLAT)]}
        instance._matched_pubchem_compounds(
            flow=Flow(uuid="u", identifier="i", name="", source="EF 3.1"),
            cas_numbers=[LOST_CAS],
            chebi_ids=[],
        )
        instance._restore_lost_stereochemistry(
            cas_numbers=[LOST_CAS],
            chebi_ids=[],
            pubchem_compounds=[compound(1, LOST_FLAT)],
        )
        return instance

    def test_a_repaired_number_is_no_longer_an_open_defect(self):
        self.assertNotIn(
            f"{LOST_CAS}:lost", self.instance_after_repair()._stereo_disagreements
        )

    def test_the_repair_is_reported_rather_than_done_silently(self):
        entry = self.instance_after_repair()._stereo_disagreements[
            f"{LOST_CAS}:restored"
        ]
        self.assertEqual(entry["corrected_inchikey"], LOST_CORRECTED)
        self.assertEqual(entry["published_inchikeys"], [LOST_FLAT])

    def test_the_repair_does_not_block(self):
        items = [
            item
            for item in self.instance_after_repair().review_queue_items()
            if item.item_key == f"{LOST_CAS}:restored"
        ]
        self.assertEqual([item.severity for item in items], [Severity.INFO])

    def test_a_second_flow_does_not_reopen_what_was_repaired(self):
        instance = self.instance_after_repair()
        instance._matched_pubchem_compounds(
            flow=Flow(uuid="u2", identifier="i2", name="", source="EF 3.1"),
            cas_numbers=[LOST_CAS],
            chebi_ids=[],
        )
        self.assertNotIn(f"{LOST_CAS}:lost", instance._stereo_disagreements)


if __name__ == "__main__":
    unittest.main()
