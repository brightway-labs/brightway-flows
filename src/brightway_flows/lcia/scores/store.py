"""The score comparison tables, in the file `build` and `characterise` wrote.

Seven relations, rewritten by every `compare-scores` run like the `lcia_*`
tables and for the same reason: the comparison is a projection of one build,
one characterisation and one set of artifacts, and running it again over the
same three has to produce the same rows.

The large one is `score_contributions`, and it is deliberately incomplete:
`lcia.scores.compare` keeps a contribution where the two sides disagree about
it or where it is at least a thousandth of the pair's score, and counts the
rest into `score_runs.stats_json`.  A reader asking "what moved this score"
gets every row that did; a reader asking "what is the whole inventory" has the
artifact.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import orjson
import structlog

from brightway_flows.domain.lcia.unit_process_scores import ScoreArtifact
from brightway_flows.lcia.scores.compare import ComparisonResult
from brightway_flows.pipeline.sqlite_schema import insert_statement, recreate

logger = structlog.get_logger(__name__)

#: The tables' own version, on `score_runs`.  Module-local (rule 13).
SCORES_SCHEMA_VERSION = 1

RELATIONS = (
    "score_runs",
    "score_releases",
    "score_unit_processes",
    "score_categories",
    "score_comparisons",
    "score_contributions",
    "score_flow_priorities",
)

SCHEMA = (
    """
    CREATE TABLE score_runs (
        run_id TEXT PRIMARY KEY,
        started_at TEXT NOT NULL,
        finished_at TEXT,
        schema_version INTEGER NOT NULL,
        build_run_id TEXT,
        lcia_run_id TEXT,
        stats_json TEXT NOT NULL DEFAULT '{}'
    )
    """,
    """
    CREATE TABLE score_releases (
        release_key TEXT PRIMARY KEY,
        list_name TEXT NOT NULL,
        list_version TEXT NOT NULL,
        system_model TEXT NOT NULL,
        method_family TEXT NOT NULL,
        artifact_path TEXT NOT NULL,
        artifact_sha256 TEXT NOT NULL,
        generator_json TEXT NOT NULL DEFAULT '{}',
        created_at TEXT NOT NULL,
        unit_processes INTEGER NOT NULL,
        sample_size INTEGER NOT NULL,
        sample_seed INTEGER NOT NULL,
        stats_json TEXT NOT NULL DEFAULT '{}'
    )
    """,
    """
    CREATE TABLE score_unit_processes (
        release_key TEXT NOT NULL,
        activity_code TEXT NOT NULL,
        activity_uuid TEXT NOT NULL,
        name TEXT NOT NULL,
        reference_product TEXT NOT NULL,
        product_amount REAL NOT NULL,
        product_unit TEXT NOT NULL,
        geography TEXT NOT NULL,
        classifications_json TEXT NOT NULL DEFAULT '{}',
        inventory_lines INTEGER NOT NULL,
        mapped_lines INTEGER NOT NULL,
        unmapped_lines INTEGER NOT NULL,
        PRIMARY KEY (release_key, activity_code)
    )
    """,
    # The vendor's categories in the vendor's words, and which of ours each
    # is about.  `impact_category_id` is NULL where the crosswalk has no row:
    # EF 3.0's three `metals` categories.
    """
    CREATE TABLE score_categories (
        release_key TEXT NOT NULL,
        category_key TEXT NOT NULL,
        method_family TEXT NOT NULL,
        category TEXT NOT NULL,
        indicator TEXT NOT NULL,
        unit TEXT NOT NULL,
        category_slug TEXT,
        impact_category_id TEXT,
        PRIMARY KEY (release_key, category_key)
    )
    """,
    """
    CREATE TABLE score_comparisons (
        release_key TEXT NOT NULL,
        activity_code TEXT NOT NULL,
        category_key TEXT NOT NULL,
        their_score REAL NOT NULL,
        our_score REAL NOT NULL,
        signed_ratio REAL,
        band TEXT NOT NULL,
        unmapped_share REAL NOT NULL,
        PRIMARY KEY (release_key, activity_code, category_key)
    )
    """,
    """
    CREATE INDEX score_comparisons_by_band ON score_comparisons (release_key, band)
    """,
    """
    CREATE TABLE score_contributions (
        release_key TEXT NOT NULL,
        activity_code TEXT NOT NULL,
        category_key TEXT NOT NULL,
        source_flow_uuid TEXT NOT NULL,
        elementary_flow_uuid TEXT,
        amount REAL NOT NULL,
        multiplier REAL,
        their_factor REAL,
        our_factor REAL,
        their_contribution REAL NOT NULL,
        our_contribution REAL NOT NULL,
        delta REAL NOT NULL,
        reason TEXT NOT NULL,
        PRIMARY KEY (release_key, activity_code, category_key, source_flow_uuid)
    )
    """,
    """
    CREATE INDEX score_contributions_by_flow
        ON score_contributions (release_key, category_key, source_flow_uuid)
    """,
    """
    CREATE TABLE score_flow_priorities (
        release_key TEXT NOT NULL,
        category_key TEXT NOT NULL,
        source_flow_uuid TEXT NOT NULL,
        elementary_flow_uuid TEXT,
        reason TEXT NOT NULL,
        datasets_affected INTEGER NOT NULL,
        abs_delta_sum REAL NOT NULL,
        share_of_category REAL NOT NULL,
        max_share REAL NOT NULL,
        PRIMARY KEY (release_key, category_key, source_flow_uuid)
    )
    """,
)

_RUN_COLUMNS = (
    "run_id", "started_at", "schema_version", "build_run_id", "lcia_run_id",
)
_RELEASE_COLUMNS = (
    "release_key", "list_name", "list_version", "system_model", "method_family",
    "artifact_path", "artifact_sha256", "generator_json", "created_at",
    "unit_processes", "sample_size", "sample_seed", "stats_json",
)
_UNIT_PROCESS_COLUMNS = (
    "release_key", "activity_code", "activity_uuid", "name", "reference_product",
    "product_amount", "product_unit", "geography", "classifications_json",
    "inventory_lines", "mapped_lines", "unmapped_lines",
)
_CATEGORY_COLUMNS = (
    "release_key", "category_key", "method_family", "category", "indicator", "unit",
    "category_slug", "impact_category_id",
)
_COMPARISON_COLUMNS = (
    "release_key", "activity_code", "category_key", "their_score", "our_score",
    "signed_ratio", "band", "unmapped_share",
)
_CONTRIBUTION_COLUMNS = (
    "release_key", "activity_code", "category_key", "source_flow_uuid",
    "elementary_flow_uuid", "amount", "multiplier", "their_factor", "our_factor",
    "their_contribution", "our_contribution", "delta", "reason",
)
_PRIORITY_COLUMNS = (
    "release_key", "category_key", "source_flow_uuid", "elementary_flow_uuid",
    "reason", "datasets_affected", "abs_delta_sum", "share_of_category", "max_share",
)


@dataclass(frozen=True, slots=True)
class ScoreRun:
    """One `compare-scores` run, and which build and characterisation it read."""

    run_id: str
    started_at: str
    build_run_id: str | None
    lcia_run_id: str | None


@dataclass(frozen=True, slots=True)
class ReleaseRecord:
    """Which artifact one release's rows came from."""

    release_key: str
    artifact_path: str
    artifact_sha256: str


