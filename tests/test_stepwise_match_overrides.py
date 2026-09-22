"""Stepwise 2006's curated targets, and what each one is about.

Stepwise arrives as an LCIA method file, so it has no correspondence table at
all and every row of `stepwise-2006-match-overrides.json` is appended onto an
empty one.  That makes the failure mode sharper than it is for a list with a
table: an override naming a uuid Stepwise does not ship overrides nothing,
raises nothing, and reads in review exactly like one that does its job.

Stepwise derives its identifiers from `(name, compartment, subcompartment,
unit)` rather than shipping them, so the check can be made without the vendor's
file: recomputing the identifier from the four fields the row already carries
for the reader's sake says whether the row names the flow it claims to.
"""

from __future__ import annotations

import unittest

from brightway_flows.filesystem import PACKAGE_DATA_DIR
from brightway_flows.integrations.stepwise import _flow_uuid
from brightway_flows.match_overrides import load_match_overrides
from brightway_flows.sources import (
    known_source_lists,
    load_prepared_match_table,
    resolve_source_list,
)

KEY = "stepwise-2006-1.09"
OVERRIDES_PATH = PACKAGE_DATA_DIR / "stepwise-2006-match-overrides.json"

#: The row of #175, and the unit it is shipped in.  `Carbon dioxide` in
#: unspecified air, in kilograms -- one of four carbon dioxide rows Stepwise
#: files there, and the one that says nothing about where its carbon came from.
PLAIN_CARBON_DIOXIDE = "81bef0b2-3ddf-541f-a485-26355997c376"

#: EF 3.1's `carbon dioxide (fossil)` in `Environmental -> Air -> Unknown`, and
#: the flow BAFU's own unqualified `emissions to air / unspecified` row reaches
#: (#139 §17), so that two SimaPro-lineage lists' plain rows meet.
FOSSIL_CARBON_DIOXIDE_IN_AIR = "08a91e70-3ddc-11dd-923d-0050c2490048"

#: The three rows that *do* say what they are, and must keep saying it.  An
#: override that read `Carbon dioxide` as a prefix rather than as the whole
#: name would take these with it, and all three would then be published as
#: fossil -- including the biogenic one, which is the opposite of what the
#: method states for it.
QUALIFIED_CARBON_DIOXIDE = {
    "bb0f8f42-b565-5777-a22b-3a35eda6c990": "Carbon dioxide, fossil",
    "68bdc0f3-b825-5c5f-aaa0-817d3994cfbe": "Carbon dioxide, biogenic",
    "44568309-3092-571c-9964-f2dd2c4ea2e6": "Carbon dioxide, land transformation",
}


class TheFileTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.source = known_source_lists()[KEY]
        self.overrides = load_match_overrides(OVERRIDES_PATH)

    def test_the_manifest_declares_it(self) -> None:
        self.assertEqual(self.source.match_overrides_path, OVERRIDES_PATH)
        self.assertEqual(self.source.missing_curated_inputs(), [])

    def test_every_row_names_a_flow_stepwise_ships(self) -> None:
        # The check the file exists to survive.  A uuid no row carries decides
        # nothing and looks exactly like a decision.
        #
        # The unit is part of the identifier, so a converting row is checked
        # against the unit it says it converts *from*; the one row that states
        # no conversion is a kilogram of carbon dioxide.
        for override in self.overrides:
            with self.subTest(override.source_name):
                self.assertTrue(override.source_context)
                compartment, subcompartment = override.source_context
                unit = override.source_unit or "kg"
                self.assertEqual(
                    _flow_uuid(override.source_name, compartment, subcompartment, unit),
                    override.source_uuid,
                )

    def test_the_plain_carbon_dioxide_row_is_sent_to_the_fossil_flow(self) -> None:
        rows = {
            row["source"]["uuid"]: row["target"]["uuid"]
            for row in load_prepared_match_table(resolve_source_list(KEY))
        }
        self.assertEqual(
            rows.get(PLAIN_CARBON_DIOXIDE), FOSSIL_CARBON_DIOXIDE_IN_AIR
        )

    def test_the_rows_that_say_what_they_are_are_left_alone(self) -> None:
        rows = {
            row["source"]["uuid"]
            for row in load_prepared_match_table(resolve_source_list(KEY))
        }
        for uuid_, name in sorted(QUALIFIED_CARBON_DIOXIDE.items()):
            with self.subTest(name):
                self.assertNotIn(uuid_, rows)


if __name__ == "__main__":
    unittest.main()
