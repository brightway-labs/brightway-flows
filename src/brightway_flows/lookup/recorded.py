"""Tier one: the decision a build already made about this exact row.

The algorithm is a re-derivation.  Where a build has already decided a row, the
decision itself is better evidence than deriving it again -- it is exact, it is
instant, and it includes the curated ones the algorithm would not reproduce.  On
the 21 August 2026 build that is 11,974 prepared matches and 1,232 prepared
mappings the correspondence tables settled, which the algorithm on its own
reaches 92.8% and 93.6% of.

Two ways in, and they are not the same kind of claim.

**By identifier.**  The caller says which list their row came from and what its
identifier is in that list.  ``elementary_flow_sources`` is the join: 110,993
links on that build, covering all four merged lists *including EF 3.1 itself*,
so a caller holding the base list gets an exact answer for all 94,040 of its
rows.  This is not a guess of any kind -- the row is the row -- and it is on by
default.

**By name and medium.**  A row of a caller's list may be spelled identically to
a row of a list already merged, in the same place, in which case the decision
has been made and reviewed.  The key is the name and the *resolved* consensus
context, not the source's spelling of its compartment (#357): keyed on
spellings, BAFU's ``["resources", "in air"]`` and ecoinvent's ``["natural
resource", "in air"]`` were different keys for the same place, and a caller
writing either got nothing recorded under their own -- so the tier answered
only a caller who happened to spell a compartment exactly as some merged list
had.  The build writes the resolved context into every match record
(``detail_json``'s ``source_context_iri``; the prepared kind gained the field
in #361).  A record from before the field existed is resolved here through the
same rules a build resolves with -- and so is a record whose field is present
but empty, because the build itself could resolve no place for that row.  Only
the former counts as a fallback, because only it goes away when the build is
remade.  Rows the merge did not place are not decisions and are not read at
all, whatever their columns carry.

A key two rows disagree about **declines rather than arbitrates**, at every
rung.  On the 1 September 2026 build, 15,757 distinct ``(name, resolved
context)`` keys hold one recorded flow and **42 hold two** -- and most of what
a name-level count calls a collision is not one: ``carbon dioxide`` reaches
eight flows by name and one per place.  The ladder loosens only where the
caller said less -- a caller who resolved to a context is answered at that
context or handed to the algorithm; one who named only a dimension is answered
where every recorded row of that dimension agrees; one whose compartment could
not be read at all is answered only where the name has one recorded flow
everywhere.

The one exception to declining is the caller who has *said which list they
mean* (#359).  ``Carbon dioxide`` in unspecified air is fossil to BAFU and
Stepwise and land-use change to ecoinvent -- ecoinvent spells fossil out and
qualifies this variant by uuid alone -- and no rule derives an answer.  But a
caller whose ``source_label`` names a merged list has supplied the missing
fact, so the named list's own recorded decision is used, reported as such,
with the competing flows listed beside it.  34 of the 43 disagreements are
settleable that way.

It is **off by default**, and §8 of ``plans/lookup-api.md`` leaves the default
open.  The residual objection is the one no measurement answers: a name a third
list spells the same and means differently is not in this build to be counted.
So the default stays off, and a caller who turns it on gets `tier` saying so on
every answer it produced.
"""

from __future__ import annotations

import sqlite3

from dataclasses import dataclass
from functools import cached_property, lru_cache
from pathlib import Path
from typing import NamedTuple

import orjson
import structlog

from brightway_flows.context_mapping import (
    consensus_context_strings,
    normalize_mapping_text,
)
from brightway_flows.merge.store import Outcome

logger = structlog.get_logger(__name__)

#: The whole-name rung of the name index: what is recorded under a name
#: anywhere at all, which is all a caller whose compartment could not be read
#: has asked about.
_NAME_RUNG = ""

#: The outcomes that are decisions.  `merge_outcomes` also stores what the
#: merge refused -- and two refusal paths (a prepared target that no longer
#: exists, a context contradiction) fill `target_elementary_flow_id` with the
#: flow they refused, so the target column alone cannot say "this row was
#: placed".  The outcome column can.
_MATCHED_OUTCOMES = tuple(
    outcome.value for outcome in Outcome if outcome is not Outcome.UNMATCHED
)

