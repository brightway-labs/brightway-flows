"""Each mechanism behind #116's splits, at the function that decides.

Four substance records each held two different things, and one substance was
published under the name of the family it belongs to.  The build-level claims
are in `expectations/0588-a-substance-record-holds-one-thing.json`; what these
pin is the rule behind each one -- the qualifier that separates the 100-year
accounting flow from plain biogenic CO2, the curated rulings that separate the
carbon stock and the rhenium ion from the element records they shared, the
class-name test that keeps `polyhaloalkene` off the renamed refrigerant's
synonyms, and the manual fix itself -- each tested for what it must do and for
what it must leave alone.
"""

import tempfile
import unittest
from pathlib import Path

import orjson

from brightway_flows.domain.elementary_flow import ElementaryFlow
from brightway_flows.domain.flow_object import FlowObject
from brightway_flows.domain.preferred_label_decisions import (
    load_preferred_label_decisions,
    rule_on_replacement,
    LabelRuling,
)
from brightway_flows.flow_layers.contested_cas import load_decisions
from brightway_flows.flow_layers.synonyms import (
    carry_member_names,
    load_place_vocabulary,
    names_a_class,
)
from brightway_flows.manual_fixes import apply_manual_fixes
from brightway_flows.filesystem import PACKAGE_DATA_DIR
from brightway_flows.qualifiers import detect_origin_qualifier

FIXES_PATH = PACKAGE_DATA_DIR / "ef-3.1-manual-fixes.json"


class The100YearQualifierTestCase(unittest.TestCase):
    """The variant is an accounting statement, and the word inside it is not."""

    def test_the_accounting_flow_is_its_own_qualifier(self):
        self.assertEqual(
            detect_origin_qualifier("carbon dioxide (biogenic-100yr)"),
            "biogenic_100yr",
        )

    def test_the_cased_and_spaced_spellings_read_the_same(self):
        for name in (
            "Carbon Dioxide (biogenic-100yr)",
            "carbon dioxide (biogenic 100yr)",
            "carbon dioxide (biogenic-100 yr)",
        ):
            with self.subTest(name):
                self.assertEqual(detect_origin_qualifier(name), "biogenic_100yr")

    def test_plain_biogenic_is_left_alone(self):
        """The other half: the rule that refines must not widen.  Ordinary
        biogenic CO2 keeps the qualifier it always had."""
        self.assertEqual(
            detect_origin_qualifier("carbon dioxide (biogenic)"), "biogenic"
        )

    def test_a_horizon_without_a_carbon_origin_is_not_a_qualifier(self):
        """`100yr` alone is a time horizon in a method name, not an origin."""
        self.assertIsNone(detect_origin_qualifier("GWP 100yr"))

    def test_a_delayed_emission_correction_still_outranks_it(self):
        """The correction patterns sit above this one, and a name saying both
        is a correction: the order in QUALIFIER_CHECKS is behaviour."""
        self.assertEqual(
            detect_origin_qualifier(
                "correction flow for delayed emission of biogenic carbon dioxide"
            ),
            "biogenic_delayed_emission_correction",
        )


class TheTwoSeparateRulingsTestCase(unittest.TestCase):
    """The carbon stock and the rhenium ion each leave the element's record."""

    @classmethod
    def setUpClass(cls):
        cls.decisions = load_decisions()

    def test_the_carbon_stock_is_ruled_apart(self):
        ruling = self.decisions.get("7440-44-0")
        self.assertIsNotNone(ruling, "no ruling for the carbon stock split")
        self.assertEqual(str(ruling.verdict), "separate")

    def test_the_rhenium_ion_is_ruled_apart(self):
        ruling = self.decisions.get("7440-15-5")
        self.assertIsNotNone(ruling, "no ruling for the rhenium split")
        self.assertEqual(str(ruling.verdict), "separate")

    def test_each_ruling_records_the_names_it_was_written_about(self):
        """A changed name set is logged rather than obeyed silently, so the
        names recorded must be the names the build actually carries."""
        self.assertEqual(
            sorted(self.decisions["7440-44-0"].names),
            ["carbon", "carbon, organic, in soil or biomass stock"],
        )
        self.assertEqual(
            sorted(self.decisions["7440-15-5"].names),
            ["rhenium", "rhenium(2+)"],
        )

    def test_graphites_contest_is_not_ruled_by_these(self):
        """EF also carries a `Carbon` resource row under graphite's 7782-42-5,
        a different question deliberately left undecided here."""
        ruling = self.decisions.get("7782-42-5")
        if ruling is not None:
            self.fail(
                "7782-42-5 acquired a ruling; the carbon/graphite contest was "
                "deliberately left open by #116"
            )


