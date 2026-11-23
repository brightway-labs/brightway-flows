"""Expectations: what each file in `expectations/` says, and whether the recorded build meets it.

A pull request that closes an issue states what it should make true in
`expectations/`, one file per issue, and `brightway-flows assess --record`
writes every expectation's status into `expectations/baseline.json`.  Both are
committed, and until this module nothing on the website showed either: to learn
whether the BAFU rows named `Water` land where #381 said they would, a reader
had to clone the repository and run a build.

Nothing here is a second record of any of it, and nothing has a second name.
A file is one expectations file, read by `assessment.load_expectations`; an
expectation's state is the status the baseline holds for it; the build those
statuses came from is the one the baseline names.  So there is no register to
keep in step with the issues -- the page is as current as the two things a pull
request already has to change.

The one module in this package that takes a directory rather than a connection:
none of this is in the database, and it is here because it is the same kind of
thing as its neighbours -- a Flask-free read that hands the view records.
"""

from __future__ import annotations

import re
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
    """Where an expectation stands, most in need of a reader first.

    The four statuses `assess` records, and the two things a status alone does
    not say: that the project already agreed an expectation is not true yet, and
    that it was written after the build the baseline records.  The order is the
    order a file takes its own state in -- a file with one unmet expectation
    among nine met ones is an unmet file.
    """

    UNMET = "unmet"
    ERROR = "error"
    UNRESOLVED = "unresolved"
    PENDING = "pending"
    UNRECORDED = "unrecorded"
    MET = "met"


#: What each state means.  The four statuses follow the table in
#: `expectations/README.md`.
STATE_MEANINGS: dict[State, str] = {
    State.UNMET: "The recorded build does something else.",
    State.ERROR: "The recorded build could not answer: a table the expectation needs is missing.",
    State.UNRESOLVED: (
        "Nothing in the recorded build matches what the expectation is about: "
        "the row was renamed or removed upstream, its list was not merged, or "
        "the expectation names it wrongly. It needs rewriting, which is not "
        "the same job as fixing the pipeline."
    ),
    State.PENDING: "Agreed not to be true yet: the work queue.",
    State.UNRECORDED: "Written after the recorded build, so it has no status yet.",
    State.MET: "The recorded build does what the expectation says.",
}

#: The statuses `pending` excuses, which are the ones `assess --strict` would
#: otherwise fail on.  `unresolved` is not among them: an expectation that has
#: lost its subject is stale whether or not the work it describes was agreed to
#: be open, and `expectations/README.md` keeps that status apart on purpose.
_EXCUSED_BY_PENDING = frozenset({Status.UNMET, Status.ERROR})


@dataclass(frozen=True)
class RecordedExpectation:
    """One expectation, with the status the baseline records for it."""

    id: str
    title: str
    comment: str
    issue: int | None
    #: `source_row`, `flow`, `substance`, `factor` or `measure`.
    kind: str
    #: What the expectation is about, as the file names it: a list and a row
    #: name, a flow's UUID, a registry number.  An external payload, shown as
    #: written.
    subject: dict[str, Any]
    state: State


@dataclass(frozen=True)
class ExpectationFile:
    """One file in `expectations/`: an issue, and everything expected of it."""

    #: The file's name without its suffix -- `0381-bafu-water-names`.  It is
    #: what the address is made of and what the page is headed with: a file is
    #: not renamed once merged, and a title made out of the name would have to
    #: guess that `bafu` is written `BAFU`.
    id: str
    #: The file's own `description`: why it exists, in prose.
    description: str
    expectations: tuple[RecordedExpectation, ...]

    @property
    def filename(self) -> str:
        return f"{self.id}.json"

    @property
    def paragraphs(self) -> tuple[str, ...]:
        """The description, split where its author left a blank line."""
        return tuple(
            " ".join(part.split())
            for part in re.split(r"\n\s*\n", self.description)
            if part.strip()
        )

    @property
    def issues(self) -> tuple[int, ...]:
        return tuple(sorted({e.issue for e in self.expectations if e.issue}))

    @property
    def lists(self) -> tuple[str, ...]:
        """The source lists its expectations name, for the filter."""
        return tuple(sorted({
            str(e.subject["list"]) for e in self.expectations if e.subject.get("list")
        }))

    @property
    def counts(self) -> Counter[State]:
        return Counter(e.state for e in self.expectations)

    @property
    def state(self) -> State:
        """Its expectation most in need of a reader; `MET` only when every one is."""
        present = {e.state for e in self.expectations}
        return next((state for state in State if state in present), State.MET)


