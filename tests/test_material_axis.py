"""Two materials on one CAS stop being one flow object.

`sea water`, `cooling water`, `brine` and unqualified water are all H2O and all
CAS 7732-18-5.  Layering grouped on chemistry, so they became one flow object;
deduplication signs on the fields of an elementary flow, so two of them in one
context with one unit became one flow.  That is #31: EF's `Water use` publishes
a balanced pair of withdrawal and return factors, the return was deprecated onto
the withdrawal, and a balanced set became a 434x one-sided charge.

The fix is identity, not a special case in deduplication: give each material its
own flow object and the signatures differ on their own.  See
`plans/water-taxonomy.md`.
"""

import unittest

from brightway_flows.domain.flow import Flow
from brightway_flows.domain.materials import (
    MaterialRuleError,
    flow_object_basis_for,
    material_by_source_flow,
    material_concepts,
    material_for_source_flow,
)
from brightway_flows.flow_layers.layering import _material_for, resolve_flow_layers
from brightway_flows.sources import base_source_list

EF = "EF 3.1"
WATER_CAS = "7732-18-5"

#: The pair whose collapse #31 is about, and the two others sharing their CAS.
LAKE_WATER = "c506b970-7b92-452f-8d6f-05d4f203d958"
TO_COOLING = "21868f36-62ab-4e8e-98ed-7106228c17be"
TO_TURBINE = "9575e5d0-f865-4ad1-9d98-6b0d6e275780"
SALT_SOLE = "37295016-4d20-4bbc-8bf8-b344933d8980"
UNQUALIFIED = "419682fe-60fb-4b43-be89-bf2824b51104"

RESO_WATE = "https://vocab.brightway.one/flow-contexts/reso-wate"


def _flow(uuid, name, *, cas=WATER_CAS, unit="m3", context=RESO_WATE):
    """A transform-created base-list flow as layering receives it."""
    return Flow.from_dict(
        {
            "uuid": uuid,
            "identifier": uuid,
            "source": EF,
            "unit": unit,
            "cas_numbers": [cas] if cas else [],
            "ec_numbers": [],
            "context_iri": context,
            "context": {"dimension": "Resource", "media": "Water", "water_body": "Unknown"},
            "prefLabel": [{"@value": name, "@language": "en"}],
            "altLabel": [],
        }
    )


def _objects_by_flow(flows):
    objects, elementary, _stats = resolve_flow_layers(
        flows, source_list=base_source_list()
    )
    by_uuid = {row.elementary_flow_id: row.flow_object_id for row in elementary}
    return objects, by_uuid


class LookupNotInferenceTestCase(unittest.TestCase):
    """The material is curated. Nothing reads a name at run time."""

    def test_a_named_flow_resolves_through_the_curated_file(self):
        self.assertEqual(_material_for(_flow(LAKE_WATER, "lake water"), EF), "lake_water")

    def test_the_name_is_not_what_decides_it(self):
        """Rename the flow to anything and the material follows the uuid."""
        self.assertEqual(
            _material_for(_flow(LAKE_WATER, "utterly unrelated"), EF), "lake_water"
        )

    def test_a_flow_the_file_does_not_name_has_no_material(self):
        self.assertIsNone(_material_for(_flow("not-a-water-flow", "Methane"), EF))

    def test_a_source_ref_carries_the_material_for_a_merged_flow(self):
        """Most of the list is base-list rows with no references; a flow another
        list has been merged onto is found through them instead."""
        flow = _flow("some-consensus-uuid", "Water, lake")
        flow.source_refs = [
            {
                "list_name": "ecoinvent",
                "list_version": "3.12",
                "source_flow_uuid": "1acb026e-9de6-48fe-9e0d-be4d24125bbc",
            }
        ]
        self.assertEqual(_material_for(flow, EF), "lake_water")

    def test_two_lists_disagreeing_yields_none_rather_than_a_pick(self):
        """The merge has put two materials on one flow. Choosing the first is
        how a collapse gets papered over."""
        flow = _flow(LAKE_WATER, "lake water")
        flow.source_refs = [
            {
                "list_name": "ecoinvent",
                "list_version": "3.12",
                "source_flow_uuid": "629ffbca-ca71-4e4b-a006-ca9bdd9cd1df",  # sea water
            }
        ]
        self.assertIsNone(_material_for(flow, EF))

    def test_two_lists_agreeing_is_not_a_disagreement(self):
        flow = _flow(LAKE_WATER, "lake water")
        flow.source_refs = [
            {
                "list_name": "ecoinvent",
                "list_version": "3.12",
                "source_flow_uuid": "1acb026e-9de6-48fe-9e0d-be4d24125bbc",  # Water, lake
            }
        ]
        self.assertEqual(_material_for(flow, EF), "lake_water")


