"""Download, parse, and extract EF 3.1 ILCD flow and LCIA data."""

from __future__ import annotations

import re
from collections import defaultdict
from io import BytesIO
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING
from xml.etree import ElementTree
from xml.etree.ElementTree import Element
from zipfile import ZipFile

import httpx
import orjson
import structlog
from tqdm import tqdm

from brightway_flows.domain.lcia.records import (
    StatedFactor,
    flow_entries,
    stated_category,
)
from brightway_flows.filesystem import EF31_ZIP_FILEPATH
from brightway_flows.integrations.chebi import load_chebi_index
from brightway_flows.pipeline import normalize
from brightway_flows.filesystem import PACKAGE_DATA_DIR

if TYPE_CHECKING:  # `sources` reads the pipeline normaliser, which reads this.
    from brightway_flows.sources import SourceList

logger = structlog.get_logger(__name__)

EF31_URL = "https://eplca.jrc.ec.europa.eu/permalink/EF3_1/EF-v3.1.zip"

#: Corrections to the vendor data, applied at extraction so that nothing
#: downstream ever sees the uncorrected value.  Read by the generic
#: `brightway_flows.manual_fixes`; EF 3.1 has no fixing code of its own.
MANUAL_FIXES_FILEPATH = (
    PACKAGE_DATA_DIR / "ef-3.1-manual-fixes.json"
)

NAMESPACES: dict[str, str] = {
    "flow": "http://lca.jrc.it/ILCD/Flow",
    "fp": "http://lca.jrc.it/ILCD/FlowProperty",
    "ug": "http://lca.jrc.it/ILCD/UnitGroup",
    "lcia": "http://lca.jrc.it/ILCD/LCIAMethod",
    "common": "http://lca.jrc.it/ILCD/Common",
    "ecn": "http://eplca.jrc.ec.europa.eu/ILCD/Extensions/2018/ECNumber",
}
XML_LANG = "{http://www.w3.org/XML/1998/namespace}lang"
UNITS_FILEPATH = PACKAGE_DATA_DIR / "units.json"
CHEBI_UI_PREFIX = "https://www.ebi.ac.uk/chebi/searchId.do?chebiId="

UNIT_ALIASES: dict[str, tuple[str, float]] = {
    "item(s)": ("#", 1.0),
    "item": ("#", 1.0),
    "mol": ("mole", 1.0),
    "m2.a": ("m2.a", 1.0),
    "m3.a": ("m3.a", 1.0),
    "kg.d": ("kg.d", 1.0),
    # Year-based mass*time unit isn't in units.json; normalize to kg.d.
    "kg.a": ("kg.d", 365.25),
}

ELEMENT_NAME_ALIASES: dict[str, str] = {
    "aluminum": "aluminium",
    "cesium": "caesium",
    "praseodym": "praseodymium",
}


# ---------------------------------------------------------------------------
# Download helpers
# ---------------------------------------------------------------------------


def download_ef31(url: str = EF31_URL, force: bool = False) -> Path:
    """Download the EF 3.1 ZIP archive to the platformdirs data directory.

    Returns the path to the downloaded file.  Skips downloading if the file
    already exists unless *force* is ``True``.

    Parameters
    ----------
    url : str
        URL of the ZIP archive.
    force : bool
        Re-download even if the file already exists.
    """
    dest = EF31_ZIP_FILEPATH

    if dest.exists() and not force:
        logger.info("already downloaded EF 3.1 source data", path=str(dest))
        return dest

    logger.info("downloading EF 3.1 source data", url=url, destination=str(dest))

    with httpx.stream("GET", url, follow_redirects=True, timeout=120) as response:
        response.raise_for_status()
        total = int(response.headers.get("content-length", 0))

        with dest.open("wb") as f, tqdm(
            total=total or None,
            unit="B",
            unit_scale=True,
            desc=str(EF31_ZIP_FILEPATH),
        ) as progress:
            for chunk in response.iter_bytes(chunk_size=1024 * 64):
                f.write(chunk)
                progress.update(len(chunk))

    return dest


# ---------------------------------------------------------------------------
# XML extraction helpers
# ---------------------------------------------------------------------------


