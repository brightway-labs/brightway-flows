"""JSON Schemas for the published artifacts, derived from the record classes.

The schemas are *generated* rather than hand-written, so they cannot drift from
the dataclasses they describe. `tests/test_schemas.py` regenerates them and fails
if the checked-in copies differ, which is what makes them a contract rather than
documentation.

Generation is not simply `TypeAdapter(cls).json_schema()`, because a record's
serialised shape differs from its Python shape in three ways, all handled here:

- fields whose serialised key is not a valid Python identifier are renamed via
  the record's ``_ALIASES``
- fields listed in ``_OMIT_IF_NONE`` are absent from the output when unset, so
  they are not required
- a record with an ``_EXTRA_FIELD`` inlines unrecognised keys at the top level,
  so its schema must permit additional properties

Bump ``SCHEMA_VERSION`` when a change would break a reader. Adding an optional
field does not; removing one, renaming one, or narrowing a type does.
"""

from __future__ import annotations

from dataclasses import fields, is_dataclass
from typing import Any

from pydantic import TypeAdapter

from brightway_flows.domain.elementary_flow import ElementaryFlow
from brightway_flows.domain.flow import Flow
from brightway_flows.domain.flow_object import FlowObject
from brightway_flows.domain.simple_flow import FlowRedirect, SimpleFlow

#: Version written into every artifact envelope, and required on read.
#:
#: 2 -- `concept_associations` no longer carries `xkos:mapType`.  XKOS defines no
#:      property for the type or strength of a mapping, so the match is expressed
#:      with the SKOS mapping property itself (`skos:exactMatch`) on the source
#:      concept.  A consumer reading `xkos:mapType` gets nothing, and until this
#:      bump had no version signal to detect it.
#:
#: 3 -- The published export is JSON-LD.  It carries `@context` and each flow
#:      carries `@id`, so the document expands.  Two changes break a reader that
#:      assumed strings: numeric semantic properties (`molecular_mass`,
#:      `elemental_charge`, ...) are now JSON numbers rather than quoted ones,
#:      and a whole-entity charge moved from `chemrof:formal_charge` -- which
#:      ChemROF scopes to `AtomOccurrence` -- to `chemrof:elemental_charge`.
#:      Anything reading the old key finds nothing.
#: 4 -- The mappings to other flow lists moved out of the flows.  A flow no
#:      longer carries `concept_associations`; the document carries
#:      `concept_schemes` and `correspondences`, and each mapping is an
#:      `xkos:ConceptAssociation` node with its own IRI, collected by the
#:      `xkos:Correspondence` for its source list.  Find the mappings for a flow
#:      by its `xkos:targetConcept`.  Flows also gain `skos:Concept` in `@type`
#:      and a `skos:inScheme`.
#: 5 -- The document carries `redirects`: one record per deprecated flow, saying
#:      which surviving flow its identifier resolves to and whether the two were
#:      ever the same flow.  A reader that validates against version 4's schema
#:      rejects the new key -- the document is `additionalProperties: False` --
#:      and, more to the point, a reader that finds no `redirects` needs to know
#:      whether that means "nothing was deprecated" or "an export from before
#:      they were published".  Without the bump those two are the same ambiguity
#:      #39 was raised to remove.
#: 6 -- `context` is described rather than merely named.  It was
#:      `{"title": "Context"}` on an elementary flow -- which permits anything --
#:      and "an array or an object, contents unspecified" on a harmonised one,
#:      because the field held two things: the compartment path a source list
#:      ships and the consensus context the run decides on.  It holds the second
#:      alone now, and the schema says so: eight named fields, each constrained
#:      to its enum (#97).
#:
#:      No published document changes.  Every one of the 40 distinct contexts in
#:      a full 95,193-flow build validates against the new schema, so a consumer
#:      re-validating artifacts it already has finds them still valid.  The bump
#:      is for the consumer going the other way: one that *wrote* a document
#:      against version 5 could put an array in `context`, or an object with
#:      fields of its own choosing, and this version rejects both.  A narrowing
#:      is a break for a writer even when it is a no-op for a reader.
#: 7 -- a redirect may carry no replacement.  `dcterms:isReplacedBy` and
#:      `replaced_by_identifier` were required on every record in `redirects`,
#:      and a reader written against version 6 may dereference either without
#:      checking.  A *withdrawal* has neither: the source row the flow was minted
#:      from is one this list has decided not to map, so the flow is gone and
#:      nothing takes its place, which
#:      `brightway:deprecationReason: source-row-withdrawn` says (#115).  Made
#:      optional rather than filled with a sentinel, because a redirect onto an
#:      identifier the document does not carry is the silent miss the whole
#:      `redirects` block exists to remove.
#:
#:      Adding `brightway:excludedSourceConcept` to a correspondence in the same
#:      change needs no bump on its own -- it is an optional field, and the
#:      document is not `additionalProperties: False` at that level -- but it is
#:      what a reader should look at on meeting the new reason, so the two arrive
#:      together.
SCHEMA_VERSION = 7

