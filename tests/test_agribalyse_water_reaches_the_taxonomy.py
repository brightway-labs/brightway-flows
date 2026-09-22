"""Which water each of AGRIBALYSE's water rows is, and that the merge reads it.

AGRIBALYSE 3.2 ships 1,036 water rows outside the air compartments, and on the
first build to merge the list (1 September 2026) 1,019 of them matched nothing:
every kind of water shares CAS 7732-18-5, so the registry number reaches twelve
substances and chooses none, and which kind a row means -- river, well,
cooling, rain, brine -- is written only in the flow name.  The assignment in
`water-flow-materials.json` is the same curation BAFU's 290 rows got (#86,
and see `test_bafu_water_reaches_the_taxonomy.py`), generated per uuid by
`tools/build_water_flow_materials.py` from eighteen base names because the
vendor writes the inventory's place onto the name -- `Water, river, FR` -- and
one base fans out over up to two hundred places.

The compartment is the other half.  AGRIBALYSE files 70 water intakes under
the bare `Resources` heading among the ores, and 49 more under `Resources /
in ground` because a well reaches the water through the ground; the compartment
rulings read both as ground resources, and a river intake filed in the ground
contradicts every flow its material can reach.  Two `Water` name-prefix rules
in `context-manual-mapping.json` say the medium (`Resource -> Water`) the
filing slip does not, the same way the `Occupation, ` rules say land use.
"""

from __future__ import annotations

import unittest

from brightway_flows.domain.materials import (
    flow_object_basis_for,
    material_by_source_flow,
    material_for_source_flow,
)
from brightway_flows.lookup.query import FlowQuery, resolve_context

AGB = "agribalyse-3.2"

#: One real AGRIBALYSE flow per assignment worth naming, by uuid.  The uuid is
#: what the lookup is keyed on, so these are the rows themselves.
RIVER_FR_IN_WATER = "ac7ae4f6-eb08-5fe5-84bb-e499bfec6032"  # Water, river, FR
WELL_FR_IN_WATER = "e836af7b-b021-5962-9012-9f409a282db0"  # Water, well, FR
WELL_BARE_HEADING = "bb4a32fc-31bf-59e2-93b0-bf9e26c745da"  # Water, well / Resources
SALT_SOLE = "00751e0d-c4db-5db0-87de-34f20f6ee504"  # Water, salt, sole
IN_AIR_RESOURCE = "dbd2713a-c472-5571-8be2-f92e2f7e5896"  # Water, in air
RAIN_TO_RIVER = "eaf99464-7cc4-551b-9776-a6e6e130ef93"  # Water, rain, emitted
COOLING_WELL = "c88650ff-2109-5535-92e9-5b3ca92f4315"  # Water, cooling, well
LAND_TRANSFORMATION = "f09dd74c-3f3a-5692-9435-cf1d9509bf24"  # not water at all

#: Base names AGRIBALYSE shares with a sibling list, spelled identically.  Two
#: lists spelling a flow the same way and meaning different things is not
#: something a curator should have to discover from a merge report.
SHARED_BASES = (
    "Water, lake",
    "Water, river",
    "Water, salt, ocean",
    "Water, salt, sole",
    "Water, cooling, unspecified natural origin",
    "Water, turbine use, unspecified natural origin",
)


def _agb_rows() -> dict[str, dict]:
    """Every curated assignment for AGRIBALYSE, by source uuid."""
    return {
        uuid: row
        for (source, uuid), row in material_by_source_flow().items()
        if source == AGB
    }


