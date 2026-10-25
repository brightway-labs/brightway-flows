"""The quantity vocabulary: what a number a list states about a flow measures.

A unit does not say it.  A megajoule can be net calorific value, gross calorific
value, or a heat of combustion whose basis nobody wrote down -- and uranium's
560,000 MJ per kilogram is not a heat of combustion at all.  EF 3.1 declares,
for each of its 34 energy flows, that the megajoule is *net calorific value*;
AGRIBALYSE's substance block states a lower and a higher heating value for the
same coal; Stepwise's method converts by the gross one.  Which of those a
kilogram of coal becomes when it reaches an EF flow is a question about
quantities, and this module is where the quantities are named.

The vocabulary is ``quantities.json``, registered beside ``units.json`` as what
the words mean rather than a decision anybody made.  Each row carries the
label ILCD uses, the other spellings the vendor files use, the ILCD flow
property it is the same thing as where ILCD has one, the kind its unit must
belong to in ``units.json``'s spelling, and the published QUDT quantity kind it
matches or narrows -- looked up in QUDT, never inferred, in the spirit of rule
18 (confirm an ontology's IRI before using it).

Where a row is reached:

* a :class:`~brightway_flows.domain.property_statements.PropertyStatement`
  names its quantity by ``slug``;
* a published mapping names the quantity its multiplier was derived through
  by :attr:`Quantity.iri`;
* :func:`quantity_for_unit` answers what a flow's unit measures when nothing
  states otherwise, which is how a target flow in kilograms is known to be a
  mass and one in megajoules a calorific value of unstated basis.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

import orjson

from brightway_flows.domain.units import unit_row_for
from brightway_flows.domain.vocabulary import QUANTITY_IRI_PREFIX, Term, curie
from brightway_flows.filesystem import PACKAGE_DATA_DIR

QUANTITIES_FILEPATH = PACKAGE_DATA_DIR / "quantities.json"

#: How a row may relate to the QUDT kind it names: the same thing, or a
#: narrower one (net calorific value narrows QUDT's undivided `HeatingValue`).
_QUDT_RELATIONS = frozenset({curie(Term.EXACT_MATCH), curie(Term.BROADER)})

#: The slugs code branches on.  Each is checked against the file by
#: `tests/test_quantities.py`, so the file stays the one home for what a
#: quantity is called and these stay spellings of rows it has.
MASS = "mass"
VOLUME = "volume"
NET_CALORIFIC_VALUE = "net-calorific-value"
GROSS_CALORIFIC_VALUE = "gross-calorific-value"
#: A heat of combustion whose source did not say net or gross.
CALORIFIC_VALUE = "calorific-value"
#: What a nuclear fuel yields by fission.  Not a heat of combustion.
FISSION_ENERGY = "fission-energy"
RADIOACTIVITY = "radioactivity"

#: The quantity a flow's unit measures when nothing states otherwise, by the
#: quantity kind `units.json` gives the unit.  A megajoule is a calorific value
#: of unstated basis: EF says *net* for its own flows through
#: `flow-properties.json`, and a created flow in megajoules has nobody to say
#: so for it.
_GENERIC_BY_KIND: dict[str, str] = {
    "Mass": MASS,
    "Volume": VOLUME,
    "Energy": CALORIFIC_VALUE,
    "Activity": RADIOACTIVITY,
}


@dataclass(frozen=True)
class Quantity:
    """One row of ``quantities.json``."""

    slug: str
    label: str
    aliases: tuple[str, ...]
    #: The ILCD flow property this is the same thing as, or ``None`` for a
    #: quantity ILCD does not name (`calorific-value`, `fission-energy`).
    ilcd_flow_property_uuid: str | None
    #: The kind a statement's `unit` must belong to, as `units.json` spells
    #: it: `https://vocab.brightway.one/units/quantity-kind/Energy`.
    quantity_kind_iri: str
    #: How this row relates to a published QUDT quantity kind:
    #: `skos:exactMatch` or `skos:broader`, and the QUDT IRI.
    qudt_match_relation: str
    qudt_match_iri: str
    definition: str

    @property
    def iri(self) -> str:
        """The minted IRI a published mapping names this quantity by."""
        return f"{QUANTITY_IRI_PREFIX}{self.slug}"

    @property
    def quantity_kind(self) -> str:
        """The kind's local name, `Energy` for the IRI ending in it."""
        return self.quantity_kind_iri.rsplit("/", 1)[-1]


