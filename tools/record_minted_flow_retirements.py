"""Record what a build published for the flows the merge mints, before renaming them.

#102 changed how a minted flow is named: from the source row that reached the
compartment first to the substance and the compartment.  That renames every
minted flow at once, and the old names cannot be worked out afterwards -- doing
so would mean keeping the rule that made them move.  So they are read off the
build that published them, once, into
``src/brightway_flows/data/retired-minted-flow-ids.json``, which
`pipeline/redirects.py` publishes a redirect from.

    uv run python tools/record_minted_flow_retirements.py \\
        --database ~/.local/share/brightway-flows/consensus-flows.sqlite3

The database has to be a build made **before** the rename -- otherwise every
identifier in it is already the new one and the file records nothing.  That is
not assumed: a flow already named the way this project now names it is skipped
and counted, and a run in which every flow is skipped says so and writes
nothing.

What it records is what *that* build published.  A build merging a different set
of source lists minted a different set of flows, and named them from its own
rows; those identifiers are not recoverable from here either, and the file says
which build it came from so a reader knows what it covers.
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from contextlib import closing
from pathlib import Path

import orjson

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from brightway_flows.domain.elementary_flow import (  # noqa: E402
    minted_elementary_flow_id,
)
from brightway_flows.pipeline.redirects import (  # noqa: E402
    RETIREMENTS_FILEPATH,
    RETIREMENTS_SCHEMA_VERSION,
)
from brightway_flows.sources import known_source_lists  # noqa: E402


def _minted_sources() -> list[str]:
    return sorted({
        source
        for entry in known_source_lists().values()
        for source in entry.addition_sources
    })


def _provenance(connection: sqlite3.Connection) -> dict[str, object]:
    """Which build this came from, as far as it can say.

    `pipeline_runs` carries the revision since #101.  A build that does not say
    is still usable -- the identifiers in it are what they are -- so a missing
    stamp is recorded as absent rather than refused.
    """
    out: dict[str, object] = {}
    columns = {
        row[1]
        for row in connection.execute("PRAGMA table_info(pipeline_runs)")
    }
    for column, key in (("git_commit", "commit"), ("run_id", "run_id")):
        if column in columns:
            row = connection.execute(
                f"SELECT {column} FROM pipeline_runs ORDER BY rowid DESC LIMIT 1"
            ).fetchone()
            if row and row[0]:
                out[key] = str(row[0])
    try:
        out["merged"] = [
            f"{name} {version}"
            for name, version in connection.execute(
                "SELECT DISTINCT list_name, list_version FROM merge_run_inputs "
                "ORDER BY list_name, list_version"
            )
        ]
    except sqlite3.OperationalError:
        out["merged"] = []
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--database", type=Path, required=True,
        help="The build to read the published identifiers out of.",
    )
    parser.add_argument(
        "--output", type=Path, default=RETIREMENTS_FILEPATH,
        help="Where to write. Defaults to the bundled data file.",
    )
    args = parser.parse_args()

    sources = _minted_sources()
    placeholders = ", ".join("?" * len(sources))
    with closing(sqlite3.connect(f"file:{args.database}?mode=ro", uri=True)) as db:
        provenance = _provenance(db)
        rows = list(db.execute(
            f"SELECT uuid, flow_object_id, context_iri, pref_label_value "
            f"FROM elementary_flows WHERE source IN ({placeholders}) "
            f"ORDER BY uuid",
            sources,
        ))

    retirements = []
    already_named = 0
    for identifier, object_id, context_iri, name in rows:
        replaced_by = minted_elementary_flow_id(
            str(object_id or ""), str(context_iri or "")
        )
        if str(identifier) == replaced_by:
            already_named += 1
            continue
        retirements.append({
            "identifier": str(identifier),
            "replaced_by": replaced_by,
            "flow_object_id": str(object_id or ""),
            "context_iri": str(context_iri or ""),
            "name": str(name or ""),
        })

    print(f"minted flows in {args.database}: {len(rows)}")
    print(f"  already named from the flow: {already_named}")
    print(f"  retired here:                {len(retirements)}")
    if not retirements:
        print("Nothing to record; this build already names its minted flows "
              "the way this project does. Not writing.")
        return 1

    payload = {
        "schema_version": RETIREMENTS_SCHEMA_VERSION,
        "description": (
            "Identifiers this project published for flows the merge mints, "
            "before #102 made a minted identifier a function of the substance "
            "and the compartment rather than of whichever source row reached "
            "the compartment first. One entry per flow that was renamed; the "
            "export publishes a redirect from each to the flow it named, so an "
            "identifier a consumer pinned still resolves. Generated by "
            "tools/record_minted_flow_retirements.py; do not hand-edit -- the "
            "loader recomputes every replacement from the substance and the "
            "context and refuses the file if one disagrees."
        ),
        "recorded_from": provenance,
        "retirements": retirements,
    }
    args.output.write_bytes(orjson.dumps(payload, option=orjson.OPT_INDENT_2))
    print(f"wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
