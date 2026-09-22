# Which output do I need?

A pipeline run writes a lot of files. Most of them are caches or review
artifacts; only a few are the actual product. This page tells you which is
which.

All of them are written to the **data directory**:

| Platform | Location |
|---|---|
| macOS | `~/Library/Application Support/brightway-flows/` |
| Linux | `~/.local/share/brightway-flows/` |
| Windows | `%LOCALAPPDATA%\brightway-labs\brightway-flows\` |

Set the `BRIGHTWAY_FLOWS_DATA_DIR` environment variable to override this —
useful for keeping a test run away from real artifacts.

## Start here

### `harmonised-flows-simple.json.gz` — the published list

**This is what most consumers want.** Gzip-compressed JSON, one entry per
non-deprecated flow, with a consistent set of fields regardless of which source
list the flow came from. Characterisation factors, internal identifiers, and
processing bookkeeping are stripped out.

```json
{
  "@context": { … },
  "schema_version": 5,
  "flows": [
    {
      "identifier": "0000b186-aea3-4c0a-b0c2-c284de7cdf92",
      "@id": "https://vocab.brightway.dev/elementary-flows/0000b186-…",
      "@type": ["http://www.w3.org/2004/02/skos/core#Concept",
                "https://w3id.org/chemrof/NeutralMolecule"],
      "source": "EF 3.1",
      "cas_numbers": ["64896-70-4"],
      "ec_numbers": ["807-840-4"],
      "context_iri": "https://vocab.brightway.one/flow-contexts/envi-air-indr-unkn",
      "unit": "kg",
      "unit_iri": "https://vocab.brightway.one/units/unit/KiloGM",
      "prefLabel": "…",
      "altLabel": ["…"],
      "properties": {
        "https://w3id.org/chemrof/molecular_formula": "C22H38O6",
        "https://w3id.org/chemrof/smiles_string": "CCCCCCCC(=O)OC1COC2C(OC(=O)CCCCCCC)COC12"
      },
      "references": ["https://…"],
      "definition": ["…"]
    }
  ],
  "redirects": [
    {
      "identifier": "0005ab9c-ad0b-4776-9ea5-5e6374140008",
      "replaced_by_identifier": "d626c3bb-c0b0-427d-a671-af3de83d1df4",
      "@id": "https://vocab.brightway.dev/elementary-flows/0005ab9c-…",
      "http://purl.org/dc/terms/isReplacedBy": {"@id": "https://…/d626c3bb-…"},
      "http://www.w3.org/2002/07/owl#deprecated": true,
      "https://vocab.brightway.one/terms/deprecationReason": {
        "@id": "https://vocab.brightway.one/deprecation-reasons/context-collapse"
      }
    }
  ],
  "concept_schemes": [ … ],
  "correspondences": [ … ]
}
```

Use it when you want a substance list, a name-to-identifier lookup, or a
translation table.

!!! note "Property keys are IRIs, not short names"

    Read as plain JSON — which is how most consumers read it — a flow's
    `properties` is keyed by the **full ChemROF IRI**:
    `properties["https://w3id.org/chemrof/molecular_formula"]`, not
    `properties["molecular_formula"]`. What is unwrapped here are the *values*:
    plain strings and numbers, rather than the `{"@value": …}` objects with
    provenance that the layered records carry.

    The short names exist, but on the other side of a JSON-LD processor. The
    `@context` declares one per term, and it maps `properties` to `@nest` — so
    expanding and compacting the document moves those keys **out of
    `properties` and onto the flow itself**, under `molecular_formula`,
    `smiles_string` and the rest, with a few appearing as `chemrof:`-prefixed
    CURIEs. A flow read that way has no `properties` key at all. See
    [JSON-LD](../reference/jsonld.md).

    Links to the source lists are **not** on the flow either. They moved out of
    it in schema version 4 and are the top-level `concept_schemes` and
    `correspondences`, one correspondence per source list.

`flows` holds only non-deprecated flows, and `redirects` says where every
identifier that left it went — 130 of them on the 2026-08-12 build. A lookup
that misses both is a flow this list has never carried; a lookup that hits
`redirects` is one it merged into another.

!!! warning "Check `deprecationReason` before following a redirect"

    Only `identity-merge` and `identifier-scheme-change` mean the two flows were
    ever the same flow; `context-collapse` fused two source contexts the
    consensus vocabulary cannot tell apart, whose characterisation factors
    legitimately disagree. All 130 redirects in this build are identity merges —
    which is not a promise that the two flows' factors agreed, only that no
    distinction was crossed. See
    [known limitations](../reference/limitations.md#what-a-redirects-reason-does-and-does-not-promise).

    `identifier-scheme-change` is the one that is always safe to follow: nothing
    about the flow changed, only what this list calls it. There are 2,561 of
    them, all from one renaming — a flow this list mints used to be named after
    whichever source row reached its compartment first, and is now named after
    the substance and the compartment.

### `lcia-factors.json.gz` — the characterisation factors

Written by `characterise`, which runs after a build. Two methods in one file.
Four implementations of EF 3.1: **the European Commission's JRC**, **the
ecoinvent Centre's**, **GreenDelta's**, and **this list's**, which publishes the
numbers the two deciding implementations — the JRC's and the ecoinvent Centre's
— agree on and asks a curator about the rest. Two of Stepwise 2006: **2.-0 LCA
consultants'**, and this list's beside it.

```json
{
  "schema_version": 1,
  "methods": [ { "id": "3c980711-…", "name": "EF", "meta": { … } } ],
  "impact_categories": [
    {
      "id": "3897dc04-68ec-5953-a76d-d40db54cc82a",
      "method": { "id": "3c980711-…", "name": "EF", "meta": { … } },
      "name": "Climate change",
      "version": "3.1",
      "implemented_by": "European Commission — JRC",
      "unit_iri": "https://vocab.brightway.one/units/unit/KiloGM-CO2eq",
      "indicator": "Radiative forcing as Global Warming Potential (GWP100)",
      "timeframe": "Long term impacts (no time horizon)",
      "meta": {"iri": "https://vocab.brightway.one/lcia/impact-category/ef/3.1/jrc/long/climate-change", "…": "…"}
    }
  ],
  "characterization_factors": [
    {
      "elementary_flow_uuid": "08a91e70-3ddc-11dd-923d-0050c2490048",
      "impact_category_id": "3897dc04-68ec-5953-a76d-d40db54cc82a",
      "amount": 1.0,
      "geography": null,
      "derivation": null,
      "source_flow_uuid": null
    }
  ],
  "stats": { … }
}
```

Four things to know before you read a number out of it:

* **An implementation is not a method.** A method's version and its implementer
  are fields on the *category*, so four implementations of EF 3.1 are 100
  categories under one method rather than four methods with one name. Two
  methods are published — EF 3.1 and Stepwise 2006 — and they share the flow
  list and nothing else.
* **A factor has no identifier of its own.** It is identified by the three
  things that make it one: `impact_category_id`, `elementary_flow_uuid` and
  `geography`. Those are the names the SQLite tables use too — an artifact and
  the table beside it describing one row two ways is a translation step nobody
  should have to make.
  There is exactly one factor per triple.
* **`implemented_by` is the field that matters.** There is no correct
  implementation of a method. EF 3.1 as the JRC published it and EF 3.1 as the
  ecoinvent Centre implemented it are two renderings of one method against two
  flow lists; both are published here, unchanged, beside this list's judgement.
* **`derivation` is empty on a transcription.** It says how *this list* arrived
  at the number — `agreed` where the implementations stated the same one, `sole`
  where only one spoke, `ruled` where a curator decided between them — and is
  `null` on the transcriptions, which arrive at nothing: they say what their
  publisher said.

`geography` is the publisher's own code, published verbatim: EF states one on
42,871 of its factors, mostly ISO 3166-1 alpha-2. Two places are two factors —
`Land use` for one flow is `-522.81` in `ES-CA` and `-227.0` in `YE`.

### `lcia-differences.json` — where the implementations disagree

The comparison, as a deliverable rather than a page to browse. One row per
(flow, category, place) triple **more than one** published implementation
states, with each side's number, the ratio and a band:

```json
{
  "schema_version": 2,
  "differences": [
    {
      "method": "ef",
      "elementary_flow_uuid": "1c9d4f7b-803f-4b74-b5fa-8bf642c94b2c",
      "category_slug": "ecotoxicity-freshwater", "geography": "",
      "implemented_by": "European Commission — JRC", "amount": 6297400.0,
      "source_flow_uuid": null,
      "band": "over-100x", "ratio": 1441.48, "derivation": null
    },
    {
      "method": "ef",
      "elementary_flow_uuid": "1c9d4f7b-803f-4b74-b5fa-8bf642c94b2c",
      "category_slug": "ecotoxicity-freshwater", "geography": "",
      "implemented_by": "ecoinvent Centre", "amount": 4368.7,
      "source_flow_uuid": "0ec92f76-932f-4407-bd4f-eb9aa426e099",
      "band": "over-100x", "ratio": 1441.48, "derivation": null
    }
  ],
  "coverage": [
    {"method": "ef", "implemented_by": "European Commission — JRC",
     "dimension": "category",
     "value": "photochemical-ozone-formation-human-health", "flows": 881}
  ],
  "stats": { … }
}
```

**`method` is on every row, and a `category_slug` means nothing without it.** A
slug names a category inside one method: another method can have an
`acidification` too, counted in a different unit from a different model, and a
join on the slug alone would put the two side by side. The same goes for the
coverage rows, where one implementer can render two methods and what it skips
under one says nothing about the other.

**One row per implementation, not per pair.** Two implementations of one triple
are two rows sharing a `band` and a `ratio`; three would be three. A column named
after a source list would have to be added for every list this project ever
compares, and would be missing from every file written before it existed — so the
report is long form, which loads into a dataframe as it stands and groups in SQL
without a pivot. On the four-list build of 2026-08-29 that is 36,744 triples,
each written as one row per implementation that states it.

**A difference is not an error.** The headline of this file is the agreement:
the published implementations of EF 3.1 agree exactly, same float at full
precision, on 36,065 of the 36,744 triples more than one of them states — 98.2%.
Of the 679 that differ, most are modelling choices between competent teams; the
36 over 100× are worth a conversation, not a correction.

Where only one implementation speaks there is no comparison to record, so those
are counted in `stats` and not listed: 302,728 triples of "nobody disagreed,
because nobody else spoke" is a fact about differently sized flow lists — and,
for the 9,624 that are Stepwise 2006's, about a method this list publishes one
implementation of.

`coverage` is the second report and a different question: where does one
implementation characterise a substance in one context and skip the context
beside it? It is a summary by compartment and by category and names no flow,
deliberately — asked as a list it is thousands of rows, most of them a substance
with no global-warming potential, where absence is the right answer.

Rows whose `dimension` is `blank` are a third count, asked of this list rather
than of a publisher: ammonium is characterised in surface water and has a river
flow that no deciding implementation states anything for. The row names the
context and how many such flows it holds after the convention in
`data/context-carry-rules.json` has filled the ones it names — 3,336 flows for
EF 3.1 on the 2026-09-01 build, 3,093 of them the unconfined aquifer, and 2,591
for Stepwise 2006, 2,126 of them aircraft cruise height — and nothing is
published for any of them. Which context a blank takes its number from, if any,
is that convention, written from these counts
([How a factor is decided](../deciding-factors/blanks.md));
`tools/count_context_blanks.py` prints the same census per pair of contexts.

Rows whose `dimension` is `identity-blank` count a blank beside a *substance*
rather than beside a context: zinc emitted to water is characterised by Stepwise
2006, zinc's ion emitted to water has a flow in the same compartment, and no
deciding implementation states anything for the ion. The row names the pair —
`Zinc(2+) — ion of Zinc` — and how many (flow, category) pairs are blank; 634
over 25 ions for Stepwise 2006 on the 2026-09-02 build before the ions were
signed, 24 over the two chromium states after, and 168 over 15 for EF 3.1.
Whether an ion takes its element's number is a signed entry in the method's
adoptions file, never a rule that reads the count.

### `releases/migrations/<from>__<to>/` — moving a database from one release to the next

Suppose you loaded a release of this list into your own database — a
Brightway biosphere, a SimaPro substance library, a method table — and built
inventories against it. The next release renames cadmium's ion, merges two
flows of chloroform in air that were the same flow, moves a resource from one
substance to another after a registry number was corrected, and revalues a
hundred factors. Reloading the whole list loses every link you made. What you
want is the list of what changed, in a form your database can apply.

That is what `release-migrations` writes: three files in
[randonneur's](https://github.com/brightway-lca/randonneur) format, one for
each kind of thing your database holds, each a datapackage naming the two
releases (`source_id`, `target_id`), saying where each field is read from
(`mapping`), and listing the changes under four verbs.

| File | What it migrates | Verbs |
|---|---|---|
| `flow-objects.json` | The substances: the `flow_objects` table | `create`, `update`, `replace`, `delete` |
| `elementary-flows.json` | The flows: `flows` in `harmonised-flows-simple.json.gz` | `create`, `update`, `replace`, `delete` |
| `characterization-factors.json` | The factors: `characterization_factors` in `lcia-factors.json.gz` | `create`, `update`, `delete` |

An `update` names the identifier and carries the whole new value of every
field that changed — a longer synonym list arrives complete, not as the one
label that was added, because randonneur overwrites a nested value rather
than merging into it. A `replace` says an identifier you hold is now another
one, with a `conversion_factor` of `1.0` where the unit is the same; the
export's own `redirects` are the first thing it is written from, and a
context-collapse redirect, which the export tells you to refuse, is *not*
written as a `replace`. A `delete` is a flow whose source rows reach nothing
in the later release, or one whose source row this list withdrew.

```python
import randonneur as rn

