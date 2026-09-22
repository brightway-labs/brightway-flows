"""What CAS and this list disagree about, and which of those is a disagreement.

Two of #42's three bands are not fixable by a gate. Where CAS gives a number a
stereochemistry and the structure we publish is flat, the direction is certain
but the correction is not available -- in nine of the ten cases CAS's key comes
from a non-standard InChI and cannot be copied in as a value. Where both sides
are specific and standard and they disagree, neither source can be trusted
silently. Both want a curator, and until this queue existed neither was reported
anywhere: the existing structure queues only fire when the pipeline *acts*, and
here it does not.

The third band is in this queue for a different reason. When CAS's key is
non-standard the two hashes were never comparable, so there is no disagreement
to report -- but it is indistinguishable from a real conflict in the raw
strings, which is exactly how #42 came to count 91 defects where there are 45.
Leaving it out would invite the next reader to rediscover it as a bug. It is
reported as its own kind, at `INFO`, saying in the title that it is not known to
be a disagreement.

**"Both sides specific and different" then turned out to be three findings, not
one** (#56). A key hashes every stereo layer at once, so a record that leaves
one corner of thirty undetermined gets a hash as different from the complete
record's as inverting all thirty would give -- and fifteen rows arrived wearing
one label because of it. Ten of them were one record simply not stating
something the other did, agreeing everywhere both spoke. This file's own
`conflict` example was one of them: bornyl acetate is the registry stating two
centres the published record leaves undetermined, and it sat here as a
contradiction because its `/t` layer and its mirror flag both differ from ours.
They differ because dropping an assignment changes which enantiomer InChI writes
down; the substance does not.

What is pinned here:

- **The five kinds are told apart**, and by the structures rather than by the
  hash -- for the flag question as much as for the undetermined-corner one.
- **Only survivors are reported.** A structure a gate refused is not what the
  list publishes, and reporting it would double-count the refusals as defects.
- **A different skeleton is not a stereochemistry question.** That is #35 and
  #38, and it has its own queues.
- **A structure that cannot be read leaves the disagreement standing**, because
  `conflict` is the answer that sends a person to look.
- **`BLOCKING` for what the pipeline will not act on**, `INFO` for what needs
  no action -- including the band a rule settles.
- **Both lookup paths report.**
"""

import unittest

from brightway_flows.domain.flow import Flow
from brightway_flows.integrations.commonchemistry import build_commonchemistry_index
from brightway_flows.pipeline.review_records import ReviewQueue, Severity
from brightway_flows.transformers.enrich_references import (
    EnrichReferencesTransformer,
    StructureCandidate,
)
from brightway_flows.webapps.app.queries import queue as queue_queries

