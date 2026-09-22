"""One record stating an arrangement the other left undetermined.

An InChIKey hashes every stereo layer at once, so a record that leaves one
corner of thirty undetermined gets a hash as different from the complete
record's as inverting all thirty would give::

    α-cyclodextrin   ours  …,22-,23-,24-,25-,…   HFHDHCJBZVLPGP-RWMJIURBSA-N
                     CAS   …,22-,23-,24?,25-,…   HFHDHCJBZVLPGP-FXNRASGISA-N

By key that reads as two substances; by content it is one substance described
once fully and once with a gap. #56 is fifteen rows that could not tell those
apart, all of them labelled "same skeleton, different stereochemistry, both
specific", and ten of them turned out to be a gap rather than a disagreement.

:func:`states_more_stereochemistry` answers the question the keys cannot, and it
answers it by construction rather than by reading the layers off: blank, in the
fuller record, exactly what the sparser one leaves undetermined, and ask InChI
for the key of what remains. That is not fussiness. The obvious approach --
compare the `/t` layers element by element -- gets two of these fifteen wrong,
because `/t` cannot be read without the `/m` beside it and `/m` depends on which
centres are being written::

    chloralose       ours  /t2?,3-,4+,5+,6?,7+/m0/s1
                     CAS   /t2-,3+,4-,5-,6-,7-/m1/s1

Every assigned parity differs and so does the flag, which reads as a flat
contradiction. Blank centres 2 and 6 in CAS's record and InChI re-canonicalises
the rest to exactly ours: one substance, described twice, and #56 sent it to a
curator as a genuine disagreement.

What is pinned here:

- **The six substances where the registry's record has the gap** are not
  reported as disagreements, and nothing about them is changed.
- **The six where ours has it** are repaired from the registry, which is the
  same repair as a wholly lost shape and rests on more evidence.
- **The three that really do contradict each other** survive both tests and
  still want a person.
- **The direction is not symmetric**: a record that both completes ours at one
  centre and contradicts it at another fails, in both directions.
"""

import unittest

from brightway_flows.chem import states_more_stereochemistry
from brightway_flows.integrations.commonchemistry import build_commonchemistry_index
from brightway_flows.transformers.enrich_references import (
    EnrichReferencesTransformer,
    StructureCandidate,
)

#: α-Cyclodextrin, CAS 10016-20-3.  Thirty centres; the registry leaves one of
#: them undetermined and agrees with us on the other twenty-nine.
CYCLODEXTRIN = (
    "InChI=1S/C36H60O30/c37-1-7-25-13(43)19(49)31(55-7)62-26-8(2-38)57-33(21(51)"
    "15(26)45)64-28-10(4-40)59-35(23(53)17(28)47)66-30-12(6-42)60-36(24(54)18(30)"
    "48)65-29-11(5-41)58-34(22(52)16(29)46)63-27-9(3-39)56-32(61-25)20(50)14(27)"
    "44/h7-54H,1-6H2/t{}/m1/s1"
)
CYCLODEXTRIN_CENTRES = [f"{n}-" for n in range(7, 37)]
CYCLODEXTRIN_OURS = CYCLODEXTRIN.format(",".join(CYCLODEXTRIN_CENTRES))
CYCLODEXTRIN_THEIRS = CYCLODEXTRIN.format(
    ",".join(["24?" if c == "24-" else c for c in CYCLODEXTRIN_CENTRES])
)

