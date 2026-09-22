"""Run the pipeline into an isolated data directory and snapshot what it wrote.

A refactor of this project is verified by running the same bounded job under two
revisions and diffing every artifact, because the test suite has twice passed
over code that was broken.  This tool is that harness.

It exists as a repository tool rather than a throwaway script because the merge
rewrite moves the artifacts from JSON files into SQLite, and hashing files stops
detecting anything once that happens.  A snapshot therefore covers both: JSON
payloads canonicalised, and every SQLite table dumped row by row.

Three commands:

    verify_run.py run BASE_DIR [--max-flows N] [--include-uuid UUID ...]
                              [--max-rows N] [--include-source-uuid UUID ...]
    verify_run.py snapshot DATA_DIR SNAPSHOT_DIR   snapshot a directory as-is
    verify_run.py compare SNAPSHOT_A SNAPSHOT_B    report what differs

`run` places the working data directory and its snapshot under BASE_DIR, so two
revisions are compared by running each into its own BASE_DIR and pointing
`compare` at the two snapshots.

**Two things about it that have misled a reader, and now do not.**

`--max-flows N` builds `flows[:N]`, a prefix of the base list in file order.
Whether that contains the flows a change is about is an accident of where they
sort: EF 3.1's eleven water withdrawals sit at indices 12,722 to 75,846 of
94,062, so the default run reaches none of them, and a change to those flows
passed it while aborting the build at 80,000.  `--include-uuid` names what the
run is about and keeps it regardless of position, added to the prefix rather
than replacing it so two runs stay comparable.

`--max-rows N` is the same bound on the other side, and it is the one that
makes a verification run finish: `--max-flows` bounds the transform, and the
merge went on matching every row of every `--source` against the bounded
consensus list.  Left off, nothing changes and the merge is whole.  Set, both
sides of the comparison must set it to the same value -- and they cannot
silently differ, because `merge_run_inputs` records the limit and the rows
available, so the snapshot of a bounded run differs from the snapshot of a
whole one in exactly that row.

And a comparison used to report every row whose JSON keys had moved as changed
-- 386 of 389 `flow_object_payloads` rows on a run where none had.  Key order is
still recorded, because converting a dict to a dataclass record reorders keys
and that is worth seeing; what changed is that `compare` now says which rows
differ only that way instead of burying the one that does not among them.

**Run it from a copy of the tree, not the tree you are editing.**  `run_stage`
sets `PYTHONPATH` to this repository and spawns the build after extraction
finishes, so switching branches while a run is in flight silently reports on
whichever code is checked out when the build starts.  `git archive <rev> | tar
-x -C somewhere` and run it from there.

Snapshot output is plain text, one file per artifact, so `diff -r` works on it
directly and a difference can be read rather than merely detected.

`run` extracts EF 3.1 before it builds, rather than being handed the extracted
file (#237).  That is most of a run's wall clock -- 94,000 flows out of a
207 MB archive -- and it adds `ef-31-flows.json`, about 190 MB, to each
snapshot.  Both are the price of the comparison covering extraction at all;
seeding the derived file instead held extraction fixed on both sides and made
a change to it, or to `ef-3.1-manual-fixes.json`, produce an identical
snapshot.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import os
import re
import sqlite3
import subprocess
import sys
from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import Any

import orjson
from brightway_flows.data_dir import machine_data_dir

REPO_ROOT = Path(__file__).resolve().parent.parent

#: Where the caches and vendor archives are seeded from.  Asked of
#: `data_dir.machine_data_dir`, the way `filesystem.DATA_DIR` and `tools/seed_data_dir.py`
#: both ask: this was the macOS path spelled out, so the tool AGENTS.md rule 22
#: mandates for every refactor failed on Linux with "source data directory not
#: found" before it had run anything.
DEFAULT_SOURCE_DATA_DIR = machine_data_dir()

#: Inputs and caches seeded into the isolated directory.  Everything else the
#: run finds there it must have produced itself -- that is what makes the
#: snapshot meaningful.  Hard links, so a 2 GB cache costs nothing.
#:
#: `ef-31-flows.json` was here until #237, and it broke that premise: it is
#: derived from `EF-v3.1.zip`, which is seeded too, and `build` reads the
#: derived file rather than producing it.  So the harness pinned one revision's
#: extraction on both sides of every comparison.  A change to extraction code,
#: or to `ef-3.1-manual-fixes.json`, produced an identical snapshot either way
#: -- which is how #231 was verified, merged, and inert for five months.  The
#: run extracts it now, from the zip it was always given.
SEED_NAMES = (
    "EF-v3.1.zip",
    "chebi.json.gz",
    "chemlin-isotopes.json",
    "commonchemistry-cache.json",
    "compound-profile-cache.json",
    "pubchem-data.json",
    "pubchem-elements-isotopes.json",
    "settings.json",
    "web-lookup-cache.json",
    "wikidata-cache.json",
    # The GLAD correspondence table.  Read by a build that merges a list whose
    # flows originate in SimaPro, so a run comparing two such builds has to
    # start from the same copy of it rather than re-downloading.
    "glad-ilcd-ef31-to-simapro-10.2.json",
    # And under the name it had while it was on the input path.  Every other
    # `additional-flow-input-*.json` was seeded by a glob until the transform
    # stopped having an input path at all (#210); this one is read, as a
    # correspondence table, so it is named.
    "additional-flow-input-glad-ilcd-ef31-to-simapro-10.2.json",
)
SEED_GLOBS = (
    "ecoinvent-biosphere-flows-*.json",
    "*SubstanceMappingsGLAD.xlsx",
)

#: SQLite's write-ahead log and shared-memory sidecars.  Whether they exist at
#: the moment of the snapshot depends on how the last connection was closed, not
#: on what the run produced; their content is already in the database itself.
SQLITE_SIDECAR_SUFFIXES = ("-wal", "-shm", "-journal")

#: Fields whose value is a property of *when* the run happened, not of what it
#: produced.  Replaced with a placeholder rather than dropped, so that a field
#: appearing or disappearing still shows up as a difference.
VOLATILE_KEYS = frozenset({
    "generated_at",
    "timestamp",
    "run_id",
    "started_at",
    "finished_at",
    "created_at",
    "duration_seconds",
    "elapsed_seconds",
    # `dcterms:created` on the consensus scheme and on every correspondence in
    # `harmonised-flows-simple.json.gz`.  The published artifact is this tool's
    # gate, and this is the only key in it that a second run over identical
    # inputs changes -- without this line every comparison would fail, and the
    # tool would stop being able to tell a real difference from a clock tick.
    "dcterms:created",
})

#: Columns holding an AUTOINCREMENT rowid, which depends on insertion order
#: rather than content.  Dropped before rows are sorted; duplicate rows still
#: appear twice, so nothing is masked.
VOLATILE_COLUMNS = frozenset({"id"})

PLACEHOLDER = "<volatile>"
DATA_DIR_PLACEHOLDER = "<DATA_DIR>"

#: `opsin-log.txt` and `rdkit-log.txt` stamp every line with the wall-clock time.
#: Without masking it, two runs of the same revision always differ, which is the
#: quickest way to make a verification harness stop being run.
LOG_TIMESTAMP = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z?\t")


# --------------------------------------------------------------------------
# seeding and running


def seed_data_dir(work: Path, source: Path) -> list[str]:
    """Hard-link inputs and caches from *source* into *work*."""
    work.mkdir(parents=True, exist_ok=True)
    if not source.exists():
        raise SystemExit(f"source data directory not found: {source}")

    names: list[str] = list(SEED_NAMES)
    for pattern in SEED_GLOBS:
        names.extend(path.name for path in sorted(source.glob(pattern)))

    linked: list[str] = []
    for name in sorted(set(names)):
        src = source / name
        dst = work / name
        if not src.exists() or dst.exists():
            continue
        try:
            os.link(src, dst)
        except OSError:
            dst.write_bytes(src.read_bytes())
        linked.append(name)
    return linked


def run_stage(argv: list[str], work: Path, label: str) -> int:
    """Invoke the CLI of the working tree against the isolated data directory."""
    env = dict(
        os.environ,
        BRIGHTWAY_FLOWS_DATA_DIR=str(work),
        PYTHONPATH=str(REPO_ROOT / "src"),
    )
    invocation = ["brightway-flows", *argv]
    code = (
        f"import sys; sys.argv = {invocation!r}; "
        "from brightway_flows import main; main()"
    )
    result = subprocess.run(
        [sys.executable, "-c", code], env=env, capture_output=True, text=True,
        check=False,  # a failing stage is reported by the caller, not raised
    )
    print(f"[{label}] exit={result.returncode}", flush=True)
    if result.returncode:
        sys.stderr.write(result.stderr[-4000:])
    return result.returncode


# --------------------------------------------------------------------------
# canonicalisation


def scrub(value: Any, data_dir: str) -> Any:
    """Replace volatile values and absolute data-directory paths.

    The data directory differs between the two runs being compared, so any
    string carrying it would differ for reasons that say nothing about the code.
    """
    if isinstance(value, dict):
        return {
            key: PLACEHOLDER if key in VOLATILE_KEYS else scrub(item, data_dir)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [scrub(item, data_dir) for item in value]
    if isinstance(value, str) and data_dir in value:
        return value.replace(data_dir, DATA_DIR_PLACEHOLDER)
    return value


def canonical_json(payload: Any) -> bytes:
    """Indented, but with key order preserved.

    Sorting keys would be the obvious thing and it is wrong here.  The pipeline
    is deterministic, so there is no source of key-order noise to suppress --
    while converting a dict to a dataclass record *does* reorder keys, because
    `to_dict()` follows declaration order.  That is exactly the change the next
    PRs in this stack make, so key order has to be part of what is compared.
    """
    return orjson.dumps(payload, option=orjson.OPT_INDENT_2)


def canonical_log(path: Path, data_dir: str) -> bytes:
    """A text log with its per-line timestamps masked.

    Line order is kept: the sequence a log was written in is part of what it
    says, unlike the row order of a table.
    """
    lines = [
        LOG_TIMESTAMP.sub(f"{PLACEHOLDER}\t", line).replace(data_dir, DATA_DIR_PLACEHOLDER)
        for line in path.read_text(errors="replace").splitlines()
    ]
    return ("\n".join(lines) + "\n").encode()


def load_json_artifact(path: Path) -> Any:
    raw = gzip.decompress(path.read_bytes()) if path.suffix == ".gz" else path.read_bytes()
    return orjson.loads(raw)


# --------------------------------------------------------------------------
# SQLite dumping


def fts_shadow_prefixes(conn: sqlite3.Connection) -> tuple[str, ...]:
    """Prefixes of the internal tables fts5 maintains for each virtual table.

    Their contents are an implementation detail of the index and are not stable
    across builds, so they are excluded; the virtual table itself is dumped and
    carries the indexed text.
    """
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' "
        "AND sql LIKE '%USING fts5%' ORDER BY name"
    ).fetchall()
    return tuple(f"{row[0]}_" for row in rows)


def dumpable_tables(conn: sqlite3.Connection) -> list[str]:
    shadows = fts_shadow_prefixes(conn)
    names = [
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type IN ('table', 'view') "
            "AND name NOT LIKE 'sqlite_%' ORDER BY name"
        )
    ]
    return [name for name in names if not name.startswith(shadows)]


def dump_table(conn: sqlite3.Connection, table: str, data_dir: str) -> bytes:
    """One table as sorted, JSON-encoded rows.

    Every cell is JSON-encoded so that embedded tabs and newlines cannot break
    the line structure, and rows are sorted by their encoded form so that
    insertion order does not show up as a difference.
    """
    cursor = conn.execute(f'SELECT * FROM "{table}"')
    columns = [description[0] for description in cursor.description]
    keep = [
        index for index, name in enumerate(columns) if name not in VOLATILE_COLUMNS
    ]
    header = "\t".join(columns[index] for index in keep)

    lines: list[str] = []
    for row in cursor:
        cells = []
        for index in keep:
            value = row[index]
            if columns[index] in VOLATILE_KEYS:
                value = PLACEHOLDER
            elif isinstance(value, str) and data_dir in value:
                value = value.replace(data_dir, DATA_DIR_PLACEHOLDER)
            elif isinstance(value, bytes):
                value = f"<blob:{hashlib.sha256(value).hexdigest()[:16]}>"
            cells.append(orjson.dumps(value).decode())
        lines.append("\t".join(cells))
    lines.sort()

    body = "\n".join([f"# rows: {len(lines)}", header, *lines])
    return body.encode() + b"\n"


def dump_sqlite(path: Path, data_dir: str) -> Iterator[tuple[str, bytes]]:
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        for table in dumpable_tables(conn):
            yield f"{path.name}/{table}.tsv", dump_table(conn, table, data_dir)
    finally:
        conn.close()


# --------------------------------------------------------------------------
# snapshotting


def snapshot(data_dir: Path, out_dir: Path) -> dict[str, str]:
    """Write a canonical, diffable form of every artifact in *data_dir*.

    Returns a manifest of artifact name to digest, which is what makes a
    same-or-different judgement cheap; the files themselves are what makes a
    difference readable.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    data_dir_str = str(data_dir)
    manifest: dict[str, str] = {}

    def emit(name: str, payload: bytes) -> None:
        target = out_dir / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(payload)
        manifest[name] = hashlib.sha256(payload).hexdigest()[:16]

    seeded = set(SEED_NAMES)
    for path in sorted(data_dir.iterdir()):
        if not path.is_file() or path.name in seeded:
            continue
        if any(path.match(pattern) for pattern in SEED_GLOBS):
            continue
        if path.name.endswith(SQLITE_SIDECAR_SUFFIXES):
            continue

        if path.suffix in {".sqlite3", ".db"}:
            try:
                for name, payload in dump_sqlite(path, data_dir_str):
                    emit(name, payload)
            except sqlite3.Error as error:
                # A database left mid-transaction cannot be read without being
                # recovered, which a snapshot must not do.  Report it: an
                # unreadable database is a finding, not a reason to abort.
                emit(f"{path.name}.unreadable", str(error).encode() + b"\n")
        elif path.suffix == ".json" or path.name.endswith(".json.gz"):
            try:
                payload = load_json_artifact(path)
            except Exception as error:  # noqa: BLE001 -- report, do not abort
                emit(f"{path.name}.unreadable", str(error).encode())
                continue
            emit(f"{path.name}.canonical", canonical_json(scrub(payload, data_dir_str)))
        elif path.suffix in {".txt", ".log"}:
            emit(f"{path.name}.canonical", canonical_log(path, data_dir_str))
        else:
            digest = hashlib.sha256(path.read_bytes()).hexdigest()[:16]
            emit(f"{path.name}.digest", digest.encode() + b"\n")

    emit("MANIFEST.json", canonical_json(manifest))
    return manifest


