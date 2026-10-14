# Source evidence audit, 13 October 2026

The recorded Aldrin factors can be traced to an exact JRC worksheet row. A cooling-water factor of zero needs a different kind of support: it is a local inventory convention with an explicitly unmeasured evaporation error. Both have preserved sources, but they answer different review questions. Curation needs to show that distinction before either is accepted as a reusable correction.

This audit examined the local migration register with SHA-256 `b0a0858f29ddba7edff6dae5c63a2e853c38afc546d3d364a1eceb39e21d7caa`: 5,479 entries and 82 source documents. It reviewed every collection's import procedure and metadata, inspected the source mechanisms below, and independently compared all 292 recorded factor amendments with the pinned JRC workbook. It did **not** scientifically adjudicate 5,479 entries or execute a scientific build. The original register remains the baseline for the counts below; later enrichment must have its own receipt. [Migration crosswalk](/curation/evidence/migration-index), [preserved source inventory](/curation/evidence/migration-coverage).

## What the existing record can prove

Every entry has a source reference. Only five have a recorded discovery reporter and date, four have validation records, six have structured proposals, three have explicit test paths, and none has a scientific sign-off. Missing fields mean the register does not hold that evidence; they do not establish that nobody ever reviewed or tested the underlying work. Thirteen entries are finding-class indexes, so a missing scientific approval is not itself an actionable defect for those indexes. [Register model and public records](register.json), [complete local migration crosswalk](/curation/evidence/migration-index).

| Collection in the audited snapshot | Entries | Existing basis and unresolved review |
|---|---:|---|
| Upstream reference cases | 17 | Thirteen source-document indexes and four upstream cases; keep source article, issue state, test receipt and scientific acceptance distinct. |
| Migration cases | 3 | Preserved contribution ledger and received evidence; historical status text does not reconstruct a verified lifecycle. |
| Legacy normalization rules | 129 | Exact literal entries and code comments; chemical identity and interpretation are not independently established by code presence. |
| Identity evidence mechanisms | 19 | Code and historical evidence weights; corroboration is not an identity vote. |
| Method policy areas | 13 | Migration inventory and selected sidecars; no structured links to their historical implementations in the original register. |
| Normalization and cluster mechanisms | 22 | Function or phase source spans; applicability, negative examples and scientific effects still need case-specific evidence. |
| Historical comparisons | 1,031 | Exact historical report rows, including 132 repeated rows retained separately in the crosswalk; input generation and current reproduction remain unresolved. |
| External synonym assertions | 3,576 | FEDEFL mapping rows and exact local selection procedure; provider mapping scope is broader than the name-only projection retains. |
| Factor producer rules | 341 | Literal tables/constants from five producers; explicit defaults, vocabularies and scientific assumptions are mixed. |
| Documented factor corrections | 13 | Changelog sections; a prose claim that checks passed is not a captured execution receipt. |
| Historical factor investigations | 9 | Historical status sections, sometimes containing later corrections to earlier claims. |
| Recorded factor amendments | 292 | Overlay outcomes and implementation source; new source corroboration is described below. |
| Consensus integration changes | 14 | Exact Git diffs and author/date; code readiness is not scientific receiving or consumer adoption. |

Counts were calculated directly from the named register snapshot, not estimated from the interface. The importer documents the collection boundaries, exclusions, duplicate-row handling and source revisions. [Migration crosswalk](/curation/evidence/migration-index).

## Independent factor-source corroboration

