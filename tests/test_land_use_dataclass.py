"""#66: a land class is a value with fields, and the fields were read off the data.

Three things are pinned here, and they are the three claims
`plans/land-class-taxonomy.md` makes about `domain/land_use.py`:

1. **Every land class the source lists actually ship constructs.** A validator
   that rejects a real class is a validator that would make a real flow
   unpublishable, so the 336 values in `tests/data/observed-land-classes.json`
   are run through the dataclass one by one.
2. **The combinations §3.5 rules out raise.** Otherwise the rules are decoration
   and the enumeration is the raw product.
3. **Identity is structural.** Two spellings of one land class produce one
   value, which is the whole reason this is a dataclass rather than a list of
   curated concepts.
"""

import json
import unittest
from pathlib import Path

from brightway_flows.domain.context import LandUseClass
from brightway_flows.domain.land_use import (
    COVER_AXES,
    QUALIFIER_AXES,
    BuiltForm,
    Direction,
    Infrastructure,
    Irrigation,
    LandCover,
    LandUse,
    LandUseError,
    ManagementIntensity,
    Origin,
    ProhibitedLandUseCombinationError,
    SilviculturalRegime,
    SuccessionalStage,
    Tillage,
    UseStatus,
    VegetationForm,
    all_land_uses,
    land_uses_by_key,
)

OBSERVED_PATH = Path(__file__).parent / "data" / "observed-land-classes.json"


def observed() -> list[dict]:
    return json.loads(OBSERVED_PATH.read_bytes())["land_classes"]


class ObservedLandClassesTestCase(unittest.TestCase):
    """The dataclass has to hold what the lists ship, all of it."""

    def test_every_observed_land_class_constructs(self):
        for record in observed():
            with self.subTest(key=record["key"]):
                land_use = LandUse.from_dict(
                    {
                        key: value
                        for key, value in record.items()
                        if key not in ("key", "label", "spellings")
                    }
                )
                self.assertEqual(land_use.key, record["key"])

    #: The thirteen Stepwise 2006 rows no axis can read, and the one thing they
    #: have in common: each names the state the land was in *before*.  A land
    #: class here is a direction and a cover with qualifying axes, and every
    #: axis describes the land as it is.  `Occupation, sealed, on grassland` is
    #: a paved square metre that was grassland, and Stepwise charges 0.7 for it
    #: against 0.2 for the same paving on arable land -- so the previous state
    #: is what the number turns on, and it is exactly what cannot be written
    #: down.  Listed by name rather than counted, so that a fourteenth is a
    #: failure and not a number somebody bumps.
    STEPWISE_PREVIOUS_STATE = {
        "Occupation, accelerated denaturalisation, grassland to pasture",
        "Occupation, accelerated denaturalisation, primary forest to extensive forest",
        "Occupation, accelerated denaturalisation, primary forest to intensive forest",
        "Occupation, accelerated denaturalisation, primary forest to managed forest",
        "Occupation, accelerated denaturalisation, secondary forest to arable",
        "Occupation, accelerated denaturalisation, secondary forest to extensive forest",
        "Occupation, accelerated denaturalisation, secondary forest to intensive forest",
        "Occupation, accelerated denaturalisation, secondary forest to managed forest",
        "Occupation, forest, on arable land",
        "Occupation, sealed, on arable land",
        "Occupation, sealed, on extensive forest land",
        "Occupation, sealed, on grassland",
        "Occupation, sealed, on intensive forest land",
    }

    def test_nothing_the_flow_lists_ship_is_unparsed(self):
        """The residue is the measure of whether the axes are the right ones.

        One token no axis claims is one token the dataclass would have to keep
        as a string, which is the thing #66 is about.

        Empty for the four lists that publish flows -- EF 3.1, the five
        ecoinvent releases, BAFU 2026 v1 -- which is the claim this case has
        always made and still makes.
        """
        payload = json.loads(OBSERVED_PATH.read_bytes())
        residue = [
            row for row in payload["unparsed"] if row["source"] != "Stepwise 2006"
        ]
        self.assertEqual(residue, [])

    def test_the_only_residue_is_stepwise_naming_a_previous_state(self):
        """And Stepwise 2006's thirteen, which are one question.

        Stepwise is an LCIA method file and its land rows are whatever its
        `Nature occupation` category characterises; #174 curated 28 of its 41
        and these are the rest.  The exemption is written as the names rather
        than as a count so that a fourteenth row, or a different thirteen,
        fails here instead of being absorbed.  Whether the axes should gain a
        previous state is #176.
        """
        payload = json.loads(OBSERVED_PATH.read_bytes())
        self.assertEqual(
            {row["name"] for row in payload["unparsed"]},
            self.STEPWISE_PREVIOUS_STATE,
        )
        for row in payload["unparsed"]:
            with self.subTest(row["name"]):
                self.assertEqual(row["source"], "Stepwise 2006")

    def test_the_fixture_covers_all_three_directions(self):
        directions = {record["direction"] for record in observed()}
        self.assertEqual(
            directions,
            {"OCCUPATION", "TRANSFORMATION_FROM", "TRANSFORMATION_TO"},
        )

    def test_every_observed_value_is_in_the_enumeration(self):
        """What is enumerated and what is observed cannot drift apart.

        `all_land_uses` prunes the product with the same validators the
        constructor runs, so a class that constructs but is not enumerated
        would mean the enumeration had lost a cover or an axis.
        """
        enumerated = land_uses_by_key()
        for record in observed():
            with self.subTest(key=record["key"]):
                self.assertIn(record["key"], enumerated)

    def test_the_cover_axis_table_claims_nothing_unused(self):
        """`COVER_AXES` is read off the data, so every entry earns its place.

        A cover that admits an axis no source ever states of it is a cover whose
        enumeration is bigger than the evidence for it.
        """
        stated = {cover: set() for cover in LandCover}
        for record in observed():
            cover = LandCover[record["cover"]]
            stated[cover] |= set(record) & set(QUALIFIER_AXES)
        for cover, axes in COVER_AXES.items():
            with self.subTest(cover=cover.name):
                self.assertEqual(set(axes), stated[cover])


