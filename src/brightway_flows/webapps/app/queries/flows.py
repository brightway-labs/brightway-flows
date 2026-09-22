"""Elementary flows: the list, its filters, and one flow's detail.

`/consensus-flows` was the densest page in the four applications and the one
most used, so what it did is ported rather than reinterpreted: the same filters,
the same sort keys, the same FTS-with-LIKE-fallback, the same precomputed
filter options.

Two things it did are not ported. It read `consensus_changes` for the change
count, which covers one transformer; that becomes `changelog`, which covers
every one. And the detail page rendered its history inline -- fourteen stacked
sections, the three heaviest of which are history -- which moves behind
`/flows/<uuid>/changes` in Phase 3. Nothing here reads a history table.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from typing import Any

from brightway_flows.domain.labels import coerce_alt_labels
from brightway_flows.domain.vocabulary import (
    CHEMINF_CAS_REGISTRY_NUMBER,
    CHEMINF_EC_NUMBER,
)
from brightway_flows.domain.lcia.crosswalk import CONSENSUS_IMPLEMENTATION
from brightway_flows.pipeline.sqlite import merge_object_payload
from brightway_flows.sources import base_source_label
from brightway_flows.webapps.app.db import table_exists
from brightway_flows.webapps.app.labels import type_label
from brightway_flows.webapps.app.match_reasons import match_reason
from brightway_flows.webapps.app.queries.common import (
    PAGE_SIZE,
    Page,
    load_json,
    order_by,
    resolve_page,
)

#: The eight context axes a flow can be filtered on, and how they are labelled.
#: Column names are `context_<key>` on `elementary_flows`.
CONTEXT_AXES: tuple[tuple[str, str], ...] = (
    ("dimension", "Dimension"),
    ("media", "Media"),
    ("strata", "Strata"),
    ("indoor", "Indoor"),
    ("population_density", "Population density"),
    ("geography", "Geography"),
    ("water_body", "Water body"),
    ("land_use", "Land use"),
)
CONTEXT_KEYS = tuple(key for key, _ in CONTEXT_AXES)

_SORT_COLUMNS = {
    "name": "lower(ef.pref_label_value)",
    "context": "lower(ef.context_display)",
    "source": "lower(ef.source)",
    "unit": "lower(ef.unit)",
    "type": "fo.flow_type",
    "lcia": "ef.lcia_factor_count",
    "changes": "ef.consensus_change_count",
}
_DEFAULT_SORT = "lower(ef.pref_label_value)"

_SELECT = """
    SELECT
        ef.uuid, ef.flow_object_id, ef.source, ef.unit, ef.lcia_factor_count,
        ef.is_deprecated, ef.replaced_by_uuid, ef.context_display,
        ef.consensus_change_count,
        fo.pref_label_value, fo.alt_label_json, fo.classifications_json,
        fo.flow_type, fo.origin_qualifier
    FROM elementary_flows ef
    LEFT JOIN flow_objects fo ON fo.flow_object_id = ef.flow_object_id
