"""A release of the list, projected onto what a migration compares.

A build drops and recreates its flow tables, so nothing in a database says
what the release before it published.  The before side of a migration has to
be a separate file, and a 2 GB database is the wrong one: what a migration
compares is a few published fields on each substance, each flow and each
factor, plus the source rows that let one build's identifiers be matched to
another's.  That is what a snapshot holds, and it is a few megabytes gzipped.

Three things decide what is in it:

**Published fields only.**  A consumer's database holds what
`harmonised-flows-simple.json.gz` and the `flow_objects` table carry -- a
label, its synonyms, the registry numbers, a context, a unit, the semantic
properties, the references -- and a migration describes changes to those.
Provenance, `source_refs` and pipeline bookkeeping never reach a consumer and
never appear here.  A flow is projected by the same function the export uses,
so the two cannot disagree about what a field's published shape is.

**Deprecated flows are kept.**  The export drops them from ``flows``; the
before side of a migration needs their substance, unit and context to say what
became of them, so the snapshot reads the payloads directly and marks them.
The redirects the export publishes are kept beside them, terminal and
classified, because they are the first thing the alignment asks.

**The source rows are the alignment key.**  A flow's identifier can move
between two builds -- a minted identifier is a function of the substance and
the compartment, and a substance regrouped by a corrected CAS number takes a
new one -- but the vendor row that reached it does not.  ``(list, version,
source uuid)`` is the same key `tools/compare_merge_outcomes.py` aligns on,
version included (#317).
"""

from __future__ import annotations

import gzip
import sqlite3
from collections import defaultdict
from contextlib import closing
from dataclasses import dataclass, field, fields
from datetime import datetime, timezone
from functools import cached_property
from pathlib import Path
from typing import Any, ClassVar

import orjson

from brightway_flows.domain.labels import flow_label_value
from brightway_flows.domain.lcia.records import LCIA_SCHEMA_VERSION
from brightway_flows.domain.records import SerialisableRecord
from brightway_flows.domain.schema import SCHEMA_VERSION, SchemaVersionError
from brightway_flows.domain.simple_flow import FlowRedirect, SimpleFlow
from brightway_flows.domain.vocabulary import (
    RO_HAS_ROLE_IRI,
    SKOS_DEFINITION_IRI,
    SKOS_IN_SCHEME_IRI,
)
from brightway_flows.filesystem import RELEASES_DIR
from brightway_flows.merge.store import MERGE_SCHEMA_VERSION
from brightway_flows.pipeline.exporting import (
    export_alt_labels,
    export_classifications,
    export_definitions,
    export_properties,
    export_references,
    export_roles,
    simple_flow_from_payload,
)
from brightway_flows.pipeline.redirects import build_redirects, is_deprecated
from brightway_flows.pipeline.sqlite import (
    read_published_flow_payloads,
    read_source_contexts,
)
from brightway_flows.releases.version import ReleaseVersion, release_version

#: This file's own format version, checked where it is read (rule 13).
RELEASE_SNAPSHOT_SCHEMA_VERSION = 1

#: The published-flow keys a migration never states: both are functions of
#: the identifier, and a consumer's database keys on the identifier.
_DERIVED_FLOW_KEYS = frozenset({"@id", SKOS_IN_SCHEME_IRI})


class SnapshotError(ValueError):
    """A snapshot file cannot be read, or a database cannot be snapshotted."""


@dataclass
class ReleaseStamp(SerialisableRecord):
    """Which build a snapshot came from, and what it was called."""

    version: str
    development: bool
    run_id: str
    revision: str
    revision_dirty: bool
    timestamp: str
    merge_run_id: str = ""
    merge_finished_at: str = ""
    merged_lists: list[str] = field(default_factory=list)
    characterise_run_id: str = ""
    flow_schema_version: int = SCHEMA_VERSION
    lcia_schema_version: int = LCIA_SCHEMA_VERSION
    merge_schema_version: int = MERGE_SCHEMA_VERSION
    created: str = ""

    @property
    def release(self) -> ReleaseVersion:
        return ReleaseVersion(self.version, development=self.development)

    @property
    def randonneur_id(self) -> str:
        return self.release.randonneur_id


