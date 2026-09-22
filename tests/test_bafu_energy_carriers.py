"""BAFU's energy carriers are flows the list already has, not new substances.

BAFU 2026 states the same fossil and nuclear carriers twice, in two quantity
kinds.  Six `Energy, from X` rows give them in megajoules; `Coal, hard`,
`Coal, brown`, `Oil, crude`, `Peat` and `Uranium` give them in kilograms, and
`Gas, natural/m3` and the coal-mine off-gas give them by volume.  Read as names
the megajoule rows look like a quantity no flow list should carry -- energy is
not a substance -- and #69 raised them on that basis, as a second view of a mass
the inventory has usually already recorded.

Both readings are wrong, and the difference decides whether these rows are
filtered or merged.

**EF 3.1 accounts fossil energy carriers by energy content on purpose.**
`hard coal`, `brown coal`, `crude oil`, `peat` and `uranium` are all declared in
MJ, not kg, and the list publishes them that way.  So BAFU's `Energy, from coal`
is not a second view of `Hard Coal` -- in the same unit and the same compartment,
it *is* `Hard Coal`, and BAFU's `Coal, hard` in kilograms is the same substance
again on the other side of a mass-to-energy conversion.

**The two conventions never meet.**  Measured over all 11,947 datasets in the
BAFU 2026 ecoSpold release, the energy row and the mass row for one carrier never
appear in the same dataset: not once, for any of them.  That settles what #3
left open, which named this exact pair -- `Coal, brown` in kg beside
`Energy, from coal, brown` in MJ -- as two coexisting conventions whose merge
"still double-counts", and asked for a flag.  The overlap is empty, so sharing a
flow counts nothing twice and no flag is needed.

BAFU declares no correspondence table, so there is no published decision to
override -- `apply_match_overrides` appends instead, which is the path a list
with no table takes for every row.

The two groups are held to opposite rules about conversion, and that asymmetry is
the point:

- The **six MJ rows carry no factor**, and that is the finding rather than an
  omission.  Between two MJ rows there is nothing to convert, and
  `_validate_conversion` refuses a factor `units.json` already states.
- The **nine mass and volume rows all carry one**, because there the units
  really do cross quantity kinds.  Each pair is also accepted in
  `unit-change-allowlist.json` -- this file supplies the number, that file
  accepts the crossing.

Where the numbers come from is not one source, and the test data records the
value rather than the provenance, so it is worth stating here.  Every factor is
the one this project already applies to ecoinvent's flow onto the same target, so
that two source lists reaching one flow reach it by one conversion.  For hard
coal, brown coal, crude oil, uranium and gas that is the EF 3.1 LCIA method as
implemented by the ecoinvent Centre; only peat is an IPCC 2006 Table 1.2 value,
and only because no ecoinvent association for peat has ever existed.  For the
coals the two bases are far apart -- 18.01 against IPCC's 25.8 -- which is a
question about the target flow rather than about these rows.

Five of these rows would otherwise be `created` or unmatched.  EF declares no kg
flow for the coals and oil to match, so algorithmic matching mints a duplicate
substance beside the one every other list shares, and both natural gas rows
reached nothing at all.  The other four already matched, but with the units
disagreeing and no factor, so the mapping was right and only the number missing.

BAFU spells the gas unit `Nm3` in some datasets and `m3` in others.  Both take
the same factor, because for gas the two name the same quantity; see
`GasVolumeTestCase` and `TheGasUnitsAgree`.

Only natural gas is here.  BAFU's coal-mine off-gas is a different substance
(#80) with its own EF flow, and it needs no override: its `Nm3` spelling
matches once the registry number stops pointing both names at one flow, and its
`m3` spelling waits on #67 to take the unit back out of its name.
"""

import unittest

from brightway_flows.domain.units import (
    build_units_index,
    resolve_unit_notation,
    unit_row_for,
)
from brightway_flows.merge.unit_changes import canonical_unit
from brightway_flows.match_overrides import apply_match_overrides, load_match_overrides
from brightway_flows.sources import PACKAGE_DATA_DIR, resolve_source_list

OVERRIDES_FILE = "bafu-2026-v1-match-overrides.json"
OVERRIDES_PATH = PACKAGE_DATA_DIR / OVERRIDES_FILE
ALLOWLIST_PATH = PACKAGE_DATA_DIR / "unit-change-allowlist.json"

