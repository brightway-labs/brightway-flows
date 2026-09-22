"""`/factors`: what each implementation of a method says, and where they differ.

The queue under `/queue` is a backlog to drain. This section is the opposite —
the layer as it stands, for a reader asking what this list says a substance is
worth and how that compares to what the publishers say.

Six pages, and the split is by question rather than by table:

* the index, a section per characterised method and a row per category;
* `/factors/category/<method>/<version>/<slug>`, one category opened: every
  factor published under it, as many implementations wide as there are;
* `…/<slug>/differences`, that category narrowed to two of its implementations
  and the rows they disagree about;
* `/factors/differences`, the difference report sorted by ratio;
* `/factors/coverage`, where one implementation skips a context of a substance
  it characterises;
* `/factors/findings/<kind>`, mirroring `/checks` — the things `characterise`
  found and did not silently resolve.

Every one of them renders `factors_unavailable.html` where `characterise` has
not run, rather than a page of zeros: "nobody has asked yet" is a different
statement from "there is nothing there".

Nothing here names a method or an implementation. EF 3.1 is what is loaded
today and it is not what will be loaded; the pages take their sections, their
columns and their labels from the rows the run wrote.
"""

from __future__ import annotations

from flask import Blueprint, abort, render_template, request

from brightway_flows.webapps.app import db
from brightway_flows.webapps.app.queries import factors as queries

blueprint = Blueprint("factors", __name__, url_prefix="/factors")


def _unavailable() -> str | None:
    """The page to render instead, or ``None`` if there is something to show."""
    if not db.database_exists():
        return render_template("no_database.html")
    if not db.table_exists(db.get_connection(), "lcia_impact_categories"):
        return render_template("factors_unavailable.html")
    return None


@blueprint.route("/")
def index():
    if unavailable := _unavailable():
        return unavailable
    connection = db.get_connection()
    return render_template(
        "factors.html",
        overview=queries.overview(connection),
        # The four groups rather than the seven bands: a summary is asked which
        # side of the tolerance a row falls on, and the report states the exact
        # ratio for the reader who wants more.
        bands=queries.band_groups(connection),
        compared=queries.compared_implementations(connection),
        findings=queries.findings_index(connection),
    )


@blueprint.route("/category/<method>/<version>/<slug>")
def category(method: str, version: str, slug: str):
    """One impact category, and every factor published under it.

    Addressed the way the category's own IRI addresses it -- method, version,
    slug -- because that is what identifies it. A route keyed on the name alone
    would be a route that stops working the day a second method publishes a
    `Climate change`.
    """
    if unavailable := _unavailable():
        return unavailable
    connection = db.get_connection()
    detail = queries.category(
        connection, method=method, version=version, slug=slug
    )
    if detail is None:
        abort(404)
    query = request.args.get("q", "").strip()
    sort = request.args.get("sort", "")
    return render_template(
        "factor_category.html",
        detail=detail,
        query=query,
        sort=sort,
        # The three that address the category travel with every pager and sort
        # link, because they are path segments rather than query parameters and
        # `url_for` cannot build the route without them.
        args={
            "method": method,
            "version": version,
            "slug": slug,
            **{key: value for key, value in (("q", query), ("sort", sort)) if value},
        },
        page=queries.category_factors(
            connection, detail, query=query, sort=sort,
            page=request.args.get("page", 1, type=int),
        ),
    )


def _pair(detail, arguments) -> tuple[str, str]:
    """The two implementations to compare, from the query string or by default.

    A slug this category has no implementation for is a 404 rather than a silent
    fallback: a stale or hand-edited URL that quietly compares two other
    implementations is a page answering a question nobody asked. One side alone
    is filled from the other end of the default pair, so a link naming a single
    implementation still opens on a comparison.
    """
    requested = [arguments.get(side, "").strip() for side in ("left", "right")]
    if not any(requested):
        return queries.default_pair(detail) or ("", "")
    chosen = [detail.named(slug) if slug else "" for slug in requested]
    if any(slug and not name for slug, name in zip(requested, chosen, strict=True)):
        abort(404)
    for index, name in enumerate(chosen):
        if not name:
            chosen[index] = next(
                (
                    candidate
                    for candidate in detail.implementations
                    if candidate != chosen[1 - index]
                    and detail.counts[candidate].factors
                ),
                "",
            )
    return chosen[0], chosen[1]