The local `EF-LCIAMethod_CF(EF-v3.1).xlsx` was first hashed and matched the Workbench input pin `c4518bbb05edddc6e7023b165d0d0847d0f219a48497fba85f66115e4a2e22c5`. A read-only scan examined 319,575 data rows in `lciamethods_CF`. All **292 of 292** recorded amendment values exactly matched a row selected by their EF UUID, category and location using the retained headline-method preference; none had conflicting candidate numerical values. [Pinned input declaration](https://gitlab.com/eos-lci/lci-workbench/-/blob/4bec1691c938db6ec61a8c7e667e10c5307827c7/data/biosphere/INPUTS.md), [selection policy](/curation/evidence/overlay-producer?line=107&end=169).

The reproducible local script is `check_jrc_factor_sources.py` in the migration bundle. Its result, `jrc-factor-source-check.json`, contains the case ID, original-record digest, selected Excel row number, original method UUID/name, flow UUID/name, context, direction, derivation and candidate rows. Receipt SHA-256: `77f18c1535e7de3d3ddf80ed80b67428c95c3581125431556222bc89542e4c29`. The script SHA-256 recorded in it is `99a7c3d9446c8cb5daa9fdb56b5e06b4f421de4b913b2d0aeee87eabcd42f003`. This receipt is source corroboration, not a new execution or sign-off.

For example, `wb-factor-af8bc1926a017bd6` records the BAFU label “TiO2, 54% in ilmenite, 2.6% in crude ore”. Its numerical value `2.79e-08` equals worksheet row **156706**, whose flow is **titanium**, EF UUID `2906898f-6556-11dd-ad8b-0800200c9a66`, method “Resource use, minerals and metals”, input from ground. That equality proves the factor's numerical source. It does not prove the original BAFU amount has the titanium quantity basis required to use it. The workbook sheet has **no flow-unit or factor-unit columns**, so the audit cannot independently settle that dimension from this sheet. The source-flow definition and correspondence quantity must still be inspected. [Recorded amendment](/curation/evidence/factor-overlay?pointer=%2Fcodes%2Fresource_minerals%2Fe33e1426905cc904d15d53d9bcc25730).

## Concrete gaps and contributions

### FEDEFL metadata is present but underexposed

All 3,576 selected rows contain the original mapper, date string, source/target UUIDs, contexts and units. Mapper values are Hottle on 3,143 and Edelen on 433 rows. The original `Verifier` field is populated on 1,468 rows and blank on 2,108. These are provider mapping credits; they must not become Curation discovery authors or scientific approvals. Preserve the original date strings unless the provider's date convention is established. [Selected original rows](/curation/evidence/fedefl-selections).

The selection procedure tests `MatchCondition = '='`, string conversion factor `1.0`, and the first unused lowercased source name. It does not enforce unit equivalence or preserve context in the synonym lookup key. Three accepted rows have different unit strings, **m2 → m2*a**:

| Case | Original CSV row | Source name | Target |
|---|---:|---|---|
| `wb-fedefl-e310cd310cc679ea` | 1265 | Occupation, arable, conservation tillage | Land use |
| `wb-fedefl-b3aacac86b0d1b6a` | 1267 | Occupation, arable, conventional tillage | Land use |
| `wb-fedefl-ea35ae08799b9b9b` | 1282 | Occupation, arable, reduced tillage | Land use |

These are real source inconsistencies requiring quantity review; a factor of one is insufficient evidence to apply them as dimension-preserving synonyms. No same-lowercased-source-name/different-target-name conflicts were found among the eligible rows in this CSV. That narrower result does not validate their chemistry or context equivalence. [Preserved CSV](/curation/evidence/fedefl-input), [selection code](/curation/evidence/prior-normalization-code?line=1172&end=1193).

### Cooling water has a documented limitation that needs to travel with the rule

`policy-06`, `wb-rule-96ab1268f59f312d` and `wb-rule-c65a6e7dfbf38d60` record cooling/turbine net-zero behavior. The original bundle omitted the substantive method note. It says the convention has two error directions and that uncounted cooling evaporation under the net-zero convention is **not yet measured**. It also says GLAM inherits this local rule; it is not an independently established GLAM convention. Preserve and directly attach this note before treating these entries as complete. [Pinned method note](https://gitlab.com/eos-lci/lci-workbench/-/blob/4bec1691c938db6ec61a8c7e667e10c5307827c7/docs/biosphere/water_use_cooling_turbine.md), [original water rules](/curation/evidence/ef31-producer?line=574&end=617), [GLAM implementation](/curation/evidence/glam-producer?line=200&end=267).

The independent JRC scan corroborated the global pair values: cooling return at Excel row 158334 is −42.95 and intake at 158619 is +42.95; turbine return at 158449 is −42.95 and intake at 158847 is +42.95. These rows support a balanced-pair arithmetic claim. They do not prove each BAFU activity returns all intake or that evaporation is separately inventoried. Required next evidence is a source-activity census of intake/return/evaporation, technology-specific bounds and a documented policy decision.

### Fossil defaults are locally calibrated assumptions

The code calls the values “EF 3.1 net-calorific defaults”, but its own adjacent comment says they were **recalibrated to BAFU's implied densities** so the median tracked the published column. Cases `wb-rule-ccddda6b343610bb` (crude oil 43.3), `wb-rule-05bb20c712ad9572` (hard coal 18.5), `wb-rule-ab5c3902c29f1c42` (brown coal 9.5), and `wb-rule-354c824339cb7705` (natural gas 36.0 per m3) need the calibration inputs, source-flow quantity definition and a scientific rationale. Matching a benchmark is not an independent citation for the assumed heating value. Do not turn these defaults into generic upstream unit conversions without that evidence. [Exact comments and values](/curation/evidence/ef31-producer?line=682&end=714).

### Normalization comments overstate what the register establishes

The literal `SYNONYMS` table labels its contents “validated IUPAC/common-name equivalences” but does not attach per-pair chemical evidence. It includes interpretations that need targeted review, such as `wb-rule-8e62b8d891b086a1` (propanol → n-propanol), `wb-rule-05592d196631f8ba` (ethyl cellulose → cellulose, ethyl ester), `wb-rule-49b6fac941b5aa01` (dioxins measured as TCDD → TCDD), `wb-rule-8a37f68d8c451def` (VOC → NMVOC), and `wb-rule-bbb0f9325132916f` (unpositioned dichloroethane → 1,2-dichloroethane). This audit does not declare these wrong from their labels; it identifies the missing source-specific identity, aggregate/measurement-basis and qualifier evidence. [Original table and comments](/curation/evidence/prior-normalization-code?line=84&end=153).

A regression test reproducing the same table entry would not supply that evidence. The useful contribution is a source-row definition or authoritative identifier, a scoped interpretation, and counterexamples that must stay separate. The older grouped review already warned that factor agreement, especially equal zeros, does not establish identity. [Disposition inventory](/curation/evidence/prior-rules).

### Historical measurements need their complete input generation

The 1,031 distinct historical comparison cases preserve exact rows, but their original report describes `ef31_flows` and `cf_files` as “canonical checkout copy (read-only)” without hashes. The producing script `scripts/build_consensus_contribution_candidates.py` was also absent from the original bundle. Preserving it and the input declaration is recoverable now; reproducing the old classification still requires identifying those original files. Counts and interpretations remain historical until then. [Report input declaration](/curation/evidence/historical-comparisons?pointer=%2Finputs), [owning producer at the source pin](https://gitlab.com/eos-lci/lci-workbench/-/blob/4bec1691c938db6ec61a8c7e667e10c5307827c7/scripts/build_consensus_contribution_candidates.py).

The change records contain corrections to earlier accounts: the 10 October compartment-guard entry explicitly says the earlier 9 October subcompartment entry omitted 116 removals, 3,679 additions and 370 changed values. Link these as later corrections to the older statement, retaining both source generations. “Documented” must not imply that the original prose was complete or independently checked. [Changelog](/curation/evidence/factor-changelog?line=29&end=35).

### Git attribution must retain explicit agent involvement

Of 42 distinct commits referenced by implementation attribution in the audited register, 25 contain explicit AI co-author trailers. They are connected to 4,369 cases through code attribution; **3,576 of those share the FEDEFL selection algorithm's commit**, so this does not mean the provider's mapping assertions were generated by AI. Retain the trailer as tooling provenance and continue to distinguish it from the provider mapper, finding author and scientific reviewer.

Examples are `f81ffcd47cb1bbefdf27f04129f4b40fce0228ff` (FEDEFL selection, `Co-Authored-By: Claude Opus 4.6 (1M context)`), `832a46ae358c150ebff472835d58fd0d1ff067bf` (fossil defaults, Claude Opus 4.8), and `8f4f1097e9eacb07412b9582dd6eae21a4b154f1` (Chromium VI, Claude Opus 5.5, with a session link). These were read with `git show -s --format=%B`; absence of a trailer on another commit establishes no claim about its authoring method. [FEDEFL implementation commit](https://gitlab.com/eos-lci/lci-workbench/-/commit/f81ffcd47cb1bbefdf27f04129f4b40fce0228ff), [fossil-default commit](https://gitlab.com/eos-lci/lci-workbench/-/commit/832a46ae358c150ebff472835d58fd0d1ff067bf), [Chromium VI commit](https://gitlab.com/eos-lci/lci-workbench/-/commit/8f4f1097e9eacb07412b9582dd6eae21a4b154f1).

## Recoverable policy-source links

All Workbench locations below refer to `4bec1691c938db6ec61a8c7e667e10c5307827c7`. The links identify implementation evidence, not acceptance of those policies.

| Case | Owning source to attach |
|---|---|
| `policy-01` | [JrcUuidIndex](/curation/evidence/overlay-producer?line=107&end=169) and [name-index selection](/curation/evidence/ef31-producer?line=882&end=1015). |
| `policy-02` | [Compartment gate](/curation/evidence/ef31-producer?line=152&end=167), [category application](/curation/evidence/ef31-producer?line=1331&end=1380), [bio3 subcompartment links](/curation/evidence/bio3-producer?line=203&end=306). |
| `policy-03` | [Regional categories](/curation/evidence/ef31-producer?line=118&end=126), [location parsing](/curation/evidence/ef31-producer?line=1102&end=1112), [factor lookup](/curation/evidence/ef31-producer?line=1211&end=1221). |
| `policy-04` | [Land mappings and resolution](/curation/evidence/ef31-producer?line=393&end=564), [land factor selection](/curation/evidence/ef31-producer?line=1224&end=1247). |
| `policy-05` | [Water classes](/curation/evidence/ef31-producer?line=592&end=617) and [application](/curation/evidence/ef31-producer?line=1307&end=1330). |
| `policy-06` | [Net-zero convention](/curation/evidence/ef31-producer?line=574&end=617) plus the pinned water method note cited above. |
| `policy-07` | [GLAM regional bridge](/curation/evidence/glam-producer?line=200&end=267) and [application sidecar](/curation/evidence/glam-water-applications). |
| `policy-08` | [Heating-value defaults](/curation/evidence/ef31-producer?line=682&end=714), [quantity implementation](/curation/evidence/ef31-producer?line=745&end=780). |
| `policy-09` | [Leading-element implementation](/curation/evidence/ef31-producer?line=718&end=742). |
| `policy-10` | [Particulate and SOx rules](/curation/evidence/ef31-producer?line=784&end=877). |
| `policy-11` | [Climate extension](/curation/evidence/ef31-producer?line=1248&end=1260), [BAFU sidecar](/curation/evidence/bafu-climate-extensions), [bio3 sidecar](/curation/evidence/bio3-climate-extensions). |
| `policy-12` | [Ecological scarcity and ILCD extraction](/curation/evidence/export-producer?line=414&end=527), [IPCC extraction](/curation/evidence/export-producer?line=1044&end=1046), [GLAM bridge](/curation/evidence/glam-producer). The separate AWARE policy remains externally owned. |
| `policy-13` | [Method registration and refusal behavior](https://gitlab.com/eos-lci/lci-workbench/-/blob/4bec1691c938db6ec61a8c7e667e10c5307827c7/scripts/register_methods.py#L131-248) and [served-code snapshot](/curation/evidence/ef31-producer?line=1504&end=1620). |

`policy-12` also needs the nine literal IPCC additions in [scripts/add_bafu_cfs.py](https://gitlab.com/eos-lci/lci-workbench/-/blob/4bec1691c938db6ec61a8c7e667e10c5307827c7/scripts/add_bafu_cfs.py#L19-30). They were outside the importer's five-producer inventory, so “all biosphere amendments” is too broad a completeness claim. The script targets the historical `bafu_fresh` project; preserving it is not a recommendation to run it. The AWARE ownership and convention must be recovered from the water tributary, rather than inferred from the EF producer.

## Review work that would establish a sound contribution

A case can graduate from captured evidence when its claim is explicit enough to falsify. For source mappings this means the source and target definitions, version, compartment, quantity and identifiers. For factor corrections it means the exact method row, input quantity and applicable implementation. For local conventions it means the rationale, alternatives, bounds and recorded decision. Reproduction should carry command, code revision, input digests, expected and observed output, and a counterexample. Scientific receiving then records who reviewed that exact revision, their scope and evidence; code authorship or a provider's `Verifier` field cannot substitute for it.

The central literature library was checked from the canonical Workbench checkout, after reading its shared-literature workflow. Queries were `water cooling turbine`, `Environmental Footprint` and `FEDEFL`. The first two returned fuzzy candidates rather than an exact identified source; the third returned no match. This is a query result, not proof the library contains no relevant evidence. No new study was acquired or scientific parameter changed. The concrete next literature need is technology-specific cooling evaporation evidence linked to the existing policy, after canonical DOI/title identification and a fresh catalog check.
