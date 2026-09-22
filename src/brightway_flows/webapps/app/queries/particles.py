"""The particle size windows, read off the scheme and counted against the build.

An airborne-particle flow says which particles were counted -- everything below
ten micrometres, the 2.5-10 um slice, dust of no stated size -- and until
`domain/particulate_size.py` the list had no field for it, so five source lists'
seventeen spellings of seven windows collapsed, minted, or reached the wrong
window on a label (#153).  Since then the window is a **curated scheme of seven
concepts**, each with its bounds in micrometres, its parent by containment,
the `Particulates` spellings it always publishes, and one flow object.

This module is how a page reads that back, and it is built the way
`queries/water.py` is, for the same reason: **the tree comes from the scheme,
the counts come from the build.**  A window the build reached shows its flows;
a window it did not reach still appears and says so.  Three questions the page
answers that nothing else does: where each list's particle rows landed
(`merge_outcomes`), what each method states for each window and what this list
carries across the windows (`lcia_characterization_factors`), and whether a
particle row the scheme has not read would stop the next merge
(`plans/particle-family.md` §5, #196).
"""

from __future__ import annotations

import sqlite3
from collections import Counter, defaultdict
from dataclasses import dataclass, field

from brightway_flows.domain.particulate_size import (
    SizeClass,
    broader_chain,
    names_a_particle_by_size,
    particulate_class_by_source_flow,
    size_classes,
)
from brightway_flows.webapps.app.db import table_exists
from brightway_flows.webapps.app.queries.common import alphabetical

#: What a carried factor's `derivation` reads.
CARRIED = "carried"


@dataclass
class ParticleFlowRow:
    """One published particle flow, as the flows table shows it."""

    uuid: str
    name: str
    window_id: str
    window: str
    context: str
    unit: str
    source: str
    lcia_factor_count: int = 0
    is_deprecated: bool = False


@dataclass
class WindowFactors:
    """What one method's consensus implementation publishes for one window."""

    method: str
    category: str
    published: int = 0
    carried: int = 0
    #: The number in unspecified air, where there is one, and how it got there.
    in_unspecified_air: float | None = None
    derivation_in_unspecified_air: str = ""


@dataclass
class WindowRow:
    """One window: its place in the scheme, its spellings, its flows, its numbers."""

    concept_id: str
    label: str
    definition: str
    definition_source: str
    comment: str
    lower_um: float | None
    upper_um: float | None
    selection: str
    alt_labels: tuple[str, ...]
    flow_object_id: str
    parent_id: str = ""
    parent_label: str = ""
    depth: int = 0
    in_build: bool = False
    flows: int = 0
    deprecated_flows: int = 0
    lcia_factor_count: int = 0
    sources: tuple[str, ...] = ()
    #: Source rows of each merged list that landed on this window, by list.
    rows_by_list: dict[str, int] = field(default_factory=dict)
    factors: list[WindowFactors] = field(default_factory=list)

    @property
    def window_text(self) -> str:
        """The bounds as a reader would say them."""
        if self.lower_um is None and self.upper_um is None:
            return "no cut stated"
        if self.lower_um is None:
            return f"below {self.upper_um:g} µm"
        if self.upper_um is None:
            return f"above {self.lower_um:g} µm"
        return f"{self.lower_um:g} – {self.upper_um:g} µm"

    @property
    def is_root(self) -> bool:
        return not self.parent_id

    @property
    def source_rows(self) -> int:
        return sum(self.rows_by_list.values())


