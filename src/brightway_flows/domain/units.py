"""Unit strings, canonical notations, and the minted unit IRIs.

Lives in ``domain`` rather than beside the transformer that was its only caller,
because it is now also read where a published node needs a unit IRI -- and
``transformers.unit_normalization`` imports ``Transformer`` from ``pipeline``,
so a ``pipeline`` module importing it closes a cycle.  Nothing here depends on
anything but ``units.json``.
"""

from __future__ import annotations

import math
from functools import lru_cache
from typing import Any

import orjson
from brightway_flows.filesystem import PACKAGE_DATA_DIR

UNITS_FILEPATH = PACKAGE_DATA_DIR / "units.json"

# Aliases from normalized input token → canonical notation in units.json.
# Normalized means: lowercased, spaces removed, · and * replaced by .
# Only include aliases that do NOT require a numeric multiplier.
UNIT_ALIASES: dict[str, str] = {
    # Mole variants
    "mol": "mole",
    # Count / items
    "item": "#",
    "item(s)": "#",
    "piece": "#",
    "pieces": "#",
    # Mass
    "kilogram": "kg",
    "kilograms": "kg",
    # Volume
    "litre": "l",
    "liter": "l",
    "litres": "l",
    "liters": "l",
    "m³": "m3",
    "cubicmetre": "m3",
    "cubicmeter": "m3",
    # Transport
    "tkm": "t.km",
    "ton.km": "t.km",
    # Mass-time: kg*a and kg*yr both normalise to kg.a via _normalize_unit_token
    # (which replaces * with .), so only kg.yr needs an explicit alias.
    "kg.yr": "kg.a",
    # Area-time: m2*year → m2.a
    "m2.year": "m2.a",
    # Volume-time: m3*year → m3.a
    "m3.year": "m3.a",
    # Separator-free spellings.  A correspondence table renders both sides of a
    # mapping in its own house style, and GLAD's has no separator at all: EF
    # 3.1's own `m2*a` reaches it as `m2yr` and SimaPro's as `m2a`.  Without
    # these the source concept for 1,556 GLAD rows shipped with no
    # `qudt:hasUnit` -- a unit both lists agree on, dropped over punctuation.
    "m2yr": "m2.a",
    "m2a": "m2.a",
    "kgy": "kg.a",
    # BAFU's ecoSpold v1 writes the same three without separators.  `m3y` is
    # `Volume occupied, reservoir` -- reservoir volume held over time, the
    # volume analogue of land occupation -- and `personkm` is the two noise
    # flows, aircraft and passenger rail, whose intensity is per passenger
    # carried per kilometre.  Both notations are already in `units.json` as
    # `m3.a` and `p.km`; only the spelling was missing, exactly as with `m2a`.
    "m3y": "m3.a",
    "personkm": "p.km",
    # Stepwise 2006's SimaPro method export writes the hectare-year with a
    # space, which `_normalize_unit_token` closes up to `haa` -- the same
    # separator-free habit as `m2a`, on the two occupation flows the method
    # states in hectares rather than square metres.
    "haa": "ha.a",
    # SimaPro's `ton` is the metric tonne: its own unit table defines it as
    # 1000 kg, and the seven Stepwise rows carrying it are carbon dioxide and
    # its companions, written a tonne at a time where the rest of the list is
    # kilograms.  Neither the short (907.18 kg) nor the long ton (1016.05 kg)
    # is ever meant, so this is a spelling rather than a conversion.
    "ton": "t",
    "tonne": "t",
    "tonnes": "t",
    # SimaPro writes a counted thing as `p`, which is `#` here: Stepwise's
    # three injury flows are counts of injuries.
    "p": "#",
    # Currency: EUR2005 is the same currency unit as EUR (year suffix is a vintage label)
    "eur2005": "EUR",
    # EUR2003 is Stepwise 2006's, whose economic flows and weighting are stated
    # in it.  Same reading as EUR2005: the year is the vintage the method's
    # prices are quoted at, not a different currency.
    "eur2003": "EUR",
    # Gas volume.  For gas a normal cubic metre and a standard cubic metre are
    # the same quantity -- both 15.00 C (288.15 K) at 101.325 kPa -- so this is
    # a spelling, not a conversion, and belongs here rather than in a
    # multiplier.  The other reading of `Nm3`, 0 C per DIN 1343, is the general
    # industrial convention; gas is the only substance the notation appears on
    # in these lists, on BAFU's natural gas and its coal-mine off-gas.  See
    # #292, and #291 for what believing the 0 C reading cost.
    "nm3": "sm3",
}


def _normalize_unit_token(value: str) -> str:
    """Lowercase, remove spaces, replace · and * with ."""
    token = value.strip().lower()
    token = token.replace("·", ".").replace("*", ".")
    token = token.replace(" ", "")
    return token


def build_units_index() -> dict[str, dict[str, Any]]:
    """Load units.json and return a normalized-token → row mapping."""
    data = orjson.loads(UNITS_FILEPATH.read_bytes())
    by_notation: dict[str, dict[str, Any]] = {}
    for row in data:
        notation = row.get("notation")
        label = row.get("label")
        if isinstance(notation, str) and notation.strip():
            tok = _normalize_unit_token(notation)
            by_notation[tok] = row
        if isinstance(label, str) and label.strip():
            tok = _normalize_unit_token(label)
            if tok not in by_notation:
                by_notation[tok] = row
    return by_notation


