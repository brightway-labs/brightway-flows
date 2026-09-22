"""Stage 5: a land class is a flow object, and the object is the class.

`plans/land-class-taxonomy.md` §3.4, §3.7 and §3.9.  Stage 4 assigned every
source flow to a `LandUse`; this is what the pipeline then does with it, and
what is pinned is the four claims the design rests on:

- **Identity is structural.**  Two spellings of one class meet on one object
  with no crosswalk row, because they produce one key.  That is the whole of
  §3.4, and it is the reason BAFU's 123 land rows stop duplicating EF's work.
- **Direction is a field, and that keeps the balanced pair apart.**
  `from forest, primary` and `to forest, primary` are characterised at -396.7
  and +396.7 in one context and one unit.  Before this, the only thing holding
  them apart was the words `from` and `to` inside a label, and
  `pipeline/deduplication.py` signs on every semantic field but six -- so they
  were #31 waiting to happen.  Two values, two objects, is the fix.
- **The hierarchy is generated, never curated.**  Dropping the most specific
  stated qualifier gives the parent, so the whole edge set is this project's by
  construction and no edge can be published as ENVO's or GET's that they do not
  assert.
- **Nothing is minted.**  A class no source flow reaches is not carried, so an
  object hangs off whichever ancestor this build actually has.

`LandUse.from_key` is here too, because the published record carries the key
and everything reading a built list back has to be able to read it.
"""

import unittest

from brightway_flows.domain.flow_object import FlowObject
from brightway_flows.domain.land_use import (
    QUALIFIER_AXES,
    Direction,
    Irrigation,
    LandCover,
    LandUse,
    LandUseError,
    ManagementIntensity,
    SuccessionalStage,
)
from brightway_flows.domain.land_flow_classes import published_land_classes
from brightway_flows.domain.land_use_anchors import anchors_for
from brightway_flows.flow_layers.land_hierarchy import (
    attach_land_hierarchy,
    land_object_id,
)
from brightway_flows.pipeline.semantic_typing import (
    LAND_CLASSIFICATION,
    _attach_land_class,
    _land_class_by_object_id,
)

CROPLAND = LandUse(direction=Direction.OCCUPATION, cover=LandCover.CROPLAND)
RAINFED = LandUse(
    direction=Direction.OCCUPATION,
    cover=LandCover.CROPLAND,
    irrigation=Irrigation.RAINFED,
)
RAINFED_INTENSIVE = LandUse(
    direction=Direction.OCCUPATION,
    cover=LandCover.CROPLAND,
    irrigation=Irrigation.RAINFED,
    intensity=ManagementIntensity.INTENSIVE,
)
FROM_PRIMARY_FOREST = LandUse(
    direction=Direction.TRANSFORMATION_FROM,
    cover=LandCover.FOREST,
    stage=SuccessionalStage.PRIMARY,
)
TO_PRIMARY_FOREST = LandUse(
    direction=Direction.TRANSFORMATION_TO,
    cover=LandCover.FOREST,
    stage=SuccessionalStage.PRIMARY,
)


def _object(land_use: LandUse) -> FlowObject:
    """A flow object at the id its land class mints, as the layering makes it."""
    return FlowObject(
        flow_object_id=land_object_id(land_use),
        prefLabel=[{"@value": land_use.label, "@language": "en"}],
        altLabel=[],
        properties={},
        references=[],
        created_from={},
        classifications={},
    )