#: Chloralose, CAS 15879-93-3.  Six centres; we leave two undetermined, and
#: every parity we do assign is written with the opposite sign from CAS's, along
#: with the opposite mirror flag.  It is still one substance.
CHLORALOSE = (
    "InChI=1S/C8H11Cl3O6/c9-8(10,11)7-16-5-3(14)4(2(13)1-12)15-6(5)17-7/"
    "h2-7,12-14H,1H2/t{}/m{}/s1"
)
CHLORALOSE_OURS = CHLORALOSE.format("2?,3-,4+,5+,6?,7+", 0)
CHLORALOSE_THEIRS = CHLORALOSE.format("2-,3+,4-,5-,6-,7-", 1)
CHLORALOSE_OURS_KEY = "OJYGBLRPYBAHRT-OPKHMCHVSA-N"
CHLORALOSE_THEIRS_KEY = "OJYGBLRPYBAHRT-IPQSZEQASA-N"

#: Nivalenol, CAS 23282-20-4.  Eight centres, all assigned on both sides, and
#: the last one inverted.  A genuine disagreement.
NIVALENOL = (
    "InChI=1S/C15H20O7/c1-6-3-7-14(4-16,11(20)8(6)17)13(2)10(19)9(18)12(22-7)15"
    "(13)5-21-15/h3,7,9-12,16,18-20H,4-5H2,1-2H3/t7-,9-,10-,11-,12-,13-,14-,{}/"
    "m1/s1"
)
NIVALENOL_OURS = NIVALENOL.format("15-")
NIVALENOL_THEIRS = NIVALENOL.format("15+")

#: Carbetamide, CAS 16118-49-3.  One centre, assigned by both, and the two
#: records are mirror images.  For a herbicide the two hands are not
#: interchangeable, which is why this one wants a person.
CARBETAMIDE = (
    "InChI=1S/C12H16N2O3/c1-3-13-11(15)9(2)17-12(16)14-10-7-5-4-6-8-10/"
    "h4-9H,3H2,1-2H3,(H,13,15)(H,14,16)/t9-/m{}/s1"
)
CARBETAMIDE_OURS = CARBETAMIDE.format(0)
CARBETAMIDE_THEIRS = CARBETAMIDE.format(1)

#: Senkirkine, CAS 2318-18-5: the gap is a double bond rather than a centre, so
#: it is `/b` and not `/t` that differs.
SENKIRKINE = (
    "InChI=1S/C19H27NO6/c1-5-13-10-12(2)19(3,24)18(23)25-11-14-6-8-20(4)9-7-15"
    "(16(14)21)26-17(13)22/h5-6,12,15,24H,7-11H2,1-4H3/b13-5-,14-6{}/"
    "t12-,15-,19-/m1/s1"
)
SENKIRKINE_OURS = SENKIRKINE.format("-")
SENKIRKINE_THEIRS = SENKIRKINE.format("?")


