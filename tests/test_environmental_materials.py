"""The material taxonomy: its shape, its anchors, and whose edges they are.

The scheme is ours and some of its edges are not.  `sea water skos:broader
saline water` is ENVO's own; `lake water skos:broader surface water` is one we
add because the LCA reading needs it and ENVO declines to make it.  Publishing
both indistinguishably is the one thing a scheme that maps out to a published
ontology must not do, so `broader_source` records which is which — and these
tests are what stop it being decoration, by checking every claim in it back
against `material-anchor-snapshot.json`.

The file is generated. Hand-editing it could relabel one of our edges as the
authority's, which nothing downstream would notice, so a test regenerates it and
compares.
"""

import json
import unittest
from hashlib import sha1

import orjson

from brightway_flows.domain.flow_object import stable_flow_object_id
from brightway_flows.domain.materials import (
    BROADER_ASSERTED,
    BROADER_OURS,
    BROADER_ROOT,
    BROADER_SHORTENED,
    MATERIALS_FILEPATH,
    anchor_snapshot,
    broader_chain,
    material_concepts,
)

WATER_CAS = "7732-18-5"


def _envo_parents(accession):
    row = anchor_snapshot()["envo"].get(accession)
    return {p["id"].replace(":", "_") for p in row["parents"]} if row else set()


def _envo_id(concept):
    return next(
        (a["id"] for a in concept["anchors"] if a["authority"] == "envo"), None
    )


class ShapeTestCase(unittest.TestCase):
    def test_seventeen_concepts_and_sixteen_flow_objects(self):
        concepts = material_concepts()
        self.assertEqual(len(concepts), 17)
        self.assertEqual(sum(1 for c in concepts.values() if c["flow_object_id"]), 16)

    def test_the_one_concept_without_an_object_is_the_one_nothing_maps_onto(self):
        """A concept earns an object when a source flow lands on it. Carrying
        `saline_water` is what gives sea water and brine the parent ENVO gives
        them; nothing maps onto it, so it mints nothing."""
        without = [
            c["id"] for c in material_concepts().values() if not c["flow_object_id"]
        ]
        self.assertEqual(without, ["saline_water"])

    def test_an_intermediate_is_carried_only_when_it_groups_two_concepts(self):
        """The test for adding one. `underground water`, `hypersaline water` and
        `stream water` would each group one, and are recorded as skipped steps."""
        concepts = material_concepts()
        children: dict[str, int] = {}
        for concept in concepts.values():
            if concept["broader"]:
                children[concept["broader"]] = children.get(concept["broader"], 0) + 1
        for concept_id in (c for c in concepts if not concepts[c]["flow_object_id"]):
            with self.subTest(concept=concept_id):
                self.assertGreaterEqual(children.get(concept_id, 0), 2)

    def test_every_broader_names_a_concept_that_exists(self):
        concepts = material_concepts()
        for concept in concepts.values():
            with self.subTest(concept=concept["id"]):
                if concept["broader"] is not None:
                    self.assertIn(concept["broader"], concepts)

    def test_every_chain_terminates(self):
        for concept_id in material_concepts():
            with self.subTest(concept=concept_id):
                self.assertEqual(broader_chain(concept_id)[0], concept_id)

    def test_the_scheme_has_two_material_roots_and_one_concept_outside_it(self):
        """ENVO branches vapour away from liquid water, so one root cannot hold
        both. `green_water` is a third root but not a material: it is an
        accounting category, separate for accounting reasons and not physics."""
        roots = {
            c["id"]
            for c in material_concepts().values()
            if c["broader_source"] == BROADER_ROOT
        }
        self.assertEqual(roots, {"water", "water_vapour", "green_water"})
        self.assertEqual(material_concepts()["green_water"]["related"], ["rainwater"])

    def test_every_concept_carries_its_reasoning(self):
        for concept in material_concepts().values():
            with self.subTest(concept=concept["id"]):
                self.assertGreater(len(concept["comment"]), 40)


