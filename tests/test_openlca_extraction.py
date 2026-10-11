"""Reading GreenDelta's openLCA LCIA method package as a flow list.

The archive is 167 MB and not in the repository, so these build a stand-in with
the documents' real shape -- copied from `openLCA LCIA Methods 2.8.2
2026-07-01.zip` -- and the case at the end reads what a real fetch wrote, and
skips where nothing has.
"""

from __future__ import annotations

import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

import orjson

from brightway_flows import filesystem
from brightway_flows.integrations.openlca import (
    OpenLcaPackageError,
    extract_elementary_flows,
    record,
)
from brightway_flows.sources import base_source_list, known_source_lists

KEY = "openlca-2.8.2"

MASS = {
    "@type": "FlowPropertyFactor",
    "isRefFlowProperty": True,
    "flowProperty": {
        "@type": "FlowProperty",
        "@id": "93a60a56-a3c8-11da-a746-0800200b9a66",
        "name": "Mass",
        "category": "Technical flow properties",
        "refUnit": "kg",
    },
    "conversionFactor": 1.0,
}

#: As shipped, `flows/000080c6-0c78-3cf1-b49a-ef60e1cac45d.json`.
THEOPHYLLINE = {
    "@type": "Flow",
    "@id": "000080c6-0c78-3cf1-b49a-ef60e1cac45d",
    "name": "Theophylline",
    "description": "",
    "category": "Elementary flows/Emission to soil/agricultural",
    "version": "00.00.000",
    "flowType": "ELEMENTARY_FLOW",
    "cas": "000058-55-9",
    "formula": "",
    "isInfrastructureFlow": False,
    "flowProperties": [MASS],
}

#: A flow carrying synonyms and a formula, in the package's own spelling.
THIRAM = {
    **THEOPHYLLINE,
    "@id": "11111111-0000-4000-8000-000000000001",
    "name": "Thiram",
    "category": "Elementary flows/Emission to air/unspecified",
    "cas": "000137-26-8",
    "formula": "C6H12N2S4",
    "synonyms": (
        "dimethylcarbamothioylsulfanyl n,n-dimethylcarbamodithioate; "
        "tetramethylthiuram disulfide"
    ),
}


def _archive(directory: Path, *flows: dict) -> Path:
    path = directory / "openLCA LCIA Methods 2.8.2 2026-07-01.zip"
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("openlca.json", '{"schemaVersion":5}')
        for flow in flows:
            zf.writestr(f"flows/{flow['@id']}.json", orjson.dumps(flow))
        # Not a flow: a method package ships these beside them.
        zf.writestr("lcia_methods/m.json", '{"@type":"ImpactMethod"}')
    return path


class RecordTestCase(unittest.TestCase):
    def test_a_flow_document_becomes_a_source_list_record(self):
        self.assertEqual(
            record(THEOPHYLLINE, source=KEY),
            {
                "uuid": "000080c6-0c78-3cf1-b49a-ef60e1cac45d",
                "name": "Theophylline",
                "source": KEY,
                "context": ["Emission to soil", "agricultural"],
                "unit": "kg",
                "cas_numbers": ["58-55-9"],
            },
        )

    def test_synonyms_are_split_and_the_formula_kept(self):
        row = record(THIRAM, source=KEY)
        self.assertEqual(
            row["synonyms"],
            [
                "dimethylcarbamothioylsulfanyl n,n-dimethylcarbamodithioate",
                "tetramethylthiuram disulfide",
            ],
        )
        self.assertEqual(row["formula"], "C6H12N2S4")
        self.assertEqual(row["cas_numbers"], ["137-26-8"])

    def test_a_value_that_is_not_a_cas_number_is_kept_as_shipped(self):
        """The CAS transformer reports it; dropping it here would hide it."""
        row = record({**THEOPHYLLINE, "cas": "E1730135"}, source=KEY)
        self.assertEqual(row["cas_numbers"], ["E1730135"])

    def test_the_unit_is_the_reference_property_s(self):
        area_time = {
            **MASS,
            "flowProperty": {**MASS["flowProperty"], "name": "Area*Time", "refUnit": "m2*a"},
        }
        row = record({**THEOPHYLLINE, "flowProperties": [area_time]}, source=KEY)
        self.assertEqual(row["unit"], "m2*a")

    def test_a_flow_without_one_reference_property_is_refused(self):
        for properties in ([], [MASS, MASS], [{**MASS, "isRefFlowProperty": False}]):
            with self.subTest(count=len(properties)):
                with self.assertRaises(OpenLcaPackageError):
                    record({**THEOPHYLLINE, "flowProperties": properties}, source=KEY)

    def test_a_flow_outside_the_elementary_root_is_refused(self):
        for category in ("Emission to air/unspecified", "Elementary flows", ""):
            with self.subTest(category=category):
                with self.assertRaises(OpenLcaPackageError):
                    record({**THEOPHYLLINE, "category": category}, source=KEY)


