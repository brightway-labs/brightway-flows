---
name: fixing-a-matching-defect
description: Use when a source row reaches the wrong consensus flow, several flows, or none — anything that changes where the merge puts a row, whether the change is a rule in `merge/`, a curated file in `data/`, or a manual override. Covers naming the row before touching code, measuring what the build does with it today, writing the expectation and the unit test before the fix, and the two builds that say what moved.
---

# Fixing a matching defect

The rules are `AGENTS.md` 22–26; the reasoning is
[`docs/reference/conventions.md`](../../../docs/reference/conventions.md) §9.
This is the order to do the work in. It is written down because the tempting
order — write the fix, then measure it — hides the two things that go wrong most
often: the defect is not what the issue said it was, and the fix moves rows
nobody was looking at.

Steps 1 and 2 come before any code. They are cheap, and both have changed what
the fix turned out to be.

## 1. Name the row

Not "BAFU's water rows". One row, by uuid, with its name, its compartment as the
vendor writes it, its unit and its registry number — and what it *should* reach,
stated as a flow that exists.

    BAFU  Water, lake   213c9949-…   resources / in water   m3   7732-18-5
      should reach:  Lake water, Resource → Water → Lake

A defect you cannot write in those terms is not understood yet, and the issue
that describes it will be rewritten once it is. If several rows fail, name the
one whose failure is clearest and say how many share it.

## 2. Measure what the build does with it today

Read the row out of `merge_outcomes`. Do not reason from the code about what it
must be doing.

