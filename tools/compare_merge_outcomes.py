"""What two builds decided differently about the same source rows.

`verify_run.py` answers "did any artifact change", by hash, which is the question
a refactor asks.  `assess` answers "is this one build right", against
`expectations/`.  Neither answers the question a change to the *matching* asks,
which is **which rows moved, and where to** -- and that question is asked of
every such change, so it stops being retyped here.

    uv run python tools/compare_merge_outcomes.py BEFORE.sqlite3 AFTER.sqlite3
    uv run python tools/compare_merge_outcomes.py BEFORE AFTER --detail
    uv run python tools/compare_merge_outcomes.py BEFORE AFTER --list bafu

The before side may be *named* rather than found: `base` is where this branch
left `main`, and any commit-ish is that commit, both resolved against the
archive `tools/refresh_base_build.py` keeps.  The archive holds extracts rather
than whole builds -- the tables below and nothing else, 44 MB against 2.0 GB --
which this reads as though they were builds, because they hold every column it
asks for.

    uv run python tools/compare_merge_outcomes.py base .data/consensus-flows.sqlite3

It reads two databases and writes to neither.  A build leaves its database
behind, so keeping the two files is what makes the comparison repeatable without
re-running anything: every question below is answered from what is already on
disk, in about a second, however long the builds took.

**The comparison is only as honest as the pair.**  Two builds of the same source
lists, from the same extracted vendor files, differing in one revision, is what
this is for.  A build that merged a different `--source` set reports every row of
the missing list as gone; a bounded merge (`--max-rows`) reports the rows it did
not read the same way.  Both are visible in `merge_run_inputs`, which this prints
first for exactly that reason -- rather than guessing whether the pair is
comparable, read the header.

Which *code* built each side is the other half of that, and it used to be
guessed at.  Comparing a branch against a stored build of an older `main`
reported eight halocarbon rows as having moved, none of them the branch's doing:
the stored build predated #90 and #95, and the diff was attributing those
merges to the change under review.  It was caught only because the rows were
visibly unrelated to water (#101).

So a build stamps the revision it came from, and this refuses a pair that cannot
answer the question asked of it -- either side unstamped or built from a modified
tree, both sides from the same commit, or a before side that is not an ancestor
of the after side.  It prints why and stops, rather than printing a diff that
reads as an answer.  `--anyway` compares them regardless, for a pair that is
deliberate: the same code over different inputs, or two branches neither of
which descends from the other.

With that check in place the before side no longer has to be rebuilt per pull
request.  A stored build of the branch's merge base is reusable, and this says
so when it is not.
"""

from __future__ import annotations

import argparse
import collections
import sqlite3
import subprocess
from pathlib import Path
from typing import Any

from brightway_flows.data_dir import machine_data_dir

#: The repository the two builds claim to have come from, for asking git how
#: their commits are related.  `tools/verify_run.py` spells it the same way.
REPO_ROOT = Path(__file__).resolve().parent.parent

#: What identifies a decision, and what counts as the decision having changed.
#: `basis` and `basis_value` are deliberately *not* here: a row that reached the
#: same flow on better evidence has not moved, and a run that reported every such
#: row would bury the rows that did.  `--detail` prints the basis anyway.
DECISION_FIELDS = ("outcome", "reason", "flow_object_id", "target_elementary_flow_id")

OUTCOME_COLUMNS = (
    "list_name, list_version, source_uuid, source_name, source_context_json, "
    "source_unit, outcome, reason, flow_object_id, target_elementary_flow_id, "
    "basis, has_unit_mismatch"
)