def find_ilcd_root(zf: ZipFile) -> str:
    """Locate the ILCD root directory inside the ZIP archive.

    The ZIP may contain an arbitrary top-level folder (e.g. ``EF-v3.1 (4)/``).
    This function finds the path prefix that contains the ``ILCD/flows/``
    subdirectory.

    Returns the prefix string including the trailing slash,
    e.g. ``"EF-v3.1 (4)/ILCD/"``.
    """
    for name in zf.namelist():
        if "/ILCD/flows/" in name:
            return name.split("ILCD/flows/")[0] + "ILCD/"
    raise FileNotFoundError("Could not find ILCD/flows/ directory inside the ZIP archive")


def zip_xml_paths(zf: ZipFile, ilcd_root: str, subdirectory: str) -> list[str]:
    """Return sorted ZIP member paths for all XMLs in an ILCD subdirectory.

    Parameters
    ----------
    zf : ZipFile
        The opened ZIP archive.
    ilcd_root : str
        The ILCD root prefix as returned by :func:`find_ilcd_root`.
    subdirectory : str
        ILCD subdirectory name, e.g. ``"flows"`` or ``"lciamethods"``.
    """
    prefix = ilcd_root + subdirectory + "/"
    return sorted(n for n in zf.namelist() if n.startswith(prefix) and n.endswith(".xml"))


def parse_xml_from_zip(zf: ZipFile, member: str) -> Element:
    """Parse an XML file from the ZIP and return the root element.

    Parameters
    ----------
    zf : ZipFile
        The opened ZIP archive.
    member : str
        Full path of the member inside the ZIP.
    """
    with zf.open(member) as f:
        return ElementTree.parse(BytesIO(f.read())).getroot()


def resolve_uri(base_member: str, uri: str) -> str:
    """Resolve a relative URI against a ZIP member's parent directory.

    For example, given a base member ``".../ILCD/flows/abc.xml"`` and a URI
    ``"../flowproperties/def.xml"``, returns ``".../ILCD/flowproperties/def.xml"``.

    Parameters
    ----------
    base_member : str
        ZIP path of the file that contains the URI reference.
    uri : str
        Relative URI to resolve (e.g. ``"../flowproperties/xxx.xml"``).
    """
    base_dir = PurePosixPath(base_member).parent
    resolved = (base_dir / uri).as_posix()

    parts: list[str] = []
    for part in resolved.split("/"):
        if part == "..":
            parts.pop()
        elif part != ".":
            parts.append(part)
    return "/".join(parts)


def get_text_en(parent: Element, tag: str) -> str | None:
    """Return the English text content of a child element.

    Looks for a child matching *tag* with ``xml:lang="en"``; falls back to the
    first child matching *tag* regardless of language.

    Parameters
    ----------
    parent : Element
        The parent XML element to search within.
    tag : str
        Namespace-prefixed tag name (e.g. ``"flow:baseName"``).
    """
    for child in parent.findall(tag, NAMESPACES):
        if child.get(XML_LANG) == "en":
            return child.text
    child = parent.find(tag, NAMESPACES)
    return child.text if child is not None else None


#: The boilerplate EF puts in `generalComment` on flows that have nothing to
#: say.  Present on thousands of rows, identical on every one of them, and
#: about the list rather than about the flow.
_ILCD_BOILERPLATE = (
    "Reference elementary flow of the International Reference Life Cycle Data "
    "System (ILCD)."
)

#: A comment that is nothing but a version number.  EF 3.1 has two -- 514 flows
#: carrying `01.00.000` and 53 carrying `03.01.000` -- and neither is the
#: version of the flow it sits on: every one of those rows declares
#: `dataSetVersion` `01.00.004`.  Anchored, and applied only to the whole
#: string, because a version number *inside* a sentence would be a sentence: no
#: comment in EF 3.1 contains one, and 84 distinct comments were read to check.
_VERSION_ONLY = re.compile(r"^\d{2}\.\d{2}\.\d{3}$")