# --------------------------------------------------------------------------
# comparison


def read_manifest(snapshot_dir: Path) -> dict[str, str]:
    path = snapshot_dir / "MANIFEST.json"
    if not path.exists():
        raise SystemExit(f"not a snapshot directory (no MANIFEST.json): {snapshot_dir}")
    return orjson.loads(path.read_bytes())


def reordered_json(left: str, right: str) -> bool:
    """Whether two cells are the same JSON with its keys in a different order.

    A snapshot keeps key order, deliberately: converting a dict to a dataclass
    record reorders keys, and that is a change worth seeing.  But the payload
    columns are not reliably ordered between two runs of the *same* code, so a
    comparison that cannot tell the two apart reports most of a table as changed
    on every run -- 386 of 389 `flow_object_payloads` rows, none of which had
    changed, which is enough noise to make a reviewer stop reading the table.

    So the order is still recorded and the *report* classifies it.  A row whose
    content is identical once sorted is counted and named as such, rather than
    shown as a diff or hidden.
    """
    if left == right:
        return False
    canonical = [_sorted_json(left), _sorted_json(right)]
    return canonical[0] is not None and canonical[0] == canonical[1]


def _sorted_json(cell: str) -> bytes | None:
    """*cell* as JSON with keys sorted, or None if it does not hold an object.

    Twice, because the dump encodes every cell as JSON and several columns hold
    a JSON *string*: the cell is a quoted document, and decoding once yields the
    document rather than its keys. Reading it once and comparing is what made
    the first attempt at this report every payload row as changed anyway.
    """
    value: Any = cell
    for _ in range(2):
        if not isinstance(value, str):
            break
        try:
            value = orjson.loads(value)
        except orjson.JSONDecodeError:
            return None
    if not isinstance(value, (dict, list)):
        return None
    return orjson.dumps(value, option=orjson.OPT_SORT_KEYS)