HARD_COAL = "fe0acd60-3ddc-11dd-a6fc-0050c2490048"
BROWN_COAL = "fe0acd60-3ddc-11dd-a6f9-0050c2490048"
CRUDE_OIL = "fe0acd60-3ddc-11dd-a6f8-0050c2490048"
PEAT = "e2fba107-6555-11dd-ad8b-0800200c9a66"
URANIUM = "3e4d2966-6556-11dd-ad8b-0800200c9a66"
HYDRO = "e89f564c-7250-4fee-b759-dc8b42fe62bf"
NATURAL_GAS = "fe0acd60-3ddc-11dd-a6fa-0050c2490048"

#: BAFU's megajoule rows.  Every target is MJ, which is the whole point: EF 3.1
#: accounts these by energy content, so no unit changes and no factor is needed.
ENERGY_ROWS = {
    "3d3fcad0-110b-549b-9092-7d8cafc44fb4": ("Energy, from coal", HARD_COAL, "hard coal"),
    "156b4e11-1135-5657-b345-dec81c8918f3": ("Energy, from coal, brown", BROWN_COAL, "brown coal"),
    "16b4382a-901e-52a0-a8f4-816b157b8f56": ("Energy, from oil", CRUDE_OIL, "crude oil"),
    "b2b18479-42c0-51f4-9da9-27df4541fb8b": ("Energy, from peat", PEAT, "peat"),
    "32f249ab-b66f-5a1f-87b0-658b3704103d": ("Energy, from uranium", URANIUM, "uranium"),
    "7ce60787-e722-5bfd-b595-a8924e189472": (
        "Energy, from hydro power", HYDRO, "Energy, potential (in hydropower reservoir), converted",
    ),
}

#: BAFU's mass and volume rows for those same carriers, and the factor that takes
#: each one to the megajoule flow.  Uranium appears three times because BAFU files
#: it in three compartments, each with its own uuid, and natural gas appears
#: twice, once per unit spelling.
MASS_ROWS = {
    "d144bede-fdfa-580c-ad08-4fbaf0b35291": ("Coal, hard", HARD_COAL, 18.01),
    "80922cad-30bf-5248-ae0a-656cae92b95c": ("Coal, brown", BROWN_COAL, 9.41),
    # The one carrier here whose number is BAFU's own rather than ecoinvent's.
    # `Cement ZN, D, at plant [CH]` carries both this flow and `Energy, from
    # oil` and implies 43.1 MJ/kg; the row took ecoinvent's 43.4 until #162, on
    # a rule that one target takes one conversion whichever list the kilogram
    # came from. That rule was for lists with no number of their own, which is
    # every other row here, and BAFU has one for this row.
    "e48b3dc1-e9e7-54c1-aafb-3332dbd06a3e": ("Oil, crude", CRUDE_OIL, 43.1),
    "25d290ab-0e08-5963-9141-cbcbb998c559": ("Peat", PEAT, 9.76),
    # BAFU's main peat row, from the `biotic` compartment. It is the same
    # substance as the row above -- the archive shows it is the extraction
    # for `Peat, at mine`, filed under `fuels / peat` -- so it takes the same
    # calorific value (#89).
    "0417d728-9c64-5755-9685-e547485968d4": ("Peat", PEAT, 9.76),
    "dbfc8434-b713-5719-94bf-3b6643530e07": ("Uranium", URANIUM, 560000.0),
    "8daa605b-050a-50ea-800d-e491a93eb282": ("Uranium", URANIUM, 560000.0),
    "108c7884-7e7d-5765-a951-3276d4e09499": ("Uranium", URANIUM, 560000.0),
    "528d5071-4006-5f56-adc9-b39f23d13a03": ("Gas, natural/m3", NATURAL_GAS, 36.0),
    "99bbee18-e1d0-5600-82df-d0bfa91394c7": ("Gas, natural", NATURAL_GAS, 36.0),
}

#: BAFU's coal-mine off-gas, which is *not* here.  #80 established that gas
#: drawn off a coal seam is a different substance from natural gas, and EF
#: carries it separately; an earlier revision of this file sent both spellings to
#: natural gas, which was the same conflation #80 removed everywhere else.
COAL_MINE_OFF_GAS = {
    "8fd7095d-f33f-580a-8018-2d24479170ca",   # Nm3; matches EF's own flow
    "4ffc062b-520e-5bf6-bc4d-3c16db9c1113",   # m3; still unmatched, waiting on #67
}

