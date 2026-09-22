"""The published artifacts have a schema, and it is enforced.

Three jobs, kept separate:

- **Drift guard** -- the checked-in schemas must equal what the record classes
  generate. Editing a dataclass without regenerating fails here, which is what
  makes the schemas a contract rather than stale documentation.
- **Conformance** -- a record produced by each dataclass validates against its
  own schema, so the generator and the serialiser cannot disagree.
- **Record shape** -- every record in a file must carry the same fields,
  whichever path produced it. The merge used to append elementary-flow-shaped
  dicts into a file of Flow records; this catches a regression of that.
"""

import gzip
import unittest
from pathlib import Path
from typing import Any

import orjson
from jsonschema import Draft202012Validator

from brightway_flows.domain.elementary_flow import ElementaryFlow
from brightway_flows.domain.lcia.records import LCIA_SCHEMA_VERSION
from brightway_flows.domain.lcia.unit_process_scores import ARTIFACT_SCHEMA_VERSION
from brightway_flows.domain.flow import Flow
from brightway_flows.domain.flow_object import FlowObject
from brightway_flows.domain.schema import (
    SCHEMA_VERSION,
    SchemaVersionError,
    build_all,
    check_schema_version,
    record_schema,
)
from brightway_flows.domain.simple_flow import SimpleFlow
from brightway_flows.domain.vocabulary import (
    MintedNamespace,
    SKOS_DEFINITION_IRI,
    XKOS_SOURCE_CONCEPT_CURIE,
    XKOS_TARGET_CONCEPT_CURIE,
)
from brightway_flows.filesystem import (
    ELEMENTARY_FLOWS_FILEPATH,
    FLOW_OBJECTS_FILEPATH,
    HARMONISED_FLOWS_SIMPLE_FILEPATH,
)
from brightway_flows.merge.report import UnmatchedReason, UnmatchedRow
from brightway_flows.pipeline.exporting import strip_lcia_from_flows
from brightway_flows.releases.randonneur_files import UNRESOLVED_REPORT_SCHEMA_VERSION
from brightway_flows.releases.snapshot import RELEASE_SNAPSHOT_SCHEMA_VERSION

SCHEMA_DIR = (
    Path(__file__).resolve().parent.parent
    / "src" / "brightway_flows" / "data" / "schemas"
)


def _refs(node: Any) -> list[str]:
    """Every ``$ref`` value anywhere in a schema."""
    if isinstance(node, dict):
        found = [node["$ref"]] if isinstance(node.get("$ref"), str) else []
        for value in node.values():
            found.extend(_refs(value))
        return found
    if isinstance(node, list):
        return [ref for item in node for ref in _refs(item)]
    return []


def _checked_in(artifact: str) -> dict[str, Any]:
    path = SCHEMA_DIR / (artifact.replace(".json", "") + ".schema.json")
    return orjson.loads(path.read_bytes())


