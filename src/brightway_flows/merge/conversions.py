"""The conversion factor a correspondence table states for a mapped flow.

A factor is a statement about a *pair*: one unit of this source flow is `factor`
units of that target flow.  It is not a property of either flow on its own --
9.41 is not a fact about brown coal until it is 9.41 MJ per kg -- which is why
it is recorded on the mapping and never on a consensus flow or a flow object.
`qudt:conversionMultiplier` on an `xkos:ConceptAssociation` is where it lands.

Being pairwise is also why carrying it needs a guard.  A source flow can reach a
consensus flow by a route the correspondence table did not name -- the table's
target was deprecated and redirected, a curator rejected it, or matching placed
the row itself -- and the merge should still convert the amount rather than
silently pass a mass off as an energy.  What has to survive the redirect is the
*units*: a factor stated between kilograms and megajoules holds for any pair
that is still kilograms to megajoules, and for no other.

Units are compared as IRIs rather than as text, so `Sm3` and `m3` are two units
and not one spelling of the same.  ecoinvent gives natural gas in standard cubic
metres from 3.9 on and in cubic metres before it, and 36 MJ per standard cubic
metre is not 36 MJ per cubic metre.

Only a conversion `units.json` could not already have made is published.  That
rules out two things at once, and it is one test rather than two:

- **Crossing quantity kinds.**  Kilograms to megajoules, cubic metres to
  kilograms.  The unit table has no factor between two quantity kinds, because
  there is none to have -- how many megajoules a kilogram is depends on the
  substance.
- **Changing what is being measured.**  ecoinvent's `TiO2, 54% in ilmenite`
  maps onto EF 3.1's elemental `titanium`, both in kilograms.  The units agree;
  the substances do not, and 0.599 is titanium's share of titanium dioxide by
  mass.  The unit table has a factor for this unit pair -- 1.0 -- and it is the
  wrong one.

One conversion crosses quantity kinds and is still refused unless a curator
states it here: anything crossing a **time dimension**.  See
:func:`crosses_a_time_dimension`.

What both have in common is that the stated factor is *not* the one the unit
table implies, and that is the test: litres to cubic metres at 0.001 is exactly
what `units.json` says, so it is left to the reader who already has it.

The test is applied once.  :meth:`UnitConversion.holds_between` is the last
place a factor can be refused, and what survives it is written out unexamined --
onto the source ref, onto the `xkos:ConceptAssociation`, into the merge report.
A writer that re-asked the question could only disagree with the answer, and the
blanket "is it 1.0?" the writers used to ask did disagree: it discarded the one
class of conversion this rule exists to admit, a factor of 1.0 across a time
dimension, so the land-occupation mappings published nothing.  See #272.

The values are the EF 3.1 LCIA method as implemented by the ecoinvent Centre,
reaching this project through the `randonneur_data` correspondence tables.  They
are not in the JRC's own EF 3.1 distribution, whose flow datasets for these
flows carry a single flow-property value of 1.0.

A table is not the only place a factor can come from.  A list that has none --
BAFU ships no correspondence at all -- states one on the manual fix that rebases
a row's unit, and `conversion_from_source_flow` reads it back.  Everything below
this point treats the two the same, because a factor is a factor whichever
curated file said it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from brightway_flows.domain.units import (
    states_more_than_the_unit_table,
    unit_iri_for,
    unit_row_for,
)
from brightway_flows.manual_fixes import UNIT_CONVERSION_KEY


@dataclass(frozen=True)
class UnitConversion:
    """A correspondence row's `conversion_factor` and the units it joins."""

    factor: float
    source_unit: str
    target_unit: str
    comment: str = ""
    #: Further spellings the vendor has used for the source flow's unit across
    #: releases; the factor was stated for each of them too.  Empty for every
    #: conversion built from a manual fix, whose pair is about one release.
    source_unit_alternates: tuple[str, ...] = ()

    def holds_between(self, *, source_unit: str, target_unit: str) -> bool:
        """Whether this factor still converts *source_unit* to *target_unit*.

        False when either side is a unit the factor was not stated for, and
        false when the row named no target unit at all: an unpaired number
        cannot be checked, and applying it unchecked is how a mass gets recorded
        as an energy.

        False too when `units.json` already states this factor, so the rule
        holds however the conversion was built rather than only for the ones
        `conversion_from_prepared_rows` let through.
        """
        if not self.source_unit or not self.target_unit:
            return False
        stated_spellings = (self.source_unit, *self.source_unit_alternates)
        return (
            any(
                _same_unit(spelling, source_unit)
                for spelling in stated_spellings
                if spelling
            )
            and _same_unit(self.target_unit, target_unit)
            and states_more_than_the_unit_table(source_unit, target_unit, self.factor)
        )


def _same_unit(left: str, right: str) -> bool:
    """Whether two unit strings name the same unit.

    By IRI where `units.json` knows both, so that a table's `kg` and a flow's
    `kilogram` agree.  Two units it does not know are compared as text, which is
    weaker but still refuses a pair that does not even spell the same.
    """
    left_iri, right_iri = unit_iri_for(left), unit_iri_for(right)
    if left_iri and right_iri:
        return left_iri == right_iri
    return left.strip().casefold() == right.strip().casefold()