def flow_general_comment(value: str | None) -> str | None:
    """What a flow's `generalComment` says about the flow, or `None`.

    Two things EF writes in that field are not descriptions, and this reads
    both as the absence of one.

    The boilerplate has been read this way since the extractor was written.
    The version number has not, and that is #62: a description is one of the
    fields deduplication compares, so `01.00.000` on one row and nothing on its
    twin is a difference, and the pipeline keeps two live flows for one
    substance in one context because of it.  116 such pairs are in the
    2026-08-12 build and 90 are held apart by this string alone.

    Reading it as no comment is not a cosmetic change: 77 of the 116 pairs
    collapse, which is why it is a decision (#62) rather than a cleanup.  No
    characterisation factor is lost -- in all 77 the dropped row's factors are
    a subset of the survivor's -- and in the 32 where both rows publish one
    factor with slightly different numbers, `deduplication.settle_factor_values`
    keeps the more precise of the two and records the other beside it (#63).
    That is what makes the collapse safe to let happen: before it, the number
    published was whichever one the sort reached.
    """
    if value is None:
        return None
    if value == _ILCD_BOILERPLATE:
        return None
    if _VERSION_ONLY.match(value.strip()):
        return None
    return value


def get_unit_group_units(zf: ZipFile, member: str) -> list[dict[str, str | float]]:
    """Parse a unit group XML and return its list of units.

    Parameters
    ----------
    zf : ZipFile
        The opened ZIP archive.
    member : str
        ZIP path of the unit group XML file.

    Returns
    -------
    list[dict[str, str | float]]
        Each dict has keys ``"name"`` (str) and ``"mean_value"`` (float).
    """
    root = parse_xml_from_zip(zf, member)
    units: list[dict[str, str | float]] = []
    for unit in root.findall(".//ug:units/ug:unit", NAMESPACES):
        name = unit.find("ug:name", NAMESPACES).text
        mean_value = float(unit.find("ug:meanValue", NAMESPACES).text)
        units.append({"name": name, "mean_value": mean_value})
    return units


def get_flow_property_unit_group_uri(zf: ZipFile, member: str) -> str:
    """Parse a flow property XML and return the URI of its reference unit group.

    Parameters
    ----------
    zf : ZipFile
        The opened ZIP archive.
    member : str
        ZIP path of the flow property XML file.
    """
    root = parse_xml_from_zip(zf, member)
    ref = root.find(
        ".//fp:flowPropertiesInformation/fp:quantitativeReference"
        "/fp:referenceToReferenceUnitGroup",
        NAMESPACES,
    )
    return ref.get("uri")


def get_reference_unit(zf: ZipFile, flow_member: str, root: Element) -> str | None:
    """Walk flow -> flow property -> unit group to find the reference unit name.

    Parameters
    ----------
    zf : ZipFile
        The opened ZIP archive.
    flow_member : str
        ZIP path of the flow XML being processed (used for URI resolution).
    root : Element
        Parsed root element of the flow XML.

    Returns
    -------
    str or None
        The unit name, or ``None`` if the chain cannot be resolved.
    """
    flow_info = root.find(".//flow:flowInformation", NAMESPACES)

    ref_idx_elem = flow_info.find(
        "flow:quantitativeReference/flow:referenceToReferenceFlowProperty", NAMESPACES
    )
    if ref_idx_elem is None:
        return None
    ref_idx = ref_idx_elem.text

    target_fp: Element | None = None
    for fp in root.findall(".//flow:flowProperties/flow:flowProperty", NAMESPACES):
        if fp.get("dataSetInternalID") == ref_idx:
            target_fp = fp
            break
    if target_fp is None:
        return None

    fp_ref = target_fp.find("flow:referenceToFlowPropertyDataSet", NAMESPACES)
    fp_uri = fp_ref.get("uri")
    flow_mean_value = float(target_fp.find("flow:meanValue", NAMESPACES).text)

    fp_member = resolve_uri(flow_member, fp_uri)
    ug_uri = get_flow_property_unit_group_uri(zf, fp_member)

    ug_member = resolve_uri(fp_member, ug_uri)
    units = get_unit_group_units(zf, ug_member)

    for unit in units:
        if unit["mean_value"] == flow_mean_value:
            return unit["name"]

    return None


def _normalize_unit_token(value: str) -> str:
    token = value.strip().lower()
    token = token.replace("·", ".").replace("*", ".")
    token = token.replace(" ", "")
    return token


