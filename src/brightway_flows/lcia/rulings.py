"""Curated answers to the three factor queues.

`lcia.consensus` asks the questions -- two implementations of EF 3.1 state
different numbers for one flow, category and place; only one of them states a
number at all; or the model the method is derived from states something more than
a hundredfold away (#107) -- and publishes nothing for any of them.  This is where
the answers are applied.

The third queue takes the same two verdicts as the other two and means something
of its own with each.  `publish` names the implementation whose number this list
takes **in spite of** the model: a curator who has read the JRC's report and
decided the adjustment was deliberate says so here, and the factor comes back as
`derivation: ruled` with the reasoning attached.  `decline` withholds it on the
record.  What neither verdict can do is publish the model's number -- USEtox 2.1
is not an implementation of EF 3.1, it is what EF 3.1 says it is derived from, and
`implemented_by` must name an implementation the question is about.

A ruling is keyed on **the queue and the queue item's own key**, which is
`flow_object_id|category_slug`: about a substance and a category rather than about
a flow, so it goes on answering the same question when EF re-publishes the same
substance in a fourteenth context.  That is the contract
`elementary-flow-collision-decisions.json` has for the collision queue, and the
reason is the same -- a ruling written against a uuid is a ruling that expires.

**The queue is part of the key**, because the item key alone is not unique across
them.  One substance and one category can be contested in one compartment and
proposed in another -- both implementations state a number for vanadium in air,
and only ecoinvent states one for it somewhere our flow list reaches and EF's
does not -- so the same `item_key` appears in two queues, asking two different
questions that need two different answers.  A contradicted row can carry an
`item_key` a contested ruling was written about as well, and the answer to "which
of these two is right" is not an answer to "is either of them".

**The comment is mandatory.**  Every ruling here is a statement about somebody
else's science: that the JRC's 134.73 is right and the ecoinvent Centre's 53,540
is not, or that a number the method's own publisher never stated should be
published anyway.  A ruling with no reasoning is unreviewable, so the loader
refuses one -- the same way `contested-cas-decisions.json` does.

**Two verdicts, and neither names a source list.**  `publish` names the
implementation whose number this list takes; `decline` publishes nothing.  The
first shape of this had four -- `jrc`, `ecoinvent`, `adopt`, `decline` -- which
reads well with exactly two implementations and cannot express a third: every
source list that ships factors is an implementation, and a verdict per list means
a new verdict per list.  `publish` with an `implemented_by` says the same thing
about any number of them, and the loader checks that the implementation named is
one the question is about.

It also makes a verdict that was unreachable before expressible: `decline` on a
*contested* question is "neither of them, deliberately", which the four-verdict
shape had no way to say.

`decline` publishes nothing and is here anyway, which is a departure from the
collision file, where a verdict that changes no output is deliberately absent.
The difference is the size of the queue: 36 contested questions can be left open,
and the 3,455 proposed ones the queue held when this was designed could not -- a
curator who has looked at one and decided
against it needs somewhere to say so, or the row asks forever.  A declined
question stays on the page as `info` with the reasoning on it, which is the
record; what it stops being is `blocking`.

**A ruling written about different numbers is not obeyed.**  `ruled_about` states
what every implementation stated when the ruling was made.  A row whose number is
not among them goes back to the queue as a question rather than being settled by a
decision taken about something else -- the same rule `collision_decisions` applies
to a collision whose flows have changed, and for the same reason.

**And it is required, not offered.**  A ruling with no `ruled_about` would be one
this check could never fail, which is the same as not having the check: the
promise above would hold for the rulings that happened to carry the numbers and
silently not for the rest.  So the loader refuses a ruling that does not say what
every implementation named in the question stated -- there is no grandfathered
population, because this file was born with the check.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

import orjson
import structlog

from brightway_flows.filesystem import PACKAGE_DATA_DIR
from brightway_flows.lcia.scope import curated_method, out_of_scope
from brightway_flows.pipeline.review_records import ReviewQueue

logger = structlog.get_logger(__name__)

#: The curated file.  One constant per data file (rule 5).
FACTOR_RULINGS_FILEPATH = PACKAGE_DATA_DIR / "lcia-factor-rulings.json"

#: Bumped when the file's shape changes.  Module-local and checked where the file
#: is read, because unqualified `SCHEMA_VERSION` means the published list's
#: (rule 13).
RULINGS_SCHEMA_VERSION = 1

#: There is deliberately no `GENERATED_BY` here, and the absence is the decision.
#: `pipeline.collision_decisions` stamps one because it writes onto a `Flow`
#: through a `LayerWriteLog`, so the changelog can say a person decided; a factor
#: has no changelog and no writes to record.  What says a person decided is
#: `derivation: ruled` on the published factor, and what says who and why is this
#: file -- a second, weaker signal on the row would only be a second place to look.


class Verdict(StrEnum):
    """What a curator decided.

    Each verdict names what gets published, never a rule for next time: a ruling
    is about one substance and one category, and a rule that generalised would
    belong in the pipeline where it could be tested.
    """

    #: Publish the number `implemented_by` names, as `derivation: ruled`.
    PUBLISH = "publish"
    #: Publish nothing for this question, deliberately and on the record.
    DECLINE = "decline"


#: The queues a ruling can answer.  Both take both verdicts: which question is
#: being answered is the queue's business, and what to do about it is the
#: verdict's.
ANSWERABLE_QUEUES: frozenset[str] = frozenset({
    str(ReviewQueue.CONTESTED_FACTOR),
    str(ReviewQueue.PROPOSED_FACTOR),
    str(ReviewQueue.CONTRADICTED_FACTOR),
})


@dataclass(frozen=True)
class FactorRuling:
    """One curator's answer to one factor question."""

    #: Which method's category ``category_slug`` names, from the file's own
    #: `method`.  A slug is unique inside a method and not across methods.
    method: str
    flow_object_id: str
    category_slug: str
    queue: str
    verdict: Verdict
    comment: str
    #: Whose number to publish, as `implemented_by` spells it everywhere else in
    #: this layer.  Empty on a `decline`, which publishes nobody's.
    implemented_by: str = ""
    #: The names, for a reader of the file.  Not the key: a display name is the
    #: publisher's and can be re-spelled, and a ruling has to survive that.
    substance: str = ""
    category: str = ""
    #: What every implementation stated when the ruling was made, keyed by
    #: `implemented_by`.  A row stating something else is not what this ruling was
    #: about.  Required: see the module docstring.
    ruled_about: dict[str, tuple[float, ...]] = field(default_factory=dict)

    @property
    def key(self) -> tuple[str, str, str]:
        """What this ruling answers: a queue, a substance and a category."""
        return (self.queue, self.flow_object_id, self.category_slug)

    @property
    def item_key(self) -> str:
        """The queue item this answers, spelled as the queue spells it.

        The method first, because a category slug belongs to one and the queues
        hold every method's questions.
        """
        return f"{self.method}|{self.flow_object_id}|{self.category_slug}"

    @property
    def publishes(self) -> bool:
        return self.verdict is not Verdict.DECLINE

    def covers(self, *, stated: dict[str, float]) -> bool:
        """Whether this ruling was made about these numbers.

        *stated* is every implementation's amount for one row.  Three ways this
        says no, and each is a row the ruling was not written about: an
        implementation states a number the ruling never saw, an implementation
        speaks that the ruling never heard from, or one the ruling was made about
        has gone silent.  The last two matter more than they look -- a third
        implementation arriving changes what "which of these is right" means, and
        answering it with a decision taken between two is the silent-obedience
        failure this check exists for.
        """
        if set(stated) != set(self.ruled_about):
            return False
        return all(
            amount in self.ruled_about[implementation]
            for implementation, amount in stated.items()
        )


