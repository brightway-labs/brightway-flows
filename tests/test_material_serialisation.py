"""What a flow object says about the material it is, and in whose words.

Q2 of `plans/water-taxonomy.md`, answered *as a type*: the ENVO or AGROVOC class
goes in `@type`, and the concept's place in our own scheme goes in
`classifications` beside the CHEMINF registry numbers.

Two things this has to get right and nothing else checks.

**The two typings are both true.** An object typed `chemrof:NeutralMolecule` and
`ENVO:00002149` looks like two incompatible claims and is not: ENVO defines
`liquid water` as *an environmental material primarily composed of dihydrogen
oxide*, so the chemistry describes what the material is made of. Substituting
one for the other would drop a true statement.

**Whose edge each one is has to survive onto the published object.** The scheme
asserts two `skos:broader` links ENVO declines to make, and a consumer that
cannot tell them from ENVO's own would be reading our additions as the
authority's.
"""

import unittest

from brightway_flows.domain.flow_object import FlowObject
from brightway_flows.domain.materials import material_concepts
from brightway_flows.domain.vocabulary import (
    IRIS,
    RDFS_LABEL_CURIE,
    SKOS_BROADER_IRI,
    SKOS_EXACT_MATCH_IRI,
    SKOS_IN_SCHEME_IRI,
    SKOS_RELATED_IRI,
    SKOS_RELATED_MATCH_IRI,
    Term,
)
from brightway_flows.pipeline.semantic_typing import (
    MATERIAL_CLASSIFICATION,
    MATERIAL_SCHEME,
    MATERIAL_SCHEME_IRI,
    _attach_material,
    _named,
)

CHEMROF_NEUTRAL_MOLECULE = IRIS[Term.NEUTRAL_MOLECULE]
ENVO_SEA_WATER = "http://purl.obolibrary.org/obo/ENVO_00002149"
ENVO_BRINE = "http://purl.obolibrary.org/obo/ENVO_00003044"


def _object(concept_id, *, types=(), flow_object_id=None):
    """A flow object as the chemistry rules leave it, before the material."""
    return FlowObject.from_dict(
        {
            "flow_object_id": flow_object_id
            or material_concepts()[concept_id]["flow_object_id"],
            "@type": list(types),
            "prefLabel": [],
            "altLabel": [],
            "classifications": {},
            "properties": {},
            "references": [],
            "created_from": {},
        }
    )


class TypingTestCase(unittest.TestCase):
    def test_the_anchor_class_is_added(self):
        obj = _object("sea_water", types=[CHEMROF_NEUTRAL_MOLECULE])
        _attach_material(obj)
        self.assertIn(ENVO_SEA_WATER, obj.types)

    def test_the_chemistry_typing_is_kept_beside_it(self):
        """Both are true. Sea water is an environmental material *and* the
        object carries the CAS of the molecule it is composed of."""
        obj = _object("sea_water", types=[CHEMROF_NEUTRAL_MOLECULE])
        _attach_material(obj)
        self.assertIn(CHEMROF_NEUTRAL_MOLECULE, obj.types)

    def test_an_object_that_is_not_a_material_is_untouched(self):
        obj = _object(None, types=[CHEMROF_NEUTRAL_MOLECULE], flow_object_id="fo-not-a-material")
        before = list(obj.types)
        self.assertEqual(_attach_material(obj), {})
        self.assertEqual(obj.types, before)
        self.assertNotIn(MATERIAL_CLASSIFICATION, obj.classifications or {})

    def test_applying_it_twice_adds_nothing(self):
        """The pipeline types objects more than once over a run."""
        obj = _object("sea_water", types=[CHEMROF_NEUTRAL_MOLECULE])
        _attach_material(obj)
        once = list(obj.types)
        _attach_material(obj)
        self.assertEqual(obj.types, once)

    def test_both_authorities_land_when_both_carry_the_concept(self):
        obj = _object("cooling_water")
        _attach_material(obj)
        self.assertIn("http://purl.obolibrary.org/obo/ENVO_03600002", obj.types)
        self.assertIn("http://aims.fao.org/aos/agrovoc/c_b1215876", obj.types)

    def test_a_minted_concept_is_typed_with_the_iri_we_minted(self):
        obj = _object("turbine_water")
        _attach_material(obj)
        self.assertTrue(
            any(t.startswith(MATERIAL_SCHEME) for t in obj.types), obj.types
        )


