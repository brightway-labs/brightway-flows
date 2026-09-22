"""Land occupation and transformation, read off the built list.

A land flow says five things and the list used to have slots for two: how much
land for how long (the unit), and which side of the boundary it crossed (the
context).  Which way a transformation runs, what the land is, and how it is used
lived in a comma-separated name that three source lists spell three ways -- so
`arable, non-irrigated, intensive`, `annual crop, non-irrigated, intensive` and
BAFU's spelling of the second were three flow objects for one piece of land, and
`from forest, primary` and `to forest, primary` -- a balanced pair EF
characterises at -396.7 and +396.7 -- were held apart by the words `from` and
`to` inside a string.

Since #66's fifth stage each of those is a field, and this module is how a page
reads them back.  A land flow object carries a classification block naming its
class by :attr:`~brightway_flows.domain.land_use.LandUse.key`, and
:meth:`~brightway_flows.domain.land_use.LandUse.from_key` turns that back
into the value with its seventeen axes.  Nothing here parses a vendor's name;
the key is a string this project wrote from fields it already had.

**Read at query time rather than from columns of its own.**  The same choice the
origin facet makes, for the same reason: a new column means every deployment
needs a rebuild before the page works at all, and the review app runs whatever
build is in the shared data directory.  Decomposing 362 land objects out of
`classifications_json` costs a scan the page can afford; 7,700 substances would
not be.
"""

from __future__ import annotations

import sqlite3
from collections import Counter
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from brightway_flows.domain.land_use import (
    QUALIFIER_AXES,
    Direction,
    LandCover,
    LandUse,
    LandUseError,
)
from brightway_flows.domain.land_use_anchors import anchors_for
from brightway_flows.domain.vocabulary import MintedNamespace
from brightway_flows.webapps.app.db import table_exists
from brightway_flows.webapps.app.queries.common import alphabetical, load_json

#: Where the land block sits among an object's classifications.  The same
#: string `pipeline/semantic_typing.py` writes, from the registry rather than
#: spelled twice.
LAND_CLASSIFICATION = f"{MintedNamespace.LAND_CLASS.value}concept"

#: The axes a reader can filter on, in the order a label reads.
#:
#: `direction` and `cover` first because they are the two every class states,
#: then the qualifiers in :data:`QUALIFIER_AXES` order, which is the order the
#: source lists write them and the reverse of the order
#: :meth:`LandUse.broader` drops them.  One list, so a new axis on the value
#: type is a filter on this page without a second place to remember.
FILTER_AXES: tuple[tuple[str, str, type[StrEnum]], ...] = (
    ("direction", "Direction", Direction),
    ("cover", "Cover", LandCover),
    *(
        (name, name.replace("_", " ").capitalize(), enum)
        for name, enum in QUALIFIER_AXES.items()
    ),
)


@dataclass
class LandRow:
    """One published land class, and the flows that resolve to it."""

    flow_object_id: str
    land_use: LandUse
    name: str = ""
    parent_id: str = ""
    linked_flows: int = 0
    deprecated_flows: int = 0
    lcia_factor_count: int = 0
    sources: tuple[str, ...] = ()

    @property
    def key(self) -> str:
        return self.land_use.key

    @property
    def label(self) -> str:
        return self.land_use.label

    @property
    def direction(self) -> Direction:
        return self.land_use.direction

    @property
    def cover(self) -> LandCover:
        return self.land_use.cover

    @property
    def qualifiers(self) -> dict[str, StrEnum]:
        return self.land_use.qualifiers()

    @property
    def depth(self) -> int:
        """How many qualifiers this class states.

        The tree's indent, and a useful sort: the bare `(direction, cover)`
        classes are the roots and everything else hangs under one of them.
        """
        return len(self.land_use.qualifiers())

    @property
    def anchor_rows(self) -> list[Any]:
        """Every published class this one cites, computed from its fields.

        Not read back out of the database.  A land class asserts nothing of its
        own -- it is cropland because its `cover` is -- so the citation belongs
        to the axis value and is the same for every class that states it.  The
        built record carries the same anchors; recomputing them here means the
        page cannot show a citation the taxonomy has since corrected.
        """
        return anchors_for(self.land_use)


@dataclass
class LandOverview:
    """Everything the land page shows above its table."""

    rows: list[LandRow] = field(default_factory=list)
    #: Every class in the build, before the filters, keyed by class key. The
    #: tree needs the parents of a filtered row even when the filter excludes
    #: them, or a filtered view would show orphans.
    all_rows: dict[str, LandRow] = field(default_factory=dict)
    total: int = 0
    unreadable: int = 0

    @property
    def by_direction(self) -> dict[str, int]:
        counts = Counter(row.direction.value for row in self.all_rows.values())
        return {direction.value: counts.get(direction.value, 0) for direction in Direction}

    @property
    def covers(self) -> int:
        return len({row.cover for row in self.all_rows.values()})

    @property
    def flows(self) -> int:
        return sum(row.linked_flows for row in self.all_rows.values())

    def axis_options(self, axis: str) -> list[tuple[str, str]]:
        """The values of *axis* in use, with a count of the classes stating each.

        Only the values this build reaches.  A dropdown offering all four
        silvicultural regimes over a list carrying one would invite three
        filters that select nothing, and the reader could not tell that from a
        filter that is broken.

        In label order, like every other filter list in this application.
        """
        counts: Counter = Counter()
        for row in self.all_rows.values():
            value = _axis_value(row.land_use, axis)
            if value is not None:
                counts[value.value] += 1
        return alphabetical((value, value, count) for value, count in counts.items())


