"""Derive the retired-name aliases from ecoinvent's own 2.2 -> 3.12 crosswalk.

ecoinvent publishes, through `randonneur_data`, a transitive correspondence
from its 2.2 biosphere to 3.12: for every flow whose identity changed on the
way, the 2.2 name and the newest release's statement about the same flow.  This
tool reads that table and writes the pairs a name alias can honestly decide to
`src/brightway_flows/data/ecoinvent-historical-names.json`, checked in, so
what the merge will treat as a retired spelling is a reviewable diff rather
than a function of which `randonneur_data` happens to be installed.

`merge/historical_names.py` loads the file and says where it is consulted; its
docstring is also the reasoning behind the exclusions below.  An entry is
written only where a *name*, on its own, can carry the decision:

* **a deleted flow decides nothing** -- the vendor marks these
  ``[Deleted]``, and there is nothing current to alias to;
* **an unchanged name decides nothing** -- most correspondence rows record a
  moved context or a corrected CAS, and mapping a spelling to itself is a
  no-op;
* **a name with two answers is decided by context** -- 2.2's `Water,
  unspecified natural origin` became groundwater in one subcompartment and
  fossil groundwater in another, so no single alias is right;
* **a land name is decided by the land classes** -- occupation and
  transformation rows match by decomposed land class
  (`land-flow-groupings.json`), never by label;
* **the element/ion family is decided by `merge/species.py`** -- a bare
  `Cadmium` is the element in air and `Cadmium II` in water, and `Calcium,
  ion` -> `Calcium II` writes in an oxidation state the alias has no business
  assigning.  Kept are only the pairs where both sides state the same thing
  about the same element: a generic ion respelt (`Copper, ion` -> `Copper
  ion`) or a stated charge restated (`Chromium IV` -> `Chromium VI`, the
  vendor's own correction).

The loader refuses every excluded family a second time, so a hand edit cannot
smuggle one back in.

    uv run python tools/derive_ecoinvent_historical_names.py \\
        --output src/brightway_flows/data/ecoinvent-historical-names.json

Regenerate whenever `randonneur_data` publishes a new revision of the
correspondence (for a new release, the transitive table's name changes with
it -- pass ``--table``); the derivation is deterministic, so an unchanged
input reproduces the file byte for byte.
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

import orjson

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from brightway_flows.context_mapping import normalize_mapping_text  # noqa: E402
from brightway_flows.merge.historical_names import (  # noqa: E402
    HISTORICAL_NAMES_SCHEMA_VERSION,
    LAND_NAME_PREFIXES,
)
from brightway_flows.merge.species import parse_species  # noqa: E402

DEFAULT_TABLE = "ecoinvent-2.2-biosphere-ecoinvent-3.12-biosphere-transitive"


def _version_key(version: str) -> tuple[int, ...]:
    """`ecoinvent-3.10.1-biosphere` sorted numerically, so 3.10.1 > 3.9.1."""
    digits = [part for part in version.replace("-", ".").split(".") if part.isdigit()]
    return tuple(int(part) for part in digits)


def _species_pair_is_alias(source_name: str, target_name: str) -> bool:
    """Whether an element/ion pair states the same thing about the element.

    `True` is the pair an alias can carry; everything else in the family is
    `merge/species.py`'s decision.  A source that is not the family's business
    never reaches here.
    """
    source = parse_species(source_name)
    target = parse_species(target_name)
    assert source is not None
    if source.kind == "bare":
        return False
    return (
        target is not None
        and target.element == source.element
        and target.kind == source.kind
    )


def derive(correspondence: dict) -> tuple[dict, Counter]:
    """The historical-names payload, and a tally of what was dropped and why."""
    updates = correspondence.get("update")
    if not isinstance(updates, list) or not updates:
        raise SystemExit(
            f"{correspondence.get('name')!r} carries no update section; "
            f"a correspondence without one has nothing to derive from."
        )

    dropped: Counter = Counter()
    #: normalised source name -> {normalised target names seen}
    targets_of: dict[str, set[str]] = {}
    #: normalised source name -> (source name, target name, newest version)
    survivors: dict[str, tuple[str, str, str]] = {}

    for row in updates:
        source_name = " ".join(str(row["source"]["name"]).split())
        target_name = " ".join(str(row["target"]["name"]).split())
        if not source_name or not target_name:
            raise SystemExit(f"a correspondence row is missing a name: {row!r}")
        key = normalize_mapping_text(source_name)
        if target_name.startswith("[Deleted]"):
            dropped["deleted-target"] += 1
            continue
        targets_of.setdefault(key, set()).add(normalize_mapping_text(target_name))
        if key == normalize_mapping_text(target_name):
            dropped["name-unchanged"] += 1
            continue
        if key.startswith(LAND_NAME_PREFIXES):
            dropped["land-name"] += 1
            continue
        if parse_species(source_name) is not None and not _species_pair_is_alias(
            source_name, target_name
        ):
            dropped["element-ion-family"] += 1
            continue
        version = str(row.get("target_version") or "")
        held = survivors.get(key)
        if held is None or _version_key(version) > _version_key(held[2]):
            survivors[key] = (source_name, target_name, version)

    names = []
    for key, (source_name, target_name, version) in survivors.items():
        # A name the vendor sent to two different flows depending on context
        # cannot be a flat alias, whichever rows it would have survived on.
        if len(targets_of[key]) > 1:
            dropped["several-canonical-names"] += 1
            continue
        names.append({
            "historical_name": source_name,
            "canonical_name": target_name,
            "decided_by": version,
        })
    names.sort(key=lambda row: row["historical_name"].lower())

    payload = {
        "schema_version": HISTORICAL_NAMES_SCHEMA_VERSION,
        "description": (
            "Every name ecoinvent retired between 2.2 and 3.12 that a name "
            "alias can honestly decide, with the newest release's name for the "
            "same flow. Derived by tools/derive_ecoinvent_historical_names.py "
            f"from randonneur_data's {correspondence.get('name')} "
            f"v{correspondence.get('version')}; do not edit by hand -- "
            "regenerate. merge/historical_names.py loads it and says where it "
            "is consulted and what is deliberately absent."
        ),
        "derived_from": {
            "table": str(correspondence.get("name") or ""),
            "version": str(correspondence.get("version") or ""),
            "created": str(correspondence.get("created") or ""),
        },
        "names": names,
    }
    return payload, dropped


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument(
        "--table",
        default=DEFAULT_TABLE,
        help=f"randonneur_data table name (default: {DEFAULT_TABLE})",
    )
    parser.add_argument(
        "--input",
        type=Path,
        help="read the correspondence from a JSON file instead of the registry",
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)

    if args.input:
        correspondence = orjson.loads(args.input.read_bytes())
    else:
        import randonneur_data

        correspondence = randonneur_data.Registry().get_file(args.table)

    payload, dropped = derive(correspondence)
    args.output.write_bytes(
        orjson.dumps(payload, option=orjson.OPT_INDENT_2) + b"\n"
    )
    print(
        f"{len(payload['names'])} historical names from "
        f"{payload['derived_from']['table']} v{payload['derived_from']['version']} "
        f"-> {args.output}"
    )
    for reason, count in sorted(dropped.items()):
        print(f"  dropped {count:4d}  {reason}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
