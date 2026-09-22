"""Give a worktree its own data directory, sharing only what came from outside.

Every worktree used to point at the one platform data directory, and #82 is
what that costs: two branches write the same extracted flow list, so a build
reads flows another branch's code produced.  Nothing warns.  In the case that
prompted the issue the borrowed rows had different names, and therefore
different UUIDs, than the reading branch could produce -- a merge matched
against flows that did not exist on that branch, and every number in the run
looked ordinary.

The split this makes is between what came from outside the project and what the
project's own code writes:

* **From outside** -- vendor archives, the ChEBI dump, the GLAD workbook, the
  web-service caches -- is the same file whatever branch you are on, is slow or
  impossible to fetch again, and is symlinked back to the shared directory.
* **Written here** -- extracted flow lists, layered artifacts, the SQLite
  database, logs -- belongs to the branch that produced it and is written fresh
  in the worktree.  Regenerate a list with `brightway-flows fetch-source`;
  never copy one in from another worktree.

The caches are shared as a link, not a copy, and most of their writers replace
the file rather than rewriting it in place (`tmp` then `os.replace`), which
drops the link and leaves the worktree with its own copy from that point on.
That is the intended outcome either way: the shared cache is never left
half-written, and a worktree that has diverged sends what it learned back with
`pack-cache` / `fetch-cache` rather than by having written through.

Run it once per worktree, then export the variable it prints:

    uv run python tools/seed_data_dir.py
    export BRIGHTWAY_FLOWS_DATA_DIR=$PWD/.data

`.data/` is git-ignored, so removing the worktree removes it.
"""

from __future__ import annotations

import argparse
import fnmatch
import json
from pathlib import Path

from brightway_flows.data_dir import machine_data_dir

REPO_ROOT = Path(__file__).resolve().parent.parent
SOURCE_MANIFEST_DIR = REPO_ROOT / "src" / "brightway_flows" / "data" / "sources"

#: What a worktree links rather than fetches again.  Spelled here as patterns
#: rather than imported from `cache_archive.CACHED_FILES`, because the set is
#: wider than that archive: it also holds the two vendor archives, which are
#: not in it (EF 3.1 is one public GET, BAFU's export is handed over and cannot
#: be downloaded at all).  A name missing from this list costs a re-fetch; a
#: name wrongly on it is #82 again, so nothing derived may be added.
SHARED_PATTERNS: tuple[str, ...] = (
    # Vendor archives and workbooks.
    "EF-v3.1.zip",
    "BAFU-*_ecoSpold v1.zip",
    # BAFU's openLCA distribution, holding GreenDelta's method package.  This
    # one *is* downloadable -- the project hosts the copy it read -- but it is
    # 9.6 MB and the same bytes on every branch, so a worktree links it.
    "bafu-greendelta-lcia.zip",
    "Stepwise2006_v1.09.csv",
    # AGRIBALYSE's SimaPro process export, under the name ADEME circulates it
    # as -- 507 MB, handed over rather than downloadable, like BAFU's archive.
    "AGB32_final.CSV",
    "ILCD_*SubstanceMappingsGLAD.xlsx",
    # Public dumps.
    "chebi.json.gz",
    # Web-service caches: keyed by flow name, CAS number or element, none of
    # which a branch's code decides.
    "chemlin-isotopes.json",
    "commonchemistry-cache.json",
    "compound-profile-cache.json",
    "pubchem-data.json",
    "pubchem-elements-isotopes.json",
    "web-lookup-cache.json",
    "wikidata-cache.json",
    # The Common Chemistry token, so it is entered once per machine.
    "settings.json",
)


def shared_data_dir() -> Path:
    """The machine-wide directory, ignoring `BRIGHTWAY_FLOWS_DATA_DIR`.

    Read from `brightway_flows.data_dir` rather than from
    `brightway_flows.filesystem`: by the time this is worth running the
    variable already points at some worktree, and importing that module would
    seed a worktree from itself.
    """
    return machine_data_dir()


def is_shared(name: str) -> bool:
    return any(fnmatch.fnmatch(name, pattern) for pattern in SHARED_PATTERNS)


def derived_flow_lists() -> dict[str, str]:
    """Each source list's extracted flows file, by the key that regenerates it.

    These are the files #82 is about, and the reason the manifests are read
    here at all: what the report says is missing has to be what this branch's
    own code produces, not a list spelled twice.
    """
    lists: dict[str, str] = {}
    for manifest_path in sorted(SOURCE_MANIFEST_DIR.glob("*.json")):
        manifest = json.loads(manifest_path.read_text())
        flows = (manifest.get("inputs") or {}).get("flows")
        if flows:
            # The key `fetch-source` accepts is `list_name-list_version`, not the
            # manifest's filename.  The two agree for every ecoinvent manifest and
            # disagree for EF -- the file is `ef-3.1.json` and the registry key is
            # `EF-3.1` -- so a filename here printed a command the CLI refuses.
            key = f"{manifest['list_name']}-{manifest['list_version']}"
            lists[key] = flows
    return lists


def seed(shared: Path, target: Path) -> None:
    target.mkdir(parents=True, exist_ok=True)

    linked: list[str] = []
    kept: list[str] = []
    if shared.is_dir():
        for entry in sorted(shared.iterdir()):
            if not entry.is_file() or not is_shared(entry.name):
                continue
            destination = target / entry.name
            if destination.exists() or destination.is_symlink():
                kept.append(entry.name)
                continue
            destination.symlink_to(entry)
            linked.append(entry.name)
    else:
        print(f"No shared directory at {shared}; nothing to link.")

    print(f"Data directory: {target}")
    if linked:
        print(f"Linked {len(linked)} shared file(s) from {shared}:")
        for name in linked:
            print(f"  {name}")
    if kept:
        print(f"Already here, left alone: {', '.join(kept)}")
    if not linked and not kept and shared.is_dir():
        print(f"Nothing to link: {shared} holds none of the shared inputs.")

    missing = {
        key: flows
        for key, flows in derived_flow_lists().items()
        if not (target / flows).exists()
    }
    if missing:
        print("\nExtracted with this branch's code, so not linked. Run:")
        for key, flows in sorted(missing.items()):
            print(f"  uv run brightway-flows fetch-source {key}    # writes {flows}")

    print(f"\nexport BRIGHTWAY_FLOWS_DATA_DIR={target}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--target",
        type=Path,
        default=REPO_ROOT / ".data",
        help="Directory to seed. Defaults to .data/ in this worktree.",
    )
    parser.add_argument(
        "--shared",
        type=Path,
        default=None,
        help="Directory to link from. Defaults to the platform data directory.",
    )
    args = parser.parse_args()
    seed((args.shared or shared_data_dir()).expanduser(), args.target.expanduser().resolve())


if __name__ == "__main__":
    main()
