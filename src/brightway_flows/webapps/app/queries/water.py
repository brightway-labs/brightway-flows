"""The kinds of water, read off the taxonomy and counted against the build.

A water flow says four things and the list used to have somewhere to put three:
which molecule it is, which way it crossed the boundary, and which body it came
from or went to.  What kind of water it was -- sea water, cooling water, brine,
rainwater -- lived only in the source list's free-text name, and because
`pipeline/deduplication.py` signs on every semantic field of an elementary flow,
a difference held in no field is a difference that collapses.  That is #31,
where EF 3.1's balanced pair of water-use factors became a one-sided charge and
a result came out about 434 times too large.  See `water-taxonomy-overview.md`.

Since the water taxonomy each kind is a **material**: a concept in this
project's own SKOS scheme, anchored to ENVO for what the stuff is and to AGROVOC
for the one entry that is an accounting category rather than a physical kind.
This module is how a page reads that back.

**The tree comes from the taxonomy, the counts come from the build.**  The other
way round -- deriving the tree from the flow objects, as `queries/land.py`
derives a land class from its key -- would show a taxonomy with holes in it, and
the holes are the point: `saline_water` mints no flow object at all, because it
exists so that sea water and brine have the parent ENVO gives them, and three
more kinds carry no flow in a build that leaves BAFU out.  A page that listed
only what the build reached could not tell a concept nothing maps onto from a
concept this build happens not to have.

So the rows are `domain/materials.py`'s concepts, joined to the build by
`flow_object_id`, and a concept the build has no object for says so rather than
vanishing.  The reverse mismatch -- a build published under a concept this
checkout's taxonomy does not carry -- is counted in
:attr:`WaterOverview.unrecognised` for the same reason `queries/land.py` counts
an unreadable key: sixteen kinds shown out of seventeen looks like a smaller
taxonomy rather than an older build.
"""

from __future__ import annotations

import sqlite3
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from brightway_flows.domain.context import Dimension
from brightway_flows.domain.materials import (
    BROADER_OURS,
    BROADER_ROOT,
    broader_chain,
    material_concepts,
    withdrawal_water_body,
)
from brightway_flows.domain.vocabulary import MintedNamespace
from brightway_flows.webapps.app.db import table_exists
from brightway_flows.webapps.app.queries.common import alphabetical, load_json

#: Where the material block sits among an object's classifications.  The same
#: string `pipeline/semantic_typing.py` writes, built from the registry rather
#: than spelled twice.
MATERIAL_CLASSIFICATION = f"{MintedNamespace.ENVIRONMENTAL_MATERIAL.value}concept"

#: The two sides of the boundary, in the words the water taxonomy uses for
#: them.  A withdrawal and a return are the halves of EF 3.1's water use pair --
#: a positive factor and a negative one -- and the collapse of one into the
#: other is what this taxonomy was built to stop, so the page names them rather
#: than showing `Resource` and `Environmental` and leaving a reader to know that
#: those are the two.
WITHDRAWAL = "Withdrawal"
RETURN = "Return"

#: The `predicate` an anchor carries when the taxonomy is citing itself.
#:
#: `turbine_water` is the only one: no published class exists for it in ENVO or
#: anywhere else, so the scheme mints an identifier and says so in the same
#: field the other sixteen use to cite somebody.  It is not a weaker match --
#: it is not a match at all, and reading it as one would file the one concept
#: with no external support beside the one whose support is merely inexact.
MINTED_PREDICATE = "minted"


def direction_of(dimension: str) -> str:
    """Which way a flow in *dimension* crossed the boundary.

    Anything that is neither of the two is passed through under its own name
    rather than forced into one of them.  BAFU carries a water flow in the
    `Economic` dimension, which is neither a withdrawal from the environment nor
    a return to it, and calling it either would be a claim this module is in no
    position to make.
    """
    if dimension == Dimension.RESOURCE.value:
        return WITHDRAWAL
    if dimension == Dimension.ENVIRONMENTAL.value:
        return RETURN
    return dimension or "Unknown"


@dataclass(frozen=True)
class Anchor:
    """One published class a kind of water cites, as the taxonomy states it."""

    authority: str
    accession: str
    iri: str
    label: str
    predicate: str

    @property
    def is_minted(self) -> bool:
        """Whether this "citation" is the scheme naming its own concept."""
        return self.predicate == MINTED_PREDICATE

    @property
    def is_exact(self) -> bool:
        """Whether the kind claims to *be* the class, rather than to overlap it.

        All but one of the published citations do.  `fossil_groundwater` is the
        exception: ENVO's `bore hole water` describes how the water was reached
        rather than that it is fossil, so the two overlap without being the same
        thing.
        """
        return self.predicate.endswith("exactMatch")


