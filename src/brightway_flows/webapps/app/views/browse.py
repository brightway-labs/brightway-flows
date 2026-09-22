"""`/browse/`: every section, for a reader with no Browse panel.

The panel in the top bar is a script's addition; without `app.js`, Browse and
the mobile menu icon are links here, so no section is reachable only through
something a script opens.  Same two groups, same order and wording as the
panel, with each section's blurb in place of the panel's one-line summary.
"""

from __future__ import annotations

from flask import Blueprint, render_template

from brightway_flows.webapps.app.sections import SECTIONS

blueprint = Blueprint("browse", __name__, url_prefix="/browse")


@blueprint.route("/")
def index():
    return render_template(
        "browse.html",
        records=[section for section in SECTIONS if section.group == "browse"],
        tools=[section for section in SECTIONS if section.group == "build"],
    )
