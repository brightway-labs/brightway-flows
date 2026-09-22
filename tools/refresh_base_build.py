"""Is the stored build a before side for this branch, and if so, take a copy.

#101 gave a build a stamp saying which revision it came from, so that a *stored*
build could be reused as the before side of `compare_merge_outcomes.py` instead
of being rebuilt per pull request.  It left open where those builds live and who
refreshes them when `main` moves.  This is that half.

**Nothing runs on a schedule.**  The question "is the stored build still the
right one" only has to be answered when somebody is about to use it, which is
the beginning of an investigation, and that is when this runs -- step 2 of the
matching-defect skill.  A timer would rebuild in the background at times nobody
asked about, and its worst failure -- rewriting the data directory while a
branch is reading it -- would be silent.

    uv run python tools/refresh_base_build.py           # can I use what is stored?
    uv run python tools/refresh_base_build.py --build   # ...and build one if not
    uv run python tools/refresh_base_build.py --ref origin/main

It exits 0 where the stored build answers for this branch, having copied the
44 MB a comparison reads into `base-builds/<commit>.sqlite3`; 1 where a build is
needed and `--build` was not given; 2 where it was asked to publish something it
cannot stand behind, or where the build it made is not the whole of what the
shared directory is supposed to hold.

## A build is `build` and then `characterise`

`--build` runs both, because a database with no `lcia_*` tables is not a build
anybody can use: the review webapp reads them, `assess` reads them, and a
refresh that left them out would replace a characterised build of `main` with
one that answers "no factors" to every question about a flow.  They are two
commands rather than one because characterisation reads what a build wrote and
nothing else, so a rule about factors can be iterated in a minute instead of an
hour -- and the same separation is why the extract is copied out *before*
`characterise` runs.  It touches no table `build` owns, so the before side is
complete either way, and a characterisation that fails on a missing
`fetch-lcia` file loses nothing but the factors.

## Where the stored build lives

The shared data directory: the one a plain `brightway-flows build` writes
when `BRIGHTWAY_FLOWS_DATA_DIR` is unset.  Not a directory of its own -- only
347 MB of that 12 GB came from outside the project and would be shared by
symlink, so a second one means about 11.6 GB of files re-derived to say the same
thing, and a second run of the hours that derive them.  It is also what the
review webapp serves and what `assess` reads by default, so a build of `main` is
what a reader wants to find there anyway.  One build, serving the reader, the
assessment and the before side at once.

The rule that comes with it: **nothing but a refresh writes that directory.**  A
build there deletes and rewrites the database and rewrites the extracted source
lists beside it, so a development build in it is destroyed by the next refresh --
and, worse because it is silent, a refresh mid-investigation swaps the extracted
lists under a branch that is reading them, which is #82 by another route.
Development builds belong in a worktree's own `.data`, which
`tools/seed_data_dir.py` makes.  It also rests on one data-changing change being
in flight at a time, which is a decision about how the work is sequenced rather
than something this enforces.

## What is copied is an extract, not a build

A comparison reads almost none of a 2.0 GB database: `merge_outcomes` whole --
31 MB, `detail_json` and every scored candidate included -- plus two columns of
`flow_objects`, six of `elementary_flows`, and the two run headers.  Extracted,
that is 44 MB, which `compare_merge_outcomes.py` reads as though it were the
build.  So a copy is taken per commit rather than per branch, ten of them cost
less than one build, and a question asked after `main` has moved on is still
answerable.

What an extract cannot do is `assess`, or be served: those want the whole
database, and the whole database is what the shared directory holds for the
commit it is currently at.
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

from brightway_flows.data_dir import machine_data_dir

REPO_ROOT = Path(__file__).resolve().parent.parent

#: What a base build merges.  A comparison is only comparable where both sides
#: merged the same lists, so this is the set a before side has to have.
#: ecoinvent 3.12 and 3.8 are the two releases the current work measures against,
#: and BAFU 2026 v1 is here because it was the first merged list whose flows come
#: out of SimaPro: the name-matching strategies that de-invert `Benzene,
#: chloro-`, strip a geography and read a unit out of a name run on no other
#: list, so a before side without it cannot say what a change did to the rows
#: they decide.
#:
#: Stepwise 2006 is here because this build is not only a before side.  It is
#: also what `assess` grades and what the review application serves, and an
#: expectation about a row of a list the build does not merge cannot be graded
#: at all: it reports `unresolved`, which is the status for a subject that has
#: gone away rather than for a claim nobody checked.  #167 states six things
#: about chlordane, three of them flow counts that only hold once Stepwise's
#: rows have landed and one of them about a Stepwise row directly, and on a
#: three-list build all four were failing for a reason that had nothing to do
#: with chlordane.  Registering a list (#164) and grading what it does are two
#: steps, and this is the second.
#:
#: The cost is the one #164 named when it left the list out: Stepwise's review
#: queues have not been worked through, so its rows move counts in every
#: comparison read against this baseline.  That is a reason to read a diff with
#: the list in mind, not a reason to grade nothing about it.
#:
#: AGRIBALYSE 3.2 is here for Stepwise's reason: it is registered to be graded
#: and served, and an expectation about a row of a list the build does not
#: merge reports `unresolved`.  Its review queues are as unworked as Stepwise's
#: were on arrival, so the same caveat applies to every comparison read against
#: this baseline.
DEFAULT_SOURCES: tuple[str, ...] = (
    "ecoinvent-3.12",
    "ecoinvent-3.8",
    "bafu-2026-v1",
    "stepwise-2006-1.09",
    "agribalyse-3.2",
)

#: How many extracts to keep.  At 44 MB each, ten is smaller than one build, and
#: the bound is here because an archive nobody prunes is a disk that fills
#: quietly.
DEFAULT_KEEP = 10

#: Where a commit between two builds can move a row.  The merge decides; the
#: transform prepares what the merge scores; the layering writes what it scores
#: against; the curated files are the rulings it reads.  A commit anywhere else
#: in `src/` cannot move a row on its own -- writers, reports and the CLI are
#: downstream of the decision -- so a stored build older than the branch is still
#: a before side when nothing in these four paths has changed since.
DECIDING_PATHS: tuple[str, ...] = (
    "src/brightway_flows/merge",
    "src/brightway_flows/transformers",
    "src/brightway_flows/flow_layers",
    "src/brightway_flows/data",
)

#: Exactly what `compare_merge_outcomes.py` reads, spelled as the select that
#: produces it.  A table listed whole is one it reads whole; the two large ones
#: are narrowed to the columns it names, which is the whole of why an extract is
#: 2% of a build.
EXTRACT_TABLES: dict[str, str] = {
    "merge_outcomes": "select * from merge_outcomes",
    "flow_objects": "select flow_object_id, pref_label_value from flow_objects",
    "elementary_flows": (
        "select uuid, pref_label_value, unit, context_display, lcia_factor_count,"
        " is_deprecated from elementary_flows"
    ),
    "pipeline_runs": "select * from pipeline_runs",
    "merge_run_inputs": "select * from merge_run_inputs",
}

#: Tables an older build may not have, which are absent rather than wrong.
#: `merge_run_inputs` arrived with #308, and a build from before it compares as
#: it always did -- `compare_merge_outcomes.py` already treats it as optional.
OPTIONAL_TABLES = frozenset({"merge_run_inputs"})


def shared_data_dir() -> Path:
    """The machine-wide data directory, ignoring `BRIGHTWAY_FLOWS_DATA_DIR`.

    Read from `brightway_flows.data_dir` rather than from `brightway_flows.filesystem`,
    the same way and for the same reason as `tools/seed_data_dir.py`: by the
    time this is worth running the variable points at the worktree holding the
    *after* side, and honouring it would ask that worktree about itself.
    """
    return machine_data_dir()


def archive_dir(shared: Path) -> Path:
    return shared / "base-builds"


def archived_path(shared: Path, commit: str) -> Path:
    """Where a commit's extract lives.  Named by commit, because that is the question."""
    return archive_dir(shared) / f"{commit}.sqlite3"