def _load_units_index() -> dict[str, dict]:
    data = orjson.loads(UNITS_FILEPATH.read_bytes())
    by_notation: dict[str, dict] = {}
    by_label: dict[str, dict] = {}
    for row in data:
        notation = row.get("notation")
        label = row.get("label")
        if isinstance(notation, str) and notation.strip():
            by_notation[_normalize_unit_token(notation)] = row
        if isinstance(label, str) and label.strip():
            by_label[_normalize_unit_token(label)] = row
    return {
        "by_notation": by_notation,
        "by_label": by_label,
    }


def _resolve_unit(unit_name: str, units_index: dict[str, dict]) -> tuple[dict | None, float]:
    token = _normalize_unit_token(unit_name)
    if token in UNIT_ALIASES:
        mapped, multiplier = UNIT_ALIASES[token]
        entry = units_index["by_notation"].get(_normalize_unit_token(mapped))
        return entry, multiplier
    entry = units_index["by_notation"].get(token)
    if entry is not None:
        return entry, 1.0
    entry = units_index["by_label"].get(token)
    if entry is not None:
        return entry, 1.0
    return None, 1.0


def _extract_element_name(property_name: str) -> str | None:
    match = re.match(r"^\s*([A-Za-z][A-Za-z -]*)\s+content(?:\s+\([^)]*\))?\s*$", property_name)
    if not match:
        return None
    candidate = match.group(1).strip()
    key = candidate.lower()
    if key in ELEMENT_NAME_ALIASES:
        return ELEMENT_NAME_ALIASES[key]
    return candidate


def _choose_atom_chebi_record(
    element_name: str, chebi_index: dict[str, dict],
) -> dict | None:
    by_name = chebi_index["by_name"]
    records = chebi_index["records"]
    ids = by_name.get(normalize(element_name), [])
    if not ids:
        return None
    preferred_label = f"{element_name.lower()} atom"
    candidates = [records[cid] for cid in ids if cid in records]
    for record in candidates:
        label = (record.get("label") or "").lower()
        if label == preferred_label:
            return record
    for record in candidates:
        label = (record.get("label") or "").lower()
        if label.endswith(" atom"):
            return record
    return None


def load_flow_properties(
    zf: ZipFile, ilcd_root: str,
) -> tuple[dict[str, dict], list[dict]]:
    """Load ILCD flow property definitions and map units + element links."""
    units_index = _load_units_index()
    chebi_index = load_chebi_index()

    by_id: dict[str, dict] = {}
    unmapped: list[dict] = []
    for member in tqdm(
        zip_xml_paths(zf, ilcd_root, "flowproperties"), desc="Flow properties"
    ):
        root = parse_xml_from_zip(zf, member)
        ds_info = root.find(".//fp:flowPropertiesInformation/fp:dataSetInformation", NAMESPACES)
        if ds_info is None:
            continue
        property_id = ds_info.findtext("common:UUID", namespaces=NAMESPACES)
        if not property_id:
            continue
        name = get_text_en(ds_info, "common:name") or ""
        description = get_text_en(ds_info, "common:generalComment") or ""

        ug_uri = get_flow_property_unit_group_uri(zf, member)
        ug_member = resolve_uri(member, ug_uri)
        units = get_unit_group_units(zf, ug_member)
        reference_unit_name = None
        for unit in units:
            if unit["mean_value"] == 1.0:
                reference_unit_name = unit["name"]
                break
        if reference_unit_name is None:
            raise ValueError(f"Missing reference unit for flow property {property_id}")

        unit_entry, amount_multiplier = _resolve_unit(reference_unit_name, units_index)
        unit_iri = unit_entry["iri"] if unit_entry is not None else ""

        meta: dict = {
            "source": "ILCD EF 3.1",
            "ilcd_reference_unit": reference_unit_name,
            "normalization_multiplier": amount_multiplier,
        }
        if unit_entry is not None:
            meta["normalized_unit_notation"] = unit_entry.get("notation")
            meta["normalized_quantity_kind_iri"] = unit_entry.get("quantity_kind_iri")
        else:
            unmapped.append({
                "property_id": property_id,
                "property_name": name,
                "ilcd_unit": reference_unit_name,
            })

        element_name = _extract_element_name(name)
        if element_name:
            atom_record = _choose_atom_chebi_record(element_name, chebi_index)
            if atom_record:
                chebi_iri = atom_record.get("id")
                chebi_compact = ""
                if isinstance(chebi_iri, str):
                    tail = chebi_iri.rsplit("/", 1)[-1]
                    if tail.startswith("CHEBI_"):
                        chebi_compact = tail.replace("_", ":", 1)
                    else:
                        chebi_compact = tail
                meta["element"] = {
                    "name": element_name,
                    "chebi_iri": chebi_iri,
                    "chebi_id": chebi_compact,
                    "chebi_label": atom_record.get("label"),
                    "chebi_url": f"{CHEBI_UI_PREFIX}{chebi_compact}",
                }

        by_id[property_id] = {
            "id": property_id,
            "name": name,
            "description": description,
            "unit_iri": unit_iri,
            "meta": meta,
        }

    return by_id, unmapped


