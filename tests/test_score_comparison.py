"""Two scores for one unit process, and every reason they can differ.

The inventory is common to both sides, so a difference for one flow is one of
six things -- the flow did not map, it mapped onto a flow in another unit with
no conversion, we have no factor, the vendor has none, the two factors differ,
or they agree -- and each has a case here that no other reason would pass.

The worked example is the hand analysis's second table, on a
hand-made inventory shaped like the wind activity's: the fossil factors
imported as 1.0 are `factor-differs`, uranium with no factor of ours is
`no-consensus-factor`, and the multiplier the merge recorded for a `kg -> MJ`
crossing goes on the amount, not on the factor.
"""

from __future__ import annotations

import unittest

from brightway_flows.domain.lcia.crosswalk import (
    by_stated_method_category,
    impact_categories,
)
from brightway_flows.domain.lcia.records import Band
from brightway_flows.domain.lcia.unit_process_scores import (
    ARTIFACT_SCHEMA_VERSION,
    ArtifactCategory,
    ArtifactFactor,
    ArtifactFlow,
    ArtifactRelease,
    InventoryLine,
    ScoreArtifact,
    UnitProcess,
)
from brightway_flows.lcia.conversion import UnitCrossing
from brightway_flows.lcia.matching import MergeTarget
from brightway_flows.lcia.scores.compare import (
    ContributionReason,
    compare_release,
    contributions_for,
    match_categories,
)

FOSSILS = "EF v3.0|energy resources: non-renewable|abiotic depletion potential (ADP): fossil fuels"
METALS = "EF v3.0|ecotoxicity: freshwater, metals|comparative toxic unit for ecosystems (CTUe)"
COAL, OIL, GAS, URANIUM, PEAT, WATER = "s-coal", "s-oil", "s-gas", "s-uranium", "s-peat", "s-water"
#: How our factors are keyed: the method as well as the category, because a
#: slug is unique inside a method and not across them (#349).
EF_FOSSILS = ("ef", "resource-use-fossils")


def _target(uuid: str, *, source_unit="kilogram", target_unit="kilogram", multiplier=None):
    return MergeTarget(uuid, UnitCrossing(source_unit, target_unit, multiplier))


def artifact(*, inventory=None, scores=None) -> ScoreArtifact:
    inventory = inventory or [
        InventoryLine(COAL, 0.00590783),
        InventoryLine(OIL, 0.00222268),
        InventoryLine(GAS, 0.00192141),
        InventoryLine(URANIUM, 6.0e-8),
        InventoryLine(PEAT, 1.0e-6),
        InventoryLine(WATER, 0.12),
    ]
    factors = [
        ArtifactFactor(FOSSILS, COAL, 18.0),
        ArtifactFactor(FOSSILS, OIL, 42.3),
        ArtifactFactor(FOSSILS, GAS, 33.7),
        ArtifactFactor(FOSSILS, URANIUM, 560000.0),
        ArtifactFactor(FOSSILS, PEAT, 9.0),
        ArtifactFactor(METALS, WATER, 0.0),
    ]
    by_flow = {f.source_flow_uuid: f.amount for f in factors if f.category_key == FOSSILS}
    stated = sum(line.amount * by_flow.get(line.source_flow_uuid, 0.0) for line in inventory)
    return ScoreArtifact(
        schema_version=ARTIFACT_SCHEMA_VERSION,
        release=ArtifactRelease(
            "ecoinvent", "3.8", "apos", "ecoinvent-3.8-apos", "ecoinvent-3.8-apos",
            "EF v3.0", {}, "2026-08-25T00:00:00+00:00", 1, 79,
        ),
        categories=[
            ArtifactCategory(FOSSILS, "EF v3.0", "energy resources: non-renewable",
                             "abiotic depletion potential (ADP): fossil fuels", "MJ"),
            ArtifactCategory(METALS, "EF v3.0", "ecotoxicity: freshwater, metals",
                             "comparative toxic unit for ecosystems (CTUe)", "CTUe"),
        ],
        flows=[ArtifactFlow(u, u, "kilogram", ["natural resource", "in ground"]) for u in
               (COAL, OIL, GAS, URANIUM, PEAT, WATER)],
        factors=factors,
        unit_processes=[UnitProcess(
            "wind", "035af6a2", "electricity production, wind", "electricity, high voltage",
            1.0, "kilowatt hour", "SE", {}, inventory,
            scores or {FOSSILS: stated, METALS: 0.0},
        )],
    )


