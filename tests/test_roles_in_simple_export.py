"""Roles reaching `harmonised-flows-simple`, the export a practitioner reads.

The flow-object artifact carried roles from #269; this covers the path that puts
them on a flow: flow object -> `Flow.roles` -> `SimpleFlow` -> published
document, and the flattening that happens on the way.
"""

from __future__ import annotations

import unittest
from typing import Any

from brightway_flows.domain.common import Provenance
from brightway_flows.domain.context_registry import (
    context_for_iri,
    context_from_dict,
)

AGRICULTURAL_SOIL = "https://vocab.brightway.one/flow-contexts/envi-grou-agri"
from brightway_flows.domain.flow import Flow
from brightway_flows.domain.flow_object import FlowObject, Role
from brightway_flows.domain.simple_flow import SimpleFlow
from brightway_flows.domain.vocabulary import (
    JSONLD_CONTEXT,
    RDFS_LABEL_CURIE,
    RO_HAS_ROLE_IRI,
    SKOS_DEFINITION_IRI,
)
from brightway_flows.pipeline.exporting import export_roles, strip_lcia_from_flows

HERBICIDE = "http://purl.obolibrary.org/obo/CHEBI_24527"
PESTICIDE = "http://purl.obolibrary.org/obo/CHEBI_25944"


#: Air of unstated height.  These fixtures said `["Air"]` back when the
#: field held anything; the context they meant is this one.
_AIR = context_from_dict(
    {"dimension": "Environmental", "media": "Air", "strata": "Unknown"}
)

def _role(iri: str, label: str, **extra: Any) -> dict[str, Any]:
    return Role(iri=iri, label=label, **extra).to_dict()


class FlattenTestCase(unittest.TestCase):
    """`export_roles`, the simplification."""

    def test_it_keeps_the_iri_and_the_label(self):
        """Both, on the precedent `unit`/`unit_iri` sets. The IRI is what a
        consumer groups and reasons on; the label is what stops a reader having
        to resolve `CHEBI_24527` to learn the flow is a herbicide."""
        self.assertEqual(
            export_roles([_role(HERBICIDE, "herbicide")]),
            [{"@id": HERBICIDE, RDFS_LABEL_CURIE: "herbicide"}],
        )

    def test_it_drops_the_definition_and_the_provenance(self):
        """What "simple" means in this export: `altLabel` is a list of strings
        rather than of label records and `references` a list of IRIs rather than
        of reference objects, for the same reason. The flow-object artifact
        publishes the audit trail; this one publishes the content."""
        rich = _role(
            HERBICIDE, "herbicide", definition="A substance used to destroy plant pests.",
        )
        self.assertIn(SKOS_DEFINITION_IRI, rich)
        flattened = export_roles([rich])
        self.assertEqual(set(flattened[0]), {"@id", RDFS_LABEL_CURIE})

    def test_no_roles_gives_none_and_not_an_empty_list(self):
        """An empty list reads as "checked, and it bears no role", which is a
        stronger claim than "ChEBI has nothing to say". `_OMIT_IF_NONE` then
        keeps the key out of the document entirely."""
        for value in (None, [], "not a list", 7):
            with self.subTest(value=value):
                self.assertIsNone(export_roles(value))

    def test_a_row_with_no_iri_is_dropped(self):
        """The `@id` is the whole point of the row; a label alone names nothing
        a consumer can resolve or group on."""
        self.assertIsNone(export_roles([{RDFS_LABEL_CURIE: "herbicide"}]))
        self.assertIsNone(export_roles([{"@id": "   "}]))

    def test_a_row_with_no_label_still_publishes_the_iri(self):
        """The reverse: the IRI carries the meaning, so a missing label degrades
        readability rather than losing the assertion."""
        self.assertEqual(export_roles([{"@id": HERBICIDE}]), [{"@id": HERBICIDE}])

    def test_order_is_preserved(self):
        """`flow_layers.roles` writes them sorted by label, and #264 is what an
        unstable order costs: a diff that reports every row as changed."""
        rows = export_roles([_role(PESTICIDE, "pesticide"), _role(HERBICIDE, "herbicide")])
        self.assertEqual([r[RDFS_LABEL_CURIE] for r in rows], ["pesticide", "herbicide"])


