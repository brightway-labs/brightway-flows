"""The published export is JSON-LD, and these tests are what make that true.

Before this, `harmonised-flows-simple.json.gz` was JSON with IRI-shaped keys:
`JSONLD_CONTEXT` was built, tested, and never written to any artifact, so a
consumer expanding the document got an empty graph.  Every key vanished, silently.

The guard against that returning is to run the real JSON-LD algorithm over a
real export and assert the triples that come out.  A hand-rolled approximation
would not have caught the failure it is here to prevent -- the document looked
correct, and only expansion showed it was not.

Three groups:

- **Expansion**  -- a built export expands, and known flows yield known triples.
- **Datatypes**  -- a slot ChemROF declares as a number publishes as a number,
  and a value that will not parse is kept rather than dropped.
- **Charge**     -- a whole-entity charge is `elemental_charge`, never
  `formal_charge`, which ChemROF scopes to `AtomOccurrence`.
"""

import gzip
import re
import sqlite3
import tempfile
import unittest
from dataclasses import fields
from pathlib import Path
from typing import Any

import orjson
from pyld import jsonld

from brightway_flows.domain.property_values import (
    coerce_property_datatypes,
    migrate_entity_charge,
    normalise_semantic_properties,
)
from brightway_flows.domain.schema import SCHEMA_VERSION
from brightway_flows.domain.vocabulary import (
    CHEMROF_ELEMENTAL_CHARGE,
    DCTERMS_IS_REPLACED_BY,
    OWL_DEPRECATED,
    deprecation_reason_iri,
    CHEMROF_FORMAL_CHARGE,
    CHEMROF_MOLECULAR_FORMULA,
    CHEMROF_MOLECULAR_MASS,
    CHEMROF_MONOISOTOPIC_MASS,
    CHEMROF_SMILES_STRING,
    CONSENSUS_ELEMENTARY_FLOW_IRI_PREFIX,
    JSONLD_CONTEXT,
    SKOS_CONCEPT_IRI,
    SKOS_PREF_LABEL_IRI,
    Term,
    iri,
)
from brightway_flows.domain.simple_flow import SimpleFlow
from brightway_flows.pipeline.correspondences import CONSENSUS_SCHEME_IRI
from brightway_flows.pipeline.exporting import write_simple_export

DCTERMS_IDENTIFIER = iri(Term.IDENTIFIER)
QUDT_HAS_UNIT = iri(Term.HAS_UNIT)
RDFS_SEE_ALSO = iri(Term.SEE_ALSO)
CHEMINF_CAS = iri(Term.CAS_REGISTRY_NUMBER)


def _semantic(iri_value: str, values: list[Any], unit: str | None = None) -> dict[str, Any]:
    """One `properties` entry in the shape the transformers write."""
    entry: dict[str, Any] = {"rdfs:label": "x", "@value": values}
    if unit:
        entry[QUDT_HAS_UNIT] = unit
    entry["provenance"] = {
        "prov:wasGeneratedBy": "enrich_references.pubchem_semantic",
        "prov:wasAttributedTo": "brightway-flows",
        "prov:hadPrimarySource": ["CID:280"],
        "prov:wasDerivedFrom": "pubchem.props.Charge",
    }
    return entry


