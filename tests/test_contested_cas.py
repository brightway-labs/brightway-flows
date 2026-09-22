"""The four signals that decide a registry number two names claim.

The rule this module does *not* implement is the one #34 proposed -- refuse to
merge on a contested number without external corroboration -- and the first test
class is why: 19 of EF 3.1's 68 contested groups are contested because a manual
fix of ours made them so, and corroboration-required splits them.  So the order
of the signals is the design, and it is what these assert.
"""

from __future__ import annotations

import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

import orjson

from brightway_flows.domain.flow import Flow
from brightway_flows.domain.flow_object import stable_flow_object_id
from brightway_flows.flow_layers import resolve_flow_layers
from brightway_flows.flow_layers.contested_cas import (
    DECISIONS_FILEPATH,
    FACTOR_TOLERANCE,
    ContestedCasRuling,
    Verdict,
    cas_supplied_by_manual_fixes,
    contested_cas_index,
    corroborated_by_synonyms,
    factor_disagreement,
    load_decisions,
    more_precise_value,
    names_claiming,
    significant_digits,
    to_significant_digits,
)
from brightway_flows.integrations.ef31 import MANUAL_FIXES_FILEPATH
from brightway_flows.pipeline.contested_cas_review import contested_cas_items
from brightway_flows.pipeline.review_records import ReviewQueue
from brightway_flows.sources import base_source_list
from brightway_flows.webapps.app.queries.queue import DEFINITIONS as QUEUE_DEFINITIONS
from brightway_flows.transformers.consensus_match.rename_gate import RenameGate
from brightway_flows.transformers.enrich_references import EnrichReferencesTransformer
from brightway_flows.domain.context_registry import context_dict_for_iri

# Two contexts from the vocabulary, resolved rather than written out.  They
# used to be hand-written dicts, and neither was a context: the air one omitted
# the population density that ground-level emissions require, and the water one
# put "Freshwater" -- not a vertical strata value at all -- in `strata`.  Both
# were built into `Flow` records that nothing validated, which is what typing
# the field as a `Context` ends (#97).
_AIR = context_dict_for_iri("https://vocab.brightway.one/flow-contexts/envi-air-grle-ru10pesq")
_WATER = context_dict_for_iri("https://vocab.brightway.one/flow-contexts/envi-wate-suwa")


def _flow(uuid, name, cas, factors=(), context=None):
    return Flow.from_dict({
        "uuid": uuid,
        "prefLabel": [{"@value": name, "@language": "en"}],
        "source": "EF 3.1",
        "context": context or _AIR,
        "cas_numbers": list(cas),
        "lcia_methods": [
            {"name": method, "characterization_factor": value} for method, value in factors
        ],
    })


def _write(tmp, decisions):
    path = Path(tmp) / "decisions.json"
    path.write_bytes(orjson.dumps({"schema_version": 1, "decisions": decisions}))
    return path


class OnlyASharedNumberIsContestedTestCase(unittest.TestCase):
    def test_one_name_one_number_is_not_contested(self):
        index = contested_cas_index([
            _flow("u-1", "Dichloromethane", ["75-09-2"]),
            _flow("u-2", "Dichloromethane", ["75-09-2"], context=_WATER),
        ])
        self.assertEqual(index, {})

    def test_two_names_on_one_number_are(self):
        index = contested_cas_index([
            _flow("u-1", "HFE-236ea2", ["84011-06-3"]),
            _flow("u-2", "HFE-236fa", ["84011-06-3"]),
        ])
        self.assertEqual(sorted(index), ["84011-06-3"])
        self.assertEqual(index["84011-06-3"].names, ("hfe-236ea2", "hfe-236fa"))

    def test_case_and_spacing_do_not_make_a_second_name(self):
        """`HCFC-140` and `hcfc-140` are one name to the layering, so one here."""
        index = contested_cas_index([
            _flow("u-1", "HCFC-140", ["71-55-6"]),
            _flow("u-2", "hcfc-140", ["71-55-6"]),
        ])
        self.assertEqual(index, {})


