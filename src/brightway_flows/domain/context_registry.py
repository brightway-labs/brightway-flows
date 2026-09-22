"""Resolution of consensus context IRIs to :class:`Context` instances.

``consensus-flow-contexts.json`` is the vocabulary: one row per valid context,
keyed by ``context_iri``.  This module is the only place that reads it and the
only supported way to turn a ``context_iri`` into the structured ``context``
dict stored on flow records.

Do not rebuild a context by parsing its display strings.  ``Context.to_list()``
omits ``"Unknown"`` values and orders fields for human reading, so parsing that
output positionally silently mis-assigns fields (e.g. a water body landing in
``strata``).  Resolve from the IRI instead, or use :meth:`Context.from_list`,
which is an exact inverse of ``to_list``.
"""

from __future__ import annotations

import functools
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import orjson

from brightway_flows.domain.context import (
    Context,
    Dimension,
    Geography,
    IndoorAirClass,
    LandUseClass,
    Media,
    PopulationDensity,
    ProhibitedContextCombinationError,
    VerticalStrata,
    WaterBody,
)
from brightway_flows.filesystem import PACKAGE_DATA_DIR

CONTEXTS_FILEPATH = (
    PACKAGE_DATA_DIR / "consensus-flow-contexts.json"
)

# Field order used when serialising a Context to the ``context`` dict on a flow
# record.  Matches the key order in consensus-flow-contexts.json.
CONTEXT_FIELDS: tuple[str, ...] = (
    "dimension",
    "media",
    "strata",
    "indoor",
    "population_density",
    "geography",
    "water_body",
    "land_use",
)

_ENUM_BY_FIELD: dict[str, Any] = {
    "dimension": Dimension,
    "media": Media,
    "strata": VerticalStrata,
    "indoor": IndoorAirClass,
    "population_density": PopulationDensity,
    "geography": Geography,
    "water_body": WaterBody,
    "land_use": LandUseClass,
}


class UnknownContextIRIError(KeyError):
    """The given context IRI is not present in the consensus context vocabulary."""


class InvalidContextError(ValueError):
    """A structured context dict is not a valid :class:`Context`."""


def context_from_dict(data: dict[str, Any]) -> Context:
    """Build a :class:`Context` from a structured ``context`` dict.

    Values are coerced to their enum members, so the result serialises correctly
    (a bare string would satisfy ``StrEnum`` comparisons but break ``to_list()``).
    Unrecognised fields and values are rejected rather than ignored.

    :raises InvalidContextError: if a field, a value, or the combination is invalid.
    """
    if not isinstance(data, dict):
        raise InvalidContextError(f"context must be a dict, got {type(data).__name__}")

    unknown = sorted(set(data) - set(CONTEXT_FIELDS))
    if unknown:
        raise InvalidContextError(f"unknown context field(s): {unknown}")

    kwargs: dict[str, Any] = {}
    for field, enum_cls in _ENUM_BY_FIELD.items():
        raw = data.get(field)
        if raw in (None, "", []):
            kwargs[field] = None
            continue
        try:
            kwargs[field] = enum_cls(raw)
        except ValueError as exc:
            raise InvalidContextError(
                f"invalid value for {field!r}: {raw!r}"
            ) from exc

    if kwargs.get("dimension") is None:
        raise InvalidContextError("context is missing a 'dimension'")

    try:
        return Context(**kwargs)
    except ProhibitedContextCombinationError as exc:
        raise InvalidContextError(str(exc)) from exc


def context_field_from_serialised(value: Any) -> Context | None:
    """Decode a record's serialised ``context`` value.

    The decode half of the codec :data:`~brightway_flows.domain.records.SerialisableRecord._CODECS`
    names on ``Flow`` and ``ElementaryFlow``.

    A dict is the consensus context and is rebuilt.  Anything else is *not* a
    consensus context and becomes ``None``: an input row carries the compartment
    strings its source list ships, which is a different fact about the flow and
    is kept as ``Flow.provided.context`` rather than mistaken for this field.

    :raises InvalidContextError: if the dict is not a constructible context.
    """
    if isinstance(value, dict) and value:
        return context_from_dict(value)
    return None


def context_field_to_serialised(context: Context | None) -> dict[str, str] | None:
    """Encode a record's ``context`` for the on-disk shape; the codec's other half."""
    return None if context is None else context_to_dict(context)


def check_context_against_iri(
    context: Any,
    context_iri: str,
) -> str | None:
    """Return a human-readable problem description, or ``None`` when consistent.

    Accepts either a :class:`Context` -- what a record holds -- or the dict a
    payload read back from an artifact holds.  An absent context is skipped:
    whether a flow is allowed to reach this point without one is
    :func:`validate_flow_contexts`'s question, not this one's.

    When *context_iri* is set, the context must equal the vocabulary entry for
    that IRI exactly -- this is the invariant that positional string parsing
    violated.
    """
    if isinstance(context, Context):
        resolved = context
    elif isinstance(context, dict) and context:
        try:
            resolved = context_from_dict(context)
        except InvalidContextError as exc:
            return f"invalid context {context!r}: {exc}"
    else:
        return None

    iri = (context_iri or "").strip()
    if not iri:
        return None

    try:
        expected = context_for_iri(iri)
    except UnknownContextIRIError:
        return f"context_iri is not in the consensus vocabulary: {iri!r}"

    if resolved != expected:
        return (
            f"context does not match context_iri {iri!r}: "
            f"got {context_to_dict(resolved)!r}, "
            f"vocabulary says {context_to_dict(expected)!r}"
        )
    return None