class SimpleFlowTestCase(unittest.TestCase):

    def _flow(self, roles) -> SimpleFlow:
        return SimpleFlow(
            identifier="x", source="EF 3.1", cas_numbers=[], ec_numbers=[],
            context_iri="", unit="kg", unit_iri="", prefLabel="x", altLabel=[],
            properties={}, references=[], definition=[], roles=roles,
        )

    def test_roles_serialise_under_the_ro_iri(self):
        payload = self._flow([{"@id": HERBICIDE, RDFS_LABEL_CURIE: "herbicide"}]).to_dict()
        self.assertEqual(payload[RO_HAS_ROLE_IRI][0]["@id"], HERBICIDE)

    def test_the_key_is_absent_when_there_are_no_roles(self):
        self.assertNotIn(RO_HAS_ROLE_IRI, self._flow(None).to_dict())

    def test_it_round_trips(self):
        rows = [{"@id": HERBICIDE, RDFS_LABEL_CURIE: "herbicide"}]
        payload = self._flow(rows).to_dict()
        self.assertEqual(SimpleFlow.from_dict(payload).roles, rows)


class ContextTestCase(unittest.TestCase):

    def test_the_export_key_is_declared_as_a_set_of_nodes(self):
        """Not `@type: @id`. That coerces a plain string into a reference, and
        these rows are already objects carrying their own `@id`; declaring it
        would make the row itself the node reference instead of its `@id`."""
        declaration = JSONLD_CONTEXT[RO_HAS_ROLE_IRI]
        self.assertEqual(declaration, {"@container": "@set"})

    def test_the_label_key_expands(self):
        """A key that does not expand contributes no triples."""
        self.assertEqual(RDFS_LABEL_CURIE, "rdfs:label")
        self.assertEqual(JSONLD_CONTEXT["rdfs"], "http://www.w3.org/2000/01/rdf-schema#")


class EndToEndTestCase(unittest.TestCase):
    """Flow object -> published simple flow, through the real builder."""

    def test_a_flows_roles_reach_the_document(self):
        flow = Flow(
            uuid="u-1", name="Beflubutamid", unit="kg", source="ecoinvent-3.12",
            context=context_for_iri(AGRICULTURAL_SOIL),
        )
        flow.identifier = "u-1"
        flow.unit_iri = "https://vocab.brightway.one/units/unit/KiloGM"
        flow.context_iri = "envi-grou-agri"
        flow.roles = [
            _role(HERBICIDE, "herbicide",
                  definition="A substance used to destroy plant pests."),
            _role(PESTICIDE, "pesticide"),
        ]
        document = strip_lcia_from_flows([flow.to_dict()]).to_dict()
        published = document["flows"][0]
        self.assertEqual(
            published[RO_HAS_ROLE_IRI],
            [
                {"@id": HERBICIDE, RDFS_LABEL_CURIE: "herbicide"},
                {"@id": PESTICIDE, RDFS_LABEL_CURIE: "pesticide"},
            ],
        )
        self.assertNotIn(SKOS_DEFINITION_IRI, published[RO_HAS_ROLE_IRI][0])

    def test_a_flow_without_roles_publishes_no_key(self):
        flow = Flow(
            uuid="u-2", name="Arsenic", unit="kg", source="EF 3.1",
            context=context_from_dict(
                {"dimension": "Environmental", "media": "Air", "strata": "Unknown"}
        ),
        )
        flow.identifier = "u-2"
        flow.unit_iri = "https://vocab.brightway.one/units/unit/KiloGM"
        document = strip_lcia_from_flows([flow.to_dict()]).to_dict()
        self.assertNotIn(RO_HAS_ROLE_IRI, document["flows"][0])


class PropagationTestCase(unittest.TestCase):
    """Roles are a property of the *substance*, copied onto the flow."""

    def test_a_flow_copies_its_objects_roles(self):
        """The same path `types`, `origin_qualifier` and `parent_flow_object_id`
        take: derived once on the flow object, copied so the export reads one
        record instead of joining two."""
        from brightway_flows.pipeline.engine import _link_flows_to_their_substance
        from brightway_flows.domain.elementary_flow import ElementaryFlow

        rows = [_role(HERBICIDE, "herbicide")]
        obj = FlowObject(
            flow_object_id="fo-1", prefLabel=[], altLabel=[], properties={},
            references=[], created_from={}, roles=rows,
        )
        flow = Flow(uuid="u-1", name="x", unit="kg", source="s", context=_AIR)
        layer = ElementaryFlow(
            elementary_flow_id="u-1", flow_object_id="fo-1", source="s",
            unit="kg", context=_AIR, context_iri="", unit_iri=None,
            lcia_methods=[], general_comment=None,
        )
        _link_flows_to_their_substance([flow], [obj], {"u-1": layer})
        self.assertEqual(flow.roles, rows)

    def test_the_copy_is_not_shared_with_the_flow_object(self):
        """Mutating a published flow must not reach back into the substance that
        several other flows also read.

        Both levels, because the first version of this test only checked the
        top-level key while the code only made a shallow copy: a role row nests
        a `provenance` dict, so `[dict(row) for row in ...]` left every flow of
        an object sharing one, and the test's name promised more than the code
        gave. Review of #270 found the gap.
        """
        from brightway_flows.pipeline.engine import _link_flows_to_their_substance
        from brightway_flows.domain.elementary_flow import ElementaryFlow

        obj = FlowObject(
            flow_object_id="fo-1", prefLabel=[], altLabel=[], properties={},
            references=[], created_from={},
            roles=[_role(
                HERBICIDE, "herbicide",
                provenance=Provenance(
                    was_generated_by="chebi_roles",
                    was_attributed_to="brightway-flows",
                ),
            )],
        )
        flow = Flow(uuid="u-1", name="x", unit="kg", source="s", context=_AIR)
        layer = ElementaryFlow(
            elementary_flow_id="u-1", flow_object_id="fo-1", source="s",
            unit="kg", context=_AIR, context_iri="", unit_iri=None,
            lcia_methods=[], general_comment=None,
        )
        _link_flows_to_their_substance([flow], [obj], {"u-1": layer})

        flow.roles[0]["@id"] = "tampered"
        self.assertEqual(obj.roles[0]["@id"], HERBICIDE)

        flow.roles[0]["provenance"]["prov:wasGeneratedBy"] = "tampered"
        self.assertEqual(
            obj.roles[0]["provenance"]["prov:wasGeneratedBy"], "chebi_roles"
        )