class ExtractTestCase(unittest.TestCase):
    def setUp(self):
        self.directory = Path(tempfile.mkdtemp())

    def test_every_flow_in_the_archive_and_nothing_else(self):
        rows = extract_elementary_flows(
            _archive(self.directory, THEOPHYLLINE, THIRAM), source=KEY
        )
        self.assertEqual([row["name"] for row in rows], ["Theophylline", "Thiram"])

    def test_a_product_flow_is_refused(self):
        product = {**THIRAM, "@id": "22222222-0000-4000-8000-000000000002",
                   "flowType": "PRODUCT_FLOW"}
        with self.assertRaises(OpenLcaPackageError):
            extract_elementary_flows(
                _archive(self.directory, THEOPHYLLINE, product), source=KEY
            )

    def test_an_archive_with_no_flows_is_refused(self):
        with self.assertRaises(OpenLcaPackageError):
            extract_elementary_flows(_archive(self.directory), source=KEY)


class ArchivePathTestCase(unittest.TestCase):
    def setUp(self):
        self.directory = Path(tempfile.mkdtemp())
        patcher = mock.patch.object(filesystem, "DATA_DIR", self.directory)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_the_archive_is_found_by_its_version_whatever_its_date(self):
        path = _archive(self.directory, THEOPHYLLINE)
        self.assertEqual(filesystem.openlca_lcia_zip_path("2.8.2"), path)

    def test_none_or_two_archives_of_a_version_is_a_question_for_a_person(self):
        with self.assertRaises(FileNotFoundError):
            filesystem.openlca_lcia_zip_path("2.8.2")
        _archive(self.directory, THEOPHYLLINE)
        (self.directory / "openLCA LCIA Methods 2.8.2 2026-08-01.zip").write_bytes(b"")
        with self.assertRaises(FileNotFoundError):
            filesystem.openlca_lcia_zip_path("2.8.2")


class FetchedListTestCase(unittest.TestCase):
    """What a real fetch wrote, where one has run."""

    def setUp(self):
        self.source = known_source_lists()[KEY]
        if not self.source.flows_path.exists():
            self.skipTest(f"{self.source.flows_path} has not been fetched")
        self.rows = orjson.loads(self.source.flows_path.read_bytes())

    def test_the_package_s_counts(self):
        self.assertEqual(len(self.rows), 61_211)
        self.assertEqual(sum(1 for row in self.rows if "cas_numbers" in row), 55_630)
        self.assertEqual(len({row["uuid"] for row in self.rows}), 61_211)

    def test_no_registry_number_is_left_padded(self):
        padded = [
            number
            for row in self.rows
            for number in row.get("cas_numbers", ())
            if number[:1] == "0" and "-" in number
        ]
        self.assertEqual(padded, [])

    def test_every_compartment_has_a_rule(self):
        from brightway_flows.context_mapping import context_iri_by_source_context
        from brightway_flows.context_mapping import normalize_context_key

        rules = context_iri_by_source_context(self.source.source_label)
        unruled = sorted(
            {
                tuple(row["context"])
                for row in self.rows
                if normalize_context_key(row["context"]) not in rules
            }
        )
        # The two waste compartments are refused rather than placed (#189).
        self.assertEqual(
            unruled, [("Waste", "ecopoints 97, CH"), ("Waste", "unspecified")]
        )

    def test_the_refused_rows_are_the_waste_compartments_and_black_carbon(self):
        from brightway_flows.additional_flows import load_excluded_source_flows

        refused = {
            record.uuid
            for record in load_excluded_source_flows(
                self.source.additional_flows_path, source=self.source.source_label
            )
        }
        waste = {row["uuid"] for row in self.rows if row["context"][0] == "Waste"}
        # Black carbon carries climate factors no plain particle flow has, and
        # is kept out until it is decided as a substance.
        black_carbon = {
            row["uuid"] for row in self.rows if "black carbon" in row["name"].lower()
        }
        self.assertEqual((len(waste), len(black_carbon)), (186, 13))
        self.assertEqual(refused, waste | black_carbon)
        self.assertEqual(len(self.source.load_flows()), 61_211 - 199)

    def test_shares_125_uuids_with_ef_3_1(self):
        # GreenDelta ships these EF 3.1 flows under EF's own uuids, renamed in
        # ecoinvent's spelling; the merge matches them by that uuid.
        ef = base_source_list()
        if not ef.flows_path.exists():
            self.skipTest(f"{ef.flows_path} has not been fetched")
        ef_uuids = {row["uuid"] for row in orjson.loads(ef.flows_path.read_bytes())}
        self.assertEqual(len(ef_uuids & {row["uuid"] for row in self.rows}), 125)

if __name__ == "__main__":
    unittest.main()