#: Carbon dioxide, as the pipeline writes it: masses and charge as strings, the
#: charge on `formal_charge`.  This is the "before" state the export has to fix.
CARBON_DIOXIDE = {
    "uuid": "d1e1b8f1-0000-4000-8000-000000000001",
    "identifier": "d1e1b8f1-0000-4000-8000-000000000001",
    "source": "EF 3.1",
    "cas_numbers": ["124-38-9"],
    "ec_numbers": ["204-696-9"],
    "context_iri": "https://vocab.brightway.one/flow-contexts/envi-air",
    "unit": "kg",
    "unit_iri": "https://vocab.brightway.one/units/unit/KiloGM",
    "prefLabel": [{"@value": "Carbon dioxide", "@language": "en"}],
    "altLabel": [{"@value": "carbonic anhydride", "@language": "en"}],
    "properties": {
        CHEMROF_MOLECULAR_FORMULA: _semantic(CHEMROF_MOLECULAR_FORMULA, ["CO2"]),
        CHEMROF_MOLECULAR_MASS: _semantic(
            CHEMROF_MOLECULAR_MASS, ["44.009"], "gm-per-mol"
        ),
        CHEMROF_MONOISOTOPIC_MASS: _semantic(
            CHEMROF_MONOISOTOPIC_MASS, ["43.98983"], "gm-per-mol"
        ),
        CHEMROF_FORMAL_CHARGE: _semantic(CHEMROF_FORMAL_CHARGE, ["0"], "num"),
        CHEMROF_SMILES_STRING: _semantic(CHEMROF_SMILES_STRING, ["O=C=O"]),
    },
    "references": [{"@id": "https://pubchem.ncbi.nlm.nih.gov/compound/280"}],
    "concept_associations": [
        {
            "@type": "xkos:ConceptAssociation",
            "xkos:sourceConcept": {
                "@id": "https://vocab.brightway.one/ef/3.1/flow/ef-co2",
                "skos:prefLabel": "carbon dioxide",
                # What the builder writes: the match quality is a statement
                # about this concept, not about the association.
                "skos:exactMatch": {
                    "@id": (
                        "https://vocab.brightway.dev/elementary-flows/"
                        "d1e1b8f1-0000-4000-8000-000000000001"
                    )
                },
            },
            "xkos:targetConcept": {
                "@id": (
                    "https://vocab.brightway.dev/elementary-flows/"
                    "d1e1b8f1-0000-4000-8000-000000000001"
                )
            },
        }
    ],
}

#: Nickel(2+): a charged entity, so its charge must survive the move intact.
NICKEL_ION = {
    "uuid": "d1e1b8f1-0000-4000-8000-000000000002",
    "identifier": "d1e1b8f1-0000-4000-8000-000000000002",
    "source": "EF 3.1",
    "cas_numbers": ["14701-22-5"],
    "ec_numbers": [],
    "context_iri": "https://vocab.brightway.one/flow-contexts/envi-water",
    "unit": "kg",
    "unit_iri": "https://vocab.brightway.one/units/unit/KiloGM",
    "prefLabel": [{"@value": "Nickel(2+)", "@language": "en"}],
    "origin_qualifier": "fossil",
    "parent_flow_object_id": "fo-a379de24c34d0838",
    "altLabel": [],
    "properties": {
        CHEMROF_MOLECULAR_FORMULA: _semantic(CHEMROF_MOLECULAR_FORMULA, ["Ni"]),
        CHEMROF_FORMAL_CHARGE: _semantic(CHEMROF_FORMAL_CHARGE, ["2"], "num"),
    },
    "references": [],
    "concept_associations": [],
}

#: A mass the sources give as a range.  It must not be coerced, and must not be
#: dropped: publishing it untyped is honest, publishing nothing is not.
DIRTY_MASS = {
    "uuid": "d1e1b8f1-0000-4000-8000-000000000003",
    "identifier": "d1e1b8f1-0000-4000-8000-000000000003",
    "source": "EF 3.1",
    "cas_numbers": [],
    "ec_numbers": [],
    "context_iri": "https://vocab.brightway.one/flow-contexts/envi-air",
    "unit": "kg",
    "unit_iri": "https://vocab.brightway.one/units/unit/KiloGM",
    "prefLabel": [{"@value": "Alcohols, C12-15, ethoxylated", "@language": "en"}],
    "altLabel": [],
    "properties": {
        CHEMROF_MOLECULAR_MASS: _semantic(
            CHEMROF_MOLECULAR_MASS, ["approx. 400", "402.5"], "gm-per-mol"
        ),
    },
    "references": [],
    "concept_associations": [],
}


def build_db(path: Path, payloads: list[dict[str, Any]]) -> None:
    connection = sqlite3.connect(path)
    connection.execute(
        "CREATE TABLE elementary_flows (uuid TEXT PRIMARY KEY, flow_object_id TEXT, "
        "flow_json TEXT)"
    )
    for index, payload in enumerate(payloads):
        connection.execute(
            "INSERT INTO elementary_flows VALUES (?, ?, ?)",
            (f"row-{index}", "fo", orjson.dumps(payload).decode()),
        )
    connection.commit()
    connection.close()


