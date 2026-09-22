"""A CAS that denotes no single structure must not lend one to a flow.

PubChem's `by_cas` index answers every registry number with a compound, whether
or not the number names one substance.  For a UVCB, an unspecified isomer or a
commercial mixture it returns one component, or -- where its `xref/RN`
aggregation went wrong -- something unrelated:

    1300-21-6    dichloroethane, no isomer stated   →  CID 6365, 1,1-dichloroethane
    68475-60-5   alkanes, C4-5                      →  CID 8003, n-pentane
    8006-64-2    gum turpentine                     →  CID 6506, triethyl citrate
    111937-03-2  isononanoic acid, C16-18 esters    →  CID 962,  water

Each returns a *single* compound, so the two filters already here could not
fire: both read `len(cas_compounds) > 1` as "was this CAS ambiguous", and an
unopposed wrong answer is not ambiguous.  The result was flow objects carrying a
structure looked up through a CAS that has none, which then collided under
InChIKey with the specific substance whose structure they had borrowed (#35).

CAS Common Chemistry can tell them apart, but only partly, and the part it
cannot is what most of this file is about.  Its records come in three usable
shapes:

    75-34-3      1,1-Dichloroethane   C2H4Cl2       InChIKey=SCYULBFZEHDVBN-…
    68475-60-5   Alkanes, C4-5        Unspecified   (no key)
    1300-21-6    Dichloroethane       C2H4Cl2       (no key)
    10028-15-6   Ozone                O3            (no key)

The second shape is unambiguous: CAS is stating the number has no definite
composition.  The third and fourth are *identical in the record* and opposite in
meaning -- an isomer family and a single molecule Common Chemistry happens to
hold no key for.  319 cached records have that shape, and reading them all as
non-specific strips **ozone**.

What is pinned here:

- **No composition means no structure**, from PubChem or ChEBI, however many or
  few candidates the number has.
- **A formula with no key changes nothing on its own.** Ozone keeps its
  structure. Dichloroethane loses its only because a curator ruled on it in
  `commonchemistry-structure-decisions.json`.
- **A ruling without a comment is ignored.** Every entry denies a substance its
  structure, and that assertion has to carry its reasoning.
- **An uncached CAS changes nothing.** A gap in the cache must not decide
  identity, which is the rule the curated-CAS gate already follows.
- **The narrowing gate stays one-sided.** A contradicted compound is dropped
  only when another is confirmed, because Common Chemistry is evidence and not
  an oracle -- for metaldehyde it publishes acetaldehyde.
- **A key that does not match is not always a contradiction.** Where CAS
  published a non-standard key -- which it does to express relative
  stereochemistry, which standard InChI has no layer for -- no standard key can
  equal it, and the verdict is `INCOMPARABLE`.  That is 45 of the 91 flow
  objects #42 reported as stereochemistry defects.
- **The full CAS list still reaches the reference builder.** The Common
  Chemistry page for 1300-21-6 describes that registry entry and is a correct
  reference for a flow carrying the number; only the *structure* is withheld.
"""

import tempfile
import unittest
from pathlib import Path
from unittest import mock

import orjson

from brightway_flows.domain.flow import Flow
from brightway_flows.integrations import commonchemistry
from brightway_flows.integrations.commonchemistry import (
    CommonChemistryIndex,
    StructureRuling,
    StructureRulingVerdict,
    build_commonchemistry_index,
    load_structure_decisions,
    normalise_formula,
)
from brightway_flows.pipeline.review_records import ReviewQueue, Severity
from brightway_flows.transformers.enrich_references import (
    EnrichReferencesTransformer,
    StructureVerdict,
)

#: A specific substance: formula and key.
SPECIFIC_CAS = "75-34-3"
DICHLOROETHANE_11 = 6365
DICHLOROETHANE_11_KEY = "SCYULBFZEHDVBN-UHFFFAOYSA-N"
#: 1,2-dichloroethane, a second candidate with a different structure.
DICHLOROETHANE_12 = 11
DICHLOROETHANE_12_KEY = "WSLDOOZREJYCGB-UHFFFAOYSA-N"
#: No composition at all: CAS says `Unspecified`.  Acted on without a ruling.
NO_COMPOSITION_CAS = "68475-60-5"
PENTANE = 8003
#: A formula and no key, and genuinely an isomer family.  Needs a ruling.
AMBIGUOUS_CAS = "1300-21-6"
#: A formula and no key, and genuinely one molecule.  Must never be withheld.
OZONE_CAS = "10028-15-6"
OZONE = 24823
OZONE_KEY = "CBENFWSGALASAD-UHFFFAOYSA-N"
UNCACHED_CAS = "999999-99-9"


