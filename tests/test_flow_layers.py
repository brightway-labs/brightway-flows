import json
import tempfile
import unittest
from dataclasses import fields
from pathlib import Path

from brightway_flows.domain.elementary_flow import ElementaryFlow
from brightway_flows.domain.flow import Flow
from brightway_flows.domain.flow_object import FlowObject
from brightway_flows.flow_layers import resolve_flow_layers
from brightway_flows.flow_layers.labels import (
    _object_alt_label_values,
    _object_pref_label_value,
)
from brightway_flows.sources import base_source_list

#: `resolve_flow_layers` asks which list its flows came from rather than
#: reading it off `flow.source`, and these are the base list's rows (#13).
BASE = base_source_list()


def _as_flows(rows):
    """resolve_flow_layers takes Flow records; tests still author dicts."""
    return [Flow.from_dict(r) for r in rows]



class FlowLayersTestCase(unittest.TestCase):
    def test_groups_same_substance_across_contexts(self):
        flows = [
            {
                "uuid": "u1",
                "name": "Carbon dioxide",
                "source": "EF 3.1",
                "context": {"dimension": "Environmental", "media": "Air", "strata": "Ground level", "population_density": "Urban (>1000 people/square mile)"},
                "cas_numbers": ["124-38-9"],
                "ec_numbers": ["204-696-9"],
                "properties": {"pubchem": {"cids": [280]}},
            },
            {
                "uuid": "u2",
                "name": "carbon dioxide",
                "source": "ecoinvent-3.12",
                "context": {"dimension": "Environmental", "media": "Air", "strata": "Ground level", "population_density": "Rural (<1000 people/square mile)"},
                "cas_numbers": ["124-38-9"],
                "ec_numbers": ["204-696-9"],
                "properties": {"pubchem": {"cids": [280], "formulas": ["CO2"]}},
            },
        ]

        flow_objects, elementary_flows, stats = resolve_flow_layers(_as_flows(flows), source_list=BASE)

        self.assertEqual(stats["flow_object_count"], 1)
        self.assertEqual(stats["elementary_flow_count"], 2)
        self.assertEqual(elementary_flows[0].flow_object_id, elementary_flows[1].flow_object_id)
        self.assertIn("formulas", flow_objects[0].properties["pubchem"])
        classifications = flow_objects[0].classifications
        self.assertIn("http://semanticscience.org/resource/CHEMINF_000446", classifications)
        self.assertIn("http://semanticscience.org/resource/CHEMINF_000447", classifications)
        cas_class = classifications["http://semanticscience.org/resource/CHEMINF_000446"]
        self.assertEqual(cas_class.get("@value"), ["124-38-9"])
        self.assertTrue(cas_class.get("rdfs:seeAlso"))
        self.assertIn("provenance", cas_class)

    def test_uuid_override_forces_object_id(self):
        flows = [
            {
                "uuid": "u1",
                "name": "Methane",
                "source": "EF 3.1",
                "context": {"dimension": "Environmental", "media": "Air", "strata": "High stack, >150 meters",
             "population_density": "Urban (>1000 people/square mile)"},
                "cas_numbers": ["74-82-8"],
            }
        ]
        payload = {
            "schema_version": 1,
            "uuid_overrides": [
                {"source_uuid": "u1", "flow_object_id": "fo-manual"}
            ],
            "merge_groups": [],
        }

        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "overrides.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            flow_objects, elementary_flows, stats = resolve_flow_layers(
                _as_flows(flows), source_list=BASE, overrides_path=path
            )

        self.assertEqual(flow_objects[0].flow_object_id, "fo-manual")
        self.assertEqual(elementary_flows[0].flow_object_id, "fo-manual")
        self.assertEqual(stats["override_hits"], 1)


