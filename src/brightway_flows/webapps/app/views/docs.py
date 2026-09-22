"""`/docs`: the project documentation, in the application that needs it.

One route for the whole tree. A page and a file beside it are the same URL
shape -- `docs/concepts/contexts.md` is `/docs/concepts/contexts`, and a data
file a page links to, `docs/reference/preferred-label-worklist.json`, keeps its
own name -- so a link written for GitHub keeps working after the rewriting in
`documentation`, and a second route cannot disagree with the first about what
is inside the tree.
"""

from __future__ import annotations

from pathlib import Path

from flask import Blueprint, abort, current_app, render_template, send_from_directory

from brightway_flows.webapps.app import documentation

blueprint = Blueprint("docs", __name__, url_prefix="/docs")


def _root() -> Path:
    """Where this application instance reads the documentation from.

    On the config rather than imported, like the database path: a test points
    an app at a fixture tree without touching the environment.
    """
    return Path(current_app.config["CONSENSUS_DOCS_PATH"])


@blueprint.route("/")
@blueprint.route("/<path:page>")
def page(page: str = ""):
    """One page of documentation, or a file it refers to.

    A tree that is not there is a page naming where it looked, not a 500: the
    package installs without `docs/`, and "this checkout has no documentation"
    is a thing a reader can act on.
    """
    root = _root()
    if not root.is_dir():
        return render_template("no_documentation.html", docs_path=str(root))

    found = documentation.resolve(root, page)
    if found is None:
        abort(404)
    kind, path = found
    if kind == "asset":
        resolved = root.resolve()
        return send_from_directory(resolved, path.relative_to(resolved).as_posix())

    sections = documentation.navigation(root)
    known_titles = {
        link.slug: link.title for section in sections for link in section.pages
    }
    document = documentation.load_page(root, page, known_titles=known_titles)
    if document is None:
        abort(404)
    previous_page, next_page = documentation.neighbours(sections, document.slug)
    return render_template(
        "documentation.html",
        page=document,
        sections=sections,
        group=documentation.group_of(sections, document.slug),
        previous_page=previous_page,
        next_page=next_page,
    )
