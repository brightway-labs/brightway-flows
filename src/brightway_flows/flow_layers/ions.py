"""Monoatomic ions: parsing their names, and enriching their flow objects.

An ion arrives named in one of several ways -- "Sodium, ion", "Iron(III)",
"sodium(1+)" -- and the charge is in the name or not at all.  What is parsed out
of it drives everything else here: the link to the parent element object, the
`chemrof:elemental_charge` property, the canonical prefLabel, and the CAS
lookups against Common Chemistry and PubChem that fill the classification.
"""

from __future__ import annotations

import os
import re
from typing import Any
from urllib.parse import quote_plus

import httpx
import orjson

from brightway_flows.domain.flow_object import FlowObject
from brightway_flows.domain.vocabulary import (
    CHEMINF_CAS_REGISTRY_NUMBER,
    CHEMINF_EC_NUMBER,
    CHEMROF_CHEMICAL_ELEMENT,
    CHEMROF_ELEMENTAL_CHARGE,
    CHEMROF_MONOATOMIC_ION,
    QUDT_HAS_UNIT,
    RDFS_LABEL_CURIE,
    UNIT_IRI_NUM,
)
from brightway_flows.filesystem import COMMONCHEMISTRY_CACHE_FILEPATH
from brightway_flows.flow_layers.classifications import (
    _build_classifications,
    _classification_values,
)
from brightway_flows.flow_layers.labels import (
    _norm_text,
    _object_pref_label_value,
    _set_pref_label,
)
from brightway_flows.flow_layers.provenance import (
    ELEMENT_ENRICHMENT_GENERATED_BY,
    _element_property_provenance,
)
from brightway_flows.settings import get_settings
from brightway_flows.sources import base_source_label

roman_numberals_optional_parentheses = re.compile(
    r"[\,\s]+\(?\s*(?P<numeral>[IVX]+)\s*(?P<sign>[+-]*)\)?\s*$",
    flags=re.IGNORECASE,
)
numbers_optional_parentheses = re.compile(
    r"[\,\s]+\(?\s*(?P<sign>[+-]+)(?P<numeral>[0-9]+)\)?\s*$"
)
numbers_then_sign_optional_parentheses = re.compile(
    r"\(?\s*(?P<numeral>[0-9]+)\s*(?P<sign>[+-]+)\)?\s*$"
)


def _roman_to_int(text: str) -> int:
    values = {"I": 1, "V": 5, "X": 10}
    total = 0
    prev = 0
    for ch in reversed(text.upper()):
        value = values.get(ch, 0)
        if value < prev:
            total -= value
        else:
            total += value
            prev = value
    return total


def _extract_ion_base_and_charge(name: str) -> tuple[str, int | None]:
    text = str(name or "").strip()
    if not text:
        return "", None
    lower = text.lower()
    if lower.endswith(", ion"):
        return text[: -len(", ion")].strip(), None
    # ecoinvent 3.9.1 onward drop the comma -- `Iron ion`, `Copper ion` -- and
    # the substances minted from those rows after the correspondence tables
    # retired (#141) were coming out `unclassified` because only the
    # comma-spelled form parsed.  Same statement, same reading: an ion of the
    # named element, charge unstated.
    if lower.endswith(" ion"):
        return text[: -len(" ion")].strip().rstrip(","), None

    match = roman_numberals_optional_parentheses.search(text)
    if match:
        numeral = str(match.group("numeral") or "").strip()
        if numeral:
            charge = _roman_to_int(numeral)
            sign = str(match.group("sign") or "").strip()
            if "-" in sign:
                charge *= -1
            if -5 <= charge <= 9:
                return text[: match.start()].strip(), charge

    match = numbers_optional_parentheses.search(text)
    if match:
        numeral = str(match.group("numeral") or "").strip()
        sign = str(match.group("sign") or "").strip()
        if numeral and sign:
            charge = int(numeral.lstrip("0") or "0")
            if "-" in sign:
                charge *= -1
            if -5 <= charge <= 9:
                return text[: match.start()].strip(), charge

    # Additional real-world variant: sodium(1+) / sodium 2+
    match = numbers_then_sign_optional_parentheses.search(text)
    if match:
        numeral = str(match.group("numeral") or "").strip()
        sign = str(match.group("sign") or "").strip()
        if numeral and sign:
            charge = int(numeral.lstrip("0") or "0")
            if "-" in sign:
                charge *= -1
            if -5 <= charge <= 9:
                return text[: match.start()].strip(" ,("), charge

    return "", None


