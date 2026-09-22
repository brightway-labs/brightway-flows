# Conventions

!!! note "For developers"

    This page is the reasoning behind the rules in `AGENTS.md`. That file is
    short and imperative so it can be read at the start of every session; this
    one says *why*, and is read when the question comes up.

    To understand or use the data, start at
    [Why this exists](../concepts/why.md) or
    [Which output do I need?](../using/outputs.md) instead.

Related pages: [Architecture](architecture.md) is where the code lives;
[Data model](data-model.md) is what each record class is for. This page is how
to work with them.

---

## 1. Records, not dictionaries

**The rule.** Pipeline data is dataclass records. `Flow`, `FlowObject` and
`ElementaryFlow` are the record types. Read and write them by attribute
(`flow.cas_numbers`), never `flow.get("cas_numbers")`.

**Why.** The records deliberately have no `get()`. Attribute access makes a
wrong field name raise *where it is written*, instead of returning `None` and
producing a branch that never runs. That is not hypothetical: seven dead
dict-shaped guards were found this way, one of which had disabled
`consensus_match` outright and another the whole element and isotope
enrichment.

**Where the conversion happens.** At an I/O boundary, with `from_dict()` /
`to_dict()`. A dict inside the pipeline is a bug **unless** it is an external
payload — ChEBI records, PubChem compounds, GLAD rows, SQLite rows read back —
which stays a dict by design and is parsed where it is read.

**The passthrough bag.** Source-specific keys no record declares live in the
record's `extra` field and are read from it explicitly
(`flow.extra["elementary_flow_categorization"]`). `FlowObject` has no such bag,
on purpose: an undeclared key on a flow object is dropped rather than carried,
and `tests/test_merge_working_set_records.py` states that as a decision rather
than leaving it to be discovered.

**How this is enforced.** `DictGuardsOverRecordsTestCase` in
`tests/test_architecture_structure.py` is an AST detector: a value guarded as a
dict and read as a record in the same function is reported. It reads both
`flow.uuid` and a literal `getattr(flow, "uuid")` as a record read — the second
was added because the one live instance of the bug escaped the first.

**The last one converted, and what it cost.** The merge's elementary-flow
working list was the mutable half — rows are added to it, merged into and
written back — and `ElementaryFlow`'s serialised key order differs from the
projection that builds it, so converting it reordered 93,993 of the 2026-08-14
build's 95,190 rows (#93). It moves no published byte, because nothing
serialises the working list in the order it is held: a created flow reaches
`flow_json` through `_as_harmonised`, which rebuilds it as a `Flow`. The flow
object round trip needed no such argument — it is byte-exact.

---

## 2. Pydantic at a boundary, dataclasses inside

- **Pydantic** validates a payload arriving from a file or the network, and
  runtime settings.
- **Dataclasses** are the working records and value objects.

Applied to flows: `models.HarmonisedFlow` validates an input record at the file
boundary; `domain.flow.Flow` is what the transform stage reads and writes. These
are a boundary contract and a domain object, not parallel models.

`Flow` is separate from `HarmonisedFlow` for a measured reason:
`validate_assignment=True` would re-run full model validation on every attribute
write, in a hot loop over ~94k records.

**One class can serve both roles when that reason does not apply.**
`domain.source_ref.SourceRef` is a dataclass *and* the declared element type of
`HarmonisedFlow.source_refs` — Pydantic validates a stdlib dataclass the same
way. Nothing writes to a source reference in a loop, so there is no second class.

**Avoid parallel models for the same concept.** Where a view model is genuinely
needed — `webapps.app.queries.flows.SourceReference` is built from four columns
and has no `source_metadata` to carry — its docstring says it is a projection
and of what. The difference between a view model and a fourth model of one thing
is whether anyone wrote down which it is.

---

## 3. One canonical source per concept

- **Contexts:** `domain.context` is the only context model. Do not rebuild a
  context by parsing its display strings; resolve from the IRI, or use
  `Context.from_list`, which is the exact inverse of `to_list`.
- **Vocabulary:** `domain.vocabulary` is the only IRI registry. Do not
  re-declare an IRI in a module.