@dataclass
class ParticlesOverview:
    """Everything the particles page shows."""

    rows: list[WindowRow] = field(default_factory=list)
    all_flows: list[ParticleFlowRow] = field(default_factory=list)
    flows: list[ParticleFlowRow] = field(default_factory=list)
    #: The merged lists whose rows the table reads, in the order they appear.
    lists: tuple[str, ...] = ()
    #: The methods whose numbers the factor table shows.
    methods: tuple[str, ...] = ()
    #: Source rows named as a particle size cut that the curated table has not
    #: read -- the rows the merge guard would refuse.  Empty on a build that
    #: finished, by construction, and shown so a reader can see that it is.
    unread: list[tuple[str, str]] = field(default_factory=list)
    #: The rows the class table reads under a source category, by category.
    by_source_category: dict[str, int] = field(default_factory=dict)
    unrecognised: int = 0

    @property
    def windows(self) -> int:
        return len(self.rows)

    @property
    def windows_with_flows(self) -> int:
        return sum(1 for row in self.rows if row.flows)

    @property
    def total_flows(self) -> int:
        return len(self.all_flows)

    @property
    def deprecated_flows(self) -> int:
        return sum(1 for flow in self.all_flows if flow.is_deprecated)

    @property
    def carried_factors(self) -> int:
        return sum(entry.carried for row in self.rows for entry in row.factors)

    @property
    def readings(self) -> int:
        """Rows of the curated class table, over every registered list."""
        return len(particulate_class_by_source_flow())

    def window_options(self) -> list[tuple[str, str]]:
        counts = Counter(flow.window_id for flow in self.all_flows)
        return alphabetical(
            (row.concept_id, row.label, counts[row.concept_id])
            for row in self.rows
            if counts.get(row.concept_id)
        )

    def source_options(self) -> list[tuple[str, str]]:
        counts = Counter(flow.source for flow in self.all_flows if flow.source)
        return alphabetical((source, source, count) for source, count in counts.items())


def _tree_order(classes: dict[str, SizeClass]) -> list[str]:
    """The window ids depth-first, so the indent reads as a tree."""
    children: dict[str | None, list[str]] = defaultdict(list)
    for identifier, value in classes.items():
        children[value.broader].append(identifier)
    ordered: list[str] = []

    def walk(parent: str | None) -> None:
        for identifier in children.get(parent, ()):
            ordered.append(identifier)
            walk(identifier)

    walk(None)
    return ordered


def particles_overview(
    connection: sqlite3.Connection, *, filters: dict[str, str] | None = None
) -> ParticlesOverview | None:
    """The scheme, and what this build hangs on it.

    `None` when the database has no `flow_objects`, which is a page rather than
    a 500 -- the same empty state the other flow-object views have.
    """
    if not table_exists(connection, "flow_objects"):
        return None
    classes = size_classes()
    overview = ParticlesOverview()
    by_object: dict[str, WindowRow] = {}
    for identifier in _tree_order(classes):
        value = classes[identifier]
        parent = classes.get(value.broader or "")
        row = WindowRow(
            concept_id=identifier,
            label=value.label,
            definition=value.definition,
            definition_source=value.definition_source,
            comment=value.comment,
            lower_um=value.lower_um,
            upper_um=value.upper_um,
            selection=value.selection,
            alt_labels=value.alt_labels,
            flow_object_id=value.flow_object_id,
            parent_id=value.broader or "",
            parent_label=parent.label if parent else "",
            depth=len(broader_chain(identifier)) - 1,
        )
        overview.rows.append(row)
        by_object[value.flow_object_id] = row

    _count_flows(connection, overview, by_object)
    _count_source_rows(connection, overview, by_object)
    _count_factors(connection, overview, by_object)
    overview.unread = _unread_rows(connection)
    overview.by_source_category = dict(
        Counter(
            row.source_category
            for row in particulate_class_by_source_flow().values()
            if row.source_category
        )
    )
    overview.flows = [flow for flow in overview.all_flows if _matches(flow, filters or {})]
    return overview


def _count_flows(connection, overview, by_object) -> None:
    placeholders = ",".join("?" * len(by_object))
    rows = connection.execute(
        "SELECT uuid, flow_object_id, pref_label_value, source, unit, "
        "lcia_factor_count, is_deprecated, context_display FROM elementary_flows "
        f"WHERE flow_object_id IN ({placeholders})",
        list(by_object),
    ).fetchall()
    sources: dict[str, set[str]] = defaultdict(set)
    for row in rows:
        window = by_object[row["flow_object_id"]]
        window.in_build = True
        deprecated = bool(row["is_deprecated"])
        overview.all_flows.append(
            ParticleFlowRow(
                uuid=str(row["uuid"]),
                name=str(row["pref_label_value"] or ""),
                window_id=window.concept_id,
                window=window.label,
                context=str(row["context_display"] or ""),
                unit=str(row["unit"] or ""),
                source=str(row["source"] or ""),
                lcia_factor_count=int(row["lcia_factor_count"] or 0),
                is_deprecated=deprecated,
            )
        )
        if deprecated:
            window.deprecated_flows += 1
            continue
        window.flows += 1
        window.lcia_factor_count += int(row["lcia_factor_count"] or 0)
        if row["source"]:
            sources[window.concept_id].add(str(row["source"]))
    for window in overview.rows:
        window.sources = tuple(sorted(sources.get(window.concept_id, ())))
    overview.all_flows.sort(key=lambda flow: (flow.window.lower(), flow.context, flow.unit))