def _load_commonchemistry_cache() -> dict[str, Any]:
    if not COMMONCHEMISTRY_CACHE_FILEPATH.exists():
        return {}
    payload = orjson.loads(COMMONCHEMISTRY_CACHE_FILEPATH.read_bytes())
    if isinstance(payload, dict):
        return payload
    return {}


def _save_commonchemistry_cache(payload: dict[str, Any]) -> None:
    data = orjson.dumps(payload, option=orjson.OPT_INDENT_2)
    tmp = COMMONCHEMISTRY_CACHE_FILEPATH.with_suffix(".tmp")
    tmp.write_bytes(data)
    os.replace(tmp, COMMONCHEMISTRY_CACHE_FILEPATH)


def _lookup_commonchemistry_ion_cas_cached(
    *,
    cache: dict[str, Any],
    ion_name: str,
    api_key: str,
) -> list[str]:
    key = ion_name.strip().lower()
    if not key:
        return []
    section = cache.setdefault("search_by_query", {})
    cached = section.get(key)
    if isinstance(cached, dict):
        rows = cached.get("results")
        if isinstance(rows, list):
            return sorted({
                str(row.get("rn") or "").strip()
                for row in rows
                if isinstance(row, dict) and isinstance(row.get("rn"), str) and str(row.get("rn")).strip()
            })
    if not api_key:
        return []

    results: list[dict[str, Any]] = []
    try:
        with httpx.Client(timeout=20.0, headers={"User-Agent": "brightway-flows/1.0.0 (+https://example.org)"}) as client:
            response = client.get(
                "https://commonchemistry.cas.org/api/search",
                params={"q": ion_name.strip(), "size": 10, "offset": 0},
                headers={"X-API-KEY": api_key},
            )
            response.raise_for_status()
            payload = response.json()
        if isinstance(payload, dict) and isinstance(payload.get("results"), list):
            results = [row for row in payload.get("results", []) if isinstance(row, dict)]
    except Exception:
        results = []

    section[key] = {"results": results}
    return sorted({
        str(row.get("rn") or "").strip()
        for row in results
        if isinstance(row.get("rn"), str) and str(row.get("rn")).strip()
    })


def _lookup_pubchem_ion_cas_cached(
    *,
    cache: dict[str, Any],
    ion_name: str,
) -> list[str]:
    key = ion_name.strip().lower()
    if not key:
        return []
    section = cache.setdefault("pubchem_name_to_cas", {})
    cached = section.get(key)
    if isinstance(cached, list):
        return [str(x) for x in cached if isinstance(x, str) and x.strip()]

    out: list[str] = []
    try:
        url = f"https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/name/{quote_plus(ion_name.strip())}/xrefs/RN/JSON"
        payload = httpx.get(url, timeout=20.0).json()
        infos = (((payload or {}).get("InformationList") or {}).get("Information") or [])
        if isinstance(infos, list):
            for row in infos:
                if not isinstance(row, dict):
                    continue
                rns = row.get("RN")
                if isinstance(rns, list):
                    out.extend([str(x).strip() for x in rns if isinstance(x, str) and str(x).strip()])
    except Exception:
        out = []
    out = sorted(set(out))
    section[key] = out
    return out


