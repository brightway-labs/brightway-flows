"""Quantities the source lists report that are not substances.

``Chemical Oxygen Demand`` is a mass of oxygen a laboratory's oxidant would
consume, ``Benzene (as BTEX)`` is four compounds reported as though they were
one, ``Particles (PM2.5)`` is everything below an aerodynamic diameter.  None
names a chemical entity, and every one of them arrives in a list of substances
looking like one.

**Curated, not matched by pattern.**  The obvious rule is to read ``X as Y`` or
``, total`` out of the label, and this project had one: a regex that assigned no
class and recorded ``aggregate_measurement_not_a_substance`` as a reason.  It
worked on the thirteen names it was written against and was already wrong on
the ones beside them -- ``Alkoxylation Reaction Product of Glycerin as Starter``
is a molecule, ``Occup. as Forest Land`` is land use, ``Acid (as H+)`` was typed
`NeutralMolecule` from the hydron's CAS and never reached the regex at all.  A
pattern over labels is a guess that gets more expensive with every list added.
Each entry in ``aggregate-measurements.json`` is instead a decision about one
named quantity with its reason beside it (#68).

Names match case- and whitespace-insensitively -- BAFU writes ``as Cl`` where
the preferred label reads ``As Cl`` -- against the preferred label first and the
alternative labels second, so both a source's own spelling and the harmonised
one hit.  Which label matched is recorded on the object; a match through an
alternative label is the one that would be worth looking at.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import Any

import orjson

from brightway_flows.domain.labels import canonical_label_value
from brightway_flows.filesystem import PACKAGE_DATA_DIR

DATA_DIR = PACKAGE_DATA_DIR

#: The curated decisions.  Hand-maintained, unlike `environmental-materials.json`
#: next to it, because there is nothing to generate it from: each entry is a
#: judgement about what a source list meant by a name.
MEASUREMENTS_FILEPATH = DATA_DIR / "aggregate-measurements.json"


@dataclass(frozen=True)
class AggregateMeasurement:
    """One curated quantity, and what it is reported in terms of."""

    id: str
    label: str
    definition: str
    names: tuple[str, ...]
    #: Preferred label of the substance the number is expressed as -- ``Oxygen``
    #: for COD, ``Benzene`` for BTEX.  ``None`` where naming one would be wrong
    #: rather than merely unknown: acidity's proton is not the element hydrogen.
    expressed_as: str | None
    #: Preferred label of the grouping class whose members it counts.  Only AOX
    #: has one today, because only AOX's members are carried as a class.
    sums_over: str | None
    comment: str


@lru_cache(maxsize=None)
def aggregate_measurements() -> tuple[AggregateMeasurement, ...]:
    """The curated quantities, in file order.

    :raises FileNotFoundError: if the file is absent.  Not optional: without it
        every quantity here falls through to the chemistry rules, which is the
        state #68 describes, and an empty mapping would look like a clean run.
    """
    if not MEASUREMENTS_FILEPATH.exists():
        raise FileNotFoundError(
            f"Aggregate-measurement decisions not found at {MEASUREMENTS_FILEPATH}."
        )
    payload = orjson.loads(MEASUREMENTS_FILEPATH.read_bytes())
    return tuple(
        AggregateMeasurement(
            id=str(entry["id"]),
            label=str(entry["label"]),
            definition=str(entry["definition"]),
            names=tuple(str(name) for name in entry["names"]),
            expressed_as=_optional(entry.get("expressed_as")),
            sums_over=_optional(entry.get("sums_over")),
            comment=str(entry.get("comment") or ""),
        )
        for entry in payload["measurements"]
    )


def _optional(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


@lru_cache(maxsize=None)
def _by_canonical_name() -> dict[str, AggregateMeasurement]:
    """Every curated name, normalised, to the quantity that claims it.

    A name claimed twice is a curation error rather than an ambiguity to
    resolve at runtime -- two quantities cannot both be what a source meant --
    so it raises here, where the file is read, instead of letting whichever
    entry happened to be last silently win.
    """
    index: dict[str, AggregateMeasurement] = {}
    for measurement in aggregate_measurements():
        for name in measurement.names:
            key = canonical_label_value(name)
            claimed = index.get(key)
            if claimed is not None and claimed.id != measurement.id:
                raise ValueError(
                    f"{MEASUREMENTS_FILEPATH.name}: {name!r} is claimed by both "
                    f"{claimed.id!r} and {measurement.id!r}."
                )
            index[key] = measurement
    return index


def measurement_for_name(name: str) -> AggregateMeasurement | None:
    """The quantity *name* names, or ``None``.

    Exact after normalisation, never a substring: ``Benzene`` must not match
    ``Benzene (as BTEX)`` in either direction, and a containment test is how
    that happens.
    """
    return _by_canonical_name().get(canonical_label_value(name or ""))
