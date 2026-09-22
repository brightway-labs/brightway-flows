"""Retrieving the periodic table, its isotopes, and their decay data.

Two external sources, both cached on disk because a full run would otherwise
make thousands of requests: PubChem for the elements and their isotope tables,
and ChemLin for the per-isotope half-life and specific activity PubChem does not
publish.  Nothing here touches a flow object -- `elements` does that with what
these return.
"""

from __future__ import annotations

import math
import re
from datetime import datetime, timezone
from typing import Any

import httpx
import orjson

from brightway_flows.domain.nuclides import Nuclide, half_life_days
from brightway_flows.filesystem import (
    CHEMLIN_ISOTOPE_CACHE_FILEPATH,
    PUBCHEM_ELEMENTS_CACHE_FILEPATH,
)

#: Bumped from 3 when `_parse_isotope_decay_annotation` stopped dropping blank
#: cells: every cache written before that has decay modes and discovery years
#: out of register on 18 elements, and there is no way to put them back without
#: the blanks that were discarded.  A bump is a re-download of the periodic
#: table and 118 element pages, which is the price of the table being right.
CACHE_VERSION = 4

#: Bumped from 1 when the isomer resolution started fetching the ground-state
#: page as well.  Every entry written before that ranked a single candidate and
#: recorded it as the longest-lived of the set, which was true only because the
#: set had one member.
CHEMLIN_CACHE_VERSION = 2


def _extract_swm_strings(info: dict[str, Any]) -> list[str]:
    out: list[str] = []
    value = info.get("Value", {})
    for swm in value.get("StringWithMarkup", []):
        if isinstance(swm, dict):
            text = swm.get("String")
            if isinstance(text, str) and text.strip():
                out.append(text.strip())
    return out