#: A caller's list and row identifier, normalised.  The list key is the one a
#: `SourceList` publishes -- `ecoinvent-3.12`, `bafu-2026-v1`, `EF-3.1` -- which
#: is `list_name` and `list_version` joined, and is how `elementary_flow_sources`
#: stores them apart.
IdentifierKey = tuple[str, str]


@dataclass(frozen=True)
class RecordedDecision:
    """What a build decided about one source row, and which row that was."""

    elementary_flow_id: str
    list_name: str
    list_version: str
    source_flow_uuid: str = ""
    source_flow_name: str = ""

    @property
    def list_key(self) -> str:
        return f"{self.list_name}-{self.list_version}"


@dataclass(frozen=True)
class RecordedNameAnswer:
    """What the name index found at the rung the caller's compartment reaches.

    *decision* is the answer.  *arbitrated_by* names the list whose recorded
    ruling was preferred because the caller's ``source_label`` named it (#359),
    and is empty for the ordinary unanimous answer; where it is set,
    *alternatives* holds the competing flows, so a caller can see what the
    other lists said.  A rung nothing arbitrates is not an answer at all --
    :meth:`RecordedDecisions.for_name_in_context` returns ``None`` and the
    matcher re-derives, as it does for a name never recorded.
    """

    decision: RecordedDecision
    arbitrated_by: str = ""
    alternatives: tuple[str, ...] = ()


def _collapsed(text: str) -> str:
    """*text* normalised with the hyphen/space difference collapsed."""
    return normalize_mapping_text(text).replace(" ", "-")


@lru_cache(maxsize=None)
def _labelled_list_keys(source_label: str) -> frozenset[str]:
    """The registered list keys *source_label* names, or empty for none.

    **The one acceptor of a caller's label.**  A registered list is reachable
    by any of the three spellings a caller plausibly holds -- its key
    (``EF-3.1``), its bare list name (``stepwise``), or the ``source_label``
    its published flows carry (``EF 3.1``) -- so the same spelling that steers
    compartment resolution also settles recorded ties, rather than two private
    recognisers drifting apart.  A bare name spanning versions returns every
    version's key; arbitration still requires one target among everything the
    label reaches, so the versions agree or decline together.
    """
    from brightway_flows.sources import base_source_list, known_source_lists

    label = _collapsed(source_label)
    if not label:
        return frozenset()
    keys = {
        source.key
        for source in (base_source_list(), *known_source_lists().values())
        if label
        in (
            _collapsed(source.key),
            _collapsed(source.list_name),
            _collapsed(source.source_label),
        )
    }
    return frozenset(keys)


def _list_label_matches(decision: RecordedDecision, source_label: str) -> bool:
    """Whether *source_label* names the list *decision* was recorded from.

    Resolved through the registry (:func:`_labelled_list_keys`) so a caller
    holding any registered spelling reaches the recorded ``list_key`` exactly.
    A label the registry does not know falls back to comparing against the
    decision itself with the hyphen/space difference collapsed, so a build of
    lists the registry has never heard of -- a test fixture, a fork -- keeps
    working.
    """
    keys = _labelled_list_keys(source_label)
    if keys:
        return decision.list_key in keys
    label = _collapsed(source_label)
    return label in (
        _collapsed(decision.list_key),
        _collapsed(decision.list_name),
    )


def _registered_source_label(list_key: str) -> str:
    """The label *list_key*'s own mapping rules answer to, or the key itself.

    A recorded row's ``list_key`` and the label its compartment rules are
    registered under can differ in spelling -- the base list's key is
    ``EF-3.1`` and its rules say ``EF 3.1`` -- and ``resolve_context`` accepts
    only the registered spelling.  Passing the key raw would silently skip the
    list's own rules and resolve the row under the generic ones.
    """
    from brightway_flows.sources import base_source_list, known_source_lists

    base = base_source_list()
    if list_key == base.key:
        return base.source_label
    source = known_source_lists().get(list_key)
    return source.source_label if source is not None else list_key


def split_list_key(list_key: str) -> tuple[str, str]:
    """``ecoinvent-3.12`` into ``("ecoinvent", "3.12")``.

    Split on the *last* hyphen, because a list name may contain one -- BAFU's
    version is ``2026-v1``, so ``bafu-2026-v1`` has two -- and it is the version
    that is unhyphenated at its start.  Wrong for a hypothetical list whose
    version has no hyphen and whose name has two, and right for every list this
    project has; the lookup below is exact, so a mis-split simply finds nothing
    rather than finding the wrong thing.
    """
    key = list_key.strip()
    if "-" not in key:
        return key, ""
    name, _, version = key.partition("-")
    return name, version


