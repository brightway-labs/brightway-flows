"""`concept_associations` is keyed with CURIEs, and its shape is versioned (#218).

The object changed twice without a version signal. #208 removed `xkos:mapType` --
correctly, because XKOS defines no property for the type or strength of a
mapping, so the match belongs on the source concept as a SKOS mapping property --
and expanded `skos:prefLabel` to a full IRI in passing, leaving one object mixing
CURIEs (`xkos:`, `qudt:`) with expanded IRIs. `schema_version` stayed at 1
through both, so a consumer reading `xkos:mapType` got nothing and had no way to
detect it.

These pin what the two decisions settled on: CURIEs throughout, the mapping
property on the source concept, and a version that moves when the shape does.
"""

import unittest

from brightway_flows.domain.schema import SCHEMA_VERSION
from brightway_flows.domain.vocabulary import (
    JSONLD_CONTEXT,
    SKOS_EXACT_MATCH_CURIE,
    SKOS_PREF_LABEL_CURIE,
    Term,
    curie,
)
from brightway_flows.domain.context_registry import context_from_dict
from brightway_flows.domain.elementary_flow import ElementaryFlow
from brightway_flows.merge.provenance import _append_concept_association
from brightway_flows.sources import resolve_source_list


def _association() -> dict:
    row = ElementaryFlow(
        elementary_flow_id="ef-1",
        flow_object_id="fo-1",
        source="EF 3.1",
        context=context_from_dict(
            {"dimension": "Environmental", "media": "Air", "strata": "Unknown"}
        ),
        context_iri="",
        unit="kg",
        unit_iri="",
        lcia_methods=[],
        general_comment=None,
        concept_associations=[],
    )
    _append_concept_association(
        target_row=row,
        source=resolve_source_list("ecoinvent-3.12"),
        source_uuid="s-1",
        source_name="Carbon dioxide",
        source_context=["air", "unspecified"],
        source_unit="kg",
        map_type_curie=SKOS_EXACT_MATCH_CURIE,
        provenance={},
        conversion_factor=None,
    )
    return row.concept_associations[0]


class CurieFormTestCase(unittest.TestCase):
    def test_curie_is_generated_from_the_registry(self):
        """Not written out.  The registry exists so that a term cannot be
        emitted without being declared, and that has to hold for the compact
        form too, or the two spellings drift."""
        self.assertEqual(curie(Term.PREF_LABEL), "skos:prefLabel")
        self.assertEqual(curie(Term.EXACT_MATCH), "skos:exactMatch")
        self.assertEqual(curie(Term.SOURCE_CONCEPT), "xkos:sourceConcept")

    def test_every_prefix_a_curie_can_use_is_declared(self):
        """A CURIE only means something if its prefix expands, and
        `JSONLD_CONTEXT` is what expands it."""
        for term in Term:
            with self.subTest(term=term.value):
                prefix = curie(term).split(":", 1)[0]
                self.assertIn(prefix, JSONLD_CONTEXT)

    def test_a_curie_expands_to_its_iri(self):
        from brightway_flows.domain.vocabulary import IRIS

        for term in Term:
            with self.subTest(term=term.value):
                prefix, local = curie(term).split(":", 1)
                self.assertEqual(JSONLD_CONTEXT[prefix] + local, IRIS[term])


class AssociationShapeTestCase(unittest.TestCase):
    def test_the_source_concept_is_keyed_with_curies(self):
        source = _association()["xkos:sourceConcept"]
        self.assertIn(SKOS_PREF_LABEL_CURIE, source)
        self.assertEqual(source[SKOS_PREF_LABEL_CURIE], "Carbon dioxide")

    def test_no_key_in_the_object_is_an_expanded_iri(self):
        """The mixed-convention bug, asserted directly: one object, one
        convention."""
        assoc = _association()
        keys = list(assoc) + list(assoc["xkos:sourceConcept"])
        expanded = [k for k in keys if k.startswith("http://") or k.startswith("https://")]
        self.assertEqual(expanded, [])

    def test_the_match_is_a_mapping_property_on_the_source_concept(self):
        """XKOS has no `mapType`; #208 removed it deliberately and this keeps it
        removed rather than letting it drift back."""
        assoc = _association()
        self.assertNotIn("xkos:mapType", assoc)
        self.assertIn(SKOS_EXACT_MATCH_CURIE, assoc["xkos:sourceConcept"])

    def test_the_target_concept_is_still_a_sibling_of_the_source(self):
        assoc = _association()
        self.assertEqual(assoc["@type"], "xkos:ConceptAssociation")
        self.assertIn("xkos:targetConcept", assoc)


class SchemaVersionTestCase(unittest.TestCase):
    def test_the_version_moved_past_the_shape_that_had_map_type(self):
        """A consumer written against `xkos:mapType` needs a signal that the
        document it is holding no longer has one."""
        self.assertGreaterEqual(SCHEMA_VERSION, 2)


if __name__ == "__main__":
    unittest.main()
