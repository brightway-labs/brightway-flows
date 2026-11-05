"""What each merged list says a unit of a consensus flow is: the `flow_property_statements` table.

A source row arrives carrying what its list states about one unit of it --
AGRIBALYSE's hard coal is 18.2 MJ of net calorific value, Stepwise's 19.1 MJ
by its method, ecoinvent's 18.01 MJ by its implementation workbook -- and the
merge converts by one of those statements where the row lands on a flow
measured in another quantity (`merge.conversions`).  The mapping publishes
the one it used.  This table keeps *all* of them, one row per statement per
source row that reached a consensus flow, with which one converted, so that
a reader of `Hard Coal` can see the three numbers side by side and the spread
between them (#407, phase C).

A merge table, not a transform one: it is written list by list as each is
merged and has to outlive the next list's pass, which is the split
`pipeline/sqlite_schema.py` describes.  Rewritten per `(list_name,
list_version)` so a re-merge replaces rather than appends.  The review app and
`flow_object_properties` read it; nothing in the published files does.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import orjson
import structlog

from brightway_flows.domain.elementary_flow import ElementaryFlow
from brightway_flows.domain.flow import Flow
from brightway_flows.domain.property_statements import PropertyStatement, factor_between
from brightway_flows.domain.quantities import quantity
from brightway_flows.domain.records import SerialisableRecord
from brightway_flows.domain.units import CONVERSION_BASIS_KEY, CONVERSION_QUANTITY_KEY, ConversionBasis
from brightway_flows.domain.vocabulary import QUDT_CONVERSION_MULTIPLIER_CURIE
from brightway_flows.pipeline.sqlite_schema import insert_statement

logger = structlog.get_logger(__name__)

TABLE = "flow_property_statements"

SCHEMA = (
    f"""
    CREATE TABLE IF NOT EXISTS {TABLE} (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        run_id TEXT,
        list_name TEXT NOT NULL,
        list_version TEXT NOT NULL,
        source_flow_uuid TEXT NOT NULL,
        source_flow_name TEXT,
        elementary_flow_uuid TEXT NOT NULL,
        flow_object_id TEXT,
        quantity TEXT NOT NULL,
        quantity_iri TEXT NOT NULL,
        value REAL NOT NULL,
        unit TEXT NOT NULL,
        per_unit TEXT NOT NULL,
        stated_by TEXT NOT NULL,
        used_for_conversion INTEGER NOT NULL DEFAULT 0,
        provenance_json TEXT NOT NULL,
        comment TEXT
    )
    """,
)

INDEXES = (
    f"CREATE INDEX IF NOT EXISTS idx_{TABLE}_object ON {TABLE}(flow_object_id)",
    f"CREATE INDEX IF NOT EXISTS idx_{TABLE}_flow ON {TABLE}(elementary_flow_uuid)",
    f"CREATE INDEX IF NOT EXISTS idx_{TABLE}_list ON {TABLE}(list_name, list_version)",
)

#: The columns the `INSERT` fills; `id` is SQLite's.
COLUMNS = (
    "run_id", "list_name", "list_version", "source_flow_uuid", "source_flow_name",
    "elementary_flow_uuid", "flow_object_id", "quantity", "quantity_iri", "value",
    "unit", "per_unit", "stated_by", "used_for_conversion", "provenance_json",
    "comment",
)


@dataclass(frozen=True)
class PropertyStatementRow(SerialisableRecord):
    """One statement a source row carried onto a consensus flow (rule 19)."""

    run_id: str
    list_name: str
    list_version: str
    source_flow_uuid: str
    source_flow_name: str
    elementary_flow_uuid: str
    flow_object_id: str
    quantity: str
    quantity_iri: str
    value: float
    unit: str
    per_unit: str
    stated_by: str
    #: Whether the mapping's `qudt:conversionMultiplier` was derived from this
    #: statement, as against another statement on the same row or none.
    used_for_conversion: bool
    provenance: dict[str, Any] = field(default_factory=dict)
    comment: str = ""

    def as_tuple(self) -> tuple[Any, ...]:
        return (
            self.run_id, self.list_name, self.list_version, self.source_flow_uuid,
            self.source_flow_name, self.elementary_flow_uuid, self.flow_object_id,
            self.quantity, self.quantity_iri, self.value, self.unit, self.per_unit,
            self.stated_by, int(self.used_for_conversion),
            orjson.dumps(self.provenance).decode(), self.comment,
        )


def create_table(connection: sqlite3.Connection) -> None:
    for statement in (*SCHEMA, *INDEXES):
        connection.execute(statement)


def _converted_by(statement: PropertyStatement, metadata: Mapping[str, Any], *, target_unit: str) -> bool:
    """Whether the mapping's published multiplier is *statement*'s number.

    The mapping records the basis, the quantity IRI and the multiplier; a
    statement is the one used when all three agree with what it would give
    for the pair, which is how two statements of one quantity and one number
    -- the method's 30.3 and the name's 30.3 -- both read as used.
    """
    if metadata.get(CONVERSION_BASIS_KEY) != ConversionBasis.FLOW_PROPERTY.value:
        return False
    if metadata.get(CONVERSION_QUANTITY_KEY) != statement.quantity_iri:
        return False
    published = metadata.get(QUDT_CONVERSION_MULTIPLIER_CURIE)
    derived = factor_between(statement, str(metadata.get("unit") or ""), target_unit)
    return isinstance(published, (int, float)) and derived is not None and derived == published


def rows_for_merged_list(
    *,
    run_id: str,
    list_name: str,
    list_version: str,
    source_flows: Iterable[Flow],
    merged_elementary: Iterable[ElementaryFlow],
) -> list[PropertyStatementRow]:
    """Every statement a row of this list carried onto a consensus flow.

    Read off the flows' `source_refs`, which is where every route into the
    consensus list -- a curated target, an algorithmic match, a flow the merge
    created -- leaves the row's reference and the conversion it published, so
    one walk covers them all.  A row that reached no flow leaves no row here:
    the table is about the consensus list.
    """
    by_uuid = {flow.uuid: flow for flow in source_flows if flow.property_statements}
    if not by_uuid:
        return []
    rows: list[PropertyStatementRow] = []
    for elementary in merged_elementary:
        # `source_refs` is the external payload shape, a list of dicts the
        # record keeps as it was written (rule 2), read here as the sqlite
        # writer reads it.
        for ref in elementary.source_refs or ():
            if not isinstance(ref, dict):
                continue
            if (
                str(ref.get("list_name") or "") != list_name
                or str(ref.get("list_version") or "") != list_version
            ):
                continue
            source = by_uuid.get(str(ref.get("source_flow_uuid") or ""))
            if source is None:
                continue
            metadata = ref.get("source_metadata")
            metadata = metadata if isinstance(metadata, dict) else {}
            for statement in source.property_statements or ():
                rows.append(
                    PropertyStatementRow(
                        run_id=run_id,
                        list_name=list_name,
                        list_version=list_version,
                        source_flow_uuid=source.uuid,
                        source_flow_name=str(ref.get("source_flow_name") or source.name or ""),
                        elementary_flow_uuid=elementary.elementary_flow_id or "",
                        flow_object_id=elementary.flow_object_id or "",
                        quantity=statement.quantity,
                        quantity_iri=quantity(statement.quantity).iri,
                        value=statement.value,
                        unit=statement.unit,
                        per_unit=statement.per_unit,
                        stated_by=statement.stated_by.value,
                        used_for_conversion=_converted_by(
                            statement, metadata, target_unit=str(elementary.unit or "")
                        ),
                        provenance=statement.provenance.to_dict(),
                        comment=statement.comment,
                    )
                )
    return rows


def write_rows(
    rows: Iterable[PropertyStatementRow], *, list_name: str, list_version: str,
    db_path: Path | None = None,
) -> int:
    """Replace this list's rows with *rows*.  Returns how many were written."""
    from brightway_flows.filesystem import CONSENSUS_DB_FILEPATH

    db_path = CONSENSUS_DB_FILEPATH if db_path is None else db_path
    rows = list(rows)
    connection = sqlite3.connect(db_path)
    try:
        create_table(connection)
        connection.execute(
            f"DELETE FROM {TABLE} WHERE list_name = ? AND list_version = ?",
            (list_name, list_version),
        )
        connection.executemany(
            insert_statement(TABLE, COLUMNS), [row.as_tuple() for row in rows]
        )
        connection.commit()
    finally:
        connection.close()
    logger.info(
        "wrote_flow_property_statements", list=f"{list_name} {list_version}",
        rows=len(rows), used_for_conversion=sum(1 for r in rows if r.used_for_conversion),
    )
    return len(rows)