class TheSourceListsOwnFactorsTestCase(unittest.TestCase):
    """Signal 3, and the reason the tolerance exists."""

    def _run(self, a, b):
        return contested_cas_index([
            _flow("u-1", "HFE-236ea2", ["84011-06-3"], [("Climate change", a)]),
            _flow("u-2", "HFE-236fa", ["84011-06-3"], [("Climate change", b)]),
        ])["84011-06-3"]

    def test_different_factors_separate(self):
        verdict = self._run(2590.0, 1100.0)
        self.assertEqual(verdict.verdict, Verdict.SEPARATE)
        self.assertAlmostEqual(verdict.evidence["divergence"], 2590 / 1100 - 1)

    def test_the_same_factor_rounded_differently_does_not(self):
        """`5.5192e-08` and `5.52e-08` are one number published twice."""
        self.assertNotEqual(self._run(5.5192e-08, 5.52e-08).verdict, Verdict.SEPARATE)

    def test_a_difference_just_inside_the_tolerance_does_not_separate(self):
        self.assertNotEqual(self._run(100.0, 100.0 * (1 + FACTOR_TOLERANCE / 2)).verdict,
                            Verdict.SEPARATE)

    def test_a_difference_just_outside_it_does(self):
        self.assertEqual(self._run(100.0, 100.0 * (1 + FACTOR_TOLERANCE * 2)).verdict,
                         Verdict.SEPARATE)

    def test_factors_are_compared_within_a_context_not_across_one(self):
        """Two contexts legitimately carry different factors for one substance."""
        index = contested_cas_index([
            _flow("u-1", "Dichloromethane", ["75-09-2"], [("Human toxicity", 5.5e-08)]),
            _flow("u-2", "Methylene chloride", ["75-09-2"], [("Human toxicity", 2.4e-09)],
                  context=_WATER),
        ])
        self.assertEqual(index["75-09-2"].verdict, Verdict.UNDECIDED)

    def test_nothing_comparable_is_not_agreement(self):
        """One side carrying no factors says nothing about whether they are one."""
        index = contested_cas_index([
            _flow("u-1", "pentafluoro-1-propanol", ["422-05-9"]),
            _flow("u-2", "2,2,3,3,3-Pentafluoropropan-1-ol", ["422-05-9"],
                  [("Climate change", 34.3)]),
        ])
        self.assertEqual(index["422-05-9"].verdict, Verdict.UNDECIDED)
        self.assertEqual(index["422-05-9"].evidence["comparable"], 0)

    def test_a_zero_factor_is_skipped_rather_than_compared(self):
        index = contested_cas_index([
            _flow("u-1", "a", ["1-1-1"], [("Climate change", 0.0)]),
            _flow("u-2", "b", ["1-1-1"], [("Climate change", 12.0)]),
        ])
        self.assertEqual(index["1-1-1"].verdict, Verdict.UNDECIDED)

    def test_comparable_counts_only_pairs_both_names_publish(self):
        flows = [
            _flow("u-1", "a", ["1-1-1"], [("M1", 1.0), ("M2", 2.0)]),
            _flow("u-2", "b", ["1-1-1"], [("M1", 1.0)]),
        ]
        _, _, comparable = factor_disagreement(flows, name_of={"u-1": "a", "u-2": "b"})
        self.assertEqual(comparable, 1)