def categories(art: ScoreArtifact):
    ids = {(d.method, d.slug): f"id-{d.slug}" for d in impact_categories()}
    return match_categories(art.categories, by_stated_method_category(), consensus_ids=ids)


class CategoryMatchingTestCase(unittest.TestCase):
    def test_an_ef30_category_is_about_one_of_ours(self):
        fossils, metals = categories(artifact())
        self.assertEqual(fossils.slug, "resource-use-fossils")
        self.assertEqual(fossils.impact_category_id, "id-resource-use-fossils")

    def test_a_category_the_crosswalk_has_no_row_for_is_reported_not_dropped(self):
        fossils, metals = categories(artifact())
        self.assertIsNone(metals.slug)
        self.assertIsNone(metals.impact_category_id)

    def test_a_slug_two_methods_share_reaches_the_right_method(self):
        """#349: EF 3.1 and Stepwise 2006 both publish an `acidification`,
        counted in mol H+-eq from Accumulated Exceedance and in `m2 UES` from
        EDIP.  A vendor's EF row is about EF's, and a map keyed on the slug
        alone answered with whichever method was read last -- which scored
        ecoinvent's acidification against twelve EDIP factors instead of 935.
        """
        shared = [
            definition.slug
            for definition in impact_categories()
            if definition.method == "stepwise-2006"
            and definition.slug in {
                other.slug for other in impact_categories() if other.method == "ef"
            }
        ]
        self.assertIn("acidification", shared)
        ours = ArtifactCategory(
            "EF v3.1|acidification|accumulated exceedance (AE)", "EF v3.1",
            "acidification", "accumulated exceedance (AE)", "mol H+-Eq",
        )
        ids = {(d.method, d.slug): f"{d.method}-{d.slug}" for d in impact_categories()}
        (match,) = match_categories(
            [ours], by_stated_method_category(), consensus_ids=ids
        )
        self.assertEqual(match.slug, "acidification")
        self.assertEqual(match.method, "ef")
        self.assertEqual(match.impact_category_id, "ef-acidification")

    def test_ef31_spellings_match_too(self):
        cat = ArtifactCategory(
            "EF v3.1|photochemical oxidant formation: human health|x", "EF v3.1",
            "photochemical oxidant formation: human health", "x", "kg NMVOC-Eq",
        )
        old = ArtifactCategory(
            "EF v3.0|photochemical ozone formation: human health|x", "EF v3.0",
            "photochemical ozone formation: human health", "x", "kg NMVOC-Eq",
        )
        new, earlier = match_categories([cat, old], by_stated_method_category(), consensus_ids={})
        self.assertEqual(new.slug, earlier.slug)
        self.assertEqual(new.slug, "photochemical-ozone-formation-human-health")