_JSON_SCHEMA_DIALECT = "https://json-schema.org/draft/2020-12/schema"


def record_schema(record_cls: type) -> dict[str, Any]:
    """Return a JSON Schema for one record's ``to_dict()`` output."""
    if not is_dataclass(record_cls):
        raise TypeError(f"{record_cls.__name__} is not a dataclass")

    generated = TypeAdapter(record_cls).json_schema(mode="serialization")
    aliases: dict[str, str] = getattr(record_cls, "_ALIASES", {})
    omit_if_none: frozenset[str] = getattr(record_cls, "_OMIT_IF_NONE", frozenset())
    extra_field: str | None = getattr(record_cls, "_EXTRA_FIELD", None)

    declared: dict[str, Any] = getattr(record_cls, "_SERIALISED_SCHEMAS", {})

    properties: dict[str, Any] = {}
    for name, subschema in (generated.get("properties") or {}).items():
        if name == extra_field:
            # Inlined at the top level rather than nested under its own key.
            continue
        # A field with a codec can publish a shape its annotation does not
        # describe, and this schema is about the published shape.  Where the
        # record says what that is, the record wins.
        properties[aliases.get(name, name)] = declared.get(name, subschema)

    required = sorted(
        aliases.get(f.name, f.name)
        for f in fields(record_cls)
        if f.name != extra_field and f.name not in omit_if_none
    )

    schema: dict[str, Any] = {
        "type": "object",
        "properties": properties,
        "required": required,
        # A record with a passthrough bag round-trips source-specific keys, so
        # extra properties are expected rather than a violation.
        "additionalProperties": extra_field is not None,
    }
    if defs := _referenced_defs(generated.get("$defs") or {}, properties):
        schema["$defs"] = defs
    return schema


def _referenced_defs(
    defs: dict[str, Any], properties: dict[str, Any]
) -> dict[str, Any]:
    """The named schemas the properties actually reach.

    A field with a `_SERIALISED_SCHEMAS` entry replaces whatever the annotation
    generated, and the definitions that entry no longer points at would
    otherwise stay in the document -- describing records a reader of the
    published file never sees.  A dead `$def` is not wrong, but it is a
    published statement that this file holds something it does not.
    """
    wanted: set[str] = set()

    def visit(node: Any) -> None:
        if isinstance(node, dict):
            ref = node.get("$ref")
            if isinstance(ref, str) and ref.startswith("#/$defs/"):
                name = ref.removeprefix("#/$defs/")
                if name not in wanted:
                    wanted.add(name)
                    visit(defs.get(name))
            for value in node.values():
                visit(value)
        elif isinstance(node, list):
            for value in node:
                visit(value)

    visit(properties)
    return {name: subschema for name, subschema in defs.items() if name in wanted}


def _hoist_defs(record: dict[str, Any], *, into: dict[str, Any]) -> dict[str, Any]:
    """Move a record's ``$defs`` to the root of the document embedding it.

    :func:`record_schema` returns a self-contained schema, so a field whose type
    is a named schema -- an enum, say -- is a ``$ref`` rooted at ``#/$defs/``.
    Embedding that under ``properties`` without moving its definitions to the
    document root leaves those references pointing at a ``$defs`` that is not
    where they say it is, and they resolve to nothing.

    :raises ValueError: if two records define the same name differently.
    """
    defs = record.pop("$defs", None)
    if not defs:
        return record
    root = into.setdefault("$defs", {})
    for name, subschema in defs.items():
        if root.get(name, subschema) != subschema:
            raise ValueError(
                f"two records define $defs/{name} differently; "
                "one of them needs a distinct name"
            )
        root[name] = subschema
    return record


