# The review application

One application, one port, one database.

```bash
uv run brightway-flows webapp            # http://127.0.0.1:5000
```

`--host`, `--port` and `--debug` are all it takes. It reads
`consensus-flows.sqlite3` from the data directory and nothing else, so it shows
whatever the last build produced. A missing database is a page naming the path
and the command that fills it, not an error. For serving it properly, see
[Deployment](deployment.md).

## Where the four applications went

There were four — `webapp-inputs` on 5001, `webapp-consensus` on 5002,
`webapp-run-report` on 5003 and `webapp-etl` on 5004 — each with its own
navigation, its own idea of what "no data" looks like, and no links to the
others. They are gone, along with their commands.

What replaced them is organised by the question being asked rather than by
which application used to own the page:

| Section | Question | State |
|---|---|---|
| Docs | What is a flow object, and why was this one deprecated? | **built** |
| Current run | What did the last build do, what is waiting on me, and where do I download it? | **built** |
| Flow objects | What is this substance, and which flows resolve to it? | **built** |
| Elementary flows | What is in the list, and why is this flow called that? | **built** |
| Factors | What is this flow worth, and where do two methods disagree? | **built** |
| Checks | Where might an identity resolution have gone wrong? | **built** |
| Queue | Which decisions need a human? | **built** |
| Merge | What happened when a source list was merged in? | **built** |

**The homepage is the front page, and the documentation is at `/docs/`.** `/`
says what the list is, where to download it and how to cite it, with the
build's counts and the questions this documentation answers; the page you are
reading now is served from `/docs/`, and the build's own state is at `/run/`.
Somebody arriving at a published flow list is asking what it *is* before they
ask what the last run counted. The sections above are listed, each with a
sentence, at `/browse/`.

All of them are built. The navigation lists only routes that exist, which is
enforced by a test rather than intended. `plans/webapp-consolidation.md` holds the page-by-page inventory of what
each of the four applications showed and where each page went — including the
pages that were dropped, so those decisions are reversible from that document
rather than from git history.

### What was dropped, and why

**The input layer.** The `inputs` application browsed source flows as they were
*before* harmonisation, and is not being ported. Its CAS-conflict and duplicate
checks survive at the consensus layer, where they are more useful: **Checks →
duplication report** finds one CAS claimed by flows that disagree, and **Checks
→ shared labels** catches the inverse. Per-flow source provenance survives too,
on the flow detail page, which lists every source list a flow came from and the
name it had there.

**LCIA methods and characterisation factors.** Both pages lived in the `inputs`
application. The `lcia_factor_count` column stays on the flows table, because
"is this flow characterised by anything at all" is a property of the flow.

**The ecoinvent sub-dashboard.** Six pages, answered better by the merge
tables: they are not scoped to one version's JSON file, and they can describe a
run that merged several source lists.

---

## Current run

What the last build did, and what it is waiting on, at `/run/`.

The four applications could not have had this page. The ETL dashboard counted
its own queues, the run report counted the merge, and neither knew the other
existed — but they are one build.

It leads with what needs a curator: decisions blocked in the queues, and source
flows the merge could not place. When the build was bounded with `--max-flows`
it says so *before* any count, because every number on the page then describes
part of the list rather than the list.

**Take it away** at the foot of the page is the four files the build publishes,
as downloads: `consensus-flows.sqlite3`, which is everything these pages read,
and the three JSON exports — the harmonised flows, the characterisation factors
and the differences between the implementations. Each row states the size before
you start, and a file this run did not write says so rather than disappearing:
a build that has not been characterised has no factor file, and that is worth
knowing. [Which output do I need?](../using/outputs.md) says what is in each.

The page names no file paths. It used to print the database and every input by
absolute path, which is a fact about one machine and no use to a reader who has
no account on it — and it was the only thing on the page that came close to
answering "how do I get this data?". The inputs are still listed, by file name.

**What each stage did** is the section to read run over run. Every stage of the
pipeline counts its own work — objects typed and the reason each untyped one
was left alone, duplicates deprecated, properties retyped, associations per
correspondence — and those numbers used to be logged and dropped. A fall in the
typed-object ratio is a regression in the typing rules; a non-zero
`skipped_unknown_scheme` means a source list is minting flow IRIs under a prefix
nothing recognises. Neither has any other detector.

---

## Flow objects and elementary flows

The two layers of the list, named in the navigation the way the data model
names them.

**Flow objects** are identities: names, synonyms, registry numbers, properties,
references, and a rendered structure diagram. Carbon dioxide is one flow
object however many places it is released into. **Elementary flows** are that
substance in one context, with the source list, unit and every applied change:
carbon dioxide to air and carbon dioxide to water are two of them, sharing a
flow object. A source list carries a row per elementary flow, which is why a
list of 9,850 rows names far fewer substances.

