"""`compare-scores`: the order the steps run in.

After `build` and after `characterise`, reading what both wrote and the
artifacts the brightway exporter wrote, and writing the `score_*` tables
into the same file.  Like `characterise`, it touches nothing the earlier
stages own, and iterating on it costs seconds.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import uuid
from pathlib import Path
from typing import Any

import structlog

from brightway_flows.domain.lcia.crosswalk import (
    by_stated_method_category,
    lcia_methods,
)
from brightway_flows.domain.lcia.unit_process_scores import (
    ScoreArtifact,
    load_score_artifact,
)
from brightway_flows.lcia.categories import consensus_categories_for
from brightway_flows.lcia.matching import merge_targets
from brightway_flows.lcia.scores.compare import (
    ComparisonResult,
    compare_release,
    match_categories,
)
from brightway_flows.lcia.scores.store import (
    ReleaseRecord,
    ScoreRun,
    consensus_factors,
    finish_run,
    lcia_run_id,
    start_run,
    write_release,
)
from brightway_flows.lcia.store import build_run_id
from brightway_flows.settings import AssessedRelease, ScoreComparisonSettings

logger = structlog.get_logger(__name__)


def consensus_category_ids() -> dict[tuple[str, str], str]:
    """``(method slug, category slug) -> impact_category_id``, for ours.

    Over every method, because a score names a category by the words its own
    release used and `by_stated_method_category` has already said which of ours
    that is.  Keyed on the method as well as the slug, because a slug is unique
    inside a method and not across them: #346 published Stepwise 2006 beside
    EF 3.1, both of which have an `acidification` and a
    `eutrophication-terrestrial`, and a map keyed on the slug alone kept
    whichever method was read last.  What that cost is #349: ecoinvent's EF
    acidification was scored against Stepwise's twelve EDIP factors rather than
    EF's 935, over both releases, and 626 (unit process, category) pairs moved a
    band or more.
    """
    return {
        (method.slug, str(category.meta["iri"]).rsplit("/", 1)[-1]): str(category.id)
        for method in lcia_methods()
        for category in consensus_categories_for(method.slug)
    }


def compare_artifact(
    artifact: ScoreArtifact,
    *,
    db_path: Path,
    release: AssessedRelease,
    our_factors: dict[tuple[str, str], dict[str, float]],
    category_ids: dict[tuple[str, str], str],
) -> ComparisonResult:
    """One artifact against one build, in memory."""
    targets = merge_targets(
        db_path, list_name=release.list_name, list_version=release.list_version
    )
    categories = match_categories(
        artifact.categories, by_stated_method_category(), consensus_ids=category_ids
    )
    return compare_release(
        artifact, categories=categories, targets=targets, our_factors=our_factors
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def compare_scores(
    db_path: Path | None = None,
    *,
    settings: ScoreComparisonSettings | None = None,
    releases: list[str] | None = None,
) -> dict[str, Any]:
    """Score every configured release's artifact against the build, and write.

    An absent artifact is logged and counted, not raised: the exporter runs
    under another Python on another schedule, and a release nobody has
    exported yet is not a failed comparison.  A database nobody has
    characterised *is* refused, because there are then no factors of ours to
    compare against.

    :returns: the run's stats, as `score_runs.stats_json` holds them.
    """
    from brightway_flows.filesystem import CONSENSUS_DB_FILEPATH

    db_path = Path(db_path or CONSENSUS_DB_FILEPATH)
    if settings is None:
        from brightway_flows.settings import get_settings

        settings = get_settings().score_comparison
    characterisation = lcia_run_id(db_path)
    if characterisation is None:
        raise RuntimeError(
            f"{db_path} has no characterisation; run `characterise` before "
            "`compare-scores`, or there are no factors of ours to compare against."
        )

    run = ScoreRun(
        run_id=uuid.uuid4().hex,
        started_at=dt.datetime.now(dt.timezone.utc).isoformat(),
        build_run_id=build_run_id(db_path),
        lcia_run_id=characterisation,
    )
    start_run(db_path, run=run)

    category_ids = consensus_category_ids()
    our_factors = consensus_factors(db_path, category_ids=category_ids)
    wanted = [r for r in settings.releases if not releases or r.key in releases]
    if releases:
        unknown = set(releases) - {r.key for r in wanted}
        if unknown:
            raise KeyError(
                f"not configured: {sorted(unknown)}; configured: "
                f"{[r.key for r in settings.releases]}"
            )

    stats: dict[str, Any] = {
        "releases_configured": len(settings.releases),
        "releases_compared": 0,
        "releases_without_artifact": 0,
    }
    for release in wanted:
        path = settings.artifact_path(release)
        if not path.exists():
            logger.warning("score_artifact_absent", release=release.key, path=str(path))
            stats["releases_without_artifact"] += 1
            continue
        artifact = load_score_artifact(path)
        if artifact.release.key != release.key:
            raise ValueError(
                f"{path} describes {artifact.release.key}, not {release.key}"
            )
        result = compare_artifact(
            artifact,
            db_path=db_path,
            release=release,
            our_factors=our_factors,
            category_ids=category_ids,
        )
        write_release(
            db_path,
            release=ReleaseRecord(
                release_key=release.key,
                artifact_path=str(path),
                artifact_sha256=_sha256(path),
            ),
            artifact=artifact,
            result=result,
        )
        stats["releases_compared"] += 1
        for name, value in result.stats.items():
            stats[f"{release.key}.{name}"] = value
    finish_run(
        db_path,
        run_id=run.run_id,
        finished_at=dt.datetime.now(dt.timezone.utc).isoformat(),
        stats=stats,
    )
    return stats
