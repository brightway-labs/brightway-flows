"""Load and index ChEBI ontology JSON for flow matching."""

from __future__ import annotations

import functools
import gzip
from collections import defaultdict
from typing import Any

import orjson

from brightway_flows.filesystem import CHEBI_JSON_GZ_FILEPATH
from brightway_flows.pipeline import normalize

XREF_URL_PREFIXES = {
    "chebi": "https://www.ebi.ac.uk/chebi/searchId.do?chebiId=CHEBI:",
    "cas": "https://commonchemistry.cas.org/detail?cas_rn=",
    "kegg.compound": "https://www.genome.jp/entry/",
    "kegg.drug": "https://www.genome.jp/entry/",
    "hmdb": "https://hmdb.ca/metabolites/",
    "drugbank": "https://go.drugbank.com/drugs/",
    "chemspider": "https://www.chemspider.com/Chemical-Structure.",
    "lipidmaps": "https://www.lipidmaps.org/databases/lmsd/",
    "metacyc.compound": "https://metacyc.org/compound?orgid=META&id=",
    "pubmed": "https://pubmed.ncbi.nlm.nih.gov/",
    "wikipedia.en": "https://en.wikipedia.org/wiki/",
}


def _expand_xref(value: str) -> str:
    """Expand a CURIE-like xref value to a best-effort canonical URL."""
    if value.startswith(("http://", "https://")):
        return value
    if ":" not in value:
        return value

    prefix, suffix = value.split(":", 1)
    prefix_lower = prefix.lower()
    base = XREF_URL_PREFIXES.get(prefix_lower)
    if base is None:
        return value
    if prefix_lower == "chemspider":
        return f"{base}{suffix}.html"
    return base + suffix


def _extract_cas_numbers(xrefs: list[dict[str, Any]]) -> set[str]:
    cas: set[str] = set()
    for xr in xrefs:
        value = xr.get("val")
        if not isinstance(value, str):
            continue
        if value.lower().startswith("cas:"):
            cas.add(value.split(":", 1)[1].strip())
    return cas


def _extract_kegg_ids(xrefs: list[dict[str, Any]]) -> set[str]:
    kegg: set[str] = set()
    for xr in xrefs:
        value = xr.get("val")
        if not isinstance(value, str):
            continue
        lowered = value.lower()
        if lowered.startswith("kegg.compound:") or lowered.startswith("kegg.drug:"):
            kegg.add(value.split(":", 1)[1].strip())
    return kegg


def _extract_synonyms(meta: dict[str, Any]) -> set[str]:
    synonyms: set[str] = set()
    for syn in meta.get("synonyms", []):
        val = syn.get("val")
        if isinstance(val, str) and val.strip():
            synonyms.add(val.strip())
    return synonyms


def _extract_formula(meta: dict[str, Any]) -> str | None:
    for bpv in meta.get("basicPropertyValues", []):
        pred = bpv.get("pred")
        if not isinstance(pred, str):
            continue
        if pred.endswith("/generalized_empirical_formula"):
            val = bpv.get("val")
            if isinstance(val, str) and val.strip():
                return val.strip()
    return None


def _extract_definitions(meta: dict[str, Any]) -> list[str]:
    """Extract ChEBI definition text values."""
    raw = meta.get("definition")
    out: set[str] = set()
    if isinstance(raw, dict):
        val = raw.get("val")
        if isinstance(val, str) and val.strip():
            out.add(val.strip())
    elif isinstance(raw, list):
        for item in raw:
            if isinstance(item, dict):
                val = item.get("val")
                if isinstance(val, str) and val.strip():
                    out.add(val.strip())
            elif isinstance(item, str) and item.strip():
                out.add(item.strip())
    elif isinstance(raw, str) and raw.strip():
        out.add(raw.strip())
    return sorted(out)


def _extract_basic_property_values(meta: dict[str, Any]) -> dict[str, list[str]]:
    """Extract ChEBI basicPropertyValues keyed by compact property name."""
    out: dict[str, set[str]] = defaultdict(set)
    for bpv in meta.get("basicPropertyValues", []):
        if not isinstance(bpv, dict):
            continue
        pred = bpv.get("pred")
        val = bpv.get("val")
        if not isinstance(pred, str):
            continue
        if isinstance(val, str):
            text = val.strip()
        elif isinstance(val, (int, float, bool)):
            text = str(val)
        else:
            continue
        if not text:
            continue
        key = pred.rsplit("/", 1)[-1].strip() if "/" in pred else pred.strip()
        if not key:
            continue
        out[key].add(text)
    return {k: sorted(v) for k, v in out.items()}


def _get_graph_nodes(payload: dict[str, Any]) -> list[dict[str, Any]]:
    if isinstance(payload.get("graph"), dict):
        return payload["graph"].get("nodes", [])
    if isinstance(payload.get("graphs"), list) and payload["graphs"]:
        return payload["graphs"][0].get("nodes", [])
    return []


@functools.cache
def load_chebi_index() -> dict[str, Any]:
    """Return ChEBI indexes for CLASS nodes keyed by CAS and names."""
    if not CHEBI_JSON_GZ_FILEPATH.exists():
        raise FileNotFoundError(
            f"ChEBI JSON not found at {CHEBI_JSON_GZ_FILEPATH}. "
            "Run 'brightway-flows chebi' first."
        )

    payload = orjson.loads(gzip.open(CHEBI_JSON_GZ_FILEPATH, "rb").read())
    nodes = _get_graph_nodes(payload)

    records: dict[str, dict[str, Any]] = {}
    by_cas: dict[str, set[str]] = defaultdict(set)
    by_name: dict[str, set[str]] = defaultdict(set)

    for node in nodes:
        if node.get("type") != "CLASS":
            continue
        chebi_id = node.get("id")
        if not isinstance(chebi_id, str):
            continue

        label = node.get("lbl")
        label = label.strip() if isinstance(label, str) else None

        meta = node.get("meta", {})
        xrefs = meta.get("xrefs", [])
        if not isinstance(xrefs, list):
            xrefs = []

        cas_numbers = _extract_cas_numbers(xrefs)
        synonyms = _extract_synonyms(meta)
        kegg_ids = _extract_kegg_ids(xrefs)
        formula = _extract_formula(meta)
        definitions = _extract_definitions(meta)
        basic_property_values = _extract_basic_property_values(meta)

        raw_xrefs = sorted(
            xr["val"] for xr in xrefs
            if isinstance(xr, dict) and isinstance(xr.get("val"), str)
        )
        expanded_xrefs = sorted({_expand_xref(xr) for xr in raw_xrefs})

        record = {
            "id": chebi_id,
            "label": label,
            "synonyms": sorted(synonyms),
            "cas_numbers": sorted(cas_numbers),
            "kegg_ids": sorted(kegg_ids),
            "formula": formula,
            "definitions": definitions,
            "basic_property_values": basic_property_values,
            "xrefs_raw": raw_xrefs,
            "xrefs_urls": expanded_xrefs,
        }
        records[chebi_id] = record

        if label:
            by_name[normalize(label)].add(chebi_id)
        for syn in synonyms:
            by_name[normalize(syn)].add(chebi_id)
        for cas in cas_numbers:
            by_cas[cas].add(chebi_id)

    return {
        "records": records,
        "by_cas": {k: sorted(v) for k, v in by_cas.items()},
        "by_name": {k: sorted(v) for k, v in by_name.items()},
    }