def _count_source_rows(connection, overview, by_object) -> None:
    """Where each merged list's particle rows landed, by window."""
    if not table_exists(connection, "merge_outcomes"):
        return
    placeholders = ",".join("?" * len(by_object))
    rows = connection.execute(
        "SELECT list_name, list_version, flow_object_id, COUNT(*) AS n "
        "FROM merge_outcomes "
        f"WHERE flow_object_id IN ({placeholders}) "
        "GROUP BY list_name, list_version, flow_object_id",
        list(by_object),
    ).fetchall()
    lists: list[str] = []
    for row in rows:
        key = f"{row['list_name']}-{row['list_version']}"
        if key not in lists:
            lists.append(key)
        by_object[row["flow_object_id"]].rows_by_list[key] = int(row["n"])
    overview.lists = tuple(sorted(lists))


def _count_factors(connection, overview, by_object) -> None:
    """What the consensus implementation of each method publishes per window."""
    for name in ("lcia_characterization_factors", "lcia_impact_categories", "lcia_methods"):
        if not table_exists(connection, name):
            return
    placeholders = ",".join("?" * len(by_object))
    rows = connection.execute(
        "SELECT m.name AS method, c.name AS category, e.flow_object_id, "
        "f.derivation, f.amount, e.context_display "
        "FROM lcia_characterization_factors f "
        "JOIN lcia_impact_categories c ON c.id = f.impact_category_id "
        "JOIN lcia_methods m ON m.id = c.method_id "
        "JOIN elementary_flows e ON e.uuid = f.elementary_flow_uuid "
        "WHERE c.implemented_by = 'brightway-flows' "
        f"AND e.flow_object_id IN ({placeholders}) AND e.is_deprecated = 0 "
        "AND (LOWER(c.name) LIKE '%particul%' OR LOWER(c.name) LIKE '%respiratory inorg%')",
        list(by_object),
    ).fetchall()
    methods: list[str] = []
    cells: dict[tuple[str, str, str], WindowFactors] = {}
    for row in rows:
        method = str(row["method"])
        if method not in methods:
            methods.append(method)
        key = (row["flow_object_id"], method, str(row["category"]))
        cell = cells.get(key)
        if cell is None:
            cell = cells[key] = WindowFactors(method=method, category=str(row["category"]))
            by_object[row["flow_object_id"]].factors.append(cell)
        cell.published += 1
        if row["derivation"] == CARRIED:
            cell.carried += 1
        if str(row["context_display"] or "").endswith("Air → Unknown"):
            cell.in_unspecified_air = float(row["amount"])
            cell.derivation_in_unspecified_air = str(row["derivation"] or "")
    overview.methods = tuple(sorted(methods))
    for window in overview.rows:
        window.factors.sort(key=lambda cell: (cell.method, cell.category))


def _unread_rows(connection) -> list[tuple[str, str]]:
    """Source rows named as a particle size cut that no curated row reads.

    The population the merge guard refuses.  Read off `merge_outcomes`, so it
    is the rows the build actually saw; a build that finished shows none.
    """
    if not table_exists(connection, "merge_outcomes"):
        return []
    read = {
        (row.source, row.source_uuid) for row in particulate_class_by_source_flow().values()
    }
    out: list[tuple[str, str]] = []
    for row in connection.execute(
        "SELECT DISTINCT list_name, list_version, source_uuid, source_name FROM merge_outcomes"
    ):
        name = str(row["source_name"] or "")
        if not names_a_particle_by_size(name):
            continue
        source = f"{row['list_name']}-{row['list_version']}"
        if (source, str(row["source_uuid"])) not in read:
            out.append((source, name))
    return sorted(set(out))


def _matches(flow: ParticleFlowRow, filters: dict[str, str]) -> bool:
    if filters.get("window") and flow.window_id != filters["window"]:
        return False
    if filters.get("source") and flow.source != filters["source"]:
        return False
    return True
