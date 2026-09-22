# Project Agent Instructions

The rules. Each one is a sentence; the reasoning is in
[`docs/reference/conventions.md`](docs/reference/conventions.md), which is the
page to read when a rule looks wrong or does not obviously apply. Section
numbers below point into it.

Two other pages are worth knowing about:
[`docs/reference/architecture.md`](docs/reference/architecture.md) says where
code lives, and [`docs/reference/data-model.md`](docs/reference/data-model.md)
says what each record class is for.

Two jobs have a procedure rather than a rule, and each is a skill:

- [`.claude/skills/adding-a-transformer`](.claude/skills/adding-a-transformer/SKILL.md),
  for adding, removing or reordering a step in the harmonisation chain. Read it
  before touching `DEFAULT_TRANSFORMERS` — five things outside the module have
  to move with it.
- [`.claude/skills/fixing-a-matching-defect`](.claude/skills/fixing-a-matching-defect/SKILL.md),
  for changing where the merge puts a source row. Read it before writing the
  fix: the row is named and the build is measured first, and the expectation is
  written while it still fails.

## Records

1. Pipeline data is dataclass records — `Flow`, `FlowObject`, `ElementaryFlow` —
   read and written by attribute, never `.get()`. (§1)
2. Convert with `from_dict()` / `to_dict()` at an I/O boundary only. A dict
   inside the pipeline is a bug unless it is an external payload (ChEBI,
   PubChem, GLAD, a SQLite row), which stays a dict and is parsed where it is
   read. (§1)
3. Source-specific keys no record declares go in the record's `extra` bag and
   are read from it explicitly. (§1)
4. Pydantic validates payloads at a file or network boundary; dataclasses are
   the working records. Do not add a second model of a concept that already has
   one. (§2)
5. Use `domain.context` for contexts, `domain.vocabulary` for IRIs, and
   `filesystem.PACKAGE_DATA_DIR` for bundled data. One constant per data file.
   (§3)

## Writing to a flow

6. A transformer proposes `Change` objects and never mutates a flow. (§4)
7. Every transformer declares `answers_per_flow`, decided by reading what the
   transformer reads — not by whether the tests pass, because getting it wrong
   is silent. When it is `False`, add the name to
   `RegisteredChainClassificationTestCase.WHOLE_LIST` in
   `tests/test_apply_transformers.py`. (§4)
8. A `True` answer reads the flow it is asked about and what `setup()` loaded,
   and nothing else about the flows it was shown. Batching one external call
   across them is still `True`; carrying a count, an index or a comparison
   between iterations is not. (§4)
9. A `False` transformer indexes over every flow and decides over
   `pipeline.writable_flows(flows)`. The engine drops a proposal for a finished
   flow, so deriving one is work done to be discarded. (§4)
10. Detect a capability by duck type. Never branch on a transformer's name. (§4)
11. A pass that runs after `resolve_flow_layers` returns a `Counter` and writes
    through `LayerWriteLog`, so the write reaches the changelog. Do not give the
    passes one shared signature — the merge reuses several over a subset of its
    own layers. (§5)

## Curated data

12. Every file in `data/` is registered in `domain/rulings.py`, as a ruling, a
    vocabulary or reference data. (§6)
13. A ruling lives beside the stage that applies it. Its loader returns records
    — or, where the whole decision is membership, the set it tests — and never a
    bag. It is cached exactly when its path is fixed: a path-injectable loader
    must not be cached, and one that takes nothing must be. A file that versions
    its own format spells that `DECISIONS_SCHEMA_VERSION`, module-local and
    checked where the file is read; unqualified `SCHEMA_VERSION` means the
    published list's. (§6)
14. A malformed ruling raises. Never skip one. (§6)
15. Nothing in a build may import `curation/`; it holds shortlists, which decide
    nothing. (§6)

## Provenance

16. Provenance is structured, via `domain.common.Provenance`, with
    `prov:hadPrimarySource` whenever available — never a free-text string where
    structured provenance is expected. (§7)
17. Code that mutates data in `flow_objects` or `elementary_flows` adds or
    merges the `provenance` section for the affected values in the same change.
    (§7)
