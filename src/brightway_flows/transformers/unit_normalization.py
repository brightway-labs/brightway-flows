"""Normalize unit strings in flows to canonical notations from units.json."""

from __future__ import annotations

from typing import Any

import orjson
import structlog

from brightway_flows.domain.flow import Flow
from brightway_flows.domain.units import (
    build_units_index,
    resolve_unit_notation,
)
from brightway_flows.filesystem import DATA_DIR
from brightway_flows.pipeline import Change, Transformer

logger = structlog.get_logger(__name__)

class UnitNormalizationTransformer(Transformer):
    """Normalize unit strings to canonical notations from units.json.

    For each flow with a ``unit`` field:
    - Resolves the unit string to the canonical notation and IRI from ``units.json``.
    - Emits ``Change`` records for ``unit`` and ``unit_iri`` when normalization
      changes the current value.
    - Raises ``ValueError`` if any units cannot be resolved; details are written
      to ``DATA_DIR/missing-units.json``.  Add missing units to ``units.json``
      or ``UNIT_ALIASES`` to fix the error.
    """

    name = "unit_normalization"
    answers_per_flow = True

    def __init__(self) -> None:
        self._by_notation: dict[str, dict[str, Any]] = {}

    def setup(self) -> None:
        self._by_notation = build_units_index()

    def _resolve(self, unit: str) -> tuple[str, str] | None:
        """Return ``(canonical_notation, unit_iri)`` or ``None`` if unresolved."""
        return resolve_unit_notation(unit, self._by_notation)

    def transform(self, flows: list[Flow]) -> list[Change]:
        missing: dict[str, int] = {}
        changes: list[Change] = []

        for flow in flows:
            unit = flow.unit
            if not isinstance(unit, str) or not unit.strip():
                continue

            resolved = self._resolve(unit)
            if resolved is None:
                missing[unit] = missing.get(unit, 0) + 1
                continue

            canonical, unit_iri = resolved
            if flow.unit != canonical:
                changes.append(Change(
                    flow.uuid,
                    "unit",
                    canonical,
                    comment=f"Unit normalized from '{unit}' to '{canonical}'",
                ))
            if flow.unit_iri != unit_iri:
                changes.append(Change(
                    flow.uuid,
                    "unit_iri",
                    unit_iri,
                    comment=f"Unit IRI set from normalization of '{unit}'",
                ))

        if missing:
            missing_path = DATA_DIR / "missing-units.json"
            missing_path.write_bytes(orjson.dumps(
                {"missing": [{"unit": u, "count": c} for u, c in sorted(missing.items(), key=lambda x: -x[1])]},
                option=orjson.OPT_INDENT_2,
            ))
            logger.error(
                "unit_normalization.unresolved",
                missing_count=len(missing),
                path=str(missing_path),
            )
            raise ValueError(
                f"unit_normalization: {len(missing)} unit(s) could not be resolved. "
                f"Add them to units.json or UNIT_ALIASES. "
                f"Details written to {missing_path}. "
                f"Unresolved: {sorted(missing)}"
            )

        logger.info("unit_normalization.done", changes=len(changes))
        return changes
