---
name: adding-a-transformer
description: Use when adding, removing, reordering or reclassifying a step in the harmonisation chain — anything that changes `DEFAULT_TRANSFORMERS` or a `Transformer` subclass in `src/brightway_flows/transformers/`. Covers the `answers_per_flow` decision, the three registration points, the page and tests that must move with the chain, the `expectations/` file stating what the step should make true of the published output, and how to verify with `verify_run.py` and `assess`.
---

# Adding a transformer

The rules are `AGENTS.md` 6–10 for the transformer itself and 22–26 for
verifying it; the reasoning is
[`docs/reference/conventions.md`](../../../docs/reference/conventions.md) §4 and
§9, which is what to read when one of them looks wrong. This is the order to do
the work in, and the five things outside the module that have to move with it.

Steps 1 and 2 are decisions. Do them before writing `transform()`, because both
change what the code looks like.

## 1. Decide `answers_per_flow`

Not after the tests pass — the tests pass either way. Read what the transformer
reads, and answer: *does the proposal for a flow depend on any other flow?*

`True` — it reads the flow it is asked about and whatever `setup()` loaded, and
nothing else. Batching one external call across the flows is still `True`
(`opsin_iupac` starts the JVM once); carrying a count, an index or a comparison
between iterations is not.

`False` — it asks a question about the *set*. Five of the twenty-seven do:
"is this synonym some other substance's name?", "which flow *is* the element for
this symbol?", "do the source lists agree?", "is this structure unique?".

Wrong in the `True` direction is silent. The base list hides nothing, so the
transformer behaves correctly there, and then answers a different question on
every merge afterwards. `False` is the default and the safe one: it costs time
and cannot cost correctness.

The full reasoning, including the two things that look like exceptions and are
not, is conventions §4 and the `answers_per_flow` docstring on
`pipeline.engine.Transformer`.

## 2. Decide where in the chain it goes

The chain is ordered for a single pass over raw input and is not idempotent.
Last writer wins per field, so position is behaviour, not taste. Ask what must
already have happened for this step to be right, and what must not have happened
yet.

If the position is load-bearing, the comment goes in `DEFAULT_TRANSFORMERS`
next to the entry, saying what it must follow and what it must precede — the way
`strip_catalogue_altlabels` and `strip_product_families` do. A position with no
comment reads as arbitrary and the next person will move it.

## 3. Write the module

One file in `src/brightway_flows/transformers/`, one class subclassing
`pipeline.Transformer`.

- **A module docstring that says how the detection works**, not what the class
  is called. `strip_element_symbol_altlabels.py` is the shape: what the problem
  is, a "Detection strategy" section saying how a flow is recognised, and the
  exact forms that are matched or protected. This is where a reviewer checks
  whether the rule is the rule you meant.
- **`name`** — the snake_case string written into `flow.pipeline_sources` and
  the changelog. It is data, published on `/changes`; renaming one later is a
  migration.
- **`answers_per_flow`**, with a comment when it is `False` saying which
  question about the whole set it asks.
- **`setup()`** loads and indexes supplementary data, once. Not in `__init__`,
  and not per flow.
- **`transform(flows) -> list[Change]`** proposes; it never mutates a flow.
  `Change` validates the field name against `Flow` at construction, so a
  misspelling raises where it is written. Give every `Change` a `comment` — it
  is the reason column the curator reads.

A `False` transformer has two phases, and only the first needs the whole list:

```python
for flow in flows:                  # phase 1: the question about the set
    ...
for flow in writable_flows(flows):  # phase 2: the decision, flow by flow
    ...
```

`pipeline.writable_flows` is the filter. Skipping it is not a correctness bug —
`apply_transformers` drops a proposal for a finished flow — it is the cost of
deriving one, and on a merge that is 95,193 consensus flows walked per source
list.

If the step also produces curator work, implement `review_queue_items()`.
`collect_review_queue_items` asks whatever it is handed; nothing branches on a
transformer's name, and nothing should start.

## 4. Register it in three places

All in `src/brightway_flows/transformers/__init__.py`:

1. the import,
2. the entry in `DEFAULT_TRANSFORMERS`, at the position decided in step 2,
3. the name in `__all__`.

A module that exists and is not in `DEFAULT_TRANSFORMERS` does not run.

## 5. Move the tests and the page with it

Four things outside the module go stale otherwise. The last three are checked by
`tests/test_documentation.py`, so they will fail rather than drift — but they
fail on *your* branch, so do them here.

- **`tests/test_apply_transformers.py`** — when `answers_per_flow` is `False`,
  add the name to `RegisteredChainClassificationTestCase.WHOLE_LIST`. This is
  the test that makes the classification a decision somebody signed rather than
  a default nobody looked at.
- **The order table** in
  [`docs/reference/harmonisation-steps.md`](../../../docs/reference/harmonisation-steps.md)
  — one row per step, numbered in chain order. Inserting a step renumbers every
  row after it.
