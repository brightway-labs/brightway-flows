"""A migration applied the way a consumer applies it, and checked.

`docs/using/outputs.md` tells a consumer how to apply the four files with
randonneur.  This does exactly that to the before release -- its substances,
flows, categories and factors as a consumer's tables would hold them, plus an
inventory with one exchange of every flow -- and compares what comes out with
the after release.  Every row must then be the after release's, and every
exchange must name a flow the after release publishes, except where
``unresolved.json`` says the migration left something as it was.

Nothing else checks that the files do what they say.  The diff can be right
and the file wrong -- a verb randonneur cannot apply to a node, a source that
names a key the consumer no longer holds by the time it is applied -- and the
only way to see that is to apply it.  `release-migrations` runs this on
every pair it writes.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from randonneur import Datapackage, MigrationConfig, migrate_edges, migrate_nodes

from brightway_flows.releases.diff import DeltaKind, ReleaseDiff
from brightway_flows.releases.randonneur_files import FILE_NAMES, migration_directory
from brightway_flows.releases.rulings import EntityKind
from brightway_flows.releases.snapshot import FACTOR_KEYS, ReleaseSnapshot, SnapshotFactor

#: What `outputs.md` tells a consumer to pass for a table of nodes.
NODE_VERBS = ["update", "delete", "create"]
#: And for an inventory's exchanges.
EDGE_VERBS = ["replace"]
#: How many identifiers a report lists per problem before it stops.
SHOWN = 10


@dataclass
class EntityReplay:
    """One table, migrated, against the after release's."""

    entity: EntityKind
    expected: int
    migrated: int
    #: Rows the after release publishes that the migrated table lacks.
    missing: list[str] = field(default_factory=list)
    #: Rows the migrated table holds that the after release does not publish.
    unexpected: list[str] = field(default_factory=list)
    #: Rows on both sides whose published fields disagree.
    differing: list[str] = field(default_factory=list)
    #: Keys the migrated table holds more than one row under.
    duplicated: list[str] = field(default_factory=list)
    #: Rows the files left as they were because the migration could not decide.
    left_unresolved: int = 0

    @property
    def ok(self) -> bool:
        return not (self.missing or self.unexpected or self.differing or self.duplicated)


@dataclass
class ReplayReport:
    """Every table, and the inventory."""

    entities: list[EntityReplay]
    edges: int = 0
    #: Exchanges left on a flow the after release does not publish, though the
    #: migration did not leave that flow unresolved.
    stranded_edges: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return all(entity.ok for entity in self.entities) and not self.stranded_edges

    def lines(self) -> list[str]:
        out = []
        for entity in self.entities:
            status = "ok" if entity.ok else "MISMATCH"
            out.append(
                f"{entity.entity.plural:28}{entity.migrated:>10} rows, "
                f"{entity.expected} expected  {status}"
                + (f"  ({entity.left_unresolved} left unresolved)" if entity.left_unresolved else "")
            )
            for name in ("missing", "unexpected", "differing", "duplicated"):
                found = getattr(entity, name)
                if found:
                    shown = ", ".join(found[:SHOWN]) + (" ..." if len(found) > SHOWN else "")
                    out.append(f"    {len(found)} {name}: {shown}")
        out.append(
            f"{'inventory exchanges':28}{self.edges:>10} edges "
            + ("ok" if not self.stranded_edges else f"MISMATCH: {len(self.stranded_edges)} stranded")
        )
        return out


def _flow_rows(snapshot: ReleaseSnapshot) -> list[dict[str, Any]]:
    return [
        {"identifier": identifier, **flow.published_fields()}
        for identifier, flow in sorted(snapshot.live_flows.items())
    ]


def _object_rows(snapshot: ReleaseSnapshot) -> list[dict[str, Any]]:
    return [
        {"flow_object_id": identifier, **obj.published_fields()}
        for identifier, obj in sorted(snapshot.objects_by_id.items())
    ]


