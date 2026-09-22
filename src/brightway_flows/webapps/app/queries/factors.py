"""The evidence a factor ruling needs, gathered for one page of questions.

A curator asked "should this list publish 53,540 or 134.73?" cannot answer it
from the two numbers.  What they need is everything that put the numbers in front
of them:

* **where the flow came from** -- every source list that contributed to it, under
  the name and compartment that list used, and by what route the merge placed it;
* **what happened to it since** -- the changes the transform recorded against its
  substance, each naming the transformer that made it and what it read;
* **every number anybody states** -- all three implementations, in every context
  the question covers, plus the numbers a collapse already declined (§4.2).

Read here rather than baked into the queue item's payload, for the reason
`queries/collisions.py` reads its flows here: the payload is what the question
*is*, and the evidence is a join over tables that are already in the database.
Baking it in would freeze it at the moment `characterise` ran and make the row
enormous.
"""

from __future__ import annotations

import math
import sqlite3
from collections import Counter
from dataclasses import dataclass, field, replace
from typing import Any

from brightway_flows.domain.lcia.crosswalk import (
    CONSENSUS_IMPLEMENTATION,
    lcia_method_by_slug,
    lcia_methods,
)
from brightway_flows.domain.lcia.records import Band
from brightway_flows.lcia.differences import band_for
from brightway_flows.pipeline.review_records import ReviewQueue
from brightway_flows.webapps.app.db import table_exists
from brightway_flows.webapps.app.queries.common import (
    PAGE_SIZE,
    Page,
    clamp_page,
    load_json,
    order_by,
)

#: How many changes to show per substance.  A flow object with 200 changes is
#: not evidence, it is a wall; the first ones are the identity decisions and
#: those are what a factor ruling turns on.
CHANGE_LIMIT = 12


@dataclass
class SourceRow:
    """One source list's contribution to a flow, as the merge recorded it."""

    list_name: str
    list_version: str
    source_flow_uuid: str
    source_flow_name: str
    original_context: str
    unit: str
    merge_basis: str
    mapping_file: str


@dataclass
class ChangeRow:
    """One thing the transform did to the substance behind a flow."""

    transformer: str
    field_name: str
    comment: str


@dataclass
class FactorRow:
    """One implementation's number for one flow, category and place."""

    implemented_by: str
    amount: float
    geography: str
    derivation: str
    source_flow_uuid: str


@dataclass
class DeclinedRow:
    """A number a collapse declined on the way here (#63)."""

    detail: str


@dataclass
class FlowFacts:
    """What a flow is called, in what unit, and where -- for one uuid.

    The queue item names its flows by uuid, and a uuid is not a thing a curator
    can weigh.  Read from `elementary_flows` rather than from the payload
    because the payload states the substance once for the whole question, and
    the rows of one question differ by context and can differ by unit.
    """

    label: str = ""
    unit: str = ""
    context_display: str = ""


@dataclass
class ElsewhereRow:
    """An accepted factor somewhere else that states one of these numbers.

    A proposed factor is a number one implementation states and this list does
    not publish.  Finding the same number already published against a *different*
    flow is evidence about where it came from: ecoinvent's implementation states
    the catch-all's number for many named pesticides, and a curator ruling on
    `Abamectin` should see that the number they are being asked to accept is the
    one this list already publishes for `Insecticides, unspecified` (#76).
    """

    amount: float
    substance: str
    flow_object_id: str
    category: str
    context_display: str
    derivation: str


@dataclass
class Question:
    """One queue item with its evidence read."""

    item: Any
    flows: list[dict[str, Any]] = field(default_factory=list)
    sources: dict[str, list[SourceRow]] = field(default_factory=dict)
    changes: list[ChangeRow] = field(default_factory=list)
    factors: dict[str, list[FactorRow]] = field(default_factory=dict)
    declined: list[DeclinedRow] = field(default_factory=list)
    flow_facts: dict[str, FlowFacts] = field(default_factory=dict)
    elsewhere: list[ElsewhereRow] = field(default_factory=list)
    #: How many matches there are in all, of which `elsewhere` is the first
    #: `ELSEWHERE_LIMIT`.
    elsewhere_total: int = 0

    @property
    def units(self) -> list[str]:
        """Every unit the flows of this question are measured in.

        A list rather than a value: one question covers a substance across its
        compartments, and nothing forces those to share a unit -- a resource in
        cubic metres beside an emission in kilograms is exactly the case a
        curator must not read past.
        """
        return sorted({facts.unit for facts in self.flow_facts.values() if facts.unit})

    def label_for(self, uuid: str) -> str:
        """What to call a flow in a table: its context, falling back to its uuid.

        The substance is stated once in the section header, so repeating it on
        every row would say nothing; what distinguishes one row from the next is
        where the release happened.
        """
        facts = self.flow_facts.get(uuid)
        if facts and facts.context_display:
            return facts.context_display
        return uuid

    def original_contexts(self, uuid: str) -> list[str]:
        """The compartments the source lists shipped this flow in.

        Distinct and ordered, because two lists spelling one compartment two ways
        is the normal case and is worth seeing beside the number.
        """
        seen: list[str] = []
        for row in self.sources.get(uuid, ()):
            if row.original_context and row.original_context not in seen:
                seen.append(row.original_context)
        return seen

    @property
    def elsewhere_amounts(self) -> list[float]:
        """The distinct proposed numbers that are published somewhere else."""
        return sorted({row.amount for row in self.elsewhere})

    @property
    def elsewhere_substances(self) -> list[str]:
        """Which substances those numbers are published for, commonest first.

        The substance is the part that carries information.  A number this list
        publishes for `Insecticides, unspecified` is a bucket's number arriving
        under a specific name; a number it publishes for the sodium salt of the
        substance under question is a different story and needs a different
        ruling.  Sparser than it used to be, and that is the point: a proposed
        number the list already publishes in the same category -- the same
        substance within tolerance, or any flow bit for bit -- is published as
        `restated` and never reaches this queue, so a match shown here is
        either in a different category or not quite the same number, and both
        are worth a curator's eye.
        """
        counted = Counter(row.substance for row in self.elsewhere if row.substance)
        return [name for name, _ in counted.most_common()]


def _sources(
    connection: sqlite3.Connection, uuids: list[str]
) -> dict[str, list[SourceRow]]:
    if not uuids or not table_exists(connection, "elementary_flow_sources"):
        return {}
    placeholders = ", ".join("?" * len(uuids))
    rows: dict[str, list[SourceRow]] = {}
    for (
        elementary_uuid,
        list_name,
        list_version,
        source_uuid,
        source_name,
        metadata,
    ) in connection.execute(
        "SELECT elementary_flow_uuid, list_name, list_version, source_flow_uuid, "
        "source_flow_name, source_metadata_json FROM elementary_flow_sources "
        f"WHERE elementary_flow_uuid IN ({placeholders}) "
        "ORDER BY list_name, list_version",
        uuids,
    ):
        payload = load_json(metadata, {}) or {}
        context = payload.get("original_context")
        rows.setdefault(str(elementary_uuid), []).append(
            SourceRow(
                list_name=str(list_name or ""),
                list_version=str(list_version or ""),
                source_flow_uuid=str(source_uuid or ""),
                source_flow_name=str(source_name or ""),
                original_context=(
                    " / ".join(str(part) for part in context)
                    if isinstance(context, list)
                    else str(context or "")
                ),
                unit=str(payload.get("unit") or ""),
                merge_basis=str(payload.get("merge_basis") or ""),
                mapping_file=str(payload.get("mapping_file") or ""),
            )
        )
    return rows


def _changes(
    connection: sqlite3.Connection, flow_object_id: str
) -> list[ChangeRow]:
    if not flow_object_id or not table_exists(connection, "changelog"):
        return []
    return [
        ChangeRow(
            transformer=str(transformer or ""),
            field_name=str(field_name or ""),
            comment=str(comment or ""),
        )
        for transformer, field_name, comment in connection.execute(
            "SELECT transformer, field, comment FROM changelog "
            "WHERE flow_object_id = ? ORDER BY change_index LIMIT ?",
            (flow_object_id, CHANGE_LIMIT),
        )
    ]


def _factors(
    connection: sqlite3.Connection, uuids: list[str], category: str
) -> dict[str, list[FactorRow]]:
    if not uuids or not table_exists(connection, "lcia_characterization_factors"):
        return {}
    placeholders = ", ".join("?" * len(uuids))
    rows: dict[str, list[FactorRow]] = {}
    for elementary_uuid, implemented_by, amount, geography, derivation, source in (
        connection.execute(
            "SELECT f.elementary_flow_uuid, c.implemented_by, f.amount, "
            "f.geography, f.derivation, f.source_flow_uuid "
            "FROM lcia_characterization_factors f "
            "JOIN lcia_impact_categories c ON c.id = f.impact_category_id "
            f"WHERE f.elementary_flow_uuid IN ({placeholders}) AND c.name = ? "
            "ORDER BY c.implemented_by, f.geography",
            (*uuids, category),
        )
    ):
        rows.setdefault(str(elementary_uuid), []).append(
            FactorRow(
                implemented_by=str(implemented_by or ""),
                amount=amount,
                geography=str(geography or ""),
                derivation=str(derivation or ""),
                source_flow_uuid=str(source or ""),
            )
        )
    return rows


def _declined(
    connection: sqlite3.Connection, uuids: list[str], category: str
) -> list[DeclinedRow]:
    if not uuids or not table_exists(connection, "lcia_findings"):
        return []
    placeholders = ", ".join("?" * len(uuids))
    return [
        DeclinedRow(detail=str(detail or ""))
        for (detail,) in connection.execute(
            "SELECT detail FROM lcia_findings "
            f"WHERE elementary_flow_uuid IN ({placeholders}) "
            "AND kind IN ('superseded-value', 'factor-collision') "
            "AND detail LIKE ?",
            (*uuids, f"{category}%"),
        )
    ]


def _flow_facts(
    connection: sqlite3.Connection, uuids: list[str]
) -> dict[str, FlowFacts]:
    """What each flow is called, its unit and its compartment."""
    if not uuids or not table_exists(connection, "elementary_flows"):
        return {}
    placeholders = ", ".join("?" * len(uuids))
    return {
        str(uuid): FlowFacts(
            label=str(label or ""),
            unit=str(unit or ""),
            context_display=str(context or ""),
        )
        for uuid, label, unit, context in connection.execute(
            "SELECT uuid, pref_label_value, unit, context_display "
            f"FROM elementary_flows WHERE uuid IN ({placeholders})",
            uuids,
        )
    }


