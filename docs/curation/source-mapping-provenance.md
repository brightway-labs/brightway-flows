# Follow each mapping back to its original row

Two placeholder rows can both carry `placeholder_code="nan"` while proposing
different substances. They are two original assertions with missing flow
identifiers. The provenance ledger preserves both rows and their coordinates;
it never overwrites them into one mapping or supplies a guessed flow identity.

Open [original mapping provenance](/curation/mappings/) or the
[quarantined placeholder rows](/curation/mappings/?source=inhouse-placeholder&status=quarantined).
The [missing-identifier case](/curation/cases/placeholder-missing-source-identifiers)
groups the original records around the recovery question. The rows themselves
remain separate evidence records, rather than thousands of new findings.

## What the checks verify

The input manifest identifies every retained artifact by title, source reference,
recorded version scope, filename and SHA-256. It distinguishes the recovered
bytes from proof that those bytes were the inputs of a historical execution.
Original provider rows keep their source and target identifiers, labels,
contexts, units, relation, conversion statement, mapper, verifier and stated
date, including unknown fields. Provider authorship does not fill a missing
mapper or verifier.

The legacy seed mappings retain their original database keys, categories,
matching algorithm and confidence. Those fields do not establish a source
release, scientific relation or amount conversion. The separate Sentier
BAFU-to-EF replacement mapping retains its source/target quantities, contexts
and original comments. Its source-list labels are checked against the original
artifact title; a replacement operation supplies no implicit factor-one
conversion or scientific approval.

Each artifact also states its role and scope. In particular, the retained
Sentier BAFU mapping is cross-validation evidence for the contributor's
carbonminds subset. It is not authority for every BAFU flow. Registry definitions,
historical results and proposed correspondences remain distinguishable. An
unqualified role stays visible as a gap rather than becoming an implicit vote
for a consensus mapping.

Every evidence-record ID depends on the original artifact digest and exact row
coordinate. It identifies evidence, **not a new source flow**. Editing the
artifact creates a different evidence generation. CSV records retain their row
number, workbook records their sheet and row, and JSON records their pointer.
Click **Original artifact row** to read the retained record and its hash.

The checks reproduce the complete assertion population from the retained files,
then compare every generated record and the full historical alias population.
They also verify source copies, output populations, case identity bindings,
verification source files, dependency lock and parser runtime. A changed source,
payload, manifest, procedure or runtime invalidates the recorded trace; the
application refuses to present it as current verification.

Original formulas remain text and are never executed. Non-standard JSON number
literals such as `NaN` have an explicit tagged evidence representation,
`{"__original_json_nonfinite_literal__":"NaN"}`. The original file bytes remain
unchanged. The tag records the source literal; it does not supply a numeric
value, a CAS number or a flow identifier. Duplicate original JSON keys and
malformed tables fail validation instead of silently choosing the last value.

## Quarantine and unresolved evidence

| State | Meaning |
|---|---|
| **Quarantined** | The original source identifier is missing or is a null-like token. The row is preserved but excluded from identifier-based candidate indexes and alias support links. |
| **Unresolved** | The original assertion is captured. Its historical execution, version compatibility, relation, quantity/context applicability, scientific review or consumer application still needs evidence. |
| **Reference** | A retained workbook summary row supplies context or counts; it is not a proposed mapping. |

Whitespace and case variations of `nan`, null, `None`, `NaT` and other explicit
missing-value tokens cannot become flow keys. Original values remain in the
record. The index scopes valid identifiers to the source list/version label
actually recorded and returns **all** assertions; it never uses first-row or
last-row selection. The recorded label still needs version qualification where
the source gives only an unversioned list name.

Competing outcomes within the same recorded identifier, context and unit remain
visible. Repeated assertions are retained as repeated evidence. Assertions
from different artifacts that share endpoint identifiers have explicit links
and an independence warning. These links do not establish compatible source
versions or prove that one input was derived from another.

The acceptance guard rejects assertions with unresolved evidence. Capturing a
factor-one statement, a verifier name or an original confidence score does not
approve a new consensus mapping. Missing conversions are never filled with one;
name-only targets are never assigned an identifier automatically.

## Check recovered placeholder definitions against their generation

The [original classification](/curation/evidence/placeholder-original-v2?pointer=%2Fmetadata)
reports 1,590 placeholders and −27 unmatched entries. The retained March 2026
classification contains 1,617 mapping records, each with a distinct literal
name/category description. The [count finding](/curation/cases/placeholder-negative-unmatched-count)
retains the original metadata and the source routine that subtracts the mapped
descriptions from the reported population. The audit flags the inconsistency;
it does not choose a replacement population.