def validate_flow_contexts(flows: Sequence[Any]) -> list[str]:
    """Return one problem description per flow with an inconsistent context.

    Transformers mutate :class:`~brightway_flows.domain.flow.Flow` records in
    place rather than re-validating them, so nothing re-checks a context once a
    transformer has written it.  Call this after transformers have run and
    before writing artifacts, so a corrupt context is caught instead of being
    serialised.

    Two problems are reported.  A context that contradicts its ``context_iri``
    is the one this was written for.  The other is a flow with *no* consensus
    context, which used to pass silently: a flow the mapping could not place
    kept the compartment strings its source list shipped, and this function
    skipped anything that was not a dict.  Publishing that flow would put a
    source list's own vocabulary into an artifact whose point is that it has
    none, so it stops the run instead.  It has never fired --
    ``default_context_mapping`` places all 93,993 flows of a full EF 3.1 run --
    which is what makes it an invariant to state rather than a gate to fear.

    Accepts ``Flow`` records, ``ElementaryFlow`` records, or raw dicts.

    Returns an empty list when every context is consistent.
    """
    def read(record: Any, name: str) -> Any:
        """Read a field from a record or a plain mapping."""
        if isinstance(record, dict):
            return record.get(name)
        return getattr(record, name, None)

    problems: list[str] = []
    for flow in flows:
        context = read(flow, "context")
        if context:
            problem = check_context_against_iri(
                context, read(flow, "context_iri") or ""
            )
        else:
            shipped = read(read(flow, "provided"), "context") or []
            problem = (
                "no consensus context: the context mapping placed this flow "
                f"nowhere, and it still ships {shipped!r}"
            )
        if problem is None:
            continue
        uuid = read(flow, "uuid") or read(flow, "elementary_flow_id") or "<no id>"
        source = read(flow, "source") or "<no source>"
        problems.append(f"[{source}] {uuid}: {problem}")
    return problems


def context_to_dict(context: Context) -> dict[str, str]:
    """Serialise *context* to the structured dict stored on a flow record.

    Unset fields are omitted; ``"Unknown"`` values are kept, because they are
    meaningful (an explicitly unknown water body is not the same as no water
    body at all).
    """
    out: dict[str, str] = {}
    for field in CONTEXT_FIELDS:
        value = getattr(context, field)
        if value is None:
            continue
        out[field] = value.value
    return out


@functools.cache
def build_context_lookup(
    contexts_path: Path | None = None,
) -> dict[str, Context]:
    """Return a mapping of ``context_iri`` to validated :class:`Context`.

    Every row is passed through the :class:`Context` constructor, so an invalid
    combination in the vocabulary file raises at load time rather than producing
    a silently malformed flow record.
    """
    path = contexts_path or CONTEXTS_FILEPATH
    payload = orjson.loads(path.read_bytes())
    if not isinstance(payload, list):
        raise ValueError(f"{path} must contain a JSON list")

    lookup: dict[str, Context] = {}
    for index, row in enumerate(payload):
        if not isinstance(row, dict):
            raise ValueError(f"context entry at index {index} must be an object")
        iri = row.get("context_iri")
        if not isinstance(iri, str) or not iri.strip():
            raise ValueError(f"context entry at index {index} missing 'context_iri'")
        iri = iri.strip()
        if iri in lookup:
            raise ValueError(f"duplicate context_iri in {path}: {iri}")
        kwargs: dict[str, Any] = {}
        for field, enum_cls in _ENUM_BY_FIELD.items():
            raw = row.get(field)
            if raw in (None, "", []):
                kwargs[field] = None
                continue
            try:
                kwargs[field] = enum_cls(raw)
            except ValueError as exc:
                raise ValueError(
                    f"context {iri}: invalid value for {field!r}: {raw!r}"
                ) from exc
        lookup[iri] = Context(**kwargs)
    return lookup


@functools.cache
def _iri_by_context() -> dict[tuple[tuple[str, str], ...], str]:
    """The vocabulary read the other way round: context -> its IRI.

    Keyed on the serialised form rather than on :class:`Context` itself, which
    is a mutable dataclass and therefore unhashable.  Built once and cached
    beside :func:`build_context_lookup`, which it inverts.
    """
    return {
        tuple(sorted(context_to_dict(context).items())): iri
        for iri, context in build_context_lookup().items()
    }


