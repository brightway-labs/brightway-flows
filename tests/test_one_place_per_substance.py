"""One substance, one place it is taken from.

Where a substance is *released* is a fact about the process, and two release
contexts on one substance are two ordinary flows.  Where it is *taken from* is a
fact about the substance: peat comes out of the ground, wood off a living tree,
platinum out of rock, and no process chooses.  So a substance filed in two
intake places is two answers to a question that has one, and the list published
both -- two flows that look equally authoritative, are told apart by a
compartment a reader has no reason to distrust, and cannot be added together.

`merge/places.py` reports them; #89 counted nine on the build of `b03c940`, four
of them with a characterisation factor on one side and nothing on the other.
These tests are about the seventeen rules as *data*: which rows they move, where
to, and -- the half that matters more -- the rows in the same compartments they
must leave alone.  What the build then publishes is
`expectations/0450-one-place-per-substance.json`.
"""

from __future__ import annotations

import unittest

import orjson

from brightway_flows.context_mapping import MANUAL_MAPPING_FILEPATH

NS = "https://vocab.brightway.one/flow-contexts/"
WATER = NS + "reso-wate"
GROUND = NS + "reso-grou"
BIOTIC = NS + "reso-biot"
AIR = NS + "reso-air"
INDICATOR = NS + "inin"

BAFU = "bafu-2026-v1"
ECO312 = "ecoinvent-3.12"
EF = "EF 3.1"

#: Every row #89 rules on: (source, uuid) -> (destination, the compartment the
#: vendor ships it in).  Named by uuid because that is what the rule keys on and
#: because several of these names are also on flows that must not move --
#: `Platinum` is on twelve emission flows, `Water, well` on four rows that are
#: already right.
RULED = {
    # Groundwater: three BAFU rows minting a second `Groundwater` in the ground.
    (BAFU, "1cb76acd-05eb-5243-a882-de030c4836d0"): (WATER, ["resources", "in ground"]),
    (BAFU, "dd30b001-a2f2-5c50-b459-405d4e23e25d"): (WATER, ["resources", "in ground"]),
    (BAFU, "c13a514d-6615-592c-b0d2-af333adec22b"): (WATER, ["resources", "unspecified"]),
    # Water: five `Water, embodied in product` rows minting an `Economic` flow.
    (BAFU, "1eaa17ec-2a8f-5b7a-9f41-d7b4ba38ea44"): (WATER, ["economic issues", "unspecified"]),
    (BAFU, "d839a838-c091-5c51-8b35-45ece308a255"): (WATER, ["economic issues", "unspecified"]),
    (BAFU, "819a0461-b3c1-5307-aa7b-28329022a562"): (WATER, ["economic issues", "unspecified"]),
    (BAFU, "84f4ea65-3afd-5788-9190-f0a5318f852a"): (WATER, ["economic issues", "unspecified"]),
    (BAFU, "e24060b7-46ef-571c-9111-cd495936368a"): (WATER, ["economic issues", "unspecified"]),
    # Green water: a decision rather than a filing slip.
    (ECO312, "36dfb44d-db99-4cc5-bfb7-f266d69abf3e"): (AIR, ["natural resource", "in ground"]),
    # BAFU's peat, which is the fuel: the list publishes fuel peat as a ground
    # resource and BAFU files this row under `biotic`, so the compartment and
    # the substance disagree.  The *material* peat needs no rule at all -- EF
    # and ecoinvent both file it as biotic already, and that distinction is the
    # source lists' own.
    (BAFU, "0417d728-9c64-5755-9685-e547485968d4"): (GROUND, ["resources", "biotic"]),
    # Platinum and basalt: rock, filed as living or as taken from the air.
    (BAFU, "c553eed2-4503-5e24-9175-c710b92d0582"): (GROUND, ["resources", "biotic"]),
    (BAFU, "b226e506-4d57-50ee-92c1-f7b0cc344613"): (GROUND, ["resources", "biotic"]),
    (BAFU, "a8c0c6e7-47cd-56eb-b9c1-e29b295230e2"): (GROUND, ["resources", "in air"]),
    # The energy in wood, from the two compartments that are not `biotic`.
    (BAFU, "d00a990d-15ae-5ea8-95ff-08c2afd27568"): (BIOTIC, ["resources", "in air"]),
    (BAFU, "feece912-d5e6-5bb7-bac0-166faf4f9552"): (BIOTIC, ["resources", "unspecified"]),
    # The landfill pair: accounting entries filed as things dug out of the ground.
    (BAFU, "c31ff9aa-30f6-5793-8c0a-607e039d1b27"): (INDICATOR, ["resources", "in ground"]),
    (BAFU, "6301844f-2f4d-5352-980a-3e16dbb0e8dc"): (INDICATOR, ["resources", "in ground"]),
}

