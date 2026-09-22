"""Apply context mappings from context-manual-mapping.json.

Three rules, and the more specific one wins.  ``default_context_mappings``
places a flow by its compartment, which is right for almost everything;
``name_prefix_context_mappings`` reads the flow name where the compartment holds
two contexts and the name is what tells them apart, which is ecoinvent's
``natural resource / land`` (#52); ``flow_specific_context_mappings`` places one
named flow, which is the only way to say something neither of those can.  EF 3.1
gives all six of its water bodies one compartment, so for those flows the
per-flow rule is not a refinement of the compartment rule -- it is the
correction of it.

The merge reads the same two rules through the same loader, so a row added here
places a flow in both stages or in neither (#11).
"""

from __future__ import annotations

import structlog

from brightway_flows.context_mapping import (
    CompartmentRule,
    ContextKey,
    context_mapping_index,
    flow_context_iri,
    name_prefix_context_iri,
    normalize_context_key,
    normalize_mapping_text,
)
from brightway_flows.domain.flow import Flow
from brightway_flows.domain.labels import flow_label_value
from brightway_flows.domain.context_registry import (
    UnknownContextIRIError,
    context_for_iri,
)
from brightway_flows.pipeline import Change, Transformer

logger = structlog.get_logger(__name__)


class DefaultContextMappingTransformer(Transformer):
    """Map raw source contexts onto consensus context definitions."""

    name = "default_context_mapping"
    answers_per_flow = True

    def __init__(self) -> None:
        self._default_by_key: dict[tuple[str, ContextKey], CompartmentRule] = {}

    def setup(self) -> None:
        # The merge reads the same file through the same loader, so a rule
        # added here places a row in both stages or in neither (#11).
        self._default_by_key = dict(context_mapping_index())

    def transform(self, flows: list[Flow]) -> list[Change]:
        changes: list[Change] = []

        for flow in flows:
            source = flow.source
            if not isinstance(source, str) or not source.strip():
                continue
            # The context the list shipped, which is what both stages key on.
            # It is only ever `provided.context` now: `flow.context` is the
            # consensus answer this transformer writes, so it could not be the
            # question as well (#97).  The passthrough key is the one source
            # list that files its compartment under another name.
            raw_context = (
                flow.provided.context
                or flow.extra.get("elementary_flow_categorization")
                or []
            )
            # A rule naming this flow outranks its compartment's rule, and is
            # consulted first so that a flow with a per-flow rule but no
            # compartment rule is still placed.  Raises if the row describes a
            # compartment the vendor has since moved the flow out of.
            iri = flow_context_iri(source, flow.uuid, raw_context)
            if not iri:
                # `bootstrap_labels` moves the shipped name into `prefLabel` and
                # purges `name`, and this transformer runs on both sides of
                # that, so the snapshot is read first for the same reason
                # `raw_context` is.
                raw_name = (
                    flow.provided.name or flow_label_value(flow) or flow.name or ""
                )
                # Raises if the compartment's contexts are told apart by name
                # and this name says nothing -- filing it under the
                # compartment's rule anyway is #52.
                iri = name_prefix_context_iri(source, raw_name, raw_context)
            if not iri:
                key = (normalize_mapping_text(source), normalize_context_key(raw_context))
                rule = self._default_by_key.get(key)
                if rule is None:
                    continue
                iri = rule.context_iri
            if not isinstance(iri, str) or not iri:
                continue

            # Resolve the context from the shared vocabulary rather than from
            # this file's own copy, so there is one context source.  The
            # registry's instances are shared between the flows that land on the
            # same context, which is what makes a `Context` per flow cheaper
            # than the dict it replaces; nothing mutates one.
            try:
                new_context = context_for_iri(iri)
            except UnknownContextIRIError:
                logger.warning(
                    "default_context_mapping_unknown_iri", context_iri=iri, source=source
                )
                continue
            # The compartment is named in the comment because it is no longer
            # the change's old value: `context` is unset until this runs, so the
            # changelog's before-column now says so.  What a curator reading the
            # changes page needs is which compartment produced this context, and
            # the comment says it outright rather than leaving it to be inferred
            # from a cell that happened to hold the input (#97).
            shipped = " > ".join(str(part) for part in raw_context if str(part).strip())
            comment = f"Mapped from context mapping for source={source}"
            if shipped:
                comment = f"{comment}, source context {shipped}"
            if flow.context != new_context:
                changes.append(Change(flow.uuid, "context", new_context, comment=comment))
            if flow.context_iri != iri:
                changes.append(Change(flow.uuid, "context_iri", iri, comment=comment))

        return changes
