"""Reads for `/scores`: a release's datasets scored two ways, and what moved.

Pure functions, a connection in and dataclasses out, so the views stay Flask
and the reads are tested without one.  Three questions, three shapes:

* the index -- per release, the table the hand analysis drew for one
  activity, drawn for the whole sample: each category, how many datasets
  agree, how many are within 2x, and the median of ours over theirs;
* a category -- the vendor's flows ranked by how much of that category's total
  they move, with the reason;
* a dataset -- every category both ways, and under one of them every flow.

Nothing here names a release or a method.  What is on the pages comes from
the rows `compare-scores` wrote, and a third release is a third card.
"""

from __future__ import annotations

import sqlite3
import statistics
from dataclasses import dataclass, field
from typing import Any

from brightway_flows.domain.lcia.records import Band
from brightway_flows.webapps.app.db import table_exists
from brightway_flows.webapps.app.queries.common import PAGE_SIZE, Page, load_json, resolve_page

#: The bands, grouped the way a summary is asked: which side of the 2% line,
#: then how far.
AGREE = (str(Band.IDENTICAL), str(Band.WITHIN_TOLERANCE))
CLOSE = (str(Band.UP_TO_2X),)
FAR = (str(Band.UP_TO_10X),)
WORSE = (str(Band.UP_TO_100X), str(Band.OVER_100X))


@dataclass(frozen=True)
class ScoreRun:
    run_id: str
    started_at: str
    finished_at: str | None
    build_run_id: str | None
    lcia_run_id: str | None
    stats: dict[str, Any]


@dataclass(frozen=True)
class CategoryRow:
    """One vendor category of one release, over every dataset."""

    key: str
    name: str
    unit: str
    slug: str | None
    datasets: int
    agree: int
    close: int
    far: int
    worse: int
    incomparable: int
    median_ratio: float | None

    @property
    def unmatched(self) -> bool:
        return self.slug is None


@dataclass(frozen=True)
class ReleaseCard:
    key: str
    list_name: str
    list_version: str
    system_model: str
    method_family: str
    unit_processes: int
    created_at: str
    generator: dict[str, str]
    stats: dict[str, Any]
    categories: list[CategoryRow] = field(default_factory=list)


@dataclass(frozen=True)
class PriorityRow:
    source_flow_uuid: str
    source_flow_name: str
    elementary_flow_uuid: str | None
    flow_name: str | None
    context_display: str | None
    reason: str
    datasets_affected: int
    abs_delta_sum: float
    share_of_category: float
    max_share: float


@dataclass(frozen=True)
class CategoryDetail:
    release: ReleaseCard
    category: CategoryRow
    unit: str
    reasons: list[tuple[str, int]]


@dataclass(frozen=True)
class DatasetScore:
    category_key: str
    category: str
    unit: str
    slug: str | None
    their_score: float
    our_score: float
    signed_ratio: float | None
    band: str
    unmapped_share: float


@dataclass(frozen=True)
class ContributionRow:
    source_flow_uuid: str
    source_flow_name: str
    elementary_flow_uuid: str | None
    flow_name: str | None
    amount: float
    multiplier: float | None
    their_factor: float | None
    our_factor: float | None
    their_contribution: float
    our_contribution: float
    delta: float
    reason: str


@dataclass(frozen=True)
class DatasetDetail:
    release: ReleaseCard
    activity_code: str
    activity_uuid: str
    name: str
    reference_product: str
    product_amount: float
    product_unit: str
    geography: str
    classifications: dict[str, str]
    inventory_lines: int
    mapped_lines: int
    unmapped_lines: int
    scores: list[DatasetScore]


def available(connection: sqlite3.Connection) -> bool:
    return table_exists(connection, "score_runs")


def run(connection: sqlite3.Connection) -> ScoreRun | None:
    row = connection.execute(
        "SELECT run_id, started_at, finished_at, build_run_id, lcia_run_id, stats_json "
        "FROM score_runs ORDER BY started_at DESC LIMIT 1"
    ).fetchone()
    if row is None:
        return None
    return ScoreRun(
        run_id=str(row["run_id"]),
        started_at=str(row["started_at"]),
        finished_at=row["finished_at"],
        build_run_id=row["build_run_id"],
        lcia_run_id=row["lcia_run_id"],
        stats=load_json(row["stats_json"], {}),
    )


