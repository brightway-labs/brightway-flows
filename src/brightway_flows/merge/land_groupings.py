"""Which land classes a source list is allowed to publish as one flow.

A vendor's correspondence table maps flows one at a time, so nothing in it ever
says "these five are now one".  Applied flow by flow it can still fold five
classes onto one and nobody sees it happen: until #111 was measured, ecoinvent's
five landfill classes -- inert material, residual material, sanitary, slag
compartment, and the unqualified dump site -- were published as one `Dump Site`,
twice over, and the five kinds of arable land as one `Arable`.  Reading the
list, there is no way back to which one the inventory meant.

Losing a distinction is sometimes right.  `Transformation, from unknown` and
`Transformation, from unspecified` are two spellings of the same absence of
information, and publishing them as one flow says something true.  What must not
happen is losing it *by accident*, which is what a crosswalk applied flow by flow
does by default.

So this file is the list of the ones this project has looked at and accepted,
each with its reasoning, and `land-flow-groupings.json` is where they are
written down.  A land flow that two source rows reach and this file does not
name stops the build: see :func:`unrecorded_land_groupings`.  The count of
folded land classes is then a number this project states rather than one a
reader discovers.

The other answer to the same question lives in
`brightway_flows.match_overrides`: a ``decline`` row takes the coarsening
row away, and the source flow is published under its own name by the addition
path.  That is what fourteen of ecoinvent's twenty-five folded rows got, and it
is the answer to prefer -- this file is for the folds that are *meant*.

A grouping names its list, not its release.  Within one list a uuid names the
same flow across releases, so a decision about a flow is a decision about it in
every release that ships it; a member no release carries is inert, exactly as a
match override for a dropped flow is.  It never names a *version*, because
requiring one would make a curator re-decide the same fold every release.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from functools import cache

import orjson
import structlog

from brightway_flows.domain.context import Dimension
from brightway_flows.filesystem import PACKAGE_DATA_DIR
from brightway_flows.merge.report import AlgorithmMatch, PreparedMatch

logger = structlog.get_logger(__name__)

GROUPINGS_FILEPATH = PACKAGE_DATA_DIR / "land-flow-groupings.json"

#: The on-disk format of *this* ruling file, and nothing else.  The bare
#: ``SCHEMA_VERSION`` is ``domain.schema``'s, the version the project publishes.
DECISIONS_SCHEMA_VERSION = 1

#: What a grouping has to carry.  ``comment`` is not optional for the same
#: reason it is not optional on a match override: the row asserts that a
#: distinction the source list drew is not worth keeping, and an assertion with
#: no stated reasoning cannot be re-checked against the vendor's next release.
REQUIRED_FIELDS = ("list_name", "target_uuid", "absorbs", "comment")


@dataclass(frozen=True)
class GroupedFlow:
    """One source flow a grouping folds into its target.

    The name is read by nobody.  It is stated so that a curator reading the file
    can see which flow a row is about without looking the uuid up, and it is
    declared here rather than dropped so the record says everything the file
    does.
    """

    source_uuid: str
    source_name: str = ""


@dataclass(frozen=True)
class LandGrouping:
    """One accepted fold: several of a list's land flows, published as one."""

    list_name: str
    target_uuid: str
    #: Why the distinction the source list drew is not worth keeping.
    comment: str
    target_name: str = ""
    absorbs: tuple[GroupedFlow, ...] = ()

    @property
    def absorbed_uuids(self) -> frozenset[str]:
        """The source flows this grouping accounts for."""
        return frozenset(member.source_uuid for member in self.absorbs)


def _members(value: object, *, index: int) -> tuple[GroupedFlow, ...]:
    """The ``absorbs`` list of a stored grouping, as records.

    :raises ValueError: if it is not a list of objects each naming a source
        flow, or if it names fewer than two.  A grouping of one is not a
        grouping -- it is an ordinary mapping, written where a reader would
        take it for a decision that several classes were merged.
    """
    if not isinstance(value, list):
        raise ValueError(
            f"Grouping {index} in {GROUPINGS_FILEPATH.name} states 'absorbs' as "
            f"{value!r}. It is the list of source flows published as the target."
        )
    members: list[GroupedFlow] = []
    for entry in value:
        if not isinstance(entry, dict):
            raise ValueError(
                f"Grouping {index} in {GROUPINGS_FILEPATH.name} has {entry!r} "
                f"among its absorbed flows. Each is an object naming a "
                f"'source_uuid', and a 'source_name' so a curator can read it."
            )
        source_uuid = str(entry.get("source_uuid") or "").strip()
        if not source_uuid:
            raise ValueError(
                f"Grouping {index} in {GROUPINGS_FILEPATH.name} has an absorbed "
                f"flow with no 'source_uuid'. A grouping is stated in uuids, "
                f"because that is what the merge has in hand."
            )
        members.append(
            GroupedFlow(
                source_uuid=source_uuid,
                source_name=str(entry.get("source_name") or "").strip(),
            )
        )
    if len({member.source_uuid for member in members}) < 2:
        raise ValueError(
            f"Grouping {index} in {GROUPINGS_FILEPATH.name} absorbs "
            f"{len(members)} flow(s). Two or more: a grouping of one is an "
            f"ordinary mapping, and writing it here would read as a decision "
            f"that several land classes were deliberately merged."
        )
    return tuple(members)


