# Brightway Flows

Every life cycle inventory database names its substances differently. ecoinvent
calls it `Carbon dioxide, fossil`; EF 3.1 calls it `Carbon dioxide (fossil)`;
SimaPro has its own spelling again — and each attaches it to a differently-named
compartment. Nothing in those names tells you whether two entries mean the same
thing, and nothing tells you when two entries that *look* the same are actually
different substances.

This project builds a **consensus elementary flow list**: one identity per
substance, one controlled vocabulary of contexts, and an explicit, traceable link
from every source list's flow back to that shared identity.

## What you get

For each substance in the consensus list:

- **One preferred name per language**, drawn from the source data but cleaned,
  normalised, or replaced where a clearly better-established name exists.
- **Synonyms** from [ChEBI](https://www.ebi.ac.uk/chebi/) and
  [CAS Common Chemistry](https://commonchemistry.cas.org/), filtered to remove
  names that belong to a *different* substance.
- **Chemical identity**: CAS, EC, KEGG and Gmelin numbers; molecular formula,
  mass, charge; InChI, InChIKey, SMILES, IUPAC name.
- **Semantic typing** — `Nickel(2+)` is recorded as a
  [MonoatomicIon](https://chemkg.github.io/chemrof/MonoatomicIon/) whose
  [Atom](https://chemkg.github.io/chemrof/Atom/) is nickel.
- **A definition** and links out to chemical, biomedical, and physical databases,
  and to Wikidata.
- **Provenance for every value** — which source asserted it, and which processing
  step wrote it.
- **Cross-list links**, so a flow in EF 3.1 can be translated to its
  counterpart in SimaPro or ecoinvent.

## Who this documentation is for

It is written for engineers and analysts who work with inventory data — people
who know what an elementary flow, a compartment, and a characterisation factor
are, but who do not need to read Python to use this project.

Three pages assume you are modifying the code and say so at the top:
[Architecture](reference/architecture.md),
[Conventions](reference/conventions.md) and
[Data model](reference/data-model.md). Nothing else does — including
[Harmonisation steps](reference/harmonisation-steps.md), which describes what
the pipeline decides rather than the code that runs it.

## Where to start

**"What is this project claiming, and can I trust it?"**

: [Why this exists](concepts/why.md) → [Flow objects and elementary flows](concepts/two-layers.md)
  → [How a flow is decided](deciding/index.md) → [Known limitations](reference/limitations.md)

**"How does a row in a source list become a flow in this one?"**

: [How a flow is decided](deciding/index.md) — one substance followed from the
  row a vendor shipped to the flow this list publishes, every decision on the
  way linked to the page that answers it

**"What has this actually found in the published lists?"**

: [What we have found](findings/index.md) — the errors in the source data, grouped by
  kind, each with a worked example and a count per source list

**"I know one of the source lists. What did you change in it?"**

: [What was changed in each source](changes/index.md) — one page per input
  list: the rows one name was split over, the ions given a charge, the rows
  merged into one flow, and the registry numbers corrected, each with the
  source's own identifier and the reason

**"What is still open, for the list I care about?"**

: [Open questions, by source list and by topic](reference/limitations.md#open-questions-by-source-list-and-by-topic)
  — one link per source list and per topic into the issue tracker, always current

**"I have the output files and want to use them."**

: [Which output do I need?](using/outputs.md) → [Recipes](using/recipes.md)
  → [File schemas](reference/schemas.md)

**"I have a flow list of my own and want to know which consensus flows its rows
are."**

: [Matching your own list](using/matching-your-own-list.md) — ask about a row,
  or a whole list, against a build that has already happened

**"I need to run or re-run the pipeline."**

: [Installation](operating/install.md) → [Running a transform](operating/running.md)
  → [Choosing sources](operating/sources.md) → [The review application](operating/review-app.md)

**"I am reviewing the harmonisation decisions."**

: [The review application](operating/review-app.md) → [How a flow is decided](deciding/index.md)
  → [Harmonisation steps](reference/harmonisation-steps.md)

If a term is unfamiliar, check the [Glossary](concepts/glossary.md).

## Project status

This is active research software. The consensus context taxonomy and the
harmonisation rules both still change as they meet more real-world data. The
[Known limitations](reference/limitations.md) page lists what is currently
unresolved, including cases where the output is known to be wrong — read it
before depending on the data for anything consequential.