class AssignmentTestCase(unittest.TestCase):
    """What the curated file says about AGRIBALYSE's water."""

    def test_every_water_row_is_assigned(self):
        """1,047 rows: the 1,036 outside the air compartments (#352, with
        `Turbined water` the one spelling that does not lead with the word)
        plus the eleven emissions to air, which #353 answered with the vapour
        rule."""
        rows = _agb_rows()
        self.assertEqual(len(rows), 1047)
        air = [
            row for row in rows.values()
            if row["source_context"][:1] == ["Emissions to air"]
        ]
        self.assertEqual(len(air), 11)

    def test_the_geography_never_reaches_the_assignment(self):
        """`Water, river, FR` and `Water, river` are one material.  The place
        is the inventory's, not the water's, and the table is keyed on the
        uuid so the spelling never matters at run time."""
        self.assertEqual(material_for_source_flow(AGB, RIVER_FR_IN_WATER), "river_water")
        self.assertEqual(material_for_source_flow(AGB, WELL_FR_IN_WATER), "groundwater")

    def test_a_bare_heading_intake_is_assigned_like_its_sited_twin(self):
        self.assertEqual(material_for_source_flow(AGB, WELL_BARE_HEADING), "groundwater")

    def test_the_use_wins_over_the_origin(self):
        """`Water, cooling, well` names where the water came from and what it
        is for, and the use wins -- the same reading that makes EF's `Water
        Cooling sea` cooling water rather than sea water."""
        self.assertEqual(material_for_source_flow(AGB, COOLING_WELL), "cooling_water")

    def test_brine_and_vapour_are_not_water(self):
        self.assertEqual(material_for_source_flow(AGB, SALT_SOLE), "brine")
        self.assertEqual(material_for_source_flow(AGB, IN_AIR_RESOURCE), "water_vapour")

    def test_rain_emitted_to_a_river_is_still_rainwater(self):
        """The release does not change what the water is made of; whether the
        consensus list carries a rainwater emission flow is the selector's
        question, not the material's."""
        self.assertEqual(material_for_source_flow(AGB, RAIN_TO_RIVER), "rainwater")

    def test_a_row_that_is_not_water_has_no_material(self):
        """The negative half: the busiest land row gains nothing here.  A
        table that quietly grew opinions about land would be the widening the
        matching rules warn about."""
        self.assertIsNone(material_for_source_flow(AGB, LAND_TRANSFORMATION))

    def test_shared_spellings_agree_with_the_sibling_lists(self):
        by_vendor: dict[str, dict[str, set[str]]] = {}
        for (source, _uuid), row in material_by_source_flow().items():
            vendor = source.split("-")[0] if source != "EF 3.1" else "EF 3.1"
            by_vendor.setdefault(vendor, {}).setdefault(
                row["source_name"], set()
            ).add(row["node"])
        for name in SHARED_BASES:
            ours = by_vendor["agribalyse"].get(name)
            if ours is None:
                # AGRIBALYSE ships this base only with a place or a unit
                # written onto it; the spelling comparison has no exact pair.
                continue
            for sibling in ("bafu", "ecoinvent"):
                theirs = by_vendor.get(sibling, {}).get(name)
                if theirs is None:
                    continue
                with self.subTest(name=name, sibling=sibling):
                    self.assertEqual(ours, theirs)

    def test_every_assignment_mints_an_object(self):
        for uuid, row in _agb_rows().items():
            with self.subTest(uuid=uuid):
                self.assertTrue(flow_object_basis_for(row["node"]))


class MediumRuleTestCase(unittest.TestCase):
    """The two `Water` name-prefix rules: an intake filed among the ores or
    the boreholes resolves to the water medium, and nothing else moves."""

    def _resolved(self, name: str, context: list[str]) -> str:
        result = resolve_context(
            FlowQuery(
                name=name, context=context, unit="m3",
                simapro_origin=True, source_label=AGB,
            )
        )
        return result.context_iri.rsplit("/", 1)[-1] if result.context_iri else ""

    def test_a_bare_heading_intake_resolves_to_water(self):
        self.assertEqual(self._resolved("Water, Well, AT", ["Resources"]), "reso-wate")

    def test_an_in_ground_intake_resolves_to_water(self):
        self.assertEqual(
            self._resolved("Water, Well, FR", ["Resources", "in ground"]), "reso-wate"
        )

    def test_the_ores_stay_where_the_compartment_says(self):
        """The `select` half of the rule: a name the prefix does not catch is
        the compartment ruling's to decide, exactly as before."""
        self.assertEqual(self._resolved("Ferromanganese", ["Resources"]), "reso-grou")
        self.assertEqual(
            self._resolved("Kaolin Ore", ["Resources", "in ground"]), "reso-grou"
        )

    def test_the_land_rules_still_pick_their_rows_out(self):
        """Three prefix rules now share the bare heading; each still catches
        only its own rows."""
        self.assertEqual(
            self._resolved("Occupation, annual crop", ["Resources"]), "laus-occu"
        )


