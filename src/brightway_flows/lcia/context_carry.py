"""One context convention: which neighbour's number a blank takes, if any.

Ammonium emitted to a river carried no factor in any category, while ammonium
emitted to surface water is characterised in twenty-five (#159).  Nobody stated
a river number; the river is a context BAFU brought and no method's flow list
has.  Whether the river takes the surface-water number is not a fact about
ammonium and not a fact about EF 3.1 -- it is a fact about *our* taxonomy, and
it is written down once, here, for every method this list publishes.

``data/context-carry-rules.json`` is that convention.  It holds two kinds of
row and a list of walls, and nothing else:

* **downward** -- a recipient context and an ordered list of donor contexts.
  The first donor the substance is published in gives its number.  Silvicultural
  soil takes non-agricultural soil's number, failing that unspecified soil's;
  a river takes surface water's, failing that unspecified water's.
* **upward** -- a parent and its children: each class root, and surface water,
  the one parent below a root.  The parent takes their number only
  where exactly one child is published, or every published child states the
  same number to numerical precision, the most precise printing kept.  Run
  after the downward rules, and only from numbers an implementation stated.
* **walls** -- contexts no rule may name: long-term air and water (#158),
  indoor air, and the ocean on both the emission and the withdrawal side.  A
  rule naming one fails to load.

The rows were decided class by class from the census in
:mod:`brightway_flows.lcia.census` on the 2026-09-01 build, and each carries
the numbers it was decided on.  What ecoinvent did with the same blanks
(forestry soil takes EF's non-agricultural number in 2,747 of 2,765 rows) and
what SimaPro does (the unspecified sub-compartment's factor fills the rest) are
in the comments as evidence; neither is the authority.
``plans/lcia-consensus-decisions.md`` §5 is the design.

**The pass carries a number; it never invents one.**  :func:`carry_across_contexts`
runs last -- after `derive()`, the moves and the printings, because everything
that could still publish a row has to have run -- and does four things and no
more.  It reads only what the consensus implementation just published as
donors.  It fills a triple only where **no deciding implementation states
anything** for that flow, category and place: a compartment somebody spoke
about is a queue's business.  It never publishes onto a withdrawn flow and
never carries from a factor carried across compartments, so no chain walks a
number away from what an implementation stated -- a number the size-window
convention carried *within* the compartment (`lcia.size_class_carry`) is a
donor like a stated one.  And it writes ``derivation: carried`` with the
flow it carried from as ``source_flow_uuid`` -- the rule is the one for the
recipient's context, and a recipient has one rule per direction, so the pair
names it.

A stated zero carries like any other number: it is a statement, and the rule
says the two contexts are one statement.  A donor the substance is not published
in is skipped; a recipient no rule names stays blank and is counted by the
census.  Nothing here needs the inputs to be clean.

This replaced ``lcia.air_compartments`` and ``data/lcia-well-mixed-categories.json``
(#152), which carried one air factor across every air sub-compartment in three
well-mixed categories, indoor and long-term air included.  Under one convention
those two are walls for every category, and the outdoor strata take unspecified
air's number in every category; the 35 factors that rule carried on the
2026-09-01 build become 18 carried by the air rules and 17 withdrawn.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Mapping
from dataclasses import dataclass, replace
from enum import StrEnum
from pathlib import Path
from typing import Any

import orjson
import structlog

from brightway_flows.domain.context_registry import (
    UnknownContextIRIError,
    context_display_parts,
    context_for_iri,
)
from brightway_flows.filesystem import PACKAGE_DATA_DIR
from brightway_flows.flow_layers.contested_cas import more_precise_value
from brightway_flows.lcia.consensus import (
    RESTATED_PRECISION,
    Derivation,
    _all_agree,
)

logger = structlog.get_logger(__name__)

#: The curated file.
CONTEXT_CARRY_RULES_FILEPATH = PACKAGE_DATA_DIR / "context-carry-rules.json"

#: Bumped when the shape changes, and read rather than assumed.
CONTEXT_CARRY_SCHEMA_VERSION = 1

#: The separator a context's display name is written with.
ARROW = " → "

#: What a carried factor's `derivation` says.
CARRIED = str(Derivation.CARRIED)


class ContextCarryRuleError(ValueError):
    """A rule or wall that cannot be read as one.

    Raised rather than skipped, for the reason `lcia.rulings` raises: a
    malformed convention that is quietly ignored looks applied and is not.
    """


class CarryDirection(StrEnum):
    """Which way a rule carries, which is also how it decides."""

    #: The first published donor gives its number.
    DOWNWARD = "downward"
    #: All published donors must state one number, and it is taken.
    UPWARD = "upward"


@dataclass(frozen=True)
class Wall:
    """A context nothing is carried into or out of."""

    context_iri: str
    context: str
    comment: str


@dataclass(frozen=True)
class CarryRule:
    """One recipient context and the contexts it may take a number from."""

    direction: CarryDirection
    recipient_iri: str
    recipient: str
    donor_iris: tuple[str, ...]
    donors: tuple[str, ...]
    comment: str

    @property
    def rule_id(self) -> str:
        """What a run's counts call this rule."""
        return f"{self.direction}:{self.recipient_iri.rsplit('/', 1)[-1]}"


