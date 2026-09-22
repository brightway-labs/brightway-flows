"""`/about/`: who builds the list, how it is governed, and how to reach them.

`plans/public-site.md` §3.  Copy as on the About board.  Every fact the board
draws as an amber chip -- maintainers, governance, the licences, the
address, the email, the log retention period -- comes from `publication.py`
through `placeholder` in the template, so this view has nothing to read.
"""

from __future__ import annotations

from flask import Blueprint, render_template

blueprint = Blueprint("about", __name__, url_prefix="/about")


@blueprint.route("/")
def index():
    return render_template("about.html")
