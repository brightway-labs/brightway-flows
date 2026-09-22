# brightway-flows

[![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.22857950.svg)](https://doi.org/10.5281/zenodo.22857950)

A toolchain for building a **consensus elementary flow list** for sustainability
analysis: one identity per substance, one controlled vocabulary of contexts, and
explicit, traceable links from every source list's flow back to that shared
identity.

It downloads and parses source data (EF 3.1 as the base, plus ecoinvent, SimaPro
via GLAD, and others), enriches chemical identity from ChEBI, CAS Common
Chemistry, PubChem and the ECHA EC inventory, applies a transparent
twenty-seven-step harmonisation pipeline followed by fourteen passes over the
two layers it produces, and exports harmonised outputs for both downstream use
and human review. A second pass puts published characterisation factors onto
those flows — EF 3.1 as the JRC published it, as the ecoinvent Centre
implemented it, as GreenDelta transcribed it, and as this list judges it should
be implemented, and Stepwise 2006 as 2.-0 LCA consultants ship it — and says
where the implementations of one method disagree. One Flask application reads
the result: the consensus flows, the changes behind them, the factors, the merge
outcome, and the queue of decisions that need a human.

For each substance in the output:

- One preferred label per language, cleaned and normalised, with synonyms from
  ChEBI and CAS Common Chemistry
- CAS and EC numbers; molecular formula, mass and charge; InChI, InChIKey,
  SMILES and IUPAC name; links to KEGG and Gmelin among the references
- Semantic typing and relationships, derived from the chemistry rather than the
  name — `Nickel(2+)` is an
  [AtomCation](https://chemkg.github.io/chemrof/AtomCation/) whose
  [`has_element`](https://chemkg.github.io/chemrof/has_element/) is nickel;
  `Alcohols, C12-15, ethoxylated` is an
  [ImpreciseChemicalMixture](https://chemkg.github.io/chemrof/ImpreciseChemicalMixture/),
  which is what a UVCB is
- A definition, and links to chemical, biomedical and physical databases and
  Wikidata
- Structured provenance for every value
- Links to the same flow as expressed in other elementary flow lists

## Documentation

**[Full documentation](https://github.com/brightway-labs/brightway-flows)** —
build it locally with `uv run mkdocs serve`.

| If you want to… | Read |
|---|---|
| Understand the model | [Why this exists](docs/concepts/why.md), [Flow objects and elementary flows](docs/concepts/two-layers.md) |
| Follow a row from a source list to a published flow | [How a flow is decided](docs/deciding/index.md) |
| See what was changed in a source list you know | [What was changed in each source](docs/changes/index.md) |
| Understand the contexts | [Flow contexts](docs/concepts/contexts.md) |
| Understand the factors | [Characterisation factors](docs/concepts/factors.md) |
| Use the output files | [Which output do I need?](docs/using/outputs.md), [Recipes](docs/using/recipes.md) |
| Match a list of your own against it | [Matching your own list](docs/using/matching-your-own-list.md) |
| Run the pipeline | [Installation](docs/operating/install.md), [Running a transform](docs/operating/running.md) |
| Review the decisions | [The review application](docs/operating/review-app.md), [How a flow is decided](docs/deciding/index.md) |
| Know whether a change worked | [Assessing a build](docs/operating/assessing.md), [`expectations/`](expectations/README.md) |
| Know what's broken | [Known limitations](docs/reference/limitations.md) |
| Modify the code | [Architecture](docs/reference/architecture.md), [Data model](docs/reference/data-model.md) |

## Quick start

Requires Python ≥ 3.14, [`uv`](https://docs.astral.sh/uv/), and Java (for
OPSIN). Budget 40 GB of disk.

```bash
uv venv
uv run brightway-flows download
uv run brightway-flows fetch-source EF-3.1
uv run brightway-flows set-commonchemistry-token --token "<COMMON_CHEMISTRY_API_KEY>"
uv run brightway-flows build
uv run brightway-flows webapp
```

Then open <http://127.0.0.1:5000>.

> **`build` merges nothing unless you ask it to.** That command builds the
> consensus list from EF 3.1 and stops, which needs no licence and no vendor
> archive. Bringing another list in is `--source`, below.

> **The first run takes several hours.** The pipeline queries PubChem, ChEBI,
> Common Chemistry and Wikidata under deliberate rate limits so as not to
> overload the providers. Every result is cached, so this cost is paid once —
> do not delete the caches.

Those caches move between machines, so the hours need only be paid once by
anybody. Given an archive somebody published with `pack-cache`:

```bash
export BRIGHTWAY_FLOWS_CACHE_URL=https://example.org/brightway-flows-cache.tar.gz
uv run brightway-flows fetch-cache        # then build as above
```

See [Start from somebody else's caches](docs/operating/install.md#start-from-somebody-elses-caches).

Outputs are written to the platform data directory
(`~/Library/Application Support/brightway-flows/` on macOS), overridable
with `BRIGHTWAY_FLOWS_DATA_DIR`. **Use that variable for test runs**:
`--max-flows` shortens a run but still overwrites the real layered artifacts and
SQLite database.

The published export is `harmonised-flows-simple.json.gz`. See
[Which output do I need?](docs/using/outputs.md) for the rest.

### ecoinvent (requires a licence)

One build does it. `build` transforms the inputs, then for each source list
enriches that list's flows — together with the consensus so far — and matches
the enriched rows. This used to take three builds, with the unmatched flows
written back out as an input file in between.

```bash
uv run brightway-flows fetch-source ecoinvent-3.12
uv run brightway-flows build --source ecoinvent-3.12
uv run brightway-flows webapp
```

Requires credentials configured for
[ecoinvent_interface](https://github.com/brightway-lca/ecoinvent_interface).
ecoinvent is **not** merged unless `--source` names it, and neither is anything
else. Merge a different version, or several lists at once, by naming each: see
[Choosing sources](docs/operating/sources.md).

## Characterisation factors

`build` publishes flows. `characterise` publishes what a flow is worth under an
impact category, and who says so. It needs the ecoinvent licence too, for the
ecoinvent Centre's implementation:

```bash
uv run brightway-flows fetch-lcia ecoinvent-3.12
uv run brightway-flows characterise
```

It reads the database `build` wrote and adds the `lcia_*` tables to it, touching
no table `build` owns, so it runs against a finished build rather than needing one
of its own. It stops if there is no build to read, and stops rather than quietly
publishing one implementation when the other's file has not been fetched.

**There is no correct implementation of an LCIA method**, so the list publishes
four of EF 3.1: as the European Commission's JRC published it, as the ecoinvent
Centre implemented it, as GreenDelta transcribed it, and as this list judges it
should be implemented given these flows. The first three are transcriptions and
change no number anybody stated. The fourth is judgment, is labelled as such
wherever it appears, and publishes nothing where the deciding implementations —
the JRC's and the ecoinvent Centre's — disagree and no curator has ruled;
GreenDelta's is published to be compared with and decides nothing.

A second method is published beside it: **Stepwise 2006**, as 2.-0 LCA
consultants ship it, with 19 categories against EF 3.1's 25.

Kresoxim-methyl sprayed on agricultural soil is worth 134.73 to the JRC and
53,540 to the ecoinvent Centre. Neither team made an arithmetic mistake: EF's own
files carry that substance twice in every context, under two EC numbers and with
different factors, and the two implementations kept different rows. A curator
ruled, in `data/lcia-factor-rulings.json`, with the reasoning attached to the
ruling.

The published files are `lcia-factors.json.gz` and `lcia-differences.json`,
whose headline is the agreement: the published implementations of EF 3.1 agree
exactly, same float, on 98.2% of the triples more than one of them states. See
[Characterisation factors](docs/concepts/factors.md).

## The review application

```bash
uv run brightway-flows webapp            # http://127.0.0.1:5000
uv run brightway-flows webapp --port 8080 --host 0.0.0.0
```

It reads one file, `consensus-flows.sqlite3`, and nothing else. If that file is
not there it says so and tells you what to run, which is the state of a fresh
checkout.

There were four applications on four ports — `webapp-inputs`,
`webapp-consensus`, `webapp-run-report` and `webapp-etl`. They are gone, along
with the commands that started them. `webapp` used to be an alias for the first
of them and is now the whole thing.

Seven sections: the overview, flows, substances, the factors, checks, the
decision queues and the merge outcome. See [The review application](docs/operating/review-app.md)
for what each holds, and [Deployment](docs/operating/deployment.md) for serving
it in production.

## Matching a list of your own

You have a flow list — your own, a client's, a version of SimaPro nobody here has
fetched — and one question about every row: **which consensus flow is this?**
Asking used to mean adding the list as a source list and running a build. It is a
lookup against a build that has already happened, and it writes nothing.

```python
from brightway_flows.lookup import FlowMatcher, FlowQuery

matcher = FlowMatcher.from_results()

answer = matcher.match(FlowQuery(
    name="Benzene, chloro-",
    context=["Emissions to air", "low. pop."],
    cas="108-90-7",
    unit="kg",
    simapro_origin=True,
))

answer.pref_label          # 'Chlorobenzene'
answer.context_display     # ('Environmental', 'Air', 'Medium stack, <150 meters',
                           #  'Rural (<1000 people/square mile)')
answer.elementary_flow_id  # 'fe0acd60-3ddc-11dd-a2e3-0050c2490048'
answer.basis               # 'cas'
```

`matcher.match_many(queries)` takes a whole list: reading the consensus list
costs a couple of seconds and answering a row costs under half a millisecond, so
2,679 rows come back in about a second.

It calls the merge's own matching functions rather than reimplementing them, so
an answer from it is the answer a build would have given. Replayed against all
16,953 rows of a three-list build, it reaches the flow the build chose for 2,490
of the 2,519 rows it has the evidence for — and places **none** of them anywhere
else. Where it cannot tell, it says so and names every substance the row could
have been.

Asked cold, with nothing but what a vendor file carries, it answers 89.1% of
BAFU's 2,679 rows. **Give it every CAS number and every synonym you have**: the
registry numbers alone are worth eleven rows in a hundred.

See [Matching your own list](docs/using/matching-your-own-list.md) for what it
cannot do — which kind of water a row is, which land class — and how to tell it.

## Did the change work?

```bash
uv run brightway-flows assess
```

The test suite says whether the code is broken. `assess` says whether the output
is right: how much of each source list lands and on what, and whether every
statement in `expectations/` still holds. Each of those statements is a file a
pull request added when it claimed to fix something — *the BAFU rows named
`Water` land on the consensus water flow* — so the claim can be run rather than
only read. Anything that does not hold is printed with the merge's own trace
behind it, including every candidate the selector scored.

`assess --record` writes the measured numbers to `expectations/baseline.json`,
which is committed, so the next pull request that improves the matching carries
`275 → 22` in its own diff. See [Assessing a build](docs/operating/assessing.md)
and [`expectations/README.md`](expectations/README.md).

## Package layout

- `application` — CLI and orchestration entry points
- `pipeline` — the transform stage, split by responsibility
- `transformers` — the individual harmonisation steps
- `integrations` — adapters for external sources (EF, PubChem, ChEBI,
  ecoinvent, EC inventory)
- `merge` — the merge pipeline
- `lookup` — answering "which consensus flow is this?" for a list nobody has
  merged, against a build that has already happened
- `lcia` — the characterisation layer: `characterise`, and the three
  implementations it publishes
- `domain` — canonical domain models, including contexts and flow objects
- `assessment` — grading a finished build against `expectations/`
- `webapps.app` — the review application: `views/` for routes, `queries/` for
  Flask-free reads returning dataclasses, one vendored stylesheet

Details in [Architecture](docs/reference/architecture.md).

## A note on sources

EF 3.1 appears to draw its synonyms from
[PubChem](https://pubchem.ncbi.nlm.nih.gov/). PubChem's synonym and
cross-reference data is crowd-sourced and contains real errors — it has been
observed linking a CAS number to a structurally unrelated compound — so neither
those synonyms nor PubChem directly are trusted as a sole basis for an identity
claim. Several guards exist specifically to catch that class of mistake; they
are described in [What do we do when one registry number reaches several
substances?](docs/deciding/registry-numbers.md).
