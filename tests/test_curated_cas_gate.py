"""A CAS link PubChem's own curated record does not support is not evidence.

`pubchem-data.json`'s `by_cas` comes from PubChem's `xref/RN` index, which
aggregates the CAS numbers of every *substance* record standardised onto a
compound.  Vendor catalogue entries are substance records, and a vendor that
types the wrong CAS into its catalogue puts that number on a compound it does
not belong to.  Nothing downstream could tell: every CID the index returned was
merged into the flow object with equal weight.

The worked case is `fo-5c5d410a3e086625`, tert-amyl peroxy-2-ethylhexanoate,
CAS 686-31-7.  Two vendor listings -- AAA Chemistry SID 103827914 and Amadis
Chemical SID 131323647 -- carry that number on magnesium bis(quinolin-8-olate),
so `xref/RN` returns CID 106206 alongside the two correct compounds, and the
substance published two molecular formulas, three InChI and four SMILES across
two unrelated compounds.  PubChem's curated CAS section for CID 106206 lists
67952-28-7 and 14639-28-2, and not 686-31-7.

What is pinned here:

- **A contradicted compound is dropped, an attested one is kept.**
- **An unknown compound is kept.** The gate must never let a gap in the
  identifier cache decide identity.
- **No attestation anywhere means no filtering.** There has to be a better
  answer before a worse one is discarded.
- **"Asked, and PubChem holds none" is stored, and is different from "not
  asked".** The distinction the whole rule rests on, and the one the fetcher
  used to throw away.
"""

import unittest

from brightway_flows.integrations.fetch_pubchem_identifiers import (
    NoOtherIdentifiers,
    extract_other_identifiers,
)
from brightway_flows.domain.flow import Flow
from brightway_flows.integrations.pubchem import store_identifiers
from brightway_flows.transformers.enrich_references import (
    CasAttestation,
    EnrichReferencesTransformer,
)

#: The real case, trimmed to the fields the gate reads.
PEROXYESTER = 102465
PEROXYESTER_R = 121489259
MAGNESIUM_SALT = 106206
CAS = "686-31-7"


def compound(cid: int) -> dict:
    return {"cid": cid, "charge": 0, "props": []}


def transformer(*, identifiers: dict) -> EnrichReferencesTransformer:
    """A transformer with only the two tables the gate consults populated.

    `setup()` is not called: it loads the ChEBI index and the whole PubChem
    cache off disk, and neither is what is under test here.
    """
    instance = EnrichReferencesTransformer()
    instance._pubchem_identifiers_by_cid = identifiers
    return instance


def curated_identifiers() -> dict:
    """CID 102465 attests the CAS; CID 106206 lists two others and not it."""
    return {
        str(PEROXYESTER): {
            "CAS": [{
                "value": CAS,
                "sources": ["CAS Common Chemistry", "European Chemicals Agency (ECHA)"],
            }],
        },
        str(MAGNESIUM_SALT): {
            "CAS": [
                {"value": "67952-28-7", "sources": ["CAS Common Chemistry"]},
                {"value": "14639-28-2", "sources": ["European Chemicals Agency (ECHA)"]},
            ],
        },
    }