class OneNumberWrittenTwiceTestCase(unittest.TestCase):
    """Which of two published numbers is the other one rounded (#63).

    Not a signal: nothing here decides a contest.  It answers the question a
    merge asks after the contest is over -- both rows publish this factor, only
    one number can be published, which one is it?
    """

    def test_the_rounded_number_gives_way_to_the_precise_one(self):
        """EF's refrigerant, published under two names to two precisions."""
        self.assertEqual(more_precise_value(0.000118, 0.00011755), 0.00011755)
        self.assertEqual(more_precise_value(0.00011755, 0.000118), 0.00011755)

    def test_rounding_goes_away_from_zero_the_way_a_published_table_does(self):
        """`%.3g` gives `7.13e-09` for `7.135e-09` and EF publishes `7.14e-09`;
        rounding the shorter way would read one number as two."""
        self.assertEqual(to_significant_digits(7.135e-09, 3), Decimal("7.14E-9"))
        self.assertEqual(more_precise_value(7.14e-09, 7.135e-09), 7.135e-09)

    def test_two_numbers_at_one_precision_prefer_neither(self):
        self.assertIsNone(more_precise_value(1.23e-05, 1.24e-05))

    def test_close_is_not_the_same_as_rounded(self):
        """`0.000119` is well inside the tolerance of `0.00011755` and is not
        what that number becomes at three figures.  Two numbers."""
        self.assertIsNone(more_precise_value(0.000119, 0.00011755))

    def test_a_rounding_wider_than_the_tolerance_prefers_neither(self):
        """`5` is `5.4` at one significant figure, and they are 8% apart --
        further than this project lets two numbers be and stay one number."""
        self.assertIsNone(more_precise_value(5.0, 5.4))
        self.assertEqual(more_precise_value(5.0, 5.04), 5.04)

    def test_equal_numbers_prefer_neither(self):
        self.assertIsNone(more_precise_value(34.3, 34.3))

    def test_zero_is_a_rounding_of_nothing(self):
        self.assertIsNone(more_precise_value(0.0, 0.5))

    def test_two_signs_are_two_numbers(self):
        """An uptake credit against an emission is a question about sign
        conventions, which is not this one."""
        self.assertIsNone(more_precise_value(-0.000118, 0.00011755))

    def test_a_negative_pair_is_read_the_same_way(self):
        self.assertEqual(more_precise_value(-0.000118, -0.00011755), -0.00011755)

    def test_trailing_zeros_are_not_claimed_precision(self):
        """A source list writing `100` has not measured three digits."""
        self.assertEqual(significant_digits(100.0), 1)
        self.assertEqual(significant_digits(0.000118), 3)
        self.assertEqual(significant_digits(0.00011755), 5)


class CommonChemistrySynonymyTestCase(unittest.TestCase):
    """Signal 4."""

    RECORD = {"rn": "75-09-2", "name": "Dichloromethane",
              "synonyms": ["Methane, dichloro-", "Methylene chloride"]}

    def test_every_name_a_synonym_corroborates(self):
        self.assertTrue(corroborated_by_synonyms(
            ["dichloromethane", "methylene chloride"], self.RECORD))

    def test_one_name_outside_the_synonyms_does_not(self):
        self.assertFalse(corroborated_by_synonyms(
            ["dichloromethane", "something else"], self.RECORD))

    def test_a_spelling_variant_still_corroborates(self):
        record = {"name": "Barium sulfate", "synonyms": ["Baryte"]}
        self.assertTrue(corroborated_by_synonyms(["barium sulphate", "baryte"], record))

    def test_markup_in_a_synonym_is_stripped(self):
        record = {"name": "<em>N</em>,<em>N</em>-dimethylformamide", "synonyms": []}
        self.assertTrue(corroborated_by_synonyms(["n,n-dimethylformamide"], record))

    def test_an_empty_record_corroborates_nothing(self):
        """`{}` is a 404 or a failed request, not an answer -- #267's correction."""
        self.assertFalse(corroborated_by_synonyms(["anything"], {}))
        self.assertFalse(corroborated_by_synonyms(["anything"], None))

    def test_it_merges_when_the_factors_are_silent(self):
        index = contested_cas_index(
            [_flow("u-1", "Dichloromethane", ["75-09-2"]),
             _flow("u-2", "Methylene chloride", ["75-09-2"])],
            commonchemistry={"75-09-2": self.RECORD},
        )
        self.assertEqual(index["75-09-2"].verdict, Verdict.MERGE)