#: Carbetamide, CAS 16118-49-3: one stereocentre, assigned by both records, and
#: the two records are mirror images of each other.  A herbicide whose two hands
#: are not interchangeable, and the cleanest genuine disagreement #56 found.
CONFLICT_CAS = "16118-49-3"
CONFLICT_OURS = "AMRQXHFXNZFDCH-VIFPVBQESA-N"
CONFLICT_THEIRS = "AMRQXHFXNZFDCH-SECBINFHSA-N"
CONFLICT_OURS_INCHI = (
    "InChI=1S/C12H16N2O3/c1-3-13-11(15)9(2)17-12(16)14-10-7-5-4-6-8-10/"
    "h4-9H,3H2,1-2H3,(H,13,15)(H,14,16)/t9-/m0/s1"
)
#: Senkirkine, CAS 2318-18-5: we state the geometry of both double bonds, the
#: registry states one and leaves the other undetermined, and they agree on the
#: one both state.  A gap in the registry's drawing, not a claim about the
#: substance -- and settled here rather than by a curator.
CAS_UNDETERMINED_CAS = "2318-18-5"
CAS_UNDETERMINED_OURS = "HPDHKHMHQGCNPE-QLJRNOHWSA-N"
CAS_UNDETERMINED_THEIRS = "HPDHKHMHQGCNPE-QESVCWQLSA-N"
CAS_UNDETERMINED_OURS_INCHI = (
    "InChI=1S/C19H27NO6/c1-5-13-10-12(2)19(3,24)18(23)25-11-14-6-8-20(4)9-7-"
    "15(16(14)21)26-17(13)22/h5-6,12,15,24H,7-11H2,1-4H3/b13-5-,14-6-/"
    "t12-,15-,19-/m1/s1"
)
#: Bornyl acetate, CAS 5655-61-8: the same the other way round.  Two of its
#: three centres are undetermined in the record we publish and assigned by the
#: registry, which agrees with us on the third.  The published key therefore
#: names a broader substance than the number does.
OURS_UNDETERMINED_CAS = "5655-61-8"
OURS_UNDETERMINED_OURS = "KGEKLUUHTZCSIP-SQLBVSGCSA-N"
OURS_UNDETERMINED_THEIRS = "KGEKLUUHTZCSIP-HOSYDEDBSA-N"
OURS_UNDETERMINED_OURS_INCHI = (
    "InChI=1S/C12H20O2/c1-8(13)14-10-7-9-5-6-12(10,4)11(9,2)3/h9-10H,5-7H2,"
    "1-4H3/t9?,10-,12?/m1/s1"
)
#: trans-4-tert-butylcyclohexanol, CAS 21862-63-5: CAS gives it a
#: stereochemistry, we publish the flat key.
LOST_CAS = "21862-63-5"
LOST_OURS = "CCOQPGVQAWPUPE-UHFFFAOYSA-N"
LOST_THEIRS = "CCOQPGVQAWPUPE-KYZUINATNA-N"
#: (2RS,4SR)-2-methyl-4-propyl-1,3-oxathiane, CAS 59323-76-1: CAS's key encodes
#: relative stereochemistry, so it is not comparable with ours.
INCOMPARABLE_CAS = "59323-76-1"
INCOMPARABLE_OURS = "GKGOLPMYJJXRGD-SFYZADRCSA-N"
INCOMPARABLE_THEIRS = "GKGOLPMYJJXRGD-HGXVMFPFNA-N"
#: Crotonaldehyde: registered flat, and owned by the gate in the previous
#: change rather than by this queue.
FLAT_CAS = "4170-30-3"
FLAT_THEIRS = "MLUCVPSAIODCQM-UHFFFAOYSA-N"
TRANS_KEY = "MLUCVPSAIODCQM-NSCUHMNNSA-N"
DIFFERENT_SKELETON = "SCYULBFZEHDVBN-UHFFFAOYSA-N"
UNCACHED_CAS = "999999-99-9"

TRANS_CHEBI = "http://purl.obolibrary.org/obo/CHEBI_15366"


def flow() -> Flow:
    """A flow with nothing on it: this queue reads the CAS and the key only."""
    return Flow(uuid="u", identifier="i", name="", source="EF 3.1")


def compound(cid: int, inchikey: str = "", inchi: str = "") -> dict:
    props = []
    if inchikey:
        props.append({"urn": {"label": "InChIKey"}, "value": {"sval": inchikey}})
    if inchi:
        props.append({"urn": {"label": "InChI"}, "value": {"sval": inchi}})
    return {"cid": cid, "charge": 0, "props": props}


