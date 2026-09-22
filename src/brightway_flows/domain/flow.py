"""The in-memory flow record that transformers read and write.

This is the working representation for the transform stage.  ``HarmonisedFlow``
in ``models.py`` remains the *input file* contract -- it validates raw JSON at the
boundary -- and this dataclass is what the pipeline operates on afterwards, per
the layering in ``docs/architecture.md``: translate external payloads at the
boundary, then work with domain objects.

Why a dataclass and not the Pydantic model: transformers mutate flows in a hot
loop over ~94k records, and ``HarmonisedFlow`` sets ``validate_assignment=True``,
so every attribute write would re-run full model validation.  A dataclass also
gives ``dataclasses.fields()``, which is what lets :class:`~.pipeline.Change`
reject a misspelled field name instead of silently creating a new key.

Serialisation is deliberately *not* automatic.  ``to_dict()`` reproduces the
on-disk key names -- including the IRI-keyed and underscore-prefixed ones that
are not valid Python identifiers -- so the published artifacts are unchanged.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, ClassVar

from brightway_flows.domain.context import Context
from brightway_flows.domain.context_registry import (
    context_field_from_serialised,
    context_field_to_serialised,
)
from brightway_flows.domain.lcia.records import (
    FLOW_ENTRIES_SCHEMA,
    StatedFactor,
    flow_entries,
    stated_factors,
)
from brightway_flows.domain.records import (
    SerialisableRecord,
    UnknownRecordFieldError,
)
from brightway_flows.domain.vocabulary import (
    DCTERMS_IS_REPLACED_BY,
    OWL_DEPRECATED,
    RO_HAS_ROLE_IRI,
    SKOS_DEFINITION_IRI,
)

# Python attribute name -> serialised key, for the fields whose on-disk key is
# not a valid Python identifier.
FIELD_ALIASES: dict[str, str] = {
    "types": "@type",
    "skos_definition": SKOS_DEFINITION_IRI,
    "owl_deprecated": OWL_DEPRECATED,
    "dcterms_is_replaced_by": DCTERMS_IS_REPLACED_BY,
    "roles": RO_HAS_ROLE_IRI,
    "pipeline_sources": "_sources",
    "transformed": "_transformed",
    "provided": "_provided",
}
ALIAS_TO_FIELD: dict[str, str] = {v: k for k, v in FIELD_ALIASES.items()}

# Fields that are omitted from to_dict() when None, matching the previous
# behaviour where an absent optional key stayed absent for non-deprecated flows.
_OMIT_WHEN_NONE = frozenset({
    "types",
    "origin_qualifier",
    "parent_flow_object_id",
    "parent_intervention_id",
    "roles",
    "name",
    "unit",
    "prefLabel",
    "skos_definition",
    "owl_deprecated",
    "dcterms_is_replaced_by",
    "is_replaced_by_uuid",
    "cas_match_labels",
    "cas_number_sources",
    "general_comment",
})


#: Raised when a field name is not part of the flow record.  Aliased to the
#: shared record error so ``except UnknownFlowFieldError`` keeps working.
UnknownFlowFieldError = UnknownRecordFieldError


@dataclass
class ProvidedValues(SerialisableRecord):
    """What a source list shipped, before any transformer touched it.

    The pipeline does not only add to a flow, it *replaces*: ``bootstrap_labels``
    moves ``name`` into ``prefLabel`` and then purges ``name`` and ``synonyms``,
    and the CAS transformers substitute a different registry number for the one
    the list gave.  Once that has run there is no way back to the input, and the
    merge found this out the hard way: it matched on ``name`` and got nothing,
    because enrichment had emptied it.

    So the displaced values are kept rather than reconstructed.  Populated once,
    at the boundary where an input row becomes a record
    (``_normalize_input_flow_record``), and never written by a transformer.

    ``context`` is here for a different reason from the other five, and is the
    only one that is not a displaced copy of a field of the same name.  The
    compartment a source list ships and the consensus context a flow is in are
    two facts, not one fact at two times; ``Flow.context`` holds the second and
    this holds the first, permanently, because it is what the mapping keys on
    and what every artifact reports as ``original_context`` (#97).

    These six fields are what the pipeline is known to overwrite.  It is not the
    whole input row: the point is to keep what would otherwise be destroyed, not
    to carry a second copy of every flow through a 94k-record build.
    """

    name: str | None = None
    synonyms: list[str] = field(default_factory=list)
    #: The compartment path the source list shipped, verbatim -- ``["Emissions",
    #: "Emissions to air", "Emissions to air, unspecified"]``.  Not a consensus
    #: context and never becomes one: `default_context_mapping` reads this to
    #: decide which consensus context the flow belongs in, and writes that
    #: answer to `Flow.context`.  All 94,062 rows of EF 3.1 ship a list of
    #: strings here, as do the merged lists.
    context: list[str] = field(default_factory=list)
    cas_numbers: list[str] = field(default_factory=list)
    ec_numbers: list[str] = field(default_factory=list)
    unit: str | None = None

    def labels(self) -> list[str]:
        """The shipped name and synonyms, in that order, non-empty."""
        return [
            value.strip()
            for value in [self.name, *self.synonyms]
            if isinstance(value, str) and value.strip()
        ]


@dataclass
class Flow(SerialisableRecord):
    """One flow as it moves through the transform stage.

    ``extra`` holds source-specific keys that are not declared here.  They are
    round-tripped verbatim so an unrecognised input field is preserved rather
    than dropped, which is what the previous dict-based pipeline did implicitly.
    """

    # Declaration order mirrors HarmonisedFlow so to_dict() reproduces the
    # existing key order in the artifacts.  Do not reorder without checking
    # tests/test_flow_model.py, which asserts that correspondence.

    # ── Identity ─────────────────────────────────────────────────────────────
    uuid: str
    identifier: str = ""
    name: str | None = None
    source: str = "unknown"

    # ── Chemical identifiers ─────────────────────────────────────────────────
    cas_numbers: list[str] = field(default_factory=list)
    ec_numbers: list[str] = field(default_factory=list)

    # ── Context and unit ─────────────────────────────────────────────────────
    # The consensus context this flow is in: the canonical `Context`, not a
    # dict and not the source list's own compartment.  None until
    # `DefaultContextMappingTransformer` -- the second of the twenty-two -- has
    # decided; after that every flow has one, and
    # `context_registry.validate_flow_contexts` refuses to publish a flow that
    # does not (#97).  What the source list shipped is `provided.context`,
    # which is where every reader of the pre-mapping compartment already looks.
    context: Context | None = None
    synonyms: list[str] = field(default_factory=list)
    #: The characterisation factors the source list states about this flow, as
    #: records.  A dict here was rule 2's oldest exception: six keys read with
    #: `.get()` in four modules, one of which decides which CAS number a
    #: substance keeps.  The published shape does not move -- the codec renders
    #: it back at the I/O boundary.
    #:
    #: **Kept, and not the place to read a factor from.**  Since `characterise`,
    #: the JRC's implementation of EF 3.1 is published as
    #: `lcia_characterization_factors` rows and in `lcia-factors.json.gz`, joined
    #: to a category that says who implemented it, what unit its numbers are in
    #: and what it protects -- none of which a row here carries.  The two cannot
    #: disagree, because that implementation is read off *this* field: it is the
    #: source and the tables are the projection.  It stays because it is a
    #: published field with readers, and retiring it is a one-way door with its
    #: own issue (`plans/lcia-factors.md` §4.4, PR 8).
    lcia_methods: list[StatedFactor] = field(default_factory=list)
    unit: str | None = None

    # ── Layering and provenance of the record itself ─────────────────────────
    input_datasets: list[str] = field(default_factory=list)
    source_refs: list[dict[str, Any]] = field(default_factory=list)

    # ── Labels ───────────────────────────────────────────────────────────────
    # Lang-tagged label rows; see labels.coerce_pref_labels / coerce_alt_labels.
    prefLabel: list[dict[str, Any]] | str | None = None
    altLabel: list[Any] = field(default_factory=list)

    # ── Enrichment ───────────────────────────────────────────────────────────
    context_iri: str = ""
    unit_iri: str = ""
    flow_object_id: str = ""
    properties: dict[str, Any] = field(default_factory=dict)
    references: list[Any] = field(default_factory=list)
    concept_associations: list[dict[str, Any]] = field(default_factory=list)
    skos_definition: list[dict[str, Any]] | None = None

    # ── Deprecation ──────────────────────────────────────────────────────────
    owl_deprecated: bool | None = None
    dcterms_is_replaced_by: str | None = None
    is_replaced_by_uuid: str | None = None

    # ── Pipeline bookkeeping ─────────────────────────────────────────────────
    # field name -> name of the last transformer that wrote it.
    pipeline_sources: dict[str, str] = field(default_factory=dict)

    # Not declared on HarmonisedFlow, so these serialise after the model fields;
    # keep them last so key order is unchanged.  They default to None rather than
    # {} because the keys are absent until a transformer sets them, and emitting
    # empty dicts on every record would change the artifacts.
    # cas_match_labels: CAS number -> SKOS match quality.
    cas_match_labels: dict[str, str] | None = None
    # cas_number_sources: CAS number -> structured provenance for that number.
    cas_number_sources: dict[str, Any] | None = None
    # general_comment: free-text note carried from the source list.
    general_comment: str | None = None
    # types: the RDF classes of this flow's substance, copied from its flow
    # object once the layers resolve.  Identity is a property of the substance,
    # so the classes are derived on `FlowObject`; a flow carries a copy only so
    # the published export can state them, rather than making every consumer
    # re-derive what kind of thing the flow is.  Serialised as "@type", and
    # absent rather than null when unset.  Declared here, after the fields
    # `HarmonisedFlow` shares, because that is where the un-mirrored fields go.
    types: list[str] | None = None
    # origin_qualifier: why this substance is held apart from one it shares a
    # CAS number with -- `biogenic`, `fossil`, `land_use_change`, a water
    # category.  Like `types` it is a property of the substance, derived on the
    # `FlowObject`, and carried here so the export can state it: the difference
    # between fossil and biogenic CO2 decides an entire impact category, and
    # until now the only published trace of it was the preferred label.
    origin_qualifier: str | None = None
    # parent_flow_object_id: the undifferentiated substance this flow's
    # substance was split from -- the CO2 that biogenic CO2 is biogenic
    # *relative to*.  The other half of `origin_qualifier`, derived on the
    # `FlowObject` beside it and carried here for the same reason: the export
    # is flow-shaped, and a qualifier that names a distinction without naming
    # its other side leaves a consumer resolving the base substance by CAS
    # lookup, which returns the siblings as well.  Set on the 13 qualified
    # objects whose CAS resolves to an unqualified one; absent otherwise.
    parent_flow_object_id: str | None = None
    # parent_intervention_id: the non-material intervention this flow is one
    # occurrence of -- the `Noise` that `Noise, Road, Lorry, Average` is noise
    # of (#70).  Derived on the `FlowObject` and carried here for the reason
    # `parent_flow_object_id` is: the export is flow-shaped.  Separate from it
    # because that field publishes under `brightway:baseSubstance`, and noise
    # has no base substance -- it is not matter at all, which is why the
    # semantic typing can give it no chemical class.
    parent_intervention_id: str | None = None
    # roles: what this flow's substance is *used for* -- herbicide, fertilizer,
    # environmental contaminant -- as `RO:0000087` assertions onto ChEBI role
    # classes.  Like `types`, `origin_qualifier` and `parent_flow_object_id` it
    # is a property of the *substance*, derived on the flow object and copied
    # here so the export reads one record rather than joining two.
    roles: list[dict[str, Any]] | None = None

    # transformed: has this flow already been through the transformer chain?
    # The chain is ordered for one pass over raw input and is not idempotent --
    # `normalize_name_case` runs fifth and re-title-cases labels that
    # `consensus_match` sets at fourteenth -- so running it again over its own
    # output degrades it.  The flag lives on the flow rather than at the call
    # site because it is a property of the flow: the merge reads consensus flows
    # back from the database already marked, and hands them to the chain
    # alongside a source list that is not.  See `apply_transformers`.
    transformed: bool = False
    # provided: the values the source list shipped; see `ProvidedValues`.
    provided: ProvidedValues = field(default_factory=ProvidedValues)

    # ── Unrecognised source-specific keys, round-tripped verbatim ────────────
    extra: dict[str, Any] = field(default_factory=dict)

    _ALIASES: ClassVar[dict[str, str]] = FIELD_ALIASES
    _OMIT_IF_NONE: ClassVar[frozenset[str]] = _OMIT_WHEN_NONE
    _EXTRA_FIELD: ClassVar[str | None] = "extra"
    _NESTED: ClassVar[dict[str, type]] = {"provided": ProvidedValues}
    _CODECS: ClassVar[dict[str, tuple[Any, Any]]] = {
        "context": (context_field_to_serialised, context_field_from_serialised),
        "lcia_methods": (flow_entries, stated_factors),
    }
    _SERIALISED_SCHEMAS: ClassVar[dict[str, Any]] = {
        "lcia_methods": FLOW_ENTRIES_SCHEMA,
    }