#: How many published matches to carry per question.  The flag is the finding;
#: the list under it is there to say *where*, and a curator who needs all of them
#: has the substance page.
ELSEWHERE_LIMIT = 12


def _elsewhere(
    connection: sqlite3.Connection, items: list[Any]
) -> dict[str, tuple[list[ElsewhereRow], int]]:
    """For each item, the accepted factors elsewhere stating one of its numbers.

    One query for the whole page rather than one per item: the match is on the
    amount, no index covers it, and fifty scans of the factor table to answer
    fifty questions is fifty times the work of one.
    """
    if not items or not table_exists(connection, "lcia_characterization_factors"):
        return {}
    wanted: set[float] = set()
    for item in items:
        for value in item.payload.get("stated_values") or ():
            if isinstance(value, (int, float)):
                wanted.add(float(value))
    if not wanted:
        return {}

    values = sorted(wanted)
    placeholders = ", ".join("?" * len(values))
    published: dict[float, list[ElsewhereRow]] = {}
    for amount, uuid, category, label, flow_object_id, context, derivation in (
        connection.execute(
            "SELECT f.amount, f.elementary_flow_uuid, c.name, e.pref_label_value, "
            "e.flow_object_id, e.context_display, f.derivation "
            "FROM lcia_characterization_factors f "
            "JOIN lcia_impact_categories c ON c.id = f.impact_category_id "
            "LEFT JOIN elementary_flows e ON e.uuid = f.elementary_flow_uuid "
            f"WHERE c.implemented_by = ? AND f.amount IN ({placeholders})",
            (OUR_IMPLEMENTATION, *values),
        )
    ):
        published.setdefault(float(amount), []).append(
            (
                str(uuid or ""),
                ElsewhereRow(
                    amount=float(amount),
                    substance=str(label or ""),
                    flow_object_id=str(flow_object_id or ""),
                    category=str(category or ""),
                    context_display=str(context or ""),
                    derivation=str(derivation or ""),
                ),
            )
        )

    found: dict[str, tuple[list[ElsewhereRow], int]] = {}
    for item in items:
        own = {
            str(row.get("elementary_flow_uuid") or "")
            for row in item.payload.get("rows") or ()
        }
        rows: list[ElsewhereRow] = []
        seen: set[tuple[float, str]] = set()
        for value in item.payload.get("stated_values") or ():
            if not isinstance(value, (int, float)):
                continue
            for uuid, row in published.get(float(value), ()):
                # The question's own flows are not "elsewhere": they are what is
                # being asked about, and this list publishing a number on one of
                # them is what `derivation` on the row below already says.
                if uuid in own:
                    continue
                # One line per number and flow, not per category: EF ships
                # `Ecotoxicity, freshwater` and `Ecotoxicity, freshwater_organics`
                # with the same value on the same flow, and printing both says
                # the number was found twice when it was found once.
                key = (row.amount, uuid)
                if key in seen:
                    continue
                seen.add(key)
                rows.append(row)
        if rows:
            found[item.item_key] = (rows[:ELSEWHERE_LIMIT], len(rows))
    return found


def questions(
    connection: sqlite3.Connection, page: Page, *, queue: str = ""
) -> Page:
    """The same page of items, with each one's evidence read.

    One query per item rather than one per page: an item names a handful of
    flows, and a curator reads one question at a time.  The one exception is
    `_elsewhere`, which matches on an unindexed amount and is asked once for the
    whole page.

    *queue* names the queue being rendered.  The published-elsewhere search is
    run for `proposed-factor` alone: it is the queue whose question is "should
    this list publish a number nobody here states", and the answer turns on
    whether that number is already published against something else.
    """
    elsewhere = (
        _elsewhere(connection, page.rows)
        if queue == str(ReviewQueue.PROPOSED_FACTOR)
        else {}
    )
    answered: list[Question] = []
    for item in page.rows:
        rows = item.payload.get("rows") or []
        uuids = [str(row.get("elementary_flow_uuid") or "") for row in rows]
        uuids = [uuid for uuid in uuids if uuid]
        category = str(item.payload.get("category") or "")
        answered.append(
            Question(
                item=item,
                flows=rows,
                sources=_sources(connection, uuids),
                changes=_changes(connection, item.flow_object_id),
                factors=_factors(connection, uuids, category),
                declined=_declined(connection, uuids, category),
                flow_facts=_flow_facts(connection, uuids),
                elsewhere=elsewhere.get(item.item_key, ([], 0))[0],
                elsewhere_total=elsewhere.get(item.item_key, ([], 0))[1],
            )
        )
    return Page(
        rows=answered, total=page.total, number=page.number, size=page.size
    )


# ─── Browsing what `characterise` published ──────────────────────────────────
# The queue above is a backlog to drain.  Everything below is the opposite: the
# layer as it stands, for a reader who wants to know what this list says a
# substance is worth and how that compares to what the two publishers say.


@dataclass
class RunSummary:
    """Which `characterise` run these pages are describing.

    Recorded rather than assumed, for the reason `lcia_runs.build_run_id` exists:
    the factors are a projection of one build, and a reader holding a factor and
    a flow needs to know they came from the same run.
    """

    run_id: str = ""
    started_at: str = ""
    finished_at: str = ""
    build_run_id: str = ""
    stats: dict[str, Any] = field(default_factory=dict)

    @property
    def ran(self) -> bool:
        return bool(self.run_id)


#: A published category's IRI ends ``…/<method>/<version>/<implementation>/
#: <timeframe>/<slug>``, which `lcia.categories.impact_category_iri` mints.  Its
#: last segment is the only place the category's own slug is written down -- the
#: table stores the publisher-independent *name*, which is prose and not a URL --
#: and its method and implementation segments are the only places those slugs
#: are.  All three are read back off the identifier rather than re-derived by
#: slugifying a name, for the reason #13 gives: a second way of naming a thing
#: is a second thing.
_IRI_SEGMENTS = 5


def _identity(iri: str) -> tuple[str, str, str]:
    """``(method slug, implementation slug, category slug)`` from a category IRI.

    Three empty strings where the IRI is not one of ours, which renders a category
    the detail page cannot be reached from rather than raising on the index.
    """
    parts = str(iri or "").rsplit("/", _IRI_SEGMENTS)
    if len(parts) <= _IRI_SEGMENTS:
        return "", "", ""
    return parts[1], parts[3], parts[5]


@dataclass
class ImplementationCount:
    """One implementation's share of one impact category."""

    implemented_by: str
    factors: int = 0
    flows: int = 0
    non_zero: int = 0

    @property
    def zeros(self) -> int:
        return self.factors - self.non_zero


@dataclass
class ImplementationSummary:
    """One implementation across the whole run, and what became of it.

    More than a total, because a total of zero is the one number in this section
    a reader cannot act on.  `ecoinvent Centre — 0` reads as "the file was
    empty", and the file was not empty: 27,415 factors were stated and every one
    of them named a source flow no consensus flow was merged from, because the
    build that was characterised never merged ecoinvent's list. The run counted
    both halves, so the page says both rather than leaving the difference to be
    guessed at.
    """

    implemented_by: str
    #: Whether this is the implementation this list publishes -- the one column
    #: that is always there, and so the one that goes first.
    ours: bool = False
    factors: int = 0
    non_zero: int = 0
    #: What the publisher's own file states, before anything was matched.
    #: ``None`` where the run counted no such thing, which is the case for an
    #: implementation that states nothing and derives everything: ours.
    stated: int | None = None
    #: How many source flows of this implementation's list the merge placed on a
    #: consensus flow.  ``None`` for an implementation whose factors already name
    #: consensus flows and so are never matched.
    merged: int | None = None
    #: Source flows carrying factors that reached no consensus flow.
    unreached: int = 0

    @property
    def silent(self) -> bool:
        """Nothing of this implementation reached the published layer."""
        return not self.factors

    @property
    def unpublished(self) -> int:
        """Stated and not published, where the run counted both."""
        return max(0, (self.stated or 0) - self.factors)


@dataclass
class CategoryRow:
    """One impact category, with every implementation of it side by side.

    Keyed on the name, which is *ours*: the JRC calls it `Ecotoxicity,
    freshwater` and ecoinvent calls it `ecotoxicity: freshwater`, and the
    crosswalk in `data/lcia-impact-categories.json` is the only thing that knows
    those are one category.  A page keyed on either publisher's own name would
    show 50 categories that never line up.
    """

    name: str
    method_slug: str = ""
    version: str = ""
    slug: str = ""
    indicator: str = ""
    area_of_protection: str = ""
    unit_iri: str = ""
    #: By ``implemented_by`` rather than in column order, because the set of
    #: implementations is data.  A list positioned against a column order is what
    #: made a third implementation a template change; a mapping the template looks
    #: names up in is not.
    counts: dict[str, ImplementationCount] = field(default_factory=dict)

    @property
    def unit(self) -> str:
        """The reference unit, as the last segment of its IRI.

        An IRI is what the record holds -- inventing a second identity for a unit
        is #13's mistake -- and a table cell is not where a reader wants to read
        one.
        """
        return self.unit_iri.rsplit("/", 1)[-1] if self.unit_iri else ""

    @property
    def total(self) -> int:
        return sum(count.factors for count in self.counts.values())

    @property
    def linkable(self) -> bool:
        """Whether the category has a detail page to link to."""
        return bool(self.method_slug and self.version and self.slug)

    def count(self, implemented_by: str) -> ImplementationCount | None:
        return self.counts.get(implemented_by)


@dataclass
class MethodRow:
    """One LCIA method at one version, and the categories it publishes.

    A section of its own rather than a flag on a row.  EF 3.1 is the only method
    characterised today and it is not the only method: two methods share neither
    a category list nor a reference unit, and one table over both would put
    `Climate change` of one beside `Climate change` of the other on the strength
    of the names matching -- which is exactly the mistake the crosswalk exists to
    stop being made between two implementations of *one* method.
    """

    name: str
    version: str
    slug: str = ""
    categories: list[CategoryRow] = field(default_factory=list)
    #: Every implementation of *this* method, ours first and the rest by weight.
    #: Taken from the rows, never from a list written into a template.
    implementations: list[str] = field(default_factory=list)
    #: The same implementations with what the run counted around each: what its
    #: own file stated, how much of it reached this layer, and why where it did
    #: not.  Per method rather than per run, because two methods' figures for one
    #: implementer are two different facts.
    summaries: list[ImplementationSummary] = field(default_factory=list)

    @property
    def label(self) -> str:
        return f"{self.name} {self.version}".strip()

    @property
    def ours(self) -> list[str]:
        """The implementations this list publishes: the leading column."""
        return [name for name in self.implementations if name == OUR_IMPLEMENTATION]

    @property
    def inputs(self) -> list[str]:
        """The implementations this list read, in the order they are listed."""
        return [name for name in self.implementations if name != OUR_IMPLEMENTATION]