def compound(cid: int, inchikey: str = "") -> dict:
    props = []
    if inchikey:
        props.append({"urn": {"label": "InChIKey"}, "value": {"sval": inchikey}})
    return {"cid": cid, "charge": 0, "props": props}


def cache_payload() -> dict:
    """The four records as CAS Common Chemistry really returns them."""
    return {
        "detail_by_cas": {
            SPECIFIC_CAS: {
                "rn": SPECIFIC_CAS,
                "name": "1,1-Dichloroethane",
                "molecularFormula": "C<sub>2</sub>H<sub>4</sub>Cl<sub>2</sub>",
                "inchiKey": f"InChIKey={DICHLOROETHANE_11_KEY}",
            },
            NO_COMPOSITION_CAS: {
                "rn": NO_COMPOSITION_CAS,
                "name": "Alkanes, C<sub>4-5</sub>",
                "molecularFormula": "Unspecified",
                "inchiKey": "",
            },
            AMBIGUOUS_CAS: {
                "rn": AMBIGUOUS_CAS,
                "name": "Dichloroethane",
                "molecularFormula": "C<sub>2</sub>H<sub>4</sub>Cl<sub>2</sub>",
                "inchiKey": "",
            },
            OZONE_CAS: {
                "rn": OZONE_CAS,
                "name": "Ozone",
                "molecularFormula": "O<sub>3</sub>",
                "inchiKey": "",
            },
        }
    }


def _ruling(cas: str, verdict: StructureRulingVerdict) -> dict[str, StructureRuling]:
    """One curated structure ruling, as `load_structure_decisions` hands it out."""
    return {cas: StructureRuling(cas=cas, verdict=verdict, comment="isomer unstated")}


def transformer(
    index: CommonChemistryIndex | None = None,
    rulings: dict[str, StructureRuling] | None = None,
) -> EnrichReferencesTransformer:
    """A transformer with only the tables these gates consult.

    `setup()` is not called: it loads the ChEBI index and the whole PubChem
    cache off disk, and neither is what is under test here.
    """
    instance = EnrichReferencesTransformer()
    instance._commonchemistry = (
        build_commonchemistry_index(cache_payload()) if index is None else index
    )
    instance._structure_rulings = {} if rulings is None else rulings
    instance._pubchem_by_cas = {
        SPECIFIC_CAS: [compound(DICHLOROETHANE_11, DICHLOROETHANE_11_KEY)],
        AMBIGUOUS_CAS: [compound(DICHLOROETHANE_11, DICHLOROETHANE_11_KEY)],
        NO_COMPOSITION_CAS: [compound(PENTANE, "OFBQJSOFQDEBGM-UHFFFAOYSA-N")],
        OZONE_CAS: [compound(OZONE, OZONE_KEY)],
    }
    instance._chebi_by_cas = {NO_COMPOSITION_CAS: ["CHEBI:15359"]}
    return instance


