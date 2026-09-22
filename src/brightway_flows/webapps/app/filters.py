"""Jinja filters shared by every page.

Small and few on purpose.  The applications this replaces format numbers and
timestamps inline in each template, so the same quantity renders three ways on
three pages; these are the formats, defined once.
"""

from __future__ import annotations

import re
from datetime import datetime
from functools import lru_cache
from typing import Any

import orjson
from flask import Flask
from markupsafe import Markup, escape

from brightway_flows.domain.vocabulary import (
    QUDT_CONVERSION_MULTIPLIER_CURIE,
    SKOS_BROAD_MATCH_CURIE,
    SKOS_CLOSE_MATCH_CURIE,
    SKOS_EXACT_MATCH_CURIE,
    SKOS_NARROW_MATCH_CURIE,
    SKOS_PREF_LABEL_CURIE,
    SKOS_RELATED_MATCH_CURIE,
    XKOS_SOURCE_CONCEPT_CURIE,
)
from brightway_flows.sources import base_source_list, known_source_lists
from brightway_flows.webapps.app.labels import local_name as _local_name
from brightway_flows.webapps.app.labels import type_label as _type_label


def thousands(value: Any) -> str:
    """A count, grouped.  `None` renders as an em dash, not as zero.

    The difference matters on the overview: a table this database does not have
    is not a table with nothing in it.
    """
    if value is None:
        return "—"
    try:
        return f"{int(value):,}"
    except (TypeError, ValueError):
        return str(value)


def amount(value: Any) -> str:
    """A characterisation factor, at a precision a reader can compare.

    Factors span sixteen orders of magnitude -- `1.5458e-09` for a
    non-cancer toxicity and `6,297,400` for a freshwater ecotoxicity, in the
    same table -- so neither fixed decimals nor plain scientific notation reads
    well for both.  Anything a person can read as a number stays one; the rest
    goes to four significant figures in exponent form.

    A stated zero is `0` and not `0.0000`: #47 kept those because "assessed,
    and zero" is not "never assessed", and it should look like a decision.
    """
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value if value is not None else "—")
    if number == 0:
        return "0"
    magnitude = abs(number)
    if magnitude >= 1e6 or magnitude < 1e-3:
        return f"{number:.4e}"
    text = f"{number:,.6f}".rstrip("0").rstrip(".")
    return text or "0"


def ratio(value: Any) -> str:
    """How far apart two implementations are, as `1,441×`.

    `None` is an em dash rather than a zero or a one: a relative difference
    across zero or a sign change is not defined, and rendering it as a number
    would invent a comparison the report deliberately refuses to make.
    """
    if value is None:
        return "—"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    if number < 1.01:
        # A rounding rather than a disagreement -- `1x` would hide the whole
        # point of the within-tolerance band, which is that the two numbers are
        # one number written twice.
        return f"{number:.4f}×"
    if number < 10:
        return f"{number:,.3g}×"
    return f"{number:,.0f}×"


def stated_amounts(value: Any) -> dict[str, Any]:
    """A row's stated numbers, keyed by the implementation that states them.

    The queue payload holds them as a list -- a question about three
    implementations is the same question as one about two, and a payload with a
    key per source list could not hold it -- and a table cell wants a lookup.
    """
    if not isinstance(value, list):
        return {}
    return {
        str(entry.get("implemented_by") or ""): entry.get("amount")
        for entry in value
        if isinstance(entry, dict)
    }


def timestamp(value: Any) -> str:
    """An ISO timestamp as `YYYY-MM-DD HH:MM UTC`.

    Anything unparseable renders unchanged rather than as an error: the column
    holds whatever the run wrote, and showing it is more use than hiding it.
    """
    text = str(value or "").strip()
    if not text:
        return "—"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return text
    return parsed.strftime("%Y-%m-%d %H:%M UTC")


def queue_label(value: Any) -> str:
    """A queue's URL segment as a heading: `ec-cross-check` -> `EC cross check`.

    The segment is the identity, so it stays lower-case and hyphenated in URLs
    and in the database; this is only how it is read aloud.
    """
    text = str(value or "").replace("-", " ").replace("_", " ").strip()
    if not text:
        return ""
    words = [
        word.upper() if word in {"ec", "cas", "chebi", "lcia"} else word
        for word in text.split()
    ]
    first, *rest = words
    return " ".join([first if first.isupper() else first.capitalize(), *rest])


def pretty_json(value: Any) -> str:
    """A payload as indented JSON, for a `<details>` block.

    Not syntax-highlighted. The consensus app ran every detail page's full
    record through Pygments, which for a flow carrying a large property set was
    most of the page's render time -- and the reader who opens that block is
    copying it out, not reading it.
    """
    try:
        return orjson.dumps(value, option=orjson.OPT_INDENT_2).decode()
    except TypeError:
        return str(value)