flows = rn.Datapackage.from_json("elementary-flows.json")
# Your flow table, one dict per flow keyed by `identifier`:
rn.migrate_nodes(my_flows, flows.data, rn.MigrationConfig(verbs=["update", "delete", "create"]))
# Your inventories, exchanges under an "edges" key:
rn.migrate_edges(my_processes, flows.data, rn.MigrationConfig(verbs=["replace"]))

factors = rn.Datapackage.from_json("characterization-factors.json")
rn.migrate_nodes(my_method_rows, factors.data, rn.MigrationConfig(verbs=["update", "delete", "create"]))
```

**Apply the flows before the factors.** The factor file is stated against
the *later* release's flow identifiers: a factor of a flow that was replaced
is written as an `update` on the survivor, not as a deletion and a creation,
and that is only right once your method rows name the survivor.

A fourth file, `unresolved.json`, is not a migration. It lists every
identifier of the earlier release the migration could not decide, with the
candidates and the reason:

| Reason | What happened |
|---|---|
| `split` | The flow's source rows now land on several flows — water released to air became water vapour and water, say — and choosing is a decision about the substance, not an arithmetic |
| `unit-change` | One flow, published in another unit; the conversion is not something to guess |
| `refused-redirect` | The export redirects it with a reason (`context-collapse`, `unclassified`) it tells you to refuse |
| `list-not-merged` | Its source rows belong to a list only the earlier release merged |
| `category-gone` | A factor of an impact category the later release does not publish |

Nothing in the three migrations mentions an unresolved identifier, so a
database you migrate keeps it as it was. Each is answered, once somebody has
looked, by a ruling in `release-migration-rulings.json`; the next run of
`release-migrations` writes the answer into the files.

What one looks like: between the build of 2026-09-02 at `944b274` and the
build of the same day at `f8867d1`, which signed Stepwise 2006's numbers onto
23 metal ions, the migration is 637 factors created, 13 flows and one
substance updated (a synonym list and a molecular formula), no identifier
replaced or deleted, and nothing unresolved. A snapshot diffed against itself
writes four files with no entries.

Two things a migration is not: a diff of every field — provenance,
`source_refs` and pipeline bookkeeping never reach your database and are not
compared — and a promise between development builds. A build of a commit no
tag names is written as `brightway-flows-<git describe>-dev`, which is
reproducible but is not a release.

### `consensus-flows.sqlite3` — everything else

The two layers, the change log, the PROV-O trail, the decision queues and the
merge outcome, in one file. Use it when you need the identity/occurrence split
explicitly — all the contexts one substance appears in, all the substances
sharing a property — or when you want to run ad-hoc queries rather than parse
JSON.

| Want | Table |
|---|---|
| Substances, with full provenance on every value | `flow_objects` |
| Occurrences: substance × context | `elementary_flows` |
| Which source rows produced a flow | `elementary_flow_sources` |
| What each step changed, and why | `changelog` |
| What the run counted about itself | `run_stats`, `pipeline_runs` |
| How long the run's stages took | `run_timings` |
| The categories and factors, as the two files above hold them | `lcia_impact_categories`, `lcia_characterization_factors` |
| A flow's factors, counted per implementation | `lcia_flow_factor_counts` |

`elementary_flows.lcia_factor_count` is **the JRC's non-zero factors** and keeps
that meaning now that there are four implementations, so a query written before
`characterise` existed still answers what it always answered. The question it
cannot answer — how many each implementation states — is
`lcia_flow_factor_counts`, a view over the factors themselves, so the two cannot
drift apart.

`flow_objects.flow_object_json` and `elementary_flows.flow_json` hold the whole
record, so anything the old JSON layer files carried is a `json_extract` away.
[Recipes](recipes.md) has worked queries. If what you have is a flow list of
your own rather than a question about this one, [Matching your own list](matching-your-own-list.md) is the page you want.

Skip the underscore-prefixed keys in `flow_json` — `_provided`, `_sources` and
`_transformed` are the transform stage's working state, not part of the flow.
They are a bit over a quarter of the column, no reader downstream of the
transform touches them, and they are absent from the published export; see
[the underscore keys](../reference/schemas.md#the-underscore-keys-are-transform-state-readers-should-skip-them).

Rebuilt from scratch on every transform run — do not edit it and expect the
changes to survive.

A release publishes this file too, beside the three JSON exports on the
Download page: it is the complete result of the build, and the exports are
views of it. It is by far the largest of the four — 3.8 GB in release 1.0,
against 45.9 MB for the harmonised flows — so the Download page states its
size before you start.

!!! note "`elementary-flows.json` and `flow-objects.json` are not written"

    The pipeline stopped writing them, and the review application reads the
    database instead. Their **record shapes** are still real, still generated
    into [File schemas](../reference/schemas.md), and still what the JSON
    columns above contain — it is the files on disk that are gone, not the
    structures. A data directory from an older run may still have them; they
    describe that run, not the current one.

## Everything else

### Intermediate artifacts

| File | What it is |
|---|---|
| `ef-31-flows.json` | EF 3.1 parsed out of ILCD XML. Input to the transform. |
| `ecoinvent-biosphere-flows-<version>.json` | One source list's flows, as fetched. Where each list's file lives is `inputs.flows` in its manifest under `data/sources/`. |

Two rows are gone from this table. `elementary-flows-merged-ecoinvent-<version>.json`
was the merge's output before it wrote to the database, and
`additional-flow-input-*.json` was a second way into the transform before a list
became a `--source` and nothing else. Neither is written.

### Review queues

These are the human-decision backlog. See
[The review application](../operating/review-app.md) for the interfaces that
present them.

These are tables in `consensus-flows.sqlite3`, not files. Each was a JSON
side-car until the review web application was consolidated onto the database;
three of them had stopped being written at all, and the pages reading them had
shown an empty state ever since, because a missing file and an empty file look
the same from a route.

| Table | Contains |
|---|---|
| `review_queue` | Every decision waiting on a curator, one row shape for all of them, split by `queue_name`: CAS ↔ EC pairings that contradict the ECHA inventory, EC numbers failing their check digit, Common Chemistry name/CAS updates and disagreements, ambiguous ChEBI matches, cases consensus matching declined to resolve, and preferred-label renames awaiting a ruling |
| `formula_mismatches` | Flow objects whose molecular formula disagrees with a ChEBI record they cite |
| `element_coverage` | Every chemical element, and whether the consensus list covers it |
| `context_default_mappings` | The rules mapping each source's raw compartments onto consensus contexts |
| `merge_outcomes`, `merge_conflicts` | What became of each source flow in the merge, and where two lists disagree |

`ecoinvent-merge-report-<version>.json` was replaced by the merge tables: it was
one file per source version and could not describe a run merging several.

### Logs

| Artifact | Contains |
|---|---|
| `changelog` (table) | Every field change from every transformer: flow, substance, field, old value, new value, which step, why. Indexed by flow uuid and by flow object id, so either layer's history is one query. |
| `provenance_activities` (table) | The PROV-O activity trail: which version of a flow each change consumed and produced. Values are on the `changelog` row with the same `change_index`. |
| `pipeline_runs` (table) | One row: the run id, its timestamp, its inputs, and what it did. |
| `run_stats` (table) | What each stage of the run counted about its own work — objects typed and why not, duplicates deprecated, properties retyped, associations per correspondence. Compare them against the last run: a drop in the typed ratio is a regression in the typing rules, and nothing else would notice. |
| `run_timings` (table) | How long each stage of the build took — one row per stage, with each transformer and each merged list named. Read it before trying to make a build faster; the answer is rarely where it feels like it is. |
| `rdkit-log.txt`, `opsin-log.txt` | Chemistry toolkit warnings, with the flow that triggered each. |

`transform-log.json` and `provenance.json` were these three tables, written only
when a run was given `--write-transform-log` / `--write-provenance`. Both flags
are gone: a review page that works only when someone remembered a flag is a
review page that does not work.

### Caches

`chebi.json.gz`, `pubchem-data.json`, `commonchemistry-cache.json`,
`compound-profile-cache.json`, `web-lookup-cache.json`, `wikidata-cache.json`,
`chemlin-isotopes.json`, `pubchem-elements-isotopes.json`, `EF-v3.1.zip`.

These hold downloaded reference data. Together they are tens of gigabytes and
represent hours of rate-limited API traffic — **do not delete them casually.**
Deleting one means re-downloading it on the next run.

The compound profile cache self-heals: entries recorded before the primary-CAS
rule was introduced are detected and recomputed rather than trusted.

`pubchem-elements-isotopes.json` and `chemlin-isotopes.json` carry a
`cache_version`, and both were bumped when the nuclide handling was corrected.
An older file is discarded rather than read, so the first run after that change
re-downloads the periodic table, 118 element pages, and one ChemLIN page per
nuclide. That is deliberate and not optional: the decay modes in an older
element cache are one row out of step on 18 elements, and there is no way to put
them back without the blank cells that were discarded when it was written.

## A caution about staleness

Files in the data directory are whatever the last run left there, and a bounded
run (`--max-flows 500`) overwrites the layered artifacts and the SQLite database
with a small subset. A `flow-objects.json` of a few megabytes is a test run, not
a full list.

Two habits avoid the confusion:

- Point test runs at a separate directory with `BRIGHTWAY_FLOWS_DATA_DIR`.
- Check the `stats` block and the file's modification time before trusting it.

## Precise field definitions

[File schemas](../reference/schemas.md) documents every field of every output
file, with types and what they mean.

If you want to validate rather than read, JSON Schemas for the four published
artifacts are checked in under `src/brightway_flows/data/schemas/`. They are
generated from the record classes and tested against real artifacts, so they are
the authority when they and the prose disagree.