#: The InChI behind each key above, copied verbatim from the cache.  These are
#: no longer decoration: the classifier reads the InChI to decide whether CAS's
#: structure can be expressed as a comparable key at all, and then whether it
#: states more or less than ours, so a placeholder would test the wrong thing.
#: Note which of them is `InChI=1S/` and which is `InChI=1/` -- the second is
#: CAS saying it needed options standard InChI does not have.
CACHE_RECORDS = {
    CONFLICT_CAS: (
        CONFLICT_THEIRS,
        "InChI=1S/C12H16N2O3/c1-3-13-11(15)9(2)17-12(16)14-10-7-5-4-6-8-10/"
        "h4-9H,3H2,1-2H3,(H,13,15)(H,14,16)/t9-/m1/s1",
        "C<sub>12</sub>H<sub>16</sub>N<sub>2</sub>O<sub>3</sub>",
    ),
    CAS_UNDETERMINED_CAS: (
        CAS_UNDETERMINED_THEIRS,
        "InChI=1S/C19H27NO6/c1-5-13-10-12(2)19(3,24)18(23)25-11-14-6-8-20(4)9-7-"
        "15(16(14)21)26-17(13)22/h5-6,12,15,24H,7-11H2,1-4H3/b13-5-,14-6?/"
        "t12-,15-,19-/m1/s1",
        "C<sub>19</sub>H<sub>27</sub>NO<sub>6</sub>",
    ),
    OURS_UNDETERMINED_CAS: (
        OURS_UNDETERMINED_THEIRS,
        "InChI=1S/C12H20O2/c1-8(13)14-10-7-9-5-6-12(10,4)11(9,2)3/h9-10H,5-7H2,"
        "1-4H3/t9-,10+,12+/m0/s1",
        "C<sub>12</sub>H<sub>20</sub>O<sub>2</sub>",
    ),
    LOST_CAS: (
        LOST_THEIRS,
        "InChI=1/C10H20O/c1-10(2,3)8-4-6-9(11)7-5-8/h8-9,11H,4-7H2,1-3H3/t8-,9-",
        "C<sub>10</sub>H<sub>20</sub>O",
    ),
    INCOMPARABLE_CAS: (
        INCOMPARABLE_THEIRS,
        "InChI=1/C8H16OS/c1-3-4-8-5-6-9-7(2)10-8/h7-8H,3-6H2,1-2H3/t7-,8+/s2",
        "C<sub>8</sub>H<sub>16</sub>OS",
    ),
    FLAT_CAS: (
        FLAT_THEIRS,
        "InChI=1S/C4H6O/c1-2-3-4-5/h2-4H,1H3",
        "C<sub>4</sub>H<sub>6</sub>O",
    ),
}

#: What re-expressing `LOST_CAS`'s structure as a standard key gives.  Same
#: stereochemistry hash as CAS's own key, differing only in the character that
#: records how the key was computed -- which is the whole point.
LOST_CORRECTED = "CCOQPGVQAWPUPE-KYZUINATSA-N"


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


