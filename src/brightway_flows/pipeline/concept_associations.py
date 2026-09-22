"""Links from consensus flows back to the source-list flows they came from.

Each association is an xkos:ConceptAssociation carrying a SKOS mapping property
on the source concept.  XKOS defines no property for the type of a mapping, so
the match kind is expressed with skos:exactMatch / skos:broadMatch /
skos:narrowMatch / skos:relatedMatch directly.

There used to be a builder class per source list, and only one of the two was
registered: SimaPro associations were never built in any real run, while every
`extract` downloaded and parsed the 124,318-row GLAD workbook to feed them
(#244).  The classes differed in four things -- which scheme's IRIs to mint,
where the pairs come from, what to cite, and whether a conversion factor exists
-- so they are now one builder configured from a manifest's
`concept_associations` block, and a list's mappings are built only on a run that
names that list.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Callable, Protocol

import orjson
import structlog

from brightway_flows.domain.common import Provenance
from brightway_flows.domain.elementary_flow import ElementaryFlow
from brightway_flows.domain.units import unit_iri_for
from brightway_flows.domain.vocabulary import (
    CONSENSUS_ELEMENTARY_FLOW_IRI_PREFIX,
    QUDT_CONVERSION_MULTIPLIER_CURIE,
    QUDT_HAS_UNIT_CURIE,
    SKOS_EXACT_MATCH_CURIE,
    SKOS_PREF_LABEL_CURIE,
    SourceScheme,
    XKOS_CONCEPT_ASSOCIATION_CURIE,
    XKOS_SOURCE_CONCEPT_CURIE,
    XKOS_TARGET_CONCEPT_CURIE,
    source_scheme,
)
from brightway_flows.filesystem import glad_ilcd_to_simapro_path
from brightway_flows.pipeline.match_strength import match_property

if TYPE_CHECKING:  # pragma: no cover - import cycle at runtime, types only
    from brightway_flows.sources import SourceList

logger = structlog.get_logger(__name__)

#: What a `glad` pair source cites as `prov:hadPrimarySource` when its manifest
#: names none.  Kept here rather than only in a manifest because it is a
#: property of the table this module reads, not of the list that asks for it.
GLAD_PRIMARY_SOURCE = "https://github.com/One-Click-LCA/GLAD-ElementaryFlowResources"


@dataclass(frozen=True)
class SourceConcept:
    """One source-list flow, as it will appear as an `xkos:sourceConcept`.

    The match property is carried here rather than fixed by the builder because
    it is a statement about *this pair*: a correspondence table can pair one
    source flow with several consensus flows, and `skos:exactMatch` -- which is
    symmetric and transitive -- would then entail that those consensus flows are
    the same concept as each other.
    """

    iri: str
    label: str = ""
    context: str = ""
    unit: str = ""
    match: str = SKOS_EXACT_MATCH_CURIE
    conversion_multiplier: float | None = None


class PairSource(Protocol):
    """Where one list's (source flow, consensus flow) pairs come from."""

    def prepare(self, elementary_flows: list[ElementaryFlow]) -> None:
        """See the whole flow list once, before any association is built.

        Two things need it and neither is knowable one flow at a time: which
        deprecated flow a mapping should be redirected to, and how many
        consensus flows a source flow is paired with -- the latter being what
        decides the match property.
        """

    def concepts_for(self, flow_id: str, flow: ElementaryFlow) -> list[SourceConcept]:
        """The source-list flows paired with the consensus flow *flow_id*."""