class RecordedCrossingsTestCase(unittest.TestCase):
    """The density crossings the water curation creates are recorded, with
    the factor on the mapping.

    Placing every row by material put thirteen rows on flows that keep the
    other quantity basis -- kilogram intakes on cubic-metre flows and
    cubic-metre rows on kilogram flows.  The units still disagree and the
    `has_unit_mismatch` annotation stays truthful; what these tests hold is
    that each crossing is accepted in `unit-change-allowlist.json` and that
    the mapping states its density in `agribalyse-3.2-match-overrides.json`,
    so `merge.unit_crossings_unrecorded` (#171) stays at nothing and no
    consumer has to invent the number.
    """

    #: (source uuid, target flow) for the nine whose mapping carries the
    #: density as a `conversion_factor` (target units per source unit).
    CROSSINGS = {
        ("bbb5091d-e7a8-50da-bb55-ec6365216033",
         "21868f36-62ab-4e8e-98ed-7106228c17be"): 0.000976,
        ("9aef3b90-11aa-53d6-b21d-a28d7ce798d2",
         "21868f36-62ab-4e8e-98ed-7106228c17be"): 0.000976,
        ("b0354aab-3d37-5f18-97be-a7cb803a016e",
         "21868f36-62ab-4e8e-98ed-7106228c17be"): 0.001,
        ("c88650ff-2109-5535-92e9-5b3ca92f4315",
         "21868f36-62ab-4e8e-98ed-7106228c17be"): 0.001,
        ("d48aed46-a1e1-5e4f-ae88-bf7c16a0a11b",
         "419682fe-60fb-4b43-be89-bf2824b51104"): 0.001,
        ("6a4e5330-9eec-5b5d-8168-8104a8ac6a47",
         "2a240c57-b782-4745-943b-0602d7a953c4"): 1000.0,
        ("fbc974be-79c5-58f5-bbb3-ac8334bed8b9",
         "2a240c57-b782-4745-943b-0602d7a953c4"): 1000.0,
        ("100a6a8c-179e-5beb-a266-e35a0dc210b6",
         "419682fe-60fb-4b43-be89-bf2824b51104"): 0.001,
        ("cd0eb42b-f9bd-5b9f-b4d5-3d53be8fa9fb",
         "419682fe-60fb-4b43-be89-bf2824b51104"): 0.001,
    }

    #: The four whose crossing is accepted but deliberately carries no mapping
    #: override: for the barrage and groundwater intakes the prepared
    #: machinery would refuse the finer-context target and mint a second
    #: resource place for the substance, which #89 prohibits; the two ocean
    #: rows land where ecoinvent's identical rows land instead of where the
    #: unit preference would put them.  Their density lives in the allowlist
    #: comment.
    RECORDED_ONLY = {
        ("876eb811-e758-5661-9ec5-bf921691f3e8",
         "f21cd78e163bcc18b4aff7578fc28b39e5e7cd4f"),
        ("b547b1b1-d190-55e0-8fc7-f142d52c85d1",
         "4f462198-40cd-4184-8733-86648a20dc3f"),
        ("adb5276d-5e47-566a-8884-d74b8eb0034c",
         "172a3db9-6556-11dd-ad8b-0800200c9a66"),
        ("395406e5-adc4-5096-b159-e6aca93682af",
         "172a3db9-6556-11dd-ad8b-0800200c9a66"),
    }

    def test_every_crossing_is_accepted(self):
        from brightway_flows.merge.unit_changes import (
            load_unit_change_allowlist,
        )

        allowed = load_unit_change_allowlist()
        for pair in list(self.CROSSINGS) + sorted(self.RECORDED_ONLY):
            self.assertIn(pair, allowed, f"{pair}: crossing not accepted")

    def test_the_recorded_only_pairs_have_no_override(self):
        """The negative half of the mapping question: a pair whose override
        would mint a second place for its substance stays out of the
        overrides file, so #89's one-place rulings hold."""
        from brightway_flows.filesystem import PACKAGE_DATA_DIR
        from brightway_flows.match_overrides import load_match_overrides

        stated = {
            (r.source_uuid, r.target_uuid)
            for r in load_match_overrides(
                PACKAGE_DATA_DIR / "agribalyse-3.2-match-overrides.json"
            )
        }
        for pair in self.RECORDED_ONLY:
            self.assertNotIn(pair, stated, f"{pair}: override would mint")

    def test_every_mapping_states_its_density(self):
        from brightway_flows.filesystem import PACKAGE_DATA_DIR
        from brightway_flows.match_overrides import load_match_overrides

        rows = {
            (r.source_uuid, r.target_uuid): r
            for r in load_match_overrides(
                PACKAGE_DATA_DIR / "agribalyse-3.2-match-overrides.json"
            )
        }
        for pair, factor in self.CROSSINGS.items():
            self.assertIn(pair, rows, f"{pair}: no override states the factor")
            row = rows[pair]
            self.assertTrue(row.converts, f"{pair}: no conversion on the row")
            self.assertEqual(row.factor_for("3.2"), factor)

    def test_the_salt_rows_use_the_ocean_pairs_density(self):
        """One density for one ocean: 1025 kg/m3 is what ecoinvent's
        `Water, salt, ocean` entry records, and AGRIBALYSE's rows cross at
        the same number (its reciprocal, for the kilogram cooling intakes)."""
        salt = {
            pair: f for pair, f in self.CROSSINGS.items()
            if f in (1025.0, 0.000976)
        }
        self.assertEqual(len(salt), 2)
        ocean = {
            pair for pair in self.RECORDED_ONLY
            if pair[1] == "172a3db9-6556-11dd-ad8b-0800200c9a66"
        }
        self.assertEqual(len(ocean), 2)

    def test_the_turbined_discharge_is_in_the_table(self):
        """The one water spelling that does not lead with the word, and the
        one row of the family the first curation pass missed: `Turbined
        water`, an m3 discharge onto an m3 flow -- no crossing."""
        row = _agb_rows().get("855c60b9-1e46-50ef-8030-efbdb08c6b29")
        self.assertIsNotNone(row, "Turbined water is not in the table")
        self.assertEqual(row["node"], "turbine_water")
        self.assertEqual(row["match"], "exact")


