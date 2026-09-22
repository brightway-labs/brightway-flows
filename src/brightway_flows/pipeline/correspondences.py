"""The published mappings, as the XKOS model actually defines them.

Until now a mapping was a blank node nested inside the flow it pointed at, and
the key holding it was undeclared -- so the links to EF 3.1, SimaPro and
ecoinvent were in the JSON and contributed nothing to the graph.  #9 removed
the one predicate that would have carried them, `xkos:madeOf`, because its
domain is `xkos:Correspondence` and this project had no such resource.

This module builds it.  The shape is the one
`py-semantic-taxonomy <https://github.com/cauldron/py-semantic-taxonomy>`_ uses::

    Correspondence                     (one per source list)
      ├── xkos:compares  → the two ConceptSchemes it relates
      └── xkos:madeOf    → ConceptAssociation   (its own @id, a real node)
                             ├── xkos:sourceConcept → the source list's flow
                             └── xkos:targetConcept → the consensus flow

Three things follow from that, and each is a change in what gets published:

**Associations are nodes, not blank ones.**  Their IRIs are minted from the two
flows they relate, so the same mapping gets the same IRI on every run and a
consumer can cite one.

**The match is a statement about the concepts.**  XKOS defines no property for
the type or strength of a mapping -- the specification says so -- so
`skos:exactMatch` belongs on the source concept, not on the association.  It is
written inside the `xkos:sourceConcept` node object, which in RDF is exactly a
statement about that concept and not about the association.

**The scheme is recovered from the IRI.**  Associations are built per flow and
carry only IRIs, so which source list a mapping came from is worked out by
matching the source concept's IRI against the registered flow prefixes.  A
mapping whose source belongs to no registered scheme is dropped and counted
rather than guessed at.

## What a correspondence says about what it does *not* map

`xkos:madeOf` lists the pairs that were formed.  A source flow that forms none
is simply absent, and absent is ambiguous: it reads the same whether the flow
was examined and refused or never looked at.  #115 is what that ambiguity costs
-- a consumer counted ecoinvent 3.8's 4,424 elementary exchanges against the
associations, found three fewer, and had no way to learn that all three are
products ecoinvent duplicated into its elementary list by mistake.

So a correspondence carries a second list, `brightway:excludedSourceConcept`,
holding the source flows this list looked at and decided not to map, each with
its reason.  It is a statement about the comparison rather than about either
scheme, which is why it hangs here and not on the source concept scheme: the
vendor goes on shipping the flow whatever this project decides.

Empty is not the same as absent here either, but the distinction is cheaper than
it looks: a list that refuses nothing publishes no key, and a list that refuses
something publishes it, so the presence of the key is the finding.  What was
compared, and against which releases, stays in the curated file the records come
from -- see :mod:`brightway_flows.additional_flows`.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
from importlib.metadata import PackageNotFoundError, version as package_version
from typing import Any, ClassVar

import structlog

from brightway_flows.additional_flows import ExcludedSourceFlow
from brightway_flows.domain.records import SerialisableRecord
from brightway_flows.domain.units import unit_iri_for
from brightway_flows.domain.vocabulary import (
    BIBO_STATUS_ACCEPTED,
    BIBO_STATUS_CURIE,
    BRIGHTWAY_EXCLUDED_SOURCE_CONCEPT_CURIE,
    BRIGHTWAY_EXCLUSION_REASON_CURIE,
    DCTERMS_CREATED_CURIE,
    DCTERMS_CREATOR_CURIE,
    MintedNamespace,
    OWL_VERSION_INFO_CURIE,
    QUDT_CONVERSION_MULTIPLIER_CURIE,
    QUDT_HAS_UNIT_CURIE,
    SKOS_CONCEPT_SCHEME_CURIE,
    SKOS_PREF_LABEL_CURIE,
    SourceScheme,
    XKOS_COMPARES_CURIE,
    XKOS_CONCEPT_ASSOCIATION_CURIE,
    XKOS_CORRESPONDENCE_CURIE,
    XKOS_MADE_OF_CURIE,
    XKOS_SOURCE_CONCEPT_CURIE,
    XKOS_TARGET_CONCEPT_CURIE,
    scheme_for_flow_iri,
)
from brightway_flows.pipeline.match_strength import (
    Cardinality,
    match_property_key,
    rewrite_source_concept,
)

logger = structlog.get_logger(__name__)

#: The consensus list itself, as a scheme.  Every published flow is a
#: `skos:Concept` in it, and every correspondence compares something to it.
CONSENSUS_SCHEME_IRI = MintedNamespace.CONSENSUS_SCHEME.value
CONSENSUS_SCHEME_LABEL = "Consensus elementary flow list"


@dataclass
class ConceptSchemeNode(SerialisableRecord):
    """A `skos:ConceptScheme`: the consensus list, or one source list."""

    jsonld_id: str
    pref_label: dict[str, str]
    version_info: str = ""
    jsonld_type: str = SKOS_CONCEPT_SCHEME_CURIE
    status: dict[str, str] = field(
        default_factory=lambda: {"@id": BIBO_STATUS_ACCEPTED}
    )
    #: Set on the consensus scheme and left unset on a source list's, because
    #: they are different claims.  This project created the consensus list; it
    #: did not create EF 3.1 or ecoinvent, and stamping itself as their creator
    #: would be false.  A source scheme appears here only so the correspondence
    #: has something well-formed to `xkos:compares`, and what it asserts about
    #: that scheme should stay limited to its IRI, label and version.
    created: str | None = None
    creator: str | None = None

    _ALIASES: ClassVar[dict[str, str]] = {
        "jsonld_id": "@id",
        "jsonld_type": "@type",
        "pref_label": SKOS_PREF_LABEL_CURIE,
        "version_info": OWL_VERSION_INFO_CURIE,
        "status": BIBO_STATUS_CURIE,
        "created": DCTERMS_CREATED_CURIE,
        "creator": DCTERMS_CREATOR_CURIE,
    }
    _OMIT_IF_NONE: ClassVar[frozenset[str]] = frozenset({"created", "creator"})


@dataclass
class ConceptAssociationNode(SerialisableRecord):
    """One `xkos:ConceptAssociation`, with an IRI of its own.

    `source_concept` is a node object rather than a bare reference: the source
    list's label, unit and `skos:exactMatch` are statements about that concept,
    and nesting them here is how they reach the graph attached to it.
    """

    jsonld_id: str
    source_concept: dict[str, Any]
    target_concept: dict[str, Any]
    jsonld_type: str = XKOS_CONCEPT_ASSOCIATION_CURIE
    conversion_multiplier: float | None = None

    _ALIASES: ClassVar[dict[str, str]] = {
        "jsonld_id": "@id",
        "jsonld_type": "@type",
        "source_concept": XKOS_SOURCE_CONCEPT_CURIE,
        "target_concept": XKOS_TARGET_CONCEPT_CURIE,
        "conversion_multiplier": QUDT_CONVERSION_MULTIPLIER_CURIE,
    }
    _OMIT_IF_NONE: ClassVar[frozenset[str]] = frozenset({"conversion_multiplier"})


@dataclass
class CorrespondenceNode(SerialisableRecord):
    """One `xkos:Correspondence`: everything mapped between two schemes."""

    jsonld_id: str
    pref_label: dict[str, str]
    compares: list[dict[str, str]]
    made_of: list[ConceptAssociationNode] = field(default_factory=list)
    version_info: str = ""
    jsonld_type: str = XKOS_CORRESPONDENCE_CURIE
    status: dict[str, str] = field(
        default_factory=lambda: {"@id": BIBO_STATUS_ACCEPTED}
    )
    #: Always set, unlike on a source `ConceptSchemeNode`.  A correspondence is
    #: this project's own assertion -- that these two schemes were compared and
    #: these concepts matched -- so it has exactly one creator and one moment of
    #: creation, and both are ours to state.
    created: str | None = None
    creator: str | None = None
    #: The source flows this list examined and decided not to map, each a node
    #: object carrying the vendor's own identity for the flow -- IRI, label,
    #: compartment path and unit -- and `brightway:exclusionReason`.
    #:
    #: ``None`` rather than ``[]`` for a list that excludes nothing, so the key
    #: is absent rather than empty: a correspondence that has refused nothing and
    #: one whose exclusions were not loaded should not serialise alike.
    #:
    #: The label is the vendor's spelling, not the consensus list's.  Nothing
    #: was harmonised here, so there is no consensus spelling to give -- and the
    #: consumer this record is for is holding the vendor's file, where the
    #: vendor's spelling is what they will find.
    excluded_source_concepts: list[dict[str, Any]] | None = None

    _ALIASES: ClassVar[dict[str, str]] = {
        "jsonld_id": "@id",
        "jsonld_type": "@type",
        "pref_label": SKOS_PREF_LABEL_CURIE,
        "compares": XKOS_COMPARES_CURIE,
        "made_of": XKOS_MADE_OF_CURIE,
        "version_info": OWL_VERSION_INFO_CURIE,
        "status": BIBO_STATUS_CURIE,
        "created": DCTERMS_CREATED_CURIE,
        "creator": DCTERMS_CREATOR_CURIE,
        "excluded_source_concepts": BRIGHTWAY_EXCLUDED_SOURCE_CONCEPT_CURIE,
    }
    _OMIT_IF_NONE: ClassVar[frozenset[str]] = frozenset(
        {"created", "creator", "excluded_source_concepts"}
    )
    #: Described rather than merely named, for the reason `context` was in
    #: schema version 6: `list[dict[str, Any]]` generates "an array of objects,
    #: contents unspecified", which permits anything and tells a consumer
    #: nothing.  The node is built in one place -- see
    #: :func:`excluded_source_concept_node` -- so its shape is known here even
    #: though the annotation cannot carry it.
    _SERIALISED_SCHEMAS: ClassVar[dict[str, dict[str, Any]]] = {
        "excluded_source_concepts": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "@id": {
                        "type": "string",
                        "description": (
                            "The source list's own IRI for the flow, minted from "
                            "that list's flow prefix and the vendor's identifier."
                        ),
                    },
                    SKOS_PREF_LABEL_CURIE: {
                        "type": "string",
                        "description": "The vendor's spelling of the flow's name.",
                    },
                    "context": {
                        "type": "string",
                        "description": (
                            "The vendor's compartment path, joined with ' / '. "
                            "Not a consensus context: nothing was harmonised here."
                        ),
                    },
                    QUDT_HAS_UNIT_CURIE: {
                        "type": "object",
                        "additionalProperties": {"type": "string"},
                        "description": "The flow's unit, as a minted unit IRI.",
                    },
                    BRIGHTWAY_EXCLUSION_REASON_CURIE: {
                        "type": "string",
                        "description": "Why this list does not map the flow.",
                    },
                },
                "required": ["@id", SKOS_PREF_LABEL_CURIE, BRIGHTWAY_EXCLUSION_REASON_CURIE],
            },
        }
    }

    def to_dict(self) -> dict[str, Any]:
        """Serialise, expanding the associations.

        `_NESTED` handles a field holding one record; this one holds a list of
        them, which is why the conversion is written out here.
        """
        payload = super().to_dict()
        payload[XKOS_MADE_OF_CURIE] = [row.to_dict() for row in self.made_of]
        return payload


def excluded_source_concept_node(
    record: ExcludedSourceFlow, scheme: SourceScheme
) -> dict[str, Any]:
    """One :class:`~brightway_flows.additional_flows.ExcludedSourceFlow`, as
    it appears under `brightway:excludedSourceConcept`.

    Shaped like an association's `xkos:sourceConcept` -- same `@id`,
    `skos:prefLabel`, `context` and `qudt:hasUnit` keys -- so that a consumer
    reading both lists off one correspondence reads one shape twice.  What it
    does not carry is a `skos:` mapping property, and that absence is the point:
    there is no concept on the other side to relate it to.

    The IRI is minted from *scheme* rather than stored on the record, for the
    reason every other source-flow IRI is: the prefix is the scheme's, and a
    second copy of it in a curated file is a second place for it to go stale.
    """
    node: dict[str, Any] = {
        "@id": f"{scheme.flow_prefix}{record.uuid}",
        SKOS_PREF_LABEL_CURIE: record.name,
    }
    if record.context:
        node["context"] = " / ".join(record.context)
    if unit_iri := unit_iri_for(record.unit):
        node[QUDT_HAS_UNIT_CURIE] = {"@id": unit_iri}
    node[BRIGHTWAY_EXCLUSION_REASON_CURIE] = record.reason
    return node


def _language_label(value: str) -> dict[str, str]:
    return {"@value": value, "@language": "en"}


#: The distributed name of this project, as `importlib.metadata` knows it.
_DISTRIBUTION = "brightway-flows"

#: The name `creator` writes into the export.  Still the project's name before
#: it became `brightway-flows`: it is published, and the rename changed nothing
#: a build writes.  Moving it is a change to the output and a decision of its own.
_CREATOR_NAME = "brightway-flows"


def creator() -> str:
    """What produced this document: the project, and which version of it.

    A plain literal rather than an IRI.  `dcterms:creator` ranges over
    `dcterms:Agent`, and a piece of software is one -- but this project has no
    published IRI for itself, and minting one to describe the generator would
    be a second publishing commitment for no gain over the string PyST accepts.

    The version falls back to `unknown` rather than raising: an editable
    checkout with no installed distribution metadata is a normal way to run
    this, and failing an export over a provenance label would be the wrong
    trade.
    """
    try:
        return f"{_CREATOR_NAME} {package_version(_DISTRIBUTION)}"
    except PackageNotFoundError:
        return f"{_CREATOR_NAME} unknown"


def _now() -> str:
    """The run's timestamp, as `xsd:dateTime` in UTC.

    The one value in the export that differs between two runs over identical
    inputs, which is why `tools/verify_run.py` scrubs it.
    """
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _local_name(iri: str, prefix: str) -> str:
    return iri[len(prefix):].strip("/") if iri.startswith(prefix) else iri.rsplit("/", 1)[-1]


def association_iri(scheme: SourceScheme, source_iri: str, target_iri: str) -> str:
    """A stable IRI for one mapping.

    Built from the two flows it relates, so the same mapping gets the same IRI
    on every run -- which is what makes it citable, and what stops a rebuild
    from renaming every association in the graph.
    """
    source = _local_name(source_iri, scheme.flow_prefix)
    target = _local_name(target_iri, MintedNamespace.CONSENSUS_ELEMENTARY_FLOW.value)
    return f"{MintedNamespace.ASSOCIATION.value}{scheme.slug}/{source}/{target}"


def _consensus_scheme_node(created: str) -> ConceptSchemeNode:
    return ConceptSchemeNode(
        jsonld_id=CONSENSUS_SCHEME_IRI,
        pref_label=_language_label(CONSENSUS_SCHEME_LABEL),
        created=created,
        creator=creator(),
    )


def build_correspondences(
    flows: list[dict[str, Any]],
    *,
    created: str | None = None,
    excluded: Mapping[str, tuple[ExcludedSourceFlow, ...]] | None = None,
) -> tuple[list[ConceptSchemeNode], list[CorrespondenceNode], Counter]:
    """Regroup the per-flow associations into correspondences.

    *flows* are the published flow payloads, each still carrying the
    `concept_associations` the pipeline attached to it.  Returns the concept
    schemes, one correspondence per source list that actually contributed a
    mapping, and a tally.

    A source list with no mappings gets no correspondence: an empty
    `xkos:Correspondence` asserts that two schemes were compared and nothing
    matched, which is a different claim from not having compared them.

    *created* is the `dcterms:created` stamp written on the consensus scheme and
    on every correspondence.  Taken as an argument rather than read from the
    clock per node so that one document carries one timestamp: nodes built
    milliseconds apart would otherwise disagree about when the run happened.
    Defaults to now, which is what a caller building a document wants.

    *excluded* is what each list refused, keyed by scheme slug, from
    :func:`~brightway_flows.sources.excluded_source_flows`.  Entries for a
    scheme this build publishes no correspondence for are dropped and counted:
    there is no node to hang them off, and minting an otherwise empty
    correspondence to carry them would assert that the two schemes were compared
    when the build did not merge one of them.  Default ``None`` reads the
    registry; pass ``{}`` for a caller that wants the associations alone.
    """
    created = created if created is not None else _now()
    if excluded is None:
        # Imported here rather than at module scope: `sources` reaches
        # `pipeline.loading` and back, the same cycle `additional_flows` breaks
        # this way.
        from brightway_flows.sources import excluded_source_flows

        excluded = excluded_source_flows()
    counts: Counter = Counter()
    by_scheme: dict[str, list[ConceptAssociationNode]] = defaultdict(list)
    schemes_seen: dict[str, SourceScheme] = {}
    seen_iris: set[str] = set()
    #: One entry per mapping that will be published: the scheme it belongs to,
    #: its association IRI, the two flows, a copy of the source concept, and the
    #: conversion factor.  Collected before any node is built, because the match
    #: strength of any one mapping depends on mappings its flow never sees.
    collected: list[tuple[SourceScheme, str, str, str, dict[str, Any], float | None]] = []
    cardinality = Cardinality()

    for flow in flows:
        associations = flow.get("concept_associations")
        if not isinstance(associations, list):
            continue
        for association in associations:
            if not isinstance(association, dict):
                continue
            source = association.get(XKOS_SOURCE_CONCEPT_CURIE)
            target = association.get(XKOS_TARGET_CONCEPT_CURIE)
            if not isinstance(source, dict) or not isinstance(target, dict):
                counts["skipped_malformed"] += 1
                continue
            source_iri = str(source.get("@id") or "").strip()
            target_iri = str(target.get("@id") or "").strip()
            if not source_iri or not target_iri:
                counts["skipped_missing_iri"] += 1
                continue
            scheme = scheme_for_flow_iri(source_iri)
            if scheme is None:
                counts["skipped_unknown_scheme"] += 1
                continue
            iri = association_iri(scheme, source_iri, target_iri)
            if iri in seen_iris:
                # The same pair reached here twice -- one mapping, one node.
                counts["deduplicated"] += 1
                continue
            seen_iris.add(iri)
            schemes_seen[scheme.slug] = scheme
            multiplier = association.get(QUDT_CONVERSION_MULTIPLIER_CURIE)
            # Copied, not referenced: the strength is settled below and the
            # payload this came from belongs to the caller.
            collected.append((
                scheme,
                iri,
                source_iri,
                target_iri,
                dict(source),
                (
                    float(multiplier)
                    if isinstance(multiplier, (int, float))
                    and not isinstance(multiplier, bool)
                    else None
                ),
            ))
            cardinality.observe(scheme.slug, source_iri, target_iri)
            counts[f"associations_{scheme.slug}"] += 1

    # The strength, settled with every mapping of every list in hand.  The
    # merge writes it one row at a time and `match_strength` corrects the
    # records and the database before this runs, so in a healthy run nothing is
    # weakened here and the counter stays absent.  It is done again anyway
    # because this is the last point before the claim is published, and a
    # non-zero `weakened_*` says a route into the export skipped the pass (#76).
    for scheme, iri, source_iri, target_iri, source, multiplier in collected:
        current = match_property_key(source)
        published = cardinality.published_match_for(
            current, scheme.slug, source_iri, target_iri
        )
        if rewrite_source_concept(source, published):
            counts[f"weakened_{scheme.slug}"] += 1
        by_scheme[scheme.slug].append(
            ConceptAssociationNode(
                jsonld_id=iri,
                source_concept=source,
                target_concept={"@id": target_iri},
                conversion_multiplier=multiplier,
            )
        )

    schemes = [_consensus_scheme_node(created)]
    correspondences: list[CorrespondenceNode] = []
    for slug in sorted(by_scheme):
        scheme = schemes_seen[slug]
        schemes.append(
            ConceptSchemeNode(
                jsonld_id=scheme.scheme_iri,
                pref_label=_language_label(scheme.label),
                version_info=scheme.version,
            )
        )
        correspondences.append(
            CorrespondenceNode(
                jsonld_id=f"{MintedNamespace.CORRESPONDENCE.value}{slug}",
                pref_label=_language_label(
                    f"{scheme.label} to {CONSENSUS_SCHEME_LABEL}"
                ),
                compares=[
                    {"@id": scheme.scheme_iri},
                    {"@id": CONSENSUS_SCHEME_IRI},
                ],
                made_of=sorted(by_scheme[slug], key=lambda row: row.jsonld_id),
                version_info=scheme.version,
                created=created,
                creator=creator(),
                excluded_source_concepts=(
                    [
                        excluded_source_concept_node(record, scheme)
                        for record in refused
                    ]
                    if (refused := excluded.get(slug))
                    else None
                ),
            )
        )
        if refused:
            counts[f"excluded_{slug}"] += len(refused)

    for slug, refused in excluded.items():
        if slug not in by_scheme:
            counts["excluded_scheme_not_published"] += len(refused)
            logger.info(
                "exclusions_for_unpublished_scheme", scheme=slug, records=len(refused)
            )

    logger.info("built_correspondences", correspondences=len(correspondences), **dict(counts))
    return schemes, correspondences, counts