class SourceRefPairs:
    """Pairs read from the flow's own ``source_refs``.

    For a list the consensus flows were built or merged from: each flow records
    which of that list's flows it came from, so the pairing is already on the
    record and no correspondence table is involved.
    """

    def __init__(self, *, list_name: str, scheme: SourceScheme) -> None:
        self._list_name = list_name
        self._scheme = scheme

    def prepare(self, elementary_flows: list[ElementaryFlow]) -> None:
        """Nothing to see: a `source_refs` pairing is written one flow at a time.

        It used to say every such pairing was one-to-one and therefore exact.
        It is not: deduplication retires one consensus flow onto another and
        moves its refs there, which on the 2026-08-13 build left 28 EF 3.1 flows
        carrying two refs to one flow and claiming both were exact matches for
        it.  The strength is settled by
        :mod:`brightway_flows.pipeline.match_strength` once the whole list
        is in view (#76); what is written here is the claim before that count.
        """

    def concepts_for(self, flow_id: str, flow: ElementaryFlow) -> list[SourceConcept]:
        unit = str(flow.unit or "").strip()
        concepts: list[SourceConcept] = []
        for ref in flow.source_refs or []:
            if not isinstance(ref, dict) or ref.get("list_name") != self._list_name:
                continue
            source_uuid = str(ref.get("source_flow_uuid") or "").strip()
            if not source_uuid:
                continue
            original = ref.get("source_metadata", {}).get("original_context", [])
            concepts.append(
                SourceConcept(
                    iri=f"{self._scheme.flow_prefix}{source_uuid}",
                    label=str(ref.get("source_flow_name") or "").strip(),
                    context="/".join(
                        str(part)
                        for part in original
                        if isinstance(part, str) and str(part).strip()
                    ),
                    unit=unit,
                )
            )
        return concepts


def _context_slug(value: str) -> str:
    """A single IRI path segment for a source list's compartment string."""
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", value.lower())).strip("-")


class GladPairs:
    """Pairs read from the GLAD ILCD-to-SimaPro correspondence table.

    GLAD is the only route to SimaPro flow identity: the consensus list is built
    from EF 3.1 and has never merged SimaPro, so a flow carries no SimaPro
    ``source_refs``.  The table pairs an EF 3.1 flow UUID with a SimaPro one, and
    the EF UUID *is* the consensus flow's id, which is what makes the join
    possible at all.

    Two properties of the table shape everything here:

    **``TargetFlowUUID`` identifies a substance, not a flow.**  25,777 of its
    33,238 target UUIDs appear under more than one ``TargetFlowContext``, so
    minting one IRI per UUID gave a single SimaPro concept up to twelve
    `skos:exactMatch` statements -- one of them entailing that Beryllium and
    Beryllium(2+) are the same concept.  A SimaPro flow is a substance *in a
    compartment*, so the compartment is part of the minted IRI.

    **``MatchCondition`` is ``=`` on all 124,318 rows** and cannot be believed
    as a claim of equivalence: 90 consensus flows are paired with more than one
    SimaPro flow (one with 441 -- SimaPro's per-country water flows). The match
    property is therefore derived from the cardinality of the pairing, not read
    from the column.
    """

    def __init__(self, *, scheme: SourceScheme) -> None:
        self._scheme = scheme
        self._concepts: dict[str, list[SourceConcept]] = {}

    def prepare(self, elementary_flows: list[ElementaryFlow]) -> None:
        rows = self._load_rows()
        if not rows:
            self._concepts = {}
            return

        live, replacement = _replacement_index(elementary_flows)

        # Two passes: the match property of any one pair depends on how many
        # other pairs share either end of it, so nothing can be emitted until
        # every row has been placed.
        pairs: list[tuple[str, str, dict[str, Any]]] = []
        counts = {
            "rows": len(rows),
            "skipped_no_uuid": 0,
            "skipped_no_context": 0,
            "skipped_unknown_flow": 0,
            "redirected_from_deprecated": 0,
            "deduplicated": 0,
        }
        for row in rows:
            source_uuid = str(row.get("SourceFlowUUID") or "").strip()
            target_uuid = str(row.get("TargetFlowUUID") or "").strip()
            if not source_uuid or not target_uuid:
                counts["skipped_no_uuid"] += 1
                continue
            context = str(row.get("TargetFlowContext") or "").strip()
            slug = _context_slug(context)
            if not slug:
                # Without a compartment the row does not name a SimaPro flow,
                # only a substance, and there is no IRI to mint that would not
                # collide with a real one.
                counts["skipped_no_context"] += 1
                continue
            flow_id = replacement.get(source_uuid, source_uuid)
            if flow_id != source_uuid:
                counts["redirected_from_deprecated"] += 1
            if flow_id not in live:
                counts["skipped_unknown_flow"] += 1
                continue
            pairs.append((f"{self._scheme.flow_prefix}{target_uuid}/{slug}", flow_id, row))

        targets_per_source: dict[str, set[str]] = {}
        sources_per_target: dict[str, set[str]] = {}
        for source_iri, flow_id, _row in pairs:
            targets_per_source.setdefault(source_iri, set()).add(flow_id)
            sources_per_target.setdefault(flow_id, set()).add(source_iri)

        concepts: dict[str, list[SourceConcept]] = {}
        seen: set[tuple[str, str]] = set()
        matches: dict[str, int] = {}
        for source_iri, flow_id, row in pairs:
            if (source_iri, flow_id) in seen:
                # Two rows differing only in a field the IRI does not carry --
                # 99 of them differ only by `TargetGeography`. One pair, one
                # association.
                counts["deduplicated"] += 1
                continue
            seen.add((source_iri, flow_id))
            match = match_property(
                broader_than_target=len(targets_per_source[source_iri]) > 1,
                narrower_than_target=len(sources_per_target[flow_id]) > 1,
            )
            matches[match] = matches.get(match, 0) + 1
            multiplier = row.get("ConversionFactor")
            concepts.setdefault(flow_id, []).append(
                SourceConcept(
                    iri=source_iri,
                    label=str(row.get("TargetFlowName") or "").strip(),
                    context=str(row.get("TargetFlowContext") or "").strip(),
                    unit=str(row.get("TargetUnit") or "").strip(),
                    match=match,
                    conversion_multiplier=(
                        float(multiplier)
                        if isinstance(multiplier, (int, float))
                        and not isinstance(multiplier, bool)
                        and multiplier != 1.0
                        else None
                    ),
                )
            )
        self._concepts = concepts
        logger.info(
            "indexed_glad_correspondence",
            source_concepts=len(targets_per_source),
            consensus_flows=len(concepts),
            **{k: v for k, v in counts.items() if v},
            **{f"match_{k.split(':')[-1]}": v for k, v in matches.items()},
        )

    def _load_rows(self) -> list[dict[str, Any]]:
        path = glad_ilcd_to_simapro_path()
        if not path.exists():
            logger.warning("glad_mapping_not_found", path=str(path))
            return []
        payload = orjson.loads(path.read_bytes())
        return [row for row in payload if isinstance(row, dict)]

    def concepts_for(self, flow_id: str, flow: ElementaryFlow) -> list[SourceConcept]:
        return self._concepts.get(flow_id, [])


