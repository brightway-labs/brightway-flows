---
name: reviewing-a-contributed-change
description: Use when reviewing a pull request somebody else wrote — a contributor's fork, or any change not made by following this repository's own skills — that changes where the merge puts a row, a curated file in `data/`, or the transformer chain. Covers checking it out with its own data directory, verifying its claims against our own build rather than its table, the full build, `characterise` and baseline only a maintainer can run, the precedents a contributor will not know, and how to answer.
---

# Reviewing a contributed change

The pull request should already contain what
[`fixing-a-matching-defect`](../fixing-a-matching-defect/SKILL.md) or
[`adding-a-transformer`](../adding-a-transformer/SKILL.md) asks for: the row
named by uuid, what the build did with it before, an expectation that failed
first, a unit test of both halves of the rule, and a two-build diff. Use the
skill that fits as the checklist, and say in the review which item is missing
rather than doing it silently. This page is the rest — what only a maintainer
can do, and what a contributor cannot be expected to know.

The worked case is #472, which wrote CAS numbers on BAFU's `P-cyanophenol` and
on Stepwise's two β-amylene rows through each list's `*-manual-fixes.json`.

## 1. Check it out on its own

    git fetch origin pull/<n>/head:pr-<n>
    git worktree add .claude/worktrees/pr-<n> pr-<n>
    cd .claude/worktrees/pr-<n>
    uv run python tools/seed_data_dir.py
    export BRIGHTWAY_FLOWS_DATA_DIR=$PWD/.data

Its own data directory, as for any branch (`AGENTS.md` 33): a contributor's
code writing the shared one replaces `main`'s build under everyone reading it.

If you may push fixups, check first that you are allowed to:

    gh pr view <n> --json maintainerCanModify,headRepositoryOwner,headRefName

## 2. Check the claims against our build, not the PR's table

The description's table came from the contributor's build, which is usually
not ours (step 3). Ask the stored build of `main` — `refresh_base_build.py`
says in a second whether it answers for the PR's base:

    uv run python tools/refresh_base_build.py

Then, read-only, from `consensus-flows.sqlite3` in the shared directory or the
extract under `base-builds/`:

- **each named row exists and goes where the PR says it goes today** —
  `merge_outcomes` by `source_uuid`, its `outcome`, `basis` and
  `target_elementary_flow_id`. A row the PR says is unmatched may already have
  matched the wrong thing.
- **each stated target exists under the stated registry number** —
  `flow_objects_fts.cas_numbers`, and the flows in `elementary_flows` for that
  `flow_object_id` in the row's compartment. In #472, check that 4-cyanophenol
  and cis- and trans-2-pentene are published under the numbers written, and
  in the compartments BAFU and Stepwise file those rows in.
- **which neighbours the fix could pull rows onto.** A registry number is the
  strongest evidence a row can carry, so a wrong one is silent. Look for
  isomers and near-names — for #472's β-amylenes, 1-pentene, the isomer
  mixture `Pentylene` (25377-72-4) and 2-methyl-2-butene, each its own
  substance — and check that the number written is the one the row's name
  means, not the one beside it.

## 3. Do what the contributor could not

A contributor usually has no licensed ecoinvent, so their build left out the
ecoinvent lists, and they could not run `characterise` — it needs the ecoinvent
Centre's factor file from `fetch-lcia ecoinvent-3.12` — or record
`expectations/baseline.json`, which is only recorded from a full build. Those
three are yours.

Fetch every list the default build merges (the `DEFAULT_SOURCES` in
`tools/refresh_base_build.py`) with `fetch-source`, and with `fetch-lcia` every
list whose manifest in `src/brightway_flows/data/sources/` has an `lcia`
section — ecoinvent-3.12, bafu-2026-v1 and stepwise-2006-1.09 today — into the
PR worktree's `.data`. `characterise` stops on one that is missing. Then:

    uv run brightway-flows build --source ecoinvent-3.13 --source ecoinvent-3.12 ...
    uv run brightway-flows characterise
    uv run brightway-flows assess
    uv run python tools/compare_merge_outcomes.py \
        base $BRIGHTWAY_FLOWS_DATA_DIR/consensus-flows.sqlite3

