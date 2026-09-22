"""Write `land-flow-classes.json`: which land class each land flow is.

`plans/land-class-taxonomy.md` §3.8.  A land flow says what the land **is** --
forest, cropland, seabed -- and how it is **used** -- irrigated, intensive,
clear-cut -- and until `domain/land_use.py` the list had a field for neither, so
both lived in a comma-separated name that three source lists spell three ways.
This file is where a name stops being the only place a land class lives.

The same shape as `water-flow-materials.json`, and for the same reason.  The
layering could read a flow's name at run time and split it on commas; that is
exactly what these files exist to avoid.  `heterogeneous, agricultural` is
`agriculture, mosaic` because a curator read both and said so, not because a
parser found a token it recognised -- and a parser that ran in the build would
make every one of those readings a silent rule with nothing to review.

So: the uuid, name, context and unit columns are the vendor's, taken mechanically
from the shipped files and unable to drift from them by transcription; the
`land_use` fields are the curated part; and `tools/land_class_parser.py` drafts
them for a curator rather than deciding them.  A string the parser cannot place
is printed and left out, which is a question for a person and not a fallback.

`key` is redundant with `land_use` and is here anyway, because it is what a
curator greps the file for.  :func:`~brightway_flows.domain.land_flow_classes.land_class_by_source_flow`
raises if the two disagree, so the redundancy cannot rot into a second answer.

Where #290 has split a place off a BAFU name, the row records `location` and
`original_name` beside the split name, so the audit trail shows what the vendor
shipped.  Nothing is lost by the fold: `location` is part of #290's identity
seed, so the Swiss row and the unregionalised row stay two flows sharing one
land class.

Usage::

    uv run python tools/build_land_flow_classes.py
    uv run python tools/build_land_flow_classes.py --check
"""

from __future__ import annotations

import argparse
import collections
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from land_class_parser import (  # noqa: E402
    VOLUME_PREFIX,
    parse,
    strip_direction,
    without_geography,
)

from brightway_flows.domain.land_use import LandUse  # noqa: E402
from brightway_flows.sources import registered_source_list  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = REPO_ROOT / "src" / "brightway_flows" / "data"
OUTPUT_PATH = DATA_DIR / "land-flow-classes.json"

#: Every registered list, read through the source registry rather than by a path
#: spelled here, so what this classifies is what the merge loads.  The registry
#: also supplies the `source` column: the merge looks a row up under
#: `SourceList.source_label`, and writing anything else here produces a table
#: that loads and never matches.
SOURCE_KEYS = (
    "EF-3.1",
    "ecoinvent-3.8",
    "ecoinvent-3.9.1",
    "ecoinvent-3.10.1",
    "ecoinvent-3.11",
    "ecoinvent-3.12",
    "bafu-2026-v1",
    "stepwise-2006-1.09",
    "agribalyse-3.2",
)

#: How a list says a flow is a land flow.
#:
#: Two rules and not one, because the lists say it in two places.  EF 3.1 files
#: land under a `Land use` context and leaves the direction to the name; the
#: SimaPro-lineage lists write the direction into the name and file a fifth of
#: BAFU's land rows under `resources / unspecified` and `resources / in ground`
#: (§1.9).  A context test alone would miss those 29; a name test alone would
#: miss every EF row, whose names begin `arable` and `from forest`.
_LAND_CONTEXT = "land use"
_LAND_NAME_PREFIXES = ("occupation", "transformation")

#: The curated answers for strings the parser declines.
#:
#: Keyed by the name as the vendor ships it, lower-cased.  `cropland fallow
#: (non-use)` is the one the plan names: the parser rewrites `(non-use)` into a
#: `not used` status everywhere else, and here that would state twice that the
#: land is idle -- a fallow field is by definition out of use -- so the rewrite
#: is declined and the class is stated by hand.
#:
#: Empty is the goal and not the expectation.  A row here is a curator's answer
#: to a question the axes could not; a row the parser *silently* placed would be
#: the same answer with nobody's name on it.
CURATED: dict[str, tuple[dict[str, str], str]] = {}


def _axis_words(land_use: LandUse) -> str:
    """What this value asserts, in the words the axes are named in."""
    stated = land_use.qualifiers()
    if not stated:
        return f"the cover is {land_use.cover.value.lower()} and nothing else is stated"
    parts = [f"the cover is {land_use.cover.value.lower()}"]
    parts += [
        f"the {name.replace('_', ' ')} is {value.value.lower()}"
        for name, value in stated.items()
    ]
    return ", ".join(parts)


def _comment(name: str, land_use: LandUse) -> str:
    """Why this row says what it says.

    Written from the decomposition rather than by hand for each of 1,288 rows,
    and it says the one thing a reviewer is checking: which axis each token of
    the vendor's name was read as.  A row whose comment does not match its name
    is a row read wrongly, and that is visible without opening the parser.
    """
    return (
        f"{name!r} decomposes onto {len(land_use.qualifiers()) + 1} "
        f"{'axis' if not land_use.qualifiers() else 'axes'}: {_axis_words(land_use)}. "
        f"Published as {land_use.label!r}."
    )