class CuratedChemRofTestCase(unittest.TestCase):
    """`chemrof_type` is read from the taxonomy, never derived.

    Brine is a mixture rather than the molecule, and the chemistry rules leave
    it structureless because it carries no CAS -- EF's 7732-18-5 on `Water,
    salt, sole` is an error. But *carrying no CAS does not imply being a
    mixture*, so the class is a curated fact rather than a rule applied here.
    """

    def test_a_stated_class_replaces_the_chemistry_conclusion(self):
        """It does not join it. Stating a `chemrof_type` says the chemistry
        rules cannot reach this concept, and brine is why that matters: it
        arrived carrying water's CAS -- EF's error -- and was typed
        `NeutralMolecule` from it. A published object said brine was both a
        neutral molecule and a mixture."""
        obj = _object("brine", types=[CHEMROF_NEUTRAL_MOLECULE])
        _attach_material(obj)
        self.assertNotIn(CHEMROF_NEUTRAL_MOLECULE, obj.types)
        self.assertIn(IRIS[Term.IMPRECISE_CHEMICAL_MIXTURE], obj.types)

    def test_replacing_leaves_the_anchor_alone(self):
        """Only the ChemROF conclusion is displaced; ENVO's class is not a
        competing claim about the chemistry."""
        obj = _object("brine", types=[CHEMROF_NEUTRAL_MOLECULE])
        _attach_material(obj)
        self.assertIn(ENVO_BRINE, obj.types)

    def test_brine_gets_the_class_the_taxonomy_states(self):
        obj = _object("brine")
        _attach_material(obj)
        self.assertIn(IRIS[Term.IMPRECISE_CHEMICAL_MIXTURE], obj.types)
        self.assertIn(ENVO_BRINE, obj.types)

    def test_it_is_the_only_concept_stating_one(self):
        """A second would need its own reasoning, and this is where that gets
        noticed rather than inferred."""
        stated = {
            c["id"] for c in material_concepts().values() if c.get("chemrof_type")
        }
        self.assertEqual(stated, {"brine"})

    def test_no_class_is_invented_for_the_others(self):
        """Every other water concept is composed of the molecule, so the
        chemistry rules already have it right and nothing is added."""
        for concept_id in ("sea_water", "lake_water", "water", "cooling_water"):
            with self.subTest(concept=concept_id):
                obj = _object(concept_id)
                _attach_material(obj)
                self.assertNotIn(IRIS[Term.IMPRECISE_CHEMICAL_MIXTURE], obj.types)


class SchemeTestCase(unittest.TestCase):
    def _entry(self, concept_id):
        obj = _object(concept_id)
        _attach_material(obj)
        return obj.classifications[MATERIAL_CLASSIFICATION]

    def test_the_concept_is_identified_by_its_own_iri(self):
        """`@id` is what identity is for. The block carried none because a
        JSON-LD value object may not have one -- but it is not a value object,
        `@value` being an array and `rdfs:label` sitting beside it, and nothing
        expands the flow-object layer anyway (#273)."""
        entry = self._entry("sea_water")
        self.assertEqual(entry["@id"], f"{MATERIAL_SCHEME}sea-water")
        self.assertEqual(entry["@value"], ["sea_water"])

    def test_the_scheme_is_the_scheme_and_not_the_concept(self):
        """`skos:inScheme` relates a concept to a `skos:ConceptScheme`. Naming
        the concept there said every concept was its own scheme."""
        entry = self._entry("sea_water")
        self.assertEqual(
            entry[SKOS_IN_SCHEME_IRI], [{"@id": MATERIAL_SCHEME_IRI}]
        )
        self.assertNotIn(
            {"@id": f"{MATERIAL_SCHEME}sea-water"}, entry[SKOS_IN_SCHEME_IRI]
        )

    def test_every_concept_is_in_the_one_scheme(self):
        for concept in material_concepts().values():
            if not concept["flow_object_id"]:
                continue
            with self.subTest(concept=concept["id"]):
                entry = self._entry(concept["id"])
                self.assertEqual(
                    entry[SKOS_IN_SCHEME_IRI], [{"@id": MATERIAL_SCHEME_IRI}]
                )

    def test_the_scheme_iri_is_not_a_prefix(self):
        """The namespace ends in the separator that makes it one; the scheme is
        the IRI it is a namespace of."""
        self.assertFalse(MATERIAL_SCHEME_IRI.endswith("/"))
        self.assertEqual(f"{MATERIAL_SCHEME_IRI}/", MATERIAL_SCHEME)

    def test_the_anchor_is_an_exact_match_across_schemes(self):
        """`exactMatch` is a mapping property, which SKOS says is by convention
        only used between schemes. ENVO's concept is not ours."""
        entry = self._entry("sea_water")
        self.assertEqual(entry[SKOS_EXACT_MATCH_IRI], [{"@id": ENVO_SEA_WATER}])

    def test_the_parent_is_broader_within_our_scheme(self):
        """`broader`, not `broadMatch`: both endpoints are ours, and the mapping
        properties are for links that leave the scheme."""
        entry = self._entry("sea_water")
        parent = entry[SKOS_BROADER_IRI][0]
        self.assertEqual(parent["@id"], f"{MATERIAL_SCHEME}saline-water")

    def test_a_root_states_no_parent(self):
        self.assertNotIn(SKOS_BROADER_IRI, self._entry("water"))
        self.assertNotIn(SKOS_BROADER_IRI, self._entry("water_vapour"))

    def test_green_water_is_related_rather_than_narrower(self):
        """Separate for accounting reasons and not physics, so `broader
        rainwater` would be defensible and would misfile it."""
        entry = self._entry("green_water")
        self.assertNotIn(SKOS_BROADER_IRI, entry)
        # `related`, not `relatedMatch`: both ends are ours, and the mapping
        # properties are for links that leave the scheme.
        self.assertEqual(
            entry[SKOS_RELATED_IRI], [{"@id": f"{MATERIAL_SCHEME}rainwater"}]
        )
        self.assertNotIn(SKOS_RELATED_MATCH_IRI, entry)


