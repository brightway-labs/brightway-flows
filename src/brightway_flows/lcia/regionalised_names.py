"""A publisher's flow that carries the country inside its name, and what to do
with its factor.

GreenDelta's package states ``Water, well, CH`` beside ``Water, well``: the same
withdrawal, once for Switzerland and once for nowhere in particular.  The
site-generic row carries one water-use factor for each of 209 countries, the
Swiss row carries one number, and the number is the one the site-generic row
already states for Switzerland.  196 of their flows are of this shape -- 98
emissions to water and 98 withdrawals -- and none of them is a water this list
is missing (#166).

**The place goes in the context, never in the name.**  That is how this list
models geography, and it is how BAFU's rows of exactly these names are read:
`integrations.bafu` splits ``Water, well, CH`` into ``Water, well`` in ``CH``
and the build places it on `Groundwater` with the rest.  A factor is different.
It is a number about a flow *in a place*, and the place is already a column of
its own -- `StatedFactor.geography` -- so a row whose name says the country is a
regionalised factor written twice over, and publishing it a second time keyed
on the name would put 47 different site-generic numbers on one flow.  That is
the collision the build reported before this rule: 47 ``Water, XX`` rows
reaching `Water` in Environmental → Water → River, each stating its own
country's number for no country at all.

**Three shapes, and one rule.**

* The set has a **site-generic member** in the same compartment -- ``Water,
  well`` beside ``Water, well, CH`` -- and that member carries the country
  factors.  The coded row is set aside: its number is published from there.
* The set has **no site-generic member but a global one** -- ``Water,
  unspecified natural origin`` exists only as 77 countries and ``GLO``.  The
  global member is the site-generic row under another spelling, and is left to
  the ordinary routes (a curated decision, in practice, because ``Resource / in
  water`` is a compartment this list reads by the kind of water and not by a
  rule).  The other 77 are set aside behind it.
* The set has **neither** -- ``Water, well, RER`` is filed under ``Resource /
  in ground`` where their ``Water, well`` is not, and ``Water, NO`` under
  ``Emission to water / fossil-``.  Every member is set aside, and the reason
  says so, because there is nothing site-generic to publish and a country's
  number is not the world's.  Three rows.

**A sibling may carry its unit in its name.**  ``Water, cooling, unspecified
natural origin/m3`` is the site-generic row beside six country rows of that
name, spelled the way SimaPro spells a flow measured two ways; it is read as
the sibling with the unit taken off, by `simapro_names.name_without_unit_suffix`,
the same rule BAFU's extractor applies to the same names.

**A curated decision outranks this.**  `lcia.substance_decisions` is applied
first, so a curator who reads one of these rows differently writes a row and
wins.  None does today.

**What is reported.**  A row set aside reaches nothing, and `matching.match`
reports it as `flow-not-reached` carrying the reason from here, the same way a
declined curated row is reported: the row was decided, not missed, and a reader
of the finding can see which.  The count is its own statistic,
``source_flows_regionalised_in_name``, and is not folded into the curated
declines: those are nine rows somebody wrote, and these are what a rule found.

**The splitter is `simapro_names.split_geography_suffix`**, the one BAFU's
extractor uses, with its base-label whitelist: a name is read as regionalised
only when the part before the last comma is one of eleven water and land names
that ship this way.  ``Transformation, to annual crop, non-irrigated, fallow``
ends in a word and is not a place; ``Water, unspecified natural origin, Europe
without Switzerland`` names a region no code covers and is left alone, which is
one flow and one factor.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

import structlog

from brightway_flows.context_mapping import normalize_mapping_text
from brightway_flows.lcia.sources import FactorSource
from brightway_flows.simapro_names import (
    canonical_geography_code,
    name_without_unit_suffix,
    split_geography_suffix,
)

logger = structlog.get_logger(__name__)

#: The code that means the world, which is what a site-generic factor is about.
GLOBAL = "GLO"


@dataclass(frozen=True, slots=True)
class RegionalisedName:
    """One of their flows, read as a name and a place."""

    flow_uuid: str
    name: str
    stem: str
    code: str
    context: str

    @property
    def is_global(self) -> bool:
        return canonical_geography_code(self.code) == GLOBAL


def regionalised_names(source: FactorSource, flow_uuids) -> list[RegionalisedName]:
    """Every flow among *flow_uuids* whose name carries a place."""
    found: list[RegionalisedName] = []
    for flow_uuid in sorted(flow_uuids):
        described = source.descriptions.get(flow_uuid) or {}
        name = str(described.get("name") or "")
        split = split_geography_suffix(name)
        if split is None:
            continue
        stem, code = split
        found.append(
            RegionalisedName(
                flow_uuid=flow_uuid,
                name=name,
                stem=stem,
                code=code,
                context=str(described.get("context") or ""),
            )
        )
    return found


def _site_generic_members(source: FactorSource) -> set[tuple[str, str]]:
    """``(compartment, casefolded name)`` of every flow of theirs with no place
    in its name, so a coded row can ask whether its stem is stated beside it."""
    members: set[tuple[str, str]] = set()
    for described in source.descriptions.values():
        name = str(described.get("name") or "")
        name = name_without_unit_suffix(name, str(described.get("unit") or "")) or name
        if split_geography_suffix(name) is None:
            members.add(
                (str(described.get("context") or ""), normalize_mapping_text(name))
            )
    return members


def set_aside(source: FactorSource, flow_uuids) -> dict[str, str]:
    """The flows among *flow_uuids* whose factor is not published because the
    place is in the name, each with the reason, keyed on their uuid.

    Looks at every flow of *source* to find a set's site-generic and global
    members, and returns only rows from *flow_uuids*: a row an identifier
    already reached is not reconsidered here, for the reason
    `substance_matching.substance_targets` gives.
    """
    coded = regionalised_names(source, flow_uuids)
    if not coded:
        return {}
    generic = _site_generic_members(source)
    sets: dict[tuple[str, str], list[RegionalisedName]] = defaultdict(list)
    for row in coded:
        sets[(row.context, normalize_mapping_text(row.stem))].append(row)

    reasons: dict[str, str] = {}
    for (context, _stem_key), members in sets.items():
        stem = members[0].stem
        has_generic = (context, normalize_mapping_text(stem)) in generic
        has_global = any(row.is_global for row in members)
        for row in members:
            if has_generic:
                reasons[row.flow_uuid] = (
                    f"`{row.name}` writes the place into the flow name, and their "
                    f"package states `{stem}` in the same compartment as a "
                    f"site-generic row carrying one factor per country. A factor's "
                    f"place is its geography and never its name, so the number is "
                    f"published from that row and not again from this one (#166)."
                )
            elif has_global and not row.is_global:
                reasons[row.flow_uuid] = (
                    f"`{row.name}` writes the place into the flow name, and their "
                    f"package states no site-generic `{stem}` in this compartment; "
                    f"`{stem}, {GLOBAL}` is the member that stands for the set, and "
                    f"a country's number is not published under a name (#166)."
                )
            elif not has_global:
                reasons[row.flow_uuid] = (
                    f"`{row.name}` writes the place into the flow name, and their "
                    f"package states neither a site-generic `{stem}` nor a "
                    f"`{stem}, {GLOBAL}` in this compartment. A country's number "
                    f"is not the world's, so none of the {len(members)} members "
                    f"is published (#166)."
                )
            # The global member of a set with no site-generic row is the
            # site-generic row under another spelling, and is left to the
            # routes that follow.
    logger.info(
        "regionalised_names_set_aside",
        implemented_by=source.implementation.name,
        regionalised=len(coded),
        set_aside=len(reasons),
        sets=len(sets),
    )
    return reasons