@dataclass
class FactorsOverview:
    """Everything `/factors/` shows."""

    run: RunSummary = field(default_factory=RunSummary)
    methods: list[MethodRow] = field(default_factory=list)

    @property
    def implementations(self) -> list[ImplementationSummary]:
        """Every method's implementations, for a caller that wants the count.

        Not what the page renders: the cards belong inside the method section,
        because "ecoinvent Centre — 26,479 factors" is a fact about one method
        and reads as a fact about the run.
        """
        return [
            summary for method in self.methods for summary in method.summaries
        ]

    @property
    def categories(self) -> list[CategoryRow]:
        """Every category of every method, for a caller that wants the count."""
        return [row for method in self.methods for row in method.categories]


def _run(connection: sqlite3.Connection) -> RunSummary:
    row = connection.execute(
        "SELECT run_id, started_at, finished_at, build_run_id, stats_json "
        "FROM lcia_runs ORDER BY started_at DESC LIMIT 1"
    ).fetchone()
    if row is None:
        return RunSummary()
    return RunSummary(
        run_id=row["run_id"] or "",
        started_at=row["started_at"] or "",
        finished_at=row["finished_at"] or "",
        build_run_id=row["build_run_id"] or "",
        stats=load_json(row["stats_json"], {}) or {},
    )


def run_stats(connection: sqlite3.Connection) -> dict[str, Any]:
    """What the last `characterise` run counted, for a page that needs only that.

    Separate from :func:`overview` because reading a stats blob should not cost
    what building the category table costs.
    """
    return _run(connection).stats


#: What this list publishes under its own name.  Read from the method files
#: rather than spelled here, because it is the same string `characterise` stamps
#: on every factor it derived, for every method it derived one for.
OUR_IMPLEMENTATION = CONSENSUS_IMPLEMENTATION


def _method_labels() -> dict[str, str]:
    """``method slug -> the name and version a reader knows it by``.

    A row of the difference report and of the coverage summary carries the slug,
    because that is what identifies the method; a page shows `EF 3.1`.  A slug the
    crosswalk no longer registers keeps its slug rather than disappearing: the
    run wrote the row, and hiding which method it was about would be worse than
    showing an unfamiliar word.
    """
    return {
        slug: method.label_with_version
        for slug, method in lcia_method_by_slug().items()
    }


def _names_by_slug() -> dict[tuple[str, str], str]:
    """``(method slug, category slug) -> the name this list publishes``.

    Keyed on the method as well as the slug, because a slug names a category
    inside one method: EF 3.1 and a second method can both have an
    ``acidification``, and a map keyed on the slug alone would title one of them
    with the other's name.
    """
    return {
        (method.slug, definition.slug): definition.name
        for method in lcia_methods()
        for definition in method.categories
    }


def _ordering(weights: dict[str, int]):
    """Ours first, then by how much each implementation says.

    The one guaranteed column goes first because it is the answer to the question
    the section is asked -- what does *this list* say this substance is worth --
    and the rest follow by weight, so a reader sees where the numbers are.
    """

    def key(name: str) -> tuple[int, int, str]:
        return (0 if name == OUR_IMPLEMENTATION else 1, -weights.get(name, 0), name)

    return key


def _summaries(
    totals: dict[tuple[str, str], ImplementationCount],
    slugs: dict[tuple[str, str], str],
    stats: dict[str, Any],
) -> dict[str, list[ImplementationSummary]]:
    """Each implementation's totals, per method, with what the run counted around
    them.

    Keyed on the method as well, because the run keys its own counts that way:
    two methods' ``brightway-flows`` rows are two different things, and an
    implementer that renders both states a different number of factors for each.

    The stats blob keys everything on ``{method}_{implementation}``, and the
    implementation slug is read off the category IRI -- so an implementation
    nothing in this build has heard of still gets its totals, and gets none of
    the surrounding numbers, which is the honest answer rather than a zero that
    would read as "nothing was stated".
    """
    summaries: dict[str, list[ImplementationSummary]] = {}
    for (method_slug, name), count in totals.items():
        implementation_slug = slugs.get((method_slug, name), "")
        prefix = (
            f"{method_slug}_{implementation_slug.replace('-', '_')}"
            if implementation_slug
            else ""
        )
        stated = stats.get(f"{prefix}_factors_stated") if prefix else None
        merged = stats.get(f"{prefix}_source_flows_merged") if prefix else None
        summaries.setdefault(method_slug, []).append(
            ImplementationSummary(
                implemented_by=name,
                ours=name == OUR_IMPLEMENTATION,
                factors=count.factors,
                non_zero=count.non_zero,
                stated=int(stated) if isinstance(stated, (int, float)) else None,
                merged=int(merged) if isinstance(merged, (int, float)) else None,
                unreached=(
                    int(stats.get(f"{prefix}_flow-not-reached", 0) or 0)
                    if prefix
                    else 0
                ),
            )
        )
    return summaries


def overview(connection: sqlite3.Connection) -> FactorsOverview:
    """Every characterised method, its categories, and every implementation.

    **One query over the category rows.**  The three counts are read from them
    rather than derived: `characterise` wrote them with the factors in hand, and
    grouping over every factor to recover them costs 519 ms against 665,521 rows
    -- on the landing page of the section, for numbers the run already knew.  The
    columns are not a cache, they are where the count is kept; the view
    `lcia_flow_factor_counts` is the one that must not drift, because it answers a
    question about a *flow* and the flow table carries a count of its own.
    """
    if not table_exists(connection, "lcia_impact_categories"):
        return FactorsOverview()

    methods: dict[tuple[str, str], MethodRow] = {}
    categories: dict[tuple[str, str, str], CategoryRow] = {}
    totals: dict[tuple[str, str], ImplementationCount] = {}
    #: ``(method slug, implemented_by) -> implementation slug``, off the IRI,
    #: which is where the run's own statistic keys come from.
    slugs: dict[tuple[str, str], str] = {}
    for row in connection.execute(
        "SELECT category.iri, category.name, category.version, "
        "category.implemented_by, category.indicator, category.area_of_protection, "
        "category.unit_iri, category.factor_count, category.flow_count, "
        "category.non_zero_factor_count, method.name AS method_name "
        "FROM lcia_impact_categories AS category "
        "LEFT JOIN lcia_methods AS method ON method.id = category.method_id "
        "ORDER BY method.name, category.version, category.name"
    ):
        method_slug, implementation_slug, slug = _identity(row["iri"])
        version = row["version"] or ""
        method_name = row["method_name"] or method_slug.upper()
        method = methods.setdefault(
            (method_name, version),
            MethodRow(name=method_name, version=version, slug=method_slug),
        )
        key = (method_name, version, row["name"])
        category = categories.get(key)
        if category is None:
            category = CategoryRow(
                name=row["name"],
                method_slug=method_slug,
                version=version,
                slug=slug,
                indicator=row["indicator"] or "",
                area_of_protection=row["area_of_protection"] or "",
                unit_iri=row["unit_iri"] or "",
            )
            categories[key] = category
            method.categories.append(category)
        implemented_by = row["implemented_by"] or ""
        count = ImplementationCount(
            implemented_by=implemented_by,
            factors=int(row["factor_count"] or 0),
            flows=int(row["flow_count"] or 0),
            non_zero=int(row["non_zero_factor_count"] or 0),
        )
        category.counts[implemented_by] = count
        if implemented_by not in method.implementations:
            method.implementations.append(implemented_by)
        slugs[(method_slug, implemented_by)] = implementation_slug
        total = totals.setdefault(
            (method_slug, implemented_by),
            ImplementationCount(implemented_by=implemented_by),
        )
        total.factors += count.factors
        total.non_zero += count.non_zero

    weights: dict[str, int] = {}
    for (_method_slug, name), count in totals.items():
        weights[name] = weights.get(name, 0) + count.factors
    ordering = _ordering(weights)
    run = _run(connection)
    summaries = _summaries(totals, slugs, run.stats)
    for method in methods.values():
        method.implementations.sort(key=ordering)
        method.summaries = sorted(
            summaries.get(method.slug, []),
            key=lambda summary: ordering(summary.implemented_by),
        )
    return FactorsOverview(
        run=run,
        methods=sorted(methods.values(), key=lambda row: (row.name, row.version)),
    )


@dataclass
class CategoryDetail:
    """One impact category of one method, and every implementation of it.

    The row of the index, opened.  What a reader wants from a category is the
    numbers under it -- "which substances does this list say matter here, and by
    how much" -- and the index can only ever say how many there are.
    """

    name: str
    method: str = ""
    method_slug: str = ""
    version: str = ""
    slug: str = ""
    indicator: str = ""
    area_of_protection: str = ""
    unit_iri: str = ""
    description: str = ""
    #: The category row's id under each implementation, which is what the factor
    #: table joins on.  One category is as many rows here as there are
    #: implementations of it.
    ids: dict[str, str] = field(default_factory=dict)
    counts: dict[str, ImplementationCount] = field(default_factory=dict)
    #: How each implementation is spelled in a URL, read off its own category's
    #: IRI.  `implemented_by` is prose with an em dash in it -- `European
    #: Commission — JRC` -- and the comparison page has to name two of them in a
    #: query string.  Off the IRI rather than slugified here, because the IRI
    #: segment is the published spelling and a second one would be a second thing.
    slugs: dict[str, str] = field(default_factory=dict)
    #: Ours first, then by weight -- the same order the index columns are in.
    implementations: list[str] = field(default_factory=list)

    @property
    def unit(self) -> str:
        return self.unit_iri.rsplit("/", 1)[-1] if self.unit_iri else ""

    @property
    def label(self) -> str:
        return f"{self.method} {self.version}".strip()

    def count(self, implemented_by: str) -> ImplementationCount | None:
        return self.counts.get(implemented_by)

    def named(self, slug: str) -> str:
        """The implementation a URL segment names, or ``""`` if this category has
        no such implementation."""
        return next(
            (name for name, value in self.slugs.items() if value == slug), ""
        )


