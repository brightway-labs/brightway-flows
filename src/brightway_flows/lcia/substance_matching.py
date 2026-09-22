"""Reaching a flow by what the substance is, when no identifier connects the two.

The second route, and it exists because a method package is not a flow list.
GreenDelta's identifies a flow by the ecoinvent UUID it was built against, and
`matching.chained_merge_targets` follows that for 1,223 of its 1,781 flows.  The
other 558 name a substance under an identifier nothing here has -- and they are
not substances this list is missing.  `Arsenic ion` is our `Arsenic, Ion`;
`Tetrachloroethylene` is our `Ethene, tetrachloro-`; 410 of them state a registry
number we already publish, once the zero-padding their file writes is taken off
(`000056-23-5`).  #165.

**Three routes, and a curated decision comes first.**  Where a publisher names a
substance in a spelling of their own and states no number for it, no comparison
of strings reaches the flow: GreenDelta writes ``Copper ion`` where this list
publishes ``Copper, Ion``.  `lcia.substance_decisions` is the table that says
which flow such a row is about, written from the publisher's own package, and it
is tried before the number and the name both (#347).

**A substance and a place, never a substance alone.**  A factor is a number about
a substance *in a compartment*, so a match needs both halves.  Reaching a flow by
name and letting the compartment fall where it may would put a freshwater number
on an emission to air, which is a wrong factor rather than a missing one.

**Where the compartments come from.**  `data/context-manual-mapping.json`, under
the source ``GreenDelta`` -- the same file, the same shape and the same loader
every merged list uses, because "what does this publisher's compartment mean" is
one question however the rows arrive.  Each of its 21 rows records the evidence
it was written from, and three of their compartments deliberately have none:
``Resource / land``, ``Resource / in water`` and ``Resource / unspecified`` name
a place where this list names an action (``Occupation, agriculture``) or a kind
of water (``Water, well``), so one compartment of theirs is two contexts of ours
and no rule can say which.  The 56 flows filed there are reached by a curated
decision instead, which is applied before a compartment is looked up at all
(#166).

**The unit is canonicalised before it is compared.**  Both other routes compare
two notations the merge already wrote in this list's spelling; this one is handed
the vendor's own string, and openLCA writes the area-time unit ``m2*a`` where
this list publishes ``m2.a``.  `lcia.conversion.UnitCrossing` compares notations
as text, so without `domain.units.canonical_unit` every land occupation row would
cross a unit against itself and publish nothing.  A notation `units.json` does
not know is left as it arrived, so a real crossing -- a number stated per kg
against a flow published per m3 -- still reads as one.

**A place written into the name is not a substance.**  ``Water, well, CH`` is
``Water, well`` in Switzerland, and their package states ``Water, well`` beside
it with a factor for Switzerland already.  `lcia.regionalised_names` reads the
196 rows of that shape and sets aside every one whose number is carried by a
site-generic or global sibling, before a number or a name is looked at; a
curated decision still comes first (#166).

**The registry number outranks the name**, which is this project's ordinary rule
and the one #146 and #157 both turned on: a name and a number that disagree are
usually a name that drifted.  A number matching two flows, or a name matching
two, is reported and matched to neither -- picking one would be inventing an
answer where the evidence is that there is more than one.
"""

from __future__ import annotations

import sqlite3
from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

import orjson
import structlog

from brightway_flows.context_mapping import (
    ContextKey,
    context_iri_by_source_context,
    normalize_mapping_text,
)
from brightway_flows.domain.units import canonical_unit
from brightway_flows.domain.vocabulary import CHEMINF_CAS_REGISTRY_NUMBER
from brightway_flows.integrations.ecoinvent import normalize_cas_number
from brightway_flows.lcia.conversion import UnitCrossing
from brightway_flows.lcia.matching import MergeTarget
from brightway_flows.lcia.regionalised_names import (
    set_aside as regionalised_set_aside,
)
from brightway_flows.lcia.report import Finding, FindingKind
from brightway_flows.lcia.sources import FactorSource
from brightway_flows.lcia.substance_decisions import (
    BY_DECISION,
    SubstanceDecision,
    SubstanceDecisionError,
    decisions_for,
)

