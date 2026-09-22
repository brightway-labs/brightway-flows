"""The invariant `ElementaryFlow` declares and nothing checked.

Its docstring says ``(flow_object_id, context_iri)`` must be unique across
non-deprecated flows.  Those fields plus the unit are most of what
`pipeline/deduplication.py` signs on, so two live flows sharing them are two
flows one field away from collapsing -- and when they do, a lexicographic
identifier sort picks which keeps its identity.

That is #31: `Water to Cooling` and `Water to turbine` shared an object, a
context and a unit, were told apart only by a `general_comment` neither carried,
and the one holding 209 characterisation factors was deprecated onto the other.
An audit found it. This is the check that would have.

The check is also asked by the merge, of the flows it is about to write, which
is what #60 added: what a stage put there is the stage's own knowledge, so it
is passed in rather than read off a flow, and a group is attributed to whichever
stage it could not exist without.
"""

import unittest

from brightway_flows.domain.lcia.records import StatedFactor, stated_category
from brightway_flows.pipeline.collisions import (
    STAGE_MERGE,
    STAGE_TRANSFORM,
    find_collisions,
    report_collisions,
)
from brightway_flows.pipeline.review_records import ReviewQueue, Severity


class _Flow:
    """The fields the guard reads, and nothing else.

    `to_dict` because the item now says which fields are holding a pair apart,
    and that is answered by `deduplication.fields_holding_apart` reading the
    record the way deduplication itself signs it.
    """

    def __init__(
        self,
        elementary_flow_id,
        flow_object_id="fo-1",
        context_iri="ctx-1",
        unit="kg",
        deprecated=False,
        factors=0,
        factor_values=None,
        general_comment=None,
    ):
        self.elementary_flow_id = elementary_flow_id
        self.flow_object_id = flow_object_id
        self.context_iri = context_iri
        self.unit = unit
        self.owl_deprecated = True if deprecated else None
        self.general_comment = general_comment
        if factor_values is None:
            factor_values = {f"m{i}": 1.0 for i in range(factors)}
        self.lcia_methods = [
            StatedFactor(
                category=stated_category(uuid=name, name=name),
                flow_uuid=elementary_flow_id,
                amount=value,
            )
            for name, value in factor_values.items()
        ]

    def to_dict(self):
        return {
            "elementary_flow_id": self.elementary_flow_id,
            "flow_object_id": self.flow_object_id,
            "context_iri": self.context_iri,
            "unit": self.unit,
            "general_comment": self.general_comment,
            "lcia_methods": self.lcia_methods,
        }


class FindingThemTestCase(unittest.TestCase):
    def test_two_live_flows_on_one_key_collide(self):
        groups = find_collisions([_Flow("a"), _Flow("b")])
        self.assertEqual(len(groups), 1)
        self.assertEqual(len(groups[0]), 2)

    def test_a_different_unit_is_not_a_collision(self):
        """The unit is in the signature, so kg and m3 are two flows even of one
        substance in one context. EF ships exactly that for water vapour."""
        self.assertEqual(find_collisions([_Flow("a"), _Flow("b", unit="m3")]), [])

    def test_a_different_context_is_not_a_collision(self):
        self.assertEqual(find_collisions([_Flow("a"), _Flow("b", context_iri="ctx-2")]), [])

    def test_a_different_object_is_not_a_collision(self):
        """The whole of Stage 3: giving each material its own object is what
        stopped water colliding."""
        self.assertEqual(
            find_collisions([_Flow("a"), _Flow("b", flow_object_id="fo-2")]), []
        )

    def test_a_deprecated_flow_is_not_counted(self):
        """A deprecated flow *is* the record of a collision already resolved.
        Counting it again would report every resolution as an open problem."""
        self.assertEqual(find_collisions([_Flow("a"), _Flow("b", deprecated=True)]), [])

    def test_a_group_of_three_is_one_group(self):
        groups = find_collisions([_Flow("a"), _Flow("b"), _Flow("c")])
        self.assertEqual(len(groups), 1)
        self.assertEqual(len(groups[0]), 3)

    def test_an_unplaced_flow_is_not_paired_with_another(self):
        """Two flows with no context are not two flows in one context. Pairing
        them would be an invented finding, and the merge reports them already."""
        self.assertEqual(
            find_collisions([_Flow("a", context_iri=""), _Flow("b", context_iri="")]),
            [],
        )


