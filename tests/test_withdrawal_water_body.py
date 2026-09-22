"""A withdrawal whose material names a body is taken from that body.

BAFU withdraws water from a lake and writes the lake in the *name* --
`Water, lake` -- while its compartment says `resources / in water`, which is
water of no stated body.  The kind of water is read from the name into the
material, and for a withdrawal the material says the body as well: water taken
from a lake was taken from a lake.  `water-taxonomy-overview.md` §2 states that
in words -- for withdrawals the kind and the body agree, for discharges they do
not -- and this is that rule applied.

What the rule must not become is "the name beats the compartment".  It refines a
body the source left unstated and never overrides one the source stated, which
is the same distinction #90 turns on: `Unknown` prints an answer without
stating one.  Every test below is one half of that line.
"""

from __future__ import annotations

import unittest

from brightway_flows.domain.context import (
    Context,
    Dimension,
    Media,
    ProhibitedContextCombinationError,
    VerticalStrata,
    WaterBody,
)
from brightway_flows.domain.context_registry import (
    context_for_iri,
    iri_for_context,
)
from brightway_flows.domain.materials import (
    WITHDRAWAL_WATER_BODY,
    material_concepts,
    withdrawal_water_body,
)
from brightway_flows.merge.contexts import water_body_from_material

#: `Resource → Water → Unknown`: a withdrawal from a body nobody stated, which
#: is where every BAFU water resource arrives.
RESOURCE_WATER_UNKNOWN = "https://vocab.brightway.one/flow-contexts/reso-wate"
#: `Environmental → Water → River`: a discharge, where the body is the source's.
ENVIRONMENTAL_WATER_RIVER = (
    "https://vocab.brightway.one/flow-contexts/envi-wate-rive"
)
#: `Resource → Ground`, which is not a water context at all.
RESOURCE_GROUND = "https://vocab.brightway.one/flow-contexts/reso-grou"


class TheMappingTestCase(unittest.TestCase):
    """What the mapping says, and what it deliberately declines to say."""

    def test_every_material_named_is_one_the_taxonomy_carries(self):
        concepts = material_concepts()
        for concept_id in WITHDRAWAL_WATER_BODY:
            with self.subTest(concept=concept_id):
                self.assertIn(concept_id, concepts)

    def test_every_body_named_is_one_a_withdrawal_can_take(self):
        """A body an emission can take and a withdrawal cannot -- a treatment
        plant, long-term -- would raise when the context was built, so the
        mapping is checked against the enum rather than against a spelling."""
        for concept_id, body in WITHDRAWAL_WATER_BODY.items():
            with self.subTest(concept=concept_id):
                context = Context(
                    dimension=Dimension.RESOURCE,
                    media=Media.WATER,
                    water_body=WaterBody(body),
                )
                self.assertIsNotNone(iri_for_context(context))

    def test_a_material_that_names_no_body_is_none(self):
        """Cooling water names what the water was used for, fresh water names a
        quality of it, and brine occurs in the ocean and in salt domes alike.
        None of the three says where it was drawn from."""
        for concept_id in ("cooling_water", "turbine_water", "fresh_water", "brine"):
            with self.subTest(concept=concept_id):
                self.assertIsNone(withdrawal_water_body(concept_id))

    def test_a_concept_that_is_not_water_is_none(self):
        self.assertIsNone(withdrawal_water_body("not_a_concept"))
        self.assertIsNone(withdrawal_water_body(""))


class RefiningAnUnstatedBodyTestCase(unittest.TestCase):
    """The half of the line the rule is allowed to cross."""

    def test_lake_water_is_withdrawn_from_a_lake(self):
        iri, body = water_body_from_material(
            material="lake_water", source_context_iri=RESOURCE_WATER_UNKNOWN
        )
        self.assertEqual(body, "Lake")
        self.assertEqual(context_for_iri(iri).water_body, WaterBody.LAKE)

    def test_each_of_the_six_reaches_the_body_it_names(self):
        expected = {
            "lake_water": WaterBody.LAKE,
            "river_water": WaterBody.RIVER,
            "sea_water": WaterBody.OCEAN,
            "surface_water": WaterBody.SURFACE_WATER,
            "groundwater": WaterBody.UNCONFINED_AQUIFER,
            "fossil_groundwater": WaterBody.CONFINED_AQUIFER,
        }
        for concept_id, water_body in expected.items():
            with self.subTest(concept=concept_id):
                iri, body = water_body_from_material(
                    material=concept_id,
                    source_context_iri=RESOURCE_WATER_UNKNOWN,
                )
                self.assertEqual(body, water_body.value)
                context = context_for_iri(iri)
                self.assertEqual(context.water_body, water_body)
                self.assertEqual(context.dimension, Dimension.RESOURCE)
                self.assertEqual(context.media, Media.WATER)