#: The natural gas row BAFU spells in `Nm3` rather than `m3`.  It states `sm3`,
#: because that is what `Nm3` normalises to and the merge resolves a source unit
#: before it builds the pair a factor is checked against.
NM3_ROWS = {"99bbee18-e1d0-5600-82df-d0bfa91394c7"}

#: Empty, and kept so that the assertion below stays an assertion about what
#: the file holds rather than about what somebody remembered putting in it.
#:
#: It used to hold BAFU's kilogram of biotic peat, which #87 routed to the
#: *other* peat EF 3.1 ships -- the material one, in kilograms -- on the reading
#: that a mass of peat is that substance and a megajoule of peat is the carrier.
#: #89 measured what BAFU actually does with the row: it is the extraction
#: input to `Peat, at mine`, one kilogram per kilogram, and that dataset is
#: filed under `fuels / peat` and feeds `Peat, burned in power plant`.  So it is
#: an energy carrier recorded as a mass, which is what every other row in
#: `MASS_ROWS` is, and it moved there.
NOT_A_CARRIER: dict[str, tuple[str, str]] = {}

#: BAFU's carbon dioxide rows whose target no rule can reach, for the same reason
#: they share the file: a list with no correspondence table has one place to put a
#: curated target.  Three say `in air`, which is a compartment and not an origin,
#: so nothing in the name can carry them to EF's biogenic uptake from air; two say
#: nothing at all, and the evidence that they are fossil is in BAFU's own datasets
#: rather than in anything this pipeline can read.  Their reasoning is in the file
#: and in #135 and #139 §17; named here so the assertion below stays an assertion
#: about what the file holds.
CARBON_DIOXIDE_ROWS = {
    "94b15b96-c2b5-5dfc-acb4-0cec3414d037": (
        "Carbon dioxide, in air", "da174fac-e567-42d3-99b5-a688913dc88e",
    ),
    "38e9ff00-8bf9-5a6f-aee4-1033bf899e94": (
        "Carbon dioxide, in air", "da174fac-e567-42d3-99b5-a688913dc88e",
    ),
    "513f1d03-fdd8-5906-9eee-00ef20a0dea8": (
        "Carbon dioxide, in air", "da174fac-e567-42d3-99b5-a688913dc88e",
    ),
    "2c3a4703-fb4e-5333-b38d-ed5c4e05f304": (
        "Carbon dioxide", "08a91e70-3ddc-11dd-9c13-0050c2490048",
    ),
    "8658d26b-02b4-5e39-b010-15ed7c1eb2ed": (
        "Carbon dioxide", "08a91e70-3ddc-11dd-923d-0050c2490048",
    ),
}

#: The one row here that is neither a carrier nor a substance disagreement: a
#: density.  BAFU states the volume of sea water and EF 3.1 states its mass, so
#: the pair crosses quantity kinds and `units.json` has no answer to defer to --
#: and BAFU declares no correspondence table, so an override is the only place a
#: factor for one of its rows can be written.  ecoinvent ships the same vendor
#: name against the same target and carries the same 1025 kg/m3 from its own
#: table; two lists shipping one row should not be treated differently (#78).
DENSITY_ROWS = {
    "44360b86-a3d8-5623-b211-44ec41853fcd": (
        "Water, salt, ocean", "172a3db9-6556-11dd-ad8b-0800200c9a66", 1025.0,
    ),
}

#: Not energy carriers at all, but rows of this file all the same: BAFU ships
#: the titanium-ore flow in ecoinvent 3.8's old spelling under its own uuids,
#: and the 0.599 kg-of-titanium-per-kg-of-ore decision covers them (#141,
#: moved here from the ecoinvent file by review on #336 -- an override lives
#: in the file of the list whose uuids it names).  Their factors are tested
#: beside the ecoinvent siblings' in `test_conversion_multipliers.py`.
ORE_ROWS = {
    "52b760ca-3444-564a-a215-271d4af41250",
    "73746710-2506-50d1-811a-521b48526172",
}