class Build:
    """One build's database, read-only, with the views this needs."""

    def __init__(self, path: Path) -> None:
        self.path = path
        if not path.exists():
            raise SystemExit(f"no database at {path}")
        self.connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        self.connection.row_factory = sqlite3.Row

    def _rows(self, query: str) -> list[sqlite3.Row]:
        return list(self.connection.execute(query))

    @property
    def outcomes(self) -> dict[tuple[str, str, str], sqlite3.Row]:
        """Every decision, keyed by the list *version* as well as the list.

        The version is part of the key because it is part of the identity of a
        decision.  ecoinvent keeps a flow's uuid stable across releases -- the
        property `ecoinvent-match-overrides.json` is built on -- so a build
        merging 3.12 and 3.8 holds two rows under one uuid, deciding the same
        flow twice.  Keyed on `(list_name, source_uuid)` the second overwrote
        the first, and 3,968 of the 2026-08-17 build's 14,274 rows, 27.8% of
        it, were never compared to anything: not reported unchanged, not
        looked at.  A change that moved rows only in the older version could
        report `ROWS DECIDED DIFFERENTLY: 0` (#317).
        """
        return {
            (row["list_name"], row["list_version"], row["source_uuid"]): row
            for row in self._rows(f"select {OUTCOME_COLUMNS} from merge_outcomes")
        }

    @property
    def substances(self) -> dict[str, str]:
        return {
            row["flow_object_id"]: row["pref_label_value"]
            for row in self._rows(
                "select flow_object_id, pref_label_value from flow_objects"
            )
        }

    @property
    def flows(self) -> dict[str, tuple[str, str, str, int, int]]:
        return {
            row["uuid"]: (
                row["pref_label_value"],
                row["unit"],
                row["context_display"],
                row["lcia_factor_count"] or 0,
                row["is_deprecated"] or 0,
            )
            for row in self._rows(
                "select uuid, pref_label_value, unit, context_display,"
                " lcia_factor_count, is_deprecated from elementary_flows"
            )
        }

    @property
    def inputs(self) -> list[sqlite3.Row]:
        try:
            return self._rows("select * from merge_run_inputs")
        except sqlite3.OperationalError:  # a build older than #308
            return []

    @property
    def revision(self) -> tuple[str, bool] | None:
        """``(commit, dirty)``, or None where the build does not say.

        None covers three cases that are one case to a reader: a build older
        than #101, a build made from an installed copy with no repository, and
        a build whose git would not answer.  All three mean the same thing --
        this database cannot say what code produced it -- and none of them is
        safe to compare against.
        """
        try:
            rows = self._rows("select * from pipeline_runs limit 1")
        except sqlite3.OperationalError:  # not a build database at all
            return None
        if not rows:
            return None
        fields = dict(rows[0])
        commit = fields.get("git_commit") or ""
        if not commit:
            return None
        return commit, bool(fields.get("git_dirty"))


def _git(*args: str) -> subprocess.CompletedProcess[str] | None:
    """Git in this repository, or None where it would not run at all."""
    try:
        return subprocess.run(
            ["git", "-C", str(REPO_ROOT), *args],
            capture_output=True, text=True, check=False, timeout=10,
        )
    except (OSError, subprocess.SubprocessError):  # pragma: no cover
        return None


def _known(commit: str) -> bool:
    """Whether this repository holds *commit*.

    A build carried in from another clone, or from a branch never fetched here,
    stamps a commit this repository cannot place.  That is not a match and not a
    mismatch: it is a question git has not been given enough to answer, which is
    its own reason to refuse.
    """
    done = _git("cat-file", "-e", f"{commit}^{{commit}}")
    return done is not None and done.returncode == 0


def _subject(commit: str) -> str:
    done = _git("log", "-1", "--format=%s", commit)
    return done.stdout.strip() if done is not None and not done.returncode else ""


def _is_ancestor(earlier: str, later: str) -> bool | None:
    """Whether *earlier* is an ancestor of *later*; None if git could not say.

    `merge-base --is-ancestor` answers by exit status -- 0 yes, 1 no, anything
    else an error, which must not read as "no".
    """
    done = _git("merge-base", "--is-ancestor", earlier, later)
    if done is None or done.returncode not in (0, 1):
        return None
    return done.returncode == 0


def _comparability(before: Build, after: Build) -> list[str]:
    """Every reason this pair cannot answer "what did the change do".

    Empty means the diff below means what it appears to mean: one commit's worth
    of code, on the same inputs.  Each reason is a way the diff would otherwise
    report somebody else's commits, or the reader's own uncommitted edits, as
    the change under review.
    """
    reasons: list[str] = []
    revisions = {"before": before.revision, "after": after.revision}
    for label, revision in revisions.items():
        if revision is None:
            reasons.append(
                f"the {label} build does not say which revision it came from"
            )
        elif revision[1]:
            reasons.append(
                f"the {label} build came from a modified tree, so it is not a "
                f"build of {revision[0][:12]}"
            )
    if revisions["before"] is None or revisions["after"] is None:
        return reasons

    earlier, later = revisions["before"][0], revisions["after"][0]
    if earlier == later:
        reasons.append(
            f"both builds came from {earlier[:12]}, so nothing between them is a "
            "change to the code"
        )
        return reasons

    unplaceable = [commit for commit in (earlier, later) if not _known(commit)]
    if unplaceable:
        reasons.append(
            "this repository has no "
            + " or ".join(commit[:12] for commit in unplaceable)
            + ", so which build is ahead of the other cannot be checked"
        )
        return reasons

    ancestry = _is_ancestor(earlier, later)
    if ancestry is None:
        reasons.append(
            f"git would not say whether {earlier[:12]} is an ancestor of "
            f"{later[:12]}"
        )
    elif not ancestry:
        reasons.append(
            f"{earlier[:12]} is not an ancestor of {later[:12]}, so the diff "
            "mixes what the after build changed with what it does not have"
        )
    return reasons