@dataclass
class SnapshotFlowObject(SerialisableRecord):
    """A substance as the `flow_objects` table publishes it.

    CAS and EC numbers are inside ``classifications``, keyed by registry IRI,
    which is where the table reads them from; a corrected number is one
    change to that field, not two.
    """

    flow_object_id: str
    prefLabel: str = ""
    altLabel: list[str] = field(default_factory=list)
    classifications: dict[str, list[str]] = field(default_factory=dict)
    properties: dict[str, Any] = field(default_factory=dict)
    references: list[str] = field(default_factory=list)
    definition: list[str] = field(default_factory=list)
    types: list[str] = field(default_factory=list)
    roles: list[dict[str, str]] | None = None
    origin_qualifier: str | None = None
    parent_flow_object_id: str | None = None
    parent_intervention_id: str | None = None

    _ALIASES: ClassVar[dict[str, str]] = {"types": "@type", "roles": RO_HAS_ROLE_IRI}
    _OMIT_IF_NONE: ClassVar[frozenset[str]] = frozenset({
        "roles", "origin_qualifier", "parent_flow_object_id", "parent_intervention_id",
    })

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> SnapshotFlowObject:
        """Project a stored `FlowObject.to_dict()` payload."""
        raw_types = payload.get("@type")
        if isinstance(raw_types, str):
            raw_types = [raw_types]
        return cls(
            flow_object_id=str(payload.get("flow_object_id") or ""),
            prefLabel=flow_label_value(payload),
            altLabel=export_alt_labels(payload.get("altLabel")),
            classifications=export_classifications(payload.get("classifications")),
            properties=export_properties(payload.get("properties")),
            references=export_references(payload.get("references")),
            definition=export_definitions(payload.get(SKOS_DEFINITION_IRI)),
            types=[str(x) for x in raw_types if isinstance(x, str) and x.strip()]
            if isinstance(raw_types, list) else [],
            roles=export_roles(payload.get(RO_HAS_ROLE_IRI)),
            origin_qualifier=_optional_text(payload.get("origin_qualifier")),
            parent_flow_object_id=_optional_text(payload.get("parent_flow_object_id")),
            parent_intervention_id=_optional_text(payload.get("parent_intervention_id")),
        )

    @classmethod
    def published_keys(cls) -> tuple[str, ...]:
        """Every serialised key, identifier first."""
        return tuple(cls._ALIASES.get(f.name, f.name) for f in fields(cls))

    def published_fields(self) -> dict[str, Any]:
        """What a consumer's table holds for this substance, less its key."""
        out = self.to_dict()
        out.pop("flow_object_id", None)
        return out