class IndexTestCase(unittest.TestCase):
    def test_the_four_states_are_distinct(self):
        index = build_commonchemistry_index(cache_payload())

        self.assertTrue(index.has_structure(SPECIFIC_CAS))
        self.assertFalse(index.holds_no_composition(SPECIFIC_CAS))

        self.assertTrue(index.holds_no_composition(NO_COMPOSITION_CAS))
        self.assertFalse(index.has_formula_but_no_structure(NO_COMPOSITION_CAS))

        self.assertTrue(index.has_formula_but_no_structure(AMBIGUOUS_CAS))
        self.assertFalse(index.holds_no_composition(AMBIGUOUS_CAS))
        self.assertFalse(index.has_structure(AMBIGUOUS_CAS))

        self.assertFalse(index.is_known(UNCACHED_CAS))

    def test_ozone_and_dichloroethane_are_indistinguishable_in_the_record(self):
        """Which is why the third state cannot be acted on without a ruling."""
        index = build_commonchemistry_index(cache_payload())
        for cas in (OZONE_CAS, AMBIGUOUS_CAS):
            with self.subTest(cas=cas):
                self.assertTrue(index.has_formula_but_no_structure(cas))
                self.assertFalse(index.holds_no_composition(cas))

    def test_display_markup_is_stripped_from_the_formula(self):
        self.assertEqual(
            normalise_formula("C<sub>2</sub>H<sub>4</sub>Cl<sub>2</sub>"), "C2H4Cl2"
        )
        self.assertEqual(normalise_formula(None), "")

    def test_the_stored_prefix_is_stripped(self):
        index = build_commonchemistry_index(cache_payload())
        self.assertEqual(index.inchikey_for(SPECIFIC_CAS), DICHLOROETHANE_11_KEY)

    def test_a_malformed_key_is_neither_answer(self):
        """A fault in the cache must widen no gate, and close none either."""
        index = build_commonchemistry_index(
            {"detail_by_cas": {SPECIFIC_CAS: {"inchiKey": "InChIKey=rubbish"}}}
        )
        self.assertFalse(index.has_structure(SPECIFIC_CAS))
        self.assertFalse(index.holds_no_composition(SPECIFIC_CAS))
        self.assertFalse(index.has_formula_but_no_structure(SPECIFIC_CAS))

    def test_an_empty_record_is_not_an_answer(self):
        """`{}` is a 404 or a failed request, not "CAS publishes no structure".

        `_lookup_commonchemistry_detail_cached` caches `{}` for both, and 286 of
        the 7,409 entries in the 2026-08-07 cache are that shape.  Reading them
        as an answer would let a network error withhold a flow's structure.
        """
        index = build_commonchemistry_index({"detail_by_cas": {UNCACHED_CAS: {}}})
        self.assertFalse(index.holds_no_composition(UNCACHED_CAS))
        self.assertFalse(index.is_known(UNCACHED_CAS))

    def test_an_unnamed_record_is_not_an_answer(self):
        """The name is what distinguishes an answer from a hole in the cache."""
        index = build_commonchemistry_index(
            {"detail_by_cas": {UNCACHED_CAS: {"name": "", "rn": "", "inchiKey": ""}}}
        )
        self.assertFalse(index.holds_no_composition(UNCACHED_CAS))

    def test_a_record_named_by_rn_alone_is_an_answer(self):
        index = build_commonchemistry_index(
            {"detail_by_cas": {NO_COMPOSITION_CAS: {"rn": NO_COMPOSITION_CAS, "inchiKey": ""}}}
        )
        self.assertTrue(index.holds_no_composition(NO_COMPOSITION_CAS))

    def test_an_empty_payload_knows_nothing(self):
        index = build_commonchemistry_index({})
        self.assertEqual(len(index), 0)
        self.assertFalse(index.is_known(SPECIFIC_CAS))