The separately recovered native definition export supplies one literal
name/category/unit candidate for each of the 1,194 rows whose original code is
`nan`. However, comparison also finds 190 different codes among records with
known original identifiers, and 132 classification descriptions absent from the
export. The candidate CAS fields are blank for all 1,194 missing-code records.
These counts describe the retained
[14 October source comparison](/curation/evidence/placeholder-source-identity-comparison),
not a newly qualified common source generation. The later May classification
has a separate population and timestamp; it cannot silently fill the March
identity gap.

The captured classifier can stringify an empty spreadsheet code as `nan`.
This is a possible mechanism identified in original source text, without a
receipt proving which workbook and native export produced the March result.
The [lineage census](/curation/evidence/placeholder-source-metadata-census)
records these limits. All original rows and values remain; candidate codes
stay supplementary evidence and the missing identifiers remain quarantined.

Original artifact hashes and row pointers identify these comparisons. Each
record digest belongs to its declared procedure: different representations
of the same row can have different digests. Use the original artifact and
coordinate to follow a record between the comparison and mapping ledger.
The [captured procedure](/curation/evidence/placeholder-source-lineage-procedure)
retains the exact comparison convention.

The [retained declared input workbook comparison](/curation/evidence/placeholder-input-workbook-comparison)
adds cell coordinates for the missing codes. Each of the 1,194 `nan` records
has a literal name/category/unit candidate with an empty code cell in that
workbook. Its full 1,642-row population and code values correspond to the later
May classification's mappings and unmatched records. This is content
correspondence; the exact March input and execution are still unreceived.

The March classification contains both workbook and native-export code values.
Its 190 codes that differ
from the native export equal the retained workbook cells. The other 101 known
codes that match the export occur in the updater's two new mapping tiers,
where the source routine takes the native definition's code. In the later
workbook, 99 corresponding cells are empty and two hold different codes.
The comparison retains these distinctions and the original cells. The static
source path and matching later content supply context without approving an
identifier substitution or the proposed substance mapping.

## Reading historical aliases

[Historical alias traces](/curation/mappings/?kind=aliases) preserve a pointer
and digest for each original result, every recoverable original registry
membership, and links to source assertions with matching identifiers. Each
member has a readable original record. Missing definitions and invalid
placeholder identities remain explicit issues. Historical factors and evidence
tags are accessible in the original alias record.

The alias links are **identifier occurrences**, not proof that a row supported
the historical scorer or that the resulting mapping is correct. A quarantined
placeholder's apparent target is excluded from these links. Exact historical
execution ancestry and applicability remain unqualified; no legacy alias is
promoted into a newly accepted identity by this ledger.

Existing Curation cases with matching original identifiers link to these traces
in their provenance panel. The selected FEDEFL cases bind to their precise
original CSV row. Trace associations are pinned to the original case identity;
a changed case cannot inherit the earlier trace unnoticed. Source custody and
mapping applicability retain separate labels and gaps.

### Keep source findings in the persistent case history

The missing-placeholder-identifier finding and the two consumer method metadata
findings also have a [private Workbench intake receipt](/curation/evidence/workbench-source-case-receiving).
It exercises the existing case ledger with the exact Curation IDs and
[original attributed records](/curation/evidence/workbench-source-case-original-register).
Reporting authorship and ownership stay separate: an unassigned case remains
explicitly unassigned. An empty source-reference list keeps missing source-flow
identities unresolved.

The [mapping receiving check](/curation/evidence/workbench-source-mapping-receiving)
reproduces the complete original row and alias populations and checks that
quarantined rows supply neither identifier candidates nor alias support.
The [persistent history](/curation/evidence/workbench-source-case-ledger)
retains the earlier contribution events and adds observations. Exact retries
leave its bytes unchanged; no intake observation grants scientific approval,
changes a method or records consumer adoption.