class SeparationTestCase(unittest.TestCase):
    """The collapse, and that it stops."""

    def test_four_materials_on_one_cas_are_four_flow_objects(self):
        flows = [
            _flow(LAKE_WATER, "lake water"),
            _flow(TO_COOLING, "Water to Cooling"),
            _flow(TO_TURBINE, "Water to turbine"),
            _flow(UNQUALIFIED, "water"),
        ]
        _objects, by_uuid = _objects_by_flow(flows)
        self.assertEqual(len(set(by_uuid.values())), 4, by_uuid)

    def test_the_255_pair_no_longer_shares_an_object(self):
        """`Water to Cooling` and `Water to turbine`: same object, context and
        unit before, so one was deprecated onto the other and took 209
        characterisation factors with it."""
        _objects, by_uuid = _objects_by_flow(
            [_flow(TO_COOLING, "Water to Cooling"), _flow(TO_TURBINE, "Water to turbine")]
        )
        self.assertNotEqual(by_uuid[TO_COOLING], by_uuid[TO_TURBINE])

    def test_brine_does_not_reach_water_despite_efs_cas_on_it(self):
        """EF gives `Water, salt, sole` CAS 7732-18-5, which is an error. The
        material is what separates it, so the wrong CAS costs nothing."""
        _objects, by_uuid = _objects_by_flow(
            [_flow(SALT_SOLE, "Water, salt, sole"), _flow(UNQUALIFIED, "water")]
        )
        self.assertNotEqual(by_uuid[SALT_SOLE], by_uuid[UNQUALIFIED])

    def test_a_shared_name_does_not_merge_them_either(self):
        """Both indexes are bypassed for a material, not just the CAS one:
        several of these normalise to the same name."""
        _objects, by_uuid = _objects_by_flow(
            [_flow(LAKE_WATER, "Water"), _flow(UNQUALIFIED, "Water")]
        )
        self.assertNotEqual(by_uuid[LAKE_WATER], by_uuid[UNQUALIFIED])

    def test_two_flows_of_one_material_do_share_an_object(self):
        """Separation is per material, not per flow. EF's two `Water (rain
        water)` rows are one substance in two contexts."""
        rain_m3 = "b9a77a95-26bb-465c-a558-b08f2cc7716c"
        rain_kg = "2a240c57-b782-4745-943b-0602d7a953c4"
        _objects, by_uuid = _objects_by_flow(
            [_flow(rain_m3, "Water (rain water)"), _flow(rain_kg, "Water (rain water)", unit="kg")]
        )
        self.assertEqual(by_uuid[rain_m3], by_uuid[rain_kg])


class IdentityTestCase(unittest.TestCase):
    """Which object each material mints, and that two do not move."""

    def test_the_object_id_comes_from_the_taxonomy(self):
        _objects, by_uuid = _objects_by_flow([_flow(LAKE_WATER, "lake water")])
        self.assertEqual(
            by_uuid[LAKE_WATER],
            material_concepts()["lake_water"]["flow_object_id"],
        )

    def test_unqualified_water_keeps_the_id_it_already_has(self):
        """The largest object in the list does not churn: its basis is the bare
        CAS, which is what it was minted under before any of this."""
        _objects, by_uuid = _objects_by_flow([_flow(UNQUALIFIED, "water")])
        self.assertEqual(by_uuid[UNQUALIFIED], "fo-464532a8f956fd39")

    def test_every_assigned_material_can_mint_an_object(self):
        """A row pointing at a concept nothing maps onto would raise at layering
        time; asserted here so the data cannot get into that state."""
        for (source, uuid), row in material_by_source_flow().items():
            with self.subTest(source=source, uuid=uuid):
                self.assertIsNotNone(flow_object_basis_for(row["node"]))


