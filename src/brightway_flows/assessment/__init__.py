"""Assessing a build: what it measures, and what it was supposed to do.

The test suite answers "is the code broken".  This package answers the other
question, the one that has had no home: *is the output getting better, and did
the change we just made do the thing we said it would do.*

Five modules, in the order a reader meets them:

`expectations` reads `expectations/*.json` at the repository root -- one file
per issue or theme, added by the pull request that claims to fix it.  An
expectation names a subject in the built output ("the BAFU rows named `Water`")
and states what should be true of it ("they land on an existing consensus flow
named `Water`").

`measures` counts the build: how each source list places, how much of it reaches
a characterised flow, how many flows collide, how long each review queue is.
Everything the pipeline already counted into `run_stats` is folded in, so the
hundred-odd counters the transformers write are measures too, without being
restated here.

`evaluate` resolves each expectation against `consensus-flows.sqlite3` and
grades it.  A failure carries the trace that explains it -- for a source row,
every candidate the selector scored and why the winner won -- because "unmet"
alone sends a reader back to the database to find out what happened, and the
database already knows.

`baseline` holds the last recorded numbers, committed to the repository, so a
pull request's diff shows what moved.  `report` renders all of it.

Nothing here writes to the database.  `assess` is a reader; a build is the only
thing that produces the artifact it reads.
"""

from brightway_flows.assessment.baseline import (
    Baseline,
    BaselineComparison,
    compare_to_baseline,
    load_baseline,
    write_baseline,
)
from brightway_flows.assessment.evaluate import (
    Assessment,
    ClaimResult,
    ExpectationResult,
    Status,
    assess,
)
from brightway_flows.assessment.expectations import (
    Expectation,
    ExpectationFileError,
    load_expectations,
)
from brightway_flows.assessment.measures import MeasureValue, collect_measures

__all__ = [
    "Assessment",
    "Baseline",
    "BaselineComparison",
    "ClaimResult",
    "Expectation",
    "ExpectationFileError",
    "ExpectationResult",
    "MeasureValue",
    "Status",
    "assess",
    "collect_measures",
    "compare_to_baseline",
    "load_baseline",
    "load_expectations",
    "write_baseline",
]