class SchemaDriftTestCase(unittest.TestCase):
    """The checked-in schemas must match what the record classes generate."""

    def test_every_artifact_has_a_checked_in_schema(self):
        for artifact in build_all():
            with self.subTest(artifact=artifact):
                path = SCHEMA_DIR / (artifact.replace(".json", "") + ".schema.json")
                self.assertTrue(path.exists(), f"missing {path.name}")

    def test_every_checked_in_schema_has_a_producer(self):
        """The other direction, which nothing checked until #243.

        `ecoinvent-merge-report.schema.json` was 1,101 lines describing an
        artifact no run had written since the merge report moved into SQLite.
        The drift guard iterates `build_all()`, so it regenerated and compared
        the file every run and reported it healthy; a schema file with no
        producer was invisible. Deleting a producer now leaves a failing test
        rather than a maintained-looking orphan.
        """
        produced = {
            artifact.replace(".json", "") + ".schema.json" for artifact in build_all()
        }
        checked_in = {path.name for path in SCHEMA_DIR.glob("*.schema.json")}
        self.assertEqual(
            checked_in - produced, set(),
            "schema file with no entry in ARTIFACT_SCHEMAS: nothing generates "
            "it, so nothing can tell whether it is current",
        )

    def test_checked_in_schemas_match_generated(self):
        for artifact, generated in build_all().items():
            with self.subTest(artifact=artifact):
                self.assertEqual(
                    _checked_in(artifact), generated,
                    f"{artifact} schema is stale. Regenerate it:\n"
                    "  python -c \"import orjson,pathlib;"
                    "from brightway_flows.domain.schema import build_all;"
                    "[pathlib.Path('src/brightway_flows/data/schemas',"
                    "n.replace('.json','')+'.schema.json').write_bytes("
                    "orjson.dumps(s,option=orjson.OPT_INDENT_2|orjson.OPT_SORT_KEYS)+b'\\n')"
                    " for n,s in build_all().items()]\"",
                )

    def test_schemas_are_themselves_valid(self):
        for artifact, schema in build_all().items():
            with self.subTest(artifact=artifact):
                Draft202012Validator.check_schema(schema)

    def test_every_internal_reference_resolves(self):
        """A `$ref` must point at something in the document that emits it.

        A record whose field is a named schema -- an enum -- generates a `$ref`
        rooted at `#/$defs/`, but the record is embedded under `properties`, so
        its definitions have to be hoisted to the document root.  Left where
        they were generated they resolve to nothing, and neither `check_schema`
        nor the drift guard notices: both are satisfied by a schema whose
        references go nowhere.
        """
        for artifact, schema in build_all().items():
            for ref in _refs(schema):
                with self.subTest(artifact=artifact, ref=ref):
                    self.assertTrue(
                        ref.startswith("#/"),
                        f"{ref} is not a local reference",
                    )
                    node: Any = schema
                    for token in ref.removeprefix("#/").split("/"):
                        self.assertIsInstance(
                            node, dict, f"{ref} does not resolve in {artifact}"
                        )
                        self.assertIn(
                            token, node, f"{ref} does not resolve in {artifact}"
                        )
                        node = node[token]


class RecordSchemaTestCase(unittest.TestCase):
    """The generator must reflect how records actually serialise."""

    def test_aliased_keys_appear_under_their_serialised_name(self):
        schema = record_schema(Flow)
        for attr, alias in Flow._ALIASES.items():
            with self.subTest(field=attr):
                self.assertIn(alias, schema["properties"])
                self.assertNotIn(attr, schema["properties"])

    def test_omit_if_none_fields_are_not_required(self):
        for cls in (Flow, FlowObject, ElementaryFlow):
            schema = record_schema(cls)
            for attr in cls._OMIT_IF_NONE:
                with self.subTest(cls=cls.__name__, field=attr):
                    serialised = cls._ALIASES.get(attr, attr)
                    self.assertNotIn(serialised, schema["required"])

    def test_passthrough_bag_permits_extra_properties(self):
        self.assertTrue(record_schema(Flow)["additionalProperties"])
        self.assertFalse(record_schema(SimpleFlow)["additionalProperties"])

    def test_passthrough_bag_is_not_itself_a_property(self):
        """`extra` is inlined at the top level, not nested under its own key."""
        self.assertNotIn("extra", record_schema(Flow)["properties"])

    def test_a_serialised_record_validates_against_its_schema(self):
        """The generator and the serialiser must not disagree.

        Each record is serialised the way its writer serialises it: records with
        a `to_dict()` through that, and `SimpleFlow` through orjson's native
        dataclass support, which is what `pipeline.exporting` relies on.
        """
        cases = [
            (Flow, Flow(uuid="u-1", source="EF 3.1", unit="kg")),
            # Carries an enum field, so its schema is the one with a `$ref`.
            (UnmatchedRow, UnmatchedRow(
                source_uuid="u-1", source_name="Carbon dioxide",
                source_context=["air"], source_unit="kg", source_cas="124-38-9",
                source_ec="", reason=UnmatchedReason.NO_FLOW_OBJECT_CANDIDATE,
            )),
            (SimpleFlow, SimpleFlow(
                identifier="u-1", source="EF 3.1", cas_numbers=[], ec_numbers=[],
                context_iri="x", unit="kg", unit_iri="y", prefLabel="Water",
                altLabel=[], properties={}, references=[], definition=[],
            )),
        ]
        for cls, instance in cases:
            with self.subTest(cls=cls.__name__):
                serialised = (
                    instance.to_dict()
                    if hasattr(instance, "to_dict")
                    else orjson.loads(orjson.dumps(instance))
                )
                validator = Draft202012Validator(record_schema(cls))
                errors = sorted(validator.iter_errors(serialised),
                                key=lambda e: list(e.path))
                self.assertEqual(
                    errors, [],
                    "; ".join(f"{list(e.path)}: {e.message}" for e in errors),
                )


