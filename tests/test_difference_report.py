"""Two renderings of one method, compared factor by factor.

The headline is the agreement: over a full build of 2026-08-17 the JRC's
implementation of EF 3.1 and the ecoinvent Centre's agree **exactly** -- same
float, full precision -- on 21,800 of the 22,107 (flow, category, place) triples
they both state. 98.6%. That is what makes the other 307 readable as signal, and
it is not a number anybody could quote before, because until both are on one flow
list the triples cannot be formed.

Two things the report must get right, and both are here:

* a band is not a verdict. 307 differences between two competent teams are mostly
  modelling choices; the 20 over 100x are worth a conversation, not a correction.
  A difference across zero gets a band of its own because a relative difference
  there is not defined -- there are none today, which is worth knowing rather than
  assuming.
* the coverage report is a summary, not a list. Asked per (substance, category)
  over every flow it is 36,007 rows, mostly the two flow lists being different
  sizes; restricted to flows each implementation's own list has, 5,668. Neither is
  a thing to publish as a list of defects, because the JRC's largest populations
  are substances with no global-warming potential -- absence is the right answer
  and nobody should be asked to fill it in.
"""

from __future__ import annotations

import unittest

from brightway_flows.domain.lcia.records import StatedFactor, stated_category
from brightway_flows.domain.lcia.crosswalk import ef_method
from brightway_flows.lcia.differences import (
    Band,
    compare,
    coverage,
    only_stated_by,
)
from brightway_flows.lcia.matching import MatchedFactor

#: EF 3.1's three implementations, read from its method file rather than from an
#: enum: an implementation belongs to a method, and which three these are is what
#: `data/lcia-impact-categories.json` says.
_METHOD = ef_method()
JRC_IMPL = _METHOD.reference
ECOINVENT_IMPL = _METHOD.implementation("ecoinvent-centre")
CONSENSUS_IMPL = _METHOD.consensus
IMPLEMENTATION_NAMES = {row.name for row in _METHOD.implementations}

SLUG = "ecotoxicity-freshwater"

#: What "only one of them spoke" is counted under, built from the implementation
#: rather than from a constant per source list.
ONLY_JRC = only_stated_by(JRC_IMPL.name)
ONLY_JRC_ZERO = only_stated_by(JRC_IMPL.name, zero=True)
ONLY_ECOINVENT = only_stated_by(ECOINVENT_IMPL.name)


def _matched(amount, *, flow="cf-1", geography="", source=None):
    return MatchedFactor(
        elementary_flow_uuid=flow,
        factor=StatedFactor(
            category=stated_category(uuid="ef-m1", name="Ecotoxicity, freshwater"),
            flow_uuid="",
            amount=amount,
            geography=geography or None,
        ),
        source_flow_uuid=source,
    )


def _keyed(rows):
    return {
        (row.elementary_flow_uuid, SLUG, row.factor.geography or ""): row
        for row in rows
    }


def _compare(*, jrc=(), ecoinvent=(), consensus=None):
    """The two published implementations, as `compare` now takes them.

    A mapping keyed by implementation, so that comparing a third is passing a
    third entry rather than changing a signature.
    """
    return compare(
        method=_METHOD.slug,
        stated={
            JRC_IMPL: _keyed(jrc),
            ECOINVENT_IMPL: _keyed(ecoinvent),
        },
        consensus=consensus or {},
    )


def _amounts(row_group):
    """A difference's rows as {implementation: amount}."""
    return {row.implemented_by: row.amount for row in row_group}