class ReasonsTestCase(unittest.TestCase):
    """Every reason, on the #209 inventory."""

    def setUp(self):
        self.art = artifact()
        self.process = self.art.unit_processes[0]
        self.fossils = categories(self.art)[0]
        self.theirs = self.art.factors_by_category()[FOSSILS]

    def rows(self, *, ours, targets):
        out = contributions_for(
            self.process, self.fossils, their_factors=self.theirs, our_factors=ours, targets=targets,
        )
        return {row.source_flow_uuid: row for row in out}

    def test_the_factors_imported_as_unity_differ(self):
        targets = {u: _target(f"c-{u}") for u in (COAL, OIL, GAS)}
        rows = self.rows(ours={"c-s-coal": 1.0, "c-s-oil": 1.0, "c-s-gas": 1.0}, targets=targets)
        for flow in (COAL, OIL, GAS):
            self.assertIs(rows[flow].reason, ContributionReason.FACTOR_DIFFERS)
        self.assertAlmostEqual(rows[COAL].their_contribution, 0.00590783 * 18.0)
        self.assertAlmostEqual(rows[COAL].our_contribution, 0.00590783)
        self.assertAlmostEqual(rows[COAL].delta, 0.00590783 - 0.00590783 * 18.0)

    def test_a_flow_we_do_not_characterise(self):
        rows = self.rows(ours={}, targets={URANIUM: _target("c-uranium")})
        self.assertIs(rows[URANIUM].reason, ContributionReason.NO_CONSENSUS_FACTOR)
        self.assertEqual(rows[URANIUM].our_contribution, 0.0)
        self.assertIsNone(rows[URANIUM].our_factor)

    def test_a_flow_that_reached_no_consensus_flow(self):
        rows = self.rows(ours={}, targets={})
        self.assertIs(rows[PEAT].reason, ContributionReason.UNMAPPED_FLOW)
        self.assertIsNone(rows[PEAT].elementary_flow_uuid)
        # WATER has no factor of theirs under fossils and no target: nothing.
        self.assertNotIn(WATER, rows)

    def test_the_multiplier_goes_on_the_amount(self):
        """560,000 MJ/kg: theirs is per kg, ours is 1.0 per MJ, and they agree."""
        targets = {URANIUM: _target("c-uranium", source_unit="kilogram", target_unit="megajoule", multiplier=560000.0)}
        rows = self.rows(ours={"c-uranium": 1.0}, targets=targets)
        self.assertIs(rows[URANIUM].reason, ContributionReason.AGREE)
        self.assertAlmostEqual(rows[URANIUM].our_contribution, 6.0e-8 * 560000.0)
        self.assertEqual(rows[URANIUM].multiplier, 560000.0)

    def test_a_crossing_with_no_multiplier_applies_nothing(self):
        targets = {URANIUM: _target("c-uranium", source_unit="kilogram", target_unit="megajoule")}
        rows = self.rows(ours={"c-uranium": 1.0}, targets=targets)
        self.assertIs(rows[URANIUM].reason, ContributionReason.UNIT_CROSSING_UNCONVERTED)
        self.assertEqual(rows[URANIUM].our_contribution, 0.0)

    def test_a_factor_only_we_state(self):
        rows = self.rows(ours={"c-water": 5.0}, targets={WATER: _target("c-water")})
        self.assertIs(rows[WATER].reason, ContributionReason.ONLY_CONSENSUS_FACTOR)
        self.assertIsNone(rows[WATER].their_factor)
        self.assertAlmostEqual(rows[WATER].our_contribution, 0.6)

    def test_agreement_is_within_the_factor_tolerance(self):
        targets = {COAL: _target("c-coal")}
        self.assertIs(self.rows(ours={"c-coal": 18.0 * 1.01}, targets=targets)[COAL].reason,
                      ContributionReason.AGREE)
        self.assertIs(self.rows(ours={"c-coal": 18.0 * 1.05}, targets=targets)[COAL].reason,
                      ContributionReason.FACTOR_DIFFERS)

    def test_every_reason_has_a_case_above(self):
        """The list is closed; a new member needs a case."""
        self.assertEqual(
            {r for r in ContributionReason},
            {ContributionReason.AGREE, ContributionReason.FACTOR_DIFFERS,
             ContributionReason.NO_CONSENSUS_FACTOR, ContributionReason.UNMAPPED_FLOW,
             ContributionReason.UNIT_CROSSING_UNCONVERTED, ContributionReason.ONLY_CONSENSUS_FACTOR},
        )