class LabelTestCase(unittest.TestCase):
    """Every `rdfs:label` in the document is a display string, or is absent.

    `saline_water` was the case: the one concept the taxonomy left unlabelled,
    reaching the graph as `rdfs:label "saline_water"` because the builder fell
    back to the id. A snake_case identifier where a name belongs is
    indistinguishable from one a curator typed (#273).
    """

    def _entry(self, concept_id):
        obj = _object(concept_id)
        _attach_material(obj)
        return obj.classifications[MATERIAL_CLASSIFICATION]

    def test_the_taxonomy_labels_every_concept(self):
        unlabelled = [c["id"] for c in material_concepts().values() if not c["label"]]
        self.assertEqual(unlabelled, [])

    def test_the_grouping_concept_is_labelled_where_it_is_read(self):
        """Nothing lands on `saline_water`, so it has no object of its own and
        the only place it is read is as somebody's parent."""
        for child in ("sea_water", "brine"):
            with self.subTest(concept=child):
                parent = self._entry(child)[SKOS_BROADER_IRI][0]
                self.assertEqual(parent["@id"], f"{MATERIAL_SCHEME}saline-water")
                self.assertEqual(parent[RDFS_LABEL_CURIE], "Saline water")

    def test_no_label_is_published_as_no_label(self):
        """The taxonomy labels all sixteen today; the fallback is what has to
        stay gone, so a future unlabelled concept says nothing rather than
        publishing its id."""
        node = _named({"id": "hypersaline_water", "label": None})
        self.assertEqual(node, {"@id": f"{MATERIAL_SCHEME}hypersaline-water"})
        self.assertNotIn(RDFS_LABEL_CURIE, node)


class WhoseEdgeSurvivesTestCase(unittest.TestCase):
    """The provenance has to reach the published object, not stop at the file.

    A consumer reading `lake water broader surface water` has no way to know
    ENVO does not say that unless the object says so.
    """

    def _parent(self, concept_id):
        obj = _object(concept_id)
        _attach_material(obj)
        return obj.classifications[MATERIAL_CLASSIFICATION][SKOS_BROADER_IRI][0]

    @staticmethod
    def _edge_source(parent):
        return parent["provenance"]["edge_source"]

    def test_an_edge_of_ours_says_so(self):
        self.assertEqual(self._edge_source(self._parent("lake_water")), "ours")
        self.assertEqual(self._edge_source(self._parent("river_water")), "ours")

    def test_an_edge_of_theirs_says_so(self):
        self.assertEqual(self._edge_source(self._parent("sea_water")), "asserted")
        self.assertEqual(self._edge_source(self._parent("rainwater")), "asserted")

    def test_a_shortened_chain_says_so(self):
        self.assertEqual(self._edge_source(self._parent("brine")), "shortened")

    def test_every_material_object_carries_its_provenance(self):
        for concept in material_concepts().values():
            if not concept.get("flow_object_id"):
                continue
            with self.subTest(concept=concept["id"]):
                entry = self._entry_for(concept["id"])
                self.assertTrue(entry["provenance"]["prov:wasGeneratedBy"])

    def _entry_for(self, concept_id):
        obj = _object(concept_id)
        _attach_material(obj)
        return obj.classifications[MATERIAL_CLASSIFICATION]
