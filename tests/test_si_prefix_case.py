"""The public unit readers cannot turn a milli amount into a mega amount."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import orjson

from brightway_flows.domain.flow import Flow
from brightway_flows.domain import units
from brightway_flows.domain.units import (
    UNITS_FILEPATH,
    build_units_index,
    canonical_unit,
    resolve_unit_notation,
    unit_iri_for,
    unit_row_for,
    unit_table_factor,
)
from brightway_flows.transformers.unit_normalization import UnitNormalizationTransformer
from brightway_flows.integrations import ef31
from brightway_flows.merge.conversions import UnitConversion


class SIPrefixCaseTestCase(unittest.TestCase):
    def test_milli_cannot_reach_the_mega_energy_unit_through_any_reader(self):
        index = build_units_index()
        for symbol in (
            "mJ",
            "mj",
            "mJ/kg",
            "mj/kg",
            "mJ primary",
            "mJ extra",
            "mJprimary",
            "mJextra",
        ):
            with self.subTest(symbol=symbol):
                self.assertIsNone(unit_row_for(symbol))
                self.assertIsNone(resolve_unit_notation(symbol, index))
                self.assertEqual(unit_iri_for(symbol), "")
                self.assertEqual(canonical_unit(symbol), symbol)
                self.assertIsNone(unit_table_factor(symbol, "MJ"))

    def test_existing_provider_spellings_keep_their_quantities(self):
        for symbol, target, factor in (
            ("KG", "g", 1000),
            ("Kilograms", "g", 1000),
            ("Tonnes", "kg", 1000),
            ("L", "m3", 0.001),
            ("BQ", "kBq", 0.001),
            ("kbq", "Bq", 1000),
            ("KBq", "Bq", 1000),
            ("KWH", "MJ", 3.6),
            ("MJ", "J", 1_000_000),
            ("MJ/kg", "J/kg", 1_000_000),
        ):
            with self.subTest(symbol=symbol):
                self.assertIsNotNone(unit_row_for(symbol))
                self.assertAlmostEqual(unit_table_factor(symbol, target), factor)

    def test_kilowatt_hour_has_one_canonical_symbol_and_keeps_legacy_aliases(self):
        expected = unit_row_for("kWh")
        self.assertEqual(expected["notation"], "kWh")
        for symbol in ("kwh", "KWH", "kWh", "Kilowatt Hour"):
            with self.subTest(symbol=symbol):
                self.assertEqual(unit_row_for(symbol), expected)
                self.assertEqual(canonical_unit(symbol), "kWh")
                self.assertAlmostEqual(unit_table_factor(symbol, "MJ"), 3.6)

    def test_every_declared_unit_notation_and_label_still_resolves(self):
        for row in orjson.loads(UNITS_FILEPATH.read_bytes()):
            for token in (
                row["notation"],
                row["notation"].replace(" ", ""),
                row["label"],
                row["label"].upper(),
                row["label"].lower(),
            ):
                with self.subTest(token=token):
                    resolved = unit_row_for(token)
                    self.assertIsNotNone(resolved)
                    self.assertEqual(resolved["iri"], row["iri"])

    def test_particulate_annotation_is_not_an_si_prefix(self):
        expected = unit_row_for("kg PM2.5-eq")
        for token in ("kg pm2.5-eq", "kgPM2.5-eq", "kilogram pm2.5-eq."):
            with self.subTest(token=token):
                self.assertEqual(unit_row_for(token), expected)

    def test_recorded_factor_cannot_bind_to_the_opposite_prefix(self):
        conversion = UnitConversion(1_000_000, "MJ", "J")
        self.assertFalse(conversion.holds_between(source_unit="mJ", target_unit="J"))
        conversion = UnitConversion(9.41, "kg", "MJ")
        self.assertFalse(conversion.holds_between(source_unit="kg", target_unit="mJ"))
        self.assertTrue(
            conversion.holds_between(source_unit="Kilograms", target_unit="MJ")
        )

    def test_unknown_units_need_the_same_case_to_bind_a_recorded_factor(self):
        # These labels are deliberately absent from the package vocabulary.
        conversion = UnitConversion(0.5, "mX", "test-unit")
        self.assertFalse(
            conversion.holds_between(source_unit="MX", target_unit="test-unit")
        )
        self.assertTrue(
            conversion.holds_between(source_unit=" mX ", target_unit="test-unit")
        )

    def test_ef_reference_units_use_the_same_prefix_guard(self):
        index = ef31._load_units_index()
        for token in ("mJ", "mJ/kg", "mJprimary", "mJ extra"):
            with self.subTest(token=token):
                self.assertEqual(ef31._resolve_unit(token, index), (None, 1.0))
        for token, notation, multiplier in (
            ("MJ", "MJ", 1.0),
            ("KG", "kg", 1.0),
            ("L", "l", 1.0),
            ("kbq", "kBq", 1.0),
            ("kg*a", "kg.d", 365.25),
        ):
            with self.subTest(token=token):
                row, factor = ef31._resolve_unit(token, index)
                self.assertEqual(row["notation"], notation)
                self.assertEqual(factor, multiplier)

    def test_source_normalisation_reports_the_unsupported_symbol(self):
        # An isolated test flow, never a registered source row or Curation case.
        flow = Flow(uuid="unit-prefix-test", name="Test energy amount", unit="mJ")
        transformer = UnitNormalizationTransformer()
        transformer.setup()
        with tempfile.TemporaryDirectory() as directory:
            with patch(
                "brightway_flows.transformers.unit_normalization.DATA_DIR",
                Path(directory),
            ):
                with self.assertRaisesRegex(ValueError, "mJ"):
                    transformer.transform([flow])
                evidence = orjson.loads(
                    (Path(directory) / "missing-units.json").read_bytes()
                )
        self.assertEqual(evidence, {"missing": [{"unit": "mJ", "count": 1}]})
        self.assertEqual(flow.unit, "mJ")

    def test_declared_opposite_prefixes_remain_distinct_quantities(self):
        # Test-only vocabulary: actual SI prefix scales from BIPM, never added
        # to the package vocabulary or to a registered source list.
        joule = unit_row_for("J")
        pairs = (
            ("m", -3, "M", 6),
            ("p", -12, "P", 15),
            ("z", -21, "Z", 21),
            ("y", -24, "Y", 24),
            ("r", -27, "R", 27),
            ("q", -30, "Q", 30),
        )
        rows = [joule]
        for lower, low_power, upper, high_power in pairs:
            for prefix, power in ((lower, low_power), (upper, high_power)):
                rows.append(
                    dict(
                        joule,
                        notation=prefix + "J",
                        label="Isolated SI test unit " + prefix,
                        iri="https://example.test/unit/" + prefix + "J",
                        conversion_multiplier=10.0**power,
                    )
                )
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "test-only-units.json"
            source.write_bytes(orjson.dumps(rows))
            with patch.object(units, "UNITS_FILEPATH", source):
                index = build_units_index()
            with patch.object(units, "_UNITS_INDEX_CACHE", index):
                for lower, low_power, upper, high_power in pairs:
                    with self.subTest(prefix=lower):
                        self.assertNotEqual(
                            unit_iri_for(lower + "J"), unit_iri_for(upper + "J")
                        )
                        self.assertAlmostEqual(
                            unit_table_factor(lower + "J", upper + "J")
                            / 10.0 ** (low_power - high_power),
                            1.0,
                        )