class _NameIndex(NamedTuple):
    """What one walk of ``merge_outcomes`` builds, kept together because the
    count is a fact about the walk -- it cannot be derived from the finished
    index, so returning it beside the index is what keeps it from living in
    mutable instance state a refactor could silently orphan."""

    index: dict[tuple[str, str], tuple[RecordedDecision, ...]]
    resolved_without_recorded_context: int


class RecordedDecisions:
    """Every decision a build recorded, indexed two ways, built on first use.

    Lazy on purpose.  The identifier index is 110,993 entries and the name index
    walks 16,953 outcome rows, and a caller who asks neither question should pay
    for neither.  `cached_property` is the whole of it: the first question builds
    the index it needs and every question after that is a dictionary lookup.
    """

    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(f"file:{self._db_path}?mode=ro", uri=True)

    @cached_property
    def _by_identifier(self) -> dict[IdentifierKey, tuple[RecordedDecision, ...]]:
        """``(list key, source uuid) -> the flows that row reached``.

        A tuple rather than a single decision because a source row *can* reach
        two consensus flows -- 47 of the 110,993 links do, where one vendor row
        was mapped onto two flows -- and a tier that returned the first would be
        choosing between two recorded decisions by row order, which is the thing
        this project keeps removing.
        """
        index: dict[IdentifierKey, list[RecordedDecision]] = {}
        connection = self._connect()
        try:
            rows = connection.execute(
                "SELECT list_name, list_version, source_flow_uuid, "
                "elementary_flow_uuid, source_flow_name "
                "FROM elementary_flow_sources "
                "WHERE source_flow_uuid IS NOT NULL AND source_flow_uuid != '' "
                "ORDER BY id"
            ).fetchall()
        finally:
            connection.close()
        for list_name, list_version, source_uuid, flow_uuid, source_name in rows:
            key = (f"{list_name}-{list_version}", str(source_uuid).strip())
            index.setdefault(key, []).append(
                RecordedDecision(
                    elementary_flow_id=str(flow_uuid or ""),
                    list_name=str(list_name or ""),
                    list_version=str(list_version or ""),
                    source_flow_uuid=str(source_uuid or ""),
                    source_flow_name=str(source_name or ""),
                )
            )
        logger.info("lookup_recorded_identifier_index", links=len(rows), keys=len(index))
        return {key: tuple(values) for key, values in index.items()}

    @cached_property
    def _name_index(self) -> _NameIndex:
        """``(normalised name, rung) -> the distinct decisions recorded there``.

        Only rows the merge placed are read: the ``outcome`` column is the
        authority, because two refusal paths store the refused target in
        ``target_elementary_flow_id`` and an index keyed on that column alone
        would serve a failed match as a recorded decision.

        Three rungs per row, and a decision is written under all three: the
        whole-name rung (``""``), the dimension rung (``dim:Resource``), and
        the resolved context IRI.  The reader
        (:meth:`for_name_in_context`) reads exactly one of them -- the one the
        caller's own compartment reached -- so writing every coarser rung is
        what lets a vaguer caller be answered without a finer one ever being
        answered from a place they did not name.
        (``lookup/curated_names.py`` keys its curated tables by the same
        one-rung-per-caller rule; a change to how a rung is spelled belongs in
        both.)

        The resolved context comes from the build itself where the build wrote
        it down (``detail_json``'s ``source_context_iri``, extracted in SQL so
        the rest of the payload is never parsed); rows that carry none are
        resolved here under their own list's rules -- the *registered* label
        of that list, because ``resolve_context`` does not answer to a raw
        ``list_key`` spelling -- which is the resolution a build applies.  An
        absent field means the record predates #361 and counts toward
        :attr:`resolved_without_recorded_context`; a present-but-empty field
        means the build itself resolved no place, which re-deriving cannot
        improve on and remaking the build will not change, so it is re-derived
        without being counted.
        Decisions are deduplicated by ``(list, flow)``, so one list recording
        the same answer in five spellings of a compartment is one voice, not
        five.
        """
        from brightway_flows.lookup.query import (
            FlowQuery,
            ResolvedContext,
            resolve_context,
        )

        index: dict[tuple[str, str], dict[tuple[str, str], RecordedDecision]] = {}
        connection = self._connect()
        try:
            placeholders = ", ".join("?" for _ in _MATCHED_OUTCOMES)
            rows = connection.execute(
                "SELECT source_name, source_context_json, target_elementary_flow_id, "
                "list_name, list_version, source_uuid, "
                "json_extract(detail_json, '$.source_context_iri') "
                "FROM merge_outcomes "
                f"WHERE outcome IN ({placeholders}) "
                "AND target_elementary_flow_id IS NOT NULL "
                "AND target_elementary_flow_id != '' ORDER BY rowid",
                _MATCHED_OUTCOMES,
            ).fetchall()
        finally:
            connection.close()
        renderings = consensus_context_strings()
        resolved_here = 0
        # The rows without a recorded IRI name a handful of distinct
        # compartments between them, so the resolution is remembered per
        # (list, compartment) rather than re-derived per row.
        resolutions: dict[tuple[str, tuple[str, ...]], ResolvedContext] = {}
        for name, context_json, target, list_name, list_version, source_uuid, iri in rows:
            key = normalize_mapping_text(str(name or ""))
            if not key:
                continue
            decision = RecordedDecision(
                elementary_flow_id=str(target),
                list_name=str(list_name or ""),
                list_version=str(list_version or ""),
                source_flow_uuid=str(source_uuid or ""),
                source_flow_name=str(name or ""),
            )
            # NULL from json_extract means the key is absent -- a record from
            # before #361 -- and only that is counted; "" means the field was
            # written and the build resolved nothing.
            field_absent = iri is None
            iri = str(iri or "")
            if iri:
                dimension = ResolvedContext(
                    context_iri=iri,
                    resolution="recorded",
                    strings=tuple(renderings.get(iri) or ()),
                ).dimension
            else:
                if field_absent:
                    resolved_here += 1
                parts = tuple(
                    str(part)
                    for part in orjson.loads(context_json or b"[]")
                    if isinstance(part, str)
                )
                cache_key = (decision.list_key, parts)
                context = resolutions.get(cache_key)
                if context is None:
                    context = resolve_context(FlowQuery(
                        name=str(name or ""),
                        context=list(parts),
                        source_label=_registered_source_label(decision.list_key),
                    ))
                    resolutions[cache_key] = context
                iri = context.context_iri
                dimension = context.dimension
            rungs = [_NAME_RUNG]
            if dimension:
                rungs.append(f"dim:{dimension}")
            if iri:
                rungs.append(iri)
            for rung in rungs:
                index.setdefault((key, rung), {})[
                    (decision.list_key, decision.elementary_flow_id)
                ] = decision
        built = {
            rung_key: tuple(decisions.values()) for rung_key, decisions in index.items()
        }
        unanimous, conflicted, _ = self._count_context_keys(built)
        logger.info(
            "lookup_recorded_name_index",
            rows=len(rows),
            context_keys=unanimous,
            conflicted_context_keys=conflicted,
            resolved_without_recorded_context=resolved_here,
        )
        return _NameIndex(index=built, resolved_without_recorded_context=resolved_here)

    @property
    def _by_name(self) -> dict[tuple[str, str], tuple[RecordedDecision, ...]]:
        return self._name_index.index

    @property
    def resolved_without_recorded_context(self) -> int:
        """How many stored decisions carried no place field and were re-derived.

        Any matched record kind can contribute; before #361 the prepared kind
        was the one that never wrote the field.  The re-derivation is weaker
        than the build's own resolution (a rule keyed to a vendor identifier
        cannot fire outside the build), so on a build made with the field in
        place this is zero -- a record whose field is present but empty means
        the build itself resolved no place, and is re-derived without being
        counted, because remaking the build would not change it.
        """
        return self._name_index.resolved_without_recorded_context

    @staticmethod
    def _count_context_keys(
        index: dict[tuple[str, str], tuple[RecordedDecision, ...]]
    ) -> tuple[int, int, int]:
        """(unanimous, conflicted, arbitrable) counts over the context-IRI rung.

        One pass for all three, because the three are one question asked of
        every key: how many recorded flows does it hold, and where it holds
        two, is some single list unanimous there -- the condition under which
        a caller's ``source_label`` could settle it (#359).
        """
        unanimous = conflicted = arbitrable = 0
        for (_, rung), decisions in index.items():
            if not rung or rung.startswith("dim:"):
                continue
            if len({d.elementary_flow_id for d in decisions}) == 1:
                unanimous += 1
                continue
            conflicted += 1
            by_list: dict[str, set[str]] = {}
            for decision in decisions:
                by_list.setdefault(decision.list_key, set()).add(
                    decision.elementary_flow_id
                )
            if any(len(targets) == 1 for targets in by_list.values()):
                arbitrable += 1
        return unanimous, conflicted, arbitrable

    @cached_property
    def _name_rung_counts(self) -> tuple[int, int, int]:
        """The context-key counts, computed once per index build."""
        return self._count_context_keys(self._by_name)

    # ── the two questions ────────────────────────────────────────────────────

    def for_identifier(
        self, list_key: str, identifier: str
    ) -> tuple[RecordedDecision, ...]:
        """What this build decided about *identifier* in *list_key*.

        Empty for a row this build did not merge, which includes every row of a
        list it has never seen -- and that is the ordinary case, because the
        whole point of the API is lists nobody has merged.
        """
        if not list_key.strip() or not identifier.strip():
            return ()
        return self._by_identifier.get((list_key.strip(), identifier.strip()), ())

    def for_name_in_context(
        self,
        name: str,
        *,
        context_iri: str = "",
        dimension: str = "",
        source_label: str = "",
    ) -> RecordedNameAnswer | None:
        """What was recorded for this name where the caller says their row is.

        **Exactly one rung is read** -- the one the caller's own compartment
        reached.  A resolved context is answered at that context or not at
        all; a caller who resolved only a dimension is answered where every
        recorded row of the dimension agrees; only a compartment that could
        not be read at all is answered from the whole-name rung, where the
        name must have one recorded flow everywhere.  There is no falling
        through: a name recorded only as an air emission says nothing about
        the caller who resolved to water, and answering them from the
        dimension rung -- which pools every emission medium -- would cross
        the boundary the caller named.  ``None`` for a rung holding nothing,
        and the matcher re-derives.

        A rung two rows disagree about answers only for a caller whose
        *source_label* names a merged list that is itself unanimous there
        (#359); otherwise ``None`` again -- the behaviour a dropped key had
        before the rungs existed.  On a unanimous rung the caller's
        *source_label*, where it names one of the agreeing lists, picks whose
        decision reports the answer, so the attribution is the caller's own
        list rather than whichever row a merge happened to write first.
        """
        key = normalize_mapping_text(name)
        if not key:
            return None
        if context_iri.strip():
            rung = context_iri.strip()
        elif dimension.strip():
            rung = f"dim:{dimension.strip()}"
        else:
            rung = _NAME_RUNG
        decisions = self._by_name.get((key, rung))
        if decisions is None:
            return None
        targets = sorted({d.elementary_flow_id for d in decisions})
        named = (
            [d for d in decisions if _list_label_matches(d, source_label)]
            if source_label.strip()
            else []
        )
        if len(targets) == 1:
            return RecordedNameAnswer(decision=named[0] if named else decisions[0])
        named_targets = {d.elementary_flow_id for d in named}
        if len(named_targets) == 1:
            return RecordedNameAnswer(
                decision=named[0],
                arbitrated_by=named[0].list_key,
                alternatives=tuple(t for t in targets if t not in named_targets),
            )
        return None

    # ── what a report wants to say about the indexes ─────────────────────────

    @property
    def identifier_links(self) -> int:
        """How many source rows this build can answer for exactly."""
        return len(self._by_identifier)

    @property
    def context_keys(self) -> int:
        """How many ``(name, resolved context)`` keys hold one recorded flow."""
        return self._name_rung_counts[0]

    @property
    def conflicted_context_keys(self) -> int:
        """How many hold two -- the genuine disagreements, which decline unless
        the caller's ``source_label`` names a list that ruled."""
        return self._name_rung_counts[1]

    @property
    def arbitrable_context_keys(self) -> int:
        """How many of the conflicted keys a ``source_label`` could settle --
        that is, where at least one merged list is itself unanimous."""
        return self._name_rung_counts[2]