def crosses_a_time_dimension(source_unit: str, target_unit: str) -> bool:
    """Whether the two units differ by a time dimension and nothing else.

    `units.json` names these quantity kinds in pairs -- Area and AreaTime, Mass
    and MassTime, Volume and VolumeTime, Length and LengthTime -- so the pairing
    is read off the vocabulary rather than listed here, and a kind added later
    is covered without this function being touched.

    Worth its own question because a factor across one is not a fact about the
    substance: m2 to m2*a asserts a *duration*, and how long an occupation
    lasted is a modelling choice that belongs to whoever made it.
    """
    source_row, target_row = unit_row_for(source_unit), unit_row_for(target_unit)
    if source_row is None or target_row is None:
        return False
    kinds = {
        str(source_row.get("quantity_kind_iri") or "").rsplit("/", 1)[-1],
        str(target_row.get("quantity_kind_iri") or "").rsplit("/", 1)[-1],
    }
    if len(kinds) != 2:
        return False
    timed = {k for k in kinds if k.endswith("Time")}
    if len(timed) != 1:
        return False
    untimed = kinds - timed
    if len(untimed) != 1:
        return False
    return next(iter(timed))[:-len("Time")] == next(iter(untimed))


def _is_curated(row: dict[str, Any]) -> bool:
    """Whether this row's decision was made here rather than inherited.

    `apply_match_overrides` and the 3.8 composition both stamp `route` on a row
    they rewrote, and no published correspondence table carries the key at all.
    """
    return str(row.get("route") or "").strip() == "override"


def conversion_from_source_flow(source_flow: Any) -> UnitConversion | None:
    """The conversion a manual fix declared when it rewrote this row's unit.

    The other half of the same idea as :func:`conversion_from_prepared_rows`,
    for a list that has no correspondence table to state a factor in.  A vendor
    measuring standing wood in kilograms is not making a mistake; it is
    measuring the resource another way, and a fix that rebases it onto the unit
    the rest of the list uses discards that unless the factor comes with it.

    The row arrives already rewritten -- ``flow.unit`` is the new unit by the
    time the merge sees it -- so what this recovers is the pair: which unit the
    vendor shipped, and how many of the new one it is.  Both come from the fix
    rather than from the row, which is what lets it survive the rewrite.

    Curated by construction, so unlike a table row this may cross a time
    dimension: that guard exists to stop somebody else's modelling assumption
    being inherited silently, and a hand-written fix with a mandatory comment is
    the opposite of silent.  The unit-table guard still applies -- a factor
    ``units.json`` already implies is a second copy of it, not a decision.
    """
    extra = getattr(source_flow, "extra", None)
    stated = extra.get(UNIT_CONVERSION_KEY) if isinstance(extra, dict) else None
    if not isinstance(stated, dict):
        return None
    factor = stated.get("factor")
    if isinstance(factor, bool) or not isinstance(factor, (int, float)):
        return None
    source_unit = str(stated.get("source_unit") or "").strip()
    target_unit = str(stated.get("target_unit") or "").strip()
    if not states_more_than_the_unit_table(source_unit, target_unit, float(factor)):
        return None
    return UnitConversion(
        factor=float(factor),
        source_unit=source_unit,
        target_unit=target_unit,
        comment=str(stated.get("comment") or ""),
    )


def conversion_from_prepared_rows(
    prepared_rows: list[dict[str, Any]],
) -> UnitConversion | None:
    """The conversion the first prepared row stating one asks for, if any.

    A factor `units.json` already implies is not one: it has a home on the unit,
    and restating it per mapping would be a second copy of it.  That is the test
    a bare "is it 1.0?" used to stand in for, and the two differ exactly where
    it matters -- kilograms to kilograms at 1.0 converts nothing, but `m2` to
    `m2*a` at 1.0 changes the quantity kind and the unit table has no such
    factor to defer to.

    A **time dimension** is crossed only on a curated row.  Every ecoinvent
    correspondence table states 1.0 for the three obsolete land-occupation
    flows, commented "Assumed conversion based on land use through an entire
    year" -- an assumption neither list publishes, inherited silently by
    whoever loads the table.  Taking it automatically would republish somebody
    else's modelling choice as though it were a measurement; stated in
    `ecoinvent-match-overrides.json` it is this project's assertion, with its
    reasoning attached.  See #3.

    No **prepared row** states one today.  Those three flows were the only ones
    that ever did, and #111 declined their mappings: tillage regime is a land
    class EF 3.1 has no room for, so each is published under its own name now.
    The duration did not go away with the mapping -- it was never about the
    mapping.  It moved onto the manual fix that rebases the row's own unit from
    m2 to m2*a, where :func:`conversion_from_source_flow` reads it, which is the
    same assertion made about the row rather than about a pair of flows.  The
    rule here stays because the tables still state the factor, and a curated row
    is still the only thing that could take it.
    """
    for row in prepared_rows:
        if not isinstance(row, dict):
            continue
        value = row.get("conversion_factor")
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            continue
        source = row.get("source") if isinstance(row.get("source"), dict) else {}
        target = row.get("target") if isinstance(row.get("target"), dict) else {}
        source_unit = str(source.get("unit") or "").strip()
        target_unit = str(target.get("unit_name") or "").strip()
        if not states_more_than_the_unit_table(
            source_unit, target_unit, float(value)
        ):
            continue
        if crosses_a_time_dimension(source_unit, target_unit) and not _is_curated(row):
            continue
        alternates = source.get("unit_alternates")
        return UnitConversion(
            factor=float(value),
            source_unit=source_unit,
            target_unit=target_unit,
            comment=str(row.get("comment") or ""),
            source_unit_alternates=tuple(
                str(part or "").strip() for part in alternates
            )
            if isinstance(alternates, (list, tuple))
            else (),
        )
    return None