class ClassificationTestCase(unittest.TestCase):
    def test_a_flat_structure_for_a_specific_number_is_lost(self):
        self.assertEqual(
            transformer()._stereo_disagreement(
                cas=LOST_CAS, candidate=StructureCandidate(LOST_OURS)
            ),
            "lost",
        )

    def test_two_records_that_contradict_each_other_are_a_conflict(self):
        """Carbetamide: one centre, assigned by both, and opposite."""
        self.assertEqual(
            transformer()._stereo_disagreement(
                cas=CONFLICT_CAS,
                candidate=StructureCandidate(CONFLICT_OURS, CONFLICT_OURS_INCHI),
            ),
            "conflict",
        )

    def test_a_gap_on_the_registrys_side_is_not_a_contradiction(self):
        """#56's first band: six substances, and no curator needed."""
        self.assertEqual(
            transformer()._stereo_disagreement(
                cas=CAS_UNDETERMINED_CAS,
                candidate=StructureCandidate(
                    CAS_UNDETERMINED_OURS, CAS_UNDETERMINED_OURS_INCHI
                ),
            ),
            "cas-undetermined",
        )

    def test_a_gap_on_our_side_is_reported_as_its_own_finding(self):
        """The published key names more substances than the number does."""
        self.assertEqual(
            transformer()._stereo_disagreement(
                cas=OURS_UNDETERMINED_CAS,
                candidate=StructureCandidate(
                    OURS_UNDETERMINED_OURS, OURS_UNDETERMINED_OURS_INCHI
                ),
            ),
            "ours-undetermined",
        )

    def test_a_mirror_flag_alone_does_not_decide_which_of_the_three(self):
        """Both bands above differ from ours in `/m`, and only one is a defect.

        `/m` says which of two mirror images the `/t` layer was written for, and
        that depends on the set of centres being written -- so blanking a centre
        can flip it without the substance changing.  Bornyl acetate's records
        differ in every assigned parity *and* in the flag, and are still one
        record completing the other.
        """
        instance = transformer()
        theirs = instance._commonchemistry.inchi_for(OURS_UNDETERMINED_CAS)
        self.assertIn("/m0/", theirs)
        self.assertIn("/m1/", OURS_UNDETERMINED_OURS_INCHI)
        self.assertEqual(
            instance._stereo_disagreement(
                cas=OURS_UNDETERMINED_CAS,
                candidate=StructureCandidate(
                    OURS_UNDETERMINED_OURS, OURS_UNDETERMINED_OURS_INCHI
                ),
            ),
            "ours-undetermined",
        )

    def test_without_a_structure_the_disagreement_stands(self):
        """A key alone cannot say which of the three this is, so it says none.

        `conflict` is the status quo and the answer that sends a person to look,
        which is what an unanswerable question deserves.
        """
        self.assertEqual(
            transformer()._stereo_disagreement(
                cas=OURS_UNDETERMINED_CAS,
                candidate=StructureCandidate(OURS_UNDETERMINED_OURS),
            ),
            "conflict",
        )

    def test_an_inchi_belonging_to_another_structure_is_not_read(self):
        """The key and the InChI arrive from one record and are not checked.

        Reading a stereochemistry off a string that does not describe the key
        beside it would answer about the wrong molecule, so the two are required
        to agree first -- and where they do not, the finding falls back to the
        answer a key alone supports.
        """
        self.assertEqual(
            transformer()._stereo_disagreement(
                cas=OURS_UNDETERMINED_CAS,
                candidate=StructureCandidate(
                    OURS_UNDETERMINED_OURS, CAS_UNDETERMINED_OURS_INCHI
                ),
            ),
            "conflict",
        )

    def test_a_non_standard_key_is_incomparable_not_a_conflict(self):
        """The distinction that turns 91 reported defects into 45."""
        self.assertEqual(
            transformer()._stereo_disagreement(
                cas=INCOMPARABLE_CAS,
                candidate=StructureCandidate(INCOMPARABLE_OURS),
            ),
            "incomparable",
        )

    def test_agreement_reports_nothing(self):
        self.assertIsNone(
            transformer()._stereo_disagreement(
                cas=LOST_CAS, candidate=StructureCandidate(LOST_THEIRS)
            )
        )

    def test_a_different_skeleton_is_not_a_stereochemistry_question(self):
        """#35 and #38 own that, and have their own queues for it."""
        self.assertIsNone(
            transformer()._stereo_disagreement(
                cas=CONFLICT_CAS, candidate=StructureCandidate(DIFFERENT_SKELETON)
            )
        )

    def test_a_flat_registration_belongs_to_the_gate_not_the_queue(self):
        """Reporting it here as well would count one defect twice."""
        self.assertIsNone(
            transformer()._stereo_disagreement(
                cas=FLAT_CAS, candidate=StructureCandidate(TRANS_KEY)
            )
        )

    def test_an_uncached_number_reports_nothing(self):
        self.assertIsNone(
            transformer()._stereo_disagreement(
                cas=UNCACHED_CAS, candidate=StructureCandidate(CONFLICT_OURS)
            )
        )

    def test_an_unreadable_key_reports_nothing(self):
        for key in ("", "rubbish"):
            with self.subTest(candidate=key):
                self.assertIsNone(
                    transformer()._stereo_disagreement(
                        cas=CONFLICT_CAS, candidate=StructureCandidate(key)
                    )
                )


