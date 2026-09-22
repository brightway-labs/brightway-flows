"""Which water each of bafu's water rows is, and that the merge reads it.

Every water flow in every list is H2O and CAS 7732-18-5, so the registry
number cannot separate lake water from sea water and the taxonomy carries a
*material* instead -- one curated assignment per source flow, in
`water-flow-materials.json`.  EF 3.1 and all five ecoinvent releases were
assigned when the scheme was built.  bafu was not, and its 290 water rows
arrived at a merge that could only see one registry number shared by twelve
substances: 253 of them were reported `multiple-flow-object-candidates` and
placed nowhere, which is 9.6% of the whole list (#86).

Three of the taxonomy's concepts were added *because bafu ships flows for
them* -- `environmental-materials.json` names `Chemically polluted water`,
`Waste water` and `Water, process, surface` in the comments explaining why
contaminated water, waste water and surface water are in the scheme at all --
and until now not one flow had been assigned to any of the three.

What this file asserts is the assignment, not a name-reading rule.  The
difference matters most for the plain name: bafu ships 55 rows called simply
`Water` in an air compartment and 113 called simply `Water` in a water one,
and they are not the same substance.  Water in the air domain is vapour; water
discharged to a river is water, and the river is the *context* rather than
what the water is made of.  Nothing in the name says which, so no ranking of
names could ever tell them apart -- which is why the material is curated and
looked up rather than inferred at run time.
"""

from __future__ import annotations

import unittest

from brightway_flows.domain.flow_object import stable_flow_object_id
from brightway_flows.domain.materials import (
    flow_object_basis_for,
    material_by_source_flow,
    material_concepts,
    material_for_source_flow,
)
from brightway_flows.merge.contexts import ContextExpectations
from brightway_flows.merge.matching import resolve_flow_object
from brightway_flows.merge.state import MergeAccumulator, MergeIndexes, SourceRow
from brightway_flows.sources import resolve_source_list

BAFU = "bafu-2026-v1"
WATER_CAS = "7732-18-5"

#: One real bafu flow per assignment worth naming, by uuid.  The uuid is what
#: the lookup is keyed on, so these are the rows themselves rather than a
#: description of them.
WATER_TO_AIR = "00c14af0-f679-508c-a5e0-eb0a776ecded"
WATER_TO_WATER = "01126e7f-15d8-5f9e-bc21-c0f14e81965d"
WATER_WELL = "8908ed8f-7c01-54dd-bd95-fe5a1a1704ff"
WATER_RIVER = "213c9949-bd9f-5993-bcd1-dbc8151e5b7e"
WASTE_WATER = "0ca978b5-a565-5f83-9f69-96938875c811"
POLLUTED_WATER = "92ab1b7f-b38e-5f0d-9ace-b885693600ae"
PROCESS_SURFACE = "5737b3f7-a4a3-52fb-9aee-06af6e2a207f"

#: The concepts whose reason for existing is a bafu flow, and the flow named.
ADDED_FOR_BAFU = {
    "contaminated_water": "Chemically polluted water",
    "waste_water": "Waste water",
    "surface_water": "Water, process, surface",
}

#: Names both ecoinvent and bafu ship.  Two lists spelling a flow the same way
#: and meaning different things is not something a curator should have to
#: discover from a merge report, so they are asserted equal rather than left
#: to two tables that happen to agree today.
SHARED_WITH_ECOINVENT = (
    "Water, cooling, unspecified natural origin",
    "Water, lake",
    "Water, river",
    "Water, salt, ocean",
    "Water, salt, sole",
    "Water, turbine use, unspecified natural origin",
)


def _bafu_rows() -> dict[str, dict]:
    """Every curated assignment for bafu, by source uuid."""
    return {
        uuid: row
        for (source, uuid), row in material_by_source_flow().items()
        if source == BAFU
    }


class AssignmentTestCase(unittest.TestCase):
    """What the curated file now says about bafu's water."""

    def test_every_water_row_bafu_ships_is_assigned(self):
        """290 rows: the 294 names carrying the word `water` less the four
        land classes -- `Occupation, water bodies, artificial` and its three
        siblings -- which are a land use and not a substance."""
        rows = _bafu_rows()
        self.assertEqual(len(rows), 290)
        for name in (row["source_name"] for row in rows.values()):
            self.assertNotIn(name.split(",")[0], {"Occupation", "Transformation"})

    def test_each_concept_added_for_bafu_now_carries_its_flow(self):
        """The three the taxonomy names bafu for. Each had a concept, an ENVO
        anchor and a flow object id, and no flow."""
        by_node: dict[str, set[str]] = {}
        for row in _bafu_rows().values():
            by_node.setdefault(row["node"], set()).add(row["source_name"])
        for node, name in ADDED_FOR_BAFU.items():
            with self.subTest(node=node):
                self.assertIn(name, by_node.get(node, set()))

    def test_the_same_name_in_two_lists_is_the_same_material(self):
        by_source: dict[str, dict[str, set[str]]] = {}
        for (source, _uuid), row in material_by_source_flow().items():
            vendor = "bafu" if source.startswith("bafu") else source.split("-")[0]
            by_source.setdefault(vendor, {}).setdefault(
                row["source_name"], set()
            ).add(row["node"])
        for name in SHARED_WITH_ECOINVENT:
            with self.subTest(name=name):
                self.assertEqual(
                    by_source["bafu"].get(name), by_source["ecoinvent"].get(name)
                )

    def test_every_assignment_mints_an_object(self):
        """A row naming a concept nothing maps onto raises at layering time.
        `saline_water` is the one such concept, and nothing is assigned to it."""
        for uuid, row in _bafu_rows().items():
            with self.subTest(uuid=uuid):
                self.assertTrue(flow_object_basis_for(row["node"]))

    def test_water_in_the_air_and_water_in_a_river_are_not_one_substance(self):
        """The distinction no reading of the name could make: both rows are
        called `Water`, and one of them is vapour."""
        self.assertEqual(material_for_source_flow(BAFU, WATER_TO_AIR), "water_vapour")
        self.assertEqual(material_for_source_flow(BAFU, WATER_TO_WATER), "water")

    def test_a_water_body_in_a_withdrawal_is_the_material_and_in_a_release_is_not(self):
        """`Water, well` is groundwater because the well is where the water was
        taken *from*. `Water` released to a river is water: the river is where
        it went, and a discharge does not become river water on arrival."""
        self.assertEqual(material_for_source_flow(BAFU, WATER_WELL), "groundwater")
        self.assertEqual(material_for_source_flow(BAFU, WATER_RIVER), "river_water")
        self.assertEqual(material_for_source_flow(BAFU, WATER_TO_WATER), "water")


