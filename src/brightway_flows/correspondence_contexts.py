"""Police a correspondence table's target contexts against our own vocabulary.

The ecoinvent-to-EF tables are curated rather than vendor-published -- GLAD's
mappings plus algorithmic and manual matches -- and nothing checks that a row's
target context means the same thing as its source context.  One layer matched on
substance name alone and pointed 66 ordinary-groundwater rows at EF's long-term
water flow, which EF characterises as zero for all four USEtox categories
(#48).  Nothing in the table, the flow names or the units shows that; only the
contexts disagree, and only once both are read through our vocabulary.

That is what this module does.  Map the source row with the ecoinvent rules, map
the target context with the EF rules, and compare the two IRIs.

"The source row", not "the source context": ecoinvent's ``natural resource /
land`` holds both land occupation and land transformation and says which in the
flow name, so the name is part of the mapping there (#52).  Reading only the
compartment made the guard's own largest finding -- 122 rows per table -- a
disagreement between the table and a rule the pipeline no longer applies.

Equality is the wrong test on its own: 2,380 of 9,238 rows in the 3.11 table
disagree for a good reason, almost always that EF has no context as specific as
ecoinvent's -- no forestry soil, no groundwater.  So the comparison is paired
with a file of permitted coarsenings, and what survives both is a violation.
`data/correspondence-context-routing.json` holds the decisions; this module only
applies them.

Two questions are asked of those decisions, not one.  A table may name EF's
nearest flow for a compartment EF does not have -- that is what a correspondence
table is for -- without that flow's compartment being where the emission goes.
Forestry soil is the case: EF has none, the table points at non-agricultural
soil correctly, and the pesticide was still sprayed on forest (#84).
:func:`permitted_coarsenings` answers the first question and
:func:`publishable_coarsenings` the second.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Iterable

import orjson

from brightway_flows.context_mapping import (
    ContextKey,
    context_iri_by_source_context,
    name_prefix_context_iri,
    normalize_context_key,
)
from brightway_flows.sources import base_source_label
from brightway_flows.filesystem import PACKAGE_DATA_DIR

#: Package data, because these are decisions rather than derived data.
ROUTING_FILEPATH = (
    PACKAGE_DATA_DIR / "correspondence-context-routing.json"
)



@dataclass(frozen=True)
class ContextRoutingViolation:
    """One row whose target context does not mean what its source context means."""

    source_context: ContextKey
    target_context: ContextKey
    source_iri: str
    target_iri: str
    source_name: str
    target_name: str

    @property
    def pair(self) -> tuple[ContextKey, ContextKey]:
        """What the guard compares.  Row counts drift; the pair is the identity."""
        return (self.source_context, self.target_context)


def _load() -> dict[str, Any]:
    if not ROUTING_FILEPATH.exists():
        raise FileNotFoundError(f"Routing rules not found at {ROUTING_FILEPATH}")
    payload = orjson.loads(ROUTING_FILEPATH.read_bytes())
    if not isinstance(payload, dict):
        raise ValueError(f"{ROUTING_FILEPATH} must contain a JSON object")
    return payload


def _coarsening_rows() -> list[dict[str, Any]]:
    """The entries both readers below share, minus the ones missing an IRI."""
    return [
        row
        for row in _load().get("permitted_coarsenings", [])
        if isinstance(row, dict) and row.get("source_iri") and row.get("target_iri")
    ]


@lru_cache(maxsize=None)
def permitted_coarsenings() -> frozenset[tuple[str, str]]:
    """``(source_iri, target_iri)`` pairs a correspondence table may state.

    Each is a decision about what EF cannot express, not a rule that can be
    derived -- which is why they are listed rather than computed.
    """
    return frozenset(
        (str(row["source_iri"]), str(row["target_iri"])) for row in _coarsening_rows()
    )


@lru_cache(maxsize=None)
def publishable_coarsenings() -> frozenset[tuple[str, str]]:
    """The pairs of :func:`permitted_coarsenings` a row may also be published on.

    A subset, and a strict one.  A forestry soil release is not treated as
    happening on non-agricultural soil by anybody; the table names that flow
    because it is the nearest EF has, and reading the compartment off it as well
    made where the emission is published depend on whether EF ships the
    substance (#84).  Groundwater onto EF's fresh water is the same act, and
    was the entry that stayed published longest: ecoinvent's own `EF v3.1`
    implementation characterises those rows with the freshwater factor, which is
    a fact about characterisation rather than about where the release went, and
    it split ecoinvent's groundwater from BAFU's (#77).

    So an entry may set ``publishable`` to false, and the merge then takes the
    substance the table names and leaves the compartment to the row's own list.
    Absent, it is true: the ordinary coarsening, accepted by both readers.
    """
    return frozenset(
        (str(row["source_iri"]), str(row["target_iri"]))
        for row in _coarsening_rows()
        if row.get("publishable", True) is not False
    )


@lru_cache(maxsize=None)
def known_violations() -> frozenset[tuple[ContextKey, ContextKey]]:
    """Context pairs the guard flags today.

    A ratchet rather than an approval: listed so that a *new* violation fails the
    build, and so that fixing one is visible as an entry that stops appearing.
    """
    return frozenset(
        (
            normalize_context_key(row.get("source_context")),
            normalize_context_key(row.get("target_context")),
        )
        for row in _load().get("known_violations", [])
        if isinstance(row, dict)
    )


def audit_correspondence_contexts(
    rows: Iterable[dict[str, Any]],
    source_label: str,
    target_label: str | None = None,
) -> list[ContextRoutingViolation]:
    """Every row whose source and target contexts disagree without a reason.

    Parameters
    ----------
    rows
        A correspondence table's ``replace`` entries, each with ``source`` and
        ``target`` dicts carrying a ``context`` list.  These are external
        payloads and stay dicts.
    source_label
        The list the rows come *from*, e.g. ``"ecoinvent-3.11"``, used to pick
        its context rules.
    target_label
        The list they map *to*.  Defaults to the base list, which every
        correspondence in the project targets; named rather than hard-coded so
        that changing the base list stays a one-line change to its manifest.

    Notes
    -----
    A row whose context has no rule on either side is skipped rather than
    reported.  An unmapped context is a gap in `context-manual-mapping.json`,
    which is a different defect with a different fix, and reporting it here
    would bury the routing errors this guard exists to find.
    """
    source_rules = context_iri_by_source_context(source_label)
    target_rules = context_iri_by_source_context(target_label or base_source_label())
    permitted = permitted_coarsenings()

    violations: list[ContextRoutingViolation] = []
    for row in rows:
        source = row.get("source") or {}
        target = row.get("target") or {}
        source_context = normalize_context_key(source.get("context"))
        target_context = normalize_context_key(target.get("context"))
        # The name first, where a compartment holds two contexts and only the
        # name separates them, because that is the order the transform and the
        # merge read the rules in.  A guard that reads a different rule than the
        # pipeline reports disagreements the pipeline does not have (#52).
        source_iri = name_prefix_context_iri(
            source_label, source.get("name"), source.get("context")
        ) or source_rules.get(source_context)
        target_iri = target_rules.get(target_context)
        if source_iri is None or target_iri is None:
            continue
        if source_iri == target_iri:
            continue
        if (source_iri, target_iri) in permitted:
            continue
        violations.append(
            ContextRoutingViolation(
                source_context=source_context,
                target_context=target_context,
                source_iri=source_iri,
                target_iri=target_iri,
                source_name=str(source.get("name", "")),
                target_name=str(target.get("name", "")),
            )
        )
    return violations