class SchemaVersionTestCase(unittest.TestCase):
    def test_accepts_the_current_version(self):
        self.assertEqual(
            check_schema_version({"schema_version": SCHEMA_VERSION}, artifact="x"),
            SCHEMA_VERSION,
        )

    def test_rejects_a_missing_version(self):
        with self.assertRaises(SchemaVersionError):
            check_schema_version({}, artifact="x")

    def test_rejects_an_unsupported_version(self):
        """Reading a newer artifact silently is the failure this prevents."""
        with self.assertRaises(SchemaVersionError) as ctx:
            check_schema_version({"schema_version": 99}, artifact="x")
        self.assertIn("99", str(ctx.exception))

    def test_rejects_a_non_object_payload(self):
        with self.assertRaises(SchemaVersionError):
            check_schema_version([], artifact="x")

    def test_every_enveloped_schema_pins_the_version(self):
        """And pins *its own* version.

        The LCIA artifacts are versioned by `LCIA_SCHEMA_VERSION` rather than by
        the flow list's, because a flow-list bump has nothing to say about a
        factor (rule 13).  So this asserts the mapping rather than one constant --
        an artifact missing from it fails, which is what stops a new family from
        quietly pinning whichever number happened to be in scope.
        """
        expected = {
            "flow-objects.json": SCHEMA_VERSION,
            "elementary-flows.json": SCHEMA_VERSION,
            "harmonised-flows-simple.json": SCHEMA_VERSION,
            "harmonised-flows.json": SCHEMA_VERSION,
            "lcia-factors.json": LCIA_SCHEMA_VERSION,
            "lcia-differences.json": LCIA_SCHEMA_VERSION,
            "unit-process-scores.json": ARTIFACT_SCHEMA_VERSION,
            "release-snapshot.json": RELEASE_SNAPSHOT_SCHEMA_VERSION,
            "release-migration-unresolved.json": UNRESOLVED_REPORT_SCHEMA_VERSION,
        }
        self.assertEqual(set(expected), set(build_all()))
        for artifact, schema in build_all().items():
            if schema.get("type") != "object":
                continue
            with self.subTest(artifact=artifact):
                self.assertEqual(
                    schema["properties"]["schema_version"]["const"],
                    expected[artifact],
                )
                self.assertIn("schema_version", schema["required"])