"""


@dataclass
class FlowFilters:
    """What the reader asked for, parsed once.

    A record rather than a bag of keyword arguments, because it is built from
    the query string in the view, passed to two queries, and rendered back into
    the filter chips -- and every place that reads it should fail loudly on a
    field this does not have.
    """

    query: str = ""
    name_only: bool = False
    source: str = ""
    unit: str = ""
    flow_type: str = ""
    #: One of `qualifiers.ORIGIN_QUALIFIERS`. A separate filter from `flow_type`
    #: and not a value of it: 10 of the 14 qualified substances are typed
    #: identically to the substance they were split from, so the type axis
    #: cannot answer "which of these is the biogenic one".
    origin_qualifier: str = ""
    #: `exclude` (the default), `only`, or `all`. Deprecated flows are hidden
    #: unless asked for: they are replaced, and a reader looking for a substance
    #: wants the row that is current.
    deprecated: str = "exclude"
    context: dict[str, str] = field(default_factory=dict)

    @property
    def active(self) -> list[tuple[str, str, str]]:
        """`(parameter, label, value)` for each filter in force.

        What the chips above the table render. `deprecated=exclude` is not in
        it: it is the default, and a chip for it would be noise on every page.
        """
        chips: list[tuple[str, str, str]] = []
        if self.query:
            chips.append(("q", "Name only" if self.name_only else "Search", self.query))
        if self.source:
            chips.append(("source", "Source", self.source))
        if self.unit:
            chips.append(("unit", "Unit", self.unit))
        if self.flow_type:
            chips.append(("type", "Type", type_label(self.flow_type)))
        if self.origin_qualifier:
            chips.append(("qualifier", "Origin", self.origin_qualifier))
        if self.deprecated != "exclude":
            chips.append(("deprecated", "Deprecated", self.deprecated))
        labels = dict(CONTEXT_AXES)
        for key, value in self.context.items():
            if value:
                chips.append((key, labels.get(key, key), value))
        return chips


@dataclass
class FlowRow:
    """One row of the flows table."""

    uuid: str
    flow_object_id: str = ""
    name: str = ""
    source: str = ""
    unit: str = ""
    context_display: str = ""
    flow_type: str = ""
    origin_qualifier: str = ""
    lcia_factor_count: int = 0
    change_count: int = 0
    alt_label_count: int = 0
    cas_numbers: list[str] = field(default_factory=list)
    is_deprecated: bool = False
    replaced_by_uuid: str = ""

    @property
    def type_label(self) -> str:
        """The type as a person reads it, not as the IRI spells it.

        `NeutralMolecule` reads "Neutral molecule" and `ENVO_01000892` reads
        "area of cropland" -- the second only because `labels.type_label` asks
        the anchor snapshot.  The last segment of the IRI was what this column
        showed, and the 198 flow objects the build of 2026-08-20 types by ENVO
        showed an accession.
        """
        return type_label(self.flow_type)


@dataclass
class FactorCount:
    """One implementation's factor count for one flow.

    Both numbers, because they answer different questions: `factors` is how many
    the implementation states and `non_zero_factors` is how many of them are not
    a stated zero.  #47 kept the zeros -- "assessed, and zero" is not "never
    assessed" -- and a page showing one number would have to pick which.
    """

    implemented_by: str
    factors: int
    non_zero_factors: int

    @property
    def zeros(self) -> int:
        return self.factors - self.non_zero_factors


@dataclass
class SourceReference:
    """Which source list a flow came from, and what it was called there.

    The read-side projection of `domain.source_ref.SourceRef`, and deliberately
    not that record (#92). This is built from the columns of
    `elementary_flow_sources` the page renders, and `match_reason` is not one of
    them: it is the row's stored `source_metadata` read as a sentence, so the
    field the record carries as a bag of merge categories reaches the page as
    the one thing a reader wants from it.

    Stated here because three types for one concept is how the four models #92
    counted came about, and the difference between a view model and a fourth
    model is whether anyone wrote down which it is.
    """

    list_name: str = ""
    list_version: str = ""
    source_flow_uuid: str = ""
    source_flow_name: str = ""
    #: Why the merge holds this source flow to be this consensus flow, in words.
    #: Empty where the row records no decision, which is a database written
    #: before the merge stored one.
    match_reason: str = ""


@dataclass
class FlowDetail:
    """Everything `/flows/<uuid>` shows, except its history.

    History -- the change log, the PROV trail and the consolidated field
    provenance -- is the three heaviest sections of the fourteen this page had,
    and the least often read. It moves behind `/flows/<uuid>/changes` in Phase
    3, and nothing here queries for it.
    """

    uuid: str
    name: str = ""
    flow_object_id: str = ""
    source: str = ""
    unit: str = ""
    context_display: str = ""
    context: dict[str, Any] = field(default_factory=dict)
    flow_type: str = ""
    origin_qualifier: str = ""
    lcia_factor_count: int = 0
    #: How many factors each implementation of EF 3.1 states for this flow, most
    #: first.  `lcia_factor_count` beside it is the JRC's non-zero count and
    #: keeps that meaning, so a query written before `characterise` existed still
    #: answers what it always answered; this is the question that column cannot
    #: answer now that there are three implementations.  Empty when
    #: `characterise` has not run against this build.
    factor_counts: list[FactorCount] = field(default_factory=list)
    change_count: int = 0
    is_deprecated: bool = False
    replaced_by_uuid: str = ""
    cas_numbers: list[str] = field(default_factory=list)
    ec_numbers: list[str] = field(default_factory=list)
    pref_labels: list[dict[str, Any]] = field(default_factory=list)
    alt_labels: list[str] = field(default_factory=list)
    sources: list[SourceReference] = field(default_factory=list)
    concept_associations: list[dict[str, Any]] = field(default_factory=list)
    flow_json: dict[str, Any] = field(default_factory=dict)

    @property
    def type_label(self) -> str:
        return type_label(self.flow_type)


def _factor_counts(
    connection: sqlite3.Connection, uuid: str
) -> list[FactorCount]:
    """One flow's factors, counted per implementation.

    Read from `lcia_flow_factor_counts`, which is a view over the factors
    themselves -- so this cannot show a number the factor list disagrees with.
    Empty where `characterise` has not run, which is the normal state of a build
    that has only been built: the honest answer is "not known", and the page says
    so rather than showing three zeros.
    """
    if not table_exists(connection, "lcia_flow_factor_counts"):
        return []
    return [
        FactorCount(
            implemented_by=row["implemented_by"] or "",
            factors=int(row["factors"] or 0),
            non_zero_factors=int(row["non_zero_factors"] or 0),
        )
        for row in connection.execute(
            "SELECT implemented_by, factors, non_zero_factors "
            "FROM lcia_flow_factor_counts WHERE elementary_flow_uuid = ? "
            # The consensus implementation first -- it is the one this list
            # publishes -- then the transcriptions by how much they say.
            "ORDER BY implemented_by = ? DESC, factors DESC, implemented_by",
            (uuid, CONSENSUS_IMPLEMENTATION),
        )
    ]


def _classification_values(classifications: Any, iri: str) -> list[str]:
    """The `@value` list under one classification IRI.

    Serialised payload, so it is read defensively: the shape is a dict keyed by
    IRI whose values are dicts with an `@value` that may be a string or a list.
    """
    if not isinstance(classifications, dict):
        return []
    entry = classifications.get(iri)
    if not isinstance(entry, dict):
        return []
    raw = entry.get("@value")
    if isinstance(raw, str):
        return [raw] if raw.strip() else []
    if isinstance(raw, list):
        return [str(v) for v in raw if isinstance(v, str) and v.strip()]
    return []


def _row(row: sqlite3.Row) -> FlowRow:
    classifications = load_json(row["classifications_json"], {})
    return FlowRow(
        uuid=row["uuid"],
        flow_object_id=row["flow_object_id"] or "",
        name=row["pref_label_value"] or "",
        source=row["source"] or "",
        unit=row["unit"] or "",
        context_display=row["context_display"] or "",
        flow_type=row["flow_type"] or "",
        origin_qualifier=row["origin_qualifier"] or "",
        lcia_factor_count=int(row["lcia_factor_count"] or 0),
        change_count=int(row["consensus_change_count"] or 0),
        alt_label_count=len(load_json(row["alt_label_json"], [])),
        cas_numbers=_classification_values(classifications, CHEMINF_CAS_REGISTRY_NUMBER),
        is_deprecated=bool(row["is_deprecated"]),
        replaced_by_uuid=row["replaced_by_uuid"] or "",
    )


def _where(filters: FlowFilters) -> tuple[list[str], list[Any]]:
    """Everything except the search term, which needs a fallback of its own."""
    clauses: list[str] = []
    params: list[Any] = []
    if filters.source:
        clauses.append("ef.source = ?")
        params.append(filters.source)
    if filters.unit:
        clauses.append("ef.unit = ?")
        params.append(filters.unit)
    if filters.flow_type:
        clauses.append("fo.flow_type = ?")
        params.append(filters.flow_type)
    if filters.origin_qualifier:
        clauses.append("fo.origin_qualifier = ?")
        params.append(filters.origin_qualifier)
    if filters.deprecated == "only":
        clauses.append("ef.is_deprecated = 1")
    elif filters.deprecated == "exclude":
        clauses.append("ef.is_deprecated = 0")
    for key in CONTEXT_KEYS:
        value = filters.context.get(key, "")
        if value:
            # Column name from a fixed tuple, never from the query string.
            clauses.append(f"ef.context_{key} = ?")
            params.append(value)
    return clauses, params


def _search_fts(filters: FlowFilters) -> tuple[str, list[Any]]:
    clause = (
        "(ef.uuid IN (SELECT uuid FROM elementary_flows_fts "
        "WHERE elementary_flows_fts MATCH ?) "
        "OR ef.flow_object_id IN (SELECT flow_object_id FROM flow_objects_fts "
        "WHERE flow_objects_fts MATCH ?))"
    )
    if filters.name_only:
        return clause, [f"name:{filters.query}", f"pref_label:{filters.query}"]
    return clause, [filters.query, filters.query]


def _search_like(filters: FlowFilters) -> tuple[str, list[Any]]:
    """The fallback for a search the FTS index cannot serve.

    Two cases, and they are worth separating because only one of them recovers
    anything. `carbon AND` is a reasonable thing for a reader to type and a
    syntax error to FTS5; the fallback then searches for that literal string
    and finds nothing, which is fine -- the point is that a malformed query is
    an empty result rather than a 500.

    The case that does recover is a database with no FTS index: `no such table:
    elementary_flows_fts` raises the same `OperationalError`, and here the
    substring search is a real answer rather than a graceful failure.
    """
    like = f"%{filters.query.lower()}%"
    if filters.name_only:
        return "lower(fo.pref_label_value) LIKE ?", [like]
    return (
        "(lower(fo.pref_label_value) LIKE ? OR lower(ef.uuid) LIKE ? "
        "OR lower(ef.context_display) LIKE ? OR lower(fo.alt_label_json) LIKE ?)",
        [like, like, like, like],
    )


def flow_page(
    connection: sqlite3.Connection,
    filters: FlowFilters,
    *,
    sort: str = "",
    page: int = 1,
) -> Page[FlowRow]:
    """One page of flows, filtered and sorted in SQL.

    Filtered and paged in SQL, not in Python: there are 94,270 elementary
    flows, and the ETL app's habit of reading everything and slicing afterwards
    is what made it unusable on the real database.

    *page* may be `common.RANDOM_PAGE`, which the view passes when the reader
    asked for nothing at all -- see :func:`common.resolve_page`.
    """
    base, params = _where(filters)
    order = order_by(sort, _SORT_COLUMNS, _DEFAULT_SORT)

    def run(clauses: list[str], values: list[Any]) -> Page[FlowRow]:
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        total = int(
            connection.execute(
                "SELECT count(*) FROM elementary_flows ef "
                "LEFT JOIN flow_objects fo ON fo.flow_object_id = ef.flow_object_id "
                f"{where}",
                values,
            ).fetchone()[0]
        )
        number = resolve_page(page, total)
        rows = connection.execute(
            f"{_SELECT} {where} ORDER BY {order} LIMIT ? OFFSET ?",
            [*values, PAGE_SIZE, (number - 1) * PAGE_SIZE],
        ).fetchall()
        return Page(rows=[_row(row) for row in rows], total=total, number=number)

    if not filters.query:
        return run(base, params)

    clause, search_params = _search_fts(filters)
    try:
        return run([*base, clause], [*params, *search_params])
    except sqlite3.OperationalError:
        clause, search_params = _search_like(filters)
        return run([*base, clause], [*params, *search_params])


#: The two filters whose value lives on `flow_objects` rather than on the flow:
#: `key -> (SQL column, how the value reads in a dropdown)`. A type is an IRI
#: and what belongs in a list of options is the name the vocabulary gives it; a
#: qualifier is already the local name of one.
_FACET_COLUMNS: dict[str, tuple[str, Any]] = {
    "type": ("flow_type", type_label),
    "qualifier": ("origin_qualifier", lambda value: value),
}


def _option_text(key: str, value: str) -> str:
    """The words a filter option is chosen by, without its count."""
    facet = _FACET_COLUMNS.get(key)
    return facet[1](value) if facet else value


def _option_label(key: str, value: str, count: int, *, unit: str = "") -> str:
    text = _option_text(key, value)
    if not unit:
        return f"{text} ({count:,})"
    return f"{text} ({count:,} {unit if count != 1 else unit.rstrip('s')})"


def _sorted_options(
    key: str, options: list[tuple[str, str]]
) -> list[tuple[str, str]]:
    """A dropdown in the order a reader looks things up in: alphabetically.

    Every one of these lists was ordered by how many rows the value has, which
    is the order the precomputation wrote them in and reads as no order at all
    once a list is longer than a screen: `Unit` offered fourteen units and
    finding `m3` meant reading all fourteen.  A count is still on every option,
    so the popular value is still recognisable -- it is just no longer the only
    way to find one.

    Case-folded, because `ENVO`-derived names are lower case and ChemROF's are
    not, and a case-sensitive sort files every capital before every lower-case
    letter.
    """
    return sorted(options, key=lambda option: (_option_text(key, option[0]).lower(),
                                               option[0].lower()))


def _facet_options_from_substances(
    connection: sqlite3.Connection, key: str
) -> list[tuple[str, str]]:
    """One facet's options for a database that has not been rebuilt.

    Counted in *substances*, and the label says so, because there is no cheap
    way to count them in flows here. Counting flows needs the join, and the join
    over 94,429 rows costs 652ms without `idx_flow_objects_facets` -- which a
    database written before this change does not have either. Adding it at read
    time is not an option: the webapp's connection is `mode=ro` with
    `PRAGMA query_only`, deliberately, because the pipeline owns this artifact.

    So the fallback is the honest cheap answer rather than a slow accurate one
    or a fast wrong one, and a rebuild replaces it with flow counts. The index
    still pays for itself here: `flow_type` and `origin_qualifier` are declared
    after `flow_object_json`, so even this GROUP BY steps over a multi-kilobyte
    blob per row -- 54ms without the index, 1.3ms with it.
    """
    column, _ = _FACET_COLUMNS[key]
    return [
        (
            row["value"],
            _option_label(key, row["value"], int(row["n"]), unit="substances"),
        )
        for row in connection.execute(
            f"SELECT {column} AS value, count(*) AS n FROM flow_objects "
            f"WHERE coalesce({column}, '') <> '' GROUP BY {column} "
            f"ORDER BY n DESC, {column}"
        )
    ]


def filter_options(
    connection: sqlite3.Connection, filters: FlowFilters
) -> dict[str, list[tuple[str, str]]]:
    """The values each filter offers, as `(value, label)`.

    Read from `filter_option_counts` when nothing is filtered, which is the
    common case and the one worth the precomputation. Once a filter is applied
    the counts no longer describe what is on screen, so the options are derived
    from the filtered set instead -- otherwise a reader is offered a source with
    "1,204" beside it that selects nothing.

    The two substance-layer facets do not narrow with the rest. They never have
    -- `type` was a global `GROUP BY` over `flow_objects` on both sides of this
    change -- and narrowing them means the join, which costs 652ms over 94,429
    rows. They are read from the precomputed counts whether or not anything else
    is filtered, which is also what keeps them counted in flows.

    Every option here is a count of flows. What it is *not* is the number of
    rows the filter returns: the precomputed counts do not exclude deprecated
    flows and the page does, so `EF 3.1` reads 93,993 above a result of 79,391.
    That is a magnitude and it predates this change; a *unit* that changed from
    one dropdown to the next would not be, which is what `biogenic (4)` above
    "of 28" was.
    """
    unfiltered = not (
        filters.source
        or filters.unit
        or any(filters.context.values())
    )
    has_counts = table_exists(connection, "filter_option_counts")
    options: dict[str, list[tuple[str, str]]] = {}

    if has_counts:
        # Filtered, only the facets are read from here: the rest are recomputed
        # against the filtered set below and would be overwritten anyway.
        groups = "" if unfiltered else "WHERE option_group IN ('type', 'qualifier') "
        rows = connection.execute(
            "SELECT option_group, option_key, option_value, item_count "
            f"FROM filter_option_counts {groups}"
            "ORDER BY option_group, option_key, item_count DESC, lower(option_value)"
        ).fetchall()
        for row in rows:
            group = row["option_group"]
            key = group if group != "context" else row["option_key"]
            value = row["option_value"]
            if not isinstance(value, str) or not value:
                continue
            options.setdefault(key, []).append(
                (value, _option_label(key, value, int(row["item_count"] or 0)))
            )

    if not unfiltered or not has_counts:
        clauses, params = _where(filters)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        for key, column in (("source", "ef.source"), ("unit", "ef.unit")):
            rows = connection.execute(
                f"SELECT {column} AS value, count(*) AS n FROM elementary_flows ef "
                "LEFT JOIN flow_objects fo ON fo.flow_object_id = ef.flow_object_id "
                f"{where} {'AND' if where else 'WHERE'} coalesce({column}, '') <> '' "
                f"GROUP BY {column} ORDER BY n DESC, lower({column})",
                params,
            ).fetchall()
            options[key] = [
                (row["value"], f"{row['value']} ({int(row['n']):,})") for row in rows
            ]
        for key in CONTEXT_KEYS:
            column = f"ef.context_{key}"
            rows = connection.execute(
                f"SELECT {column} AS value, count(*) AS n FROM elementary_flows ef "
                "LEFT JOIN flow_objects fo ON fo.flow_object_id = ef.flow_object_id "
                f"{where} {'AND' if where else 'WHERE'} coalesce({column}, '') <> '' "
                f"GROUP BY {column} ORDER BY n DESC, lower({column})",
                params,
            ).fetchall()
            options[key] = [
                (row["value"], f"{row['value']} ({int(row['n']):,})") for row in rows
            ]

    # A database written before the facets were precomputed is still readable,
    # and offering no options at all would read as "this list has no types".
    for key in _FACET_COLUMNS:
        if not options.get(key):
            options[key] = _facet_options_from_substances(connection, key)
    for key in ("source", "unit", *CONTEXT_KEYS):
        options.setdefault(key, [])
    return {key: _sorted_options(key, values) for key, values in options.items()}


def flow_detail(connection: sqlite3.Connection, uuid: str) -> FlowDetail | None:
    """One flow, or None if this database does not have it."""
    row = connection.execute(
        f"{_SELECT} WHERE ef.uuid = ?", (uuid,)
    ).fetchone()
    if row is None:
        return None

    # Joined to `flow_object_payloads`: `flow_json` no longer carries the
    # substance-level keys its object's other flows also had (#253), so the
    # labels and properties this page reads come back through
    # `merge_object_payload`.  `LEFT JOIN` because an object whose flows
    # disagreed has no payload row, and the flow's own keys win regardless.
    context_row = connection.execute(
        "SELECT ef.context_json AS context_json, ef.flow_json AS flow_json, "
        "p.payload_json AS payload_json FROM elementary_flows ef "
        "LEFT JOIN flow_object_payloads p ON p.flow_object_id = ef.flow_object_id "
        "WHERE ef.uuid = ?",
        (uuid,),
    ).fetchone()
    flow_json = merge_object_payload(
        load_json(context_row["flow_json"], {}), context_row["payload_json"]
    )
    classifications = load_json(row["classifications_json"], {})

    # `source_metadata_json` is read here and nowhere else on the page: it is
    # where the merge recorded why it put this row on this flow, and
    # `match_reason` is the only thing this page asks of it.  The base list is
    # recognised by its label rather than by the absence of a decision, because
    # "nothing was recorded" and "this row is the flow" are different answers.
    base_label = base_source_label()
    sources = [
        SourceReference(
            list_name=item["list_name"] or "",
            list_version=item["list_version"] or "",
            source_flow_uuid=item["source_flow_uuid"] or "",
            source_flow_name=item["source_flow_name"] or "",
            match_reason=match_reason(
                load_json(item["source_metadata_json"], {}),
                base_list=(
                    f"{item['list_name'] or ''} {item['list_version'] or ''}"
                ).strip() == base_label,
            ),
        )
        for item in connection.execute(
            "SELECT list_name, list_version, source_flow_uuid, source_flow_name, "
            "source_metadata_json "
            "FROM elementary_flow_sources WHERE elementary_flow_uuid = ? "
            "ORDER BY list_name, list_version",
            (uuid,),
        )
    ]

    associations = flow_json.get("concept_associations")
    return FlowDetail(
        uuid=uuid,
        name=row["pref_label_value"] or "",
        flow_object_id=row["flow_object_id"] or "",
        source=row["source"] or "",
        unit=row["unit"] or "",
        context_display=row["context_display"] or "",
        context=load_json(context_row["context_json"], {}) or {},
        flow_type=row["flow_type"] or "",
        origin_qualifier=row["origin_qualifier"] or "",
        lcia_factor_count=int(row["lcia_factor_count"] or 0),
        factor_counts=_factor_counts(connection, uuid),
        change_count=int(row["consensus_change_count"] or 0),
        is_deprecated=bool(row["is_deprecated"]),
        replaced_by_uuid=row["replaced_by_uuid"] or "",
        cas_numbers=_classification_values(classifications, CHEMINF_CAS_REGISTRY_NUMBER),
        ec_numbers=_classification_values(classifications, CHEMINF_EC_NUMBER),
        pref_labels=flow_json.get("prefLabel") if isinstance(flow_json.get("prefLabel"), list) else [],
        alt_labels=[label.value for label in coerce_alt_labels(flow_json.get("altLabel"))],
        sources=sources,
        concept_associations=associations if isinstance(associations, list) else [],
        flow_json=flow_json,
    )
