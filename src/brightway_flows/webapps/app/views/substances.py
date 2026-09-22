"""`/flow-objects`, its detail page, and the structure diagram."""

from __future__ import annotations

from flask import (
    Blueprint,
    Response,
    abort,
    redirect,
    render_template,
    request,
    url_for,
)

from brightway_flows.webapps.app import db
from brightway_flows.webapps.app.queries import substances as queries
from brightway_flows.webapps.app.queries.common import RANDOM_PAGE

#: The endpoints keep the name `substances` while the URL does not.  A reader
#: is looking at a substance, which is why the pages read the way they do; the
#: address bar and the navigation say "flow object", which is what the data
#: model calls the record and what every other page links to it as.  Renaming
#: the endpoint too would rewrite `url_for` in a dozen templates and change
#: nothing anybody sees.
blueprint = Blueprint("substances", __name__, url_prefix="/flow-objects")


@blueprint.route("/")
def index():
    if not db.database_exists():
        return render_template("no_database.html")
    connection = db.get_connection()
    # Nothing asked for at all: open somewhere in the middle.  See the same
    # decision, and the reason for it, in `views.flows.index`.
    landing = not request.args
    return render_template(
        "substances.html",
        landed_at_random=landing,
        page=queries.substance_page(
            connection,
            query=request.args.get("q", "").strip(),
            name_only=request.args.get("name_only") == "1",
            flow_type=request.args.get("type", "").strip(),
            origin_qualifier=request.args.get("qualifier", "").strip(),
            origin_source=request.args.get("origin", "").strip(),
            sort=request.args.get("sort", ""),
            page=(
                RANDOM_PAGE if landing
                else request.args.get("page", 1, type=int)
            ),
        ),
        type_options=queries.substance_type_options(connection),
        qualifier_options=queries.substance_qualifier_options(connection),
        origin_options=queries.substance_origin_options(connection),
        query=request.args.get("q", "").strip(),
        name_only=request.args.get("name_only") == "1",
        flow_type=request.args.get("type", "").strip(),
        origin_qualifier=request.args.get("qualifier", "").strip(),
        origin_source=request.args.get("origin", "").strip(),
        sort=request.args.get("sort", ""),
    )


@blueprint.route("/<path:flow_object_id>/structure.svg")
def structure(flow_object_id: str):
    """The substance drawn from its SMILES, or 404.

    RDKit is imported inside the view, not at module scope. It is the heaviest
    import in the project, and a page that never asks for a diagram should not
    pay for it -- which is also why this is a separate request rather than an
    inline data URI.
    """
    if not db.database_exists():
        abort(404)
    substance = queries.substance_detail(db.get_connection(), flow_object_id)
    if substance is None or not substance.has_structure:
        abort(404)

    from brightway_flows.chem import mol_from_smiles, structure_svg

    # Each candidate in turn: a substance whose structure is not settled
    # carries several, and the first is not reliably the parseable one.
    for smiles in substance.smiles_candidates:
        mol = mol_from_smiles(smiles)
        if mol is None:
            continue
        svg = structure_svg(mol, width=400, height=260)
        if svg:
            return Response(svg, mimetype="image/svg+xml")
    abort(404)


@blueprint.route("/<path:flow_object_id>")
def detail(flow_object_id: str):
    if not db.database_exists():
        return render_template("no_database.html")
    substance = queries.substance_detail(db.get_connection(), flow_object_id)
    if substance is None:
        abort(404)
    return render_template("substance_detail.html", substance=substance)


#: Where these pages used to live.
#:
#: `/substances` was the consensus app's word for a flow object.  The
#: navigation stopped using it when the sections were named, and the address
#: bar was the last place it survived.  The old paths redirect rather than
#: 404: this app is linked to from issues, from `docs/`, and from whatever a
#: curator bookmarked, and none of those get to be rewritten by a rename.
#:
#: All four are here, including the one whose page lives in `views.changes`,
#: because what they have in common is the prefix they are moving off -- and
#: a reader asking "is the old URL still answered?" should find one list.
#:
#: The view names are prefixed because this module already defines `index`,
#: `detail` and `structure` for the pages themselves, and a second
#: definition would shadow the first at module scope.
legacy_blueprint = Blueprint(
    "substances_legacy", __name__, url_prefix="/substances"
)


def _moved(endpoint: str, **values: str) -> Response:
    """A permanent redirect to *endpoint*, carrying the query string over.

    The filters on the list page are query parameters, so a redirect that
    dropped them would answer a different question from the one that was
    asked.
    """
    target = url_for(endpoint, **values)
    query = request.query_string.decode()
    return redirect(f"{target}?{query}" if query else target, code=301)


@legacy_blueprint.route("/")
def legacy_index():
    return _moved("substances.index")


@legacy_blueprint.route("/<path:flow_object_id>/structure.svg")
def legacy_structure(flow_object_id: str):
    return _moved("substances.structure", flow_object_id=flow_object_id)


@legacy_blueprint.route("/<path:flow_object_id>/changes")
def legacy_changes(flow_object_id: str):
    return _moved("changes.substance", flow_object_id=flow_object_id)


@legacy_blueprint.route("/<path:flow_object_id>")
def legacy_detail(flow_object_id: str):
    return _moved("substances.detail", flow_object_id=flow_object_id)