18. Confirm a CHEMROF predicate's canonical IRI before using it. Never invent or
    infer one. (§7)

## Results

19. A row written to a review or merge table is a dataclass, with closed
    categories as a `StrEnum`. (§8)
20. A writer takes a `db_path`, resolved at call time when it has a default. (§8)
21. A new field on a published record means regenerating the JSON Schemas in
    `src/brightway_flows/data/schemas/`. (§8)

## Verifying

22. The test suite is not sufficient. Verify a refactor by running the same
    bounded job under your branch and `main` and diffing every artifact with
    `tools/verify_run.py`; an identical hash is the criterion, unless the change
    is meant to alter output, in which case say what moved. (§9)
23. Run `ruff --select F821,F401,F811`. It has repeatedly caught defects no test
    exercises. (§9)
24. Judge a change to behaviour on a **full build**, against a full build of the
    branch's merge base from the same inputs — start with
    `tools/refresh_base_build.py`, which says in a second whether the stored
    build answers for this branch and copies out what a comparison reads — and
    diff them with `tools/compare_merge_outcomes.py base <yours>`, which prints
    the revision each side came from and refuses a pair that cannot answer the
    question; a bound hides exactly what a new rule does to the rows outside it.
    Bounded runs are for iterating, and for a curated override whose targets are
    few — and bound both sides when you use
    one: `--max-flows` with `--include-uuid` over the base list, `--max-rows`
    with `--include-source-uuid` over each merged list, because a limit alone
    is a sample nobody chose. (§9)
25. The shared data directory holds a build of `main` and nothing else writes it:
    your builds go in your worktree's own `.data`, made by
    `tools/seed_data_dir.py`. A build of your branch there is destroyed by the
    next refresh, and swaps the extracted lists under whatever else is reading
    them, which is #82 by another route. (§9)
26. A change that claims to fix an issue states the claim as data in
    `expectations/`, one file per issue, and `brightway-flows assess` grades
    it against the build. Mark it `pending` while it is not yet true; drop the
    flag in the change that makes it true. (§9)

## Writing

27. Documentation is written for an environmental engineer, not a programmer:
    an example before the rule, substances and compartments rather than classes
    and functions, and code only where the reader will type it. (§11)
28. Three pages are exempt and say so at the top —
    `docs/reference/architecture.md`, `conventions.md` and `data-model.md`.
    Every other page, including `harmonisation-steps.md`, is for the engineer.
    (§11)
29. Quote the number and name the build it came from, rather than writing
    "some" or "many". (§11)
30. A list or a count copied out of `data/` gets a case in
    `tests/test_documentation.py`. Nothing else stops it drifting. (§11)
31. A number copied out of a *build* drifts the same way and is caught by
    nothing, so quote it only where a reader needs it, name the run, and where
    the page prints a whole table of them check it against
    `expectations/baseline.json` in `tests/test_documentation.py`. (§11)

## Working here

32. Every unit of work goes on a new, explicitly named branch off `main`;
    `git checkout main && git pull` first. (§10)
33. Every worktree gets its own data directory: `uv run python
    tools/seed_data_dir.py`, then `export
    BRIGHTWAY_FLOWS_DATA_DIR=$PWD/.data` in every shell that fetches,
    builds or runs the tests. Never point a worktree at the shared platform
    data directory, and never copy an extracted list, a layered artifact or
    `consensus-flows.sqlite3` in from another worktree. A test reads a data
    file through the data directory as well — `base_source_list().flows_path`
    or a `filesystem` constant, never `Path.home()`. (§10)
34. An issue or pull request title says plainly what changed, concretely enough
    to mean something to somebody who has not read it: `Fix nine substances
    published in two resource contexts`, not `A substance is taken from one
    place, and the rule now says which`. No two-clause antithesis — `X, not Y`,
    `X, and so does Y`, `X, so Y` — and no aphorism. Name the substance, the
    list, the file or the count. (§10)

## Naming a substance

35. Where two curated sources give one substance two names that differ only in
    style — systematic against common, `Trifluoromethane` against `fluoroform` —
    the published label is the name other contributing lists use. Written down
    rather than coded: which of two names is the common one is not a question a
    string can be asked. (§6)