def _release(row: sqlite3.Row) -> ReleaseCard:
    return ReleaseCard(
        key=str(row["release_key"]),
        list_name=str(row["list_name"]),
        list_version=str(row["list_version"]),
        system_model=str(row["system_model"]),
        method_family=str(row["method_family"]),
        unit_processes=int(row["unit_processes"]),
        created_at=str(row["created_at"]),
        generator=load_json(row["generator_json"], {}),
        stats=load_json(row["stats_json"], {}),
    )


def _category_rows(connection: sqlite3.Connection, release_key: str) -> list[CategoryRow]:
    """The #209 table: one row per vendor category, counts by band."""
    categories = connection.execute(
        "SELECT category_key, category, unit, category_slug FROM score_categories "
        "WHERE release_key = ? ORDER BY category",
        (release_key,),
    ).fetchall()
    counts: dict[str, dict[str, int]] = {}
    for row in connection.execute(
        "SELECT category_key, band, count(*) AS n FROM score_comparisons "
        "WHERE release_key = ? AND their_score != 0 GROUP BY category_key, band",
        (release_key,),
    ):
        counts.setdefault(str(row["category_key"]), {})[str(row["band"])] = int(row["n"])
    ratios: dict[str, list[float]] = {}
    for row in connection.execute(
        "SELECT category_key, signed_ratio FROM score_comparisons "
        "WHERE release_key = ? AND signed_ratio IS NOT NULL",
        (release_key,),
    ):
        ratios.setdefault(str(row["category_key"]), []).append(float(row["signed_ratio"]))
    out = []
    for row in categories:
        key = str(row["category_key"])
        by_band = counts.get(key, {})
        total = sum(by_band.values())
        out.append(
            CategoryRow(
                key=key,
                name=str(row["category"]),
                unit=str(row["unit"]),
                slug=row["category_slug"],
                datasets=total,
                agree=sum(by_band.get(b, 0) for b in AGREE),
                close=sum(by_band.get(b, 0) for b in CLOSE),
                far=sum(by_band.get(b, 0) for b in FAR),
                worse=sum(by_band.get(b, 0) for b in WORSE),
                incomparable=by_band.get(str(Band.INCOMPARABLE), 0),
                median_ratio=statistics.median(ratios[key]) if ratios.get(key) else None,
            )
        )
    return out


def releases(connection: sqlite3.Connection) -> list[ReleaseCard]:
    """Every compared release, with its category table."""
    out = []
    for row in connection.execute(
        "SELECT * FROM score_releases ORDER BY list_name, list_version, system_model"
    ):
        card = _release(row)
        out.append(
            ReleaseCard(
                **{k: getattr(card, k) for k in card.__dataclass_fields__ if k != "categories"},
                categories=_category_rows(connection, card.key),
            )
        )
    return out


def release(connection: sqlite3.Connection, key: str) -> ReleaseCard | None:
    row = connection.execute(
        "SELECT * FROM score_releases WHERE release_key = ?", (key,)
    ).fetchone()
    if row is None:
        return None
    card = _release(row)
    return ReleaseCard(
        **{k: getattr(card, k) for k in card.__dataclass_fields__ if k != "categories"},
        categories=_category_rows(connection, card.key),
    )


def category(connection: sqlite3.Connection, key: str, category_key: str) -> CategoryDetail | None:
    card = release(connection, key)
    if card is None:
        return None
    row = next((c for c in card.categories if c.key == category_key), None)
    if row is None:
        return None
    reasons = [
        (str(r["reason"]), int(r["n"]))
        for r in connection.execute(
            "SELECT reason, count(*) AS n FROM score_flow_priorities "
            "WHERE release_key = ? AND category_key = ? GROUP BY reason ORDER BY n DESC",
            (key, category_key),
        )
    ]
    return CategoryDetail(release=card, category=row, unit=row.unit, reasons=reasons)