class StructureBearingCasTestCase(unittest.TestCase):
    def test_a_cas_with_no_composition_is_withheld(self):
        instance = transformer()
        self.assertEqual(
            instance._structure_bearing_cas([NO_COMPOSITION_CAS, SPECIFIC_CAS]),
            [SPECIFIC_CAS],
        )

    def test_ozone_keeps_its_structure(self):
        """The regression this design exists for.

        Common Chemistry publishes no InChIKey for ozone.  An earlier version of
        this gate read that as "the number is non-specific" and withheld O3 --
        along with nitric oxide, nitrogen dioxide, chlorine dioxide and
        doramectin, 313 flow objects in all.
        """
        instance = transformer()
        flow = Flow(uuid="u", identifier="i", name="Ozone", source="EF 3.1")
        usable = instance._structure_bearing_cas([OZONE_CAS])
        self.assertEqual(usable, [OZONE_CAS])
        self.assertEqual(instance._structure_exclusions, {})
        matched = instance._matched_pubchem_compounds(
            flow=flow, cas_numbers=usable, chebi_ids=[]
        )
        self.assertEqual([c["cid"] for c in matched], [OZONE])

    def test_an_isomer_family_needs_a_ruling(self):
        """Identical record shape to ozone; only the ruling separates them."""
        without = transformer()
        self.assertEqual(without._structure_bearing_cas([AMBIGUOUS_CAS]), [AMBIGUOUS_CAS])

        withruling = transformer(rulings=_ruling(AMBIGUOUS_CAS, StructureRulingVerdict.ISOMER_AMBIGUOUS))
        self.assertEqual(withruling._structure_bearing_cas([AMBIGUOUS_CAS]), [])
        self.assertIn(
            "isomer unstated",
            withruling._structure_exclusions[AMBIGUOUS_CAS]["why"],
        )

    def test_a_ruling_cannot_withhold_ozone_by_accident(self):
        """A ruling is per-CAS, so ozone is unaffected by dichloroethane's."""
        instance = transformer(rulings=_ruling(AMBIGUOUS_CAS, StructureRulingVerdict.ISOMER_AMBIGUOUS))
        self.assertEqual(instance._structure_bearing_cas([OZONE_CAS]), [OZONE_CAS])

    def test_an_uncached_cas_is_kept(self):
        """A gap in the cache must never decide identity."""
        instance = transformer()
        self.assertEqual(
            instance._structure_bearing_cas([UNCACHED_CAS]), [UNCACHED_CAS]
        )
        self.assertEqual(instance._structure_exclusions, {})

    def test_an_empty_index_is_a_no_op(self):
        """A first build on a fresh machine has no cache, and must still run."""
        instance = transformer(index=CommonChemistryIndex({}, set(), set()))
        self.assertEqual(
            instance._structure_bearing_cas([NO_COMPOSITION_CAS, SPECIFIC_CAS]),
            [NO_COMPOSITION_CAS, SPECIFIC_CAS],
        )

    def test_a_specific_ruling_overrides_the_registry(self):
        """The escape hatch for a CAS whose `Unspecified` is wrong."""
        instance = transformer(
            rulings=_ruling(NO_COMPOSITION_CAS, StructureRulingVerdict.SPECIFIC)
        )
        self.assertEqual(
            instance._structure_bearing_cas([NO_COMPOSITION_CAS]), [NO_COMPOSITION_CAS]
        )

    def test_both_lookup_paths_are_recorded_as_withheld(self):
        """ChEBI matches by CAS too, so it has to be blocked by the same rule."""
        instance = transformer()
        instance._structure_bearing_cas([NO_COMPOSITION_CAS])
        entry = instance._structure_exclusions[NO_COMPOSITION_CAS]
        self.assertEqual(entry["reason"], StructureVerdict.NO_STRUCTURE.value)
        self.assertEqual(entry["dropped_cids"], [PENTANE])
        self.assertEqual(entry["dropped_chebi_ids"], ["CHEBI:15359"])

    def test_no_compound_survives_a_withheld_cas(self):
        """The end-to-end shape: the single unopposed hit does not get through."""
        instance = transformer()
        flow = Flow(uuid="u", identifier="i", name="Alkanes, C4-5", source="EF 3.1")
        usable = instance._structure_bearing_cas([NO_COMPOSITION_CAS])
        self.assertEqual(
            instance._matched_pubchem_compounds(
                flow=flow, cas_numbers=usable, chebi_ids=[]
            ),
            [],
        )

    def test_the_specific_cas_still_resolves(self):
        """The gate withholds the mixture's structure and nothing else."""
        instance = transformer()
        flow = Flow(uuid="u", identifier="i", name="1,1-Dichloroethane", source="EF 3.1")
        usable = instance._structure_bearing_cas([SPECIFIC_CAS])
        matched = instance._matched_pubchem_compounds(
            flow=flow, cas_numbers=usable, chebi_ids=[]
        )
        self.assertEqual([c["cid"] for c in matched], [DICHLOROETHANE_11])


