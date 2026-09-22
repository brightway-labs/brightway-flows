"""What the homepage reads from the build: three counts and one example.

Every number on the Home board is sample data from a local build; here each is
read at request time (`AGENTS.md` rule 31).  Measured on the build of
2026-09-16: under 10ms for all of it, most of that the source-list scan over
122,529 `elementary_flow_sources` rows.  No Flask import, like the other query
modules.
"""

from __future__ import annotations

import sqlite3
from collections import Counter
from dataclasses import dataclass
from typing import Any

from brightway_flows.domain.vocabulary import (
    CHEMINF_CAS_REGISTRY_NUMBER,
    CHEMROF_INCHI2D_KEY_STRING,
    CHEMROF_ISOMERIC_SMILES_STRING,
    CHEMROF_IUPAC_NAME,
    CHEMROF_MOLECULAR_FORMULA,
    CHEMROF_MOLECULAR_MASS,
    CHEMROF_SMILES_STRING,
)
from brightway_flows.webapps.app.db import table_exists
from brightway_flows.webapps.app.queries import navigation
from brightway_flows.webapps.app.queries.common import load_json
from brightway_flows.webapps.app.queries.flows import _classification_values
from brightway_flows.webapps.app.queries.substances import reference_rows


#: The registries the example card links out to, in the order it shows them
#: and under the names `labels.resource_name` gives them on the substance page.
#: Four of the dozens a substance collects: the card is an example of what one
#: identity looks like, not the substance's reference list, which is one click
#: away on the flow object page.
EXAMPLE_RESOURCES: tuple[str, ...] = (
    "ChEBI",
    "CAS Common Chemistry",
    "PubChem",
    "Wikidata",
)


def _list_label(list_name: str, list_version: str) -> str:
    """`ecoinvent 3.12`: how `filters.source_list` names a list on every other page."""
    return f"{list_name} {list_version}".strip()


@dataclass(frozen=True)
class HomeCounts:
    """`None`, or an empty tuple, where this database cannot answer."""

    flow_objects: int | None = None
    elementary_flows: int | None = None
    source_lists: tuple[str, ...] = ()


def load_counts(connection: sqlite3.Connection) -> HomeCounts:
    """The Browse panel's two counts, and every list a source row came from.

    The lists are the ones the published flows cite, not the ones a run was
    configured with: a list that contributed no row is not one this list was
    built from.
    """
    browse = navigation.load_counts(connection)
    lists: tuple[str, ...] = ()
    if table_exists(connection, "elementary_flow_sources"):
        rows = connection.execute(
            "SELECT DISTINCT list_name, list_version FROM elementary_flow_sources"
        ).fetchall()
        lists = tuple(sorted(
            (_list_label(row["list_name"] or "", row["list_version"] or "") for row in rows),
            key=str.casefold,
        ))
    return HomeCounts(
        flow_objects=browse.flow_objects,
        elementary_flows=browse.elementary_flows,
        source_lists=lists,
    )


@dataclass(frozen=True)
class Example:
    """One flow object, and how the asked-for source lists spell it.

    `source_rows` is `(list label, source flow name)` per list asked for, in
    the order asked.  `row_count` and `list_count` are over every list.
    """

    flow_object_id: str
    name: str
    cas_number: str
    inchikey: str
    source_rows: tuple[tuple[str, str], ...]
    row_count: int
    list_count: int
    #: Whether the substance carries a SMILES, and so whether
    #: `substances.structure` can draw it.  The card asks before it writes the
    #: `<img>`: the endpoint 404s for a substance with no structure, and a
    #: broken image on the homepage is worse than no diagram.
    has_structure: bool = False
    #: `(resource, url)` for each of `EXAMPLE_RESOURCES` this substance has a
    #: link to, in that order.  Empty where the build recorded none.
    links: tuple[tuple[str, str], ...] = ()
    #: What the substance is, from its ChemROF properties.  Each is shown only
    #: where the build states one value (`_settled`): a substance carrying two
    #: formulas has an unsettled structure, and a card that printed the first
    #: of them would be settling it.
    formula: str = ""
    iupac_name: str = ""
    smiles: str = ""
    #: The molar mass, under the same rule and read by `_measurements`: the
    #: vocabulary declares it `xsd:double` and the build stores it as a number
    #: rather than a string, which is that reader's reason for existing.
    molecular_mass: str = ""