#: BAFU's five `Hydrocarbons, unspecified` rows, curated onto EF's
#: `hydrocarbons (unspecified)` because the name differs from EF's only in
#: punctuation and nothing else on the row can match (#178).  Enumerated here so
#: that the file's whole content stays accounted for; the rows themselves are
#: tested in `test_hydrocarbons_unspecified_targets.py`.
HYDROCARBON_ROWS = {
    "3a47b869-9ac2-5e24-b6cd-d695188a0cb7",
    "3b50226c-c9ab-5cbf-9af7-2da71da1e042",
    "612a6cef-d1e7-524d-a3c3-c664e7c20e51",
    "21aa7a0c-606f-5d29-b960-a50c2f5bc0dd",
    "83944839-e21a-5c7d-92c0-70ee8dbc60a4",
}

#: The unit each row is stated in.  Gas is by volume in two spellings, everything
#: else by mass, and the guard refuses a factor whose pair it cannot check.
MASS_ROW_UNITS = {
    uuid: ("sm3" if uuid in NM3_ROWS else "m3" if "Gas" in name else "kg")
    for uuid, (name, _, _) in MASS_ROWS.items()
}


class OverrideFileTestCase(unittest.TestCase):
    """What the checked-in file says."""

    def setUp(self):
        self.rows = load_match_overrides(OVERRIDES_PATH)
        self.by_source = {row.source_uuid: row for row in self.rows}

    def test_every_carrier_has_a_target_in_both_units(self):
        self.assertEqual(
            set(self.by_source),
            set(ENERGY_ROWS) | set(MASS_ROWS) | set(NOT_A_CARRIER)
            | set(DENSITY_ROWS) | set(CARBON_DIOXIDE_ROWS) | ORE_ROWS
            | HYDROCARBON_ROWS,
        )

    def test_the_density_row_states_its_pair_and_its_factor(self):
        """A density is checkable only against the units it is stated between,
        so the row has to name both -- the merge refuses a factor whose pair it
        cannot check against the mapping it builds."""
        for source_uuid, (source_name, target_uuid, factor) in DENSITY_ROWS.items():
            with self.subTest(source_name):
                row = self.by_source[source_uuid]
                self.assertEqual(row.source_name, source_name)
                self.assertEqual(row.target_uuid, target_uuid)
                self.assertTrue(row.converts)
                self.assertEqual(row.conversion_factor, factor)
                self.assertEqual(row.source_unit, "m3")
                self.assertEqual(row.target_unit, "kg")

    def test_every_row_in_this_file_is_an_energy_carrier_or_named_otherwise(self):
        """`NOT_A_CARRIER` is empty, and this is what would notice it filling.

        A row that reaches a curated target without crossing a unit is not
        wrong, but it is a different kind of claim from the rest of this file,
        and the last one to sit here unremarked was on the wrong substance for
        two releases (#87, corrected by #89).
        """
        self.assertEqual(NOT_A_CARRIER, {})

    def test_each_energy_row_reaches_the_flow_the_list_already_has(self):
        for source_uuid, (source_name, target_uuid, target_name) in ENERGY_ROWS.items():
            with self.subTest(source_name):
                row = self.by_source[source_uuid]
                self.assertEqual(row.source_name, source_name)
                self.assertEqual(row.target_uuid, target_uuid)
                self.assertEqual(row.target_name, target_name)

    def test_no_energy_row_states_a_conversion_factor(self):
        # Both sides are already MJ.  A factor here would be a mass-to-energy
        # calorific value applied to a row that carries no mass.
        for source_uuid, (source_name, _, _) in ENERGY_ROWS.items():
            with self.subTest(source_name):
                self.assertFalse(self.by_source[source_uuid].converts)

    def test_each_mass_row_reaches_the_same_flow_as_its_energy_twin(self):
        for source_uuid, (source_name, target_uuid, _) in MASS_ROWS.items():
            with self.subTest(f"{source_name} {source_uuid[:8]}"):
                self.assertEqual(self.by_source[source_uuid].target_uuid, target_uuid)

    def test_every_mass_row_states_its_factor_between_its_unit_and_mj(self):
        for source_uuid, (source_name, _, factor) in MASS_ROWS.items():
            with self.subTest(f"{source_name} {source_uuid[:8]}"):
                row = self.by_source[source_uuid]
                self.assertEqual(row.conversion_factor, factor)
                self.assertEqual(row.source_unit, MASS_ROW_UNITS[source_uuid])
                self.assertEqual(row.target_unit, "MJ")

    def test_the_two_groups_do_not_overlap(self):
        # A carrier stated in both units is two source flows, never one.
        self.assertEqual(set(ENERGY_ROWS) & set(MASS_ROWS), set())

    def test_no_row_declines(self):
        # A decline leaves the flow to algorithmic matching, which is what
        # minted the separate substances this file exists to remove.
        for row in self.rows:
            with self.subTest(row.source_name):
                self.assertFalse(row.decline)

    def test_every_row_carries_its_reasoning(self):
        for row in self.rows:
            with self.subTest(row.source_name):
                self.assertTrue(row.comment.strip())