class ProhibitedCombinationTestCase(unittest.TestCase):
    """The rules of §3.5, each with the case that made it."""

    def test_a_cover_refuses_an_axis_it_is_never_asked(self):
        with self.assertRaises(ProhibitedLandUseCombinationError):
            LandUse(
                direction=Direction.OCCUPATION,
                cover=LandCover.DUMP_SITE,
                silviculture=SilviculturalRegime.CLEAR_CUTTING,
            )

    def test_tillage_replaces_the_intensity_rather_than_joining_it(self):
        LandUse(
            direction=Direction.OCCUPATION,
            cover=LandCover.CROPLAND,
            tillage=Tillage.REDUCED,
        )
        with self.assertRaises(ProhibitedLandUseCombinationError):
            LandUse(
                direction=Direction.OCCUPATION,
                cover=LandCover.CROPLAND,
                tillage=Tillage.REDUCED,
                intensity=ManagementIntensity.INTENSIVE,
            )

    def test_a_paddy_has_already_answered_the_water_question(self):
        LandUse(
            direction=Direction.OCCUPATION,
            cover=LandCover.CROPLAND,
            vegetation_form=VegetationForm.FLOODED,
        )
        with self.assertRaises(ProhibitedLandUseCombinationError):
            LandUse(
                direction=Direction.OCCUPATION,
                cover=LandCover.CROPLAND,
                vegetation_form=VegetationForm.FLOODED,
                irrigation=Irrigation.IRRIGATED,
            )

    def test_only_a_managed_stand_has_a_rotation(self):
        LandUse(
            direction=Direction.OCCUPATION,
            cover=LandCover.FOREST,
            intensity=ManagementIntensity.INTENSIVE,
            silviculture=SilviculturalRegime.SHORT_ROTATION,
        )
        with self.assertRaises(ProhibitedLandUseCombinationError):
            LandUse(
                direction=Direction.OCCUPATION,
                cover=LandCover.FOREST,
                silviculture=SilviculturalRegime.SHORT_ROTATION,
            )

    def test_succession_and_intensity_describe_a_stand_two_ways(self):
        with self.assertRaises(ProhibitedLandUseCombinationError):
            LandUse(
                direction=Direction.OCCUPATION,
                cover=LandCover.FOREST,
                stage=SuccessionalStage.PRIMARY,
                intensity=ManagementIntensity.INTENSIVE,
            )

    def test_land_that_is_not_used_has_no_management_intensity(self):
        with self.assertRaises(ProhibitedLandUseCombinationError):
            LandUse(
                direction=Direction.OCCUPATION,
                cover=LandCover.FOREST,
                use_status=UseStatus.UNUSED,
                intensity=ManagementIntensity.EXTENSIVE,
            )

    def test_the_rules_prune_the_enumeration_rather_than_decorating_it(self):
        """The validators have to remove something, or they are commentary.

        Pinned as numbers rather than an inequality so the effect of a new rule
        is visible in the diff.  The per-cover product is 4,097 land classes;
        the rules of §3.5 cut that to 1,665, against 119 the lists actually
        ship.  Both grew by one when `GRASSLAND_PASTURE_MEADOW` was added:
        it takes no qualifiers, so it contributes exactly one combination.  The plan quoted 4,286 for the raw figure, measured before #290
        removed the `geography` axis and before the cover table was tightened
        to what the sources state.

        It was 3,588 and 1,588 until #174 added the two values Stepwise 2006
        names -- `ManagementIntensity.INTEGRATED` and
        `Infrastructure.RAIL_EMBANKMENT`.  A value on an axis multiplies every
        cover that admits the axis, which is why two values cost 491
        combinations and 59 legal ones: the raw space grows faster than the
        published one, and that gap is what the rules are for.

        And 4,079 and 1,647 until #351 added `CropType.VINE`, the crop
        AGRIBALYSE 3.2 states and the axes lacked: one value, 18 raw
        combinations, 18 legal ones, because `crop_type` multiplies only the
        permanent cropland it belongs to.

        Still sparse, and deliberately: this is the *legal* space, and the
        published one is what a source flow lands on.
        """
        import itertools

        raw = 0
        for cover in LandCover:
            axes = sorted(COVER_AXES.get(cover, frozenset()))
            choices = [list(QUALIFIER_AXES[name]) + [None] for name in axes]
            raw += len(list(itertools.product(*choices)))
        self.assertEqual(raw, 4097)
        self.assertEqual(len(all_land_uses()), 1665 * len(Direction))


