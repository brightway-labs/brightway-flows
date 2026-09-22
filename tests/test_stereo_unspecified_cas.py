"""A number registered without stereochemistry must not be given one.

CAS registers `4170-30-3` as `Crotonaldehyde` with the flat key
`MLUCVPSAIODCQM-UHFFFAOYSA-N`, and registers the *trans* isomer separately as
`123-73-9`.  The flat key is not a gap in the record; it is the registry saying
which of the two substances the number means.

Every source we look a structure up in disagrees, and all in the same direction.
ChEBI's entry for a common name is the stereo-defined natural isomer, and
PubChem's CAS index answers with the compound it has a record for -- a substance
with unstated stereochemistry is not a compound either of them holds.  So the
flow object got the *trans* key, and then collided under InChIKey with
`trans-2-butenal`, which is a different substance with its own registry number
(#35).

**The gates already here cannot catch this, and it is not an oversight in them.**
They are comparative: `_filter_compounds_by_curated_cas` and
`_filter_compounds_by_commonchemistry` weigh candidates against each other and
act only when one is better than another.  That is the right shape for "which of
these structures does the number mean".  It is the wrong shape here, because
there is no better candidate -- in 20 of the 33 flow objects PubChem and ChEBI
return the *same* stereo-specific structure, so nothing is contradicted, nothing
is confirmed, and the narrowing gate returns early exactly as designed.

So this gate reads Common Chemistry's flat key as a statement in its own right
rather than as a tie-break, and refuses a stereoisomer of it however many
sources offer one.

What is pinned here:

- **All three conditions are required.** CAS registers the number flat, the
  candidate shares the skeleton, and the candidate carries stereochemistry.
- **A flat candidate for a flat number is untouched.** That is 5,726 of the
  6,300 keyed numbers in the cache, and the overwhelming majority agree.
- **A different skeleton is not this gate's business.** #35 and #38 own that,
  and a stereochemistry rule must not quietly delete a wrong-hit structure.
- **A non-standard flat key states nothing.** Those options can suppress
  stereochemistry the substance has, and this gate refuses data.
- **Both lookup paths are gated.** ChEBI is where 32 of the 33 come from, and it
  had no Common Chemistry gate at all before this.
- **The structure CAS does publish is put back.** Withholding alone would trade
  #42 for #223 -- a flow object with no identity at all.
- **An uncached number changes nothing**, the rule every gate here follows.

Measured against the 2026-08-11 build, the gate fires on 33 flow objects: all
33 of #42's "stereo invented", and none of its "lost", none of its "conflict",
and none of the 318 skeleton disagreements.
"""

import unittest

from brightway_flows.domain.flow import Flow
from brightway_flows.integrations.commonchemistry import (
    CommonChemistryIndex,
    build_commonchemistry_index,
)
from brightway_flows.pipeline.review_records import ReviewQueue, Severity
from brightway_flows.transformers.enrich_references import (
    EnrichReferencesTransformer,
    StructureVerdict,
)

#: Crotonaldehyde: registered flat, with the isomers registered separately.
CROTONALDEHYDE_CAS = "4170-30-3"
CROTONALDEHYDE_FLAT = "MLUCVPSAIODCQM-UHFFFAOYSA-N"
CROTONALDEHYDE_INCHI = "InChI=1S/C4H6O/c1-2-3-4-5/h2-4H,1H3"
#: The *trans* isomer, which both PubChem and ChEBI answer 4170-30-3 with.
TRANS_KEY = "MLUCVPSAIODCQM-NSCUHMNNSA-N"
TRANS_CID = 5280498
FLAT_CID = 447466
TRANS_CHEBI = "http://purl.obolibrary.org/obo/CHEBI_15366"
#: A wholly different substance, to show the gate does not reach for it.
DICHLOROETHANE_KEY = "SCYULBFZEHDVBN-UHFFFAOYSA-N"
OTHER_CID = 6365
#: trans-4-tert-butylcyclohexanol: CAS registers it flat only in a *non-standard*
#: key, which states nothing about stereochemistry.
NONSTANDARD_CAS = "21862-63-5"
UNCACHED_CAS = "999999-99-9"


def compound(cid: int, inchikey: str = "") -> dict:
    props = []
    if inchikey:
        props.append({"urn": {"label": "InChIKey"}, "value": {"sval": inchikey}})
    return {"cid": cid, "charge": 0, "props": props}


