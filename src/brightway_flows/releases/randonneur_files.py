"""The migration between two releases, written in randonneur's format.

Four files, one per kind of thing a consumer's database holds -- substances,
flows, impact categories, characterisation factors -- each a randonneur
datapackage (https://github.com/brightway-lca/randonneur): a header naming
the two releases, a ``mapping`` saying where each field is read from in the
published artifacts, and the changes under the verbs ``create``, ``update``,
``replace`` and ``delete``.  ``disaggregate`` is never written: splitting a
consumer's amount across the flows a split produced is almost never what the
chemistry says, so a split is left unresolved for a curator instead.

**What a replaced identifier is written as depends on where it is held.**
randonneur applies ``replace`` to edges only; on a node it raises.  A flow is
an edge in an inventory and a node in a flow list, so a replaced flow is a
``replace`` (for the inventory) and a ``delete`` (for the list, where its
survivor is already held or arrives by ``create``); a replaced substance is
the same.  An impact category and a factor are only ever rows of a method
table, and the row itself has to survive -- it is the factor -- so a renamed
category or a factor whose flow or category moved is an ``update`` that
matches the old key and sets the new one.  Every source is therefore stated
in the before release's identifiers, and the files can be applied in any
order.

A fifth file, ``unresolved.json``, is not a migration.  It lists every
identifier the alignment could not decide, with the candidates and the
reason, and is the worklist for `release-migration-rulings.json`.

The files are written from `releases/diff.py`'s records, and
``randonneur.Datapackage`` validates each entry's fields against the mapping
as they are added, so a field this project publishes that the mapping does
not name cannot reach a file.  The whole datapackage is deterministic for
one pair of snapshots: ``created`` is the after release's own timestamp, and
every list is sorted.
"""

from __future__ import annotations

import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import orjson
from randonneur import Datapackage

from brightway_flows.releases.diff import Delta, DeltaKind, ReleaseDiff
from brightway_flows.releases.rulings import EntityKind
from brightway_flows.releases.snapshot import (
    FACTOR_KEYS,
    SnapshotElementaryFlow,
    SnapshotFactor,
    SnapshotFlowObject,
    SnapshotImpactCategory,
)
from brightway_flows.releases.version import LIST_NAME

HOMEPAGE = "https://github.com/brightway-labs/brightway-flows"
CONTRIBUTORS = [{"title": LIST_NAME, "roles": ["author"], "path": HOMEPAGE}]
#: randonneur's own default.  The repository declares no licence of its own
#: yet; when it does, this is the one place to say so.
LICENSES = [{
    "name": "CC-BY-4.0",
    "path": "https://creativecommons.org/licenses/by/4.0/",
    "title": "Creative Commons Attribution 4.0 International",
}]

#: This file's own format version, checked where it is read (rule 13).
UNRESOLVED_REPORT_SCHEMA_VERSION = 1

FILE_NAMES: dict[EntityKind, str] = {
    EntityKind.FLOW_OBJECT: "flow-objects.json",
    EntityKind.ELEMENTARY_FLOW: "elementary-flows.json",
    EntityKind.IMPACT_CATEGORY: "impact-categories.json",
    EntityKind.FACTOR: "characterization-factors.json",
}
UNRESOLVED_FILE_NAME = "unresolved.json"

#: The time every member of the archive is stamped with.  A member's own
#: modification time would make two archives of one migration differ, and the
#: files already carry the after release's timestamp as ``created``.
ARCHIVE_MEMBER_TIME = (1980, 1, 1, 0, 0, 0)


def _jsonpath(prefix: str, key: str) -> str:
    """``$.flows[*].unit``, or the bracket form for a key that is an IRI."""
    if all(ch.isalnum() or ch == "_" for ch in key):
        return f"{prefix}.{key}"
    return f"{prefix}['{key}']"


