"""Stepwise 2006 refuses nine rows, and the file that says so has to keep working.

An `excluded` record is keyed on the vendor's uuid, and the whole failure mode of
the shape is an exclusion that quietly applies to nothing -- a uuid that no row
carries removes no row, raises nothing, and reads in review exactly like one that
does its job.  Stepwise derives its identifiers from `(name, compartment,
subcompartment, unit)` rather than shipping them, which means the nine can be
checked without the vendor's file: the identifier is a function of the four
fields the record already carries for the reader's sake, so recomputing it says
whether the record names the row it claims to.

Six are the `Chlordane, gamma-` flows of #167.  Gamma-chlordane is not a
substance an inventory reports: the name means trans-chlordane, which Stepwise
ships in the same compartments with the same factors, and the registry number on
the row belongs to a different compound that nobody inventories.

Three are the injury counts of #173 -- fatal injuries, non-fatal injuries at
work, non-fatal road injuries -- measured in persons and filed under a `Social`
compartment.  They are refused for a different reason: not that the row is
wrong, but that a count of people hurt is not an environmental flow, and this
list is a list of those.
"""

from __future__ import annotations

import unittest

from brightway_flows.additional_flows import (
    apply_additional_flows,
    load_excluded_source_flows,
)
from brightway_flows.integrations.stepwise import _flow_uuid
from brightway_flows.sources import excluded_source_flows, known_source_lists

_KEY = "stepwise-2006-1.09"
_SCHEME = "stepwise-2006-1.09"


def _stepwise():
    return known_source_lists()[_KEY]


class StepwiseExclusionsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.source = _stepwise()
        self.path = self.source.additional_flows_path
        self.assertIsNotNone(
            self.path,
            "The Stepwise manifest has to name its additional-flows file, or the "
            "exclusions are read by nothing.",
        )
        self.records = load_excluded_source_flows(
            self.path, source=self.source.source_label
        )

    def test_the_six_gamma_rows_are_what_is_refused(self) -> None:
        gamma = [r for r in self.records if r.name == "Chlordane, gamma-"]
        self.assertEqual(len(gamma), 6)
        self.assertEqual(
            {record.context for record in gamma},
            {
                ("Air", "(unspecified)"),
                ("Soil", "(unspecified)"),
                ("Soil", "agricultural"),
                ("Water", "(unspecified)"),
                ("Water", "groundwater"),
                ("Water", "groundwater, long-term"),
            },
        )

    def test_the_three_injury_rows_are_what_else_is_refused(self) -> None:
        # #173.  All three are in the one compartment, and all three are
        # counted in persons -- which is the first thing that says they are a
        # different kind of thing from every other row this project merges.
        injuries = [r for r in self.records if r.name.startswith("Injuries")]
        self.assertEqual(
            {record.name for record in injuries},
            {
                "Injuries, fatal",
                "Injuries, non-fatal, at work",
                "Injuries, non-fatal, road",
            },
        )
        for record in injuries:
            with self.subTest(record.name):
                self.assertEqual(record.context, ("Social", "(unspecified)"))
                self.assertEqual(record.unit, "p")

    def test_nine_rows_are_refused_and_no_more(self) -> None:
        self.assertEqual(len(self.records), 9)

    def test_every_record_names_the_row_it_claims_to(self) -> None:
        # The check the shape exists for.  A uuid no row carries removes no row
        # and says nothing about it: the exclusion would read as a decision and
        # act as a typo.  Stepwise derives its identifiers, so the record's own
        # four fields have to reproduce the one it is keyed on.
        for record in self.records:
            compartment, subcompartment = record.context
            self.assertEqual(
                _flow_uuid(record.name, compartment, subcompartment, record.unit),
                record.uuid,
                f"{record.name} in {record.context} is not {record.uuid}",
            )

    def test_nothing_was_withdrawn(self) -> None:
        # Stepwise is merged in no build of `main` -- the shared build of
        # 505ba28 merges ecoinvent 3.12, ecoinvent 3.8 and BAFU -- so neither
        # the gamma rows nor the injury rows minted a consensus identifier a
        # consumer could hold.  A `withdrew_identifier` here would be a
        # redirect published for a flow that was never published.
        for record in self.records:
            self.assertEqual(record.withdrew_identifier, "")

    def test_the_exclusions_have_somewhere_to_be_published(self) -> None:
        # `excluded_source_flows` raises for a list whose flow IRI prefix no
        # concept scheme claims, because there would be nowhere to hang the
        # records.  Asking for the whole mapping is what checks that Stepwise's
        # prefix and its scheme still agree.
        self.assertEqual(len(excluded_source_flows()[_SCHEME]), 9)

    def test_applying_the_file_removes_the_rows(self) -> None:
        gamma = {
            "uuid": "540ddfe4-9f93-5af2-bbe7-c912be0cac60",
            "name": "Chlordane, gamma-",
            "source": _KEY,
            "context": ["Air", "(unspecified)"],
            "unit": "kg",
            "cas_numbers": ["5566-34-7"],
        }
        trans = {
            "uuid": "160d13a8-15eb-5c28-9e59-46d1e170a684",
            "name": "Chlordane, trans-",
            "source": _KEY,
            "context": ["Air", "(unspecified)"],
            "unit": "kg",
            "cas_numbers": ["5103-74-2"],
        }
        flows = [gamma, trans]
        apply_additional_flows(
            flows, self.path, source=self.source.source_label, label=_KEY
        )
        self.assertEqual(flows, [trans])

    def test_applying_the_file_removes_the_injury_rows(self) -> None:
        # The other half of #173: the record has to take the row out of the
        # fetch, and take only that row.  `Carbon dioxide, fossil` is here as
        # the row that must survive -- an exclusion that removed a whole
        # compartment, or every row of the list, would pass a test that only
        # looked at what went.
        fatal = {
            "uuid": "2d507c7d-8784-5199-b3e5-272f7601c281",
            "name": "Injuries, fatal",
            "source": _KEY,
            "context": ["Social", "(unspecified)"],
            "unit": "p",
        }
        road = {
            "uuid": "5f177c64-720c-5230-b3a4-807633eb0a22",
            "name": "Injuries, non-fatal, road",
            "source": _KEY,
            "context": ["Social", "(unspecified)"],
            "unit": "p",
        }
        fossil = {
            "uuid": "bb0f8f42-b565-5777-a22b-3a35eda6c990",
            "name": "Carbon dioxide, fossil",
            "source": _KEY,
            "context": ["Air", "(unspecified)"],
            "unit": "kg",
            "cas_numbers": ["124-38-9"],
        }
        flows = [fatal, fossil, road]
        apply_additional_flows(
            flows, self.path, source=self.source.source_label, label=_KEY
        )
        self.assertEqual(flows, [fossil])


if __name__ == "__main__":
    unittest.main()