def category(
    connection: sqlite3.Connection, *, method: str, version: str, slug: str
) -> CategoryDetail | None:
    """One category, addressed the way its IRI addresses it.

    By ``(method, version, slug)`` and not by name, because a name is prose --
    `Ecotoxicity, freshwater` -- and because two methods may well use one name for
    two different things.  ``None`` where no such category was characterised,
    which the view turns into a 404 rather than an empty table.
    """
    if not table_exists(connection, "lcia_impact_categories"):
        return None
    detail: CategoryDetail | None = None
    for row in connection.execute(
        "SELECT category.*, method.name AS method_name "
        "FROM lcia_impact_categories AS category "
        "LEFT JOIN lcia_methods AS method ON method.id = category.method_id "
        "WHERE category.version = ?",
        (version,),
    ):
        method_slug, implementation_slug, category_slug = _identity(row["iri"])
        if method_slug != method or category_slug != slug:
            continue
        if detail is None:
            detail = CategoryDetail(
                name=row["name"],
                method=row["method_name"] or method_slug.upper(),
                method_slug=method_slug,
                version=version,
                slug=slug,
                indicator=row["indicator"] or "",
                area_of_protection=row["area_of_protection"] or "",
                unit_iri=row["unit_iri"] or "",
                description=row["description"] or "",
            )
        implemented_by = row["implemented_by"] or ""
        detail.ids[implemented_by] = str(row["id"])
        detail.slugs[implemented_by] = implementation_slug
        detail.counts[implemented_by] = ImplementationCount(
            implemented_by=implemented_by,
            factors=int(row["factor_count"] or 0),
            flows=int(row["flow_count"] or 0),
            non_zero=int(row["non_zero_factor_count"] or 0),
        )
    if detail is None:
        return None
    weights = {name: count.factors for name, count in detail.counts.items()}
    detail.implementations = sorted(detail.counts, key=_ordering(weights))
    return detail


@dataclass
class CategoryFactorRow:
    """What every implementation says one flow is worth under one category."""

    elementary_flow_uuid: str
    flow_name: str = ""
    context_display: str = ""
    geography: str = ""
    amounts: dict[str, float] = field(default_factory=dict)
    #: How this list arrived at its number, where it published one.
    derivation: str = ""

    @property
    def ours(self) -> float | None:
        return self.amounts.get(OUR_IMPLEMENTATION)

    @property
    def disputed(self) -> bool:
        """Somebody states a number here and this list publishes none.

        The row a curator is looking for on this page: not a disagreement between
        two publishers, which the difference report ranks, but a substance this
        category leaves uncharacterised in the published layer.
        """
        return bool(self.amounts) and OUR_IMPLEMENTATION not in self.amounts


#: What the category page can be ordered by.  Nothing per implementation, for
#: the reason the difference report states: a column that only exists when a
#: particular list is loaded is what this shape removes.
_CATEGORY_SORTS = {
    "amount": "max(abs(factor.amount))",
    "flow": "max(flow.pref_label_value)",
}


def category_factors(
    connection: sqlite3.Connection,
    detail: CategoryDetail,
    *,
    query: str = "",
    page: int = 1,
    sort: str = "",
) -> Page[CategoryFactorRow]:
    """Every factor under one category, as many implementations wide as there are.

    Paged over *(flow, place)* pairs rather than over factor rows, for the reason
    the difference report is: the table holds a row per implementation, so a page
    of fifty rows would be twenty-five comparisons under two implementations and
    seventeen under three -- and would change size the day a third is loaded.

    Sorted by the largest number stated by anybody, descending: this page is read
    to find out which substances a category weighs heavily, and the answer to that
    is not alphabetical.
    """
    if not detail.ids or not table_exists(
        connection, "lcia_characterization_factors"
    ):
        return Page()
    placeholders = ", ".join("?" * len(detail.ids))
    where = [f"factor.impact_category_id IN ({placeholders})"]
    parameters: list[Any] = list(detail.ids.values())
    if query:
        where.append(
            "(flow.pref_label_value LIKE ? OR flow.context_display LIKE ? "
            "OR factor.elementary_flow_uuid = ?)"
        )
        parameters.extend([f"%{query}%", f"%{query}%", query])
    source = (
        "FROM lcia_characterization_factors AS factor "
        "LEFT JOIN elementary_flows AS flow "
        "ON flow.uuid = factor.elementary_flow_uuid "
        f"WHERE {' AND '.join(where)}"
    )
    grouping = "GROUP BY factor.elementary_flow_uuid, factor.geography"
    total = int(
        connection.execute(
            f"SELECT count(*) FROM (SELECT 1 {source} {grouping})", parameters
        ).fetchone()[0]
    )
    number = clamp_page(page, total)
    ordering = order_by(
        sort or "-amount", _CATEGORY_SORTS, _CATEGORY_SORTS["amount"]
    )
    keys = [
        (row["elementary_flow_uuid"], row["geography"] or "")
        for row in connection.execute(
            f"SELECT factor.elementary_flow_uuid, factor.geography {source} "
            f"{grouping} ORDER BY {ordering} LIMIT ? OFFSET ?",
            (*parameters, PAGE_SIZE, (number - 1) * PAGE_SIZE),
        )
    ]
    return Page(
        rows=_category_wide(connection, detail, keys),
        total=total,
        number=number,
        size=PAGE_SIZE,
    )


def _category_wide(
    connection: sqlite3.Connection,
    detail: CategoryDetail,
    keys: list[tuple[str, str]],
) -> list[CategoryFactorRow]:
    """One page of pairs, with every implementation's number on each."""
    if not keys:
        return []
    by_id = {value: name for name, value in detail.ids.items()}
    pairs = ", ".join("(?, ?)" for _ in keys)
    parameters = [value for key in keys for value in key]
    rows: dict[tuple[str, str], CategoryFactorRow] = {}
    for row in connection.execute(
        "SELECT factor.impact_category_id, factor.elementary_flow_uuid, "
        "factor.geography, factor.amount, factor.derivation, "
        "flow.pref_label_value, flow.context_display "
        "FROM lcia_characterization_factors AS factor "
        "LEFT JOIN elementary_flows AS flow "
        "ON flow.uuid = factor.elementary_flow_uuid "
        f"WHERE factor.impact_category_id IN ({', '.join('?' * len(detail.ids))}) "
        f"AND (factor.elementary_flow_uuid, factor.geography) IN ({pairs})",
        (*detail.ids.values(), *parameters),
    ):
        key = (row["elementary_flow_uuid"], row["geography"] or "")
        entry = rows.setdefault(
            key,
            CategoryFactorRow(
                elementary_flow_uuid=row["elementary_flow_uuid"],
                flow_name=row["pref_label_value"] or "",
                context_display=row["context_display"] or "",
                geography=row["geography"] or "",
            ),
        )
        implemented_by = by_id.get(str(row["impact_category_id"]), "")
        entry.amounts[implemented_by] = float(row["amount"])
        if row["derivation"]:
            entry.derivation = row["derivation"]
    # In the order the page asked for them, which the second query does not keep.
    return [rows[key] for key in keys if key in rows]


@dataclass
class DifferenceRow:
    """One triple more than one published implementation states.

    Read from the long-form table and assembled wide here, because a reader
    comparing implementations wants them beside each other and a table cannot have
    a column per implementation without knowing how many there are.  `amounts` is
    keyed by `implemented_by`, and the page takes its columns from the set the
    query saw rather than from a list written into a template.
    """

    elementary_flow_uuid: str
    #: Which method's category this is about.  On the row rather than left to the
    #: page, because a category name is only a name inside a method.
    method: str = ""
    #: The same method as a reader knows it: `EF 3.1`.
    method_label: str = ""
    flow_name: str = ""
    context_display: str = ""
    category: str = ""
    geography: str = ""
    amounts: dict[str, float] = field(default_factory=dict)
    band: str = ""
    ratio: float | None = None
    derivation: str = ""

    @property
    def widest(self) -> str:
        """Which implementation states the largest number, by magnitude.

        A ratio alone does not say which way round it is, and "which of them is
        higher" is the first question a reader of this table asks.  Empty where
        they all state one number, because then nobody is higher.
        """
        if len(set(self.amounts.values())) < 2:
            return ""
        return max(self.amounts, key=lambda name: abs(self.amounts[name]))


#: The bands, in the order a reader wants them: widest disagreement first, and
#: the incomparable one -- a stated zero against a number -- at the top, because
#: it is the one no ratio can rank.
BAND_ORDER: tuple[str, ...] = (
    "incomparable",
    "over-100x",
    "100x",
    "10x",
    "2x",
    "within-tolerance",
    "identical",
)

#: What the report can be ordered by.  Nothing per implementation: with the rows
#: long, "sort by the JRC's number" is a sort over a subset, and a column that
#: only exists when a particular list is loaded is the thing this shape removed.
_DIFFERENCE_SORTS = {
    "ratio": "coalesce(max(difference.ratio), 1e308)",
    "flow": "max(flow.pref_label_value)",
    "category": "difference.category_slug",
}


def differences(
    connection: sqlite3.Connection,
    *,
    query: str = "",
    band: str = "",
    page: int = 1,
    sort: str = "",
) -> tuple[Page[DifferenceRow], list[str]]:
    """The difference report, browsable, with the implementations it compares.

    Sorted by ratio descending by default, which is the order the report is read
    in: the widest disagreements first.  A band with no ratio -- a stated zero
    against a number -- sorts above everything, because it is not a smaller
    disagreement than 1,441x, it is a different kind of one.

    Paged over *triples* rather than over rows: the table holds one row per
    implementation, and a page of fifty rows would be twenty-five comparisons with
    two implementations and ten with five.
    """
    if not table_exists(connection, "lcia_differences"):
        return Page(), []

    names = _names_by_slug()
    where = ["1 = 1"]
    parameters: list[Any] = []
    if band:
        # A group or an exact band, resolved the same way everywhere the filter
        # is offered, so a card, a chip and a hand-typed URL agree.
        members = band_members(band)
        where.append(f"difference.band IN ({', '.join('?' * len(members))})")
        parameters.extend(members)
    if query:
        where.append(
            "(flow.pref_label_value LIKE ? OR difference.elementary_flow_uuid = ? "
            "OR difference.category_slug LIKE ?)"
        )
        parameters.extend([f"%{query}%", query, f"%{query}%"])
    clause = " AND ".join(where)
    source = (
        "FROM lcia_differences AS difference "
        "LEFT JOIN elementary_flows AS flow "
        "ON flow.uuid = difference.elementary_flow_uuid "
        f"WHERE {clause}"
    )
    grouping = (
        "GROUP BY difference.method, difference.elementary_flow_uuid, "
        "difference.category_slug, difference.geography"
    )
    total = int(
        connection.execute(
            f"SELECT count(*) FROM (SELECT 1 {source} {grouping})", parameters
        ).fetchone()[0]
    )
    number = clamp_page(page, total)
    ordering = order_by(
        sort or "-ratio", _DIFFERENCE_SORTS, _DIFFERENCE_SORTS["ratio"]
    )
    keys = [
        (
            row["method"],
            row["elementary_flow_uuid"],
            row["category_slug"],
            row["geography"],
        )
        for row in connection.execute(
            "SELECT difference.method, difference.elementary_flow_uuid, "
            "difference.category_slug, "
            f"difference.geography {source} {grouping} "
            f"ORDER BY {ordering} LIMIT ? OFFSET ?",
            (*parameters, PAGE_SIZE, (number - 1) * PAGE_SIZE),
        )
    ]
    return Page(
        rows=_wide(connection, keys, names=names),
        total=total,
        number=number,
        size=PAGE_SIZE,
    ), compared_implementations(connection)