def git(*args: str, cwd: Path | None = None) -> str:
    """Git, or a failure loud enough to stop.

    Nothing here is worth guessing at: a check that cannot say which commit it is
    asking about has no answer to give.
    """
    done = subprocess.run(
        ["git", "-C", str(cwd or REPO_ROOT), *args],
        capture_output=True,
        text=True,
        check=False,
    )
    if done.returncode != 0:
        raise SystemExit(
            f"git {' '.join(args)} failed:\n{done.stderr.strip() or done.stdout.strip()}"
        )
    return done.stdout.strip()


def wanted_commit(ref: str | None, fetch: bool) -> str:
    """The commit a before side should be a build of.

    Where the branch left `main`, by default, rather than `main` itself: that is
    the commit the diff is supposed to attribute nothing to, and on `main` the
    two are the same answer.
    """
    if fetch:
        git("fetch", "--quiet", "origin")
    if ref:
        return git("rev-parse", ref)
    return git("merge-base", "origin/main", "HEAD")


def stamp(database: Path) -> tuple[str, bool] | None:
    """``(commit, dirty)`` a build recorded, or None where it does not say.

    The same three cases `compare_merge_outcomes.py` folds into one: a build
    older than #101, one made outside a repository, one whose git would not
    answer.  None of them can be published as a build of anything.
    """
    if not database.exists():
        return None
    connection = sqlite3.connect(f"file:{database}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        rows = connection.execute("select * from pipeline_runs limit 1").fetchall()
    except sqlite3.OperationalError:
        return None
    finally:
        connection.close()
    if not rows:
        return None
    fields = dict(rows[0])
    commit = fields.get("git_commit") or ""
    if not commit:
        return None
    return commit, bool(fields.get("git_dirty"))


def is_ancestor(earlier: str, later: str) -> bool | None:
    """Answered by exit status -- 0 yes, 1 no, anything else an error.

    None for the error, and it must not read as "no": a git that would not
    answer has not said the stored build is too new.
    """
    done = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "merge-base", "--is-ancestor", earlier, later],
        capture_output=True, text=True, check=False,
    )
    if done.returncode in (0, 1):
        return done.returncode == 0
    return None