_SOURCE_CONCEPT = _local_name(XKOS_SOURCE_CONCEPT_CURIE)
_PREF_LABEL = _local_name(SKOS_PREF_LABEL_CURIE)
_CONVERSION_MULTIPLIER = _local_name(QUDT_CONVERSION_MULTIPLIER_CURIE)
_MATCH_PROPERTIES = frozenset(
    _local_name(curie) for curie in (
        SKOS_EXACT_MATCH_CURIE,
        SKOS_CLOSE_MATCH_CURIE,
        SKOS_BROAD_MATCH_CURIE,
        SKOS_NARROW_MATCH_CURIE,
        SKOS_RELATED_MATCH_CURIE,
    )
)


def _term(node: Any, name: str) -> Any:
    """What *node* carries under *name*, whichever spelling of the key it used."""
    if not isinstance(node, dict):
        return None
    for key, value in node.items():
        if _local_name(key) == name:
            return value
    return None


@lru_cache(maxsize=1)
def _list_names_by_iri_prefix() -> tuple[tuple[str, str], ...]:
    """Every registered list's minted flow-IRI prefix, and how to name it.

    Read from the source registry rather than written out here: the prefix is
    declared in one manifest per list and cannot change once that list has
    shipped, so a second copy of it would be a second thing to keep right.  The
    base list is included -- it is where most associations point -- which
    `known_source_lists` deliberately leaves out.
    """
    lists = [*known_source_lists().values(), base_source_list()]
    return tuple(
        (source.flow_iri_prefix, f"{source.list_name} {source.list_version}")
        for source in lists
        if source.flow_iri_prefix
    )


def source_concept_iri(association: Any) -> str:
    """The `@id` of the source flow an association is about."""
    return str(_term(_term(association, _SOURCE_CONCEPT), "@id") or "")


def source_list(association: Any) -> str:
    """Which list the associated flow comes from, as `ecoinvent 3.12`.

    Read off the source concept's IRI, because that is the only place it is: an
    association names the flow it maps by the IRI that flow's list mints, and
    carries no field spelling the list out.  The column asked for `source_list`
    and then `list_name`, neither of which any association has ever had, so
    every row on every flow page printed an em dash.

    An IRI no registered prefix claims -- a database written while a list was
    minting a different one -- falls back to the two path segments a prefix is
    made of, which is where the name and the version are.
    """
    iri = source_concept_iri(association)
    if not iri:
        return ""
    for prefix, name in _list_names_by_iri_prefix():
        if iri.startswith(prefix):
            return name
    parts = [part for part in iri.split("/") if part]
    return " ".join(parts[-4:-2]) if len(parts) >= 4 else ""


def source_flow_uuid(association: Any) -> str:
    """The associated flow's identifier in its own list: the IRI's last segment."""
    return source_concept_iri(association).rsplit("/", 1)[-1]


def source_flow_name(association: Any) -> str:
    """What the associated flow is called in its own list."""
    label = _term(_term(association, _SOURCE_CONCEPT), _PREF_LABEL)
    if isinstance(label, dict):
        return str(label.get("@value") or "")
    if isinstance(label, list):
        return ", ".join(
            str(entry.get("@value") if isinstance(entry, dict) else entry)
            for entry in label
        )
    return "" if label is None else str(label)


def source_flow_context(association: Any) -> str:
    """The compartment the associated flow sits in, as its own list writes it."""
    context = _term(_term(association, _SOURCE_CONCEPT), "context")
    if isinstance(context, list):
        return " / ".join(str(part) for part in context if part)
    return "" if context is None else str(context)


def conversion_multiplier(association: Any) -> str:
    """How many of the source list's units make one of this flow's.

    Carried by the association itself rather than by either concept, and only
    where the two lists state different units, so an empty cell here means the
    units agree rather than that nobody checked.
    """
    value = _term(association, _CONVERSION_MULTIPLIER)
    return "" if value is None else amount(value)


def match_type(association: Any) -> str:
    """The SKOS predicate a concept association carries, as a short name.

    Looked for on the source concept first, which is where it is: XKOS defines
    no property for the strength of a mapping, so the SKOS mapping property is
    written on `xkos:sourceConcept` and is a statement about that concept rather
    than about the association. Read only off the association, this column had
    nothing to show and printed an em dash for every row -- including the ones
    #76 weakened from `exactMatch` to `broadMatch`, which is exactly what a
    curator opening the page needs to see.
    """
    if not isinstance(association, dict):
        return ""
    source = _term(association, _SOURCE_CONCEPT)
    for holder in (source if isinstance(source, dict) else {}, association):
        for key in holder:
            name = _local_name(key)
            if name in _MATCH_PROPERTIES:
                return name
    return str(association.get("match_type") or "")