class MergeGroupLabelTestCase(unittest.TestCase):
    """A merge group joins flows whose names disagree, so it has to say which
    name the object takes.

    Without a statement that is settled by the length rule, which prefers the
    longer string and is not a decision -- on EF 3.1's renewable energy pairs it
    keeps one legacy name and drops another, on nothing but how the two strings
    happened to be spelled (#73).
    """

    FLOWS = [
        {
            "uuid": "u-kept",
            "name": "Energy, Geothermal, Converted",
            "prefLabel": [{"@value": "Energy, Geothermal, Converted", "@language": "en"}],
            "source": "EF 3.1",
            "unit": "MJ",
            "context": {"dimension": "Resource", "media": "Ground"},
        },
        {
            "uuid": "u-legacy",
            "name": "Primary Energy From Geothermics",
            "prefLabel": [
                {"@value": "Primary Energy From Geothermics", "@language": "en"}
            ],
            "source": "EF 3.1",
            "unit": "MJ",
            "context": {"dimension": "Resource", "media": "Ground"},
        },
    ]

    def _resolve(self, group):
        payload = {
            "schema_version": 1,
            "uuid_overrides": [],
            "merge_groups": [group],
        }
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "overrides.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            return resolve_flow_layers(
                _as_flows(self.FLOWS), source_list=BASE, overrides_path=path
            )

    def test_a_stated_label_names_the_object_and_the_other_name_is_kept(self):
        flow_objects, elementary_flows, _stats = self._resolve({
            "flow_object_id": "fo-energy",
            "preferred_label": "Energy, Geothermal, Converted",
            "source_uuids": ["u-kept", "u-legacy"],
        })

        self.assertEqual(len(flow_objects), 1)
        self.assertEqual(
            _object_pref_label_value(flow_objects[0]),
            "Energy, Geothermal, Converted",
        )
        self.assertIn(
            "Primary Energy From Geothermics",
            _object_alt_label_values(flow_objects[0]),
        )
        self.assertEqual(
            {row.flow_object_id for row in elementary_flows}, {"fo-energy"}
        )

    def test_the_statement_does_not_depend_on_the_order_the_flows_arrive_in(self):
        payload = {
            "schema_version": 1,
            "uuid_overrides": [],
            "merge_groups": [{
                "flow_object_id": "fo-energy",
                "preferred_label": "Energy, Geothermal, Converted",
                "source_uuids": ["u-kept", "u-legacy"],
            }],
        }
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "overrides.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            flow_objects, _flows, _stats = resolve_flow_layers(
                _as_flows(list(reversed(self.FLOWS))),
                source_list=BASE,
                overrides_path=path,
            )

        self.assertEqual(
            _object_pref_label_value(flow_objects[0]),
            "Energy, Geothermal, Converted",
        )
        self.assertIn(
            "Primary Energy From Geothermics",
            _object_alt_label_values(flow_objects[0]),
        )

    def test_a_group_that_states_nothing_falls_back_to_the_length_rule(self):
        """The behaviour a group written before this had, kept so that adding
        the field to one group does not change another."""
        flow_objects, _flows, _stats = self._resolve({
            "flow_object_id": "fo-energy",
            "source_uuids": ["u-kept", "u-legacy"],
        })

        self.assertEqual(
            _object_pref_label_value(flow_objects[0]),
            "Primary Energy From Geothermics",
        )
        self.assertEqual(_object_alt_label_values(flow_objects[0]), [])

    def test_a_stated_label_no_member_carries_still_names_the_object(self):
        """Both names then become alternatives.  Nothing in the shipped file
        does this, and it is checked because the alternative -- silently
        ignoring a label that matches no member -- would leave the length rule
        deciding under a statement that says otherwise."""
        flow_objects, _flows, _stats = self._resolve({
            "flow_object_id": "fo-energy",
            "preferred_label": "Geothermal energy",
            "source_uuids": ["u-kept", "u-legacy"],
        })

        self.assertEqual(
            _object_pref_label_value(flow_objects[0]), "Geothermal energy"
        )
        self.assertEqual(
            sorted(_object_alt_label_values(flow_objects[0])),
            ["Energy, Geothermal, Converted", "Primary Energy From Geothermics"],
        )


class ElementaryFlowRepresentsEveryFlowTestCase(unittest.TestCase):
    """`ElementaryFlow` must be able to hold any row of `elementary-flows.json`.

    It could not: `source_refs` was declared required, and a flow that no source
    list has been merged onto does not have one -- which is most of them. The
    merge only ever round-tripped the flows it had just created, so `from_dict`
    raised on two thirds of the file and nothing noticed.

    The merge holds these as records from here on, so both shapes have to parse,
    and both have to serialise back to exactly what they came from: key order
    included, since `to_dict()` output is the published artifact.
    """

    BASE = {
        "elementary_flow_id": "ef-1",
        "flow_object_id": "fo-1",
        "source": "EF 3.1",
        "context": {"dimension": "Environmental", "media": "Air", "strata": "Unknown"},
        "context_iri": "https://vocab.brightway.one/flow-contexts/envi-air",
        "unit": "kg",
        "unit_iri": "https://qudt.org/vocab/unit/KiloGM",
        "lcia_methods": [],
        "general_comment": None,
        "cas_match_labels": {},
        "concept_associations": [],
    }

    def test_a_flow_with_no_source_refs_parses(self):
        flow = ElementaryFlow.from_dict(dict(self.BASE))
        self.assertIsNone(flow.source_refs)

    def test_a_flow_with_no_source_refs_does_not_gain_the_key(self):
        """Emitting `"source_refs": []` would change 400 records in the file."""
        self.assertNotIn("source_refs", ElementaryFlow.from_dict(dict(self.BASE)).to_dict())

    def test_both_shapes_round_trip_exactly(self):
        # Built key by key rather than with `dict(BASE, source_refs=...)`: that
        # would append the key at the end, whereas the artifact carries it
        # fourth, and the point of the test is that the position is preserved.
        merged = {}
        for key, value in self.BASE.items():
            merged[key] = "ecoinvent algorithm addition" if key == "source" else value
            if key == "source":
                merged["source_refs"] = [
                    {"list_name": "ecoinvent", "list_version": "3.12"}
                ]
        for label, payload in (("no source refs", dict(self.BASE)), ("merged", merged)):
            with self.subTest(label):
                out = ElementaryFlow.from_dict(payload).to_dict()
                self.assertEqual(out, payload)
                self.assertEqual(list(out), list(payload), "key order moved")

    def test_source_refs_keeps_its_declared_position(self):
        """It is keyword-only so that a default need not move the declaration.

        Moving it would move the key in every merged record's serialisation.
        """
        names = [f.name for f in fields(ElementaryFlow)]
        self.assertEqual(names[:5],
                         ["elementary_flow_id", "flow_object_id", "source",
                          "source_refs", "context"])


