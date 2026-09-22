"""Pydantic models for the harmonised flow record that flows through the ETL pipeline.

Fields whose serialised keys are not valid Python identifiers carry an alias so
that code works with clean Python names while ``to_dict()`` exports with the
canonical IRI / prefixed keys expected by downstream consumers.

Mirrors the pattern used in pyst-client: Python field names in code, semantic
aliases on the wire, with ``additional_properties`` absorbing any source-specific
keys that don't map to a declared field.
"""

from __future__ import annotations

from typing import Any, ClassVar

from pydantic import BaseModel, ConfigDict, Field, field_validator

from brightway_flows.domain.source_ref import SourceRef
from brightway_flows.domain.vocabulary import (
    DCTERMS_IS_REPLACED_BY,
    OWL_DEPRECATED,
    SKOS_DEFINITION_IRI,
)


# `SourceRef` was declared here until #92, as a Pydantic model reached only as
# the element type of `HarmonisedFlow.source_refs` below -- while
# `flow_layers.layering` carried a dataclass with the identical five fields and
# `Flow.source_refs` stored bare dicts.  It is now one record,
# `domain.source_ref.SourceRef`, imported below and still validated here:
# Pydantic validates a stdlib dataclass the same way, so the boundary check on
# an input file's references is unchanged.