def _print_revisions(before: Build, after: Build) -> None:
    print("WHICH CODE BUILT THEM")
    for label, build in (("before", before), ("after", after)):
        revision = build.revision
        if revision is None:
            print(
                f"  {label:7} does not say  (a build before #101, or one made "
                "outside a repository)"
            )
            continue
        commit, dirty = revision
        state = "MODIFIED TREE" if dirty else "clean"
        subject = _subject(commit)
        tail = f"  {subject}" if subject else "  (not a commit in this repository)"
        print(f"  {label:7} {commit[:12]}  {state:13}{tail}")
    print()


def _decision(row: sqlite3.Row) -> tuple[Any, ...]:
    return tuple(row[field] for field in DECISION_FIELDS)


def _state(row: sqlite3.Row) -> str:
    return f"{row['outcome']}/{row['reason']}" if row["reason"] else str(row["outcome"])


def _print_inputs(before: Build, after: Build) -> None:
    print("WHAT WAS MERGED")
    for label, build in (("before", before), ("after", after)):
        rows = build.inputs
        if not rows:
            print(f"  {label:7} {build.path}  (no merge_run_inputs; a build before #308)")
            continue
        for row in rows:
            fields = dict(row)
            name = fields.get("source_key") or fields.get("list_name") or "?"
            read = fields.get("rows_read")
            available = fields.get("rows_available")
            bound = f"  {read} of {available}" if read is not None else ""
            print(f"  {label:7} {name}{bound}")
    print()


def _print_outcome_counts(before: Build, after: Build, lists: set[str] | None) -> None:
    b, a = before.outcomes, after.outcomes
    print("OUTCOMES, PER LIST")
    names = sorted({key[0] for key in (set(b) | set(a))})
    for name in names:
        if lists and name not in lists:
            continue
        for label, rows in (("before", b), ("after", a)):
            counts = collections.Counter(
                _state(row) for key, row in rows.items() if key[0] == name
            )
            shown = ", ".join(f"{k}={v}" for k, v in sorted(counts.items()))
            print(f"  {name:16} {label:7} {shown}")
    print()


def _print_moved(
    before: Build, after: Build, lists: set[str] | None, detail: bool
) -> None:
    b, a = before.outcomes, after.outcomes
    only_before = sorted(set(b) - set(a))
    only_after = sorted(set(a) - set(b))
    if only_before or only_after:
        print(
            f"  !! {len(only_before)} rows only in the before build and "
            f"{len(only_after)} only in the after build -- the pair is not "
            "comparable row for row"
        )
        print()

    moved = [
        (key, b[key], a[key])
        for key in sorted(set(b) & set(a))
        if (not lists or key[0] in lists) and _decision(b[key]) != _decision(a[key])
    ]
    print(f"ROWS DECIDED DIFFERENTLY: {len(moved)}")
    shape = collections.Counter(
        (key[0], _state(bb), _state(aa)) for key, bb, aa in moved
    )
    for (name, was, now), count in shape.most_common():
        print(f"  {count:6}  {name:12} {was:42} -> {now}")
    print()

    by_name = collections.Counter((key[0], bb["source_name"]) for key, bb, _a in moved)
    print("  by source name")
    for (name, source_name), count in sorted(by_name.items()):
        print(f"  {count:6}  {name:12} {source_name}")
    print()

    if not detail:
        return
    before_flows, after_flows = before.flows, after.flows
    before_names, after_names = before.substances, after.substances
    print("EVERY ROW THAT MOVED")
    for key, bb, aa in moved:
        was = before_flows.get(bb["target_elementary_flow_id"], ("-", "-", "-", 0, 0))
        now = after_flows.get(aa["target_elementary_flow_id"], ("-", "-", "-", 0, 0))
        print(
            f"  {bb['source_name']}  {bb['source_context_json']}  {bb['source_unit']}\n"
            f"      before  {_state(bb):38} "
            f"{before_names.get(bb['flow_object_id'], '-')!r} "
            f"{was[2]} [{was[1]}] factors={was[3]}\n"
            f"      after   {_state(aa):38} "
            f"{after_names.get(aa['flow_object_id'], '-')!r} "
            f"{now[2]} [{now[1]}] factors={now[3]}  basis={aa['basis']}"
        )
    print()