def create_score_tables(connection: sqlite3.Connection) -> None:
    recreate(connection, relations=RELATIONS, schema=SCHEMA)


def start_run(db_path: Path, *, run: ScoreRun) -> None:
    """Drop and recreate the tables, and open the run's row."""
    connection = sqlite3.connect(db_path)
    try:
        create_score_tables(connection)
        connection.execute(
            insert_statement("score_runs", _RUN_COLUMNS),
            (run.run_id, run.started_at, SCORES_SCHEMA_VERSION, run.build_run_id, run.lcia_run_id),
        )
        connection.commit()
    finally:
        connection.close()


def write_release(
    db_path: Path,
    *,
    release: ReleaseRecord,
    artifact: ScoreArtifact,
    result: ComparisonResult,
) -> None:
    """One release's rows, into tables `start_run` already emptied."""
    key = release.release_key
    summaries = {s.activity_code: s for s in result.unit_processes}
    connection = sqlite3.connect(db_path)
    try:
        connection.execute(
            insert_statement("score_releases", _RELEASE_COLUMNS),
            (
                key,
                artifact.release.list_name,
                artifact.release.list_version,
                artifact.release.system_model,
                artifact.release.method_family,
                release.artifact_path,
                release.artifact_sha256,
                orjson.dumps(artifact.release.generator).decode(),
                artifact.release.created_at,
                len(artifact.unit_processes),
                artifact.release.sample_size,
                artifact.release.sample_seed,
                orjson.dumps(result.stats).decode(),
            ),
        )
        connection.executemany(
            insert_statement("score_unit_processes", _UNIT_PROCESS_COLUMNS),
            [
                (
                    key, p.activity_code, p.activity_uuid, p.name, p.reference_product,
                    p.product_amount, p.product_unit, p.geography,
                    orjson.dumps(p.classifications).decode(),
                    summaries[p.activity_code].inventory_lines,
                    summaries[p.activity_code].mapped_lines,
                    summaries[p.activity_code].unmapped_lines,
                )
                for p in artifact.unit_processes
            ],
        )
        connection.executemany(
            insert_statement("score_categories", _CATEGORY_COLUMNS),
            [
                (
                    key, c.key, c.method_family, c.category, c.indicator, c.unit,
                    c.slug, c.impact_category_id,
                )
                for c in result.categories
            ],
        )
        connection.executemany(
            insert_statement("score_comparisons", _COMPARISON_COLUMNS),
            [
                (
                    key, c.activity_code, c.category_key, c.their_score, c.our_score,
                    c.signed_ratio, str(c.band), c.unmapped_share,
                )
                for c in result.comparisons
            ],
        )
        connection.executemany(
            insert_statement("score_contributions", _CONTRIBUTION_COLUMNS),
            [
                (
                    key, c.activity_code, c.category_key, c.source_flow_uuid,
                    c.elementary_flow_uuid, c.amount, c.multiplier, c.their_factor,
                    c.our_factor, c.their_contribution, c.our_contribution, c.delta,
                    str(c.reason),
                )
                for c in result.contributions
            ],
        )
        connection.executemany(
            insert_statement("score_flow_priorities", _PRIORITY_COLUMNS),
            [
                (
                    key, p.category_key, p.source_flow_uuid, p.elementary_flow_uuid,
                    str(p.reason), p.datasets_affected, p.abs_delta_sum,
                    p.share_of_category, p.max_share,
                )
                for p in result.priorities
            ],
        )
        connection.commit()
    finally:
        connection.close()
    logger.info(
        "wrote_score_comparison",
        release=key,
        unit_processes=len(artifact.unit_processes),
        comparisons=len(result.comparisons),
        contributions=len(result.contributions),
        priorities=len(result.priorities),
    )


