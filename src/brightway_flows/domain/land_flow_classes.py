"""Which land class each source flow is, looked up rather than parsed.

`domain/land_use.py` is the value type and `domain/land_use_anchors.py` says
what each of its axis values is anchored to.  This is the third piece: the
curated assignment of a source list's flow to one of those values, one row per
`(source, uuid)`.  See `plans/land-class-taxonomy.md` §3.8.

**The layering does a lookup here and never reads a name.**  It could split a
flow name on commas and recognise tokens -- `tools/land_class_parser.py` does
exactly that, and gets 152 of 153 strings right -- and that is precisely what
this file exists to prevent.  A parser inside the build would make every one of
those readings a silent rule: `heterogeneous, agricultural` would become
`agriculture, mosaic` because a token matched, with no curator's name on the
decision and nothing to review when it was wrong.  It is the same discipline
`domain/materials.py` follows for water, where no algorithm reads `Water, salt,
sole` and knows it is brine.

Keyed on `(source, uuid)` and not on the uuid alone, for the reason
`material_by_source_flow` gives: the lists are independent vocabularies that
happen to share a uuid format, and one list naming a flow says nothing about
another's flow of the same name.

**One flow, one land class.**  Two rows for one pair would be two curated
statements arbitrated by file order, which is the collapse the whole taxonomy
exists to undo, so it raises rather than picking.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import Any

import orjson

from brightway_flows.domain.land_use import LandUse, LandUseError
from brightway_flows.filesystem import PACKAGE_DATA_DIR

#: The on-disk format of `land-flow-classes.json`, and of nothing else.  Not
#: the version of the list this project publishes, which is
#: `domain.schema.SCHEMA_VERSION`.
DECISIONS_SCHEMA_VERSION = 1

LAND_FLOW_CLASSES_FILEPATH = PACKAGE_DATA_DIR / "land-flow-classes.json"

#: The fields every row must carry a value for.  `location` and `original_name`
#: are absent from most rows and are not here: they record that #290 split a
#: place off a name, and a row for a name with no place in it has nothing to
#: say about that.
_REQUIRED = ("source", "source_uuid", "source_name", "key", "land_use", "comment")


class LandFlowClassError(ValueError):
    """A `land-flow-classes.json` row that cannot be read as one.

    Raised rather than skipped, for the reason every decisions file in this
    project raises: a row that is silently ignored is a curator's decision that
    looks applied and is not.
    """


@dataclass(frozen=True)
class LandFlowClass:
    """One source flow's land class, and what the vendor shipped it as.

    *land_use* is the curated part.  Everything else is the vendor's, taken
    mechanically from the shipped file by `tools/build_land_flow_classes.py`, so
    a reviewer checking a row is checking one field against four they can trust.

    *original_name* and *location* are set only where a place was split off the
    name (#290).  The Swiss row and the unregionalised row stay two flows
    sharing one land class -- `location` is part of #290's identity seed -- and
    the pair is recorded here so the audit trail shows what the vendor shipped
    rather than what this project reads.
    """

    source: str
    source_uuid: str
    source_name: str
    land_use: LandUse
    comment: str
    source_context: tuple[str, ...] = ()
    unit: str = ""
    original_name: str = ""
    location: str = ""

    @property
    def key(self) -> str:
        return self.land_use.key


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise LandFlowClassError(f"{LAND_FLOW_CLASSES_FILEPATH}: {message}")


@lru_cache(maxsize=None)
def land_class_by_source_flow() -> dict[tuple[str, str], LandFlowClass]:
    """``(source, source_uuid) -> row``, validated.

    Cached and taking nothing, because its path is fixed.

    :raises LandFlowClassError: on a row missing a field, a row whose `key` and
        `land_use` disagree, a combination the axes rule out, or two rows for
        one flow.
    """
    if not LAND_FLOW_CLASSES_FILEPATH.exists():
        raise FileNotFoundError(
            f"Land flow classes not found at {LAND_FLOW_CLASSES_FILEPATH}. "
            "Run `uv run python tools/build_land_flow_classes.py`."
        )
    payload = orjson.loads(LAND_FLOW_CLASSES_FILEPATH.read_bytes())
    version = payload.get("schema_version")
    _require(
        version == DECISIONS_SCHEMA_VERSION,
        f"schema_version is {version!r}, and this reader is written for "
        f"{DECISIONS_SCHEMA_VERSION}",
    )

    rows: dict[tuple[str, str], LandFlowClass] = {}
    for row in payload.get("rows") or ():
        missing = [field for field in _REQUIRED if not row.get(field)]
        _require(
            not missing,
            f"row {row.get('source_uuid')!r} is missing {missing}",
        )
        fields: Any = row["land_use"]
        _require(
            isinstance(fields, dict),
            f"row {row['source_uuid']!r} has a land_use that is not a mapping",
        )
        try:
            land_use = LandUse.from_dict(fields)
        except (LandUseError, KeyError) as error:
            raise LandFlowClassError(
                f"{LAND_FLOW_CLASSES_FILEPATH}: row {row['source_uuid']!r} "
                f"states a land class the axes do not allow: {error}"
            ) from error
        # The redundancy is the point: `key` is what a curator greps the file
        # by, and a hand edit to one half without the other would otherwise
        # publish a class under another class's name.
        _require(
            land_use.key == row["key"],
            f"row {row['source_uuid']!r} says {row['key']!r} and its fields "
            f"decompose to {land_use.key!r}",
        )

        key = (str(row["source"]).strip(), str(row["source_uuid"]).strip())
        existing = rows.get(key)
        _require(
            existing is None or existing.land_use == land_use,
            f"{key} is assigned both {existing.key if existing else ''!r} and "
            f"{land_use.key!r}. One flow, one land class.",
        )
        rows[key] = LandFlowClass(
            source=key[0],
            source_uuid=key[1],
            source_name=str(row["source_name"]),
            land_use=land_use,
            comment=str(row["comment"]),
            source_context=tuple(str(part) for part in row.get("source_context") or ()),
            unit=str(row.get("unit") or ""),
            original_name=str(row.get("original_name") or ""),
            location=str(row.get("location") or ""),
        )
    return rows


def land_class_for_source_flow(source: str, source_uuid: str) -> LandUse | None:
    """The land class *source_uuid* is, or `None` if no row names it.

    `None` is the answer for almost every flow in the list: this file covers
    land, and a substance with no land class is not a gap in it.
    """
    row = land_class_by_source_flow().get(
        (str(source or "").strip(), str(source_uuid or "").strip())
    )
    return row.land_use if row else None


@lru_cache(maxsize=1)
def published_land_classes() -> dict[str, LandUse]:
    """Every land class a source flow reaches, keyed by :attr:`LandUse.key`.

    The *reached* space, not the legal one.  `domain/land_use.py` enumerates
    what the axes permit, which is thousands of combinations; this is the 336
    that three source lists between them actually ship, and it is what the
    published scheme is built from.
    """
    return {row.key: row.land_use for row in land_class_by_source_flow().values()}
