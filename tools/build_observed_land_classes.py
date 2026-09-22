"""Write `tests/data/observed-land-classes.json`: every land class the lists ship.

`domain/land_use.py` claims its axes were read off the data rather than invented.
This is the reading.  It decomposes every land-class string EF 3.1, ecoinvent
3.8-3.12 and BAFU 2026 v1 ship into a :class:`~brightway_flows.domain.land_use.LandUse`
and reports what is left over -- a token no axis claims is a token the dataclass
would have to keep as a string, and the count of those is the measure of whether
the axes are the right ones.

The output is a fixture rather than package data, and the distinction matters.
It is *evidence for* the dataclass, not an input to it: nothing in
`src/` reads it, and `tests/test_land_use_dataclass.py` fails if a class this
file lists stops being constructible.  The curated assignment of a source flow
to a land class is a different file for a different stage --
`data/land-flow-classes.json`, one row per `(source, uuid)`, reviewed and
frozen.  See `plans/land-class-taxonomy.md` §3.8.

**The parser here is a build-time aid and must never become a run-time rule.**
It gets a curator to 152 of 153 strings; it does not get to decide, unsupervised,
that `heterogeneous, agricultural` is `agriculture, mosaic`.  That is the same
discipline `tools/build_water_flow_materials.py` follows, and for the same
reason: no algorithm reads `Water, salt, sole` and knows it is brine.

Usage::

    uv run python tools/build_observed_land_classes.py
"""

from __future__ import annotations

import argparse
import collections
import json
import sys
from pathlib import Path
from typing import Any

# `tools/` on the path, so `land_class_parser` imports whether this is run as
# `tools/build_observed_land_classes.py` or from the repository root.
sys.path.insert(0, str(Path(__file__).resolve().parent))

# The decomposition tables live beside this tool rather than in it: the
# assignment file `build_land_flow_classes.py` writes has to read a name the
# same way this evidence does, and a second copy of a 150-row table is how two
# readings of one name diverge.
from land_class_parser import (  # noqa: E402
    VOLUME_PREFIX,
    parse,
    strip_direction,
    without_geography,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
OUTPUT_PATH = REPO_ROOT / "tests" / "data" / "observed-land-classes.json"
VENDOR_DIR = Path.home() / ".local" / "share" / "brightway-flows"

ECOINVENT_VERSIONS = ("3.8", "3.9.1", "3.10.1", "3.11", "3.12")

def source_names() -> tuple[dict[str, set[str]], int]:
    """Every land-flow name each registered list ships, and how many were split.

    A non-zero split count means the vendor files on disk predate #290.  Said
    out loud by :func:`main` rather than swallowed, because it tells a curator
    their download is older than their checkout.
    """
    names: dict[str, set[str]] = collections.defaultdict(set)
    split_here = 0

    ef = json.loads((VENDOR_DIR / "ef-31-flows.json").read_bytes())
    for flow in ef:
        if "Land use" in " ".join(flow["context"]):
            names["EF 3.1"].add(flow["name"])

    for version in ECOINVENT_VERSIONS:
        path = VENDOR_DIR / f"ecoinvent-biosphere-flows-{version}.json"
        for flow in json.loads(path.read_bytes()):
            if flow["name"].lower().startswith(("occupation", "transformation")):
                names[f"ecoinvent {version}"].add(flow["name"])

    bafu = json.loads((VENDOR_DIR / "bafu-2026-v1.json").read_bytes())
    for flow in bafu:
        if not flow["name"].lower().startswith(("occupation", "transformation")):
            continue
        base, place = without_geography(flow["name"])
        split_here += place is not None
        names["BAFU 2026 v1"].add(base)

    # Stepwise 2006 is an LCIA method file rather than a flow list, and its
    # land rows are whatever its `Nature occupation` category characterises.
    # They are here for the same reason the other four lists are: the axes are
    # only right if they read every land name a merged list ships, and thirteen
    # of Stepwise's they cannot -- which is what `unparsed` is for.
    stepwise = json.loads((VENDOR_DIR / "stepwise-2006-1.09.json").read_bytes())
    for flow in stepwise:
        if flow["name"].lower().startswith(("occupation", "transformation")):
            names["Stepwise 2006"].add(flow["name"])

    # AGRIBALYSE writes a country onto four of its land names the way BAFU
    # does, so its names are split the same way BAFU's are.
    agribalyse = json.loads((VENDOR_DIR / "agribalyse-3.2.json").read_bytes())
    for flow in agribalyse:
        if not flow["name"].lower().startswith(("occupation", "transformation")):
            continue
        base, place = without_geography(flow["name"])
        split_here += place is not None
        names["AGRIBALYSE 3.2"].add(base)

    return names, split_here


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="fail instead of writing if the output would change",
    )
    args = parser.parse_args()

    by_list, split_here = source_names()
    seen: dict[str, dict[str, Any]] = {}
    unparsed: list[dict[str, Any]] = []
    for source, names in sorted(by_list.items()):
        for name in sorted(names):
            direction, land_class = strip_direction(name)
            if land_class.startswith(VOLUME_PREFIX):
                continue
            land_use, residue = parse(direction, land_class)
            if land_use is None:
                unparsed.append({"source": source, "name": name, "residue": residue})
                continue
            record = seen.setdefault(
                land_use.key,
                {"key": land_use.key, "label": land_use.label, **land_use.to_dict(),
                 "spellings": []},
            )
            record["spellings"].append({"source": source, "name": name})

    payload = {
        "schema_version": 1,
        "description": (
            "Every land class EF 3.1, ecoinvent 3.8-3.12, BAFU 2026 v1 and "
            "Stepwise 2006 ship, "
            "decomposed into the axes of domain/land_use.py. Evidence for the "
            "dataclass, not an input to it: nothing in src/ reads this file. "
            "Generated by tools/build_observed_land_classes.py -- the spellings "
            "are the vendors', and the axes are ours. `unparsed` is the measure "
            "of whether the axes are right. It is empty for the four lists that "
            "publish flows and holds thirteen rows of Stepwise 2006, every one "
            "of them naming the state the land was in before -- `sealed, on "
            "grassland`, `forest, on arable land`, `accelerated "
            "denaturalisation, primary forest to intensive forest` -- which no "
            "axis here has a word for."
        ),
        "land_classes": [seen[key] for key in sorted(seen)],
        "unparsed": unparsed,
    }
    rendered = json.dumps(payload, indent=2, sort_keys=False) + "\n"

    if args.check:
        current = OUTPUT_PATH.read_text() if OUTPUT_PATH.exists() else ""
        if current != rendered:
            print(f"{OUTPUT_PATH} is out of date; re-run without --check")
            return 1
        print(f"{OUTPUT_PATH} is up to date")
        return 0

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(rendered)
    directions = collections.Counter(
        record["direction"] for record in payload["land_classes"]
    )
    print(f"{len(payload['land_classes'])} land classes -> {OUTPUT_PATH}")
    print(f"  by direction: {dict(directions)}")
    if split_here:
        print(
            f"  note: {split_here} BAFU names still carried a place, so the "
            "vendor file on disk predates #290 -- split here instead"
        )
    print(f"  unparsed: {len(unparsed)}")
    for row in unparsed:
        print(f"    {row['source']:16} {row['name']!r} -> {row['residue']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