class SurvivorsOnlyTestCase(unittest.TestCase):
    def test_the_pubchem_survivor_is_reported(self):
        instance = transformer()
        instance._pubchem_by_cas = {CONFLICT_CAS: [compound(1, CONFLICT_OURS)]}
        instance._matched_pubchem_compounds(
            flow=flow(), cas_numbers=[CONFLICT_CAS], chebi_ids=[]
        )
        entry = instance._stereo_disagreements[f"{CONFLICT_CAS}:conflict"]
        self.assertEqual(entry["published_inchikeys"], [CONFLICT_OURS])
        self.assertEqual(entry["sources"], ["CID:1"])

    def test_the_pubchem_survivors_structure_is_read(self):
        """PubChem publishes the InChI beside the key, so the split is available."""
        instance = transformer()
        instance._pubchem_by_cas = {
            CAS_UNDETERMINED_CAS: [
                compound(1, CAS_UNDETERMINED_OURS, CAS_UNDETERMINED_OURS_INCHI)
            ]
        }
        instance._matched_pubchem_compounds(
            flow=flow(), cas_numbers=[CAS_UNDETERMINED_CAS], chebi_ids=[]
        )
        self.assertEqual(
            sorted(instance._stereo_disagreements),
            [f"{CAS_UNDETERMINED_CAS}:cas-undetermined"],
        )

    def test_a_refused_structure_is_not_reported_as_a_disagreement(self):
        """The gate already withheld it, and it is not what the list publishes."""
        instance = transformer()
        instance._pubchem_by_cas = {FLAT_CAS: [compound(1, TRANS_KEY)]}
        instance._matched_pubchem_compounds(
            flow=flow(), cas_numbers=[FLAT_CAS], chebi_ids=[]
        )
        self.assertEqual(instance._stereo_disagreements, {})
        self.assertIn(FLAT_CAS, instance._stereo_exclusions)

    def test_the_chebi_survivor_is_reported(self):
        instance = transformer()
        instance._chebi_by_cas = {CONFLICT_CAS: [TRANS_CHEBI]}
        instance._chebi_records = {
            TRANS_CHEBI: {
                "formula": "C12H16N2O3",
                "cas_numbers": [CONFLICT_CAS],
                "basic_property_values": {"inchi_key_string": [CONFLICT_OURS]},
            }
        }
        instance._matched_chebi_ids([CONFLICT_CAS])
        entry = instance._stereo_disagreements[f"{CONFLICT_CAS}:conflict"]
        self.assertEqual(entry["sources"], [TRANS_CHEBI])

    def test_the_chebi_survivors_structure_is_read(self):
        instance = transformer()
        instance._chebi_by_cas = {CAS_UNDETERMINED_CAS: [TRANS_CHEBI]}
        instance._chebi_records = {
            TRANS_CHEBI: {
                "formula": "C19H27NO6",
                "cas_numbers": [CAS_UNDETERMINED_CAS],
                "basic_property_values": {
                    "inchi_key_string": [CAS_UNDETERMINED_OURS],
                    "inchi_string": [CAS_UNDETERMINED_OURS_INCHI],
                },
            }
        }
        instance._matched_chebi_ids([CAS_UNDETERMINED_CAS])
        self.assertEqual(
            sorted(instance._stereo_disagreements),
            [f"{CAS_UNDETERMINED_CAS}:cas-undetermined"],
        )

    def test_one_number_can_disagree_in_two_ways_at_once(self):
        """Keyed on (CAS, kind), so neither report swallows the other.

        Both findings are about 21862-63-5: one structure has no stereochemistry
        where CAS gives one, and another has a stereochemistry that is not CAS's.
        The second is a real `conflict` rather than an unanswerable comparison,
        because CAS's structure for this number can be re-expressed as a
        standard key -- the difference reading the InChI makes.
        """
        instance = transformer()
        instance._record_stereo_disagreement(
            cas=LOST_CAS, source="CID:1", candidate=StructureCandidate(LOST_OURS)
        )
        instance._record_stereo_disagreement(
            cas=LOST_CAS,
            source="CID:2",
            candidate=StructureCandidate("CCOQPGVQAWPUPE-QMMMGPOBSA-N"),
        )
        self.assertEqual(
            sorted(instance._stereo_disagreements),
            [f"{LOST_CAS}:conflict", f"{LOST_CAS}:lost"],
        )


