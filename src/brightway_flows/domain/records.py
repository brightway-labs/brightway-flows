"""Shared serialisation for the dataclass records the ETL passes around.

Three record types -- `Flow`, `FlowObject` and `ElementaryFlow` -- have the same
two problems: some of their serialised keys are not valid Python identifiers
(`@type`, `_sources`, IRI-keyed fields), and some optional fields must stay
*absent* from the output rather than serialise as null. `dataclasses.asdict()`
solves neither, so the conversion is explicit and lives here once.

Subclasses declare:

- ``_ALIASES``       attribute name -> serialised key
- ``_OMIT_IF_NONE``  attribute names dropped from output when None
- ``_EXTRA_FIELD``   name of the passthrough dict for unrecognised keys, if any
- ``_NESTED``        attribute name -> record type, for a field holding a record
- ``_CODECS``        attribute name -> (encode, decode), for a field holding a
                     domain object that is not a record

Records deliberately do **not** provide a ``get()``.  Reading by attribute means a
misspelled or non-existent field raises where it is written, rather than silently
returning None -- which is how three dead branches survived in the transformers.
Read the passthrough bag explicitly via the record's extra field.

Key order in the output follows dataclass declaration order, with the
passthrough bag inlined last.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import fields
from typing import Any, ClassVar


class UnknownRecordFieldError(AttributeError):
    """A field name that is not part of this record type."""


class SerialisableRecord:
    """Mixin providing dict conversion for a dataclass record.

    Deliberately field-free so it composes with ``@dataclass`` subclasses
    without perturbing their field order.
    """

    _ALIASES: ClassVar[dict[str, str]] = {}
    _OMIT_IF_NONE: ClassVar[frozenset[str]] = frozenset()
    _EXTRA_FIELD: ClassVar[str | None] = None
    #: Fields whose value is itself a record.  ``asdict()`` would flatten these
    #: to plain dicts on the way out and never rebuild them on the way in, so
    #: the two directions are declared once here rather than overridden per
    #: record.  Declared rather than inferred from the annotation because a
    #: field's declared type is a string under ``from __future__ import
    #: annotations``, and resolving it would mean importing the record's module
    #: from this one.
    _NESTED: ClassVar[dict[str, type]] = {}
    #: Fields holding a domain object that is *not* a record, given as
    #: ``attribute -> (encode, decode)``.  ``_NESTED`` cannot serve them: it
    #: calls ``to_dict``/``from_dict`` on the value's own class, and the object
    #: this exists for -- :class:`~brightway_flows.domain.context.Context`
    #: -- deliberately does not carry them.  Its dict form omits unset fields
    #: and belongs to this project rather than to the shared context contract,
    #: so it lives in ``domain.context_registry`` and is named here.
    #:
    #: ``encode`` is given the attribute's value, including ``None``; ``decode``
    #: is given whatever the payload held, which for a field the pipeline fills
    #: in later includes shapes that are not the object at all.
    _CODECS: ClassVar[dict[str, tuple[Callable[[Any], Any], Callable[[Any], Any]]]] = {}
    #: JSON Schema for a field whose serialised shape is not its declared type,
    #: as ``attribute -> subschema``.  A ``_CODECS`` entry is free to publish
    #: something the annotation does not describe -- ``lcia_methods`` holds
    #: `StatedFactor` records and publishes the six-key rows a source list
    #: states -- and the generated schema describes ``to_dict()`` output, so for
    #: those fields it has to be told rather than inferred.  Declared beside the
    #: codec that makes it necessary; see :func:`domain.schema.record_schema`.
    _SERIALISED_SCHEMAS: ClassVar[dict[str, dict[str, Any]]] = {}

    # Populated lazily; keyed per concrete class.
    _FIELD_NAME_CACHE: ClassVar[dict[type, frozenset[str]]] = {}
    _ALIAS_TO_FIELD_CACHE: ClassVar[dict[type, dict[str, str]]] = {}

    @classmethod
    def alias_to_field(cls) -> dict[str, str]:
        cached = SerialisableRecord._ALIAS_TO_FIELD_CACHE.get(cls)
        if cached is None:
            cached = {v: k for k, v in cls._ALIASES.items()}
            SerialisableRecord._ALIAS_TO_FIELD_CACHE[cls] = cached
        return cached

    @classmethod
    def field_names(cls) -> frozenset[str]:
        """Settable field names, excluding the passthrough bag."""
        cached = SerialisableRecord._FIELD_NAME_CACHE.get(cls)
        if cached is None:
            cached = frozenset(
                f.name for f in fields(cls) if f.name != cls._EXTRA_FIELD
            )
            SerialisableRecord._FIELD_NAME_CACHE[cls] = cached
        return cached

    @classmethod
    def resolve_field(cls, name: str) -> str:
        """Map a serialised key or attribute name to an attribute name.

        :raises UnknownRecordFieldError: if the name is not a field.
        """
        resolved = cls.alias_to_field().get(name, name)
        if resolved not in cls.field_names():
            raise UnknownRecordFieldError(
                f"{name!r} is not a field of {cls.__name__}. Valid fields: "
                f"{', '.join(sorted(cls.field_names()))}"
            )
        return resolved

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> Any:
        """Build a record from a serialised payload.

        Unrecognised keys go to the passthrough bag when one is declared, and
        are dropped otherwise.
        """
        alias_to_field = cls.alias_to_field()
        known = cls.field_names()
        kwargs: dict[str, Any] = {}
        extra: dict[str, Any] = {}
        for key, value in payload.items():
            attr = alias_to_field.get(key, key)
            if attr in known:
                nested = cls._NESTED.get(attr)
                if nested is not None and isinstance(value, dict):
                    value = nested.from_dict(value)
                codec = cls._CODECS.get(attr)
                if codec is not None:
                    value = codec[1](value)
                kwargs[attr] = value
            else:
                extra[key] = value
        record = cls(**kwargs)
        if cls._EXTRA_FIELD is not None and extra:
            setattr(record, cls._EXTRA_FIELD, extra)
        return record

    def to_dict(self) -> dict[str, Any]:
        """Serialise to the on-disk record shape.

        Aliased keys are restored, optional fields that are None and listed in
        ``_OMIT_IF_NONE`` are dropped so absent keys stay absent, and the
        passthrough bag is inlined at the top level.
        """
        cls = type(self)
        out: dict[str, Any] = {}
        for f in fields(self):
            if f.name == cls._EXTRA_FIELD:
                continue
            value = getattr(self, f.name)
            if value is None and f.name in cls._OMIT_IF_NONE:
                continue
            if f.name in cls._NESTED and isinstance(value, SerialisableRecord):
                value = value.to_dict()
            codec = cls._CODECS.get(f.name)
            if codec is not None:
                value = codec[0](value)
            out[cls._ALIASES.get(f.name, f.name)] = value
        if cls._EXTRA_FIELD is not None:
            out.update(getattr(self, cls._EXTRA_FIELD))
        return out