def cache_payload() -> dict:
    return {
        "detail_by_cas": {
            CROTONALDEHYDE_CAS: {
                "rn": CROTONALDEHYDE_CAS,
                "name": "Crotonaldehyde",
                "molecularFormula": "C<sub>4</sub>H<sub>6</sub>O",
                "inchi": CROTONALDEHYDE_INCHI,
                "inchiKey": f"InChIKey={CROTONALDEHYDE_FLAT}",
            },
            NONSTANDARD_CAS: {
                "rn": NONSTANDARD_CAS,
                "name": "trans-4-tert-Butylcyclohexanol",
                "molecularFormula": "C<sub>10</sub>H<sub>20</sub>O",
                # A flat *hash* in a non-standard key: the options behind it can
                # suppress stereochemistry the substance has.
                "inchiKey": "InChIKey=CCOQPGVQAWPUPE-UHFFFAOYNA-N",
            },
        }
    }


def transformer(index: CommonChemistryIndex | None = None) -> EnrichReferencesTransformer:
    """A transformer with only the tables this gate consults.

    `setup()` is not called: it loads the ChEBI index and the whole PubChem
    cache off disk, and neither is what is under test.
    """
    instance = EnrichReferencesTransformer()
    instance._commonchemistry = (
        build_commonchemistry_index(cache_payload()) if index is None else index
    )
    instance._structure_rulings = {}
    instance._pubchem_by_cas = {CROTONALDEHYDE_CAS: [compound(TRANS_CID, TRANS_KEY)]}
    instance._chebi_by_cas = {CROTONALDEHYDE_CAS: [TRANS_CHEBI]}
    instance._chebi_records = {
        TRANS_CHEBI: {
            "formula": "C4H6O",
            "cas_numbers": [CROTONALDEHYDE_CAS],
            "basic_property_values": {"inchi_key_string": [TRANS_KEY]},
        }
    }
    return instance


class IndexTestCase(unittest.TestCase):
    def test_a_flat_standard_key_is_a_statement(self):
        index = build_commonchemistry_index(cache_payload())
        self.assertTrue(index.registers_without_stereochemistry(CROTONALDEHYDE_CAS))

    def test_a_flat_non_standard_key_is_not(self):
        """Those options can suppress stereochemistry the substance has."""
        index = build_commonchemistry_index(cache_payload())
        self.assertFalse(index.registers_without_stereochemistry(NONSTANDARD_CAS))

    def test_an_uncached_number_states_nothing(self):
        index = build_commonchemistry_index(cache_payload())
        self.assertFalse(index.registers_without_stereochemistry(UNCACHED_CAS))

    def test_the_structure_behind_the_key_is_available(self):
        """The gate has to be able to put back what it takes away."""
        index = build_commonchemistry_index(cache_payload())
        self.assertEqual(index.inchi_for(CROTONALDEHYDE_CAS), CROTONALDEHYDE_INCHI)
        self.assertEqual(index.formula_for(CROTONALDEHYDE_CAS), "C4H6O")

    def test_an_index_built_without_them_still_works(self):
        """The three-argument constructor is used across the tests here."""
        index = CommonChemistryIndex({CROTONALDEHYDE_CAS: CROTONALDEHYDE_FLAT}, set(), set())
        self.assertTrue(index.registers_without_stereochemistry(CROTONALDEHYDE_CAS))
        self.assertIsNone(index.inchi_for(CROTONALDEHYDE_CAS))


class InventsStereochemistryTestCase(unittest.TestCase):
    """All three conditions, one at a time."""

    def test_a_stereoisomer_of_a_flat_registration_is_refused(self):
        self.assertTrue(
            transformer()._invents_stereochemistry(
                cas=CROTONALDEHYDE_CAS, candidate=TRANS_KEY
            )
        )

    def test_a_flat_candidate_agrees(self):
        """5,726 of the 6,300 keyed numbers are flat; this is the normal case."""
        self.assertFalse(
            transformer()._invents_stereochemistry(
                cas=CROTONALDEHYDE_CAS, candidate=CROTONALDEHYDE_FLAT
            )
        )

    def test_a_different_skeleton_is_a_different_bug(self):
        """#35 and #38 own that, and must not be acted on by this rule."""
        self.assertFalse(
            transformer()._invents_stereochemistry(
                cas=CROTONALDEHYDE_CAS, candidate=DICHLOROETHANE_KEY
            )
        )

    def test_a_non_standard_registration_refuses_nothing(self):
        self.assertFalse(
            transformer()._invents_stereochemistry(
                cas=NONSTANDARD_CAS, candidate="CCOQPGVQAWPUPE-KYZUINATSA-N"
            )
        )

    def test_an_uncached_number_refuses_nothing(self):
        self.assertFalse(
            transformer()._invents_stereochemistry(cas=UNCACHED_CAS, candidate=TRANS_KEY)
        )

    def test_an_unreadable_candidate_refuses_nothing(self):
        for candidate in ("", "rubbish"):
            with self.subTest(candidate=candidate):
                self.assertFalse(
                    transformer()._invents_stereochemistry(
                        cas=CROTONALDEHYDE_CAS, candidate=candidate
                    )
                )