class TheKeyReadsBackTestCase(unittest.TestCase):
    """`from_key` is the exact inverse of `key`, over the whole enumeration."""

    def test_no_enumerated_value_name_can_break_the_slug_rule(self):
        """The rule `from_key` rests on, checked where it is actually a rule.

        `key` lower-cases a member name and turns underscores into hyphens, and
        reading it back turns every hyphen into an underscore.  That is exact
        only because no member name contains a hyphen of its own -- so this
        checks the names rather than sampling combinations of them, which is
        the difference between the property and an instance of it.
        """
        for enum in (Direction, LandCover, *QUALIFIER_AXES.values()):
            for value in enum:
                with self.subTest(value=f"{enum.__name__}.{value.name}"):
                    self.assertNotIn("-", value.name)
                    self.assertEqual(value.name, value.name.upper())

    def test_every_published_class_round_trips(self):
        """The 345 classes five source lists between them ship.

        The reached space rather than the legal one, which is what any reader
        of a built list will actually hold.  It was 336 and three lists until
        #174 curated Stepwise 2006's land rows, and 339 and four until #351
        curated AGRIBALYSE 3.2's.
        """
        published = published_land_classes()
        self.assertEqual(len(published), 345)
        for key, value in published.items():
            with self.subTest(key=key):
                self.assertEqual(LandUse.from_key(key), value)
                self.assertEqual(LandUse.from_key(key).key, key)

    def test_every_axis_value_the_lists_reach_survives_a_round_trip(self):
        """Each axis value in use appears in some key, and reads back from it."""
        seen: set[str] = set()
        for value in published_land_classes().values():
            for stated in (value.direction, value.cover, *value.qualifiers().values()):
                seen.add(f"{type(stated).__name__}.{stated.name}")
        self.assertGreater(len(seen), 40)
        for value in published_land_classes().values():
            self.assertEqual(LandUse.from_key(value.key), value)

    def test_a_key_naming_no_such_value_raises(self):
        for key in (
            "",
            "occupation",
            "occupation/not-a-cover",
            "sideways/cropland",
            "occupation/cropland/irrigation",
            "occupation/cropland/irrigation=drizzled",
        ):
            with self.subTest(key=key), self.assertRaises(LandUseError):
                LandUse.from_key(key)

    def test_a_combination_the_axes_rule_out_raises(self):
        """Reading a key runs the validators, like every other way in."""
        with self.assertRaises(Exception):
            LandUse.from_key("occupation/forest/landfill=sanitary")


class TheObjectIsTheClassTestCase(unittest.TestCase):
    def test_two_spellings_of_one_class_mint_one_id(self):
        """§3.4, as arithmetic: identity falls out of the fields.

        EF's `arable, non-irrigated, intensive` and ecoinvent's and BAFU's
        `annual crop, non-irrigated, intensive` decompose to this one value, so
        there is nothing left for a crosswalk row to do.
        """
        again = LandUse.from_key(RAINFED_INTENSIVE.key)
        self.assertEqual(land_object_id(again), land_object_id(RAINFED_INTENSIVE))

    def test_the_balanced_pair_mints_two_ids(self):
        """The repair the whole design exists for.

        -396.7 and +396.7 in one context and one unit, held apart by two words
        inside a label until direction became a field.
        """
        self.assertNotEqual(
            land_object_id(FROM_PRIMARY_FOREST), land_object_id(TO_PRIMARY_FOREST)
        )

    def test_the_id_is_a_function_of_the_class_and_nothing_else(self):
        self.assertEqual(land_object_id(RAINFED_INTENSIVE), land_object_id(RAINFED_INTENSIVE))
        self.assertTrue(land_object_id(CROPLAND).startswith("fo-"))


class TheHierarchyTestCase(unittest.TestCase):
    def test_a_class_hangs_off_its_nearest_present_ancestor(self):
        objects = [_object(RAINFED_INTENSIVE), _object(RAINFED), _object(CROPLAND)]
        objects, stats = attach_land_hierarchy(objects)
        by_key = {obj.flow_object_id: obj for obj in objects}
        self.assertEqual(
            by_key[land_object_id(RAINFED_INTENSIVE)].parent_intervention_id,
            land_object_id(RAINFED),
        )
        self.assertEqual(
            by_key[land_object_id(RAINFED)].parent_intervention_id,
            land_object_id(CROPLAND),
        )
        self.assertEqual(stats["land_classes_linked"], 2)
        self.assertEqual(stats["land_classes_rooted"], 1)

    def test_a_missing_intermediate_is_skipped_rather_than_minted(self):
        """§3.6: the published scheme is the reached space, not the legal one.

        With no `(CROPLAND, rainfed)` object in the build, the intensive class
        hangs off `(CROPLAND)` -- and no third object appears.
        """
        objects = [_object(RAINFED_INTENSIVE), _object(CROPLAND)]
        objects, stats = attach_land_hierarchy(objects)
        self.assertEqual(len(objects), 2, "nothing is minted")
        by_id = {obj.flow_object_id: obj for obj in objects}
        self.assertEqual(
            by_id[land_object_id(RAINFED_INTENSIVE)].parent_intervention_id,
            land_object_id(CROPLAND),
        )

    def test_a_root_gets_no_parent(self):
        objects, stats = attach_land_hierarchy([_object(CROPLAND)])
        self.assertEqual(objects[0].parent_intervention_id, None)
        self.assertEqual(stats["land_classes_rooted"], 1)

    def test_an_object_that_is_not_a_land_class_is_untouched(self):
        other = FlowObject(
            flow_object_id="fo-benzene",
            prefLabel=[], altLabel=[], properties={}, references=[], created_from={},
        )
        objects, stats = attach_land_hierarchy([other])
        self.assertIsNone(other.parent_intervention_id)
        self.assertEqual(stats["land_classes_seen"], 0)

    def test_the_parent_is_the_class_with_one_qualifier_dropped(self):
        """The edge is generated, and this is the generator."""
        self.assertEqual(RAINFED_INTENSIVE.broader(), RAINFED)
        self.assertEqual(RAINFED.broader(), CROPLAND)
        self.assertIsNone(CROPLAND.broader())