class WhoseEdgeIsItTestCase(unittest.TestCase):
    """Each `broader_source` claim, checked back against the authority.

    A wrong value here is undetectable downstream and dishonest upstream: it
    would either credit ENVO with an edge we invented, or claim as ours one they
    already make.
    """

    def test_an_asserted_edge_really_is_asserted(self):
        concepts = material_concepts()
        for concept in concepts.values():
            if concept["broader_source"] != BROADER_ASSERTED:
                continue
            with self.subTest(concept=concept["id"]):
                parent_envo = _envo_id(concepts[concept["broader"]])
                self.assertIn(parent_envo, _envo_parents(_envo_id(concept)))

    def test_a_shortened_edge_is_not_direct_but_is_reachable(self):
        concepts = material_concepts()
        shortened = [
            c for c in concepts.values() if c["broader_source"] == BROADER_SHORTENED
        ]
        self.assertTrue(shortened)
        for concept in shortened:
            with self.subTest(concept=concept["id"]):
                parent_envo = _envo_id(concepts[concept["broader"]])
                self.assertNotIn(parent_envo, _envo_parents(_envo_id(concept)))
                self.assertTrue(concept["broader_via"], "the skipped step is unrecorded")

    def test_an_edge_we_claim_as_ours_really_is_not_theirs(self):
        """Directly or transitively. Getting this backwards would overstate what
        we invented, which is the safer error but still an error."""
        concepts = material_concepts()
        for concept in concepts.values():
            if concept["broader_source"] != BROADER_OURS:
                continue
            envo_id = _envo_id(concept)
            if envo_id is None:
                continue  # turbine water: no published class to disagree with
            with self.subTest(concept=concept["id"]):
                reachable, frontier = set(), list(_envo_parents(envo_id))
                while frontier:
                    current = frontier.pop()
                    if current in reachable:
                        continue
                    reachable.add(current)
                    frontier.extend(_envo_parents(current))
                self.assertNotIn(_envo_id(concepts[concept["broader"]]), reachable)

    def test_three_edges_are_ours_where_the_authority_has_an_opinion(self):
        """Section 2 of the plan named two. `fossil_groundwater` is the third,
        and it is here rather than in the set because each of the three was
        argued for on the record: ENVO files bore hole water under liquid water,
        so putting it under groundwater is our claim and not ENVO's. A fourth
        appearing unannounced is what this asserts against."""
        ours = {
            c["id"]
            for c in material_concepts().values()
            if c["broader_source"] == BROADER_OURS and _envo_id(c)
        }
        self.assertEqual(ours, {"lake_water", "river_water", "fossil_groundwater"})

    def test_the_one_close_match_is_the_one_that_is_not_an_equivalence(self):
        """Every other concept says `exactMatch`, and means it. Fossil
        groundwater overlaps ENVO's `bore hole water` without being it -- a bore
        hole says how the water was reached, not that it is fossil -- so an
        equivalence would be a claim the authority does not carry."""
        close = {
            c["id"]: [a["predicate"] for a in c["anchors"] if a["authority"] == "envo"]
            for c in material_concepts().values()
            if any(
                a.get("predicate") == "skos:closeMatch"
                for a in c["anchors"]
            )
        }
        self.assertEqual(close, {"fossil_groundwater": ["skos:closeMatch"]})

    def test_the_only_other_edge_of_ours_is_the_one_with_no_class_at_all(self):
        """A different kind of ours: not a disagreement, an absence."""
        concepts = material_concepts()
        unanchored = [
            c["id"]
            for c in concepts.values()
            if c["broader_source"] == BROADER_OURS and not _envo_id(c)
        ]
        self.assertEqual(unanchored, ["turbine_water"])
        minted = concepts["turbine_water"]["anchors"]
        self.assertEqual([a["authority"] for a in minted], ["brightway"])
        self.assertTrue(minted[0]["iri"].startswith("https://vocab.brightway.one/"))

    def test_following_the_authority_where_it_has_an_opinion(self):
        """Two edges an earlier draft flattened onto the root. Both are ENVO's,
        and inventing an edge where the authority already has one is the same
        error as the reverse."""
        concepts = material_concepts()
        self.assertEqual(concepts["rainwater"]["broader"], "fresh_water")
        self.assertEqual(concepts["rainwater"]["broader_source"], BROADER_ASSERTED)
        self.assertEqual(concepts["waste_water"]["broader"], "contaminated_water")
        self.assertEqual(concepts["waste_water"]["broader_source"], BROADER_ASSERTED)