@dataclass
class WaterFlowRow:
    """One published water flow, as the flows table shows it."""

    uuid: str
    name: str
    concept_id: str
    kind: str
    direction: str
    water_body: str
    context: str
    unit: str
    source: str
    lcia_factor_count: int = 0
    is_deprecated: bool = False


@dataclass
class WaterRow:
    """One kind of water: its place in the tree, its citations, its flows."""

    concept_id: str
    label: str
    comment: str = ""
    flow_object_id: str = ""
    parent_id: str = ""
    parent_label: str = ""
    broader_source: str = BROADER_ROOT
    #: Why the edge is ours, where the taxonomy says so.  Read rather than
    #: restated: `lake_water` and `fossil_groundwater` are both `ours` and are
    #: ours for different reasons, and a page that gave one reason for the
    #: group would be wrong about one of them.
    broader_reason: str = ""
    #: The classes a `shortened` edge passes through to reach its parent.
    broader_via: tuple[str, ...] = ()
    anchors: tuple[Anchor, ...] = ()
    depth: int = 0
    in_build: bool = False
    withdrawals: int = 0
    returns: int = 0
    other_flows: int = 0
    deprecated_flows: int = 0
    lcia_factor_count: int = 0
    sources: tuple[str, ...] = ()

    @property
    def linked_flows(self) -> int:
        return self.withdrawals + self.returns + self.other_flows

    @property
    def is_root(self) -> bool:
        return not self.parent_id

    @property
    def hierarchy_is_ours(self) -> bool:
        """Whether this kind's parent is an edge no authority asserts.

        Three are: ENVO files neither lake water nor river water under surface
        water, and it files bore hole water under liquid water rather than under
        groundwater.  LCA needs those containments, so the scheme states them --
        and says that it is the one stating them.
        """
        return self.broader_source == BROADER_OURS

    @property
    def published_anchors(self) -> tuple[Anchor, ...]:
        """The classes this kind cites in somebody else's vocabulary."""
        return tuple(anchor for anchor in self.anchors if not anchor.is_minted)

    @property
    def is_minted(self) -> bool:
        """Whether the kind cites nothing, because nothing published it.

        `turbine_water` is the only one, in ENVO or anywhere else, and an ENVO
        term request goes with the minted identifier -- so the scheme's own
        concept retires if ENVO adopts the term.
        """
        return not self.published_anchors

    @property
    def is_inexact(self) -> bool:
        """Whether the kind overlaps what it cites rather than being it.

        A kind that cites nothing is not inexact, it is unpublished, and the
        two are different findings about how well anchored a concept is.
        """
        return bool(self.published_anchors) and not all(
            anchor.is_exact for anchor in self.published_anchors
        )

    @property
    def withdrawal_body(self) -> str:
        """The body a withdrawal of this kind was taken from, or "".

        Only for the kinds that name a place.  For a withdrawal the kind of
        water and the body it came from are one fact stated twice; for a
        discharge they are two different facts, which is why nothing here is
        ever applied to a return.
        """
        return withdrawal_water_body(self.concept_id) or ""