def resolve_unit_notation(
    unit: str, by_notation: dict[str, dict[str, Any]]
) -> tuple[str, str] | None:
    """Return ``(canonical_notation, unit_iri)`` or ``None`` if unresolved.

    Reusable outside the transformer class.
    """
    tok = _normalize_unit_token(unit)
    if tok in UNIT_ALIASES:
        canon_tok = _normalize_unit_token(UNIT_ALIASES[tok])
        row = by_notation.get(canon_tok)
        if row:
            return row["notation"], row.get("iri") or ""
    row = by_notation.get(tok)
    if row is not None:
        return row["notation"], row.get("iri") or ""
    return None


#: Built once: `units.json` is small but the source-concept nodes resolve a unit
#: per mapping, and there are tens of thousands of those.
_UNITS_INDEX_CACHE: dict[str, dict[str, Any]] | None = None


def unit_iri_for(unit: str) -> str:
    """The minted unit IRI for a source list's unit string, or ``""``.

    Source lists give a unit as text -- ``"kg"``, ``"m3"`` -- and a published
    node needs the IRI, because `qudt:hasUnit` ranges over `qudt:Unit` and a
    bare string is not one.  Returns ``""`` for a unit `units.json` does not
    know, so the caller can leave the statement out rather than make a false one.
    """
    global _UNITS_INDEX_CACHE
    if _UNITS_INDEX_CACHE is None:
        _UNITS_INDEX_CACHE = build_units_index()
    resolved = resolve_unit_notation(unit, _UNITS_INDEX_CACHE)
    return resolved[1] if resolved else ""


def unit_row_for(unit: str) -> dict[str, Any] | None:
    """The `units.json` row for a source list's unit string, or None.

    The whole row rather than one field of it, because the question a caller
    usually has takes three of them at once: whether two units measure the same
    kind of quantity (`quantity_kind_iri`), whether they are spellings of one
    scale (`reference_unit_iri`), and how far apart on it they sit
    (`conversion_multiplier`).  :func:`unit_iri_for` is the narrower form for
    the one caller that needs only the identifier.
    """
    global _UNITS_INDEX_CACHE
    if _UNITS_INDEX_CACHE is None:
        _UNITS_INDEX_CACHE = build_units_index()
    token = _normalize_unit_token(unit)
    row = _UNITS_INDEX_CACHE.get(token)
    if row is None and (alias := UNIT_ALIASES.get(token)):
        row = _UNITS_INDEX_CACHE.get(_normalize_unit_token(alias))
    return row


def canonical_unit(
    unit: str, units_index: dict[str, dict[str, Any]] | None = None
) -> str:
    """*unit* in canonical notation, or unchanged if `units.json` lacks it.

    An unresolvable unit is compared as it arrived rather than raising: the
    merge already refuses a *source* unit it cannot normalise, and a target
    unit the units table does not know is a reason to report the pair, not to
    stop the run.

    Lives here rather than in `merge.unit_changes`, which was its only caller,
    for the reason this module exists at all: two units are compared wherever a
    source row meets the flow it landed on, and the LCIA passes do that too --
    `lcia.substance_matching` is handed a publisher's raw ``m2*a`` against a
    flow this list publishes per ``m2.a``.  *units_index* stays available for
    the merge, which builds one for a whole run; omit it and the cached index
    :func:`unit_row_for` uses answers instead.
    """
    if not unit:
        return ""
    global _UNITS_INDEX_CACHE
    if units_index is None:
        if _UNITS_INDEX_CACHE is None:
            _UNITS_INDEX_CACHE = build_units_index()
        units_index = _UNITS_INDEX_CACHE
    resolved = resolve_unit_notation(unit, units_index)
    return resolved[0] if resolved else unit


@lru_cache(maxsize=None)
def known_unit_iris() -> frozenset[str]:
    """Every unit IRI `units.json` mints.

    For a caller that already holds an IRI and needs to know whether it names a
    unit -- the impact-category crosswalk states its reference unit that way,
    because both LCIA publishers write theirs as text and neither text is an
    identifier.  A membership test, so this is a set rather than an index
    (rule 13).
    """
    return frozenset(
        str(row["iri"])
        for row in orjson.loads(UNITS_FILEPATH.read_bytes())
        if row.get("iri")
    )


def unit_table_factor(source_unit: str, target_unit: str) -> float | None:
    """What `units.json` alone converts *source_unit* to *target_unit* by.

    None when it says nothing: either unit unknown, different quantity kinds, or
    the same quantity kind reached through different reference units, where the
    stored multipliers are not on one scale and dividing them would invent a
    number.  `Nm3` used to be that last case, stated against `sm3` whose own
    reference is `mol`; it is an alias of `sm3` now (#292) and the file has no
    two-hop row left, but the branch stays because it is what makes the next one
    safe.
    """
    source_row = unit_row_for(source_unit)
    target_row = unit_row_for(target_unit)
    if source_row is None or target_row is None:
        return None
    if source_row.get("quantity_kind_iri") != target_row.get("quantity_kind_iri"):
        return None
    if source_row.get("reference_unit_iri") != target_row.get("reference_unit_iri"):
        return None
    source_multiplier = source_row.get("conversion_multiplier")
    target_multiplier = target_row.get("conversion_multiplier")
    if not isinstance(source_multiplier, (int, float)):
        return None
    if not isinstance(target_multiplier, (int, float)) or not target_multiplier:
        return None
    return float(source_multiplier) / float(target_multiplier)


def states_more_than_the_unit_table(
    source_unit: str, target_unit: str, factor: float
) -> bool:
    """Whether *factor* says anything `units.json` does not already say.

    True when the unit table has no answer for the pair, and true when it has
    one that disagrees -- a mineral's elemental content is stated between two
    units the table converts at 1.0, and 0.599 is not 1.0.
    """
    implied = unit_table_factor(source_unit, target_unit)
    if implied is None:
        return True
    return not math.isclose(factor, implied, rel_tol=1e-9)
