# Follow a correction from observation to use

A kilogram of baddeleyite is not a kilogram of zirconium — the worked example
in [A kilogram of ore is not a kilogram of
metal](../findings/units.md#a-kilogram-of-ore-is-not-a-kilogram-of-metal). The
source observation, the proposal to preserve its conversion, the code that
applies it and the checks that exercise that code answer different questions.
**Curation**, a section of the review application, connects them.

Open [Curation](/curation/) to search cases, sort them, group by collection, stage or source,
and inspect each case's evidence, people, proposals, modules and validation.
The module catalogue reads the existing ruling register and transformer chain;
it does not create another correction engine.

The [Brightway Labs source findings](../findings/index.md) retain their worked
examples, evidence, decisions and measured outcomes. Their **finding-class
records** index families of errors; a class registration does not say that an
already documented correction is awaiting implementation. Each findings article
links to its class record and to individual cases that explicitly cite it.
The overview also lists those registered cases, including withdrawn
interpretations. This index is a partial migration of the investigations.

The [historical IPCC source review](historical-ipcc-primary-basis-2026-10-14.md)
separates the original literals, published corroboration, method policies and
native quantity requirements. Additional source facts are bound to the exact
case identity and retained source bytes. They append evidence and unresolved
questions; they cannot clear an earlier gap, change a claim assessment or
supply a scientific sign-off.

For example, search **water**, then choose a workstream above the package table.
Results update as you type or select a filter. Switch to **Cases** to inspect
individual evidence, or **Modules** to inspect shared code; the search carries
across these views. Column filters sit beneath the headings they control. Click
a heading to sort and click it again to reverse the order.

The URL retains the current view, filters and sort order. Browser Back and
Forward restore earlier views. **Clear filters** keeps a package or module scope
when one is shown; **Remove scope** returns to the wider case register. A new
filter starts on the first results page. Documentation scope works the same way
as package or module scope and follows the selected local register. Choose
**Individual cases** or **Finding classes** in Record type to distinguish them.
On a narrow screen, scroll across the
case table for the remaining columns. Without JavaScript, press Enter in the
search field to submit the selected filters.

## Triage a review package

Land-class mappings often belong to one policy discussion even when they affect
many source entries. A **review package** joins those entries, the existing
policy and related change records around one review question. A **workstream**
groups packages by the part of the work they concern.

The local migration opens on packages. Every package states its grouping rule,
review question and membership; its record browser retains the individual IDs
and original evidence. Package size is a count of records, not a priority or an
estimate of how many scientific defects exist.

1. Read the shared question and evidence. Check whether the records really need
   the same decision.
2. Star individual cases that need separate attention. Use those shortlisted
   cases as **exceptions** in the package's triage form.
3. Record your name, reason and next action. Acknowledge the scope, request
   investigation, request a split, or reopen earlier triage.
4. Export your triage when you want a portable record. It stays in this browser
   until you choose to share it.

An acknowledgement concerns intake and next steps. It changes no case's
validation, scientific sign-off or adoption. Exceptions remain unresolved and
visible. Changed package membership, grouping rationale or evidence makes an
earlier acknowledgement stale; the earlier event remains in the history.

Packages can be regrouped by changing their explicit membership in the reviewed
register. Cases keep their IDs. Newly imported cases without a package appear
in **Cases awaiting grouping**, so an import cannot silently omit them from
triage. A split request records the proposed separation and its rationale; it
does not automatically change the shared register.

## Four linked records

1. **Finding or processing defect:** what was observed, in which source or
   build, by whom, and why the evidence supports it. A *finding* is an error in
   the source data, in the sense of [What we have found](../findings/index.md);
   a mistake in this project's own processing is a *processing defect*, and the
   register marks it so. Curation tracks both; only the first kind belongs in the
   findings pages.
2. **Proposal:** an issue, discussion or PR describing a possible response.
   Rejected alternatives stay attached to the case. The claim itself is stated
   as data, one file per issue in `expectations/`, and graded against the build
   by `brightway-flows assess` — the proposal record points at that file rather
   than restating it. Changing where the merge puts a row follows the
   fixing-a-matching-defect procedure in `.claude/skills/`.
3. **Module:** the code and decision files applying the change, pinned to a
   revision and connected to its tests. Cases and modules can have several links
   in either direction.
4. **Validation and review:** executed checks with their scope, and named
   sign-offs tied to the exact revision. Release adoption has its own evidence.
   A validation receipt here is what `brightway-flows assess` or a test run
   produced on a named revision, not a sentence saying that it passed.

Checks remains overall quality control. Its observations and the existing
decision queues link into cases; an empty check or closed issue is not proof
that a proposed correction has been reviewed.

## Review the implementation where the decision lives

Open a package's **Implementations** section to see its shared code and proposed
upstream destinations beside the review question. Each case uses the same view,
with its exact source attribution. A historical Workbench implementation remains
labelled historical. A suggested Consensus module remains a proposed destination
until an implementation link is explicitly recorded.

The **Modules** tab is a shared reference for code used by several packages.
It links back to those packages and separates implementation links from proposed
destinations. The case browser can filter either relationship without losing
search, sorting or pagination. Thousands of cases sharing a source file therefore
do not become thousands of module cards.

Its coverage statement is precise: all default transformer steps, all registered
rulings, vocabulary and reference-data readers, and every actual, proposed and recorded implementation link in the loaded
register. A source file is grouped by repository and path; its revisions and
recorded roles remain separate. Unproven repository origins remain separate too.
Helpers and post-processing passes without a ruling or case link are outside this
inventory. An inventory count is never a completeness claim about scientific
review or the entire processing system.

For upstream code, the detail view retains the source documentation, each class's
order and per-flow classification, every ruling description, resolved files,
supporting vocabularies and reference inputs. Direct imports connect transformers
to separate registered readers of those files. Package modules expose their Python
support files. Full source downloads are available alongside the bounded preview.
Git history records code contributors at the stated baseline; it does not identify
finding authors or scientific reviewers. Renamed paths are not followed by this
history view.

Test imports and ruling-file references are discovered in the current checkout.
They indicate where to read tests, not whether the tests passed or how much they
cover. Recorded external implementation versions retain their case evidence and
any preserved test sources. Execution receipts, sign-off and adoption stay with
the case and revision. Recency alone cannot establish the best scientific version.

## Reading the local preview

The initial register contains selected public examples and the existing finding
classes. It is explicitly an incomplete migration, not an inventory of every
historic decision. GitHub status and authorship have a retrieval date. Existing
records without a named reviewer, date or approval say **not recorded**.
Focused validation, full-build assessment, scientific sign-off and release
adoption are shown separately. Legacy baseline results are dated historical
evidence, never silently treated as checks of current code.

Your shortlist and notes are stored only in this browser. They organise your
review and cannot approve a correction, change a module or post to GitHub.
The register is read-only; proposed record changes belong in a normal reviewed
repository change. No button in this preview applies a correction to data.

A local evidence register can hold individual legacy normalization rules,
factor amendments and historical observations alongside these public cases.
Choose a **collection** to review one body of work, or search an original flow
name, native code or reference. Results have pages; the shortlist spans all
pages. Code contributors are labelled separately from the person who reported
the finding.

Each imported case keeps its original record and source reference. Evidence
snapshots show their generation and verified SHA-256. A historical implementation
and a proposed upstream destination have separate labels. Importing a record does
not advance it through scientific review, create a test result or establish
consumer adoption. A migration receipt, when supplied, documents coverage,
duplicate handling and exclusions.

See [Evidence quality and provenance](evidence-quality.md) for source checks,
claim-specific gaps and what to contribute before scientific receiving.

## Run and review locally

From a checkout, install the locked development environment and run:

```sh
uv sync --frozen --group dev
uv run python tools/serve_curation_preview.py
```

To review a separate local register, add `--register /path/to/register.json`.
Its preserved files belong in the sibling `sources/` directory and are listed
with their hashes in the register's document manifest. The public example
register remains available in the checkout. Keep private evidence bundles local
until their contents are cleared for publication.

Open `http://127.0.0.1:5188/curation/`. Curation works without a built database.
To also inspect flows and quality checks, pass `--database` with a published
Brightway Flows SQLite snapshot. That snapshot's run is separate from the
source baseline inspected by Curation.

The [description-source comparison](validation-2026-10-13-claims.md) records
the follow-through on inherited claims and recovered numerical receipts.
The later [original evidence recovery](original-evidence-recovery-2026-10-13.md)
preserves those comparisons and adds verified receiving results, provider rows
and the remaining questions to individual cases.
The [titanium quantity trace](titanium-quantity-application-2026-10-13.md)
follows original amounts through import, registered and processed factors,
and the newer quantity-aware projection mechanism.
The [Workbench capability assessment](workbench-capability-assessment-2026-10-13.md)
compares retained sources and results with the published biosphere page and
records what remains before the integrated project can replace that alignment.
The [original mapping provenance checks](source-mapping-provenance.md) now
reproduce complete retained source rows, quarantine missing identifiers, and
link each historical alias to its original result and registry members.

The [module inventory validation](validation-2026-10-13-modules.md) covers the
contextual implementation view. The initial [focused validation receipt](validation-2026-10-13.md) describes
what was exercised locally. The [design proposal](proposal.md) records scope,
review questions and the remaining migration work.
