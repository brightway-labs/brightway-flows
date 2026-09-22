"""`/search`: what one box finds among the flows and the flow objects.

`plans/public-site.md` §3, Search.  The documentation half is in
`documentation.search`, which reads files rather than this database.

Wraps the list pages' own queries rather than writing a third search, so a
count here and the page its "All N →" link opens are the same query: the flow
objects are `substances.substance_page` and the elementary flows are
`flows.flow_page`, deprecated flows excluded as that page excludes them.

What the wrapping adds is the query itself.  FTS5 reads `124-38-9` as syntax --
the hyphen is not a word character to it -- so both list pages fall back to a
substring search over names and find nothing for a CAS number, which is the
identifier a reader is most likely to paste.  `fts_terms` quotes each word
FTS5 would misread, and the links carry the quoted form, so the list page they
open counts what this page counted.

And the identifiers.  A current flow's UUID is a redirect; a CAS number or an
InChIKey is never one, because one registry number is recorded on several flow
objects -- carbon dioxide's on nine in the build of 2026-09-16 -- and choosing
one of them would be the search deciding something the list does not
(decision 3).  Those get `exact_match` instead.
"""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass, field
from typing import Literal

from brightway_flows.domain.vocabulary import (
    CHEMINF_CAS_REGISTRY_NUMBER,
    CHEMROF_INCHI2D_KEY_STRING,
)
from brightway_flows.webapps.app.queries.common import Page, load_json
from brightway_flows.webapps.app.queries.flows import (
    FlowFilters,
    FlowRow,
    _classification_values,
    flow_page,
)
from brightway_flows.webapps.app.queries.substances import (
    _LINKED_FLOWS,
    SubstanceRow,
    substance_page,
)

#: A query longer than this is cut to it before anything reads it (§4).  No
#: name in the list comes near it, and FTS5's cost grows with every word.
MAX_QUERY_LENGTH = 200

IdentifierKind = Literal["uuid", "cas", "inchikey"]

_UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.I)
#: Two to seven digits, two, one: the registry's own format.  The check digit
#: is not verified -- a number that fails it is still what a source list wrote.
_CAS = re.compile(r"\d{2,7}-\d{2}-\d")
#: Upper case only, as every InChIKey is written.  A lower-case one is somebody
#: typing words, and gets a text search.
_INCHIKEY = re.compile(r"[A-Z]{14}-[A-Z]{10}-[A-Z]")

#: A word FTS5 reads as a word: letters, digits and underscores, with a prefix
#: `*` at the end.  `\w` also admits letters outside ASCII, which FTS5 treats
#: as word characters too.
_BAREWORD = re.compile(r"\w+\*?")
_OPERATORS = frozenset({"AND", "OR", "NOT", "NEAR"})

#: The Exact match card's label for each kind of registry number.
_LABELS: dict[str, str] = {"cas": "CAS number", "inchikey": "InChIKey"}


def normalise(raw: str) -> str:
    """The query as searched: whitespace collapsed, cut to `MAX_QUERY_LENGTH`."""
    return " ".join(str(raw or "").split())[:MAX_QUERY_LENGTH].strip()


def identifier_kind(query: str) -> IdentifierKind | None:
    """Which identifier *query* is, if it is one and nothing else."""
    if _UUID.fullmatch(query):
        return "uuid"
    if _CAS.fullmatch(query):
        return "cas"
    if _INCHIKEY.fullmatch(query):
        return "inchikey"
    return None


def fts_terms(query: str) -> str:
    """*query* with each word FTS5 would misread quoted as a phrase.

    `124-38-9` becomes `"124-38-9"`, which FTS5 tokenises into the phrase
    `124 38 9` and finds.  A word that is already a word is left alone, so
    "carbon dioxide" is exactly what the list pages have always searched for.
    So are `AND`, `OR` and `NOT`: a query using them is a reader writing FTS5,
    and `carbon AND` is left to fail and fall back as it does on the list pages
    (§4) rather than being turned into a search for the word "AND".
    """
    terms = []
    for word in query.split():
        if word in _OPERATORS or _BAREWORD.fullmatch(word):
            terms.append(word)
        else:
            terms.append('"' + word.replace('"', '""') + '"')
    return " ".join(terms)


def flow_objects(
    connection: sqlite3.Connection, query: str, *, page: int = 1
) -> Page[SubstanceRow]:
    """The flow objects `/flow-objects/?q=` lists for `fts_terms(query)`."""
    return substance_page(connection, query=fts_terms(query), page=page)


