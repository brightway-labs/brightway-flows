"""The one water pair carrying a published conversion, and what holds it together.

`Water, salt, ocean` (m3) maps onto EF 3.1's `sea water` (kg) and publishes
`qudt:conversionMultiplier` 1025 kg/m3 -- the only conversion in the water
corpus.  Three files have to agree for that to keep working, and the material
split (#31) moved one of the things they agree about:

- `unit-change-allowlist.json` is keyed on the **target elementary flow id**, so
  the pair is reported as an unreviewed unit mismatch the moment that id moves;
- `merge/conversions.py` carries the factor onto whatever pair the merge built,
  guarded by the **units as IRIs**, so it survives a moved target but not a
  changed unit;
- `tests/test_conversion_multipliers.py` pins the allowlist and the conversions
  together, so a pair cannot be published with a multiplier while being reported
  as unreviewed on the same run.

What makes the split safe is that the elementary flow keeps its identifier when
its **flow object** changes.  That is not obvious and nothing else asserts it,
so it is asserted here: if identifiers were derived from the object, every
conversion and every allowlist entry in the project would move whenever a
substance was regrouped.
"""

import unittest

import orjson

from brightway_flows.domain.flow import Flow
from brightway_flows.domain.materials import (
    material_concepts,
    material_for_source_flow,
)
from brightway_flows.domain.units import states_more_than_the_unit_table
from brightway_flows.flow_layers.layering import resolve_flow_layers
from brightway_flows.merge.conversions import UnitConversion
from brightway_flows.sources import base_source_list

EF = "EF 3.1"
#: EF 3.1 `sea water`, kg -- the target the allowlist and the factor both name.
SEA_WATER = "172a3db9-6556-11dd-ad8b-0800200c9a66"
#: ecoinvent `Water, salt, ocean`, m3.
SALT_OCEAN = "629ffbca-ca71-4e4b-a006-ca9bdd9cd1df"
RESO_OCEA = "https://vocab.brightway.one/flow-contexts/reso-wate-ocea"


def _allowlist_row():
    from brightway_flows.domain.materials import DATA_DIR

    payload = orjson.loads((DATA_DIR / "unit-change-allowlist.json").read_bytes())
    return next(
        row for row in payload["accepted"] if row["source_uuid"] == SALT_OCEAN
    )


class IdentitySurvivesTheSplitTestCase(unittest.TestCase):
    """The property the allowlist key rests on."""

    def test_an_elementary_flow_keeps_its_identifier_when_its_object_moves(self):
        flow = Flow.from_dict(
            {
                "uuid": SEA_WATER,
                "identifier": SEA_WATER,
                "source": EF,
                "unit": "kg",
                "cas_numbers": ["7732-18-5"],
                "context_iri": RESO_OCEA,
                "context": {
                    "dimension": "Resource",
                    "media": "Water",
                    "water_body": "Ocean",
                },
                "prefLabel": [{"@value": "sea water", "@language": "en"}],
                "altLabel": [],
            }
        )
        _objects, elementary, _stats = resolve_flow_layers(
            [flow], source_list=base_source_list()
        )
        self.assertEqual(len(elementary), 1)
        row = elementary[0]
        # The object moved -- this is the whole of Stage 3 -- and the identifier
        # did not.
        self.assertEqual(
            row.flow_object_id, material_concepts()["sea_water"]["flow_object_id"]
        )
        self.assertEqual(row.elementary_flow_id, SEA_WATER)

    def test_the_allowlist_still_names_that_identifier(self):
        self.assertEqual(_allowlist_row()["target_elementary_flow_id"], SEA_WATER)


class BothSidesAreSeaWaterTestCase(unittest.TestCase):
    """The pair the factor is stated between, from the material file."""

    def test_the_source_and_the_target_are_one_material(self):
        self.assertEqual(material_for_source_flow(EF, SEA_WATER), "sea_water")
        self.assertEqual(
            material_for_source_flow("ecoinvent-3.12", SALT_OCEAN), "sea_water"
        )

    def test_the_material_is_asserted_for_every_registered_version(self):
        for version in ("3.8", "3.9.1", "3.10.1", "3.11", "3.12"):
            with self.subTest(version=version):
                self.assertEqual(
                    material_for_source_flow(f"ecoinvent-{version}", SALT_OCEAN),
                    "sea_water",
                )


