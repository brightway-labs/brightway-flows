#!/usr/bin/env python
"""Shortlist the names that reach one substance and name a second one.

The merge places a source row by whatever evidence it has -- a correspondence
table, a registry number, a curated override -- and none of those puts the row's
*name* on the flow object it lands on.  So a name can be what one list calls a
substance and still be reachable nowhere.  The next list that ships that string
finds nothing, mints the substance again, and the same quantity is published
twice under two ids.

#74 is that failure with 394 BAFU datasets behind it, and it asked for a check
because it is unlikely to be the only one.  This is the check.  It reads a
finished build and reports every name that is both unreachable where it belongs
and already the published name of some other object -- so every split that has
happened, not every one that could.

    tools/build_unreachable_name_shortlist.py [--database PATH] [--output PATH]
                                              [--run-id ID]

Defaults read `consensus-flows.sqlite3` from the platform data directory and
write `docs/reference/unreachable-name-shortlist.json`.

It shortlists; it does not decide.  Two objects with one name are sometimes two
substances, and `brightway_flows.curation.unreachable_names` says which
pairs it drops for that reason and on what evidence.  What it cannot drop is a
pair that is genuinely two things and carries no evidence saying so, so a reader
still has to read.  Fixing one row means a curated entry that gives the name
somewhere to land -- a synonym in the list's manual fixes, as `COD, Chemical
Oxygen Demand` and `Energy, gross calorific value, in biomass` have -- or a
ruling that the two really are two.
"""

from __future__ import annotations

import argparse
import json
import sys

from pathlib import Path

from brightway_flows.curation.unreachable_names import unreachable_names
from brightway_flows.filesystem import CONSENSUS_DB_FILEPATH
from brightway_flows.merge.store import latest_run_id

DEFAULT_OUTPUT = (
    Path(__file__).resolve().parent.parent
    / "docs" / "reference" / "unreachable-name-shortlist.json"
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--database", type=Path, default=CONSENSUS_DB_FILEPATH)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--run-id",
        default=None,
        help="Merge run to read; the most recent one by default.",
    )
    args = parser.parse_args(argv)

    if not args.database.exists():
        print(f"No database at {args.database}", file=sys.stderr)
        return 1

    run = args.run_id or latest_run_id(args.database)
    if run is None:
        print(f"{args.database} records no merge run", file=sys.stderr)
        return 1

    findings = unreachable_names(args.database, run_id=run)
    payload = {
        "schema_version": 1,
        "description": (
            "Names that were placed on a flow object which does not publish "
            "them, and that are also some other flow object's own published "
            "name -- so the same string reaches one substance and names a "
            "second. Built by tools/build_unreachable_name_shortlist.py from "
            f"merge run {run}. A shortlist for a curator, not a ruling: see "
            "brightway_flows.curation.unreachable_names for what it drops "
            "and why."
        ),
        "run_id": run,
        "count": len(findings),
        "names": [finding.to_dict() for finding in findings],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")

    rows = sum(finding.row_count for finding in findings)
    print(f"{len(findings)} name(s) over {rows} source row(s) -> {args.output}")
    for finding in findings[:20]:
        print(
            f"  {finding.row_count:>3}  {finding.name}"
            f"  -> reaches {', '.join(finding.placed_on)}"
            f" ({', '.join(finding.placed_on_labels)});"
            f" names {', '.join(finding.names)}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