The flow objects live under `/flow-objects`. `/substances` — what the consensus
app called them, and the last place that word survived — redirects permanently
to the same pages, so an old link or a bookmark still lands.

A flow object's page names each stored property in words *and* in the term the
published document is keyed by: `CHEMINF_000446` is "CAS registry number", and
nothing about the accession says so, but the accession is what a curator greps
for. Below the properties, **Known URLs** is every external record the pipeline
resolved this substance against — ChEBI's cross-references, PubChem's
identifier list, the CAS registry — each credited to the pass that recorded it.
They are evidence the merge read, not searches it suggests, which is why the
column says which pass rather than nothing at all.

The flows table filters on source, unit, type, deprecation and eight context
axes, and searches full text with a name-only mode. Applied filters appear as
removable chips above the table — the page this replaces had eleven unlabelled
dropdowns and no other indication of what was filtered.

Every dropdown in the application is in alphabetical order with a count beside
each value, and a type is named the way its vocabulary names it: `ENVO_01000892`
is *area of cropland* and `NeutralMolecule` is *neutral molecule*. Both lists
were ordered by how many rows each value had, which is no order at all once the
list is longer than a screen.

**Both list pages open at a random page** when you arrive with nothing asked
for. Sorted by name and opened at the first page, the only substances anybody
ever saw were the ones beginning with a digit — the page says which page it
picked and links to the beginning. Searching, filtering, sorting or asking for a
page all land where you asked, as before.

Deprecated flows are hidden unless asked for. They have been replaced, and a
reader looking for a substance wants the row that is current; the substance
page lists them regardless, because that is where you go to find out what
happened to one.

The flow detail page is the one to reach for when asking "why is this called
that?". Its history — the change log, the PROV-O trail and the per-field
summary — is the heaviest part of the page and the least often read, so it sits
behind `/flows/<uuid>/changes`, as a `<details>` that fetches the section on
first open. With JavaScript off the same link lands on the full page. Nothing on
the detail page queries for history, and a test asserts the query is never
issued.

It also answers "why is this the same flow as that one?". **Source lists** names
every source flow this one was built from and, beside each, why the merge holds
it to be this flow: *The CAS numbers are the same (76703-62-3); both name the
same compartment*, or *A curated override row names a flow that has since been
deprecated, and this flow replaced it*. **Concept associations** below it is the
same links as they are published — the source flow's own identifier, name and
compartment, how strong the mapping is claimed to be, and the unit conversion
where the two lists measure the substance differently.

`/flow-objects/<id>/changes` is the same arrangement for a substance. It has no
PROV-O trail — the graph is per flow version, and a substance is not a version
of anything — but it does have the change log, because `changelog` is keyed by
`flow_object_id`. The flow-level page reaches the same rows through
`changelog_flows`.

A row on either page is one *edit*, not one edit per affected flow, so a row can
name several flows. An edit to a substance lands on every elementary flow
sharing it — stripping the catalogue labels off Silicon Dioxide touched
fourteen — and listing it fourteen times was both a worse page and 3.7 GiB of
duplicated payload.

---

## Factors

What each implementation of a characterised method says, and where they differ.
Unlike Queue, this section asks nothing — it is the layer as it stands, for a
reader who wants to know what this list says a substance is worth. See
[Characterisation factors](../concepts/factors.md) for what the three
implementations loaded today are and why there are three.

Nothing in this section names a method or an implementation. EF 3.1 is what is
loaded today and it is not what will be loaded, so the sections, the columns and
the labels all come from the rows `characterise` wrote. The index is a section
per method; within it, the column that is always there — what *this list*
publishes — comes first, and everything read is a stack of one line per
implementation in a single column. A fourth implementation adds a line, not a
column, and no template has to learn its name.

