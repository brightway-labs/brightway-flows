"""CAS and EC classification blocks on a flow object.

A classification is not a bare list of numbers: it carries the registry IRI it
is keyed by, the resource URLs a reader can follow, the SKOS predicate the match
was made with, and provenance for the set and for each value.  Both the layering
algorithm and the ion enrichment build them, so they are built in one place.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import quote_plus

from brightway_flows.domain.common import Provenance
from brightway_flows.domain.flow_object import Classification
from brightway_flows.domain.vocabulary import (
    CHEMINF_CAS_REGISTRY_NUMBER,
    CHEMINF_EC_NUMBER,
    SKOS_CLOSE_MATCH_IRI,
    SKOS_EXACT_MATCH_IRI,
    SKOS_RELATED_MATCH_IRI,
)


def _map_cas_quality_to_skos(cas_quality_values: set[str]) -> str | None:
    if "exactMatch" in cas_quality_values:
        return SKOS_EXACT_MATCH_IRI
    if "closeMatch" in cas_quality_values:
        return SKOS_CLOSE_MATCH_IRI
    if "relatedMatch" in cas_quality_values:
        return SKOS_RELATED_MATCH_IRI
    return None


def _cas_resource_urls(cas_numbers: list[str]) -> list[str]:
    out = [
        f"https://commonchemistry.cas.org/detail?cas_rn={quote_plus(cas)}"
        for cas in cas_numbers
        if isinstance(cas, str) and cas.strip()
    ]
    return sorted(set(out))


def _ec_resource_urls(ec_numbers: list[str]) -> list[str]:
    out = [
        f"https://echa.europa.eu/search-for-chemicals?query={quote_plus(ec)}"
        for ec in ec_numbers
        if isinstance(ec, str) and ec.strip()
    ]
    return sorted(set(out))


def _build_classifications(
    *,
    cas_numbers: list[str],
    ec_numbers: list[str],
    seed_source: str,
    resolver_name: str,
    cas_quality_values: set[str] | None = None,
    cas_number_sources: dict[str, dict[str, Any]] | None = None,
) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}

    if cas_numbers:
        sorted_cas = sorted(set(cas_numbers))
        per_value: dict[str, dict[str, Any]] | None = None
        if cas_number_sources:
            per_value = {
                cas: prov
                for cas, prov in cas_number_sources.items()
                if cas in set(sorted_cas) and isinstance(prov, dict)
            } or None
        out[CHEMINF_CAS_REGISTRY_NUMBER] = Classification(
            value=sorted_cas,
            resource_urls=_cas_resource_urls(cas_numbers),
            skos_match_predicate=_map_cas_quality_to_skos(cas_quality_values or set()),
            provenance=Provenance(
                was_generated_by=resolver_name,
                was_attributed_to="brightway-flows",
                had_primary_source=[seed_source] if seed_source else [],
                was_derived_from="cas_numbers",
            ),
            per_value_provenance=per_value,
        ).to_dict()

    if ec_numbers:
        out[CHEMINF_EC_NUMBER] = Classification(
            value=sorted(set(ec_numbers)),
            resource_urls=_ec_resource_urls(ec_numbers),
            provenance=Provenance(
                was_generated_by=resolver_name,
                was_attributed_to="brightway-flows",
                had_primary_source=[seed_source] if seed_source else [],
                was_derived_from="ec_numbers",
            ),
        ).to_dict()

    return out


def _classification_values(
    classifications: dict[str, Any],
    key: str,
) -> list[str]:
    if not isinstance(classifications, dict):
        return []
    row = classifications.get(key)
    if not isinstance(row, dict):
        return []
    raw = row.get("@value")
    if not isinstance(raw, list):
        return []
    return [x for x in raw if isinstance(x, str) and x.strip()]