class TheOrderOfTheSignalsTestCase(unittest.TestCase):
    """Which signal wins when two of them speak."""

    FLOWS = [
        _flow("u-1", "HFE-236ea2", ["84011-06-3"], [("Climate change", 2590.0)]),
        _flow("u-2", "HFE-236fa", ["84011-06-3"], [("Climate change", 1100.0)]),
    ]

    def test_a_ruling_beats_the_factors(self):
        with self.subTest("merge"):
            index = contested_cas_index(self.FLOWS, decisions={
                "84011-06-3": ContestedCasRuling(
                    cas="84011-06-3", verdict=Verdict.MERGE, names=(), comment="curator",
                ),
            })
            self.assertEqual(index["84011-06-3"].verdict, Verdict.MERGE)
            self.assertEqual(index["84011-06-3"].decided_by, "curated ruling")

    def test_a_ruling_beats_a_manual_fix_of_ours(self):
        index = contested_cas_index(self.FLOWS, decisions={
            "84011-06-3": ContestedCasRuling(
                cas="84011-06-3", verdict=Verdict.SEPARATE, names=(), comment="curator",
            ),
        }, supplied_by_us=frozenset({"84011-06-3"}))
        self.assertEqual(index["84011-06-3"].verdict, Verdict.SEPARATE)

    def test_a_manual_fix_of_ours_beats_the_factors(self):
        """The merge is the point of supplying the number; #19 and #35 depend on this."""
        index = contested_cas_index(self.FLOWS, supplied_by_us=frozenset({"84011-06-3"}))
        self.assertEqual(index["84011-06-3"].verdict, Verdict.MERGE)

    def test_the_factors_beat_common_chemistry(self):
        index = contested_cas_index(self.FLOWS, commonchemistry={
            "84011-06-3": {"name": "HFE-236ea2", "synonyms": ["HFE-236fa"]},
        })
        self.assertEqual(index["84011-06-3"].verdict, Verdict.SEPARATE)

    def test_nothing_speaking_leaves_it_undecided(self):
        index = contested_cas_index([
            _flow("u-1", "borate", ["12447-40-4"]),
            _flow("u-2", "borax", ["12447-40-4"]),
        ])
        self.assertEqual(index["12447-40-4"].verdict, Verdict.UNDECIDED)


class ReadingTheCuratedInputsTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def test_a_ruling_without_a_comment_is_refused(self):
        with self.assertRaises(ValueError):
            load_decisions(_write(self.tmp.name, [{"cas": "1-1-1", "decision": "separate"}]))

    def test_an_unrecognised_decision_is_dropped_rather_than_guessed(self):
        path = _write(self.tmp.name, [{"cas": "1-1-1", "decision": "maybe", "comment": "x"}])
        self.assertEqual(load_decisions(path), {})

    def test_a_missing_file_yields_no_rulings(self):
        self.assertEqual(load_decisions(Path("/nonexistent/decisions.json")), {})

    def test_manual_fixes_supply_the_numbers_they_write(self):
        supplied = cas_supplied_by_manual_fixes(MANUAL_FIXES_FILEPATH)
        self.assertIn("75-09-2", supplied)      # #35, Methylene chloride
        self.assertIn("754-12-1", supplied)     # #19, HFO-1234yf
        self.assertNotIn("84011-06-3", supplied)

    def test_a_fix_that_removes_a_value_supplies_nothing(self):
        path = Path(self.tmp.name) / "fixes.json"
        path.write_bytes(orjson.dumps({"fixes": [
            {"match": {"uuid": "u"}, "field": "cas_numbers",
             "remove_value": "7732-18-5", "comment": "brine"},
        ]}))
        self.assertEqual(cas_supplied_by_manual_fixes(path), frozenset())