def flow_object_mapping() -> dict[str, Any]:
    """Where each substance field is read from: the `flow_objects` table."""
    columns = {
        "flow_object_id": "flow_objects.flow_object_id",
        "prefLabel": "flow_objects.pref_label_value",
        "altLabel": "flow_objects.alt_label_json",
        "classifications": "flow_objects.classifications_json",
        "properties": "flow_objects.properties_json",
        "references": "flow_objects.references_json",
        "origin_qualifier": "flow_objects.origin_qualifier",
        "parent_flow_object_id": "flow_objects.parent_flow_object_id",
        "parent_intervention_id": "flow_objects.parent_intervention_id",
    }
    labels = {
        key: columns.get(key, f"json_extract(flow_objects.flow_object_json, '$.\"{key}\"')")
        for key in SnapshotFlowObject.published_keys()
    }
    return {"expression language": "SQL", "labels": labels}


def elementary_flow_mapping() -> dict[str, Any]:
    """Where each flow field is read from: ``flows`` in the published export."""
    return {
        "expression language": "JSONPath",
        "labels": {
            key: _jsonpath("$.flows[*]", key) for key in SnapshotElementaryFlow.published_keys()
        },
    }


def impact_category_mapping() -> dict[str, Any]:
    """Where each category field is read from: ``impact_categories`` in the
    published factors file."""
    return {
        "expression language": "JSONPath",
        "labels": {
            key: _jsonpath("$.impact_categories[*]", key)
            for key in SnapshotImpactCategory.published_keys()
        },
    }


def factor_mapping() -> dict[str, Any]:
    """Where each factor field is read from: ``characterization_factors`` in
    the published factors file."""
    return {
        "expression language": "JSONPath",
        "labels": {
            key: _jsonpath("$.characterization_factors[*]", key)
            for key in (*FACTOR_KEYS, "amount")
        },
    }


MAPPINGS: dict[EntityKind, Any] = {
    EntityKind.FLOW_OBJECT: flow_object_mapping,
    EntityKind.ELEMENTARY_FLOW: elementary_flow_mapping,
    EntityKind.IMPACT_CATEGORY: impact_category_mapping,
    EntityKind.FACTOR: factor_mapping,
}
KEY_FIELDS: dict[EntityKind, str] = {
    EntityKind.FLOW_OBJECT: "flow_object_id",
    EntityKind.ELEMENTARY_FLOW: "identifier",
    EntityKind.IMPACT_CATEGORY: "id",
}
GRAPH_CONTEXTS: dict[EntityKind, list[str]] = {
    # A substance is a node.  A flow is a node in a flow list and an edge in
    # an inventory, and a `replace` is what an inventory applies.  A category
    # and a factor are rows of a method table: nodes.
    EntityKind.FLOW_OBJECT: ["nodes"],
    EntityKind.ELEMENTARY_FLOW: ["nodes", "edges"],
    EntityKind.IMPACT_CATEGORY: ["nodes"],
    EntityKind.FACTOR: ["nodes"],
}
#: The entities whose replaced rows are moved by an `update` rather than
#: replaced and deleted; see the module docstring.
_MOVED_BY_UPDATE = frozenset({EntityKind.IMPACT_CATEGORY, EntityKind.FACTOR})


def _factor_triple(delta: Delta) -> dict[str, str | None]:
    """The factor's key as the published file spells it: no place is ``null``.

    A source is matched by randonneur on the exact value of each field, so
    the ``""`` the snapshot keys on would match nothing in a table loaded
    from `lcia-factors.json.gz`.
    """
    category, flow, geography = delta.identifier.split("|", 2)
    return SnapshotFactor.published_triple((category, flow, geography))


def _source(entity: EntityKind, delta: Delta) -> dict[str, Any]:
    if entity is EntityKind.FACTOR:
        return _factor_triple(delta)
    return {KEY_FIELDS[entity]: delta.identifier}


def _create_target(entity: EntityKind, delta: Delta) -> dict[str, Any]:
    payload = dict(delta.after or {})
    if entity is EntityKind.FACTOR:
        return {
            **SnapshotFactor.published_triple(tuple(payload[key] for key in FACTOR_KEYS)),
            "amount": payload["amount"],
        }
    return {KEY_FIELDS[entity]: delta.identifier, **payload}