logger = structlog.get_logger(__name__)

#: What a match was made on, in the order they are tried.  Published on the
#: finding and counted in the run's statistics, because "reached by its number"
#: and "reached by its name" are different strengths of claim and a reader
#: deciding whether to trust a factor needs to know which one this was.
BY_REGISTRY_NUMBER = "registry-number"
BY_NAME = "name"
#: Both, and it is the number that did the work.  ``Water`` and ``Water vapour``
#: are two flows of ours under one registry number, 7732-18-5, so a row stating
#: that number is about one of them and the number cannot say which -- but the
#: name can, and a name agreeing with a number is not the weak claim a name
#: alone would be.  50 of GreenDelta's rows are this pair, and the four carbon
#: monoxide and carbon dioxide flows this list splits by origin are the rest.
BY_NUMBER_AND_NAME = "registry-number-and-name"
#: A curator read the publisher's own package and said which flow the row is
#: about, in `data/lcia-substance-decisions.json`.  Tried before either of the
#: others: see `lcia.substance_decisions`.
BY_CURATED_DECISION = BY_DECISION


@dataclass(frozen=True, slots=True)
class SubstanceIndex:
    """The published flows, keyed the two ways a substance can be recognised.

    Deprecated flows are left out.  A factor landing on a flow this list has
    withdrawn would be a number published against something a consumer is being
    told not to use, and the identifier route cannot reach one either: it goes
    through the merge, which points a withdrawn flow's reference at the survivor.
    """

    #: ``(context iri, registry number)`` to the flows carrying it.
    by_number: dict[tuple[str, str], set[str]]
    #: ``(context iri, casefolded label)`` to the flows carrying it.
    by_name: dict[tuple[str, str], set[str]]
    #: What each flow is published per, for the unit check.
    units: dict[str, str]
    #: ``(label, context, unit)`` per flow, which is what a curated decision
    #: recorded about its target and is checked against before the row applies
    #: (`lcia.substance_decisions`).
    published: dict[str, tuple[str, str, str]]

    @property
    def flow_count(self) -> int:
        return len(self.units)


def substance_index(db_path: Path) -> SubstanceIndex:
    """Read the published flows once, in the two shapes a lookup needs."""
    by_number: dict[tuple[str, str], set[str]] = defaultdict(set)
    by_name: dict[tuple[str, str], set[str]] = defaultdict(set)
    units: dict[str, str] = {}
    published: dict[str, tuple[str, str, str]] = {}
    connection = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        rows = connection.execute(
            "SELECT ef.uuid, ef.pref_label_value, ef.context_iri, ef.unit, "
            "       ef.context_display, fo.classifications_json "
            "FROM elementary_flows ef "
            "LEFT JOIN flow_objects fo ON fo.flow_object_id = ef.flow_object_id "
            "WHERE ef.is_deprecated = 0"
        )
        for uuid, label, context_iri, unit, display, classifications in rows:
            uuid, context_iri = str(uuid), str(context_iri or "")
            if not context_iri:
                continue
            units[uuid] = str(unit or "")
            published[uuid] = (
                str(label or ""),
                str(display or ""),
                str(unit or ""),
            )
            if label:
                by_name[(context_iri, normalize_mapping_text(label))].add(uuid)
            payload = orjson.loads(classifications or "{}")
            entry = payload.get(CHEMINF_CAS_REGISTRY_NUMBER) or {}
            for value in entry.get("@value") or ():
                by_number[(context_iri, str(value))].add(uuid)
    finally:
        connection.close()
    return SubstanceIndex(
        by_number=dict(by_number),
        by_name=dict(by_name),
        units=units,
        published=published,
    )


def compartment_key(context: str) -> ContextKey:
    """One of their compartment strings as a context-mapping key.

    ``Elementary flows/Emission to air/unspecified`` is ``("emission to air",
    "unspecified")``.  The leading segment is the openLCA root that every
    elementary flow sits under and says nothing about the place; the rest is the
    compartment and its sub-compartment, which is what a rule is keyed on.
    """
    parts = [part.strip() for part in str(context).split("/") if part.strip()]
    if parts and normalize_mapping_text(parts[0]) == "elementary flows":
        parts = parts[1:]
    return tuple(normalize_mapping_text(part) for part in parts)


