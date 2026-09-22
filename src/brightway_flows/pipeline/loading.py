"""Reading the base flow records from disk into validated Flow objects.

The transform has exactly one input: the base list -- the fixed starting point
every other list is merged against, today EF 3.1.  Which list that is, and where
its flows live, is the one manifest in `data/sources/` with `role: "base"`
(#14).  Every other list arrives as a `SourceList` and is enriched and matched
by the merge, so there is nothing for this module to discover or configure
(#210).

Input-stage deduplication is intentionally not performed: every valid row is
loaded and its source reference preserved. See docs/operating/sources.md.
"""

from __future__ import annotations

from typing import Any

import orjson
import structlog

from brightway_flows.domain.context_registry import context_display_parts
from brightway_flows.domain.flow import Flow
from brightway_flows.domain.models import HarmonisedFlow
from brightway_flows.manual_fixes import apply_manual_fixes
from brightway_flows.sources import SourceList, base_source_list

logger = structlog.get_logger(__name__)


def _normalize_input_flow_record(flow: dict[str, Any], *, source_hint: str = "") -> dict[str, Any] | None:
    if not isinstance(flow, dict):
        return None

    uuid = flow.get("uuid")
    if not isinstance(uuid, str) or not uuid.strip():
        identifier = flow.get("identifier")
        if isinstance(identifier, str) and identifier.strip():
            uuid = identifier.strip()
        else:
            return None
    uuid = uuid.strip()

    out = dict(flow)
    out["uuid"] = uuid
    out.setdefault("identifier", uuid)
    out.setdefault("name", flow.get("name"))

    cas_numbers = out.get("cas_numbers")
    if not isinstance(cas_numbers, list):
        single_cas = out.get("cas_number")
        if isinstance(single_cas, str) and single_cas.strip():
            cas_numbers = [single_cas.strip()]
        else:
            cas_numbers = []
    out["cas_numbers"] = [str(x).strip() for x in cas_numbers if isinstance(x, str) and str(x).strip()]

    ec_numbers = out.get("ec_numbers")
    if not isinstance(ec_numbers, list):
        single_ec = out.get("ec_number")
        if isinstance(single_ec, str) and single_ec.strip():
            ec_numbers = [single_ec.strip()]
        else:
            ec_numbers = []
    out["ec_numbers"] = [str(x).strip() for x in ec_numbers if isinstance(x, str) and str(x).strip()]

    # The compartment path, which is a list of strings on every row of every
    # list the project reads -- 94,062 of 94,062 in EF 3.1.  A dict used to be
    # accepted here as well, from when this field also carried the consensus
    # context later in the run; nothing ever supplied one, and the consensus
    # context now has a field of its own (#97).
    context = out.get("context")
    if not isinstance(context, list):
        fallback_context = out.get("elementary_flow_categorization")
        context = fallback_context if isinstance(fallback_context, list) else []
    out["context"] = [
        str(part).strip() for part in context if isinstance(part, str) and part.strip()
    ]

    synonyms = out.get("synonyms")
    if not isinstance(synonyms, list):
        synonyms = []
    out["synonyms"] = [str(x).strip() for x in synonyms if isinstance(x, str) and str(x).strip()]

    if not isinstance(out.get("lcia_methods"), list):
        out["lcia_methods"] = []
    if not isinstance(out.get("unit"), str):
        out["unit"] = out.get("unit") if out.get("unit") is None else str(out.get("unit"))

    source_value = out.get("source")
    if isinstance(source_value, str) and source_value.strip():
        out["source"] = source_value.strip()
    elif source_hint:
        out["source"] = source_hint
    else:
        out["source"] = "unknown"

    # The values the source list shipped, kept because the pipeline replaces
    # rather than only adds: `bootstrap_labels` purges `name` and `synonyms`
    # once it has moved them into the label fields, `default_context_mapping`
    # rewrites `context`, and the CAS transformers substitute a different
    # registry number.  This is the boundary where an input row becomes a
    # record, so it is the last point at which the input still exists.  An
    # already-normalised payload keeps the snapshot it arrived with.
    out.setdefault("_provided", {
        "name": out.get("name"),
        "synonyms": list(out["synonyms"]),
        "context": orjson.loads(orjson.dumps(out["context"])),
        "cas_numbers": list(out["cas_numbers"]),
        "ec_numbers": list(out["ec_numbers"]),
        "unit": out.get("unit"),
    })

    return out

