"""Curated correspondence rows -- since #141, the correspondence itself.

This module grew up overriding somebody else's decisions: a vendor's
correspondence table said where each source flow belongs, most of its rows
were right, and a row here said "whatever the table says, this flow maps
*there*", with the reasoning that makes the assertion checkable.  The tables
are retired now and every manifest declares none, so the overrides are applied
onto an empty table and **are** the whole prepared correspondence -- a few
hundred rows, each one a written-down decision.  The mechanics below survive
unchanged, because "applied on top of whatever the table says" degrades
cleanly to "applied on top of nothing"; where a mechanism's meaning shifted
with the retirement, its own docstring says so.

A target here still cannot be repaired by editing the source data:
:mod:`brightway_flows.manual_fixes` names a field on a source flow and
says the vendor got it wrong, and a target uuid is not a field on the source
flow.

**One override set covers every version of a list.**  ecoinvent's flow uuids are
stable across releases -- ``Particulates, > 2.5 um, and < 10um`` in 3.8 and
``Particulate Matter, > 2.5 um and < 10um`` in 3.12 are the same uuid, the name
having gained and lost a comma -- so a decision about a flow is a decision about
that flow in every release that ships it.  The alternative, a file per version,
would have restated the same five rows five times and let them drift.

A row whose source uuid no version carries is inert rather than an error: ten
rows here name flows 3.9.1 onwards dropped, and a per-version file would only
have hidden that they were 3.8-specific.  (Inert is also how a misfiled row
fails, which review on #336 found the hard way: two rows naming *BAFU* uuids
sat in ecoinvent's file doing nothing while the build minted the duplicate
they existed to prevent.  A row belongs in the file of the list whose uuids it
names.)

**Where the premise fails, it fails visibly.**  A uuid naming the same flow in
every release is what lets one row decide for all of them, and ecoinvent breaks
it twice over: it renames flows, which is usually cosmetic, and it *renumbers*
them, which is not.  A renumbering is the vendor saying the flow is a different
substance -- 3.8's `Vanadium` 7440-62-2 and 3.12's `Vanadium V` 22537-31-1 share
thirteen uuids and are not the same thing -- and it is the one case where a row
written about one release must not reach another.  So a row that a renumbering
touches states which release it was written about, with
:attr:`MatchOverride.only_when_named`, or states the registrations the decision
was checked against, with :attr:`MatchOverride.carries_when_registered_as`.
Which of those two is right is not derivable: nine `Chromium` rows have exactly
the shape of the thirteen vanadium ones and the opposite answer.  What *is*
mechanical is the question -- ``tests/test_renumbered_flow_corrections.py`` asks
it of every row against every release on disk -- and what happens when a new
release asks it again, which is :func:`_refuse_unchecked_renumbering` (#109).

The converse is the point of the file.  The four `Carbon dioxide, to soil or
biomass stock` rows were written for 3.8 (#258), and 3.9.1 to 3.12 ship those
same uuids, in the same contexts, mapped by their published tables to the same
unqualified `carbon dioxide` 3.8's table mapped them to.  One file means the
decision reaches them without anybody restating it four times.

Applied by :func:`brightway_flows.sources.load_prepared_match_table`, onto
the empty table every manifest now declares; the appended rows are what reach
the merge.  (They used to be applied in a second place too -- the tool that
composed 3.8's table applied them, so the checked-in table showed the curated
choices in a reviewable diff.  Table and tool both live in git history now,
#141's last follow-up.)

A row may also state a **conversion factor** for its pair.  ecoinvent's three
`TiO2 ... in crude ore` flows map onto EF 3.1's elemental `titanium`; both sides
are in kilograms, so the units raise no objection, and mapping at parity would
credit an inventory with a kilogram of titanium for every kilogram of ore
dioxide extracted.  ecoinvent's own transitive table states 0.599 for that
substitution and the route this project takes does not, so the factor is stated
here rather than left to which route reaches the flow first.

**A factor does not reach every version the way a target does.**  It used to be
said that it did, by the same argument -- and the argument is about identity.  A
uuid names one flow in every release, so where that flow maps is one decision;
but how many megajoules a kilogram of it is, is a quantity somebody measured,
and a measurement has a vintage.  ecoinvent revised crude oil's lower heating
value from 42.3 to 43.4 MJ/kg at 3.9 following Meili et al. (2021) and rebuilt
its oil and gas datasets on the new number, so converting a 3.8 inventory with
43.4 uses a value that release never had.  The tell was in the file: the natural
gas row said ecoinvent respelled the unit at 3.9 "without restating any amount",
and the amount had been restated in that very release -- `source_unit` taking a
list of spellings, a statement about *units*, had been standing in for a
statement about *releases*, and for crude oil the two do not even coincide.

So a converting row states which releases its factor was checked against, with
:attr:`MatchOverride.conversion_checked_against`, and the releases that take
another number, with :attr:`MatchOverride.conversion_by_release`.  The row stays
one row: the target really is version-free, and splitting it per release would
restate hundreds of identity decisions and let them drift, which is what this
module already rejects about per-version override files.  A release named in
neither is refused rather than handed the default (#162).

A row may instead **decline** its prepared rows, with ``"decline": true`` and no
target.  A rewrite answers "this flow maps to the wrong place, send it *there*
instead"; a decline answers "this flow maps to the wrong place and the target
list has nowhere right to send it", which a rewrite cannot say because it must
name a ``target_uuid``.  The declined flow then reaches the merge looking like
a flow no decision mentions, and the addition path mints a consensus flow for
it.  The mechanism's great case was the tables' own rows -- EF 3.1 carries
`Trifloxystrobin` in agricultural soil and non-urban air and nowhere else, so
ecoinvent's table coarsened the two water flows into `Fungicides, unspecified`,
and declining them was what let one substance agree with itself across four
contexts (#206).  The 346 declines that existed to undo the tables went with the
tables (#141).  Four remain -- the `Carbon dioxide, to soil or biomass stock`
rows #334 wrote while the tables still shipped -- and with no table they
decline nothing: they stand as the written-down withdrawal of #258, and the
landing they argue for happens without them, through the qualifier rule of
#133.  Any new decline row is likewise documentary until a table exists again.

A row is read into a :class:`MatchOverride` at the file boundary, and the rest
of this module works from the record.  What it *writes* is a
correspondence-table row -- randonneur's shape, kept because everything
downstream of the loader still reads that shape -- built by the three
``override_*`` functions below.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import orjson
import structlog

from brightway_flows.domain.units import states_more_than_the_unit_table

logger = structlog.get_logger(__name__)

#: The shape of a registry number, for the numbers a row records having been
#: checked against.  Only the shape: these are read off a release rather than
#: typed from memory, so the mistake worth catching is a name or a uuid pasted
#: into the field, not a wrong check digit.
REGISTRY_NUMBER_RE = re.compile(r"^\d{2,7}-\d{2}-\d$")

#: What an override has to carry.  ``comment`` is not optional: every row here
#: asserts something the published table disagrees with, and an assertion with
#: no stated reasoning cannot be re-checked against the vendor's next release.
REQUIRED_FIELDS = ("source_uuid", "target_uuid", "comment")

#: What a ``decline`` row has to carry.  No ``target_uuid``: the whole point of
#: a decline is that there is no target to name.  ``comment`` stays mandatory
#: for the same reason it is mandatory on a rewrite -- declining a published row
#: is an assertion about the vendor's table, and one with no stated reasoning
#: cannot be re-checked against the next release.
DECLINE_FIELDS = ("source_uuid", "comment")

#: What a row stating a ``conversion_factor`` has to carry with it.  A factor is
#: a statement *between two units* -- 0.599 kilograms of titanium per kilogram
#: of titanium dioxide -- and a bare number cannot be checked against the pair
#: the merge finally builds, so the merge would decline to carry it anywhere.
CONVERSION_FIELDS = ("source_unit", "target_unit")

#: What a row stating a ``conversion_factor`` has to say about *when* it holds.
#: A target is an identity and an identity is the same in every release, which
#: is what lets one row decide for all of them.  A conversion factor is a
#: quantity somebody measured, and a measurement has a vintage: ecoinvent
#: revised crude oil's lower heating value from 42.3 to 43.4 MJ/kg at 3.9,
#: following Meili et al. (2021), and rebuilt its oil datasets on the new
#: number.  So the releases a factor has been checked against are stated, and a
#: release named by neither :attr:`MatchOverride.conversion_checked_against`
#: nor :attr:`MatchOverride.conversion_by_release` is refused rather than handed
#: the default -- the same discipline
#: :func:`_refuse_unchecked_renumbering` applies to a substance identity, for
#: the same reason (#162).
CONVERSION_SCOPE_FIELD = "conversion_checked_against"


@dataclass(frozen=True)
class MatchOverride:
    """One curated decision about where a correspondence table sends a flow.

    Either a **rewrite** -- the table sends this flow to the wrong place, send
    it to ``target_uuid`` instead -- or a **decline**, which says the table
    sends it to the wrong place and the target list has nowhere right to send
    it.  A decline is the one thing a rewrite cannot express, because a rewrite
    must name a target; see :attr:`decline`.

    ``source_context`` is read by nobody.  It is stated so that a curator
    reading the file can see which flow a row is about without looking the uuid
    up, and it is declared here rather than dropped so that the record says
    everything the file does.
    """

    source_uuid: str
    #: Not optional: every row here asserts something the published table
    #: disagrees with, and an assertion with no stated reasoning cannot be
    #: re-checked against the vendor's next release.
    comment: str
    source_name: str = ""
    source_context: tuple[str, ...] = ()
    target_uuid: str = ""
    target_name: str = ""
    target_context: tuple[str, ...] = ()
    #: This project's assertion about the pair the row makes, where the two
    #: sides are measured in different quantities.  ``None`` where the row makes
    #: none, which is not the same as ``1.0``: kilograms to kilograms at 1.0
    #: converts nothing, while `m2` to `m2*a` at 1.0 changes the quantity kind
    #: and is the whole point of the row.
    conversion_factor: float | None = None
    source_unit: str = ""
    #: Further spellings the vendor has used for the same flow's unit across
    #: releases.  ecoinvent registered natural gas in `m3` at 3.8 and `sm3`
    #: from 3.9.1 without restating any amount, so one factor holds for each
    #: spelling -- and a factor checked against only the newest spelling is
    #: silently dropped for the release that ships the older one, which is how
    #: 3.8's gas row lost its 36.0 MJ in the first cut of #141.  Stated in the
    #: file as a list under `source_unit`, first spelling first.
    source_unit_alternates: tuple[str, ...] = ()
    #: The releases :attr:`conversion_factor` has been checked against, as the
    #: versions their manifests declare -- `"3.9.1"`, `"2026-v1"`.  Mandatory on
    #: a row that states a factor and meaningless on one that does not.
    #:
    #: A target reaches every release by one argument -- a uuid names the same
    #: flow in all of them -- and a factor borrowed that argument without being
    #: entitled to it.  Where a flow maps is an identity; how many megajoules a
    #: kilogram of it is, is a measurement, and ecoinvent restates its
    #: measurements.  The tell was in the file already: the natural gas row said
    #: ecoinvent "respelled" the unit at 3.9 "without restating any amount", and
    #: ecoinvent had restated the amount in the same release.
    #:
    #: What a *new* release does is the point of recording it.  A release named
    #: here takes :attr:`conversion_factor`; one named in
    #: :attr:`conversion_by_release` takes the number stated there; one named in
    #: neither is refused, so that when 3.13 lands somebody opens the
    #: implementation report rather than inheriting a number by default.
    conversion_checked_against: tuple[str, ...] = ()
    #: The releases whose factor is *not* :attr:`conversion_factor`, and what it
    #: is for each, as pairs in file order.
    #:
    #: One row per flow, with the factor alone carrying the scope, rather than a
    #: row per release: the target genuinely is version-free, so splitting the
    #: row would restate an identity decision per release and let the copies
    #: drift -- which is what this module already rejects about per-version
    #: override files.
    #:
    #: A release may not appear both here and in
    #: :attr:`conversion_checked_against`; the two answer one question and a row
    #: that answers it twice has not decided.
    conversion_by_release: tuple[tuple[str, float], ...] = ()
    target_unit: str = ""
    #: This row's target is deliberately not the substance the row's stated
    #: registry number names, and the comment says why.  The audit
    #: (`tools/audit_prepared_correspondence.py`) refuses to pass a curated
    #: row that contradicts its own registry number unless the row signs the
    #: contradiction with this field -- an unsigned one is presumed a
    #: leftover.  The carbon rows are the founding case: ecoinvent registers
    #: its soot measure 7440-44-0, the element's number, and routing it to
    #: `Elemental Carbon` anyway is a decision #141 recorded.  A signature on
    #: a row that in fact agrees with its number is stale, and the audit
    #: fails on it just as it fails on an unsigned contradiction.
    not_the_stated_substance: bool = False

    #: Whether the row takes the table's answer away rather than replacing it.
    #:
    #: A decline says "whatever the table routes this flow to, take the row away
    #: and let the flow go through algorithmic matching like any flow the table
    #: never mentioned".  The case it exists for is a published row whose target
    #: is wrong *and* for which the target list has nothing right -- ecoinvent's
    #: `Trifloxystrobin` in water, which EF 3.1 carries in soil and air and
    #: nowhere else, so the table coarsens it to `Fungicides, unspecified`
    #: because it had no third option.
    #:
    #: Declining is not deleting the flow.  The merge's addition path already
    #: mints a specific consensus flow for a source row that matches nothing,
    #: and it already does so for these very substances in every context the
    #: table happens not to mention -- `Trifloxystrobin` in `water/unspecified`
    #: is published under its own name today while `water/surface water` is not.
    #: A decline makes that treatment a decision rather than an accident of
    #: which rows ecoinvent's table contains.
    decline: bool = False
    #: The names this decision was written about, where a uuid is *not* stable
    #: enough to carry it alone.  Absent -- which is the normal case and every
    #: row that predates #49 -- means "whatever the table calls this flow".
    #:
    #: The file's premise is that a flow uuid names the same flow in every
    #: release, so one row can decide for all of them.  Thirteen vanadium flows
    #: are the counter-example: ecoinvent 3.8 ships them as `Vanadium`
    #: (7440-62-2) and `Vanadium, ion` (22541-77-1), and 3.12 ships the *same
    #: thirteen uuids* as `Vanadium V` (22537-31-1). Three substances, one set
    #: of identifiers. A decision about where pentavalent vanadium belongs is
    #: not a decision about elemental vanadium, and applying it to 3.8 would
    #: move nine elemental-vanadium rows and four trivalent-ion rows onto a
    #: substance neither of them is.
    #:
    #: So a row may name the spellings it was written about, and is skipped
    #: where the table calls the flow something else.  Opt-in rather than
    #: enforced on every row, because most renames are cosmetic and must not
    #: cost a decision: `Particulates, > 2.5 um, and < 10um` became `Particulate
    #: Matter, > 2.5 um and < 10um` between the same two releases, and the four
    #: overrides about it are as true after the comma moved as before.
    #:
    #: Compared without regard to case and to surrounding space, because that
    #: is the part of a vendor's spelling that varies without meaning anything.
    only_when_named: tuple[str, ...] = ()
    #: The registry numbers this decision has been **checked against**, for a
    #: flow ecoinvent registers differently in different releases.  Absent --
    #: the normal case -- means nobody has had to ask, because every release
    #: that ships the flow registers it the same way.
    #:
    #: A rename is cosmetic often enough that :attr:`only_when_named` has to be
    #: opt-in.  A *renumbering* is not: it is the vendor saying the flow is a
    #: different substance, and the same shape has produced opposite answers
    #: nine rows apart.  ecoinvent 3.8 ships nine `Chromium` flows registered
    #: 7440-47-3 that 3.9.1 onwards ship as `Chromium III`, 16065-83-1, and the
    #: decision carries: 3.8 shipped a separate `Chromium VI` flow in those
    #: same nine contexts, so its unspeciated flow already meant trivalent.
    #: Thirteen vanadium flows have exactly that shape and the decision does
    #: *not* carry, which is what :attr:`only_when_named` is for.
    #:
    #: So the two fields answer one question -- does this decision reach that
    #: release -- and a row states one of them, never both.  A guard says no by
    #: construction; this says yes, and says what the yes was checked against.
    #:
    #: At least two numbers, because one records no renumbering: a row that
    #: means to reach only the releases spelling the flow one way is guarded by
    #: name instead.
    #:
    #: What a *new* release does is the point of recording it.  A release that
    #: registers the flow as none of these numbers is a release nobody has
    #: checked, and :func:`apply_match_overrides` refuses the row and names it
    #: rather than applying it and hoping.
    carries_when_registered_as: tuple[str, ...] = ()

    def applies_to(self, stated_name: str) -> bool:
        """Whether this row decides for a table row naming the flow *stated_name*."""
        if not self.only_when_named:
            return True
        wanted = {name.strip().lower() for name in self.only_when_named}
        return str(stated_name or "").strip().lower() in wanted

    def was_checked_against(self, registered_as: Sequence[str]) -> bool:
        """Whether *registered_as* is a registration this row was checked for.

        *registered_as* is what one release states for the flow, which is
        usually one number and occasionally none.

        **A release that states no number has not renumbered anything**, so it
        does not reopen the row.  Whole families of ecoinvent flows -- land
        occupations, water, energy carriers -- carry no registry number at all,
        and one that had a number and stopped stating it has said nothing about
        what the substance is.  This is the opposite of the reading
        :attr:`only_when_named` takes of a missing name, and deliberately: a
        correspondence row always names the flow, so a missing name there is an
        anomaly, while a missing registry number is ordinary.

        Any one number being among the checked ones is enough.  A release that
        renumbers a flow and keeps the old number beside the new one still
        registers it as something this row was checked for.
        """
        if not self.carries_when_registered_as:
            return True
        stated = {
            str(number).strip() for number in registered_as if str(number).strip()
        }
        return not stated or bool(stated & set(self.carries_when_registered_as))

    @property
    def converts(self) -> bool:
        """Whether the row states a conversion factor for its pair."""
        return self.conversion_factor is not None

    def covers_release(self, release: str) -> bool:
        """Whether this row's factor has been checked against *release*.

        True for a row that states no factor, which has nothing to check, and
        for any caller passing no release: the 3.8 composition and every caller
        with no list in hand ask nothing, exactly as they ask nothing of
        :meth:`was_checked_against`.
        """
        if not self.converts or not str(release or "").strip():
            return True
        wanted = str(release).strip()
        return wanted in self.conversion_checked_against or any(
            wanted == named for named, _ in self.conversion_by_release
        )

    def factor_for(self, release: str) -> float | None:
        """This row's conversion factor for *release*.

        The release's own number where the row states one, and
        :attr:`conversion_factor` otherwise.  ``None`` for a row that converts
        nothing.

        It does not refuse an unchecked release: resolving happens once per
        row while a table is being built, and refusing there would name the row
        without naming the release's other rows.  :func:`apply_match_overrides`
        asks :meth:`covers_release` of every row first, which is where the
        refusal reads like the one a curator has to act on.
        """
        if not self.converts:
            return None
        wanted = str(release or "").strip()
        for named, factor in self.conversion_by_release:
            if named == wanted:
                return factor
        return self.conversion_factor


def load_match_overrides(path: Path | None) -> list[MatchOverride]:
    """The override rows in *path*, validated.

    A missing path or a missing file is not an error: a list with no overrides
    is the normal state of every list.

    :raises ValueError: if the payload has no ``overrides`` list, if a row is
        missing any of :data:`REQUIRED_FIELDS`, if a row is still a placeholder,
        or if two rows claim the same source flow.  All four are authoring
        mistakes that would otherwise produce an override doing nothing, or two
        overrides silently taking turns.
    """
    if path is None or not path.exists():
        return []

    payload = orjson.loads(path.read_bytes())
    if not isinstance(payload, dict) or not isinstance(payload.get("overrides"), list):
        raise ValueError(f"{path.name} must contain an 'overrides' list.")

    rows = [row for row in payload["overrides"] if isinstance(row, dict)]
    overrides: list[MatchOverride] = []
    seen: dict[str, int] = {}
    for index, row in enumerate(rows):
        required = DECLINE_FIELDS if row.get("decline") else REQUIRED_FIELDS
        for field in required:
            if not str(row.get(field) or "").strip():
                raise ValueError(
                    f"Override {index} in {path.name} has no {field!r}. Every "
                    f"row here asserts something the published table does not, "
                    f"and that needs {', '.join(required)}."
                )
        _validate_decline(row, index=index, filename=path.name)
        _validate_signed_contradiction(row, index=index, filename=path.name)
        source_uuid = str(row["source_uuid"]).strip()
        if source_uuid.startswith("PLACEHOLDER"):
            # Refused rather than skipped.  An override with no source yet is a
            # decision nobody has made, and composing around it would quietly
            # assert the opposite of what the file says about that flow.
            raise ValueError(
                f"Override {index} in {path.name} is still a placeholder. Each "
                f"needs a source uuid read off the release and a target uuid "
                f"read off the target list."
            )
        if source_uuid in seen:
            raise ValueError(
                f"Overrides {seen[source_uuid]} and {index} in {path.name} both "
                f"claim {source_uuid}. One flow, one decision: two rows would "
                f"mean the last one read wins, which is not a decision anyone "
                f"made."
            )
        seen[source_uuid] = index
        _validate_conversion(row, index=index, filename=path.name)
        _validate_registry_check(row, index=index, filename=path.name)
        overrides.append(_as_override(row))
    return overrides


def _unit_spellings(value: Any) -> tuple[str, ...]:
    """The unit spellings a row states, primary first; `("",)` for none.

    A string is the ordinary single spelling.  A list is one flow whose unit
    the vendor has *respelled* across releases -- the same quantity under two
    names, so the factor is stated once and checked against whichever spelling
    the release at hand ships.  Not for two genuinely different units: a row
    that needs two factors is two decisions, and this field cannot hold two.
    """
    if isinstance(value, (list, tuple)):
        spellings = tuple(str(part or "").strip() for part in value)
        return spellings if spellings else ("",)
    return (str(value or "").strip(),)


def _as_override(row: dict[str, Any]) -> MatchOverride:
    """One validated row, as the record the rest of the module reads."""
    factor = row.get("conversion_factor")
    return MatchOverride(
        source_uuid=str(row["source_uuid"]).strip(),
        comment=str(row.get("comment") or ""),
        source_name=str(row.get("source_name") or ""),
        source_context=_context_parts(row.get("source_context")),
        target_uuid=str(row.get("target_uuid") or "").strip(),
        target_name=str(row.get("target_name") or ""),
        target_context=_context_parts(row.get("target_context")),
        conversion_factor=None if factor is None else float(factor),
        source_unit=_unit_spellings(row.get("source_unit"))[0],
        source_unit_alternates=_unit_spellings(row.get("source_unit"))[1:],
        conversion_checked_against=_releases(row.get("conversion_checked_against")),
        conversion_by_release=_releases_with_factors(row.get("conversion_by_release")),
        target_unit=str(row.get("target_unit") or "").strip(),
        decline=bool(row.get("decline")),
        not_the_stated_substance=bool(row.get("not_the_stated_substance")),
        only_when_named=_name_guard(row.get("only_when_named")),
        carries_when_registered_as=_registry_numbers(
            row.get("carries_when_registered_as")
        ),
    )


def _name_guard(value: Any) -> tuple[str, ...]:
    """The spellings a row was written about, as stated.

    A bare string is accepted as the one-name case, because a guard naming one
    spelling is what most of them will be and `["Vanadium V"]` reads worse than
    `"Vanadium V"` for no gain.
    """
    if isinstance(value, str):
        return (value,) if value.strip() else ()
    if not isinstance(value, list):
        return ()
    return tuple(str(part) for part in value if isinstance(part, str) and part.strip())


def _registry_numbers(value: Any) -> tuple[str, ...]:
    """The registry numbers a row records having been checked against.

    A list, always: unlike :func:`_name_guard` a bare string is not accepted,
    because one number records no renumbering and writing it as a bare string
    would make the mistake read like the ordinary case.
    """
    if not isinstance(value, list):
        return ()
    return tuple(
        str(part).strip()
        for part in value
        if isinstance(part, str) and part.strip()
    )


def _releases(value: Any) -> tuple[str, ...]:
    """The releases a row records having checked its factor against.

    A list, always.  Unlike :func:`_name_guard` a bare string is not accepted:
    one release is the ordinary state of a list with one version and reads
    perfectly well as `["2026-v1"]`, while a bare string would invite
    `"3.8, 3.9.1"` -- one string naming two releases, which this would read as
    a release nobody has.
    """
    if not isinstance(value, list):
        return ()
    return tuple(
        str(part).strip()
        for part in value
        if isinstance(part, str) and part.strip()
    )


def _releases_with_factors(value: Any) -> tuple[tuple[str, float], ...]:
    """The per-release factors a row states, as pairs in file order.

    Spelled in the file as an object keyed by release, because that is what it
    is -- `{"3.8": 42.3}` -- and held as pairs so the record stays hashable
    like every other field on it.
    """
    if not isinstance(value, dict):
        return ()
    return tuple(
        (str(release).strip(), float(factor))
        for release, factor in value.items()
        if str(release).strip() and isinstance(factor, (int, float))
        and not isinstance(factor, bool)
    )


def _context_parts(value: Any) -> tuple[str, ...]:
    """A stated context, as the list of display strings a table row carries."""
    if not isinstance(value, list):
        return ()
    return tuple(str(part) for part in value if isinstance(part, str) and part.strip())


def _validate_decline(row: dict[str, Any], *, index: int, filename: str) -> None:
    """Refuse a decline that also says where the flow goes.

    :raises ValueError: if ``decline`` is not a boolean, or if a declining row
        also carries a ``target_uuid`` or a ``conversion_factor``.  Both are
        contradictions rather than redundancies -- a row cannot both take the
        table's answer away and supply one, and a conversion is a statement
        about a pair this row declines to form.  Silently preferring one half
        would make the file's plain reading wrong.
    """
    if "decline" not in row:
        return
    if not isinstance(row["decline"], bool):
        raise ValueError(
            f"Override {index} in {filename} has a non-boolean 'decline'. It "
            f"says whether the published row is taken away, and only true or "
            f"false say that."
        )
    if not row["decline"]:
        return
    for field in ("target_uuid", "target_name", "target_context", "conversion_factor"):
        if row.get(field):
            raise ValueError(
                f"Override {index} in {filename} declines its prepared row and "
                f"also states {field!r}. A decline takes the table's answer "
                f"away and leaves the flow to algorithmic matching; a row that "
                f"names a target is a rewrite. Pick one."
            )


def _validate_signed_contradiction(
    row: dict[str, Any], *, index: int, filename: str
) -> None:
    """Refuse a signature that signs nothing.

    :raises ValueError: if the field is not a boolean, or if it is on a
        decline -- a decline names no substance, so there is no target to be
        deliberately different from the stated number.
    """
    if "not_the_stated_substance" not in row:
        return
    if not isinstance(row["not_the_stated_substance"], bool):
        raise ValueError(
            f"Override {index} in {filename} has a non-boolean "
            f"'not_the_stated_substance'. It signs a contradiction the row's "
            f"comment explains, and only true or false sign anything."
        )
    if row["not_the_stated_substance"] and row.get("decline"):
        raise ValueError(
            f"Override {index} in {filename} declines its prepared row and "
            f"signs 'not_the_stated_substance'. A decline names no substance, "
            f"so there is nothing here to be deliberately different from the "
            f"stated number."
        )


def _validate_registry_check(row: dict[str, Any], *, index: int, filename: str) -> None:
    """Refuse a renumbering check that records nothing checkable.

    :raises ValueError: if the field is not a list of registry numbers, if it
        names fewer than two, or if the row is also guarded by
        ``only_when_named``.  All three are the same authoring mistake in
        different clothes -- a record of a check that cannot be re-asked when
        the next release lands.  One number spans no renumbering, and a row
        with both fields has answered "does this decision reach that release"
        twice, once yes and once no.
    """
    if "carries_when_registered_as" not in row:
        return
    stated = row["carries_when_registered_as"]
    if not isinstance(stated, list) or not all(isinstance(p, str) for p in stated):
        raise ValueError(
            f"Override {index} in {filename} states "
            f"'carries_when_registered_as' as {stated!r}. It is the list of "
            f"registry numbers this decision has been checked against, read "
            f"off the releases that ship the flow."
        )
    numbers = _registry_numbers(stated)
    for number in numbers:
        if not REGISTRY_NUMBER_RE.match(number):
            raise ValueError(
                f"Override {index} in {filename} records having been checked "
                f"against {number!r}, which is not a registry number. These "
                f"are read off the releases, so a name or a uuid here means "
                f"the wrong field was copied."
            )
    if len(set(numbers)) < 2:
        raise ValueError(
            f"Override {index} in {filename} records having been checked "
            f"against {list(numbers)}. Two or more, or none: one number spans "
            f"no renumbering, and a decision that means to reach only the "
            f"releases spelling the flow one way is guarded with "
            f"'only_when_named' instead."
        )
    if row.get("only_when_named"):
        raise ValueError(
            f"Override {index} in {filename} is guarded with 'only_when_named' "
            f"and also records having been checked against "
            f"{list(numbers)}. Both answer whether this decision reaches a "
            f"release, and the guard already answers no. Pick one."
        )


def _validate_conversion(row: dict[str, Any], *, index: int, filename: str) -> None:
    """Refuse a conversion factor that could not be carried anywhere.

    :raises ValueError: if the factor is not a number, if either unit it is
        stated between is missing, if `units.json` already states it -- the
        "converts nothing" case, which is not the same as "is 1.0": kilograms
        to kilograms at 1.0 converts nothing, while `m2` to `m2*a` at 1.0
        changes the quantity kind and is the whole point of the row -- or if
        the row does not say which releases the factor was checked against.

    Every per-release factor is checked the way the scalar is, against the same
    unit pair: a release's own number is the same kind of assertion as the
    default, and one that `units.json` already implies converts nothing there
    either.
    """
    if "conversion_factor" not in row:
        _refuse_orphan_conversion_scope(row, index=index, filename=filename)
        return
    factor = row["conversion_factor"]
    if isinstance(factor, bool) or not isinstance(factor, (int, float)):
        raise ValueError(
            f"Override {index} in {filename} has a non-numeric "
            f"'conversion_factor'."
        )
    for field in CONVERSION_FIELDS:
        if not str(row.get(field) or "").strip():
            raise ValueError(
                f"Override {index} in {filename} states a 'conversion_factor' "
                f"with no {field!r}. A factor is a statement between two units, "
                f"and the merge will not carry one it cannot check against the "
                f"pair it builds."
            )
    target_unit = str(row["target_unit"]).strip()
    for source_unit in _unit_spellings(row["source_unit"]):
        if not source_unit:
            raise ValueError(
                f"Override {index} in {filename} states an empty spelling "
                f"under 'source_unit'. Each spelling is a unit the factor is "
                f"checked against, and an empty one can never be."
            )
        if not states_more_than_the_unit_table(
            source_unit, target_unit, float(factor)
        ):
            raise ValueError(
                f"Override {index} in {filename} states a 'conversion_factor' of "
                f"{factor} from {source_unit!r} to {target_unit!r}, which is what "
                f"units.json already converts them by. Omit it: a second copy of a "
                f"fact that has a home is one that can disagree with it."
            )
    _validate_conversion_scope(row, index=index, filename=filename)


def _validate_conversion_scope(
    row: dict[str, Any], *, index: int, filename: str
) -> None:
    """Refuse a factor that does not say which releases it was checked against.

    :raises ValueError: if the row names no release, if ``conversion_by_release``
        is not an object of release to number, if a per-release factor is one
        `units.json` already implies, or if one release is named on both sides.
    """
    checked = row.get(CONVERSION_SCOPE_FIELD)
    if not isinstance(checked, list) or not _releases(checked):
        raise ValueError(
            f"Override {index} in {filename} states a 'conversion_factor' and "
            f"no {CONVERSION_SCOPE_FIELD!r}. A target reaches every release "
            f"because a uuid names one flow in all of them; a heating value is "
            f"a measurement and ecoinvent restates its measurements -- crude "
            f"oil went from 42.3 to 43.4 MJ/kg at 3.9. Name the releases this "
            f"number was checked against, as a list of the versions their "
            f"manifests declare."
        )

    by_release = row.get("conversion_by_release")
    if by_release is None:
        return
    if not isinstance(by_release, dict):
        raise ValueError(
            f"Override {index} in {filename} has a 'conversion_by_release' that "
            f"is not an object. It maps a release to the factor that release "
            f"takes, as {{\"3.8\": 42.3}}."
        )

    target_unit = str(row["target_unit"]).strip()
    spellings = _unit_spellings(row["source_unit"])
    for release, factor in by_release.items():
        named = str(release or "").strip()
        if not named:
            raise ValueError(
                f"Override {index} in {filename} states a factor under an empty "
                f"release in 'conversion_by_release'. A factor that names no "
                f"release reaches none."
            )
        if isinstance(factor, bool) or not isinstance(factor, (int, float)):
            raise ValueError(
                f"Override {index} in {filename} states a non-numeric factor "
                f"for release {named!r} in 'conversion_by_release'."
            )
        if named in _releases(checked):
            raise ValueError(
                f"Override {index} in {filename} names release {named!r} in "
                f"both {CONVERSION_SCOPE_FIELD!r} and 'conversion_by_release'. "
                f"The first says the release takes the default factor and the "
                f"second says it takes another; a row that says both has not "
                f"decided which number that release converts by."
            )
        for source_unit in spellings:
            if not states_more_than_the_unit_table(
                source_unit, target_unit, float(factor)
            ):
                raise ValueError(
                    f"Override {index} in {filename} states {factor} from "
                    f"{source_unit!r} to {target_unit!r} for release {named!r}, "
                    f"which is what units.json already converts them by. A "
                    f"release's own number is the same kind of assertion as the "
                    f"default and is refused for the same reason."
                )


def _refuse_orphan_conversion_scope(
    row: dict[str, Any], *, index: int, filename: str
) -> None:
    """Refuse a release scope on a row that converts nothing.

    :raises ValueError: if a row with no ``conversion_factor`` states either
        scope field.  Both describe when a factor holds, and a row with no
        factor has nothing for them to be about -- most likely the factor was
        removed and its scope left behind, which reads like a decision and is
        not one.
    """
    for field in (CONVERSION_SCOPE_FIELD, "conversion_by_release"):
        if row.get(field):
            raise ValueError(
                f"Override {index} in {filename} states {field!r} and no "
                f"'conversion_factor'. That field says when a factor holds, and "
                f"this row states no factor for it to be about."
            )


def _row_source_uuid(row: Any) -> str:
    """The source uuid of a correspondence row.

    ``replace`` rows spell it ``uuid``; ``update`` rows spell it ``identifier``.
    Reading only one silently matches nothing on half the tables.
    """
    if not isinstance(row, dict):
        return ""
    side = row.get("source")
    if not isinstance(side, dict):
        return ""
    return str(side.get("uuid") or side.get("identifier") or "").strip()


def _row_source_name(row: Any) -> str:
    """What a correspondence row calls the flow it is about.

    Read only by :attr:`MatchOverride.only_when_named`, which is the one place
    a vendor's spelling decides anything here.  Empty for a row that states no
    name, which a guarded override then does not apply to -- the guard asks
    whether the table names the flow the way the decision was written about,
    and a table that names it nothing has not answered yes.
    """
    if not isinstance(row, dict):
        return ""
    side = row.get("source")
    if not isinstance(side, dict):
        return ""
    return str(side.get("name") or "")


def override_target_side(override: MatchOverride) -> dict[str, Any]:
    """The override's target, as a correspondence row's target object.

    The table's own target object is discarded rather than updated in place: its
    ``context`` describes the flow the table chose, and carrying it onto a
    different flow would publish a context nobody checked.  The override's own
    ``target_context`` is carried through where it states one, and omitted
    otherwise rather than emitted empty -- an empty list would read as "the
    target list gives this flow no context", which is a different claim from
    "this row does not say".

    No consumer reads it: the merge takes the target's context from the
    consensus flow it resolves to, never from the correspondence row
    (`merge/prepared.py`).  It is there so a curated row in the composed 3.8
    table reads like the route A and route B rows beside it (#258).

    Public since the days when the 3.8-table composer built the same object;
    the composer is git history now (#141), and what keeps this the one
    spelling of "what an override's target looks like" is that every appended
    row goes through it.
    """
    target: dict[str, Any] = {
        "uuid": override.target_uuid,
        "name": override.target_name,
    }
    if override.target_context:
        target["context"] = list(override.target_context)
    if override.converts:
        # Under the name the correspondence tables use, so the row the merge
        # reads looks the same whichever of the two produced it.
        target["unit_name"] = override.target_unit
    return target


def override_row_extras(
    override: MatchOverride, *, release: str = ""
) -> dict[str, Any]:
    """The row fields beyond the target that an override sets, if any.

    A conversion, and the name guard.  Kept apart from the target because a
    factor is a statement about the *pair*, and the table spells it as a
    sibling of `target` rather than a field inside it.

    The factor written is the one *release* takes, which is the row's default
    unless the row states another for it.  Only the resolved number travels:
    everything downstream reads a correspondence row, where a factor is one
    number for the pair in hand, and a release is not something the merge would
    know to ask again.  A caller naming no release gets the default, which is
    what the callers holding no list want.

    The guard travels because appending is where it stopped meaning anything:
    with every prepared table retired the append loop has no table row whose
    stated name it could check, so every guarded override reaches every
    release, and the check has to happen where the release's own row is in
    hand -- the merge, via :func:`admitted_prepared_rows`.  Found by review
    on #336.
    """
    extras: dict[str, Any] = {}
    if override.converts:
        extras["conversion_factor"] = override.factor_for(release)
    if override.only_when_named:
        extras["only_when_named"] = list(override.only_when_named)
    return extras


def admitted_prepared_rows(
    prepared_rows: list[dict[str, Any]], *, row_name: str
) -> list[dict[str, Any]]:
    """The prepared rows whose name guard admits a row named *row_name*.

    A row carrying no ``only_when_named`` is admitted -- the ordinary case.
    One carrying the guard was written about specific spellings, and a release
    whose flow answers to none of them is a release the decision was not
    written about: the row is withheld and the flow goes through ordinary
    matching, exactly as it would have when the guard was checked against a
    table row's stated name.

    *row_name* is the name the merge is matching on, which under the
    element/ion rule is the canonical identity's -- so a guard naming the
    vendor's newest spelling admits every release of that uuid, older
    spellings included, without widening to any other substance.
    """
    admitted = []
    for item in prepared_rows:
        guard = item.get("only_when_named")
        if isinstance(guard, str):
            guard = [guard]
        if not isinstance(guard, list) or not guard:
            admitted.append(item)
            continue
        wanted = {str(name or "").strip().lower() for name in guard}
        wanted.discard("")
        if str(row_name or "").strip().lower() in wanted:
            admitted.append(item)
    return admitted


def override_source_side(override: MatchOverride) -> dict[str, Any]:
    """The source object for a row appended for an override the table omits.

    Carries the unit only where the override states a conversion: that is the
    one case where a consumer reads it, and inventing one elsewhere would put a
    unit nobody checked on a row that does not need it.
    """
    source: dict[str, Any] = {
        "uuid": override.source_uuid,
        "name": override.source_name,
    }
    if override.converts:
        source["unit"] = override.source_unit
        if override.source_unit_alternates:
            # The other spellings the vendor has used for this unit, so the
            # factor still holds for a release shipping an older one -- see
            # `MatchOverride.source_unit_alternates`.
            source["unit_alternates"] = list(override.source_unit_alternates)
    return source


def _refuse_unchecked_renumbering(
    by_source: dict[str, MatchOverride],
    *,
    registered_as: Mapping[str, Sequence[str]] | None,
    path: Path | None,
    label: str,
) -> None:
    """Refuse a row this release has renumbered out from under.

    A row records the registry numbers it was checked against precisely so that
    the question can be re-asked, and this is where it is re-asked: a release
    that registers the flow as none of them is a release nobody has looked at.

    Raised rather than skipped, and the contrast with ``only_when_named`` is
    the reason.  A guard is a *decision* -- this correction is not about that
    release -- so skipping it carries the decision out.  A number nobody has
    seen before is an *unanswered question*, and there is no answer to carry
    out: applying the row asserts a substance identity nobody checked, and
    skipping it publishes whatever the vendor's table said, equally unchecked.
    Refusing names the row that has to be re-read, which is the only thing here
    a person can act on.

    :raises ValueError: naming the flow, what it was checked against and what
        this release registers it as.
    """
    if not registered_as:
        return
    for source_uuid, override in by_source.items():
        if not override.carries_when_registered_as:
            continue
        stated = [
            str(number).strip()
            for number in registered_as.get(source_uuid, ())
            if str(number).strip()
        ]
        if override.was_checked_against(stated):
            continue
        name = override.source_name or source_uuid
        raise ValueError(
            f"{label or 'This release'} registers {name} ({source_uuid}) as "
            f"{', '.join(sorted(stated))}, and the override for it in "
            f"{path.name if path else 'the overrides file'} was checked "
            f"against {', '.join(override.carries_when_registered_as)}. A "
            f"registry number nobody has seen before is ecoinvent saying this "
            f"is a different substance, which is what happened to thirteen "
            f"vanadium flows between 3.8 and 3.12. Re-read the row against "
            f"this release: add the number if the decision still holds, or "
            f"guard the row with 'only_when_named' if it does not."
        )


def _refuse_unchecked_conversion(
    by_source: dict[str, MatchOverride],
    *,
    release: str,
    path: Path | None,
    label: str,
) -> None:
    """Refuse a factor nobody has checked against this release.

    The twin of :func:`_refuse_unchecked_renumbering`, and it is a twin because
    the two questions are the same one asked of the two halves of a row.  A
    renumbering asks whether this release still means the substance the row's
    *target* was written about.  This asks whether it still measures the
    substance the way the row's *factor* was written about.  Both are the
    vendor changing something under a decision, and neither is answerable by
    the file alone.

    Raised rather than defaulted, for the reason its twin is raised rather than
    skipped: a release nobody has checked is an unanswered question, and both
    ways of proceeding answer it silently.  Applying the default publishes a
    number for a release nobody compared it against -- which is how ecoinvent
    3.8's oil chains came to be converted at 43.4 MJ/kg, a value that release
    never used, and scored 2.6% high.  Refusing names the row to re-read.

    :raises ValueError: naming the release, the flow and what the row was
        checked against.
    """
    if not str(release or "").strip():
        return
    for source_uuid, override in by_source.items():
        if override.covers_release(release):
            continue
        name = override.source_name or source_uuid
        checked = ", ".join(
            [*override.conversion_checked_against]
            + [named for named, _ in override.conversion_by_release]
        )
        raise ValueError(
            f"{label or 'This release'} is {release}, and the conversion for "
            f"{name} ({source_uuid}) in "
            f"{path.name if path else 'the overrides file'} was checked "
            f"against {checked}. A factor is a measurement and a measurement "
            f"has a vintage: ecoinvent revised crude oil from 42.3 to 43.4 "
            f"MJ/kg at 3.9 and rebuilt its oil datasets on it. Read this "
            f"release's implementation report: add {release} to "
            f"'{CONVERSION_SCOPE_FIELD}' if the number holds, or state the "
            f"release's own number under 'conversion_by_release' if it does not."
        )


def apply_match_overrides(
    rows: list[Any],
    path: Path | None,
    *,
    label: str = "",
    release: str = "",
    registered_as: Mapping[str, Sequence[str]] | None = None,
) -> list[Any]:
    """*rows*, with the overrides in *path* applied.

    Returns a new list; *rows* is not mutated.

    *registered_as* is what this release registers each of its flows as, by
    uuid, and is how a row that records a renumbering check is re-asked when a
    new release lands; see :func:`_refuse_unchecked_renumbering`.  ``None`` --
    which is what the 3.8 composition and every caller with no flows in hand
    passes -- asks nothing, because there is nothing to ask it of.

    *release* is the version of the list being built, as its manifest declares
    it, and does the same for a curated *conversion*: it selects the factor the
    release takes, and refuses a row no one has checked against it.  Empty asks
    nothing, for the same reason ``registered_as`` of ``None`` asks nothing.

    An override rewrites the target of every row for its source flow.  Every
    row, not the first: the merge refuses a source flow whose prepared rows
    disagree on a target, so leaving one behind would turn a curated decision
    into an unmatched row.

    An override whose source flow the table has no row for is **appended**.  A
    table can simply omit a flow -- the 3.8 table is composed and omits every
    flow no route reaches -- and an override that silently did nothing there
    would leave the flow to algorithmic matching while the file said otherwise.
    A row appended for a flow the source list does not carry is inert: the merge
    walks the source flows and looks each one up here.

    A row carrying ``only_when_named`` is skipped where the table calls the flow
    something else -- and skipped completely, so it is not appended either.
    That guard exists because a uuid is not always stable enough to carry a
    decision: ecoinvent ships thirteen uuids as `Vanadium` and `Vanadium, ion`
    in 3.8 and as `Vanadium V` in 3.12, and a decision about pentavalent
    vanadium must not reach the release where those flows are the element.  See
    :attr:`MatchOverride.only_when_named`.
    """
    overrides = load_match_overrides(path)
    if not overrides:
        return list(rows)

    by_source = {override.source_uuid: override for override in overrides}
    _refuse_unchecked_renumbering(
        by_source, registered_as=registered_as, path=path, label=label,
    )
    _refuse_unchecked_conversion(
        by_source, release=release, path=path, label=label,
    )
    applied: dict[str, int] = {uuid: 0 for uuid in by_source}
    #: Rows whose guard the table's own naming did not satisfy.  Counted so the
    #: log says a row was *declined by its guard* rather than leaving it
    #: indistinguishable from a row for a flow this version does not ship.
    skipped: set[str] = set()

    result: list[Any] = []
    declined = 0
    for row in rows:
        override = by_source.get(_row_source_uuid(row))
        if override is None:
            result.append(row)
            continue
        if not override.applies_to(_row_source_name(row)):
            skipped.add(override.source_uuid)
            result.append(row)
            continue
        if override.decline:
            # Dropped, not rewritten to nothing: the merge keys prepared rows by
            # source uuid, so a row left behind with an empty target would be a
            # decision that resolves to no flow rather than the absence of one.
            applied[override.source_uuid] += 1
            declined += 1
            continue
        rewritten = {
            **row,
            "target": override_target_side(override),
            **override_row_extras(override, release=release),
            "comment": override.comment,
            "route": "override",
        }
        if not override.converts:
            # A redirected pair re-earns its factor.  A conversion is a
            # statement about a pair of flows, so rewriting the target leaves
            # whatever the table stated describing a mapping that no longer
            # exists: 36 MJ per standard cubic metre was the price of pointing
            # ecoinvent's coal-mine off-gas at an energy-accounted natural gas
            # flow, and it says nothing whatever about EF 3.1's coal-mine flow
            # the override sends it to instead (#80).  Inherited, it survived
            # as a bare number beside a target with no unit on it at all,
            # which `conversion_from_prepared_rows` published.
            #
            # An override that means to keep a conversion states one, with the
            # two units it holds between -- and then it is this project's
            # assertion about the pair it actually made.
            rewritten.pop("conversion_factor", None)
        result.append(rewritten)
        applied[override.source_uuid] += 1

    appended = 0
    for source_uuid, override in by_source.items():
        if source_uuid in skipped:
            # Its guard said this release is not the one the decision was
            # written about, and appending the row would be that decision
            # arriving by the other door.
            continue
        if applied[source_uuid] or override.decline:
            # A decline is never appended.  Appending exists so a rewrite
            # reaches a flow the table omits; a decline for a flow the table
            # omits has already got what it asked for, and inventing a row to
            # express that would be a row saying nothing.
            continue
        result.append({
            "source": override_source_side(override),
            "target": override_target_side(override),
            **override_row_extras(override, release=release),
            "comment": override.comment,
            "route": "override",
        })
        appended += 1

    logger.info(
        "match_overrides_applied",
        source=label,
        path=str(path),
        total=len(overrides),
        rewritten=sum(applied.values()) - declined,
        declined=declined,
        appended=appended,
        skipped_by_name_guard=len(skipped),
    )
    return result
