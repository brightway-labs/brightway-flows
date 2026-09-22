"""A version number in the description field is not a description.

EF 3.1 writes `01.00.000` into `common:generalComment` on 514 flows and
`03.01.000` on 53 more.  Neither is the version of the flow it sits on -- every
one of those rows declares `dataSetVersion` `01.00.004` -- and neither says
anything about the substance, where it was released, or how it differs from any
other row.

It matters because a description is one of the fields deduplication compares.
`01.00.000` on one row and nothing on its twin is a difference, so the pipeline
publishes two live flows for one substance in one context and unit.  116 such
pairs are in the 2026-08-12 build, and 90 are held apart by this string alone
(#62).

What is pinned here is the rule and its edges: the whole string, not a version
number inside a sentence, and not a comment that merely begins with one.
"""

import unittest

from brightway_flows.integrations.ef31 import flow_general_comment


class VersionOnlyCommentsTestCase(unittest.TestCase):
    def test_the_two_versions_ef_ships_are_read_as_no_comment(self):
        self.assertIsNone(flow_general_comment("01.00.000"))
        self.assertIsNone(flow_general_comment("03.01.000"))

    def test_a_version_ef_has_not_shipped_yet_is_read_the_same_way(self):
        """The rule is the shape, not the two values in this release. EF
        bumping to `01.00.001` would otherwise put all 90 pairs back."""
        self.assertIsNone(flow_general_comment("02.07.013"))

    def test_surrounding_whitespace_does_not_make_it_a_description(self):
        self.assertIsNone(flow_general_comment("  01.00.000\n"))

    def test_the_ilcd_boilerplate_is_still_read_as_no_comment(self):
        """Read this way since the extractor was written: it is on thousands of
        flows, identical on every one, and about the list rather than the flow."""
        self.assertIsNone(flow_general_comment(
            "Reference elementary flow of the International Reference Life "
            "Cycle Data System (ILCD)."
        ))

    def test_no_comment_stays_no_comment(self):
        self.assertIsNone(flow_general_comment(None))


class WhatIsStillADescriptionTestCase(unittest.TestCase):
    """The rule has to keep prose, including prose about versions."""

    def test_a_real_note_survives(self):
        comment = (
            "Correct mapping CAS and flow to be verified, potentially wrong. "
            "Note that the CAS No is that of the anhydrous form."
        )
        self.assertEqual(flow_general_comment(comment), comment)

    def test_a_version_inside_a_sentence_is_a_sentence(self):
        """Anchored deliberately. No comment in EF 3.1 contains a version-shaped
        substring -- all 84 distinct comments were read -- but a rule that
        matched anywhere would delete a real note the day one does."""
        comment = "Factor corrected in 01.00.000; see the release notes."
        self.assertEqual(flow_general_comment(comment), comment)

    def test_something_merely_version_shaped_is_not_stripped_loosely(self):
        """Three groups of digits in the published shape, and nothing else."""
        for value in ("1.0.0", "01.00", "01.00.0000", "v01.00.000", "01.00.000 kg"):
            with self.subTest(value=value):
                self.assertEqual(flow_general_comment(value), value)