def _flow_names(connection: sqlite3.Connection, uuids: list[str]) -> dict[str, tuple[str, str]]:
    """Consensus flow uuid -> (label, context), for the flows on a page."""
    if not uuids or not table_exists(connection, "elementary_flows"):
        return {}
    out: dict[str, tuple[str, str]] = {}
    for start in range(0, len(uuids), 500):
        chunk = uuids[start:start + 500]
        for row in connection.execute(
            "SELECT uuid, pref_label_value, context_display FROM elementary_flows "
            f"WHERE uuid IN ({','.join('?' * len(chunk))})",
            chunk,
        ):
            out[str(row["uuid"])] = (str(row["pref_label_value"] or ""), str(row["context_display"] or ""))
    return out


def _source_names(connection: sqlite3.Connection, card: ReleaseCard, uuids: list[str]) -> dict[str, str]:
    """Vendor flow uuid -> the name the vendor gave it, from the merge's record."""
    if not uuids or not table_exists(connection, "elementary_flow_sources"):
        return {}
    out: dict[str, str] = {}
    for start in range(0, len(uuids), 500):
        chunk = uuids[start:start + 500]
        for row in connection.execute(
            "SELECT source_flow_uuid, source_flow_name FROM elementary_flow_sources "
            f"WHERE list_name = ? AND list_version = ? AND source_flow_uuid IN ({','.join('?' * len(chunk))})",
            (card.list_name, card.list_version, *chunk),
        ):
            out.setdefault(str(row["source_flow_uuid"]), str(row["source_flow_name"] or ""))
    return out


def priorities(
    connection: sqlite3.Connection,
    detail: CategoryDetail,
    *,
    reason: str = "",
    page: int = 1,
) -> Page[PriorityRow]:
    """The vendor's flows under one category, ranked by share of the category."""
    where = ["release_key = ?", "category_key = ?"]
    params: list[Any] = [detail.release.key, detail.category.key]
    if reason:
        where.append("reason = ?")
        params.append(reason)
    clause = " AND ".join(where)
    total = connection.execute(
        f"SELECT count(*) FROM score_flow_priorities WHERE {clause}", params
    ).fetchone()[0]
    number = resolve_page(page, total)
    rows = connection.execute(
        f"SELECT * FROM score_flow_priorities WHERE {clause} "
        "ORDER BY share_of_category DESC, abs_delta_sum DESC, source_flow_uuid "
        "LIMIT ? OFFSET ?",
        (*params, PAGE_SIZE, (number - 1) * PAGE_SIZE),
    ).fetchall()
    names = _flow_names(connection, [r["elementary_flow_uuid"] for r in rows if r["elementary_flow_uuid"]])
    sources = _source_names(connection, detail.release, [str(r["source_flow_uuid"]) for r in rows])
    items = [
        PriorityRow(
            source_flow_uuid=str(r["source_flow_uuid"]),
            source_flow_name=sources.get(str(r["source_flow_uuid"]), ""),
            elementary_flow_uuid=r["elementary_flow_uuid"],
            flow_name=names.get(r["elementary_flow_uuid"], ("", ""))[0] if r["elementary_flow_uuid"] else None,
            context_display=names.get(r["elementary_flow_uuid"], ("", ""))[1] if r["elementary_flow_uuid"] else None,
            reason=str(r["reason"]),
            datasets_affected=int(r["datasets_affected"]),
            abs_delta_sum=float(r["abs_delta_sum"]),
            share_of_category=float(r["share_of_category"]),
            max_share=float(r["max_share"]),
        )
        for r in rows
    ]
    return Page(rows=items, total=total, number=number, size=PAGE_SIZE)


