"""Download and parse GLAD ILCD-to-SimaPro substance mappings."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import openpyxl
import orjson
import structlog

from brightway_flows.downloads import PinnedFile
from brightway_flows.filesystem import (
    GLAD_ILCD_TO_SIMAPRO_JSON_FILEPATH,
    GLAD_ILCD_TO_SIMAPRO_XLSX_FILEPATH,
)

logger = structlog.get_logger(__name__)

#: The commit the builds' copy of the workbook is from.  It used to be read
#: from the tip of ``master``, so a commit upstream changed what a fresh data
#: directory read with no change here, and a renamed path stopped the build
#: (#431).  Moving to a newer workbook is changing this and the digest below.
GLAD_COMMIT = "124bef3d8c25b1f6fe478980502a115e0582c604"

GLAD_ILCD_TO_SIMAPRO_URL = (
    "https://github.com/One-Click-LCA/GLAD-ElementaryFlowResources/raw/"
    f"{GLAD_COMMIT}/Mapping/Output/Mapped_files/"
    "ILCD_EF3.1_TO_SimaProCSV_Professional10.2_SubstanceMappingsGLAD.xlsx"
)

#: The workbook at :data:`GLAD_COMMIT`, which is the one every build has read.
GLAD_ILCD_TO_SIMAPRO_SHA256 = (
    "56062d1f9e22329012112474a59d42dcea13a3b9b362f7a2e7bcfa8aca60d45d"
)


def download_glad_ilcd_to_simapro(
    url: str = GLAD_ILCD_TO_SIMAPRO_URL,
    force: bool = False,
) -> Path:
    """Download the GLAD ILCD-to-SimaPro workbook, checked against its digest."""
    return PinnedFile(urls=(url,), sha256=GLAD_ILCD_TO_SIMAPRO_SHA256).download(
        GLAD_ILCD_TO_SIMAPRO_XLSX_FILEPATH, force=force
    )


def _cell_text(value: object) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _json_safe_cell(value: object) -> object:
    if isinstance(value, datetime):
        return value.isoformat()
    return value


def parse_glad_ilcd_to_simapro_workbook(
    workbook_path: Path,
    *,
    output_path: Path = GLAD_ILCD_TO_SIMAPRO_JSON_FILEPATH,
) -> Path:
    """Parse GLAD workbook rows to JSON without reshaping."""
    wb = openpyxl.load_workbook(workbook_path, read_only=True, data_only=True)
    ws = wb[wb.sheetnames[0]]

    rows = ws.iter_rows(values_only=True)
    headers_row = next(rows, ())
    headers = [_cell_text(value) for value in headers_row]

    output: list[dict[str, object]] = []

    for raw_row in rows:
        row: dict[str, object] = {}
        for idx, value in enumerate(raw_row):
            if idx >= len(headers):
                continue
            header = headers[idx]
            if not header:
                continue
            row[header] = _json_safe_cell(value)
        if row:
            output.append(row)

    output_path.write_bytes(orjson.dumps(output, option=orjson.OPT_INDENT_2))
    logger.info(
        "saved_glad_additional_input",
        path=str(output_path),
        row_count=len(output),
    )
    return output_path