class ReportingTestCase(unittest.TestCase):
    def test_a_clean_list_produces_no_items_and_a_zero(self):
        """The zero matters: a run_stats key that only appears when something is
        wrong cannot show the run it stopped being wrong."""
        counts, items = report_collisions([_Flow("a"), _Flow("b", unit="m3")])
        self.assertEqual(items, [])
        self.assertEqual(counts["collision_groups"], 0)
        self.assertEqual(counts["collision_flows"], 0)

    def test_a_collision_raises_one_item_for_the_group(self):
        _counts, items = report_collisions([_Flow("a"), _Flow("b")])
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].queue_name, ReviewQueue.ELEMENTARY_FLOW_COLLISION)
        self.assertEqual(items[0].severity, Severity.INFO)

    def test_the_item_names_which_flow_would_be_kept(self):
        """With nothing to choose between them, the identifier breaks the tie."""
        _counts, items = report_collisions([_Flow("zzz"), _Flow("aaa")])
        self.assertEqual(items[0].payload["deduplication_would_keep"], "aaa")

    def test_the_flow_holding_the_factors_is_named_over_the_lower_identifier(self):
        """The rule is factors first, identifier only to break a tie -- and the
        queue used to restate it as the identifier alone, which named the flow
        holding nothing on 26 of the 116 groups in the 2026-08-12 build."""
        _counts, items = report_collisions(
            [_Flow("zzz", factors=209), _Flow("aaa", factors=0)]
        )
        self.assertEqual(items[0].payload["deduplication_would_keep"], "zzz")

    def test_the_item_says_what_is_holding_the_pair_apart(self):
        """A curator's first question about a collision, and the only thing that
        decides whether it can ever collapse."""
        _counts, items = report_collisions(
            [_Flow("a", general_comment="from EF 3.1"), _Flow("b")]
        )
        self.assertEqual(items[0].payload["differing_fields"], ["general_comment"])

    def test_a_field_deduplication_does_not_sign_on_holds_nothing_apart(self):
        """`lcia_methods` is not in the signature: two flows differing only in
        their factors are duplicates and get collapsed. That is #31."""
        _counts, items = report_collisions(
            [_Flow("a", factors=209), _Flow("b", factors=0)]
        )
        self.assertEqual(items[0].payload["differing_fields"], [])

    def test_unequal_factor_counts_are_counted_separately(self):
        """The case that cost #31 its factors: the two flows do not carry the
        same characterisation, so collapsing them loses one side."""
        counts, _items = report_collisions(
            [_Flow("a", factors=209), _Flow("b", factors=0)]
        )
        self.assertEqual(counts["collision_with_unequal_factors"], 1)

    def test_equal_factor_counts_are_not(self):
        counts, _items = report_collisions(
            [_Flow("a", factors=209), _Flow("b", factors=209)]
        )
        self.assertEqual(counts["collision_with_unequal_factors"], 0)

    def test_the_item_key_is_the_collision_rather_than_a_flow(self):
        """Stable across runs, so a curator's decision survives the next build
        and the same collision does not reappear as a new row."""
        _counts, items = report_collisions([_Flow("a"), _Flow("b")])
        self.assertEqual(items[0].item_key, "fo-1|ctx-1|kg")

    def test_the_group_size_is_tallied(self):
        counts, _items = report_collisions([_Flow("a"), _Flow("b"), _Flow("c")])
        self.assertEqual(counts["collision_group_of_3"], 1)

    def test_the_object_label_reaches_the_title(self):
        _counts, items = report_collisions(
            [_Flow("a"), _Flow("b")], labels_by_object={"fo-1": "Cooling water"}
        )
        self.assertIn("Cooling water", items[0].title)