def finish_run(db_path: Path, *, run_id: str, finished_at: str, stats: dict[str, Any]) -> None:
    connection = sqlite3.connect(db_path)
    try:
        connection.execute(
            "UPDATE score_runs SET finished_at = ?, stats_json = ? WHERE run_id = ?",
            (finished_at, orjson.dumps(stats).decode(), run_id),
        )
        connection.commit()
    finally:
        connection.close()


def lcia_run_id(db_path: Path) -> str | None:
    """Which characterisation the consensus factors came from, or ``None``."""
    connection = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        row = connection.execute(
            "SELECT run_id FROM lcia_runs ORDER BY started_at DESC LIMIT 1"
        ).fetchone()
    except sqlite3.OperationalError:
        return None
    finally:
        connection.close()
    return str(row[0]) if row else None


def consensus_factors(
    db_path: Path, *, category_ids: dict[tuple[str, str], str]
) -> dict[tuple[str, str], dict[str, float]]:
    """``(method, category) -> {consensus flow uuid: amount}``, for ours.

    Geography ``''`` only: an aggregate inventory has no place to apply a
    regional factor to.  *category_ids* is
    ``(method slug, category slug) -> impact_category_id``, keyed on the method
    as well because two methods can share a category slug and mean two
    different numbers (#349).
    """
    by_id = {category_id: key for key, category_id in category_ids.items()}
    out: dict[tuple[str, str], dict[str, float]] = {key: {} for key in category_ids}
    connection = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        rows = connection.execute(
            "SELECT impact_category_id, elementary_flow_uuid, amount "
            "FROM lcia_characterization_factors WHERE geography = ''"
        )
        for category_id, flow_uuid, amount in rows:
            key = by_id.get(str(category_id))
            if key is not None:
                out[key][str(flow_uuid)] = float(amount)
    finally:
        connection.close()
    return out