def deciding_commits(earlier: str, later: str) -> list[str]:
    """Commits between two revisions that could move a row, newest first."""
    log = git("log", "--oneline", f"{earlier}..{later}", "--", *DECIDING_PATHS)
    return log.splitlines() if log else []


def survey(shared: Path, wanted: str) -> tuple[str | None, list[str]]:
    """The stored build's commit if it answers for `wanted`, and why not if it does not.

    Returning the commit rather than True: where the stored build is older than
    the branch's base and nothing between them moves a row, it is still a before
    side, and it is archived under the commit it *is* -- never under the one it
    was asked about, which would be a file saying it is a build it is not.
    """
    recorded = stamp(shared / "consensus-flows.sqlite3")
    if recorded is None:
        return None, [
            "the stored build does not say which revision it came from"
            " (older than #101, or made outside a repository)"
        ]
    commit, dirty = recorded
    if dirty:
        return None, [
            f"the stored build came from a modified tree, so it is not a build of {commit[:12]}"
        ]
    if commit == wanted:
        return commit, []

    ancestry = is_ancestor(commit, wanted)
    if ancestry is None:
        return None, [f"git would not say whether {commit[:12]} is an ancestor of {wanted[:12]}"]
    if not ancestry:
        return None, [
            f"the stored build is {commit[:12]}, which {wanted[:12]} does not descend from,"
            " so the diff would report what this branch does not have"
        ]

    moving = deciding_commits(commit, wanted)
    if moving:
        reasons = [
            f"{len(moving)} commit(s) since {commit[:12]} decide where a row goes:"
        ]
        reasons += [f"    {line}" for line in moving[:5]]
        if len(moving) > 5:
            reasons.append(f"    ... and {len(moving) - 5} more")
        return None, reasons
    return commit, []


def build_worktree(commit: str, path: Path) -> Path:
    """A real checkout of `commit`, because an archive of one stamps wrongly.

    `git archive <commit> | tar -x` was the recipe, and it cannot work.  The
    extracted tree has no `.git`, so `git_revision()` -- which runs `git -C
    REPO_ROOT rev-parse HEAD` against the tree -- has git search upward: inside
    the repository it reports the *outer* worktree's HEAD, so the before side is
    stamped as the branch it is meant to be compared against, and outside one it
    reports nothing at all.  Probed on 2026-08-15: an archive of `060c024`
    extracted in a worktree stamped that worktree's `9e6cf5f`.

    A worktree is a real checkout with a real `.git` file, so the stamp is the
    commit asked for.  Detached, because nothing here should move a branch.
    """
    if (path / ".git").exists():
        git("checkout", "--quiet", "--detach", commit, cwd=path)
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        git("worktree", "add", "--quiet", "--detach", str(path), commit)
    if git("status", "--porcelain", cwd=path):
        raise SystemExit(f"{path} is not clean, so a build of it is not a build of {commit[:12]}")
    return path