The original intake register and verification procedure are frozen with the
receipt. References point to retained generations, so later edits to the live
Curation register do not replace the earlier evidence. The lowercase-ID reader
change was merged in [Workbench !531](https://gitlab.com/eos-lci/lci-workbench/-/merge_requests/531).
The original private intake retains its reviewed candidate pin. A separate
[merged-reader check](/curation/evidence/workbench-case-id-merged-history)
replays the complete private history through the exact merged source: every
case ID, prior event and rendered history remains unchanged. This verifies the
reader; the shared case ledger and scientific consumer bundle are not activated.

The [later placeholder intake](/curation/evidence/workbench-placeholder-source-receiving)
adds the negative-count finding and the retained worksheet observation to the
same [private history](/curation/evidence/workbench-placeholder-source-ledger).
The earlier definitions and events remain unchanged. The original attributed
case record is frozen with each intake; new observations leave ownership,
scientific approval and consumer adoption unresolved.

The [complete case census intake](/curation/evidence/workbench-all-cases-receiving)
also preserves every registered Curation case in the private Workbench history.
Each keeps its exact ID, original reported state, attribution and a pointer to
the frozen complete case record. Original mapping and factor payloads remain
in that private record. Seventeen cases have no original payload field; their
absence is explicit. Another 22 retain blank original payloads, marked separately
from populated records. Historical implemented or withdrawn states do not create
verified lifecycle events. Earlier definitions and decisions remain unchanged.

## Verify the method-provider evidence too

A mapping to a JRC flow does not, by itself, justify the factor used for that
flow. The retained method profile must also point to its original flow,
method and factor rows. For example, an explicit zero must occur in the
original workbook; a missing factor or a cached formula result cannot supply it.

`tools/verify_method_profile_sources.py` compares every retained provider row
with its exact worksheet and row in the pinned JRC workbook. It rejects
conflicting copies, invented values, missing coordinates and duplicate JSON
keys. It reads formulas as text. Take both expected hashes from independently
reviewed custody records, rather than accepting the candidate's own declarations:

```sh
uv run python tools/verify_method_profile_sources.py \
  --profile /private/provider/profile.json \
  --workbook /private/provider/original.xlsx \
  --expected-profile-sha256 "$PROVIDER_PROFILE_SHA256" \
  --expected-workbook-sha256 "$PROVIDER_WORKBOOK_SHA256" \
  --output /private/review/new-provider-verification
```

The receipt retains each profile pointer, original coordinate and row digest,
plus the verifier source, dependency lock and parser versions. Output must be
new; failed verification produces no completion marker. The
[retained JRC profile](/curation/evidence/jrc-provider-original-profile) and
[original-row verification](/curation/evidence/jrc-provider-source-verification)
remain dated source evidence. The consumer preflight must recheck its supplied
input bytes before any use.

This verifies original statements and their literal values. The choice between
method variants, regional selection, target context and quantity interpretation,
scientific acceptance and actual consumer application remain separate questions.
An independently recovered workbook can close a custody gap while historical
execution ancestry remains unknown.

### Retain method metadata disagreements

The September `v2026.09.02.23` Agribalyse payload's BAFU IPCC method retains
40 distinct native factors while its original metadata reports 16. Its standard
IPCC method retains 226 factors but no impact-unit key. These are separate
[count](/curation/cases/agribalyse-ipcc-bafu-factor-count) and
[unit](/curation/cases/agribalyse-ipcc-standard-unit) findings, linked to the
exact original method records. They do not establish a numerical-impact defect.

The metadata describes copying from Agribalyse 3.2 and a BAFU rebuild. The
[source-lineage review](/curation/evidence/agribalyse-ipcc-source-lineage) preserves
those declarations, tracked possible execution paths and their limits. A
matching packaged archive cannot choose the historical provider route. The
audit reports actual entries, distinct native keys, recorded units and missing
evidence; it neither fills a unit from another generation nor drops factors to
match a stale count. Repeated native keys remain a separate finding.

## Preserve or verify another generation

Prepare a version-one input manifest and its sibling `source-inputs/` directory,
then run from this checkout:

```sh
uv run python tools/stage_mapping_provenance.py \
  --inputs /private/custody/mapping-source-inputs.json \
  --register /private/review/register.json \
  --output /private/review/sources/new-mapping-provenance
```

Output must be new. Completion is recorded only after full source-row
reproduction; failed or interrupted output is not a completed generation.
Register the manifest and text payloads in the existing evidence-document
manifest. Keep original binaries in private custody. The application verifies
those originals as well as the registered text documents.

This procedure does not run harmonisation, change inventories or CFs, register
methods, grant scientific sign-off or adopt a consumer release. It supplies the
traceable evidence for the next consensus decision. See the
[capability assessment](workbench-capability-assessment-2026-10-13.md) for the
separate application and receiving requirements.