class AllowlistTestCase(unittest.TestCase):
    """A stated factor is not the same as an accepted dimension crossing.

    The override file supplies the number; `unit-change-allowlist.json` is where
    the kg-to-MJ crossing is accepted.  A mass row in one and not the other would
    either convert without review or be reported as a defect every run.
    """

    def setUp(self):
        import orjson
        payload = orjson.loads(ALLOWLIST_PATH.read_bytes())
        self.accepted = {
            (entry["source_uuid"], entry["target_elementary_flow_id"]): entry
            for entry in payload["accepted"]
        }

    def test_every_mass_row_has_its_crossing_accepted(self):
        for source_uuid, (source_name, target_uuid, _) in MASS_ROWS.items():
            with self.subTest(f"{source_name} {source_uuid[:8]}"):
                self.assertIn((source_uuid, target_uuid), self.accepted)

    def test_each_accepted_pair_agrees_with_the_override_on_units(self):
        for source_uuid, (source_name, target_uuid, _) in MASS_ROWS.items():
            with self.subTest(f"{source_name} {source_uuid[:8]}"):
                entry = self.accepted[(source_uuid, target_uuid)]
                self.assertEqual(entry["source_unit"], MASS_ROW_UNITS[source_uuid])
                self.assertEqual(entry["target_unit"], "MJ")
                self.assertTrue(entry["comment"].strip())

    def test_no_energy_row_is_listed(self):
        # MJ to MJ is not a dimension crossing and has nothing to accept.
        for source_uuid, (source_name, target_uuid, _) in ENERGY_ROWS.items():
            with self.subTest(source_name):
                self.assertNotIn((source_uuid, target_uuid), self.accepted)


class ManifestTestCase(unittest.TestCase):
    """That the file is wired to the list, not merely checked in."""

    def setUp(self):
        self.source = resolve_source_list("bafu-2026-v1")

    def test_the_manifest_names_the_override_file(self):
        self.assertIsNotNone(self.source.match_overrides_path)
        self.assertEqual(self.source.match_overrides_path.name, OVERRIDES_FILE)

    def test_the_file_is_on_disk(self):
        self.assertEqual(self.source.missing_curated_inputs(), [])

    def test_a_list_with_no_table_gets_every_row_appended(self):
        # BAFU declares no correspondence table, so nothing is rewritten and the
        # prepared table is exactly these rows.
        rows = apply_match_overrides([], self.source.match_overrides_path, label="bafu")
        expected = (
            set(ENERGY_ROWS) | set(MASS_ROWS) | set(NOT_A_CARRIER)
            | set(DENSITY_ROWS) | set(CARBON_DIOXIDE_ROWS) | ORE_ROWS
            | HYDROCARBON_ROWS
        )
        self.assertEqual(len(rows), len(expected))
        self.assertEqual({row["source"]["uuid"] for row in rows}, expected)
        for row in rows:
            with self.subTest(row["source"]["uuid"][:8]):
                self.assertEqual(row["route"], "override")

    def test_a_mass_row_carries_its_unit_so_the_factor_can_be_checked(self):
        # `override_source_side` emits the source unit only where a conversion
        # is stated, and the merge refuses a factor it cannot check against the
        # pair it builds.
        rows = {r["source"]["uuid"]: r for r in
                apply_match_overrides([], self.source.match_overrides_path)}
        for source_uuid, (source_name, _, factor) in MASS_ROWS.items():
            with self.subTest(f"{source_name} {source_uuid[:8]}"):
                row = rows[source_uuid]
                self.assertEqual(row["conversion_factor"], factor)
                self.assertEqual(row["source"]["unit"], MASS_ROW_UNITS[source_uuid])

    def test_applying_twice_is_applying_once(self):
        once = apply_match_overrides([], self.source.match_overrides_path)
        twice = apply_match_overrides(once, self.source.match_overrides_path)
        self.assertEqual(once, twice)