class DisagreeingFactorValuesTestCase(unittest.TestCase):
    """Not how many factors each side carries -- what they say.

    #281: six turpentine groups where both flows carry two factors and disagree
    about both. The count test cannot see any of them, and on the 2026-08-12
    build the two tests flag disjoint sets: 28 groups and 6, no overlap.
    """

    def test_two_flows_that_disagree_about_a_shared_factor_are_counted(self):
        counts, items = report_collisions([
            _Flow("a", factor_values={"Ecotoxicity, freshwater": 687.04}),
            _Flow("b", factor_values={"Ecotoxicity, freshwater": 256.29}),
        ])
        self.assertEqual(counts["collision_with_disagreeing_factor_values"], 1)
        payload = items[0].payload["factor_value_disagreement"]
        self.assertEqual(payload["method"], "Ecotoxicity, freshwater")
        self.assertEqual((payload["low"], payload["high"]), (256.29, 687.04))
        self.assertEqual(payload["comparable"], 1)
        self.assertAlmostEqual(payload["worst"], 687.04 / 256.29 - 1)

    def test_and_the_count_test_says_nothing_about_them(self):
        """Both sides carry one factor, so nothing is unequal about the counts.
        This is why the queue was silent on the only groups in the build whose
        numbers actually disagree."""
        counts, _items = report_collisions([
            _Flow("a", factor_values={"Ecotoxicity, freshwater": 687.04}),
            _Flow("b", factor_values={"Ecotoxicity, freshwater": 256.29}),
        ])
        self.assertEqual(counts["collision_with_unequal_factors"], 0)

    def test_a_rounding_difference_is_not_a_disagreement(self):
        """EF publishes one factor to different precision under two names --
        `5.5192e-08` and `5.52e-08`. Exact equality calls that a conflict, and
        it would have swamped this test: 42 of the 116 groups differ by 0.38% or
        less. `FACTOR_TOLERANCE` is the threshold this project already set."""
        counts, items = report_collisions([
            _Flow("a", factor_values={"Climate change": 5.5192e-08}),
            _Flow("b", factor_values={"Climate change": 5.52e-08}),
        ])
        self.assertEqual(counts["collision_with_disagreeing_factor_values"], 0)
        self.assertGreater(items[0].payload["factor_value_disagreement"]["worst"], 0)

    def test_a_method_only_one_side_publishes_is_not_a_comparison(self):
        """"There was nothing to compare" is not "these agree", which is what
        `comparable` separates."""
        counts, items = report_collisions([
            _Flow("a", factor_values={"Climate change": 7380.0}),
            _Flow("b", factor_values={"Ecotoxicity, freshwater": 0.02}),
        ])
        self.assertEqual(counts["collision_with_disagreeing_factor_values"], 0)
        self.assertIsNone(items[0].payload["factor_value_disagreement"])

    def test_a_group_carrying_no_factors_at_all_reports_none(self):
        _counts, items = report_collisions([_Flow("a"), _Flow("b")])
        self.assertIsNone(items[0].payload["factor_value_disagreement"])

    def test_agreement_is_recorded_as_agreement_rather_than_as_nothing(self):
        """`comparable` is what says the two were compared at all, which is the
        difference between "these agree" and "there was nothing to compare". Of
        the 116 groups, 30 agree exactly like this and 38 report nothing,
        because the two sides share no method."""
        _counts, items = report_collisions([
            _Flow("a", factor_values={"Climate change": 7380.0}),
            _Flow("b", factor_values={"Climate change": 7380.0}),
        ])
        payload = items[0].payload["factor_value_disagreement"]
        self.assertEqual(payload, {"worst": 0.0, "comparable": 1})


class TheCaseItWasWrittenForTestCase(unittest.TestCase):
    """#31, reconstructed: two water withdrawals that shared everything."""

    def test_the_255_pair_would_have_been_reported(self):
        before_stage_3 = [
            _Flow("21868f36", flow_object_id="fo-water", context_iri="reso-wate",
                  unit="m3", factors=209),
            _Flow("9575e5d0", flow_object_id="fo-water", context_iri="reso-wate",
                  unit="m3", factors=209),
            _Flow("37295016", flow_object_id="fo-water", context_iri="reso-wate",
                  unit="m3", factors=0),
        ]
        counts, items = report_collisions(before_stage_3)
        self.assertEqual(counts["collision_groups"], 1)
        self.assertEqual(counts["collision_flows"], 3)
        self.assertEqual(counts["collision_with_unequal_factors"], 1)
        # One of the two holding 209 factors, and the lower of their two
        # identifiers: here the old rule and the real one happen to agree.
        self.assertEqual(items[0].payload["deduplication_would_keep"], "21868f36")

    def test_and_after_stage_3_it_is_not(self):
        """Each material its own object, which is what the fix was."""
        after = [
            _Flow("21868f36", flow_object_id="fo-cooling", context_iri="reso-wate",
                  unit="m3", factors=209),
            _Flow("9575e5d0", flow_object_id="fo-turbine", context_iri="reso-wate",
                  unit="m3", factors=209),
            _Flow("37295016", flow_object_id="fo-brine", context_iri="reso-wate",
                  unit="m3", factors=0),
        ]
        counts, items = report_collisions(after)
        self.assertEqual(counts["collision_groups"], 0)
        self.assertEqual(items, [])