def _envelope(
    *,
    title: str,
    description: str,
    collection_key: str,
    record_cls: type,
    omit_record_fields: frozenset[str] = frozenset(),
) -> dict[str, Any]:
    """Wrap a record schema in the ``{schema_version, <collection>, stats}`` envelope."""
    record = record_schema(record_cls)
    for name in omit_record_fields:
        record["properties"].pop(name, None)
        record["required"] = [r for r in record["required"] if r != name]
    document: dict[str, Any] = {
        "$schema": _JSON_SCHEMA_DIALECT,
        "title": title,
        "description": description,
        "type": "object",
        "properties": {
            "schema_version": {"type": "integer", "const": SCHEMA_VERSION},
            collection_key: {"type": "array", "items": record},
            "stats": {"type": "object"},
        },
        "required": ["schema_version", collection_key],
        "additionalProperties": True,
    }
    _hoist_defs(record, into=document)
    return document


def flow_objects_schema() -> dict[str, Any]:
    """Schema for ``flow-objects.json``."""
    return _envelope(
        title="flow-objects.json",
        description="Canonical substance identities, shared across contexts.",
        collection_key="flow_objects",
        record_cls=FlowObject,
    )


def elementary_flows_schema() -> dict[str, Any]:
    """Schema for ``elementary-flows.json``.

    ``source_refs`` is deliberately absent: the writer strips it, because the
    per-source detail lives in the merge report and the SQLite database instead.
    """
    return _envelope(
        title="elementary-flows.json",
        description=(
            "Substances in contexts. The (flow_object_id, context_iri) pair is "
            "unique across non-deprecated flows."
        ),
        collection_key="elementary_flows",
        record_cls=ElementaryFlow,
        omit_record_fields=frozenset({"source_refs"}),
    )


def harmonised_flows_simple_schema() -> dict[str, Any]:
    """Schema for ``harmonised-flows-simple.json.gz``, the published export.

    ``@context`` is required, not optional.  A JSON-LD document without one
    expands to nothing, and this artifact's whole point is that the IRIs in it
    resolve -- so an export that omitted it would be silently unusable, which is
    exactly the failure a schema exists to make loud.

    ``redirects`` is required for a third reason, and the one that matters most
    to a consumer: an export whose ``redirects`` key is missing is
    indistinguishable from one where nothing was deprecated, which is the exact
    ambiguity #39 exists to remove.  Required and possibly empty says
    something; absent says nothing.

    ``concept_schemes`` and ``correspondences`` are required for the same
    reason they exist: #230 moved the mappings out of the flows and into these
    two keys, so a document without them carries no mappings at all.  They were
    added to the export and not to this schema, which -- with
    ``additionalProperties: False`` -- meant the published artifact did not
    validate against its own schema from #230 until now.  Nothing caught it
    because the conformance test skips when the data directory has no export in
    it; ``test_the_built_export_conforms`` now builds one instead of looking for
    one.
    """
    from brightway_flows.pipeline.correspondences import (
        ConceptAssociationNode,
        ConceptSchemeNode,
        CorrespondenceNode,
        XKOS_MADE_OF_CURIE,
    )

    # `record_schema` applies `_ALIASES` to the record it is given, but pydantic
    # generates a nested record's schema from its *attribute* names, and nothing
    # renames those.  `CorrespondenceNode.made_of` is the only nested-record
    # field in any published artifact, and its `to_dict()` is hand-written for
    # the same reason -- so the substitution is done here rather than by making
    # `record_schema` recursive, which would change every artifact's schema to
    # fix one field.  If a second nested-record field appears, that recursion is
    # the right fix.
    correspondence = record_schema(CorrespondenceNode)
    correspondence.pop("$defs", None)
    correspondence["properties"][XKOS_MADE_OF_CURIE] = {
        "type": "array", "items": record_schema(ConceptAssociationNode),
    }

    document: dict[str, Any] = {
        "$schema": _JSON_SCHEMA_DIALECT,
        "title": "harmonised-flows-simple.json.gz",
        "description": (
            "Simplified non-deprecated flows, for downstream consumers, with a "
            "redirect for every identifier that was deprecated."
        ),
        "type": "object",
        "properties": {
            "@context": {"type": "object", "minProperties": 1},
            "schema_version": {"type": "integer", "const": SCHEMA_VERSION},
            "flows": {"type": "array", "items": record_schema(SimpleFlow)},
            "redirects": {"type": "array", "items": record_schema(FlowRedirect)},
            "concept_schemes": {
                "type": "array", "items": record_schema(ConceptSchemeNode),
            },
            "correspondences": {"type": "array", "items": correspondence},
        },
        "required": [
            "@context", "schema_version", "flows", "redirects",
            "concept_schemes", "correspondences",
        ],
        "additionalProperties": False,
    }
    # As elsewhere: the records are embedded under `items`, so any `$defs` they
    # generated have to reach the document root or their `$ref`s dangle.
    for record in document["properties"].values():
        if isinstance(record.get("items"), dict):
            _hoist_defs(record["items"], into=document)
    return document


