"""The change log: every field the pipeline wrote, and why.

`changelog` covers all twenty transformers and holds one row per *edit*.  An
edit is keyed by substance, which is what it is: the two biggest fields in the
log, `altLabel` and `properties`, belong to the flow object, and one edit to a
substance lands on every elementary flow that shares it.  `changelog_flows`
records which ones.

So "everything that happened to this substance" is a filter on `changelog`, and
"everything that happened to this flow" is a filter on `changelog_flows`.  The
second is a join, but a cheap one -- that table holds a uuid and a name, where
storing the edit per flow held the payload a dozen times over and cost 3.7 GiB
(#253).

One consequence is visible on the page: a row is an edit, not an edit-flow
pair, so the counts are smaller than they were and a row can name several
flows.  That is the honest number -- stripping catalogue labels off Silicon
Dioxide was one edit, and the page used to show it thirteen times.

The three history sections of a flow detail page live here. They are the
heaviest part of that page and the least often read, so they are their own
route: a detail page does not pay for history nobody opens.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from typing import Any

from brightway_flows.pipeline.review_records import (
    ProvenanceActivity,
    prov_activity_id,
)
from brightway_flows.webapps.app.db import table_exists
from brightway_flows.webapps.app.queries.common import (
    PAGE_SIZE,
    Page,
    alphabetical,
    clamp_page,
    load_json,
    order_by,
)

#: How many of an edit's flows a row names before it says "and N more".  An
#: edit can land on a few hundred; the page is not the place to list them.
_FLOWS_SHOWN = 3

_SORT_COLUMNS = {
    "order": "c.change_index",
    "field": "lower(c.field)",
    "transformer": "lower(c.transformer)",
}


@dataclass
class ChangeFlow:
    """One elementary flow an edit landed on."""

    uuid: str
    name: str = ""


@dataclass
class ChangeRow:
    """One applied field change, as the log recorded it.

    Named `ChangeRow` and not `Change` because `pipeline.engine.Change` is the
    other end of the same pipe: a change a transformer *proposes*, before
    anything has agreed to apply it. This is the record of one having been
    applied, read back out of `changelog` a build later, and confusing a
    request with a receipt is easy enough without one name for both (#98).
    The `Row` suffix is the one `FlowRow` and `SubstanceRow` already use for a
    row of a paginated list.

    `flows` is capped at :data:`_FLOWS_SHOWN`; `flow_count` is the real total,
    so a row can say "and 11 more" without the query returning them.
    """

    change_index: int
    transformer: str
    flow_object_id: str = ""
    field_name: str = ""
    old_value: Any = None
    new_value: Any = None
    comment: str = ""
    flow_count: int = 0
    flows: list[ChangeFlow] = field(default_factory=list)


@dataclass
class Activity:
    """One PROV-O activity, with the IRIs composed for display.

    The table stores a version number and the change's index; the IRIs are a
    fixed function of those plus the run id, so they are minted here rather
    than stored three times per row.
    """

    activity_id: str
    used_entity_id: str
    generated_entity_id: str
    agent_id: str
    change_index: int
    uuid: str
    field_name: str
    transformer: str
    time: str = ""
    comment: str = ""


@dataclass
class FieldHistory:
    """What happened to one field of one flow, folded together.

    `provenance.json` materialised this as `flow_field_provenance`, a second
    copy of the activities grouped by field. It is a `GROUP BY` over the
    activities of one flow, so it is computed rather than stored.
    """

    field_name: str
    change_count: int = 0
    latest_time: str = ""
    latest_comment: str = ""
    transformers: list[str] = field(default_factory=list)


@dataclass
class History:
    """Everything behind one object's changes page."""

    changes: Page[ChangeRow] = field(default_factory=Page)
    activities: list[Activity] = field(default_factory=list)
    fields: list[FieldHistory] = field(default_factory=list)
    available: bool = True


def available(connection: sqlite3.Connection) -> bool:
    """Whether this database carries a change log at all.

    False for one written before Phase 0, which is the normal state of a data
    directory nobody has rebuilt. The page says so rather than showing nothing.
    """
    return table_exists(connection, "changelog")


def _change(row: sqlite3.Row) -> ChangeRow:
    return ChangeRow(
        change_index=int(row["change_index"]),
        transformer=row["transformer"],
        flow_object_id=row["flow_object_id"] or "",
        field_name=row["field"] or "",
        old_value=load_json(row["old_value_json"], None),
        new_value=load_json(row["new_value_json"], None),
        comment=row["comment"] or "",
    )


def _attach_flows(connection: sqlite3.Connection, changes: list[ChangeRow]) -> None:
    """Fill in `flows` and `flow_count` for a page of edits, in two queries.

    Two, not two per row: a page is 100 edits and a correlated subquery per row
    is 200 round trips for something one `IN` clause answers.
    """
    if not changes:
        return
    by_index = {change.change_index: change for change in changes}
    placeholders = ",".join("?" * len(by_index))
    keys = list(by_index)

    for row in connection.execute(
        f"SELECT change_index, count(*) AS n FROM changelog_flows "
        f"WHERE change_index IN ({placeholders}) GROUP BY change_index",
        keys,
    ):
        by_index[int(row["change_index"])].flow_count = int(row["n"])

    # `ORDER BY` then take the first few per edit in Python: SQLite has window
    # functions, but a page's worth of rows is small and this keeps the query
    # readable.  Ordered by name so the flows a row names are stable.
    for row in connection.execute(
        f"SELECT change_index, elementary_flow_uuid, flow_name FROM changelog_flows "
        f"WHERE change_index IN ({placeholders}) "
        "ORDER BY change_index, lower(flow_name), elementary_flow_uuid",
        keys,
    ):
        change = by_index[int(row["change_index"])]
        if len(change.flows) < _FLOWS_SHOWN:
            change.flows.append(
                ChangeFlow(
                    uuid=row["elementary_flow_uuid"],
                    name=row["flow_name"] or "",
                )
            )


def change_page(
    connection: sqlite3.Connection,
    *,
    query: str = "",
    transformer: str = "",
    field_name: str = "",
    uuid: str = "",
    flow_object_id: str = "",
    sort: str = "",
    page: int = 1,
) -> Page[ChangeRow]:
    """Applied changes, filtered and paged in SQL.

    The page this replaces read `transform-log.json` into a module global and
    filtered the whole list in Python. That file is 1.26 GB for one transformer.

    A row is one edit.  Filtering by `uuid` asks `changelog_flows` which edits
    touched that flow; filtering by `flow_object_id` reads `changelog` directly,
    because that is what the table is keyed by.
    """
    if not available(connection):
        return Page()

    clauses: list[str] = []
    params: list[Any] = []
    if transformer:
        clauses.append("c.transformer = ?")
        params.append(transformer)
    if field_name:
        clauses.append("c.field = ?")
        params.append(field_name)
    if uuid:
        clauses.append(
            "EXISTS (SELECT 1 FROM changelog_flows f "
            "WHERE f.change_index = c.change_index AND f.elementary_flow_uuid = ?)"
        )
        params.append(uuid)
    if flow_object_id:
        clauses.append("c.flow_object_id = ?")
        params.append(flow_object_id)
    if query:
        like = f"%{query.lower()}%"
        # The flow name and uuid moved to `changelog_flows`, so searching them
        # is an EXISTS rather than a column test.  The value payloads stay on
        # `changelog` and are searched in place -- which is the reason those
        # columns are not compressed.
        clauses.append(
            "(lower(c.comment) LIKE ? OR lower(c.old_value_json) LIKE ? "
            "OR lower(c.new_value_json) LIKE ? "
            "OR EXISTS (SELECT 1 FROM changelog_flows f "
            "WHERE f.change_index = c.change_index "
            "AND (lower(f.flow_name) LIKE ? OR lower(f.elementary_flow_uuid) LIKE ?)))"
        )
        params.extend([like] * 5)

    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    total = int(
        connection.execute(
            f"SELECT count(*) FROM changelog c {where}", params
        ).fetchone()[0]
    )
    number = clamp_page(page, total)
    rows = connection.execute(
        f"SELECT c.* FROM changelog c {where} "
        f"ORDER BY {order_by(sort, _SORT_COLUMNS, 'c.change_index')} LIMIT ? OFFSET ?",
        [*params, PAGE_SIZE, (number - 1) * PAGE_SIZE],
    ).fetchall()
    changes = [_change(row) for row in rows]
    _attach_flows(connection, changes)
    return Page(rows=changes, total=total, number=number)


def transformers(connection: sqlite3.Connection) -> list[tuple[str, str]]:
    """Which transformers changed anything, most active first.

    Counts edits, not edit-flow pairs, which is what the rows of this page are.
    """
    if not available(connection):
        return []
    return alphabetical(
        (row["transformer"], row["transformer"], int(row["n"]))
        for row in connection.execute(
            "SELECT transformer, count(*) AS n FROM changelog GROUP BY transformer"
        )
    )


def fields(connection: sqlite3.Connection) -> list[tuple[str, str]]:
    """Which fields were written, in name order with a count of the edits.

    Counts edits, as :func:`transformers` does.
    """
    if not available(connection):
        return []
    return alphabetical(
        (row["field"], row["field"], int(row["n"]))
        for row in connection.execute(
            "SELECT field, count(*) AS n FROM changelog GROUP BY field"
        )
    )


def _run_id(connection: sqlite3.Connection) -> str:
    if not table_exists(connection, "pipeline_runs"):
        return ""
    row = connection.execute("SELECT run_id FROM pipeline_runs LIMIT 1").fetchone()
    return row["run_id"] if row else ""


def _run_timestamp(connection: sqlite3.Connection) -> str:
    if not table_exists(connection, "pipeline_runs"):
        return ""
    row = connection.execute("SELECT timestamp FROM pipeline_runs LIMIT 1").fetchone()
    return row["timestamp"] if row else ""


def activities(connection: sqlite3.Connection, *, uuid: str) -> list[Activity]:
    """The PROV-O trail for one flow, with its IRIs composed.

    Joined to `changelog` for the comment: the activity table stores the graph
    structure and nothing the change already says, which is what stops it being
    a second copy of the largest payload in the run.
    """
    if not table_exists(connection, "provenance_activities"):
        return []
    run_id = _run_id(connection)
    time = _run_timestamp(connection)
    # Ordered by `entity_version`, not `change_index`: the trail chains, each
    # activity consuming what the last produced, and `change_index` orders by
    # an edit's first appearance anywhere rather than by when it reached this
    # flow.
    rows = connection.execute(
        "SELECT a.*, c.comment AS comment FROM provenance_activities a "
        "LEFT JOIN changelog c ON c.change_index = a.change_index "
        "WHERE a.elementary_flow_uuid = ? ORDER BY a.entity_version",
        (uuid,),
    ).fetchall()
    trail: list[Activity] = []
    for row in rows:
        record = ProvenanceActivity(
            change_index=int(row["change_index"]),
            uuid=row["elementary_flow_uuid"],
            field_name=row["field"],
            transformer=row["transformer"],
            entity_version=int(row["entity_version"]),
        )
        trail.append(Activity(
            activity_id=prov_activity_id(run_id, record.change_index),
            used_entity_id=record.used_entity_id,
            generated_entity_id=record.generated_entity_id,
            agent_id=record.agent_id,
            change_index=record.change_index,
            uuid=record.uuid,
            field_name=record.field_name,
            transformer=record.transformer,
            time=time,
            comment=row["comment"] or "",
        ))
    return trail


def field_history(connection: sqlite3.Connection, *, uuid: str) -> list[FieldHistory]:
    """Per-field summary for one flow, most-changed first."""
    if not available(connection):
        return []
    rows = connection.execute(
        "SELECT c.field AS field, count(*) AS n, max(c.change_index) AS latest "
        "FROM changelog c JOIN changelog_flows f ON f.change_index = c.change_index "
        "WHERE f.elementary_flow_uuid = ? GROUP BY c.field "
        "ORDER BY n DESC, c.field",
        (uuid,),
    ).fetchall()
    time = _run_timestamp(connection)

    summaries: list[FieldHistory] = []
    for row in rows:
        names = [
            item["transformer"]
            for item in connection.execute(
                "SELECT DISTINCT c.transformer AS transformer FROM changelog c "
                "JOIN changelog_flows f ON f.change_index = c.change_index "
                "WHERE f.elementary_flow_uuid = ? AND c.field = ? "
                "ORDER BY c.transformer",
                (uuid, row["field"]),
            )
        ]
        latest = connection.execute(
            "SELECT comment FROM changelog WHERE change_index = ?", (row["latest"],)
        ).fetchone()
        summaries.append(FieldHistory(
            field_name=row["field"],
            change_count=int(row["n"]),
            latest_time=time,
            latest_comment=(latest["comment"] if latest else "") or "",
            transformers=names,
        ))
    return summaries


def flow_history(
    connection: sqlite3.Connection, uuid: str, *, page: int = 1
) -> History:
    """Everything `/flows/<uuid>/changes` shows."""
    if not available(connection):
        return History(available=False)
    return History(
        changes=change_page(connection, uuid=uuid, page=page),
        activities=activities(connection, uuid=uuid),
        fields=field_history(connection, uuid=uuid),
    )


def substance_history(
    connection: sqlite3.Connection, flow_object_id: str, *, page: int = 1
) -> History:
    """Everything `/flow-objects/<id>/changes` shows.

    No PROV trail: the graph is per flow version, and a substance is not a
    version of anything. What it has is the change log, which `changelog` keys
    by `flow_object_id` -- the reason it replaces `consensus_changes`, which
    could only be reached through a join on the flow uuid.
    """
    if not available(connection):
        return History(available=False)
    return History(
        changes=change_page(connection, flow_object_id=flow_object_id, page=page),
    )
