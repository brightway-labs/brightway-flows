"""One window convention: which size window's number a blank particle flow takes.

`Particles (PM2.5 - PM10)` in urban ground-level air carried no factor under
EF 3.1's particulate matter category, while `Particles (PM10)` in the same
compartment was worth 5.49e-5 disease incidences per kilogram.  Nobody stated a
coarse-band number: EF's own flow list has the band and its factor table does
not, and this list publishes only what somebody stated.  Whether the coarse band
takes PM10's number is not a fact about particles and not a fact about EF 3.1 --
it is a fact about *our* size scheme, and it is written down once, here, for
every method this list publishes (`plans/particle-family.md` §6).

``data/particle-size-carry-rules.json`` is that convention, in the shape
``context-carry-rules.json`` has for compartments:

* **downward** -- a recipient window and its broader windows, nearest first.
  The loader refuses a donor list that is not the recipient's own chain in
  ``particulate-size-classes.json``, so the file can say which windows carry and
  cannot contradict the scheme about which contains which.  The first donor
  published in the compartment gives its number: the coarse band takes PM10's,
  failing that the unsized total's.
* **upward** -- the size-unstated total from its direct children, only where
  every one of them is published and they state the same number, the most
  precise printing kept.  Stricter than the compartment convention, which lets
  a root take a sole child's number: PM10 is the total's only characterised
  child under EF, and giving the total PM10's number is the "unspecified means
  PM10" reading the owner declined for Stepwise.  Run after the downward rules,
  and only from stated numbers.

**The pass carries a number; it never invents one.**  It runs inside one
compartment, *before* the compartment convention, and does what
:func:`~brightway_flows.lcia.context_carry.carry_across_contexts` does and no
more: it fills a triple only where no deciding implementation states anything
for that flow, category and place; it never publishes onto a withdrawn flow;
and it writes ``derivation: carried`` with the donor flow as
``source_flow_uuid`` -- the rule is the one for the recipient's window, and a
window has one rule per direction, so the pair names it.  A number carried here
is then a donor for the compartment convention, which spreads it into the
outdoor strata the way it spreads a stated one: it was carried *within* a
compartment, not along a chain of them, which is the chain that convention
refuses to walk.

On the 944b274 build this fills the coarse band under EF in its air compartments,
and under Stepwise 2006 the two windows finer than PM2.5, the coarse band and --
once the collision on the unsized total is ruled -- the above-ten fraction.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Mapping
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

import orjson
import structlog

from brightway_flows.domain.particulate_size import (
    SizeClass,
    broader_chain,
    class_by_flow_object,
    size_classes,
)
from brightway_flows.filesystem import PACKAGE_DATA_DIR
from brightway_flows.lcia.consensus import RESTATED_PRECISION, Derivation, _all_agree
from brightway_flows.lcia.context_carry import CarryDirection, _most_precise

logger = structlog.get_logger(__name__)

#: The curated file.
SIZE_CLASS_CARRY_RULES_FILEPATH = PACKAGE_DATA_DIR / "particle-size-carry-rules.json"

#: Bumped when the shape changes, and read rather than assumed.
SIZE_CLASS_CARRY_SCHEMA_VERSION = 1

#: What a carried factor's `derivation` says -- the same word the compartment
#: convention writes, because it is the same kind of statement.
CARRIED = str(Derivation.CARRIED)


class SizeClassCarryRuleError(ValueError):
    """A rule that cannot be read as one.

    Raised rather than skipped, for the reason `lcia.context_carry` raises: a
    malformed convention that is quietly ignored looks applied and is not.
    """


@dataclass(frozen=True)
class SizeCarryRule:
    """One recipient window and the windows it may take a number from."""

    direction: CarryDirection
    recipient: SizeClass
    donors: tuple[SizeClass, ...]
    comment: str

    @property
    def rule_id(self) -> str:
        """What a run's counts call this rule."""
        return f"{self.direction}:{self.recipient.id}"


@dataclass(frozen=True)
class SizeClassCarryRules:
    """The whole convention, as read."""

    downward: tuple[SizeCarryRule, ...]
    upward: tuple[SizeCarryRule, ...]

    @property
    def rules(self) -> tuple[SizeCarryRule, ...]:
        """Every rule, downward first -- the order the pass runs them in."""
        return self.downward + self.upward