def _stated_number(described: dict[str, str]) -> str:
    """Their registry number, in this list's spelling.

    They write it zero-padded to six digits -- ``000056-23-5`` for carbon
    tetrachloride -- which is SimaPro's convention and matches nothing here as
    written.  Normalised by the same function the ecoinvent adapter uses, so a
    number reaches the same substance whichever file it arrived in.
    """
    raw = (described.get("cas") or "").strip()
    if not raw:
        return ""
    try:
        return normalize_cas_number(raw) or ""
    except Exception:  # pragma: no cover - malformed input is not a crash here
        return ""


def _ambiguous(
    source: FactorSource,
    flow_uuid: str,
    described: dict[str, str],
    basis: str,
    candidates: set[str],
    factor_count: int,
) -> Finding:
    """Their row, and the several flows of ours it could be about."""
    return Finding(
        kind=FindingKind.FLOW_NOT_REACHED,
        implemented_by=source.implementation.name,
        elementary_flow_uuid=None,
        impact_category_id=None,
        detail=(
            f"{described.get('name') or flow_uuid} carries {factor_count} factors "
            f"and its {basis} reaches {len(candidates)} flows in "
            f"{described.get('context') or 'no compartment'}, so none of them can "
            "be said to be the one it is about"
        ),
        context={
            "source_flow_uuid": flow_uuid,
            "name": described.get("name") or "",
            "context": described.get("context") or "",
            "unit": described.get("unit") or "",
            "cas": described.get("cas") or "",
            "matched_on": basis,
            "candidates": sorted(candidates),
            "factor_count": factor_count,
        },
    )


def _decided(
    decision: SubstanceDecision,
    described: dict[str, str],
    *,
    index: SubstanceIndex,
) -> MergeTarget:
    """The target a curated decision names, once its guard has held.

    The guard is what the row recorded about the flow it was written against.  A
    build where that uuid publishes a different substance, sits in a different
    compartment or is stated in a different unit raises rather than applying the
    row, because a decision that quietly lands somewhere else is worse than one
    that stops working.
    """
    substance, context, unit = index.published.get(
        decision.elementary_flow_uuid, ("", "", "")
    )
    if not substance:
        raise SubstanceDecisionError(
            f"the decision about {decision.source_flow_name!r} reaches "
            f"{decision.elementary_flow_uuid}, which this build does not publish"
        )
    if not decision.covers(substance=substance, context=context, unit=unit):
        raise SubstanceDecisionError(
            f"the decision about {decision.source_flow_name!r} was written "
            f"about {decision.substance!r} in {decision.context!r} "
            f"({decision.unit}); {decision.elementary_flow_uuid} now publishes "
            f"{substance!r} in {context!r} ({unit})"
        )
    return MergeTarget(
        elementary_flow_uuid=decision.elementary_flow_uuid,
        crossing=UnitCrossing(
            source_unit=canonical_unit(str(described.get("unit") or "")),
            target_unit=unit,
        ),
    )