def _parse_isotope_mass_abundance(section: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for info in section.get("Information", []):
        if not isinstance(info, dict):
            continue
        table = (info.get("Value") or {}).get("Table")
        if not isinstance(table, dict):
            continue
        columns = table.get("ColumnName", [])
        table_rows = table.get("Row", [])
        if not isinstance(columns, list) or not isinstance(table_rows, list):
            continue
        for trow in table_rows:
            if not isinstance(trow, dict):
                continue
            cells = trow.get("Cell", [])
            if not isinstance(cells, list):
                continue
            row_payload: dict[str, Any] = {}
            for idx, col in enumerate(columns):
                if idx >= len(cells):
                    continue
                key = str(col).lower().replace(" ", "_").replace("(", "").replace(")", "")
                row_payload[key] = str(cells[idx]).strip()
            if row_payload:
                rows.append(row_payload)
    current: dict[str, Any] = {}
    for info in section.get("Information", []):
        if not isinstance(info, dict):
            continue
        name = info.get("Name")
        values = _extract_swm_strings(info)
        value = values[0] if values else ""
        if name == "Isotope":
            if current:
                rows.append(current)
            current = {"nuclide": value}
        elif name and current:
            key = str(name).lower().replace(" ", "_").replace("(", "").replace(")", "")
            current[key] = value
    if current:
        rows.append(current)
    dedup: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in rows:
        marker = orjson.dumps(row, option=orjson.OPT_SORT_KEYS).decode("utf-8")
        if marker in seen:
            continue
        seen.add(marker)
        dedup.append(row)
    return dedup


def _parse_isotope_decay(section: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for info in section.get("Information", []):
        if not isinstance(info, dict):
            continue
        table = (info.get("Value") or {}).get("Table")
        if not isinstance(table, dict):
            continue
        columns = table.get("ColumnName", [])
        table_rows = table.get("Row", [])
        if not isinstance(columns, list) or not isinstance(table_rows, list):
            continue
        for trow in table_rows:
            if not isinstance(trow, dict):
                continue
            cells = trow.get("Cell", [])
            if not isinstance(cells, list):
                continue
            row_payload: dict[str, Any] = {}
            for idx, col in enumerate(columns):
                if idx >= len(cells):
                    continue
                key = (
                    str(col)
                    .lower()
                    .replace(" ", "_")
                    .replace("[", "")
                    .replace("]", "")
                    .replace(",", "")
                    .replace("(", "")
                    .replace(")", "")
                )
                row_payload[key] = str(cells[idx]).strip()
            if row_payload:
                rows.append(row_payload)
    current: dict[str, Any] = {}
    for info in section.get("Information", []):
        if not isinstance(info, dict):
            continue
        name = info.get("Name")
        values = _extract_swm_strings(info)
        value = values[0] if values else ""
        if name == "Nuclide":
            if current:
                rows.append(current)
            current = {"nuclide": value}
        elif name and current:
            key = str(name).lower().replace(" ", "_").replace("[", "").replace("]", "").replace(",", "")
            current[key] = value
    if current:
        rows.append(current)
    dedup: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in rows:
        marker = orjson.dumps(row, option=orjson.OPT_SORT_KEYS).decode("utf-8")
        if marker in seen:
            continue
        seen.add(marker)
        dedup.append(row)
    return dedup


def _parse_isotope_decay_annotation(annotation: dict[str, Any]) -> list[dict[str, Any]]:
    """PubChem's decay table, which arrives as parallel columns rather than rows.

    The columns are zipped back together by position, so an entry dropped from
    one of them takes every later value in that column one row out of step.
    Skipping the blank cells did exactly that: PubChem has no discovery year for
    four curium nuclides and no decay mode for the last one, and the values
    below each gap moved up, so **18 of the 118 elements published a decay mode
    belonging to a different nuclide**.  Curium-242 was given curium-242m's,
    Lead-210 lead-210m's, and 138 ground states across the table came out
    decaying by isomeric transition -- which a ground state cannot do, since
    there is no higher state for it to fall from.

    Blank cells are therefore kept as blanks: they are what holds the column in
    register.  A column that still comes back a different length from the
    nuclide column is a shape this cannot read, and the rows are refused rather
    than zipped short -- the caller keeps the section-parsed table, which is
    keyed by nuclide rather than by position and cannot slip.
    """
    data = annotation.get("Data", [])
    if not isinstance(data, list):
        return []
    columns: dict[str, list[str]] = {}
    name_map = {
        "Nuclide": "nuclide",
        "Atomic Mass and Uncertainty [u]": "atomic_mass_and_uncertainty_u",
        "Half Life and Uncertainty": "half_life_and_uncertainty",
        "Discovery Year": "discovery_year",
        "Decay Modes, Intensities and Uncertainties [%]": "decay_modes_intensities_and_uncertainties_%",
    }
    for entry in data:
        if not isinstance(entry, dict):
            continue
        raw_name = entry.get("Name")
        if not isinstance(raw_name, str):
            continue
        key = name_map.get(raw_name)
        if not key:
            continue
        values: list[str] = []
        swm = (entry.get("Value") or {}).get("StringWithMarkup", [])
        if isinstance(swm, list):
            for item in swm:
                if isinstance(item, dict):
                    values.append(str(item.get("String") or "").strip())
        if values:
            columns[key] = values
    nuclides = columns.get("nuclide")
    if not nuclides:
        return []
    if any(len(values) != len(nuclides) for values in columns.values()):
        return []
    rows: list[dict[str, Any]] = []
    for idx in range(len(nuclides)):
        row = {
            key: values[idx]
            for key, values in columns.items()
            if values[idx]
        }
        if row.get("nuclide"):
            rows.append(row)
    return rows


def _load_pubchem_isotope_decay_map(client: httpx.Client) -> dict[int, list[dict[str, Any]]]:
    url = "https://pubchem.ncbi.nlm.nih.gov/rest/pug_view/annotations/heading/JSON"
    params = {
        "heading": "Atomic Mass, Half Life, and Decay",
        "heading_type": "Element",
    }
    try:
        response = client.get(url, params=params)
        response.raise_for_status()
        payload = response.json()
    except Exception:
        return {}

    annotations = (payload.get("Annotations") or {}).get("Annotation", [])
    if not isinstance(annotations, list):
        return {}
    out: dict[int, list[dict[str, Any]]] = {}
    for ann in annotations:
        if not isinstance(ann, dict):
            continue
        linked_elements = (ann.get("LinkedRecords") or {}).get("Element", [])
        if not isinstance(linked_elements, list) or not linked_elements:
            continue
        atomic_number = linked_elements[0]
        if not isinstance(atomic_number, int):
            continue
        rows = _parse_isotope_decay_annotation(ann)
        if rows:
            out[atomic_number] = rows
    return out


def _parse_relative_abundance(value: str) -> float | None:
    text = str(value or "").strip()
    if not text:
        return None
    match = re.search(r"(\d+(?:\.\d+)?)", text)
    if not match:
        return None
    try:
        return float(match.group(1))
    except Exception:
        return None


def _load_chemlin_cache() -> dict[str, Any]:
    if CHEMLIN_ISOTOPE_CACHE_FILEPATH.exists():
        payload = orjson.loads(CHEMLIN_ISOTOPE_CACHE_FILEPATH.read_bytes())
        if isinstance(payload, dict) and payload.get("cache_version") == CHEMLIN_CACHE_VERSION:
            records = payload.get("records")
            if isinstance(records, dict):
                return payload
    return {
        "cache_version": CHEMLIN_CACHE_VERSION,
        "retrieved_at": datetime.now(timezone.utc).isoformat(),
        "records": {},
    }


def _save_chemlin_cache(payload: dict[str, Any]) -> None:
    payload["retrieved_at"] = datetime.now(timezone.utc).isoformat()
    CHEMLIN_ISOTOPE_CACHE_FILEPATH.write_bytes(
        orjson.dumps(payload, option=orjson.OPT_INDENT_2)
    )


#: ChemLIN writes a power of ten as `&times; 10<sup>8</sup>`, sometimes with the
#: sign inside the tag.  `domain.nuclides` reads a magnitude and a unit and has
#: no notion of markup, so the whole construct is folded to an `e` exponent
#: before it ever sees the string.
_SCIENTIFIC_NOTATION = re.compile(
    r"\s*(?:&times;|×|x)\s*10\s*<sup>\s*([+-]?\d+)\s*</sup>",
    flags=re.IGNORECASE,
)

#: Whatever markup is left once the exponent has been folded in.
_MARKUP = re.compile(r"<[^>]+>")


def _fold_scientific_notation(text: str) -> str:
    """`7.04(1) &times; 10<sup>8</sup> a` as `7.04(1)e8 a`."""
    folded = _SCIENTIFIC_NOTATION.sub(r"e\1", str(text or ""))
    return _MARKUP.sub("", folded).strip()


def _fetch_chemlin_isotope_data(
    client: httpx.Client,
    *,
    element_name: str,
    mass_suffix: str,
) -> dict[str, Any]:
    slug = f"{element_name.lower()}-{mass_suffix}"
    url = f"https://www.chemlin.org/isotope/{slug}"
    try:
        response = client.get(url, timeout=20.0)
        if response.status_code != 200:
            return {"url": url, "slug": slug, "found": False}
        html = response.text
    except Exception:
        return {"url": url, "slug": slug, "found": False}

    # The value runs to the end of its `<st2>` element, not to the first `<`
    # inside it.  A half-life in scientific notation is written
    # `7.04(1) &times; 10<sup>8</sup> a`, so stopping at the tag took the
    # mantissa and left the exponent behind: uranium-235 came back as
    # `7.04(1) &times; 10`, which is not a number this project can rank or
    # publish, and six nuclides lost their ChemLIN half-life to it.  The `<sup>`
    # is folded to `e` so the exponent survives into the text the parser reads.
    half_life_match = re.search(
        r"<st1><b>Half-life</b>:</st1><st2>(.*?)</st2>",
        html,
        flags=re.IGNORECASE | re.DOTALL,
    )
    specific_match = re.search(
        r"Specific activity[^:]*:</st1><st2>\s*([0-9\.\s&times;\+<sup>/\-]+?)\s*Bq\s*g<sup>-1</sup>",
        html,
        flags=re.IGNORECASE,
    )
    half_life_value = (
        _fold_scientific_notation(half_life_match.group(1)) if half_life_match else ""
    )
    specific_activity = ""
    if specific_match:
        raw = specific_match.group(1)
        sci = re.search(r"([0-9\.]+)\s*&times;\s*10<sup>([+\-]?\d+)</sup>", raw)
        if sci:
            specific_activity = f"{sci.group(1)}e{sci.group(2)}"
        else:
            plain = re.search(r"([0-9]+(?:\.[0-9]+)?)", raw)
            if plain:
                specific_activity = plain.group(1)
    found = "Properties and data of the isotope" in html and (half_life_value or specific_activity)
    specific_activity_value = None
    if specific_activity:
        try:
            specific_activity_value = float(specific_activity)
        except Exception:
            specific_activity_value = None
    return {
        "url": url,
        "slug": slug,
        "found": bool(found),
        "half_life": half_life_value,
        "half_life_days": half_life_days(half_life_value) if half_life_value else None,
        "specific_activity_bq_per_g": specific_activity,
        "specific_activity_bq_per_g_value": specific_activity_value,
        "source": "ChemLin",
    }


def _resolve_chemlin_isotope_data(
    client: httpx.Client,
    *,
    element_name: str,
    nuclide: Nuclide,
    expected_half_life_days: float | None,
) -> dict[str, Any]:
    """The ChemLIN page for *nuclide*, chosen by the half-life PubChem gives it.

    ChemLIN spells the excited states ``m``, ``m1``, ``m2``, ``m3`` where
    PubChem spells them ``m``, ``n``, ``p``, ``q``, and the two orderings are
    not reliably the same nuclide, so the state cannot simply be translated.
    What settles it is that PubChem has already stated a half-life for the
    nuclide we want: whichever page agrees with it is the page for that
    nuclide.  *expected_half_life_days* is that value, and the selection is a
    cross-check between two independent sources rather than a preference.

    The **ground-state page is always fetched**, including for an isomer.  It
    used to be requested only for a ground state, so an isomer's resolution
    ranked a single candidate, called it the longest-lived of the set, and
    recorded a `strategy` that had nothing to choose between -- and a
    metastable flag that turned out to be wrong was unrecoverable rather than
    merely mistaken.  With the ground state in the set there is always
    something to disagree with.
    """
    suffixes = [str(nuclide.mass_number)]
    if not nuclide.is_ground_state:
        suffixes += [f"{nuclide.mass_number}m{n}" for n in ("", 1, 2, 3)]
    attempts = [
        _fetch_chemlin_isotope_data(
            client,
            element_name=element_name,
            mass_suffix=suffix,
        )
        for suffix in suffixes
    ]
    resolution: dict[str, Any] = {
        "wanted_nuclide": nuclide.key,
        "expected_half_life_days": expected_half_life_days,
        "attempted_slugs": suffixes,
        "attempted_urls": [a.get("url", "") for a in attempts if isinstance(a, dict)],
    }
    found = [a for a in attempts if isinstance(a, dict) and a.get("found")]
    if not found:
        return {
            "url": attempts[0].get("url", "") if attempts else "",
            "found": False,
            "half_life": "",
            "specific_activity_bq_per_g": "",
            "specific_activity_bq_per_g_value": None,
            "source": "ChemLin",
            "isomer_resolution": {
                **resolution,
                "strategy": "no_page_found",
                "selected_slug": "",
                "alternates": [],
            },
        }

    def days(item: dict[str, Any]) -> float | None:
        value = item.get("half_life_days")
        return float(value) if isinstance(value, (int, float)) else None

    # `expected_half_life_days` is *infinite* for a stable nuclide -- that is
    # what `half_life_days` returns for "Stable", and what the ranking in the
    # branch below needs it to return.  It cannot be compared against: every
    # candidate is infinitely far from it, and the reciprocal of that distance
    # divides by zero.  A stable nuclide is one of the cases with nothing to
    # agree with, so it takes the named-guess branch.
    comparable = (
        isinstance(expected_half_life_days, (int, float))
        and math.isfinite(expected_half_life_days)
        and expected_half_life_days > 0
    )
    if comparable:
        strategy = "half_life_agrees_with_pubchem"
        # Ranked on the ratio rather than the difference: these half-lives span
        # nanoseconds to gigayears, and on that scale a difference is only ever
        # a statement about the largest number in the set.  Written as the
        # larger over the smaller rather than as a reciprocal, so that a ratio
        # small enough to underflow to zero cannot be inverted.  A candidate
        # ChemLIN has no half-life for cannot be compared and sorts last.
        def rank_key(item: dict[str, Any]) -> tuple[int, float, str]:
            value = days(item)
            if value is None or value <= 0:
                return (1, 0.0, str(item.get("slug") or ""))
            high, low = max(value, expected_half_life_days), min(value, expected_half_life_days)
            return (0, high / low, str(item.get("slug") or ""))

        selected = min(found, key=rank_key)
    else:
        # Nothing to agree with.  A ground state is still exactly one page, and
        # for an isomer the longest-lived candidate is the one an inventory
        # means when it writes a bare `m` -- but the guess is named as one.
        strategy = (
            "ground_state_slug"
            if nuclide.is_ground_state
            else "longest_half_life_no_expected_value"
        )
        selected = (
            found[0]
            if nuclide.is_ground_state
            else max(found, key=lambda item: (days(item) or -1.0, str(item.get("slug") or "")))
        )

    selected_days = days(selected)
    return {
        "url": selected.get("url", ""),
        "found": True,
        "half_life": selected.get("half_life", ""),
        "specific_activity_bq_per_g": selected.get("specific_activity_bq_per_g", ""),
        "specific_activity_bq_per_g_value": selected.get("specific_activity_bq_per_g_value"),
        "source": "ChemLin",
        "isomer_resolution": {
            **resolution,
            "strategy": strategy,
            "selected_slug": selected.get("slug", ""),
            "selected_half_life": selected.get("half_life", ""),
            "selected_half_life_days": selected_days,
            "half_life_ratio_to_pubchem": (
                selected_days / expected_half_life_days
                if selected_days and expected_half_life_days
                else None
            ),
            "alternates": [
                {
                    "slug": item.get("slug", ""),
                    "url": item.get("url", ""),
                    "half_life": item.get("half_life", ""),
                    "half_life_days": item.get("half_life_days"),
                }
                for item in found
                if item is not selected
            ],
        },
    }


def _load_or_fetch_pubchem_element_cache() -> dict[str, Any]:
    if PUBCHEM_ELEMENTS_CACHE_FILEPATH.exists():
        payload = orjson.loads(PUBCHEM_ELEMENTS_CACHE_FILEPATH.read_bytes())
        if (
            isinstance(payload, dict)
            and isinstance(payload.get("elements"), list)
            and payload.get("cache_version") == CACHE_VERSION
        ):
            return payload

    try:
        periodic = httpx.get(
            "https://pubchem.ncbi.nlm.nih.gov/rest/pug/periodictable/JSON",
            timeout=30.0,
        ).json()
        cols = periodic["Table"]["Columns"]["Column"]
        rows = periodic["Table"]["Row"]
    except Exception:
        return {
            "retrieved_at": datetime.now(timezone.utc).isoformat(),
            "elements": [],
        }
    col_idx = {name: i for i, name in enumerate(cols)}
    elements: list[dict[str, Any]] = []
    client = httpx.Client(timeout=30.0)
    try:
        isotope_decay_map = _load_pubchem_isotope_decay_map(client)
        for row in rows:
            cells = row.get("Cell", [])
            try:
                atomic_number = int(cells[col_idx["AtomicNumber"]])
            except Exception:
                continue
            symbol = cells[col_idx["Symbol"]] if "Symbol" in col_idx else ""
            name = cells[col_idx["Name"]] if "Name" in col_idx else ""
            api_url = f"https://pubchem.ncbi.nlm.nih.gov/rest/pug_view/data/element/{atomic_number}/JSON"
            page_url = f"https://pubchem.ncbi.nlm.nih.gov/element/{atomic_number}"
            try:
                detail = client.get(api_url).json()
            except Exception:
                continue
            top_sections = detail.get("Record", {}).get("Section", [])
            iso_section = next((s for s in top_sections if s.get("TOCHeading") == "Isotopes"), {})
            sub = iso_section.get("Section", []) if isinstance(iso_section, dict) else []
            mass_abundance = next((s for s in sub if s.get("TOCHeading") == "Isotope Mass and Abundance"), {})
            decay = next((s for s in sub if s.get("TOCHeading") == "Atomic Mass, Half Life, and Decay"), {})
            decay_rows = _parse_isotope_decay(decay if isinstance(decay, dict) else {})
            if atomic_number in isotope_decay_map:
                decay_rows = isotope_decay_map[atomic_number]
            elements.append({
                "atomic_number": atomic_number,
                "symbol": symbol,
                "name": name,
                "api_url": api_url,
                "page_url": page_url,
                "stable_isotopes": _parse_isotope_mass_abundance(mass_abundance if isinstance(mass_abundance, dict) else {}),
                "isotope_decay": decay_rows,
            })
    finally:
        client.close()

    payload = {
        "cache_version": CACHE_VERSION,
        "retrieved_at": datetime.now(timezone.utc).isoformat(),
        "elements": sorted(elements, key=lambda x: x["atomic_number"]),
    }
    PUBCHEM_ELEMENTS_CACHE_FILEPATH.write_bytes(
        orjson.dumps(payload, option=orjson.OPT_INDENT_2)
    )
    return payload
