"""Reads for the merge section: what a run did with each source flow.

Every page is a query over `merge_runs`, `merge_run_inputs`, `merge_outcomes`
and `merge_conflicts`. That is the point of the tables: the old report was seven
parallel JSON lists, and the three unmatched views it shipped were the same
9,614 rows stored twice, split on a boolean. They are three calls to
`outcome_page` here.

Results come back as `MergeOutcome` records, not rows, so the templates read
attributes and a wrong field name raises rather than rendering blank.

This came from `webapps/run_report/queries.py`, which was already what
`queries/` asks for and was the only part of the four applications that had
tests. Two things changed when the `/merge` views were written against it: it
took a path and opened a connection per call, where the rest of `queries/`
takes the request's connection -- four calls on the summary page meant four
file opens -- and it had a page type of its own, so the shared pager could not
render it.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from typing import Any

import orjson

from brightway_flows.merge.store import (
    ConflictKind,
    MergeOutcome,
    Outcome,
    _outcome_from_row,
)
from brightway_flows.webapps.app.db import table_exists
from brightway_flows.webapps.app.queries.common import PAGE_SIZE, Page, clamp_page


@dataclass
class OutcomeCounts:
    """A set of source rows, counted three ways.

    Rows are not substances and substances are not flows. A source list carries
    one row per substance per context, so the 12,373 rows the 3.12 and 3.8 run
    of 2026-08-16 resolved from a stored decision name 1,958 distinct
    substances; and those rows landed on fewer consensus flows than there are
    rows, because two lists can send their own row to the same flow.

    Counting only rows is what made the summary page misread: "9,850 rows" is
    the size of the job, not the size of the problem, and a curator deciding
    whether an unmatched pile is worth an afternoon needs to know it is eleven
    substances rather than eleven hundred.
    """

    #: The `Outcome` these rows share, or `""` for a count over every row.
    outcome: str = ""
    rows: int = 0
    #: Distinct source names. The source rows have no flow object of their own
    #: -- that is what the merge decides -- so the name is what stands in for
    #: the substance, which is also how the source lists are counted above.
    flow_objects: int = 0
    #: Distinct consensus flows these rows landed on. Zero for unmatched rows,
    #: which by definition landed on none.
    elementary_flows: int = 0


@dataclass
class RunSummary:
    """The header every merge page carries: which run is being looked at."""

    run_id: str = ""
    started_at: str = ""
    finished_at: str = ""
    stats: dict[str, Any] = field(default_factory=dict)
    inputs: list[dict[str, Any]] = field(default_factory=list)
    exists: bool = False


def _latest_run_id(connection: sqlite3.Connection) -> str | None:
    row = connection.execute(
        "SELECT run_id FROM merge_runs ORDER BY started_at DESC, rowid DESC LIMIT 1"
    ).fetchone()
    return row[0] if row else None


def run_stats(connection: sqlite3.Connection, run_id: str) -> dict[str, int]:
    """Counts by outcome, computed rather than stored.

    Computed so they cannot disagree with the rows beside them, which is what
    happened while they were read back out of a `stats` block in the JSON
    report.
    """
    by_outcome = dict(
        connection.execute(
            "SELECT outcome, count(*) FROM merge_outcomes WHERE run_id = ? "
            "GROUP BY outcome",
            (run_id,),
        ).fetchall()
    )
    with_candidates = int(
        connection.execute(
            "SELECT count(*) FROM merge_outcomes WHERE run_id = ? AND outcome = ? "
            "AND has_flow_object_candidates = 1",
            (run_id, str(Outcome.UNMATCHED)),
        ).fetchone()[0]
    )
    inconsistent = int(
        connection.execute(
            "SELECT count(*) FROM merge_outcomes WHERE run_id = ? "
            "AND has_context_inconsistency = 1",
            (run_id,),
        ).fetchone()[0]
    )
    total = sum(by_outcome.values())
    unmatched = by_outcome.get(str(Outcome.UNMATCHED), 0)
    return {
        "source rows": total,
        "prepared": by_outcome.get(str(Outcome.PREPARED), 0),
        "algorithm": by_outcome.get(str(Outcome.ALGORITHM), 0),
        "manual additions": by_outcome.get(str(Outcome.MANUAL_ADDITION), 0),
        "created substances": by_outcome.get(str(Outcome.CREATED), 0),
        "matched": total - unmatched,
        "unmatched": unmatched,
        "unmatched with candidates": with_candidates,
        "unmatched without candidates": unmatched - with_candidates,
        "stale decisions": inconsistent,
    }


#: The three counts, spelled once.  `nullif` is what makes the third column a
#: count of flows rather than a count of rows with a target: an unmatched row
#: stores `''`, and `count(DISTINCT ...)` would otherwise count that empty
#: string as a flow.
_COUNT_COLUMNS = (
    "count(*) AS rows, "
    "count(DISTINCT source_name) AS flow_objects, "
    "count(DISTINCT nullif(target_elementary_flow_id, '')) AS elementary_flows"
)


def _counts_from_row(row: sqlite3.Row, outcome: str = "") -> OutcomeCounts:
    return OutcomeCounts(
        outcome=outcome,
        rows=int(row["rows"]),
        flow_objects=int(row["flow_objects"]),
        elementary_flows=int(row["elementary_flows"]),
    )


def outcome_counts(
    connection: sqlite3.Connection, run_id: str
) -> list[OutcomeCounts]:
    """Rows, substances and consensus flows per outcome, in the merge's order.

    In `Outcome`'s order rather than by size, because the order is the sequence
    a row goes through -- a stored decision first, then the algorithm, then a
    curator's addition, then a creation, then nothing worked -- and a table
    sorted by count reads as a ranking of things that are not in competition.
    """
    found = {
        row["outcome"]: _counts_from_row(row, row["outcome"])
        for row in connection.execute(
            f"SELECT outcome, {_COUNT_COLUMNS} FROM merge_outcomes "
            "WHERE run_id = ? GROUP BY outcome",
            (run_id,),
        )
    }
    known = [str(value) for value in Outcome]
    ordered = [found.pop(name) for name in known if name in found]
    # A category this code does not know about is still shown: the table
    # outlives the run that wrote it, and an outcome written by an older
    # version is not a reason to report a smaller total than the run had.
    ordered.extend(found[name] for name in sorted(found))
    return ordered


def run_totals(connection: sqlite3.Connection, run_id: str) -> OutcomeCounts:
    """The same three counts over every row, which is not their column sums.

    A substance unmatched in one list and matched in another is one substance,
    and two lists can send a row each to the same consensus flow, so both
    distinct counts are smaller than the sum of the outcomes above.
    """
    row = connection.execute(
        f"SELECT {_COUNT_COLUMNS} FROM merge_outcomes WHERE run_id = ?",
        (run_id,),
    ).fetchone()
    return _counts_from_row(row)


def input_counts(
    connection: sqlite3.Connection, run_id: str
) -> dict[tuple[str, str], OutcomeCounts]:
    """The same three counts per source list, keyed by name and version."""
    return {
        (row["list_name"], row["list_version"]): _counts_from_row(row)
        for row in connection.execute(
            f"SELECT list_name, list_version, {_COUNT_COLUMNS} FROM merge_outcomes "
            "WHERE run_id = ? GROUP BY list_name, list_version",
            (run_id,),
        )
    }


def load_run(connection: sqlite3.Connection, run_id: str | None = None) -> RunSummary:
    """The run being reported on, or an empty summary if there is none.

    A database with no merge tables is what a build that merged no source list
    produces, so it is reported rather than raised: the app says "no run yet",
    not 500.
    """
    if not table_exists(connection, "merge_runs"):
        return RunSummary()
    run = run_id or _latest_run_id(connection)
    if run is None:
        return RunSummary()

    row = connection.execute(
        "SELECT * FROM merge_runs WHERE run_id = ?", (run,)
    ).fetchone()
    if row is None:
        return RunSummary()

    per_list = input_counts(connection, run)
    inputs = [
        {
            "list_name": item["list_name"],
            "list_version": item["list_version"],
            "sequence": item["sequence"],
            "row_count": item["row_count"],
            # What those rows are, rather than how many there are.  A key on
            # the dict rather than a second list the template has to line up
            # with this one by index.
            "flow_object_count": per_list.get(
                (item["list_name"], item["list_version"]), OutcomeCounts()
            ).flow_objects,
        }
        for item in connection.execute(
            "SELECT * FROM merge_run_inputs WHERE run_id = ? ORDER BY sequence",
            (run,),
        )
    ]
    return RunSummary(
        run_id=run,
        started_at=row["started_at"] or "",
        finished_at=row["finished_at"] or "",
        stats=run_stats(connection, run),
        inputs=inputs,
        exists=True,
    )


def _outcome_clauses(
    *,
    run_id: str,
    outcome: Outcome | None = None,
    has_flow_object_candidates: bool | None = None,
    has_context_inconsistency: bool | None = None,
    source_list: str = "",
    query: str = "",
) -> tuple[list[str], list[Any]]:
    """The `WHERE` the outcome table is selected by, shared by rows and counts.

    One place, so the chip above the table cannot count a set the table does not
    show.
    """
    clauses = ["run_id = ?"]
    params: list[Any] = [run_id]
    if outcome is not None:
        clauses.append("outcome = ?")
        params.append(str(outcome))
    if has_flow_object_candidates is not None:
        clauses.append("has_flow_object_candidates = ?")
        params.append(int(has_flow_object_candidates))
    if has_context_inconsistency is not None:
        clauses.append("has_context_inconsistency = ?")
        params.append(int(has_context_inconsistency))
    if source_list:
        name, _, version = source_list.partition("-")
        clauses.append("list_name = ? AND list_version = ?")
        params.extend([name, version])
    if query:
        clauses.append(
            "(lower(source_name) LIKE ? OR source_uuid LIKE ? OR source_cas LIKE ?)"
        )
        like = f"%{query.lower()}%"
        params.extend([like, like, like])
    return clauses, params


def outcome_badges(
    connection: sqlite3.Connection, **filters: Any
) -> tuple[list[tuple[str, str, int]], int]:
    """Each outcome, its label and how many rows carry it under *filters*.

    The badge in the `Outcome` column, offered as a filter above the table.
    Counted with every filter in force except the outcome itself, so a chip
    reading 1,204 selects 1,204 rows rather than the number the run produced
    before anything was narrowed.

    In `Outcome`'s own order rather than by size, for the reason
    :func:`outcome_counts` gives: the order is the sequence a source row goes
    through, and sorting by count reads as a ranking of things that are not in
    competition.
    """
    clauses, params = _outcome_clauses(**{**filters, "outcome": None})
    where = " AND ".join(clauses)
    counted = {
        str(row["outcome"]): int(row["n"])
        for row in connection.execute(
            f"SELECT outcome, count(*) AS n FROM merge_outcomes WHERE {where} "
            "GROUP BY outcome",
            params,
        )
    }
    known = [str(value) for value in Outcome]
    badges = [
        (name, name.replace("-", " "), counted[name])
        for name in [*known, *sorted(set(counted) - set(known))]
        if counted.get(name)
    ]
    return badges, sum(counted.values())


def outcome_page(
    connection: sqlite3.Connection,
    *,
    run_id: str,
    outcome: Outcome | None = None,
    has_flow_object_candidates: bool | None = None,
    has_context_inconsistency: bool | None = None,
    source_list: str = "",
    query: str = "",
    page: int = 1,
) -> Page[MergeOutcome]:
    """Outcomes matching the given filters, one page at a time.

    The old report's `unmatched`, `unmatched_with_flow_object_candidates` and
    `unmatched_without_flow_object_candidates` are this function with
    `has_flow_object_candidates` unset, True and False.
    """
    clauses, params = _outcome_clauses(
        run_id=run_id,
        outcome=outcome,
        has_flow_object_candidates=has_flow_object_candidates,
        has_context_inconsistency=has_context_inconsistency,
        source_list=source_list,
        query=query,
    )
    where = " AND ".join(clauses)
    total = int(
        connection.execute(
            f"SELECT count(*) FROM merge_outcomes WHERE {where}", params
        ).fetchone()[0]
    )
    number = clamp_page(page, total)
    rows = connection.execute(
        f"SELECT * FROM merge_outcomes WHERE {where} ORDER BY rowid LIMIT ? OFFSET ?",
        [*params, PAGE_SIZE, (number - 1) * PAGE_SIZE],
    ).fetchall()
    return Page(
        rows=[_outcome_from_row(row) for row in rows], total=total, number=number
    )


def outcome_detail(
    connection: sqlite3.Connection, run_id: str, source_uuid: str
) -> list[MergeOutcome]:
    """Every list's outcome for one source flow.

    A list, not one record: the same source uuid can appear once per source
    list, and seeing them together is how a divergent mapping is understood.
    """
    rows = connection.execute(
        "SELECT * FROM merge_outcomes WHERE run_id = ? AND source_uuid = ? "
        "ORDER BY list_name, list_version",
        (run_id, source_uuid),
    ).fetchall()
    return [_outcome_from_row(row) for row in rows]


def reason_breakdown(
    connection: sqlite3.Connection, run_id: str
) -> list[dict[str, Any]]:
    """Why rows could not be placed, by category, most common first.

    A plain `GROUP BY reason`, because `reason` is a category:
    :class:`~brightway_flows.merge.report.UnmatchedReason`. It used to
    embed the target uuid for one of the categories, which this had to split
    back out in SQL to keep the summary from rendering 8,439 groups at 2 MB.
    """
    return [
        {"reason": row["reason"], "count": int(row["n"])}
        for row in connection.execute(
            "SELECT reason, count(*) AS n FROM merge_outcomes "
            "WHERE run_id = ? AND outcome = ? AND reason != '' "
            "GROUP BY reason ORDER BY n DESC",
            (run_id, str(Outcome.UNMATCHED)),
        )
    ]


def basis_breakdown(
    connection: sqlite3.Connection, run_id: str
) -> list[dict[str, Any]]:
    """What matches rested on: cas, ec, label, or a narrowed combination."""
    return [
        {"basis": row["basis"], "count": int(row["n"])}
        for row in connection.execute(
            "SELECT basis, count(*) AS n FROM merge_outcomes "
            "WHERE run_id = ? AND basis != '' GROUP BY basis ORDER BY n DESC",
            (run_id,),
        )
    ]


def conflicts(connection: sqlite3.Connection, run_id: str) -> list[dict[str, Any]]:
    """Disagreements between source lists. Empty unless a run merged several."""
    if not table_exists(connection, "merge_conflicts"):
        return []
    return [
        {
            "target_elementary_flow_id": row["target_elementary_flow_id"],
            "kind": ConflictKind(row["kind"]),
            "claimants": orjson.loads(row["claimants_json"]),
        }
        for row in connection.execute(
            "SELECT * FROM merge_conflicts WHERE run_id = ? ORDER BY rowid",
            (run_id,),
        )
    ]


def source_lists(connection: sqlite3.Connection, run_id: str) -> list[str]:
    """The lists this run consumed, in merge order.

    The one list in this application that is not alphabetical, and deliberately:
    order matters here, because a later list can match a flow an earlier one
    created.  Sorting it by name would make a dropdown of six entries marginally
    easier to scan and would throw away the only place that sequence is stated.
    """
    return [
        f"{row['list_name']}-{row['list_version']}"
        for row in connection.execute(
            "SELECT DISTINCT list_name, list_version FROM merge_run_inputs "
            "WHERE run_id = ? ORDER BY sequence",
            (run_id,),
        )
    ]


@dataclass
class CandidateObject:
    """A substance an unmatched row could belong to."""

    flow_object_id: str
    name: str = ""
    #: Which identifiers put this substance forward: `cas`, `ec`, `label`.
    basis_hits: list[str] = field(default_factory=list)


@dataclass
class CandidateFlow:
    """A consensus flow an unmatched row could have landed on.

    The name, the unit and the context are the point of this record. A row is
    unmatched with `tied-elementary-candidates` because the selector could not
    choose between several flows, and a curator cannot choose either while the
    page shows eighteen uuids and no properties: two candidates with the same
    name, unit and context are a duplicate in the consensus list, and two with
    the same score and different contexts are a question about the source row.
    Which of the two it is decides what the curator does next.
    """

    elementary_flow_id: str
    name: str = ""
    unit: str = ""
    context: list[str] = field(default_factory=list)
    context_iri: str = ""
    #: What the selector scored it, where it got as far as scoring.
    score: int | None = None
    #: Shares the winning score, which is what "tied" means.
    tied_at_top: bool = False
    #: Counts read off the flow itself, for choosing between candidates that
    #: look alike: a deprecated flow is not the answer, and of two live
    #: duplicates the one characterisation methods use is.
    lcia_factor_count: int = 0
    is_deprecated: bool = False
    #: Whether the published list still holds this uuid. A run recorded against
    #: an older list can name a flow that is gone, and saying so is better than
    #: printing a blank name beside a uuid.
    resolved: bool = False


@dataclass
class CandidateSummary:
    """What one source row had to choose from.

    One summary per outcome, whether or not the row is unmatched: a placed row
    summarises to an empty record, so a template asks `if candidates.flows`
    rather than repeating the test on the outcome.
    """

    objects: list[CandidateObject] = field(default_factory=list)
    #: The flows, best score first, capped by the caller: the list page shows
    #: three of them, the detail page all of them.
    flows: list[CandidateFlow] = field(default_factory=list)
    #: How many there were before the cap.
    flow_count: int = 0
    #: How many share the winning score, or zero where nothing tied.
    tied_count: int = 0
    winning_score: int | None = None
    #: What the selector recorded about the field it scored over: how many
    #: flows the candidate substances have between them, how many survived the
    #: dimension and media filter, and how many a context mismatch removed.
    candidate_count: int = 0
    eligible_count: int = 0
    filtered_out_count: int = 0


def _as_dicts(value: Any) -> list[dict[str, Any]]:
    """A `detail` field that should hold records, as records.

    `detail` is an external payload -- whatever the run serialised -- so every
    read of it is defensive. A field written by an older version, or written as
    something other than a list of objects, renders as nothing rather than
    raising inside a template.
    """
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _as_strings(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if isinstance(item, str) and item.strip()]


def _score(entry: dict[str, Any]) -> int | None:
    raw = entry.get("score")
    return int(raw) if isinstance(raw, int | float) and not isinstance(raw, bool) else None


def _scored_candidates(detail: dict[str, Any]) -> list[dict[str, Any]]:
    """The scored candidates, wherever this run recorded them.

    An unmatched row carries them under `candidate_elementary_flows`;
    `algorithm_details` holds the same list as `scored_candidates`, and a run
    that kept only the shortlist has `top_candidates`. First one with anything
    in it wins, so the page does not depend on which path wrote the row.
    """
    details = detail.get("algorithm_details")
    details = details if isinstance(details, dict) else {}
    for holder, key in (
        (detail, "candidate_elementary_flows"),
        (details, "scored_candidates"),
        (details, "top_candidates"),
    ):
        entries = _as_dicts(holder.get(key))
        if entries:
            return entries
    return []


def _ranked_candidates(detail: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    """Candidate flows, best first, from whichever record the run left.

    Sorted here rather than trusted from the payload: the scored list is in
    score order when the selector writes it, but the ids-only fallback -- a row
    that failed before scoring, or a prepared decision naming several targets
    -- has no order at all. `sorted` is stable, so equal scores keep the order
    the run put them in, which is the order the selector considered them.
    """
    entries = [
        (str(entry.get("elementary_flow_id") or ""), entry)
        for entry in _scored_candidates(detail)
    ]
    entries = [(flow_id, entry) for flow_id, entry in entries if flow_id]
    seen = {flow_id for flow_id, _ in entries}
    bare = _as_strings(detail.get("candidate_elementary_flow_ids")) or _as_strings(
        detail.get("candidate_target_uuids")
    )
    entries.extend((flow_id, {}) for flow_id in bare if flow_id not in seen)
    return sorted(
        entries,
        key=lambda pair: (
            0 if _score(pair[1]) is not None else 1,
            -(_score(pair[1]) or 0),
        ),
    )


def _candidate_objects(detail: dict[str, Any]) -> list[CandidateObject]:
    """The substances the row could belong to, records first, then bare ids."""
    objects = [
        CandidateObject(
            flow_object_id=str(entry.get("flow_object_id") or ""),
            name=str(entry.get("name") or ""),
            basis_hits=_as_strings(entry.get("basis_hits")),
        )
        for entry in _as_dicts(detail.get("candidate_flow_objects"))
    ]
    objects = [entry for entry in objects if entry.flow_object_id]
    seen = {entry.flow_object_id for entry in objects}
    objects.extend(
        CandidateObject(flow_object_id=flow_object_id)
        for flow_object_id in _as_strings(detail.get("candidate_flow_object_ids"))
        if flow_object_id not in seen
    )
    return objects


def _lookup(
    connection: sqlite3.Connection, statement: str, key: str, ids: set[str]
) -> dict[str, sqlite3.Row]:
    """*statement* run over *ids*, keyed by *key*.

    Chunked under SQLite's variable limit: a page of fifty unmatched rows with
    a dozen candidates each is six hundred parameters, and the detail page caps
    nothing at all.
    """
    ordered = sorted(identifier for identifier in ids if identifier)
    found: dict[str, sqlite3.Row] = {}
    for start in range(0, len(ordered), 400):
        chunk = ordered[start : start + 400]
        placeholders = ",".join("?" * len(chunk))
        for row in connection.execute(f"{statement} ({placeholders})", chunk):
            found[row[key]] = row
    return found


def _candidate_flow(
    flow_id: str,
    entry: dict[str, Any],
    row: sqlite3.Row | None,
    *,
    tied_at_top: bool,
) -> CandidateFlow:
    """One candidate, from what the run recorded and what the list holds now.

    The run's own record wins for unit and context -- those are the values the
    selector scored, and the point of showing them is to explain a decision
    that has already been taken -- while the published list supplies the name,
    which the run did not store, and the two counts that separate candidates
    the run could not separate.
    """
    context = _as_strings(entry.get("context"))
    if not context and row is not None:
        context = [
            part.strip()
            for part in str(row["context_display"] or "").split("→")
            if part.strip()
        ]
    return CandidateFlow(
        elementary_flow_id=flow_id,
        name=str(row["pref_label_value"] or "") if row is not None else "",
        unit=str(entry.get("unit") or "")
        or (str(row["unit"] or "") if row is not None else ""),
        context=context,
        context_iri=str(entry.get("context_iri") or ""),
        score=_score(entry),
        tied_at_top=tied_at_top,
        lcia_factor_count=int(row["lcia_factor_count"]) if row is not None else 0,
        is_deprecated=bool(row["is_deprecated"]) if row is not None else False,
        resolved=row is not None,
    )


def candidate_summaries(
    connection: sqlite3.Connection,
    outcomes: list[MergeOutcome],
    *,
    limit: int | None = None,
) -> list[CandidateSummary]:
    """What each of *outcomes* had to choose from, in the order given.

    A list parallel to the rows rather than a dict keyed by the source uuid:
    the same uuid appears once per source list, so a uuid is not a key here.

    Two queries for the whole page however many rows it holds. The candidates
    are stored as identifiers -- the run had the flows in memory and wrote down
    which ones it was choosing between -- so the names come from
    `elementary_flows` and `flow_objects`, and a lookup per candidate on a page
    of fifty unmatched rows would be several hundred of them.
    """
    ranked = [_ranked_candidates(outcome.detail) for outcome in outcomes]
    shown = [entries[:limit] if limit is not None else entries for entries in ranked]
    objects = [_candidate_objects(outcome.detail) for outcome in outcomes]

    # Guarded, like the read of `merge_conflicts` above: these tables outlive
    # the run that wrote them and `write_merge_run` will write its four into a
    # database that holds nothing else, so a merge run can be reported on
    # without a published list beside it.  The candidates are then identifiers
    # without names, which is what the run recorded and still worth showing.
    flow_rows = (
        _lookup(
            connection,
            "SELECT uuid, pref_label_value, unit, context_display, "
            "lcia_factor_count, is_deprecated FROM elementary_flows WHERE uuid IN",
            "uuid",
            {flow_id for entries in shown for flow_id, _ in entries},
        )
        if table_exists(connection, "elementary_flows")
        else {}
    )
    object_rows = (
        _lookup(
            connection,
            "SELECT flow_object_id, pref_label_value FROM flow_objects "
            "WHERE flow_object_id IN",
            "flow_object_id",
            {
                entry.flow_object_id
                for group in objects
                for entry in group
                if not entry.name
            },
        )
        if table_exists(connection, "flow_objects")
        else {}
    )

    summaries: list[CandidateSummary] = []
    for outcome, entries, visible, group in zip(
        outcomes, ranked, shown, objects, strict=True
    ):
        top = _score(entries[0][1]) if entries else None
        tied = (
            sum(1 for _, entry in entries if _score(entry) == top)
            if top is not None
            else 0
        )
        details = outcome.detail.get("algorithm_details")
        details = details if isinstance(details, dict) else {}
        for candidate in group:
            if not candidate.name and candidate.flow_object_id in object_rows:
                candidate.name = (
                    object_rows[candidate.flow_object_id]["pref_label_value"] or ""
                )
        summaries.append(
            CandidateSummary(
                objects=group,
                flows=[
                    _candidate_flow(
                        flow_id,
                        entry,
                        flow_rows.get(flow_id),
                        tied_at_top=tied > 1 and _score(entry) == top,
                    )
                    for flow_id, entry in visible
                ],
                flow_count=len(entries),
                tied_count=tied if tied > 1 else 0,
                winning_score=top,
                candidate_count=int(details.get("elementary_candidate_count") or 0),
                eligible_count=int(details.get("eligible_candidate_count") or 0),
                filtered_out_count=int(
                    details.get("filtered_out_context_mismatch_count") or 0
                ),
            )
        )
    return summaries


def decode_detail(outcome: MergeOutcome) -> str:
    """The type-specific remainder, formatted for display."""
    return orjson.dumps(outcome.detail, option=orjson.OPT_INDENT_2).decode()