def _rule(
    row: dict[str, Any], *, direction: CarryDirection, position: int
) -> SizeCarryRule:
    where = f"{direction} rule {position}"
    classes = size_classes()
    recipient_id = str(row.get("recipient") or "").strip()
    if recipient_id not in classes:
        raise SizeClassCarryRuleError(
            f"{where}: {recipient_id!r} is not a window of particulate-size-classes.json"
        )
    donor_ids = [str(value or "").strip() for value in row.get("donors") or ()]
    if not donor_ids:
        raise SizeClassCarryRuleError(f"{where}: `donors` is required")
    for donor_id in donor_ids:
        if donor_id not in classes:
            raise SizeClassCarryRuleError(
                f"{where}: donor {donor_id!r} is not a window of "
                "particulate-size-classes.json"
            )
    if len(set(donor_ids)) != len(donor_ids):
        raise SizeClassCarryRuleError(f"{where}: a donor is listed twice")
    if recipient_id in donor_ids:
        raise SizeClassCarryRuleError(f"{where}: {recipient_id!r} cannot be its own donor")
    if direction is CarryDirection.DOWNWARD:
        # The scheme says which window contains which; the file may only say
        # how far up the chain a blank looks.  A donor list that skips a
        # window, reorders two, or names a sibling is a containment claim the
        # bounds do not make, and the bounds are what a reviewer can check.
        chain = broader_chain(recipient_id)[1:]
        if donor_ids != chain[: len(donor_ids)]:
            raise SizeClassCarryRuleError(
                f"{where}: the donors of {recipient_id!r} must be its broader "
                f"windows nearest first, {chain}; the row says {donor_ids}"
            )
    else:
        children = sorted(
            identifier for identifier, value in classes.items() if value.broader == recipient_id
        )
        if sorted(donor_ids) != children:
            raise SizeClassCarryRuleError(
                f"{where}: the donors of {recipient_id!r} must be its direct "
                f"children, {children}; the row says {sorted(donor_ids)}"
            )
    comment = str(row.get("comment") or "").strip()
    if not comment:
        raise SizeClassCarryRuleError(f"{where}: comment is required")
    return SizeCarryRule(
        direction=direction,
        recipient=classes[recipient_id],
        donors=tuple(classes[donor_id] for donor_id in donor_ids),
        comment=comment,
    )


def load_size_class_carry_rules(path: Path | None = None) -> SizeClassCarryRules:
    """The convention, checked.

    Not cached, because it takes a path; the pass reads it once per run.

    :raises SizeClassCarryRuleError: on a schema version this code does not
        know, a window the scheme does not have, a downward donor list that is
        not the recipient's chain, an upward donor list that is not the
        recipient's children, a recipient named twice in one direction, or a
        missing comment.
    """
    source = path or SIZE_CLASS_CARRY_RULES_FILEPATH
    document = orjson.loads(source.read_bytes())
    version = document.get("schema_version")
    if version != SIZE_CLASS_CARRY_SCHEMA_VERSION:
        raise SizeClassCarryRuleError(
            f"{source.name} states schema_version {version!r}; this reads "
            f"{SIZE_CLASS_CARRY_SCHEMA_VERSION}"
        )
    by_direction: dict[CarryDirection, tuple[SizeCarryRule, ...]] = {}
    for direction in CarryDirection:
        rules = tuple(
            _rule(row, direction=direction, position=position)
            for position, row in enumerate(document.get(str(direction)) or (), start=1)
        )
        recipients = [rule.recipient.id for rule in rules]
        if len(set(recipients)) != len(recipients):
            raise SizeClassCarryRuleError(
                f"{source.name}: a {direction} recipient has two rules; write one "
                f"with the donors in order"
            )
        by_direction[direction] = rules
    rules = SizeClassCarryRules(
        downward=by_direction[CarryDirection.DOWNWARD],
        upward=by_direction[CarryDirection.UPWARD],
    )
    logger.info(
        "loaded_size_class_carry_rules",
        path=str(source),
        downward=len(rules.downward),
        upward=len(rules.upward),
    )
    return rules