def build_environment(tree: Path, shared: Path) -> dict[str, str]:
    """The checkout's code, writing the shared directory.

    `PYTHONPATH` shadows the installed package rather than the tree being
    installed, which is cheap and is what the skill's recipe does.  Shared by
    the build and the characterisation so the second cannot quietly run against
    a different checkout than the first.
    """
    return {
        **os.environ,
        "BRIGHTWAY_FLOWS_DATA_DIR": str(shared),
        "PYTHONPATH": str(tree / "src"),
    }


def run_build(tree: Path, shared: Path, sources: tuple[str, ...]) -> None:
    """Build that tree's code into the shared directory, having proved it is that code.

    The `PYTHONPATH` shadowing is silent when it fails, because a build against
    the wrong checkout looks exactly like a build against the right one.  So the
    import is asserted first, in the same interpreter configuration the build
    will run in.
    """
    environment = build_environment(tree, shared)
    proof = subprocess.run(
        [sys.executable, "-c", "import brightway_flows as m; print(m.__file__)"],
        capture_output=True, text=True, check=False, env=environment, cwd=tree,
    )
    resolved = proof.stdout.strip()
    if proof.returncode != 0 or not resolved.startswith(str(tree)):
        raise SystemExit(
            f"brightway_flows resolves to {resolved or proof.stderr.strip()}, "
            f"not to {tree}; the build would be of the wrong code"
        )

    command = ["brightway-flows", "build"]
    for source in sources:
        command += ["--source", source]
    print(f"$ {' '.join(command)}")
    done = subprocess.run(command, check=False, env=environment, cwd=tree)
    if done.returncode != 0:
        raise SystemExit(f"build failed with status {done.returncode}")


def run_characterise(tree: Path, shared: Path) -> bool:
    """Match the published factors onto the flows the build just wrote.

    Separate from :func:`run_build` and reported separately, because the two
    fail differently.  A build that fails leaves no before side and there is
    nothing to do but stop.  A characterisation that fails -- almost always
    `fetch-lcia ecoinvent-3.12` never having run -- leaves a complete build
    whose `lcia_*` tables are missing, which is worth an exit status and is not
    worth throwing the build away over.  So this answers rather than raises, and
    the caller has already archived the extract by the time it is asked.
    """
    command = ["brightway-flows", "characterise"]
    print(f"$ {' '.join(command)}")
    done = subprocess.run(
        command, check=False, env=build_environment(tree, shared), cwd=tree
    )
    if done.returncode != 0:
        print(f"\ncharacterise failed with status {done.returncode}")
        return False
    return True


def extract(database: Path, destination: Path) -> Path:
    """Write the tables a comparison reads, and nothing else.

    Through a temporary file and `os.replace`, so an interrupted extract does
    not leave a short database under a commit's name -- which would read as that
    commit having decided nothing about the rows it is missing.
    """
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(".sqlite3.tmp")
    temporary.unlink(missing_ok=True)
    connection = sqlite3.connect(f"file:{database}?mode=ro", uri=True)
    try:
        connection.execute("attach database ? as extract", (str(temporary),))
        for table, select in EXTRACT_TABLES.items():
            try:
                connection.execute(f"create table extract.{table} as {select}")
            except sqlite3.OperationalError:
                if table not in OPTIONAL_TABLES:
                    raise
        connection.commit()
    finally:
        connection.close()
    os.replace(temporary, destination)
    return destination


def prune(shared: Path, keep: int) -> list[Path]:
    """Drop the oldest extracts past `keep`, and say which.

    By modification time rather than by ancestry: an archive is a record of what
    was built, and asking git to rank commits it may no longer have is a way to
    delete the one file that could still answer.
    """
    directory = archive_dir(shared)
    if not directory.is_dir():
        return []
    extracts = sorted(directory.glob("*.sqlite3"), key=lambda path: path.stat().st_mtime)
    removed = extracts[: max(0, len(extracts) - keep)]
    for path in removed:
        path.unlink()
    return removed