class ExportFixtureTestCase(unittest.TestCase):
    """Base: build a database, export it, keep both the JSON and the triples."""

    payloads: list[dict[str, Any]] = [CARBON_DIOXIDE, NICKEL_ION, DIRTY_MASS]

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        root = Path(self._tmp.name)
        self.db = root / "consensus-flows.sqlite3"
        self.output = root / "harmonised-flows-simple.json.gz"
        build_db(self.db, self.payloads)
        write_simple_export(self.db, self.output)
        self.document = orjson.loads(gzip.decompress(self.output.read_bytes()))
        # `flatten`, not `expand`.  With the document's node arrays declared as
        # `@included`, `expand` returns the one wrapping node and leaves the
        # real nodes inside it; `flatten` returns them, which is what these
        # tests assert over.  `to_rdf` is used where the question is which
        # graph a triple landed in -- `expand` cannot answer that at all.
        self.expanded = jsonld.flatten(self.document)
        self.by_id = {node["@id"]: node for node in self.expanded if "@id" in node}
        self.quads = jsonld.to_rdf(
            self.document, {"format": "application/n-quads"}
        ).strip().splitlines()

    def node(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self.by_id[
            f"{CONSENSUS_ELEMENTARY_FLOW_IRI_PREFIX}{payload['identifier']}"
        ]

    def association_for(self, payload: dict[str, Any]) -> dict[str, Any]:
        """The one association whose target is *payload*'s flow."""
        target = f"{CONSENSUS_ELEMENTARY_FLOW_IRI_PREFIX}{payload['identifier']}"
        matches = [
            node for node in self.expanded
            if any(
                entry.get("@id") == target
                for entry in node.get(iri(Term.TARGET_CONCEPT), [])
            )
        ]
        self.assertEqual(len(matches), 1, f"expected one association for {target}")
        return matches[0]

    def values(self, node: dict[str, Any], predicate: str) -> list[Any]:
        return [entry.get("@value", entry.get("@id")) for entry in node.get(predicate, [])]


class DocumentShapeTestCase(ExportFixtureTestCase):
    def test_the_export_carries_a_context(self):
        """Without this the whole document expands to nothing."""
        self.assertIn("@context", self.document)
        self.assertEqual(self.document["@context"], JSONLD_CONTEXT)

    def test_the_export_declares_the_current_schema_version(self):
        self.assertEqual(self.document["schema_version"], SCHEMA_VERSION)

    def test_every_flow_is_a_named_node(self):
        """A flow without an `@id` is a blank node: nothing can cite it."""
        for payload in self.payloads:
            with self.subTest(flow=payload["identifier"]):
                self.assertIn(
                    f"{CONSENSUS_ELEMENTARY_FLOW_IRI_PREFIX}{payload['identifier']}",
                    self.by_id,
                )

    def test_nothing_in_the_document_is_a_blank_node(self):
        """Schemes, correspondences and associations are all citable too."""
        blank = [node["@id"] for node in self.expanded
                 if str(node.get("@id", "")).startswith("_:")]
        self.assertEqual(blank, [])

    def test_every_triple_is_in_the_default_graph(self):
        """The hazard `@graph` introduced once there was a second top-level key.

        A node object carrying nothing but `@graph` is a plain graph container,
        so while `flows` was the only thing producing triples they landed in the
        default graph.  Add `correspondences` beside it and the document object
        becomes a named node, its `@graph` becomes a *named* graph, and the
        flows move into a blank-node-named one -- leaving a consumer querying
        the default graph with the correspondences and none of the flows.
        `@included` is what keeps them together, and only `to_rdf` shows it.
        """
        named = [q for q in self.quads if re.search(r"\s_:\w+\s*\.$", q)]
        self.assertEqual(named, [], "some triples landed in a blank-node graph")

    def test_a_flow_is_a_concept_in_the_consensus_scheme(self):
        node = self.node(CARBON_DIOXIDE)
        self.assertIn(SKOS_CONCEPT_IRI, node["@type"])
        self.assertEqual(
            [entry["@id"] for entry in node[iri(Term.IN_SCHEME)]],
            [CONSENSUS_SCHEME_IRI],
        )

    def test_the_minted_id_is_the_one_the_associations_point_at(self):
        """The flow's `@id` and its mapping's `xkos:targetConcept` are one thing."""
        association = self.association_for(CARBON_DIOXIDE)
        self.assertEqual(
            [entry["@id"] for entry in association[iri(Term.TARGET_CONCEPT)]],
            [self.node(CARBON_DIOXIDE)["@id"]],
        )

    def test_expansion_loses_nothing_that_was_declared(self):
        """Every declared key survives the round trip to triples."""
        node = self.node(CARBON_DIOXIDE)
        for predicate in (
            SKOS_PREF_LABEL_IRI, iri(Term.ALT_LABEL), DCTERMS_IDENTIFIER,
            iri(Term.SOURCE), CHEMINF_CAS, iri(Term.EC_NUMBER), QUDT_HAS_UNIT,
            RDFS_SEE_ALSO, CHEMROF_MOLECULAR_FORMULA,
        ):
            with self.subTest(predicate=predicate):
                self.assertIn(predicate, node)


class CorrespondenceTestCase(ExportFixtureTestCase):
    """The mappings are a graph now, not a blank node inside a flow.

    #9 left `concept_associations` undeclared rather than assert `xkos:madeOf`
    on a flow, whose domain is `xkos:Correspondence`. The fix was never a
    different predicate -- it was the resource we had nothing to put on the
    left of. These pin the shape py-semantic-taxonomy models.
    """

    def test_the_correspondence_exists_and_compares_two_schemes(self):
        correspondence = self.by_id[
            "https://vocab.brightway.dev/correspondences/ef-3.1"
        ]
        self.assertIn(iri(Term.CORRESPONDENCE), correspondence["@type"])
        self.assertEqual(
            sorted(entry["@id"] for entry in correspondence[iri(Term.COMPARES)]),
            sorted([CONSENSUS_SCHEME_IRI, "https://vocab.brightway.one/ef/3.1"]),
        )

    def test_made_of_now_has_a_correspondence_on_its_left(self):
        correspondence = self.by_id[
            "https://vocab.brightway.dev/correspondences/ef-3.1"
        ]
        self.assertEqual(len(correspondence[iri(Term.MADE_OF)]), 1)

    def test_no_flow_asserts_made_of(self):
        """A flow is not a correspondence.  That was #9's whole point."""
        for payload in self.payloads:
            node = self.by_id.get(
                f"{CONSENSUS_ELEMENTARY_FLOW_IRI_PREFIX}{payload['identifier']}"
            )
            with self.subTest(flow=payload["identifier"]):
                self.assertNotIn(iri(Term.MADE_OF), node or {})

    def test_the_association_is_a_node_with_its_own_iri(self):
        association = self.association_for(CARBON_DIOXIDE)
        self.assertIn(iri(Term.CONCEPT_ASSOCIATION), association["@type"])
        self.assertTrue(
            association["@id"].startswith(
                "https://vocab.brightway.dev/concept-associations/ef-3.1/"
            ),
            association["@id"],
        )

    def test_the_association_iri_is_derived_from_the_two_flows(self):
        """Stable across runs, so a rebuild does not rename the whole graph."""
        self.assertEqual(
            self.association_for(CARBON_DIOXIDE)["@id"],
            "https://vocab.brightway.dev/concept-associations/ef-3.1/"
            f"ef-co2/{CARBON_DIOXIDE['identifier']}",
        )

    def test_the_match_is_a_statement_about_the_source_concept(self):
        """XKOS defines no property for mapping quality, so it goes on the
        concepts -- not on the association.  py-semantic-taxonomy says so
        explicitly, and this is what that looks like in triples."""
        source = self.by_id["https://vocab.brightway.one/ef/3.1/flow/ef-co2"]
        self.assertEqual(
            [entry["@id"] for entry in source[iri(Term.EXACT_MATCH)]],
            [self.node(CARBON_DIOXIDE)["@id"]],
        )
        association = self.association_for(CARBON_DIOXIDE)
        self.assertNotIn(iri(Term.EXACT_MATCH), association)

    def test_both_schemes_are_published_as_concept_schemes(self):
        for scheme_iri in (CONSENSUS_SCHEME_IRI, "https://vocab.brightway.one/ef/3.1"):
            with self.subTest(scheme=scheme_iri):
                self.assertIn(
                    iri(Term.CONCEPT_SCHEME), self.by_id[scheme_iri]["@type"]
                )

    def test_a_flow_no_longer_carries_its_mappings(self):
        """They moved.  Find them by `xkos:targetConcept` instead."""
        flow = next(
            f for f in self.document["flows"]
            if f["identifier"] == CARBON_DIOXIDE["identifier"]
        )
        self.assertNotIn("concept_associations", flow)


class MintedPredicateTestCase(ExportFixtureTestCase):
    """The three relations no published vocabulary provides.

    `context_iri` was the sharpest cost of not minting: the compartment is the
    field an LCA practitioner filters on first, and it was the one thing in the
    export contributing no triples.  `origin_qualifier` is the second -- the
    difference between fossil and biogenic CO2 decides an entire impact
    category, and the only published trace of it was the preferred label.
    `parent_flow_object_id` is its other half: the qualifier names a
    distinction, and this names the substance the distinction is against.
    """

    def test_the_compartment_is_a_triple_now(self):
        self.assertEqual(
            self.values(self.node(CARBON_DIOXIDE), iri(Term.FLOW_CONTEXT)),
            ["https://vocab.brightway.one/flow-contexts/envi-air"],
        )

    def test_the_compartment_is_a_reference_not_a_string(self):
        """`@type: @id` -- the context is a resource, and it already has an IRI."""
        entry = self.node(CARBON_DIOXIDE)[iri(Term.FLOW_CONTEXT)][0]
        self.assertIn("@id", entry)
        self.assertNotIn("@value", entry)

    def test_the_origin_qualifier_is_a_concept_not_a_bare_string(self):
        self.assertEqual(
            self.values(self.node(NICKEL_ION), iri(Term.ORIGIN_QUALIFIER)),
            ["https://vocab.brightway.one/origin-qualifiers/fossil"],
        )

    def test_an_unqualified_substance_says_nothing(self):
        """Most flows have no qualifier, and absent is not the same as empty."""
        self.assertNotIn(iri(Term.ORIGIN_QUALIFIER), self.node(CARBON_DIOXIDE))
        flow = next(
            f for f in self.document["flows"]
            if f["identifier"] == CARBON_DIOXIDE["identifier"]
        )
        self.assertNotIn(iri(Term.ORIGIN_QUALIFIER), flow)

    def test_the_base_substance_is_a_node_reference(self):
        """The identifier `chemrof:has_element` already points over.

        Not a node in this document -- the flow-object layer is unpublished --
        but a link waiting for its object, not a literal that can never
        become one.
        """
        self.assertEqual(
            self.values(self.node(NICKEL_ION), iri(Term.BASE_SUBSTANCE)),
            ["https://vocab.brightway.dev/flow-objects/fo-a379de24c34d0838"],
        )
        entry = self.node(NICKEL_ION)[iri(Term.BASE_SUBSTANCE)][0]
        self.assertIn("@id", entry)
        self.assertNotIn("@value", entry)

    def test_a_substance_split_from_nothing_says_nothing(self):
        """Absent wherever the qualifier is, and on the one qualified object
        with no CAS number to resolve a parent through."""
        self.assertNotIn(iri(Term.BASE_SUBSTANCE), self.node(CARBON_DIOXIDE))
        flow = next(
            f for f in self.document["flows"]
            if f["identifier"] == CARBON_DIOXIDE["identifier"]
        )
        self.assertNotIn(iri(Term.BASE_SUBSTANCE), flow)

    def test_all_three_predicates_are_under_the_project_namespace(self):
        """Minted, and visibly ours -- not passed off as someone else's term."""
        for term in (
            Term.FLOW_CONTEXT, Term.ORIGIN_QUALIFIER, Term.BASE_SUBSTANCE,
        ):
            with self.subTest(term=term.name):
                self.assertTrue(
                    iri(term).startswith("https://vocab.brightway.one/terms/"),
                    iri(term),
                )


class NestedPropertiesTestCase(ExportFixtureTestCase):
    """`properties` is a nesting of the file format, not a node in the graph."""

    def test_semantic_properties_attach_to_the_flow_itself(self):
        node = self.node(CARBON_DIOXIDE)
        self.assertEqual(self.values(node, CHEMROF_MOLECULAR_FORMULA), ["CO2"])
        self.assertEqual(self.values(node, CHEMROF_SMILES_STRING), ["O=C=O"])

    def test_no_intermediate_properties_node_is_created(self):
        """`@nest` must not leave a `properties` predicate behind."""
        node = self.node(CARBON_DIOXIDE)
        self.assertNotIn("properties", node)
        for predicate in node:
            self.assertFalse(predicate.endswith("/properties"), predicate)


class DatatypeTestCase(ExportFixtureTestCase):
    """A slot ChemROF declares as a number must publish as a number."""

    def test_mass_is_a_number_not_a_string(self):
        node = self.node(CARBON_DIOXIDE)
        self.assertEqual(self.values(node, CHEMROF_MOLECULAR_MASS), [44.009])
        self.assertEqual(self.values(node, CHEMROF_MONOISOTOPIC_MASS), [43.98983])

    def test_charge_is_an_integer_not_a_string(self):
        self.assertEqual(
            self.values(self.node(NICKEL_ION), CHEMROF_ELEMENTAL_CHARGE), [2]
        )
        self.assertEqual(
            self.values(self.node(CARBON_DIOXIDE), CHEMROF_ELEMENTAL_CHARGE), [0]
        )

    def test_the_raw_json_holds_numbers_too(self):
        """Not only the expansion: a consumer reading the JSON directly benefits."""
        flow = next(
            f for f in self.document["flows"]
            if f["identifier"] == CARBON_DIOXIDE["identifier"]
        )
        self.assertIsInstance(flow["properties"][CHEMROF_MOLECULAR_MASS], float)
        self.assertIsInstance(flow["properties"][CHEMROF_ELEMENTAL_CHARGE], int)

    def test_an_unparseable_value_is_kept_beside_the_parseable_one(self):
        """Dirty data must survive typing.  Dropping it would lose the record."""
        node = self.node(DIRTY_MASS)
        self.assertEqual(
            sorted(self.values(node, CHEMROF_MOLECULAR_MASS), key=str),
            [402.5, "approx. 400"],
        )


class ChargePredicateTestCase(ExportFixtureTestCase):
    """`formal_charge` is one atom's charge inside a molecule, per ChemROF."""

    def test_formal_charge_is_not_published(self):
        for payload in (CARBON_DIOXIDE, NICKEL_ION):
            with self.subTest(flow=payload["identifier"]):
                self.assertNotIn(CHEMROF_FORMAL_CHARGE, self.node(payload))

    def test_the_charge_moved_rather_than_being_dropped(self):
        self.assertEqual(
            self.values(self.node(NICKEL_ION), CHEMROF_ELEMENTAL_CHARGE), [2]
        )

    def test_the_moved_value_keeps_its_lineage(self):
        """A moved value with no provenance would be a value from nowhere."""
        properties, moved = migrate_entity_charge(
            {CHEMROF_FORMAL_CHARGE: _semantic(CHEMROF_FORMAL_CHARGE, ["2"])}
        )
        self.assertTrue(moved)
        provenance = properties[CHEMROF_ELEMENTAL_CHARGE]["provenance"]
        self.assertEqual(provenance["prov:hadPrimarySource"], ["CID:280"])
        self.assertEqual(provenance["prov:wasDerivedFrom"], "pubchem.props.Charge")
        self.assertIn("prov:wasGeneratedBy", provenance)


class NormalisationUnitTestCase(unittest.TestCase):
    """The two corrections, away from the export."""

    def test_normalisation_is_idempotent(self):
        """The export normalises again after the engine already has."""
        once, _ = normalise_semantic_properties(CARBON_DIOXIDE["properties"])
        twice, counts = normalise_semantic_properties(once)
        self.assertEqual(once, twice)
        self.assertEqual(counts["coerced"], 0)
        self.assertEqual(counts["charge_migrated"], 0)

    def test_an_existing_elemental_charge_wins(self):
        """`flow_layers` writes it from the periodic table; that is the better source."""
        better = _semantic(CHEMROF_ELEMENTAL_CHARGE, [2])
        properties, moved = migrate_entity_charge({
            CHEMROF_FORMAL_CHARGE: _semantic(CHEMROF_FORMAL_CHARGE, ["-9"]),
            CHEMROF_ELEMENTAL_CHARGE: better,
        })
        self.assertTrue(moved)
        self.assertEqual(properties[CHEMROF_ELEMENTAL_CHARGE], better)
        self.assertNotIn(CHEMROF_FORMAL_CHARGE, properties)

    def test_a_boolean_is_never_published_as_a_number(self):
        """`bool` is an `int` subclass in Python and is not an XSD integer."""
        properties, _ = coerce_property_datatypes(
            {CHEMROF_ELEMENTAL_CHARGE: {"@value": [True]}}
        )
        self.assertIs(properties[CHEMROF_ELEMENTAL_CHARGE]["@value"][0], True)

    def test_a_fractional_charge_is_kept_as_written(self):
        """Rounding a charge to make it fit the declared type would be a lie."""
        properties, counts = coerce_property_datatypes(
            {CHEMROF_ELEMENTAL_CHARGE: {"@value": ["2.5"]}}
        )
        self.assertEqual(properties[CHEMROF_ELEMENTAL_CHARGE]["@value"], ["2.5"])
        self.assertEqual(counts["unparseable"], 1)

    def test_an_integral_float_string_becomes_an_integer(self):
        properties, _ = coerce_property_datatypes(
            {CHEMROF_ELEMENTAL_CHARGE: {"@value": ["2.0"]}}
        )
        self.assertEqual(properties[CHEMROF_ELEMENTAL_CHARGE]["@value"], [2])

    def test_a_string_slot_is_left_alone(self):
        entry = {"@value": ["124-38-9"]}
        properties, counts = coerce_property_datatypes({CHEMROF_MOLECULAR_FORMULA: entry})
        self.assertEqual(properties[CHEMROF_MOLECULAR_FORMULA], entry)
        self.assertEqual(counts, {})


class ContextCompletenessTestCase(unittest.TestCase):
    """A key the context does not declare is dropped, taking its value with it."""

    #: `unit` is the string beside `unit_iri`, which expands as
    #: `qudt:hasUnit`; the duplicate needs no predicate of its own.  Listed here
    #: so that adding a field without deciding its meaning fails loudly.
    KNOWN_UNDECLARED = frozenset({"unit"})

    def test_every_field_of_a_published_flow_is_accounted_for(self):
        """A new field is either declared, or knowingly not.  Never accidental."""
        for field in fields(SimpleFlow):
            key = SimpleFlow._ALIASES.get(field.name, field.name)
            # A key that is already an absolute IRI needs no declaration; only
            # short names have to be looked up.
            if (
                key.startswith("@")
                or key.startswith("http")
                or key in self.KNOWN_UNDECLARED
            ):
                continue
            with self.subTest(field=key):
                self.assertIn(
                    key, JSONLD_CONTEXT,
                    f"{key} is published but undeclared, so it expands to "
                    "nothing. Declare it, or add it to KNOWN_UNDECLARED.",
                )

    def test_every_registry_term_is_declared(self):
        for term in Term:
            with self.subTest(term=term.name):
                self.assertIn(term.value, JSONLD_CONTEXT)

    def test_the_document_keys_are_aliased_to_json_ld_keywords(self):
        for key in ("flows", "redirects", "concept_schemes", "correspondences"):
            with self.subTest(key=key):
                self.assertEqual(JSONLD_CONTEXT[key], "@included")
        self.assertEqual(JSONLD_CONTEXT["properties"], "@nest")

    def test_json_ld_one_one_is_declared(self):
        """`@nest` is a 1.1 feature and silently does nothing without this."""
        self.assertEqual(JSONLD_CONTEXT["@version"], 1.1)


#: The deprecated twin of `NICKEL_ION`, pointed at it.
DEPRECATED_NICKEL = {
    **NICKEL_ION,
    "uuid": "d1e1b8f1-0000-4000-8000-00000000000d",
    "identifier": "d1e1b8f1-0000-4000-8000-00000000000d",
    OWL_DEPRECATED: True,
    "is_replaced_by_uuid": NICKEL_ION["identifier"],
}


class RedirectExpansionTestCase(ExportFixtureTestCase):
    """A redirect has to be a node in the graph, not just a JSON entry.

    The other document keys are `@included` so their contents land in the
    default graph.  A fourth key added without that declaration would put every
    redirect in a graph named by a blank node, and a consumer querying the
    default graph -- where the flows are -- would find none of them.  Nothing
    else in the suite would notice: the JSON would be exactly right.
    """

    payloads = [CARBON_DIOXIDE, DEPRECATED_NICKEL, NICKEL_ION]

    DEPRECATED_IRI = (
        f"{CONSENSUS_ELEMENTARY_FLOW_IRI_PREFIX}"
        "d1e1b8f1-0000-4000-8000-00000000000d"
    )
    SURVIVOR_IRI = (
        f"{CONSENSUS_ELEMENTARY_FLOW_IRI_PREFIX}{NICKEL_ION['identifier']}"
    )

    def test_the_deprecated_flow_is_named_but_not_published(self):
        self.assertIn(self.DEPRECATED_IRI, self.by_id)
        self.assertNotIn(
            DEPRECATED_NICKEL["identifier"],
            [flow["identifier"] for flow in self.document["flows"]],
        )

    def test_it_asserts_deprecation_its_replacement_and_the_reason(self):
        node = self.by_id[self.DEPRECATED_IRI]
        self.assertEqual(self.values(node, OWL_DEPRECATED), [True])
        self.assertEqual(
            self.values(node, DCTERMS_IS_REPLACED_BY), [self.SURVIVOR_IRI]
        )
        # No `elementary_flow_sources` table in this fixture, so the two flows'
        # source contexts are unknown -- and the record says so rather than
        # guessing that they were the same flow.
        self.assertEqual(
            self.values(node, iri(Term.DEPRECATION_REASON)),
            [deprecation_reason_iri("unclassified")],
        )

    def test_it_claims_no_membership_of_the_published_scheme(self):
        """A deprecated flow is not in the list, and must not say it is.

        `skos:inScheme` here would contradict the flow's absence from `flows`,
        and `skos:Concept` would make it a member of a taxonomy it was removed
        from.
        """
        node = self.by_id[self.DEPRECATED_IRI]
        self.assertNotIn(iri(Term.IN_SCHEME), node)
        self.assertNotIn("@type", node)

    def test_the_redirect_asserts_nothing_beyond_those_four_things(self):
        """`replaced_by_identifier` is JSON convenience, declared as `null`.

        It is in the document because #39 asked for a UUID-to-UUID map, and it
        stays out of the graph because `dcterms:isReplacedBy` already carries
        that statement -- a predicate for it would be a second, weaker name for
        the same link.  Declared and dropped is a decision; this is what keeps
        it one.
        """
        node = self.by_id[self.DEPRECATED_IRI]
        self.assertEqual(
            set(node),
            {
                "@id",
                DCTERMS_IDENTIFIER,
                OWL_DEPRECATED,
                DCTERMS_IS_REPLACED_BY,
                iri(Term.DEPRECATION_REASON),
            },
        )

    def test_the_redirect_triples_are_in_the_default_graph(self):
        redirect_quads = [
            q for q in self.quads if q.startswith(f"<{self.DEPRECATED_IRI}>")
        ]
        self.assertEqual(len(redirect_quads), 4, redirect_quads)
        # Same tell as `test_every_triple_is_in_the_default_graph`: a quad in a
        # blank-node-named graph carries that name before its `.`.
        named = [q for q in redirect_quads if re.search(r"\s_:\w+\s*\.$", q)]
        self.assertEqual(named, [], "redirect triples landed in a named graph")


if __name__ == "__main__":
    unittest.main()