# `merge_report_schema()` was here until #243, describing
# `ecoinvent-merge-report-{version}.json`.  The merge moved its report into
# SQLite; the schema stayed, was regenerated and diff-checked on every run of
# `tests/test_schemas.py`, and so read as maintained.  A schema is a contract
# with a reader, and this one had no artifact to be a contract about.  The record
# classes in `merge/report.py` are untouched: they still feed `MergeOutcome` and
# the merge tables.


def harmonised_flows_schema() -> dict[str, Any]:
    """Schema for ``harmonised-flows.json``, a bare list with no envelope.

    ``source_refs`` is absent: the writer strips it, as it does for
    ``elementary-flows.json``.
    """
    record = record_schema(Flow)
    record["properties"].pop("source_refs", None)
    record["required"] = [r for r in record["required"] if r != "source_refs"]
    document: dict[str, Any] = {
        "$schema": _JSON_SCHEMA_DIALECT,
        "title": "harmonised-flows.json",
        "description": (
            "Every flow after all transformers have run. A bare list, with no "
            "envelope and so no schema_version."
        ),
        "type": "array",
        "items": record,
    }
    # As for the enveloped artifacts: `record` is embedded under `items`, so its
    # `$defs` have to move to the document root or the `$ref`s emitted for a
    # nested record point at a `$defs` that is not where they say it is.
    _hoist_defs(record, into=document)
    return document


def _lcia_document(
    *,
    title: str,
    description: str,
    collections: dict[str, type],
    omit_record_fields: dict[str, frozenset[str]] | None = None,
) -> dict[str, Any]:
    """Wrap several record collections in an LCIA artifact's envelope.

    `_envelope` takes one collection and these documents hold three and two:
    `lcia-factors.json.gz` publishes methods, categories and factors as sibling
    arrays rather than nesting a quarter of a million factors inside 75
    categories, and `lcia-differences.json` publishes both of §5's reports.

    ``schema_version`` is `LCIA_SCHEMA_VERSION`, not the flow list's
    `SCHEMA_VERSION`: these are different artifacts and a flow-list bump has
    nothing to say about a factor (rule 13).
    """
    from brightway_flows.domain.lcia.records import LCIA_SCHEMA_VERSION

    omit = omit_record_fields or {}
    document: dict[str, Any] = {
        "$schema": _JSON_SCHEMA_DIALECT,
        "title": title,
        "description": description,
        "type": "object",
        "properties": {
            "schema_version": {"type": "integer", "const": LCIA_SCHEMA_VERSION},
            "stats": {"type": "object"},
        },
        "required": ["schema_version", *collections],
        "additionalProperties": False,
    }
    for key, record_cls in collections.items():
        record = record_schema(record_cls)
        for name in omit.get(key, frozenset()):
            record["properties"].pop(name, None)
            record["required"] = [r for r in record["required"] if r != name]
        _hoist_defs(record, into=document)
        document["properties"][key] = {"type": "array", "items": record}
    return document


def lcia_factors_schema() -> dict[str, Any]:
    """Schema for ``lcia-factors.json.gz``.

    ``characterization_factors`` is absent from a category for the same reason
    ``source_refs`` is absent from a published elementary flow: the writer strips
    it, because the factors are published once, under a key of their own, and a
    category holding a quarter of a million of them is not a row anybody can read.

    A factor has no identifier of its own, and the schema is where that is worth
    saying out loud.  It is identified by the three things that make it one --
    the category, the flow and the place -- which is what
    ``lcia_characterization_factors`` declares as its primary key.
    """
    from brightway_flows.domain.lcia.records import (
        CharacterizationFactor,
        ImpactCategory,
        LCIAMethod,
    )

    return _lcia_document(
        title="lcia-factors.json.gz",
        description=(
            "Three implementations of EF 3.1 -- the European Commission's JRC, "
            "the ecoinvent Centre's, and this list's -- as impact categories and "
            "the characterisation factors they hold, on the consensus flows. A "
            "factor is unique per (impact_category_id, flow_id, geography)."
        ),
        collections={
            "methods": LCIAMethod,
            "impact_categories": ImpactCategory,
            "characterization_factors": CharacterizationFactor,
        },
        omit_record_fields={
            "impact_categories": frozenset({"characterization_factors"})
        },
    )