def extract_flow_property_values(
    zf: ZipFile,
    member: str,
    property_defs: dict[str, dict],
    source: str = "EF 3.1",
) -> dict:
    """Extract quantitative flow property values for one flow XML."""
    root = parse_xml_from_zip(zf, member)
    ds_info = root.find(".//flow:flowInformation/flow:dataSetInformation", NAMESPACES)
    flow_uuid = ds_info.findtext("common:UUID", namespaces=NAMESPACES) if ds_info is not None else None
    if not flow_uuid:
        return {"flow_uuid": "", "source": source, "properties": []}

    values: list[dict] = []
    for fp in root.findall(".//flow:flowProperties/flow:flowProperty", NAMESPACES):
        ref = fp.find("flow:referenceToFlowPropertyDataSet", NAMESPACES)
        if ref is None:
            continue
        property_id = ref.get("refObjectId")
        if not property_id:
            continue
        amount_text = fp.findtext("flow:meanValue", namespaces=NAMESPACES)
        if amount_text is None:
            continue
        amount = float(amount_text)

        prop_def = property_defs.get(property_id)
        multiplier = 1.0
        if prop_def:
            multiplier = prop_def.get("meta", {}).get("normalization_multiplier", 1.0)
        amount *= multiplier

        meta: dict = {}
        rsd = fp.findtext("flow:relativeStandardDeviation95In", namespaces=NAMESPACES)
        if rsd is not None:
            meta["relative_standard_deviation_95_in"] = float(rsd)
        if multiplier != 1.0:
            meta["applied_unit_normalization_multiplier"] = multiplier

        values.append({
            "property_id": property_id,
            "amount": amount,
            "meta": meta,
        })

    return {
        "flow_uuid": flow_uuid,
        "source": source,
        "properties": values,
    }