def entries(entity: EntityKind, deltas: list[Delta]) -> dict[str, list[dict[str, Any]]]:
    """The randonneur entries for one entity's deltas, by verb.

    An unresolved delta produces no entry: it is in the report instead.
    """
    out: dict[str, list[dict[str, Any]]] = {}

    def add(verb: str, entry: dict[str, Any]) -> None:
        out.setdefault(verb, []).append(entry)

    for delta in deltas:
        comment = delta.comment
        if delta.kind is DeltaKind.CREATED:
            add("create", {"target": _create_target(entity, delta), "comment": comment})
        elif delta.kind is DeltaKind.UPDATED:
            add("update", {
                "source": _source(entity, delta),
                "target": dict(delta.after or {}),
                "comment": comment,
            })
        elif delta.kind is DeltaKind.REPLACED and entity in _MOVED_BY_UPDATE:
            add("update", {
                "source": _source(entity, delta),
                "target": dict(delta.after or {}),
                "comment": comment,
            })
        elif delta.kind is DeltaKind.REPLACED:
            entry: dict[str, Any] = {
                "source": _source(entity, delta),
                "target": {KEY_FIELDS[entity]: delta.replaced_by},
                "comment": comment,
            }
            if delta.conversion_factor is not None:
                entry["conversion_factor"] = delta.conversion_factor
            add("replace", entry)
            add("delete", {
                "source": _source(entity, delta),
                "comment": f"replaced by {delta.replaced_by}: {comment}",
            })
        elif delta.kind is DeltaKind.DELETED:
            add("delete", {"source": _source(entity, delta), "comment": comment})
    return out


def _created(diff: ReleaseDiff) -> datetime:
    try:
        return datetime.fromisoformat(diff.after.timestamp)
    except ValueError:
        return datetime.now(timezone.utc)


def _description(diff: ReleaseDiff, entity: EntityKind) -> str:
    counts = diff.counts()
    tally = ", ".join(
        f"{counts[(entity.value, kind.value)]} {kind.value}" for kind in DeltaKind
    )
    return (
        f"Changes to the {entity.plural.replace('-', ' ')} of the Brightway flows list "
        f"between {diff.before.randonneur_id} (run {diff.before.run_id}, commit "
        f"{diff.before.revision[:12] or 'unknown'}) and {diff.after.randonneur_id} "
        f"(run {diff.after.run_id}, commit {diff.after.revision[:12] or 'unknown'}): "
        f"{tally}. Unresolved entries are in {UNRESOLVED_FILE_NAME}, not here. "
        "Every source is stated in the before release's identifiers. "
        + {
            EntityKind.FACTOR: (
                "A factor whose flow was replaced or whose category was renamed is "
                "an `update` that sets the new identifier. A factor stated for no "
                "place has `geography` null, as the factor file publishes it."
            ),
            EntityKind.IMPACT_CATEGORY: (
                "A renamed category is an `update` that sets its new id. A field in "
                "`update` carries its whole new value."
            ),
        }.get(
            entity,
            "A replaced identifier is a `replace` for edges and a `delete` for nodes. "
            "A field in `update` carries its whole new value; a nested value "
            "replaces the old one rather than merging into it.",
        )
    )


def build_datapackage(diff: ReleaseDiff, entity: EntityKind) -> Datapackage:
    """One entity's migration as a validated randonneur datapackage."""
    mapping = MAPPINGS[entity]()
    package = Datapackage(
        name=f"{LIST_NAME}-{entity.value}s-{diff.before.version}-to-{diff.after.version}",
        description=_description(diff, entity),
        contributors=CONTRIBUTORS,
        mapping_source=mapping,
        mapping_target=mapping,
        source_id=diff.before.randonneur_id,
        target_id=diff.after.randonneur_id,
        homepage=HOMEPAGE,
        created=_created(diff),
        version=diff.after.version,
        licenses=LICENSES,
        graph_context=GRAPH_CONTEXTS[entity],
    )
    for verb, rows in entries(entity, diff.by_entity[entity]).items():
        package.add_data(verb, rows)
    return package