class TheWaterRulingTestCase(unittest.TestCase):
    def test_water_to_water_vapour_is_approved(self):
        decisions = load_preferred_label_decisions()
        self.assertIs(
            rule_on_replacement(
                decisions,
                current="Water",
                replacement="Water vapour",
                rule="substance_label_v1",
            ),
            LabelRuling.APPROVED,
        )

    def test_the_reverse_is_not_thereby_approved(self):
        """A ruling is a pair, not a symmetry: nothing may rename the liquid
        water substance's flows to `Water vapour`'s inverse on its strength."""
        decisions = load_preferred_label_decisions()
        self.assertIs(
            rule_on_replacement(
                decisions,
                current="Water vapour",
                replacement="Water",
                rule="substance_label_v1",
            ),
            LabelRuling.UNDECIDED,
        )


class TheClassNameTestCase(unittest.TestCase):
    """A family word is a name for every member at once, so for none."""

    def test_polyhaloalkene_names_a_class(self):
        self.assertTrue(names_a_class("polyhaloalkene"))
        self.assertTrue(names_a_class("  Polyhaloalkene "))

    def test_a_member_name_does_not(self):
        for name in ("HFO-1234yf", "2,3,3,3-Tetrafluoropropene", "hafnium"):
            with self.subTest(name):
                self.assertFalse(names_a_class(name))

    def test_a_name_containing_the_class_word_is_not_read(self):
        """Whole-name membership, not a substring: a vendor's `polyhaloalkene
        resin` would be a product name and none of this test's business."""
        self.assertFalse(names_a_class("polyhaloalkene resin"))

    def test_the_carrier_rejects_it_and_carries_the_member_name(self):
        """Both halves of the rule, on the pass that publishes synonyms: the
        class word stays off, and an ordinary vendor spelling still arrives."""
        obj = FlowObject(
            flow_object_id="fo-1",
            prefLabel=[{"@value": "2,3,3,3-Tetrafluoropropene", "@language": "en"}],
            altLabel=[],
            properties={},
            references=[],
            created_from={},
        )
        flow = ElementaryFlow(
            elementary_flow_id="u-1",
            flow_object_id="fo-1",
            source="EF 3.1",
            context=[],
            context_iri="",
            unit="kg",
            unit_iri="",
            lcia_methods=[],
            general_comment="",
            source_refs=[
                {"source_flow_name": "polyhaloalkene"},
                {"source_flow_name": "HFO-1234yf"},
            ],
        )
        stats = carry_member_names([obj], [flow])

        published = [
            row.get("@value") for row in obj.altLabel if isinstance(row, dict)
        ]
        self.assertIn("HFO-1234yf", published)
        self.assertNotIn("polyhaloalkene", published)
        self.assertEqual(stats["rejected_names_a_class"], 1)
        self.assertEqual(stats["names_carried"], 1)

    def test_the_vocabulary_requires_the_block(self):
        """A file without the block fails at load rather than silently
        carrying every class word (the `domain/rulings.py` rule)."""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "places.json"
            path.write_bytes(orjson.dumps({
                "land_flow_prefixes": {"values": ["occupation"]},
                "places": {"values": ["ground"]},
            }))
            with self.assertRaises(ValueError):
                load_place_vocabulary(path)


def _rename():
    payload = orjson.loads(FIXES_PATH.read_bytes())
    for fix in payload["fixes"]:
        if fix.get("field") == "name" and (fix.get("match") or {}).get("name") == "polyhaloalkene":
            return fix
    return None


class TheRefrigerantRenameTestCase(unittest.TestCase):
    def setUp(self):
        self.fix = _rename()

    def test_there_is_a_rename(self):
        self.assertIsNotNone(self.fix, "no rename for EF 3.1's `polyhaloalkene` rows")

    def test_it_publishes_common_chemistrys_name(self):
        self.assertEqual(self.fix["new_value"], "2,3,3,3-Tetrafluoropropene")

    def test_the_class_word_is_not_retained_as_a_synonym(self):
        self.assertNotIn("retain_original_as_synonym", self.fix)

    def test_the_class_word_is_in_the_curated_class_list(self):
        """The fix and the synonym carrier make one statement between them:
        renamed at the source, and kept off the synonyms at the carrier."""
        vocabulary = load_place_vocabulary()
        self.assertIn("polyhaloalkene", vocabulary.chemical_classes)

    def test_a_polyhaloalkene_row_is_renamed(self):
        flow = {"uuid": "u-1", "name": "polyhaloalkene", "cas_numbers": ["754-12-1"]}
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "fixes.json"
            path.write_bytes(orjson.dumps({"schema_version": 1, "fixes": [self.fix]}))
            apply_manual_fixes([flow], path)
        self.assertEqual(flow["name"], "2,3,3,3-Tetrafluoropropene")

    def test_a_hfo_row_is_untouched(self):
        """EF's other spelling for the same substance is already a name."""
        flow = {"uuid": "u-2", "name": "HFO-1234yf", "cas_numbers": ["754-12-1"]}
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "fixes.json"
            path.write_bytes(orjson.dumps({"schema_version": 1, "fixes": [self.fix]}))
            apply_manual_fixes([flow], path)
        self.assertEqual(flow["name"], "HFO-1234yf")


if __name__ == "__main__":
    unittest.main()