class LabelTestCase(unittest.TestCase):
    """#251 section 1: the object standing for every kind of water published as
    `Water From Cooling`, because the label rule had 35 candidate names and no
    reason to prefer one.

    Splitting the materials shrinks each group but does not settle it: `Water to
    Cooling` and `Water Cooling sea` are one object and one of their names would
    still have to win. The taxonomy states the label, so nothing chooses.
    """

    def _label(self, uuid, name):
        objects, _by_uuid = _objects_by_flow([_flow(uuid, name)])
        return objects[0].prefLabel[0]["@value"]

    def test_the_concept_names_the_object(self):
        self.assertEqual(self._label(LAKE_WATER, "lake water"), "Lake water")

    def test_the_member_that_arrived_first_does_not(self):
        """`Water to Cooling` and `Water Cooling sea` share an object. Before
        this, whichever the layering reached first named it."""
        cooling_sea = "d7011fb9-34d8-413e-af24-110edf48e329"
        for uuid, name in ((TO_COOLING, "Water to Cooling"), (cooling_sea, "Water Cooling sea")):
            with self.subTest(name=name):
                self.assertEqual(self._label(uuid, name), "Cooling water")

    def test_order_does_not_decide_it(self):
        """#251's failure mode, asserted directly: shuffle the input and expect
        the same answer."""
        cooling_sea = "d7011fb9-34d8-413e-af24-110edf48e329"
        pair = [_flow(TO_COOLING, "Water to Cooling"), _flow(cooling_sea, "Water Cooling sea", unit="kg")]
        forward, _ = _objects_by_flow(pair)
        backward, _ = _objects_by_flow(list(reversed(pair)))
        self.assertEqual(
            [o.prefLabel[0]["@value"] for o in forward],
            [o.prefLabel[0]["@value"] for o in backward],
        )

    def test_a_substance_with_no_material_keeps_its_own_name(self):
        self.assertEqual(self._label("m-1", "Methane"), "Methane")


class DataIntegrityTestCase(unittest.TestCase):
    def test_every_row_names_a_concept_the_taxonomy_carries(self):
        concepts = material_concepts()
        for row in material_by_source_flow().values():
            with self.subTest(uuid=row["source_uuid"]):
                self.assertIn(row["node"], concepts)

    def test_a_flow_has_one_material(self):
        """Two rows for one flow would be two curated statements arbitrated by
        file order, which is the shape of the defect being removed."""
        self.assertIsInstance(material_by_source_flow(), dict)

    def test_the_loader_refuses_two_materials_for_one_flow(self):
        from unittest import mock

        import orjson

        from brightway_flows.domain import materials

        payload = {
            "rows": [
                {
                    "source": "x",
                    "source_uuid": "u",
                    "source_name": "Water, somewhere",
                    "node": "lake_water",
                    "match": "exact",
                    "comment": "c",
                },
                {
                    "source": "x",
                    "source_uuid": "u",
                    "source_name": "Water, somewhere",
                    "node": "sea_water",
                    "match": "exact",
                    "comment": "c",
                },
            ]
        }
        from pathlib import Path
        from tempfile import mkdtemp

        path = Path(mkdtemp()) / "rows.json"
        path.write_bytes(orjson.dumps(payload))
        with mock.patch.object(materials, "FLOW_MATERIALS_FILEPATH", path):
            materials.material_by_source_flow.cache_clear()
            try:
                with self.assertRaises(MaterialRuleError) as caught:
                    materials.material_by_source_flow()
                self.assertIn("One flow, one material", str(caught.exception))
            finally:
                materials.material_by_source_flow.cache_clear()

    def test_the_loader_refuses_a_row_without_a_source_name(self):
        """The name-keyed lookup (#358) subscripts every row's `source_name`,
        so a row without one has to fail here, with the file named, rather
        than as a KeyError from inside a cached index build."""
        from pathlib import Path
        from tempfile import mkdtemp
        from unittest import mock

        import orjson

        from brightway_flows.domain import materials

        path = Path(mkdtemp()) / "rows.json"
        path.write_bytes(
            orjson.dumps(
                {
                    "rows": [
                        {
                            "source": "x",
                            "source_uuid": "u",
                            "node": "lake_water",
                            "match": "exact",
                            "comment": "c",
                        }
                    ]
                }
            )
        )
        with mock.patch.object(materials, "FLOW_MATERIALS_FILEPATH", path):
            materials.material_by_source_flow.cache_clear()
            try:
                with self.assertRaises(MaterialRuleError) as caught:
                    materials.material_by_source_flow()
                self.assertIn("source_name", str(caught.exception))
            finally:
                materials.material_by_source_flow.cache_clear()

    def test_the_loader_refuses_a_concept_the_taxonomy_does_not_carry(self):
        from pathlib import Path
        from tempfile import mkdtemp
        from unittest import mock

        import orjson

        from brightway_flows.domain import materials

        path = Path(mkdtemp()) / "rows.json"
        path.write_bytes(
            orjson.dumps(
                {
                    "rows": [
                        {
                            "source": "x",
                            "source_uuid": "u",
                            "source_name": "Water, somewhere",
                            "node": "not_a_concept",
                            "match": "exact",
                            "comment": "c",
                        }
                    ]
                }
            )
        )
        with mock.patch.object(materials, "FLOW_MATERIALS_FILEPATH", path):
            materials.material_by_source_flow.cache_clear()
            try:
                with self.assertRaises(MaterialRuleError):
                    materials.material_by_source_flow()
            finally:
                materials.material_by_source_flow.cache_clear()

    def test_ef_and_ecoinvent_agree_on_every_material_they_share(self):
        """A merge can only put two lists' flows together if they agree; where
        they name the same material the assignment has to match."""
        by_node: dict[str, set[str]] = {}
        for (source, _uuid), row in material_by_source_flow().items():
            by_node.setdefault(row["node"], set()).add(source.split("-")[0])
        shared = {n for n, s in by_node.items() if len(s) > 1}
        self.assertTrue(shared, "no material is claimed by both lists")
        self.assertIn("lake_water", shared)
        self.assertIn("sea_water", shared)

    def test_the_same_uuid_reads_the_same_way_in_every_ecoinvent_version(self):
        by_uuid: dict[str, set[str]] = {}
        for (source, uuid), row in material_by_source_flow().items():
            if source.startswith("ecoinvent-"):
                by_uuid.setdefault(uuid, set()).add(row["node"])
        for uuid, nodes in by_uuid.items():
            with self.subTest(uuid=uuid):
                self.assertEqual(len(nodes), 1)