class MatchingTestCase(unittest.TestCase):
    """That the merge reads the assignment, on the rows #86 is about.

    The twelve-way tie is built here rather than described: every water object
    in the list carries 7732-18-5, so a bafu row carrying that number reaches
    all twelve and the selector refuses. The material branch runs before the
    registry number is ever looked up, which is what settles them.
    """

    def _indexes(self, *, materials_known=True):
        objects = {
            stable_flow_object_id("fo", flow_object_basis_for(concept)): {}
            for concept in material_concepts()
            if flow_object_basis_for(concept)
        }
        return MergeIndexes(
            flow_objects_by_id=objects if materials_known else {},
            flow_object_label_by_id={},
            cas_index={WATER_CAS: set(objects)},
            ec_index={},
            label_index={},
            pref_label_index={},
            qualifier_index={},
            flow_objects_with_cas=set(objects),
            context_expectations=ContextExpectations(
                _by_source_context={}, _source_label=BAFU
            ),
            consensus_context_strings={},
            prepared_context_decisions={},
            mapping_file=None,
            source=resolve_source_list(BAFU),
        )

    def _resolve(self, uuid, name):
        return resolve_flow_object(
            row=SourceRow(
                uuid=uuid, name=name, synonyms=[], labels=[name],
                context=["resources", "in water"], context_iri="",
                context_normalized=(), unit="m3", unit_iri="",
                cas=WATER_CAS, ec="",
            ),
            indexes=self._indexes(),
            accumulator=MergeAccumulator(),
        )

    def _object_for(self, concept):
        return stable_flow_object_id("fo", flow_object_basis_for(concept))

    def test_the_plain_name_no_longer_ties_twelve_ways(self):
        resolution = self._resolve(WATER_TO_WATER, "Water")
        self.assertEqual(resolution.flow_object_id, self._object_for("water"))
        self.assertEqual(resolution.basis, "material")

    def test_the_same_plain_name_in_air_lands_on_vapour(self):
        resolution = self._resolve(WATER_TO_AIR, "Water")
        self.assertEqual(resolution.flow_object_id, self._object_for("water_vapour"))

    def test_the_inverted_spellings_land_on_the_bodies_they_name(self):
        """`Water, river` and `Water, well` are river water and groundwater.
        They read as an inverted phrase -- `river water` is the list's own
        spelling -- but nothing here reads them: the assignment is curated, and
        a row whose material is known never reaches a name rule at all."""
        for uuid, name, concept in (
            (WATER_RIVER, "Water, river", "river_water"),
            (WATER_WELL, "Water, well", "groundwater"),
        ):
            with self.subTest(name=name):
                resolution = self._resolve(uuid, name)
                self.assertEqual(
                    resolution.flow_object_id, self._object_for(concept)
                )

    def test_a_material_whose_object_does_not_exist_yet_is_created_not_tied(self):
        """The three concepts added for bafu have no object in the list, because
        nothing has ever been assigned to them. That is `create it`, and it is
        reported as having no candidate -- which the creation path acts on --
        rather than as twelve candidates, which it would refuse."""
        accumulator = MergeAccumulator()
        row = SourceRow(
            uuid=WASTE_WATER, name="Waste water", synonyms=[], labels=["Waste water"],
            context=["emissions to water", "river"], context_iri="",
            context_normalized=(), unit="kg", unit_iri="", cas=WATER_CAS, ec="",
        )
        resolution = resolve_flow_object(
            row=row,
            indexes=self._indexes(materials_known=False),
            accumulator=accumulator,
        )
        self.assertIsNone(resolution)
        self.assertEqual(
            [entry.reason for entry in accumulator.unmatched],
            ["no-flow-object-candidate"],
        )

    def test_the_other_two_created_concepts_are_assigned(self):
        for uuid, concept in (
            (POLLUTED_WATER, "contaminated_water"),
            (PROCESS_SURFACE, "surface_water"),
        ):
            with self.subTest(concept=concept):
                self.assertEqual(material_for_source_flow(BAFU, uuid), concept)


if __name__ == "__main__":
    unittest.main()