def _live_particle_flows(
    flows: Mapping[str, Mapping[str, Any]],
) -> dict[str, dict[str, list[str]]]:
    """Every live flow of a size window, as context IRI -> window id -> flows.

    Only the seven windows' objects; every other substance is not this pass's
    business and is skipped without being read.
    """
    windows = class_by_flow_object()
    out: dict[str, dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))
    for uuid, flow in flows.items():
        if flow.get("deprecated"):
            continue
        window = windows.get(str(flow.get("flow_object_id") or ""))
        context = str(flow.get("context_iri") or "")
        if window and context:
            out[context][window.id].append(str(uuid))
    return out


def carry_across_size_classes(
    published: list[Any],
    *,
    rules: SizeClassCarryRules,
    slug_of: Any,
    flows: Mapping[str, Mapping[str, Any]],
    stated: Mapping[Any, Mapping[tuple[str, str, str], Any]],
) -> tuple[list[Any], dict[str, int]]:
    """*published*, plus one row per blank window the convention fills.

    The same contract as `carry_across_contexts`: *published* is the consensus
    implementation's factors as everything upstream left them, *slug_of* reads a
    row's category slug, *flows* is `flow_descriptions`, and *stated* is every
    deciding implementation's factors keyed on (flow, category slug, geography)
    -- what says whether a triple is empty or merely withheld.

    The new rows are appended; nothing already published is touched.  The
    counts say what happened: ``carried`` (and per direction and per rule),
    ``held_by_a_queue`` for recipients an implementation speaks about,
    ``children_missing`` for the upward rule where a child is not published,
    and ``children_disagree`` where the published children state different
    numbers.
    """
    counts: Counter[str] = Counter()
    if not rules.rules:
        return published, dict(counts)
    live = _live_particle_flows(flows)
    if not live:
        return published, dict(counts)
    spoken: set[tuple[str, str, str]] = {
        (str(key[0]), str(key[1]), str(key[2] or ""))
        for factors in stated.values()
        for key in factors
    }
    windows = class_by_flow_object()
    #: (slug, geography, context IRI) -> window id -> the published row.
    groups: dict[tuple[str, str, str], dict[str, Any]] = defaultdict(dict)
    for row in published:
        flow = flows.get(row.elementary_flow_uuid)
        if flow is None or flow.get("deprecated"):
            continue  # a withdrawn flow: not a donor, and not filled
        window = windows.get(str(flow.get("flow_object_id") or ""))
        if window is None:
            continue
        key = (slug_of(row), row.factor.geography or "", str(flow.get("context_iri") or ""))
        groups[key].setdefault(window.id, row)

    carried: list[Any] = []
    for rule in rules.rules:
        for (slug, geography, context), by_window in list(groups.items()):
            recipients = live.get(context, {}).get(rule.recipient.id)
            if not recipients or rule.recipient.id in by_window:
                continue
            empty = [
                uuid for uuid in recipients if (uuid, slug, geography) not in spoken
            ]
            counts["held_by_a_queue"] += len(recipients) - len(empty)
            if not empty:
                continue
            donors = [
                by_window[donor.id]
                for donor in rule.donors
                if donor.id in by_window and by_window[donor.id].derivation != CARRIED
            ]
            if not donors:
                continue
            if rule.direction is CarryDirection.DOWNWARD:
                source = donors[0]
            else:
                # Every child, not any one of them.  The compartment convention
                # lets a root take a sole published child's number; here that
                # would give the size-unstated total PM10's number wherever
                # nobody characterises the above-ten fraction -- which is EF
                # everywhere, and is the "unspecified means PM10" reading the
                # owner declined for Stepwise (`lcia-factor-collision-rulings`).
                # A total is its children only where all of them are spoken for.
                if len(donors) != len(rule.donors):
                    counts["children_missing"] += 1
                    continue
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
                    # the donor; the rule is the one for this flow's window.
                    source_flow_uuid=source.elementary_flow_uuid,
                    also_stated=None,
                )
                carried.append(new)
                by_window.setdefault(rule.recipient.id, new)
                counts["carried"] += 1
                counts[f"carried_{rule.direction}"] += 1
                counts[f"rule_{rule.rule_id}"] += 1
    if carried:
        logger.info(
            "carried_across_size_classes",
            factors=len(carried),
            downward=counts.get("carried_downward", 0),
            upward=counts.get("carried_upward", 0),
        )
    return published + carried, dict(counts)