class HoistingTestCase(unittest.TestCase):
    """The role key joins `_OBJECT_DERIVED_KEYS`, so it is stored once per
    substance rather than once per flow.  That mechanism has a second branch
    this PR is the first user of for this key."""

    def test_roles_hoist_when_every_flow_of_an_object_agrees(self):
        from brightway_flows.pipeline.sqlite import (
            _EF_FLOW_JSON, _hoist_shared_object_payloads,
        )
        import orjson

        rows = [_role(HERBICIDE, "herbicide")]
        ef = [
            self._row("u-1", "fo-1", {RO_HAS_ROLE_IRI: rows}),
            self._row("u-2", "fo-1", {RO_HAS_ROLE_IRI: rows}),
        ]
        rewritten, payloads = _hoist_shared_object_payloads(ef)
        self.assertEqual(len(payloads), 1)
        self.assertEqual(orjson.loads(payloads[0][1])[RO_HAS_ROLE_IRI], rows)
        for row in rewritten:
            self.assertNotIn(RO_HAS_ROLE_IRI, orjson.loads(row[_EF_FLOW_JSON]))

    def test_a_flow_that_disagrees_keeps_its_own_roles(self):
        """The rule the hoisting rests on: a key is the object's only when every
        flow carries it *and* they agree.  Two flows of one substance should
        never disagree about its roles -- `assign_chebi_roles` writes the object
        -- but if they ever do, the losing value must not be silently replaced
        by the other, and `merge_object_payload` lets the flow's own copy win.
        """
        from brightway_flows.pipeline.sqlite import (
            _EF_FLOW_JSON, _hoist_shared_object_payloads,
        )
        import orjson

        ef = [
            self._row("u-1", "fo-1", {RO_HAS_ROLE_IRI: [_role(HERBICIDE, "herbicide")]}),
            self._row("u-2", "fo-1", {RO_HAS_ROLE_IRI: [_role(PESTICIDE, "pesticide")]}),
        ]
        rewritten, payloads = _hoist_shared_object_payloads(ef)
        self.assertEqual(payloads, [])
        for row in rewritten:
            self.assertIn(RO_HAS_ROLE_IRI, orjson.loads(row[_EF_FLOW_JSON]))

    def test_a_flow_missing_roles_stops_the_hoist(self):
        """Which is exactly the defect this PR fixes at its source: while the
        merge's additions did not inherit roles, one flow of the object had them
        and its siblings did not, so the key was never shared and the siblings
        published nothing."""
        from brightway_flows.pipeline.sqlite import _hoist_shared_object_payloads

        ef = [
            self._row("u-1", "fo-1", {RO_HAS_ROLE_IRI: [_role(HERBICIDE, "herbicide")]}),
            self._row("u-2", "fo-1", {}),
        ]
        _rewritten, payloads = _hoist_shared_object_payloads(ef)
        self.assertEqual(payloads, [])

    @staticmethod
    def _row(uuid: str, object_id: str, flow: dict[str, Any]) -> tuple:
        """One `elementary_flows` insert tuple, shaped as the writer builds it."""
        from brightway_flows.pipeline.sqlite import _EF_FLOW_JSON, _EF_FLOW_OBJECT_ID

        width = max(_EF_FLOW_JSON, _EF_FLOW_OBJECT_ID) + 1
        row: list[Any] = [None] * width
        row[_EF_FLOW_OBJECT_ID] = object_id
        row[_EF_FLOW_JSON] = {"uuid": uuid, **flow}
        return tuple(row)


if __name__ == "__main__":
    unittest.main()