class ReadingCasStructureTestCase(unittest.TestCase):
    """Comparing structures rather than comparing key strings.

    CAS often computes its key a different way from every source here, and two
    keys computed differently answer nothing.  But CAS publishes the InChI
    behind its key, and a structure can be read and re-expressed -- so a number
    that could only be shrugged at becomes one that can be checked, and
    corrected from.
    """

    def test_a_structure_standard_inchi_can_express_becomes_comparable(self):
        index = build_commonchemistry_index(cache_payload())
        self.assertEqual(index.comparable_inchikey_for(LOST_CAS), LOST_CORRECTED)

    def test_the_re_expressed_key_keeps_the_stereochemistry(self):
        """Only the character recording *how* the key was computed may move."""
        index = build_commonchemistry_index(cache_payload())
        corrected = index.comparable_inchikey_for(LOST_CAS)
        self.assertEqual(corrected.split("-")[0], LOST_THEIRS.split("-")[0])
        self.assertEqual(corrected.split("-")[1][:8], LOST_THEIRS.split("-")[1][:8])
        self.assertNotEqual(corrected, LOST_THEIRS)

    def test_relative_stereochemistry_has_no_comparable_answer(self):
        """RDKit would happily return one enantiomer here. That would be an
        invention, and inventing stereochemistry is the defect #42 is about."""
        index = build_commonchemistry_index(cache_payload())
        self.assertIsNone(index.comparable_inchikey_for(INCOMPARABLE_CAS))

    def test_an_uncached_number_has_no_comparable_answer(self):
        index = build_commonchemistry_index(cache_payload())
        self.assertIsNone(index.comparable_inchikey_for(UNCACHED_CAS))

    def test_the_loss_carries_its_own_correction(self):
        instance = transformer()
        self.assertEqual(
            instance._corrected_inchikey_for(
                cas=LOST_CAS, candidate=StructureCandidate(LOST_OURS)
            ),
            LOST_CORRECTED,
        )

    def test_a_partial_loss_carries_its_own_correction_too(self):
        """The same defect, smaller -- and the registry supplies the same fix."""
        instance = transformer()
        self.assertEqual(
            instance._corrected_inchikey_for(
                cas=OURS_UNDETERMINED_CAS,
                candidate=StructureCandidate(
                    OURS_UNDETERMINED_OURS, OURS_UNDETERMINED_OURS_INCHI
                ),
            ),
            OURS_UNDETERMINED_THEIRS,
        )

    def test_nothing_that_is_not_a_gap_carries_a_correction(self):
        instance = transformer()
        for cas, candidate in (
            (CONFLICT_CAS, StructureCandidate(CONFLICT_OURS, CONFLICT_OURS_INCHI)),
            (
                CAS_UNDETERMINED_CAS,
                StructureCandidate(
                    CAS_UNDETERMINED_OURS, CAS_UNDETERMINED_OURS_INCHI
                ),
            ),
            (INCOMPARABLE_CAS, StructureCandidate(INCOMPARABLE_OURS)),
            (LOST_CAS, StructureCandidate(LOST_THEIRS)),
        ):
            with self.subTest(cas=cas):
                self.assertEqual(
                    instance._corrected_inchikey_for(cas=cas, candidate=candidate), ""
                )

    def test_the_correction_reaches_the_queue(self):
        instance = transformer()
        instance._record_stereo_disagreement(
            cas=LOST_CAS, source="CID:1", candidate=StructureCandidate(LOST_OURS)
        )
        item = next(
            item for item in instance.review_queue_items()
            if item.queue_name == ReviewQueue.STEREO_DISAGREEMENT
        )
        self.assertEqual(item.payload["corrected_inchikey"], LOST_CORRECTED)
        self.assertIn(LOST_CORRECTED, item.title)

    def test_a_row_with_no_correction_says_nothing_about_one(self):
        instance = transformer()
        instance._record_stereo_disagreement(
            cas=INCOMPARABLE_CAS,
            source="CID:1",
            candidate=StructureCandidate(INCOMPARABLE_OURS),
        )
        item = next(
            item for item in instance.review_queue_items()
            if item.queue_name == ReviewQueue.STEREO_DISAGREEMENT
        )
        self.assertEqual(item.payload["corrected_inchikey"], "")
        self.assertNotIn("corrected key is", item.title)