class PubChemPathTestCase(unittest.TestCase):
    def test_the_unopposed_stereoisomer_is_dropped(self):
        """One candidate, nothing to weigh it against, and still refused.

        The narrowing gate returns early here -- `len(compounds) < 2` -- which
        is why this rule cannot be expressed as one more comparison.
        """
        instance = transformer()
        kept = instance._filter_compounds_by_stereo_specificity(
            cas=CROTONALDEHYDE_CAS, compounds=[compound(TRANS_CID, TRANS_KEY)]
        )
        self.assertEqual(kept, [])
        self.assertEqual(
            instance._stereo_exclusions[CROTONALDEHYDE_CAS]["dropped_cids"], [TRANS_CID]
        )

    def test_the_flat_candidate_survives_beside_it(self):
        instance = transformer()
        kept = instance._filter_compounds_by_stereo_specificity(
            cas=CROTONALDEHYDE_CAS,
            compounds=[
                compound(TRANS_CID, TRANS_KEY),
                compound(FLAT_CID, CROTONALDEHYDE_FLAT),
                compound(OTHER_CID, DICHLOROETHANE_KEY),
            ],
        )
        self.assertEqual([c["cid"] for c in kept], [FLAT_CID, OTHER_CID])

    def test_a_quiet_number_records_nothing(self):
        instance = transformer()
        instance._filter_compounds_by_stereo_specificity(
            cas=CROTONALDEHYDE_CAS, compounds=[compound(FLAT_CID, CROTONALDEHYDE_FLAT)]
        )
        self.assertEqual(instance._stereo_exclusions, {})

    def test_the_end_to_end_lookup_yields_nothing(self):
        instance = transformer()
        flow = Flow(uuid="u", identifier="i", name="Crotonaldehyde", source="EF 3.1")
        self.assertEqual(
            instance._matched_pubchem_compounds(
                flow=flow, cas_numbers=[CROTONALDEHYDE_CAS], chebi_ids=[]
            ),
            [],
        )


class ChebiPathTestCase(unittest.TestCase):
    """32 of the 33 come from here, and it had no registry gate at all."""

    def test_the_stereo_defined_record_is_refused(self):
        instance = transformer()
        self.assertEqual(instance._matched_chebi_ids([CROTONALDEHYDE_CAS]), [])
        self.assertEqual(
            instance._stereo_exclusions[CROTONALDEHYDE_CAS]["dropped_chebi_ids"],
            [TRANS_CHEBI],
        )

    def test_a_record_with_no_key_is_kept(self):
        """Absence of data is not a rejection reason, here as everywhere."""
        instance = transformer()
        instance._chebi_records[TRANS_CHEBI]["basic_property_values"] = {}
        self.assertEqual(instance._matched_chebi_ids([CROTONALDEHYDE_CAS]), [TRANS_CHEBI])

    def test_a_record_reached_through_a_second_number_survives(self):
        """Only refused if every number it was reached through registers flat.

        A record matched through a number that *does* have stereochemistry is
        that number's answer, and the flat one has no standing to withhold it.
        """
        instance = transformer()
        instance._chebi_by_cas["123-73-9"] = [TRANS_CHEBI]
        self.assertEqual(
            instance._matched_chebi_ids([CROTONALDEHYDE_CAS, "123-73-9"]),
            [TRANS_CHEBI],
        )

    def test_both_paths_report_into_one_entry(self):
        """A curator needs the whole cause, not whichever half ran first."""
        instance = transformer()
        instance._matched_chebi_ids([CROTONALDEHYDE_CAS])
        instance._filter_compounds_by_stereo_specificity(
            cas=CROTONALDEHYDE_CAS, compounds=[compound(TRANS_CID, TRANS_KEY)]
        )
        entry = instance._stereo_exclusions[CROTONALDEHYDE_CAS]
        self.assertEqual(entry["dropped_cids"], [TRANS_CID])
        self.assertEqual(entry["dropped_chebi_ids"], [TRANS_CHEBI])
        self.assertEqual(entry["reason"], StructureVerdict.STEREO_UNSPECIFIED.value)


