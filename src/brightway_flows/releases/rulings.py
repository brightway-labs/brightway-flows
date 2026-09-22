"""A curator's answer for an identifier a migration could not resolve.

`release-migrations` works out where most identifiers went from the after
side's own redirects and from the source rows both builds share.  What it
will not guess is a *split* -- a flow whose source rows now land on several
flows -- a unit that changed, or a redirect the export itself tells consumers
to refuse.  Those are written to ``unresolved.json`` and a consumer applying
the migration sees no change for them until somebody has decided.

This file is where that decision is written down.  A ruling names the pair of
releases it is about and the identifier, and says either which flow the old
one is now (``replace``, with a conversion factor where the unit moved) or
that nothing is (``delete``).  It applies to that pair only: the next
release's migration asks its own questions.

A ruling that names an identifier the pair did **not** leave unresolved is
refused, not skipped.  It is stale -- the alignment now answers the question
itself, or the identifier is not in the before side at all -- and a ruling
that silently does nothing is the failure every decisions file here is
written to avoid.
"""

from __future__ import annotations

import functools
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

import orjson

from brightway_flows.filesystem import PACKAGE_DATA_DIR

#: This file's own format version, checked where it is read (rule 13).
RULINGS_SCHEMA_VERSION = 1
RULINGS_FILEPATH = PACKAGE_DATA_DIR / "release-migration-rulings.json"


class MigrationRulingError(ValueError):
    """The rulings file is malformed, or a ruling answers no open question."""


class EntityKind(StrEnum):
    """What a migration entry is about."""

    FLOW_OBJECT = "flow-object"
    ELEMENTARY_FLOW = "elementary-flow"
    FACTOR = "characterization-factor"


class RulingVerb(StrEnum):
    """What a ruling says became of the identifier."""

    REPLACE = "replace"
    DELETE = "delete"


@dataclass(frozen=True)
class MigrationRuling:
    """One curated answer, for one identifier, between one pair of releases."""

    from_version: str
    to_version: str
    entity: EntityKind
    identifier: str
    verb: RulingVerb
    replaced_by: str | None = None
    conversion_factor: float | None = None
    comment: str = ""

    def applies_to(self, from_version: str, to_version: str) -> bool:
        return self.from_version == from_version and self.to_version == to_version


def _ruling(row: Any, *, index: int) -> MigrationRuling:
    if not isinstance(row, dict):
        raise MigrationRulingError(f"ruling {index}: expected an object, got {type(row).__name__}")
    try:
        entity = EntityKind(str(row["entity"]))
        verb = RulingVerb(str(row["verb"]))
        ruling = MigrationRuling(
            from_version=str(row["from_version"]),
            to_version=str(row["to_version"]),
            entity=entity,
            identifier=str(row["identifier"]),
            verb=verb,
            replaced_by=(
                str(row["replaced_by"]) if row.get("replaced_by") is not None else None
            ),
            conversion_factor=(
                float(row["conversion_factor"])
                if row.get("conversion_factor") is not None
                else None
            ),
            comment=str(row.get("comment") or ""),
        )
    except (KeyError, ValueError, TypeError) as error:
        raise MigrationRulingError(f"ruling {index}: {error}") from error
    if not ruling.identifier or not ruling.from_version or not ruling.to_version:
        raise MigrationRulingError(f"ruling {index}: identifier and both versions are required")
    if ruling.verb is RulingVerb.REPLACE and not ruling.replaced_by:
        raise MigrationRulingError(f"ruling {index}: a `replace` ruling names `replaced_by`")
    if ruling.verb is RulingVerb.DELETE and ruling.replaced_by:
        raise MigrationRulingError(f"ruling {index}: a `delete` ruling names no `replaced_by`")
    if not ruling.comment:
        raise MigrationRulingError(f"ruling {index}: say why, in `comment`")
    return ruling


def read_release_migration_rulings(path: Path) -> tuple[MigrationRuling, ...]:
    """Read a rulings file, refusing a malformed one.

    Path-injectable for a test, and so deliberately uncached (rule 13).
    """
    try:
        payload = orjson.loads(path.read_bytes())
    except (OSError, orjson.JSONDecodeError) as error:
        raise MigrationRulingError(f"{path}: {error}") from error
    if not isinstance(payload, dict) or payload.get("schema_version") != RULINGS_SCHEMA_VERSION:
        raise MigrationRulingError(
            f"{path}: expected schema_version {RULINGS_SCHEMA_VERSION}, got "
            f"{payload.get('schema_version') if isinstance(payload, dict) else payload!r}"
        )
    rows = payload.get("rulings")
    if not isinstance(rows, list):
        raise MigrationRulingError(f"{path}: `rulings` must be a list")
    rulings = tuple(_ruling(row, index=index) for index, row in enumerate(rows))
    seen: set[tuple[str, str, EntityKind, str]] = set()
    for ruling in rulings:
        key = (ruling.from_version, ruling.to_version, ruling.entity, ruling.identifier)
        if key in seen:
            raise MigrationRulingError(
                f"{path}: {ruling.identifier} is ruled twice between "
                f"{ruling.from_version} and {ruling.to_version}"
            )
        seen.add(key)
    return rulings


@functools.cache
def load_release_migration_rulings() -> tuple[MigrationRuling, ...]:
    """Every ruling in the bundled file.  Cached: the path is fixed."""
    return read_release_migration_rulings(RULINGS_FILEPATH)


def rulings_for(
    rulings: tuple[MigrationRuling, ...], from_version: str, to_version: str
) -> tuple[MigrationRuling, ...]:
    """The rulings about one pair of releases."""
    return tuple(r for r in rulings if r.applies_to(from_version, to_version))
