"""Projection of harmonised flows onto the simplified published export.

`harmonised-flows-simple.json.gz` is what downstream consumers read, so these
helpers decide what leaves the project: language-resolved labels, simplified
property values, and reference IRIs.
"""

from __future__ import annotations

import gzip
import sqlite3
from collections import Counter
from collections.abc import Mapping
from contextlib import closing
from pathlib import Path
from typing import Any

import orjson
import structlog

from brightway_flows.domain.property_values import normalise_semantic_properties
from brightway_flows.domain.vocabulary import (
    CONSENSUS_ELEMENTARY_FLOW_IRI_PREFIX,
    JSONLD_CONTEXT,
    RDFS_LABEL_CURIE,
    RO_HAS_ROLE_IRI,
    SKOS_CONCEPT_IRI,
    SKOS_DEFINITION_IRI,
    flow_object_iri,
    origin_qualifier_iri,
)
from brightway_flows.pipeline.correspondences import (
    CONSENSUS_SCHEME_IRI,
    build_correspondences,
)
from brightway_flows.pipeline.review_records import (
    ReviewQueue,
    ReviewQueueItem,
    Severity,
)
from brightway_flows.pipeline.redirects import (
    RetiredIdentifier,
    build_redirects,
    is_deprecated,
    load_retired_minted_flow_ids,
    published_flow_identifier,
    retirement_redirects,
)
from brightway_flows.domain.labels import coerce_alt_labels, flow_label_value
from brightway_flows.domain.schema import SCHEMA_VERSION
from brightway_flows.domain.simple_flow import HarmonisedFlowsSimple, SimpleFlow
from brightway_flows.pipeline.sqlite import (
    read_published_flow_payloads,
    read_source_contexts,
)

logger = structlog.get_logger(__name__)


