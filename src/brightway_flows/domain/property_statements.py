"""What a source list states about one of its own flows: a property statement.

"One kilogram of this coal is 18.2 MJ of net calorific value", said by
AGRIBALYSE's substance block.  "One kilogram of this coal is 19.1 MJ of gross
calorific value", said by Stepwise's method.  "One cubic metre of this sea water
is 1025 kg of mass", said by ecoinvent's EF 3.1 implementation.  Each is a
statement a list makes about a flow it ships, in the flow's own unit, and
together they are what the merge derives a mapping's `qudt:conversionMultiplier`
from when the flow lands on a consensus flow measured in another quantity.

This is ILCD's model.  An ILCD flow dataset carries a list of flow properties,
each with a `meanValue` relative to the flow's reference property; a
:class:`PropertyStatement` is one of those, with who said it and where.

**A statement is about the flow; a factor is about a pair.**  9.41 MJ per
kilogram is a fact about ecoinvent's brown coal.  9.41 is what a kilogram of it
becomes on EF's `Brown Coal` in megajoules, and that number is published on the
mapping and nowhere else (`merge.conversions`).  Until #407 the project kept
only the second and typed it by hand on each override row, so the same heating
value was written four times for four lists with no unit, no basis and no
provenance beyond a comment.

Three readers:

* :func:`factor_between` turns a statement into the multiplier for one unit
  pair, scaling through `units.json` on both ends.  Direction is carried by the
  units, never by the quantity: a statement written `0.000976 m3 per kg` and
  one written `1024.6 kg per m3` both answer a kilogram-to-cubic-metre pair,
  and a curated file states each in the direction its mapping uses so that the
  published number is the stated number bit for bit.
* :func:`choose_statement` says which of a flow's statements converts onto a
  target of a given quantity -- what the list's conversion rule says first,
  else the exact one, else a basis-unstated calorific value -- which is how net
  and gross coexist on one flow and the choice between them is data.
* :func:`parse_value_per_unit` and :func:`vendor_statement` are what the
  adapters build a statement with when they read one off the vendor's file:
  SimaPro's substance block says `Higher heating value (HHV): 19.1 MJ/kg`,
  ecoinvent's exchange carries a `heating value, net` property, Stepwise's
  method gives a kilogram of hard coal 19.1 MJ, and a SimaPro flow name says
  `46.8 MJ per kg`.
* The codec pair and :data:`PROPERTY_STATEMENTS_SCHEMA` carry the statements
  on `Flow.property_statements` across the file boundary.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, ClassVar

from brightway_flows.domain.common import Provenance
from brightway_flows.domain.quantities import (
    CALORIFIC_VALUE,
    GROSS_CALORIFIC_VALUE,
    NET_CALORIFIC_VALUE,
    quantity,
)
from brightway_flows.domain.records import SerialisableRecord
from brightway_flows.domain.units import quantity_factor


class StatementOrigin(StrEnum):
    """Who stated a property of a flow.

    What makes a borrowed number visible: BAFU's 18.01 MJ/kg for hard coal is
    ecoinvent's workbook figure, and a reader of the mapping should be able to
    see that the list did not say so itself.
    """

    #: The list's own flow dataset or substance block states it.
    VENDOR_FLOW = "vendor-flow"
    #: The list's own LCIA method implementation states it, as the factor its
    #: energy category gives a kilogram of the flow.
    VENDOR_METHOD = "vendor-method"
    #: The flow's own name states it: `Gas, natural, 46.8 MJ per kg`.
    FLOW_NAME = "flow-name"
    #: This project states it, in a ruling, naming where the number came from.
    CURATED = "curated"


def _encode_provenance(value: Any) -> Any:
    return value.to_dict() if isinstance(value, Provenance) else value


def _decode_provenance(value: Any) -> Any:
    return Provenance.from_dict(value) if isinstance(value, dict) else value


def _decode_origin(value: Any) -> Any:
    return StatementOrigin(value) if isinstance(value, str) else value


@dataclass(frozen=True)
class PropertyStatement(SerialisableRecord):
    """One `per_unit` of this flow is `value` `unit` of `quantity`, says *stated_by*."""

    #: A slug of `quantities.json`: `net-calorific-value`.
    quantity: str
    value: float
    #: The quantity's unit, a `units.json` notation: `MJ`.
    unit: str
    #: The flow's own unit, or one `units.json` scales to it: `kg`.
    per_unit: str
    stated_by: StatementOrigin
    #: `prov:hadPrimarySource` names what stated it -- the vendor's file and
    #: section, the workbook, the flow's name, the IPCC table.
    provenance: Provenance
    comment: str = ""

    _CODECS: ClassVar[dict[str, tuple[Any, Any]]] = {
        "provenance": (_encode_provenance, _decode_provenance),
        "stated_by": (str, _decode_origin),
    }

    def __post_init__(self) -> None:
        if isinstance(self.value, bool) or not isinstance(self.value, (int, float)):
            raise ValueError(
                f"A property statement's value must be a number, not {self.value!r}."
            )
        if not self.value > 0:
            raise ValueError(
                f"A property statement's value must be positive; {self.value!r} "
                f"of {self.quantity} per {self.per_unit} converts nothing."
            )
        object.__setattr__(self, "value", float(self.value))

    @property
    def quantity_iri(self) -> str:
        return quantity(self.quantity).iri


#: The published shape of `Flow.property_statements`, for the schema generator.
#: Declared because `provenance` publishes CURIE keys the record's annotation
#: does not describe, exactly as `lcia_methods` does.
PROPERTY_STATEMENTS_SCHEMA: dict[str, Any] = {
    "title": "Property Statements",
    "type": "array",
    "items": {
        "type": "object",
        "properties": {
            "quantity": {"type": "string"},
            "value": {"type": "number"},
            "unit": {"type": "string"},
            "per_unit": {"type": "string"},
            "stated_by": {
                "type": "string",
                "enum": [origin.value for origin in StatementOrigin],
            },
            "provenance": {"type": "object", "additionalProperties": True},
            "comment": {"type": "string"},
        },
        "required": [
            "quantity", "value", "unit", "per_unit", "stated_by", "provenance",
            "comment",
        ],
        "additionalProperties": False,
    },
}


def encode_statements(value: Any) -> Any:
    """The encode half of the codec `Flow` declares for `property_statements`."""
    if not isinstance(value, list):
        return value
    return [
        statement.to_dict() if isinstance(statement, PropertyStatement) else statement
        for statement in value
    ]


def decode_statements(value: Any) -> Any:
    """The decode half.  A record already built is passed through."""
    if not isinstance(value, list):
        return value
    return [
        PropertyStatement.from_dict(entry) if isinstance(entry, dict) else entry
        for entry in value
    ]


def factor_between(
    statement: PropertyStatement, source_unit: str, target_unit: str
) -> float | None:
    """How many *target_unit* one *source_unit* of the flow is, by *statement*.

    The statement is read in the direction it is written first -- the source
    unit scaled onto `per_unit`, the stated `unit` scaled onto the target --
    and inverted if that fails, so a density stated kilograms per cubic metre
    serves a kilogram-to-cubic-metre mapping as one over the value.  Each
    scaling is :func:`~brightway_flows.domain.units.quantity_factor`: 1.0 for
    one unit, the table factor within a kind, ``None`` across kinds -- which is
    what keeps a statement per standard cubic metre off a row in plain cubic
    metres (#292).  ``None`` where neither reading bridges the pair.
    """
    forward = quantity_factor(source_unit, statement.per_unit)
    back = quantity_factor(statement.unit, target_unit)
    if forward is not None and back is not None:
        return forward * statement.value * back
    forward = quantity_factor(source_unit, statement.unit)
    back = quantity_factor(statement.per_unit, target_unit)
    if forward is not None and back is not None:
        return forward * (1.0 / statement.value) * back
    return None


@dataclass(frozen=True)
class ConversionRule:
    """A list's ruling that one quantity converts onto a target of another.

    Stepwise 2006 counts a kilogram of coal as whatever its own method's
    `Non-renewable energy` category gives it -- the higher heating value for
    hard coal, the number in the name for `Coal, 18 MJ per kg` -- so its rows
    convert onto EF's net-calorific-value flows by that number, whatever closer
    statement the flow also carries, and the mapping says so.  That is a
    decision a person wrote down with a reason, not a default the code
    applies, and it comes before the exact match because it is written exactly
    where the exact match is not what the list counts.
    """

    #: The target's reference quantity this rule is about.
    onto: str
    #: The statement quantity that converts onto it.
    convert_by: str
    comment: str
    #: Only a statement of this origin, where the rule names one: Stepwise's
    #: converts by the method's number and not by the same quantity read off
    #: the flow's name.
    stated_by: StatementOrigin | None = None

    def admits(self, statement: PropertyStatement) -> bool:
        return statement.quantity == self.convert_by and (
            self.stated_by is None or statement.stated_by is self.stated_by
        )


class AmbiguousPropertyStatementsError(ValueError):
    """Two statements answered the same question about one flow."""


def _one_of(
    candidates: list[PropertyStatement], *, step: str, target_quantity: str
) -> PropertyStatement | None:
    """The one answer among *candidates*, or ``None`` for none.

    Two statements that state the same number -- the method's 30.3 MJ per
    kilogram and the 30.3 in the flow's name -- are one answer said twice,
    and the first stands.  Two different numbers are a question.
    """
    distinct = {(s.value, s.unit, s.per_unit) for s in candidates}
    if len(distinct) > 1:
        described = "; ".join(
            f"{s.value} {s.unit} of {s.quantity} per {s.per_unit} ({s.stated_by})"
            for s in candidates
        )
        raise AmbiguousPropertyStatementsError(
            f"{len(candidates)} statements convert onto {target_quantity!r} "
            f"{step}: {described}. A ruling has to say which, in the list's "
            f"property statements file; file order does not decide."
        )
    return candidates[0] if candidates else None


def _basis_unstated_pair(statement_quantity: str, target_quantity: str) -> bool:
    """A calorific value of unstated basis against a stated one, either way."""
    stated = {NET_CALORIFIC_VALUE, GROSS_CALORIFIC_VALUE}
    return (statement_quantity == CALORIFIC_VALUE and target_quantity in stated) or (
        target_quantity == CALORIFIC_VALUE and statement_quantity in stated
    )


def choose_statement(
    statements: Iterable[PropertyStatement],
    *,
    target_quantity: str,
    rules: Sequence[ConversionRule] = (),
) -> PropertyStatement | None:
    """Which of *statements* converts onto a target measuring *target_quantity*.

    1. What the list's conversion *rules* say converts onto this target, where
       a rule names it and the flow carries such a statement.  A rule is the
       list's own accounting convention, written down with its reason, and it
       comes first because it is written exactly where the closer statement is
       not what the list counts: Stepwise's brown coal carries the substance
       block's net 8.75 and the method's 9.9, and Stepwise counts 9.9.
    2. Else the statement whose quantity *is* the target's.
    3. Else a calorific value of unstated basis for a net or gross target, or
       the reverse; the caller publishes that the basis was unstated.  A
       fission energy is never accepted here: it converts only onto a target
       ruled `fission-energy`, because it is not a heat of combustion.
    4. Else nothing.

    :raises AmbiguousPropertyStatementsError: when two statements of different
        numbers answer at one step.  Two gross values for one flow from two of
        the vendor's own sources is a question for a ruling, never for file
        order (rule 14).  The same number said twice -- by the method and by
        the flow's name -- is one answer.
    """
    candidates = list(statements)
    for rule in rules:
        if rule.onto != target_quantity:
            continue
        ruled = [s for s in candidates if rule.admits(s)]
        chosen = _one_of(
            ruled, step=f"by the rule converting {rule.convert_by!r}",
            target_quantity=target_quantity,
        )
        if chosen is not None:
            return chosen
    exact = [s for s in candidates if s.quantity == target_quantity]
    chosen = _one_of(exact, step="exactly", target_quantity=target_quantity)
    if chosen is not None:
        return chosen
    unstated = [
        s for s in candidates if _basis_unstated_pair(s.quantity, target_quantity)
    ]
    return _one_of(
        unstated, step="with the basis unstated", target_quantity=target_quantity
    )


#: `19.1 MJ/kg`, `650 kg/m3`, `1.5e3 MJ/m3`: a number, a unit, a slash, the
#: unit it is per.  A decimal comma is accepted because SimaPro exports write
#: one where the export's locale does.
_VALUE_PER_UNIT = re.compile(
    r"^\s*(?P<value>[-+]?\d+(?:[.,]\d+)?(?:[eE][-+]?\d+)?)\s*"
    r"(?P<unit>[A-Za-z][A-Za-z0-9]*)\s*/\s*(?P<per>[A-Za-z][A-Za-z0-9]*)\s*$"
)


def parse_value_per_unit(text: str) -> tuple[float, str, str] | None:
    """``"19.1 MJ/kg"`` -> ``(19.1, "MJ", "kg")``; ``None`` where the text is not that shape.

    The units come back as the vendor spelled them -- `MH` in SimaPro's
    `18.2 MH/kg` is returned as written, and it is the caller's business to
    find that `units.json` does not know it and to say so.
    """
    match = _VALUE_PER_UNIT.match(str(text or ""))
    if match is None:
        return None
    return (
        float(match["value"].replace(",", ".")),
        match["unit"],
        match["per"],
    )


def vendor_statement(
    *,
    quantity: str,
    value: float,
    unit: str,
    per_unit: str,
    stated_by: StatementOrigin,
    primary_source: Sequence[str],
    derived_from: str,
    generated_by: str,
    attributed_to: str,
    comment: str,
) -> PropertyStatement:
    """A statement a vendor's own file makes, with its provenance spelled out.

    What the adapters and the name reader build: *derived_from* is the file
    the number was read out of, *primary_source* says where in it, and
    *attributed_to* is the list that said it.  The record's own checks refuse
    a value that converts nothing.
    """
    return PropertyStatement(
        quantity=quantity,
        value=value,
        unit=unit,
        per_unit=per_unit,
        stated_by=stated_by,
        provenance=Provenance(
            was_generated_by=generated_by,
            was_attributed_to=attributed_to,
            had_primary_source=list(primary_source),
            was_derived_from=derived_from,
        ),
        comment=comment,
    )
