"""The census counts blanks and decides nothing.

Metaldehyde is characterised in agricultural, non-agricultural and unspecified
soil, and has a silvicultural flow nobody characterised.  The census says that
silvicultural is blank, that each of the three would be its donor, what the
taxonomy says about each pair, and how often two stated soils agree -- and it
publishes nothing, which is the whole point of stage 1 of
``plans/lcia-consensus-decisions.md``.
"""

from __future__ import annotations

import unittest

from brightway_flows.lcia.census import (
    BLANK_DIMENSION,
    IDENTITY_BLANK_DIMENSION,
    ContextClass,
    PublishedFactor,
    Relation,
    SubstanceRelative,
    context_census,
    context_class_of,
    identity_census,
    relation_of,
)

SOIL = "Environmental → Ground → "
WATER = "Environmental → Water → "
AIR = "Environmental → Air → "
SLUG = "ecotoxicity-freshwater"
SUBSTANCE = "fo-metaldehyde"


def _flows(*contexts: tuple[str, str], substance: str = SUBSTANCE, deprecated=()):
    return {
        uuid: {
            "flow_object_id": substance,
            "context_display": context,
            "deprecated": uuid in deprecated,
        }
        for uuid, context in contexts
    }


def _published(*rows: tuple[str, float, str]):
    return [
        PublishedFactor(uuid, SLUG, "", amount, derivation)
        for uuid, amount, derivation in rows
    ]


def _pairs(rows, donor, recipient):
    found = [row for row in rows if row.donor == donor and row.recipient == recipient]
    assert len(found) == 1, (donor, recipient, rows)
    return found[0]


class ClassesTest(unittest.TestCase):
    def test_walls_are_in_no_class(self):
        for wall in (AIR + "Long-term", WATER + "Long-term", AIR + "Indoor",
                     WATER + "Ocean", "Resource → Water → Ocean"):
            self.assertIsNone(context_class_of(wall), wall)

    def test_classes(self):
        self.assertIs(context_class_of(SOIL + "Silvicultural"), ContextClass.SOIL)
        self.assertIs(context_class_of(WATER + "River"), ContextClass.FRESH_WATER)
        self.assertIs(
            context_class_of(AIR + "Ground level → Urban (>1000 people/square mile)"),
            ContextClass.AIR,
        )
        self.assertIs(
            context_class_of("Resource → Water → Unconfined aquifer"),
            ContextClass.RESOURCE_WATER,
        )
        self.assertIsNone(context_class_of("Land Use → Occupation"))
        self.assertIsNone(context_class_of("Resource → Ground"))

    def test_relations(self):
        self.assertIs(relation_of(SOIL + "Unknown", SOIL + "Silvicultural"), Relation.BROADER)
        self.assertIs(relation_of(SOIL + "Silvicultural", SOIL + "Unknown"), Relation.NARROWER)
        self.assertIs(relation_of(SOIL + "Agricultural", SOIL + "Silvicultural"), Relation.SIBLING)
        # Our water vocabulary files river and lake under surface water.
        self.assertIs(relation_of(WATER + "Surface water", WATER + "River"), Relation.BROADER)
        self.assertIs(relation_of(WATER + "Lake", WATER + "Surface water"), Relation.NARROWER)
        self.assertIs(relation_of(WATER + "River", WATER + "Unconfined aquifer"), Relation.SIBLING)
        self.assertIs(
            relation_of(AIR + "Unknown", AIR + "Medium stack, <150 meters → Rural (<1000 people/square mile)"),
            Relation.BROADER,
        )