def load_lcia_methods(
    zf: ZipFile, ilcd_root: str,
) -> tuple[dict[str, list[StatedFactor]], list[dict]]:
    """Parse all LCIA method XMLs.

    Returns
    -------
    tuple[dict[str, list[StatedFactor]], list[dict]]
        A pair of ``(flow_cfs, methods_meta)``.

        *flow_cfs* maps flow UUID to the factors that file names for it, as
        :class:`~brightway_flows.domain.lcia.records.StatedFactor` records.
        The 25 method files between them state 319,575 of these about 89,070
        flows, and the 25 :class:`~brightway_flows.domain.lcia.records.
        StatedCategory` objects they name are interned, so a category's five
        strings are held once rather than 12,783 times on average.

        *methods_meta* is the payload for ``lcia-methods.json``: one entry per
        method file, which is a category plus the number of factors it states.
    """
    flow_cfs: dict[str, list[StatedFactor]] = defaultdict(list)
    methods_meta: list[dict] = []

    for member in tqdm(
        zip_xml_paths(zf, ilcd_root, "lciamethods"), desc="LCIA methods"
    ):
        root = parse_xml_from_zip(zf, member)

        lcia_info = root.find(".//lcia:LCIAMethodInformation", NAMESPACES)
        ds_info = lcia_info.find("lcia:dataSetInformation", NAMESPACES)

        method_uuid = ds_info.find("common:UUID", NAMESPACES).text
        name = get_text_en(ds_info, "common:name")
        methodology = ds_info.findtext("lcia:methodology", namespaces=NAMESPACES)
        impact_category = ds_info.findtext("lcia:impactCategory", namespaces=NAMESPACES)
        impact_indicator = ds_info.findtext("lcia:impactIndicator", namespaces=NAMESPACES)
        general_comment = get_text_en(ds_info, "common:generalComment")

        ref_qty = lcia_info.find(
            "lcia:quantitativeReference/lcia:referenceQuantity", NAMESPACES
        )
        reference_unit: str | None = None
        if ref_qty is not None:
            reference_unit = get_text_en(ref_qty, "common:shortDescription")

        category = stated_category(
            uuid=method_uuid,
            name=name,
            methodology=methodology,
            impact_category=impact_category,
            impact_indicator=impact_indicator,
            reference_unit=reference_unit,
            general_comment=general_comment,
        )

        factor_count = 0
        for factor in root.findall(
            ".//lcia:characterisationFactors/lcia:factor", NAMESPACES
        ):
            # A stated zero is a statement, and it is kept (#47).  EF 3.1
            # declares 52,088 factors of exactly 0.0 -- 16.3% of the method
            # files, and nearly half of `Human toxicity, cancer`.  Discarding
            # them made "EF assessed this flow and the factor is zero"
            # indistinguishable from "EF never assessed this flow", which is
            # how 244 groundwater rows came to be read as uncharacterised when
            # EF had characterised them as zero (#48).
            mean_value = float(factor.findtext("lcia:meanValue", namespaces=NAMESPACES))
            ref = factor.find("lcia:referenceToFlowDataSet", NAMESPACES)
            flow_uuid = ref.get("refObjectId")
            # `lcia:location` is what makes the row unique, and it was dropped
            # until #314's PR 3b: 42,871 of these 319,575 factors state one, and
            # without it `Land use` puts 213 numbers on one flow with nothing to
            # tell them apart.  Absent on the other 276,704, where a factor is
            # about a substance in a compartment and that is all.
            location = (
                factor.findtext("lcia:location", namespaces=NAMESPACES) or ""
            ).strip()
            flow_cfs[flow_uuid].append(
                StatedFactor(
                    category=category,
                    flow_uuid=flow_uuid,
                    amount=mean_value,
                    geography=location or None,
                )
            )
            factor_count += 1

        methods_meta.append(category.to_method_entry(factor_count))

    return dict(flow_cfs), methods_meta


def extract_flow_data(
    zf: ZipFile,
    member: str,
    lcia_map: dict[str, list[StatedFactor]],
    source: str = "EF 3.1",
) -> dict:
    """Extract structured data from a single flow XML.

    Parameters
    ----------
    zf : ZipFile
        The opened ZIP archive.
    member : str
        ZIP path of the flow XML file.
    lcia_map : dict[str, list[StatedFactor]]
        Pre-loaded LCIA characterisation factors (from :func:`load_lcia_methods`).
    source : str
        Name of the flow list this flow belongs to (e.g. ``"EF 3.1"``).

    Returns
    -------
    dict
        A dict with keys: ``uuid``, ``name``, ``cas_numbers``, ``ec_numbers``,
        ``context``, ``general_comment``, ``synonyms``,
        ``unit``, ``lcia_methods``, and ``source``.
    """
    root = parse_xml_from_zip(zf, member)

    ds_info = root.find(".//flow:flowInformation/flow:dataSetInformation", NAMESPACES)

    uuid: str = ds_info.find("common:UUID", NAMESPACES).text

    name_elem = ds_info.find("flow:name", NAMESPACES)
    base_name: str | None = (
        get_text_en(name_elem, "flow:baseName") if name_elem is not None else None
    )

    cas_elem = ds_info.find("flow:CASNumber", NAMESPACES)
    cas_numbers: list[str] = [cas_elem.text] if cas_elem is not None and cas_elem.text else []

    ec_elem = ds_info.find("common:other/ecn:ECNumber", NAMESPACES)
    ec_numbers: list[str] = [ec_elem.text] if ec_elem is not None and ec_elem.text else []

    categories: list[str] = [
        cat.text
        for cat in ds_info.findall(
            ".//common:elementaryFlowCategorization/common:category", NAMESPACES
        )
    ]

    comment: str | None = flow_general_comment(get_text_en(ds_info, "common:generalComment"))

    synonyms_text = get_text_en(ds_info, "common:synonyms")
    synonyms: list[str] = (
        [s.strip() for s in synonyms_text.split(";")] if synonyms_text else []
    )

    unit: str | None = get_reference_unit(zf, member, root)

    return {
        "uuid": uuid,
        "name": base_name,
        "cas_numbers": cas_numbers,
        "ec_numbers": ec_numbers,
        "context": categories,
        "general_comment": comment,
        "synonyms": synonyms,
        "unit": unit,
        # Serialised here: this builds the extracted file, which is where the
        # records leave the process.  What the pipeline reads back is records
        # again, via the codec `Flow` declares for the field.
        "lcia_methods": flow_entries(lcia_map.get(uuid, [])),
        "source": source,
    }