class WaterToAirIsVapourTestCase(unittest.TestCase):
    """Water released to air is the Water vapour substance (#353).

    Eleven AGRIBALYSE rows evaporate water -- nine spellings of `Water` and
    two `Water (evapotranspiration)` rows.  On the first build to merge the
    list none reached vapour: the first row in each air compartment minted a
    plain-Water air flow, the siblings matched the fresh mints (four crossing
    m3 to kg silently), and evapotranspiration minted its own substance.  The
    air rule in `tools/build_water_flow_materials.py` now reads them all as
    vapour, the same way it reads EF's, ecoinvent's and BAFU's airborne water.
    """

    #: The busiest row and its kilogram twin, unspecified air.
    BUSIEST_M3 = "ba3524e6-0d54-52a5-828f-8ad0267f1683"  # Water/m3
    BARE_KG = "6ed103e1-aa33-56e7-93e3-29eca1854827"  # Water, kg
    EVAPO_BARE = "cd61811d-4031-52b7-b106-73dcb33a3e34"  # Water (evapotranspiration)
    #: EF's m3 vapour flow in unspecified air -- the one ecoinvent's identical
    #: rows reach, and the match override's stated target.
    EF_VAPOUR_M3 = "0342f5e5-b53e-4cec-9e67-fb197f24fff0"

    def test_every_water_to_air_row_is_vapour(self):
        rows = {
            uuid: row
            for uuid, row in _agb_rows().items()
            if row["source_context"][:1] == ["Emissions to air"]
        }
        self.assertEqual(len(rows), 11)
        for uuid, row in rows.items():
            with self.subTest(name=row["source_name"], uuid=uuid):
                self.assertEqual(row["node"], "water_vapour")
                self.assertEqual(row["match"], "close")

    def test_the_air_rows_join_without_moving_a_water_intake(self):
        """The negative half: lifting the air carve-out adds exactly the
        eleven rows and reassigns nothing #352 already curated.  1,047 with
        the turbined discharge the crossing work added."""
        rows = _agb_rows()
        self.assertEqual(len(rows), 1047)
        self.assertEqual(rows[RIVER_FR_IN_WATER]["node"], "river_water")
        self.assertEqual(rows[WELL_BARE_HEADING]["node"], "groundwater")

    def test_the_sibling_lists_airborne_water_is_untouched(self):
        """BAFU's airborne water said vapour before this change and says it
        after: the air rule that now reads AGRIBALYSE's rows is the one that
        already read BAFU's, not a new one beside it."""
        bafu = [
            row
            for (source, _), row in material_by_source_flow().items()
            if source == "bafu-2026-v1"
            and row["source_context"][:1] == ["emissions to air"]
        ]
        self.assertTrue(bafu)
        for row in bafu:
            self.assertEqual(row["node"], "water_vapour")

    def test_the_override_names_the_flow_ecoinvent_reaches(self):
        """EF publishes two m3 vapour flows in unspecified air, so the busiest
        row's choice between them is stated, not guessed -- and stated as the
        flow ecoinvent's identical rows already reach."""
        from brightway_flows.filesystem import PACKAGE_DATA_DIR
        from brightway_flows.match_overrides import load_match_overrides

        overrides = load_match_overrides(
            PACKAGE_DATA_DIR / "agribalyse-3.2-match-overrides.json"
        )
        by_uuid = {row.source_uuid: row for row in overrides}
        # The file also carries #190's three resource and soil rows and the
        # thirteen density crossings; this test is about the one water-to-air
        # row.
        self.assertIn(self.BUSIEST_M3, by_uuid)
        self.assertEqual(by_uuid[self.BUSIEST_M3].target_uuid, self.EF_VAPOUR_M3)