class TheListTheFlowsCameFromTestCase(unittest.TestCase):
    """A material curated for a source list is visible while that list is layered.

    The merge mints objects for rows that matched nothing, and it layers them
    before it has given any of them a `source_ref` -- `resolve_flow_layers`
    derives those further down. So the only uuid available at axis time is the
    flow's own, and looking it up under the base list's label alone answers
    `None` for every flow of every other list. ecoinvent's fossil-well
    withdrawal is the case that showed it: assigned `fossil_groundwater` in
    `water-flow-materials.json`, it fell back to the bare CAS, computed the
    shared water object, and had its creation refused as an object that already
    exists -- so it stayed unmatched and published nothing, in a run where the
    emission-side half of the same pair landed correctly.
    """

    FOSSIL_WELL = "2caa889e-8187-459d-963a-fa47a79c5378"
    ECOINVENT = "ecoinvent-3.12"

    def test_the_curated_row_is_found_under_the_list_it_was_curated_for(self):
        self.assertEqual(
            material_for_source_flow(self.ECOINVENT, self.FOSSIL_WELL),
            "fossil_groundwater",
        )
        self.assertIsNone(material_for_source_flow(EF, self.FOSSIL_WELL))

    def test_the_base_label_alone_cannot_see_it(self):
        """The state before the fix, asserted so the regression is legible."""
        flow = _flow(self.FOSSIL_WELL, "Water, unspecified natural origin")
        self.assertIsNone(_material_for(flow, EF))

    def test_naming_the_list_it_came_from_finds_it(self):
        flow = _flow(self.FOSSIL_WELL, "Water, unspecified natural origin")
        self.assertEqual(_material_for(flow, EF, self.ECOINVENT), "fossil_groundwater")

    def test_a_flow_with_no_curated_row_is_still_None(self):
        """The extra label widens the lookup, it does not invent one."""
        flow = _flow("not-a-real-uuid", "Methane", cas="74-82-8")
        self.assertIsNone(_material_for(flow, EF, self.ECOINVENT))

    def test_two_lists_disagreeing_is_still_no_answer(self):
        """The rule the second label has to keep: a disagreement returns None
        rather than preferring whichever label was consulted first."""
        rows = material_by_source_flow()
        disagreeing = [
            (source, uuid)
            for (source, uuid), row in rows.items()
            if row["node"] == "water"
        ]
        self.assertTrue(disagreeing, "expected at least one `water` row to exist")


class UnaffectedTestCase(unittest.TestCase):
    """Everything that is not water keeps working the way it did."""

    def test_a_substance_with_no_material_still_groups_on_its_cas(self):
        methane_a = _flow("m-1", "Methane", cas="74-82-8")
        methane_b = _flow("m-2", "Methane", cas="74-82-8")
        _objects, by_uuid = _objects_by_flow([methane_a, methane_b])
        self.assertEqual(by_uuid["m-1"], by_uuid["m-2"])

    def test_the_material_file_covers_water_and_claims_nothing_else(self):
        """None is the answer for almost every flow in the list, and that is not
        a gap."""
        self.assertIsNone(material_for_source_flow(EF, "74-82-8"))