#: BAFU's four well-water rows that were already right, and must stay untouched.
#: They are in `resources / in water`, reach EF 3.1's groundwater and its 209
#: factors, and a rule that read the *name* `Water, well` rather than the uuid
#: would have swept them up and re-answered a question they had already answered.
WELL_WATER_ALREADY_RIGHT = (
    "c7887393-ba5e-545d-a1ab-9fd05d26d62c",
    "c21c8f44-7ba2-5f7f-8c04-7e765c8ac47b",
    "8908ed8f-7c01-54dd-bd95-fe5a1a1704ff",
    "9c22bd27-3a4d-5519-8e9d-e843f18786a7",
)

#: BAFU's biotic compartment holds twelve names and eight of them really are
#: biotic.  A rule that moved the compartment rather than the rows would be a
#: different change, and wrong in the direction this one is right in.
GENUINELY_BIOTIC = ("wood", "peat", "energy, gross calorific value, in biomass")


def _rows() -> list[dict]:
    payload = orjson.loads(MANUAL_MAPPING_FILEPATH.read_bytes())
    return payload["flow_specific_context_mappings"]


def _by_key() -> dict[tuple[str, str], dict]:
    return {(r.get("source"), r.get("source_uuid")): r for r in _rows()}


class EveryRuledRowIsStatedTestCase(unittest.TestCase):
    """The seventeen rows, each sending one flow to one place."""

    def setUp(self):
        self.rows = _by_key()

    def test_every_row_has_a_rule(self):
        for key in RULED:
            with self.subTest(key):
                self.assertIn(key, self.rows, f"no rule for {key[0]} {key[1]}")

    def test_every_rule_sends_it_where_the_issue_says(self):
        for key, (destination, _) in RULED.items():
            with self.subTest(key):
                self.assertEqual(self.rows[key]["context_iri"], destination)

    def test_every_rule_records_the_compartment_it_overrules(self):
        """Not decoration: it is what makes a stale row fail loudly.

        A rule naming a flow by uuid keeps applying after the vendor moves that
        flow to another compartment, and the reasoning that justified it was
        about the old one.  `flow_context_iri` raises on a mismatch.
        """
        for key, (_, compartment) in RULED.items():
            with self.subTest(key):
                self.assertEqual(self.rows[key]["source_context"], compartment)

    def test_every_rule_says_why_and_cites_the_issue(self):
        for key in RULED:
            with self.subTest(key):
                comment = self.rows[key]["comment"]
                self.assertIn("#89", comment)
                self.assertGreater(len(comment), 200, "a rule that cannot say why")


class NoWaterIsTakenOutOfTheGroundTestCase(unittest.TestCase):
    """The half of #89 that changes published numbers.

    Water pumped out of an aquifer is not a mineral dug out of rock.  Every
    BAFU water row that reached `Resource / Ground` is sent to water; none is
    sent anywhere else.
    """

    def setUp(self):
        self.rows = _by_key()

    def test_the_three_groundwater_rows_go_to_water(self):
        for uuid in (
            "1cb76acd-05eb-5243-a882-de030c4836d0",
            "dd30b001-a2f2-5c50-b459-405d4e23e25d",
            "c13a514d-6615-592c-b0d2-af333adec22b",
        ):
            with self.subTest(uuid):
                self.assertEqual(self.rows[(BAFU, uuid)]["context_iri"], WATER)

    def test_the_embodied_water_rows_go_to_water(self):
        embodied = [
            key for key, (dest, ctx) in RULED.items()
            if ctx == ["economic issues", "unspecified"]
        ]
        self.assertEqual(len(embodied), 5)
        for key in embodied:
            with self.subTest(key):
                self.assertEqual(self.rows[key]["context_iri"], WATER)

    def test_no_bafu_water_row_is_sent_to_the_ground(self):
        """The rule that must not exist, stated as a test.

        This is the whole of the user-facing defect: a water row in
        `Resource / Ground` carries no factor while the flow beside it carries
        209, and an inventory reaching the wrong one scores zero.
        """
        for row in _rows():
            name = str(row.get("source_name") or "").lower()
            if row.get("source") == BAFU and name.startswith("water,"):
                with self.subTest(row.get("source_uuid")):
                    self.assertNotEqual(row["context_iri"], GROUND)