def substance_targets(
    source: FactorSource,
    *,
    index: SubstanceIndex,
    outstanding: set[str],
    decisions: dict[str, SubstanceDecision] | None = None,
    set_aside: Mapping[str, str] | None = None,
) -> tuple[dict[str, MergeTarget], dict[str, str], list[Finding], dict[str, str]]:
    """Where each *outstanding* flow of *source* goes, and why.

    *outstanding* is the flows the identifier route did not reach; everything
    else is already placed and is not reconsidered here, because an identifier is
    a stronger statement than a name and re-deciding on a weaker one would be a
    step backwards.

    Three routes, in this order: a curated decision, then a registry number, then
    an exact name.  The decision comes first because a curator who read the
    publisher's own package has more to go on than a string comparison does
    (`lcia.substance_decisions`).  *decisions* defaults to the ones shipped for
    this implementation.

    *set_aside* is the rows whose place is written into the name and whose
    number a sibling already carries, each with its reason
    (`lcia.regionalised_names.set_aside`); it defaults to what that rule finds
    among *outstanding*.  Applied after a curated decision and before a number
    or a name is looked up, and returned with the declined rows, because to
    the finding that reports the row the two are the same thing: decided, not
    missed.

    Returns the targets, what each was matched on, a finding for every row whose
    number or name reached more than one flow, and the reason recorded for every
    row a decision declined or this rule set aside.  A row that reaches none is
    not a finding here: `matching.match` already reports it -- carrying the
    reason, where there is one -- and reporting it twice would say two things
    happened.
    """
    rules = context_iri_by_source_context(source.implementation.name)
    if decisions is None:
        decisions = decisions_for(source.implementation.name)
    if set_aside is None:
        set_aside = regionalised_set_aside(source, outstanding)
    targets: dict[str, MergeTarget] = {}
    basis_of: dict[str, str] = {}
    findings: list[Finding] = []
    declined: dict[str, str] = {}
    if not rules:
        logger.info(
            "no_compartment_rules",
            implemented_by=source.implementation.name,
            outstanding=len(outstanding),
        )
        return targets, basis_of, findings, declined
    for flow_uuid in sorted(outstanding):
        described = source.descriptions.get(flow_uuid) or {}
        decision = decisions.get(flow_uuid)
        if decision is not None:
            if decision.reaches:
                targets[flow_uuid] = _decided(decision, described, index=index)
                basis_of[flow_uuid] = BY_CURATED_DECISION
            else:
                declined[flow_uuid] = decision.comment
            continue
        if (reason := set_aside.get(flow_uuid)) is not None:
            declined[flow_uuid] = reason
            continue
        context_iri = rules.get(compartment_key(described.get("context") or ""))
        if not context_iri:
            continue
        number = _stated_number(described)
        attempts: list[tuple[str, set[str] | None]] = []
        if number:
            attempts.append(
                (BY_REGISTRY_NUMBER, index.by_number.get((context_iri, number)))
            )
        attempts.append(
            (
                BY_NAME,
                index.by_name.get(
                    (context_iri, normalize_mapping_text(described.get("name") or ""))
                ),
            )
        )
        for basis, candidates in attempts:
            if not candidates:
                continue
            if len(candidates) > 1 and basis == BY_REGISTRY_NUMBER:
                # Two flows of ours share the number. The name is allowed to
                # settle it -- and only to settle it: it narrows the candidates
                # the number chose and never reaches outside them.
                named = index.by_name.get(
                    (context_iri, normalize_mapping_text(described.get("name") or ""))
                ) or set()
                if len(narrowed := candidates & named) == 1:
                    candidates, basis = narrowed, BY_NUMBER_AND_NAME
            if len(candidates) > 1:
                findings.append(
                    _ambiguous(
                        source,
                        flow_uuid,
                        described,
                        basis,
                        candidates,
                        len(source.by_flow.get(flow_uuid, ())),
                    )
                )
                break
            target = next(iter(candidates))
            targets[flow_uuid] = MergeTarget(
                elementary_flow_uuid=target,
                # No multiplier: a conversion factor is a statement about a pair
                # of flows that somebody recorded, and nobody has recorded one
                # for a pair this pass invented. Where the units differ,
                # `matching.match` reports it and publishes nothing.
                crossing=UnitCrossing(
                    source_unit=canonical_unit(str(described.get("unit") or "")),
                    target_unit=index.units.get(target, ""),
                ),
            )
            basis_of[flow_uuid] = basis
            break
    logger.info(
        "matched_by_substance",
        implemented_by=source.implementation.name,
        outstanding=len(outstanding),
        matched=len(targets),
        ambiguous=len(findings),
        declined=len(declined),
        **{
            basis.replace("-", "_"): sum(
                1 for value in basis_of.values() if value == basis
            )
            for basis in (
                BY_CURATED_DECISION,
                BY_REGISTRY_NUMBER,
                BY_NUMBER_AND_NAME,
                BY_NAME,
            )
        },
    )
    return targets, basis_of, findings, declined