# ---------------------------------------------------------------------------
# The adapter
# ---------------------------------------------------------------------------


def fetch(
    source: SourceList, *, force: bool = False, keep_zip: bool = False
) -> Path:
    """The :class:`~brightway_flows.sources.SourceAdapter` for EF 3.1.

    This body was ~55 lines inline in `cli.extract` until #15, which is why
    `docs/operating/sources.md` could tell a reader to "write an adapter" while
    the base list's own lived in a CLI command.  A list's fetch belongs beside
    the vendor parsing it drives, and `role: "base"` means nothing if the base
    list is the one list reached differently.

    Three files, not one.  The return value is the flows, because that is what
    the protocol is about and what the merge reads; the LCIA methods and the
    flow-property values are extracted from the same archive in the same pass
    and would cost a second full walk of 20,000 XML members to produce
    separately.

    *keep_zip* is beyond the protocol and defaults to the protocol's behaviour,
    so `fetch-source EF-3.1` deletes the archive as `extract` always has. It is
    reachable from `extract --keep-zip`, which is where a reader debugging the
    vendor XML needs it.
    """
    # Imported here rather than at module scope: `sources` imports
    # `manual_fixes` and the pipeline normaliser, and this module is imported by
    # `cli` at startup.
    from brightway_flows.filesystem import (
        FLOW_PROPERTIES_FILEPATH,
        LCIA_METHODS_FILEPATH,
    )
    from brightway_flows.manual_fixes import apply_manual_fixes

    zip_path = download_ef31(force=force)

    with ZipFile(zip_path) as zf:
        ilcd_root = find_ilcd_root(zf)

        logger.info("extracting lcia methods data")
        lcia_map, methods_meta = load_lcia_methods(zf, ilcd_root)
        logger.info("extracting flow properties data")
        property_defs_by_id, unmapped_units = load_flow_properties(zf, ilcd_root)

        flow_members = zip_xml_paths(zf, ilcd_root, "flows")
        flows: list[dict] = []
        flow_property_values: list[dict] = []
        for member in tqdm(flow_members, desc="Flows"):
            flows.append(extract_flow_data(zf, member, lcia_map))
            flow_property_values.append(
                extract_flow_property_values(
                    zf, member, property_defs_by_id, source=source.source_label
                )
            )

    if source.manual_fixes_path is not None:
        apply_manual_fixes(flows, source.manual_fixes_path, label=source.source_label)

    source.flows_path.write_bytes(orjson.dumps(flows, option=orjson.OPT_INDENT_2))
    logger.info("saved flow data file", path=str(source.flows_path))

    LCIA_METHODS_FILEPATH.write_bytes(
        orjson.dumps(methods_meta, option=orjson.OPT_INDENT_2)
    )
    logger.info("saved lcia methods file", path=str(LCIA_METHODS_FILEPATH))

    FLOW_PROPERTIES_FILEPATH.write_bytes(
        orjson.dumps(
            {
                "schema_version": 1,
                "source": source.source_label,
                "properties": sorted(
                    property_defs_by_id.values(),
                    key=lambda row: row["name"].lower(),
                ),
                "flow_property_values": [
                    row for row in flow_property_values if row["flow_uuid"]
                ],
                "unmapped_units": sorted(
                    unmapped_units,
                    key=lambda row: (row["property_name"].lower(), row["ilcd_unit"]),
                ),
            },
            option=orjson.OPT_INDENT_2,
        )
    )
    logger.info("saved flow properties file", path=str(FLOW_PROPERTIES_FILEPATH))

    if keep_zip:
        logger.info("keeping zip archive", path=str(zip_path))
    else:
        zip_path.unlink()
        logger.info("deleted zip archive", path=str(zip_path))

    return source.flows_path