class TheCheckedInRulingsTestCase(unittest.TestCase):
    def test_they_load_and_state_their_reasons(self):
        rulings = load_decisions()
        self.assertTrue(rulings)
        for cas, ruling in rulings.items():
            with self.subTest(cas=cas):
                self.assertIn(ruling.verdict, (Verdict.MERGE, Verdict.SEPARATE))
                self.assertTrue(ruling.comment.strip())

    def test_the_four_hydrofluoroether_numbers_are_ruled_separate(self):
        rulings = load_decisions()
        for cas in ("382-34-3", "84011-06-3", "406-78-0", "1885-48-9"):
            with self.subTest(cas=cas):
                self.assertEqual(rulings[cas].verdict, Verdict.SEPARATE)

    def test_no_ruling_contradicts_a_manual_fix_of_ours(self):
        """A number we supplied and a `separate` ruling would be two curators disagreeing."""
        supplied = cas_supplied_by_manual_fixes(MANUAL_FIXES_FILEPATH)
        for cas, ruling in load_decisions().items():
            if ruling.verdict is Verdict.SEPARATE:
                self.assertNotIn(cas, supplied, f"{cas} is both supplied by us and ruled separate")

    def test_the_file_is_where_the_module_looks_for_it(self):
        self.assertTrue(DECISIONS_FILEPATH.exists())


class TheLayeringActsOnTheVerdictTestCase(unittest.TestCase):
    """`resolve_flow_layers` consulting the index, against the checked-in rulings.

    These run through the real `contested-cas-decisions.json` and the real EF 3.1
    fixes file, because the wiring is only worth testing against what it will
    actually read.  Signal 4 is not exercised here: its input is a download cache
    that is not in the repository, and a test that passes only on a machine that
    has run the enrichment is worse than no test.
    """

    def _resolve(self, rows):
        flow_objects, elementary_flows, stats = resolve_flow_layers(
            [Flow.from_dict(r) for r in rows], source_list=base_source_list()
        )
        return {f.elementary_flow_id: f.flow_object_id for f in elementary_flows}, stats

    def _row(self, uuid, name, cas, factors=()):
        return {
            "uuid": uuid,
            "prefLabel": [{"@value": name, "@language": "en"}],
            "source": "EF 3.1",
            "context": _AIR,
            "cas_numbers": list(cas),
            "lcia_methods": [
                {"name": m, "characterization_factor": v} for m, v in factors
            ],
        }

    def test_a_ruling_separates_two_names_on_one_number(self):
        resolved, stats = self._resolve([
            self._row("u-1", "HFE-236ea2", ["84011-06-3"]),
            self._row("u-2", "HFE-236fa", ["84011-06-3"]),
        ])
        self.assertNotEqual(resolved["u-1"], resolved["u-2"])
        self.assertEqual(stats["contested_cas_separations"], 2)

    def test_the_separated_objects_are_keyed_on_name_and_number(self):
        resolved, _ = self._resolve([
            self._row("u-1", "HFE-236ea2", ["84011-06-3"]),
            self._row("u-2", "HFE-236fa", ["84011-06-3"]),
        ])
        self.assertEqual(
            resolved["u-1"],
            stable_flow_object_id("fo", "name:hfe-236ea2|cas:84011-06-3"),
        )

    def test_the_fused_identifier_is_not_inherited_by_either_side(self):
        """Nothing should keep the id of an object that was the wrong merge."""
        resolved, _ = self._resolve([
            self._row("u-1", "HFE-236ea2", ["84011-06-3"]),
            self._row("u-2", "HFE-236fa", ["84011-06-3"]),
        ])
        fused = stable_flow_object_id("fo", "cas:84011-06-3")
        self.assertNotIn(fused, set(resolved.values()))

    def test_the_same_name_still_meets_itself_across_contexts(self):
        rows = [
            self._row("u-1", "HFE-236ea2", ["84011-06-3"]),
            self._row("u-2", "HFE-236fa", ["84011-06-3"]),
        ]
        rows.append({**self._row("u-3", "HFE-236ea2", ["84011-06-3"]), "context": _WATER})
        resolved, _ = self._resolve(rows)
        self.assertEqual(resolved["u-1"], resolved["u-3"])

    def test_a_later_flow_cannot_rejoin_them_through_the_number(self):
        """The separated objects are registered in no CAS table, which is the point."""
        resolved, _ = self._resolve([
            self._row("u-1", "HFE-236ea2", ["84011-06-3"]),
            self._row("u-2", "HFE-236fa", ["84011-06-3"]),
            self._row("u-3", "Some other name", ["84011-06-3"]),
        ])
        self.assertEqual(len(set(resolved.values())), 3)

    def test_a_number_one_of_our_fixes_supplied_still_merges(self):
        """#35's merge, through the whole layering, factors and all."""
        resolved, stats = self._resolve([
            self._row("u-1", "Dichloromethane", ["75-09-2"], [("Human toxicity", 5.5192e-08)]),
            self._row("u-2", "Methylene Chloride", ["75-09-2"], [("Human toxicity", 5.52e-08)]),
        ])
        self.assertEqual(resolved["u-1"], resolved["u-2"])
        self.assertEqual(resolved["u-1"], stable_flow_object_id("fo", "cas:75-09-2"))
        self.assertEqual(stats["contested_cas_separations"], 0)

    def test_an_uncontested_number_is_untouched(self):
        resolved, stats = self._resolve([
            self._row("u-1", "Dichloromethane", ["75-09-2"]),
            self._row("u-2", "Dichloromethane", ["75-09-2"]),
        ])
        self.assertEqual(len(set(resolved.values())), 1)
        self.assertEqual(stats["contested_cas_numbers"], 0)

    def test_a_qualified_flow_is_not_dragged_into_the_contest(self):
        """The qualifier axis claims it first, so it never asks the question.

        Methane is the live case: EF's biogenic and fossil correction flows are
        characterised differently from unqualified methane, and reading that as a
        contested number would move unqualified methane off `cas:74-82-8`.
        """
        resolved, stats = self._resolve([
            self._row("u-1", "Methane", ["74-82-8"], [("Climate change", 29.8)]),
            self._row("u-2", "Methane (biogenic)", ["74-82-8"], [("Climate change", 27.0)]),
        ])
        self.assertEqual(stats["contested_cas_numbers"], 0)
        self.assertEqual(resolved["u-1"], stable_flow_object_id("fo", "cas:74-82-8"))


