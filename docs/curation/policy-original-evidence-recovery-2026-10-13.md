# Original evidence recovery for twelve method policies

Recorded 2026-10-13T20:36:17.265413+00:00. Coding-agent research; no scientific sign-off.

Recovered provider files, original mapping decisions, calibration history and existing application observations. All twelve complete policy requirements remain **partial**. The narrower improvements are concrete: 29 GLAM workbooks have two-source byte identity; 4,924 retained regional/fallback values now have exact provider rows; three AWARE tables reproduce from the pinned original workbook; JRC resource quantities now have their original flow-property rows. No claim text or earlier receipt was rewritten.

Machine-readable receipt: [policy-original-evidence-recovery.json](/curation/evidence/policy-original-evidence-recovery). Provider comparison procedure: [original-evidence-provider-check-procedure.py](/curation/evidence/original-evidence-provider-check-procedure).

## Material correction to the evidence picture

The upstream BAFU mapping already carries explicit conversions. Its two TiO2 mappings declare 0.599 kg Ti per kg TiO2; fossil mappings declare energy factors, with some values different from the historical Workbench calibration. The Workbench derivative omitted multiplier and match-relation fields. The preserved upstream SQLite has matching explicit associations but a different run identity from the Workbench 22 September JSON pin, so equivalence to that exact export remains unproved. This is evidence to investigate application, not proof that a factor was applied twice or permission to change a served result. [Pinned upstream decisions](https://github.com/brightway-labs/brightway-flows/blob/19d6cc6268e59e18fcbb47bfec0f440fb0f6a353/src/brightway_flows/data/bafu-2026-v1-match-overrides.json), [original associations](/curation/evidence/original-evidence-upstream-quantity-associations), [historical derivative](/curation/evidence/original-evidence-historical-quantity-extract).

## policy-01: JRC headline versus organic/inorganic sub-method priority

Inherited claim: “Keep the selected implementation and row provenance from `JrcUuidIndex`/the provider reader. A profile must not mix competing implementations by arbitrary first match.”

**Recovered original evidence**

- **provider-row corroboration:** The pinned JRC workbook contains distinct headline and inorganic human-toxicity implementations. For arsenic in unspecified air, cancer rows 27094 and 159924 each carry 4.3981e-05 but distinct method names; non-cancer rows 46899 and 159184 each carry 0.0024884. Row equality for these examples does not collapse implementation identity. The receipt retains source UUID, implementation, context, location and source row.

**Still required**

- **selection policy:** Which exact implementation and tie disposition was selected for every emitted category/flow, beyond the 292 previously checked amendment rows? Next evidence: Full per-factor provider-row and competing-row selection ledger from the accepted projection.
- **application:** Does the registered/served profile use the same selected provider rows? Next evidence: Factor-value and quantity readback bound to the accepted profile and receiving project.

**Disposition:** stays partial. The specific recovered facts may be shown as corroborated without changing the whole case to supported.

Sources: [original-evidence-provider-row-checks](/curation/evidence/original-evidence-provider-row-checks), [original-evidence-provider-check-procedure](/curation/evidence/original-evidence-provider-check-procedure), [jrc-factor-source-check](/curation/evidence/jrc-factor-source-check), [overlay-producer](/curation/evidence/overlay-producer).

## policy-02: Compartment restrictions and the sub-compartment coverage repair

Inherited claim: “Exact target context in the profile and every consumed native code in the census. A missing factor stays absent; a sibling flow cannot supply one silently.”

**Recovered original evidence**

- **provider-row corroboration:** Original JRC arsenic cancer factors differ by soil context: agricultural row 9311 is 5.6899e-05, non-agricultural row 9316 is 1.8035e-05, unspecified row 9320 is 3.7467e-05. These are concrete counterexamples to treating same substance/top compartment as sufficient evidence for interchangeable factors. Provider contexts and units are now retained in the recovery receipt.

**Still required**

- **application:** Which sibling values were copied by the historical registration step, and do all consumed native codes have their own justified factor/context disposition? Next evidence: Original full registration input/output with donor code, target code, context and accepted source row; no live re-registration was performed.
- **scientific applicability:** Is any subcompartment default scientifically accepted for each missing context? Next evidence: Method-owned default or a reviewed case disposition, separate from code matching.

**Disposition:** stays partial. The specific recovered facts may be shown as corroborated without changing the whole case to supported.

Sources: [original-evidence-provider-row-checks](/curation/evidence/original-evidence-provider-row-checks), [method-registration](/curation/evidence/method-registration), [bio3-producer](/curation/evidence/bio3-producer).

## policy-03: Regional emission factors

Inherited claim: “Explicit category/location selection. Any accepted default-region policy must be materialized and identified by the profile/application provider, not an implicit projector fallback.”

**Recovered original evidence**

- **provider-row corroboration:** JRC sulfur dioxide acidification row 613 is 0.494 for CH and row 624 is 1.31 with no location. Both use source UUID fe0acd60-3ddc-11dd-ac48-0050c2490048 and air/unspecified. The recovered provider rows prove that regional selection materially changes the value.

**Still required**

- **regional application:** Which absent-region cases intentionally use the unlocated default, and where is that choice recorded per factor? Next evidence: Historical and candidate emission application records including requested location, selected location, rule and source row.
- **adoption:** Who accepted this fallback for the intended application? Next evidence: Recorded scoped decision, not a matching aggregate benchmark.

**Disposition:** stays partial. The specific recovered facts may be shown as corroborated without changing the whole case to supported.

Sources: [original-evidence-provider-row-checks](/curation/evidence/original-evidence-provider-row-checks), [ef31-producer](/curation/evidence/ef31-producer), [current-consensus-method-projection](/curation/evidence/current-consensus-method-projection).

## policy-04: Land class mapping, occupation and transformation from/to

Inherited claim: “Named, versioned land policy with source class, geography and sign retained. Preserve paired from/to treatment and test numerical changes against the accepted producer.”

**Recovered original evidence**

- **provider-row corroboration:** Recovered 171 original JRC Land use rows for GLO/unlocated selections, with source property rows and signs. Example row 119164 is arable at 50.191; the provider evidence is distinct from the local class-synonym policy. Retained original EF benchmark baseline has land_use median 1.00031 over 11,661 comparisons, but contains no source input hash or per-flow class decisions.

**Still required**

- **class interpretation:** Which original evidence permits each BAFU class synonym, qualifier stripping and organic/extensive-to-intensive fallback? Next evidence: Source land-class definitions plus a named reviewed decision for each non-exact mapping.
- **sign and geography application:** Were paired from/to signs and geography preserved for all consumed flows, including absent-country defaults and published zero factors? Next evidence: Per-native-code source-row and quantity ledger, followed by the same-input numerical comparison.

**Disposition:** stays partial. The specific recovered facts may be shown as corroborated without changing the whole case to supported.

Sources: [original-evidence-provider-row-checks](/curation/evidence/original-evidence-provider-row-checks), [original-evidence-ef31-oracle-baseline](/curation/evidence/original-evidence-ef31-oracle-baseline), [ef31-producer](/curation/evidence/ef31-producer).

## policy-05: Water class mapping and withdrawal/return distinction

Inherited claim: “Named water policy retaining physical direction and origin. A shared substance identity does not equate withdrawal, return, evaporation or embodied water.”

**Recovered original evidence**

- **original application observations:** Recovered existing water-balance receipts rather than repeating their prose: the eos_base receipt contains 2,554 ecoinvent 3.6 cooling activities, 2,297 with a return, and median return/cooling 0.9865521480160593 when recomputed from its saved rows. A BAFU census record for process 212792 records equal recorded saltwater intake and generic return, with no freshwater intake. These demonstrate why direction and origin matter; the receipts lack execution code/store hashes.
- **current implementation scope:** Pinned water-tributary code 6b2da9b7 retains roles for withdrawals, pass-through, returns, evaporation and excluded flows and per-activity consumption handling. This is a distinct method application from the historical EF/GLAM withdrawal policy.

**Still required**

- **scientific applicability:** How should each method treat embodied water, freshwater return, saltwater return, evaporation and pass-through for each source convention? Next evidence: Provider definitions and a scoped application decision with a measured per-activity balance; shared substance identity alone is insufficient.
- **current receiving evidence:** Is the current receiving store census clean under the intended two-sided method? Next evidence: Current code/input-bound census and per-root result; the recovered 9 October census is transition_clean=false, with 2,040 roots over balance.

**Disposition:** stays partial. The specific recovered facts may be shown as corroborated without changing the whole case to supported.

Sources: [original-evidence-water-receipt-summary](/curation/evidence/original-evidence-water-receipt-summary), [original-evidence-water-census-20261009](/curation/evidence/original-evidence-water-census-20261009), [original-evidence-water-emitter](/curation/evidence/original-evidence-water-emitter), [original-evidence-water-bafu-roles](/curation/evidence/original-evidence-water-bafu-roles), [original-evidence-water-bio3-roles](/curation/evidence/original-evidence-water-bio3-roles).

## policy-07: GLAM regional water and recorded GLO fallback

Inherited claim: “Preserve `water_regionalisation.json`, the selected country/GLO disposition and withdrawal policy. Keep experimental/beta designations and provider implementation metadata.”

**Recovered original evidence**

- **provider-release identity:** All 29 local GLAM workbooks match both the historical GLAM_CHECKSUMS SHA-256 entries and the publisher MD5 values in Zenodo record 20630461, version 1.1.2026.06.24beta.
- **provider-row corroboration:** All 4,924 explicitly recorded regional/GLO-fallback water assignments match an original provider row exactly: 1,231 per method. EQ damage has 802 regional/429 fallback; EQ midpoint 952/279; HH damage 932/299; HH midpoint 952/279. Every match retains workbook hash, sheet, row, method, flow class, location and unit. Each method separately has 8 regionless assignments and 503 local policy zeros; those are not counted among the 4,924 checks.

**Still required**

- **policy versus provider:** Are the 503 pass-through zeros per method and country→GLO fallback choices accepted for this application? Next evidence: Explicit application decision plus inventory evidence; source CF equality only establishes the selected provider values.
- **complete application coverage:** What are the exact source and receiving rows for the eight regionless assignments per method and all rejected/unmapped classes? Next evidence: Complete code-level application census including deliberate absences and quantity conversions.
- **scientific scope:** Have beta/experimental implementation caveats been reviewed for each adopted category? Next evidence: Method-specific scope review; file identity does not approve experimental methods.

**Disposition:** stays partial. The specific recovered facts may be shown as corroborated without changing the whole case to supported.

Sources: [original-evidence-provider-row-checks](/curation/evidence/original-evidence-provider-row-checks), [original-evidence-glam-checksums](/curation/evidence/original-evidence-glam-checksums), [original-evidence-glam-extraction-manifest](/curation/evidence/original-evidence-glam-extraction-manifest), [original-evidence-zenodo-20630461](/curation/evidence/original-evidence-zenodo-20630461), [glam-water-applications](/curation/evidence/glam-water-applications).

## policy-08: Fossil resource heating values, density and composition

Inherited claim: “Determine whether the pinned source correspondence already includes the conversion. Apply it exactly once; retain any remaining source-specific assumption as an explicit, evidenced quantity binding or held case.”

**Recovered original evidence**

- **target source quantity:** JRC original flow-property rows 40003/44950/57844/70708/75246/92612 declare brown coal/crude oil/hard coal/natural gas/peat/uranium as Net calorific value, MJ; CF rows 156658–156663 are 1 per native MJ.
- **upstream conversion:** The pinned upstream BAFU overrides at 19d6cc6268e59e18fcbb47bfec0f440fb0f6a353 explicitly state kg/m3→MJ factors: oil 43.1, hard coal 18.01, brown coal 9.41, natural gas 36, peat 9.76, uranium 560000. Exact local upstream concept associations independently retain these numbers. They are original mapping decisions, not independently validated calorific measurements. The historical Workbench derivative exposes source/target unit changes but drops conversion/match fields.
- **historical calibration:** Original commit 832a46ae states BAFU-output calibration of oil 45.8→43.3, hard coal 30.7→18.5, brown coal 9.9→9.5 and gas 40.3→36. Its AI coauthor trailer is retained. This explains the different local constants; benchmark fit does not establish the physical quantity.
- **source quantity example:** The inspected original BAFU XML process 68bb95fd-1526-388c-a01a-50b8d99534b1 has Oil, crude, Coal, hard and Coal, brown quantities in kg. The source quantities are not MJ merely because the target is MJ.

**Still required**

- **historical full pin:** Did the exact 22 September source JSON export carry these same conversion values before the Workbench derivative omitted them? Next evidence: Recover original full export with SHA-256 22b1b5f0b2e34a9840f3ee34f656adc4f47ad72b7e53c0e548f6924d1834129f; the local SQLite has a different recorded run identity.
- **physical derivation:** What original supplier/calorific evidence supports each adopted NCV, particularly where upstream and local calibration differ? Next evidence: Actual referenced provider table or source-dataset energy evidence; recovered upstream comments are not measurement validation.
- **application:** For each real consumed native quantity, is conversion applied exactly once before the MJ-based factor? Next evidence: Conversion ledger and same-input source→projection→registered→served value receipt. No duplicate application is asserted without that evidence.

**Disposition:** stays partial. The specific recovered facts may be shown as corroborated without changing the whole case to supported.

Sources: [original-evidence-provider-row-checks](/curation/evidence/original-evidence-provider-row-checks), [original-evidence-upstream-bafu-overrides](/curation/evidence/original-evidence-upstream-bafu-overrides), [original-evidence-upstream-quantity-associations](/curation/evidence/original-evidence-upstream-quantity-associations), [original-evidence-historical-quantity-extract](/curation/evidence/original-evidence-historical-quantity-extract), [original-evidence-bafu-quantity-example](/curation/evidence/original-evidence-bafu-quantity-example), [original-evidence-fossil-calibration-commit](/curation/evidence/original-evidence-fossil-calibration-commit), [original-evidence-workbench-consensus-run](/curation/evidence/original-evidence-workbench-consensus-run).

## policy-09: Mineral-resource leading-element treatment

The later [titanium application trace](titanium-quantity-application-2026-10-13.md)
receives the current quantities and processed factors. It finds zero applications
of 0.599 in the selected historical path, while scientific interpretation and a
qualified quantity-aware replacement remain open. The earlier questions below
are preserved as the record of this recovery stage.

Inherited claim: “Preserve its quantity basis and derivation. Ore grade and element mass must not be multiplied twice or treated as interchangeable identities.”

**Recovered original evidence**

- **original quantity evidence:** The source BAFU XML explicitly names TiO2, 54% in ilmenite, 2.6% in crude ore, CAS 13463-67-7, unit kg, with an empty generalComment. JRC row 156706 is titanium 2.79e-08; source property row 89298 is titanium, Mass/kg. Neither equal unit labels nor a leading-element name proves equal mass bases.
- **original upstream decision:** Pinned upstream BAFU overrides for source UUIDs 52b760ca-3444-564a-a215-271d4af41250 and 73746710-2506-50d1-811a-521b48526172 explicitly require conversion_factor 0.599, cite rulings #118/#141 and state TiO2→elemental Ti. The recovered local upstream associations mark these broadMatch with qudt:conversionMultiplier 0.599. Historical Workbench derived rows retain the target but omit both conversion and match qualification.
- **historical rationale:** Commit 7d169b0f records the leading-element policy and BAFU aggregate agreement, with an AI coauthor. It establishes origin of the local rule, not that every ore/compound quantity is elemental mass. This is a concrete unresolved conflict for wb-factor-af8bc1926a017bd6 and wb-factor-cacf7c5e1102cf6c.

**Still required**

- **binding/application:** Are the two TiO2 quantities converted by 0.599 exactly once in the accepted flow correspondence and actual factor application? Next evidence: Exact pinned full correspondence plus receiving quantity ledger for the two native BAFU codes; do not silently change their existing factors from this audit.
- **scientific applicability:** Which remaining mineral flows represent elemental, compound or ore mass, and what derivation applies to each? Next evidence: Original flow-property/source documentation and a case-level reviewed quantity decision; aggregate agreement cannot settle each identity.

**Disposition:** stays partial. The specific recovered facts may be shown as corroborated without changing the whole case to supported.

Sources: [original-evidence-provider-row-checks](/curation/evidence/original-evidence-provider-row-checks), [original-evidence-upstream-bafu-overrides](/curation/evidence/original-evidence-upstream-bafu-overrides), [original-evidence-upstream-quantity-associations](/curation/evidence/original-evidence-upstream-quantity-associations), [original-evidence-historical-quantity-extract](/curation/evidence/original-evidence-historical-quantity-extract), [original-evidence-bafu-quantity-example](/curation/evidence/original-evidence-bafu-quantity-example), [original-evidence-mineral-leading-commit](/curation/evidence/original-evidence-mineral-leading-commit).

## policy-10: Particulate and sulfur-oxide defaults

Inherited claim: “Preserve the chosen category/context policy and source row. Compare with consensus-resolved targets; similar names alone cannot carry a factor.”

**Recovered original evidence**

- **provider-row corroboration:** Recovered original PM rows: PM2.5 unspecified 2.38497e-04 (2559), non-urban/high-stack 3.01757e-06 (2562); PM10 unspecified 5.48544e-05 (2555), non-urban/high-stack 6.94042e-07 (2558). Sulfur dioxide unspecified is 8e-06 (3415, long-term; other exact contexts retained), non-urban/high-stack 9.9e-07 (3489). These source values corroborate constants, not the choice of a context.
- **original rejected hypothesis:** Commit e1653988 records that switching PM to non-urban/high-stack worsened its BAFU comparison to −88.5%, and restored the unspecified default. The preserved text records the historical hypothesis and reversal; its asserted cause remains unproved without the original diagnostic inputs/results.

**Still required**

- **calibration history:** Where are the original 28 single-flow SO2 product calculations and failed PM diagnostic outputs with exact source/input identities? Next evidence: Recover row-level calibration files or archived original run output; current code comments and git messages alone do not reproduce them.
- **scientific applicability:** What method/source evidence authorises PM size-bin proxies and the SOx chosen context/quantity convention? Next evidence: Category and source-flow definition with exact source row and reviewed treatment of unsupported bins/context.

**Disposition:** stays partial. The specific recovered facts may be shown as corroborated without changing the whole case to supported.

Sources: [original-evidence-provider-row-checks](/curation/evidence/original-evidence-provider-row-checks), [original-evidence-pm-reversal-commit](/curation/evidence/original-evidence-pm-reversal-commit), [original-evidence-ef31-oracle-baseline](/curation/evidence/original-evidence-ef31-oracle-baseline), [ef31-producer](/curation/evidence/ef31-producer).

## policy-11: Climate extensions and unqualified carbon treatment

Inherited claim: “Preserve the BAFU and bio3 extension sidecars, code coverage and scientific scope. Explicit fossil, biogenic, land-use and stock/correction semantics must survive.”

**Recovered original evidence**

- **provider scientific scope:** Recovered original JRC climate rows distinguish fossil CO2 emission 1 (1121–1126), fossil uptake 0 (160403/160689), biogenic CO2 0 (1114–1120), and land-use-change CO2 with opposite input/output signs (2547/2548). This corroborates the need to retain physical direction and category; it does not authorise stock/delay/bare-CO2 extensions.
- **upstream decision trail:** The pinned upstream BAFU override file retains distinct decisions for unqualified CO2 and source-specific carbon meanings. The original BAFU/bio3 extension sidecars continue to identify four codes each. These are maintained as local extension coverage, not relabelled as JRC-exact.

**Still required**

- **scientific extension basis:** What original method authority and inventory convention support each stock, delayed-emission, land-transformation and bare-CO2 extension value? Next evidence: Per-code source definition, sign/quantity rationale, primary method reference and scoped review.
- **receiving coverage:** Do the accepted profile and consuming inventories preserve all extension codes and their separate dispositions? Next evidence: Code/quantity/value coverage receipt spanning producer, registered factors and served inventory.

**Disposition:** stays partial. The specific recovered facts may be shown as corroborated without changing the whole case to supported.

Sources: [original-evidence-provider-row-checks](/curation/evidence/original-evidence-provider-row-checks), [original-evidence-upstream-bafu-overrides](/curation/evidence/original-evidence-upstream-bafu-overrides), [bafu-climate-extensions](/curation/evidence/bafu-climate-extensions), [bio3-climate-extensions](/curation/evidence/bio3-climate-extensions).

## policy-12: IPCC, ILCD, GLAM, ecological-scarcity and AWARE implementations

Inherited claim: “Keep their accepted provider/version/category/quantity and regional metadata. Migrate each independently; absence from the first profile is not retirement.”

**Recovered original evidence**

- **AWARE original provider tables:** Downloaded the exact original AWARE2.0 country workbook from Zenodo 15133241 (v1.0.0); provider MD5 15a9326a27bf5686019bbf3fe3ae7936 matches, SHA-256 b8481b0fac18864a9854e785007c5e21f9594f8735c5678d7ebdffb1ed9b15c6. With the pinned reader, annual and monthly 519-location JSON tables and the 540-location monthly water-demand table reproduce exactly. This corroborates the committed table values, not all CF resolution/application policies or newest release adoption.
- **UBP original history:** Recovered original UBP validation report from commit 6ca04d10: 11,837 comparisons, median 0.9115205298114746 and 87.41574950942751% within 2x. This is the pre-supplement run, not proof of the later 13 inferred land factors. The exact 13-value land supplement says factors were backed out from product totals; original per-factor product/mass/residual derivation is not present there.
- **method identity:** Recovered historical extraction metadata and original GLAM release pins. The original records distinguish source extract, locally inferred supplement and newer water application. A family label cannot imply all are the same provider-approved method.

**Still required**

- **provider-specific independence:** Where are the complete accepted IPCC/ILCD/UBP provider versions, original factor tables and registration manifests for each retained method? Next evidence: Individual provider input/version/quantity ledgers; the historical exporter names live Brightway sources but does not provide all original provider bytes.
- **UBP calibration:** Which product, observed land mass, known-factor subtraction and residual justifies each of the 13 supplemented factors? Next evidence: Original calibration dataset and script/output for each value, plus explicit scientific review; do not count the pre-supplement validation as validation of those additions.
- **AWARE applicability:** Which variant, region, source water basis and fallback is adopted for each actual use? Next evidence: Application row/quantity evidence and scoped method decision; provider table roundtrip does not establish consumption accounting.

**Disposition:** stays partial. The specific recovered facts may be shown as corroborated without changing the whole case to supported.

Sources: [original-evidence-provider-row-checks](/curation/evidence/original-evidence-provider-row-checks), [original-evidence-zenodo-15133241](/curation/evidence/original-evidence-zenodo-15133241), [original-evidence-aware-provider-reader](/curation/evidence/original-evidence-aware-provider-reader), [original-evidence-ubp-original-validation](/curation/evidence/original-evidence-ubp-original-validation), [original-evidence-ubp-land-supplement](/curation/evidence/original-evidence-ubp-land-supplement), [original-evidence-workbench-extraction-meta](/curation/evidence/original-evidence-workbench-extraction-meta), [original-evidence-water-registry-manifest](/curation/evidence/original-evidence-water-registry-manifest).

## policy-13: Method registration and served-code checks

Inherited claim: “Reuse existing project-local key resolution and differential acceptance. Validate registered factors and served inventories separately from source output.”

**Recovered original evidence**

- **receiving project identity:** Recovered BAFU build manifest dated 2026-09-29T04:50:42+00:00, importer 0.1.10, content_sha256 045764a2d8589109f51f38cb49086468243ca4d6c99230ba059d263942dea61b. It records release/raw identities, corrections and measured counts. The catalogue contract says content identity covers no method; this manifest is not an EF/GLAM factor-value readback.
- **application observations:** The independently preserved 9 October EDB_BAFU water census is not clean (2,040 roots exceed balance). The EF oracle baseline retains per-category aggregate ratios, including PM 1.868154 and freshwater ecotoxicity 2.799344; these are historical accepted comparison baselines, not universal accuracy or current application receipts.

**Still required**

- **registered factors:** Do receiving methods contain the exact intended factor values, conversions and native-flow keys after registration? Next evidence: Complete project-local value/key readback bound to the actual source/profile and code generation.
- **served inventory:** Does the intended served graph consume the same flows/quantities and satisfy the specific acceptance test? Next evidence: Current inventory/store identity plus served factor and quantity census; recovered historic build identity and differential tolerance do not establish this.
- **acceptance:** Who accepted the stated comparison scope and unresolved scientific limitations? Next evidence: Scoped reviewer/sign-off record; no approval is fabricated by this recovery.

**Disposition:** stays partial. The specific recovered facts may be shown as corroborated without changing the whole case to supported.

Sources: [original-evidence-bafu-build-manifest](/curation/evidence/original-evidence-bafu-build-manifest), [original-evidence-bafu-release](/curation/evidence/original-evidence-bafu-release), [original-evidence-water-census-20261009](/curation/evidence/original-evidence-water-census-20261009), [original-evidence-ef31-oracle-baseline](/curation/evidence/original-evidence-ef31-oracle-baseline), [policy-differential-gate](/curation/evidence/policy-differential-gate), [policy-method-gate](/curation/evidence/policy-method-gate), [method-registration](/curation/evidence/method-registration).

## Evidence and research limits

The source index in the receipt binds each cited new artifact to its SHA-256. Git copies retain exact revision and path; provider records retain immutable release URLs. The numerical provider check reads original Excel cells using openpyxl; it imports only the pinned pure AWARE reader functions, and performs no registration or LCA. Its GLAM check corroborates recorded CF values at the chosen class/location, not correctness of that class/location choice. Regionless and local-zero dispositions are explicitly outside that comparison.

Historical receipts establish what was recorded at that time. They do not become current acceptance evidence because their files were recovered. The 9 October water census explicitly records failure of the transition criterion. Catalogue manifest identity also excludes method values; it cannot substitute for an LCIA readback.

The canonical shared literature guide and source-value knowledge context were loaded. Library queries and published-catalog/MR checks are retained in the receipt. The original AWARE workbook/API were recovered from [Zenodo 15133241](https://zenodo.org/records/15133241); its metadata identifies [the method paper](https://doi.org/10.1111/jiec.70023). No claim of having read or scientifically validated that paper is made. The GLAM provider record is [Zenodo 20630461](https://zenodo.org/records/20630461). Central library acquisition remains a separate task if those scientific claims are to be adopted.

Only the new receipt, evidence captures and this report were written. The register, app, scientific input data, methods and served state were not changed. Raw BAFU XML/workbooks and private inventory corpora were not copied into Git. Local selected-source excerpts must remain subject to BAFU terms.
