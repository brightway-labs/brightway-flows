"""A land class folded into another is a decision, or it stops the build.

The rule has two halves and the second is the one that decays. Refusing a fold
nobody recorded is the point; *not* refusing the folds that are recorded, and
not refusing a release that simply does not ship one of a fold's members, is
what keeps the first half from being switched off the next time a vendor drops
a flow. Both are tested here (#111).
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from brightway_flows.match_overrides import load_match_overrides
from brightway_flows.merge.land_groupings import (
    GROUPINGS_FILEPATH,
    LandGrouping,
    load_land_flow_groupings,
    unrecorded_land_groupings,
)
from brightway_flows.merge.report import AlgorithmMatch, PreparedMatch

OVERRIDES = (
    Path(__file__).parent.parent
    / "src/brightway_flows/data/ecoinvent-match-overrides.json"
)

LAND = ["Land Use", "Transformation"]
WATER = ["Environmental", "Water", "Surface water"]


def prepared(source_uuid: str, name: str, target: str, *, context=None) -> PreparedMatch:
    """One prepared match, with only the fields the grouping check reads set."""
    return PreparedMatch(
        source_uuid=source_uuid,
        source_name=name,
        source_context=["natural resource", "land"],
        source_context_iri="",
        source_unit="m2",
        source_cas="",
        target_elementary_flow_id=target,
        prepared_target_elementary_flow_id=target,
        target_flow_object_id="fo-1",
        target_name=f"target {target}",
        target_context=LAND if context is None else context,
        target_unit="m2",
        prepared_target_resolution="direct-active-target",
        prepared_target_trace=[target],
        prepared_context_decision="mapped",
        provenance={},
    )


def algorithmic(source_uuid: str, name: str, target: str) -> AlgorithmMatch:
    """The same, for a match the selector made rather than a curator."""
    return AlgorithmMatch(
        source_uuid=source_uuid,
        source_name=name,
        source_context=["natural resource", "land"],
        source_context_normalized=None,
        source_context_iri="",
        source_unit="m2",
        source_cas="",
        source_ec="",
        flow_object_id="fo-1",
        target_name=f"target {target}",
        target_elementary_flow_id=target,
        target_context=LAND,
        target_unit="m2",
        basis="label",
        basis_value="",
        selector_reason="",
        matching_method="label",
        algorithm_details={},
        provenance={},
    )


def grouping(target: str, *members: str) -> dict[tuple[str, str], LandGrouping]:
    from brightway_flows.merge.land_groupings import GroupedFlow

    return {
        ("ecoinvent", target): LandGrouping(
            list_name="ecoinvent",
            target_uuid=target,
            comment="because",
            target_name="Dump Site",
            absorbs=tuple(GroupedFlow(source_uuid=m) for m in members),
        )
    }


class AFoldNobodyRecordedStopsTheBuildTestCase(unittest.TestCase):
    def test_two_rows_on_one_land_flow_with_no_grouping_is_reported(self):
        problems = unrecorded_land_groupings(
            [prepared("a", "sanitary landfill", "dump"),
             prepared("b", "inert material landfill", "dump")],
            list_name="ecoinvent",
            recorded={},
        )
        self.assertEqual(len(problems), 1)
        self.assertIn("sanitary landfill", problems[0])
        self.assertIn("inert material landfill", problems[0])

    def test_a_fold_the_selector_made_is_reported_too(self):
        """A fold is a fold whether a curator's table made it or matching did."""
        problems = unrecorded_land_groupings(
            [algorithmic("a", "sanitary landfill", "dump"),
             algorithmic("b", "inert material landfill", "dump")],
            list_name="ecoinvent",
            recorded={},
        )
        self.assertEqual(len(problems), 1)

    def test_a_release_that_adds_a_member_reopens_the_decision(self):
        """The case the record exists for: a fold grows and nobody looked."""
        problems = unrecorded_land_groupings(
            [prepared("a", "unknown", "unspec"),
             prepared("b", "unspecified", "unspec"),
             prepared("c", "not stated", "unspec")],
            list_name="ecoinvent",
            recorded=grouping("unspec", "a", "b"),
        )
        self.assertEqual(len(problems), 1)
        self.assertIn("not stated", problems[0])
        self.assertNotIn("unknown", problems[0])