def _wide(
    connection: sqlite3.Connection,
    keys: list[tuple[str, str, str, str]],
    *,
    names: dict[tuple[str, str], str],
) -> list[DifferenceRow]:
    """One page of triples, with every implementation's number on each.

    A second query rather than a window function or a pivot: the page is fifty
    triples, and what it needs is every row of those fifty, whichever
    implementations they belong to.
    """
    if not keys:
        return []
    labels = _method_labels()
    placeholders = ", ".join("(?, ?, ?, ?)" * 1 for _ in keys)
    parameters = [value for key in keys for value in key]
    rows: dict[tuple[str, str, str, str], DifferenceRow] = {}
    for row in connection.execute(
        "SELECT difference.*, flow.pref_label_value, flow.context_display "
        "FROM lcia_differences AS difference "
        "LEFT JOIN elementary_flows AS flow "
        "ON flow.uuid = difference.elementary_flow_uuid "
        "WHERE (difference.method, difference.elementary_flow_uuid, "
        "difference.category_slug, "
        f"difference.geography) IN ({placeholders})",
        parameters,
    ):
        key = (
            row["method"],
            row["elementary_flow_uuid"],
            row["category_slug"],
            row["geography"],
        )
        entry = rows.setdefault(
            key,
            DifferenceRow(
                method=row["method"] or "",
                method_label=labels.get(row["method"] or "", row["method"] or ""),
                elementary_flow_uuid=row["elementary_flow_uuid"],
                flow_name=row["pref_label_value"] or "",
                context_display=row["context_display"] or "",
                category=names.get(
                    (row["method"], row["category_slug"]), row["category_slug"]
                ),
                geography=row["geography"] or "",
                band=row["band"] or "",
                ratio=row["ratio"],
                derivation=row["derivation"] or "",
            ),
        )
        entry.amounts[row["implemented_by"]] = float(row["amount"])
    # In the order the page asked for them, which the second query does not keep.
    return [rows[key] for key in keys if key in rows]


def compared_implementations(connection: sqlite3.Connection) -> list[str]:
    """Every implementation the report compares, in the order columns go in."""
    if not table_exists(connection, "lcia_differences"):
        return []
    return [
        row["implemented_by"]
        for row in connection.execute(
            "SELECT DISTINCT implemented_by FROM lcia_differences "
            "ORDER BY implemented_by"
        )
    ]


def band_counts(connection: sqlite3.Connection) -> list[tuple[str, int]]:
    """Every band and how many triples are in it, in reading order.

    Triples and not rows: the table holds one row per implementation, so counting
    rows would say a comparison between two of them is two comparisons -- and
    would say something different again once a third implementation is compared,
    which is the kind of number that quietly stops matching the run's own stats.
    """
    if not table_exists(connection, "lcia_differences"):
        return []
    counted = {
        row["band"]: int(row["triples"] or 0)
        for row in connection.execute(
            "SELECT band, count(*) AS triples FROM ("
            "  SELECT DISTINCT method, elementary_flow_uuid, category_slug, "
            "         geography, band"
            "  FROM lcia_differences"
            ") GROUP BY band"
        )
    }
    return [(band, counted.get(band, 0)) for band in BAND_ORDER]


#: The four answers a reader actually wants, and the bands each is made of.
#:
#: Seven bands is the resolution the *report* is banded at, and it is the wrong
#: resolution for a summary: `2x`, `10x`, `100x` and `over-100x` are one answer --
#: *these two do not agree about this number* -- split four ways, and a card for
#: each says four times over what one card says once.  The line that carries
#: meaning is `FACTOR_TOLERANCE`, the same 2% `contested_cas` draws between a
#: rounding and a disagreement, and either side of it is a different kind of
#: event.  The ratio in the table is still the exact one and every row still
#: carries its own band, so nothing is rounded away -- only the summary is.
#:
#: A group is also a filter value, so a card links to the rows it counts.
BAND_GROUPS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("incomparable", "Incomparable", (str(Band.INCOMPARABLE),)),
    (
        "outside-tolerance",
        "Outside tolerance",
        (
            str(Band.OVER_100X),
            str(Band.UP_TO_100X),
            str(Band.UP_TO_10X),
            str(Band.UP_TO_2X),
        ),
    ),
    ("within-tolerance", "Within tolerance", (str(Band.WITHIN_TOLERANCE),)),
    ("identical", "Identical", (str(Band.IDENTICAL),)),
)

_GROUP_MEMBERS: dict[str, tuple[str, ...]] = {
    slug: members for slug, _label, members in BAND_GROUPS
}


def band_members(band: str) -> tuple[str, ...]:
    """Every band one filter value selects.

    A group selects its members; anything else selects itself, so a link to an
    exact band -- `?band=10x`, which the tables and the published report still
    spell -- goes on working after the summary stopped offering it as a card.
    """
    return _GROUP_MEMBERS.get(band, (band,))


def band_groups(connection: sqlite3.Connection) -> list[tuple[str, str, int]]:
    """The four groups, labelled and counted, in reading order.

    Counted from the bands rather than re-derived from the rows, so the summary
    and the report cannot come to different totals.
    """
    counted = dict(band_counts(connection))
    return [
        (slug, label, sum(counted.get(member, 0) for member in members))
        for slug, label, members in BAND_GROUPS
    ]


#: How many flow labels to read in one statement.  The rows two implementations
#: differ on under one category are few -- 307 over all 25 of them in the build
#: of 2026-08-17 -- but a page that puts a set of unknown size into one `IN`
#: clause is a page that stops working on the build where they are not few.
_LOOKUP_CHUNK = 500


def _flow_labels(
    connection: sqlite3.Connection, uuids: list[str]
) -> dict[str, tuple[str, str]]:
    """``uuid -> (name, compartment)``, for the rows a page is about to show."""
    labels: dict[str, tuple[str, str]] = {}
    for start in range(0, len(uuids), _LOOKUP_CHUNK):
        batch = uuids[start : start + _LOOKUP_CHUNK]
        for row in connection.execute(
            "SELECT uuid, pref_label_value, context_display FROM elementary_flows "
            f"WHERE uuid IN ({', '.join('?' * len(batch))})",
            batch,
        ):
            labels[str(row["uuid"])] = (
                row["pref_label_value"] or "",
                row["context_display"] or "",
            )
    return labels


@dataclass
class PairRow:
    """One (flow, place) two implementations both state, and disagree about.

    `amounts` holds the two of them and nothing else, so `higher` is the higher
    of the pair rather than the higher of everybody -- which is the whole
    difference between this page and the report it narrows.
    """

    elementary_flow_uuid: str
    geography: str = ""
    flow_name: str = ""
    context_display: str = ""
    amounts: dict[str, float] = field(default_factory=dict)
    band: str = ""
    ratio: float | None = None
    #: Which of the two states the larger number, by magnitude.  A ratio does not
    #: say which way round it is, and that is the first thing a reader asks.
    higher: str = ""
    #: What this list published for the row.  `None` where it published nothing,
    #: which is what a disagreement between two publishers usually leaves behind:
    #: a question in a queue.
    ours: float | None = None
    derivation: str = ""

    @property
    def queued(self) -> bool:
        """Both of them state a number here and this list publishes none."""
        return self.ours is None


@dataclass
class PairComparison:
    """What two implementations of one category say about each other.

    **The headline is the agreement**, as it is on the report this narrows: a
    page that opens on the rows two implementations differ about, without saying
    how many they do not, invites a reader to read a modelling choice as an
    error.  `shared` is what both state, `identical` how much of that is the same
    number to the last bit, and `only` how many each states that the other does
    not -- a fact about two differently sized flow lists rather than a
    disagreement, which is why it is counted here and not listed below.
    """

    left: str = ""
    right: str = ""
    shared: int = 0
    identical: int = 0
    #: Triples only one of the two states, by implementation.
    only: dict[str, int] = field(default_factory=dict)
    #: Every group a difference can fall in except `identical`, in reading order
    #: and including the empty ones: "nothing here is incomparable" is an answer.
    #: `(slug, label, count)`, the same four the index summarises with.
    bands: list[tuple[str, str, int]] = field(default_factory=list)

    @property
    def comparable(self) -> bool:
        """Whether there are two implementations here to compare at all."""
        return bool(self.left and self.right)

    @property
    def pair(self) -> list[str]:
        """The two, in column order."""
        return [self.left, self.right]

    @property
    def differing(self) -> int:
        return self.shared - self.identical

    @property
    def agreement(self) -> float:
        """The share of what both state that they state identically, 0 to 1."""
        return self.identical / self.shared if self.shared else 0.0

    @property
    def includes_ours(self) -> bool:
        """Whether this list is one of the two being compared.

        Where it is not, what it published about a row is a column of its own;
        where it is, that number is already on the page.
        """
        return OUR_IMPLEMENTATION in (self.left, self.right)


def default_pair(detail: CategoryDetail) -> tuple[str, str] | None:
    """The two implementations a category's comparison opens on.

    Two publishers rather than this list and a publisher, where the category has
    two: this list's implementation is *derived* from theirs and agrees with one
    of them by construction on nearly every row, so the comparison carrying
    information is between two independent renderings of the method.  Ours is one
    click away, and is in the pair where nobody else fills the category.

    ``None`` where fewer than two implementations state anything here, which is a
    category that cannot be compared rather than one that agrees with itself.
    """
    speaking = [
        name for name in detail.implementations if detail.counts[name].factors
    ]
    others = [name for name in speaking if name != OUR_IMPLEMENTATION]
    chosen = others if len(others) >= 2 else speaking
    return (chosen[0], chosen[1]) if len(chosen) >= 2 else None