def classify_rows(left: Path, right: Path) -> tuple[int, int]:
    """`(rows that really differ, rows differing only in key order)`.

    `(-1, 0)` when the pair is not a row dump this can read -- a JSON artifact
    or a log, where the whole file is one payload and the caller falls back to
    showing the diff.
    """
    if left.suffix != ".tsv":
        return -1, 0
    try:
        left_lines = left.read_text().splitlines()
        right_lines = right.read_text().splitlines()
    except UnicodeDecodeError:
        return -1, 0
    if len(left_lines) != len(right_lines):
        return -1, 0

    real = reordered = 0
    for a, b in zip(left_lines, right_lines):
        if a == b:
            continue
        cells_a, cells_b = a.split("\t"), b.split("\t")
        if len(cells_a) != len(cells_b):
            real += 1
            continue
        if all(x == y or reordered_json(x, y) for x, y in zip(cells_a, cells_b)):
            reordered += 1
        else:
            real += 1
    return real, reordered


def compare(left: Path, right: Path) -> int:
    """Report artifacts that differ between two snapshots.  Returns exit code."""
    left_manifest = read_manifest(left)
    right_manifest = read_manifest(right)
    left_manifest.pop("MANIFEST.json", None)
    right_manifest.pop("MANIFEST.json", None)

    only_left = sorted(set(left_manifest) - set(right_manifest))
    only_right = sorted(set(right_manifest) - set(left_manifest))
    differing = sorted(
        name
        for name in set(left_manifest) & set(right_manifest)
        if left_manifest[name] != right_manifest[name]
    )

    for name in only_left:
        print(f"only in {left.name}: {name}")
    for name in only_right:
        print(f"only in {right.name}: {name}")

    reordered_only = []
    for name in differing:
        real, reordered = classify_rows(left / name, right / name)
        if real == 0 and reordered:
            reordered_only.append((name, reordered))
            continue
        suffix = f" ({reordered} more differ only in JSON key order)" if reordered else ""
        print(f"differs: {name}{suffix}")
        print(indent(diff_excerpt(left / name, right / name)))

    for name, count in reordered_only:
        print(f"key order only: {name} -- {count} row(s), no content changed")

    total = len(only_left) + len(only_right) + len(differing)
    substantive = total - len(reordered_only)
    shared = len(set(left_manifest) & set(right_manifest))
    print(f"\n{shared - len(differing)}/{shared} shared artifacts identical")
    if reordered_only:
        print(f"{len(reordered_only)} differing only in JSON key order")
    if total:
        print(f"{total} difference(s), {substantive} substantive")
        # Key order is real output, so it is still a difference and still fails.
        # What changes is that a reviewer can see at a glance that it is all of
        # what changed.
        return 1
    print("snapshots are identical")
    return 0


