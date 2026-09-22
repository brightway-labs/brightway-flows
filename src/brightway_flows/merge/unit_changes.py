"""Does the flow a source row landed on measure the same thing the row does?

A correspondence table says which target a source flow maps to.  It does not
say the two are measured in the same unit, and nothing in the merge noticed
when they were not: ecoinvent 3.8's `Manganese-55` becomes 3.10.1's `Manganese`
under an unchanged UUID while its unit changes from kBq to kg, recorded in no
table at all.

**The comparison is source flow against the elementary flow it resolved onto,
not the two sides of a table row.**  That is forced -- the
`ecoinvent-*-biosphere-EF-3.1-biosphere` tables carry no `unit` key on either
side of any row -- and it is also the better check, because it covers
algorithmic matches too, which is what a list arriving with no table gets.  The
first real defect this found was an algorithmic one.

Both sides are canonicalised before comparison.  The source side is already
canonical by the time a row reaches the merge; the target side is whatever the
elementary flow record stores, and comparing raw notations reports `m2.a`
against `m2*a` as a disagreement.

**It reports; it never raises and never converts.**  A dimension change is
usually an error but not always: EF 3.1 accounts fossil energy carriers by
energy content on purpose, so ecoinvent's `Coal, brown` in kg maps onto brown
coal in MJ and that mapping is right.  Those decisions live in
`unit-change-allowlist.json`, each with a comment, because an entry there
asserts that a dimensionally impossible mapping is nonetheless correct and that
assertion needs its reasoning attached.

**A mismatch annotates a match; it does not replace one.**  This runs as a pass
over the matches the merge already made, and sets `has_unit_mismatch` on the
outcome -- the same shape as `has_context_inconsistency`, and for the same
reason `merge/store.py` gives: an inconsistency is an annotation on an outcome,
not an outcome of its own.  It deliberately does *not* push rows into
`accumulator.unmatched`: that list is consumed by the manual-additions pass,
which creates elementary flows, so reporting an already-matched flow there
would mint a duplicate of it.

The creation side
-----------------

A row that matches nothing is not skipped -- it creates a flow -- and for a
long time nothing asked the unit question of those rows at all, because the
question above cannot be asked of them: the row *is* the target.  What can be
asked, and is, is whether the rows landing together agree with **each other**.

BAFU ships one flow twice more often than that sounds: four road-noise rows are
two flows written in kilometres and again in metres, and `Heat, Waste` arrives
in megajoules and in kilowatt-hours (#78).  Both rows of a pair land on one
created flow, because `(flow_object_id, context_iri)` is unique, and the flow
states one unit.

:func:`decide_created_flow_unit` is what states it, and the answer comes from
one of four places, in this order:

``curator``
    ``created-flow-unit-decisions.json`` names the row whose unit wins.  For
    where neither table below has an opinion and somebody has to have one.

``published_unit``
    ``published-units.json`` names the unit this list publishes that quantity
    kind in -- the kilobecquerel for an activity -- and every unit offered
    sits on its scale, so the flow states it whether or not any row arrived in
    it.  This is a fact about the list rather than about units, which is why
    it outranks the reference unit: the becquerel defines the activity scale,
    and the list still writes that scale in kilobecquerels, on every one of
    EF 3.1's 954 radionuclide flows (#142).

``unit_table``
    One of the units offered is the reference unit `units.json` names for that
    quantity kind -- the metre for a length -- and that is the one the flow
    states.

``unresolved``
    None of them, so the first row stands and the run says so.  Megajoules
    against kilowatt-hours is this: the coherent unit for an energy is the
    joule and BAFU offers neither, so preferring one over the other would be a
    convention this project had invented rather than a fact it had read.
    Where the project *has* read such a convention off its own published list,
    it is written into ``published-units.json`` and stops being invented.

Whichever way it goes, a row whose own unit is not the one the flow states is
flagged exactly as a matched row would be, and means the same thing by it: this
source row is measured in something other than the flow it landed on.  Which
kind of disagreement it was is the outcome's own `outcome` column -- `created`
against `algorithm` or `prepared` -- so no second flag says it twice.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

from pathlib import Path

import orjson
import structlog

from brightway_flows.domain.units import (
    canonical_unit,
    unit_row_for,
    unit_table_factor,
)
from brightway_flows.filesystem import PACKAGE_DATA_DIR

logger = structlog.get_logger(__name__)

ALLOWLIST_FILEPATH = (
    PACKAGE_DATA_DIR / "unit-change-allowlist.json"
)


def load_unit_change_allowlist(path: Path | None = None) -> set[tuple[str, str]]:
    """Accepted unit changes, as ``(source uuid, target elementary flow id)``.

    *path* is injectable and this is deliberately **not** cached: those two go
    together, per the convention in `domain.rulings`. A cached loader that also
    takes a path serves the first caller's file to every caller after it, which
    in a test suite means one fixture leaking into every later test.

    Keyed on the pair rather than on the source flow alone, because the same
    flow can be accepted against one target and wrong against another.
    `Gas, mine, off-gas, process, coal mining` is both: sm3 to MJ against EF
    3.1's natural gas, which is accepted, and m3 to Sm3 within ecoinvent, which
    is a different assertion about the same flow.

    An entry with no comment is ignored and its pair reported as if unlisted.
    The comment is the entry's whole justification; an uncommented row would
    silence the guard while asserting nothing.
    """
    path = ALLOWLIST_FILEPATH if path is None else path
    if not path.exists():
        return set()
    payload = orjson.loads(path.read_bytes())
    allowed: set[tuple[str, str]] = set()
    for row in payload.get("accepted", []):
        if not isinstance(row, dict):
            continue
        source_uuid = str(row.get("source_uuid") or "").strip()
        target_id = str(row.get("target_elementary_flow_id") or "").strip()
        if not source_uuid or not target_id:
            continue
        if not str(row.get("comment") or "").strip():
            logger.warning(
                "unit_change_allowlist_entry_without_comment",
                source_uuid=source_uuid, target_elementary_flow_id=target_id,
            )
            continue
        allowed.add((source_uuid, target_id))
    return allowed


def find_unit_mismatches(
    matches: list[Any],
    *,
    units_index: dict[str, dict[str, Any]],
    allowed: set[tuple[str, str]],
) -> set[str]:
    """Source uuids in *matches* whose units disagree with their target's.

    *matches* are `PreparedMatch` or `AlgorithmMatch` records; both carry
    `source_unit` and `target_unit`, so this needs nothing the merge did not
    already record.

    A row with either unit missing is not reported: an absent unit is its own
    problem and is not evidence that the two sides disagree.
    """
    mismatched: set[str] = set()
    for row in matches:
        source_unit = canonical_unit(str(row.source_unit or ""), units_index)
        target_unit = canonical_unit(str(row.target_unit or ""), units_index)
        if not source_unit or not target_unit or source_unit == target_unit:
            continue
        target_id = str(row.target_elementary_flow_id or "")
        if (row.source_uuid, target_id) in allowed:
            continue
        mismatched.add(row.source_uuid)
        logger.info(
            "unit_mismatch",
            source_uuid=row.source_uuid, source_name=row.source_name,
            source_unit=row.source_unit, target_unit=row.target_unit,
            target_elementary_flow_id=target_id,
        )
    return mismatched


def crosses_quantity_kinds(source_unit: str, target_unit: str) -> bool:
    """Whether the two units measure different kinds of quantity.

    The distinction the guard above does not draw, and the one that decides
    whether a pair needs a curator.  A becquerel against a kilobecquerel is one
    quantity written at two scales, and `units.json` converts it without
    anybody's help.  A kilogram against a megajoule is a mass against an
    energy, and no table converts those, because how many megajoules a kilogram
    is depends on the substance.

    False for a unit `units.json` does not know: an unreadable unit is its own
    problem, and reporting it as a quantity-kind crossing would say something
    about the two units that has not been established.
    """
    source_row = unit_row_for(source_unit)
    target_row = unit_row_for(target_unit)
    if source_row is None or target_row is None:
        return False
    return source_row.get("quantity_kind_iri") != target_row.get("quantity_kind_iri")


def report_unrecorded_crossings(
    matches: list[Any],
    *,
    units_index: dict[str, dict[str, Any]],
    allowed: set[tuple[str, str]],
) -> list[tuple[str, str]]:
    """Say, at build time, which quantity-kind crossings nobody has ruled on.

    Returns the ``(source uuid, target elementary flow id)`` pairs, and logs one
    warning per pair, so a run that publishes a mass on an energy for which no
    heating value has been written down says so where somebody reading the log
    will see it.

    It warns and does not raise, which is the answer #171 settled on.  Refusing
    the merge would make a new source list unmergeable until every crossing it
    happens to produce had been argued -- and a crossing is usually the vendor's
    accounting convention rather than a defect, so the first thing a curator
    needs is the list, not a stopped build.  What stops one being forgotten is
    `merge.unit_crossings_unrecorded`, which `assess` grades against
    `expectations/0805-every-quantity-kind-crossing-is-recorded.json`.
    """
    unrecorded: list[tuple[str, str]] = []
    for row in matches:
        source_unit = canonical_unit(str(row.source_unit or ""), units_index)
        target_unit = canonical_unit(str(row.target_unit or ""), units_index)
        if not crosses_quantity_kinds(source_unit, target_unit):
            continue
        target_id = str(row.target_elementary_flow_id or "")
        if (row.source_uuid, target_id) in allowed:
            continue
        unrecorded.append((row.source_uuid, target_id))
        logger.warning(
            "unit_crossing_without_a_ruling",
            source_uuid=row.source_uuid, source_name=row.source_name,
            source_unit=row.source_unit, target_unit=row.target_unit,
            target_elementary_flow_id=target_id,
        )
    return unrecorded


DECISIONS_FILEPATH = (
    PACKAGE_DATA_DIR / "created-flow-unit-decisions.json"
)

#: What a decision has to carry.  `source_unit` is not decoration: it is what
#: makes a stale decision fail loudly.  A decision names a row by uuid and keeps
#: applying after the vendor changes that row's unit, and the reasoning that
#: justified it was about the old one.
_DECISION_FIELDS = ("source", "source_uuid", "source_name", "source_unit", "comment")

#: How a created flow's unit was arrived at, most authoritative first.
DECIDED_BY_CURATOR = "curator"
DECIDED_BY_PUBLISHED_UNIT = "published_unit"
DECIDED_BY_UNIT_TABLE = "unit_table"
UNDECIDED = "unresolved"


class CreatedFlowUnitError(ValueError):
    """A ``created-flow-unit-decisions.json`` row is unusable."""


@dataclass(frozen=True)
class CreatedFlowUnitDecision:
    """Which of the disagreeing rows a created flow takes its unit from.

    The row is named rather than the unit: ``source_name`` and ``source_unit``
    are what the vendor file said when the decision was made, so a uuid the list
    stopped shipping, or a row whose unit changed, is a decision that has
    outlived what it was written about and can be caught saying so.
    """

    source: str
    source_uuid: str
    source_name: str
    source_unit: str
    comment: str


@lru_cache(maxsize=None)
def created_flow_unit_decisions(source_label: str) -> dict[str, CreatedFlowUnitDecision]:
    """``source_uuid -> decision`` for one list's created-flow unit choices.

    A decision names the row whose unit the flow states, rather than naming the
    unit directly, so it can be checked against the vendor file: a uuid the list
    stopped shipping, or a row whose unit changed, is a decision that has
    outlived what it was written about.

    :raises CreatedFlowUnitError: if a row is missing a required field or two
        rows name one flow.  These are hand-written decisions about what this
        list publishes; one that cannot say which row it is about, or why, is
        not a decision anyone can re-check.
    """
    if not DECISIONS_FILEPATH.exists():
        return {}
    payload = orjson.loads(DECISIONS_FILEPATH.read_bytes())
    rows = payload.get("decisions")
    if rows is None:
        return {}
    if not isinstance(rows, list):
        raise CreatedFlowUnitError(f"{DECISIONS_FILEPATH}: 'decisions' must be a list")

    wanted = str(source_label or "").strip().lower()
    decisions: dict[str, CreatedFlowUnitDecision] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        missing = [
            field for field in _DECISION_FIELDS
            if not str(row.get(field) or "").strip()
        ]
        if missing:
            raise CreatedFlowUnitError(
                f"{DECISIONS_FILEPATH}: decision for source={row.get('source')!r} "
                f"uuid={row.get('source_uuid')!r} is missing {missing}"
            )
        if str(row["source"]).strip().lower() != wanted:
            continue
        uuid = str(row["source_uuid"]).strip()
        if uuid in decisions:
            # Last-wins would pick one of two curated statements about one flow
            # by file order, which is the arbitration every other curated file
            # in this project refuses.
            raise CreatedFlowUnitError(
                f"{DECISIONS_FILEPATH}: two decisions for {source_label} {uuid} -- "
                f"{decisions[uuid].source_unit} and {row.get('source_unit')}. "
                f"One flow, one decision."
            )
        decisions[uuid] = CreatedFlowUnitDecision(
            source=str(row["source"]).strip(),
            source_uuid=uuid,
            source_name=str(row["source_name"]).strip(),
            source_unit=str(row["source_unit"]).strip(),
            comment=str(row["comment"]).strip(),
        )
    return decisions


def is_a_reference_unit(unit: str) -> bool:
    """Whether `units.json` makes *unit* the reference for its quantity kind.

    The metre for a length, the becquerel for an activity: the unit every other
    unit of that kind states its multiplier against, and so the one spelling of
    the scale that cannot itself be a conversion of something else.
    """
    row = unit_row_for(unit)
    if row is None:
        return False
    return bool(row.get("iri")) and row.get("iri") == row.get("reference_unit_iri")


PUBLISHED_UNITS_FILEPATH = PACKAGE_DATA_DIR / "published-units.json"

#: What a published-unit convention has to carry.  `quantity_kind_iri` and
#: `notation` are cross-checked against `units.json` at load, so an entry
#: claiming a unit measures something it does not fails the build rather than
#: silently never applying.
_PUBLISHED_UNIT_FIELDS = ("quantity_kind_iri", "notation", "comment")


class PublishedUnitError(ValueError):
    """A ``published-units.json`` row is unusable."""


@dataclass(frozen=True)
class PublishedUnit:
    """The unit this list publishes one quantity kind in, and the evidence."""

    quantity_kind_iri: str
    notation: str
    comment: str


@lru_cache(maxsize=None)
def published_units() -> dict[str, PublishedUnit]:
    """``quantity_kind_iri -> the unit this list publishes that kind in``.

    A convention rather than a fact about units: `units.json` says the
    becquerel defines the activity scale, and cannot say that this list writes
    activity in kilobecquerels -- that is a fact about the list, asserted in
    ``published-units.json`` with its evidence.  Cached because the path is
    fixed (rule 13).

    :raises PublishedUnitError: if a row is missing a field, names a unit the
        unit table does not know, names a unit of a different quantity kind
        than it claims, or two rows name one kind.  These are hand-written
        conventions about what this list publishes; one the unit table cannot
        corroborate is not one.
    """
    if not PUBLISHED_UNITS_FILEPATH.exists():
        return {}
    payload = orjson.loads(PUBLISHED_UNITS_FILEPATH.read_bytes())
    rows = payload.get("units")
    if rows is None:
        return {}
    if not isinstance(rows, list):
        raise PublishedUnitError(
            f"{PUBLISHED_UNITS_FILEPATH}: 'units' must be a list"
        )
    published: dict[str, PublishedUnit] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        missing = [
            field for field in _PUBLISHED_UNIT_FIELDS
            if not str(row.get(field) or "").strip()
        ]
        if missing:
            raise PublishedUnitError(
                f"{PUBLISHED_UNITS_FILEPATH}: entry for "
                f"quantity_kind_iri={row.get('quantity_kind_iri')!r} is "
                f"missing {missing}"
            )
        kind = str(row["quantity_kind_iri"]).strip()
        notation = str(row["notation"]).strip()
        unit_row = unit_row_for(notation)
        if unit_row is None:
            raise PublishedUnitError(
                f"{PUBLISHED_UNITS_FILEPATH}: {notation!r} is not a unit "
                f"`units.json` knows, so nothing can be published in it."
            )
        if str(unit_row.get("quantity_kind_iri") or "") != kind:
            raise PublishedUnitError(
                f"{PUBLISHED_UNITS_FILEPATH}: {notation!r} measures "
                f"{unit_row.get('quantity_kind_iri')!r}, not {kind!r}."
            )
        if kind in published:
            raise PublishedUnitError(
                f"{PUBLISHED_UNITS_FILEPATH}: two units for {kind} -- "
                f"{published[kind].notation} and {notation}. "
                f"One quantity kind, one published unit."
            )
        published[kind] = PublishedUnit(
            quantity_kind_iri=kind,
            notation=notation,
            comment=str(row["comment"]).strip(),
        )
    return published


def published_unit_for(units: Sequence[str]) -> str | None:
    """The unit this list publishes *units*' quantity kind in, where stating
    it would change anything.

    ``None`` in every case where the convention has nothing to say: a unit the
    table does not know, units of two quantity kinds, a kind with no published
    unit, a unit the table cannot convert onto the published one's scale, and
    units that already *are* the published unit -- so a caller can fall
    through to the rules that handle those.  The conversion test matters: a
    flow stated in a unit no row arrived in is only honest where `units.json`
    itself joins the two, the way it joins the becquerel to the kilobecquerel
    and does not join a kilogram to a cubic metre.
    """
    rows = []
    for unit in units:
        row = unit_row_for(unit)
        if row is None:
            return None
        rows.append(row)
    kinds = {str(row.get("quantity_kind_iri") or "") for row in rows}
    if len(kinds) != 1:
        return None
    convention = published_units().get(next(iter(kinds)))
    if convention is None:
        return None
    stated = unit_row_for(convention.notation) or {}
    if all(row.get("iri") == stated.get("iri") for row in rows):
        return None
    if any(
        unit_table_factor(unit, convention.notation) is None for unit in units
    ):
        return None
    return convention.notation


@dataclass(frozen=True)
class CreatedFlowUnit:
    """The unit one created flow states, and where the answer came from."""

    #: Every distinct unit the rows landing on this flow offer, in row order.
    units: tuple[str, ...]
    #: The one the flow states.
    declared: str
    #: `curator`, `published_unit`, `unit_table`, or `unresolved`.
    decided_by: str

    @property
    def rows_disagree(self) -> bool:
        return len(self.units) > 1

    def to_dict(self) -> dict[str, Any]:
        return {
            "units": list(self.units),
            "declared": self.declared,
            "decided_by": self.decided_by,
        }


def decide_created_flow_unit(
    units: Sequence[str],
    *,
    source_uuids: Sequence[str] = (),
    decisions: dict[str, CreatedFlowUnitDecision] | None = None,
) -> CreatedFlowUnit:
    """Which unit a created flow states, given the units of its rows.

    *units* and *source_uuids* are parallel: the unit each row offers, and the
    row it came from, in the order the merge read them.  Duplicates in *units*
    are collapsed, first spelling kept.

    A single unit is not a decision and is reported as ``unit_table``: there was
    nothing to choose between.  The one exception is a lone unit whose quantity
    kind the list publishes in some other unit on the same scale -- a single
    becquerel row still mints a kilobecquerel flow, because the published unit
    is a statement about the list rather than an arbitration between rows.
    """
    ordered: list[str] = []
    uuid_by_unit: dict[str, str] = {}
    for index, unit in enumerate(units):
        unit = str(unit or "").strip()
        if not unit or unit in uuid_by_unit:
            continue
        ordered.append(unit)
        uuid_by_unit[unit] = (
            str(source_uuids[index]) if index < len(source_uuids) else ""
        )
    if not ordered:
        return CreatedFlowUnit((), "", DECIDED_BY_UNIT_TABLE)
    published = published_unit_for(ordered)
    if len(ordered) == 1:
        if published is not None:
            return CreatedFlowUnit(
                tuple(ordered), published, DECIDED_BY_PUBLISHED_UNIT
            )
        return CreatedFlowUnit(tuple(ordered), ordered[0], DECIDED_BY_UNIT_TABLE)

    for unit in ordered:
        uuid = uuid_by_unit.get(unit, "")
        if uuid and uuid in (decisions or {}):
            return CreatedFlowUnit(tuple(ordered), unit, DECIDED_BY_CURATOR)

    if published is not None:
        return CreatedFlowUnit(tuple(ordered), published, DECIDED_BY_PUBLISHED_UNIT)

    references = [unit for unit in ordered if is_a_reference_unit(unit)]
    if len(references) == 1:
        return CreatedFlowUnit(tuple(ordered), references[0], DECIDED_BY_UNIT_TABLE)

    return CreatedFlowUnit(tuple(ordered), ordered[0], UNDECIDED)