def lcia_differences_schema() -> dict[str, Any]:
    """Schema for ``lcia-differences.json``, the comparison deliverable.

    Two arrays, because §5 is two reports: `differences` is between the two
    published implementations and `coverage` is about each of them on its own.
    Both are required and either may be empty -- an absent key would be
    indistinguishable from a run that found nothing, which is the ambiguity a
    required-and-possibly-empty array exists to remove.
    """
    from brightway_flows.domain.lcia.records import CoverageGap, Difference

    return _lcia_document(
        title="lcia-differences.json",
        description=(
            "Where two implementations of EF 3.1 state different numbers for one "
            "flow, category and place, and where each of them characterises a "
            "substance in one context and skips the context beside it. A "
            "difference is not an error: most are modelling choices."
        ),
        collections={"differences": Difference, "coverage": CoverageGap},
    )


def unit_process_scores_schema() -> dict[str, Any]:
    """Schema for ``unit-process-scores-<release>.json``, the one artifact read in.

    Every other schema here describes a file this package writes.  This one
    describes a file it *reads*, written by `tools/export_unit_process_scores.py`
    under a brightway Python that has no access to the records -- so the schema
    is the whole contract between the two, and the exporter validates against
    the checked-in copy before it writes.

    ``schema_version`` is the artifact's own, `ARTIFACT_SCHEMA_VERSION`, for
    the reason the LCIA files carry theirs (rule 13).  ``additionalProperties``
    is false throughout: a key the records do not declare is a key the
    comparison would silently ignore, and an exporter that added one should
    hear so.
    """
    from brightway_flows.domain.lcia.unit_process_scores import (
        ARTIFACT_SCHEMA_VERSION,
        ScoreArtifact,
    )

    record = record_schema(ScoreArtifact)
    record["properties"]["schema_version"] = {
        "type": "integer", "const": ARTIFACT_SCHEMA_VERSION,
    }
    # `record_schema` closes the record it is given; the records nested under
    # it come from pydantic as generated, which permits extra keys.  The
    # contract is closed all the way down.
    for definition in record.get("$defs", {}).values():
        if definition.get("type") == "object" and "properties" in definition:
            definition["additionalProperties"] = False
    document: dict[str, Any] = {
        "$schema": _JSON_SCHEMA_DIALECT,
        "title": "unit-process-scores.json",
        "description": (
            "What a vendor's own tooling says a sample of its unit processes "
            "are worth: each one's cumulative inventory by the vendor's own "
            "flow identifiers, the factors that tooling applied, and the scores "
            "the two reproduce. Written by tools/export_unit_process_scores.py "
            "under brightway; read by compare-scores."
        ),
        **record,
    }
    return document


def release_snapshot_schema() -> dict[str, Any]:
    """Schema for ``releases/<version>.json.gz``, a release as a migration sees it.

    ``schema_version`` is `RELEASE_SNAPSHOT_SCHEMA_VERSION`: the file is this
    project's own, read by `release-migrations` alone, and versions
    independently of the flow list it projects (rule 13).  Every collection is
    required, and possibly empty -- a build nobody has characterised has no
    factors, and says so with an empty list rather than a missing key.
    """
    from brightway_flows.releases.snapshot import (
        RELEASE_SNAPSHOT_SCHEMA_VERSION,
        ReleaseSnapshot,
        ReleaseStamp,
    )

    document: dict[str, Any] = {
        "$schema": _JSON_SCHEMA_DIALECT,
        "title": "release-snapshot.json",
        "description": (
            "One release of the Brightway flows list, projected onto what a "
            "migration compares: the published fields of every substance and "
            "flow, the redirects, the characterisation factors by their triple, "
            "and the source rows that align one build's identifiers with "
            "another's. Written by release-snapshot; read by release-migrations."
        ),
        "type": "object",
        "properties": {
            "schema_version": {"type": "integer", "const": RELEASE_SNAPSHOT_SCHEMA_VERSION},
        },
        "required": ["schema_version", "stamp", *ReleaseSnapshot._COLLECTIONS],
        "additionalProperties": False,
    }
    stamp = record_schema(ReleaseStamp)
    _hoist_defs(stamp, into=document)
    document["properties"]["stamp"] = stamp
    for key, record_cls in ReleaseSnapshot._COLLECTIONS.items():
        record = record_schema(record_cls)
        _hoist_defs(record, into=document)
        document["properties"][key] = {"type": "array", "items": record}
    return document