Same `--source` set as the base build, unbounded. Read the diff as
`fixing-a-matching-defect` step 6 says: the rows meant to move, named, and
nothing else.

**Scope decides how much can move, not whether to measure.** A list's own
manual-fixes file rewrites that list's rows and nothing else, so #472 could
only move BAFU and Stepwise rows — the merge risk of such a fix is low. What it
can still move is published factors: a row that now reaches a characterised
flow brings factors with it, or leaves some behind. Count
`lcia_characterization_factors` rows per `elementary_flow_uuid` on both builds.
Not the `lcia_factor_count` column of `elementary_flows`, and not
`compare_merge_outcomes.py`'s factor section, which reads it: it can read 0 on
flows `characterise` gives factors to.

Then record the baseline and commit it on the PR:

    uv run brightway-flows assess --record

`main` has usually moved since the baseline was last recorded, so say which of
its movements are the PR's and which were already there.

## 4. Check what a contributor will not know

- **A minted flow the fix removes.** When the substance and compartment survive
  on another flow, its entry in
  `src/brightway_flows/data/retired-minted-flow-ids.json` is repointed —
  `replaced_by` and `flow_object_id` — at the surviving flow, as #424 did for
  Fenpropimorph's forestry-soil identifier. Not accepted as a rise in the
  `retired-identifier-unresolved` queue. The loader recomputes each
  replacement and refuses the file if one disagrees, so the entry has to be
  the flow the build mints there. That identifier needs no build: it is
  `minted_elementary_flow_id(flow_object_id, context_iri)` from
  `brightway_flows.domain.elementary_flow`. Check it first on the entry's old
  values, which must give back the old `replaced_by`. For #472's
  P-cyanophenol, `fo-d9eedca3b8d92223` in Ground → Industrial gives
  `95a020d9…`.
- **Counts in a data file's `description`.** "Nineteen of these" in
  `bafu-2026-v1-manual-fixes.json` is prose, and `tests/test_documentation.py`
  checks pages, not data files. A fix that adds an entry leaves it wrong.
- **Tests that pin the engine rather than the fix.** A test that asserts how
  manual fixes are applied in general passes before the change and says
  nothing about it. Ask for one that fails without the new entries.
- **The rest of the chain's moving parts**, for a transformer: the
  `answers_per_flow` decision, and the registration points, tests and page in
  `adding-a-transformer` steps 4 and 5. A contributor following the code
  rather than the skill usually misses `WHOLE_LIST` and the page.

## 5. Tests and static checks, as a difference

    uv run pytest -q
    uvx ruff check --select F821,F401,F811 src tests tools

Run the suite in the PR worktree and in a checkout of `main`, both with the
same `BRIGHTWAY_FLOWS_DATA_DIR`. Tests that need a build skip or fail on an
empty data directory either way; those are the environment. Judge only the
failures `main` does not have.

## 6. Answer

Either a review, or fixups:

- **A review** is posted on GitHub and read by the contributor and anyone
  watching. Draft it, show it to the user, and post only when they say so.
  Name the row, the number and the build each finding came from.
- **Fixups**, when `maintainerCanModify` is true, go on the contributor's
  branch as separate commits, one per finding, so the contributor can see what
  changed and why. Re-measure after them: a repointed retirement or a
  corrected number is a new build.

Commit before building. A build from a modified tree is stamped as such and
`compare_merge_outcomes.py` refuses it, and a baseline recorded from one
describes code nobody can check out.

## What tends to go wrong

**Trusting the table.** The numbers in the description were measured on a
build without ecoinvent, and possibly from an older `main`. Every number in
the review should come from a build you made or stored.

**Reading a factor change from the wrong column.** `lcia_factor_count` has
read 0 for `Arsenic, ion` while the factor table held 15 to 22 rows per
compartment for it. A claim about published factors is a count of
`lcia_characterization_factors`.

**Fixing it quietly.** A missing expectation or a stale count fixed in a
maintainer commit teaches nothing; say what was missing in the review, even
when you push the fix yourself.