**Ask the stored build first, with one command.** A build records the commit it
came from (#101), and the shared data directory holds one — so before running
anything, ask whether what is stored answers for this branch:

    uv run python tools/refresh_base_build.py

It exits 0 having copied the 44 MB a comparison reads into
`base-builds/<commit>.sqlite3`, and that is the whole beginning of an
investigation done in a second rather than in the ten minutes or more a build
that merges a source list takes. It exits 1 with the reason when what is stored
cannot answer, which is one of three:

- **it does not say which revision it came from, or came from a modified tree.**
  Unstamped is a build older than #101 or one made outside a repository; a
  modified tree is not a build of its commit.
- **this branch does not descend from it**, so a diff against it would report
  what the branch does not have.
- **commits since it decide where a row goes** — `merge/`, `transformers/`,
  `flow_layers/` or the curated `data/`. It names them. A commit anywhere else in
  `src/` is downstream of the decision and leaves the stored build usable, which
  is why the answer is usually yes.

Where it is no, `--build` makes one — hours rather than seconds, which is why it
is opt-in — into the shared directory, from a real checkout of the commit:

    uv run python tools/refresh_base_build.py --build

That build is also step 6's before side, so this is read once and used twice.
Its `--source` list — ecoinvent 3.12, ecoinvent 3.8 and BAFU 2026 v1 — is what a
comparison needs both sides to have, so a build of your own has to merge the
same three, and it goes in **your worktree's own `.data`**, made by
`tools/seed_data_dir.py`. The shared data directory belongs to `main`: a build
of your branch there is destroyed by the next refresh, and swaps the extracted
lists under anything else reading them, which is #82 again.

BAFU is on that list because it is the only merged list whose flows came out of
SimaPro, and the name-matching strategies that undo SimaPro's habits run on no
other list. If the row you are chasing is one of them, a pair of builds that
left BAFU out would report nothing at all.

`--build` also runs `brightway-flows characterise` when the build finishes,
because the shared directory is served and assessed as well as compared, and a
build with no `lcia_*` tables answers "no factors" to both. It runs after the
extract has been copied out, so a missing `fetch-lcia ecoinvent-3.12` leaves
your before side intact — exit status 2 and the two commands that finish it.

**Then read the row**, out of `merge_outcomes` in whichever database answered.
The archived extract carries that table whole, `detail_json` and every scored
candidate included, which is what the rest of this step is about. Read it with
a query; **do not point `assess` at the archive** — it holds the five tables a
comparison reads and no `elementary_flows`, so `assess --database` on it dies
on a missing column. To grade an expectation on the before side (step 3), run
`assess` against the full shared build the archive was copied from, once
`refresh_base_build.py` has said its commit is the branch point:

    uv run brightway-flows assess     # the shared build, stamped with the branch point

`merge_outcomes.detail_json` holds every candidate the selector scored, the
basis it matched on, and the harmonised compartment — which is usually enough to
find that the row fails one stage earlier or later than the issue says. Both
halves of the 2026-08-15 water work were found this way: 50 rows filed under a
compartment tie were in fact failing on a substance tie, and a row the issue said
was unmatched had in fact matched the wrong substance silently.

Record what you found. It goes in the pull request, and it is what the
expectation in step 3 has to fail against.

## 3. Write the expectation, and watch it fail

One file per issue in `expectations/`, named for it, stating what should be true
of the row you named in step 1 — see
[`expectations/README.md`](../../../expectations/README.md) for the vocabulary.
Write it before the fix and run `assess` against the build from step 2. **An
expectation that passes before the fix is testing nothing**, and finding that out
now costs a minute.

Claim the basis as well as the target where the two differ: `{"outcome":
"matched", "basis": "material", "target_name": "Lake water"}` says the curated
assignment answered, and would fail if a later change reached the same flow by
guessing at a name.

`pending: true` is for a claim you are recording and *not* fixing now. A claim
this change makes true is written without it.

## 4. Write the unit test

Against the smallest thing that can answer: the function, not the build. It runs
in milliseconds and says which rule is wrong; the expectation runs in ten minutes
and says the output is wrong. Both, not either.

Test both halves of any rule that refines something. A rule that fills in an
unstated value must be tested for leaving a stated one alone, and that test is
the one that stops it growing into a rule that overrides the source.

## 5. Implement

## 6. Two builds, and diff them

A change to behaviour is judged on a **full build**, compared against a full
build of the commit the branch started at, from the same inputs. Not a bounded
one: `--max-flows` and `--max-rows` bound what is matched, so a rule's side
effects on the rows outside the bound are exactly what they hide. The exception
is a manual override or a curated row with few targets, where nothing outside
the named rows can move.

The before side does not have to be built again if you already have one — and
step 2 already asked. `compare_merge_outcomes.py` takes `base` for "where this
branch left `main`", looks it up in the archive step 2 copied it into, and reads
the 44 MB extract as though it were the build:

    uv run python tools/compare_merge_outcomes.py \
        base $BRIGHTWAY_FLOWS_DATA_DIR/consensus-flows.sqlite3

**Do not build a before side with `git archive`.** The recipe here used to say
`git archive <commit> | tar -x -C .base-tree`, and it cannot work: the extracted
tree has no `.git`, so the build's stamp — `git -C REPO_ROOT rev-parse HEAD` —
has git search upward and report the *outer* worktree's HEAD, which is the very
branch being compared. Probed on 2026-08-15: an archive of `060c024` stamped
`9e6cf5f`. `refresh_base_build.py --build` uses `git worktree add --detach`,
which is a real checkout and stamps the commit asked for.

**Read the two headers before the diff.** `WHAT WAS MERGED` says the pair merged
the same lists, unbounded; `WHICH CODE BUILT THEM` says which revision each side
came from. A pair that cannot answer the question — either side unstamped or
built from a modified tree, both from the same commit, or a before side the after
side does not descend from — is refused with the reason and exit status 2, since
that diff reports somebody else's commits, or your own uncommitted edits, as the
change under review. `--anyway` is for when the pair is deliberate; commit first
is usually the right answer.

`compare_merge_outcomes.py` reads the two databases and writes to neither, so
**keep them**: every further question — which rows, which flows, what happened to
the factors — is answered from what is already on disk in about a second,
however long the builds took. Re-running the pipeline to ask a second question is
the mistake this tool exists to stop.

What the diff has to show:

- **the rows you meant moved, and you can name them** — if the count is round
  and the rows are not enumerable, the rule is broader than the issue;
- **no other row moved**, or every other row that moved is explained. "290 rows
  moved and they are the 290 the table assigns" is a result; "about 300 rows
  moved" is not;
- **what happened to characterisation.** A flow whose factor count changed, or
  whose deprecation changed, is a published number changing. Say so, or say
  plainly that none did.

## 7. Everything else, then record

    uv run pytest
    uvx ruff check --select F821,F401,F811 src/ tests/ tools/
    uv run brightway-flows assess          # every expectation, not just yours
    uv run brightway-flows assess --record # then commit expectations/baseline.json

Read the whole `assess` report, not your own expectation. A fix that makes one
claim true and another false is the ordinary outcome, and an expectation that
turns out to have claimed the wrong thing gets **rewritten, with the reason
recorded in its comment** — keeping its id, so the baseline keeps its history for
that question.

The baseline moves for reasons that are not yours, too, when `main` has moved
since it was last recorded. Say which of its movements are the change's and which
were already there.

## What tends to go wrong

**Reasoning from the code instead of the build.** The pipeline is long enough
that the stage you are reading is often not the stage that decides.

**A rule that reads a name.** Names are the evidence of last resort here, and a
rule that reads one has to say why the curated alternative was not used. A source
row carries its shipped name, its synonyms, and everything enrichment found —
matching on all of them is almost never what is meant, and for water it is 23
names shared by every water row alike.

**Widening a rule to make one more row pass.** Each widening is defensible and
the total is not. The count in step 6 is the check: a rule that moves rows you
cannot enumerate has stopped being the fix for the issue you named.
