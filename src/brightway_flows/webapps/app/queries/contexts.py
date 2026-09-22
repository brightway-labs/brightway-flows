"""The context mapping rules: each source's compartments, and where they land.

Read from `context_default_mappings`, which the pipeline copies out of
`data/context-manual-mapping.json` -- a package data file describing the rules
themselves, not a run artifact, which is why it survives the input layer that
used to display it.

Not to be confused with the per-release `ecoinvent-<version>-context-mapping.json`
files: those are read by the *merge*, to place one source list's contexts. These
are what the `default_context_mapping` transformer applies during the transform,
to every list at once.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from typing import Any

from brightway_flows.webapps.app.db import table_exists
from brightway_flows.webapps.app.queries.common import (
    PAGE_SIZE,
    Page,
    clamp_page,
    load_json,
)


@dataclass
class ContextMapping:
    """One rule: a source's raw compartment, and the consensus context it becomes."""

    source: str
    source_context: list[str] = field(default_factory=list)
    context_iri: str = ""
    context_display: str = ""
    comment: str = ""

    @property
    def source_display(self) -> str:
        return " → ".join(self.source_context)

    @property
    def context_short(self) -> str:
        """The IRI's last segment, which is what fits in a column."""
        return self.context_iri.rsplit("/", 1)[-1]


def available(connection: sqlite3.Connection) -> bool:
    return table_exists(connection, "context_default_mappings")


def mapping_page(
    connection: sqlite3.Connection,
    *,
    query: str = "",
    source: str = "",
    page: int = 1,
) -> Page[ContextMapping]:
    if not available(connection):
        return Page()

    clauses: list[str] = []
    params: list[Any] = []
    if source:
        clauses.append("source = ?")
        params.append(source)
    if query:
        like = f"%{query.lower()}%"
        clauses.append(
            "(lower(source) LIKE ? OR lower(source_context_json) LIKE ? "
            "OR lower(context_iri) LIKE ? OR lower(context_display) LIKE ? "
            "OR lower(comment) LIKE ?)"
        )
        params.extend([like] * 5)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""

    total = int(
        connection.execute(
            f"SELECT count(*) FROM context_default_mappings {where}", params
        ).fetchone()[0]
    )
    number = clamp_page(page, total)
    rows = connection.execute(
        f"SELECT * FROM context_default_mappings {where} "
        "ORDER BY lower(source), lower(source_context_json) LIMIT ? OFFSET ?",
        [*params, PAGE_SIZE, (number - 1) * PAGE_SIZE],
    ).fetchall()
    return Page(
        rows=[
            ContextMapping(
                source=row["source"],
                source_context=load_json(row["source_context_json"], []),
                context_iri=row["context_iri"] or "",
                context_display=row["context_display"] or "",
                comment=row["comment"] or "",
            )
            for row in rows
        ],
        total=total,
        number=number,
    )


def sources(connection: sqlite3.Connection) -> list[tuple[str, str]]:
    if not available(connection):
        return []
    return [
        (row["source"], f"{row['source']} ({int(row['n']):,})")
        for row in connection.execute(
            "SELECT source, count(*) AS n FROM context_default_mappings "
            "GROUP BY source ORDER BY lower(source)"
        )
    ]