class AContestedNumberLendsNoStructureTestCase(unittest.TestCase):
    """Stage 4 of the plan: separating the flows is not enough on its own.

    Separated flows still carry the contested number, and the number still
    drives the structure lookup -- so without this the four hydrofluoroether
    groups become twelve flow objects that all hold one ether's structure,
    formula and InChIKey.  That is #6's shape reached from a new direction.

    Only *ruled* separations withhold, not the ones the factor signal derives.
    Withholding chemistry is the stronger action, and the principle is the one
    `commonchemistry-structure-decisions.json` already follows: the default is
    to do nothing, and a number is withheld only where a curator says so.
    """

    def _transformer(self):
        instance = EnrichReferencesTransformer()
        instance._contested_rulings = {
            cas for cas, ruling in load_decisions().items()
            if ruling.verdict is Verdict.SEPARATE
        }
        return instance

    def test_a_ruled_number_lends_none(self):
        reason = self._transformer()._lends_no_structure("84011-06-3")
        self.assertIsNotNone(reason)
        self.assertIn("contested", reason)

    def test_all_four_hydrofluoroether_numbers_lend_none(self):
        instance = self._transformer()
        for cas in ("382-34-3", "84011-06-3", "406-78-0", "1885-48-9"):
            with self.subTest(cas=cas):
                self.assertIsNotNone(instance._lends_no_structure(cas))

    def test_an_uncontested_number_still_lends_one(self):
        self.assertIsNone(self._transformer()._lends_no_structure("75-09-2"))

    def test_the_numbers_our_own_fixes_supplied_still_lend_one(self):
        """#19 and #35 give a designation a number *so that* it resolves."""
        instance = self._transformer()
        for cas in sorted(cas_supplied_by_manual_fixes(MANUAL_FIXES_FILEPATH)):
            with self.subTest(cas=cas):
                self.assertIsNone(instance._lends_no_structure(cas))

    def test_a_transformer_that_never_loaded_the_rulings_withholds_nothing(self):
        """`setup()` is not called in every test, and a missing table is not a ruling."""
        self.assertIsNone(EnrichReferencesTransformer()._lends_no_structure("84011-06-3"))