class ComparisonTestCase(unittest.TestCase):
    def test_one_undetermined_corner_in_thirty_is_not_a_disagreement(self):
        self.assertTrue(
            states_more_stereochemistry(CYCLODEXTRIN_OURS, CYCLODEXTRIN_THEIRS)
        )

    def test_the_gap_is_only_in_the_direction_it_is_in(self):
        self.assertFalse(
            states_more_stereochemistry(CYCLODEXTRIN_THEIRS, CYCLODEXTRIN_OURS)
        )

    def test_an_undetermined_double_bond_counts_the_same_as_a_centre(self):
        """`/b` and `/t` are one question, and #56's group has both."""
        self.assertTrue(
            states_more_stereochemistry(SENKIRKINE_OURS, SENKIRKINE_THEIRS)
        )

    def test_a_mirror_flag_difference_is_not_evidence_of_anything(self):
        """Chloralose, which #56 read as a genuine disagreement and is not."""
        self.assertTrue(
            states_more_stereochemistry(CHLORALOSE_THEIRS, CHLORALOSE_OURS)
        )

    def test_an_inverted_centre_is_a_disagreement_in_both_directions(self):
        for fuller, sparser in (
            (NIVALENOL_OURS, NIVALENOL_THEIRS),
            (NIVALENOL_THEIRS, NIVALENOL_OURS),
        ):
            with self.subTest(fuller=fuller):
                self.assertFalse(states_more_stereochemistry(fuller, sparser))

    def test_two_mirror_images_of_a_complete_record_are_a_disagreement(self):
        """Carbetamide: nothing is undetermined on either side."""
        for fuller, sparser in (
            (CARBETAMIDE_OURS, CARBETAMIDE_THEIRS),
            (CARBETAMIDE_THEIRS, CARBETAMIDE_OURS),
        ):
            with self.subTest(fuller=fuller):
                self.assertFalse(states_more_stereochemistry(fuller, sparser))

    def test_a_record_that_completes_one_centre_and_inverts_another_fails(self):
        """The case the set inclusion alone would wave through.

        Ours leaves centre 15 undetermined, so the registry's record does state
        more; it also states the opposite of ours at centre 14.  Filling the gap
        from a record that contradicts what is already there is not filling a
        gap, and the round trip is what notices.
        """
        ours = NIVALENOL.format("15?")
        theirs = NIVALENOL.replace("14-,", "14+,").format("15+")
        self.assertFalse(states_more_stereochemistry(theirs, ours))

    def test_an_identical_record_states_no_more(self):
        self.assertFalse(
            states_more_stereochemistry(CYCLODEXTRIN_OURS, CYCLODEXTRIN_OURS)
        )

    def test_an_unreadable_string_answers_no(self):
        for fuller, sparser in (
            ("", CYCLODEXTRIN_THEIRS),
            (CYCLODEXTRIN_OURS, ""),
            ("rubbish", "nonsense"),
        ):
            with self.subTest(fuller=fuller[:12]):
                self.assertFalse(states_more_stereochemistry(fuller, sparser))


def cache_payload() -> dict:
    return {
        "detail_by_cas": {
            "15879-93-3": {
                "rn": "15879-93-3",
                "name": "Chloralose",
                "molecularFormula": "C<sub>8</sub>H<sub>11</sub>Cl<sub>3</sub>O<sub>6</sub>",
                "inchi": CHLORALOSE_THEIRS,
                "inchiKey": f"InChIKey={CHLORALOSE_THEIRS_KEY}",
            }
        }
    }


def transformer() -> EnrichReferencesTransformer:
    instance = EnrichReferencesTransformer()
    instance._commonchemistry = build_commonchemistry_index(cache_payload())
    instance._structure_rulings = {}
    return instance


def compound(cid: int, inchikey: str, inchi: str = "") -> dict:
    props = [{"urn": {"label": "InChIKey"}, "value": {"sval": inchikey}}]
    if inchi:
        props.append({"urn": {"label": "InChI"}, "value": {"sval": inchi}})
    return {"cid": cid, "charge": 0, "props": props}