class TheRowsThatWereAlreadyRightAreLeftAloneTestCase(unittest.TestCase):
    """A rule keyed on a name rather than a uuid would re-answer these.

    Names are the evidence of last resort here.  `Water, well` names six BAFU
    rows: four are in `resources / in water` and already reach EF 3.1's
    groundwater with its 209 factors, and only two are the defect.
    """

    def setUp(self):
        self.rows = _by_key()

    def test_no_rule_touches_the_four_correct_well_water_rows(self):
        for uuid in WELL_WATER_ALREADY_RIGHT:
            with self.subTest(uuid):
                self.assertNotIn((BAFU, uuid), self.rows)

    def test_no_rule_moves_a_row_out_of_bafus_water_compartment(self):
        """`resources / in water` is BAFU's one reliable water compartment.

        Every row #89 moves is going *into* water; none is coming out of it.
        """
        for row in _rows():
            if row.get("source") != BAFU:
                continue
            if row.get("source_context") == ["resources", "in water"]:
                self.fail(f"rule moves a correctly filed row: {row['source_uuid']}")

    def test_nothing_genuinely_biotic_is_moved_out_of_biotic(self):
        moved_from_biotic = {
            str(self.rows[key]["source_name"]).lower()
            for key, (dest, ctx) in RULED.items()
            if ctx[-1] == "biotic" and dest != BIOTIC
        }
        # BAFU's peat leaves `biotic` because it is the fuel, which the list
        # publishes as a ground resource.  The *material* peat stays: EF and
        # ecoinvent both file it as biotic, and no rule touches it.
        self.assertEqual(moved_from_biotic, {"platinum", "basalt", "peat"})
        for name in GENUINELY_BIOTIC:
            if name == "peat":
                continue
            with self.subTest(name):
                self.assertNotIn(name, moved_from_biotic)