class CensusTest(unittest.TestCase):
    def setUp(self):
        self.flows = _flows(
            ("agri", SOIL + "Agricultural"),
            ("non-agri", SOIL + "Non-agricultural"),
            ("unknown", SOIL + "Unknown"),
            ("silvi", SOIL + "Silvicultural"),
            ("long-term", WATER + "Long-term"),
        )

    def test_a_blank_is_counted_once_per_donor_and_once_per_recipient(self):
        pairs, recipients = context_census(
            method="ef",
            published=_published(("agri", 5.637, "sole"), ("non-agri", 5.6369, "sole"), ("unknown", 5.637, "agreed")),
            stated=set(),
            flows=self.flows,
        )
        for donor in ("Agricultural", "Non-agricultural", "Unknown"):
            row = _pairs(pairs, SOIL + donor, SOIL + "Silvicultural")
            self.assertEqual(row.blanks, 1, donor)
            self.assertIs(row.context_class, ContextClass.SOIL)
        self.assertEqual([(r.recipient, r.blanks, r.single_donor) for r in recipients],
                         [(SOIL + "Silvicultural", 1, 0)])
        # Nothing about the wall, in either direction.
        self.assertFalse([r for r in pairs if "Long-term" in r.donor + r.recipient])

    def test_agreement_is_counted_where_both_are_published(self):
        pairs, _ = context_census(
            method="ef",
            published=_published(("agri", 100.0, "sole"), ("non-agri", 101.0, "sole"), ("unknown", 250.0, "sole")),
            stated=set(),
            flows=self.flows,
        )
        agree = _pairs(pairs, SOIL + "Agricultural", SOIL + "Non-agricultural")
        self.assertEqual((agree.both, agree.agree), (1, 1))
        differ = _pairs(pairs, SOIL + "Agricultural", SOIL + "Unknown")
        self.assertEqual((differ.both, differ.agree), (1, 0))
        self.assertIsNone(_pairs(pairs, SOIL + "Agricultural", SOIL + "Silvicultural").agreement)

    def test_a_restated_row_is_measured_against_its_donors(self):
        pairs, recipients = context_census(
            method="ef",
            published=_published(
                ("agri", 100.0, "sole"), ("non-agri", 250.0, "sole"), ("silvi", 250.0, "restated"),
            ),
            stated={("silvi", SLUG, "")},
            flows=self.flows,
        )
        from_non_agri = _pairs(pairs, SOIL + "Non-agricultural", SOIL + "Silvicultural")
        self.assertEqual((from_non_agri.restated_rows, from_non_agri.restated_matches), (1, 1))
        from_agri = _pairs(pairs, SOIL + "Agricultural", SOIL + "Silvicultural")
        self.assertEqual((from_agri.restated_rows, from_agri.restated_matches), (1, 0))
        # Unspecified soil is a blank here, with two donors; silvicultural is not.
        self.assertEqual([(r.recipient, r.blanks) for r in recipients], [(SOIL + "Unknown", 1)])

    def test_a_context_somebody_spoke_about_is_not_blank(self):
        _, recipients = context_census(
            method="ef",
            published=_published(("agri", 1.0, "sole")),
            stated={("silvi", SLUG, "")},  # held by a queue, or contradicted
            flows=self.flows,
        )
        self.assertEqual([(r.recipient, r.blanks) for r in recipients],
                         [(SOIL + "Non-agricultural", 1), (SOIL + "Unknown", 1)])

    def test_single_donor_blanks_are_counted_apart(self):
        _, recipients = context_census(
            method="stepwise-2006",
            published=_published(("unknown", 1.0, "sole")),
            stated=set(),
            flows=self.flows,
        )
        self.assertEqual({(r.recipient, r.blanks, r.single_donor) for r in recipients},
                         {(SOIL + "Agricultural", 1, 1), (SOIL + "Non-agricultural", 1, 1),
                          (SOIL + "Silvicultural", 1, 1)})

    def test_a_withdrawn_flow_is_never_a_blank(self):
        flows = _flows(("agri", SOIL + "Agricultural"), ("silvi", SOIL + "Silvicultural"),
                       deprecated={"silvi"})
        _, recipients = context_census(
            method="ef", published=_published(("agri", 1.0, "sole")), stated=set(), flows=flows,
        )
        self.assertEqual(recipients, [])

    def test_geography_is_part_of_the_key(self):
        flows = _flows(("surface", WATER + "Surface water"), ("river", WATER + "River"))
        published = [
            PublishedFactor("surface", "water-use", "", 42.95, "sole"),
            PublishedFactor("surface", "water-use", "CH", 18.6, "sole"),
            PublishedFactor("river", "water-use", "CH", 18.6, "sole"),
        ]
        _, recipients = context_census(method="ef", published=published, stated=set(), flows=flows)
        # The site-generic river number is blank; Switzerland's is stated.
        self.assertEqual([(r.recipient, r.blanks) for r in recipients], [(WATER + "River", 1)])

    def test_the_coverage_dimension_is_a_word(self):
        self.assertEqual(BLANK_DIMENSION, "blank")


ZINC = "fo-zinc"
ZINC_ION = "fo-zinc-ion"
WATER_IRI = "https://vocab.brightway.one/flow-contexts/envi-wate-unkn"
AIR_IRI = "https://vocab.brightway.one/flow-contexts/envi-air-unkn"
RIVER_IRI = "https://vocab.brightway.one/flow-contexts/envi-wate-rive"
RELATIVES = {ZINC_ION: SubstanceRelative(donor=ZINC, relationship="ion of")}