@dataclass
class WaterOverview:
    """Everything the water page shows."""

    #: Every kind, depth-first from the roots -- the order the tree reads in.
    rows: list[WaterRow] = field(default_factory=list)
    #: Every published water flow, before the filters.
    all_flows: list[WaterFlowRow] = field(default_factory=list)
    #: The flows the filters select.
    flows: list[WaterFlowRow] = field(default_factory=list)
    #: Concept ids the build published that this taxonomy does not carry.
    unrecognised: int = 0

    @property
    def kinds(self) -> int:
        return len(self.rows)

    @property
    def kinds_with_flows(self) -> int:
        return sum(1 for row in self.rows if row.linked_flows)

    @property
    def total_flows(self) -> int:
        return len(self.all_flows)

    @property
    def deprecated_flows(self) -> int:
        """Retired water flows, which is the plainest measure of the taxonomy.

        The whole exercise began with water flows being merged into each other,
        so a build in which none of them is retired is a build in which none of
        them was merged away.
        """
        return sum(1 for flow in self.all_flows if flow.is_deprecated)

    @property
    def factors(self) -> int:
        return sum(flow.lcia_factor_count for flow in self.all_flows)

    @property
    def by_direction(self) -> dict[str, int]:
        counts = Counter(flow.direction for flow in self.all_flows)
        return dict(sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])))

    @property
    def ours(self) -> list[WaterRow]:
        """The kinds whose place in the tree this project asserts itself."""
        return [row for row in self.rows if row.hierarchy_is_ours]

    @property
    def inexact(self) -> list[WaterRow]:
        """The kinds citing a class they overlap rather than are."""
        return [row for row in self.rows if row.is_inexact]

    @property
    def minted(self) -> list[WaterRow]:
        """The kinds no authority publishes at all."""
        return [row for row in self.rows if row.is_minted]

    @property
    def exceptions(self) -> list[WaterRow]:
        """Every kind that states something of its own, in tree order.

        The union rather than three lists shown one after another: two of the
        four state more than one thing -- `fossil_groundwater` asserts its
        parent *and* declines to claim equivalence with what it cites -- and
        listing it twice would read as two different concepts.
        """
        return [
            row
            for row in self.rows
            if row.hierarchy_is_ours or row.is_inexact or row.is_minted
        ]

    def kind_options(self) -> list[tuple[str, str]]:
        """The kinds carrying a flow, with how many each carries.

        Only those, for the reason the land page offers only the axis values in
        use: a filter that can select nothing looks no different from one that
        is broken.
        """
        counts = Counter(flow.concept_id for flow in self.all_flows)
        return alphabetical(
            (row.concept_id, row.label, counts[row.concept_id])
            for row in self.rows
            if counts.get(row.concept_id)
        )

    def direction_options(self) -> list[tuple[str, str]]:
        return alphabetical(
            (direction, direction, count)
            for direction, count in self.by_direction.items()
        )

    def body_options(self) -> list[tuple[str, str]]:
        counts = Counter(flow.water_body for flow in self.all_flows if flow.water_body)
        return alphabetical((body, body, count) for body, count in counts.items())


def _anchors(concept: dict[str, Any]) -> tuple[Anchor, ...]:
    return tuple(
        Anchor(
            authority=str(anchor.get("authority") or ""),
            accession=str(anchor.get("id") or ""),
            iri=str(anchor.get("iri") or ""),
            label=str(anchor.get("label") or ""),
            predicate=str(anchor.get("predicate") or ""),
        )
        for anchor in concept.get("anchors") or ()
    )


def _tree_order(concepts: dict[str, dict[str, Any]]) -> list[str]:
    """The concept ids depth-first, roots in the order the taxonomy states them.

    A child never precedes its parent, so the indent the page draws from
    :attr:`WaterRow.depth` reads as a tree rather than as a column of numbers.
    """
    children: dict[str | None, list[str]] = {}
    for concept_id, concept in concepts.items():
        children.setdefault(concept.get("broader"), []).append(concept_id)

    ordered: list[str] = []

    def walk(parent: str | None) -> None:
        for concept_id in children.get(parent, ()):
            ordered.append(concept_id)
            walk(concept_id)

    walk(None)
    return ordered


def water_overview(
    connection: sqlite3.Connection, *, filters: dict[str, str] | None = None
) -> WaterOverview | None:
    """The taxonomy, and the flows this build hangs on it.

    `None` when the database has no `flow_objects`, which is a page rather than
    a 500 -- the same empty state the other flow-object views have, and what a
    data directory looks like after an upgrade and before a rebuild.
    """
    if not table_exists(connection, "flow_objects"):
        return None

    concepts = material_concepts()
    overview = WaterOverview()
    by_object: dict[str, WaterRow] = {}

    for concept_id in _tree_order(concepts):
        concept = concepts[concept_id]
        row = WaterRow(
            concept_id=concept_id,
            label=str(concept.get("label") or concept_id),
            comment=str(concept.get("comment") or ""),
            flow_object_id=str(concept.get("flow_object_id") or ""),
            parent_id=str(concept.get("broader") or ""),
            parent_label=str(
                (concepts.get(concept.get("broader")) or {}).get("label") or ""
            ),
            broader_source=str(concept.get("broader_source") or BROADER_ROOT),
            broader_reason=str(concept.get("broader_reason") or ""),
            broader_via=tuple(str(via) for via in concept.get("broader_via") or ()),
            anchors=_anchors(concept),
            depth=len(broader_chain(concept_id)) - 1,
        )
        overview.rows.append(row)
        if row.flow_object_id:
            by_object[row.flow_object_id] = row

    _count_flows(connection, overview, by_object)
    overview.unrecognised = _unrecognised(connection, concepts)
    overview.flows = [
        flow for flow in overview.all_flows if _matches(flow, filters or {})
    ]
    return overview