@dataclass(frozen=True)
class ContextCarryRules:
    """The whole convention, as read."""

    walls: tuple[Wall, ...]
    downward: tuple[CarryRule, ...]
    upward: tuple[CarryRule, ...]

    @property
    def wall_iris(self) -> frozenset[str]:
        return frozenset(wall.context_iri for wall in self.walls)

    @property
    def rules(self) -> tuple[CarryRule, ...]:
        """Every rule, downward first -- the order the pass runs them in."""
        return self.downward + self.upward


def _display_of(iri: str, *, where: str) -> str:
    try:
        return ARROW.join(context_display_parts(context_for_iri(iri)))
    except UnknownContextIRIError:
        raise ContextCarryRuleError(
            f"{where}: {iri!r} is not a context of this list's vocabulary"
        ) from None


def _checked_context(
    iri: Any, display: Any, *, where: str
) -> tuple[str, str]:
    """The IRI and display name of a context, both required, and agreeing.

    The display name is in the file so that a reader can read it; the IRI is
    what the pass matches on.  A pair that disagrees is a rule about one
    context labelled as another, which is the mistake a reader cannot catch.
    """
    iri = str(iri or "").strip()
    display = str(display or "").strip()
    if not iri or not display:
        raise ContextCarryRuleError(f"{where}: a context needs both its IRI and its display name")
    expected = _display_of(iri, where=where)
    if display != expected:
        raise ContextCarryRuleError(
            f"{where}: {iri!r} is {expected!r}, and the row calls it {display!r}"
        )
    return iri, display


def _wall(row: dict[str, Any], *, position: int) -> Wall:
    where = f"wall {position}"
    iri, display = _checked_context(row.get("context_iri"), row.get("context"), where=where)
    comment = str(row.get("comment") or "").strip()
    if not comment:
        raise ContextCarryRuleError(f"{where}: comment is required")
    return Wall(context_iri=iri, context=display, comment=comment)


def _rule(
    row: dict[str, Any], *, direction: CarryDirection, position: int, walls: frozenset[str]
) -> CarryRule:
    where = f"{direction} rule {position}"
    recipient_iri, recipient = _checked_context(
        row.get("recipient_iri"), row.get("recipient"), where=where
    )
    donor_iris = [str(value or "").strip() for value in row.get("donor_iris") or ()]
    donors = [str(value or "").strip() for value in row.get("donors") or ()]
    if not donor_iris or len(donor_iris) != len(donors):
        raise ContextCarryRuleError(
            f"{where}: `donors` and `donor_iris` are required and list the same contexts"
        )
    checked = tuple(
        _checked_context(iri, display, where=f"{where}, donor {index}")
        for index, (iri, display) in enumerate(zip(donor_iris, donors, strict=True), start=1)
    )
    if len({iri for iri, _ in checked}) != len(checked):
        raise ContextCarryRuleError(f"{where}: a donor is listed twice")
    if recipient_iri in {iri for iri, _ in checked}:
        raise ContextCarryRuleError(f"{where}: {recipient!r} cannot be its own donor")
    for iri, display in ((recipient_iri, recipient), *checked):
        if iri in walls:
            raise ContextCarryRuleError(
                f"{where}: {display!r} is a wall, and nothing is carried into or out of one"
            )
    comment = str(row.get("comment") or "").strip()
    if not comment:
        raise ContextCarryRuleError(f"{where}: comment is required")
    return CarryRule(
        direction=direction,
        recipient_iri=recipient_iri,
        recipient=recipient,
        donor_iris=tuple(iri for iri, _ in checked),
        donors=tuple(display for _, display in checked),
        comment=comment,
    )