def _is_land_flow(name: str, context: list[str]) -> bool:
    lowered = name.strip().lower()
    if lowered.startswith(_LAND_NAME_PREFIXES):
        return True
    return _LAND_CONTEXT in " ".join(context).lower()


def source_rows(key: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """One list's land flows, classified, and the ones nothing placed."""
    source = registered_source_list(key)
    rows: list[dict[str, Any]] = []
    unplaced: list[dict[str, Any]] = []

    for flow in json.loads(Path(source.flows_path).read_bytes()):
        name = flow["name"]
        context = list(flow.get("context") or [])
        if not _is_land_flow(name, context):
            continue

        # #290 takes the place out of a BAFU name at extraction, so a freshly
        # fetched file already has `Occupation, traffic area, rail network` and
        # a `location`.  Split again here so the table does not depend on which
        # extraction happens to be on disk: a land class that appears with the
        # age of a download is not a curated assignment of anything.
        classified, place = without_geography(name)
        location = flow.get("location") or place

        direction, land_class = strip_direction(classified)
        if land_class.startswith(VOLUME_PREFIX):
            # Four EF flows measuring the inside of a mountain, filed under land
            # occupation.  No surface classification has a word for a volume, and
            # they are #72's rather than this file's (§6.3).
            continue

        curated = CURATED.get(classified.strip().lower())
        if curated is not None:
            fields, why = curated
            land_use, comment = LandUse.from_dict(fields), why
        else:
            land_use, residue = parse(direction, land_class)
            if land_use is None:
                unplaced.append(
                    {"source": source.source_label, "name": name, "residue": residue}
                )
                continue
            comment = _comment(classified, land_use)

        row: dict[str, Any] = {
            "source": source.source_label,
            "source_uuid": flow["uuid"],
            "source_name": name,
            "source_context": context,
            "unit": flow["unit"],
            "key": land_use.key,
            "land_use": land_use.to_dict(),
            "comment": comment,
        }
        if place is not None:
            # Only where *this tool* did the splitting: a name the extraction
            # already split arrives without the place, and recording the
            # `location` field beside an unsplit name would claim a fold that
            # did not happen here.
            row["original_name"] = name
            row["source_name"] = classified
        if location:
            row["location"] = location
        rows.append(row)

    return rows, unplaced


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="fail instead of writing if the output would change",
    )
    args = parser.parse_args()

    rows: list[dict[str, Any]] = []
    unplaced: list[dict[str, Any]] = []
    for key in SOURCE_KEYS:
        placed, missed = source_rows(key)
        rows.extend(placed)
        unplaced.extend(missed)
    rows.sort(key=lambda row: (row["source"], row["source_name"].lower(), row["source_uuid"]))

    payload = {
        "schema_version": 1,
        "description": (
            "Which land class in domain/land_use.py each land flow is. Curated: "
            "no algorithm reads `heterogeneous, agricultural` and knows it is "
            "agricultural mosaic, which is why the layering does a lookup here "
            "rather than splitting a name on commas at run time. Generated by "
            "tools/build_land_flow_classes.py -- the uuid, name, context and "
            "unit columns are the vendor's, and `land_use` is the curated part. "
            "`key` is what `land_use` decomposes to, carried so the file can be "
            "grepped by class; the loader raises if the two disagree. One row "
            "per (source, uuid): a flow is one land class, and two rows "
            "arbitrated by file order is the collapse this file exists to stop. "
            "Where #290 split a place off a name, `original_name` and `location` "
            "record what the vendor shipped."
        ),
        "rows": rows,
    }
    rendered = json.dumps(payload, indent=2) + "\n"

    if args.check:
        current = OUTPUT_PATH.read_text() if OUTPUT_PATH.exists() else ""
        if current != rendered:
            print(f"{OUTPUT_PATH} is out of date; re-run without --check")
            return 1
        print(f"{OUTPUT_PATH} is up to date")
        return 0

    OUTPUT_PATH.write_text(rendered)

    by_source = collections.Counter(row["source"] for row in rows)
    classes = {row["key"] for row in rows}
    print(f"{len(rows)} rows over {len(classes)} land classes -> {OUTPUT_PATH.name}")
    for source, count in sorted(by_source.items()):
        print(f"  {source:<18} {count}")
    directions = collections.Counter(row["land_use"]["direction"] for row in rows)
    print(f"  by direction: {dict(directions)}")
    print(f"  unplaced: {len(unplaced)}")
    for row in unplaced:
        print(f"    {row['source']:<18} {row['name']!r} -> {row['residue']}")
    return 1 if unplaced else 0


if __name__ == "__main__":
    raise SystemExit(main())