class HarmonisedFlow(BaseModel):
    """A harmonised flow record as it flows through the ETL pipeline.

    All fields are declared explicitly with Python-valid names.  Fields whose
    on-disk / on-wire key is not a valid Python identifier use a Pydantic alias:

    * ``owl_deprecated``         ↔  ``http://www.w3.org/2002/07/owl#deprecated``
    * ``dcterms_is_replaced_by`` ↔  ``http://purl.org/dc/terms/isReplacedBy``
    * ``skos_definition``        ↔  ``http://www.w3.org/2004/02/skos/core#definition``
    * ``pipeline_sources``       ↔  ``_sources``

    Use ``from_dict()`` to create an instance from a raw serialised dict (unknown
    keys are captured in ``additional_properties``).  Use ``to_dict()`` to
    serialise back — it emits canonical alias keys and inlines
    ``additional_properties`` at the top level.
    """

    model_config = ConfigDict(
        populate_by_name=True,
        validate_assignment=True,
        protected_namespaces=(),
    )

    # ── Core identity ────────────────────────────────────────────────────────
    uuid: str
    identifier: str = ""
    name: str | None = None
    source: str = "unknown"

    # ── Chemical identifiers ─────────────────────────────────────────────────
    cas_numbers: list[str] = Field(default_factory=list)
    ec_numbers: list[str] = Field(default_factory=list)

    # ── Context and unit ─────────────────────────────────────────────────────
    # The compartment path the input file ships, and only that.  This model is
    # the *input file* contract -- `pipeline.loading` is its one caller -- and
    # every one of EF 3.1's 94,062 rows carries a list of strings here.  The
    # consensus context is a different fact, decided later by
    # `default_context_mapping` and typed as `Context` on `Flow` (#97).
    context: list[str] = Field(default_factory=list)
    synonyms: list[str] = Field(default_factory=list)
    lcia_methods: list[dict[str, Any]] = Field(default_factory=list)
    unit: str | None = None

    # ── Pipeline bookkeeping ─────────────────────────────────────────────────
    input_datasets: list[str] = Field(default_factory=list)
    source_refs: list[SourceRef] = Field(default_factory=list)

    # ── Transformer outputs ──────────────────────────────────────────────────
    # prefLabel may be a bare string (legacy) or a list of lang-tagged dicts.
    prefLabel: list[dict[str, Any]] | str | None = None
    altLabel: list[Any] = Field(default_factory=list)
    context_iri: str = ""
    unit_iri: str = ""
    flow_object_id: str = ""
    properties: dict[str, Any] = Field(default_factory=dict)
    references: list[Any] = Field(default_factory=list)
    concept_associations: list[dict[str, Any]] = Field(default_factory=list)

    # SKOS definition — alias maps the colon-containing serialised key.
    skos_definition: list[dict[str, Any]] | None = Field(
        None, alias=SKOS_DEFINITION_IRI
    )

    # ── Deprecation ──────────────────────────────────────────────────────────
    # Three-field cluster: OWL boolean flag, DC replacement IRI, and a bare UUID
    # companion for fast lookup.  The first two use IRI aliases.
    owl_deprecated: bool | None = Field(None, alias=OWL_DEPRECATED)
    dcterms_is_replaced_by: str | None = Field(None, alias=DCTERMS_IS_REPLACED_BY)
    is_replaced_by_uuid: str | None = None

    # ── Internal provenance tracking ─────────────────────────────────────────
    # Written by the pipeline engine (field → last transformer name).
    # Alias maps the leading-underscore serialised key to a clean Python name.
    pipeline_sources: dict[str, str] = Field(default_factory=dict, alias="_sources")

    # ── Unknown / source-specific fields ────────────────────────────────────
    additional_properties: dict[str, Any] = Field(default_factory=dict)

    # All known serialised keys — used by from_dict() to route unknowns.
    __known_keys: ClassVar[set[str]] = set()

    # ── Validators ───────────────────────────────────────────────────────────

    @field_validator("uuid")
    @classmethod
    def uuid_nonempty(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("uuid must be a non-empty string")
        return v

    @field_validator("source")
    @classmethod
    def source_strip(cls, v: str) -> str:
        stripped = v.strip()
        return stripped if stripped else "unknown"

    @field_validator("cas_numbers", "ec_numbers", "synonyms", "context", mode="before")
    @classmethod
    def coerce_string_list(cls, v: Any) -> list[str]:
        if not isinstance(v, list):
            return []
        return [str(x).strip() for x in v if isinstance(x, str) and str(x).strip()]

    # There was a `context_agrees_with_context_iri` model validator here, which
    # checked a structured context against `context_iri` and skipped the list
    # form as "pre-mapping".  It skipped every row: this model reads input
    # files, and an input file ships a compartment path, never a consensus
    # context.  The check it was written for now runs where the structured
    # context actually exists -- `context_registry.validate_flow_contexts`,
    # called on every flow after the transformer chain and before any artifact
    # is written (#97).

    # ── Serialisation helpers ────────────────────────────────────────────────

    def to_dict(self) -> dict[str, Any]:
        """Serialise to a plain dict with canonical (aliased) keys.

        ``None``-valued fields are omitted so that optional IRI-keyed fields
        (e.g. ``owl_deprecated``) are absent from non-deprecated flows,
        matching the format produced before the model was introduced.
        ``additional_properties`` contents are inlined at the top level.
        """
        result = self.model_dump(
            by_alias=True,
            exclude_none=True,
            exclude={"additional_properties"},
        )
        result.update(self.additional_properties)
        return result

    @classmethod
    def _known_keys(cls) -> set[str]:
        """Return the set of all recognised serialised keys (names + aliases)."""
        if not cls.__known_keys:
            keys: set[str] = set()
            for field_name, field_info in cls.model_fields.items():
                keys.add(field_name)
                if field_info.alias:
                    keys.add(field_info.alias)
            cls.__known_keys = keys
        return cls.__known_keys

    @classmethod
    def from_dict(cls, obj: dict[str, Any]) -> HarmonisedFlow:
        """Create an instance from a raw serialised dict.

        Keys that are not declared model fields (by name or alias) are collected
        into ``additional_properties`` rather than being silently dropped.
        """
        known = cls._known_keys()
        known_values: dict[str, Any] = {}
        additional: dict[str, Any] = {}
        for key, value in obj.items():
            if key in known:
                known_values[key] = value
            else:
                additional[key] = value

        instance = cls.model_validate(known_values)
        if additional:
            instance.additional_properties = additional
        return instance