- **Package data:** `filesystem.PACKAGE_DATA_DIR`. Never spell
  `Path(__file__) / "data"` again — 23 modules did, in four variants, and the
  depth of the spelling depended on how deep the module was, so moving a module
  silently moved where it looked for its data.
- **One constant per data file.** Two constants naming one file is how a
  mapping went stale once already.

---

## 4. Transformers

A transformer has a `name`, a `setup()` and a `transform(flows) -> list[Change]`.
It **proposes** changes; it does not mutate a flow. The engine applies them,
records a `ChangeEvent`, and writes the transformer's name into
`flow.pipeline_sources`.

`Change` validates its field name against `Flow` at construction, so a
misspelling raises where it is written.

### `answers_per_flow`

Every transformer must declare it, and a new or modified one must have it
**decided** rather than inherited by accident.

- `True` — the change proposed for a flow depends only on that flow and on data
  loaded in `setup()`.
- `False` — the transformer compares, groups or indexes across flows. Add a
  comment saying which question about the whole set it asks.

A `True` transformer is shown only the flows the chain can still write to, which
is what keeps a merge proportional to the list being merged rather than to the
consensus it is merged into.

**Getting this wrong is silent.** A transformer wrongly marked `True` still
behaves correctly on the base list, where nothing is hidden, and quietly answers
a different question on every merge after it. Decide it by reading what the
transformer reads, not by whether the tests pass, and add the name to
`RegisteredChainClassificationTestCase.WHOLE_LIST` in
`tests/test_apply_transformers.py` when it is `False`.

### What a `True` answer may read

The flow it is being asked about, and whatever `setup()` loaded. Nothing else
about the flows it was shown.

Two things that look like exceptions and are not:

- **Batching one external call across the flows.** `opsin_iupac` collects every
  eligible label into one set so the JVM starts once, then answers per flow off
  the result. The answers are the same answers; only the call is shared.
- **Accumulating a diagnostic.** `unit_normalization` gathers the units it could
  not resolve and raises. That report now describes the list that arrived rather
  than the whole build, which is the right report — an unresolved unit in the
  arriving list still stops the run.

Anything else that carries state between iterations — a count, an index, a
comparison against a flow seen earlier — is a question about the set, and the
flag is `False`.

### A `False` answer indexes over everything and decides over less

All four whole-list transformers have the same two-phase shape:

```python
for flow in flows:                  # phase 1: the question about the set
    ...
for flow in writable_flows(flows):  # phase 2: the decision, flow by flow
    ...
```

Only phase 1 needs the whole list. A proposal for a flow that is already
`transformed` is dropped on arrival by `apply_transformers`, so deriving one is
the work #88 is about, one level in from where #91 stopped.
`pipeline.writable_flows` is that filter, and using it is what a new whole-list
transformer should copy.

What it costs to skip: on the 2026-08-14 build a merge loads 95,193 consensus
flows carrying 1,540,024 alternative labels between them, and three source lists
were merged. `strip_cross_object_altlabels` walked all of them, three times, and
applied 101 changes across the entire build; `strip_element_symbol_altlabels`
walked them and applied none.

`consensus_match` is the exception, and stays one. Its second phase loops over
flow objects rather than flows and emits review-queue rows as well as changes,
and a queue row is not gated by `transformed` — so narrowing it would change
`review_queue` rather than only what it costs.

### Capability by duck type, never by name

A transformer that also produces curator work implements
`review_queue_items()`, and `collect_review_queue_items` asks whatever it is
handed. Nothing checks `t.name == "..."`. That is the pattern any new
capability should follow.

---

## 5. Layer passes

The stages that run *after* `resolve_flow_layers` are not transformers. A
transformer proposes because it is shown the whole list and must not mutate it
while others are reading; a layer pass holds both layers and writes to them
directly.

**They do not share one signature, deliberately.** `assign_semantic_types` has
eleven callers, and the merge calls it, `attach_non_material_families` and
`normalise_records` over a subset of *its own* layers. A whole-run container
would break that reuse.

**They do share two things:**

1. **A return convention.** A `Counter` of what the pass did. `run_pipeline`'s
   `tally()` turns it into `RunStat` rows, so a regression is a number that
   moved between runs rather than a log line nobody read.