def load_context_carry_rules(path: Path | None = None) -> ContextCarryRules:
    """The convention, checked.

    Not cached, because it takes a path; the pass reads it once per run.

    :raises ContextCarryRuleError: on a schema version this code does not know,
        a context the vocabulary does not have, a display name that is not the
        IRI's, a rule naming a wall or itself, a recipient named twice in one
        direction, or a missing comment.
    """
    source = path or CONTEXT_CARRY_RULES_FILEPATH
    document = orjson.loads(source.read_bytes())
    version = document.get("schema_version")
    if version != CONTEXT_CARRY_SCHEMA_VERSION:
        raise ContextCarryRuleError(
            f"{source.name} states schema_version {version!r}; this reads "
            f"{CONTEXT_CARRY_SCHEMA_VERSION}"
        )
    walls = tuple(
        _wall(row, position=position)
        for position, row in enumerate(document.get("walls") or (), start=1)
    )
    if len({wall.context_iri for wall in walls}) != len(walls):
        raise ContextCarryRuleError(f"{source.name}: a wall is listed twice")
    wall_iris = frozenset(wall.context_iri for wall in walls)
    by_direction: dict[CarryDirection, tuple[CarryRule, ...]] = {}
    for direction in CarryDirection:
        rules = tuple(
            _rule(row, direction=direction, position=position, walls=wall_iris)
            for position, row in enumerate(document.get(str(direction)) or (), start=1)
        )
        recipients = [rule.recipient_iri for rule in rules]
        if len(set(recipients)) != len(recipients):
            raise ContextCarryRuleError(
                f"{source.name}: a {direction} recipient has two rules; write one "
                f"with the donors in order"
            )
        by_direction[direction] = rules
    rules = ContextCarryRules(
        walls=walls,
        downward=by_direction[CarryDirection.DOWNWARD],
        upward=by_direction[CarryDirection.UPWARD],
    )
    logger.info(
        "loaded_context_carry_rules",
        path=str(source),
        walls=len(rules.walls),
        downward=len(rules.downward),
        upward=len(rules.upward),
    )
    return rules


def _live_flows(
    flows: Mapping[str, Mapping[str, Any]],
) -> dict[str, dict[str, list[str]]]:
    """Every live flow, as substance -> context IRI -> flows.

    A context holding more than one flow of a substance is ordinary -- EF 3.1
    lists some substances twice, under a chemical name and an industry
    designation -- and every empty one of them is filled, while a number on any
    of them makes the context published.
    """
    out: dict[str, dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))
    for uuid, flow in flows.items():
        if flow.get("deprecated"):
            continue
        substance = str(flow.get("flow_object_id") or "")
        context = str(flow.get("context_iri") or "")
        if substance and context:
            out[substance][context].append(str(uuid))
    return out


def _carried_across_contexts(row: Any, context_of: Mapping[str, str]) -> bool:
    """Whether *row* is a number this pass carried from another compartment.

    Those are never donors: a chain would walk a number away from what an
    implementation stated.  A row carried from a flow *in the same
    compartment* -- the size-window convention giving the coarse band PM10's
    number, `lcia.size_class_carry` -- is a donor like a stated one, because it
    crossed no compartment and there is no chain to walk (#196).
    """
    if row.derivation != CARRIED:
        return False
    source = context_of.get(str(row.source_flow_uuid or ""))
    return source is None or source != context_of.get(str(row.elementary_flow_uuid))


