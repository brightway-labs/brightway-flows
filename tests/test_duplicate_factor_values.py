"""Two duplicate rows publishing one factor, and which number survives (#63).

Deduplication does not sign on the characterisation factors, so two rows saying
`0.000118` and `0.00011755` for one method are duplicates.  It keeps the row
holding more factors and breaks the tie on the identifier, and the number the
kept row happens to hold is then what the list publishes -- chosen by a sort
that never looked at it.  Over the 130 collapses of the 2026-08-12 build, 68
factors are published twice with different numbers, and 66 of those differ by
far more than rounding, by up to 400 times.

These assert the three things a sort cannot do: prefer the number written to
more digits where the two are one number, keep the number it did not publish
where a reader can find it, and say out loud when the gap is too wide to be
rounding at all.
"""

from __future__ import annotations

import unittest

from brightway_flows.domain.context_registry import context_from_dict
from brightway_flows.domain.elementary_flow import ElementaryFlow
from brightway_flows.domain.flow import Flow
from brightway_flows.domain.lcia.records import StatedFactor, stated_category
from brightway_flows.pipeline.deduplication import (
    _apply_elementary_duplicate_deprecations,
    settle_factor_values,
)


def _row(uuid, factors, general_comment=None):
    return ElementaryFlow(
        elementary_flow_id=uuid,
        flow_object_id="fo-1",
        source="EF 3.1",
        context=context_from_dict(
            {"dimension": "Environmental", "media": "Air", "strata": "Unknown"}
        ),
        context_iri="ctx-1",
        unit="kg",
        unit_iri=None,
        lcia_methods=[
            StatedFactor(
                category=stated_category(uuid=method, name=method),
                flow_uuid=uuid,
                amount=value,
            )
            for method, value in factors
        ],
        general_comment=general_comment,
    )


def _factor(row, method="ecotox"):
    return next(m for m in row.lcia_methods if m.category.uuid == method)


class SettlingTwoNumbersTestCase(unittest.TestCase):
    """`settle_factor_values` on its own, which is what both merge paths call."""

    def _settle(self, kept, dropped):
        self.survivor = _row("keeps", [("ecotox", kept)])
        self.dropped = _row("goes", [("ecotox", dropped)])
        return settle_factor_values(
            survivor=self.survivor,
            dropped=self.dropped,
            generated_by="pipeline.deduplication",
        )

    def test_the_precise_number_replaces_the_rounded_one(self):
        """EF's refrigerant: `0.000118` is `0.00011755` rounded to three."""
        counts = self._settle(0.000118, 0.00011755)
        self.assertEqual(counts["factors_made_precise"], 1)
        self.assertEqual(_factor(self.survivor).amount, 0.00011755)

    def test_the_rounded_number_does_not_replace_the_precise_one(self):
        counts = self._settle(0.00011755, 0.000118)
        self.assertEqual(counts["factors_made_precise"], 0)
        self.assertEqual(_factor(self.survivor).amount, 0.00011755)

    def test_the_number_not_published_is_recorded_on_the_one_that_was(self):
        self._settle(0.000118, 0.00011755)
        superseded = _factor(self.survivor).superseded_values
        self.assertEqual([row.amount for row in superseded], [0.000118])
        self.assertAlmostEqual(
            superseded[0].relative_difference, 0.000118 / 0.00011755 - 1
        )

    def test_the_declined_number_says_which_flow_published_it(self):
        self._settle(0.000118, 0.00011755)
        provenance = _factor(self.survivor).superseded_values[0].provenance
        self.assertEqual(provenance.had_primary_source, ["urn:uuid:keeps"])
        self.assertEqual(provenance.was_generated_by, "pipeline.deduplication")

    def test_a_replaced_number_says_where_it_came_from(self):
        self._settle(0.000118, 0.00011755)
        self.assertEqual(
            _factor(self.survivor).provenance.had_primary_source, ["urn:uuid:goes"]
        )

    def test_two_numbers_neither_of_which_is_the_other_rounded_change_nothing(self):
        """Nothing here adjudicates between two numbers.  The survivor's stands
        because it is the survivor's, and the other is recorded."""
        counts = self._settle(1.23e-05, 1.24e-05)
        self.assertEqual(counts["factors_made_precise"], 0)
        self.assertEqual(counts["factor_values_differ"], 1)
        self.assertEqual(_factor(self.survivor).amount, 1.23e-05)

    def test_agreement_leaves_no_trace(self):
        counts = self._settle(34.3, 34.3)
        self.assertEqual(counts["factor_values_differ"], 0)
        self.assertEqual(_factor(self.survivor).superseded_values, [])

    def test_a_gap_too_wide_to_be_rounding_is_reported(self):
        """134.73 against 53540 is not one number written twice, and 24 of the
        2026-08-12 build's collapses look like this."""
        counts = self._settle(134.73, 53540.0)
        self.assertEqual(counts["factor_values_conflict"], 1)
        self.assertEqual(counts["factors_made_precise"], 0)

    def test_a_rounding_difference_is_not_reported_as_a_conflict(self):
        self.assertEqual(self._settle(0.000118, 0.00011755)["factor_values_conflict"], 0)

    def test_a_stated_zero_against_a_number_is_a_conflict(self):
        """A relative difference is not defined across zero, and a row saying
        `0` against one saying `0.5` is not a rounding of anything."""
        counts = self._settle(0.0, 0.5)
        self.assertEqual(counts["factor_values_conflict"], 1)
        self.assertIsNone(
            _factor(self.survivor).superseded_values[0].relative_difference
        )

    def test_a_factor_only_the_dropped_row_holds_is_left_alone(self):
        """Whose characterisation applies to this flow is the question a curator
        answers in `collision_decisions`; nothing here unions a factor set."""
        survivor = _row("keeps", [("ecotox", 1.0)])
        dropped = _row("goes", [("ecotox", 1.0), ("gwp", 9220.0)])
        counts = settle_factor_values(
            survivor=survivor, dropped=dropped, generated_by="pipeline.deduplication"
        )
        self.assertEqual(counts, {})
        self.assertEqual(
            [m.category.uuid for m in survivor.lcia_methods], ["ecotox"]
        )


