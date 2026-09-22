from dataclasses import dataclass, field
from hashlib import sha1
from typing import Any, ClassVar

from brightway_flows.domain.common import Provenance
from brightway_flows.domain.records import SerialisableRecord
from brightway_flows.domain.vocabulary import (
    RDFS_LABEL_CURIE,
    RDFS_SEE_ALSO_CURIE,
    RO_HAS_ROLE_IRI,
    SKOS_DEFINITION_IRI,
)


def stable_flow_object_id(prefix: str, basis: str) -> str:
    """A flow object identifier derived from what makes the object that object.

    *basis* is a namespaced string naming the grouping key -- ``cas:7440-61-1``,
    ``name:carbon dioxide``, ``nuclide:U-238``, ``element:Am``.  The identifier
    is a function of it, so an object keeps its id across runs for as long as it
    is grouped the same way, and two objects grouped differently cannot collide.

    Lives here rather than in ``flow_layers.layering`` because two callers mint
    identifiers now: the layering, from the flows it is grouping, and the
    element enrichment, for an element that has isotopes in the list but no
    flow of its own.  ``elements`` cannot import ``layering`` -- ``layering``
    imports ``elements`` -- and a second copy of a hashing convention is how two
    passes come to disagree about what an identifier means.
    """
    return f"{prefix}-{sha1(basis.encode('utf-8')).hexdigest()[:16]}"


@dataclass
class Classification:
    value: list[str]
    resource_urls: list[str] = field(default_factory=list)
    skos_match_predicate: str | None = None
    provenance: Provenance | None = None
    per_value_provenance: dict[str, dict[str, Any]] | None = None

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "@value": self.value,
        }
        if self.resource_urls:
            payload[RDFS_SEE_ALSO_CURIE] = self.resource_urls
        if self.skos_match_predicate and self.resource_urls:
            payload[self.skos_match_predicate] = [
                {"@id": url}
                for url in self.resource_urls
            ]
        if self.provenance:
            payload["provenance"] = self.provenance.to_dict()
        if self.per_value_provenance:
            payload["per_value_provenance"] = self.per_value_provenance
        return payload


@dataclass
class Role:
    """One `RO:0000087 has role` assertion on a flow object.

    *iri* is the ChEBI role class; *label* and *definition* are copied from
    ChEBI so a reader does not have to resolve the IRI to know what the row
    says, and so the published document stays readable offline.

    *provenance* says who asserted it.  Two kinds reach this field and they must
    stay distinguishable: ChEBI's own `has role` edges, and a curator's decision
    for a substance ChEBI has no role for.  A generated assertion can be
    recomputed from a newer ChEBI release; a curated one cannot, and overwriting
    it silently is how a reasoned decision becomes invisible.
    """

    iri: str
    label: str
    definition: str | None = None
    provenance: Provenance | None = None

    def to_dict(self) -> dict[str, Any]:
        # `rdfs:label` rather than a bare `label`, to match `Classification`
        # in this module, which keys `rdfs:seeAlso`.  Both forms expand
        # identically -- `label` is declared in `JSONLD_CONTEXT` and resolves to
        # `rdfs:label` -- so this is consistency and not a correctness fix.
        #
        # `provenance` below stays a bare short name, and is *not* declared, so
        # it is the key here that really does drop on expansion.  Deliberately
        # unchanged: `Classification` publishes `provenance` and
        # `per_value_provenance` the same way, and giving one record its own
        # convention would be worse than the shared one being imperfect.
        payload: dict[str, Any] = {"@id": self.iri, RDFS_LABEL_CURIE: self.label}
        if self.definition:
            payload[SKOS_DEFINITION_IRI] = self.definition
        if self.provenance:
            payload["provenance"] = self.provenance.to_dict()
        return payload


@dataclass
class FlowObject(SerialisableRecord):
    flow_object_id: str
    prefLabel: list[dict[str, Any]]
    altLabel: list[dict[str, Any]]
    properties: dict[str, Any]
    references: list[Any]
    created_from: dict[str, Any]
    classifications: dict[str, dict[str, Any]] = field(default_factory=dict)
    # Qualifier for flows that require a separate flow object despite sharing
    # registry identifiers with the base substance.  Values: "biogenic",
    # "fossil", "land_use_change", "green_water", "blue_water", "grey_water",
    # or None (unqualified base substance).
    origin_qualifier: str | None = None
    # For qualified flows: the flow_object_id of the parent unqualified substance.
    parent_flow_object_id: str | None = None
    # For a non-material intervention: the flow_object_id of the family this
    # object is one member of -- the `Noise` every `Noise, Road, Lorry,
    # Average` is noise of (#70).  A second field rather than a reuse of
    # `parent_flow_object_id`, which serialises under `brightway:baseSubstance`
    # and would publish these objects as substances, which is the one thing
    # they are not.
    parent_intervention_id: str | None = None
    # SKOS definitions; serialised under the SKOS definition IRI.
    skos_definition: list[dict[str, Any]] | None = None
    # RDF types, e.g. chemrof:FullySpecifiedAtom.  Serialised as "@type".
    types: list[str] | None = None
    # What the substance is *used for* -- herbicide, fertilizer, environmental
    # contaminant -- as ChEBI role class IRIs under `RO:0000087 has role`.
    #
    # A list rather than a scalar because a role is many-valued: sulfluramid is
    # an insecticide and an acaricide, and chlorfenapyr is both plus a
    # proinsecticide.  That is also why this is not `parent_flow_object_id`,
    # which is single and already means the undifferentiated substance a
    # qualified flow was split from.
    #
    # Each entry is a serialised `Role`; see its docstring for the shape.
    # Allow-listed against `data/chebi-roles.json` -- ChEBI's role tree is
    # mostly biomedical, and publishing all of it would bury the fourteen roles
    # that group anything an LCA asks about.
    #
    # Reaches `flow-objects.json` and SQLite, and deliberately **not**
    # `harmonised-flows-simple` yet: `SimpleFlow` is a separate published
    # contract with `additionalProperties: false`, so carrying roles there is a
    # second schema bump and its own change.  Worth doing -- the simple export
    # is the one a practitioner reads -- and noted here rather than left for
    # someone to find as an omission.
    roles: list[dict[str, Any]] | None = None

    _ALIASES: ClassVar[dict[str, str]] = {
        "skos_definition": SKOS_DEFINITION_IRI,
        "types": "@type",
        "roles": RO_HAS_ROLE_IRI,
    }
    # These keys were absent unless set, so they must not serialise as null.
    _OMIT_IF_NONE: ClassVar[frozenset[str]] = frozenset({
        "skos_definition", "types", "roles",
    })