def read_rows(
    flow_object_ids: Iterable[str], *, db_path: Path | None = None
) -> dict[str, list[PropertyStatementRow]]:
    """Every list's rows for each of *flow_object_ids*, across every merge so far."""
    from brightway_flows.filesystem import CONSENSUS_DB_FILEPATH

    db_path = CONSENSUS_DB_FILEPATH if db_path is None else db_path
    wanted = {str(i) for i in flow_object_ids if i}
    out: dict[str, list[PropertyStatementRow]] = {}
    if not wanted:
        return out
    connection = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        create_table_exists = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (TABLE,)
        ).fetchone()
        if not create_table_exists:
            return out
        for record in connection.execute(f"SELECT * FROM {TABLE} ORDER BY list_name, list_version, source_flow_name"):
            if record["flow_object_id"] not in wanted:
                continue
            out.setdefault(record["flow_object_id"], []).append(
                PropertyStatementRow(
                    run_id=record["run_id"] or "",
                    list_name=record["list_name"],
                    list_version=record["list_version"],
                    source_flow_uuid=record["source_flow_uuid"],
                    source_flow_name=record["source_flow_name"] or "",
                    elementary_flow_uuid=record["elementary_flow_uuid"],
                    flow_object_id=record["flow_object_id"] or "",
                    quantity=record["quantity"],
                    quantity_iri=record["quantity_iri"],
                    value=float(record["value"]),
                    unit=record["unit"],
                    per_unit=record["per_unit"],
                    stated_by=record["stated_by"],
                    used_for_conversion=bool(record["used_for_conversion"]),
                    provenance=orjson.loads(record["provenance_json"] or "{}"),
                    comment=record["comment"] or "",
                )
            )
    finally:
        connection.close()
    return out