def _as_quantity(row: dict[str, Any], *, index: int) -> Quantity:
    def text(key: str) -> str:
        value = row.get(key)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(
                f"Quantity {index} in {QUANTITIES_FILEPATH.name} has no {key!r}."
            )
        return value.strip()

    aliases = row.get("aliases")
    if not isinstance(aliases, list) or not all(
        isinstance(alias, str) and alias.strip() for alias in aliases
    ):
        raise ValueError(
            f"Quantity {index} in {QUANTITIES_FILEPATH.name} has 'aliases' that "
            f"is not a list of non-empty strings."
        )
    ilcd = row.get("ilcd_flow_property_uuid")
    if ilcd is not None and (not isinstance(ilcd, str) or not ilcd.strip()):
        raise ValueError(
            f"Quantity {index} in {QUANTITIES_FILEPATH.name} has an "
            f"'ilcd_flow_property_uuid' that is neither null nor a uuid."
        )
    match = row.get("qudt_match")
    if not isinstance(match, dict):
        raise ValueError(
            f"Quantity {index} in {QUANTITIES_FILEPATH.name} has no 'qudt_match'. "
            f"Every quantity says which published QUDT kind it is, or narrows."
        )
    relation = str(match.get("relation") or "").strip()
    if relation not in _QUDT_RELATIONS:
        raise ValueError(
            f"Quantity {index} in {QUANTITIES_FILEPATH.name} relates to QUDT by "
            f"{relation!r}; only {' and '.join(sorted(_QUDT_RELATIONS))} are known."
        )
    iri = str(match.get("iri") or "").strip()
    if not iri.startswith("http://qudt.org/vocab/quantitykind/"):
        raise ValueError(
            f"Quantity {index} in {QUANTITIES_FILEPATH.name} names {iri!r} as its "
            f"QUDT kind, which is not under http://qudt.org/vocab/quantitykind/."
        )
    return Quantity(
        slug=text("slug"),
        label=text("label"),
        aliases=tuple(alias.strip() for alias in aliases),
        ilcd_flow_property_uuid=ilcd.strip() if isinstance(ilcd, str) else None,
        quantity_kind_iri=text("quantity_kind_iri"),
        qudt_match_relation=relation,
        qudt_match_iri=iri,
        definition=text("definition"),
    )


@lru_cache(maxsize=1)
def load_quantities() -> dict[str, Quantity]:
    """Every quantity, by slug.  Cached: the path is fixed."""
    payload = orjson.loads(QUANTITIES_FILEPATH.read_bytes())
    rows = payload.get("quantities") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        raise ValueError(f"{QUANTITIES_FILEPATH.name} has no 'quantities' list.")
    by_slug: dict[str, Quantity] = {}
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise ValueError(
                f"Quantity {index} in {QUANTITIES_FILEPATH.name} is not an object."
            )
        quantity = _as_quantity(row, index=index)
        if quantity.slug in by_slug:
            raise ValueError(
                f"{QUANTITIES_FILEPATH.name} names {quantity.slug!r} twice."
            )
        by_slug[quantity.slug] = quantity
    return by_slug


def quantity(slug: str) -> Quantity:
    """The quantity *slug* names.

    :raises KeyError: naming the slug and the file, for one the vocabulary
        does not have.  A ruling naming a quantity that does not exist is
        malformed, and a malformed ruling raises (rule 14).
    """
    try:
        return load_quantities()[slug]
    except KeyError:
        raise KeyError(
            f"{slug!r} is not a quantity {QUANTITIES_FILEPATH.name} knows. "
            f"Known: {', '.join(sorted(load_quantities()))}."
        ) from None


def quantity_for_unit(unit: str) -> str | None:
    """The quantity a flow measured in *unit* is of, when nothing says more.

    By the quantity kind `units.json` gives the unit: kilograms are a mass,
    cubic metres a volume, megajoules a calorific value of unstated basis,
    kilobecquerels a radioactivity.  ``None`` for a unit the table does not
    know or a kind no quantity here is the generic of -- an area, a count --
    which is right: nothing converts a mass onto those by a property, so a
    target in them has no quantity to ask a statement for.
    """
    row = unit_row_for(unit)
    if row is None:
        return None
    kind = str(row.get("quantity_kind_iri") or "").rsplit("/", 1)[-1]
    return _GENERIC_BY_KIND.get(kind)


#: A parenthetical qualifier on a vendor's label -- SimaPro's `Specific weight
#: (for absolutely dry, u=0%)` -- which says how the value was measured, not
#: what it measures.
_PARENTHETICAL = re.compile(r"\s*\([^)]*\)")


@lru_cache(maxsize=1)
def _by_label() -> dict[str, str]:
    index: dict[str, str] = {}
    for q in load_quantities().values():
        for spelling in (q.label, *q.aliases):
            index[" ".join(spelling.casefold().split())] = q.slug
    return index


def quantity_for_label(label: str) -> str | None:
    """The quantity a vendor's *label* names, by the vocabulary's spellings.

    `Higher heating value (HHV)` and `heating value, net` are aliases the file
    lists; `Specific weight (for absolutely dry, u=0%)` is read as `Specific
    weight` once its measurement qualifier is dropped.  Case and spacing do
    not count.  ``None`` for a label no row spells, which is how a parser
    passes over `wet mass` or `carbon content, fossil` without guessing.
    """
    text = " ".join(str(label or "").casefold().split())
    if not text:
        return None
    found = _by_label().get(text)
    if found is not None:
        return found
    stripped = " ".join(_PARENTHETICAL.sub("", text).split())
    return _by_label().get(stripped) if stripped != text else None


@lru_cache(maxsize=1)
def _by_ilcd_uuid() -> dict[str, str]:
    return {
        q.ilcd_flow_property_uuid: q.slug
        for q in load_quantities().values()
        if q.ilcd_flow_property_uuid
    }


def quantity_for_ilcd_flow_property(uuid: str) -> str | None:
    """The slug of the quantity ILCD flow property *uuid* is, or ``None``."""
    return _by_ilcd_uuid().get(str(uuid or "").strip())