#: What the comparison can be ordered by.  Sorted in Python and not in SQL,
#: because the band is: it comes from `lcia.differences.band_for`, the same
#: function the published report bands with, and a `CASE` expression restating
#: its thresholds in SQL would be a second copy of the one thing on this page
#: that must not drift.
_PAIR_SORTS: dict[str, Any] = {
    #: An incomparable row -- a stated zero against a number -- sorts above every
    #: ratio rather than below them, because it is not a smaller disagreement
    #: than 1,441x, it is a different kind of one.
    "ratio": lambda row: math.inf if row.ratio is None else row.ratio,
    "flow": lambda row: (row.flow_name.lower(), row.geography),
}


def pair_differences(
    connection: sqlite3.Connection,
    detail: CategoryDetail,
    *,
    left: str,
    right: str,
    band: str = "",
    query: str = "",
    sort: str = "",
    page: int = 1,
) -> tuple[Page[PairRow], PairComparison]:
    """Where two named implementations of one category state different numbers.

    The published report (`lcia_differences`) bands a triple by the widest pair
    among *everybody* who states it, which is the right number for a report about
    a method and the wrong one for a question about two implementations: with
    three of them loaded, a row the two on this page agree exactly about can
    still be banded `over-100x` by a third.  So this reads the factors and bands
    the pair, with `lcia.differences.band_for` -- the same function the report
    uses, so the two cannot reach different verdicts about one pair.

    Read whole rather than paged in SQL, because the working set is one category
    and two implementations: the largest today is a few thousand factors, of
    which the differing rows -- all this returns -- were 307 across every category
    in the build of 2026-08-17.
    """
    if (
        not table_exists(connection, "lcia_characterization_factors")
        or left == right
        or left not in detail.ids
        or right not in detail.ids
    ):
        return Page(), PairComparison()

    # Ours comes along where it is not one of the two, so that a row can say what
    # this list did about a disagreement it was not itself a party to.
    ids = {
        name: value
        for name, value in detail.ids.items()
        if name in {left, right, OUR_IMPLEMENTATION}
    }
    by_id = {value: name for name, value in ids.items()}
    stated: dict[tuple[str, str], dict[str, float]] = {}
    published: dict[tuple[str, str], tuple[float, str]] = {}
    for row in connection.execute(
        "SELECT impact_category_id, elementary_flow_uuid, geography, amount, "
        "derivation FROM lcia_characterization_factors "
        f"WHERE impact_category_id IN ({', '.join('?' * len(ids))})",
        tuple(ids.values()),
    ):
        key = (str(row["elementary_flow_uuid"]), row["geography"] or "")
        name = by_id[str(row["impact_category_id"])]
        if name == OUR_IMPLEMENTATION:
            published[key] = (float(row["amount"]), row["derivation"] or "")
        if name in (left, right):
            stated.setdefault(key, {})[name] = float(row["amount"])

    comparison = PairComparison(left=left, right=right)
    counts: Counter[str] = Counter()
    alone: Counter[str] = Counter()
    rows: list[PairRow] = []
    for key, amounts in stated.items():
        if len(amounts) < 2:
            alone[next(iter(amounts))] += 1
            continue
        comparison.shared += 1
        banded, ratio = band_for(list(amounts.values()))
        counts[str(banded)] += 1
        if banded is Band.IDENTICAL:
            comparison.identical += 1
            continue
        ours, derivation = published.get(key, (None, ""))
        rows.append(
            PairRow(
                elementary_flow_uuid=key[0],
                geography=key[1],
                amounts=amounts,
                band=str(banded),
                ratio=ratio,
                higher=max(amounts, key=lambda name: abs(amounts[name])),
                ours=ours,
                derivation=derivation,
            )
        )
    comparison.only = {name: alone[name] for name in (left, right)}
    comparison.bands = [
        (slug, label, sum(counts[member] for member in members))
        for slug, label, members in BAND_GROUPS
        if slug != str(Band.IDENTICAL)
    ]

    if band:
        members = set(band_members(band))
        rows = [row for row in rows if row.band in members]
    labels = _flow_labels(
        connection, sorted({row.elementary_flow_uuid for row in rows})
    )
    for row in rows:
        row.flow_name, row.context_display = labels.get(
            row.elementary_flow_uuid, ("", "")
        )
    if query:
        needle = query.lower()
        rows = [
            row
            for row in rows
            if needle in row.flow_name.lower()
            or needle in row.context_display.lower()
            or query == row.elementary_flow_uuid
        ]

    descending = (sort or "-ratio").startswith("-")
    ordering = _PAIR_SORTS.get((sort or "-ratio").lstrip("-"), _PAIR_SORTS["ratio"])
    rows.sort(key=ordering, reverse=descending)
    number = clamp_page(page, len(rows))
    start = (number - 1) * PAGE_SIZE
    return (
        Page(
            rows=rows[start : start + PAGE_SIZE],
            total=len(rows),
            number=number,
            size=PAGE_SIZE,
        ),
        comparison,
    )


@dataclass
class CoverageRow:
    """One line of the coverage summary."""

    method: str
    #: The method as a reader knows it: `EF 3.1`.
    method_label: str
    implemented_by: str
    dimension: str
    value: str
    flows: int


def coverage(
    connection: sqlite3.Connection,
) -> dict[tuple[str, str], list[CoverageRow]]:
    """The coverage summary, grouped by method and implementation.

    By both, because an implementer can render two methods and the two are two
    reports: what ecoinvent skips under EF 3.1 says nothing about what it skips
    under another method.

    A summary and never a list, which is a measured decision rather than a
    presentational one: asked as a list it is 5,668 rows, most of them a
    substance with no global-warming potential, where absence is the right answer
    and nobody should be asked to fill it in.
    """
    if not table_exists(connection, "lcia_coverage"):
        return {}
    names = _names_by_slug()
    labels = _method_labels()
    grouped: dict[tuple[str, str], list[CoverageRow]] = {}
    for row in connection.execute(
        "SELECT method, implemented_by, dimension, value, flows FROM lcia_coverage "
        "ORDER BY method, implemented_by, dimension, flows DESC, value"
    ):
        value = row["value"] or ""
        method = row["method"] or ""
        grouped.setdefault((method, row["implemented_by"]), []).append(
            CoverageRow(
                method=method,
                method_label=labels.get(method, method),
                implemented_by=row["implemented_by"] or "",
                dimension=row["dimension"] or "",
                value=(
                    names.get((method, value), value)
                    if row["dimension"] == "category"
                    else value
                ),
                flows=int(row["flows"] or 0),
            )
        )
    return grouped


@dataclass
class CollidingRow:
    """One of the numbers a collision is between, and where it came from.

    The finding's own sentence names the rows by uuid, which is the one thing a
    reader cannot do anything with: `03b56eb6-…` is not a substance. The name,
    the compartment and the unit are read here, from the source rows the merge
    already recorded against the flow.
    """

    amount: float
    source_flow_uuid: str = ""
    source_flow_name: str = ""
    source_context: str = ""
    source_unit: str = ""


@dataclass
class StatedRow:
    """One factor a source row states, on the way to a flow it never reached."""

    category: str
    geography: str = ""
    amount: float = 0.0


@dataclass
class CarriedBy:
    """A consensus flow that carries the source row a finding is about.

    The other half of "this row reached nothing": if a consensus flow does carry
    it, the row reached the *merge* and only its factors were left behind, which
    is a different fault in a different place. `factors` is what that flow
    already carries from anybody, so a reader can see whether the number would
    have been a first opinion or a second.
    """

    elementary_flow_uuid: str
    flow_name: str = ""
    context_display: str = ""
    factors: int = 0


@dataclass
class MergedRow:
    """One of the source rows a consensus flow was settled from.

    The declined-numbers page said which number was not kept and nothing about
    where either came from, so the duplication behind it -- the reason there
    were two numbers at all -- was invisible.  It is a publisher shipping one
    substance twice in one compartment: EF 3.1 has `dichloromethane` and two
    rows called `Methylene chloride` in indoor air, this list holds one flow,
    and the factors on the rows it collapsed did not agree.

    *shipped_as* is `(list, name)` for every source row on this flow, and it is
    the field that shows the duplication: the published label is the same on all
    of them by the time the layering has run, so printing that alone would say
    three rows are one row three times.  A row can carry several -- a consensus
    flow merged from three lists has three -- so all of them are kept rather
    than one being chosen.
    """

    uuid: str
    name: str = ""
    shipped_as: list[tuple[str, str]] = field(default_factory=list)
    context_display: str = ""
    unit: str = ""
    factors: int = 0
    is_deprecated: bool = False
    #: The row this list kept, which is the flow the finding is about.
    survivor: bool = False
    #: Whether this row is the one whose number was declined.  A collapse can
    #: decline the *survivor's* own number -- `settle_factor_values` keeps the
    #: more precise of the two, whichever row it came from -- so this is not the
    #: same question as which row was deprecated.
    declined_here: bool = False