class QueueTestCase(unittest.TestCase):
    def _queued(self) -> dict:
        instance = transformer()
        for cas, candidate in (
            (LOST_CAS, StructureCandidate(LOST_OURS)),
            (CONFLICT_CAS, StructureCandidate(CONFLICT_OURS, CONFLICT_OURS_INCHI)),
            (
                CAS_UNDETERMINED_CAS,
                StructureCandidate(
                    CAS_UNDETERMINED_OURS, CAS_UNDETERMINED_OURS_INCHI
                ),
            ),
            (
                OURS_UNDETERMINED_CAS,
                StructureCandidate(
                    OURS_UNDETERMINED_OURS, OURS_UNDETERMINED_OURS_INCHI
                ),
            ),
            (INCOMPARABLE_CAS, StructureCandidate(INCOMPARABLE_OURS)),
        ):
            instance._record_stereo_disagreement(
                cas=cas, source="CID:1", candidate=candidate
            )
        return {
            item.payload["kind"]: item
            for item in instance.review_queue_items()
            if item.queue_name == ReviewQueue.STEREO_DISAGREEMENT
        }

    def test_what_cannot_be_settled_blocks_and_what_needs_no_action_informs(self):
        items = self._queued()
        self.assertEqual(
            sorted(items),
            [
                "cas-undetermined",
                "conflict",
                "incomparable",
                "lost",
                "ours-undetermined",
            ],
        )
        self.assertIs(items["lost"].severity, Severity.BLOCKING)
        self.assertIs(items["conflict"].severity, Severity.BLOCKING)
        self.assertIs(items["ours-undetermined"].severity, Severity.BLOCKING)
        self.assertIs(items["incomparable"].severity, Severity.INFO)
        self.assertIs(items["cas-undetermined"].severity, Severity.INFO)

    def test_the_titles_say_which_question_is_being_asked(self):
        titles = {kind: item.title for kind, item in self._queued().items()}
        self.assertIn("not known to be a disagreement", titles["incomparable"].lower())
        self.assertIn("flat", titles["lost"])
        self.assertIn(LOST_THEIRS, titles["lost"])
        self.assertIn("each states an arrangement the other contradicts",
                      titles["conflict"])
        self.assertIn("gap in the registry's record", titles["cas-undetermined"])
        self.assertIn("broader substance", titles["ours-undetermined"])

    def test_the_two_gaps_do_not_read_alike(self):
        """"One side left a blank" and "the two disagree" are different findings.

        So are the two directions of the first, and until #56 all three were
        written identically.
        """
        titles = {kind: item.title for kind, item in self._queued().items()}
        self.assertNotEqual(titles["cas-undetermined"], titles["ours-undetermined"])
        self.assertEqual(
            len({titles[kind] for kind in titles}), len(titles)
        )

    def test_the_queue_renders(self):
        """A queue with no definition is a page that silently shows nothing."""
        definition = queue_queries.definition(str(ReviewQueue.STEREO_DISAGREEMENT))
        self.assertIsNotNone(definition)
        fields = {column.path for column in definition.columns}
        self.assertTrue({"cas", "kind", "published_inchikeys"} <= fields)

    def test_a_quiet_run_queues_nothing(self):
        self.assertEqual(transformer().review_queue_items(), [])