class StructuralIdentityTestCase(unittest.TestCase):
    """Two spellings of one land class are one value."""

    def test_ef_and_ecoinvent_spellings_meet(self):
        """`arable, non-irrigated, intensive` is `annual crop, non-irrigated,
        intensive`, and the fixture records both spellings on one key."""
        by_key = {record["key"]: record for record in observed()}
        record = by_key["occupation/cropland/irrigation=rainfed/intensity=intensive"]
        names = {spelling["name"].lower() for spelling in record["spellings"]}
        self.assertIn("arable, non-irrigated, intensive", names)
        self.assertIn("occupation, annual crop, non-irrigated, intensive", names)

    def test_a_bafu_class_spelled_two_ways_by_direction_meets_itself(self):
        """BAFU writes one class as `annual crop, organic` when it is occupied
        and `arable, organic` when it is transformed from -- §1.5.  Different
        directions, so two values, but one cover and one intensity."""
        occupied = LandUse(
            direction=Direction.OCCUPATION,
            cover=LandCover.CROPLAND,
            intensity=ManagementIntensity.ORGANIC,
        )
        transformed = LandUse(
            direction=Direction.TRANSFORMATION_FROM,
            cover=LandCover.CROPLAND,
            intensity=ManagementIntensity.ORGANIC,
        )
        self.assertNotEqual(occupied, transformed)
        self.assertEqual(occupied.cover, transformed.cover)
        self.assertEqual(occupied.intensity, transformed.intensity)

    def test_a_stated_unspecified_is_the_absence_of_a_statement(self):
        """ecoinvent's `arable land, unspecified use` and EF's `arable` are one
        value: `None` means the source did not say, and *unspecified* is what a
        source writes when it has nothing to say."""
        by_key = {record["key"]: record for record in observed()}
        names = {
            spelling["name"].lower()
            for spelling in by_key["occupation/cropland"]["spellings"]
        }
        self.assertIn("arable", names)
        self.assertIn("occupation, arable land, unspecified use", names)