class TheUndecidedReachACuratorTestCase(unittest.TestCase):
    """Stage 5: a merge nothing supports is asked about, not assumed."""

    def _verdicts(self):
        return contested_cas_index([
            _flow("u-1", "borate", ["12447-40-4"]),
            _flow("u-2", "borax", ["12447-40-4"]),
            _flow("u-3", "HFE-236ea2", ["84011-06-3"], [("Climate change", 2590.0)]),
            _flow("u-4", "HFE-236fa", ["84011-06-3"], [("Climate change", 1100.0)]),
        ])

    def test_only_the_undecided_are_queued(self):
        items = contested_cas_items(self._verdicts())
        self.assertEqual([i.item_key for i in items], ["12447-40-4"])

    def test_the_item_carries_the_names_and_the_evidence_that_was_missing(self):
        item, = contested_cas_items(self._verdicts())
        self.assertEqual(item.queue_name, ReviewQueue.CONTESTED_CAS)
        self.assertEqual(item.payload["names"], ["borate", "borax"])
        self.assertEqual(item.payload["comparable_factors"], 0)

    def test_the_queue_is_ordered_by_what_is_at_stake(self):
        verdicts = contested_cas_index([
            _flow("u-1", "borate", ["12447-40-4"]),
            _flow("u-2", "borax", ["12447-40-4"]),
            _flow("u-3", "1,1,1-trichloroethane", ["79-00-5"]),
            _flow("u-4", "1,1,2-trichloroethane", ["79-00-5"]),
        ])
        items = contested_cas_items(verdicts, flow_counts={"79-00-5": 13, "12447-40-4": 7})
        self.assertEqual([i.item_key for i in items], ["79-00-5", "12447-40-4"])
        self.assertEqual([i.item_index for i in items], [0, 1])

    def test_a_separated_number_is_not_a_question(self):
        """It has been answered, and the answer is on the record."""
        items = contested_cas_items(self._verdicts())
        self.assertNotIn("84011-06-3", {i.item_key for i in items})

    def test_the_queue_has_somewhere_to_render(self):
        """`review_queue` rows for a queue with no definition would not be shown."""
        self.assertIn(str(ReviewQueue.CONTESTED_CAS), {d.name for d in QUEUE_DEFINITIONS})


class TheNameAFlowArrivedUnderTestCase(unittest.TestCase):
    """A rename must not be able to erase the contest before it is asked about.

    `consensus_match` renames a flow to the name Common Chemistry gives its CAS.
    For a synonym that is right.  Where the number is wrong for the flow it
    writes another substance's name over this one -- EF's `1,1,1-trichloroethane`
    carries `79-00-5`, whose name is `1,1,2-Trichloroethane` -- and the two
    substances then share a name, so nothing is left to detect (#34).
    """

    def _renamed(self, uuid, published, arrived, cas):
        return Flow.from_dict({
            "uuid": uuid,
            "prefLabel": [{"@value": published, "@language": "en"}],
            "source": "EF 3.1",
            "context": _AIR,
            "cas_numbers": [cas],
            "source_refs": [{
                "list_name": "EF", "list_version": "3.1",
                "source_flow_uuid": uuid, "source_flow_name": arrived,
            }],
        })

    def _trichloroethanes(self):
        return [
            self._renamed("u-1", "1,1,2-Trichloroethane", "1,1,1-trichloroethane", "79-00-5"),
            self._renamed("u-2", "1,1,2-Trichloroethane", "1,1,2-trichloroethane", "79-00-5"),
        ]

    def test_the_published_labels_alone_see_no_contest(self):
        """The defect: after the rename both flows carry one name."""
        index = contested_cas_index(self._trichloroethanes())
        self.assertEqual(index, {})

    def test_the_names_they_arrived_under_do(self):
        index = contested_cas_index(
            self._trichloroethanes(), list_name="EF", list_version="3.1")
        self.assertEqual(
            index["79-00-5"].names,
            ("1,1,1-trichloroethane", "1,1,2-trichloroethane"),
        )

    def test_it_is_a_question_rather_than_an_answer(self):
        """No factor evidence and no full synonymy: it goes to a curator."""
        index = contested_cas_index(
            self._trichloroethanes(), list_name="EF", list_version="3.1")
        self.assertEqual(index["79-00-5"].verdict, Verdict.UNDECIDED)

    def test_another_list_naming_the_same_substance_is_not_a_contest(self):
        """A number meeting across two lists is the merge working."""
        flow = Flow.from_dict({
            "uuid": "u-1",
            "prefLabel": [{"@value": "Dichloromethane", "@language": "en"}],
            "source": "EF 3.1",
            "context": _AIR,
            "cas_numbers": ["75-09-2"],
            "source_refs": [
                {"list_name": "EF", "list_version": "3.1",
                 "source_flow_uuid": "u-1", "source_flow_name": "dichloromethane"},
                {"list_name": "ecoinvent", "list_version": "3.12",
                 "source_flow_uuid": "x-1", "source_flow_name": "Methylene chloride"},
            ],
        })
        self.assertEqual(
            contested_cas_index([flow], list_name="EF", list_version="3.1"), {})

    def test_no_list_named_reads_no_references_at_all(self):
        """Otherwise every list's names would count, whichever list was asked about."""
        names = names_claiming(self._trichloroethanes()[0])
        self.assertEqual(names, {"1,1,2-trichloroethane"})