def _print_published(before: Build, after: Build) -> None:
    b, a = before.flows, after.flows
    bs, as_ = before.substances, after.substances

    def characterised(flows: dict[str, tuple[str, str, str, int, int]]) -> int:
        return sum(1 for value in flows.values() if value[3])

    def deprecated(flows: dict[str, tuple[str, str, str, int, int]]) -> int:
        return sum(1 for value in flows.values() if value[4])

    print("WHAT WAS PUBLISHED")
    print(f"  flows          {len(b):>7} -> {len(a)}")
    print(f"  characterised  {characterised(b):>7} -> {characterised(a)}")
    print(f"  deprecated     {deprecated(b):>7} -> {deprecated(a)}")
    print(f"  substances     {len(bs):>7} -> {len(as_)}")
    print()

    changed = [
        (uuid, b[uuid], a[uuid])
        for uuid in sorted(set(a) & set(b))
        if b[uuid][3] != a[uuid][3] or b[uuid][4] != a[uuid][4]
    ]
    print(f"  flows whose factor count or deprecation changed: {len(changed)}")
    for uuid, was, now in changed[:40]:
        print(
            f"    {now[0]!r} {now[2]} [{now[1]}]  factors {was[3]}->{now[3]}"
            f"  deprecated {was[4]}->{now[4]}"
        )
    print()

    for label, gone in (
        ("flows only in the before build", sorted(set(b) - set(a))),
        ("flows only in the after build", sorted(set(a) - set(b))),
    ):
        source = b if "before" in label else a
        print(f"  {label}: {len(gone)}")
        for uuid in gone[:40]:
            value = source[uuid]
            print(f"    {value[0]!r} {value[2]} [{value[1]}] factors={value[3]}")
    print()

    for label, ids in (
        ("substances only in the before build", sorted(set(bs) - set(as_))),
        ("substances only in the after build", sorted(set(as_) - set(bs))),
    ):
        names = bs if "before" in label else as_
        print(f"  {label}: {len(ids)}")
        for object_id in ids[:40]:
            print(f"    {names[object_id]!r}")
    print()


def _archive_dir() -> Path:
    """Where `tools/refresh_base_build.py` keeps its extracts.

    Asked of `data_dir.machine_data_dir` the way that tool asks it, rather than from
    `brightway_flows.filesystem`, whose `DATA_DIR` honours
    `BRIGHTWAY_FLOWS_DATA_DIR` -- which, when this is worth running, points
    at the worktree holding the *after* side.
    """
    return machine_data_dir() / "base-builds"


def resolve_before(value: str) -> Path:
    """A path as given, or a commit looked up in the archive.

    An existing path wins, always: a file named `base` in the working directory
    is still the file the reader typed.  Otherwise `base` means where this
    branch left `main` -- `git merge-base origin/main HEAD`, which is the commit
    the before side is supposed to be built from -- and anything else is
    whatever git makes of it.

    A miss says which commit it looked for and how to make it, because the
    answer is one command and the alternative is the reader building the before
    side by hand again.
    """
    path = Path(value)
    if path.exists():
        return path

    reference = "merge-base origin/main HEAD" if value == "base" else f"rev-parse {value}"
    resolved = _git(*reference.split())
    if resolved is None or resolved.returncode != 0:
        raise SystemExit(f"{value} is neither a file nor a commit this repository knows")
    commit = resolved.stdout.strip()

    archived = _archive_dir() / f"{commit}.sqlite3"
    if not archived.exists():
        raise SystemExit(
            f"no archived build of {commit[:12]} ({_subject(commit) or 'unknown commit'})\n"
            f"  looked in {archived.parent}\n"
            f"  make one with:  uv run python tools/refresh_base_build.py {commit}"
        )
    return archived


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "before",
        help=(
            "the database built without the change: a path, or `base` for where "
            "this branch left main, or any commit, looked up in the archive"
        ),
    )
    parser.add_argument("after", type=Path, help="the database built with it")
    parser.add_argument(
        "--list",
        dest="lists",
        action="append",
        help="restrict the row comparison to this source list; repeatable",
    )
    parser.add_argument(
        "--detail",
        action="store_true",
        help="print every row that moved, with the flow it left and the one it reached",
    )
    parser.add_argument(
        "--anyway",
        action="store_true",
        help="compare a pair the revisions say cannot answer the question",
    )
    args = parser.parse_args()

    before, after = Build(resolve_before(args.before)), Build(args.after)
    lists = set(args.lists) if args.lists else None

    _print_inputs(before, after)
    _print_revisions(before, after)
    reasons = _comparability(before, after)
    if reasons:
        print("THIS PAIR CANNOT ANSWER WHAT THE CHANGE DID")
        for reason in reasons:
            print(f"  -- {reason}")
        print()
        if not args.anyway:
            print(
                "  Rebuild whichever side a reason names -- the before side from "
                "a commit\n  the after side descends from -- or pass --anyway."
            )
            return 2
        print("  Comparing them regardless, because --anyway was given.")
        print()

    _print_outcome_counts(before, after, lists)
    _print_moved(before, after, lists, args.detail)
    _print_published(before, after)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