class ReleaseComparisonTestCase(unittest.TestCase):
    def setUp(self):
        self.art = artifact()
        self.cats = categories(self.art)

    def test_the_issue_s_table(self):
        """#209: fossil factors at 1.0, uranium and peat absent -> 28x too low."""
        targets = {u: _target(f"c-{u}") for u in (COAL, OIL, GAS, URANIUM)}
        ours = {EF_FOSSILS: {"c-s-coal": 1.0, "c-s-oil": 1.0, "c-s-gas": 1.0}}
        result = compare_release(self.art, categories=self.cats, targets=targets, our_factors=ours)
        (comparison,) = result.comparisons
        self.assertEqual(comparison.category_key, FOSSILS)
        self.assertAlmostEqual(comparison.our_score, 0.00590783 + 0.00222268 + 0.00192141)
        self.assertLess(comparison.signed_ratio, 0.05)
        self.assertIs(comparison.band, Band.OVER_100X if comparison.signed_ratio < 0.01 else Band.UP_TO_100X)
        reasons = {row.source_flow_uuid: row.reason for row in result.contributions}
        self.assertEqual(reasons[URANIUM], ContributionReason.NO_CONSENSUS_FACTOR)
        self.assertEqual(reasons[PEAT], ContributionReason.UNMAPPED_FLOW)
        self.assertEqual(reasons[COAL], ContributionReason.FACTOR_DIFFERS)

    def test_the_unmatched_category_is_counted_and_not_scored(self):
        result = compare_release(self.art, categories=self.cats, targets={}, our_factors={})
        self.assertEqual(result.stats["their_categories_unmatched"], 1)
        self.assertEqual({c.category_key for c in result.comparisons}, {FOSSILS})

    def test_a_fully_unmapped_pair_says_so_through_unmapped_share(self):
        result = compare_release(self.art, categories=self.cats, targets={}, our_factors={})
        (comparison,) = result.comparisons
        self.assertEqual(comparison.our_score, 0.0)
        self.assertIs(comparison.band, Band.INCOMPARABLE)
        self.assertAlmostEqual(comparison.unmapped_share, 1.0)

    def test_priorities_sum_to_what_moved_and_rank_by_share(self):
        targets = {u: _target(f"c-{u}") for u in (COAL, OIL, GAS, URANIUM)}
        ours = {EF_FOSSILS: {"c-s-coal": 1.0, "c-s-oil": 1.0, "c-s-gas": 1.0}}
        result = compare_release(self.art, categories=self.cats, targets=targets, our_factors=ours)
        (comparison,) = result.comparisons
        total_delta = sum(p.abs_delta_sum for p in result.priorities)
        self.assertAlmostEqual(total_delta, abs(comparison.their_score - comparison.our_score))
        shares = [p.share_of_category for p in result.priorities]
        self.assertEqual(shares, sorted(shares, reverse=True))
        self.assertAlmostEqual(sum(shares), 1 - comparison.signed_ratio)
        top = result.priorities[0]
        self.assertEqual(top.source_flow_uuid, COAL)
        self.assertEqual(top.datasets_affected, 1)
        self.assertEqual(top.reason, ContributionReason.FACTOR_DIFFERS)

    def test_agreeing_small_contributions_are_counted_not_stored(self):
        targets = {u: _target(f"c-{u}") for u in (COAL, OIL, GAS, URANIUM, PEAT)}
        ours = {EF_FOSSILS: {
            "c-s-coal": 18.0, "c-s-oil": 42.3, "c-s-gas": 33.7, "c-s-uranium": 560000.0, "c-s-peat": 9.0,
        }}
        result = compare_release(self.art, categories=self.cats, targets=targets, our_factors=ours)
        (comparison,) = result.comparisons
        self.assertIs(comparison.band, Band.IDENTICAL)
        stored = {row.source_flow_uuid for row in result.contributions}
        self.assertNotIn(PEAT, stored)  # 9e-6 of 0.3
        self.assertIn(COAL, stored)
        self.assertEqual(result.stats["contributions_dropped_as_agreeing"], 1)
        self.assertEqual(result.stats["contributions_agree"], 5)
        self.assertEqual(result.stats["pairs_identical"], 1)
        self.assertEqual(result.stats["pairs_within_2x"], 1)

    def test_our_categories_nothing_reaches_are_counted(self):
        ours = {EF_FOSSILS: {}, ("ef", "water-use"): {}}
        result = compare_release(self.art, categories=self.cats, targets={}, our_factors=ours)
        self.assertEqual(result.stats["our_categories_unmatched"], 1)

    def test_unit_process_summary_counts_mapped_lines(self):
        result = compare_release(
            self.art, categories=self.cats, targets={COAL: _target("c-coal")}, our_factors={},
        )
        (summary,) = result.unit_processes
        self.assertEqual((summary.inventory_lines, summary.mapped_lines, summary.unmapped_lines), (6, 1, 5))