def _ion_flows(*rows: tuple[str, str, str], deprecated=()):
    """(uuid, substance, context IRI) rows, labelled by substance."""
    return {
        uuid: {
            "flow_object_id": substance,
            "label": {ZINC: "Zinc", ZINC_ION: "Zinc(2+)"}[substance],
            "context_iri": context,
            "deprecated": uuid in deprecated,
        }
        for uuid, substance, context in rows
    }


class IdentityCensusTest(unittest.TestCase):
    """Zinc is characterised in water; its ion has a water flow and nothing on
    it.  That is one blank, counted on the ion, and it is the only kind this
    census counts: same context, same category, another substance (#197)."""

    def setUp(self):
        self.flows = _ion_flows(
            ("zn-water", ZINC, WATER_IRI),
            ("zn-air", ZINC, AIR_IRI),
            ("ion-water", ZINC_ION, WATER_IRI),
            ("ion-air", ZINC_ION, AIR_IRI),
            ("ion-river", ZINC_ION, RIVER_IRI),
        )

    def _census(self, published, stated=(), flows=None, relatives=RELATIVES):
        return identity_census(
            method="stepwise-2006",
            published=published,
            stated=set(stated),
            flows=flows or self.flows,
            relatives=relatives,
        )

    def test_an_ion_beside_its_characterised_element_is_a_blank(self):
        rows = self._census(_published(("zn-water", 133.39, "sole"), ("zn-air", 92.75, "sole")))
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual((row.recipient, row.donor, row.relationship), (ZINC_ION, ZINC, "ion of"))
        self.assertEqual((row.blanks, row.contexts, row.categories), (2, 2, 1))
        self.assertEqual(row.value, "Zinc(2+) — ion of Zinc")
        self.assertEqual(row.method, "stepwise-2006")

    def test_only_the_same_context_counts(self):
        """The river is blank for the ion, but the element has no river flow either:
        that is the context census's blank, not this one's."""
        rows = self._census(_published(("zn-water", 133.39, "sole")))
        self.assertEqual([(r.blanks, r.contexts) for r in rows], [(1, 1)])

    def test_a_published_ion_is_not_blank(self):
        rows = self._census(
            _published(("zn-water", 133.39, "sole"), ("ion-water", 133.39, "adopted"))
        )
        self.assertEqual(rows, [])

    def test_a_spoken_for_ion_is_not_blank(self):
        """A publisher who characterised the ion itself owns the answer, blank or not."""
        rows = self._census(
            _published(("zn-water", 133.39, "sole")), stated={("ion-water", SLUG, "")}
        )
        self.assertEqual(rows, [])

    def test_geography_is_part_of_the_pair(self):
        published = [
            PublishedFactor("zn-water", "water-use", "CH", 18.6, "sole"),
            PublishedFactor("ion-water", "water-use", "", 42.95, "sole"),
        ]
        rows = self._census(published)
        self.assertEqual([r.blanks for r in rows], [1])

    def test_a_withdrawn_ion_flow_is_never_blank(self):
        flows = _ion_flows(("zn-water", ZINC, WATER_IRI), ("ion-water", ZINC_ION, WATER_IRI),
                           deprecated={"ion-water"})
        self.assertEqual(self._census(_published(("zn-water", 1.0, "sole")), flows=flows), [])

    def test_a_substance_with_no_relative_is_not_asked(self):
        rows = self._census(_published(("zn-water", 1.0, "sole")), relatives={})
        self.assertEqual(rows, [])

    def test_most_blanks_first(self):
        copper, copper_ion = "fo-cu", "fo-cu-ion"
        flows = {
            **self.flows,
            "cu-water": {"flow_object_id": copper, "label": "Copper", "context_iri": WATER_IRI},
            "cuion-water": {"flow_object_id": copper_ion, "label": "Copper, Ion", "context_iri": WATER_IRI},
        }
        relatives = {**RELATIVES, copper_ion: SubstanceRelative(donor=copper, relationship="ion of")}
        rows = self._census(
            _published(("zn-water", 1.0, "sole"), ("zn-air", 1.0, "sole"), ("cu-water", 1.0, "sole")),
            flows=flows,
            relatives=relatives,
        )
        self.assertEqual([(r.recipient_label, r.blanks) for r in rows], [("Zinc(2+)", 2), ("Copper, Ion", 1)])

    def test_the_coverage_dimension_is_a_word(self):
        self.assertEqual(IDENTITY_BLANK_DIMENSION, "identity-blank")


if __name__ == "__main__":
    unittest.main()