def property_value(entry: Any) -> str:
    """A ChemROF property's `@value`, however it was stored.

    One value or a list of them, depending on which transformer wrote it last.
    A list is rendered as a list rather than collapsed to its first element:
    several values means the structure is not settled, and showing one would
    assert a precision the data does not have.
    """
    if not isinstance(entry, dict):
        return "" if entry is None else str(entry)
    if "@value" not in entry:
        # A working record rather than a published term: the element
        # enrichment writes `isotope`, `isotope_lookup` and `relationships`
        # into the same bag as whole nested payloads.  They were rendering as
        # an empty cell, which reads as "this property is blank" when what is
        # true is "this property is a structure".
        return orjson.dumps(entry).decode()
    raw = entry.get("@value")
    if isinstance(raw, list):
        return ", ".join(str(value) for value in raw)
    return "" if raw is None else str(raw)


#: The inline markup a ChEBI definition uses, and nothing else.  ChEBI writes
#: its definitions for a web page -- *"members of the class `<em>Insecta</em>`"*
#: -- so a definition rendered verbatim shows the tags and one rendered with
#: `| safe` puts a third party's markup into ours.
_MARKUP = re.compile(r"</?(?:em|i|b|strong|sub|sup)\s*/?>", re.IGNORECASE)


def plain_text(value: Any) -> str:
    """A definition as words, with its inline markup removed.

    Removed rather than trusted or escaped.  Escaping shows a reader
    `<em>Insecta</em>`, and `| safe` would render whatever an upstream
    vocabulary happens to contain -- which is a rule about a file we do not
    write, and the wrong place to keep one.  Anything that is not one of the
    six inline tags stays exactly as it is and is escaped by Jinja, so a
    definition containing a stray `<` still reads as a `<`.
    """
    text = str(value or "")
    return " ".join(_MARKUP.sub("", text).split())


def highlight(value: Any, query: str) -> Markup:
    """*value* with what *query* matched wrapped in `<mark>`.

    The whole query first and then its words, longest first, so "Carbon
    Dioxide (fossil)" searched for "carbon dioxide" marks one phrase rather
    than two words and the space between them.  A word of one character is
    not marked on its own: a search for "vitamin a" would otherwise mark every
    `a` on the page.

    The text is split at the matches and every piece escaped before a tag is
    put around any of it, so neither the value nor the query -- which is
    whatever a reader typed into the address bar -- can close the `<mark>` or
    open anything else (`plans/public-site.md` §3, Search).
    """
    text = str(value or "")
    words = [word for word in str(query or "").split() if len(word) > 1]
    terms = sorted({" ".join(str(query or "").split()), *words}, key=len, reverse=True)
    terms = [term for term in terms if term]
    if not terms:
        return escape(text)
    pattern = re.compile("|".join(re.escape(term) for term in terms), re.IGNORECASE)
    pieces: list[str] = []
    position = 0
    for match in pattern.finditer(text):
        pieces.append(str(escape(text[position:match.start()])))
        pieces.append(f"<mark>{escape(match.group(0))}</mark>")
        position = match.end()
    pieces.append(str(escape(text[position:])))
    return Markup("".join(pieces))


def zip_same(values: Any) -> list[tuple[str, str]]:
    """A list of strings as `(value, label)` pairs, for `select`.

    The macro takes pairs because most option lists carry a count in the label.
    Where the value is the label, this says so rather than making the template
    build tuples.
    """
    return [(str(value), str(value)) for value in values or []]


#: Beyond this a value is truncated in a table cell. A `prefLabel` list with
#: provenance runs to several hundred characters, and a change log rendering
#: two of them per row is unreadable.
_VALUE_LIMIT = 120


def short_value(value: Any, limit: int = _VALUE_LIMIT) -> str:
    """An old or new value, short enough to sit in a table cell.

    Truncated with an ellipsis rather than hidden: the shape of the value --
    a list, a dict, a bare string -- is most of what a reader is checking, and
    the full record is on the detail page.
    """
    if value is None:
        return "—"
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, list | dict):
        try:
            text = orjson.dumps(value).decode()
        except TypeError:
            text = str(value)
    else:
        text = str(value)
    text = " ".join(text.split())
    if not text:
        return "—"
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def register(app: Flask) -> None:
    app.jinja_env.filters["thousands"] = thousands
    app.jinja_env.filters["amount"] = amount
    app.jinja_env.filters["stated_amounts"] = stated_amounts
    app.jinja_env.filters["ratio"] = ratio
    app.jinja_env.filters["timestamp"] = timestamp
    app.jinja_env.filters["queue_label"] = queue_label
    app.jinja_env.filters["pretty_json"] = pretty_json
    app.jinja_env.filters["match_type"] = match_type
    app.jinja_env.filters["source_list"] = source_list
    app.jinja_env.filters["source_flow_uuid"] = source_flow_uuid
    app.jinja_env.filters["source_flow_name"] = source_flow_name
    app.jinja_env.filters["source_flow_context"] = source_flow_context
    app.jinja_env.filters["conversion_multiplier"] = conversion_multiplier
    app.jinja_env.filters["property_value"] = property_value
    app.jinja_env.filters["plain_text"] = plain_text
    app.jinja_env.filters["highlight"] = highlight
    app.jinja_env.filters["zip_same"] = zip_same
    app.jinja_env.filters["type_label"] = _type_label
    app.jinja_env.filters["short_value"] = short_value