def human(size: int) -> str:
    return f"{size / 1e6:.0f} MB"


def publish(shared: Path, commit: str, keep: int) -> Path:
    database = shared / "consensus-flows.sqlite3"
    destination = archived_path(shared, commit)
    if destination.exists():
        print(f"\nBefore side  {destination}  ({human(destination.stat().st_size)}, already copied)")
        return destination
    extract(database, destination)
    print(
        f"\nBefore side  {destination}"
        f"  ({human(destination.stat().st_size)} copied from a {human(database.stat().st_size)} build)"
    )
    for removed in prune(shared, keep):
        print(f"Pruned       {removed.name}")
    return destination


def report(args: argparse.Namespace) -> int:
    shared = args.shared.expanduser().resolve()
    wanted = wanted_commit(args.ref, args.fetch)
    print(f"This branch left main at  {wanted[:12]}  {git('log', '-1', '--format=%s', wanted)}")
    print(f"Stored build in           {shared}")

    usable, reasons = survey(shared, wanted)
    if usable:
        note = "" if usable == wanted else " (older, but nothing since it moves a row)"
        print(f"Stored build is           {usable[:12]}{note}")
        publish(shared, usable, args.keep)
        print(
            "\n    uv run python tools/compare_merge_outcomes.py base "
            "$BRIGHTWAY_FLOWS_DATA_DIR/consensus-flows.sqlite3"
        )
        return 0

    print("\nTHE STORED BUILD IS NOT A BEFORE SIDE FOR THIS BRANCH")
    for reason in reasons:
        print(f"  -- {reason}")

    sources = " ".join(f"--source {source}" for source in args.source)
    if not args.build:
        print(
            f"\n  Build one with:  uv run python tools/refresh_base_build.py --build"
            f"\n  which runs, from a checkout of {wanted[:12]} into {shared},"
            f"\n  replacing what is there:"
            f"\n    brightway-flows build {sources}"
            f"\n    brightway-flows characterise"
        )
        return 1

    tree = build_worktree(wanted, args.worktree.expanduser().resolve())
    print(f"\nBuilding {wanted[:12]} from {tree}")
    run_build(tree, shared, tuple(args.source))
    recorded = stamp(shared / "consensus-flows.sqlite3")
    if recorded != (wanted, False):
        print(f"\nThe build stamped {recorded}, not ({wanted[:12]}, clean); not copying it.")
        return 2
    publish(shared, wanted, args.keep)

    # The before side is archived first: `characterise` writes only `lcia_*`
    # tables, none of which the extract holds, so the comparison has everything
    # it will ever have before this runs and keeps it whether or not it works.
    print()
    if not run_characterise(tree, shared):
        print(
            f"\n{shared / 'consensus-flows.sqlite3'} has no factors on it."
            "\n  The before side above is unaffected -- characterisation writes"
            " no table a comparison reads --"
            "\n  but the review webapp and `assess` read this build too, so"
            " finish it with:"
            "\n    brightway-flows fetch-lcia ecoinvent-3.12"
            "\n    brightway-flows characterise"
        )
        return 2
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--ref", default=None,
        help="What a before side should be a build of. Defaults to where this branch left main.",
    )
    parser.add_argument("--fetch", action="store_true", help="Fetch origin before resolving.")
    parser.add_argument(
        "--build", action="store_true",
        help="Build one where the stored build does not answer. Hours, not seconds.",
    )
    parser.add_argument(
        "--source", action="append", default=None,
        help=f"Source list a build merges. Repeatable. Defaults to {', '.join(DEFAULT_SOURCES)}.",
    )
    parser.add_argument("--keep", type=int, default=DEFAULT_KEEP, help=f"Extracts to keep. Defaults to {DEFAULT_KEEP}.")
    parser.add_argument("--shared", type=Path, default=None, help="Data directory to read. Defaults to the platform one.")
    parser.add_argument(
        "--worktree", type=Path, default=None,
        help="Where --build checks the commit out. Defaults to base-build-tree/ beside the repository.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    args.shared = args.shared or shared_data_dir()
    args.worktree = args.worktree or REPO_ROOT.parent / "base-build-tree"
    args.source = args.source or list(DEFAULT_SOURCES)
    return report(args)


if __name__ == "__main__":
    raise SystemExit(main())
