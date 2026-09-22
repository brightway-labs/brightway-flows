"""The two counts the Browse panel puts in front of its descriptions.

Read on every page, since the panel is in every page's markup, so it is two
`SELECT count(*)` and nothing more.  No Flask import, like the other query
modules.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from brightway_flows.webapps.app.db import count, table_exists


@dataclass(frozen=True)
class BrowseCounts:
    """`None` where this database cannot answer; the panel then shows no count.

    `elementary_flows` counts the current flows only: a deprecated flow is
    still a page, but it is not one of the flows the list publishes.
    """

    elementary_flows: int | None = None
    flow_objects: int | None = None

    def by_section(self) -> dict[str, int | None]:
        """Keyed by `Section.key`, which is how the template looks them up."""
        return {"flows": self.elementary_flows, "substances": self.flow_objects}


def load_counts(connection: sqlite3.Connection) -> BrowseCounts:
    elementary_flows = None
    if table_exists(connection, "elementary_flows"):
        # The same condition as the flows page's default filter, so the panel
        # and the page it links to agree.
        elementary_flows = int(connection.execute(
            "SELECT count(*) FROM elementary_flows WHERE is_deprecated = 0"
        ).fetchone()[0])
    return BrowseCounts(
        elementary_flows=elementary_flows,
        flow_objects=count(connection, "flow_objects"),
    )