def enrich_monoatomic_ions(
    by_id: dict[str, FlowObject],
    *,
    elements: dict[str, FlowObject] | None = None,
    rename_labels: bool = True,
) -> dict[str, int]:
    """Mark monoatomic ions in *by_id* and fill in what their name implies.

    Runs after the element pass and reads what it wrote: an ion is recognised by
    its name resolving to a flow object already typed `chemrof:ChemicalElement`,
    so the elements must be typed first.  Mutates the objects in place and
    returns the counters the caller folds into the layering statistics.

    *elements* is where those element objects are looked for, and defaults to
    *by_id* -- which is the transform, where the objects being enriched and the
    objects being resolved against are one set.  The merge is the other case:
    the batch it has just minted holds no elements at all, and the iron a row
    named `Iron, ion` is an ion *of* is in the consensus list it is merging
    into.  Passing the two separately is what lets a created object reach an
    element without this pass being handed every object in the list to write to
    (#71).  Nothing outside *by_id* is written.

    *rename_labels* is whether a recognised ion has its preferred label
    rewritten to the canonical spelling.  True in the transform, which is where
    that spelling is settled.  The merge passes False: the label a created
    object carries is the one enrichment just agreed on, and the same objection
    `merge.creations` records about the isotope pass's rewriting (#221) applies
    to this one.  It changes nothing else -- the canonical form is looked up
    against Common Chemistry either way.
    """
    elements = by_id if elements is None else elements
    commonchem_cache = _load_commonchemistry_cache()
    commonchem_dirty = False
    api_key_secret = get_settings().commonchemistry_api_key
    commonchem_api_key = api_key_secret.get_secret_value().strip() if api_key_secret else ""
    try:
        # Imported here rather than at module scope: `integrations` pulls in
        # `pipeline`, which imports this module, so a top-level import makes the
        # cycle depend on which module is loaded first.
        from brightway_flows.integrations.ec_inventory import load_ec_inventory

        ec_data = load_ec_inventory()
    except Exception:
        ec_data = {}
    ec_by_cas: dict[str, set[str]] = {}
    ec_by_name: dict[str, set[str]] = {}
    for rec in ec_data.get("records", []) if isinstance(ec_data, dict) else []:
        if not isinstance(rec, dict):
            continue
        ec_number = str(rec.get("ec_number") or "").strip()
        cas_number = str(rec.get("cas_number") or "").strip()
        rec_name = str(rec.get("name") or "").strip()
        if ec_number and cas_number:
            ec_by_cas.setdefault(cas_number, set()).add(ec_number)
        if ec_number and rec_name:
            ec_by_name.setdefault(_norm_text(rec_name), set()).add(ec_number)

    element_id_by_name: dict[str, str] = {}
    element_cas_by_id: dict[str, set[str]] = {}
    for flow_object_id, obj in elements.items():
        obj_types = obj.types
        if isinstance(obj_types, str):
            obj_type_list = [obj_types]
        elif isinstance(obj_types, list):
            obj_type_list = [str(x) for x in obj_types if isinstance(x, str) and x.strip()]
        else:
            obj_type_list = []
        if CHEMROF_CHEMICAL_ELEMENT not in obj_type_list:
            continue
        element_name = _object_pref_label_value(obj)
        if element_name:
            element_id_by_name[_norm_text(element_name)] = flow_object_id
        classifications = obj.classifications
        cas_values = (
            _classification_values(classifications, CHEMINF_CAS_REGISTRY_NUMBER)
            if isinstance(classifications, dict)
            else []
        )
        element_cas_by_id[flow_object_id] = set(cas_values)

    ion_marked_count = 0
    ion_cas_updated_count = 0
    ion_ec_updated_count = 0
    ion_charge_detected_count = 0
    for flow_object_id, obj in by_id.items():
        pref_value = _object_pref_label_value(obj)
        if not pref_value:
            continue
        base_name, charge_state = _extract_ion_base_and_charge(pref_value)
        if not base_name:
            continue
        base_title = base_name.title()
        base_object_id = element_id_by_name.get(_norm_text(base_title), "")
        if not base_object_id:
            continue
        existing_types = obj.types
        if isinstance(existing_types, str):
            merged_types = [existing_types]
        elif isinstance(existing_types, list):
            merged_types = [str(x) for x in existing_types if isinstance(x, str) and x.strip()]
        else:
            merged_types = []
        if CHEMROF_MONOATOMIC_ION not in merged_types:
            merged_types.append(CHEMROF_MONOATOMIC_ION)
        obj.types = merged_types
        props = obj.properties
        if not isinstance(props, dict):
            props = {}
        rel = dict((props.get("relationships") or {}) if isinstance(props.get("relationships"), dict) else {})
        rel.update({
            "parent_element_flow_object_id": base_object_id,
            "relationship_type": "ion_of",
            "provenance": _element_property_provenance(
                source_urls=[base_source_label(), "PubChem", "Common Chemistry"],
                derived_from="ion_label_to_base_element_mapping",
            ),
        })
        props["relationships"] = rel
        obj.properties = props
        ion_marked_count += 1

        if charge_state is None:
            ion_title = f"{base_title}, ion"
        else:
            sign = "+" if charge_state >= 0 else "-"
            ion_title = f"{base_title}({abs(charge_state)}{sign})"
            ion_charge_detected_count += 1
        if rename_labels:
            _set_pref_label(
                obj=obj,
                value=ion_title,
                resolver_name=ELEMENT_ENRICHMENT_GENERATED_BY,
                seed_source=base_source_label(),
                was_derived_from="ion.prefLabel.titlecase",
                extra_primary_sources=["PubChem", "Common Chemistry"],
            )
        if charge_state is not None:
            props = obj.properties
            if not isinstance(props, dict):
                props = {}
            props[CHEMROF_ELEMENTAL_CHARGE] = {
                RDFS_LABEL_CURIE: "elemental charge",
                "@value": [charge_state],
                QUDT_HAS_UNIT: UNIT_IRI_NUM,
                "provenance": _element_property_provenance(
                    source_urls=[base_source_label()],
                    derived_from="ion_label_charge_state_regex_parse",
                ),
            }
            obj.properties = props

        existing_classifications = obj.classifications
        existing_cas = (
            _classification_values(existing_classifications, CHEMINF_CAS_REGISTRY_NUMBER)
            if isinstance(existing_classifications, dict)
            else []
        )
        existing_ec = (
            _classification_values(existing_classifications, CHEMINF_EC_NUMBER)
            if isinstance(existing_classifications, dict)
            else []
        )
        parent_cas = element_cas_by_id.get(base_object_id, set())
        search_names = sorted({pref_value.strip(), ion_title, f"{base_title}, ion"} - {""})
        commonchem_cas: list[str] = []
        pubchem_cas: list[str] = []
        for ion_name in search_names:
            cc_result = _lookup_commonchemistry_ion_cas_cached(
                cache=commonchem_cache,
                ion_name=ion_name,
                api_key=commonchem_api_key,
            )
            commonchem_cas.extend(cc_result)
            if not cc_result:
                # Only fall back to PubChem when CC has no result for this name.
                # PubChem returns all CAS synonyms for a compound (often many),
                # and the alphabetically-first one may differ from the CAS used
                # by EF and ecoinvent.  CC is more conservative and returns an
                # exact, authoritative match when available.
                pubchem_cas.extend(
                    _lookup_pubchem_ion_cas_cached(
                        cache=commonchem_cache,
                        ion_name=ion_name,
                    )
                )
        commonchem_cas = sorted(set(commonchem_cas))
        pubchem_cas = sorted(set(pubchem_cas))
        if commonchem_cas or pubchem_cas:
            commonchem_dirty = True
        candidate_cas = [x for x in [*commonchem_cas, *pubchem_cas] if isinstance(x, str) and x.strip()]
        candidate_cas = sorted(set(candidate_cas))
        selected_cas = ""
        for cas in candidate_cas:
            if cas not in parent_cas:
                selected_cas = cas
                break
        if not selected_cas and candidate_cas:
            selected_cas = candidate_cas[0]

        cas_out = sorted(set(existing_cas))
        if selected_cas and selected_cas not in cas_out:
            cas_out = [selected_cas]
            ion_cas_updated_count += 1

        ec_candidates: set[str] = set(existing_ec)
        if selected_cas:
            ec_candidates.update(ec_by_cas.get(selected_cas, set()))
        for ion_name in search_names:
            ec_candidates.update(ec_by_name.get(_norm_text(ion_name), set()))
        ec_out = sorted({x for x in ec_candidates if isinstance(x, str) and x.strip()})
        if sorted(set(existing_ec)) != ec_out:
            ion_ec_updated_count += 1

        if cas_out or ec_out:
            obj.classifications = _build_classifications(
                cas_numbers=cas_out,
                ec_numbers=ec_out,
                seed_source=f"{base_source_label()};PubChem;Common Chemistry;EC inventory",
                resolver_name=ELEMENT_ENRICHMENT_GENERATED_BY,
                cas_quality_values=set(),
            )
        by_id[flow_object_id] = obj

    if commonchem_dirty:
        _save_commonchemistry_cache(commonchem_cache)

    return {
        "monoatomic_ion_flow_object_count_marked": ion_marked_count,
        "monoatomic_ion_charge_detected_count": ion_charge_detected_count,
        "monoatomic_ion_cas_updates": ion_cas_updated_count,
        "monoatomic_ion_ec_updates": ion_ec_updated_count,
    }