class DefinitionMarkupTestCase(unittest.TestCase):
    """Definitions are published, and never passed through `coerce_label`.

    ChEBI writes markup into 29,660 of its definitions, so a full run published
    7,647 of them with `<i>`, `<sub>` and `<small>` intact -- in
    `flow-objects.json` and, flattened to strings, in the simple export.
    """

    SKOS_DEFINITION = "http://www.w3.org/2004/02/skos/core#definition"

    def _resolve(self, definition):
        flows = _as_flows([{
            "uuid": "u1",
            "name": "(2E,4E)-hexadienal",
            "source": "EF 3.1",
            "context": {"dimension": "Environmental", "media": "Air", "strata": "Unknown"},
            "cas_numbers": ["142-83-6"],
            self.SKOS_DEFINITION: [definition],
        }])
        flow_objects, _elementary, _stats = resolve_flow_layers(flows, source_list=BASE)
        return flow_objects[0].skos_definition

    def test_markup_is_stripped_from_a_definition(self):
        definitions = self._resolve({
            "@value": "A hexadienal with <i>trans</i> double bonds at positions 2 and 4.",
            "@language": "en",
        })
        self.assertEqual(
            definitions[0]["@value"],
            "A hexadienal with trans double bonds at positions 2 and 4.",
        )

    def test_the_rest_of_the_entry_is_left_alone(self):
        """Only `@value` is rewritten; language and provenance come through."""
        definitions = self._resolve({
            "@value": "An <i>N</i>-acylglycine.",
            "@language": "en",
            "provenance": {"prov:wasGeneratedBy": "enrich_references.chebi_definition"},
        })
        self.assertEqual(definitions[0]["@language"], "en")
        self.assertEqual(
            definitions[0]["provenance"],
            {"prov:wasGeneratedBy": "enrich_references.chebi_definition"},
        )

    def test_a_clean_definition_is_unchanged(self):
        definitions = self._resolve({"@value": "A hexadienal.", "@language": "en"})
        self.assertEqual(definitions[0]["@value"], "A hexadienal.")


class ObjectLabelHelpersTestCase(unittest.TestCase):
    """Both helpers returned the empty value for every flow object.

    Their `not isinstance(obj, dict)` guard is true of every record, so the EF
    name index built from prefLabel was empty, kBq isotope objects were never
    matched by label, and the two sorts keyed on prefLabel ordered nothing.
    """

    def _object(self):
        return FlowObject(
            flow_object_id="fo-1",
            prefLabel=[{"@value": "Carbon dioxide", "@language": "en"}],
            altLabel=[{"@value": "CO2", "@language": "en"}],
            properties={}, references=[], created_from={},
        )

    def test_pref_label_of_a_flow_object_is_its_pref_label(self):
        self.assertEqual(_object_pref_label_value(self._object()), "Carbon dioxide")

    def test_alt_labels_of_a_flow_object_are_its_alt_labels(self):
        self.assertEqual(_object_alt_label_values(self._object()), ["CO2"])

    def test_a_missing_flow_object_is_still_the_empty_value(self):
        """Callers pass `by_id.get(...)` straight in, so None must be safe."""
        self.assertEqual(_object_pref_label_value(None), "")
        self.assertEqual(_object_alt_label_values(None), [])


if __name__ == "__main__":
    unittest.main()