class ARuledNumberDrivesNoRenameTestCase(unittest.TestCase):
    """The other half: a name derived from a contested number is one substance's.

    Gated on the ruling rather than on the contest.  Declining every rename from
    a contested number was measured against the 804 renames of one build: it
    would have refused 14, of which 3 were the defect and 11 were good --
    `Baryte` -> `Barium sulfate`, and this project's own `HCFC-140` ->
    `1,1,1-Trichloroethane` among them.
    """

    def _gate(self, separated=()):
        return RenameGate(separated_cas=frozenset(separated))

    def test_a_rename_from_a_ruled_number_is_declined(self):
        gate = self._gate({"84011-06-3"})
        self.assertFalse(gate.approves(
            "u-1", "HFE-236fa", "HFE-236ea2", rule="cc_chebi_agreement", cas="84011-06-3"))
        self.assertEqual(gate.declined_contested, [("84011-06-3", "HFE-236fa", "HFE-236ea2")])

    def test_a_rename_from_any_other_number_is_untouched(self):
        """Approval still comes from the label rulings, as before.

        `cc_chebi_agreement` is a trusted rule, so an unruled pair from it is
        applied -- which is what makes gating on the contest rather than on the
        ruling so expensive: this is the path all 11 good renames take.
        """
        gate = self._gate({"84011-06-3"})
        self.assertTrue(gate.approves(
            "u-1", "Baryte", "Barium sulfate", rule="cc_chebi_agreement", cas="7727-43-7"))
        self.assertEqual(gate.declined_contested, [])

    def test_a_rename_with_no_cas_is_untouched(self):
        gate = self._gate({"84011-06-3"})
        gate.approves("u-1", "Systhane", "Myclobutanil", rule="cc_chebi_agreement")
        self.assertEqual(gate.declined_contested, [])

    def test_reset_clears_the_declines(self):
        gate = self._gate({"84011-06-3"})
        gate.approves("u-1", "HFE-236fa", "HFE-236ea2",
                      rule="cc_chebi_agreement", cas="84011-06-3")
        gate.reset()
        self.assertEqual(gate.declined_contested, [])

    def test_the_checked_in_rulings_populate_it(self):
        separated = {cas for cas, r in load_decisions().items()
                     if r.verdict is Verdict.SEPARATE}
        self.assertIn("84011-06-3", separated)
        gate = self._gate(separated)
        self.assertFalse(gate.approves(
            "u-1", "HFE-236fa", "HFE-236ea2", rule="cc_chebi_agreement", cas="84011-06-3"))


if __name__ == "__main__":
    unittest.main()