def datasets(connection: sqlite3.Connection, card: ReleaseCard, *, query: str = "", page: int = 1) -> Page[dict[str, Any]]:
    """The release's datasets, searchable by name, product and geography."""
    where = ["release_key = ?"]
    params: list[Any] = [card.key]
    if query:
        where.append("(name LIKE ? OR reference_product LIKE ? OR geography = ? OR activity_code = ?)")
        params.extend([f"%{query}%", f"%{query}%", query, query])
    clause = " AND ".join(where)
    total = connection.execute(
        f"SELECT count(*) FROM score_unit_processes WHERE {clause}", params
    ).fetchone()[0]
    number = resolve_page(page, total)
    rows = connection.execute(
        f"SELECT * FROM score_unit_processes WHERE {clause} ORDER BY name, reference_product, geography "
        "LIMIT ? OFFSET ?",
        (*params, PAGE_SIZE, (number - 1) * PAGE_SIZE),
    ).fetchall()
    return Page(rows=[dict(r) for r in rows], total=total, number=number, size=PAGE_SIZE)


def dataset(connection: sqlite3.Connection, key: str, activity_code: str) -> DatasetDetail | None:
    card = release(connection, key)
    if card is None:
        return None
    row = connection.execute(
        "SELECT * FROM score_unit_processes WHERE release_key = ? AND activity_code = ?",
        (key, activity_code),
    ).fetchone()
    if row is None:
        return None
    categories = {c.key: c for c in card.categories}
    scores = [
        DatasetScore(
            category_key=str(r["category_key"]),
            category=categories[str(r["category_key"])].name if str(r["category_key"]) in categories else str(r["category_key"]),
            unit=categories[str(r["category_key"])].unit if str(r["category_key"]) in categories else "",
            slug=categories[str(r["category_key"])].slug if str(r["category_key"]) in categories else None,
            their_score=float(r["their_score"]),
            our_score=float(r["our_score"]),
            signed_ratio=r["signed_ratio"],
            band=str(r["band"]),
            unmapped_share=float(r["unmapped_share"]),
        )
        for r in connection.execute(
            "SELECT * FROM score_comparisons WHERE release_key = ? AND activity_code = ?",
            (key, activity_code),
        )
    ]
    scores.sort(key=lambda s: s.category)
    return DatasetDetail(
        release=card,
        activity_code=str(row["activity_code"]),
        activity_uuid=str(row["activity_uuid"]),
        name=str(row["name"]),
        reference_product=str(row["reference_product"]),
        product_amount=float(row["product_amount"]),
        product_unit=str(row["product_unit"]),
        geography=str(row["geography"]),
        classifications=load_json(row["classifications_json"], {}),
        inventory_lines=int(row["inventory_lines"]),
        mapped_lines=int(row["mapped_lines"]),
        unmapped_lines=int(row["unmapped_lines"]),
        scores=scores,
    )


def contributions(
    connection: sqlite3.Connection, detail: DatasetDetail, category_key: str
) -> list[ContributionRow]:
    """Every stored contribution of one dataset under one category, largest gap first."""
    rows = connection.execute(
        "SELECT * FROM score_contributions WHERE release_key = ? AND activity_code = ? "
        "AND category_key = ? ORDER BY abs(delta) DESC, abs(their_contribution) DESC",
        (detail.release.key, detail.activity_code, category_key),
    ).fetchall()
    names = _flow_names(connection, [r["elementary_flow_uuid"] for r in rows if r["elementary_flow_uuid"]])
    sources = _source_names(connection, detail.release, [str(r["source_flow_uuid"]) for r in rows])
    return [
        ContributionRow(
            source_flow_uuid=str(r["source_flow_uuid"]),
            source_flow_name=sources.get(str(r["source_flow_uuid"]), ""),
            elementary_flow_uuid=r["elementary_flow_uuid"],
            flow_name=names.get(r["elementary_flow_uuid"], ("", ""))[0] if r["elementary_flow_uuid"] else None,
            amount=float(r["amount"]),
            multiplier=r["multiplier"],
            their_factor=r["their_factor"],
            our_factor=r["our_factor"],
            their_contribution=float(r["their_contribution"]),
            our_contribution=float(r["our_contribution"]),
            delta=float(r["delta"]),
            reason=str(r["reason"]),
        )
        for r in rows
    ]