class DirectionTestCase(unittest.TestCase):
    """Direction is a field, and that is what holds #31's pair apart."""

    def test_the_two_ends_of_a_transformation_are_different_values(self):
        """EF characterises `from forest, primary` at -396.7 and `to forest,
        primary` at +396.7, in one context and one unit.  Nothing but this
        keeps them apart once they share a land class."""
        away = LandUse(
            direction=Direction.TRANSFORMATION_FROM,
            cover=LandCover.FOREST,
            stage=SuccessionalStage.PRIMARY,
        )
        into = LandUse(
            direction=Direction.TRANSFORMATION_TO,
            cover=LandCover.FOREST,
            stage=SuccessionalStage.PRIMARY,
        )
        self.assertNotEqual(away, into)
        self.assertNotEqual(away.key, into.key)

    def test_both_ends_still_belong_to_one_context_value(self):
        """The context vocabulary is untouched by #66: both directions are
        `Land Use / Transformation`, as they are today."""
        for direction in (Direction.TRANSFORMATION_FROM, Direction.TRANSFORMATION_TO):
            land_use = LandUse(direction=direction, cover=LandCover.FOREST)
            self.assertEqual(land_use.land_use_class, LandUseClass.TRANSFORMATION)
        occupation = LandUse(direction=Direction.OCCUPATION, cover=LandCover.FOREST)
        self.assertEqual(occupation.land_use_class, LandUseClass.OCCUPATION)

    def test_no_context_value_is_added_by_this_module(self):
        """A regression test for the design, not the code.  The first draft of
        the plan split `LandUseClass.TRANSFORMATION` in two and would have moved
        233 flows to new context IRIs; this asserts that was withdrawn."""
        self.assertEqual(
            {value.value for value in LandUseClass},
            {"Occupation", "Transformation"},
        )


class BroaderTestCase(unittest.TestCase):
    """`skos:broader` is generated by dropping a field, never curated."""

    def test_dropping_the_most_specific_qualifier_gives_the_parent(self):
        intensive = LandUse(
            direction=Direction.OCCUPATION,
            cover=LandCover.CROPLAND,
            irrigation=Irrigation.RAINFED,
            intensity=ManagementIntensity.INTENSIVE,
        )
        chain = [land_use.key for land_use in intensive.broader_chain()]
        self.assertEqual(
            chain,
            [
                "occupation/cropland/irrigation=rainfed/intensity=intensive",
                "occupation/cropland/irrigation=rainfed",
                "occupation/cropland",
            ],
        )

    def test_a_bare_cover_is_a_root(self):
        self.assertIsNone(
            LandUse(direction=Direction.OCCUPATION, cover=LandCover.FOREST).broader()
        )

    def test_every_ancestor_is_itself_legal(self):
        """Dropping a field must never produce a value the rules reject, or the
        generated hierarchy would have holes in it."""
        for record in observed():
            land_use = LandUse.from_dict(
                {
                    key: value
                    for key, value in record.items()
                    if key not in ("key", "label", "spellings")
                }
            )
            with self.subTest(key=land_use.key):
                self.assertTrue(all(land_use.broader_chain()))


