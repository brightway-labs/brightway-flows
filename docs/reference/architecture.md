# Architecture

!!! note "For developers"

    This page describes the Python package layout and is only useful if you are
    modifying the code. To understand or use the data, start at
    [Why this exists](../concepts/why.md) or
    [Which output do I need?](../using/outputs.md) instead.

## Module Layout

`brightway_flows` is split into logical sections:

- `application`: CLI and top-level orchestration exports.
- `pipeline`: the transform stage, split by responsibility (see below).
- `flow_layers`: resolving flows into flow objects, and enriching them (see below).
- `integrations`: external-source adapters and network/data retrieval.
- `merge`: merge-pipeline entry points.
- `lookup`: answering "which consensus flow is this?" for a list nobody has
  merged, against a build that has already happened (see below).
- `lcia`: characterisation — the impact categories, and the factors matched onto
  the consensus flows (see below).
- `webapps`: the review application. One package, `webapps.app`.
- `domain`: canonical domain models.
- `transformers`: ETL transform stages.

Thirteen modules sit at the top level rather than in a section: `sources`,
`chem`, `simapro_names`, `cache_archive`, `context_mapping`, `match_overrides`,
`manual_fixes`, `qualifiers`, `correspondence_contexts`, `additional_flows`,
`filesystem` and `settings`. These are **not** legacy — this line used to say
they were, while `sources` was the most-imported module in the project (#92).
They are cross-cutting: each is read by several sections and belongs to none.
Put a new module in a section if one section owns it, and here only if more than
one does.

`settings` is the one of them that describes the *installation* rather than the
list: an API key, and which vendor releases the unit-process score comparison
reads and from where (`ScoreComparisonSettings`). A rule about the list is a
curated file in `data/`; a fact about this machine — which brightway projects
exist, where expensive artifacts are kept — is a setting, read from
`settings.json` in the data directory with the environment on top
(`SCORE_COMPARISON__SAMPLE_SIZE`). `score-comparison-config` prints it, because
the exporter that needs it runs under a Python this package is not installed in.

`cli` is no longer among them. It lived at the top level with a five-line
`application/cli.py` re-exporting it, while `cli` imported
`application.context_commands` — so the arrow pointed both ways. The CLI is
`application/cli.py` now.

The conventions for writing code in any of these sections are in
[Conventions](conventions.md).

### The lookup section, and the arrow that must not reverse

`lookup` is a section rather than a top-level module because it owns more than
one file.

| Module | Responsibility |
|---|---|
| `index` | the column projection, the build stamp, and refusing a build that cannot answer |
| `query` | `FlowQuery`, the four-step context resolution, and the offline slice of the transform chain |
| `matcher` | `FlowMatcher`, `FlowMatch`: calling the merge's two matching functions and reading the winner back |
| `recorded` | tier one: the decision a build already made about this exact row |
| `replay` | asking the lookup every question a build has already answered, and counting |
| `__init__` | the public surface — `FlowMatcher`, `FlowQuery`, `FlowMatch` |

`FlowMatcher` and `FlowMatch` are defined in `matcher` and re-exported rather
than written into `__init__`, which `plans/lookup-api.md` §4 puts them in: the
plan's point is that those three names *are* the public surface, and a package
whose `__init__` is five hundred lines of implementation is harder to read than
one whose `__init__` says what the surface is.

It is deliberately **not** part of `merge`. `merge` is the write path — it
creates flows, mints identifiers and writes rows — and this is the same matching
decision made without any of that. The two functions that decide where a source
row goes, `resolve_flow_object` and `_select_elementary_flow`, are already pure,
so `lookup` calls them rather than reimplementing them; that is what lets it
promise that an answer from it is the answer a build would have given.

So `lookup` imports from `merge` and **`merge` must never import `lookup`**, and
nothing under `lookup` may reach `merge.creations`, `merge.additions`,
`merge.datastores`, `merge.rows`, `merge.pipeline` or either SQLite writer.

`merge.store` is the one module with both halves. `read_outcomes` is how `replay`
asks a build what it decided; `write_source_outcomes` is how a merge records it.
So the module is not blanket-forbidden — that would push `replay` into
reimplementing a reader — and its writing functions are refused by name instead.
The strong rule is kept where it matters: the four modules a question actually
travels through (`__init__`, `index`, `query`, `matcher`) may not touch
`merge.store` at all, and none of them may import `replay`.

All of it is asserted in `tests/test_lookup_writes_nothing.py`, in the style
`tests/test_architecture_structure.py` uses.

### One import cycle to be aware of

`flow_layers` → `integrations` → `chebi` → `pipeline` → `flow_layers` is a real
cycle. It went unnoticed for a long time because it only worked by accident, in
whichever order modules happened to load; sorting the imports was enough to
break it. The `ec_inventory` import — now in `flow_layers.ions` — is deferred to
the point of use, which cuts it.

Adding a module-level import between `pipeline`, `flow_layers` and
`integrations` can reintroduce it. If an import fails only under some entry
points, this is the first thing to check.

One edge of it is gone: `domain.schema` needs `ElementaryFlow` to generate the
published schemas, and used to import it from `flow_layers`, which made `domain`
depend on the layering. The record now lives in `domain.elementary_flow` with
its two siblings, so that import points inside `domain`.

## Flow Layers Package Layout

`flow_layers` is a package rather than one module. The package re-exports
`resolve_flow_layers`, so `from brightway_flows.flow_layers import
resolve_flow_layers` is unchanged.

| Module | Responsibility |
|---|---|
| `layering` | `resolve_flow_layers`: grouping flows into flow objects |
| `classifications` | CAS and EC classification blocks |
| `labels` | label and definition rows, and the keys they are indexed by |
| `element_cache` | retrieving and caching PubChem elements and ChemLin isotopes |
| `elements` | writing element and isotope facts onto flow objects |
| `ions` | ion name parsing, and monoatomic-ion enrichment |
| `provenance` | the activity name the enrichments are attributed to |

The three enrichment passes run in order and each reads what the last wrote:
`elements` types an object `chemrof:ChemicalElement`, and `ions` recognises an
ion by its name resolving to an object already carrying that type. That is why
`elements` calls into `ions` rather than `layering` calling both.

`ions` has a second caller: `merge.creations`, over the objects a merge has just
minted. It is the one of the three the merge can use, because the other two are
seeded from the base list by decision, and because it is where an object named
`Iron, ion` learns which element it is an ion of (#71). It reaches it directly
rather than through `resolve_flow_layers`, which runs the whole trio only under
`include_pubchem_isotopes` — a switch the merge sets false, since the isotope
machinery behind it enriches objects reachable from an `EF 3.1` flow and a merged
batch holds none. So `enrich_monoatomic_ions` takes the objects to write to and
the objects to resolve elements against separately: a merge mints no elements,
and a batch asked about itself would recognise nothing.

`layering` and `elements` both decide which flows are nuclides, and they have to
agree — one splits the objects and the other enriches them, so a disagreement
would leave an object split by one and unenriched by the other. Both read the
**preferred label**, and both parse it with
`domain.nuclides.parse_nuclide_label`. That parser and the periodic table it
needs are in `domain` rather than in `flow_layers` for the reason
`domain.units` is: `flow_layers` pulls in settings, the filesystem and the
integrations, and `pipeline.semantic_typing` wants only the parser. The
periodic table is a literal there — it is what makes the parsing a pure
function — and a test checks it against the PubChem cache so the two cannot
drift.

## Pipeline Package Layout

`pipeline` is a package rather than one module. Each part has a single
responsibility and the package re-exports the surface transformers use, so
`from brightway_flows.pipeline import Change, Transformer` is unchanged.

| Module | Responsibility |
|---|---|
| `engine` | `Change`, `Transformer`, `run_pipeline` |
| `loading` | reading input files into validated `Flow` records |
| `provenance` | the PROV-O graph for a run |
| `exporting` | projection onto the simplified published export |
| `deduplication` | duplicate elementary flows and their deprecation |
| `collisions` | two live flows of one substance in one context, reported as a question |
| `collision_decisions` | the curator's answers to those questions, and their application |
| `concept_associations` | links back to source-list flows |
| `match_strength` | how strong each of those links may claim to be, counted once the whole source list is in view |
| `sqlite` | the denormalised database backing the review application |
| `sqlite_schema` | how a writer into that database declares its tables: the drop-and-recreate step and the `INSERT` a column list builds |
| `text` | name and unit predicates used by transformers |

Import from the specific module in new code; the package re-exports exist so the
20 transformers did not all need editing.

## Merge Package Layout

`merge` follows the same pattern as `pipeline`: one module per responsibility,
with `merge_source_list` orchestrating them.

| Module | Responsibility |
|---|---|
| `pipeline` | `merge_source_list`: the order the steps below run in |
| `sources` | `SourceList`: which list is being merged, and where its inputs are |
| `matching` | finding the flow object and elementary flow for a source row, and the indexes that make it possible |
| `contexts` | mapping a source row's context onto a consensus context IRI |
| `prepared` | previously reviewed match decisions, following replacements, and the contexts they contradict |
| `additions` | flows added rather than matched, manual groupings included, and their stable identifiers |
| `creations` | flow objects minted for rows naming a substance the list does not have |
| `provenance` | provenance and cross-references recorded on a merge |
| `rows` | the loop over the source list, and what happens to one row in it |
| `unmatched` | the evidence attached to a row the merge could not place |
| `state` | `SourceRow`, `MatchAttempt`, `MergeIndexes`, `MergeAccumulator` |
| `report` | the record types one outcome is reported as |
| `store` | outcomes assembled and written to the merge tables |
| `unit_changes` | matches whose source and target are measured in different units |
| `collisions` | the transform's collision check, asked again of the flows the merge writes |
| `datastores` | propagating results into the elementary-flow file and SQLite |
| `manual_fixes`, `prepared_context_decisions` | hand-authored rulings, each keyed to the list it was made about |

### Identifying a source list

An input list is identified by `(list_name, list_version)` — the same pair the
in-memory `source_refs` carry and the `elementary_flow_sources` table stores.
That table is where they are read back: no published or stored JSON keeps
`source_refs` (#30).
`SourceList` holds that identity along with every input keyed to it: the source
flows, the manual fixes, the curated groupings, and the match overrides — this
project's own correspondence rows, which since
[#141](https://github.com/brightway-labs/brightway-flows/issues/141) are
loaded onto an empty table rather than onto a vendor's published one.

The context mapping is deliberately not among them. Those rules live in one
file keyed by `source`, read by the transform and the merge through a single
loader in `context_mapping`. A list used to name its own file, which was a
*generated projection* of that master that `build` never regenerated — so
editing the master moved one stage and left the other on a stale copy.

Values that appear in published artifacts are *derived* from it rather than
stored on it — the `source` of a created flow, the `prov:wasGeneratedBy`
activity, the minted IRI prefix for `xkos:sourceConcept`. Deriving them means a
newly added list cannot forget to set one; `tests/test_source_list.py` asserts
each derivation is the identity for ecoinvent, since these are published values
that must not move.

Adding a list is a JSON manifest in `data/sources/`, not another parameter
threaded through the merge and not a Python edit. `known_source_lists` used to
be a comprehension over `ECOINVENT_VERSIONS` — a function over one list's
releases — which made this sentence true about the shape of `SourceList` and
false about the code. It now reads the manifest directory, and
`tests/test_source_list.py` asserts that nothing outside it declares a list.

`SourceList` is not under `merge/`: the base list is a source list too, and it
is the transform's input rather than something merged.

Where the identity is *needed* it is passed, not re-derived. Loading a row and
resolving the flow layers both attach `source_refs`, and both take the
`SourceList` — they used to recover `(list_name, list_version)` from
`flow.source`, a display string, by splitting on its first dash (#13). Every
caller has the list: the transform reads the base list, the merge consumes one
it resolved. `resolve_flow_layers` counts the flows it had to build a reference
for, as `derived_source_refs`, because that count moving means something
upstream stopped attaching them.

The per-source-row logic reads its lookups from a frozen `MergeIndexes` and
writes results to a `MergeAccumulator`. `matching.build_merge_indexes` and
`build_merge_accumulator` construct them; nothing else is threaded through the
row logic. The loop over the source list is `rows.match_source_rows`, and it is
orchestration only — parse the row, honour a prepared decision, resolve the flow
object, select an elementary flow, then either record the match or report the
row — with each step a named function in `matching` or `rows`.

`merge_source_list` is left holding the order the steps run in: load, enrich,
index, match every row, place what did not match — a curator's grouping first,
then a minted flow object — report, persist (#10). A step that has no home in
that reading is a step that belongs in a module.

Correctness for this decomposition was not established by the test suite alone.
Each step was verified by running the same bounded transform, and then the merge,
under the branch and under `main` into isolated data directories, and comparing
every artifact byte-for-byte modulo embedded timestamps. `tools/verify_run.py`
is that method as a tool — it seeds a directory, runs the pipeline, and
snapshots every artifact, dumping each SQLite table row by row so that moving
an artifact into the database does not stop the comparison detecting anything. That has earned its keep — one module
split passed the full test suite while broken in four places, because no test
exercises the SQLite writer. Ruff's undefined-name and unused-import checks
caught those.

Use the same method for any further change here. An identical artifact hash is
the success criterion, except where a change is meant to alter output — in which
case say so and show what moved.

## LCIA Package Layout

`lcia` is the characterisation section, beside `merge` rather than inside it: a
factor is a statement about a flow and an impact category, and the flow it is
about is one the merge has already placed. Its design is
`plans/lcia-factors.md`; only the first module of it exists so far.

| Module | Responsibility |
|---|---|
| `pipeline` | `characterise`: the order the steps below run in |
| `categories` | the 138 `ImpactCategory` objects — EF 3.1's 25 categories times four implementations, Stepwise 2006's 19 times two — and the IRI and id each is published under |
| `sources` | which implementations exist and where each one's factors come from |
| `matching` | getting a factor onto a consensus flow: which flow, and in what unit |
| `conversion` | a factor stated per one unit, published per another |
| `collisions` | two source rows on one flow and one category, and which number survives |
| `consensus` | the third implementation: what this list publishes, and the three queues for what it will not decide |
| `contradictions` | what the model a method is derived from states, and which substances it contradicts in this build |
| `differences` | the two reports: where the implementations differ, and where one of them skips a context of a substance it characterises |
| `report` | what could not be done, as rows |
| `store` | the LCIA tables, written into the file `build` wrote |
| `scores/` | `compare-scores`: a vendor's datasets re-scored through the consensus flows and this list's factors, against the vendor's own scores, flow by flow — `compare` over records, `store` for the `score_*` tables, `pipeline` for the order |

The factors arrive through the integrations, one adapter per implementation.
`integrations/ef31.py` already parses EF 3.1's 25 method files as part of
`extract`, so the JRC's factors ride in on the base list's own flows.
`integrations/ecoinvent_lcia.py` is the second, reached by `fetch-lcia
ecoinvent-3.12`: a source list's manifest may declare an `lcia` block naming an
adapter and a file, on the same terms as its `inputs.flows`, and
`sources.fetch_source_lcia` holds it to the path the manifest states. A build
reads none of it — `characterise` matches the factors onto the consensus flows
afterwards, reading the database `build` wrote and writing the `lcia_*` tables into
it. That order is worth protecting: iterating on a rule about factors costs a
minute rather than an hour, which is why `tools/replay_selector_traces.py` exists
for the merge. `compare-scores` is a third stage in the same order, after
`characterise`: it reads the `score-*` artifacts `tools/export_unit_process_scores.py`
wrote under a brightway Python — brightway is not a dependency, and the two share
only the JSON Schema in `data/schemas/` — and writes the `score_*` tables.

The records are in `domain/lcia/records.py`, in two halves that the module keeps
apart on purpose: `StatedCategory` and `StatedFactor` are what a publisher said,
in its own words and against its own identifiers, and `LCIAMethod`,
`ImpactCategory` and `CharacterizationFactor` are what this list publishes,
joined by ours.

`domain/lcia/crosswalk.py` reads one file per LCIA method, listed in its
`METHOD_FILEPATHS`. `data/lcia-impact-categories.json` is EF 3.1's: the method,
its four implementations and where each one's factors are read from, and its 25
categories with every implementation's name for each under that implementation's
slug. `data/stepwise-2006-impact-categories.json` is the second method, the same
shape and no module changes; nothing under `lcia/` names a method or an
implementation. It is registered as a
vocabulary rather than a ruling: nobody is overruling the pipeline, this is what
the words mean.

A category slug is unique inside a method and not across methods — two methods
can both have an `acidification`, counted in different units from different
models — so every curated file that names a category by slug states which method
it is about, `lcia/scope.py` checks that, and each is read for one method at a
time. The same reason gives `lcia_differences` and `lcia_coverage` a `method`
column, and puts the method first in a factor queue's `item_key`.

`lcia/contradictions.py` reads `data/lcia-underlying-model-factors.json`, which
is what USEtox 2.1 states for the substances EF 3.1's toxicity categories are
derived from. Registered as reference data rather than a ruling for the same kind
of reason: it carries two numbers and no verdict. What makes a row a question is
the module's `comparable_categories` and its threshold, applied to what the build
in front of it states, so the file goes on being a measurement even after the data
moves and after a category stops being compared (#107).

## Releases Package Layout

`releases` is the section that runs after everything else has: it reads two
builds and says what changed between them, for a consumer who loaded the
earlier one. It imports from `pipeline` (the export's projection and the
redirects) and `domain`, and nothing imports from it.

| Module | Responsibility |
|---|---|
| `snapshot` | `ReleaseSnapshot`: a build projected onto what a migration compares — published fields, redirects, factors by triple, source rows — and its file |
| `version` | naming a release from the git tag on its commit, or as a development build where there is none |
| `alignment` | which identifier of the earlier release became which of the later: the export's redirects first, then the source rows, then the minted-identifier arithmetic as a check |
| `diff` | one `Delta` per substance, flow or factor that changed, with factors stated against the later release's flow identifiers |
| `randonneur_files` | the three datapackages and the unresolved report, written with `randonneur.Datapackage` so every field is validated against the mapping |
| `rulings` | `release-migration-rulings.json`: a curator's answer for an identifier the alignment left unresolved, refused when stale |

## Consensus Match Package Layout

`transformers.consensus_match` is a package rather than one module. The package
re-exports the transformer and the review records, so
`from brightway_flows.transformers.consensus_match import
ConsensusMatchTransformer` is unchanged.

| Module | Responsibility |
|---|---|
| `transformer` | `ConsensusMatchTransformer`: lifecycle, wiring, the loop over flow objects |
| `rules` | turning evidence into a `Change` or a review row |
| `grouping` | flow objects, the groups they fall into, and the evidence a group carries |
| `voting` | the multi-source ballot: a CAS from a name, a name from a CAS |
| `relationships` | how a name and a CAS, or two CAS numbers, relate |
| `profiles` | one merged view of a CAS, from PubChem and Common Chemistry |
| `indexes` | the ChEBI, EC-inventory and PubChem tables, loaded once per run |
| `lookups` | every network call, its throttling, and its on-disk caches |
| `rename_gate` | this run's label rulings, and the renames still waiting for one |
| `naming` | what a name looks like, decided from the name alone |
| `records` | the rows written to the review queues |

The dependency order runs down that table: `rules` reads everything below it,
`naming` and `records` read nothing. A new rule belongs in `rules`; a new source
belongs in `indexes` and `voting`.

Two things a reader might expect here are deliberately outside the package.
`rule_on_replacement` and the unruled-rename records live in
`domain.preferred_label_decisions`, because a ruling is keyed on a pair of names
and not on the stage that proposed it — the element pass in
`pipeline.element_labels` asks the same function (#16). `rename_gate` holds
only what one run of consensus matching carries around that decision.

The state the single class used to hold is now four collaborators the
transformer wires together in `__init__` and fills in `setup()`:
`SourceIndexes`, `LookupClient`, `CompoundProfiles` and `RenameGate`. They are
filled in place rather than reassigned, because `ConsensusVotes` and
`RelationshipClassifier` hold references to them from construction.

Verified the way the merge split was: the same bounded build under the branch
and under `main`, with `tools/verify_run.py compare` reporting all 23 artifacts
identical, plus `ruff --select F821,F401,F811`. The test suite is not sufficient
on its own here — see the note under the merge layout above.

## Dataclass vs Pydantic Convention

Use this rule consistently across the codebase:

- **Pydantic** for boundary contracts:
  - runtime settings/env configuration
  - validation of file/network payloads
  - persisted schema boundaries where strict validation is useful
- **Dataclasses** for internal domain/value objects and transformation-time in-memory structures.

Guidance:

- Avoid parallel models for the same concept.
- Keep one canonical context model (`domain/context.py`).
- Keep one canonical vocabulary registry (`domain/vocabulary.py`); do not
  re-declare an IRI in a module.
- Prefer translating external payloads at boundaries, then operate on internal dataclass/domain structures in pipeline logic.

Applied to flows, that split is:

- `models.HarmonisedFlow` (Pydantic) validates an input record at the file
  boundary.
- `domain.flow.Flow` (dataclass) is the working record the transform stage reads
  and writes.

These are a boundary contract and a domain object, not parallel models of the
same concept. See [Data Model](data-model.md) for each class and its use.

## Webapp Organization

`webapps.app` is the application, and the only package under `webapps`. There
were four -- `inputs`, `consensus`, `run_report` and `etl_review` -- with
shared helpers in `webapps.core` and 47 templates in `webapps.templates`. All
of it is gone; `tests/test_architecture_structure.py` pins the count, so a
second app package is a decision rather than a drift.

Inside `webapps.app`:

| Module | Responsibility |
|---|---|
| `__init__` | `create_app()`, and the section list the navigation is built from |
| `db` | one read-only connection per request, on `flask.g`, nothing at import |
| `documentation` | the `docs/` tree, read and rendered per request; no build step |
| `filters` | the Jinja filters every page shares |
| `views/` | one blueprint per section; Flask lives here and nowhere else |
| `queries/` | pure functions, a connection in and dataclasses out |
| `templates/` | `layout.html` plus one per page |
| `static/` | `app.css`, `app.js` — vendored, no CDN, no build step |

The split between `views/` and `queries/` is what makes the reads testable
without a Flask test client, which is how `run_report` came to be the only one
of the four with tests.
