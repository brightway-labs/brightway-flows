# Running a transform

The **transform** is the main pipeline run: load the source flow lists, apply
every processing step in order, split the result into flow objects and
elementary flows, and export. This page covers the ordinary path, the fast
development loop, and the ecoinvent merge.

Prerequisite: [Installation](install.md).

## The short version

```bash
uv run brightway-flows download             # fetch the EF 3.1 archive
uv run brightway-flows fetch-source EF-3.1  # parse ILCD XML into ef-31-flows.json
uv run brightway-flows build                # the actual work, EF 3.1 alone
```

Then browse the result:

```bash
uv run brightway-flows webapp     # http://127.0.0.1:5000
```

## Expect the first run to be slow

Several hours, at least. The pipeline queries PubChem, ChEBI, Common Chemistry,
Wikidata and, for some data, parses HTML pages. Requests are deliberately
rate-limited so as not to overload the data providers.

**This cost is paid once.** Every web result is cached in the data directory, so
subsequent runs read from disk. Do not delete the caches to "start clean" — you
will only re-download the same data over the same rate limits.

**It can also be paid by somebody else.** If a machine somewhere already has
the caches, `pack-cache` writes them into one archive and `fetch-cache` unpacks
it here, which turns those hours into one download. See
[Start from somebody else's caches](install.md#start-from-somebody-elses-caches).

## Step by step

### 1. Fetch the base list

```bash
uv run brightway-flows fetch-source EF-3.1
```

`fetch-source` fetches any list, including the base one — the manifest names the
adapter and `fetch-source` runs it, so there is nothing per-list to remember.
See [Adapters](sources.md#adapters). It downloads the archive first if needed,
so `download` on its own is only useful for pre-fetching.

`extract` is the older name for this one list, and still works. Two options live
there rather than on `fetch-source`, because neither is a property of fetching a
list:

| Option | Effect |
|---|---|
| `--force`, `-f` | Re-download even if the file is present |
| `--keep-zip`, `-k` | Keep the ZIP after extraction (it is deleted by default) |
| `--ingest-glad-mapping` | Also fetch the GLAD ILCD→SimaPro correspondence table |

GLAD is off by default: the table is read only by a build that merges a list
whose flows originate in SimaPro, so fetching its 11 MB and parsing its 124,318
rows on every extract cost every build and published nothing.

### 2. Refresh reference data (optional)

```bash
uv run brightway-flows chebi     # download ChEBI, report node statistics
uv run brightway-flows pubchem   # populate the PubChem cache
```

Both are incremental, and the transform fetches what it needs on its own. Run
them separately when you want the downloads to finish before starting the long
job, or to refresh a source deliberately with `chebi --force`.

`pubchem --limit N` populates only part of the cache — useful for a quick check
that the connection works.

The first `pubchem` run after upgrading to the curated-CAS gate is longer than
usual. A compound whose PubChem record holds no registry identifiers is now
cached as an empty record instead of being discarded, so it stops being
re-requested on every run — but the CIDs that were discarded before have to be
fetched once to be recorded. That was 4,172 of the compounds reachable by CAS.
The gate needs this: it distinguishes "PubChem was asked and holds no CAS for
this compound" from "nobody asked", and only the first may drop a candidate.

### 3. Transform

```bash
uv run brightway-flows build
```

That is the whole command. It transforms EF 3.1 into the consensus list and
merges nothing, which is what you want unless you have another list to bring in.
A run that merged nothing says so, with `no_source_lists_to_merge`.

| Option | Effect |
|---|---|
| `--source KEY`, `-s` | Merge a source list; repeatable. **Nothing by default** |
| `--max-flows N` | Process only the first N flows of the base list |
| `--include-uuid UUID` | Keep this base-list flow in a `--max-flows` run whatever its position; repeatable |
| `--max-rows N` | Merge only the first N rows of each source list |
| `--include-source-uuid UUID` | Keep this source row in a `--max-rows` run whatever its position; repeatable |
| `--dry-run`, `-n` | Write no artifact: run the transform without its writes, and skip the merge |

To bring another list in, name it:

```bash
uv run brightway-flows build --source ecoinvent-3.12
uv run brightway-flows build --source ecoinvent-3.12 --source bafu-2026-v1
```

Every list that can be merged needs something you have to obtain — an ecoinvent
licence, or the BAFU archive, which BAFU hands over rather than publishing. That
is why merging is asked for rather than opted out of: the base list on its own
needs none of it, and it is the product. `--source` defaulted to
`ecoinvent-3.12` until
[#99](https://github.com/brightway-labs/brightway-flows/issues/99), which
made the ordinary invocation of the ordinary command a build that could not
finish without a licence.

The base list itself is not a `--source`. It is the list every other list is
merged *into*, so naming it is not a build anyone means to run, and
`resolve_source_list` refuses it.

Where several are named, they are merged in the order their manifests declare,
not the order the flags were typed: the first list to reach a substance mints its flow object and
everything after it matches against what that list created, so the order is a
property of the lists. A run that reorders them says so with
`source_order_set_by_manifests`.

Every run writes its full change log, its PROV-O activity trail and every review
queue into `consensus-flows.sqlite3`. There is nothing to opt into:
`--write-transform-log`, `--write-provenance` and `--export-consensus-review`
are gone, along with the JSON files they produced. They were off by default
because the files were large — which meant the review pages reading them
normally showed nothing, and nothing said why.

The transform's input is EF 3.1 and nothing else. Every other list is a
`--source` — see [Choosing sources](sources.md).

### 4. Look at the result

```bash
uv run brightway-flows webapp     # http://127.0.0.1:5000
```

One application over the database, in six sections: the overview of what the
run did, the flows, the substances behind them, the checks, the queue of
decisions waiting on a curator, and what the merge made of each source row.

See [The review application](review-app.md).

## The development loop

Do not run a full transform to test a change. Bound it, and isolate it:

```bash
BRIGHTWAY_FLOWS_DATA_DIR=/tmp/bwf-test \
  uv run brightway-flows build --max-flows 500
```

Two things matter here.

**`--max-flows` alone is not isolation.** It shortens the run but still writes
the database to the data directory, replacing real outputs with a 500-flow
subset. Setting `BRIGHTWAY_FLOWS_DATA_DIR` is what keeps a test run from
clobbering real data.

`--dry-run` writes no artifact — the transform runs without its writes and the
merge is skipped, which it says with `dry_run_skipped_merge`. That makes it a
smoke test of the transformers rather than a way to produce a bounded build: a
run that skips the merge has not exercised it, and leaves whatever the last
real build wrote in place.

**Two diagnostic logs are the exception.** `rdkit-log.txt` and `opsin-log.txt`
are cleared and rewritten by the transformers that produce them, in `setup()`,
before the flag is consulted — so a 20-flow dry run replaces a full run's
warnings with 20 flows' worth. Nothing reads them but a human debugging a
structure problem, and that is the run whose warnings they will want.

So: `--dry-run` to check that a change runs clean, a separate data directory
whenever you care about what is left behind.

**A separate directory means separate caches.** A fresh directory re-downloads
reference data. For repeated testing, keep one dedicated test directory and
reuse it rather than making a new one each time.

**A bounded run merges against a bounded consensus list.** `--max-flows` cuts
the transform, not the merge: every source row is still matched, against a
consensus list holding only the first N base-list flows. So a bounded run places
fewer rows and creates more, and a curated grouping onto a flow object outside
the slice is skipped with `manual_addition_target_outside_bounded_slice` rather
than applied. Counts from a bounded run describe the bound as much as the data;
compare them with another bounded run of the same size, never with a full one.

**Bounding the merge as well.** `--max-rows N` reads only the first N rows of
each source list, and `--include-source-uuid` keeps a row you name whatever its
position — the same pair as `--max-flows` and `--include-uuid`, on the other
side of the run. `--max-flows` bounds the transform alone, so a build bounded
to 400 flows still matched all 9,850 rows of ecoinvent 3.12 against those 400.

On the 2026-08-15 verification run of this machine that merge was 25.9 seconds
of a 135-second build — the largest single stage, and more than the 21.7
seconds its enrichment spent running the transformer chain over rows the run
was never going to be about. Repeating it with `--max-rows 1000` took the merge
to 7.4 seconds. On a full build the difference is larger, because then each of
those rows is matched against 94,000 consensus flows rather than 400.

A bounded merge is recorded rather than inferred. Each list's row in
`merge_run_inputs` carries the rows read, the rows the list ships, and the
limit, so `1,000 of 21,088` is visible in the database and in the snapshot
`tools/verify_run.py` takes of it. `assess` prints it as a warning and refuses
to record a baseline from such a run, for the reason `--max-flows` already
could not: every merge count would be recorded as a prefix of the list.

**Where the time went.** Every build writes a `run_timings` table -- one row per
stage, with the transformers and each merge named individually -- and ends with
a `build_timings` log line listing the slowest dozen. Read that before changing
anything for speed. The table is dropped and rewritten per build, and its
durations are masked by the verification harness, so it does not make two runs
of the same code look different.

## Merging ecoinvent

Requires an ecoinvent licence and credentials configured for
[ecoinvent_interface](https://github.com/brightway-lca/ecoinvent_interface).

```bash
uv run brightway-flows fetch-source ecoinvent-3.12
uv run brightway-flows build --source ecoinvent-3.12

# Review what happened
uv run brightway-flows webapp
```

This used to be a **two-pass** workflow: flows that matched nothing were written
back out as an input file by a separate command, fed through the transform on a
second build so they received the full treatment, and matched again on a third.
That command is gone, and so is the second pass — and with it the file it wrote,
which gave a consensus flow the *source list's* uuid and so made one uuid name
two different things as soon as both were handled together.

The input route it fed is gone too. `--input`, `transform-sources.json` and
auto-discovery of the data directory each let a file's rows become consensus
flows without being matched against anything, which is the same thing a source
list does badly. There is one concept now, and it is `--source`.

`build` now enriches each source list before it matches it. The transformers run
over that list's flows *and* the consensus so far, in one list — they compare and
group across it, so showing them only the new rows would blind deduplication and
consensus matching — and the source rows carry their enrichment straight into
matching.

Three things this does not do, each deliberate:

- **It writes only to the source list.** The consensus flows are shown, never
  changed. The chain is ordered for a single pass over raw input and is not
  idempotent — `normalize_name_case` runs fifth and re-title-cases labels that
  `consensus_match` sets at fourteenth — so running it again over its own output
  degrades it. Each flow carries
  `_transformed`, so the loop can be handed both sides at once and works this
  out for itself.
- **It does not re-derive flow objects.** Matching indexes on those, so the
  benefit within one merge comes entirely from the source side: better names,
  CAS and EC before lookup.
- **It does not let enrichment reroute a row's context.** The source list's own
  context mapping still decides where its rows land, keyed on the strings the
  list shipped — which the flow keeps in `_provided`, because the chain replaces
  them rather than only adding to them.

Matching looks up **every** name a row is known by: the label enrichment settled
on, the name the source list shipped, its synonyms, and the alternative labels
enrichment found. Looking up one name breaks the moment enrichment renames the
row, which is how `MCPA` stopped matching once it became
`(4-Chloro-2-methylphenoxy)acetic acid`.

Each merge tries previously-reviewed match decisions first and falls back to the
matching algorithm. Results land in `consensus-flows.sqlite3`: what became of
each source row is the `merge_outcomes` table, and where two lists disagree is
`merge_conflicts`. Both are keyed by run, so one run merging several lists is one
set of rows — see [Which output do I need?](../using/outputs.md).

**Which lists are merged is the `--source` option**, and nothing else — see
[Choosing sources](sources.md).

## Scoring a release's unit processes with brightway

Take one dataset — `electricity production, wind, >3MW turbine, onshore` in
Sweden, one kilowatt-hour — and ask what it is worth under EF. Brightway answers
with ecoinvent's own flows and ecoinvent's own factors. This list answers with
the same flows mapped onto consensus flows and *our* factors. Where the two
disagree, the reason is one of a short list: a flow that did not map, a flow we
have no factor for, or a factor that differs. Asking that of a few hundred
datasets at once, rather than of one by hand, is what the score artifact is for.

The brightway half runs under a brightway Python, not this project's — brightway
is not a dependency of the list. The two share nothing but a JSON file and the
schema that describes it:

```bash
# Which releases, how many datasets, which seed, where the file goes.
uv run brightway-flows score-comparison-config > config.json

# Under a Python with bw2data, bw2calc and bw2io installed:
~/venvs/bw25/bin/python tools/export_unit_process_scores.py config.json \
    --release ecoinvent-3.8-apos
```

The first run of a release imports it into brightway from ecoinvent's own
archives, which takes a few minutes and needs
[ecoinvent_interface](https://github.com/brightway-lca/ecoinvent_interface)
credentials; every run after that opens the project it made. The sample is
drawn with the seed in the config, so the same seed over the same release
scores the same datasets, and a named list of activity codes is always
included whatever the sample says. The script scores each release with the
method family it *ships* — ecoinvent 3.8 carries EF v3.0, 3.12 carries EF v3.1
— and refuses to write a file whose scores its own inventories and factors do
not reproduce.

Then, after `characterise`:

```bash
uv run brightway-flows compare-scores
```

which re-scores every dataset in the file through the consensus flows and this
list's own factors and writes the `score_*` tables: each dataset under each
category both ways, every flow whose contribution differs and why, and the
flows ranked by how much of a category's total they move.

The releases, the sample size, the seed and the directory are settings, not
constants: `settings.json` in the data directory, or `SCORE_COMPARISON__…` in
the environment, and the default directory is `unit-process-scores/` under the
data directory. A curator keeping the files outside any worktree points
`artifact_dir` at them.

## Validating contexts

After editing the context definitions:

```bash
uv run brightway-flows contexts
```

This validates the definitions and regenerates the list-of-strings expression of
each context. It used to also split the default mappings into one file per
source; the transform and the merge both read `context-manual-mapping.json`
directly now, so there is nothing to split
([#11](https://github.com/brightway-labs/brightway-flows/issues/11)) and
`--manual-mapping-file` is gone with the splitting. The two paths that remain
can be overridden:

```bash
uv run brightway-flows contexts \
  --contexts-file path/to/consensus-flow-contexts.json \
  --strings-file path/to/consensus-flows-as-strings.json
```

## Recording a release, and writing the migration to the next one

A build drops and recreates its tables, so nothing in a database says what
the release before it published. When a build is a release, record it:

```bash
git tag 1.0.0                       # the commit the build was made from
uv run brightway-flows build --source ecoinvent-3.12 --source ecoinvent-3.8 \
    --source bafu-2026-v1 --source stepwise-2006-1.09 --source agribalyse-3.2
uv run brightway-flows characterise
uv run brightway-flows release-snapshot
```

The snapshot goes to `releases/1.0.0.json.gz` in the data directory: the
published fields of every substance and flow, the redirects, the factors, and
the source rows that let the next release's identifiers be matched to this
one's. The build's commit is named by its git tag; a build of an untagged
commit is a *development* build, named by `git describe` and marked `-dev`,
and a build from a modified tree is refused. `--version` names a build by
hand, for one made from an exported tree.

When the next release is built, write what changed:

```bash
uv run brightway-flows release-migrations --from 1.0.0 --to 1.1.0
```

`--from` and `--to` take a recorded version, a snapshot file, or — for `--to`
— a build's `consensus-flows.sqlite3`, which is snapshotted without being
recorded (`--to-version` names it). The four files go under
`releases/migrations/1.0.0__1.1.0/`; what they hold and how a consumer
applies them is in [Which output do I need?](../using/outputs.md#releasesmigrationsfrom__to-moving-a-database-from-one-release-to-the-next).
The two releases must have merged the same source lists;
`--allow-different-sources` lets the run proceed with every row of a list
only one side merged left unresolved rather than deleted.

The `unresolved.json` it writes is the worklist. A split, a unit change or a
refused redirect is answered in `release-migration-rulings.json`, naming the
pair of releases, the entity and the identifier; run `release-migrations`
again and the ruling is in the files. A ruling that names an identifier the
pair did not leave unresolved is refused as stale.

## All commands

| Command | Purpose |
|---|---|
| `release-snapshot` | Record what this build publishes, named by the git tag on its commit, for `release-migrations` to read |
| `release-migrations` | Write the randonneur migrations — substances, flows, factors — from one recorded release to the next, and the list of what could not be resolved |
| `fetch-source <key>` | Fetch one source list's flows, whichever list it is |
| `fetch-lcia <key>` | Fetch one source list's characterisation factors |
| `download` | Download the EF 3.1 ZIP |
| `ingest-glad-mapping` | Download and parse the GLAD ILCD→SimaPro workbook |
| `chebi` | Download ChEBI and report node statistics |
| `pubchem` | Populate the PubChem cache |
| `set-commonchemistry-token` | Persist the Common Chemistry API key |
| `fetch-cache` | Unpack somebody else's cache archive into this data directory |
| `pack-cache` | Write this data directory's caches into one archive for somebody else |
| `build` | The main pipeline run: transform EF 3.1, then merge each `--source` |
| `characterise` | Match the published characterisation factors onto the consensus flows |
| `compare-scores` | Score each release's sampled unit processes through the consensus flows and factors, and compare with the vendor's own scores flow by flow |
| `score-comparison-config` | Print, as JSON, which vendor releases the unit-process score comparison reads and where their artifacts live — for the brightway-side exporter, which cannot import this package |
| `contexts` | Validate and regenerate context definitions |
| `webapp` | The review application, port 5000 |

`extract` and `download-ecoinvent-flows` are aliases for `fetch-source EF-3.1`
and `fetch-source ecoinvent-<version>`. They route through the same registry
lookup and the same adapter, so they cannot drift; `extract` additionally
carries `--keep-zip` and `--ingest-glad-mapping`.

`webapp-inputs`, `webapp-consensus`, `webapp-run-report` and `webapp-etl` are
gone with the four applications they started. `webapp` was an alias for the
first of them and is now the whole thing.

Every command accepts `--help`.