@dataclass
class FindingRow:
    """One thing `characterise` found and did not silently resolve."""

    kind: str
    implemented_by: str
    elementary_flow_uuid: str
    flow_name: str
    context_display: str
    detail: str
    #: The impact category, in this list's words. A finding names the category
    #: the way the implementation that raised it does -- the JRC by its method
    #: file's UUID, ecoinvent by its own name for it -- and neither is a thing a
    #: reader can look up. Resolved through the categories the run wrote, so the
    #: same category reads the same on every page.
    category: str = ""
    #: What the published flow is measured in, which is what makes a factor
    #: readable: `87.261` is a number until it is `87.261 per kg`.
    unit: str = ""
    context: dict[str, Any] = field(default_factory=dict)
    #: The numbers a collision is between, named. Empty for every other kind.
    colliding: list[CollidingRow] = field(default_factory=list)
    #: What an unreached source row states. Empty for every other kind.
    stated: list[StatedRow] = field(default_factory=list)
    #: The consensus flow that carries the unreached source row, where one does.
    carried_by: CarriedBy | None = None
    #: The rows a declined number's flow was settled from, the kept one first.
    #: Empty for every other kind.
    merged: list[MergedRow] = field(default_factory=list)

    @property
    def source_flow_uuid(self) -> str:
        return str(self.context.get("source_flow_uuid") or "")

    @property
    def source_flow_name(self) -> str:
        """What the publisher calls the row, where the run recorded it.

        A finding written before the run recorded names has none, and the page
        falls back to the uuid rather than to an empty cell.
        """
        return str(self.context.get("name") or "")

    @property
    def source_context(self) -> str:
        return str(self.context.get("context") or "")

    @property
    def source_unit(self) -> str:
        return str(self.context.get("unit") or "")

    @property
    def geography(self) -> str:
        """The place the numbers were compared inside.

        A collision is between rows that share a place -- the place is in the key
        the factors are grouped by -- so this is what the disagreement is *not*
        explained by, which is the first thing a reader assumes it is.
        """
        return str(self.context.get("geography") or "")

    @property
    def ratio(self) -> float | None:
        value = self.context.get("ratio")
        return float(value) if isinstance(value, int | float) else None

    @property
    def published(self) -> float | None:
        value = self.context.get("published")
        return float(value) if isinstance(value, int | float) else None

    @property
    def declined(self) -> float | None:
        value = self.context.get("declined")
        return float(value) if isinstance(value, int | float) else None

    @property
    def settled_by(self) -> str:
        return str(self.context.get("settled_by") or "")

    @property
    def declined_by(self) -> list[str]:
        """The flows that published the number this list did not keep.

        Written by `pipeline.deduplication` as `urn:uuid:` primary sources on
        the superseded value, which is the only record of which of the collapsed
        rows the discarded number came from.
        """
        return [
            str(source).removeprefix("urn:uuid:")
            for source in (self.context.get("declined_by") or [])
            if str(source or "").strip()
        ]

    @property
    def source_rows(self) -> int:
        """How many distinct source rows the colliding numbers came from."""
        return len(
            {row.source_flow_uuid for row in self.colliding if row.source_flow_uuid}
        )


@dataclass
class FindingKindRow:
    """One kind of finding, for the index that mirrors `/checks`."""

    kind: str
    title: str
    finds: str
    #: Which table body says this kind. The four kinds are four different events
    #: with four different pieces of evidence, and one table of `detail` strings
    #: was the shape that made every one of them unreadable. Declared beside the
    #: kind rather than branched on in the template.
    layout: str = "plain"
    count: int = 0


#: What each kind is, in the words a reader needs rather than the enum's.
FINDING_KINDS: tuple[tuple[str, str, str, str], ...] = (
    (
        "factor-collision",
        "Factor collisions",
        "Two source rows reach one consensus flow and state different numbers "
        "for one category, in one place. Neither is published: the disagreement "
        "is evidence about the matching, and averaging it would hide that.",
        "collision",
    ),
    (
        "unit-crossing",
        "Unit crossings",
        "A factor stated per kilogram, published against a flow measured in "
        "megajoules. The number is converted by the flow's own property, and "
        "the crossing is recorded rather than assumed harmless.",
        "plain",
    ),
    (
        "superseded-value",
        "Declined numbers",
        "The build settled two rows that turned out to be one flow, and this is "
        "the number it did not keep (#63). A reader comparing implementations "
        "has to know the number they are comparing was chosen from two.",
        "declined",
    ),
    (
        "flow-not-reached",
        "Flows not reached",
        "A source row this list has no flow for, so its factor has nowhere to "
        "land. A question for the merge rather than for this layer.",
        "unreached",
    ),
    (
        "redirect-followed",
        "Numbers carried onto a survivor",
        "An identifier this build retired held a factor the flow that replaced "
        "it states nothing for, so the number was carried onto the survivor "
        "(#163). The one case where following a redirect adds a factor rather "
        "than restating one.",
        "plain",
    ),
    (
        "redirect-refused",
        "Redirects not followed",
        "An identifier this build retired carries factors, and its redirect is "
        "one a consumer is told to refuse — two source contexts our vocabulary "
        "cannot tell apart. The numbers are reported here rather than "
        "republished on the survivor (#163).",
        "plain",
    ),
)


def findings_index(connection: sqlite3.Connection) -> list[FindingKindRow]:
    """Every kind of finding and how many there are."""
    if not table_exists(connection, "lcia_findings"):
        return []
    counted = {
        row["kind"]: int(row["rows"] or 0)
        for row in connection.execute(
            "SELECT kind, count(*) AS rows FROM lcia_findings GROUP BY kind"
        )
    }
    return [
        FindingKindRow(
            kind=kind, title=title, finds=finds, layout=layout,
            count=counted.get(kind, 0),
        )
        for kind, title, finds, layout in FINDING_KINDS
    ]


#: What a page of findings can be ordered by. The two numbers are read out of the
#: finding's own context rather than stored in columns of their own: they mean
#: different things to different kinds -- a declined number has a ratio to what
#: was published, a collision has one across the widest pair -- and a column
#: named `ratio` on a table holding four kinds of event would be null for most of
#: them and would tempt a reader to compare the ones it is not null for.
_FINDING_SORTS = {
    "flow": "flow.pref_label_value",
    "factor": "json_extract(finding.context_json, '$.published')",
    "ratio": "json_extract(finding.context_json, '$.ratio')",
}

#: How many distinct source rows a collision's numbers came from, in SQL.
#:
#: `count(DISTINCT …)` skips nulls, so an implementation whose factors already
#: name consensus flows -- which records no source row -- counts 0 and lands on
#: the same side as one row stating several numbers, which is what it is.
_COLLISION_SOURCES = (
    "(SELECT count(DISTINCT json_extract(candidate.value, '$.source_flow_uuid')) "
    "FROM json_each(finding.context_json, '$.rows') AS candidate)"
)

#: The two things a `factor-collision` can be, and which one the page opens on.
#:
#: **Two source rows disagreeing** is the event the check exists for: the merge
#: put two of a publisher's rows on one flow and they do not state one number,
#: which is a claim about the matching.
#:
#: **One row stating several numbers** under one category and place is not a
#: disagreement at all -- it is a publisher distinguishing its rows by something
#: this list did not read. EF states 42,871 of its factors with a `location`, and
#: a build whose extracted list predates that being read collapses 213 land-use
#: numbers onto one flow. The factors are *expected* to differ; listing them
#: beside a real collision says a defect is 222 defects. Counted, kept reachable,
#: and not the default.
COLLISION_SOURCES: tuple[tuple[str, str], ...] = (
    ("many", "Two source rows disagree"),
    ("one", "One row, several numbers"),
)


def collision_sources(connection: sqlite3.Connection) -> list[tuple[str, str, int]]:
    """Each kind of collision and how many there are, in reading order."""
    if not table_exists(connection, "lcia_findings"):
        return []
    counted: dict[str, int] = {}
    for row in connection.execute(
        f"SELECT CASE WHEN {_COLLISION_SOURCES} > 1 THEN 'many' ELSE 'one' END "
        "AS sources, count(*) AS rows FROM lcia_findings AS finding "
        "WHERE finding.kind = 'factor-collision' GROUP BY sources"
    ):
        counted[str(row["sources"])] = int(row["rows"] or 0)
    return [(slug, label, counted.get(slug, 0)) for slug, label in COLLISION_SOURCES]


def _colliding(
    connection: sqlite3.Connection, rows: list[FindingRow]
) -> None:
    """Name the source row behind every colliding number, in place.

    One statement for the page rather than one per finding, and read from
    `elementary_flow_sources` -- where the merge already recorded what each
    contributing row was called -- rather than from a copy taken when
    `characterise` ran.
    """
    wanted = {
        row.source_flow_uuid
        for finding in rows
        for row in finding.colliding
        if row.source_flow_uuid
    }
    if not wanted or not table_exists(connection, "elementary_flow_sources"):
        return
    names: dict[str, tuple[str, str, str]] = {}
    uuids = sorted(wanted)
    for start in range(0, len(uuids), _LOOKUP_CHUNK):
        batch = uuids[start : start + _LOOKUP_CHUNK]
        for row in connection.execute(
            "SELECT source_flow_uuid, source_flow_name, source_metadata_json "
            "FROM elementary_flow_sources "
            f"WHERE source_flow_uuid IN ({', '.join('?' * len(batch))})",
            batch,
        ):
            payload = load_json(row["source_metadata_json"], {}) or {}
            context = payload.get("original_context")
            names[str(row["source_flow_uuid"])] = (
                str(row["source_flow_name"] or ""),
                (
                    " / ".join(str(part) for part in context)
                    if isinstance(context, list)
                    else str(context or "")
                ),
                str(payload.get("unit") or ""),
            )
    for finding in rows:
        for row in finding.colliding:
            row.source_flow_name, row.source_context, row.source_unit = names.get(
                row.source_flow_uuid, ("", "", "")
            )


def _category_names(connection: sqlite3.Connection) -> dict[str, str]:
    """Every name an implementation calls a category, mapped to ours.

    A category is one thing under three names: `Ecotoxicity, freshwater` to the
    JRC, `ecotoxicity: freshwater` to ecoinvent, and a method-file UUID in the
    rows the JRC's own factors carry. All three are in `meta_json` on the
    category rows the run wrote, which is what makes this a lookup rather than a
    second crosswalk.
    """
    names: dict[str, str] = {}
    if not table_exists(connection, "lcia_impact_categories"):
        return names
    for row in connection.execute(
        "SELECT name, meta_json FROM lcia_impact_categories"
    ):
        name = str(row["name"] or "")
        meta = load_json(row["meta_json"], {}) or {}
        names[name] = name
        for key in ("method_uuid", "stated_name"):
            if meta.get(key):
                names[str(meta[key])] = name
    return names


def _carried_by(
    connection: sqlite3.Connection, rows: list[FindingRow]
) -> None:
    """Whether a consensus flow carries each unreached source row, in place.

    "Nothing has this row" and "a flow has this row and none of its factors" are
    two different faults in two different places, and the finding's own sentence
    cannot tell them apart -- it is written by the pass that looked the row up in
    a factor index, not in the merge.
    """
    wanted = sorted({row.source_flow_uuid for row in rows if row.source_flow_uuid})
    if not wanted or not table_exists(connection, "elementary_flow_sources"):
        return
    carried: dict[str, CarriedBy] = {}
    for start in range(0, len(wanted), _LOOKUP_CHUNK):
        batch = wanted[start : start + _LOOKUP_CHUNK]
        for row in connection.execute(
            "SELECT source.source_flow_uuid AS source_flow_uuid, "
            "source.elementary_flow_uuid AS uuid, flow.pref_label_value AS name, "
            "flow.context_display AS context_display, "
            "coalesce(flow.lcia_factor_count, 0) AS factors "
            "FROM elementary_flow_sources AS source "
            "LEFT JOIN elementary_flows AS flow "
            "ON flow.uuid = source.elementary_flow_uuid "
            f"WHERE source.source_flow_uuid IN ({', '.join('?' * len(batch))})",
            batch,
        ):
            carried[str(row["source_flow_uuid"])] = CarriedBy(
                elementary_flow_uuid=str(row["uuid"] or ""),
                flow_name=str(row["name"] or ""),
                context_display=str(row["context_display"] or ""),
                factors=int(row["factors"] or 0),
            )
    for row in rows:
        row.carried_by = carried.get(row.source_flow_uuid)