class TheBandsTestCase(unittest.TestCase):
    def _band(self, left, right):
        rows, _counts = _compare(
            jrc=[_matched(left)], ecoinvent=[_matched(right, source="ei-1")]
        )
        return rows[0].band, rows[0].ratio

    def test_identical_is_identical(self):
        band, ratio = self._band(3.02, 3.02)
        self.assertEqual(band, Band.IDENTICAL)
        self.assertEqual(ratio, 1.0)

    def test_a_rounding_is_within_tolerance(self):
        """`0.000118` against `0.00011755`: one number written twice."""
        band, _ratio = self._band(0.000118, 0.00011755)
        self.assertEqual(band, Band.WITHIN_TOLERANCE)

    def test_the_bands_are_ranked_by_ratio(self):
        for left, right, expected in (
            (1.0, 1.5, Band.UP_TO_2X),
            (1.0, 5.0, Band.UP_TO_10X),
            (1.0, 50.0, Band.UP_TO_100X),
            (134.73, 53540.0, Band.OVER_100X),
        ):
            with self.subTest(f"{left} vs {right}"):
                band, ratio = self._band(left, right)
                self.assertEqual(band, expected)
                self.assertGreater(ratio, 1)

    def test_a_stated_zero_against_a_number_is_incomparable(self):
        """Not a ratio and not a rounding: two implementations disagreeing about
        whether the substance has an effect at all."""
        band, ratio = self._band(0.0, 0.5)
        self.assertEqual(band, Band.INCOMPARABLE)
        self.assertIsNone(ratio)

    def test_a_sign_change_is_incomparable(self):
        band, _ratio = self._band(-1.0, 1.0)
        self.assertEqual(band, Band.INCOMPARABLE)


class WhatTheReportHoldsTestCase(unittest.TestCase):
    def test_a_row_per_implementation_names_its_number_and_source(self):
        """Long form: one row per implementation, each carrying the band of the
        triple they share.  A column per implementation cannot hold a third, and
        every source list that ships factors is one."""
        rows, _counts = _compare(
            jrc=[_matched(134.73)], ecoinvent=[_matched(53540.0, source="ei-1")]
        )
        self.assertEqual(len(rows), 2)
        self.assertEqual(
            _amounts(rows),
            {
                JRC_IMPL.name: 134.73,
                ECOINVENT_IMPL.name: 53540.0,
            },
        )
        theirs = next(
            row for row in rows
            if row.implemented_by == ECOINVENT_IMPL.name
        )
        self.assertEqual(theirs.source_flow_uuid, "ei-1")
        self.assertEqual({row.category_slug for row in rows}, {SLUG})
        self.assertEqual({row.band for row in rows}, {Band.OVER_100X})

    def test_a_third_implementation_is_a_third_row_and_one_band(self):
        """The shape the two-column table could not hold: the band is the widest
        pair among them, and nobody has to pivot to read it."""
        rows, counts = compare(
            method=_METHOD.slug,
            stated={
                JRC_IMPL: _keyed([_matched(1.0)]),
                ECOINVENT_IMPL: _keyed([_matched(1.0, source="ei-1")]),
                CONSENSUS_IMPL: _keyed([_matched(50.0)]),
            },
            consensus={},
        )
        self.assertEqual(len(rows), 3)
        self.assertEqual({row.band for row in rows}, {Band.UP_TO_100X})
        self.assertEqual(counts["shared"], 1)

    def test_a_row_says_what_this_list_did_about_it(self):
        """A reader of one row should not have to join to find out whether we
        took a side."""
        key = ("cf-1", SLUG, "")
        rows, _counts = _compare(
            jrc=[_matched(3.02)],
            ecoinvent=[_matched(3.02, source="ei-1")],
            consensus={key: "agreed"},
        )
        self.assertEqual({row.derivation for row in rows}, {"agreed"})

    def test_a_contested_row_says_nothing_was_published(self):
        rows, _counts = _compare(
            jrc=[_matched(134.73)], ecoinvent=[_matched(53540.0, source="ei-1")]
        )
        self.assertEqual({row.derivation for row in rows}, {None})

    def test_only_one_side_is_counted_and_not_listed(self):
        """245,380 rows of "nobody disagreed, because nobody else spoke" is a
        fact about differently sized flow lists, not a difference."""
        rows, counts = _compare(
            jrc=[_matched(1.0), _matched(0.0, flow="cf-2")],
            ecoinvent=[_matched(9.9, flow="cf-3", source="ei-1")],
        )
        self.assertEqual(rows, [])
        self.assertEqual(counts[ONLY_JRC], 1)
        self.assertEqual(counts[ONLY_JRC_ZERO], 1)
        self.assertEqual(counts[ONLY_ECOINVENT], 1)
        self.assertEqual(counts["shared"], 0)
        self.assertEqual(counts["total"], 3)

    def test_a_stated_zero_is_counted_apart_from_a_number(self):
        """#47 kept the zeros because "assessed, and zero" is not "never
        assessed", and a report that lumped them would undo that."""
        _rows, counts = _compare(jrc=[_matched(0.0)])
        self.assertEqual(counts[ONLY_JRC_ZERO], 1)
        self.assertEqual(counts.get(ONLY_JRC, 0), 0)

    def test_the_count_is_named_after_whoever_spoke(self):
        """Not `jrc-only` and `ecoinvent-only` as constants: a third
        implementation would be compared and not counted, and nothing would say
        so."""
        _rows, counts = compare(
            method=_METHOD.slug,
            stated={CONSENSUS_IMPL: _keyed([_matched(1.0)])},
            consensus={},
        )
        self.assertEqual(counts[only_stated_by(CONSENSUS_IMPL.name)], 1)

    def test_two_places_are_two_comparisons(self):
        rows, _counts = _compare(
            jrc=[_matched(1.0, geography="ES-CA"), _matched(2.0, geography="YE")],
            ecoinvent=[
                _matched(1.0, geography="ES-CA", source="ei-1"),
                _matched(9.0, geography="YE", source="ei-1"),
            ],
        )
        self.assertEqual(
            sorted({(row.geography, row.band) for row in rows}),
            [("ES-CA", Band.IDENTICAL), ("YE", Band.UP_TO_10X)],
        )