| Page | Shows |
|---|---|
| `/factors` | A section per characterised method, a row per impact category, with what this list publishes and what each implementation it read states. Keyed on *our* category name: the JRC calls it `Ecotoxicity, freshwater` and ecoinvent calls it `ecotoxicity: freshwater`, and without the crosswalk this would be 50 rows that never line up. An implementation that published nothing says why rather than showing a bare zero — `ecoinvent Centre 0` means its factors named flows the characterised build never merged, not that its file was empty |
| `/factors/category/<method>/<version>/<slug>` | One category opened: every factor published under it, one row per flow and place, as many implementations wide as there are. Ordered by the largest number anybody states, because the question a category is opened with is which substances it weighs heavily. Addressed the way the category's own IRI addresses it, so a second method publishing a `Climate change` of its own is a different page rather than the same one |
| `/factors/category/<method>/<version>/<slug>/differences` | The same category narrowed to *two* of its implementations, and only the rows where they state different numbers. The headline is still the agreement — the JRC and ecoinvent state 179 numbers about `Climate change` and 167 of them are the same number, to the last bit. The band is the pair's own: the report bands a row by the widest disagreement among everybody who states it, which with four implementations loaded is a different verdict about the two on the page. Opens on two publishers rather than on this list and a publisher, because ours is derived from theirs and agrees with one of them by construction |
| `/factors/differences` | Every (flow, category, place) row more than one implementation states, sorted by ratio, filterable by band. The headline is the agreement: 21,637 of 21,944 identical in the build of 2026-08-18. A band is a filter, not a verdict, and the filter offers the four answers — incomparable, outside tolerance, within tolerance, identical — rather than the seven bands, which the ratio column states exactly anyway |
| `/factors/coverage` | Where one implementation characterises a substance in one context and skips the context beside it — counts by compartment and by category, never a list of flows |
| `/factors/findings/…` | What `characterise` found and did not silently resolve: factor collisions, unit crossings, the numbers a merge declined, and source rows that reached no flow. Each kind gets the table its evidence needs rather than a column of sentences — a collision names the two source rows and what each states, a declined number puts the two numbers and the ratio between them in columns you can sort by *and names the two rows the flow was settled from*, and an unreached row carries the publisher's own name, compartment and factors, because it is the row that did *not* become a flow and nothing else in the database can name it |

A flow's own page carries the same question about one flow: one row per factor,
with the method first and the implementation beside it, sortable by any column,
and what this list published and how it arrived at it. One row per factor rather
than a column per implementation, because a flow is characterised by several
methods and their implementations do not line up across methods — the wide table
grew a column for every implementation of every method and left most of them
empty. The table sits after the concept associations: what a flow *is* comes
before what it is worth.

Two things this section deliberately does not do. It does not compute impacts —
this list publishes factors and does not do LCIA — and it does not resolve a
disagreement. Where two implementations state different numbers for one triple,
this list publishes neither and asks; those questions are `contested-factor`,
`proposed-factor` and `contradicted-factor` under Queue — the third being where
the two implementations agree and the model they are both derived from does not.

The pages need a `characterise` run. A build that has only been built gets a page
saying so, rather than three columns of zeros: "nobody has asked yet" is a
different statement from "characterised by nobody".

---

## Scores

A sample of a vendor's datasets scored with the vendor's own factors and again
with this list's, on the same inventory, and the flows that carry the
difference. See [Scoring a dataset two ways](../using/scores.md) for what the
two sides are and the six reasons a flow can differ. Nothing here names a
release or a method: a release is a card, and a third release is a third card.

| Page | Shows |
|---|---|
| `/scores` | One card per compared release, labelled with the method it was scored with, and under it a row per category the vendor scored: how many datasets agree within 2%, how many are within 2× and 10×, how many are worse, and the median of ours over theirs. A vendor category the crosswalk has no row of ours for — EF 3.0's `metals` toxicity categories — is on the table, marked, and not linked |
| `/scores/<release>/category/<key>` | One category opened: the vendor's flows ranked by how much of the category's total across every dataset each one moves, with the reason, how many datasets it touches, and the worst single dataset. The order to fix things in. Filterable by reason |
| `/scores/<release>/datasets` | The sample, searchable by activity, product, geography or code |
| `/scores/<release>/dataset/<code>` | One dataset: every category both ways, and under the chosen one every flow whose contribution the comparison kept — the hand analysis done for one activity, for any dataset of the sample |

Rendered as "no score comparison yet" where `compare-scores` has not run,
rather than as a table of zeros.

## Checks

Where an identity resolution may have gone wrong.

| Check | Finds |
|---|---|
| Shared labels | A name on more than one substance — the signature of a false synonym |
| Formula mismatches | A substance whose formula disagrees with a ChEBI record it cites |
| Duplication report | Duplicate CAS numbers, duplicate alt labels, CAS repeated as an alt label |
| Duplicate contexts | Violations of the one-row-per-substance-and-context invariant |
| Isotope gaps | `kBq` flows carrying no isotope metadata, with the reason: an aggregate rather than a nuclide, a nuclide the tables have no row for, or a record that failed its own consistency checks |
| Unit disagreements | A source row measured in something other than the flow it landed on |

Shared labels and formula mismatches are both false-merge detectors. Anything
they find is a real error, not a stylistic one. See
[What do we do when one registry number reaches several substances?](../deciding/registry-numbers.md).