def load_example(
    connection: sqlite3.Connection,
    flow_object_id: str,
    lists: tuple[tuple[str, str], ...],
) -> Example | None:
    """*flow_object_id* as the homepage card draws it, or `None`.

    `None` when the build has no such flow object, and when any of *lists*
    has no row for it: the card's point is that several lists name one flow,
    and with a list missing it would be making it with one.

    A list can spell one flow several ways (EF 3.1 writes "carbon dioxide
    (fossil)" fourteen times and "Carbon dioxide (fossil)" once); the card
    shows the spelling it uses most.
    """
    if not table_exists(connection, "elementary_flow_sources"):
        return None
    found = connection.execute(
        "SELECT pref_label_value, classifications_json, properties_json, "
        "references_json FROM flow_objects WHERE flow_object_id = ?",
        (flow_object_id,),
    ).fetchone()
    if found is None:
        return None

    rows = connection.execute(
        "SELECT s.list_name, s.list_version, s.source_flow_name "
        "FROM elementary_flows ef "
        "JOIN elementary_flow_sources s ON s.elementary_flow_uuid = ef.uuid "
        "WHERE ef.flow_object_id = ?",
        (flow_object_id,),
    ).fetchall()
    spellings: dict[tuple[str, str], Counter[str]] = {}
    for row in rows:
        key = (row["list_name"] or "", row["list_version"] or "")
        spellings.setdefault(key, Counter())[row["source_flow_name"] or ""] += 1

    source_rows = []
    for key in lists:
        counts = spellings.get(key)
        if not counts:
            return None
        name = min(counts, key=lambda spelling: (-counts[spelling], spelling))
        source_rows.append((_list_label(*key), name))

    properties = load_json(found["properties_json"], {})
    cas = _classification_values(load_json(found["classifications_json"], {}),
                                 CHEMINF_CAS_REGISTRY_NUMBER)
    inchikey = _classification_values(properties, CHEMROF_INCHI2D_KEY_STRING)
    smiles = (_classification_values(properties, CHEMROF_ISOMERIC_SMILES_STRING)
              + _classification_values(properties, CHEMROF_SMILES_STRING))
    return Example(
        flow_object_id=flow_object_id,
        name=found["pref_label_value"] or "",
        cas_number=cas[0] if cas else "",
        inchikey=inchikey[0] if inchikey else "",
        source_rows=tuple(source_rows),
        row_count=len(rows),
        list_count=len(spellings),
        has_structure=bool(smiles),
        links=_links(load_json(found["references_json"], []), cas[0] if cas else ""),
        formula=_settled(_classification_values(properties, CHEMROF_MOLECULAR_FORMULA)),
        iupac_name=_settled(_classification_values(properties, CHEMROF_IUPAC_NAME)),
        smiles=_settled(smiles),
        molecular_mass=_settled(_measurements(properties, CHEMROF_MOLECULAR_MASS)),
    )


def _settled(values: list[str]) -> str:
    """The one value *values* holds, or `""` where it holds none or several.

    `property_value` renders a list as a list on the flow object page, which is
    the right answer for a table a curator is reading.  On the card there is
    one line and no room to say "or", so a property the build has not settled
    is left out rather than shown as the first of its candidates.

    The molar mass is under this rule too.  101 flow objects state two of them
    in the build of 2026-09-20, and half of those pairs are not one number
    rounded twice: `Aluminum Tributan-2-olate` carries 101.105 and 246.327, and
    `4-{[(2-methoxyphenyl)formamido]sulfonyl}benzoyl Chloride` carries 353.783
    and its double.  A card printing the first of two would be answering a
    question the build has not.
    """
    return values[0] if len(values) == 1 else ""


def _measurements(properties: Any, iri: str) -> list[str]:
    """The `@value` list under *iri*, as strings, numbers included.

    `_classification_values` keeps only strings, which is right for every
    other property the card reads: a formula, an InChIKey and a SMILES are
    text, and a number under one of those keys is a defect rather than a
    value to render.  The molar mass is the exception -- the vocabulary
    declares it `xsd:double` and the build stores it as a JSON number, so
    reading it the same way returned nothing and the card printed no mass for
    any substance.

    Stringified rather than formatted: these are the build's numbers and the
    card states them as it finds them, as it does with every other fact on it.
    """
    entry = properties.get(iri) if isinstance(properties, dict) else None
    if not isinstance(entry, dict):
        return []
    raw = entry.get("@value")
    values = raw if isinstance(raw, list) else [raw]
    out = []
    for value in values:
        if isinstance(value, str) and value.strip():
            out.append(value)
        elif isinstance(value, (int, float)) and not isinstance(value, bool):
            out.append(str(value))
    return out


def _links(references: Any, cas_number: str = "") -> tuple[tuple[str, str], ...]:
    """`(resource, url)` for each of `EXAMPLE_RESOURCES` *references* names.

    One link per registry, the first the substance page would list under that
    name: a substance with two ChEBI identifiers has two ChEBI URLs, and the
    card is showing that this identity is the one those registries hold, not
    how many rows it took to say so.

    Except that *which* of them is shown cannot be left to the page's ordering
    where the card is also printing a registry number.  Hexafluoroethane
    collects two CAS Common Chemistry URLs, `60720-23-2` and its own
    `76-16-4`, and the page's order -- by resource, then by URL -- puts the
    other number first.  The card would then have stated one number and linked
    another, which is the exact confusion it exists to clear up, so a URL
    carrying *cas_number* wins its registry.
    """
    by_resource: dict[str, str] = {}
    for row in reference_rows(references):
        if not row.is_link:
            continue
        if row.resource not in by_resource:
            by_resource[row.resource] = row.url
        elif cas_number and cas_number in row.url:
            by_resource[row.resource] = row.url
    return tuple(
        (resource, by_resource[resource])
        for resource in EXAMPLE_RESOURCES
        if resource in by_resource
    )