class TheTwoPeatsAreTwoSubstancesTestCase(unittest.TestCase):
    """Horticultural peat and fuel peat are not one substance measured twice.

    EF 3.1 ships both and tells them apart by compartment and unit: `peat` is a
    non-renewable *energy* resource from the ground in megajoules, carrying
    `Resource use, fossils` at 1.0; `Peat, in ground` is a renewable *material*
    resource in kilograms, carrying nothing.  The first is peat burned as fuel,
    counted by its energy; the second is peat sold as a growing medium, counted
    by its mass.

    #89 first sent ecoinvent's kilogram row to the megajoule flow, which merged
    the two, crossed a unit, and dropped the ecoinvent Centre's own factor for
    the material peat -- 9.76 per kilogram, peat's calorific value, wrong by an
    order of magnitude against megajoules.  The rename is what keeps them apart
    and the rules are what put the material one in a single place.
    """

    #: The two peats, by uuid, because both are called some form of `peat`.
    MATERIAL = "126514fa-415f-454a-8425-aa5d54a1402b"
    BAFU_BIOTIC = "0417d728-9c64-5755-9685-e547485968d4"
    ENERGETIC = "e2fba107-6555-11dd-ad8b-0800200c9a66"

    #: Every fixes file that renames the material peat, and the vendor spelling
    #: each one replaces.  All of them, or the releases disagree about what the
    #: substance is (#26).
    RENAMES = {
        "ef-3.1": ("126514fa-415f-454a-8425-aa5d54a1402b", "Peat, in ground"),
        "ecoinvent-3.12": ("c5035ce2-5ee5-431f-a287-4b25da42be74", "Peat"),
        "ecoinvent-3.11": ("c5035ce2-5ee5-431f-a287-4b25da42be74", "Peat"),
        "ecoinvent-3.10.1": ("c5035ce2-5ee5-431f-a287-4b25da42be74", "Peat"),
        "ecoinvent-3.9.1": ("c5035ce2-5ee5-431f-a287-4b25da42be74", "Peat"),
        "ecoinvent-3.8": ("c5035ce2-5ee5-431f-a287-4b25da42be74", "Peat, in ground"),
    }
    NEW_NAME = "Peat, horticulture"

    def _fixes(self, stem: str) -> list[dict]:
        from brightway_flows.filesystem import PACKAGE_DATA_DIR

        path = PACKAGE_DATA_DIR / f"{stem}-manual-fixes.json"
        return orjson.loads(path.read_bytes())["fixes"]

    def test_every_release_renames_the_material_peat(self):
        for stem, (uuid, original) in self.RENAMES.items():
            with self.subTest(stem):
                renames = [
                    f for f in self._fixes(stem)
                    if f.get("uuid") == uuid and f.get("field") == "name"
                ]
                self.assertEqual(len(renames), 1, "one rename, or none")
                self.assertEqual(renames[0]["new_value"], self.NEW_NAME)
                self.assertEqual(renames[0]["original_value"], original)

    def test_the_vendor_spelling_stays_searchable(self):
        """An inventory written against these lists holds no other string."""
        for stem, (uuid, _) in self.RENAMES.items():
            with self.subTest(stem):
                rename = next(
                    f for f in self._fixes(stem)
                    if f.get("uuid") == uuid and f.get("field") == "name"
                )
                self.assertTrue(rename.get("retain_original_as_synonym"))

    def test_the_energetic_peat_is_not_renamed_or_moved(self):
        """The half that must not move.

        EF's megajoule peat is where the `Resource use, fossils` factor is and
        is already filed in the ground. A correction that touched it would be
        answering a question nobody asked.
        """
        for fix in self._fixes("ef-3.1"):
            with self.subTest(fix.get("uuid")):
                self.assertNotEqual(fix.get("uuid"), self.ENERGETIC)
        self.assertNotIn(("EF 3.1", self.ENERGETIC), _by_key())

    def test_the_material_peat_needs_no_context_rule_at_all(self):
        """The source lists already agree about where it comes from.

        EF 3.1 files it under `Resources from biosphere` and ecoinvent under
        `natural resource / biotic`, and both compartments map to `Resource /
        Biotic`, so the renamed rows meet on EF's flow without anything being
        moved.  An earlier revision of #89 sent them all to `Resource /
        Ground`, which was unnecessary and collapsed the distinction the two
        lists draw between the two peats: it left the *name* as the only thing
        telling horticultural peat from fuel peat, where the sources tell them
        apart by compartment and by unit as well.
        """
        rows = _by_key()
        for key in rows:
            with self.subTest(key):
                self.assertNotIn(
                    key[1],
                    {self.MATERIAL, "c5035ce2-5ee5-431f-a287-4b25da42be74"},
                    "the material peat should need no rule",
                )

    def test_the_two_compartments_the_sources_use_stay_apart(self):
        """Fuel peat in the ground, material peat in the biosphere."""
        from brightway_flows.context_mapping import context_iri_by_source_context

        ef = context_iri_by_source_context("EF 3.1")
        self.assertEqual(
            ef[("resources", "resources from ground",
                "non-renewable energy resources from ground")],
            GROUND,
        )
        self.assertEqual(
            ef[("resources", "resources from biosphere",
                "renewable material resources from biosphere")],
            BIOTIC,
        )
        eco = context_iri_by_source_context("ecoinvent-3.12")
        self.assertEqual(eco[("natural resource", "biotic")], BIOTIC)

    def test_bafu_peat_is_the_one_row_that_moves(self):
        """It is the fuel, and the list publishes fuel peat in the ground."""
        from brightway_flows.context_mapping import flow_context_iri

        self.assertEqual(
            flow_context_iri(BAFU, self.BAFU_BIOTIC, ["resources", "biotic"]),
            GROUND,
        )


