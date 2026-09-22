"""A match is only made if it is written where the pass publishes from.

The merge keeps two views of the flows it loaded.  `elementary_by_object` holds
the rows as they came out of the database, and `merged_elementary` -- the list
the writers walk -- holds deep copies of them.  The split is deliberate:
matching reads its candidates from the index, so a candidate must not grow the
source refs of the flow being matched against it while the match is still being
decided.

The cost of the split is that a *chosen* target has to be turned back into the
copy before anything is appended to it.  `record_algorithmic_match` does that --
it takes the id off the selected candidate and looks it up in `by_elem_id` --
and the prepared route's `source-context-target` branch did not.  So 427 rows
were matched correctly, had their source reference and concept association
written to a record no writer reads, and were published with no mapping at all:
425 of ecoinvent 3.8, taking most of `water / ground-`, `soil / industrial` and
`soil / forestry` with them, and 2 of ecoinvent 3.12 (#321, #115).

Every test in `test_prepared_match_context` builds its accumulator with
`add_flow`, which puts one object in both collections -- so the bug was
invisible to all of them, and the rows that survived it in the real build were
exactly those whose target had been created during the same pass.  These tests
build the accumulator the way a pass does, out of loaded flows.
"""

import unittest

from brightway_flows.merge.matching import build_merge_accumulator
from brightway_flows.merge.state import MergeAccumulator

from test_prepared_match_context import (
    GROUNDWATER,
    SURFACE_WATER,
    _apply,
    _flow,
    _row,
)


def _zinc_rows():
    """One substance in two compartments, as the database hands them over.

    The prepared table names the surface-water flow; the row says groundwater,
    which the target denies, so the branch under test moves it onto the
    groundwater flow of the same substance.
    """
    return [
        _flow("ef-fresh", "fo-zinc", SURFACE_WATER),
        _flow("bafu-zinc", "fo-zinc", GROUNDWATER),
    ]


def _published(accumulator, elementary_flow_id):
    """The record the writers will read for *elementary_flow_id*."""
    return next(
        flow
        for flow in accumulator.merged_elementary
        if flow.elementary_flow_id == elementary_flow_id
    )


class LoadedTargetTestCase(unittest.TestCase):
    """The half that was broken: the target was already in the database."""

    def test_the_mapping_is_written_to_the_record_the_pass_publishes(self):
        """#115's defect, at the function that caused it.

        The match itself was never in doubt -- `merge_outcomes` recorded all
        425 of them -- so asserting that the row matched proves nothing.  What
        has to be asserted is that the mapping is on the record that gets
        written, which is the copy in `merged_elementary`.
        """
        accumulator = build_merge_accumulator(_zinc_rows())

        self.assertTrue(
            _apply(_row(name="Zinc", context=("water", "ground-")), "ef-fresh", accumulator)
        )

        (match,) = accumulator.prepared_matches
        self.assertEqual(match.prepared_target_resolution, "source-context-target")
        self.assertEqual(match.target_elementary_flow_id, "bafu-zinc")

        published = _published(accumulator, "bafu-zinc")
        self.assertEqual(len(published.concept_associations or []), 1)
        self.assertEqual(len(published.source_refs or []), 1)

    def test_the_row_the_index_handed_over_is_not_the_one_written_to(self):
        """Why the fix is a lookup and not "append to both".

        Writing to the candidate as well would put the mapping on a record the
        next match reads as evidence, which is the thing the deep copy exists
        to prevent.  The mapping belongs on the copy and nowhere else.
        """
        loaded = _zinc_rows()
        accumulator = build_merge_accumulator(loaded)

        _apply(_row(name="Zinc", context=("water", "ground-")), "ef-fresh", accumulator)

        candidate = accumulator.elementary_by_object["fo-zinc"][1]
        self.assertIs(candidate, loaded[1])
        self.assertEqual(len(candidate.concept_associations or []), 0)
        self.assertEqual(len(candidate.source_refs or []), 0)

    def test_the_flow_the_table_named_gains_nothing(self):
        """The row moved off it, so it must not keep a mapping to it.

        The failure this guards against is a fix that appends to the resolved
        target while leaving the earlier append on the table's target in place,
        which would publish the row twice.
        """
        accumulator = build_merge_accumulator(_zinc_rows())

        _apply(_row(name="Zinc", context=("water", "ground-")), "ef-fresh", accumulator)

        named = _published(accumulator, "ef-fresh")
        self.assertEqual(len(named.concept_associations or []), 0)
        self.assertEqual(len(named.source_refs or []), 0)


class TargetCreatedInThisPassTestCase(unittest.TestCase):
    """The half that already worked, and has to go on working.

    `add_flow` puts one object in the index and in `merged_elementary`, so a
    target created during the pass was written to correctly all along -- which
    is why 15 of ecoinvent 3.12's 17 `source-context-target` rows survived and 2
    did not.  A fix that resolves through `by_elem_id` must not lose these.
    """

    def test_a_target_added_in_this_pass_still_gets_its_mapping(self):
        accumulator = MergeAccumulator()
        accumulator.add_flow(_flow("ef-fresh", "fo-zinc", SURFACE_WATER))
        accumulator.add_flow(_flow("bafu-zinc", "fo-zinc", GROUNDWATER))

        self.assertTrue(
            _apply(_row(name="Zinc", context=("water", "ground-")), "ef-fresh", accumulator)
        )

        published = _published(accumulator, "bafu-zinc")
        self.assertEqual(len(published.concept_associations or []), 1)
        self.assertEqual(len(published.source_refs or []), 1)


class DirectTargetTestCase(unittest.TestCase):
    """The route the other 11,504 prepared rows take, from loaded flows.

    `direct-active-target` reads its target from `by_elem_id`, which is already
    the copy, so it was never affected.  Tested from a loaded accumulator
    anyway: it is the branch immediately beside the one being changed, and
    nothing else in the suite exercises it this way.
    """

    def test_a_direct_target_is_written_to_the_published_record(self):
        accumulator = build_merge_accumulator([
            _flow("bafu-zinc", "fo-zinc", GROUNDWATER),
        ])

        self.assertTrue(
            _apply(_row(name="Zinc", context=("water", "ground-")), "bafu-zinc", accumulator)
        )

        (match,) = accumulator.prepared_matches
        self.assertEqual(match.prepared_target_resolution, "direct-active-target")
        published = _published(accumulator, "bafu-zinc")
        self.assertEqual(len(published.concept_associations or []), 1)
        self.assertEqual(len(published.source_refs or []), 1)


if __name__ == "__main__":
    unittest.main()