def iri_for_context(context: Context) -> str | None:
    """The IRI *context* is published under, or None if the vocabulary has none.

    The inverse of :func:`context_for_iri`, and the way a caller that has
    *changed* a context field asks what the result is called.  None rather than
    a raise: a combination the vocabulary does not carry is a question for the
    caller -- the merge leaves such a row where it was -- rather than a broken
    vocabulary, which is what `build_context_lookup` already raises on.
    """
    return _iri_by_context().get(tuple(sorted(context_to_dict(context).items())))


def context_for_iri(context_iri: str) -> Context:
    """Return the :class:`Context` registered for *context_iri*.

    :raises UnknownContextIRIError: if the IRI is not in the vocabulary.
    """
    lookup = build_context_lookup()
    try:
        return lookup[context_iri]
    except KeyError:
        raise UnknownContextIRIError(context_iri) from None


def context_dict_for_iri(context_iri: str) -> dict[str, str]:
    """Return the structured ``context`` dict registered for *context_iri*.

    This is the correct replacement for rebuilding a context from display
    strings: it is exact, lossless, and validated against the vocabulary.
    """
    return context_to_dict(context_for_iri(context_iri))


# Legacy context field names, from before the consensus schema settled.  Kept so
# artifacts written by older runs still render.
_LEGACY_FIELD_NAMES: dict[str, str] = {
    "major": "dimension",
    "environment": "media",
    "vertical": "strata",
    "indoor": "indoor",
    "high_pop_density": "population_density",
    "urbanity": "geography",
    "water_location": "water_body",
    "land_use": "land_use",
}


#: A field whose *presence* states a fact that its value only refines, and what
#: to print when the value refines nothing.
#:
#: ``indoor`` is the only one.  A context that carries it is an indoor release;
#: the value says which kind of indoor setting, and
#: :class:`~brightway_flows.domain.context.IndoorAirClass` includes
#: ``Unknown`` for "indoors, kind unstated".  Printing that value gives
#: "Unknown", which throws away the one thing the context does state -- and
#: makes it identical to ``Environmental / Air`` with ``strata="Unknown"``,
#: where the word means the *height* is unstated.  Two different contexts, one
#: name, and the review page that compares contexts by name then read a
#: substance's indoor and unspecified air flows as duplicates of each other
#: (#284).
#:
#: Every other field is a plain attribute: ``Unknown`` there says the attribute
#: is unstated, which is what it prints.
_FIELD_MEANING_WHEN_UNKNOWN: dict[str, str] = {"indoor": "Indoor"}

_UNKNOWN = "Unknown"


def _display_value(field: str, raw: Any) -> str:
    """One field's contribution to the printed context."""
    text = str(raw).strip()
    if text == _UNKNOWN:
        return _FIELD_MEANING_WHEN_UNKNOWN.get(field, text)
    return text


def context_display_parts(value: Any) -> list[str]:
    """Return a context as an ordered list of strings, for display and search.

    Accepts a :class:`Context`, which is what a record holds; the dict a payload
    read back from an artifact holds; or the compartment path a source list
    ships, which is a list and is printed as it arrived.  Field order follows
    :data:`CONTEXT_FIELDS`, not insertion order, so the same context always
    renders the same way.

    A printed context has to identify the context: it is what a reader compares,
    what the flow list sorts on, what the full-text index carries, and -- in the
    merge -- what a candidate is scored on.  See
    :data:`_FIELD_MEANING_WHEN_UNKNOWN` for the one field where printing the
    value would not identify it.

    The merge carried a second copy of this function without that rule, so a
    flow in `Environmental / Air / Indoor / Unknown` rendered as
    ``["Environmental", "Air", "Unknown"]`` -- the same three strings as
    unspecified outdoor air.  That is #284 again, and in the merge it was not
    only a display fault: the source side of the same comparison comes from
    ``consensus-flows-as-strings.json``, which is ``Context.to_list()`` and does
    say ``"Indoor"``, so an indoor source row scored *against* the indoor
    candidate and level with the outdoor one.  One renderer, so the two sides of
    a comparison cannot disagree about what a context is called.
    """
    if isinstance(value, Context):
        value = context_to_dict(value)
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]
    if isinstance(value, dict):
        ordered = [
            _display_value(key, value[key])
            for key in CONTEXT_FIELDS
            if value.get(key) not in (None, "", [])
        ]
        if ordered:
            return ordered
        # Not a recognised context shape; render what is there rather than
        # silently returning nothing.
        return [f"{k}={v}" for k, v in value.items() if v not in (None, "", [])]
    return []


def context_attributes(value: Any) -> dict[str, str]:
    """Return the structured context as plain per-field strings.

    Falls back to the legacy field names when a payload predates the current
    schema.  Returns an empty dict for anything that is not a context.
    """
    if isinstance(value, Context):
        return context_to_dict(value)
    if not isinstance(value, dict):
        return {}
    if any(key in value for key in CONTEXT_FIELDS):
        return {
            key: str(value[key]).strip()
            for key in CONTEXT_FIELDS
            if value.get(key) not in (None, "", [])
        }
    return {
        new_key: str(value[old_key]).strip()
        for old_key, new_key in _LEGACY_FIELD_NAMES.items()
        if value.get(old_key) not in (None, "", [])
    }