class WhichStagePutItThereTestCase(unittest.TestCase):
    """#60: the check ran in the transform, and the merge then added flows.

    The queue described 116 groups of a published 145. The 29 it never saw held
    190 flows the merge had minted onto a substance, context and unit another
    flow already occupied -- every one of them with no factors at all, and 12
    of the groups with nothing in them from a source list.
    """

    def test_a_group_that_needs_the_minted_flows_is_the_merges(self):
        counts, items = report_collisions(
            [_Flow("ef"), _Flow("minted")], minted_flow_ids=frozenset({"minted"})
        )
        self.assertEqual(items[0].payload["stage"], STAGE_MERGE)
        self.assertEqual(counts["collision_groups_from_merge"], 1)
        self.assertEqual(counts["collision_flows_minted_by_merge"], 1)

    def test_a_group_that_would_collide_anyway_is_not(self):
        """Two flows already sharing a place, and the merge added a third.

        The group is the transform's, still: what the merge did to it is make it
        bigger, which is a different finding from one it produced on its own.
        """
        counts, items = report_collisions(
            [_Flow("ef-1"), _Flow("ef-2"), _Flow("minted")],
            minted_flow_ids=frozenset({"minted"}),
        )
        self.assertEqual(items[0].payload["stage"], STAGE_TRANSFORM)
        self.assertEqual(counts["collision_groups_from_merge"], 0)
        self.assertEqual(counts["collision_groups_enlarged_by_merge"], 1)
        self.assertEqual(counts["collision_flows_minted_by_merge"], 1)

    def test_a_group_nothing_minted_is_the_transforms(self):
        _counts, items = report_collisions(
            [_Flow("a"), _Flow("b")], minted_flow_ids=frozenset({"elsewhere"})
        )
        self.assertEqual(items[0].payload["stage"], STAGE_TRANSFORM)
        self.assertEqual(items[0].payload["minted_by_merge"], [])

    def test_the_item_names_the_flows_that_were_minted(self):
        """The question is about those flows, so the row has to name them."""
        _counts, items = report_collisions(
            [_Flow("ef"), _Flow("m-1"), _Flow("m-2")],
            minted_flow_ids=frozenset({"m-1", "m-2"}),
        )
        self.assertEqual(items[0].payload["minted_by_merge"], ["m-1", "m-2"])
        self.assertIn("the merge minted 2", items[0].title)

    def test_a_minted_flow_makes_the_item_a_review(self):
        """`info` is "the pipeline made no change". Here it made one: it wrote a
        flow onto a place another flow already held."""
        _counts, items = report_collisions(
            [_Flow("ef"), _Flow("minted")], minted_flow_ids=frozenset({"minted"})
        )
        self.assertEqual(items[0].severity, Severity.REVIEW)

    def test_a_group_of_only_minted_flows_is_counted(self):
        """12 of the 29 held no base-list flow at all: nothing in the group has
        a number on it for the others to be read against."""
        counts, _items = report_collisions(
            [_Flow("m-1"), _Flow("m-2")], minted_flow_ids=frozenset({"m-1", "m-2"})
        )
        self.assertEqual(counts["collision_groups_entirely_minted"], 1)
        self.assertEqual(counts["collision_groups_without_factors"], 1)

    def test_minted_flows_without_factors_are_counted(self):
        """All 190 of them, which is the fact about the export nothing stated."""
        counts, _items = report_collisions(
            [_Flow("ef", factors=4), _Flow("m-1"), _Flow("m-2")],
            minted_flow_ids=frozenset({"m-1", "m-2"}),
        )
        self.assertEqual(counts["collision_minted_flows_without_factors"], 2)
        self.assertEqual(counts["collision_groups_without_factors"], 0)

    def test_the_merge_keys_are_published_at_zero(self):
        """A run that stops minting into an occupied place has to be as visible
        as the run that starts, so the keys are there with nothing to report --
        but only for a stage that could have minted something."""
        counts, _items = report_collisions([_Flow("a")], minted_flow_ids=frozenset())
        self.assertEqual(counts["collision_groups_from_merge"], 0)
        self.assertIn("collision_flows_minted_by_merge", counts)

    def test_the_transform_is_not_given_merge_keys_at_all(self):
        """It mints nothing, so a row saying it minted none is noise."""
        counts, _items = report_collisions([_Flow("a"), _Flow("b")])
        self.assertNotIn("collision_flows_minted_by_merge", counts)
        self.assertNotIn("collision_groups_from_merge", counts)

    def test_payloads_are_refused_outright(self):
        """Every field is read by attribute, so a dict answers nothing to all
        of them and a whole database reports as clean."""
        with self.assertRaises(TypeError):
            find_collisions([{"flow_object_id": "fo-1", "context_iri": "ctx-1"}])