def unresolved_report(diff: ReleaseDiff) -> dict[str, Any]:
    """Every unresolved delta, with the reasons tallied."""
    items = diff.unresolved
    reasons: dict[str, int] = {}
    for delta in items:
        reasons[delta.reason] = reasons.get(delta.reason, 0) + 1
    return {
        "schema_version": UNRESOLVED_REPORT_SCHEMA_VERSION,
        "from_version": diff.before.version,
        "to_version": diff.after.version,
        "source_id": diff.before.randonneur_id,
        "target_id": diff.after.randonneur_id,
        "description": (
            "Identifiers of the before release that the migration could not "
            "resolve. Each is answered by a ruling in release-migration-rulings.json "
            "naming from_version, to_version, the entity and the identifier."
        ),
        "counts": {
            "by_reason": dict(sorted(reasons.items())),
            "by_entity": {
                entity.value: sum(1 for d in items if d.entity is entity) for entity in EntityKind
            },
        },
        "items": [delta.to_dict() for delta in items],
    }


@dataclass(frozen=True)
class MigrationFiles:
    """Where the files went."""

    directory: Path
    flow_objects: Path
    elementary_flows: Path
    impact_categories: Path
    characterization_factors: Path
    unresolved: Path

    @property
    def migrations(self) -> tuple[Path, Path, Path, Path]:
        return (
            self.flow_objects, self.elementary_flows, self.impact_categories,
            self.characterization_factors,
        )

    @property
    def by_entity(self) -> dict[EntityKind, Path]:
        return {
            EntityKind.FLOW_OBJECT: self.flow_objects,
            EntityKind.ELEMENTARY_FLOW: self.elementary_flows,
            EntityKind.IMPACT_CATEGORY: self.impact_categories,
            EntityKind.FACTOR: self.characterization_factors,
        }


def migration_directory(diff: ReleaseDiff, output_dir: Path) -> Path:
    return output_dir / f"{diff.before.version}__{diff.after.version}"


def write_migration_files(diff: ReleaseDiff, output_dir: Path) -> MigrationFiles:
    """Write the four migrations and the unresolved report under *output_dir*.

    Every file is written even when it holds no entry: an empty ``update``
    list says something a missing file does not.
    """
    directory = migration_directory(diff, output_dir)
    directory.mkdir(parents=True, exist_ok=True)
    paths: dict[EntityKind, Path] = {}
    for entity, name in FILE_NAMES.items():
        package = build_datapackage(diff, entity)
        path = directory / name
        path.write_text(package.to_json(), encoding="utf-8")
        paths[entity] = path
    unresolved = directory / UNRESOLVED_FILE_NAME
    unresolved.write_bytes(orjson.dumps(unresolved_report(diff), option=orjson.OPT_INDENT_2))
    return MigrationFiles(
        directory=directory,
        flow_objects=paths[EntityKind.FLOW_OBJECT],
        elementary_flows=paths[EntityKind.ELEMENTARY_FLOW],
        impact_categories=paths[EntityKind.IMPACT_CATEGORY],
        characterization_factors=paths[EntityKind.FACTOR],
        unresolved=unresolved,
    )


def migration_archive_path(files: MigrationFiles) -> Path:
    """Where `write_migration_archive` puts the zip: beside the directory."""
    return files.directory.with_name(f"{files.directory.name}.zip")


def write_migration_archive(files: MigrationFiles) -> Path:
    """Zip the five files beside their directory, as ``<from>__<to>.zip``.

    One file to upload with the release rather than a folder.  The members sit
    under ``<from>__<to>/`` so the archive unpacks to the directory it was
    made from, and are written in a fixed order with a fixed time, so one
    migration always zips to the same bytes.
    """
    directory = files.directory
    archive = migration_archive_path(files)
    with zipfile.ZipFile(archive, "w") as bundle:
        for path in (*files.migrations, files.unresolved):
            member = zipfile.ZipInfo(f"{directory.name}/{path.name}", ARCHIVE_MEMBER_TIME)
            member.compress_type = zipfile.ZIP_DEFLATED
            bundle.writestr(member, path.read_bytes())
    return archive