2. **How a write is recorded.** Writes go through `LayerWriteLog.write()`, which
   validates the field name, applies the value, records a `LayerWrite` and sets
   `pipeline_sources`. `run_pipeline` drains the log into the changelog.

A pass takes `writes: LayerWriteLog | None = None` and defaults to one it
discards, so a caller that does not want recording — the merge, a test — is
unchanged.

**Where the correction is a domain function**, the recording stays in
`pipeline`. `domain.property_values.normalise_records` is the correction that
says what a property means, and it runs over flow objects and over the merge's
own records as well as over the flow layer; a `LayerWriteLog` is a `pipeline`
object, and `domain` does not depend on `pipeline`. So the flow layer's caller
is `engine._normalise_flow_properties`, which holds the log and calls the same
`normalise_semantic_properties` (#94). Move the log into `domain` and the one
edge of the old import cycle that was *removed* rather than deferred comes
back — see [Architecture](architecture.md).

Two differences from `Change`, both intentional:

- **A write that changes nothing is not recorded.** These passes are bulk
  copies; logging the no-ops would be hundreds of thousands of rows.
- **The old value and the label are captured before the write**, because the
  element pass changes the very field `ChangeEvent.flow_name` is read from.

---

## 6. Curated files and curator rulings

`domain/rulings.py` is the register of every file in `data/`. Adding a file
there means adding a row, and `tests/test_ruling_convention.py` fails otherwise.

Three kinds, and they are different things:

| Kind | What it is |
|---|---|
| `RULINGS` | somebody looked at a case and overruled the pipeline |
| `VOCABULARIES` | what the words mean — authored, not decided |
| `REFERENCE_DATA` | bulk data shipped because fetching it is slow or impossible |

**Where a ruling lives:** beside the stage that applies it. A ruling is only
intelligible next to the rule it overrides —
`pipeline/collision_decisions.py` is mostly prose explaining why deduplication
cannot answer the question it answers. The register is what replaces a directory
to browse.

**What a loader looks like:**

1. **Returns records, or an index of them — never a bag.** A `dict[str, Any]` out
   of a loader is a curator's decision that nothing type-checks: spell a field
   wrong at the reading end and the answer is `None`, so the ruling silently
   does not apply and nothing says so.
2. **Except where the whole decision is membership, and then it is a set.**
   `altlabel-keep-list.json` is a list of labels a curator has ruled are names,
   and the only question asked of it is whether a label is one of them.
   Wrapping each in a record would buy nothing and make the membership test
   worse. The distinction is what the reading end asks: a *field*, or
   *membership*. Five of the thirty-four loaders answer membership — the keep
   list, the colour index names, the unit-change allowlist's accepted pairs, and
   the two the correspondence routing file holds — and the other twenty-nine hand
   out records.
3. **Cached exactly when the path is fixed.** A loader taking an injectable
   `path` must **not** be cached: the cache would serve the first test's fixture
   to every test after it. A loader taking nothing should be cached, because
   re-parsing a curated file per call is how the transformer chain got slow. A
   loader taking some *other* argument — the list being merged — is left to
   decide for itself: the cache is keyed, so it is a question about how often
   the answer is asked for rather than about correctness.

Both rules — records-or-set, and caching — are checked over a register of every
ruling's loader in `tests/test_ruling_convention.py`, which also fails when a
ruling is added with no loader listed. Until #95 the caching rule had two tests
and the records rule had none, and fifteen loaders broke it.

The rule is about **rulings**. A vocabulary is a table the code looks things up
in and reference data is bulk data somebody else published; neither is a
curator's decision with fields, and the loaders of both are covered by the
caching rule only. Two rulings have no loader at all — `*-manual-fixes.json` and
`*-additional-flows.json` — because they are randonneur payloads applied to a
vendor list before this project's records exist, which is the external-payload
case in §1.

**A malformed ruling raises; it is never skipped.** A decision that looks applied
and is not is the failure mode every decisions file here is written to avoid.

**A ruling file's own format version is `DECISIONS_SCHEMA_VERSION`.** Two ruling
files carry one — `elementary-flow-collision-decisions.json` and
`prepared-context-decisions.json` — and they version independently, so neither
gets the bare name. `SCHEMA_VERSION` unqualified is `domain/schema.py`'s: the
version of `harmonised-flows.json`, the thing this project publishes. All three
were spelled the same until #98, so grepping the name that answers "what
version does the list publish?" returned three answers. The constant is checked
where the file is read; one that nothing checks is a comment.

`curation/` is **not** where rulings live. That package holds *shortlists* —
things that rank work for a reader and decide nothing — and
`QualifierLossStaysAShortlistTestCase` pins that no build imports it.

### Which of two names a substance is published under

Common Chemistry names CAS 75-46-7 `Trifluoromethane`; ChEBI names it
`fluoroform`. Both are right, they name one gas, and the rename rule that
requires the two to agree therefore does nothing at all — so the substance goes
on being published under `HFC-23`, its refrigerant part number, which is the
worst of the three.

**Where two curated sources differ only in style, the published label is the
name other contributing lists use.** ecoinvent 3.12 reaches that flow as
`Trifluoromethane`, so that is the name. The same question over the same family
answers `Tetrafluoromethane` for CAS 75-73-0 and `Bromomethane` for 74-83-9,
and in both of those it is ChEBI's name rather than Common Chemistry's — the
rule is not "prefer the systematic form" or "prefer the trivial one", and
neither of those survives contact with six substances.

This is written down and not coded, and that is the point. Telling a systematic
name from a common one is a question about a naming grammar, not about a string,
and §6's other rulings exist because that distinction has already been tried as
a pattern and failed: `preferred_label_decisions` records three iterations of a
heuristic that read `C4-6` as an isotope. What a rule of this shape can do is
tell a curator which evidence settles the question, so that the answer written
into `preferred-label-decisions.json` or `ef-3.1-manual-fixes.json` is the same
answer next time somebody asks.

**A ruling names a collision, and naming the wrong one is silent.** Seven
rulings in `elementary-flow-collision-decisions.json` named the compartment
`envi-air-hist15me` while every flow they named was in
`envi-air-mest15me-ru10pesq`: EF 3.1 calls one compartment `Emissions to
non-urban air or from high stacks`, the project maps that whole phrase to rural
medium stack under 150 metres, and the rulings had been written from the second
half of EF's own name for it. Each keyed on a collision that does not exist, so
each applied to nothing and said nothing, and three substances #44 had already
decided went on being published twice for four more months (#106). Take the
context from the queue item, never from the vendor's words; a ruling whose flows
are live elsewhere is now counted as `collision_rulings_misplaced` rather than
folded in with the ones a bounded run simply does not hold.

---

## 7. Provenance

- Structured, using `domain.common.Provenance`, including
  `prov:hadPrimarySource` whenever available.
- No free-text provenance strings where structured provenance is expected.
- Whenever code mutates data in `flow_objects` or `elementary_flows` — including
  enrichment, harmonisation and inferred fields — add or merge a structured
  `provenance` section for the affected values **in the same change**.
- Validate CHEMROF predicates before introducing them. Do not invent or infer a
  predicate IRI; confirm the exact canonical one first.

---

## 8. Storing results

Every row written to the review or merge tables is a dataclass. A closed set of
categories is a `StrEnum` — `ReviewQueue`, `Severity`, `Outcome`,
`UnmatchedReason` — because a category invented by a typo is indistinguishable
from a real one once it is in the table.

Indexed columns are declared; everything type-specific goes in a JSON
`payload` / `detail` blob. That is what lets several queues share one table and
one template.

A writer takes a `db_path`, so it can be pointed at a temp database. Where the
default matters, resolve it at call time (`db_path = CONSENSUS_DB_FILEPATH if
db_path is None else db_path`) rather than as a default argument, which binds at
import time and defeats patching.

**A new field on a published record means regenerating the JSON Schemas** in
`src/brightway_flows/data/schemas/`. `tests/test_schemas.py` fails otherwise.

---

## 9. Verifying a change

**The test suite is not sufficient on its own.** One module split passed the full
suite while broken in four places, because no test exercised the SQLite writer.

- **Artifacts.** Run the same bounded job under your branch and under `main` and
  diff every artifact. `tools/verify_run.py` is that method as a tool: `run
  BASE_DIR` seeds an isolated data directory, runs the pipeline and snapshots
  every artifact — JSON canonicalised, every SQLite table dumped, timestamps and
  absolute paths masked; `compare A B` reports what differs. An identical hash is
  the success criterion, except where a change is *meant* to alter output — in
  which case say so and show what moved.
- **Static checks.** `ruff --select F821,F401,F811` has repeatedly caught defects
  in code paths no test exercises. Treat an unused import with care: one of them
  turned out to be an implicit re-export a test depended on.
- **Behaviour.** A change that moves rows is judged on a **full build**, against
  a full build of `main` from the same inputs, and
  `tools/compare_merge_outcomes.py` reads the two databases and says which rows
  were decided differently, what happened to the published flows, and whether
  any characterisation moved. A bound is exactly the wrong instrument here: it
  hides what a new rule does to the rows outside it, which is the thing being
  asked about. The two databases are the artifact worth keeping — every further
  question is answered from them in about a second, however long the builds
  took, and re-running a build to ask a second question is the mistake the tool
  exists to stop.
- **Which code built each side.** That diff answers "what did this change do"
  only if the before side came from the commit the branch started at, and until
  #101 no database said which commit it came from. A branch compared against a
  stored build of an older `main` reported eight halocarbon rows as having
  moved — five `Dichloromethane`, four `Methane, Bromo-, Halon 1001` and the
  rest — which were #90's and #95's merges rather than the branch's, and it
  was caught only because the rows were visibly unrelated to water. A change
  whose subject *was* halocarbons would have absorbed them.

  So `pipeline_runs` records `git_commit` and `git_dirty`. Two fields rather
  than one, because a build from a modified tree is not a build of its commit
  and treating it as reusable is the same silent failure by another route. Both
  are absent-tolerant at both ends: `git_revision()` answers `("", False)` where
  there is no repository, since a stamp is not worth failing a ten-minute run
  over, and `read_pipeline_run` reads the columns defensively, since `assess`
  and the review app open whatever is in the data directory.

  `compare_merge_outcomes.py` prints both revisions and refuses the pair
  otherwise — either side unstamped or built from a modified tree, both sides
  from the same commit, or a before side the after side does not descend from —
  with the reason and exit status 2. `--anyway` compares them regardless, for a
  pair that is deliberate: the same code over different inputs, or two branches
  neither of which descends from the other.

  What the stamp buys is that the before side stops being rebuilt per pull
  request. A stored build of the branch's merge base is reusable, which is ten
  minutes a change on this machine and more where several branches share a base,
  and the tool says so when the stored build is not the one you think it is.
- **Where the stored build lives is the shared data directory**, the one a plain
  `brightway-flows build` writes when `BRIGHTWAY_FLOWS_DATA_DIR` is
  unset. Not a directory of its own: of that directory's 12 GB only 347 MB came
  from outside the project and would be shared by symlink, so a second one means
  about 11.6 GB of files re-derived to say the same thing, and the hours that
  derive them. It
  is also what the review webapp serves and what `assess` reads by default, so a
  build of `main` is what a reader wants to find there. One build, serving the
  reader, the assessment and the before side at once.

  The rule that has to come with it: **nothing but a refresh writes that
  directory.** A refresh deletes and rewrites the database and rewrites the
  extracted source lists beside it with `main`'s code, so a development build
  there is destroyed by the next refresh — and, worse because it is silent, a
  refresh mid-investigation swaps the extracted lists under a branch reading
  them, which is #82 by another route. Development builds belong in a
  worktree's own `.data`, which `tools/seed_data_dir.py` makes. It also rests on
  one data-changing change being in flight at a time, which is a decision about
  sequencing rather than something the tool enforces.
- **The archive is an extract, not a build.** A comparison reads almost none of
  a 2.0 GB database: `merge_outcomes` whole — 31 MB, `detail_json` and every
  scored candidate included — plus two columns of `flow_objects`, six of
  `elementary_flows`, and the two run headers. Extracted, that is **44 MB**, and
  `compare_merge_outcomes.py` reads it as though it were the build, so the
  refresh keeps ten commits under `base-builds/` for less than one build costs
  and a question asked after `main` has moved on is still answerable. What an
  extract cannot do is `assess` or be served; the whole database is what the
  shared directory holds for the commit it is at.

  So the before side is named rather than found:
  `compare_merge_outcomes.py base .data/consensus-flows.sqlite3`, where `base`
  is `git merge-base origin/main HEAD` looked up in that archive.
- **The check runs at the beginning of an investigation, not on a timer.**
  `tools/refresh_base_build.py` asks the one question that matters — is what is
  stored a before side for *this* branch — and answers it in a second, copying
  the extract out where it is. Three answers are a no, and each is a way a diff
  would otherwise lie: the stored build does not say what it came from, or came
  from a modified tree; the branch does not descend from it; or commits since it
  touch `merge/`, `transformers/`, `flow_layers/` or the curated `data/`, which
  are the four paths that decide where a row goes. A commit anywhere else in
  `src/` is downstream of the decision and leaves the stored build usable — which
  is what makes the answer usually yes.

  A stored build older than the branch's base is archived under **the commit it
  is a build of**, never under the one it was asked about. `--build` is what
  makes one where the answer is no, and it is opt-in because it is hours rather
  than seconds. Nothing runs on a schedule: a timer would rewrite the data
  directory at times nobody asked about, and doing that while a branch is
  reading it is silent.
- **What `--build` makes is `build` and then `characterise`, over four lists.**
  The lists are ecoinvent 3.12, ecoinvent 3.8, BAFU 2026 v1 and Stepwise 2006,
  and the last two are not two more of the same kind: they are the merged lists
  with `simapro_origin`, so the strategies that de-invert `Benzene, chloro-`,
  split a geography off a name and read a unit out of one run on nothing else. A
  before side without them cannot say what a change to any of them did, and both
  sides of a comparison have to merge the same four.

  Stepwise is here for a second reason, which is that this build is not only a
  before side: it is also what `assess` grades. An expectation about a row of a
  list the build does not merge is not parked, it is ungradeable — it reports
  `unresolved`, the status meaning the subject has gone away — which is how
  #167's four chlordane claims came to fail on a build that had never seen a
  Stepwise row. The cost #164 named when it left the list out is real: its
  review queues have not been worked through, so its rows move counts in every
  comparison read against this baseline.

  `characterise` runs after, because a database with no `lcia_*` tables is not
  the build the shared directory is supposed to hold — the review webapp reads
  them and so does `assess`, and a refresh that left them out would replace a
  characterised build of `main` with one that answers "no factors" to every
  question. It is a second command rather than a stage of the first because it
  reads what a build wrote and nothing else, which is what makes a factor rule
  measurable in a minute. That is also why the extract is copied out **before**
  it runs: characterisation writes no table a comparison reads, so the before
  side is complete either way, and a missing `fetch-lcia ecoinvent-3.12` costs
  the factors and nothing else — reported as exit status 2 with the two
  commands that finish the job.
- **A `git archive` tree cannot be the before side**, which is what the recipe
  said until this was measured. The extracted tree has no `.git`, so
  `git_revision()` — which runs `git -C REPO_ROOT rev-parse HEAD` against it —
  has git search upward: inside the repository it reports the *outer* worktree's
  HEAD, so the before side is stamped as the very branch it is meant to be
  compared against, and outside one it reports nothing at all. Probed on
  2026-08-15: an archive of `060c024` extracted in a worktree stamped that
  worktree's `9e6cf5f`. #101's check refuses both, so nothing wrong was ever
  published — but the recipe could not work. Build a before side from a real
  checkout, which is what `git worktree add --detach` gives and what the refresh
  uses.
- **Bounded runs**, then, are for iterating, and for a curated override whose
  targets are few and where nothing else can move. `--max-flows` alone is a
  prefix, which is a sample nobody chose — name the
  flows a change is about with `--include-uuid`, or the run may contain none of
  them. `--max-flows` bounds the transform only: a 400-flow run merging
  ecoinvent 3.12 still matched all 9,850 of its rows, which was 25.9 s of a
  135 s verification run on 2026-08-15 — the largest single stage, and 7.4 s
  under `--max-rows 1000`. `--max-rows` and `--include-source-uuid` are the
  same pair on that side. Both bounds record themselves — `pipeline_runs.max_flows`,
  and the limit and available rows on each `merge_run_inputs` row — so a
  bounded run is distinguishable from a small one, and `assess` refuses to
  record a baseline from either.
- **Where the time went.** `run_timings` holds one row per stage of the build,
  the transformers and each merge named individually, and `build_timings` logs
  the slowest at the end. Measure before optimising: the three numbers that
  prompted this table were taken with a stopwatch from outside the process,
  which is as deep as a stopwatch reaches. The durations are excluded from
  artifact comparison by column name (`duration_seconds` is in
  `verify_run.VOLATILE_KEYS`), which is why they live in a table of their own
  rather than beside the counts in `run_stats`: a count must be identical
  between two runs of the same code, and a duration cannot be.
- **Expectations.** The two checks above ask whether the output *moved*. Neither
  asks whether it is *right*, and a change that claims to fix an issue is making
  exactly that claim. So it states the claim as data in `expectations/` — one
  file per issue, naming a subject in the published output and what should be
  true of it — and `brightway-flows assess` grades every one of them against
  the build. An expectation the project agrees is not yet true is marked
  `pending`: it is still evaluated and still reported, because it is the work
  queue, but it does not fail `assess --strict`. The change that makes it true
  drops the flag, and that line of the diff is the evidence.

  A failure prints the merge's own trace behind it — for a source row, every
  candidate the selector scored — because `merge_outcomes.detail_json` already
  records it, and a report that stopped at "unmet" would send its reader back to
  a database that knew the answer.

  Four results, not two. `unresolved` — the selector matched nothing — is kept
  apart from `unmet`, because an expectation whose vendor row was renamed
  upstream would otherwise go on reading as work to do while testing nothing.
  Fixing that is rewriting the expectation, which is a different job from fixing
  the pipeline.

  `expectations/baseline.json` is the last recorded build, committed, so a change
  that improves the matching carries `275 -> 22` in its own diff. Record it with
  `assess --record` from a full build only: a bounded run measures a prefix of
  the base list and would record every count as collapsed. It records and does
  not gate — whether a movement was allowed is what an expectation says, since a
  threshold on a population passes for the wrong reason as easily as the right
  one, while "this row lands on this flow" cannot.

  `expectations/README.md` is the vocabulary; `docs/operating/assessing.md` is
  the command.

---

## 10. Working in the repository

**Branches.** Every new unit of work goes on a new, explicitly named branch off
`main`. `git checkout main && git pull` first.

**Data directories.** Every worktree gets its own. Run `uv run python
tools/seed_data_dir.py` once, then `export
BRIGHTWAY_FLOWS_DATA_DIR=$PWD/.data` in every shell that fetches, builds or
runs the tests.

Never point a worktree at the shared platform data directory. Two branches then
write the same extracted flow list, and a build reads flows another branch's code
produced without saying so — the borrowed rows carry names, and therefore UUIDs,
that the reading branch cannot produce, so the merge matches against flows that
do not exist on it.

The seeded directory symlinks back to the shared one **only** what came from
outside this project: the vendor archives, the ChEBI dump, the GLAD workbook, the
web-service caches. Those are the same file on every branch and slow or
impossible to fetch again. Everything this project's own code writes is produced
fresh in the worktree — regenerate a source list with `uv run brightway-flows
fetch-source <key>`, and never copy an extracted list, a layered artifact or
`consensus-flows.sqlite3` in from another worktree.

**A test reads the data directory too.** Three test modules spelled out
`Path.home() / ".local/share/brightway-flows/..."`, which goes round
`BRIGHTWAY_FLOWS_DATA_DIR` and reads whichever branch built last — the
whole of what the paragraph above is about, in the files that are supposed to
catch it. Ask the source list where its flows are (`base_source_list().flows_path`)
or the `filesystem` module for a cache (`PUBCHEM_ELEMENTS_CACHE_FILEPATH`), and
skip when the file is not there. Read a large one once per process: the
extracted base list is 207 MB, and parsing it per test method cost 1.3 s five
times over in a 57 s suite.

**Titles say what changed.** An issue or pull request title is read in a list,
by somebody who has not read the issue and is deciding whether this is the one
they are looking for. It has one job: name the thing that changed, concretely
enough that they can tell.

The habit to break is the two-clause antithesis — *A substance is taken from one
place, and the rule now says which*; *a factor the list already publishes is
restated, not asked*; *a stated charge renames an ion label only where the rename
disambiguates, and Titanium, ion keeps its name*. Each of those reads as a
finished thought and none of them says what the change does. They are aphorisms:
the shape carries the confidence, and the reader supplies the content out of
knowledge they do not have. `Fix nine substances published in two resource
contexts` is duller and tells them everything the first one does not.

So: one clause, in the plainest words the change allows. Name the substance, the
source list, the file or the count — `Fosetyl-aluminium is fosetyl-aluminum`
names a substance and is fine at any length. Drop `X, not Y`, `X, and so does
Y`, `X, so Y` and the colon that introduces a restatement. The body is where the
reasoning goes, and it has as much room as it needs; the title does not.

---

## 11. Writing the documentation

**The reader is an environmental engineer.** Somebody who knows what an
elementary flow, a compartment and a characterisation factor are, who has an
inventory database open in another window, and who has no reason to know what a
transformer, a dataclass or a protocol is. `docs/index.md` has said this since
it was written. It is here as well because a page is written by somebody who
read this file, not by somebody who read the front page.

Three pages are exempt, and each says so in an admonition at the top:
[Architecture](architecture.md), this page, and [Data model](data-model.md).
They are read by somebody modifying the code. Everything else — including
[Harmonisation steps](harmonisation-steps.md), which describes the pipeline
rather than the code that runs it — is for the engineer.

**An example comes before the rule.** The pages that work do this already.
[Flow objects and elementary flows](../concepts/two-layers.md) follows lead
through four inventory rows — urban air, surface water, ground extraction, in
two source lists — and only then says that CAS 7439-92-1 and the atomic number
belong to the substance rather than the row. [Why this
exists](../concepts/why.md) earns "a CAS number is not a primary key" with
CHEBI:30146, lithium hydride, claiming lithium metal's number and contaminating
the element's formula.

The failure mode is the opposite order: state the rule, then illustrate it if
there is room. It reads as a specification, and a reader who did not already
believe the rule has nothing to hold on to while they read it.

**Name substances, not classes.** "A flow object may have no elementary flows"
is a sentence about the schema. "Americium appears in both source lists only as
a nuclide, so the list has americium as a substance without having an
occurrence of it" is the same fact, and it tells the reader which of their own
rows will behave that way. Field and table names are fine where the reader will
type them — a SQL recipe, a JSON key they will index into — and are noise
everywhere else.

**Code appears where the reader will type it.** A command they will run, a
query they will run, a payload they will parse. Not to show how the pipeline is
built: that is what [Architecture](architecture.md) is for, and a mechanism
explained twice drifts in one of the two places.

**Say what moved, with the number.** A page that says "some flows" where the
build says 8,643 labels from 69 objects is asking the reader to trust it
instead of check it. Where a number is in a published artifact or a `run_stats`
row, quote it and name the build it came from, the way [Known
limitations](limitations.md) does throughout.

**A claim a test can hold gets one.** `tests/test_documentation.py` keeps the
links, the navigation, the command names, the retired artifacts and the context
list honest. A list or a count copied out of `data/` belongs there too — the
context list in [Flow contexts](../concepts/contexts.md) drifted by eleven
entries over about a year because nothing compared it to the file it was copied
from. A count in prose that no test can reach is written so it does not need
one.

**A number copied out of a build drifts the same way, and nothing was catching
it.** `data/` is checked into the repository and a test can compare against it;
a build is not, so a figure copied from one goes stale the next time anybody
improves the matching, silently and in a page that reads as current. It happened
while this paragraph's own change was being written: a branch quoted 64 unplaced
BAFU rows in [Assessing a build](../operating/assessing.md) while its own
`expectations/baseline.json`, recorded twenty minutes later, said 14. So quote a
build figure only where the reader needs it, name the run, and where a page
prints a whole table of them — the placement table on that page is the one —
check it against `baseline.json`, which every full build rewrites.