class CuratedCasGateTestCase(unittest.TestCase):
    def setUp(self):
        self.identifiers = curated_identifiers()

    def test_the_vendor_supplied_link_is_dropped(self):
        instance = transformer(identifiers=self.identifiers)
        kept = instance._filter_compounds_by_curated_cas(
            cas=CAS,
            compounds=[compound(PEROXYESTER), compound(MAGNESIUM_SALT)],
        )
        self.assertEqual([c["cid"] for c in kept], [PEROXYESTER])

    def test_an_uncached_compound_is_kept(self):
        """A gap in the cache must not decide identity.

        CID 121489259 is the (2R) enantiomer: a real compound, and one whose
        PUG View record has no "Other Identifiers" section at all.  Before the
        backfill it was simply absent from `identifiers`, and a rule that
        dropped what it had not asked about would have discarded it.
        """
        instance = transformer(identifiers=self.identifiers)
        kept = instance._filter_compounds_by_curated_cas(
            cas=CAS,
            compounds=[
                compound(PEROXYESTER),
                compound(PEROXYESTER_R),
                compound(MAGNESIUM_SALT),
            ],
        )
        self.assertEqual(
            [c["cid"] for c in kept], [PEROXYESTER, PEROXYESTER_R]
        )

    def test_nothing_attested_means_nothing_filtered(self):
        """Without a better answer, the ambiguity stands rather than being guessed."""
        instance = transformer(identifiers={
            str(MAGNESIUM_SALT): self.identifiers[str(MAGNESIUM_SALT)],
            str(PEROXYESTER): {"CAS": [{"value": "7012-16-0", "sources": ["x"]}]},
        })
        compounds = [compound(PEROXYESTER), compound(MAGNESIUM_SALT)]
        kept = instance._filter_compounds_by_curated_cas(cas=CAS, compounds=compounds)
        self.assertEqual([c["cid"] for c in kept], [PEROXYESTER, MAGNESIUM_SALT])
        self.assertEqual(instance._curated_cas_exclusions, {})

    def test_a_single_candidate_is_never_filtered(self):
        """One candidate is not ambiguous, whatever its curated record says."""
        instance = transformer(identifiers=self.identifiers)
        kept = instance._filter_compounds_by_curated_cas(
            cas=CAS, compounds=[compound(MAGNESIUM_SALT)]
        )
        self.assertEqual([c["cid"] for c in kept], [MAGNESIUM_SALT])

    def test_an_empty_curated_record_contradicts(self):
        """`{}` is PubChem answering, not PubChem being unavailable."""
        instance = transformer(identifiers={
            str(PEROXYESTER): self.identifiers[str(PEROXYESTER)],
            str(MAGNESIUM_SALT): {},
        })
        self.assertIs(
            instance._cas_attestation(cas=CAS, cid=MAGNESIUM_SALT),
            CasAttestation.CONTRADICTED,
        )
        self.assertIs(
            instance._cas_attestation(cas=CAS, cid=PEROXYESTER_R),
            CasAttestation.UNKNOWN,
        )
        self.assertIs(
            instance._cas_attestation(cas=CAS, cid=PEROXYESTER),
            CasAttestation.ATTESTED,
        )

    def test_a_second_curated_cas_still_attests(self):
        """Membership, not primacy.

        `consensus_match` reads only the first entry of the curated list as the
        compound's "primary" CAS.  A compound legitimately carrying several
        registry numbers would be rejected for all but one of them, so this
        gate asks whether the number is in the list at all.
        """
        instance = transformer(identifiers={
            str(PEROXYESTER): {
                "CAS": [
                    {"value": "7012-16-0", "sources": ["ChemIDplus"]},
                    {"value": CAS, "sources": ["CAS Common Chemistry"]},
                ],
            },
        })
        self.assertIs(
            instance._cas_attestation(cas=CAS, cid=PEROXYESTER),
            CasAttestation.ATTESTED,
        )

    def test_the_exclusion_is_recorded_for_a_curator(self):
        instance = transformer(identifiers=self.identifiers)
        instance._filter_compounds_by_curated_cas(
            cas=CAS,
            compounds=[
                compound(PEROXYESTER),
                compound(PEROXYESTER_R),
                compound(MAGNESIUM_SALT),
            ],
        )
        self.assertEqual(instance._curated_cas_exclusions[CAS], {
            "cas": CAS,
            "kept_cids": [PEROXYESTER, PEROXYESTER_R],
            "dropped_cids": [MAGNESIUM_SALT],
            "unknown_cids": [PEROXYESTER_R],
        })

        items = instance.review_queue_items()
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].cas, CAS)
        self.assertEqual(items[0].payload["dropped_cids"], [MAGNESIUM_SALT])