@dataclass(frozen=True)
class ExpectationFiles:
    """Every file, and the build their statuses were recorded against."""

    files: tuple[ExpectationFile, ...]
    #: The baseline's own `recorded` block: the run, when, and the lists merged.
    recorded: dict[str, Any]

    def get(self, file_id: str) -> ExpectationFile | None:
        return next((file for file in self.files if file.id == file_id), None)

    @property
    def state_counts(self) -> Counter[State]:
        return Counter(file.state for file in self.files)

    @property
    def lists(self) -> list[str]:
        return sorted({name for file in self.files for name in file.lists})


def expectation_state(expectation: Expectation, baseline: Baseline) -> State:
    """The baseline's status for one expectation, as a `State`.

    `pending` excuses what `assess --strict` would fail on -- unmet, or
    unanswerable -- and nothing else.  An expectation the build meets is met
    whether or not the file still carries the flag: the flag is then stale, and
    saying "pending" would hide that the work is done.  One whose subject the
    build does not have is unresolved whether or not it is pending, because
    that is an expectation to rewrite rather than work to do.

    A status this code does not know raises, pending or not: a baseline written
    by a newer `assess` is not one to guess at.
    """
    recorded = baseline.statuses.get(expectation.id)
    if recorded is None:
        return State.PENDING if expectation.pending else State.UNRECORDED
    status = Status(recorded)
    if expectation.pending and status in _EXCUSED_BY_PENDING:
        return State.PENDING
    return State(status)


def load_files(directory: Path) -> ExpectationFiles:
    """Every expectations file in *directory*.

    The loader and the baseline reader are the assessment's own, so a file the
    test suite would reject is rejected here too rather than half-shown.  The
    one thing read a second time is each file's `description`, which the loader
    checks is there and does not keep.
    """
    baseline = load_baseline(directory)
    by_file: dict[str, list[RecordedExpectation]] = {}
    for expectation in load_expectations(directory):
        by_file.setdefault(expectation.source_file, []).append(RecordedExpectation(
            id=expectation.id,
            title=expectation.title,
            comment=expectation.comment,
            issue=expectation.issue,
            kind=expectation.kind,
            subject=expectation.selector,
            state=expectation_state(expectation, baseline),
        ))
    return ExpectationFiles(
        files=tuple(
            ExpectationFile(
                id=Path(filename).stem,
                description=_description(directory / Path(filename).name),
                expectations=tuple(expectations),
            )
            for filename, expectations in sorted(by_file.items())
        ),
        recorded=baseline.recorded,
    )


def _description(path: Path) -> str:
    return str(orjson.loads(path.read_bytes()).get("description") or "")


#: What the table can be sorted by.  `state` is the default, because the page is
#: a work list before it is an archive: what the build does not do comes first.
SORTS = {
    "state": lambda file: (list(State).index(file.state), file.id),
    "file": lambda file: file.id,
    "expectations": lambda file: (len(file.expectations), file.id),
}
DEFAULT_SORT = "state"


def select(
    files: Iterable[ExpectationFile],
    *,
    query: str = "",
    state: str = "",
    source: str = "",
    sort: str = DEFAULT_SORT,
) -> list[ExpectationFile]:
    """The files a reader asked for, in the order they asked for.

    *query* is matched against everything a file says in words -- its name, its
    description, each expectation's title and comment -- and against `#381`,
    because the issue number is what somebody arriving from GitHub has in hand.
    An unknown *sort* is the default one, as `queries.common.order_by` does it.
    """
    needle = query.casefold()
    descending = sort.startswith("-")
    key = SORTS.get(sort.removeprefix("-"), SORTS[DEFAULT_SORT])
    return sorted(
        (
            file for file in files
            if (not state or file.state == state)
            and (not source or source in file.lists)
            and (not needle or needle in _searchable(file))
        ),
        key=key,
        reverse=descending,
    )


def _searchable(file: ExpectationFile) -> str:
    return " ".join((
        file.id,
        file.description,
        *(f"#{issue}" for issue in file.issues),
        *(text for e in file.expectations for text in (e.id, e.title, e.comment)),
    )).casefold()