class ArtifactConformanceTestCase(unittest.TestCase):
    """Validate real artifacts when they are present.

    Skipped when the platform data directory has not been populated, so the
    suite still runs on a fresh checkout.
    """

    def _validate(self, artifact: str, document: Any) -> list[Any]:
        validator = Draft202012Validator(build_all()[artifact])
        return list(validator.iter_errors(document))

    def _require_current_version(self, document: Any, *, artifact: str) -> None:
        """Skip an artifact written by an older schema version.

        These read whatever is in the platform data directory, which outlives
        any one release -- and `flow-objects.json` and `elementary-flows.json`
        are no longer written at all, so what is there is a fossil.  A file this
        version does not produce failing this version's schema says nothing; a
        file that claims the current version and does not conform is the finding
        worth having.
        """
        try:
            check_schema_version(document, artifact=artifact)
        except SchemaVersionError as error:
            self.skipTest(str(error))

    def test_flow_objects_artifact_conforms(self):
        if not FLOW_OBJECTS_FILEPATH.exists():
            self.skipTest("flow-objects.json not present")
        document = orjson.loads(FLOW_OBJECTS_FILEPATH.read_bytes())
        self._require_current_version(document, artifact="flow-objects.json")
        errors = self._validate("flow-objects.json", document)
        self.assertEqual(
            errors, [],
            "; ".join(f"{list(e.path)[:3]}: {e.message}" for e in errors[:5]),
        )

    def test_simple_export_artifact_conforms(self):
        if not HARMONISED_FLOWS_SIMPLE_FILEPATH.exists():
            self.skipTest("harmonised-flows-simple.json.gz not present")
        document = orjson.loads(
            gzip.decompress(HARMONISED_FLOWS_SIMPLE_FILEPATH.read_bytes())
        )
        if not isinstance(document, dict):
            self.skipTest("simple export predates the envelope")
        self._require_current_version(document, artifact="harmonised-flows-simple.json")
        errors = self._validate("harmonised-flows-simple.json", document)
        self.assertEqual(
            errors, [],
            "; ".join(f"{list(e.path)[:3]}: {e.message}" for e in errors[:5]),
        )

    def test_the_built_export_conforms(self):
        """Build an export and validate it, rather than looking for one.

        `test_simple_export_artifact_conforms` skips unless the data directory
        happens to hold a `harmonised-flows-simple.json.gz` from a real run,
        which on CI and a fresh checkout it never does.  That is how #230 shipped
        an export carrying `concept_schemes` and `correspondences` against a
        schema declaring neither and `additionalProperties: False`: the
        published artifact did not validate against its own schema, and the only
        test that would have said so was skipped.

        This one has no such precondition, so the contract is checked on every
        run.
        """
        flow = {
            "uuid": "u-1",
            "identifier": "u-1",
            "source": "EF 3.1",
            "unit": "kg",
            "unit_iri": f"{MintedNamespace.UNITS.value}KiloGM",
            "context_iri": f"{MintedNamespace.FLOW_CONTEXTS.value}envi-air",
            "prefLabel": [{"@value": "Carbon dioxide", "@language": "en"}],
            SKOS_DEFINITION_IRI: [{"@value": "A colourless gas.", "@language": "en"}],
            "concept_associations": [{
                XKOS_SOURCE_CONCEPT_CURIE: {
                    "@id": f"{MintedNamespace.EF31_FLOW.value}abc",
                },
                XKOS_TARGET_CONCEPT_CURIE: {
                    "@id": f"{MintedNamespace.CONSENSUS_ELEMENTARY_FLOW.value}u-1",
                },
            }],
        }
        # `to_dict()`, because that is what `write_simple_export` writes.
        document = orjson.loads(orjson.dumps(strip_lcia_from_flows([flow]).to_dict()))
        for key in ("concept_schemes", "correspondences"):
            with self.subTest(key=key):
                self.assertTrue(document.get(key), f"{key} is empty; the test proves nothing")
        errors = self._validate("harmonised-flows-simple.json", document)
        self.assertEqual(
            errors, [],
            "; ".join(f"{list(e.path)[:4]}: {e.message}" for e in errors[:5]),
        )

    def test_elementary_flows_artifact_conforms(self):
        """Every record must conform, whichever path produced it.

        Merge-created flows used to omit fields that transform-created flows
        carried; they are now built through the record classes, so one schema
        covers both.
        """
        if not ELEMENTARY_FLOWS_FILEPATH.exists():
            self.skipTest("elementary-flows.json not present")
        document = orjson.loads(ELEMENTARY_FLOWS_FILEPATH.read_bytes())
        self._require_current_version(document, artifact="elementary-flows.json")
        errors = self._validate("elementary-flows.json", document)
        self.assertEqual(
            errors[:5], [],
            "; ".join(f"{list(e.path)[:3]}: {e.message}" for e in errors[:5]),
        )

    def test_records_share_one_shape_regardless_of_source(self):
        """No source may produce records missing fields every other source has.

        This is the invariant the merge used to break: it appended
        elementary-flow-shaped dicts into a file of Flow records.
        """
        if not ELEMENTARY_FLOWS_FILEPATH.exists():
            self.skipTest("elementary-flows.json not present")
        rows = orjson.loads(ELEMENTARY_FLOWS_FILEPATH.read_bytes())["elementary_flows"]
        if not rows:
            self.skipTest("no elementary flows")
        shapes_by_source: dict[str, list[set[str]]] = {}
        for row in rows:
            shapes_by_source.setdefault(str(row.get("source") or "?"), []).append(set(row))
        universal = set.intersection(
            *[shape for shapes in shapes_by_source.values() for shape in shapes]
        )
        offenders = {
            source: sorted(universal - set.intersection(*shapes))
            for source, shapes in shapes_by_source.items()
            if universal - set.intersection(*shapes)
        }
        self.assertEqual(offenders, {}, f"sources missing universal fields: {offenders}")


if __name__ == "__main__":
    unittest.main()