class WaterOfUnstatedOriginIsNotGroundwaterTestCase(unittest.TestCase):
    """The material this change had to withdraw along with the compartment.

    `Water, process, unspecified natural origin` was curated as `groundwater`
    for exactly one of its six rows -- the one filed in `resources / in ground`
    -- and the reason recorded in `water-flow-materials.json` was "the name says
    unspecified *origin*, and the compartment supplies it".  #89 is the finding
    that the compartment does not supply it: BAFU writes this name into four
    compartments and 54 of the 60 in-ground datasets carry the land and
    unspecified rows beside it, so it is one withdrawal written four times.

    Left alone, moving the row out of the ground would still have published it
    as a *different substance* from its five siblings -- groundwater rather than
    water -- on evidence this change removes.  A rule standing on a withdrawn
    premise is the thing worth testing for.
    """

    BAFU = "bafu-2026-v1"

    #: All six rows of the name, in the four compartments BAFU files it under.
    PROCESS_WATER = (
        "1cb76acd-05eb-5243-a882-de030c4836d0",  # in ground -- the one that moved
        "10d2fcee-f4ee-513b-baa3-671353a34df6",  # land
        "73f0a5ef-ddb2-5c74-876a-1eb50b695ac5",  # unspecified
        "8b11be39-c8a8-5db2-8ec6-0adf69830e77",  # land, m3
        "17fde9eb-4767-5355-a586-2b35fc61649f",  # unspecified, m3
        "a038808c-51a4-53fc-aaae-c71cb3e1fec5",  # in water, m3
    )

    #: A well names its body, so these stay `groundwater` -- including the two
    #: #89 moves.  The material is read from the name, and the name says well.
    WELL_WATER = (
        "dd30b001-a2f2-5c50-b459-405d4e23e25d",
        "c13a514d-6615-592c-b0d2-af333adec22b",
        *WELL_WATER_ALREADY_RIGHT,
    )

    def test_every_process_water_row_is_plain_water(self):
        from brightway_flows.domain.materials import material_for_source_flow

        for uuid in self.PROCESS_WATER:
            with self.subTest(uuid):
                self.assertEqual(material_for_source_flow(self.BAFU, uuid), "water")

    def test_well_water_keeps_its_body(self):
        """The half that must not move.

        The compartment was wrong evidence for the process-water row; the
        *name* is right evidence for these, and a correction that read the two
        the same way would have taken the aquifer off the well rows too.
        """
        from brightway_flows.domain.materials import material_for_source_flow

        for uuid in self.WELL_WATER:
            with self.subTest(uuid):
                self.assertEqual(
                    material_for_source_flow(self.BAFU, uuid), "groundwater"
                )


class OneFlowOneRuleTestCase(unittest.TestCase):
    """Two curated statements about one flow would be arbitrated by file order.

    `flow_context_rules` raises on a duplicate rather than picking one, which is
    the silent arbitration this project is removing; this says the file it reads
    does not contain one.
    """

    def test_no_flow_is_ruled_twice(self):
        seen: set[tuple[str, str]] = set()
        for row in _rows():
            key = (row.get("source"), row.get("source_uuid"))
            with self.subTest(key):
                self.assertNotIn(key, seen)
            seen.add(key)

    def test_the_rules_load(self):
        """A missing required field is a load error, not a silently inert row."""
        from brightway_flows.context_mapping import flow_context_rules

        for source in (BAFU, ECO312):
            with self.subTest(source):
                rules = flow_context_rules(source)
                for (src, uuid) in RULED:
                    if src == source:
                        self.assertIn(uuid, rules)


class TheRuleIsAppliedAsWrittenTestCase(unittest.TestCase):
    """`flow_context_iri` is what the merge and the transform both read.

    Both halves: the compartment the rule was written about gets the curated
    answer, and a flow the vendor has since moved raises rather than being
    moved on reasoning that no longer describes it.
    """

    def test_a_ruled_row_gets_the_curated_context(self):
        from brightway_flows.context_mapping import flow_context_iri

        for (source, uuid), (destination, compartment) in RULED.items():
            with self.subTest((source, uuid)):
                self.assertEqual(
                    flow_context_iri(source, uuid, compartment), destination
                )

    def test_a_row_the_vendor_moved_raises(self):
        from brightway_flows.context_mapping import (
            FlowContextRuleError,
            flow_context_iri,
        )

        with self.assertRaises(FlowContextRuleError):
            flow_context_iri(
                BAFU,
                "dd30b001-a2f2-5c50-b459-405d4e23e25d",
                ["resources", "in water"],
            )

    def test_an_unruled_row_is_left_to_its_compartment(self):
        from brightway_flows.context_mapping import flow_context_iri

        for uuid in WELL_WATER_ALREADY_RIGHT:
            with self.subTest(uuid):
                self.assertIsNone(
                    flow_context_iri(BAFU, uuid, ["resources", "in water"])
                )


if __name__ == "__main__":
    unittest.main()