def diff_excerpt(left: Path, right: Path, limit: int = 12) -> str:
    import difflib

    try:
        left_lines = left.read_text().splitlines()
        right_lines = right.read_text().splitlines()
    except UnicodeDecodeError:
        return "<binary>"
    lines = list(
        difflib.unified_diff(
            left_lines, right_lines, lineterm="", n=1, fromfile="a", tofile="b"
        )
    )
    if len(lines) > limit:
        lines = lines[:limit] + [f"... {len(lines) - limit} more diff lines"]
    return "\n".join(lines)


def indent(text: str, prefix: str = "    ") -> str:
    return "\n".join(prefix + line for line in text.splitlines())


# --------------------------------------------------------------------------
# entry point


def command_run(args: argparse.Namespace) -> int:
    base = Path(args.base_dir).resolve()
    work = base / "data"
    linked = seed_data_dir(work, Path(args.source_data_dir).expanduser())
    print(f"seeded {len(linked)} input(s) into {work}")

    # Derive the base flow file rather than seeding it.  This is the slow part
    # of a verification run -- 94,000 flows out of a 207 MB archive -- and it
    # is the part that makes the rest of the run mean anything: without it the
    # comparison holds extraction fixed and cannot see a change to it (#237).
    # `--keep-zip` because the snapshot is taken of this directory and a run
    # that deleted its own input would not be repeatable.
    if run_stage(["extract", "--keep-zip"], work, "extract"):
        return 1

    argv = [
        "build",
        "--max-flows", str(args.max_flows),
        "--source", f"ecoinvent-{args.ecoinvent_version}",
    ]
    for uuid in args.include_uuid:
        argv += ["--include-uuid", uuid]
    if args.max_rows is not None:
        argv += ["--max-rows", str(args.max_rows)]
    for uuid in args.include_source_uuid:
        argv += ["--include-source-uuid", uuid]
    if run_stage(argv, work, "build"):
        return 1

    out_dir = base / "snapshot"
    manifest = snapshot(work, out_dir)
    print(f"snapshot of {len(manifest) - 1} artifact(s) written to {out_dir}")
    return 0