def _axis_value(land_use: LandUse, axis: str) -> StrEnum | None:
    if axis == "direction":
        return land_use.direction
    if axis == "cover":
        return land_use.cover
    return getattr(land_use, axis, None)


#: The flows on a land object, counted the way the page states them.  A retired
#: flow is counted apart rather than hidden: EF ships `Occup. as Forest land`
#: beside `forest`, with no characterisation factor on it, and the two are one
#: land class -- so one of them is retired onto the other, and a page that
#: showed only the live count would not say that had happened.
_FLOW_COUNTS = (
    "(SELECT count(*) FROM elementary_flows ef "
    "WHERE ef.flow_object_id = fo.flow_object_id "
    "AND coalesce(ef.is_deprecated, 0) = 0) AS linked_flows, "
    "(SELECT count(*) FROM elementary_flows ef "
    "WHERE ef.flow_object_id = fo.flow_object_id "
    "AND coalesce(ef.is_deprecated, 0) = 1) AS deprecated_flows, "
    "(SELECT coalesce(sum(ef.lcia_factor_count), 0) FROM elementary_flows ef "
    "WHERE ef.flow_object_id = fo.flow_object_id "
    "AND coalesce(ef.is_deprecated, 0) = 0) AS lcia_factor_count"
)


def land_overview(
    connection: sqlite3.Connection, *, filters: dict[str, str] | None = None
) -> LandOverview | None:
    """Every published land class, and the ones the filters select.

    `None` when the database has no `flow_objects`, which is a page rather than
    a 500.

    A class whose key this build's vocabulary cannot read is counted in
    `unreadable` rather than dropped.  It means the database was written by a
    build whose axes this checkout no longer declares, and a page that silently
    showed 337 of 339 would look like a smaller taxonomy rather than an older
    one.
    """
    if not table_exists(connection, "flow_objects"):
        return None

    overview = LandOverview()
    rows = connection.execute(
        "SELECT fo.flow_object_id, fo.pref_label_value, fo.parent_intervention_id, "
        f"fo.classifications_json, {_FLOW_COUNTS} "
        "FROM flow_objects fo WHERE fo.classifications_json LIKE ?",
        (f"%{MintedNamespace.LAND_CLASS.value}%",),
    ).fetchall()

    for row in rows:
        entry = (load_json(row["classifications_json"], {}) or {}).get(
            LAND_CLASSIFICATION
        )
        if not isinstance(entry, dict):
            continue
        stated = entry.get("@value")
        key = str((stated[0] if isinstance(stated, list) and stated else stated) or "")
        try:
            land_use = LandUse.from_key(key)
        except LandUseError:
            overview.unreadable += 1
            continue
        overview.all_rows[key] = LandRow(
            flow_object_id=row["flow_object_id"],
            land_use=land_use,
            name=row["pref_label_value"] or land_use.label,
            parent_id=row["parent_intervention_id"] or "",
            linked_flows=int(row["linked_flows"] or 0),
            deprecated_flows=int(row["deprecated_flows"] or 0),
            lcia_factor_count=int(row["lcia_factor_count"] or 0),
            sources=_sources_for(connection, row["flow_object_id"]),
        )

    overview.total = len(overview.all_rows)
    selected = filters or {}
    overview.rows = sorted(
        (
            land_row
            for land_row in overview.all_rows.values()
            if _matches(land_row.land_use, selected)
        ),
        key=lambda land_row: (
            land_row.direction.value,
            land_row.cover.value,
            land_row.depth,
            land_row.label.lower(),
        ),
    )
    return overview


def _matches(land_use: LandUse, filters: dict[str, str]) -> bool:
    """Whether *land_use* states every axis value the filters name.

    All of them, not any: the axes are independent questions about one piece of
    land, and a reader who picks `Cropland` and `Irrigated` is asking for
    irrigated cropland rather than for everything that is either.
    """
    for axis, wanted in filters.items():
        if not wanted:
            continue
        value = _axis_value(land_use, axis)
        if value is None or value.value != wanted:
            return False
    return True


def _sources_for(connection: sqlite3.Connection, flow_object_id: str) -> tuple[str, ...]:
    """Which lists' flows resolve to this class.

    The point of the whole taxonomy, made visible: a class reached by EF 3.1,
    ecoinvent and BAFU alike is one piece of land the three lists were spelling
    three ways, and before #66 it was three flow objects.
    """
    return tuple(
        str(row["source"])
        for row in connection.execute(
            "SELECT DISTINCT source FROM elementary_flows "
            "WHERE flow_object_id = ? AND coalesce(source, '') <> '' "
            "ORDER BY source",
            (flow_object_id,),
        )
    )