def elementary_flows(
    connection: sqlite3.Connection, query: str, *, page: int = 1
) -> Page[FlowRow]:
    """The current elementary flows `/flows/?q=` lists for `fts_terms(query)`."""
    return flow_page(connection, FlowFilters(query=fts_terms(query)), page=page)


def current_flow(connection: sqlite3.Connection, query: str) -> str | None:
    """The UUID of the current elementary flow *query* names, or `None`.

    Not a deprecated one (§4): a deprecated flow has been replaced, and
    opening it from a search would send a reader to the row they should not
    use.  Their search is an ordinary one, which will say no results.
    """
    if identifier_kind(query) != "uuid":
        return None
    row = connection.execute(
        "SELECT uuid FROM elementary_flows WHERE uuid IN (?, ?) AND is_deprecated = 0",
        (query, query.lower()),
    ).fetchone()
    return row["uuid"] if row else None


@dataclass
class ExactMatch:
    """A registry number, and every flow object that records it.

    `objects` is ordered by how many current elementary flows each carries,
    most first: the substance a reader most likely meant is the one most
    source lists name.
    """

    label: str
    identifier: str
    objects: list[SubstanceRow] = field(default_factory=list)


def _cas_candidates(connection: sqlite3.Connection, cas: str) -> list[sqlite3.Row]:
    """Flow objects whose CAS numbers might include *cas*, cheaply.

    The `cas_numbers` column of `flow_objects_fts` when there is one; a
    substring scan of the classifications when there is not.  Either way the
    caller checks the stored values, because both can over-match.
    """
    try:
        return connection.execute(
            "SELECT fo.flow_object_id, fo.classifications_json AS payload "
            "FROM flow_objects fo WHERE fo.flow_object_id IN ("
            "SELECT flow_object_id FROM flow_objects_fts WHERE flow_objects_fts MATCH ?)",
            (f'cas_numbers:"{cas}"',),
        ).fetchall()
    except sqlite3.OperationalError:
        return connection.execute(
            "SELECT flow_object_id, classifications_json AS payload FROM flow_objects "
            "WHERE instr(classifications_json, ?) > 0",
            (cas,),
        ).fetchall()


def _inchikey_candidates(
    connection: sqlite3.Connection, inchikey: str
) -> list[sqlite3.Row]:
    """Flow objects whose properties mention *inchikey* anywhere.

    InChIKeys are in neither FTS table (`pipeline/sqlite.py`), so this reads
    `properties_json` for every flow object.  Measured on the build of
    2026-09-16 before choosing it over a new column: 35ms over 8,158 flow
    objects, and it runs only for a query shaped like an InChIKey.  A column
    would be a change to the SQLite writer and a rebuild before search worked.
    """
    return connection.execute(
        "SELECT flow_object_id, properties_json AS payload FROM flow_objects "
        "WHERE instr(properties_json, ?) > 0",
        (inchikey,),
    ).fetchall()


def exact_match(connection: sqlite3.Connection, query: str) -> ExactMatch | None:
    """The flow objects that record *query* as a CAS number or an InChIKey.

    `None` for any other query, and for a registry number no flow object
    records (§4): no card, and the ordinary results say what they say.
    """
    kind = identifier_kind(query)
    if kind == "cas":
        candidates, predicate = _cas_candidates(connection, query), CHEMINF_CAS_REGISTRY_NUMBER
    elif kind == "inchikey":
        candidates, predicate = _inchikey_candidates(connection, query), CHEMROF_INCHI2D_KEY_STRING
    else:
        return None

    ids = [
        row["flow_object_id"]
        for row in candidates
        if query in _classification_values(load_json(row["payload"], {}), predicate)
    ]
    if not ids:
        return None

    placeholders = ", ".join("?" * len(ids))
    rows = connection.execute(
        "SELECT fo.flow_object_id, fo.pref_label_value, fo.flow_type, "
        f"fo.origin_qualifier, {_LINKED_FLOWS} AS linked_flows "
        f"FROM flow_objects fo WHERE fo.flow_object_id IN ({placeholders})",
        ids,
    ).fetchall()
    objects = [
        SubstanceRow(
            flow_object_id=row["flow_object_id"],
            name=row["pref_label_value"] or "",
            flow_type=row["flow_type"] or "",
            origin_qualifier=row["origin_qualifier"] or "",
            linked_flows=int(row["linked_flows"] or 0),
        )
        for row in rows
    ]
    objects.sort(key=lambda row: (-row.linked_flows, row.name.lower(), row.flow_object_id))
    return ExactMatch(label=_LABELS[kind], identifier=query, objects=objects)