@cache
def load_land_flow_groupings() -> dict[tuple[str, str], LandGrouping]:
    """Every accepted fold, keyed by ``(list_name, target_uuid)``.

    A missing file is not an error: no list having an accepted fold is a state
    the project could reach, and it is the state this check exists to keep
    close to.

    :raises ValueError: if the payload has no ``groupings`` list, if a row is
        missing any of :data:`REQUIRED_FIELDS`, if a row absorbs fewer than two
        flows, or if two rows claim the same list and target.  All four are
        authoring mistakes that would otherwise leave a fold looking accounted
        for when it is not.
    """
    if not GROUPINGS_FILEPATH.exists():
        return {}

    payload = orjson.loads(GROUPINGS_FILEPATH.read_bytes())
    if not isinstance(payload, dict) or not isinstance(payload.get("groupings"), list):
        raise ValueError(
            f"{GROUPINGS_FILEPATH.name} must contain a 'groupings' list."
        )

    index: dict[tuple[str, str], LandGrouping] = {}
    for position, row in enumerate(payload["groupings"]):
        if not isinstance(row, dict):
            raise ValueError(
                f"Grouping {position} in {GROUPINGS_FILEPATH.name} is "
                f"{row!r} rather than an object."
            )
        for name in REQUIRED_FIELDS:
            if not row.get(name):
                raise ValueError(
                    f"Grouping {position} in {GROUPINGS_FILEPATH.name} has no "
                    f"{name!r}. Every row here says a distinction a source list "
                    f"drew is not worth keeping, and that needs "
                    f"{', '.join(REQUIRED_FIELDS)}."
                )
        key = (
            str(row["list_name"]).strip(),
            str(row["target_uuid"]).strip(),
        )
        if key in index:
            raise ValueError(
                f"Groupings for {key[0]} on {key[1]} are stated twice in "
                f"{GROUPINGS_FILEPATH.name}. One target, one decision: two rows "
                f"would mean the last one read wins, which is not a decision "
                f"anyone made."
            )
        index[key] = LandGrouping(
            list_name=key[0],
            target_uuid=key[1],
            comment=str(row["comment"]),
            target_name=str(row.get("target_name") or "").strip(),
            absorbs=_members(row["absorbs"], index=position),
        )
    return index


def _is_land(match: PreparedMatch | AlgorithmMatch) -> bool:
    """Whether the flow *match* landed on is a land flow.

    Read off the target's context dimension rather than its name: `Arable` and
    `From Arable` are land classes and `Arable` is also a word, and the question
    here is which part of the environment the flow is in.
    """
    context = match.target_context
    return bool(context) and str(context[0]) == Dimension.LAND_USE


def unrecorded_land_groupings(
    matches: Iterable[PreparedMatch | AlgorithmMatch],
    *,
    list_name: str,
    recorded: Mapping[tuple[str, str], LandGrouping],
) -> list[str]:
    """The folds *matches* performs that *recorded* does not account for.

    A fold is two or more of one list's source rows landing on one land flow.
    It is accounted for when a grouping names that list and that flow, and names
    every source flow that reached it.

    Stated as **observed within recorded**, not as equality.  A release that does
    not ship a member of a recorded fold reaches the target with fewer rows, and
    that is the release not carrying the flow rather than the decision changing
    -- the same reading `match_overrides` takes of a row naming a dropped flow.
    A release that folds a class nobody has looked at is the other direction,
    and is what this returns.

    Returns one line per unaccounted fold, ready to be read by a person: which
    flow, and which source rows reached it that no grouping names.
    """
    reached: dict[str, dict[str, str]] = {}
    target_names: dict[str, str] = {}
    for match in matches:
        if not _is_land(match):
            continue
        target = str(match.target_elementary_flow_id or "").strip()
        if not target:
            continue
        reached.setdefault(target, {})[str(match.source_uuid)] = str(match.source_name)
        target_names.setdefault(target, str(match.target_name))

    problems: list[str] = []
    for target, sources in sorted(reached.items(), key=lambda kv: target_names[kv[0]]):
        if len(sources) < 2:
            continue
        grouping = recorded.get((list_name, target))
        accounted = grouping.absorbed_uuids if grouping else frozenset()
        unaccounted = {
            uuid: name for uuid, name in sources.items() if uuid not in accounted
        }
        if not unaccounted:
            continue
        problems.append(
            f"{target_names[target] or target} ({target}) is reached by "
            f"{len(sources)} {list_name} flows; "
            f"{'no grouping names it' if grouping is None else 'its grouping does not name'} "
            + ", ".join(
                f"{name or '<unnamed>'} ({uuid})"
                for uuid, name in sorted(unaccounted.items(), key=lambda kv: kv[1])
            )
        )
    return problems
