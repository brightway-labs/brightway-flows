"""What a build spent its time on.

A full build takes about half an hour and nothing in it said where the time
went, so every proposal to make it faster was an argument about which stage
*looked* expensive.  What could be measured from outside with a stopwatch was
the shape of a run and no more: extraction 61 s, a 400-flow transform 42 s, a
whole verification build 135 s.  Which of the twenty-odd transformers spent the
135 seconds is not a question a stopwatch outside the process can ask -- and
the answer, the first time this table was read, was not the stage anyone had
been arguing about: 21.7 s of it was the merge running the transformer chain
over source rows, and 8.4 s was one transformer's `setup()`.

So a run records its own stages.  :class:`RunTimings` is the recorder the
stages are wrapped in; :class:`~brightway_flows.pipeline.review_records.StageTiming`
is the row it produces, and `run_timings` is the table those rows go to.

Two rules keep the table honest:

* A stage that runs more than once accumulates rather than appending, so
  `merge` over three source lists is one row of three merges and not three rows
  that a reader has to sum.  `detail` is what separates them when they should
  be separate: `("merge", "ecoinvent-3.12")`.
* Every duration is recorded, including the one a stage that raised had spent.
  The stage that dies is the one whose cost is most worth knowing.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from time import perf_counter

import structlog

from brightway_flows.pipeline.review_records import StageTiming

logger = structlog.get_logger(__name__)

#: Durations are rounded to the millisecond before they are stored.  Not for
#: precision -- a stage is not measured to the microsecond by anything here --
#: but so that the log line and the table read the same, and so that the value
#: is a number a person can compare rather than seventeen digits.
_PRECISION = 3


class RunTimings:
    """The stages of one build, and how long each one took.

    Handed down from `build` through the transform and the merge, so that one
    run produces one table rather than a set of per-stage log lines a reader
    has to reassemble.  A caller that has no recorder to pass constructs its
    own, which is what a test and a direct `run_pipeline` call do.
    """

    def __init__(self) -> None:
        self._seconds: dict[tuple[str, str], float] = {}

    @contextmanager
    def stage(self, stage: str, detail: str = "") -> Iterator[None]:
        """Time the block, and record it whether or not it succeeds."""
        started = perf_counter()
        try:
            yield
        finally:
            self.record(stage, perf_counter() - started, detail=detail)

    def record(self, stage: str, duration_seconds: float, *, detail: str = "") -> None:
        """Add *duration_seconds* to `(stage, detail)`, and say so."""
        key = (stage, detail)
        self._seconds[key] = self._seconds.get(key, 0.0) + float(duration_seconds)
        logger.info(
            "stage_timing",
            stage=stage,
            detail=detail,
            duration_seconds=round(self._seconds[key], _PRECISION),
        )

    def records(self) -> list[StageTiming]:
        """One row per `(stage, detail)`, in the order the stages first ran."""
        return [
            StageTiming(
                stage=stage,
                detail=detail,
                duration_seconds=round(seconds, _PRECISION),
            )
            for (stage, detail), seconds in self._seconds.items()
        ]

    def slowest(self, limit: int = 10) -> list[StageTiming]:
        """The costliest stages first, for the line a build ends on."""
        return sorted(
            self.records(), key=lambda row: row.duration_seconds, reverse=True
        )[:limit]

    def total_seconds(self) -> float:
        """Every stage added up.

        Not the wall clock of the build: stages nest -- `transform` contains
        every `transformer` -- and what is not wrapped in a stage at all is in
        neither figure.  It is the total of what was measured, and it is here
        so that a reader can see how much of the run the measurements account
        for.
        """
        return round(sum(self._seconds.values()), _PRECISION)