class AnchorsTestCase(unittest.TestCase):
    def test_every_anchor_is_one_the_snapshot_resolved(self):
        snapshot = anchor_snapshot()
        for concept in material_concepts().values():
            for anchor in concept["anchors"]:
                with self.subTest(concept=concept["id"], anchor=anchor["id"]):
                    if anchor["authority"] == "brightway":
                        continue
                    self.assertIn(anchor["id"], snapshot[anchor["authority"]])

    def test_every_anchor_label_matches_the_authority(self):
        """The file repeats the label for readability, which is a place for it
        to drift out of step with the class it names."""
        snapshot = anchor_snapshot()
        for concept in material_concepts().values():
            for anchor in concept["anchors"]:
                if anchor["authority"] == "brightway":
                    continue
                with self.subTest(anchor=anchor["id"]):
                    self.assertEqual(
                        anchor["label"], snapshot[anchor["authority"]][anchor["id"]]["label"]
                    )

    def test_cooling_water_is_anchored_in_both_authorities(self):
        """Where both carry a concept, mapping to both is evidence rather than
        redundancy."""
        authorities = {
            a["authority"] for a in material_concepts()["cooling_water"]["anchors"]
        }
        self.assertEqual(authorities, {"envo", "agrovoc"})

    def test_water_vapour_absorbs_a_class_that_is_really_its_child(self):
        """Folding `atmospheric water vapour` in loses nothing only because ENVO
        makes it a child. If it were a sibling this would be a lost distinction."""
        absorbed = material_concepts()["water_vapour"]["absorbs"]
        self.assertEqual([a["id"] for a in absorbed], ["ENVO_01000268"])
        self.assertIn("ENVO_01000266", _envo_parents("ENVO_01000268"))


class FlowObjectIdentityTestCase(unittest.TestCase):
    def test_every_id_reproduces_from_its_basis(self):
        for concept in material_concepts().values():
            if not concept["flow_object_id"]:
                continue
            with self.subTest(concept=concept["id"]):
                self.assertEqual(
                    concept["flow_object_id"],
                    stable_flow_object_id("fo", concept["flow_object_basis"]),
                )

    def test_the_two_published_objects_keep_their_ids(self):
        """The convention is checked against ids that already exist before any
        code mints a new one: unqualified water keeps the bare CAS basis, and
        green water's qualifier basis reproduces the id it already has."""
        concepts = material_concepts()
        self.assertEqual(concepts["water"]["flow_object_basis"], f"cas:{WATER_CAS}")
        self.assertEqual(concepts["water"]["flow_object_id"], "fo-464532a8f956fd39")
        self.assertEqual(
            concepts["green_water"]["flow_object_id"], "fo-600e1fead384b3a5"
        )

    def test_no_two_concepts_share_a_flow_object(self):
        ids = [
            c["flow_object_id"]
            for c in material_concepts().values()
            if c["flow_object_id"]
        ]
        self.assertEqual(len(ids), len(set(ids)))

    def test_brine_is_the_one_object_carrying_no_cas(self):
        """EF gives `Water, salt, sole` CAS 7732-18-5 and that is an error: brine
        is a mixture, not the molecule."""
        concepts = material_concepts()
        without = [c["id"] for c in concepts.values() if c["cas_number"] is None]
        self.assertEqual(without, ["brine"])
        self.assertEqual(concepts["brine"]["flow_object_basis"], "material:brine")

    def test_every_other_object_carries_waters_chemistry(self):
        for concept in material_concepts().values():
            if concept["id"] == "brine" or not concept["flow_object_id"]:
                continue
            with self.subTest(concept=concept["id"]):
                self.assertEqual(concept["cas_number"], WATER_CAS)
                self.assertEqual(concept["chebi"], "CHEBI:15377")
                self.assertIn(WATER_CAS, concept["flow_object_basis"])


class GeneratedFileTestCase(unittest.TestCase):
    """Hand-editing could relabel one of our edges as the authority's."""

    def test_it_is_what_the_generator_produces(self):
        import importlib.util
        import sys
        from pathlib import Path

        tool = (
            Path(__file__).resolve().parent.parent
            / "tools"
            / "build_environmental_materials.py"
        )
        spec = importlib.util.spec_from_file_location("_build_materials", tool)
        module = importlib.util.module_from_spec(spec)
        sys.modules["_build_materials"] = module
        spec.loader.exec_module(module)

        published = orjson.loads(MATERIALS_FILEPATH.read_bytes())
        try:
            module.main()
            regenerated = orjson.loads(MATERIALS_FILEPATH.read_bytes())
        finally:
            MATERIALS_FILEPATH.write_bytes(
                json.dumps(published, indent=2).encode() + b"\n"
            )
        self.assertEqual(published, regenerated)

    def test_the_generator_derives_ids_the_same_way_the_domain_does(self):
        import importlib.util
        import sys
        from pathlib import Path

        tool = (
            Path(__file__).resolve().parent.parent
            / "tools"
            / "build_environmental_materials.py"
        )
        spec = importlib.util.spec_from_file_location("_build_materials2", tool)
        module = importlib.util.module_from_spec(spec)
        sys.modules["_build_materials2"] = module
        spec.loader.exec_module(module)

        basis = "material:sea_water|cas:7732-18-5"
        self.assertEqual(
            module.flow_object_id(basis), stable_flow_object_id("fo", basis)
        )
        self.assertEqual(
            module.flow_object_id(basis), "fo-" + sha1(basis.encode()).hexdigest()[:16]
        )