class ShippedRulingsTestCase(unittest.TestCase):
    """The rulings that ship with the package."""

    def test_every_shipped_ruling_is_loadable_and_reasoned(self):
        rulings = load_structure_decisions()
        ambiguous = [
            r for r in rulings.values()
            if r.verdict is StructureRulingVerdict.ISOMER_AMBIGUOUS
        ]
        self.assertTrue(ambiguous, "the seeded rulings should load")
        for ruling in ambiguous:
            with self.subTest(cas=ruling.cas):
                self.assertRegex(ruling.cas, r"^\d{2,7}-\d{2}-\d$")
                self.assertGreater(
                    len(ruling.comment), 20, "a ruling must explain itself"
                )

    def test_a_ruling_without_a_comment_is_ignored(self):
        """An unreasoned entry must not silently deny a substance its structure."""
        instance = transformer(rulings={})
        self.assertEqual(instance._structure_bearing_cas([AMBIGUOUS_CAS]), [AMBIGUOUS_CAS])

    def test_a_number_ruled_both_ways_is_refused(self):
        """One number, one answer.

        The two verdicts are opposite answers to one question, so a number in
        both groups is two curators disagreeing.  It used to be two collections
        and a number could sit in both; which one won was then whichever branch
        `_lends_no_structure` reached first.
        """
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "commonchemistry-structure-decisions.json"
            path.write_bytes(orjson.dumps({
                "isomer_ambiguous": [
                    {"cas": AMBIGUOUS_CAS, "comment": "no isomer stated"}
                ],
                "specific": [
                    {"cas": AMBIGUOUS_CAS, "comment": "one substance after all"}
                ],
            }))
            with mock.patch.object(
                commonchemistry, "STRUCTURE_DECISIONS_FILEPATH", path
            ):
                load_structure_decisions.cache_clear()
                try:
                    with self.assertRaises(ValueError):
                        load_structure_decisions()
                finally:
                    load_structure_decisions.cache_clear()


