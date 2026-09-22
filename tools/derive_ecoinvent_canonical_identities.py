"""Derive the canonical identities of ecoinvent's element/ion flows.

ecoinvent renamed its dissolved-metal flows wholesale between 3.8 and 3.9.1 --
`Selenium` (7782-49-2) became `Selenium IV` (22541-55-5) under the same uuids --
and `plans/retire-prepared-correspondence.md` §3a reads the newest release's
identity as the vendor's current opinion, with the earlier ones mistaken. This
tool derives that reading from the release extractions and writes it to
`src/brightway_flows/data/ecoinvent-canonical-identities.json`, checked in,
so the substitutions a build will make are a reviewable diff rather than a
function of which extractions happen to be on disk.

An entry is written only where there is something to decide: the uuid's newest
name parses as the element/ion family (`merge/species.py` is the arbiter), and
at least one earlier release on disk states a different name or number. A uuid
every release names alike gets no entry, and the loader refuses an entry that
replaces nothing, so the file cannot silently grow into a general rename table.

    uv run python tools/derive_ecoinvent_canonical_identities.py \\
        --data-dir .data \\
        --output src/brightway_flows/data/ecoinvent-canonical-identities.json

Regenerate whenever a new ecoinvent release is extracted; the derivation is
deterministic, so an unchanged input set reproduces the file byte for byte.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import orjson

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from brightway_flows.manual_fixes import apply_manual_fixes  # noqa: E402
from brightway_flows.merge.species import (  # noqa: E402
    CANONICAL_IDENTITIES_SCHEMA_VERSION,
    parse_species,
)
from brightway_flows.sources import known_source_lists  # noqa: E402

_FLOWS_FILE = re.compile(r"^ecoinvent-biosphere-flows-([0-9.]+)\.json$")


def _version_key(version: str) -> tuple[int, ...]:
    return tuple(int(part) for part in version.split("."))


def registered_fixes() -> dict[str, Path]:
    """Each registered ecoinvent release's manual-fixes file, by version."""
    return {
        source.list_version: source.manual_fixes_path
        for source in known_source_lists().values()
        if source.list_name == "ecoinvent" and source.manual_fixes_path is not None
    }


def derive(data_dir: Path, fixes: dict[str, Path] | None = None) -> dict:
    """The canonical identities, read off the releases in *data_dir*.

    Each release's rows are read as the build reads them: with that release's
    `*-manual-fixes.json` applied first.  A fixes file is a curator saying the
    vendor wrote a field wrong, and it is applied "before anything reads" the
    rows (`manual_fixes`); this tool reading the raw file instead would derive
    the wrong value as the vendor's current opinion and then, at matching,
    substitute it back over the correction.  ecoinvent's `Molybdenum VI` is the
    case that found it: 3.9.1 registers the thirteen rows as the ion, 3.10.1
    onwards as the metal, the fix restores the ion's number, and an identity
    derived from the raw 3.12 file would have undone it (#181).

    *fixes* maps a release version to its fixes file; it defaults to what the
    registered source lists declare, and is a parameter so a test can hand in
    its own.
    """
    if fixes is None:
        fixes = registered_fixes()
    releases: dict[str, dict[str, tuple[str, str]]] = {}
    for path in sorted(data_dir.iterdir()):
        matched = _FLOWS_FILE.match(path.name)
        if not matched:
            continue
        version = matched.group(1)
        rows = orjson.loads(path.read_bytes())
        if version in fixes:
            apply_manual_fixes(rows, fixes[version], label=f"ecoinvent-{version}", quiet=True)
        releases[version] = {
            str(row["uuid"]): (
                " ".join(str(row.get("name") or "").split()),
                str(row.get("cas_number") or "").strip(),
            )
            for row in rows
        }
    if len(releases) < 2:
        raise SystemExit(
            f"{data_dir} holds {len(releases)} ecoinvent extraction(s); the "
            f"derivation needs at least two releases to compare. Run "
            f"`brightway-flows fetch-source ecoinvent-<version>` first."
        )

    ordered = sorted(releases, key=_version_key)
    newest_of: dict[str, str] = {}
    for version in ordered:
        for uuid in releases[version]:
            newest_of[uuid] = version

    identities = []
    for uuid, decided_by in newest_of.items():
        name, cas = releases[decided_by][uuid]
        if parse_species(name) is None:
            continue
        replaces = [
            {
                "version": version,
                "name": releases[version][uuid][0],
                "cas_number": releases[version][uuid][1],
            }
            for version in ordered
            if version != decided_by
            and uuid in releases[version]
            and releases[version][uuid] != (name, cas)
        ]
        if not replaces:
            continue
        identities.append({
            "uuid": uuid,
            "name": name,
            "cas_number": cas,
            "decided_by": decided_by,
            "replaces": replaces,
        })

    identities.sort(key=lambda row: (row["name"].lower(), row["uuid"]))
    return {
        "schema_version": CANONICAL_IDENTITIES_SCHEMA_VERSION,
        "description": (
            "The newest release's identity for every ecoinvent element/ion flow "
            "that an earlier release on disk states differently. Derived by "
            "tools/derive_ecoinvent_canonical_identities.py from the release "
            f"extractions ({', '.join(ordered)}); do not edit by hand -- "
            "regenerate. plans/retire-prepared-correspondence.md §3a is the rule "
            "this implements: the newest name is the vendor's current opinion, "
            "the earlier ones are treated as mistaken, and one uuid is one "
            "substance in every release. merge/species.py loads it, and only "
            "for a source list with no prepared correspondence table."
        ),
        "derived_from": ordered,
        "identities": identities,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    payload = derive(args.data_dir)
    args.output.write_bytes(
        orjson.dumps(payload, option=orjson.OPT_INDENT_2) + b"\n"
    )
    print(
        f"{len(payload['identities'])} identities from releases "
        f"{', '.join(payload['derived_from'])} -> {args.output}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