def _optional_text(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


@dataclass
class SnapshotElementaryFlow(SimpleFlow):
    """A flow as the export publishes it, plus what a migration needs to know.

    A `SimpleFlow` with four fields the export does not carry: which substance
    the flow is an occurrence of, and -- for a flow the export dropped --
    that it is deprecated and where its redirect points.
    """

    flow_object_id: str = ""
    is_deprecated: bool = False
    replaced_by_identifier: str | None = None
    deprecation_reason: str = ""

    _OMIT_IF_NONE: ClassVar[frozenset[str]] = SimpleFlow._OMIT_IF_NONE | frozenset({
        "replaced_by_identifier",
    })
    #: The bookkeeping this record adds to the published one.
    _BOOKKEEPING: ClassVar[frozenset[str]] = frozenset({
        "flow_object_id", "is_deprecated", "replaced_by_identifier", "deprecation_reason",
    })

    @classmethod
    def from_simple(
        cls, simple: SimpleFlow, *, flow_object_id: str, deprecated: bool = False,
        replaced_by: str | None = None, reason: str = "",
    ) -> SnapshotElementaryFlow:
        return cls(
            **{f.name: getattr(simple, f.name) for f in fields(SimpleFlow)},
            flow_object_id=flow_object_id,
            is_deprecated=deprecated,
            replaced_by_identifier=replaced_by,
            deprecation_reason=reason,
        )

    @classmethod
    def published_keys(cls) -> tuple[str, ...]:
        """The serialised keys a migration may state, identifier first."""
        return tuple(
            cls._ALIASES.get(f.name, f.name)
            for f in fields(cls)
            if f.name not in cls._BOOKKEEPING
            and cls._ALIASES.get(f.name, f.name) not in _DERIVED_FLOW_KEYS
        )

    def published_fields(self) -> dict[str, Any]:
        """What a consumer's database holds for this flow, less its identifier."""
        keep = set(self.published_keys()) - {"identifier"}
        return {key: value for key, value in self.to_dict().items() if key in keep}


@dataclass
class SnapshotRedirect(SerialisableRecord):
    """One published redirect: a deprecated identifier, its survivor, and why.

    ``reason`` is the slug of the export's ``deprecationReason`` IRI --
    ``identity-merge``, ``identifier-scheme-change``, ``context-collapse``,
    ``unclassified`` or ``source-row-withdrawn`` -- because the alignment
    branches on it, and a consumer is told to.
    """

    identifier: str
    reason: str
    replaced_by_identifier: str | None = None

    _OMIT_IF_NONE: ClassVar[frozenset[str]] = frozenset({"replaced_by_identifier"})

    @classmethod
    def from_redirect(cls, redirect: FlowRedirect) -> SnapshotRedirect:
        iri = str(redirect.deprecation_reason.get("@id") or "")
        return cls(
            identifier=redirect.identifier,
            reason=iri.rsplit("/", 1)[-1] if iri else "",
            replaced_by_identifier=redirect.replaced_by_identifier,
        )


@dataclass
class SnapshotFactor(SerialisableRecord):
    """One characterisation factor, by the triple that identifies it.

    ``method``, ``category`` and ``implemented_by`` are for a comment and the
    unresolved report; a factor is matched on the triple alone, as the
    published file and the table both key it.
    """

    impact_category_id: str
    elementary_flow_uuid: str
    geography: str
    amount: float
    method: str = ""
    category: str = ""
    implemented_by: str = ""

    @property
    def key(self) -> tuple[str, str, str]:
        return (self.impact_category_id, self.elementary_flow_uuid, self.geography)

    @staticmethod
    def key_text(key: tuple[str, str, str]) -> str:
        return "|".join(key)


@dataclass
class SnapshotSourceRow(SerialisableRecord):
    """One vendor row, and the flow it reached in this build."""

    list_name: str
    list_version: str
    source_flow_uuid: str
    elementary_flow_uuid: str

    @property
    def key(self) -> tuple[str, str, str]:
        return (self.list_name, self.list_version, self.source_flow_uuid)


@dataclass
class ReleaseSnapshot:
    """Root object of ``<version>.json.gz``: one release, as a migration sees it."""

    schema_version: int
    stamp: ReleaseStamp
    flow_objects: list[SnapshotFlowObject] = field(default_factory=list)
    elementary_flows: list[SnapshotElementaryFlow] = field(default_factory=list)
    redirects: list[SnapshotRedirect] = field(default_factory=list)
    characterization_factors: list[SnapshotFactor] = field(default_factory=list)
    source_rows: list[SnapshotSourceRow] = field(default_factory=list)

    _COLLECTIONS: ClassVar[dict[str, type]] = {
        "flow_objects": SnapshotFlowObject,
        "elementary_flows": SnapshotElementaryFlow,
        "redirects": SnapshotRedirect,
        "characterization_factors": SnapshotFactor,
        "source_rows": SnapshotSourceRow,
    }

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "stamp": self.stamp.to_dict(),
            **{
                name: [row.to_dict() for row in getattr(self, name)]
                for name in self._COLLECTIONS
            },
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any], *, source: str = "snapshot") -> ReleaseSnapshot:
        if not isinstance(payload, dict):
            raise SnapshotError(f"{source}: expected an object")
        version = payload.get("schema_version")
        if version != RELEASE_SNAPSHOT_SCHEMA_VERSION:
            raise SchemaVersionError(
                f"{source}: schema_version {version!r} is not supported; this "
                f"version of brightway-flows reads {RELEASE_SNAPSHOT_SCHEMA_VERSION}"
            )
        try:
            return cls(
                schema_version=version,
                stamp=ReleaseStamp.from_dict(payload["stamp"]),
                **{
                    name: [record_cls.from_dict(row) for row in payload.get(name, [])]
                    for name, record_cls in cls._COLLECTIONS.items()
                },
            )
        except (KeyError, TypeError) as error:
            raise SnapshotError(f"{source}: {error}") from error

    # -- indexes, built once per snapshot -----------------------------------

    @cached_property
    def flows_by_identifier(self) -> dict[str, SnapshotElementaryFlow]:
        return {flow.identifier: flow for flow in self.elementary_flows}

    @cached_property
    def live_flows(self) -> dict[str, SnapshotElementaryFlow]:
        """The flows a consumer holds: every non-deprecated one."""
        return {
            flow.identifier: flow for flow in self.elementary_flows if not flow.is_deprecated
        }

    @cached_property
    def objects_by_id(self) -> dict[str, SnapshotFlowObject]:
        return {obj.flow_object_id: obj for obj in self.flow_objects}

    @cached_property
    def redirects_by_identifier(self) -> dict[str, SnapshotRedirect]:
        return {row.identifier: row for row in self.redirects}

    @cached_property
    def factors_by_key(self) -> dict[tuple[str, str, str], SnapshotFactor]:
        return {factor.key: factor for factor in self.characterization_factors}

    @cached_property
    def rows_by_key(self) -> dict[tuple[str, str, str], set[str]]:
        """Which flows each vendor row reached.  Usually one; a deduplicated
        pair shares its base-list rows, so it can be two."""
        out: dict[tuple[str, str, str], set[str]] = defaultdict(set)
        for row in self.source_rows:
            out[row.key].add(row.elementary_flow_uuid)
        return dict(out)

    @cached_property
    def rows_by_flow(self) -> dict[str, set[tuple[str, str, str]]]:
        out: dict[str, set[tuple[str, str, str]]] = defaultdict(set)
        for row in self.source_rows:
            out[row.elementary_flow_uuid].add(row.key)
        return dict(out)

    @cached_property
    def source_lists(self) -> frozenset[tuple[str, str]]:
        """Every ``(list, version)`` a source row names."""
        return frozenset((row.list_name, row.list_version) for row in self.source_rows)

    @cached_property
    def live_flows_by_object(self) -> dict[str, list[SnapshotElementaryFlow]]:
        out: dict[str, list[SnapshotElementaryFlow]] = defaultdict(list)
        for flow in self.live_flows.values():
            out[flow.flow_object_id].append(flow)
        return dict(out)