class GasVolumeTestCase(unittest.TestCase):
    """Both spellings of a cubic metre take the same factor, because they are one.

    For natural gas a normal cubic metre and a standard cubic metre denote the
    same quantity: 15.00 C (288.15 K) at 101.325 kPa.  Nm3 is defined that way
    for natural gas by the ScienceDirect engineering reference on the cubic
    metre, and sm3 is defined identically as the gas in a cubic metre at 15 C
    and 101.325 kPa.  So 36.0 MJ per cubic metre is exact for both spellings,
    not an approximation across them, and there is no conversion between the two
    to get wrong.

    `units.json` said otherwise until this change, defining Nm3 as 0 C per DIN
    1343 -- the general industrial convention, not the gas-industry one that
    applies to the only substance the unit appears on here -- with a multiplier
    toward sm3 of 0.94803.  It now states the equivalence directly, at 1.0.
    `TheGasUnitsAgree` below is what stops the two drifting apart again: the
    factor these rows share is only right while the unit table agrees the units
    are one.

    BAFU uses the spellings in different datasets -- 115 in Nm3 against 137 in
    m3 for natural gas, and none using both -- tracking the vintage of the data
    rather than a difference in what is measured.
    """

    def setUp(self):
        self.rows = {r.source_uuid: r for r in load_match_overrides(OVERRIDES_PATH)}

    def test_both_spellings_take_the_same_factor(self):
        factors = {
            self.rows[uuid].conversion_factor
            for uuid, (name, _, _) in MASS_ROWS.items() if "Gas" in name
        }
        self.assertEqual(factors, {36.0})

    def test_the_nm3_row_is_stated_in_the_unit_it_normalises_to(self):
        # A factor is refused unless it can be checked against the pair the merge
        # builds, and the merge resolves the source unit first: BAFU ships `Nm3`,
        # the merge sees `sm3`.
        for uuid in NM3_ROWS:
            with self.subTest(uuid[:8]):
                self.assertEqual(self.rows[uuid].source_unit, "sm3")

    def test_both_gas_rows_reach_natural_gas(self):
        targets = {
            self.rows[uuid].target_uuid
            for uuid, (name, _, _) in MASS_ROWS.items() if "Gas" in name
        }
        self.assertEqual(targets, {NATURAL_GAS})

    def test_the_coal_mine_off_gas_is_not_sent_to_natural_gas(self):
        """Gas off a coal seam is a different substance (#80), and this file
        used to say otherwise.  EF carries it separately, in its own material
        compartment, and BAFU's `Nm3` spelling reaches it without an override
        once the registry number stops pointing both names at one flow."""
        for uuid in COAL_MINE_OFF_GAS:
            with self.subTest(uuid[:8]):
                self.assertNotIn(uuid, self.rows)


class TheGasUnitsAgree(unittest.TestCase):
    """`Nm3` has to keep normalising to `sm3`.

    For gas the two are one quantity -- both 15.00 C at 101.325 kPa -- so this is
    a spelling and lives in `UNIT_ALIASES`, where a multiplier is not allowed.
    Before #292 it was a row of its own, defined at 0 C per DIN 1343 with a
    multiplier that was the reciprocal of what that reading implies.

    Two things depend on the alias.  The gas override row states `sm3` because
    that is the unit the merge will have resolved by the time it checks the
    factor.  And the unit guard compares canonical notations, so without the
    alias `Nm3` against `sm3` reads as a disagreement and wants an allowlist
    entry -- which would record a reviewed disagreement where there is none.
    """

    def test_a_normal_cubic_metre_normalises_to_a_standard_one(self):
        index = build_units_index()
        self.assertEqual(
            resolve_unit_notation("Nm3", index), resolve_unit_notation("sm3", index),
        )

    def test_the_guard_sees_one_unit(self):
        index = build_units_index()
        self.assertEqual(canonical_unit("Nm3", index), canonical_unit("sm3", index))

    def test_the_conditions_are_the_gas_industry_ones(self):
        # 0 C would be the DIN 1343 reading, which is not the gas-industry one.
        definition = unit_row_for("sm3")["definition"]
        self.assertIn("15 degrees Celsius", definition)
        self.assertIn("101.325", definition)


if __name__ == "__main__":
    unittest.main()