def _build_input_source_ref(
    flow: dict[str, Any], *, source_list: SourceList, input_file: str
) -> dict[str, Any]:
    """The `source_refs` entry for one row of *source_list*'s flows file.

    `(list_name, list_version)` comes from the list, not from the row's `source`
    string.  It used to be recovered from that string by special-casing the base
    label, prefix-matching `ecoinvent-`, and otherwise splitting on the first
    dash when the tail contained a digit -- a guess that lands in `source_refs`
    and in `elementary_flow_sources`, both published, and that a list named
    `US LCI` would have failed silently by shipping a blank version (#13).

    `original_context` is attached unconditionally because this file *is* the
    base list's: it is the only list merged with its vendor's own compartment
    strings still intact, and the transform reads no other (#210).
    """
    source = str(flow.get("source") or "").strip()
    source_metadata: dict[str, Any] = {"input_file": input_file}
    if source:
        source_metadata["input_dataset"] = source
    source_metadata["original_context"] = context_display_parts(flow.get("context"))
    return {
        "list_name": source_list.list_name,
        "list_version": source_list.list_version,
        "source_flow_uuid": str(flow.get("uuid") or "").strip(),
        "source_flow_name": str(flow.get("name") or "").strip(),
        "source_metadata": source_metadata,
    }

def _extract_flow_rows_from_payload(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    if isinstance(payload, dict):
        for key in ("flows", "flow_data"):
            rows = payload.get(key)
            if isinstance(rows, list):
                return [row for row in rows if isinstance(row, dict)]
    return []

def _load_transform_inputs() -> tuple[list[Flow], list[str]]:
    """Load the base flow file into `Flow` records.

    One file, always the same one.  The transform used to compose its input out
    of a base file, whatever `--input` named, and whatever
    `additional-flow-input-*.json` happened to be in the data directory; the
    merge now enriches each source list in place, so a second route into the
    transform would only be a second way to say `--source` (#210).

    Returns the flows and the paths they were read from -- a one-element list,
    kept a list because `PipelineRun.input_files` records it.

    Which file that is comes from the manifest with `role: "base"`, not from a
    constant in `filesystem` (#14).

    The base list's manual fixes are applied here, on the raw rows and before
    normalisation, which is what `SourceList.load_flows` does for every other
    list.  They are *also* applied at extraction, and that is deliberate: the
    artifact on disk should not carry a value we know to be wrong.  But a
    derived file is only as current as the last time someone rebuilt it, and
    for five months nobody did -- #231 removed a shared EC number from the two
    jasmolins in August and every build until #237 read the March extraction
    and never saw it.  Applying them on the way in as well means an edit to
    `*-manual-fixes.json` reaches the next build whether or not `extract` was
    re-run (#237).

    Applying the same fix twice is a no-op by construction; see
    `manual_fixes.apply_manual_fixes`.
    """
    base = base_source_list()
    if not base.flows_path.exists():
        raise FileNotFoundError(
            f"No transform input found. Expected the base file at {base.flows_path}; "
            f"run 'download' and '{base.fetch_command}' to produce it."
        )

    payload = orjson.loads(base.flows_path.read_bytes())
    rows = _extract_flow_rows_from_payload(payload)
    if base.manual_fixes_path is not None:
        apply_manual_fixes(rows, base.manual_fixes_path, label=base.source_label)
    path_str = str(base.flows_path)
    normalized_rows = [
        norm
        for norm in (
            _normalize_input_flow_record(row, source_hint=base.flows_path.stem)
            for row in rows
        )
        if isinstance(norm, dict)
    ]
    for norm in normalized_rows:
        src = norm.get("source")
        datasets = []
        if isinstance(src, str) and src.strip():
            datasets.append(src.strip())
        norm["input_datasets"] = datasets
        norm["source_refs"] = [
            _build_input_source_ref(norm, source_list=base, input_file=path_str)
        ]

    combined: list[dict[str, Any]] = []
    skipped_no_context = 0
    for norm in normalized_rows:
        if norm.get("source") == base.source_label and not norm.get("context"):
            skipped_no_context += 1
            continue
        combined.append(norm)
    if skipped_no_context:
        logger.info(
            "transform_input_skipped_no_context",
            path=path_str,
            count=skipped_no_context,
        )

    if not combined:
        raise FileNotFoundError(
            f"The transform input at {base.flows_path} yielded no valid flow rows."
        )

    out = [
        Flow.from_dict(HarmonisedFlow.from_dict(flow).to_dict())
        for flow in combined
    ]
    return out, [path_str]