def _merged_from(
    connection: sqlite3.Connection, rows: list[FindingRow]
) -> None:
    """Name the rows each declined number's flow was settled from, in place.

    Two statements for the page rather than two per finding: 232 declined
    numbers on this build sit on 69 flows, so the same collapse is described
    over and over.

    The group is the surviving flow and every flow deprecated onto it.  Nothing
    records the group directly -- `settle_factor_values` writes the discarded
    *number* onto the survivor and not the set it came from -- but
    `replaced_by_uuid` is that group, because deprecating the duplicate onto the
    survivor is what the collapse does.
    """
    survivors = sorted(
        {row.elementary_flow_uuid for row in rows if row.elementary_flow_uuid}
    )
    if not survivors or not table_exists(connection, "elementary_flows"):
        return

    found: dict[str, MergedRow] = {}
    groups: dict[str, list[str]] = {uuid: [] for uuid in survivors}
    for start in range(0, len(survivors), _LOOKUP_CHUNK):
        batch = survivors[start : start + _LOOKUP_CHUNK]
        holders = ", ".join("?" * len(batch))
        for row in connection.execute(
            "SELECT uuid, pref_label_value, context_display, unit, "
            "coalesce(lcia_factor_count, 0) AS factors, "
            "coalesce(is_deprecated, 0) AS is_deprecated, "
            "coalesce(replaced_by_uuid, '') AS replaced_by_uuid "
            "FROM elementary_flows "
            f"WHERE uuid IN ({holders}) OR replaced_by_uuid IN ({holders})",
            [*batch, *batch],
        ):
            uuid = str(row["uuid"])
            found[uuid] = MergedRow(
                uuid=uuid,
                name=str(row["pref_label_value"] or ""),
                context_display=str(row["context_display"] or ""),
                unit=str(row["unit"] or ""),
                factors=int(row["factors"] or 0),
                is_deprecated=bool(row["is_deprecated"]),
                survivor=not row["is_deprecated"],
            )
            onto = str(row["replaced_by_uuid"] or "") if row["is_deprecated"] else uuid
            if onto in groups:
                groups[onto].append(uuid)

    _shipped_as(connection, found)

    for finding in rows:
        declined = set(finding.declined_by)
        merged = [found[uuid] for uuid in groups.get(finding.elementary_flow_uuid, [])]
        # A copy per finding: `declined_here` is a fact about this number, and
        # the same row is shown under every finding on the flow.
        finding.merged = sorted(
            (replace(row, declined_here=row.uuid in declined) for row in merged),
            key=lambda row: (not row.survivor, row.uuid),
        )


def _shipped_as(
    connection: sqlite3.Connection, found: dict[str, MergedRow]
) -> None:
    """Record what each list shipped each row as, in place.

    Which is where the duplication shows.  By the time the layering has run all
    the rows of a collapse carry one published label -- `Dichloromethane` on all
    three of EF 3.1's indoor-air rows -- so a page printing that says one row
    three times.  What EF shipped is `dichloromethane` and `Methylene chloride`,
    and that is the answer to how the duplication got in.

    Every source row, not the first: a consensus flow merged from three lists
    was called three things, and choosing between them would be this page
    deciding which list to believe.
    """
    if not found or not table_exists(connection, "elementary_flow_sources"):
        return
    uuids = sorted(found)
    for start in range(0, len(uuids), _LOOKUP_CHUNK):
        batch = uuids[start : start + _LOOKUP_CHUNK]
        for row in connection.execute(
            "SELECT elementary_flow_uuid, list_name, list_version, source_flow_name "
            "FROM elementary_flow_sources "
            f"WHERE elementary_flow_uuid IN ({', '.join('?' * len(batch))}) "
            "ORDER BY list_name, list_version, source_flow_name",
            batch,
        ):
            entry = found.get(str(row["elementary_flow_uuid"]))
            if entry is None:
                continue
            entry.shipped_as.append((
                f"{row['list_name'] or ''} {row['list_version'] or ''}".strip(),
                str(row["source_flow_name"] or ""),
            ))


def findings(
    connection: sqlite3.Connection,
    *,
    kind: str,
    query: str = "",
    sources: str = "",
    sort: str = "",
    page: int = 1,
) -> Page[FindingRow]:
    """One kind of finding, paged.

    *sources* narrows a `factor-collision` to one of the two things it can be;
    it means nothing to the other kinds and is ignored by them.
    """
    if not table_exists(connection, "lcia_findings"):
        return Page()
    where = ["finding.kind = ?"]
    parameters: list[Any] = [kind]
    if kind == "factor-collision":
        wanted = sources or COLLISION_SOURCES[0][0]
        where.append(
            f"{_COLLISION_SOURCES} {'>' if wanted == 'many' else '<='} 1"
        )
    if query:
        where.append(
            "(flow.pref_label_value LIKE ? OR finding.detail LIKE ? "
            "OR finding.elementary_flow_uuid = ?)"
        )
        parameters.extend([f"%{query}%", f"%{query}%", query])
    source = (
        "FROM lcia_findings AS finding "
        "LEFT JOIN elementary_flows AS flow "
        "ON flow.uuid = finding.elementary_flow_uuid "
        f"WHERE {' AND '.join(where)}"
    )
    total = int(
        connection.execute(f"SELECT count(*) {source}", parameters).fetchone()[0]
    )
    number = clamp_page(page, total)
    ordering = order_by(sort or "flow", _FINDING_SORTS, _FINDING_SORTS["flow"])
    rows = [
        FindingRow(
            kind=row["kind"] or "",
            implemented_by=row["implemented_by"] or "",
            elementary_flow_uuid=row["elementary_flow_uuid"] or "",
            flow_name=row["pref_label_value"] or "",
            context_display=row["context_display"] or "",
            detail=row["detail"] or "",
            unit=row["unit"] or "",
            context=load_json(row["context_json"], {}) or {},
        )
        for row in connection.execute(
            "SELECT finding.*, flow.pref_label_value, flow.context_display, "
            f"flow.unit {source} ORDER BY {ordering}, finding.detail "
            "LIMIT ? OFFSET ?",
            (*parameters, PAGE_SIZE, (number - 1) * PAGE_SIZE),
        )
    ]
    named = _category_names(connection)
    for finding in rows:
        stated_category = str(finding.context.get("category") or "")
        finding.category = named.get(stated_category, stated_category)
        finding.colliding = [
            CollidingRow(
                amount=float(candidate.get("amount") or 0.0),
                source_flow_uuid=str(candidate.get("source_flow_uuid") or ""),
            )
            for candidate in finding.context.get("rows") or []
            if isinstance(candidate, dict)
        ]
        finding.stated = [
            StatedRow(
                category=str(stated.get("category") or ""),
                geography=str(stated.get("geography") or ""),
                amount=float(stated.get("amount") or 0.0),
            )
            for stated in finding.context.get("factors") or []
            if isinstance(stated, dict)
        ]
    _colliding(connection, rows)
    if kind == "flow-not-reached":
        _carried_by(connection, rows)
    if kind == "superseded-value":
        _merged_from(connection, rows)
    return Page(rows=rows, total=total, number=number, size=PAGE_SIZE)


@dataclass
class FlowFactorRow:
    """One implementation's number for this flow, under one method's category.

    **One row per factor, not one per category.** The wide shape -- a column per
    implementation -- is right for a page about a *category*, where the reader is
    comparing the same number stated twice. It is wrong here: a flow is
    characterised by several methods, and a method's implementations do not line
    up across methods, so the wide table grew a column for every implementation
    of every method and left most of them empty. Long form holds any number of
    methods and implementations, and makes both of them sortable columns.
    """

    method: str
    implemented_by: str
    category: str
    geography: str = ""
    amount: float = 0.0
    #: How this list arrived at the number, on the implementation that is ours.
    #: Empty on a transcription, which arrives at nothing: it says what its
    #: publisher said.
    derivation: str = ""


#: What the flow's factor table can be ordered by. In Python because the set is
#: one flow's factors -- 75 of them at three implementations of one method -- and
#: because "ours first" is a property of the implementation rather than of a
#: column SQL can order on.
_FLOW_FACTOR_SORTS: dict[str, Any] = {
    "method": lambda row: (row.method, row.category, row.geography),
    "implementation": lambda row: (
        _ordering({})(row.implemented_by), row.method, row.category, row.geography
    ),
    "category": lambda row: (row.category, row.geography, row.method),
    "place": lambda row: (row.geography, row.method, row.category),
    "amount": lambda row: abs(row.amount),
    "published": lambda row: (row.derivation, row.method, row.category),
}


def for_flow(
    connection: sqlite3.Connection, uuid: str, *, sort: str = ""
) -> list[FlowFactorRow]:
    """One flow's factors, one row each.

    The question the flow page could not answer before there were three
    implementations of one method: what does each of them say this substance is
    worth, and where they differ, what did this list do about it?
    """
    if not table_exists(connection, "lcia_characterization_factors"):
        return []
    rows = [
        FlowFactorRow(
            method=f"{row['method_name'] or ''} {row['version'] or ''}".strip(),
            implemented_by=row["implemented_by"] or "",
            category=row["name"] or "",
            geography=row["geography"] or "",
            amount=float(row["amount"]),
            derivation=row["derivation"] or "",
        )
        for row in connection.execute(
            """
            SELECT category.name AS name, category.implemented_by AS implemented_by,
                   category.version AS version, method.name AS method_name,
                   factor.geography AS geography, factor.amount AS amount,
                   factor.derivation AS derivation
            FROM lcia_characterization_factors AS factor
            JOIN lcia_impact_categories AS category
                ON category.id = factor.impact_category_id
            LEFT JOIN lcia_methods AS method ON method.id = category.method_id
            WHERE factor.elementary_flow_uuid = ?
            """,
            (uuid,),
        )
    ]
    descending = (sort or "method").startswith("-")
    ordering = _FLOW_FACTOR_SORTS.get(
        (sort or "method").lstrip("-"), _FLOW_FACTOR_SORTS["method"]
    )
    rows.sort(key=ordering, reverse=descending)
    return rows