class RepairTestCase(unittest.TestCase):
    """The gap on our side is filled the same way a lost shape is (#42, #277).

    The published key names a set of stereoisomers where the registry number
    names one substance, and #50 describes the machinery that will use that key
    as an identity.  The registry holds the answer and has been checked against
    ours at every centre ours assigns, which is more than the wholly-shape-free
    repair ever had to go on.
    """

    def test_the_registrys_fuller_record_fills_the_gap(self):
        self.assertEqual(
            transformer()._restored_stereochemistry_for(
                cas="15879-93-3",
                candidates=[
                    StructureCandidate(CHLORALOSE_OURS_KEY, CHLORALOSE_OURS)
                ],
            ),
            CHLORALOSE_THEIRS_KEY,
        )

    def test_a_key_with_no_structure_beside_it_is_not_a_gap_to_fill(self):
        """Nothing has been checked, so there is nothing to act on."""
        self.assertEqual(
            transformer()._restored_stereochemistry_for(
                cas="15879-93-3",
                candidates=[StructureCandidate(CHLORALOSE_OURS_KEY)],
            ),
            "",
        )

    def test_one_candidate_the_registry_does_not_complete_stops_the_repair(self):
        """Every candidate must have the gap, as for the shape-free band."""
        self.assertEqual(
            transformer()._restored_stereochemistry_for(
                cas="15879-93-3",
                candidates=[
                    StructureCandidate(CHLORALOSE_OURS_KEY, CHLORALOSE_OURS),
                    StructureCandidate("OJYGBLRPYBAHRT-QMMMGPOBSA-N"),
                ],
            ),
            "",
        )

    def test_the_repaired_number_stops_being_an_open_defect(self):
        instance = transformer()
        compounds = [compound(1, CHLORALOSE_OURS_KEY, CHLORALOSE_OURS)]
        instance._record_stereo_disagreement(
            cas="15879-93-3",
            source="CID:1",
            candidate=StructureCandidate(CHLORALOSE_OURS_KEY, CHLORALOSE_OURS),
        )
        self.assertIn("15879-93-3:ours-undetermined", instance._stereo_disagreements)
        instance._restore_lost_stereochemistry(
            cas_numbers=["15879-93-3"], chebi_ids=[], pubchem_compounds=compounds
        )
        self.assertEqual(
            sorted(instance._stereo_disagreements), ["15879-93-3:restored"]
        )

    def test_the_repair_says_what_it_replaced(self):
        instance = transformer()
        compounds = [compound(1, CHLORALOSE_OURS_KEY, CHLORALOSE_OURS)]
        instance._record_stereo_disagreement(
            cas="15879-93-3",
            source="CID:1",
            candidate=StructureCandidate(CHLORALOSE_OURS_KEY, CHLORALOSE_OURS),
        )
        instance._restore_lost_stereochemistry(
            cas_numbers=["15879-93-3"], chebi_ids=[], pubchem_compounds=compounds
        )
        entry = instance._stereo_disagreements["15879-93-3:restored"]
        self.assertEqual(entry["corrected_inchikey"], CHLORALOSE_THEIRS_KEY)
        self.assertEqual(entry["published_inchikeys"], [CHLORALOSE_OURS_KEY])

    def test_the_incomplete_key_is_withdrawn_and_the_fuller_one_published(self):
        """`_drop_superseded_stereo_inchikeys` takes it once the fuller one lands.

        The under-specified key is not flat, so #50's rule does not reach it;
        #278's does, because the registry's key is now one of the object's own.
        """
        instance = transformer()
        compounds = [compound(1, CHLORALOSE_OURS_KEY, CHLORALOSE_OURS)]
        restored = instance._restore_lost_stereochemistry(
            cas_numbers=["15879-93-3"], chebi_ids=[], pubchem_compounds=compounds
        )
        properties = instance._build_properties(
            existing={},
            chebi_ids=[],
            pubchem_compounds=compounds,
            stereo_restored_cas=restored,
            structure_cas=["15879-93-3"],
        )
        values = properties[
            EnrichReferencesTransformer.CHEMROF_INCHI2D_KEY_STRING
        ]["@value"]
        self.assertEqual(values, [CHLORALOSE_THEIRS_KEY])

    def test_the_withdrawal_is_not_reported_as_a_second_finding(self):
        """One event, one row.  Two would read as two defects."""
        instance = transformer()
        compounds = [compound(1, CHLORALOSE_OURS_KEY, CHLORALOSE_OURS)]
        restored = instance._restore_lost_stereochemistry(
            cas_numbers=["15879-93-3"], chebi_ids=[], pubchem_compounds=compounds
        )
        instance._build_properties(
            existing={},
            chebi_ids=[],
            pubchem_compounds=compounds,
            stereo_restored_cas=restored,
            structure_cas=["15879-93-3"],
        )
        self.assertEqual(
            sorted(instance._stereo_disagreements), ["15879-93-3:restored"]
        )
        entry = instance._stereo_disagreements["15879-93-3:restored"]
        self.assertEqual(entry["published_inchikeys"], [CHLORALOSE_OURS_KEY])
