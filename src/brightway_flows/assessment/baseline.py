"""The last recorded build, committed, so that a diff shows what moved.

`expectations/baseline.json` holds two things: every measure's value, and every
expectation's status, as of the build somebody last ran `assess --record`
against.  It is committed for one reason -- a pull request that improves the
matching then carries

    -    "merge.bafu-2026-v1.unmatched": 275,
    +    "merge.bafu-2026-v1.unmatched": 22,

in its own diff, and the claim in the description becomes checkable by reading
the patch.  A history file in the data directory could hold the same numbers,
but only on the machine that produced them, and a reviewer cannot see it.

**It records, it does not gate.**  A measure that moved is reported; nothing
here decides whether the movement was allowed.  Deciding that is what an
expectation is for, because a threshold on a population ("no more than 300
unmatched rows") passes for the wrong reason as easily as the right one, while
"this row lands on this flow" cannot.

**A baseline is only comparable to a build of the same shape.**  Recorded
against a `--max-flows` run, it would compare a prefix of the base list to the
whole of it and report every measure as collapsed, so `write_baseline` refuses
a bounded run and `compare_to_baseline` says so rather than printing nonsense.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import orjson
import structlog

from brightway_flows.assessment.evaluate import Assessment, Status
from brightway_flows.assessment.expectations import EXPECTATIONS_DIR, BASELINE_FILENAME
from brightway_flows.assessment.measures import Direction

logger = structlog.get_logger(__name__)

#: The baseline file's own format, versioned apart from the expectation files
#: because the two change for different reasons.  Rule 13.
BASELINE_SCHEMA_VERSION = 1

BASELINE_DESCRIPTION = (
    "The last build somebody recorded, so that a change to the pipeline shows "
    "up as a diff in this file rather than as a number in a terminal nobody "
    "kept. `measures` is every counter the assessment collects; `expectations` "
    "is the status each expectation had. Rewrite it with "
    "`brightway-flows assess --record` after a full build, and never after "
    "a `--max-flows` run: a bounded run measures a prefix of the base list and "
    "would record every count as collapsed. Nothing here gates anything -- a "
    "measure that moves is reported, and whether the movement was right is what "
    "the expectations say."
)


class BaselineError(ValueError):
    """The baseline file cannot be read, or should not be written."""


@dataclass(frozen=True)
class Baseline:
    measures: dict[str, int] = field(default_factory=dict)
    statuses: dict[str, str] = field(default_factory=dict)
    recorded: dict[str, Any] = field(default_factory=dict)
    path: str = ""

    @property
    def exists(self) -> bool:
        return bool(self.measures or self.statuses)


@dataclass(frozen=True)
class MeasureDelta:
    key: str
    title: str
    before: int | None
    after: int | None
    direction: Direction

    @property
    def change(self) -> int:
        return (self.after or 0) - (self.before or 0)

    @property
    def verdict(self) -> str:
        """`improved`, `regressed`, `moved`, `new`, or `gone`.

        `moved` is not a hedge: most measures have no better direction, and
        calling a neutral change an improvement would put a judgement in the
        report that nobody made.
        """
        if self.before is None:
            return "new"
        if self.after is None:
            return "gone"
        if self.change == 0:
            return "unchanged"
        if self.direction is Direction.HIGHER:
            return "improved" if self.change > 0 else "regressed"
        if self.direction is Direction.LOWER:
            return "improved" if self.change < 0 else "regressed"
        return "moved"


@dataclass(frozen=True)
class StatusChange:
    expectation_id: str
    title: str
    before: str
    after: str

    @property
    def verdict(self) -> str:
        if self.after == Status.MET.value and self.before != Status.MET.value:
            return "now met"
        if self.before == Status.MET.value and self.after != Status.MET.value:
            return "regressed"
        return "changed"


@dataclass(frozen=True)
class BaselineComparison:
    baseline: Baseline
    #: Only the measures that moved.  A build has some fifteen hundred of them
    #: and a report of "unchanged" fifteen hundred times is not a report.
    measures: tuple[MeasureDelta, ...] = ()
    statuses: tuple[StatusChange, ...] = ()
    #: Set where the two runs are not comparable, and say why.
    incomparable: str = ""

    @property
    def improved(self) -> tuple[MeasureDelta, ...]:
        return tuple(d for d in self.measures if d.verdict == "improved")

    @property
    def regressed(self) -> tuple[MeasureDelta, ...]:
        return tuple(d for d in self.measures if d.verdict == "regressed")


def baseline_path(directory: Path | None = None) -> Path:
    return (directory or EXPECTATIONS_DIR) / BASELINE_FILENAME


def load_baseline(directory: Path | None = None) -> Baseline:
    """The recorded build, or an empty baseline if none has been recorded.

    A missing file is the normal state of a fresh checkout and of a repository
    that has not adopted this yet, so it is not an error; every comparison
    degrades to "nothing to compare against".
    """
    path = baseline_path(directory)
    if not path.exists():
        return Baseline(path=str(path))
    try:
        payload = orjson.loads(path.read_bytes())
    except orjson.JSONDecodeError as exc:
        raise BaselineError(f"{path} is not valid JSON -- {exc}") from exc
    version = payload.get("schema_version")
    if version != BASELINE_SCHEMA_VERSION:
        raise BaselineError(
            f"{path} has schema_version {version!r}, this build reads {BASELINE_SCHEMA_VERSION}"
        )
    return Baseline(
        measures={str(k): int(v) for k, v in (payload.get("measures") or {}).items()},
        statuses={str(k): str(v) for k, v in (payload.get("expectations") or {}).items()},
        recorded=dict(payload.get("recorded") or {}),
        path=str(path),
    )


def write_baseline(assessment: Assessment, directory: Path | None = None) -> Path:
    """Record *assessment* as the baseline, and return where it was written."""
    if assessment.run.max_flows:
        raise BaselineError(
            f"this build was bounded to {assessment.run.max_flows} flows. A baseline "
            "recorded from it would compare a prefix of the base list against the "
            "whole of it on the next run, and report every measure as collapsed. "
            "Record from a full build."
        )
    if assessment.run.bounded_sources:
        # The same objection on the other axis.  `--max-rows` bounds the merge,
        # so every `merge.*` measure describes a prefix of each source list, and
        # a baseline recorded from it would read as though the next full run had
        # matched thousands of rows out of nowhere.
        raise BaselineError(
            "this build bounded its merge with --max-rows ("
            + "; ".join(assessment.run.bounded_sources)
            + "). Every merge measure describes a prefix of the source list. "
            "Record from a full build."
        )
    path = baseline_path(directory)
    payload = {
        "schema_version": BASELINE_SCHEMA_VERSION,
        "description": BASELINE_DESCRIPTION,
        "recorded": {
            "pipeline_run_id": assessment.run.pipeline_run_id,
            "merge_run_id": assessment.run.merge_run_id,
            "timestamp": assessment.run.timestamp,
            "merge_finished_at": assessment.run.merge_finished_at,
            "sources": list(assessment.run.sources),
            "expectation_counts": assessment.counts,
        },
        "measures": {key: measure.value for key, measure in sorted(assessment.measures.items())},
        "expectations": {
            result.expectation.id: result.status.value
            for result in sorted(assessment.results, key=lambda r: r.expectation.id)
        },
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(orjson.dumps(payload, option=orjson.OPT_INDENT_2 | orjson.OPT_APPEND_NEWLINE))
    logger.info(
        "wrote_baseline",
        path=str(path),
        measures=len(payload["measures"]),
        expectations=len(payload["expectations"]),
    )
    return path


def compare_to_baseline(
    assessment: Assessment, baseline: Baseline | None = None, directory: Path | None = None
) -> BaselineComparison:
    """What moved between the recorded build and this one."""
    baseline = baseline if baseline is not None else load_baseline(directory)
    if not baseline.exists:
        return BaselineComparison(
            baseline=baseline,
            incomparable=(
                "no baseline recorded yet. `assess --record` after a full build "
                "writes one, and every later run is compared against it."
            ),
        )
    if assessment.run.max_flows:
        return BaselineComparison(
            baseline=baseline,
            incomparable=(
                f"this build was bounded to {assessment.run.max_flows} flows, and the "
                "baseline is a full build. The counts are not comparable; the "
                "expectations still are."
            ),
        )
    if assessment.run.bounded_sources:
        return BaselineComparison(
            baseline=baseline,
            incomparable=(
                "this build bounded its merge with --max-rows ("
                + "; ".join(assessment.run.bounded_sources)
                + "), and the baseline is a full build. The counts are not "
                "comparable; the expectations still are."
            ),
        )
    # A build merges nothing unless asked (#99), so "the same pipeline, run
    # again" and "a different set of source lists" produce the same shape of
    # result and mean entirely different things.  Comparing across them reports
    # every `merge.*` measure of a list this run did not merge as `gone`, which
    # reads as a catastrophic regression and is only a different `--source`.
    recorded_sources = tuple(baseline.recorded.get("sources") or ())
    if recorded_sources != assessment.run.sources:
        return BaselineComparison(
            baseline=baseline,
            incomparable=(
                "this build merged "
                + (", ".join(assessment.run.sources) or "no source list")
                + "; the baseline was recorded from a build that merged "
                + (", ".join(recorded_sources) or "no source list")
                + ". The counts are not comparable -- every measure of a list "
                "only one of them merged would report as gone or new. Re-record "
                "with `assess --record`, or pass the same `--source` list the "
                "baseline was built with. The expectations are still graded."
            ),
        )

    keys = sorted(set(baseline.measures) | set(assessment.measures))
    deltas = []
    for key in keys:
        before = baseline.measures.get(key)
        measure = assessment.measures.get(key)
        after = measure.value if measure else None
        if before == after:
            continue
        deltas.append(MeasureDelta(
            key=key,
            title=measure.title if measure else key,
            before=before,
            after=after,
            direction=measure.direction if measure else Direction.NEUTRAL,
        ))

    changes = []
    for result in assessment.results:
        before = baseline.statuses.get(result.expectation.id)
        if before is None or before == result.status.value:
            continue
        changes.append(StatusChange(
            expectation_id=result.expectation.id,
            title=result.expectation.title,
            before=before,
            after=result.status.value,
        ))

    return BaselineComparison(
        baseline=baseline,
        measures=tuple(deltas),
        statuses=tuple(changes),
    )
