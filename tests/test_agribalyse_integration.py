"""Reading AGRIBALYSE 3.2, the first list that arrives as a process database.

Every other SimaPro-shaped list arrives as a method file or an ecoSpold
archive; this one is a ``{processes}`` export, so its flows are whatever its
20,440 processes exchange with the environment.  The tests here are about the
places that collapse can go wrong: the unit, which is the substance block's
and not the exchange row's; the bare subcompartment, which a process export
writes as an empty cell; and the withheld waste compartment.

The fixture is a hand-cut export with the shape of the real one: two
processes, a repeated exchange so the collapse has something to collapse, a
radionuclide inventoried in ``kBq`` and exchanged in ``Bq``, and the trailing
substance blocks that carry the units, registry numbers and comments.
"""

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from brightway_flows.context_mapping import (
    context_iri_by_source_context,
    normalize_context_key,
)
from brightway_flows.integrations.agribalyse import (
    AGRIBALYSE_PROJECT_NAME,
    extract_elementary_flows,
    fetch,
)
from brightway_flows.pipeline.loading import _normalize_input_flow_record
from brightway_flows.sources import SourceList, known_source_lists

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "agribalyse-mini.csv"
KEY = "agribalyse-3.2"


class ExtractionTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.records = extract_elementary_flows(FIXTURE, source=KEY)
        cls.by_name = {row["name"]: row for row in cls.records}

    def test_the_flows_are_the_distinct_exchanges(self):
        """Two processes, nine exchange rows, eight flows: the repeated
        ammonia and caesium rows collapse.  The waste row is among them --
        extraction is faithful to the export, and the refusal of that
        compartment is the excluded list's, applied at load (#189)."""
        self.assertEqual(
            sorted(self.by_name),
            [
                "Ammonia",
                "Cesium-137",
                "Cypermethrin",
                "Nitrate",
                "Occupation, annual crop",
                "Transformation, from annual crop",
                "Waste, test",
                "Water, river, FR",
            ],
        )

    def test_the_unit_is_the_substance_block_s_not_the_exchange_row_s(self):
        """The exchange rows say ``Bq``; the substance block inventories the
        radionuclide in ``kBq``, and one flow stated in two scale variants is
        one flow.  Publishing the exchange row's unit is the thousandfold
        error the Stepwise reader documents from the other direction."""
        self.assertEqual(self.by_name["Cesium-137"]["unit"], "kBq")
        self.assertEqual(self.by_name["Cesium-137"]["context"],
                         ["Emissions to air", "low. pop."])

    def test_a_bare_subcompartment_is_a_one_level_context(self):
        """A process export writes the subcompartment cell empty where BAFU
        writes ``unspecified``.  What the file says is one level, so one level
        is what goes out; `context-manual-mapping.json` places it."""
        self.assertEqual(self.by_name["Ammonia"]["context"], ["Emissions to air"])

    def test_a_registry_number_is_a_list_with_the_padding_gone(self):
        self.assertEqual(self.by_name["Ammonia"]["cas_numbers"], ["7664-41-7"])
        self.assertEqual(self.by_name["Cesium-137"]["cas_numbers"], ["10045-97-3"])

    def test_the_synonyms_come_out_and_the_formula_stays_behind(self):
        self.assertEqual(
            self.by_name["Ammonia"]["synonyms"], ["azane", "ammonia gas"]
        )
        self.assertNotIn("Formula", " ".join(self.by_name["Ammonia"]["synonyms"]))

    def test_the_waste_compartment_is_extracted_for_the_refusal(self):
        """`Final waste flows` is extracted like every other compartment, so
        the refusal (#189) has an identity to name: the excluded list removes
        exactly these uuids at load, and a record that named a row the fetch
        never produced would be a decision applied to nothing."""
        waste = [
            row for row in self.records if row["context"] == ["Final waste flows"]
        ]
        self.assertEqual([row["name"] for row in waste], ["Waste, test"])
        self.assertEqual(waste[0]["unit"], "kg")

    def test_the_identifiers_are_the_same_every_time(self):
        again = extract_elementary_flows(FIXTURE, source=KEY)
        self.assertEqual(
            {row["uuid"] for row in self.records}, {row["uuid"] for row in again}
        )

    def test_every_row_normalises_into_the_pipeline(self):
        for row in self.records:
            with self.subTest(name=row["name"]):
                self.assertIsNotNone(_normalize_input_flow_record(dict(row)))

    def test_the_compartment_rules_cover_the_list(self):
        """Every context the fixture ships has a rule under this list's key,
        which is what `resolve_source_list` checks the cheap way (non-empty)
        and this checks the complete way.  `Final waste flows` is the one
        exception, and deliberately: its rows are refused at load by the
        excluded list (#189) and never reach matching, so a rule for it under
        this list's key would say the list speaks for a compartment it
        refuses."""
        rules = context_iri_by_source_context(KEY)
        for row in self.records:
            if row["context"] == ["Final waste flows"]:
                continue
            key = normalize_context_key(row["context"])
            with self.subTest(context=row["context"]):
                self.assertIn(key, rules)


class FetchTestCase(unittest.TestCase):
    def test_another_project_is_refused_rather_than_read(self):
        """The header's project name is the only claim the file makes about
        itself, so it is the one thing the fetch can check."""
        with tempfile.TemporaryDirectory() as tmp:
            csv_path = Path(tmp) / "AGB32_final.CSV"
            csv_path.write_text(
                FIXTURE.read_text().replace(
                    f"{{Project: {AGRIBALYSE_PROJECT_NAME}}}",
                    "{Project: Some other database}",
                )
            )
            source = SourceList(
                list_name="agribalyse",
                list_version="3.2",
                flows_path=Path(tmp) / "agribalyse-3.2.json",
            )
            with mock.patch(
                "brightway_flows.filesystem.agribalyse_csv_path",
                return_value=csv_path,
            ):
                with self.assertRaises(ValueError) as ctx:
                    fetch(source)
        self.assertIn("Some other database", str(ctx.exception))

    def test_a_missing_export_names_the_path_it_wanted(self):
        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / "AGB32_final.CSV"
            source = SourceList(
                list_name="agribalyse",
                list_version="3.2",
                flows_path=Path(tmp) / "agribalyse-3.2.json",
            )
            with mock.patch(
                "brightway_flows.filesystem.agribalyse_csv_path",
                return_value=missing,
            ):
                with self.assertRaises(FileNotFoundError) as ctx:
                    fetch(source)
        self.assertIn(str(missing), str(ctx.exception))

    def test_the_registered_list_names_this_adapter(self):
        source = known_source_lists()[KEY]
        self.assertEqual(
            source.adapter, "brightway_flows.integrations.agribalyse:fetch"
        )
        self.assertTrue(source.simapro_origin)


if __name__ == "__main__":
    unittest.main()
