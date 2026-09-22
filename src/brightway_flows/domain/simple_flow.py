"""Schema dataclasses for harmonised-flows-simple.json.gz."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, ClassVar

from brightway_flows.domain.records import SerialisableRecord
from brightway_flows.domain.vocabulary import (
    BRIGHTWAY_BASE_INTERVENTION,
    BRIGHTWAY_BASE_SUBSTANCE,
    BRIGHTWAY_DEPRECATION_REASON,
    BRIGHTWAY_ORIGIN_QUALIFIER,
    DCTERMS_IS_REPLACED_BY,
    OWL_DEPRECATED,
    RO_HAS_ROLE_IRI,
    SKOS_IN_SCHEME_IRI,
)


@dataclass
class SimpleFlow(SerialisableRecord):
    """One non-deprecated flow in the simplified export.

    ``identifier`` is always present: it holds the ILCD UUID for EF flows and
    the ``elementary_flow_id`` assigned during merging for ecoinvent-added flows.

    ``jsonld_id`` is the same flow as an IRI, under the minted consensus
    namespace, and serialises as ``@id``.  Without it every flow in the export
    expands to a blank node -- unnameable, and so unciteable by anything that
    wants to say something about one.  It is the identifier the
    ``concept_associations`` on this very row already point at.
    """

    identifier: str
    source: str
    cas_numbers: list[str]
    ec_numbers: list[str]
    context_iri: str
    unit: str
    unit_iri: str
    prefLabel: str
    altLabel: list[str]
    properties: dict[str, Any]
    references: list[str]
    definition: list[str]
    jsonld_id: str = ""
    #: `skos:Concept` first -- a published flow is an entry in a taxonomy before
    #: it is anything chemical -- then the ChemROF classes for the substance,
    #: most specific only, since a reasoner derives the rest of the chain.  A
    #: flow that is not a chemical entity at all (a land-use class) or whose
    #: identity is too thin to classify carries only `skos:Concept`;
    #: `created_from.semantic_typing.reason` on the flow object says which.
    jsonld_type: list[str] = field(default_factory=list)
    #: The `skos:ConceptScheme` this flow belongs to: the consensus list.
    in_scheme: dict[str, str] = field(default_factory=dict)
    #: Why this substance is held apart from one it shares a CAS number with,
    #: as an IRI from the minted origin-qualifier vocabulary.  Absent for the
    #: unqualified substance, which is most of them.
    origin_qualifier: dict[str, str] | None = None
    #: What it is held apart *from*: the undifferentiated substance, as an IRI
    #: from the minted flow-object namespace.  A node reference, not a literal,
    #: on the precedent `chemrof:has_element` set -- the flow-object layer is
    #: not published yet, so this refers to a substance the document does not
    #: describe, and publishing that layer later adds the description without
    #: changing the identifier.  Absent wherever `origin_qualifier` is, and on
    #: the one qualified substance with no CAS number to resolve a parent
    #: through (`Oils, Non-fossil`).
    parent_flow_object_id: dict[str, str] | None = None
    #: The non-material intervention this flow is one occurrence of, as an IRI
    #: from the minted flow-object namespace.  `parent_flow_object_id`'s
    #: counterpart for a flow that counts something other than a substance:
    #: BAFU's traffic-noise rows are each noise from one mode of transport, and
    #: this is what they are all noise *of* (#70).  A node reference for the
    #: same reason, and absent on every flow that is a substance.
    parent_intervention_id: dict[str, str] | None = None
    #: What the substance is *used for*, as `RO:0000087` assertions onto ChEBI
    #: role classes: herbicide, fertilizer, environmental contaminant.  A list
    #: because a role is many-valued -- sulfluramid is an insecticide and an
    #: acaricide -- and absent, rather than empty, where ChEBI has nothing to
    #: say.
    #:
    #: Each row holds the ChEBI class under `@id` and its label under an
    #: `rdfs:` label key -- see `flow_object.Role.to_dict`, which writes it.
    #: Both,
    #: deliberately, on the precedent `unit`/`unit_iri` sets: the IRI is what a
    #: consumer groups and reasons on, and the label is what stops a reader
    #: having to resolve `CHEBI_24527` to learn the flow is a herbicide.
    #:
    #: The definition and the provenance that the flow-object layer carries per
    #: assertion are dropped here, which is what "simple" means in this export:
    #: `altLabel` is a list of strings rather than of label records, and
    #: `references` a list of IRIs rather than of reference objects, for the
    #: same reason.
    roles: list[dict[str, str]] | None = None

    _ALIASES: ClassVar[dict[str, str]] = {
        "jsonld_id": "@id",
        "jsonld_type": "@type",
        "in_scheme": SKOS_IN_SCHEME_IRI,
        "origin_qualifier": BRIGHTWAY_ORIGIN_QUALIFIER,
        "parent_flow_object_id": BRIGHTWAY_BASE_SUBSTANCE,
        "parent_intervention_id": BRIGHTWAY_BASE_INTERVENTION,
        "roles": RO_HAS_ROLE_IRI,
    }
    _OMIT_IF_NONE: ClassVar[frozenset[str]] = frozenset(
        {
            "origin_qualifier", "parent_flow_object_id",
            "parent_intervention_id", "roles",
        }
    )


@dataclass
class FlowRedirect(SerialisableRecord):
    """One deprecated identifier, and the surviving flow it resolves to.

    The export carries only non-deprecated flows, so an identifier this project
    published and later deprecated was indistinguishable from one it never
    harmonised: both are a lookup miss, and a consumer had no way to tell "this
    flow was merged into another one" from "this flow does not exist" (#39).
    These records are the difference.  There is one for every deprecated flow in
    the database, not only for those a consumer is likely to hold, because which
    identifiers are still in circulation is not something this project knows.

    ``replaced_by`` names the *terminal* survivor.  If a flow's replacement were
    itself deprecated later, following one link would land on another redirect,
    and every consumer would have to implement the same chase -- and the same
    cycle guard.  The chain is walked here instead, once.

    Deliberately **not** a `skos:Concept` and **not** `skos:inScheme`: a
    deprecated flow is not a member of the published list, and saying it were
    would contradict its absence from ``flows``.  What these records assert is
    only what is true of the identifier -- that it is deprecated, what replaced
    it, and why.
    """

    identifier: str
    #: The surviving flow, and ``None`` where there is not one.  A withdrawal is
    #: the case with none: the source row the flow was minted from is one this
    #: list has decided not to map, so the flow is gone and nothing takes its
    #: place (#115).  Every other deprecation names a survivor, because the flow
    #: moved rather than ceased.
    #:
    #: This is why the two fields are optional rather than filled with a
    #: sentinel.  A self-referential redirect, or one onto an identifier the
    #: document does not carry, is exactly the silent miss these records exist
    #: to remove; absence, read together with
    #: `brightway:deprecationReason: source-row-withdrawn`, says the true thing.
    #: A consumer holding the identifier should drop the exchange, and find out
    #: why under `brightway:excludedSourceConcept` on the source list's
    #: `xkos:Correspondence`.
    replaced_by_identifier: str | None = None
    jsonld_id: str = ""
    replaced_by: dict[str, str] | None = None
    #: Always ``True``.  A record that exists to say a flow is deprecated could
    #: leave it implicit, but then the statement only holds while the record is
    #: read as part of this list -- and a node that is extracted from the
    #: document, which is the point of giving it an IRI, would carry no
    #: deprecation at all.
    deprecated: bool = True
    #: Whether the two flows were ever the same flow, as an IRI from the minted
    #: deprecation-reason vocabulary.  See
    #: :data:`brightway_flows.domain.vocabulary.DEPRECATION_REASONS` for why
    #: this is not a detail: a redirect between flows the context vocabulary
    #: could not tell apart is not safe to follow blindly.
    deprecation_reason: dict[str, str] = field(default_factory=dict)

    _ALIASES: ClassVar[dict[str, str]] = {
        "jsonld_id": "@id",
        "deprecated": OWL_DEPRECATED,
        "replaced_by": DCTERMS_IS_REPLACED_BY,
        "deprecation_reason": BRIGHTWAY_DEPRECATION_REASON,
    }
    _OMIT_IF_NONE: ClassVar[frozenset[str]] = frozenset(
        {"replaced_by_identifier", "replaced_by"}
    )


@dataclass
class HarmonisedFlowsSimple:
    """Root object of harmonised-flows-simple.json.gz.

    ``jsonld_context`` serialises as ``@context`` and is what makes the document
    JSON-LD rather than JSON with IRI-shaped keys.  It is generated from the term
    registry -- see :func:`brightway_flows.domain.vocabulary.build_jsonld_context`
    -- so a term cannot be published without being declared.
    """

    schema_version: int
    flows: list[SimpleFlow]
    jsonld_context: dict[str, Any] = field(default_factory=dict)
    #: The taxonomies this document describes: the consensus list, and every
    #: source list it maps to.
    concept_schemes: list[Any] = field(default_factory=list)
    #: One `xkos:Correspondence` per source list, each owning its mappings.
    #: This is where `concept_associations` went: they were blank nodes nested
    #: inside each flow under an undeclared key, and are now nodes of their own
    #: under the correspondence that relates the two schemes.
    correspondences: list[Any] = field(default_factory=list)
    #: One :class:`FlowRedirect` per deprecated flow.  Sits beside ``flows``
    #: rather than inside it: a redirect is not a flow, and a consumer
    #: iterating the list must not have to filter these out of it.
    redirects: list[FlowRedirect] = field(default_factory=list)

    _ALIASES: ClassVar[dict[str, str]] = {"jsonld_context": "@context"}

    def to_dict(self) -> dict[str, Any]:
        """Serialise with ``@context`` first, where a reader expects it."""
        return {
            "@context": self.jsonld_context,
            "schema_version": self.schema_version,
            "flows": [flow.to_dict() for flow in self.flows],
            "redirects": [row.to_dict() for row in self.redirects],
            "concept_schemes": [row.to_dict() for row in self.concept_schemes],
            "correspondences": [row.to_dict() for row in self.correspondences],
        }
