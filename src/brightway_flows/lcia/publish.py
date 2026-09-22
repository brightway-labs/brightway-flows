"""The two published LCIA artifacts, written from what a run produced.

`characterise` fills the `lcia_*` tables; this writes the same rows out as files
somebody can download without a SQLite client.  Two files, because they answer
two questions and one of them is small:

* **`lcia-factors.json.gz`** -- three implementations of EF 3.1, their 75
  categories and their 665,521 factors.  Gzipped for the same reason
  `harmonised-flows-simple.json.gz` is: it is the large one and it has consumers.
* **`lcia-differences.json`** -- §5's two reports, which are 22,107 rows and 83.
  A deliverable in its own right, and left uncompressed because it is small
  enough to open and its audience is people reading it rather than a program
  loading it.

Both carry `LCIA_SCHEMA_VERSION` and both have a generated JSON Schema in
`data/schemas/` (rule 21), so a reader can check a file against the shape its
publisher promised.

**Projections, not a third source of truth.**  Every number here is read off the
records the tables were written from, in the same call, so a file and the database
beside it cannot disagree about what the run found.
"""

from __future__ import annotations

import gzip
from pathlib import Path
from typing import Any
from uuid import UUID

import orjson
import structlog

from brightway_flows.domain.lcia.records import (
    LCIA_SCHEMA_VERSION,
    CharacterizationFactor,
    CoverageGap,
    Difference,
    ImpactCategory,
    LCIAMethod,
    PublishedDifferences,
    PublishedFactors,
)
from brightway_flows.lcia.matching import MatchedFactor

logger = structlog.get_logger(__name__)


def _methods(categories: dict[str, ImpactCategory]) -> list[LCIAMethod]:
    """One row per method, deduplicated by identifier.

    Three today, one per implementation: the categories carry the method they
    belong to, so this is a projection of them rather than a second declaration.
    """
    methods: dict[str, LCIAMethod] = {}
    for category in categories.values():
        methods.setdefault(str(category.method.id), category.method)
    return [methods[key] for key in sorted(methods)]


def _factor(matched: MatchedFactor, *, impact_category_id: str) -> CharacterizationFactor:
    """A matched row as the factor this list publishes.

    The identifiers on both sides are ours by the time this is called -- that is
    what the matching was for -- so the publisher's own flow identifier survives
    only as `source_flow_uuid`, where there was one.

    On the JRC's implementation that identifier is one of ours too, because EF is
    the base list, and it is filled in exactly where the number was read off a
    flow this build has since retired and carried onto the one that replaced it
    (#163).  The identifier is in the export's `redirects`, so a reader meeting
    it there can see where the number came from.
    """
    return CharacterizationFactor(
        elementary_flow_uuid=matched.elementary_flow_uuid,
        impact_category_id=UUID(impact_category_id),
        amount=matched.factor.amount,
        geography=matched.factor.geography,
        derivation=matched.derivation,
        source_flow_uuid=matched.source_flow_uuid,
    )


def build_factors_document(
    *,
    categories: dict[str, ImpactCategory],
    factors: dict[str, list[MatchedFactor]],
    stats: dict[str, Any],
) -> PublishedFactors:
    """Project a run onto `lcia-factors.json.gz`.

    *categories* is every category this list publishes, keyed by identifier, and
    *factors* is what reached a flow, keyed the same way -- the two arguments
    `write_characterisation` takes, so the file and the tables are written from
    one thing.

    The factors are ordered by category and then by the order they were matched
    in, which is the order the source stated them: a diff between two runs of an
    unchanged input should be empty rather than a reshuffle.
    """
    ordered = sorted(categories)
    return PublishedFactors(
        schema_version=LCIA_SCHEMA_VERSION,
        methods=_methods(categories),
        impact_categories=[categories[key] for key in ordered],
        characterization_factors=[
            _factor(matched, impact_category_id=key)
            for key in ordered
            for matched in factors.get(key, ())
        ],
        stats=dict(stats),
    )


def build_differences_document(
    *,
    differences: list[Difference],
    coverage: list[CoverageGap],
    stats: dict[str, Any],
) -> PublishedDifferences:
    """Project a run onto `lcia-differences.json`, both of §5's reports."""
    return PublishedDifferences(
        schema_version=LCIA_SCHEMA_VERSION,
        differences=sorted(
            differences,
            key=lambda row: (
                row.elementary_flow_uuid, row.category_slug, row.geography
            ),
        ),
        coverage=list(coverage),
        stats=dict(stats),
    )


def artifact_paths(db_path: Path) -> tuple[Path, Path]:
    """Where a run's two artifacts go: beside the database they describe.

    For a normal run that is the data directory, so the files are exactly
    `LCIA_FACTORS_FILEPATH` and `LCIA_DIFFERENCES_FILEPATH`; for a run against a
    database somewhere else it is that somewhere else.  Derived rather than
    defaulted on purpose -- a writer whose default is the shared data directory
    lets a test against a temporary build overwrite the published files.
    """
    from brightway_flows.filesystem import (
        LCIA_DIFFERENCES_FILEPATH,
        LCIA_FACTORS_FILEPATH,
    )

    directory = Path(db_path).parent
    return (
        directory / LCIA_FACTORS_FILEPATH.name,
        directory / LCIA_DIFFERENCES_FILEPATH.name,
    )


def write_factors(document: PublishedFactors, output_path: Path) -> Path:
    """Write `lcia-factors.json.gz`."""
    path = Path(output_path)
    path.write_bytes(
        gzip.compress(orjson.dumps(document.to_dict(), option=orjson.OPT_INDENT_2))
    )
    logger.info(
        "wrote_lcia_factors",
        path=str(path),
        categories=len(document.impact_categories),
        factors=len(document.characterization_factors),
        bytes=path.stat().st_size,
    )
    return path


def write_differences(document: PublishedDifferences, output_path: Path) -> Path:
    """Write `lcia-differences.json`."""
    path = Path(output_path)
    path.write_bytes(orjson.dumps(document.to_dict(), option=orjson.OPT_INDENT_2))
    logger.info(
        "wrote_lcia_differences",
        path=str(path),
        differences=len(document.differences),
        coverage=len(document.coverage),
        bytes=path.stat().st_size,
    )
    return path