def _replacement_index(
    elementary_flows: list[ElementaryFlow],
) -> tuple[set[str], dict[str, str]]:
    """Live flow ids, and where each deprecated one's mappings should land.

    A correspondence table pairs with the flow list as it was, and the duplicate
    pass deprecates flows after the fact.  Dropping those mappings would have
    lost 17,693 SimaPro flows -- 14.6% of the table -- to no purpose: every
    deprecated flow names its replacement, so the mapping follows it there.
    """
    live: set[str] = set()
    replaced_by: dict[str, str] = {}
    for flow in elementary_flows:
        flow_id = flow.elementary_flow_id.strip()
        if not flow_id:
            continue
        if flow.owl_deprecated is True:
            if replacement := str(flow.is_replaced_by_uuid or "").strip():
                replaced_by[flow_id] = replacement
        else:
            live.add(flow_id)

    resolved: dict[str, str] = {}
    for flow_id in replaced_by:
        target = flow_id
        seen = {flow_id}
        while (nxt := replaced_by.get(target)) is not None and nxt not in seen:
            seen.add(nxt)
            target = nxt
        resolved[flow_id] = target
    return live, resolved


class ConceptAssociationBuilder:
    """Builds one list's `xkos:ConceptAssociation` entries.

    Configured, not subclassed: what a list needs is a scheme to mint IRIs in, a
    :class:`PairSource`, and a primary source to cite.
    """

    def __init__(
        self,
        *,
        name: str,
        scheme: SourceScheme,
        pairs: PairSource,
        primary_source: str = "",
    ) -> None:
        self.name = name
        self.scheme = scheme
        self._pairs = pairs
        self._prov = Provenance(
            was_generated_by="build_concept_associations",
            was_attributed_to="brightway-flows",
            had_primary_source=[primary_source] if primary_source else [],
        ).to_dict()

    def prepare(self, elementary_flows: list[ElementaryFlow]) -> None:
        self._pairs.prepare(elementary_flows)

    def build_associations(
        self,
        flow_id: str,
        flow: ElementaryFlow,
        target_node: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """Return associations for one flow. Called only for non-deprecated flows."""
        associations: list[dict[str, Any]] = []
        for concept in self._pairs.concepts_for(flow_id, flow):
            source_node: dict[str, Any] = {"@id": concept.iri}
            if concept.label:
                source_node[SKOS_PREF_LABEL_CURIE] = concept.label
            if concept.context:
                source_node["context"] = concept.context
            if unit_iri := unit_iri_for(concept.unit):
                source_node[QUDT_HAS_UNIT_CURIE] = {"@id": unit_iri}
            source_node[concept.match] = {"@id": target_node["@id"]}
            association: dict[str, Any] = {
                "@type": XKOS_CONCEPT_ASSOCIATION_CURIE,
                XKOS_SOURCE_CONCEPT_CURIE: source_node,
                XKOS_TARGET_CONCEPT_CURIE: target_node,
                "provenance": self._prov,
            }
            if concept.conversion_multiplier is not None:
                association[QUDT_CONVERSION_MULTIPLIER_CURIE] = (
                    concept.conversion_multiplier
                )
            associations.append(association)
        return associations


#: One implementation per name in `sources.PAIR_SOURCES`, which is the manifest
#: vocabulary those names come from.  `tests/test_concept_associations.py` pins
#: the two sets equal, so a name cannot be accepted by a manifest with nothing
#: here to build it.
_PAIR_SOURCES: dict[str, Callable[[SourceList, SourceScheme], PairSource]] = {
    "source_refs": lambda source, scheme: SourceRefPairs(
        list_name=source.list_name, scheme=scheme
    ),
    "glad": lambda source, scheme: GladPairs(scheme=scheme),
}

#: Cited when a manifest names no `primary_source`.  A pair source that reads
#: one fixed artifact already knows what that artifact is; one that reads the
#: flows has to be told, because the artifact is whichever list it belongs to.
_DEFAULT_PRIMARY_SOURCE: dict[str, str] = {"glad": GLAD_PRIMARY_SOURCE}


def builder_for(source: SourceList) -> ConceptAssociationBuilder | None:
    """The builder *source*'s manifest asks for, or ``None`` if it declares none."""
    spec = source.concept_associations
    if spec is None:
        return None
    scheme = source_scheme(spec.scheme)
    return ConceptAssociationBuilder(
        name=spec.scheme,
        scheme=scheme,
        pairs=_PAIR_SOURCES[spec.pairs_from](source, scheme),
        primary_source=(
            spec.primary_source or _DEFAULT_PRIMARY_SOURCE.get(spec.pairs_from, "")
        ),
    )


def builders_for(sources: list[SourceList]) -> list[ConceptAssociationBuilder]:
    """Builders for the lists in this run, in the order they were given.

    A list contributes its builder only when the run names it, which is what
    keeps GLAD out of a build that has no SimaPro-derived list in it.
    """
    return [
        builder
        for source in sources
        if (builder := builder_for(source)) is not None
    ]


def _attach_concept_associations(
    elementary_flows: list[ElementaryFlow],
    builders: list[ConceptAssociationBuilder],
) -> None:
    """Attach concept_associations to each non-deprecated elementary flow in-place."""
    for builder in builders:
        builder.prepare(elementary_flows)

    for flow in elementary_flows:
        if flow.owl_deprecated is True:
            continue
        flow_id = flow.elementary_flow_id.strip()
        if not flow_id:
            continue
        target_node: dict[str, Any] = {"@id": f"{CONSENSUS_ELEMENTARY_FLOW_IRI_PREFIX}{flow_id}"}
        associations: list[dict[str, Any]] = []
        for builder in builders:
            associations.extend(builder.build_associations(flow_id, flow, target_node))
        if associations:
            flow.concept_associations = associations

    logger.info(
        "attached_concept_associations",
        flows_with_associations=sum(1 for f in elementary_flows if f.concept_associations),
        builders=[b.name for b in builders],
    )