class SerialisationTestCase(unittest.TestCase):
    def test_a_value_round_trips(self):
        original = LandUse(
            direction=Direction.TRANSFORMATION_TO,
            cover=LandCover.SEABED,
            origin=Origin.NATURAL,
        )
        self.assertEqual(LandUse.from_dict(original.to_dict()), original)

    def test_only_stated_fields_are_serialised(self):
        land_use = LandUse(
            direction=Direction.OCCUPATION,
            cover=LandCover.URBAN,
            built_form=BuiltForm.CONTINUOUS,
        )
        self.assertEqual(
            land_use.to_dict(),
            {"direction": "OCCUPATION", "cover": "URBAN", "built_form": "CONTINUOUS"},
        )

    def test_an_unknown_axis_raises_rather_than_being_ignored(self):
        """A typo in a curated file is a row that would otherwise silently lose
        a qualifier and become a different, legal land class."""
        with self.assertRaises(LandUseError):
            LandUse.from_dict(
                {"direction": "OCCUPATION", "cover": "CROPLAND", "irigation": "RAINFED"}
            )

    def test_the_label_says_what_the_context_does_not(self):
        """One rule, applied to both directions.

        The context carries `Land Use -> Occupation` and `Land Use ->
        Transformation`, so a label naming either repeats it.  What the context
        has never carried is *which end* of a transformation a flow is, which
        is the whole reason `direction` is a field, so the `from` or `to` is in
        the label and has to be.

        The label used to read `Transformation, from forest, primary` -- the
        redundant word dropped for occupations and kept for transformations,
        which was EF 3.1's convention for one and the SimaPro-lineage lists'
        for the other, and no rule between them.
        """
        self.assertEqual(
            LandUse(
                direction=Direction.OCCUPATION,
                cover=LandCover.TRAFFIC,
                infrastructure=Infrastructure.RAIL_NETWORK,
            ).label,
            "Traffic area, rail network",
        )
        self.assertEqual(
            LandUse(
                direction=Direction.TRANSFORMATION_FROM,
                cover=LandCover.FOREST,
                stage=SuccessionalStage.PRIMARY,
            ).label,
            "From forest, primary",
        )
        self.assertEqual(
            LandUse(
                direction=Direction.TRANSFORMATION_TO,
                cover=LandCover.FOREST,
                stage=SuccessionalStage.PRIMARY,
            ).label,
            "To forest, primary",
        )
        # No label names its own side of the boundary, in either direction.
        for value in all_land_uses():
            if value.label.lower().startswith(("occupation,", "transformation,")):
                raise AssertionError(f"{value.key} repeats its context: {value.label!r}")

    def test_grassland_is_not_meadow(self):
        """EF ships three classes here and they stay three.

        `grassland` is grassland, `pasture/meadow` is mown or grazed land --
        ENVO's `area of pastureland or hayfields`, one class for the pair --
        and `grassland/pasture/meadow` is the union of both.  Reading the third
        as the first asserted that grassland takes in hayfields, which is the
        one statement the three-way split denies.
        """
        covers = {
            LandCover.GRASSLAND,
            LandCover.PASTURE,
            LandCover.GRASSLAND_PASTURE_MEADOW,
        }
        self.assertEqual(len({cover.value for cover in covers}), 3)
        combined = LandUse(
            direction=Direction.OCCUPATION,
            cover=LandCover.GRASSLAND_PASTURE_MEADOW,
        )
        self.assertEqual(combined.label, "Grassland, pasture or meadow")
        self.assertNotEqual(
            combined.key,
            LandUse(direction=Direction.OCCUPATION, cover=LandCover.GRASSLAND).key,
        )

    def test_the_combined_grassland_cover_takes_no_qualifiers(self):
        """A source with a use status to state names one of the finer covers."""
        with self.assertRaises(ProhibitedLandUseCombinationError):
            LandUse(
                direction=Direction.OCCUPATION,
                cover=LandCover.GRASSLAND_PASTURE_MEADOW,
                use_status=UseStatus.GRAZED,
            )


if __name__ == "__main__":
    unittest.main()
