"""Which flow of ours an implementation's flow is about, where no rule can say.

`lcia.substance_matching` reaches a flow by a registry number and then by an
exact name, both inside the compartment the factor was stated in.  This is what
that rule cannot reach: a publisher who names a substance in a spelling of their
own and states no number for it.  GreenDelta writes ``Copper ion`` where this
list publishes ``Copper, Ion`` and ``Cadmium II`` where it publishes
``Cadmium(2+)``; 25 of their flows are one of those, carrying 107 factors, and
none of them is a substance this list is missing.  #347.

**Their own package is the evidence.**  Each of those names appears in their file
once per compartment -- nine to thirteen times -- and most of those copies carry
an ecoinvent identifier that already resolves.  So what they mean by ``Copper
ion`` is answered by them, in the compartments where it can be read, and a row
here carries it into the compartments where it cannot.  Not one of the names
points at two substances of ours.  That is why this is a table and not a rule:
what makes each row true is a count in their file, which no amount of string
comparison recovers.

**The other 56 rows are a land class or a kind of water (#166).**  Three of their
compartments -- ``Resource / land``, ``Resource / in water`` and ``Resource /
unspecified`` -- name a place where this list names an action, so ``Occupation,
agriculture`` reaches nothing: *Occupation* is our context and never our label.
Those rows rest on a different reading of the same shape.  The package is
distributed inside BAFU's database and names its flows as BAFU names them, and
`land-flow-classes.json` and `water-flow-materials.json` have already read every
one of those names into a class -- so the judgement is not made here, it is
carried here.  Where their own file can check it, it agrees: a shorter form of
the name usually resolves by ecoinvent uuid to the class's parent, and 640 of the
1,528 factors are bit-identical to what the JRC states for the same flow,
category and country.

**A row names a compartment, never a substance alone.**  The same rule the
matching pass holds to (`lcia.substance_matching`), for the same reason: a factor
is a number about a substance *in a place*, and a decision that reached across
compartments could put a freshwater number on an emission to air.  Each row is
one flow of theirs -- one substance in one compartment -- and one flow of ours.

**A decision outranks a number and a name both.**  It is applied before either,
because a curator who read the publisher's file has more to go on than a string
comparison does.  None of today's rows states a registry number, so nothing is
overruled in practice; the order is the claim, and
`tests/test_lcia_substance_decisions.py` pins it.

**A declined row is a decision.**  Seven of GreenDelta's rows are metals emitted
to a lake, where this list publishes only BAFU's element-named flows, and folding
an ion's number onto ``Cadmium`` would state something this list denies in every
other water context.  They are written down here with their reasoning rather than
left looking like an oversight, and the finding that reports the flow as
unreached carries the reason from here.

**The target's label, context and unit are a guard.**  They record what the flow
published when the row was written, and a build where that uuid carries something
else raises rather than applying the row.  A uuid is not a stable name for a
substance across releases -- #108 added ``only_when_named`` to
``ecoinvent-match-overrides.json`` after a uuid ecoinvent 3.8 calls ``Vanadium``
turned out to be ``Vanadium V`` in 3.12 -- and a curated decision that silently
lands on a different substance is worse than one that stops working.

The file is ``data/lcia-substance-decisions.json``.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import orjson
import structlog

from brightway_flows.filesystem import PACKAGE_DATA_DIR

logger = structlog.get_logger(__name__)

SUBSTANCE_DECISIONS_FILEPATH = PACKAGE_DATA_DIR / "lcia-substance-decisions.json"

SUBSTANCE_DECISIONS_SCHEMA_VERSION = 1

#: What a row says happened to the publisher's flow.
REACHES = "reaches"
DECLINED = "declined"
DECISIONS = (REACHES, DECLINED)

#: What a match made from this table is recorded as, beside
#: `substance_matching.BY_REGISTRY_NUMBER` and its siblings.  Its own word,
#: because "a curator read the publisher's package and said so" is a different
#: strength of claim from "the number agreed", and a reader deciding whether to
#: trust a factor needs to be able to tell them apart.
BY_DECISION = "curated-decision"


class SubstanceDecisionError(ValueError):
    """A row that cannot be read as a decision.

    Raised rather than skipped, for the reason `lcia.misattributions` raises: a
    malformed curated decision that is quietly ignored is a decision that looks
    applied and is not.
    """


@dataclass(frozen=True, slots=True)
class SubstanceDecision:
    """One flow of an implementation's, and the flow of ours it is about."""

    implemented_by: str
    #: Their flow: one substance in one compartment.  Keyed on the uuid rather
    #: than on the name, so a re-export that renumbers a flow stops applying the
    #: row instead of carrying it onto whatever now holds the name.
    source_flow_uuid: str
    source_flow_name: str
    source_context: tuple[str, ...]
    #: ``reaches`` or ``declined``.
    decision: str
    #: Not optional.  Every row asserts which substance a publisher meant, over a
    #: name that publisher chose, and an assertion with no stated reasoning
    #: cannot be re-checked against their next release.
    comment: str
    #: The flow of ours, on a ``reaches`` row and never on a ``declined`` one.
    elementary_flow_uuid: str = ""
    #: What that flow published when the row was written.  The guard: see the
    #: module docstring.
    substance: str = ""
    context: str = ""
    unit: str = ""

    @property
    def reaches(self) -> bool:
        return self.decision == REACHES

    def covers(self, *, substance: str, context: str, unit: str) -> bool:
        """Whether this row was written about the flow that is there now.

        A ``declined`` row has no target and so nothing to check; it covers
        whatever the build holds, because what it says is that no flow is the
        right place for the number.
        """
        if not self.reaches:
            return True
        return (
            substance == self.substance
            and context == self.context
            and unit == self.unit
        )


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise SubstanceDecisionError(message)