# -- reading a build --------------------------------------------------------


def _table_exists(connection: sqlite3.Connection, name: str) -> bool:
    return connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type IN ('table', 'view') AND name = ?", (name,)
    ).fetchone() is not None


def _columns(connection: sqlite3.Connection, table: str) -> set[str]:
    return {row[1] for row in connection.execute(f"PRAGMA table_info({table})")}


def read_stamp(db_path: Path, *, version: ReleaseVersion | None = None) -> ReleaseStamp:
    """Which build this is, from the run tables, named as a release.

    *version* overrides the name git would give it -- for a fixture, or for a
    build made from an exported tree.  Without it the stamped revision is
    described (see :func:`release_version`), and a modified tree is refused.
    """
    with closing(sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)) as connection:
        if not _table_exists(connection, "pipeline_runs"):
            raise SnapshotError(f"{db_path}: no `pipeline_runs` table; is this a build?")
        present = _columns(connection, "pipeline_runs")
        wanted = ["run_id", "timestamp", "git_commit", "git_dirty"]
        columns = [name for name in wanted if name in present]
        run = connection.execute(
            f"SELECT {', '.join(columns)} FROM pipeline_runs ORDER BY timestamp DESC LIMIT 1"
        ).fetchone()
        if run is None:
            raise SnapshotError(f"{db_path}: no row in `pipeline_runs`, so nothing names the build")
        row = dict(zip(columns, run))
        revision = str(row.get("git_commit") or "")
        dirty = bool(row.get("git_dirty") or 0)

        merge_run_id, merge_finished_at, merged_lists = "", "", []
        if _table_exists(connection, "merge_runs") and "finished_at" in _columns(connection, "merge_runs"):
            merge = connection.execute(
                "SELECT run_id, finished_at FROM merge_runs ORDER BY finished_at DESC LIMIT 1"
            ).fetchone()
            if merge:
                merge_run_id, merge_finished_at = str(merge[0] or ""), str(merge[1] or "")
                if _table_exists(connection, "merge_run_inputs"):
                    order = "sequence" if "sequence" in _columns(connection, "merge_run_inputs") else "rowid"
                    merged_lists = [
                        f"{name}-{list_version}"
                        for name, list_version in connection.execute(
                            "SELECT list_name, list_version FROM merge_run_inputs "
                            f"WHERE run_id = ? ORDER BY {order}",
                            (merge_run_id,),
                        )
                    ]
        characterise_run_id = ""
        if _table_exists(connection, "lcia_runs"):
            lcia = connection.execute(
                "SELECT run_id FROM lcia_runs WHERE finished_at IS NOT NULL "
                "ORDER BY started_at DESC LIMIT 1"
            ).fetchone()
            characterise_run_id = str(lcia[0]) if lcia else ""

    named = version or release_version(revision, dirty=dirty)
    return ReleaseStamp(
        version=named.version,
        development=named.development,
        run_id=str(row.get("run_id") or ""),
        revision=revision,
        revision_dirty=dirty,
        timestamp=str(row.get("timestamp") or ""),
        merge_run_id=merge_run_id,
        merge_finished_at=merge_finished_at,
        merged_lists=merged_lists,
        characterise_run_id=characterise_run_id,
        created=datetime.now(timezone.utc).isoformat(),
    )