class TheTypingTestCase(unittest.TestCase):
    def setUp(self):
        _land_class_by_object_id.cache_clear()
        self.addCleanup(_land_class_by_object_id.cache_clear)

    def test_a_land_object_is_typed_from_its_anchors(self):
        obj = _object(RAINFED_INTENSIVE)
        counts = _attach_land_class(obj)
        self.assertEqual(counts["land_taxonomy"], 1)
        expected = [anchor.iri for anchor in anchors_for(RAINFED_INTENSIVE)]
        self.assertEqual(obj.types, expected)
        # The cover first: `_compute_flow_type` reads the first class, and the
        # facet should say what the land is rather than which practice it is
        # under.
        self.assertIn("ENVO", obj.types[0])

    def test_the_classification_names_the_class_and_its_scheme(self):
        obj = _object(RAINFED_INTENSIVE)
        _attach_land_class(obj)
        entry = obj.classifications[LAND_CLASSIFICATION]
        self.assertEqual(entry["@value"], [RAINFED_INTENSIVE.key])
        self.assertTrue(entry["@id"].endswith(RAINFED_INTENSIVE.key))
        self.assertEqual(entry["rdfs:label"], RAINFED_INTENSIVE.label)

    def test_a_regime_is_a_related_match_and_not_an_exact_one(self):
        """§3.7: `exactMatch` is earned. The AGROVOC concept is a *practice*."""
        obj = _object(RAINFED_INTENSIVE)
        _attach_land_class(obj)
        entry = obj.classifications[LAND_CLASSIFICATION]
        related = entry.get("http://www.w3.org/2004/02/skos/core#relatedMatch") or []
        self.assertTrue(
            any("agrovoc" in node["@id"] for node in related),
            "the intensity and irrigation anchors are AGROVOC practices",
        )

    def test_the_broader_edge_names_the_parent_class(self):
        obj = _object(RAINFED_INTENSIVE)
        _attach_land_class(obj)
        entry = obj.classifications[LAND_CLASSIFICATION]
        broader = entry["http://www.w3.org/2004/02/skos/core#broader"]
        self.assertEqual(len(broader), 1)
        self.assertTrue(broader[0]["@id"].endswith(RAINFED.key))

    def test_no_edge_source_is_recorded(self):
        """Because there is nothing to tell apart.

        The material scheme records one on all 119 of its edges precisely
        because its hierarchy was hand-written and had to be distinguished from
        ENVO's. Every edge here is generated by dropping a field.
        """
        obj = _object(RAINFED_INTENSIVE)
        _attach_land_class(obj)
        entry = obj.classifications[LAND_CLASSIFICATION]
        broader = entry["http://www.w3.org/2004/02/skos/core#broader"]
        self.assertNotIn("provenance", broader[0])

    def test_an_object_that_is_not_a_land_class_is_untouched(self):
        obj = FlowObject(
            flow_object_id="fo-benzene",
            prefLabel=[], altLabel=[], properties={}, references=[], created_from={},
            types=["https://w3id.org/chemrof/NeutralMolecule"],
        )
        counts = _attach_land_class(obj)
        self.assertEqual(counts, {})
        self.assertEqual(obj.types, ["https://w3id.org/chemrof/NeutralMolecule"])
        self.assertEqual(obj.classifications, {})


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