Unit disagreements reads the merge's own report rather than the list, and its
rows are two kinds. A **matched** row disagrees with a flow the list already
had; some of those are deliberate, and `unit-change-allowlist.json` is where
that is written down. A **created** row is one of a group that made a new flow
between them and did not agree on its unit — the flow states one, and the
others are listed. Only `needs a decision` is asking for anything: it means the
rows disagreed and neither `published-units.json` nor `units.json` had a unit
to choose between them, so somebody has to write the answer into
`created-flow-unit-decisions.json`.

---

## Queue

Where the pipeline declined to decide. A work queue, not a browser. Twenty
queues, in two sections, because they are two kinds of work and do not even come
from the same run: **Flows and substances** are written by a build and ask what a
substance *is*, **Characterisation factors** are written by `characterise` over a
build that has already finished and ask what it is *worth*. So the two halves of
the index can be of different ages against one database. Within each section the
queues are in the order worth working them — the cheap mechanical ones first,
because they improve every identity decision downstream.

| Queue | Decide |
|---|---|
| `ec-malformed` | A string no EC number can be recovered from — not in the form `NNN-NNN-N`, or a check digit landing on a slot the register skipped rather than issued. Empty on the current build: it held 130 rows until #120, all of them real numbers from the block ECHA issued with a check digit of 1 |
| `ec-cross-check` | A CAS ↔ EC pairing contradicting the ECHA inventory |
| `commonchem-name-cas` | Common Chemistry gives a different CAS for this name. Applied when the flow had none; otherwise the flow's CAS was kept — does the name match beat it? |
| `commonchem-cas-name-differences` | Common Chemistry's name for this CAS differs from the flow's |
| `cas-ambiguous` | The name resolves to several ChEBI records and none carries the flow's CAS — which of them is the substance? One row per name and source list, however many flows carry it: the candidates come from the name alone, so `2-hydroxypropanoic Acid`, filed in thirteen contexts, is one question. Each number is shown with what the registries call it, because `299-85-4` against `71-58-9` is not a question anyone can answer by reading it and `Zytron` against `medroxyprogesterone acetate` is |
| `curated-cas-exclusion` | A compound dropped from a CAS lookup because its own curated record does not list that number — was dropping it right? |
| `commonchem-structure-exclusion` | Common Chemistry publishes no structure for this CAS, so none was looked up through it — is the number really a UVCB or an unspecified isomer? Or it registers the number without stereochemistry, so a stereoisomer offered for it was refused — is the flat key a statement or a gap? |
| `contested-cas` | More than one flow name in one source list carries this registry number and nothing decides whether they are one substance — they stay merged; are they? |
| `stereo-disagreement` | A structure that survived every gate and still disagrees with Common Chemistry about the same skeleton — which side is right? The `kind` column says which question is being asked, and only four of the nine are questions. `conflict` is a real contradiction and wants a curator; `lost` and `ours-undetermined` are gaps in the published record that the pipeline could not fill this time. `protonation` is not about shape at all: the object publishes CAS's substance with hydrogen ions added or taken away — an acid and its ion — and which of the two the object is for is the question. `cas-undetermined` is a gap in the *registry's* record — our fuller structure stands, and the row is `info`. `restored` is a gap the pipeline filled from the registry's own structure, `incomparable` is a comparison that could never run, and both are `info`. `superseded` and `protonation-withdrawn` are a second key withdrawn because another on the object is the registry's own, and are `review` because a structure claim was discarded |
| `elementary-flow-collision` | Two live flows carry the same substance, the same context and the same unit, and one field they disagree on is all that keeps them two — are they two flows or one? |
| `substance-in-two-places` | One substance is taken from two different places — two contexts where neither is the other described more vaguely — and the merge wrote a flow into one of them. Two source lists have answered differently about where the substance comes from, and the two halves are separate identifiers that can never meet. Which place is right? |
| `land-class-out-of-place` | A flow of a land-class substance published outside Land Use. The class's own direction states the one right dimension — an occupation occupies, a transformation transforms — so nothing needs to disagree for this to be wrong: a vendor's compartment overruled the curated class (#193). How did the row get past the class-first rule? |
| `retired-identifier-unresolved` | An identifier the renumbering retired whose flow this build no longer mints, so it resolves to nothing. Where the substance is gone the row is `info` and there is nothing to choose; where it survives the row is `review` and lists the contexts it survives in. The eight with exactly one surviving flow are the ones a curator can answer straight away — the rest name a substance that survives in several contexts at once, while the retired identifier names the one that is now empty. Where should it point, and what does a redirect across a context boundary promise? |
| `consensus-match` | A consensus decision that was blocked or left unresolved |
| `undecided-label-replacement` | A preferred-label rename a rule proposed and no ruling covers |
| `substance-label-conflict` | This flow's own name answers for a different substance than the one the flow sits on, so the flow keeps its own name: renaming it would delete the only visible symptom of what may be a mis-grouping. A ruling in `preferred-label-decisions.json` answers the pair — `approve` says the grouping is right, the flow takes its substance's name, and the old name is published as a synonym of neither substance; `reject` says the flow's own name stands. Where the grouping itself is wrong the answer is a split rather than a ruling, and the row waits until it has one |
| `elements` | A chemical element with no flow object, or one nothing in EF 3.1 references |
| `contested-factor` | Both deciding implementations of EF 3.1 state a characterisation factor for this substance and category and the two differ by more than rounding — which reading is right? 38 questions over 13 substances on the 2026-08-24 build, 34 of them still open: kresoxim-methyl's four are ruled, and a ruled question stays here as the record, marked `ruled` and carrying the reasoning, rather than disappearing |
| `proposed-factor` | The ecoinvent Centre characterises this substance where the JRC does not, most often because EF's flow list has no such compartment or form of the substance — should this list publish their number? 14 questions on the 2026-08-25 build, what is left after the `restated` rule took 4,397 and the approvals 899 — 876 pesticide factors from a catch-all and 23 minerals priced from the JRC's element factors (#155) |
| `contradicted-factor` | USEtox 2.1, the model EF 3.1's toxicity categories are derived from, states a number more than a hundredfold from EF's own — in every compartment — so agreement between the two implementations says nothing, because both transcribe the same file. The first table in a section is the two implementations, which is the premise; the model's numbers are in the table under it. Should EF's number be published at all? 8 questions over 110 factors and four substances, the widest being biphenyl at 1,400,000× in urban air, which EF ranks third of 3,380 substances for non-cancer human toxicity there. Two populations are deliberately absent: the metals, because EF replaced USEtox's metal factors on purpose and the JRC report tabulates each change, and freshwater ecotoxicity, because the workbook states an ecosystem-quality result there and EF a potentially affected fraction, so a ratio between them measures the two models rather than the substance |

Fourteen of them are rows in `review_queue` rendered by one template and a
column list each, because they differ only in which columns they render.
`elements` reads `element_coverage`, because it asks a different question: what is
*missing*, rather than what is wrong.

A ruling for `contested-factor` or `proposed-factor` goes in
`data/lcia-factor-rulings.json`, keyed on the queue and the item key the row
shows, with a mandatory comment; the loader refuses
one without reasoning, and one written about numbers the build no longer states is
counted `ef_factor_rulings_absent` rather than applied -- every count a run
makes about a method is named after it.

The three factor queues are `review_queue` rows too, but written by `characterise`
rather than by a build — so they say what the last `characterise` run found, and a
build without one leaves them as they were. None fits the shared template: the
item is a question about a substance across several flows, and a ruling on it is a
statement about somebody else's science. So the page carries what the ruling would
be made on — where each flow came from and under what name each source list
shipped it, what this pipeline then did to the substance, every number all three
implementations state about it, and any number a collapse already declined. On the
first contested question that is the whole answer visible at a glance: EF ships
the substance as `(s)-.alpha.-cyano-3-phenoxybenzyl…`, ecoinvent 3.12 ships
`Gamma-cyhalothrin`, the two land on one flow — by a prepared correspondence
table when this example was written, by ordinary evidence matching since the
tables retired (#141) — and the two factors are 1,441× apart.

`proposed-factor` carries one more piece of evidence, because its question is
different: nobody disagrees about the number, and what a curator has to decide is
whether a number only one implementation states should be published at all. The
page therefore says **whether that number is already published against another
flow** — and names the substance it is published for. The match is on the amount
alone, so it is a lead rather than a proof: two substances can carry one number by
coincidence, and the page names the substance so a curator can tell which they are
looking at.

That evidence is what shrank the queue, in three ways that no longer reach it at
all. A factor whose number this list already publishes *for the same substance in
another compartment* of the category — within the same 2% tolerance that separates
a rounding from a disagreement, so a unit conversion moving the last digits does
not keep a twin apart — is published automatically as `restated`. So is one whose
number already stands published **bit for bit on any flow of the category**: that
is how `Copper, Ion` gets copper's factors, because EF has no ion flows and
ecoinvent's number for the ion is exactly its number for the element, and at that
precision a shared number is a carried-over number rather than a coincidence — a
merely *similar* number on another substance settles nothing, and a shared zero
settles nothing either. And 876 factors of 62 pesticides whose numbers are a
catch-all's, with 23 minerals whose numbers are the JRC's element factors
weighted by the formula, are adopted as populations in
`data/lcia-factor-adoptions.json` and published as `adopted`
([#76](https://github.com/brightway-labs/brightway-flows/issues/76),
[#155](https://github.com/brightway-labs/brightway-flows/issues/155)). What
is left is the rocks whose composition only ecoinvent's report states, feldspar
and olivine, peat and coal-mine off-gas — rows where
ecoinvent states a number of its own, and those are the ones worth a curator's
time.

`elementary-flow-collision` is the one whose item is not a row. It is a *group*
of live flows, and its page shows them side by side: what name each arrived
under, how many characterisation factors each holds, and every field they
disagree on. The fields deduplication itself compares are marked, because those
are the whole of what keeps the flows from being collapsed — usually the
general comment, a free-text note. It has to be a note that says something:
90 of the 116 groups in the 2026-08-12 build were held apart by `01.00.000`, a
version string in EF's description field, and reading that as no description
collapses 77 of them
([#62](https://github.com/brightway-labs/brightway-flows/issues/62)).
Everything else they differ on, the two
names most of all, is evidence a curator rules on and holds nothing apart:
that is [#31](https://github.com/brightway-labs/brightway-flows/issues/31),
where two water flows separated by a name alone were merged and a balanced pair
of withdrawal and return factors became a one-sided charge.

Answering *one* means writing a ruling into
[`elementary-flow-collision-decisions.json`](https://github.com/brightway-labs/brightway-flows/blob/main/src/brightway_flows/data/elementary-flow-collision-decisions.json),
which names the flow that survives and carries the other's characterisation
factors and source references onto it; answering *two* means leaving it alone,
which is what the pipeline already does.

One flow in each group is marked **would be kept**: the one deduplication's own
ranking — most characterisation factors first, identifier only to break a tie —
would keep if what holds the group apart ever went away. The page withheld this
while the payload computed it from the lowest identifier instead, which named
the flow that would be *dropped* on 27 of the 116 groups in the 2026-08-12
build
([#58](https://github.com/brightway-labs/brightway-flows/issues/58)).
It is a conditional either way: nothing in this queue is collapsing, because the
report runs after the deduplication pass — and, for a group the merge produced,
after the last pass that will ever look at those flows.

Each item also says whether the flows disagree about a characterisation factor
they both publish, within the 2% tolerance the project uses for the same
comparison elsewhere — 42 of the 116 differ only in the precision EF published
them to, and exact equality would report every one of them as a conflict.

The queue describes the *published database*, not one stage of the build. The
check runs in the transform and again in the merge, over the flows the merge is
about to write, and the merge's answer replaces the transform's — because the
merge adds flows, and while only the transform asked, the queue held 116 groups
of a published 145
([#60](https://github.com/brightway-labs/brightway-flows/issues/60)).
Each item's payload carries the `stage` that produced it: `merge` for a group
that needs flows the merge minted to exist at all, `transform` for one that
would collide without them. A group with minted flows in it is `review` rather
than `info`, because there the pipeline did act — it wrote a flow onto a
substance, context and unit another flow already held — and `minted_by_merge`
names the flows it wrote. All 29 such groups on the 2026-08-12 build are the
pesticide classes, where a curated grouping was answered by attaching a source
reference to the flow already there when the substance was in the prepared
correspondence table, and by minting a flow when it was not — a split the
retirement of those tables
([#141](https://github.com/brightway-labs/brightway-flows/issues/141))
closed, since nothing routes a substance into a class any more. Whether
minting is right is the curator's question the queue now puts.

A `merge` group takes a different answer from a `transform` one. Deduplication
runs in the transform, and so does the pass that applies the rulings, so the
flows a merge mints are inspected by neither — not in this build, and not in the
next, whose transform starts from the base list again. A ruling written into
`elementary-flow-collision-decisions.json` against one of these is counted
`collision_rulings_absent` and changes nothing. What answers it is the grouping
that minted the flows.

`substance-in-two-places` is the other item that is not a row, and it is the
same question asked the other way round: one place holding two flows there, one
substance holding two places here
([#87](https://github.com/brightway-labs/brightway-flows/issues/87)). So
the page is shaped the other way round too — one section per substance, one row
per place, and the row names the source lists that publish the substance in that
place, the unit they measure it in, how many characterisation factors sit there
and the flows themselves. Those have to travel together. As three deduplicated
columns — every context, every unit, every source list — `Peat` read `Resource →
Biotic, Resource → Ground` beside `MJ, kg` beside `EF 3.1, ecoinvent algorithm
addition` on the 2026-08-24 build, and nothing said which unit and which list
belonged to which place. It
is `kg` in the biotic place, from a flow the merge wrote, with nothing
characterising it, and `MJ` in the ground place, from EF 3.1, with the factor;
pairing them the other way reverses both halves of the decision.

The place marked **belongs nowhere else** is the one a ruling is about: the merge
wrote a flow there and no other place of the substance is a vaguer description of
it. The others are shown because a place is only stranded relative to them —
`Resource → Water → River` beside `Resource → Water` is one place described at
two levels of detail, and a minted flow in it is marked *written by the merge*
and nothing more.

Each item carries a severity. `blocking` means the pipeline could not act and
will not until someone rules; `review` means it acted and wants the result
checked; `info` is a note. It is not a judgement about data quality — it is
about whether the pipeline already acted. A queue sorts blocking first.

### `/changes` and `/contexts`

Two pages the input application owned that have consensus-layer meaning:

- **`/changes`** — every field the pipeline wrote, from all twenty
  transformers, filterable by step, by field and by free text. It was
  `/changelog`, which read `transform-log.json` into a module global at import
  and filtered the whole list in Python — a file written only when someone
  passed `--write-transform-log`, so the page was normally empty.
- **`/contexts`** — each source list's raw compartments and the consensus
  context they become. These are the rules the *transform* applies to every
  list at once, not the per-release mappings the merge reads to place one list.

---

## Merge

What happened when a source list was merged in. Only meaningful after `build`
has run with a source list.

Every source flow gets exactly one outcome — prepared, algorithm,
manual-addition or unmatched — so the summary, the filtered outcome list and
the per-flow detail are three views of one table rather than seven parallel
lists.

The summary counts each outcome three ways, because a count of rows answers
none of the questions asked of it on its own. The 3.12 and 3.8 run of
2026-08-16 resolved 12,373 rows from a stored decision — a figure from the
table era; since the tables retired (#141) the stored decisions are the few
hundred curated override rows and the bulk resolves as `algorithm` instead.
The three-way counting is the point either way: the same counts sit beside
each source list, so "9,850 rows" reads as the 1,800 substances it is.

An unmatched row shows what it could have been. `tied-elementary-candidates`
means the selector scored several flows equally and refused to guess, and the
outcome list carries the substance it narrowed to and the best-scoring flows
with their contexts; the detail page lists every candidate with its name, unit,
context and characterisation-factor count. Two candidates alike in name, unit
and context are a duplicate in the consensus list; two that differ in context
are a question about the source row. Which of the two it is decides what you do
next, and neither is visible from the reason alone.

The **with / without flow-object candidates** split on unmatched rows drives
what you do next. Flows *with* a candidate failed on context or unit and are
usually a mapping problem. Flows *without* one are genuinely unknown
substances: the build already enriched them before matching — see
[Running a transform](running.md) — so a row still here needs a decision rather
than another pass.

**Conflicts** are disagreements between source lists: two lists claiming the
same target, or disagreeing about its unit or context. Empty unless a run
merged several, which is not the same as unchecked.

---

## Docs

These pages, in the application they describe.

They were readable in two places, and neither was in front of a curator working
through a queue: on GitHub, and under `mkdocs serve` on a developer's laptop.
The markdown in `docs/` is read and rendered per request now — the sidebar is
the `nav` block of `mkdocs.yml`, so the order is the order the documentation
was written in, and links between pages are rewritten to routes.

Nothing is built. `mkdocs build` produces a directory of HTML with its own
navigation bar and its own stylesheet, and it is exactly as fresh as the last
time somebody ran it; a stale page looks like a page. Rendering at request time
means the host serves whatever its checkout says. `mkdocs serve` still works
and is still the better tool while writing, because it reloads on save and has
a search box.

Search is `/search`, and the box in the top bar goes there; press `/` to put
the cursor in it. One box looks through the flow objects, the elementary flows
and these pages at once:

- **A name**, such as `carbon dioxide`, lists the first four of each, with a
  link to the rest. The flow objects and elementary flows are the same results
  `/flow-objects/` and `/flows/` give for that search, deprecated flows left
  out, so the number on "All … in Elementary flows" is the number of rows the
  list it opens has. A page of
  documentation is found by the whole phrase, not word by word, and a match in
  its title ranks above one in a heading, and a heading above the text.
- **A flow's UUID** opens that flow. Not a deprecated one: that search finds
  nothing, because the flow has been replaced.
- **A CAS number or an InChIKey** lists every flow object that records it
  first, and never opens one directly. In the build of 2026-09-16, `124-38-9`
  is recorded on nine flow objects — fossil, biogenic, land use change and the
  rest — and choosing one would be the search deciding which carbon dioxide you
  meant.

The list pages' own search boxes still read the text as FTS5 syntax, so
`124-38-9` typed into `/flow-objects/` finds nothing; the links out of `/search`
quote it for them.

Mermaid diagrams are drawn, which they were not until a section index came to
open with one. The bundle is checked in beside the stylesheet rather than
fetched from a CDN, on the rule the whole application follows — it renders
offline or it does not render — and it is loaded only by a page that has a
fence, because it is three and a half megabytes and three pages of thirty-six
have a diagram on them. A fence that will not draw falls back to its source,
labelled *Diagram source*, which is what every one of them did before. A drawn
one is set in the page's face rather than the code block's it is drawn inside,
with ranks 30 units apart rather than mermaid's 50, because every diagram here
is a decision chain scaled to fit a paragraph, and the two together take the
one on the section index from 1,274 units tall to 1,018 for the same twelve
boxes.

### Where a declined number comes from

*Declined numbers* is the page that most needed the row behind it. A declined
number means the build had two numbers for one flow and one category and could
publish only one — and until the rows were named, the page said a choice had
been made without saying how the list came to have a choice to make.

It is a publisher filing one substance twice in one compartment, under two
names. EF 3.1 ships `(Z)-HFC-1336` and `(2z)-1,1,1,4,4,4-hexafluorobut-2-ene`
as separate rows in the same air compartment; every field the pipeline compares
matches, so it holds them to be one flow, keeps one and deprecates the other.
Both rows carried a characterisation factor and the two did not agree.

*Settled from* names both rows, under the names their list shipped them as —
which is where the duplication shows, because by the time the layering has run
they all carry one published label. It marks which row this list kept and which
published the number it did not, and those are not the same question: where the
two numbers are one number written twice, the more precise one wins whichever
row it came from.

Whether the number kept is the *right* one is a question about EF 3.1 rather
than about this list, and
[issue #64](https://github.com/brightway-labs/brightway-flows/issues/64)
asks it — with the eight substances where the gap is too large to be rounding.

### Where a formula comes from

**Checks → formula mismatches** has the same shape of problem: two strings that
disagree, and no way to tell a defect from a difference. The page now says where
each formula came from, and often that is the whole answer. Hydrogen-3 publishes
`H2` because PubChem describes the bulk gas and RDKit agrees; the ChEBI record
it cites is *ditritium* and says `T2`. One substance, two descriptions, nothing
wrong with either.

*Supplied* is how a wrong citation shows itself. It lists what else this
substance took from that ChEBI record — a record that gave it the formula, the
mass and the structure is a record the substance is being claimed to *be*, and
a formula that disagrees with it is then a real problem rather than a difference
of description.

---

## A workable review order

1. **Current run.** It leads with what needs a curator, so it is the shortest
   way to find out whether anything does.
2. **Queue → `ec-malformed` and `ec-cross-check`.** Cheap, mechanical, and they
   improve every downstream identity decision. This is the order the queue
   index lists them in.
3. **Queue → the Common Chemistry queues.** The highest-quality evidence
   available; resolving these settles many names at once.
4. **Checks → shared labels and formula mismatches.** False-merge detection.
   Anything here is a real error.
5. **Checks → duplicate contexts.** The invariant must hold.
6. **Merge → unmatched**, if a source list was merged: those with a
   flow-object candidate first, since they are usually one mapping fix each.
7. **Factors → differences, `over-100x` first**, if `characterise` has run. Not
   a queue and not urgent: 20 rows where two competent teams are more than two
   orders of magnitude apart, which is a conversation to have with them rather
   than a defect to fix here.

When a flow looks wrong and it is not obvious why, `/flows/<uuid>/changes` is
the answer: every step that touched it, the old and new values, and the reason
each step recorded.

## Working a table

Every table that filters carries the same three controls, so none of them has to
be learned twice.

**Reset** sits beside the search box and clears everything — the search, every
dropdown, the sort and the page — without leaving the page you are on. It is
drawn whether or not anything is filtered, because a control that appears and
disappears is one you have to look for, and because the moment a filter selects
nothing is the moment you most want it.

**The pager** offers first, back five, previous, next, forward five and last. A
step that would leave the list is greyed rather than dropped, so the row of
buttons keeps its shape from the first page to the last.

**A badge is a filter.** Where a table marks its rows — *needs a decision* on
the unit disagreements, *blocking* in a queue, *created* on the merge outcomes —
those marks are also chips above the table, with a count each. Sorting the rows
that need work to the top made them findable on the first page and nowhere else:
on page 3 of 143 you are reading rows that are already settled and cannot tell
how many are left.
