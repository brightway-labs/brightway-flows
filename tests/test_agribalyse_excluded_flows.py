"""AGRIBALYSE 3.2 refuses its waste compartment, and the file that says so has to keep working.

The 43 `Final waste flows` rows are an accounting device -- waste leaving the
product system boundary -- not exchanges with the environment, and the
consensus vocabulary has no waste compartment for them to land in.  #189
decided they are refused on the record: the adapter extracts the compartment
like any other, and every row is an ``excluded`` record in
``agribalyse-3.2-additional-flows.json``, removed when the list is loaded and
published on the correspondence.  One mechanism refuses, and these tests are
its guards.

The failure mode the shape invites is Stepwise's (#167): an exclusion keyed on
a uuid no row carries removes nothing, raises nothing, and reads in review
exactly like one that does its job.  AGRIBALYSE derives its identifiers from
``(name, compartment, subcompartment, unit)``, so every record can be checked
against the row it claims without the vendor's 507 MB export: the four fields
the record carries must reproduce the uuid it is keyed on.
"""

from __future__ import annotations

import unittest

from brightway_flows.additional_flows import (
    apply_additional_flows,
    load_excluded_source_flows,
)
from brightway_flows.integrations.agribalyse import _flow_uuid
from brightway_flows.sources import excluded_source_flows, known_source_lists

_KEY = "agribalyse-3.2"
_SCHEME = "agribalyse-3.2"

#: The busiest refused row: 2,151 of the compartment's 4,640 exchange rows.
_BUSIEST = {
    "uuid": "9b8e42cd-a602-57d2-881e-9dbe0c123f99",
    "name": "Organic carbon, placed in landfill",
    "source": _KEY,
    "context": ["Final waste flows"],
    "unit": "kg",
}


def _agribalyse():
    return known_source_lists()[_KEY]


class AgribalyseWasteIsRefusedTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.source = _agribalyse()
        self.path = self.source.additional_flows_path
        self.assertIsNotNone(
            self.path,
            "The AGRIBALYSE manifest has to name its additional-flows file, or "
            "the refusal is read by nothing and the 43 rows merge into a "
            "compartment that resolves to Inventory Indicator.",
        )
        self.records = load_excluded_source_flows(
            self.path, source=self.source.source_label
        )

    def test_forty_three_rows_are_refused_and_no_more(self) -> None:
        self.assertEqual(len(self.records), 43)

    def test_every_record_is_the_waste_compartment(self) -> None:
        # One decision covers one compartment.  A record filed under any other
        # context would be a refusal smuggled past the decision that
        # authorises this file.
        for record in self.records:
            self.assertEqual(record.context, ("Final waste flows",))

    def test_every_record_names_the_row_it_claims_to(self) -> None:
        # The check the shape exists for.  The adapter derives identity from
        # the four fields the record carries -- the subcompartment is the
        # empty cell the export writes -- so the record's own fields must
        # reproduce the uuid it is keyed on.
        for record in self.records:
            self.assertEqual(
                _flow_uuid(record.name, record.context[0], "", record.unit),
                record.uuid,
                f"{record.name} is not {record.uuid}",
            )

    def test_nothing_was_withdrawn(self) -> None:
        # No build ever minted a consensus flow for a waste row -- the before
        # build of b0b8d76 merged zero of them -- so a `withdrew_identifier`
        # here would be a redirect published for a flow that never existed.
        for record in self.records:
            self.assertEqual(record.withdrew_identifier, "")

    def test_the_exclusions_have_somewhere_to_be_published(self) -> None:
        self.assertEqual(len(excluded_source_flows()[_SCHEME]), 43)

    def test_applying_the_file_removes_the_busiest_row(self) -> None:
        rows = [dict(_BUSIEST)]
        apply_additional_flows(rows, self.path, source=self.source.source_label, label=_KEY)
        self.assertEqual(rows, [])

    def test_a_row_outside_the_compartment_survives_the_file(self) -> None:
        kept = {
            "uuid": _flow_uuid("Ammonia", "Emissions to air", "", "kg"),
            "name": "Ammonia",
            "source": _KEY,
            "context": ["Emissions to air"],
            "unit": "kg",
        }
        rows = [dict(kept)]
        apply_additional_flows(rows, self.path, source=self.source.source_label, label=_KEY)
        self.assertEqual([row["name"] for row in rows], ["Ammonia"])