class ReplacementStructureTestCase(unittest.TestCase):
    """Withholding alone would trade #42 for #223."""

    def test_the_registered_structure_is_published(self):
        instance = transformer()
        properties = instance._build_properties(
            existing={},
            chebi_ids=[],
            pubchem_compounds=[],
            stereo_unspecified_cas=[CROTONALDEHYDE_CAS],
        )
        key = properties[EnrichReferencesTransformer.CHEMROF_INCHI2D_KEY_STRING]
        self.assertEqual(key["@value"], [CROTONALDEHYDE_FLAT])
        self.assertEqual(
            properties[EnrichReferencesTransformer.CHEMROF_INCHI2D_STRING]["@value"],
            [CROTONALDEHYDE_INCHI],
        )
        self.assertEqual(
            properties[EnrichReferencesTransformer.CHEMROF_MOLECULAR_FORMULA]["@value"],
            ["C4H6O"],
        )

    def test_the_registry_is_named_in_the_provenance(self):
        instance = transformer()
        properties = instance._build_properties(
            existing={},
            chebi_ids=[],
            pubchem_compounds=[],
            stereo_unspecified_cas=[CROTONALDEHYDE_CAS],
        )
        provenance = properties[
            EnrichReferencesTransformer.CHEMROF_INCHI2D_KEY_STRING
        ]["provenance"]
        entries = provenance if isinstance(provenance, list) else [provenance]
        generated = {entry["prov:wasGeneratedBy"] for entry in entries}
        self.assertIn("enrich_references.commonchemistry_semantic", generated)
        self.assertIn(
            [f"CAS:{CROTONALDEHYDE_CAS}"],
            [entry.get("prov:hadPrimarySource") for entry in entries],
        )

    def test_no_smiles_is_invented(self):
        """A value computed from the InChI belongs to the stage that computes it."""
        instance = transformer()
        properties = instance._build_properties(
            existing={},
            chebi_ids=[],
            pubchem_compounds=[],
            stereo_unspecified_cas=[CROTONALDEHYDE_CAS],
        )
        self.assertNotIn(
            EnrichReferencesTransformer.CHEMROF_SMILES_STRING, properties
        )

    def test_nothing_is_published_for_an_ungated_number(self):
        """The replacement follows the refusal; it is not a general rule."""
        instance = transformer()
        properties = instance._build_properties(
            existing={}, chebi_ids=[], pubchem_compounds=[], stereo_unspecified_cas=[]
        )
        self.assertNotIn(
            EnrichReferencesTransformer.CHEMROF_INCHI2D_KEY_STRING, properties
        )


class ReviewQueueTestCase(unittest.TestCase):
    def test_the_refusal_asks_for_review(self):
        instance = transformer()
        instance._matched_chebi_ids([CROTONALDEHYDE_CAS])
        items = [
            item for item in instance.review_queue_items()
            if item.item_key.endswith(":stereo")
        ]
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].queue_name, ReviewQueue.COMMONCHEM_STRUCTURE_EXCLUSION)
        self.assertEqual(items[0].cas, CROTONALDEHYDE_CAS)
        self.assertIs(items[0].severity, Severity.REVIEW)
        self.assertIn("without stereochemistry", items[0].title)

    def test_it_does_not_collide_with_the_other_structure_queue(self):
        """Both key on the CAS, and `item_key` has to stay unique per queue."""
        instance = transformer()
        instance._matched_chebi_ids([CROTONALDEHYDE_CAS])
        instance._structure_exclusions[CROTONALDEHYDE_CAS] = {
            "cas": CROTONALDEHYDE_CAS,
            "reason": StructureVerdict.NO_STRUCTURE.value,
            "dropped_cids": [],
            "dropped_chebi_ids": [],
        }
        keys = [
            item.item_key for item in instance.review_queue_items()
            if item.queue_name == ReviewQueue.COMMONCHEM_STRUCTURE_EXCLUSION
        ]
        self.assertEqual(len(keys), len(set(keys)))

    def test_a_quiet_run_queues_nothing(self):
        self.assertEqual(transformer().review_queue_items(), [])