def _read_flow_objects(connection: sqlite3.Connection) -> list[SnapshotFlowObject]:
    rows = connection.execute(
        "SELECT flow_object_id, flow_object_json FROM flow_objects ORDER BY flow_object_id"
    )
    out: list[SnapshotFlowObject] = []
    for object_id, payload_json in rows:
        payload = orjson.loads(payload_json) if payload_json else {}
        payload.setdefault("flow_object_id", object_id)
        out.append(SnapshotFlowObject.from_payload(payload))
    return out


def _read_factors(connection: sqlite3.Connection) -> list[SnapshotFactor]:
    if not _table_exists(connection, "lcia_characterization_factors"):
        return []
    rows = connection.execute(
        "SELECT f.impact_category_id, f.elementary_flow_uuid, f.geography, f.amount, "
        "m.name, c.name, c.implemented_by "
        "FROM lcia_characterization_factors f "
        "JOIN lcia_impact_categories c ON c.id = f.impact_category_id "
        "JOIN lcia_methods m ON m.id = c.method_id "
        "ORDER BY f.impact_category_id, f.elementary_flow_uuid, f.geography"
    )
    return [
        SnapshotFactor(
            impact_category_id=str(category_id),
            elementary_flow_uuid=str(flow_uuid),
            geography=str(geography or ""),
            amount=float(amount),
            method=str(method or ""),
            category=str(category or ""),
            implemented_by=str(implemented_by or ""),
        )
        for category_id, flow_uuid, geography, amount, method, category, implemented_by in rows
    ]


