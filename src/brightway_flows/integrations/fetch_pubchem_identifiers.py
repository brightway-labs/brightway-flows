"""Fetch the 'Other Identifiers' section from a PubChem compound page.

PubChem pages are JavaScript-rendered SPAs, so the HTML served at
https://pubchem.ncbi.nlm.nih.gov/compound/{cid} contains no actual data.
Instead we use PubChem's PUG View REST API which returns structured JSON:
https://pubchem.ncbi.nlm.nih.gov/rest/pug_view/data/compound/{cid}/JSON
"""

from __future__ import annotations

import json
import sys

import httpx

PUG_VIEW_URL = "https://pubchem.ncbi.nlm.nih.gov/rest/pug_view/data/compound/{cid}/JSON"


class NoOtherIdentifiers(ValueError):
    """PUG View served the record, and it has no "Other Identifiers" section.

    A distinct exception because the caller has to tell this apart from a
    request that failed.  "PubChem holds no registry identifiers for this
    compound" is an answer, and one the CAS gate in `enrich_references` acts
    on; "we never asked" is not, and must never drop a candidate.  Both used to
    arrive as the same bare `ValueError`, so both were skipped and neither was
    written to the cache -- which is why 4,181 CIDs were re-requested on every
    run and always discarded (#249).

    Subclasses `ValueError` so that a caller which only cares that extraction
    failed keeps working unchanged.
    """


def fetch_compound_json(cid: int) -> dict:
    url = PUG_VIEW_URL.format(cid=cid)
    resp = httpx.get(url, timeout=30, follow_redirects=True)
    resp.raise_for_status()
    return resp.json()


def find_section(sections: list[dict], heading: str) -> dict | None:
    for section in sections:
        if section.get("TOCHeading") == heading:
            return section
        child = find_section(section.get("Section", []), heading)
        if child is not None:
            return child
    return None


def build_reference_map(references: list[dict]) -> dict[int, str]:
    return {r["ReferenceNumber"]: r["SourceName"] for r in references}


def extract_value(info: dict) -> str | None:
    value = info.get("Value", {})
    for swm in value.get("StringWithMarkup", []):
        return swm.get("String")
    for num in value.get("Number", []):
        return str(num)
    return None


def extract_other_identifiers(data: dict) -> dict:
    record = data["Record"]
    ref_map = build_reference_map(record.get("Reference", []))

    section = find_section(record.get("Section", []), "Other Identifiers")
    if section is None:
        raise NoOtherIdentifiers("Section 'Other Identifiers' not found")

    result = {}
    for sub in section.get("Section", []):
        heading = sub["TOCHeading"]
        entries: list[dict] = []
        seen_values: set[str] = set()

        for info in sub.get("Information", []):
            val = extract_value(info)
            if val is None:
                continue

            source = ref_map.get(info.get("ReferenceNumber"), "Unknown")
            url = info.get("URL")
            description = None
            refs = info.get("Reference", [])
            if refs:
                description = refs[0]

            if val not in seen_values:
                seen_values.add(val)
                entry: dict = {"value": val, "sources": [source]}
                if url:
                    entry["url"] = url
                if description:
                    entry["description"] = description
                entries.append(entry)
            else:
                for e in entries:
                    if e["value"] == val:
                        if source not in e["sources"]:
                            e["sources"].append(source)
                        break

        result[heading] = entries

    # Keep the PubChem record title as a high-signal human-readable name.
    title = record.get("RecordTitle")
    if isinstance(title, str) and title.strip():
        result["RecordTitle"] = [{
            "value": title.strip(),
            "sources": ["PubChem RecordTitle"],
        }]

    # Capture descriptive text from the compound record when available.
    desc_section = find_section(record.get("Section", []), "Record Description")
    if isinstance(desc_section, dict):
        descriptions: list[dict] = []
        seen: set[str] = set()
        for info in desc_section.get("Information", []):
            if not isinstance(info, dict):
                continue
            val = extract_value(info)
            if not isinstance(val, str) or not val.strip():
                continue
            text = val.strip()
            if text in seen:
                continue
            seen.add(text)
            source = ref_map.get(info.get("ReferenceNumber"), "PubChem Record")
            entry: dict = {"value": text, "sources": [source]}
            url = info.get("URL")
            if isinstance(url, str) and url.strip():
                entry["url"] = url.strip()
            descriptions.append(entry)
        if descriptions:
            result["Record Description"] = descriptions

    return result


HMDB_SOURCE = "Human Metabolome Database (HMDB)"


def filter_cas_hmdb_only(identifiers: dict) -> dict:
    """Discard a CAS entry sourced only from HMDB when a multi-sourced alternative exists.

    When exactly two CAS values are present and one has only HMDB as its source
    while the other has multiple sources, the HMDB-only entry is removed.
    """
    cas_entries = identifiers.get("CAS")
    if not cas_entries or len(cas_entries) != 2:
        return identifiers

    hmdb_only = [e for e in cas_entries if e["sources"] == [HMDB_SOURCE]]
    multi_source = [e for e in cas_entries if len(e["sources"]) > 1]

    if len(hmdb_only) == 1 and len(multi_source) == 1:
        identifiers["CAS"] = multi_source

    return identifiers


def main():
    cid = int(sys.argv[1]) if len(sys.argv) > 1 else 297
    print(f"Fetching PubChem compound {cid}...", file=sys.stderr)

    data = fetch_compound_json(cid)
    identifiers = extract_other_identifiers(data)

    print(json.dumps(identifiers, indent=2))


if __name__ == "__main__":
    main()