class TheFactorStillHoldsTestCase(unittest.TestCase):
    """`UnitConversion` guards on units, not on the target's identity."""

    def _conversion(self):
        row = _allowlist_row()
        return UnitConversion(
            factor=1025.0,
            source_unit=row["source_unit"],
            target_unit=row["target_unit"],
        )

    def test_it_holds_for_the_pair_the_allowlist_names(self):
        row = _allowlist_row()
        self.assertTrue(
            self._conversion().holds_between(
                source_unit=row["source_unit"], target_unit=row["target_unit"]
            )
        )

    def test_moving_the_flow_object_cannot_invalidate_it(self):
        """The units are what it is stated between, so a regrouped substance
        keeps its factor as long as the units are unchanged."""
        self.assertTrue(
            self._conversion().holds_between(source_unit="m3", target_unit="kg")
        )

    def test_it_does_not_hold_if_a_unit_changes(self):
        for source, target in (("m3", "m3"), ("kg", "kg"), ("Sm3", "kg")):
            with self.subTest(pair=(source, target)):
                self.assertFalse(
                    self._conversion().holds_between(
                        source_unit=source, target_unit=target
                    )
                )

    def test_a_density_is_something_the_unit_table_cannot_supply(self):
        """Why it is published at all: m3 to kg crosses quantity kinds, so
        `units.json` has no answer to defer to."""
        self.assertTrue(states_more_than_the_unit_table("m3", "kg", 1025.0))


class SeaWaterIsTheOnlyWaterConversionTestCase(unittest.TestCase):
    """Sea water is the only water *name* accepted from more than one list.

    It was one row when this was written, ecoinvent's. BAFU ships the same
    vendor name against the same EF 3.1 target and is accepted the same way,
    and AGRIBALYSE 3.2 ships it twice (#352), so the pair is now four rows and
    one name -- which is the claim worth holding. Lists shipping one vendor row
    must not be accepted from one and reported from another, and the name
    arriving from a further list still needs the reasoning these rows carry.

    Every other water crossing BAFU had is gone rather than allowlisted: eight
    rows measured by mass what this list measures by volume, and they are
    carried in cubic metres with the density stated in
    `bafu-2026-v1-manual-fixes.json` (#78). Accepting those would have been the
    easy way and the wrong one -- the guard reports a disagreement, and there
    was no disagreement, only a vendor using the other measure.

    AGRIBALYSE's other water rows are accepted here instead (#352): thirteen
    density crossings, each with its number stated on the mapping or in the
    row's comment. `test_agribalyse_water_reaches_the_taxonomy` holds those;
    this class holds that nothing beyond them and sea water is in the
    allowlist's water corpus.
    """

    def _allowlisted_water(self) -> list[dict]:
        from brightway_flows.domain.materials import DATA_DIR

        payload = orjson.loads((DATA_DIR / "unit-change-allowlist.json").read_bytes())
        return [
            row
            for row in payload["accepted"]
            if "water" in row.get("source_name", "").lower()
            or "water" in row.get("target_name", "").lower()
        ]

    def _sea_water(self) -> list[dict]:
        return [
            row
            for row in self._allowlisted_water()
            if row["target_elementary_flow_id"] == SEA_WATER
        ]

    def test_sea_water_is_the_only_name_shared_across_lists(self):
        """Every water row that is not sea water is one of AGRIBALYSE's
        recorded crossings (#352). If a second shared water *name* ever needs
        one, it needs this reasoning too, and this test is where that gets
        noticed."""
        from test_agribalyse_water_reaches_the_taxonomy import (
            RecordedCrossingsTestCase,
        )

        agribalyse = {source for source, _ in RecordedCrossingsTestCase.CROSSINGS} | {
            source for source, _ in RecordedCrossingsTestCase.RECORDED_ONLY
        }
        others = [
            row
            for row in self._allowlisted_water()
            if row["target_elementary_flow_id"] != SEA_WATER
        ]
        self.assertNotIn("Water, salt, ocean", {row["source_name"] for row in others})
        self.assertEqual({row["source_uuid"] for row in others} - agribalyse, set())

    def test_every_list_shipping_that_name_is_accepted(self):
        """ecoinvent's row, BAFU's and AGRIBALYSE's two, against the one EF 3.1
        target. Held so that removing any of them is a decision rather than an
        omission."""
        rows = self._sea_water()
        self.assertEqual(len(rows), 4)
        self.assertEqual({row["source_name"] for row in rows}, {"Water, salt, ocean"})
        for row in rows:
            with self.subTest(source=row["source_uuid"]):
                self.assertEqual(row["source_unit"], "m3")
                self.assertEqual(row["target_unit"], "kg")
                self.assertIn("1025", row["comment"])