def command_snapshot(args: argparse.Namespace) -> int:
    manifest = snapshot(Path(args.data_dir).resolve(), Path(args.snapshot_dir).resolve())
    print(f"snapshot of {len(manifest) - 1} artifact(s) written to {args.snapshot_dir}")
    return 0


def command_compare(args: argparse.Namespace) -> int:
    return compare(Path(args.left).resolve(), Path(args.right).resolve())


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the pipeline into an isolated data directory and "
        "snapshot what it wrote."
    )
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="seed a data directory, run the pipeline, snapshot")
    run.add_argument("base_dir")
    run.add_argument("--max-flows", type=int, default=400)
    run.add_argument(
        "--include-uuid",
        action="append",
        default=[],
        metavar="UUID",
        help=(
            "Keep this base-list flow in the sample whatever its position. "
            "Repeatable. --max-flows alone takes a prefix in file order, which "
            "may contain none of the flows the change is about."
        ),
    )
    run.add_argument(
        "--max-rows",
        type=int,
        default=None,
        help=(
            "Merge only the first N rows of each source list. Off by default: "
            "the merge is whole unless the comparison is asked to bound it, and "
            "both sides must be asked the same."
        ),
    )
    run.add_argument(
        "--include-source-uuid",
        action="append",
        default=[],
        metavar="UUID",
        help=(
            "Keep this source row in a --max-rows run whatever its position. "
            "Repeatable."
        ),
    )
    run.add_argument("--ecoinvent-version", default="3.12")
    run.add_argument("--source-data-dir", default=str(DEFAULT_SOURCE_DATA_DIR))
    run.set_defaults(handler=command_run)

    snap = sub.add_parser("snapshot", help="snapshot a data directory as it stands")
    snap.add_argument("data_dir")
    snap.add_argument("snapshot_dir")
    snap.set_defaults(handler=command_snapshot)

    cmp_ = sub.add_parser("compare", help="report differences between two snapshots")
    cmp_.add_argument("left")
    cmp_.add_argument("right")
    cmp_.set_defaults(handler=command_compare)

    return parser


def main(argv: Iterable[str] | None = None) -> int:
    args = build_parser().parse_args(list(argv) if argv is not None else None)
    return args.handler(args)


if __name__ == "__main__":
    raise SystemExit(main())
