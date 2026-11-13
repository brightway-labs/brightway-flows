"""Cases: what each expectations file claims, and whether the recorded build meets it.

A pull request that closes an issue states its claim in `expectations/`, one
file per issue, and `brightway-flows assess --record` writes every claim's
status into `expectations/baseline.json`.  Both are committed, and until this
module nothing on the website showed either: to learn whether the BAFU rows
named `Water` land where #381 said they would, a reader had to clone the
repository and run a build.

Nothing here is a second record of any of it.  A case is one expectations file,
read by `assessment.load_expectations`; a claim's state is the status the
baseline holds for it; the build those statuses came from is the one the
baseline names.  So there is no register to keep in step with the issues --
the page is as current as the two things a pull request already has to change.

The one module in this package that takes a directory rather than a connection:
none of this is in the database, and it is here because it is the same kind of
thing as its neighbours -- a Flask-free read that hands the view records.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

import orjson

from brightway_flows.assessment.baseline import Baseline, load_baseline
from brightway_flows.assessment.evaluate import Status
from brightway_flows.assessment.expectations import Expectation, load_expectations


class State(StrEnum):
    """Where a claim stands, most in need of a reader first.

    The four statuses `assess` records, and the two things a status alone does
    not say: that the project already agreed a claim is not true yet, and that
    the claim was written after the build the baseline records.  The order is
    the order a case takes its own state in -- a file with one unmet claim among
    nine met ones is an unmet case.
    """

    UNMET = "unmet"
    ERROR = "error"
    UNRESOLVED = "unresolved"
    PENDING = "pending"
    UNRECORDED = "unrecorded"
    MET = "met"


#: What each state means, in the words `expectations/README.md` uses.
STATE_MEANINGS: dict[State, str] = {
    State.UNMET: "The recorded build does something else.",
    State.ERROR: "The claim could not be evaluated.",
    State.UNRESOLVED: "The recorded build did not merge the list the claim is about.",
    State.PENDING: "Agreed not to be true yet: the work queue.",
    State.UNRECORDED: "Written after the recorded build, so it has no status yet.",
    State.MET: "The recorded build does what the claim says.",
}


@dataclass(frozen=True)
class Claim:
    """One expectation, with the status the baseline records for it."""

    id: str
    title: str
    comment: str
    issue: int | None
    #: `source_row`, `flow`, `substance`, `factor` or `measure`.
    kind: str
    #: What the claim is about, as the file names it: a list and a row name, a
    #: flow's UUID, a registry number.  An external payload, shown as written.
    subject: dict[str, Any]
    state: State


@dataclass(frozen=True)
class Case:
    """One expectations file: an issue, and everything claimed about it."""

    #: The file's name without its suffix -- `0381-bafu-water-names`.  It is
    #: what the address is made of, and a file is not renamed once merged.
    id: str
    #: The file's own `description`: why it exists, in prose.
    summary: str
    claims: tuple[Claim, ...]

    @property
    def title(self) -> str:
        """The file name as a sentence: `Bafu water names`.

        The files are named for what they claim, by whoever wrote the claim, so
        the name is already the shortest honest title there is.
        """
        words = self.id.split("-")
        if words[0].isdigit():
            words = words[1:]
        return " ".join(words).capitalize() or self.id

    @property
    def filename(self) -> str:
        return f"{self.id}.json"

    @property
    def issues(self) -> tuple[int, ...]:
        return tuple(sorted({claim.issue for claim in self.claims if claim.issue}))

    @property
    def lists(self) -> tuple[str, ...]:
        """The source lists its claims name, for the filter."""
        return tuple(sorted({
            str(claim.subject["list"]) for claim in self.claims if claim.subject.get("list")
        }))

    @property
    def counts(self) -> Counter[State]:
        return Counter(claim.state for claim in self.claims)

    @property
    def state(self) -> State:
        """Its claim most in need of a reader; `MET` only when every one is."""
        present = {claim.state for claim in self.claims}
        return next((state for state in State if state in present), State.MET)


@dataclass(frozen=True)
class Cases:
    """Every case, and the build their statuses were recorded against."""

    cases: tuple[Case, ...]
    #: The baseline's own `recorded` block: the run, when, and the lists merged.
    recorded: dict[str, Any]

    def get(self, case_id: str) -> Case | None:
        return next((case for case in self.cases if case.id == case_id), None)

    @property
    def state_counts(self) -> Counter[State]:
        return Counter(case.state for case in self.cases)

    @property
    def lists(self) -> list[str]:
        return sorted({name for case in self.cases for name in case.lists})


def claim_state(expectation: Expectation, baseline: Baseline) -> State:
    """The baseline's status for one expectation, as a `State`.

    A claim the build meets is met whether or not the file still carries
    `pending` -- the flag is then stale, and saying "pending" would hide that
    the work is done.  A status this code does not know raises: a baseline
    written by a newer `assess` is not one to guess at.
    """
    status = baseline.statuses.get(expectation.id)
    if status == Status.MET:
        return State.MET
    if expectation.pending:
        return State.PENDING
    if status is None:
        return State.UNRECORDED
    return State(Status(status))


def load_cases(directory: Path) -> Cases:
    """Every expectations file in *directory* as a case.

    The loader and the baseline reader are the assessment's own, so a file the
    test suite would reject is rejected here too rather than half-shown.  The
    one thing read a second time is each file's `description`, which the loader
    checks is there and does not keep.
    """
    baseline = load_baseline(directory)
    by_file: dict[str, list[Claim]] = {}
    for expectation in load_expectations(directory):
        by_file.setdefault(expectation.source_file, []).append(Claim(
            id=expectation.id,
            title=expectation.title,
            comment=expectation.comment,
            issue=expectation.issue,
            kind=expectation.kind,
            subject=expectation.selector,
            state=claim_state(expectation, baseline),
        ))
    return Cases(
        cases=tuple(
            Case(
                id=Path(filename).stem,
                summary=_description(directory / Path(filename).name),
                claims=tuple(claims),
            )
            for filename, claims in sorted(by_file.items())
        ),
        recorded=baseline.recorded,
    )


def _description(path: Path) -> str:
    return str(orjson.loads(path.read_bytes()).get("description") or "")


#: What the table can be sorted by.  `state` is the default, because the page is
#: a work list before it is an archive: what the build does not do comes first.
SORTS = {
    "state": lambda case: (list(State).index(case.state), case.id),
    "case": lambda case: case.id,
    "claims": lambda case: (len(case.claims), case.id),
}
DEFAULT_SORT = "state"


def select(
    cases: Iterable[Case],
    *,
    query: str = "",
    state: str = "",
    source: str = "",
    sort: str = DEFAULT_SORT,
) -> list[Case]:
    """The cases a reader asked for, in the order they asked for.

    *query* is matched against everything a case says in words -- its name, its
    description, each claim's title and comment -- and against `#381`, because
    the issue number is what somebody arriving from GitHub has in hand.  An
    unknown *sort* is the default one, as `queries.common.order_by` does it.
    """
    needle = query.casefold()
    descending = sort.startswith("-")
    key = SORTS.get(sort.removeprefix("-"), SORTS[DEFAULT_SORT])
    return sorted(
        (
            case for case in cases
            if (not state or case.state == state)
            and (not source or source in case.lists)
            and (not needle or needle in _searchable(case))
        ),
        key=key,
        reverse=descending,
    )


def _searchable(case: Case) -> str:
    return " ".join((
        case.id,
        case.summary,
        *(f"#{issue}" for issue in case.issues),
        *(text for claim in case.claims for text in (claim.id, claim.title, claim.comment)),
    )).casefold()