def _category_rows(snapshot: ReleaseSnapshot) -> list[dict[str, Any]]:
    return [
        {"id": identifier, **category.published_fields()}
        for identifier, category in sorted(snapshot.categories_by_id.items())
    ]


def _factor_rows(snapshot: ReleaseSnapshot) -> list[dict[str, Any]]:
    return [
        {**dict(zip(FACTOR_KEYS, key)), "amount": factor.amount}
        for key, factor in sorted(snapshot.factors_by_key.items())
    ]


def _factor_key(row: dict[str, Any]) -> str:
    return SnapshotFactor.key_text(tuple(str(row.get(name) or "") for name in FACTOR_KEYS))


#: Per entity: the consumer's table of a release, and how a row is keyed.
TABLES: dict[EntityKind, tuple[Callable[[ReleaseSnapshot], list[dict[str, Any]]], Callable[[dict[str, Any]], str]]] = {
    EntityKind.FLOW_OBJECT: (_object_rows, lambda row: str(row["flow_object_id"])),
    EntityKind.ELEMENTARY_FLOW: (_flow_rows, lambda row: str(row["identifier"])),
    EntityKind.IMPACT_CATEGORY: (_category_rows, lambda row: str(row["id"])),
    EntityKind.FACTOR: (_factor_rows, _factor_key),
}


def _unresolved(diff: ReleaseDiff, entity: EntityKind) -> set[str]:
    return {
        delta.identifier
        for delta in diff.by_entity[entity]
        if delta.kind is DeltaKind.UNRESOLVED
    }


def _replay_table(
    entity: EntityKind, before: ReleaseSnapshot, after: ReleaseSnapshot,
    data: dict[str, Any], unresolved: set[str],
) -> EntityReplay:
    rows_of, key_of = TABLES[entity]
    table = rows_of(before)
    migrate_nodes(table, data, MigrationConfig(verbs=NODE_VERBS))
    counts = Counter(key_of(row) for row in table)
    migrated = {key_of(row): row for row in table}
    expected = {key_of(row): row for row in rows_of(after)}
    left = {key for key in migrated if key in unresolved}
    compared = {key: row for key, row in migrated.items() if key not in left}
    return EntityReplay(
        entity=entity,
        expected=len(expected),
        migrated=len(table),
        missing=sorted(set(expected) - set(compared)),
        unexpected=sorted(set(compared) - set(expected)),
        differing=sorted(
            key for key in set(expected) & set(compared) if expected[key] != compared[key]
        ),
        duplicated=sorted(key for key, n in counts.items() if n > 1),
        left_unresolved=len(left),
    )


def replay_migration(
    before: ReleaseSnapshot, after: ReleaseSnapshot, diff: ReleaseDiff, output_dir: Path
) -> ReplayReport:
    """Apply the files `write_migration_files` wrote for *diff* under
    *output_dir* to *before*, and compare the result with *after*."""
    directory = migration_directory(diff, output_dir)
    data = {
        entity: Datapackage.from_json(directory / name).data
        for entity, name in FILE_NAMES.items()
    }
    entities = [
        _replay_table(entity, before, after, data[entity], _unresolved(diff, entity))
        for entity in FILE_NAMES
    ]

    flows = sorted(before.live_flows)
    inventory = [{"name": "every flow once", "edges": [
        {"identifier": identifier, "amount": 1.0} for identifier in flows
    ]}]
    migrate_edges(inventory, data[EntityKind.ELEMENTARY_FLOW], MigrationConfig(verbs=EDGE_VERBS))
    # A flow the migration deleted or could not decide keeps its exchange; a
    # consumer is told so.  Anything else must now name a live flow.
    exempt = {
        delta.identifier
        for delta in diff.elementary_flows
        if delta.kind in (DeltaKind.UNRESOLVED, DeltaKind.DELETED)
    }
    live = after.live_flows
    stranded = sorted(
        original
        for original, edge in zip(flows, inventory[0]["edges"])
        if edge["identifier"] not in live and original not in exempt
    )
    return ReplayReport(entities=entities, edges=len(flows), stranded_edges=stranded)
