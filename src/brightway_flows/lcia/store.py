"""The characterisation tables, in the file `build` already wrote.

Six relations, a view and a run record, beside the flow tables rather than in a
database of their own: a factor is about a flow, and a reader asking what a
substance is worth under a category should not have to join across two files to
find out.

The view is the exception to everything below.  `lcia_flow_factor_counts` is a
flow's factors counted per implementation -- the count `elementary_flows`
cannot carry now that there are three of them -- and it is a view precisely so
that it is not a copy: `lcia_factor_count` on the flow keeps its meaning, the
JRC's non-zero factors, and this reproduces that number rather than restating it.

**Rewritten by every run, like the flow tables.**  A `characterise` run is the
whole content of these tables -- there is no history to accumulate, because the
factors are a projection of one build plus two published files, and running it
again against an unchanged build has to produce the same rows.  The merge tables
are the other convention, additive, because a merge outcome is about a source list
at a moment; this is not that.

**The uniqueness invariant is a primary key.**  There is one factor per (impact
category, flow, geography), which `ImpactCategory` can only half enforce -- it can
check that the factors it holds name it, not that no two of them name one flow.
Here it is a `UNIQUE` constraint, so a matching mistake is a failed write rather
than two rows a reader has to choose between.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import orjson
import structlog

from brightway_flows.domain.lcia.records import (
    LCIA_SCHEMA_VERSION,
    ImpactCategory,
)
from brightway_flows.lcia.matching import MatchedFactor
from brightway_flows.lcia.differences import CoverageGap, Difference
from brightway_flows.lcia.report import Finding
from brightway_flows.pipeline.sqlite_schema import insert_statement, recreate

logger = structlog.get_logger(__name__)

#: Re-exported from `domain.lcia.records`, where the records these tables are
#: written from live.  One number for the tables and the published files, because
#: both are renderings of those records; the published flow list's unqualified
#: `SCHEMA_VERSION` is a different thing about a different artifact (rule 13).
__all__ = ["LCIA_SCHEMA_VERSION"]

#: Every relation this module owns.  A relation it no longer creates belongs here
#: too, so a rebuild in place does not leave its rows behind.
RELATIONS = (
    "lcia_flow_factor_counts",
    "lcia_runs",
    "lcia_methods",
    "lcia_impact_categories",
    "lcia_characterization_factors",
    "lcia_findings",
    "lcia_differences",
    "lcia_coverage",
)

_RUN_COLUMNS = (
    "run_id",
    "started_at",
    "finished_at",
    "schema_version",
    "build_run_id",
    "stats_json",
)

_METHOD_COLUMNS = ("id", "name", "iri", "meta_json")

_CATEGORY_COLUMNS = (
    "id",
    "iri",
    "method_id",
    "name",
    "version",
    "implemented_by",
    "timeframe",
    "area_of_protection",
    "midpoint_endpoint",
    "uncertainty_cutoff",
    "unit_iri",
    "indicator",
    "category_group",
    "description",
    "factor_count",
    "flow_count",
    "non_zero_factor_count",
    "meta_json",
)

_FACTOR_COLUMNS = (
    "impact_category_id",
    "elementary_flow_uuid",
    "geography",
    "amount",
    "source_flow_uuid",
    "derivation",
)

_DIFFERENCE_COLUMNS = (
    "method",
    "elementary_flow_uuid",
    "category_slug",
    "geography",
    "implemented_by",
    "amount",
    "source_flow_uuid",
    "band",
    "ratio",
    "derivation",
)

_COVERAGE_COLUMNS = ("method", "implemented_by", "dimension", "value", "flows")

_FINDING_COLUMNS = (
    "kind",
    "implemented_by",
    "elementary_flow_uuid",
    "impact_category_id",
    "detail",
    "context_json",
)

SCHEMA = (
    """
    CREATE TABLE lcia_runs (
        run_id TEXT PRIMARY KEY,
        started_at TEXT NOT NULL,
        finished_at TEXT,
        schema_version INTEGER NOT NULL,
        build_run_id TEXT,
        stats_json TEXT NOT NULL DEFAULT '{}'
    )
    """,
    """
    CREATE TABLE lcia_methods (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        iri TEXT NOT NULL,
        meta_json TEXT NOT NULL DEFAULT '{}'
    )
    """,
    """
    CREATE TABLE lcia_impact_categories (
        id TEXT PRIMARY KEY,
        iri TEXT NOT NULL UNIQUE,
        method_id TEXT NOT NULL,
        name TEXT NOT NULL,
        version TEXT NOT NULL,
        implemented_by TEXT NOT NULL,
        timeframe TEXT NOT NULL,
        area_of_protection TEXT NOT NULL,
        midpoint_endpoint TEXT NOT NULL,
        uncertainty_cutoff TEXT NOT NULL,
        unit_iri TEXT NOT NULL,
        indicator TEXT,
        category_group TEXT,
        description TEXT,
        -- What this category holds, counted once by the writer that has the rows
        -- in hand.  A reader wanting "how much does each implementation say"
        -- would otherwise group over every factor in the database to answer it:
        -- 519 ms against 665,521 rows, on the landing page of the section, for
        -- three numbers this pass already knows.
        factor_count INTEGER NOT NULL DEFAULT 0,
        flow_count INTEGER NOT NULL DEFAULT 0,
        non_zero_factor_count INTEGER NOT NULL DEFAULT 0,
        meta_json TEXT NOT NULL DEFAULT '{}'
    )
    """,
    # The invariant, as a constraint: one factor per (category, flow, geography).
    # The place is in the key because EF states one on 42,871 of its factors and
    # two places are two factors -- `Land use` for one flow is -522.81 in `ES-CA`
    # and -227.0 in `YE`.  It is `''` rather than NULL where there is none, because
    # SQLite treats NULLs as distinct in a key and the invariant would not hold.
    """
    CREATE TABLE lcia_characterization_factors (
        impact_category_id TEXT NOT NULL,
        elementary_flow_uuid TEXT NOT NULL,
        geography TEXT NOT NULL DEFAULT '',
        amount REAL NOT NULL,
        source_flow_uuid TEXT,
        -- How this list arrived at the number, on the implementation that is
        -- ours.  NULL on a transcription, which arrives at nothing: it says what
        -- its publisher said.
        derivation TEXT,
        PRIMARY KEY (impact_category_id, elementary_flow_uuid, geography)
    )
    """,
    """
    CREATE INDEX lcia_factors_by_flow
        ON lcia_characterization_factors (elementary_flow_uuid)
    """,
    # The difference report (§5): one row per (triple, implementation) where more
    # than one implementation states a factor for the triple.  Long form and not a
    # column per implementation, because every source list that ships factors is
    # one and there will be more than two: a `jrc_amount` column cannot hold a
    # third, and a schema that has to change to compare one more list is a schema
    # that will be wrong before it is changed.  `band` and `ratio` are properties
    # of the triple and repeat across its rows, which is the cost of the shape.
    #
    # Where only one implementation speaks there is no comparison to record --
    # those are counted in the run's stats under `only:<implementation>`, because
    # 245,380 rows of "nobody disagreed, because nobody else spoke" is a fact
    # about differently sized flow lists and not a difference.
    """
    CREATE TABLE lcia_differences (
        method TEXT NOT NULL,
        elementary_flow_uuid TEXT NOT NULL,
        category_slug TEXT NOT NULL,
        geography TEXT NOT NULL DEFAULT '',
        implemented_by TEXT NOT NULL,
        amount REAL NOT NULL,
        source_flow_uuid TEXT,
        band TEXT NOT NULL,
        ratio REAL,
        derivation TEXT,
        PRIMARY KEY (
            method, elementary_flow_uuid, category_slug, geography, implemented_by
        )
    )
    """,
    """
    CREATE INDEX lcia_differences_by_band ON lcia_differences (band)
    """,
    """
    CREATE INDEX lcia_differences_by_implementation
        ON lcia_differences (implemented_by)
    """,
    # And the coverage summary: counts by compartment and by category, never a
    # list.  Asked as a list it is 5,668 rows of which most are a substance that
    # has no global-warming potential, and absence is the right answer there.
    """
    CREATE TABLE lcia_coverage (
        method TEXT NOT NULL,
        implemented_by TEXT NOT NULL,
        dimension TEXT NOT NULL,
        value TEXT NOT NULL,
        flows INTEGER NOT NULL,
        PRIMARY KEY (method, implemented_by, dimension, value)
    )
    """,
    # `elementary_flows.lcia_factor_count` keeps the meaning it has always had --
    # the JRC's non-zero factors -- so nothing moves under a reader who has it in
    # a query.  This is the per-implementation count beside it, and a view rather
    # than a table on purpose: computed from the factors themselves it cannot
    # drift from them, which is the whole property a second count has to have.
    # `tests/test_published_factors.py` states the invariant it must reproduce.
    """
    CREATE VIEW lcia_flow_factor_counts AS
    SELECT
        factor.elementary_flow_uuid AS elementary_flow_uuid,
        category.implemented_by AS implemented_by,
        count(*) AS factors,
        sum(CASE WHEN factor.amount != 0 THEN 1 ELSE 0 END) AS non_zero_factors
    FROM lcia_characterization_factors AS factor
    JOIN lcia_impact_categories AS category
        ON category.id = factor.impact_category_id
    GROUP BY factor.elementary_flow_uuid, category.implemented_by
    """,
    """
    CREATE TABLE lcia_findings (
        kind TEXT NOT NULL,
        implemented_by TEXT NOT NULL,
        elementary_flow_uuid TEXT,
        impact_category_id TEXT,
        detail TEXT NOT NULL,
        context_json TEXT NOT NULL DEFAULT '{}'
    )
    """,
)


@dataclass(frozen=True, slots=True)
class CharacterisationRun:
    """One `characterise` run, and which build it read."""

    run_id: str
    started_at: str
    build_run_id: str | None


def _category_row(
    category: ImpactCategory, *, factors: list[MatchedFactor]
) -> tuple:
    """One category, with what it holds counted here rather than by a reader."""
    return (
        str(category.id),
        str(category.meta.get("iri") or ""),
        str(category.method.id),
        category.name,
        category.version,
        category.implemented_by,
        str(category.timeframe),
        str(category.area_of_protection),
        str(category.midpoint_endpoint),
        str(category.uncertainty_cutoff),
        category.unit_iri,
        category.indicator,
        category.category_group,
        category.description,
        len(factors),
        len({matched.elementary_flow_uuid for matched in factors}),
        sum(1 for matched in factors if matched.factor.amount != 0),
        orjson.dumps(category.meta or {}).decode(),
    )


def _factor_row(matched: MatchedFactor, *, impact_category_id: str) -> tuple:
    return (
        impact_category_id,
        matched.elementary_flow_uuid,
        matched.factor.geography or "",
        matched.factor.amount,
        matched.source_flow_uuid,
        matched.derivation,
    )


def _difference_row(difference: Difference) -> tuple:
    return (
        difference.method,
        difference.elementary_flow_uuid,
        difference.category_slug,
        difference.geography,
        difference.implemented_by,
        difference.amount,
        difference.source_flow_uuid,
        str(difference.band),
        difference.ratio,
        difference.derivation,
    )


def _coverage_row(gap: CoverageGap) -> tuple:
    return (gap.method, gap.implemented_by, gap.dimension, gap.value, gap.flows)


def _finding_row(finding: Finding) -> tuple:
    return (
        str(finding.kind),
        finding.implemented_by,
        finding.elementary_flow_uuid,
        finding.impact_category_id,
        finding.detail,
        orjson.dumps(finding.context or {}).decode(),
    )


def build_run_id(db_path: Path) -> str | None:
    """Which build these factors are against.

    Recorded rather than assumed: the factors are a projection of one build, and a
    reader holding a factor and a flow needs to know they came from the same run.
    """
    connection = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        row = connection.execute(
            "SELECT run_id FROM pipeline_runs ORDER BY timestamp DESC LIMIT 1"
        ).fetchone()
    except sqlite3.OperationalError:  # pragma: no cover - a database without one
        return None
    finally:
        connection.close()
    return str(row[0]) if row else None


def write_characterisation(
    db_path: Path,
    *,
    run: CharacterisationRun,
    categories: dict[str, ImpactCategory],
    factors: dict[str, list[MatchedFactor]],
    findings: list[Finding],
    differences: list[Difference],
    coverage: list[CoverageGap],
    stats: dict[str, Any],
) -> None:
    """Replace the characterisation tables with what this run produced.

    *categories* and *factors* are keyed by impact-category id: the categories are
    every one this list publishes, including those a later pass will fill, and the
    factors are what reached a flow.

    :raises sqlite3.IntegrityError: if two factors claim one (category, flow,
        geography). That is the invariant, and a write is the right place to
        discover it broken.
    """
    connection = sqlite3.connect(db_path)
    try:
        recreate(connection, relations=RELATIONS, schema=SCHEMA)
        connection.execute(
            insert_statement("lcia_runs", _RUN_COLUMNS),
            (
                run.run_id,
                run.started_at,
                None,
                LCIA_SCHEMA_VERSION,
                run.build_run_id,
                orjson.dumps(stats).decode(),
            ),
        )
        methods = {
            str(category.method.id): category.method for category in categories.values()
        }
        connection.executemany(
            insert_statement("lcia_methods", _METHOD_COLUMNS),
            [
                (
                    str(method.id),
                    method.name,
                    str((method.meta or {}).get("iri") or ""),
                    orjson.dumps(method.meta or {}).decode(),
                )
                for method in methods.values()
            ],
        )
        connection.executemany(
            insert_statement("lcia_impact_categories", _CATEGORY_COLUMNS),
            [
                _category_row(category, factors=list(factors.get(category_id, ())))
                for category_id, category in categories.items()
            ],
        )
        connection.executemany(
            insert_statement("lcia_characterization_factors", _FACTOR_COLUMNS),
            [
                _factor_row(matched, impact_category_id=category_id)
                for category_id, matched_factors in factors.items()
                for matched in matched_factors
            ],
        )
        connection.executemany(
            insert_statement("lcia_findings", _FINDING_COLUMNS),
            [_finding_row(finding) for finding in findings],
        )
        connection.executemany(
            insert_statement("lcia_differences", _DIFFERENCE_COLUMNS),
            [_difference_row(difference) for difference in differences],
        )
        connection.executemany(
            insert_statement("lcia_coverage", _COVERAGE_COLUMNS),
            [_coverage_row(gap) for gap in coverage],
        )
        connection.commit()
    finally:
        connection.close()
    logger.info(
        "wrote_characterisation",
        run_id=run.run_id,
        categories=len(categories),
        factors=sum(len(rows) for rows in factors.values()),
        findings=len(findings),
        differences=len(differences),
        coverage=len(coverage),
    )


def finish_run(db_path: Path, *, run_id: str, finished_at: str) -> None:
    """Close a run, once every implementation has been written."""
    connection = sqlite3.connect(db_path)
    try:
        connection.execute(
            "UPDATE lcia_runs SET finished_at = ? WHERE run_id = ?",
            (finished_at, run_id),
        )
        connection.commit()
    finally:
        connection.close()