- **The whole-list table**, under "What each step is shown" — only if
  `answers_per_flow` is `False`. The row is the step number, the same step name
  as the order table, and the question it asks about the set.
- **The counts and the phase headings** — the "twenty-seven processing steps"
  sentence, the "Twenty-two of the twenty-seven" sentence, and the `### Steps 10–14:`
  headings in "Phase by phase", which have to keep covering every step with no
  gap. Write the new step into whichever phase section it lands in; a step in
  the table and absent from the prose is the failure this page is for.

That page is for an environmental engineer, not a programmer (conventions §11):
name substances and compartments, not classes. "Remove element symbols from
non-element flows", not "filter `altLabel` by `molecular_formula` cardinality".

## 6. Say what it should do, in `expectations/`

A step is added because something in the published output is wrong. Write down
what should be true once it is right, as data, in the same change:
`expectations/0381-bafu-water-names.json`, one file per issue, named for the
issue the step closes.

```json
{
  "schema_version": 1,
  "description": "Why this file exists, in prose. Read by a person, not by code.",
  "expectations": [
    {
      "id": "0381-bafu-water-unqualified",
      "issue": 381,
      "title": "The BAFU rows named `Water` land on a consensus flow that already exists",
      "subject": {"kind": "source_row", "list": "bafu", "name": "Water"},
      "expect": {"outcome": "matched", "target_name": "Water"},
      "comment": "What the build does today, measured, and why the expected answer is the right one.",
      "pending": true
    }
  ]
}
```

A subject is a `source_row`, a `flow`, a `substance` or a `measure`; what you
may claim about each is in
[`expectations/README.md`](../../../expectations/README.md), the reasoning is
conventions §9, and every key and
every value is checked against a closed list at load time, so a misspelled claim
fails `tests/test_expectations.py` rather than passing without testing anything.

**Write the expectation before the transformer, and mark it `pending`.** It is
then evaluated and printed, and does not fail `assess --strict`. Drop the flag
in the same change that makes it true — that diff is the evidence the step did
what it was added to do.

Pick the claim that only the new step can satisfy. `at_most` on a population
passes for the wrong reason as easily as the right one — a count falls because
the step worked or because the merge stopped reaching those rows at all — while
"this row lands on this flow" cannot. Where the step is about a group, `flow`
and `substance` are different questions: four rows named `Silver-110` reaching
four flows is right and reaching two substances is not, and only
`same_substance` catches that.

## 7. Verify

The test suite is not sufficient — it does not run a build.

```bash
export BRIGHTWAY_FLOWS_DATA_DIR=$PWD/.data   # never the shared directory
uv run ruff check --select F821,F401,F811 src tests
uv run pytest tests/test_apply_transformers.py tests/test_documentation.py \
              tests/test_expectations.py
uv run python tools/verify_run.py --include-uuid <uuid> ...

uv run brightway-flows build --source bafu-2026-v1   # the list the claim names
uv run brightway-flows assess
```

`verify_run.py` runs the same bounded job under your branch and `main` and diffs
every artifact. An identical hash is the criterion. A new step is *meant* to
change the output, so say what moved and why it is what you intended — which
flows, which fields, how many. Name the flows the step is about with
`--include-uuid`; `--max-flows` alone is a sample nobody chose, and a step that
fires on 40 flows in the whole build will not appear in it.

`verify_run.py` says *what changed*; `assess` says *whether the change was the
one claimed*. Both are needed, and neither is the test suite. `assess` reads the
database a build wrote, and grades every expectation in the repository, not only
yours, so a step that fixes its own issue by breaking somebody else's shows up
here.

**A build merges nothing unless asked.** If the expectation names a
`source_row`, the build it is graded against has to have merged that list, or
the claim comes back `unresolved` — the selector matched nothing — which is not
the same as failing and is easy to read as "no news". Pass `--source` for the
list the claim names. An expectation about a `flow`, a `substance` or a
`measure` on the base list needs no `--source`.

Re-record the baseline with `assess --record` after a **full** build, never
after a `--max-flows` run, which measures a prefix of the base list and would
record every count as collapsed. Commit it: the movement then appears in the
diff rather than in a sentence about the diff.

## Removing or reordering a step

The same list, backwards, plus two things. The expectations for the issue the
step closed still have to hold — if the behaviour is now somebody else's, leave
them; if the project no longer wants it, say so in the file rather than deleting
the claim, because a deleted expectation and a met one read the same in the
report. And say in the code why the step went. The
removed `PubChemReadableNameTransformer` is still commented in
`DEFAULT_TRANSFORMERS` with the number that got it removed — 17,942 published
labels a run from a single source with no agreement requirement — because
without it the next person adds it back under a new name. That comment is the
point of the entry, not a leftover.