def _simplify_property_value(value: Any) -> Any:
    if isinstance(value, dict):
        if "@value" in value:
            raw = value.get("@value")
            if isinstance(raw, list):
                if len(raw) == 1:
                    return raw[0]
                return raw
            return raw
        # Keep non-@value dicts but recursively simplify nested values.
        return {str(k): _simplify_property_value(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_simplify_property_value(item) for item in value]
    return value

def export_properties(value: Any) -> dict[str, Any]:
    """Flatten a flow's semantic properties for the export.

    Normalises first.  The transform engine already does this to every record it
    writes, so for a plain build this is a no-op -- but the merge appends its
    flows into SQLite by a path that never passes through the engine, and those
    rows reach the export too.  Doing it here as well is what makes the
    published artifact's typing a property of the *export* rather than of which
    pipeline happened to produce the row.
    """
    if not isinstance(value, dict):
        return {}
    normalised, _counts = normalise_semantic_properties(value)
    out: dict[str, Any] = {}
    for key, raw in normalised.items():
        key_str = str(key).strip()
        if not key_str:
            continue
        out[key_str] = _simplify_property_value(raw)
    return out

def export_alt_labels(value: Any) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for label in coerce_alt_labels(value):
        text = str(label.value or "").strip()
        if not text:
            continue
        key = text.casefold()
        if key in seen:
            continue
        seen.add(key)
        out.append(text)
    return out

def export_references(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    out: list[str] = []
    for item in value:
        if isinstance(item, str) and item.strip():
            out.append(item.strip())
            continue
        if isinstance(item, dict):
            ident = item.get("@id")
            if isinstance(ident, str) and ident.strip():
                out.append(ident.strip())
    return out

def export_roles(value: Any) -> list[dict[str, str]] | None:
    """Flatten the flow object's role assertions for the simple export.

    Keeps the IRI and the label; drops the definition and the per-assertion
    provenance the flow-object layer carries.  The same treatment
    `export_references` gives a reference record and `export_alt_labels` a
    label record: this export publishes content without the audit trail, and the
    flow-object artifact publishes both.

    Returns ``None`` rather than ``[]`` when there is nothing, so the key stays
    absent.  An empty list says "checked, and it bears no role", which is a
    stronger claim than "ChEBI has nothing to say".  Row order is preserved, and
    `flow_layers.roles` writes them sorted by label.
    """
    if not isinstance(value, list):
        return None
    out: list[dict[str, str]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        identifier = item.get("@id")
        if not isinstance(identifier, str) or not identifier.strip():
            continue
        row = {"@id": identifier.strip()}
        label = item.get(RDFS_LABEL_CURIE)
        if isinstance(label, str) and label.strip():
            row[RDFS_LABEL_CURIE] = label.strip()
        out.append(row)
    return out or None


def export_definitions(value: Any) -> list[str]:
    rows: list[Any]
    if isinstance(value, list):
        rows = value
    elif value is None:
        rows = []
    else:
        rows = [value]
    out: list[str] = []
    for item in rows:
        if isinstance(item, str) and item.strip():
            out.append(item.strip())
            continue
        if isinstance(item, dict):
            raw = item.get("@value")
            if isinstance(raw, str) and raw.strip():
                out.append(raw.strip())
    return out

def export_classifications(value: Any) -> dict[str, list[str]]:
    """Flatten a flow object's registry classifications to their values.

    A stored classification is ``{IRI: {"@value": [...], provenance...}}``; what
    a reader wants is the numbers under each registry, which is what
    `pipeline/sqlite.py` reads out for the CAS and EC columns.  The per-value
    provenance is dropped, as `export_references` drops a reference's.
    """
    if not isinstance(value, dict):
        return {}
    out: dict[str, list[str]] = {}
    for key, raw in value.items():
        key_str = str(key).strip()
        if not key_str:
            continue
        values = raw.get("@value") if isinstance(raw, dict) else raw
        if isinstance(values, str):
            values = [values]
        if not isinstance(values, list):
            continue
        cleaned = [str(x).strip() for x in values if isinstance(x, str) and x.strip()]
        if cleaned:
            out[key_str] = cleaned
    return out


def simple_flow_from_payload(flow: dict[str, Any]) -> SimpleFlow | None:
    """Project one flow payload onto its published record.

    ``None`` for a payload with no identifier, which nothing can publish.  Does
    not ask whether the flow is deprecated: the export asks that before calling,
    because a deprecated flow leaves ``flows``, and a release snapshot asks it
    after, because a migration has to say what the deprecated flow *was* --
    its substance, its unit and its context -- to say what became of it.

    :raises ValueError: for a flow with no unit, which is not publishable.
    """
    identifier = published_flow_identifier(flow)
    if not identifier:
        return None
    cas = flow.get("cas_numbers")
    ec = flow.get("ec_numbers")
    unit = flow.get("unit")
    if not isinstance(unit, str) or not unit.strip():
        raise ValueError(
            f"Flow '{identifier}' (source={flow.get('source')!r}) is missing a unit. "
            "All flows must have a unit before export."
        )
    raw_types = flow.get("@type")
    if isinstance(raw_types, str):
        raw_types = [raw_types]
    # `skos:Concept` leads: a published flow is an entry in a taxonomy
    # before it is anything chemical, and it is what makes `skos:inScheme`
    # and the correspondences' `xkos:targetConcept` well-formed.
    substance_types = [
        str(x) for x in raw_types
        if isinstance(x, str) and x.strip()
    ] if isinstance(raw_types, list) else []
    return SimpleFlow(
        identifier=identifier,
        jsonld_id=f"{CONSENSUS_ELEMENTARY_FLOW_IRI_PREFIX}{identifier}",
        jsonld_type=[SKOS_CONCEPT_IRI, *substance_types],
        in_scheme={"@id": CONSENSUS_SCHEME_IRI},
        origin_qualifier=(
            {"@id": origin_qualifier_iri(qualifier)}
            if (qualifier := str(flow.get("origin_qualifier") or "").strip())
            else None
        ),
        parent_flow_object_id=(
            {"@id": flow_object_iri(parent)}
            if (parent := str(flow.get("parent_flow_object_id") or "").strip())
            else None
        ),
        parent_intervention_id=(
            {"@id": flow_object_iri(intervention)}
            if (intervention := str(
                flow.get("parent_intervention_id") or ""
            ).strip())
            else None
        ),
        roles=export_roles(flow.get(RO_HAS_ROLE_IRI)),
        source=str(flow.get("source") or ""),
        cas_numbers=[str(x) for x in cas] if isinstance(cas, list) else [],
        ec_numbers=[str(x) for x in ec] if isinstance(ec, list) else [],
        context_iri=str(flow.get("context_iri") or ""),
        unit=unit,
        unit_iri=str(flow.get("unit_iri") or ""),
        # `flow_label_value`, not a second reader of the same field.  The
        # one this replaced parsed `prefLabel` itself and never called
        # `strip_markup`, so 66 flows published `C<sub>8-14</sub>` and
        # `<em>N</em>` into a field downstream reads as text -- while
        # `altLabel` and `definition`, which go through `coerce_label`, were
        # clean.  It also read fewer language keys, and its `fallback` was
        # unreachable: the fallback was `flow_label_value` of the same flow,
        # which returns "" in exactly the cases that triggered it.
        prefLabel=flow_label_value(flow),
        altLabel=export_alt_labels(flow.get("altLabel")),
        properties=export_properties(flow.get("properties")),
        references=export_references(flow.get("references")),
        definition=export_definitions(flow.get(SKOS_DEFINITION_IRI)),
    )


def _strip_lcia_from_flows(
    flows: list[dict[str, Any]],
    source_contexts: Mapping[str, Mapping[str, frozenset[tuple[str, ...]]]]
    | None = None,
) -> HarmonisedFlowsSimple:
    """Project the flow payloads onto the published document.

    *source_contexts* is each flow's source contexts per source list, passed
    straight to :func:`build_redirects`, which uses it to say *why* each
    deprecated identifier was retired.  It is not derivable from *flows*: since
    #30 a payload carries no `source_refs`, so a caller with only payloads in
    hand gets redirects that resolve but decline to classify themselves, and
    `build_simple_export` reads the table.
    """
    out: list[SimpleFlow] = []
    for flow in flows:
        if not isinstance(flow, dict):
            continue
        if is_deprecated(flow):
            # Not dropped from the document, only from `flows`: `build_redirects`
            # reads the same payloads below and publishes where this identifier
            # resolves to.  Until #39 it was dropped outright, and a consumer
            # holding the identifier could not tell that from never having been
            # harmonised at all.
            continue
        simple = simple_flow_from_payload(flow)
        if simple is not None:
            out.append(simple)
    # From the constant, not a literal.  Written out, the export declared 1 while
    # its generated schema declared `const: SCHEMA_VERSION`, so a bump would have
    # left the artifact contradicting the schema that describes it -- and the
    # drift guard in `tests/test_schemas.py` compares schema to schema, so it
    # would not have caught it.
    schemes, correspondences, _counts = build_correspondences(flows)
    redirects, _redirect_counts = build_redirects(flows, source_contexts)
    return HarmonisedFlowsSimple(
        schema_version=SCHEMA_VERSION,
        flows=out,
        jsonld_context=JSONLD_CONTEXT,
        concept_schemes=schemes,
        correspondences=correspondences,
        redirects=redirects,
    )


#: Public alias.  `merge/pipeline.py` imported the underscore name; both work.
strip_lcia_from_flows = _strip_lcia_from_flows


def build_simple_export(db_path: Path) -> HarmonisedFlowsSimple:
    """Project the database onto the published export.

    Two reads, not one: the flows come from `elementary_flows.flow_json` and the
    source contexts behind each redirect's reason come from
    `elementary_flow_sources`, which is where a flow's references live (#30).
    """
    return _strip_lcia_from_flows(
        read_published_flow_payloads(db_path), read_source_contexts(db_path)
    )


def correspondence_stats(db_path: Path) -> Counter:
    """What `build_correspondences` counted for this database.

    Recomputed rather than returned from `build_simple_export`, because that
    function's return value is the published document and threading a tally
    through it would put a diagnostic in the artifact's type. The work is one
    pass over the flows' `concept_associations`, and it happens once per run.
    """
    return build_correspondences(read_published_flow_payloads(db_path))[2]


def retirement_stats(db_path: Path) -> Counter:
    """What the recorded retirements came to on this build.

    Reads the identifiers out of `elementary_flows` rather than projecting the
    export again: a retirement is answered by whether this build publishes the
    flow it points at, which is one column of one table, and the export is
    already built twice.

    The two `unresolved_*` counts are #344's: a retirement this build cannot
    answer is one of two things, and only one of them is anybody's to fix.
    """
    counts, _ = _retirement_outcome(db_path)
    return counts


def retired_identifier_queue_items(db_path: Path) -> list[ReviewQueueItem]:
    """One item per retired identifier this build cannot resolve.

    A redirect is published only where the build mints the flow it points at,
    which is right for a build merging fewer source lists and wrong for a flow
    curation has taken away.  Nothing said which had happened: the identifier
    left the export and a counter went up.  These are that counter, itemised
    (#344).

    **Reported rather than repaired.**  Where the substance is gone there is no
    target to offer.  Where it survives it usually survives in *several*
    contexts -- 60 of the 68 survivors on the 2026-08-25 build, up to 24 apiece
    -- and the retired identifier names the one context that is now empty, so
    choosing among the rest is a decision about the substance rather than an
    arithmetic this can do.  The eight with exactly one live flow are the ones a
    curator can answer quickly, and the payload says which those are.
    """
    _, unresolved = _retirement_outcome(db_path)
    return unresolved


def _retirement_outcome(
    db_path: Path,
) -> tuple[Counter, list[ReviewQueueItem]]:
    """The counts and the queue items, from one pass over the database."""
    unresolved: list[RetiredIdentifier] = []
    with closing(sqlite3.connect(db_path)) as connection:
        published = {
            str(identifier)
            for (identifier,) in connection.execute(
                "SELECT uuid FROM elementary_flows WHERE is_deprecated = 0"
            )
        }
        counts = retirement_redirects(
            published, load_retired_minted_flow_ids(), unresolved=unresolved
        )[1]

        surviving: dict[str, list[tuple[str, str]]] = {}
        for retired in unresolved:
            if retired.flow_object_id in surviving:
                continue
            surviving[retired.flow_object_id] = [
                (str(uuid), str(context))
                for uuid, context in connection.execute(
                    "SELECT uuid, context_display FROM elementary_flows "
                    "WHERE flow_object_id = ? AND is_deprecated = 0 "
                    "ORDER BY context_display",
                    (retired.flow_object_id,),
                )
            ]

    items: list[ReviewQueueItem] = []
    for index, retired in enumerate(unresolved):
        places = surviving.get(retired.flow_object_id, [])
        if not places:
            counts["unresolved_substance_absent"] += 1
        else:
            counts["unresolved_substance_survives"] += 1
            if len(places) == 1:
                counts["unresolved_with_one_surviving_flow"] += 1
        items.append(
            ReviewQueueItem(
                queue_name=ReviewQueue.RETIRED_IDENTIFIER_UNRESOLVED,
                item_key=retired.identifier,
                title=(
                    f"{retired.name or retired.identifier}: the retired "
                    f"identifier resolves to nothing"
                    + ("" if places else ", and the substance is gone")
                ),
                # `review` where a curator has something to decide -- the
                # substance is still published and could be pointed at.  `info`
                # where it is not: the identifier is dead and there is nothing
                # to choose between.
                severity=Severity.REVIEW if places else Severity.INFO,
                flow_object_id=retired.flow_object_id,
                item_index=index,
                payload={
                    "identifier": retired.identifier,
                    "replaced_by": retired.replaced_by,
                    "name": retired.name,
                    "context_iri": retired.context_iri,
                    "flow_object_id": retired.flow_object_id,
                    "substance_still_published": bool(places),
                    "surviving_flows": [
                        {"uuid": uuid, "context": context}
                        for uuid, context in places
                    ],
                    "unambiguous_target": places[0][0] if len(places) == 1 else "",
                },
            )
        )
    return counts, items


def write_simple_export(db_path: Path, output_path: Path) -> int:
    """Write ``harmonised-flows-simple.json.gz`` from the database.

    This is the only artifact with a downstream consumer, and until now it was
    written inside `if harmonised-flows.json exists`, projected from that file.
    A 2.5 GB intermediate was therefore load-bearing for the one thing that has
    to keep working, and if it was missing the export was silently skipped.

    Returns the number of flows written.
    """
    export = build_simple_export(db_path)
    # `to_dict()`, not `asdict()`: the document's two JSON-LD keys are `@context`
    # and `@id`, neither of which is a valid Python identifier, so they are
    # declared as aliases on the records and only `to_dict()` restores them.
    output_path.write_bytes(
        gzip.compress(orjson.dumps(export.to_dict(), option=orjson.OPT_INDENT_2))
    )
    logger.info(
        "wrote_simple_export",
        path=str(output_path),
        flow_count=len(export.flows),
        redirect_count=len(export.redirects),
        source=str(db_path),
    )
    return len(export.flows)
