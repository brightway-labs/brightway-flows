"""Validate consensus flow contexts and export string-list expressions.

This used to also split ``context-manual-mapping.json`` into one file per
``source`` and write them into package data, which the merge then read back.
That projection is gone: both stages read the master through
:mod:`brightway_flows.context_mapping` (#11).  ``build`` never ran this
command, so the merge was reading whatever the projection said the last time
somebody ran it by hand.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import orjson

from brightway_flows.domain.context import (
    Context,
    Dimension,
    Geography,
    IndoorAirClass,
    LandUseClass,
    Media,
    PopulationDensity,
    VerticalStrata,
    WaterBody,
)
from brightway_flows.filesystem import PACKAGE_DATA_DIR

_DATA_DIR = PACKAGE_DATA_DIR
CONTEXTS_FILEPATH = _DATA_DIR / "consensus-flow-contexts.json"
STRINGS_FILEPATH = _DATA_DIR / "consensus-flows-as-strings.json"


def _enum(value: Any, enum_cls: Any, *, field: str, context_iri: str) -> Any:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(
            f"context {context_iri}: field '{field}' must be a string or null"
        )
    try:
        return enum_cls(value)
    except Exception as exc:
        raise ValueError(
            f"context {context_iri}: invalid value for '{field}': {value!r}"
        ) from exc


def _validate_context_row(row: dict[str, Any]) -> Context:
    context_iri = row.get("context_iri")
    if not isinstance(context_iri, str) or not context_iri.strip():
        raise ValueError("context entry missing non-empty 'context_iri'")

    return Context(
        dimension=_enum(row.get("dimension"), Dimension, field="dimension", context_iri=context_iri),
        media=_enum(row.get("media"), Media, field="media", context_iri=context_iri),
        strata=_enum(row.get("strata"), VerticalStrata, field="strata", context_iri=context_iri),
        geography=_enum(row.get("geography"), Geography, field="geography", context_iri=context_iri),
        water_body=_enum(row.get("water_body"), WaterBody, field="water_body", context_iri=context_iri),
        population_density=_enum(
            row.get("population_density"),
            PopulationDensity,
            field="population_density",
            context_iri=context_iri,
        ),
        indoor=_enum(row.get("indoor"), IndoorAirClass, field="indoor", context_iri=context_iri),
        land_use=_enum(row.get("land_use"), LandUseClass, field="land_use", context_iri=context_iri),
    )


def validate_contexts_and_generate_strings(
    *,
    contexts_path: Path = CONTEXTS_FILEPATH,
    strings_path: Path = STRINGS_FILEPATH,
) -> dict[str, list[str]]:
    payload = orjson.loads(contexts_path.read_bytes())
    if not isinstance(payload, list):
        raise ValueError(f"{contexts_path} must contain a JSON list")

    seen_iris: set[str] = set()
    out: dict[str, list[str]] = {}

    for idx, row in enumerate(payload):
        if not isinstance(row, dict):
            raise ValueError(f"context entry at index {idx} must be an object")
        context = _validate_context_row(row)
        context_iri = str(row["context_iri"]).strip()
        if context_iri in seen_iris:
            raise ValueError(f"duplicate context_iri found: {context_iri}")
        seen_iris.add(context_iri)
        out[context_iri] = context.to_list()

    strings_path.write_bytes(orjson.dumps(out, option=orjson.OPT_INDENT_2))
    return out