def _count_flows(
    connection: sqlite3.Connection,
    overview: WaterOverview,
    by_object: dict[str, WaterRow],
) -> None:
    """Read every flow on a water object once, and count it onto its kind.

    One query rather than four counting sub-selects per kind, because the page
    lists the flows as well as counting them -- there are a few dozen of them,
    and reading them twice would let the table and the totals disagree.
    """
    if not by_object:
        return
    placeholders = ",".join("?" * len(by_object))
    rows = connection.execute(
        "SELECT uuid, flow_object_id, pref_label_value, source, unit, "
        "lcia_factor_count, is_deprecated, context_display, context_dimension, "
        "context_water_body FROM elementary_flows "
        f"WHERE flow_object_id IN ({placeholders})",
        list(by_object),
    ).fetchall()

    sources: dict[str, set[str]] = {}
    for row in rows:
        kind = by_object[row["flow_object_id"]]
        kind.in_build = True
        deprecated = bool(row["is_deprecated"])
        factors = int(row["lcia_factor_count"] or 0)
        direction = direction_of(str(row["context_dimension"] or ""))
        overview.all_flows.append(
            WaterFlowRow(
                uuid=str(row["uuid"]),
                name=str(row["pref_label_value"] or ""),
                concept_id=kind.concept_id,
                kind=kind.label,
                direction=direction,
                water_body=str(row["context_water_body"] or ""),
                context=str(row["context_display"] or ""),
                unit=str(row["unit"] or ""),
                source=str(row["source"] or ""),
                lcia_factor_count=factors,
                is_deprecated=deprecated,
            )
        )
        if deprecated:
            # Counted apart rather than into the direction it had: a retired
            # flow is not one the list publishes, and adding it to the
            # withdrawals would make a merged-away half look like a live one.
            kind.deprecated_flows += 1
            continue
        kind.lcia_factor_count += factors
        if direction == WITHDRAWAL:
            kind.withdrawals += 1
        elif direction == RETURN:
            kind.returns += 1
        else:
            kind.other_flows += 1
        if row["source"]:
            sources.setdefault(kind.concept_id, set()).add(str(row["source"]))

    for kind in overview.rows:
        kind.sources = tuple(sorted(sources.get(kind.concept_id, ())))

    overview.all_flows.sort(
        key=lambda flow: (flow.kind.lower(), flow.direction, flow.context, flow.unit)
    )


def _unrecognised(
    connection: sqlite3.Connection, concepts: dict[str, dict[str, Any]]
) -> int:
    """Flow objects published under a concept this taxonomy does not carry.

    Zero on a build this checkout wrote.  Non-zero means the database was
    written by a build whose taxonomy has since changed, and a page that showed
    only the concepts it recognises would report a smaller taxonomy rather than
    an older build.
    """
    unrecognised = 0
    for row in connection.execute(
        "SELECT classifications_json FROM flow_objects "
        "WHERE classifications_json LIKE ?",
        (f"%{MintedNamespace.ENVIRONMENTAL_MATERIAL.value}%",),
    ):
        entry = (load_json(row["classifications_json"], {}) or {}).get(
            MATERIAL_CLASSIFICATION
        )
        if not isinstance(entry, dict):
            continue
        stated = entry.get("@value")
        concept_id = str(
            (stated[0] if isinstance(stated, list) and stated else stated) or ""
        )
        if concept_id and concept_id not in concepts:
            unrecognised += 1
    return unrecognised


def _matches(flow: WaterFlowRow, filters: dict[str, str]) -> bool:
    """Whether *flow* answers to every filter that is set.

    All of them rather than any: kind, direction and body are three different
    questions about one flow, and a reader who picks `Cooling water` and
    `Return` is asking for the return half of the cooling water pair.
    """
    if (kind := filters.get("kind")) and flow.concept_id != kind:
        return False
    if (direction := filters.get("direction")) and flow.direction != direction:
        return False
    if (body := filters.get("body")) and flow.water_body != body:
        return False
    return True