def _most_precise(rows: list[Any]) -> Any:
    best = rows[0]
    for candidate in rows[1:]:
        if more_precise_value(best.factor.amount, candidate.factor.amount) == candidate.factor.amount:
            best = candidate
    return best


def carry_across_contexts(
    published: list[Any],
    *,
    rules: ContextCarryRules,
    slug_of: Any,
    flows: Mapping[str, Mapping[str, Any]],
    stated: Mapping[Any, Mapping[tuple[str, str, str], Any]],
) -> tuple[list[Any], dict[str, int]]:
    """*published*, plus one row per blank the convention fills.

    *published* is the consensus implementation's factors as everything upstream
    left them; *slug_of* reads a row's category slug; *flows* is
    :func:`~brightway_flows.lcia.sources.flow_descriptions`; *stated* is
    every **deciding** implementation's factors keyed on (flow, category slug,
    geography) -- what says whether a triple is empty or merely withheld.

    The new rows are appended; nothing already published is touched.  The
    counts say what happened: ``carried`` (and per direction), ``held_by_a_queue``
    for recipients an implementation speaks about, and ``children_disagree``
    for an upward rule whose published children state different numbers.
    """
    counts: Counter[str] = Counter()
    if not rules.rules:
        return published, dict(counts)
    live = _live_flows(flows)
    spoken: set[tuple[str, str, str]] = {
        (str(key[0]), str(key[1]), str(key[2] or ""))
        for factors in stated.values()
        for key in factors
    }
    context_of: dict[str, str] = {
        uuid: context
        for substance, by_context in live.items()
        for context, uuids in by_context.items()
        for uuid in uuids
    }
    #: (slug, geography, substance) -> context IRI -> the published row.
    groups: dict[tuple[str, str, str], dict[str, Any]] = defaultdict(dict)
    for row in published:
        context = context_of.get(row.elementary_flow_uuid)
        if context is None:
            continue  # a withdrawn flow: not a donor, and not filled
        substance = str(flows[row.elementary_flow_uuid].get("flow_object_id") or "")
        groups[(slug_of(row), row.factor.geography or "", substance)].setdefault(context, row)

    carried: list[Any] = []
    for rule in rules.rules:
        for (slug, geography, substance), by_context in groups.items():
            recipients = live.get(substance, {}).get(rule.recipient_iri)
            if not recipients or rule.recipient_iri in by_context:
                continue
            empty = [
                uuid for uuid in recipients if (uuid, slug, geography) not in spoken
            ]
            counts["held_by_a_queue"] += len(recipients) - len(empty)
            if not empty:
                continue
            donors = [
                by_context[donor]
                for donor in rule.donor_iris
                if donor in by_context
                and not _carried_across_contexts(by_context[donor], context_of)
            ]
            if not donors:
                continue
            if rule.direction is CarryDirection.DOWNWARD:
                source = donors[0]
            else:
                if not _all_agree(
                    [row.factor.amount for row in donors], tolerance=RESTATED_PRECISION
                ):
                    counts["children_disagree"] += 1
                    continue
                source = _most_precise(donors)
            for uuid in empty:
                new = replace(
                    source,
                    elementary_flow_uuid=uuid,
                    derivation=CARRIED,
                    # The flow the number was carried from, so a reader can find
                    # the donor; the rule is the one for this flow's context.
                    # `also_stated` belongs to the donor's compartment, where
                    # somebody else spoke; nobody spoke here.
                    source_flow_uuid=source.elementary_flow_uuid,
                    also_stated=None,
                )
                carried.append(new)
                by_context.setdefault(rule.recipient_iri, new)
                counts["carried"] += 1
                counts[f"carried_{rule.direction}"] += 1
                counts[f"rule_{rule.rule_id}"] += 1
    if carried:
        logger.info(
            "carried_across_contexts",
            factors=len(carried),
            downward=counts.get("carried_downward", 0),
            upward=counts.get("carried_upward", 0),
        )
    return published + carried, dict(counts)