class FactorRulingError(ValueError):
    """A ruling that cannot be read as one.

    Raised rather than skipped, for the reason in the module docstring: a
    malformed ruling that is quietly ignored is a curator's decision that looks
    applied and is not.
    """


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise FactorRulingError(message)


def _amounts(raw: object, *, position: int) -> tuple[float, ...]:
    _require(
        isinstance(raw, list),
        f"ruling {position}: ruled_about values must be a list of numbers",
    )
    out = []
    for value in raw:  # type: ignore[union-attr]
        _require(
            isinstance(value, (int, float)) and not isinstance(value, bool),
            f"ruling {position}: {value!r} is not a number",
        )
        out.append(float(value))
    return tuple(out)


def load_factor_rulings(
    path: Path | None = None, *, method: str | None = None
) -> dict[tuple[str, str, str], FactorRuling]:
    """The rulings, keyed on the question each answers.

    Not cached, because the path is injectable (rule 13): a test hands over a
    file of its own and must not be given another one's answers.
    
    *method* is the method slug the caller is characterising: the file states
    which method its category slugs belong to, and asked for a different one this
    returns nothing rather than ruling on categories nobody wrote it about.
    """
    filepath = path or FACTOR_RULINGS_FILEPATH
    if not filepath.exists():
        return {}
    payload = orjson.loads(filepath.read_bytes())
    _require(isinstance(payload, dict), f"{filepath.name} is not an object")
    version = payload.get("schema_version")
    _require(
        version == RULINGS_SCHEMA_VERSION,
        f"{filepath.name} is schema version {version!r}; this reads "
        f"{RULINGS_SCHEMA_VERSION}",
    )
    if out_of_scope(payload, filename=filepath.name, method=method):
        return {}
    stated_method = curated_method(payload, filename=filepath.name)
    rows = payload.get("rulings")
    _require(isinstance(rows, list), f"{filepath.name} carries no rulings list")

    index: dict[tuple[str, str, str], FactorRuling] = {}
    for position, row in enumerate(rows):
        _require(isinstance(row, dict), f"ruling {position} is not an object")
        queue = str(row.get("queue") or "").strip()
        _require(
            queue in ANSWERABLE_QUEUES,
            f"ruling {position} names queue {queue!r}; the factor queues are "
            f"{sorted(ANSWERABLE_QUEUES)}",
        )
        raw_verdict = str(row.get("decision") or "").strip()
        _require(
            raw_verdict in {str(member) for member in Verdict},
            f"ruling {position} says {raw_verdict!r}; the verdicts are "
            f"{sorted(str(member) for member in Verdict)}",
        )
        verdict = Verdict(raw_verdict)
        about = row.get("ruled_about")
        _require(
            isinstance(about, dict) and bool(about),
            f"ruling {position} says nothing about what was stated when it was "
            f"made; `ruled_about` is what stops a ruling being obeyed after the "
            f"numbers move, and one without it could never fail that check",
        )
        ruling = FactorRuling(
            method=stated_method,
            flow_object_id=str(row.get("flow_object_id") or "").strip(),
            category_slug=str(row.get("category_slug") or "").strip(),
            queue=queue,
            verdict=verdict,
            comment=str(row.get("comment") or "").strip(),
            implemented_by=str(row.get("implemented_by") or "").strip(),
            substance=str(row.get("substance") or "").strip(),
            category=str(row.get("category") or "").strip(),
            ruled_about={
                str(name): _amounts(values, position=position)
                for name, values in about.items()  # type: ignore[union-attr]
            },
        )
        _require(
            all(ruling.key),
            f"ruling {position} does not name a substance and a category",
        )
        _require(
            ruling.comment != "",
            f"ruling {position} carries no comment; a ruling about somebody "
            f"else's science is unreviewable without one",
        )
        if verdict is Verdict.PUBLISH:
            _require(
                ruling.implemented_by != "",
                f"ruling {position} publishes, and names no implementation to "
                f"publish from",
            )
            _require(
                ruling.implemented_by in ruling.ruled_about,
                f"ruling {position} publishes {ruling.implemented_by!r}, which "
                f"is not among the implementations it was made about: "
                f"{sorted(ruling.ruled_about)}",
            )
        else:
            _require(
                ruling.implemented_by == "",
                f"ruling {position} declines and names "
                f"{ruling.implemented_by!r} to publish from; a decline publishes "
                f"nobody's number",
            )
        _require(
            ruling.key not in index,
            f"ruling {position} answers {ruling.item_key} in {queue} a second time",
        )
        index[ruling.key] = ruling
    logger.info(
        "loaded_factor_rulings",
        path=str(filepath),
        rulings=len(index),
        publishing=sum(1 for ruling in index.values() if ruling.publishes),
    )
    return index