class TheCoverageSummaryTestCase(unittest.TestCase):
    """Counts by compartment and category; never a list of flows."""

    FLOWS = {
        "cf-1": {
            "flow_object_id": "fo-1",
            "context_display": "Environmental → Ground → Agricultural",
            "deprecated": False,
        },
        "cf-2": {
            "flow_object_id": "fo-1",
            "context_display": "Environmental → Ground → Silvicultural",
            "deprecated": False,
        },
        "cf-3": {
            "flow_object_id": "fo-1",
            "context_display": "Environmental → Air → Long-term",
            "deprecated": False,
        },
        "cf-4": {
            "flow_object_id": "fo-1",
            "context_display": "Environmental → Water → Unknown",
            "deprecated": True,
        },
    }

    def _coverage(self, covered, own):
        return coverage(
            method=_METHOD.slug,
            characterised={(JRC_IMPL.name, SLUG, "fo-1"): covered},
            flows=self.FLOWS,
            own_flows={JRC_IMPL.name: own},
        )

    def test_a_skipped_sibling_is_counted_twice_once_per_dimension(self):
        rows, counts = self._coverage({"cf-1"}, {"cf-1", "cf-2"})
        self.assertEqual(counts[f"{_METHOD.slug}:{JRC_IMPL.name}"], 1)
        self.assertEqual(
            sorted((row.dimension, row.value, row.flows) for row in rows),
            [
                ("category", SLUG, 1),
                ("compartment", "Environmental → Ground → Silvicultural", 1),
            ],
        )

    def test_a_flow_the_implementation_does_not_have_is_not_a_gap(self):
        """30,339 of the 36,007 apparent gaps are this: an implementation cannot
        skip a flow its own list has never seen."""
        rows, counts = self._coverage({"cf-1"}, {"cf-1"})
        self.assertEqual(rows, [])
        self.assertEqual(counts["skipped_not_in_own_list"], 1)

    def test_a_long_term_compartment_is_not_a_gap(self):
        """EF has no long-term compartment by construction, so absence there is
        the right answer (§2.4)."""
        _rows, counts = self._coverage({"cf-1", "cf-2"}, {"cf-1", "cf-2", "cf-3"})
        self.assertEqual(counts["skipped_long_term"], 1)
        self.assertEqual(counts.get(f"{_METHOD.slug}:{JRC_IMPL.name}", 0), 0)

    def test_a_deprecated_flow_is_not_a_gap(self):
        """A withdrawn flow is not a place anybody should be characterising."""
        _rows, counts = self._coverage(
            {"cf-1", "cf-2"}, {"cf-1", "cf-2", "cf-3", "cf-4"}
        )
        self.assertEqual(counts.get(f"{_METHOD.slug}:{JRC_IMPL.name}", 0), 0)

    def test_nothing_names_a_flow(self):
        """The summary is where a reader finds the asymmetries; a 5,668-row list
        of them would read as a defect list whatever the prose said."""
        rows, _counts = self._coverage({"cf-1"}, {"cf-1", "cf-2"})
        self.assertTrue(all(row.value != "cf-2" for row in rows))
        self.assertEqual({row.dimension for row in rows}, {"category", "compartment"})


if __name__ == "__main__":
    unittest.main()