@blueprint.route("/category/<method>/<version>/<slug>/differences")
def category_differences(method: str, version: str, slug: str):
    """One category, narrowed to two of its implementations.

    A subpage of the category rather than a filter on `/factors/differences`,
    because it answers a different question. The report ranks a method's widest
    disagreements wherever they are; this is opened with a category already in
    mind -- "what do these two say about climate change" -- and its band is the
    pair's own, not the widest among everybody who states the row.
    """
    if unavailable := _unavailable():
        return unavailable
    connection = db.get_connection()
    detail = queries.category(
        connection, method=method, version=version, slug=slug
    )
    if detail is None:
        abort(404)
    left, right = _pair(detail, request.args)
    query = request.args.get("q", "").strip()
    band = request.args.get("band", "").strip()
    sort = request.args.get("sort", "")
    page, comparison = queries.pair_differences(
        connection, detail, left=left, right=right, band=band, query=query,
        sort=sort, page=request.args.get("page", 1, type=int),
    )
    return render_template(
        "factor_category_differences.html",
        detail=detail,
        comparison=comparison,
        query=query,
        band=band,
        sort=sort,
        # The pair travels with every pager, sort and filter link: dropping it
        # would send a reader paging through a comparison they did not choose.
        args={
            "method": method,
            "version": version,
            "slug": slug,
            **{
                key: value
                for key, value in (
                    ("left", detail.slugs.get(left, "")),
                    ("right", detail.slugs.get(right, "")),
                    ("band", band),
                    ("q", query),
                    ("sort", sort),
                )
                if value
            },
        },
        page=page,
    )


@blueprint.route("/differences")
def differences():
    if unavailable := _unavailable():
        return unavailable
    connection = db.get_connection()
    query = request.args.get("q", "").strip()
    band = request.args.get("band", "").strip()
    sort = request.args.get("sort", "")
    page, implementations = queries.differences(
        connection, query=query, band=band, sort=sort,
        page=request.args.get("page", 1, type=int),
    )
    return render_template(
        "factor_differences.html",
        query=query,
        band=band,
        sort=sort,
        args={key: value for key, value in
              (("q", query), ("band", band), ("sort", sort)) if value},
        bands=queries.band_groups(connection),
        implementations=implementations,
        page=page,
    )


@blueprint.route("/coverage")
def coverage():
    if unavailable := _unavailable():
        return unavailable
    connection = db.get_connection()
    return render_template(
        "factor_coverage.html",
        coverage=queries.coverage(connection),
        # The run's own counts, not the whole overview: this page needs the stats
        # blob and nothing else, and reading it through `overview` cost 519 ms of
        # counting factors to render 83 rows.
        stats=queries.run_stats(connection),
    )


@blueprint.route("/findings/<kind>")
def findings(kind: str):
    if unavailable := _unavailable():
        return unavailable
    definition = next(
        (row for row in queries.findings_index(db.get_connection())
         if row.kind == kind),
        None,
    )
    if definition is None:
        abort(404)
    connection = db.get_connection()
    query = request.args.get("q", "").strip()
    sort = request.args.get("sort", "")
    # Only a collision is two things, so only a collision gets the control that
    # says which. The other kinds are handed an empty list and render none.
    sources = (
        queries.collision_sources(connection)
        if definition.layout == "collision"
        else []
    )
    source = request.args.get("source", "").strip() if sources else ""
    return render_template(
        "factor_findings.html",
        definition=definition,
        query=query,
        sort=sort,
        sources=sources,
        source=source or (sources[0][0] if sources else ""),
        args={
            key: value
            for key, value in (("q", query), ("sort", sort), ("source", source))
            if value
        },
        page=queries.findings(
            connection, kind=kind, query=query, sources=source, sort=sort,
            page=request.args.get("page", 1, type=int),
        ),
    )