class GateAdmitsNothingTestCase(unittest.TestCase):
    """The gate removes candidates. It must never be the reason one is kept.

    Found by the verification run, not by the tests above.  The gate first
    narrowed `cas_compounds` itself, and `len(cas_compounds) > 1` two lines
    below is the test for whether the CAS was ambiguous *at all* -- the ChEBI
    branch rejects every candidate for an ambiguous CAS that no ChEBI record
    supports.  Narrowing three candidates to one made that test false, the
    rejection stopped firing, and a compound `main` discarded was enriched
    from instead.

    Dinitrophenol, CAS 25550-58-7, went from carrying no structure at all to
    `O=NO.O=NO.Oc1ccccc1` -- phenol with two nitrous acids beside it, C6H8N2O5,
    for a substance whose formula is C6H4N2O5.
    """

    def test_a_narrowed_cas_is_still_an_ambiguous_cas(self):
        instance = transformer(identifiers={
            "1493": {"CAS": [{"value": "25550-58-7", "sources": ["ChemIDplus"]}]},
            "6191": {"CAS": [{"value": "51-28-5", "sources": ["ChemIDplus"]}]},
            "156614053": {"CAS": [{"value": "329-71-5", "sources": ["ChemIDplus"]}]},
        })
        instance._pubchem_by_cas = {
            "25550-58-7": [compound(1493), compound(6191), compound(156614053)],
        }
        flow = Flow(uuid="u-1", name="Dinitrophenol", cas_numbers=["25550-58-7"])

        # The gate leaves one candidate, and it carries no ChEBI cross-reference
        # -- so the ChEBI branch rejects it, exactly as it did before the gate.
        self.assertEqual(
            instance._matched_pubchem_compounds(
                flow=flow,
                cas_numbers=["25550-58-7"],
                chebi_ids=["CHEBI:39352"],
            ),
            [],
        )

    def test_the_gate_still_narrows_when_nothing_downstream_objects(self):
        instance = transformer(identifiers=curated_identifiers())
        instance._pubchem_by_cas = {
            CAS: [compound(PEROXYESTER), compound(MAGNESIUM_SALT)],
        }
        flow = Flow(uuid="u-2", name="tert-Amyl peroxy-2-ethylhexanoate", cas_numbers=[CAS])
        selected = instance._matched_pubchem_compounds(
            flow=flow, cas_numbers=[CAS], chebi_ids=[]
        )
        self.assertEqual([c["cid"] for c in selected], [PEROXYESTER])


class IdentifierCacheTestCase(unittest.TestCase):
    """"Asked, and there is nothing" has to be storable."""

    def test_a_record_without_identifiers_raises_its_own_error(self):
        data = {"Record": {"Section": [{"TOCHeading": "Structures"}]}}
        with self.assertRaises(NoOtherIdentifiers):
            extract_other_identifiers(data)

    def test_a_record_without_identifiers_is_cached_as_empty(self):
        cache = {"identifiers": {}}
        store_identifiers(
            cache, "121489259", {"Record": {"Section": [{"TOCHeading": "Structures"}]}}
        )
        self.assertEqual(cache["identifiers"], {"121489259": {}})

    def test_a_malformed_response_is_not_cached(self):
        """Left absent so the next run asks again."""
        cache = {"identifiers": {}}
        store_identifiers(cache, "121489259", {"Fault": {"Code": "PUGVIEW.NotFound"}})
        self.assertEqual(cache["identifiers"], {})

    def test_identifiers_are_extracted_and_stored(self):
        data = {
            "Record": {
                "Reference": [{"ReferenceNumber": 1, "SourceName": "CAS Common Chemistry"}],
                "Section": [{
                    "TOCHeading": "Names and Identifiers",
                    "Section": [{
                        "TOCHeading": "Other Identifiers",
                        "Section": [{
                            "TOCHeading": "CAS",
                            "Information": [{
                                "ReferenceNumber": 1,
                                "Value": {"StringWithMarkup": [{"String": CAS}]},
                            }],
                        }],
                    }],
                }],
            }
        }
        cache = {"identifiers": {}}
        store_identifiers(cache, str(PEROXYESTER), data)
        self.assertEqual(
            cache["identifiers"][str(PEROXYESTER)]["CAS"],
            [{"value": CAS, "sources": ["CAS Common Chemistry"]}],
        )


if __name__ == "__main__":
    unittest.main()