class TheRecordedFoldsAndTheOrdinaryCasesPassTestCase(unittest.TestCase):
    """The other half. Each of these firing would be a check nobody could keep."""

    def test_a_recorded_fold_is_accepted(self):
        self.assertEqual(
            unrecorded_land_groupings(
                [prepared("a", "unknown", "unspec"),
                 prepared("b", "unspecified", "unspec")],
                list_name="ecoinvent",
                recorded=grouping("unspec", "a", "b"),
            ),
            [],
        )

    def test_a_release_that_does_not_ship_a_member_is_not_a_new_decision(self):
        """A recorded member the release dropped leaves one row on the target,
        which is the release not carrying the flow rather than the fold
        changing -- the reading `match_overrides` takes of the same case."""
        self.assertEqual(
            unrecorded_land_groupings(
                [prepared("a", "unknown", "unspec")],
                list_name="ecoinvent",
                recorded=grouping("unspec", "a", "b"),
            ),
            [],
        )

    def test_one_row_on_a_flow_is_not_a_fold(self):
        self.assertEqual(
            unrecorded_land_groupings(
                [prepared("a", "sanitary landfill", "dump")],
                list_name="ecoinvent",
                recorded={},
            ),
            [],
        )

    def test_two_rows_on_one_flow_outside_the_land_dimension_are_not_asked_about(self):
        """This check is about land classes. Two rows of one substance meeting
        on a water flow is what the merge is for."""
        self.assertEqual(
            unrecorded_land_groupings(
                [prepared("a", "water", "wat", context=WATER),
                 prepared("b", "water, unspecified", "wat", context=WATER)],
                list_name="ecoinvent",
                recorded={},
            ),
            [],
        )

    def test_a_grouping_recorded_for_another_list_does_not_answer(self):
        """Lists do not agree to keep out of each other's uuid space, and a
        decision made about one list is not a decision about another (#241)."""
        problems = unrecorded_land_groupings(
            [prepared("a", "unknown", "unspec"),
             prepared("b", "unspecified", "unspec")],
            list_name="bafu",
            recorded=grouping("unspec", "a", "b"),
        )
        self.assertEqual(len(problems), 1)


class AMalformedGroupingRaisesTestCase(unittest.TestCase):
    """Rule 14: a malformed ruling raises. Never skip one."""

    def _load(self, payload) -> dict:
        """*payload* as the shipped file, loaded. The cache is cleared on both
        sides: it is keyed on nothing, so a fixture left in it would be served
        to every test after this one."""
        directory = Path(tempfile.mkdtemp())
        path = directory / GROUPINGS_FILEPATH.name
        path.write_text(json.dumps(payload))
        with mock.patch(
            "brightway_flows.merge.land_groupings.GROUPINGS_FILEPATH", path
        ):
            load_land_flow_groupings.cache_clear()
            try:
                return load_land_flow_groupings()
            finally:
                load_land_flow_groupings.cache_clear()

    def test_a_grouping_of_one_is_refused(self):
        with self.assertRaises(ValueError) as caught:
            self._load({"groupings": [{
                "list_name": "ecoinvent", "target_uuid": "t", "comment": "c",
                "absorbs": [{"source_uuid": "a"}],
            }]})
        self.assertIn("Two or more", str(caught.exception))

    def test_a_grouping_with_no_reason_is_refused(self):
        with self.assertRaises(ValueError) as caught:
            self._load({"groupings": [{
                "list_name": "ecoinvent", "target_uuid": "t",
                "absorbs": [{"source_uuid": "a"}, {"source_uuid": "b"}],
            }]})
        self.assertIn("comment", str(caught.exception))

    def test_one_target_decided_twice_is_refused(self):
        row = {
            "list_name": "ecoinvent", "target_uuid": "t", "comment": "c",
            "absorbs": [{"source_uuid": "a"}, {"source_uuid": "b"}],
        }
        with self.assertRaises(ValueError) as caught:
            self._load({"groupings": [row, dict(row)]})
        self.assertIn("twice", str(caught.exception))

    def test_a_member_with_no_uuid_is_refused(self):
        with self.assertRaises(ValueError) as caught:
            self._load({"groupings": [{
                "list_name": "ecoinvent", "target_uuid": "t", "comment": "c",
                "absorbs": [{"source_name": "unknown"}, {"source_uuid": "b"}],
            }]})
        self.assertIn("source_uuid", str(caught.exception))

    def test_a_payload_with_no_groupings_list_is_refused(self):
        with self.assertRaises(ValueError):
            self._load({"decisions": []})


class TheShippedFileSaysWhatItClaimsTestCase(unittest.TestCase):
    def test_it_loads(self):
        load_land_flow_groupings.cache_clear()
        self.assertTrue(load_land_flow_groupings())

    def test_no_flow_is_both_declined_and_recorded_as_folded(self):
        """The two answers to one question, and a flow may have only one. A
        declined flow is published under its own name; a folded one is published
        as its target. A uuid in both files would mean the file that lost the
        race decided."""
        declined = {
            override.source_uuid
            for override in load_match_overrides(OVERRIDES)
            if override.decline
        }
        load_land_flow_groupings.cache_clear()
        folded = {
            member.source_uuid
            for group in load_land_flow_groupings().values()
            for member in group.absorbs
        }
        self.assertEqual(sorted(declined & folded), [])

    def test_every_recorded_target_is_named(self):
        """`target_name` is read by nobody and is why the file can be reviewed:
        a row of five uuids says nothing to the person checking it."""
        load_land_flow_groupings.cache_clear()
        for key, group in load_land_flow_groupings().items():
            with self.subTest(key):
                self.assertTrue(group.target_name)
                for member in group.absorbs:
                    self.assertTrue(member.source_name)


if __name__ == "__main__":
    unittest.main()