def load_substance_decisions(
    path: Path | None = None,
) -> dict[tuple[str, str], SubstanceDecision]:
    """The decisions, keyed on the implementation and their flow's uuid.

    Not cached, because the path is injectable (rule 13): a test hands over a
    file of its own and must not be given another one's decisions.
    """
    filepath = path or SUBSTANCE_DECISIONS_FILEPATH
    if not filepath.exists():
        return {}
    payload = orjson.loads(filepath.read_bytes())
    _require(isinstance(payload, dict), f"{filepath.name} is not an object")
    version = payload.get("schema_version")
    _require(
        version == SUBSTANCE_DECISIONS_SCHEMA_VERSION,
        f"{filepath.name} is schema version {version!r}; this reads "
        f"{SUBSTANCE_DECISIONS_SCHEMA_VERSION}",
    )
    rows = payload.get("decisions")
    _require(isinstance(rows, list), f"{filepath.name} carries no decisions list")

    index: dict[tuple[str, str], SubstanceDecision] = {}
    for position, row in enumerate(rows):
        _require(isinstance(row, dict), f"decision {position} is not an object")
        for field in ("implemented_by", "source_flow_uuid", "source_flow_name"):
            _require(
                bool(str(row.get(field) or "").strip()),
                f"decision {position} has no {field!r}",
            )
        decision = str(row.get("decision") or "").strip()
        _require(
            decision in DECISIONS,
            f"decision {position} says {decision!r}; it says one of "
            f"{', '.join(DECISIONS)}",
        )
        context = row.get("source_context")
        _require(
            isinstance(context, list) and all(isinstance(part, str) for part in context),
            f"decision {position} has no source_context, and a row that named a "
            f"substance without a compartment could put a freshwater number on "
            f"an emission to air",
        )
        _require(
            bool(str(row.get("comment") or "").strip()),
            f"decision {position} has no comment; a row here asserts which "
            f"substance a publisher meant over the name that publisher chose, "
            f"and one with no stated reasoning cannot be re-checked against "
            f"their next release",
        )
        target = str(row.get("elementary_flow_uuid") or "").strip()
        if decision == REACHES:
            _require(
                bool(target),
                f"decision {position} reaches a flow and does not say which",
            )
            for field in ("substance", "context", "unit"):
                _require(
                    bool(str(row.get(field) or "").strip()),
                    f"decision {position} does not record the {field!r} its "
                    f"target published when the row was written, which is what "
                    f"stops it landing on a different substance later",
                )
        else:
            _require(
                not target,
                f"decision {position} is declined and names a flow to reach",
            )
        made = SubstanceDecision(
            implemented_by=str(row["implemented_by"]).strip(),
            source_flow_uuid=str(row["source_flow_uuid"]).strip(),
            source_flow_name=str(row["source_flow_name"]).strip(),
            source_context=tuple(context),
            decision=decision,
            comment=str(row["comment"]).strip(),
            elementary_flow_uuid=target,
            substance=str(row.get("substance") or "").strip(),
            context=str(row.get("context") or "").strip(),
            unit=str(row.get("unit") or "").strip(),
        )
        key = (made.implemented_by, made.source_flow_uuid)
        _require(
            key not in index,
            f"decision {position} is the second about {made.source_flow_name!r} "
            f"({made.source_flow_uuid}); one flow of theirs has one decision",
        )
        index[key] = made
    logger.debug("substance_decisions_loaded", decisions=len(index))
    return index


def decisions_for(
    implemented_by: str,
    *,
    path: Path | None = None,
) -> dict[str, SubstanceDecision]:
    """The decisions about one implementation's flows, keyed on their uuid."""
    return {
        source_flow_uuid: decision
        for (owner, source_flow_uuid), decision in load_substance_decisions(path).items()
        if owner == implemented_by
    }