class TheDuplicatePassSettlesTestCase(unittest.TestCase):
    """The same, reached the way the pipeline reaches it."""

    def _collapse(self, first, second):
        # Identical in every signed-on field, so the two are duplicates and the
        # identifier is all that ranks them.
        self.low = _row("aaaa", [("ecotox", first)])
        self.high = _row("bbbb", [("ecotox", second)])
        stats = _apply_elementary_duplicate_deprecations(
            flows=[Flow(uuid="aaaa", name="a", source="EF 3.1"),
                   Flow(uuid="bbbb", name="b", source="EF 3.1")],
            elementary_flows=[self.low, self.high],
        )
        return stats

    def test_the_pair_still_collapses(self):
        stats = self._collapse(0.000118, 0.00011755)
        self.assertEqual(stats["duplicate_elementary_group_count"], 1)
        self.assertEqual(stats["deprecated_elementary_flow_count"], 1)
        self.assertTrue(self.high.owl_deprecated)
        self.assertIsNone(self.low.owl_deprecated)

    def test_the_survivor_publishes_the_precise_number_the_dropped_row_held(self):
        """The identifier sort keeps `aaaa`, which holds the rounded number.
        That is the coin flip: on the 2026-08-12 build it lands the wrong way
        70 times out of 152."""
        stats = self._collapse(0.000118, 0.00011755)
        self.assertEqual(stats["duplicate_factors_made_precise"], 1)
        self.assertEqual(_factor(self.low).amount, 0.00011755)

    def test_the_counts_reach_the_run_stats_under_their_own_names(self):
        """A number that moves between runs is the signal, and a conflict
        settled by deduplication is not the same event as one settled by a
        curator's ruling."""
        stats = self._collapse(134.73, 53540.0)
        self.assertEqual(stats["duplicate_factor_values_differ"], 1)
        self.assertEqual(stats["duplicate_factor_values_conflict"], 1)

    def test_a_group_that_agrees_reports_nothing(self):
        stats = self._collapse(34.3, 34.3)
        self.assertEqual(stats["duplicate_elementary_group_count"], 1)
        self.assertNotIn("duplicate_factor_values_differ", stats)

    def test_the_harmonised_flow_states_the_number_the_elementary_row_does(self):
        """The two records share the factor row, so settling it in place is
        what keeps `harmonised-flows.json` and `elementary-flows.json` from
        publishing one factor at two values."""
        low = _row("aaaa", [("ecotox", 0.000118)])
        high = _row("bbbb", [("ecotox", 0.00011755)])
        harmonised = Flow(uuid="aaaa", name="a", source="EF 3.1")
        harmonised.lcia_methods = low.lcia_methods
        _apply_elementary_duplicate_deprecations(
            flows=[harmonised, Flow(uuid="bbbb", name="b", source="EF 3.1")],
            elementary_flows=[low, high],
        )
        self.assertEqual(harmonised.lcia_methods[0].amount, 0.00011755)


class ADeprecationAlreadyMadeTestCase(unittest.TestCase):
    """A settled duplication is not a duplication to settle again (#73).

    The signature excludes the deprecation fields, so a deprecated row and the
    row it points at are identical to this pass, and the sort would then choose
    between them -- reversing a curated ruling whenever the sort disagrees with
    it.  EF's `Energy, geothermal, converted` and `primary energy from
    geothermics` are that case: no factors, and no other signed-on field to tell
    them apart once the layering has moved their names onto the object they
    share, so the ruling deprecated the legacy row onto the survivor and this
    pass deprecated the survivor back onto the legacy row.  Each then pointed at
    the other and ecoinvent's mapping resolved to neither.
    """

    def setUp(self):
        self.survivor = _row("c0060563", [])
        self.ruled_out = _row("04202046", [])
        self.ruled_out.owl_deprecated = True
        self.ruled_out.dcterms_is_replaced_by = "urn:uuid:c0060563"
        self.ruled_out.is_replaced_by_uuid = "c0060563"
        self.stats = _apply_elementary_duplicate_deprecations(
            flows=[
                Flow(uuid="c0060563", name="a", source="EF 3.1"),
                Flow(uuid="04202046", name="b", source="EF 3.1"),
            ],
            elementary_flows=[self.survivor, self.ruled_out],
        )

    def test_the_surviving_row_stays_live(self):
        self.assertIsNone(self.survivor.owl_deprecated)
        self.assertEqual(self.stats["deprecated_elementary_flow_count"], 0)
        self.assertEqual(self.stats["duplicate_elementary_group_count"], 0)

    def test_the_deprecated_row_still_points_where_it_was_pointed(self):
        self.assertEqual(self.ruled_out.is_replaced_by_uuid, "c0060563")

    def test_two_live_rows_that_agree_still_collapse(self):
        """The pass is not switched off by the guard -- only rows already
        settled are skipped."""
        first = _row("aaaa", [])
        second = _row("bbbb", [])
        stats = _apply_elementary_duplicate_deprecations(
            flows=[
                Flow(uuid="aaaa", name="a", source="EF 3.1"),
                Flow(uuid="bbbb", name="b", source="EF 3.1"),
            ],
            elementary_flows=[first, second],
        )
        self.assertEqual(stats["deprecated_elementary_flow_count"], 1)
        self.assertTrue(second.owl_deprecated)


if __name__ == "__main__":
    unittest.main()