class NarrowingGateTestCase(unittest.TestCase):
    def test_the_confirmed_compound_wins(self):
        instance = transformer()
        kept = instance._filter_compounds_by_commonchemistry(
            cas=SPECIFIC_CAS,
            compounds=[
                compound(DICHLOROETHANE_12, DICHLOROETHANE_12_KEY),
                compound(DICHLOROETHANE_11, DICHLOROETHANE_11_KEY),
            ],
        )
        self.assertEqual([c["cid"] for c in kept], [DICHLOROETHANE_11])

    def test_nothing_confirmed_means_nothing_filtered(self):
        """Metaldehyde's shape: CAS disagrees with every candidate we hold."""
        instance = transformer()
        kept = instance._filter_compounds_by_commonchemistry(
            cas=SPECIFIC_CAS,
            compounds=[
                compound(DICHLOROETHANE_12, DICHLOROETHANE_12_KEY),
                compound(999, "AAAAAAAAAAAAAA-BBBBBBBBSA-N"),
            ],
        )
        self.assertEqual(len(kept), 2)
        self.assertEqual(instance._structure_exclusions, {})

    def test_a_compound_with_no_inchikey_is_kept(self):
        """Absence of data is not a rejection reason."""
        instance = transformer()
        kept = instance._filter_compounds_by_commonchemistry(
            cas=SPECIFIC_CAS,
            compounds=[
                compound(DICHLOROETHANE_11, DICHLOROETHANE_11_KEY),
                compound(DICHLOROETHANE_12),
            ],
        )
        self.assertEqual(
            [c["cid"] for c in kept], [DICHLOROETHANE_11, DICHLOROETHANE_12]
        )

    def test_a_cas_with_no_published_structure_narrows_nothing(self):
        """Ozone has candidates and no key to weigh them against."""
        instance = transformer()
        kept = instance._filter_compounds_by_commonchemistry(
            cas=OZONE_CAS,
            compounds=[compound(OZONE, OZONE_KEY), compound(999, DICHLOROETHANE_12_KEY)],
        )
        self.assertEqual(len(kept), 2)

    def test_the_standard_flag_does_not_make_a_contradiction(self):
        """CAS publishes non-standard keys; they are the same structure (#42)."""
        index = build_commonchemistry_index({
            "detail_by_cas": {
                SPECIFIC_CAS: {"inchiKey": "InChIKey=JLYXXMFPNIAWKQ-CDRYSYESNA-N"}
            }
        })
        instance = transformer(index=index)
        self.assertIs(
            instance._structure_verdict(
                cas=SPECIFIC_CAS,
                compound=compound(1, "JLYXXMFPNIAWKQ-CDRYSYESSA-N"),
            ),
            StructureVerdict.CONFIRMED,
        )

    def test_a_non_standard_key_that_differs_convicts_nobody(self):
        """CAS's `/s2` keys say something standard InChI cannot (#42).

        `trans-4-tert-butylcyclohexanol` is the shape: CAS's key for 21862-63-5
        encodes relative stereochemistry, so no standard key can equal it.  The
        difference is not evidence that our structure is wrong.
        """
        index = build_commonchemistry_index({
            "detail_by_cas": {
                SPECIFIC_CAS: {"inchiKey": "InChIKey=CCOQPGVQAWPUPE-KYZUINATNA-N"}
            }
        })
        instance = transformer(index=index)
        self.assertIs(
            instance._structure_verdict(
                cas=SPECIFIC_CAS,
                compound=compound(1, "CCOQPGVQAWPUPE-UHFFFAOYSA-N"),
            ),
            StructureVerdict.INCOMPARABLE,
        )

    def test_an_incomparable_candidate_survives_a_confirmed_one(self):
        """Kept for the reason `UNKNOWN` is: nothing was said against it.

        This is where the third verdict changes an outcome.  One candidate's
        hash happens to equal CAS's non-standard key, so the gate fires; the
        other's cannot be weighed against it and must not be dropped as though
        it had lost the comparison.
        """
        index = build_commonchemistry_index({
            "detail_by_cas": {
                SPECIFIC_CAS: {"inchiKey": "InChIKey=JLYXXMFPNIAWKQ-CDRYSYESNA-N"}
            }
        })
        instance = transformer(index=index)
        kept = instance._filter_compounds_by_commonchemistry(
            cas=SPECIFIC_CAS,
            compounds=[
                compound(1, "JLYXXMFPNIAWKQ-CDRYSYESSA-N"),   # confirmed
                compound(2, "JLYXXMFPNIAWKQ-SHFUYGGZSA-N"),   # incomparable
                compound(3, DICHLOROETHANE_11_KEY),           # different skeleton
            ],
        )
        self.assertEqual([c["cid"] for c in kept], [1, 2])
        entry = instance._structure_exclusions[SPECIFIC_CAS]
        self.assertEqual(entry["dropped_cids"], [3])
        self.assertEqual(entry["incomparable_cids"], [2])

    def test_a_malformed_candidate_key_is_not_a_contradiction(self):
        """A fault in the data must not convict a compound."""
        instance = transformer()
        self.assertIs(
            instance._structure_verdict(
                cas=SPECIFIC_CAS, compound=compound(1, "rubbish")
            ),
            StructureVerdict.INCOMPARABLE,
        )

    def test_a_stereo_only_contradiction_is_flagged_as_such(self):
        """A curator has to be able to tell #42 from #35 from the queue alone."""
        index = build_commonchemistry_index({
            "detail_by_cas": {
                SPECIFIC_CAS: {"inchiKey": "InChIKey=QIVBCDIJIAJPQS-VIFPVBQESA-N"}
            }
        })
        instance = transformer(index=index)
        instance._filter_compounds_by_commonchemistry(
            cas=SPECIFIC_CAS,
            compounds=[
                compound(1, "QIVBCDIJIAJPQS-VIFPVBQESA-N"),
                compound(2, "QIVBCDIJIAJPQS-UHFFFAOYSA-N"),
                compound(3, DICHLOROETHANE_11_KEY),
            ],
        )
        entry = instance._structure_exclusions[SPECIFIC_CAS]
        self.assertEqual(entry["dropped_cids"], [2, 3])
        self.assertEqual(entry["stereo_only_cids"], [2])

    def test_a_single_candidate_is_not_narrowed(self):
        """One candidate is not a choice; the withholding gate handles the rest."""
        instance = transformer()
        kept = instance._filter_compounds_by_commonchemistry(
            cas=SPECIFIC_CAS, compounds=[compound(DICHLOROETHANE_12, DICHLOROETHANE_12_KEY)]
        )
        self.assertEqual([c["cid"] for c in kept], [DICHLOROETHANE_12])


class ReviewQueueTestCase(unittest.TestCase):
    def test_a_withheld_structure_asks_for_review(self):
        instance = transformer()
        instance._structure_bearing_cas([NO_COMPOSITION_CAS])
        items = [
            item for item in instance.review_queue_items()
            if item.queue_name == ReviewQueue.COMMONCHEM_STRUCTURE_EXCLUSION
        ]
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].item_key, NO_COMPOSITION_CAS)
        self.assertIs(items[0].severity, Severity.REVIEW)
        self.assertIn("publishes no structure", items[0].title)

    def test_a_quiet_run_queues_nothing(self):
        self.assertEqual(transformer().review_queue_items(), [])