def release_migration_unresolved_schema() -> dict[str, Any]:
    """Schema for ``unresolved.json`` beside a pair's migration files.

    One record per identifier the migration could not resolve, in the same
    shape `releases/diff.py` gives every change, so a reader sees what the
    row was and what it might have become without opening a snapshot.
    """
    from brightway_flows.releases.diff import Delta
    from brightway_flows.releases.randonneur_files import (
        UNRESOLVED_REPORT_SCHEMA_VERSION,
    )

    record = record_schema(Delta)
    document: dict[str, Any] = {
        "$schema": _JSON_SCHEMA_DIALECT,
        "title": "release-migration-unresolved.json",
        "description": (
            "The identifiers of the earlier release that release-migrations "
            "could not resolve against the later one -- a split, a unit change, "
            "a redirect the export tells a consumer to refuse -- each with its "
            "candidates and the reason. The worklist for "
            "release-migration-rulings.json."
        ),
        "type": "object",
        "properties": {
            "schema_version": {"type": "integer", "const": UNRESOLVED_REPORT_SCHEMA_VERSION},
            "from_version": {"type": "string"},
            "to_version": {"type": "string"},
            "source_id": {"type": "string"},
            "target_id": {"type": "string"},
            "description": {"type": "string"},
            "counts": {"type": "object"},
            "items": {"type": "array", "items": record},
        },
        "required": [
            "schema_version", "from_version", "to_version", "source_id", "target_id",
            "counts", "items",
        ],
        "additionalProperties": False,
    }
    _hoist_defs(record, into=document)
    return document


#: Artifact filename -> the function producing its schema.
ARTIFACT_SCHEMAS: dict[str, Any] = {
    "flow-objects.json": flow_objects_schema,
    "elementary-flows.json": elementary_flows_schema,
    "harmonised-flows-simple.json": harmonised_flows_simple_schema,
    "harmonised-flows.json": harmonised_flows_schema,
    "lcia-factors.json": lcia_factors_schema,
    "lcia-differences.json": lcia_differences_schema,
    "unit-process-scores.json": unit_process_scores_schema,
    "release-snapshot.json": release_snapshot_schema,
    "release-migration-unresolved.json": release_migration_unresolved_schema,
}


def build_all() -> dict[str, dict[str, Any]]:
    """Return every artifact schema, keyed by artifact filename."""
    return {name: build() for name, build in ARTIFACT_SCHEMAS.items()}


class SchemaVersionError(ValueError):
    """An artifact declares a schema version this code cannot read."""


def check_schema_version(
    payload: Any, *, artifact: str, expected: int | None = None
) -> int:
    """Validate the ``schema_version`` of a loaded artifact.

    Reading an artifact written by a newer, incompatible version silently is the
    failure this guards against: the fields a reader wants may be gone.

    *expected* is the published flow list's ``SCHEMA_VERSION`` unless a caller
    says otherwise, because most artifacts are versioned by it.  The LCIA files
    are not -- they carry ``LCIA_SCHEMA_VERSION``, since a flow-list bump has
    nothing to say about a factor (rule 13) -- so a reader of one passes it.

    :raises SchemaVersionError: if the version is missing or unsupported.
    """
    supported = SCHEMA_VERSION if expected is None else expected
    if not isinstance(payload, dict):
        raise SchemaVersionError(
            f"{artifact}: expected an object with a schema_version, "
            f"got {type(payload).__name__}"
        )
    version = payload.get("schema_version")
    if version is None:
        raise SchemaVersionError(f"{artifact}: missing schema_version")
    if version != supported:
        raise SchemaVersionError(
            f"{artifact}: schema_version {version!r} is not supported by this "
            f"version of brightway-flows, which reads {supported}"
        )
    return version