class LeavingAStatedBodyAloneTestCase(unittest.TestCase):
    """The half it is not, which is the whole of what makes it safe."""

    def test_a_discharge_keeps_the_body_the_source_stated(self):
        """Water released into a river is plain water and the river is where it
        went.  The rule reaches emissions through no path at all -- the material
        of a discharge is `water`, which names no body -- but a discharge of
        river water would still not be moved, and that is asserted rather than
        left to the mapping."""
        iri, body = water_body_from_material(
            material="river_water",
            source_context_iri=ENVIRONMENTAL_WATER_RIVER,
        )
        self.assertEqual(body, "")
        self.assertEqual(iri, ENVIRONMENTAL_WATER_RIVER)

    def test_a_withdrawal_that_states_its_body_is_believed(self):
        """A source that says which body it drew from is believed even where
        the material says another.  That disagreement is a curator's question,
        and this is not where it gets settled."""
        stated = iri_for_context(
            Context(
                dimension=Dimension.RESOURCE,
                media=Media.WATER,
                water_body=WaterBody.OCEAN,
            )
        )
        iri, body = water_body_from_material(
            material="lake_water", source_context_iri=stated
        )
        self.assertEqual(body, "")
        self.assertEqual(iri, stated)

    def test_a_resource_that_is_not_water_is_left_alone(self):
        iri, body = water_body_from_material(
            material="groundwater", source_context_iri=RESOURCE_GROUND
        )
        self.assertEqual(body, "")
        self.assertEqual(iri, RESOURCE_GROUND)

    def test_a_material_naming_no_body_is_left_alone(self):
        iri, body = water_body_from_material(
            material="cooling_water", source_context_iri=RESOURCE_WATER_UNKNOWN
        )
        self.assertEqual(body, "")
        self.assertEqual(iri, RESOURCE_WATER_UNKNOWN)

    def test_a_row_with_no_material_is_left_alone(self):
        for material in (None, ""):
            with self.subTest(material=material):
                iri, body = water_body_from_material(
                    material=material, source_context_iri=RESOURCE_WATER_UNKNOWN
                )
                self.assertEqual(body, "")
                self.assertEqual(iri, RESOURCE_WATER_UNKNOWN)

    def test_a_row_with_no_context_is_left_alone(self):
        iri, body = water_body_from_material(material="lake_water", source_context_iri="")
        self.assertEqual(body, "")
        self.assertEqual(iri, "")

    def test_an_iri_the_vocabulary_does_not_carry_is_left_alone(self):
        """Reported rather than raised: an unmappable compartment is already
        recorded as such, and a row the merge cannot place is not made worse by
        refusing to guess at its body."""
        iri, body = water_body_from_material(
            material="lake_water", source_context_iri="https://example.invalid/nope"
        )
        self.assertEqual(body, "")
        self.assertEqual(iri, "https://example.invalid/nope")


class TheVocabularyCarriesTheResultTestCase(unittest.TestCase):
    """A refinement that named a context nobody publishes would place a flow
    nowhere, so the six are checked against the vocabulary rather than assumed."""

    def test_the_reverse_lookup_inverts_the_forward_one(self):
        for iri in (RESOURCE_WATER_UNKNOWN, ENVIRONMENTAL_WATER_RIVER, RESOURCE_GROUND):
            with self.subTest(iri=iri):
                self.assertEqual(iri_for_context(context_for_iri(iri)), iri)

    def test_every_body_a_withdrawal_can_take_is_published(self):
        """Which is why the rule is total: there is no material it could name a
        body for and then fail to find a compartment for.  Asserted rather than
        assumed, because a body added to the enum and not to the vocabulary
        would make `water_body_from_material` silently stop refining."""
        for body in WaterBody:
            try:
                context = Context(
                    dimension=Dimension.RESOURCE,
                    media=Media.WATER,
                    water_body=body,
                )
            except ProhibitedContextCombinationError:
                continue  # a body only an emission can take
            with self.subTest(body=body.value):
                self.assertIsNotNone(iri_for_context(context))

    def test_a_combination_the_vocabulary_does_not_carry_is_none(self):
        """None rather than a raise, which is what lets the merge leave a row
        where it was instead of failing a build over a compartment nobody
        publishes.

        The combination is assembled by assignment rather than by construction,
        because the constructor refuses it -- which is the point: this exercises
        the lookup's own fallback, and every combination the constructor allows
        is published (above).
        """
        context = Context(
            dimension=Dimension.RESOURCE, media=Media.WATER, water_body=WaterBody.LAKE
        )
        context.strata = VerticalStrata.AIRCRAFT
        self.assertIsNone(iri_for_context(context))


if __name__ == "__main__":
    unittest.main()