def _read_source_rows(connection: sqlite3.Connection) -> list[SnapshotSourceRow]:
    rows = connection.execute(
        "SELECT list_name, list_version, source_flow_uuid, elementary_flow_uuid "
        "FROM elementary_flow_sources "
        "ORDER BY list_name, list_version, source_flow_uuid, elementary_flow_uuid"
    )
    return [
        SnapshotSourceRow(
            list_name=str(list_name or ""),
            list_version=str(list_version or ""),
            source_flow_uuid=str(source_uuid or ""),
            elementary_flow_uuid=str(flow_uuid or ""),
        )
        for list_name, list_version, source_uuid, flow_uuid in rows
    ]


def build_snapshot(db_path: Path, *, version: ReleaseVersion | None = None) -> ReleaseSnapshot:
    """Project one build onto a release snapshot.

    Reads only.  The flows come through the export's own projection, deprecated
    ones included, and the redirects through the export's own builder -- so the
    snapshot says exactly what the published artifact says, plus what the
    artifact leaves out.
    """
    stamp = read_stamp(db_path, version=version)
    payloads = read_published_flow_payloads(db_path)
    redirects, _counts = build_redirects(payloads, read_source_contexts(db_path))
    by_identifier = {row.identifier: SnapshotRedirect.from_redirect(row) for row in redirects}

    flows: list[SnapshotElementaryFlow] = []
    for payload in payloads:
        simple = simple_flow_from_payload(payload)
        if simple is None:
            continue
        deprecated = is_deprecated(payload)
        redirect = by_identifier.get(simple.identifier)
        flows.append(SnapshotElementaryFlow.from_simple(
            simple,
            flow_object_id=str(payload.get("flow_object_id") or ""),
            deprecated=deprecated,
            replaced_by=redirect.replaced_by_identifier if redirect else None,
            reason=redirect.reason if redirect else "",
        ))
    flows.sort(key=lambda flow: flow.identifier)

    with closing(sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)) as connection:
        objects = _read_flow_objects(connection)
        factors = _read_factors(connection)
        source_rows = _read_source_rows(connection)

    return ReleaseSnapshot(
        schema_version=RELEASE_SNAPSHOT_SCHEMA_VERSION,
        stamp=stamp,
        flow_objects=objects,
        elementary_flows=flows,
        redirects=sorted(by_identifier.values(), key=lambda row: row.identifier),
        characterization_factors=factors,
        source_rows=source_rows,
    )


# -- files ---------------------------------------------------------------------


def snapshot_path(version: str, directory: Path | None = None) -> Path:
    """Where a release's snapshot lives: ``<releases>/<version>.json.gz``."""
    return (RELEASES_DIR if directory is None else directory) / f"{version}.json.gz"


def write_snapshot(snapshot: ReleaseSnapshot, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wb") as handle:
        handle.write(orjson.dumps(snapshot.to_dict()))
    return path


def load_snapshot(path: Path) -> ReleaseSnapshot:
    """Read a snapshot, refusing one this code cannot read."""
    try:
        raw = path.read_bytes()
    except OSError as error:
        raise SnapshotError(f"{path}: {error}") from error
    if raw[:2] == b"\x1f\x8b":
        raw = gzip.decompress(raw)
    try:
        payload = orjson.loads(raw)
    except orjson.JSONDecodeError as error:
        raise SnapshotError(f"{path}: {error}") from error
    return ReleaseSnapshot.from_dict(payload, source=str(path))
