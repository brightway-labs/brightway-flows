"""Original mapping assertions and their custody, without deciding identities.

An evidence-record ID names an artifact row, never a replacement flow identity.
Missing source IDs are quarantined. References to historical aliases mean exact
identifier occurrence, not scientific support or verified execution ancestry.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import platform
from collections import Counter, defaultdict
from dataclasses import dataclass, field, replace
from datetime import date, datetime
from enum import StrEnum
from importlib.metadata import version
from pathlib import Path

from pydantic import TypeAdapter

from .curation import Digest, Identifier, Link, RecordedAt, _Record

PROCEDURE_PATHS = {
    "tools/stage_mapping_provenance.py",
    "src/brightway_flows/webapps/app/curation_mapping_provenance.py",
    "uv.lock",
}


class Format(StrEnum):
    CSV = "csv"
    XLSX = "xlsx"
    JSON = "json"


class Adapter(StrEnum):
    GLAD = "glad"
    HESTIA = "hestia"
    DDS = "dds"
    SENTIER = "sentier-placeholder"
    PLACEHOLDER = "inhouse-placeholder"
    FLOWMAPPER = "flowmapper"
    FEDEFL = "fedefl"
    REGISTRY = "registry"
    HISTORICAL = "historical"
    SEED = "historical-seed"
    SENTIER_BAFU = "sentier-bafu"


class Status(StrEnum):
    UNRESOLVED = "unresolved"
    QUARANTINED = "quarantined"
    REFERENCE = "reference"


class SourceRole(StrEnum):
    UNQUALIFIED = "unqualified"
    EVIDENCE = "mapping-evidence"
    CROSS_VALIDATION = "cross-validation-only"
    SEED = "historical-seed"
    REGISTRY = "registry-definitions"
    RESULT = "historical-result"


@dataclass(frozen=True)
class Artifact(_Record):
    id: Identifier
    title: str
    filename: str
    sha256: Digest
    format: Format
    adapter: Adapter
    reference: Link | None
    source_version: str | None
    historical_binding: str
    namespace: str = ""
    source_list: str | None = None
    target_list: str | None = None
    role: SourceRole = SourceRole.UNQUALIFIED
    scope: str | None = None


@dataclass(frozen=True)
class Inputs(_Record):
    schema_version: int
    recorded_at: RecordedAt
    scientific_signoff: bool
    artifacts: list[Artifact]


@dataclass(frozen=True)
class Endpoint(_Record):
    identifier: str | None = None
    name: str | None = None
    list_version: str | None = None
    context: str | list | None = None
    unit: str | None = None


@dataclass(frozen=True)
class Assertion(_Record):
    id: Identifier
    artifact_id: Identifier
    locator: str
    row_sha256: Digest
    source: Endpoint
    targets: list[Endpoint]
    relation: str | None
    conversion: str | int | float | None
    conversion_direction: str
    mapper: str | None
    verifier: str | None
    stated_date: str | None
    status: Status
    issues: list[str]
    original: dict  # External payload, retained verbatim at this I/O boundary.
    dependencies: list[Identifier] = field(default_factory=list)


@dataclass(frozen=True)
class RowRef(_Record):
    artifact_id: Identifier
    locator: str
    row_sha256: Digest


@dataclass(frozen=True)
class AliasTrace(_Record):
    id: str
    original: RowRef
    members: list[RowRef]
    assertions: list[Identifier]
    status: Status
    issues: list[str]


@dataclass(frozen=True)
class Payload(_Record):
    filename: str
    sha256: Digest
    rows: int


@dataclass(frozen=True)
class Manifest(_Record):
    schema_version: int
    recorded_at: RecordedAt
    inputs: Inputs
    input_manifest_sha256: Digest
    procedures: dict[str, Digest]
    runtime: dict[str, str]
    assertions: Payload
    aliases: Payload
    case_links: dict[str, dict[str, list[str]]]
    case_sha256: dict[str, Digest]
    counts: dict[str, dict[str, int]]
    scientific_signoff: bool
    consumer_adoption: bool


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def encoded(value) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
        allow_nan=False,
    ).encode()


def valid_identifier(value) -> str | None:
    """Keep an actual identifier; never stringify null/NaN into a flow key."""
    if not isinstance(value, str):
        return None
    value = value.strip()
    return (
        value
        if value and value.casefold() not in {"nan", "none", "null", "nat", "n/a"}
        else None
    )


def _text(value) -> str | None:
    if isinstance(value, dict) and "__original_json_nonfinite_literal__" in value:
        return None
    return str(value) if value is not None and value != "" else None


def loads_original(raw):
    """Retain a non-standard JSON literal explicitly, never invent a number.

    The original file bytes stay authoritative. This tagged evidence projection
    distinguishes the literal NaN from null, zero and the string "NaN".
    """

    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError(
                    "Duplicate original JSON key; interpretation unresolved"
                )
            result[key] = value
        return result

    return json.loads(
        raw,
        object_pairs_hook=pairs,
        parse_constant=lambda v: {"__original_json_nonfinite_literal__": v},
    )


def runtime():
    return {
        "python": platform.python_version(),
        "openpyxl": version("openpyxl"),
        "pydantic": version("pydantic"),
    }


def _safe_path(root: Path, filename: str) -> Path:
    path = (root / filename).resolve()
    if Path(filename).is_absolute() or not path.is_relative_to(root.resolve()):
        raise ValueError("Mapping source path escapes its custody directory")
    return path


def _cell(value):
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError(
            "Non-finite source cell; retain and qualify its original artifact"
        )
    return value


def raw_rows(artifact: Artifact, directory: Path):
    """Read all original rows; formulas remain text and are never executed."""
    path = _safe_path(directory, artifact.filename)
    raw = path.read_bytes()
    if sha(raw) != artifact.sha256:
        raise ValueError(f"Changed mapping input: {artifact.id}")
    if artifact.format == Format.CSV:
        reader = csv.DictReader(io.StringIO(raw.decode("utf-8-sig")))
        if not reader.fieldnames or len(set(reader.fieldnames)) != len(
            reader.fieldnames
        ):
            raise ValueError("Missing or duplicate CSV headers")
        for line, row in enumerate(reader, 2):
            if None in row or any(v is None for v in row.values()):
                raise ValueError("Malformed CSV row")
            yield f"csv-row:{line}", row
    elif artifact.format == Format.XLSX:
        import openpyxl

        workbook = openpyxl.load_workbook(
            io.BytesIO(raw), read_only=True, data_only=False
        )
        try:
            for sheet in workbook:
                rows = sheet.iter_rows(values_only=True)
                headers = next(rows, ())
                if (
                    not headers
                    or len(set(headers)) != len(headers)
                    or any(h is None for h in headers)
                ):
                    raise ValueError("Missing or duplicate workbook headers")
                for line, cells in enumerate(rows, 2):
                    yield (
                        f"sheet:{sheet.title}/row:{line}",
                        {str(k): _cell(v) for k, v in zip(headers, cells, strict=True)},
                    )
        finally:
            workbook.close()
    else:
        value = loads_original(raw)
        if artifact.adapter == Adapter.SENTIER_BAFU and (
            not artifact.source_list
            or not artifact.target_list
            or value.get("name") != f"{artifact.source_list}__{artifact.target_list}"
        ):
            raise ValueError(
                "Partner source/target lists differ from the original artifact title"
            )
        key = {
            Adapter.DDS: "links",
            Adapter.PLACEHOLDER: "mappings",
            Adapter.HISTORICAL: "flows",
            Adapter.FLOWMAPPER: "new_matches",
            Adapter.SENTIER_BAFU: "replace",
        }.get(artifact.adapter)
        rows = (
            value
            if artifact.adapter in {Adapter.REGISTRY, Adapter.SEED}
            else value[key]
        )
        if artifact.adapter == Adapter.FLOWMAPPER and not isinstance(rows, list):
            rows = value["matches"]
        if not isinstance(rows, (list, dict)):
            raise ValueError("Unsupported original mapping row population")
        for index, row in enumerate(rows) if isinstance(rows, list) else rows.items():
            if not isinstance(row, dict):
                raise ValueError("Original mapping row is not an object")
            escaped = str(index).replace("~", "~0").replace("/", "~1")
            yield (f"/{key}/{escaped}" if key else f"/{escaped}"), row


def _endpoint(row, prefix):
    return Endpoint(
        valid_identifier(row.get(prefix + "FlowUUID")),
        _text(row.get(prefix + "FlowName")),
        _text(row.get(prefix + "ListName")),
        row.get(prefix + "FlowContext"),
        _text(row.get(prefix + "Unit")),
    )


def assertion(artifact: Artifact, locator: str, row: dict) -> Assertion:
    source, targets = Endpoint(), []
    relation = conversion = mapper = verifier = stated_date = None
    reference = False
    if artifact.adapter in {Adapter.GLAD, Adapter.HESTIA, Adapter.FEDEFL}:
        source = _endpoint(row, "Source")
        targets = [_endpoint(row, "Target")]
        relation = _text(row.get("MatchCondition"))
        conversion = row.get("ConversionFactor")
        mapper, verifier = _text(row.get("Mapper")), _text(row.get("Verifier"))
        stated_date = _text(row.get("LastUpdated"))
    elif artifact.adapter == Adapter.DDS:
        source = Endpoint(
            valid_identifier(row.get("bio3_uuid")),
            row.get("bio3_name"),
            row.get("source_dataset"),
            row.get("bio3_context"),
            row.get("source_unit"),
        )
        targets = [
            Endpoint(
                valid_identifier(row.get("ef31_uuid")),
                row.get("ef31_name"),
                None,
                row.get("ef31_context"),
                row.get("target_unit"),
            )
        ]
        conversion = row.get("conversion_factor")
    elif artifact.adapter == Adapter.PLACEHOLDER:
        source = Endpoint(
            valid_identifier(row.get("placeholder_code")),
            row.get("placeholder_name"),
            artifact.source_version,
            row.get("placeholder_categories"),
            row.get("placeholder_unit"),
        )
        for code, name, context, version in [
            (
                "matched_ef31_uuid",
                "matched_ef31_name",
                "matched_ef31_categories",
                "EF 3.1",
            ),
            ("matched_bio3_code", "matched_bio3_name", "matched_bio3_categories", None),
        ]:
            if row.get(code) is not None or row.get(name) is not None:
                targets.append(
                    Endpoint(
                        valid_identifier(row.get(code)),
                        row.get(name),
                        version,
                        row.get(context),
                    )
                )
    elif artifact.adapter == Adapter.SENTIER:
        reference = locator.startswith("sheet:Summary/")
        source = Endpoint(
            valid_identifier(row.get("code")),
            row.get("name"),
            artifact.source_version,
            row.get("categories"),
            row.get("unit"),
        )
        for prefix, version in [
            ("matched_ef", "EF 3.1"),
            ("matched_ecoinvent", "ecoinvent 3.9.1"),
        ]:
            if row.get(prefix + "_name"):
                targets.append(
                    Endpoint(
                        None,
                        row[prefix + "_name"],
                        version,
                        row.get(prefix + "_categories"),
                    )
                )
    elif artifact.adapter == Adapter.FLOWMAPPER:
        source = Endpoint(valid_identifier(row.get("bio3_code")))
        targets = [Endpoint(valid_identifier(row.get("ef31_code")))]
    elif artifact.adapter == Adapter.SEED:
        source = Endpoint(
            valid_identifier(row.get("source_code")),
            row.get("source_name"),
            row.get("source_db"),
            row.get("source_categories"),
        )
        targets = [
            Endpoint(
                valid_identifier(row.get("target_code")),
                row.get("target_name"),
                row.get("target_db"),
                row.get("target_categories"),
            )
        ]
        # An algorithm's match_type and confidence are not a SKOS assertion
        # or a quantity conversion. They remain in the complete original row.
    elif artifact.adapter == Adapter.SENTIER_BAFU:
        original_source, original_target = row["source"], row["target"]
        source = Endpoint(
            valid_identifier(original_source.get("code")),
            original_source.get("name"),
            artifact.source_list,
            original_source.get("context"),
            original_source.get("unit"),
        )
        targets = [
            Endpoint(
                valid_identifier(original_target.get("code")),
                original_target.get("name"),
                artifact.target_list,
                original_target.get("context"),
                original_target.get("unit"),
            )
        ]
        # The artifact's title states this source/target list pairing. Its
        # replace operation does not supply a scientific relation or multiplier.
    issues = [
        "historical-input-generation-unproven",
        "scientific-review-unreceived",
        "application-unreceived",
    ]
    if artifact.role == SourceRole.CROSS_VALIDATION:
        issues.append("cross-validation-only-not-identity-authority")
    if artifact.role == SourceRole.UNQUALIFIED:
        issues.append("source-role-unqualified")
    if not source.identifier:
        issues.append("source-identifier-missing")
    if not source.list_version:
        issues.append("source-version-unrecorded")
    if not targets or any(t.identifier is None for t in targets):
        issues.append("target-identifier-missing")
    if not source.context or any(not t.context for t in targets):
        issues.append("context-unrecorded")
    if not source.unit or any(not t.unit for t in targets):
        issues.append("quantity-units-unrecorded")
    if relation is None:
        issues.append("relation-unrecorded")
    if conversion in (None, ""):
        issues.append("conversion-unrecorded")
    if mapper is None:
        issues.append("mapper-unrecorded")
    if verifier is None:
        issues.append("verifier-unrecorded")
    if "__original_json_nonfinite_literal__" in encoded(row).decode():
        issues.append("original-nonfinite-literal-unresolved")
    if any(
        isinstance(v, str) and len(v) > 1 and v.startswith("=") for v in row.values()
    ):
        issues.append("formula-or-equals-text-needs-qualification")
    if source.unit and any(t.unit and source.unit != t.unit for t in targets):
        issues.append("quantity-scope-needs-review")
    ident = "source-row-" + sha(encoded([artifact.sha256, locator]))[:32]
    status = (
        Status.REFERENCE
        if reference
        else Status.UNRESOLVED
        if source.identifier
        else Status.QUARANTINED
    )
    return Assertion(
        ident,
        artifact.id,
        locator,
        sha(encoded(row)),
        source,
        targets,
        relation,
        conversion,
        "source-to-target; recorded assertion, applicability unqualified",
        mapper,
        verifier,
        stated_date,
        status,
        issues,
        row,
    )


def identifier_index(rows: list[Assertion]):
    """Scope keys to the stated source version and keep every competing row."""
    result = defaultdict(list)
    for row in rows:
        if row.status != Status.REFERENCE and valid_identifier(row.source.identifier):
            result[row.source.list_version, row.source.identifier].append(row)
    return dict(result)


def require_qualified(row: Assertion) -> None:
    """A captured assertion with unresolved provenance cannot be accepted."""
    # This custody model has no acceptance state or independent review receipt.
    # Clearing a list of issues cannot manufacture that missing evidence.
    raise ValueError(
        "Mapping evidence remains unresolved: "
        + ", ".join(row.issues or ["mapping acceptance record unreceived"])
    )


def verify_manifest(path: Path, root: Path) -> Manifest:
    manifest = TypeAdapter(Manifest).validate_json(path.read_bytes())
    if manifest.schema_version != 1 or manifest.inputs.schema_version != 1:
        raise ValueError("Unsupported mapping provenance version")
    if (
        manifest.scientific_signoff
        or manifest.consumer_adoption
        or manifest.inputs.scientific_signoff
    ):
        raise ValueError(
            "Source custody cannot establish scientific acceptance or adoption"
        )
    inputs_path = path.parent / "mapping-source-inputs.json"
    if sha(inputs_path.read_bytes()) != manifest.input_manifest_sha256:
        raise ValueError("Changed mapping input manifest")
    if TypeAdapter(Inputs).validate_json(inputs_path.read_bytes()) != manifest.inputs:
        raise ValueError("Mapping artifact membership differs")
    if len({a.id for a in manifest.inputs.artifacts}) != len(manifest.inputs.artifacts):
        raise ValueError("Duplicate mapping artifact identity")
    for artifact in manifest.inputs.artifacts:
        if (
            sha(
                _safe_path(
                    path.parent / "source-inputs", artifact.filename
                ).read_bytes()
            )
            != artifact.sha256
        ):
            raise ValueError(f"Changed original mapping input: {artifact.id}")
    for payload in (manifest.assertions, manifest.aliases):
        raw = _safe_path(path.parent, payload.filename).read_bytes()
        if sha(raw) != payload.sha256 or len(raw.splitlines()) != payload.rows:
            raise ValueError("Changed mapping trace payload or population")
    if set(manifest.case_sha256) != set(manifest.case_links):
        raise ValueError("Case trace identity pins differ from linked cases")
    if set(manifest.procedures) != PROCEDURE_PATHS:
        raise ValueError("Mapping verification procedures are incomplete")
    if manifest.runtime != runtime():
        raise ValueError("Mapping parser runtime changed")
    for name, digest in manifest.procedures.items():
        if sha(_safe_path(root, name).read_bytes()) != digest:
            raise ValueError("Mapping provenance procedure changed")
    return manifest


def manifest_path(register_path, register):
    document = next(
        (d for d in register.documents if d.id == "source-mapping-provenance"), None
    )
    return (
        _safe_path(register_path.parent / "sources", document.filename)
        if document
        else None
    )


def read_assertions(path: Path):
    for raw in path.read_bytes().splitlines():
        yield TypeAdapter(Assertion).validate_json(raw)


def counts(rows: list[Assertion]) -> dict[str, dict[str, int]]:
    return {
        "artifacts": dict(Counter(r.artifact_id for r in rows)),
        "states": dict(Counter(r.status.value for r in rows)),
        "issues": dict(Counter(i for r in rows for i in set(r.issues))),
    }


def assertions_from_inputs(inputs: Inputs, directory: Path) -> list[Assertion]:
    rows = [
        assertion(a, location, row)
        for a in inputs.artifacts
        if a.adapter not in {Adapter.REGISTRY, Adapter.HISTORICAL}
        for location, row in raw_rows(a, directory)
    ]
    if len({r.id for r in rows}) != len(rows):
        raise ValueError("Duplicate original source-row coordinate")
    candidates = identifier_index(rows)
    endpoint_adapter = TypeAdapter(list[Endpoint])
    competing = set()
    repeats = set()
    for group in candidates.values():
        # One identifier can legitimately occur in different contexts. Review
        # competition within the recorded context/unit, never collapse it.
        scopes = defaultdict(list)
        for row in group:
            scopes[encoded([row.source.context, row.source.unit])].append(row)
        for scope in scopes.values():
            by_outcome = defaultdict(list)
            for row in scope:
                key = encoded(
                    [
                        endpoint_adapter.dump_python(row.targets),
                        row.relation,
                        row.conversion,
                    ]
                )
                by_outcome[key].append(row.id)
            if len(by_outcome) > 1:
                competing.update(r.id for r in scope)
            for identical in by_outcome.values():
                if len(identical) > 1:
                    repeats.update(identical)
    pairs = defaultdict(list)
    for row in rows:
        if row.source.identifier:
            for target in row.targets:
                if target.identifier:
                    pairs[row.source.identifier, target.identifier].append(row)
    related = defaultdict(set)
    for group in pairs.values():
        for row in group:
            related[row.id].update(
                other.id for other in group if other.artifact_id != row.artifact_id
            )
    return [
        replace(
            row,
            issues=row.issues
            + (["competing-assertions-preserved"] if row.id in competing else [])
            + (["repeated-assertion-preserved"] if row.id in repeats else [])
            + (
                ["shared-identifiers-not-independent-evidence"]
                if related[row.id]
                else []
            ),
            dependencies=sorted(related[row.id]),
        )
        for row in rows
    ]


def aliases_from_inputs(inputs: Inputs, directory: Path, assertions: list[Assertion]):
    artifacts = [a for a in inputs.artifacts if a.adapter == Adapter.HISTORICAL]
    if len(artifacts) != 1:
        raise ValueError("Require exactly one historical mapping artifact")
    artifact = artifacts[0]
    raw = _safe_path(directory, artifact.filename).read_bytes()
    if sha(raw) != artifact.sha256:
        raise ValueError("Changed historical result")
    historical = loads_original(raw)
    original_aliases = historical["flows"]
    reverse = defaultdict(list)
    registry_refs = {}
    for registry in inputs.artifacts:
        if registry.adapter != Adapter.REGISTRY:
            continue
        if registry.namespace in registry_refs:
            raise ValueError("Duplicate historical registry namespace")
        refs = defaultdict(list)
        for locator, row in raw_rows(registry, directory):
            identifier = valid_identifier(row.get("code"))
            if identifier:
                refs[identifier].append(RowRef(registry.id, locator, sha(encoded(row))))
        registry_refs[registry.namespace] = refs
    for namespace, index in historical["index"].items():
        for code, alias in index.items():
            if alias not in original_aliases:
                raise ValueError("Historical index names an absent alias")
            reverse[alias].append((namespace, code))
    row_ids = defaultdict(set)
    for row in assertions:
        # A quarantined placeholder's apparent target must not become support
        # for a valid alias. Its original row remains in the assertion ledger.
        if row.status == Status.QUARANTINED or row.status == Status.REFERENCE:
            continue
        for code in [row.source.identifier, *(t.identifier for t in row.targets)]:
            if code:
                row_ids[code].add(row.id)
    for alias, row in original_aliases.items():
        members, candidates = [], set()
        issues = [
            "historical-result-unqualified",
            "source-versions-need-reconciliation",
            "scientific-review-unreceived",
            "application-unreceived",
        ]
        for namespace, code in reverse[alias]:
            if not valid_identifier(code):
                issues.append("historical-placeholder-identifier-invalid")
                continue
            members.extend(registry_refs.get(namespace, {}).get(code, []))
            candidates.update(row_ids[code])
            if namespace in registry_refs and code not in registry_refs[namespace]:
                issues.append("historical-member-definition-missing")
        if not members:
            issues.append("original-registry-membership-unresolved")
        # Matching identifiers provide reading links only. They cannot establish
        # the actual scorer inputs, versions, source independence or support.
        if candidates:
            issues.append("assertion-links-are-identifier-occurrences-only")
        locator = "/flows/" + alias.replace("~", "~0").replace("/", "~1")
        yield AliasTrace(
            alias,
            RowRef(artifact.id, locator, sha(encoded(row))),
            members,
            sorted(candidates),
            Status.UNRESOLVED,
            sorted(set(issues)),
        )


def verify_content(manifest: Manifest, directory: Path) -> None:
    """Reproduce every row and alias from the actual originals, no shortlist."""
    rows = assertions_from_inputs(manifest.inputs, directory / "source-inputs")
    identifiers = {}
    for payload, rebuilt, model in [
        (manifest.assertions, rows, Assertion),
        (
            manifest.aliases,
            aliases_from_inputs(manifest.inputs, directory / "source-inputs", rows),
            AliasTrace,
        ),
    ]:
        digest, total = hashlib.sha256(), 0
        adapter = TypeAdapter(model)
        ids = set()
        for row in rebuilt:
            digest.update(encoded(adapter.dump_python(row, mode="json")) + b"\n")
            ids.add(row.id)
            total += 1
        identifiers[model] = ids
        if digest.hexdigest() != payload.sha256 or total != payload.rows:
            raise ValueError("Mapping traces do not reproduce the original source rows")
    if counts(rows) != manifest.counts:
        raise ValueError("Source mapping statistics do not reproduce")
    for links in manifest.case_links.values():
        if (
            set(links) != {"assertions", "aliases"}
            or not set(links["assertions"]) <= identifiers[Assertion]
            or not set(links["aliases"]) <= identifiers[AliasTrace]
        ):
            raise ValueError("Case mapping trace names an absent original record")
