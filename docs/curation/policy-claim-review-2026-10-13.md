# Method-policy review, 13 October 2026

Cooling water provides a useful distinction: the source really does record a
local zero convention and an unmeasured evaporation limitation. In contrast, the
inherited sentence that a missing factor must remain absent is a requirement for
migration; the historical registrar actually fills missing sibling factors. This
review preserves the intended rules while identifying what the retained code
does today at its pinned historical revision.

Two passes were made on 13 October 2026, and this page records both. The first
compared the 13 inherited policy descriptions with preserved Workbench sources
at revision `4bec1691`, candidate-projector code at `1aa303f9` and candidate
documentation at `03fd243f`; its receipt is `policy-claim-review.json` in the
local evidence bundle, and it pins the exact inherited summary and every cited
source by SHA-256. The second, recorded at 20:36 UTC the same day, went back to
the original provider files, mapping decisions, calibration history and
application observations for twelve of the thirteen (policy-06 was already
supported within its scope); its receipt is `policy-original-evidence-recovery.json`,
with the provider comparison procedure
`original-evidence-provider-check-procedure.py`. Under each policy below, the
comparison comes first and the recovery follows it. No claim text or earlier
receipt was rewritten by the second pass.

**Support means support for the precise description, not scientific approval.**
After both passes, one bounded preservation claim is supported and 12 are
partially supported. The recovery narrowed what is still open rather than
changing a verdict: 29 GLAM workbooks have two-source byte identity, 4,924
retained regional and fallback water values have exact provider rows, three
AWARE tables reproduce from the pinned original workbook, and the JRC resource
quantities have their original flow-property rows. A normative requirement is
not marked false because historical code fails to meet it.

| Case | Support | Main distinction |
|---|---|---|
| `policy-01` | partial | The inherited text is a migration requirement. The historical UUID index gives headline methods precedence but otherwise keeps the first row; it does not meet a general no-first-match or complete-row-origin guarantee. |
| `policy-02` | partial | The requirement to retain exact context and keep missing factors absent is stricter than the historical pipeline. The historical producer records some context fallbacks, while the registrar also fills missing sibling factors without a per-sibling source record. |
| `policy-03` | partial | Explicit location selection is implemented in the later candidate projector, but historical emission lookup has a default-location fallback. The description must identify which generation it describes. |
| `policy-04` | partial | The historical code preserves occupation versus transformation-from/to selection and uses the same land-class resolver, but some source qualifiers and locations are deliberately generalized. The migration wording must not imply full semantic preservation has already been demonstrated. |
| `policy-05` | partial | There are distinct historical water policies. EF 3.1 prices embodied water through its resource-water path, while the GLAM bridge excludes embodied water, returns and evaporation from that path. The source supports keeping their distinctions, not one universally accepted water interpretation. |
| `policy-06` | supported | Supported within the exact claim scope: an explicit local zero convention and its unresolved limitation are documented. This is support for preserving the convention as pending review, not support for scientifically approving zero consumption. |
| `policy-07` | partial | The regional/default selection and its application record are supported by source. Complete provider-version lineage and scientific acceptance of the imported net-zero convention are not established for each application. |
| `policy-08` | partial | Applying a conversion once is supported as a candidate-projector contract, not as a demonstrated property of the historical fossil producer. The historical defaults also include calibration assumptions that need their own source evidence. |
| `policy-09` | partial | The source implements a leading-element rule without multiplying ore grades. The required source-flow quantity basis remains a scientific premise, not a fact established by a kilogram unit or the existence of the code. |
| `policy-10` | partial | The code provides explicit PM/SOx defaults, but several are proxies or benchmark-derived context choices. It does not require a consensus-resolved target for each application. |
| `policy-11` | partial | The extension sidecars and named values are preserved. Scientific scope and all fossil/biogenic/stock semantics are not established merely by retaining those files; bare CO2 is explicitly given a local fossil interpretation. |
| `policy-12` | partial | The named method families have heterogeneous historical origins. The register does not establish a single set of scientifically accepted provider versions and policies, and AWARE is not evidenced by the preserved Workbench extraction code. |
| `policy-13` | partial | Existing code supports project-local key resolution and a separate differential-gate policy. Neither establishes full numerical or served-inventory validation for this migration. |

## What the recovery changed in the evidence picture

The upstream BAFU mapping already carries explicit conversions. Its two TiO2 mappings declare 0.599 kg Ti per kg TiO2; fossil mappings declare energy factors, with some values different from the historical Workbench calibration. The Workbench derivative omitted multiplier and match-relation fields. The preserved upstream SQLite has matching explicit associations but a different run identity from the Workbench 22 September JSON pin, so equivalence to that exact export remains unproved. This is evidence to investigate application, not proof that a factor was applied twice or permission to change a served result. [Pinned upstream decisions](https://github.com/brightway-labs/brightway-flows/blob/19d6cc6268e59e18fcbb47bfec0f440fb0f6a353/src/brightway_flows/data/bafu-2026-v1-match-overrides.json), original associations (evidence `original-evidence-upstream-quantity-associations`), historical derivative (evidence `original-evidence-historical-quantity-extract`).

## policy-01: JRC headline versus organic/inorganic sub-method priority

**Inherited claim:** Keep the selected implementation and row provenance from `JrcUuidIndex`/the provider reader. A profile must not mix competing implementations by arbitrary first match.

**Source comparison — partial:** The inherited text is a migration requirement. The historical UUID index gives headline methods precedence but otherwise keeps the first row; it does not meet a general no-first-match or complete-row-origin guarantee.

At Workbench 4bec1691, JrcUuidIndex keys by EF UUID, location and category and stores the winning method name internally. Its add() selects a headline over a non-headline; otherwise the first value remains. The name index separately prefers unspecified contexts. At the later 03fd243f documentation pin, the candidate profile requires provider implementation/revision and one factor per target/category/location. These are contract requirements, not a received real provider profile.

**Evidence still needed after the comparison:** Preserve the actual winner and every competing method row, including original method UUID, context, worksheet locator and source hash. Define and review a deterministic tie policy when more than one non-headline candidate remains. The historical overlay sidecar omits the selected method identity and row locator; our JRC source check recovers those for 292 amendments but does not establish the full provider or a scientific choice between alternatives.

**Recovered original evidence**

- **provider-row corroboration:** The pinned JRC workbook contains distinct headline and inorganic human-toxicity implementations. For arsenic in unspecified air, cancer rows 27094 and 159924 each carry 4.3981e-05 but distinct method names; non-cancer rows 46899 and 159184 each carry 0.0024884. Row equality for these examples does not collapse implementation identity. The receipt retains source UUID, implementation, context, location and source row.

**Still required**

- **selection policy:** Which exact implementation and tie disposition was selected for every emitted category/flow, beyond the 292 previously checked amendment rows? Next evidence: Full per-factor provider-row and competing-row selection ledger from the accepted projection.
- **application:** Does the registered/served profile use the same selected provider rows? Next evidence: Factor-value and quantity readback bound to the accepted profile and receiving project.

Sources: `overlay-producer` lines 107–170, `ef31-producer` lines 104–109, `ef31-producer` lines 882–1015, `current-consensus-method-projection` lines 19–41, `jrc-factor-source-check` at `/selection_policy`; recovery: `original-evidence-provider-row-checks`, `original-evidence-provider-check-procedure`, `jrc-factor-source-check`, `overlay-producer`.

## policy-02: Compartment restrictions and the sub-compartment coverage repair

**Inherited claim:** Exact target context in the profile and every consumed native code in the census. A missing factor stays absent; a sibling flow cannot supply one silently.

**Source comparison — partial:** The requirement to retain exact context and keep missing factors absent is stricter than the historical pipeline. The historical producer records some context fallbacks, while the registrar also fills missing sibling factors without a per-sibling source record.

The BAFU producer restricts allowed top compartments. The biosphere3 bridge first selects the mapped sub-compartment and otherwise records an unspecified-context fallback. At the same 4bec1691 pin, register_methods.py groups nodes by name and top compartment, then copies a factor to siblings with setdefault; this can fill a missing sub-compartment factor after source production. The later candidate projector instead requires context/unit equality and exact provider selection.

**Evidence still needed after the comparison:** The receipt must distinguish a source factor, an explicitly reviewed context carry and a registrar-created sibling factor. Capture every native code added by registration, its donor code, source/target contexts and policy; compare the registered result against the intended provider. Determine which historical carries should remain permitted. Source-file coverage alone cannot establish that a missing source factor stays absent in the served project.

**Recovered original evidence**

- **provider-row corroboration:** Original JRC arsenic cancer factors differ by soil context: agricultural row 9311 is 5.6899e-05, non-agricultural row 9316 is 1.8035e-05, unspecified row 9320 is 3.7467e-05. These are concrete counterexamples to treating same substance/top compartment as sufficient evidence for interchangeable factors. Provider contexts and units are now retained in the recovery receipt.

**Still required**

- **application:** Which sibling values were copied by the historical registration step, and do all consumed native codes have their own justified factor/context disposition? Next evidence: Original full registration input/output with donor code, target code, context and accepted source row; no live re-registration was performed.
- **scientific applicability:** Is any subcompartment default scientifically accepted for each missing context? Next evidence: Method-owned default or a reviewed case disposition, separate from code matching.

Sources: `ef31-producer` lines 152–167, `ef31-producer` lines 1331–1421, `bio3-producer` lines 280–305, `method-registration` lines 113–165, `module-source-f6274f266738a9c2` lines 167–189; recovery: `original-evidence-provider-row-checks`, `method-registration`, `bio3-producer`.

## policy-03: Regional emission factors

**Inherited claim:** Explicit category/location selection. Any accepted default-region policy must be materialized and identified by the profile/application provider, not an implicit projector fallback.

**Source comparison — partial:** Explicit location selection is implemented in the later candidate projector, but historical emission lookup has a default-location fallback. The description must identify which generation it describes.

The 4bec1691 producer recognizes regional category slugs, parses a location suffix and tries that location before __none__. The overlay also prefers a located row when available, otherwise retains the default and records the chosen location_key. The candidate projector source at 1aa303f9 uses an exact (target, category, selected location) key; no default-region fallback appears on that path.

**Evidence still needed after the comparison:** A real provider profile and application need an explicit policy for each regional-to-default selection, including requested location, selected location and why a default is permitted. Reconcile the historical implicit fallbacks against those decisions; the candidate code contract and historical sidecar do not by themselves prove scientific acceptance or current consumer use.

**Recovered original evidence**

- **provider-row corroboration:** JRC sulfur dioxide acidification row 613 is 0.494 for CH and row 624 is 1.31 with no location. Both use source UUID fe0acd60-3ddc-11dd-ac48-0050c2490048 and air/unspecified. The recovered provider rows prove that regional selection materially changes the value.

**Still required**

- **regional application:** Which absent-region cases intentionally use the unlocated default, and where is that choice recorded per factor? Next evidence: Historical and candidate emission application records including requested location, selected location, rule and source row.
- **adoption:** Who accepted this fallback for the intended application? Next evidence: Recorded scoped decision, not a matching aggregate benchmark.

Sources: `ef31-producer` lines 118–126, `ef31-producer` lines 1102–1110, `ef31-producer` lines 1199–1221, `overlay-producer` lines 228–268, `module-source-f6274f266738a9c2` lines 155–189, `current-consensus-method-projection` lines 57–67; recovery: `original-evidence-provider-row-checks`, `ef31-producer`, `current-consensus-method-projection`.

## policy-04: Land class mapping, occupation and transformation from/to

**Inherited claim:** Named, versioned land policy with source class, geography and sign retained. Preserve paired from/to treatment and test numerical changes against the accepted producer.

**Source comparison — partial:** The historical code preserves occupation versus transformation-from/to selection and uses the same land-class resolver, but some source qualifiers and locations are deliberately generalized. The migration wording must not imply full semantic preservation has already been demonstrated.

At 4bec1691, parse_bafu_land retains the kind and parses location; the same resolver serves all three kinds. land_cf selects the corresponding JRC value and keeps an explicit zero before trying GLO. LAND_CLASS_SYNONYMS contains interpretations such as organic pasture to intensive pasture and the resolver can remove trailing qualifiers. The generic result file records a code-to-factor value, not the complete original class and selected policy.

**Evidence still needed after the comparison:** Attach an explicit land-class decision for each generalization, preserving the original qualified class, selected class, geography and exact factor row. Verify paired from/to coverage, signs and amounts on a pinned input generation; using one resolver does not prove all source class/kind combinations have a factor or that a pair actually occurs in inventories. Recover the evidence for intensity/organic-class interpretations and identify default-location applications.

**Recovered original evidence**

- **provider-row corroboration:** Recovered 171 original JRC Land use rows for GLO/unlocated selections, with source property rows and signs. Example row 119164 is arable at 50.191; the provider evidence is distinct from the local class-synonym policy. Retained original EF benchmark baseline has land_use median 1.00031 over 11,661 comparisons, but contains no source input hash or per-flow class decisions.

**Still required**

- **class interpretation:** Which original evidence permits each BAFU class synonym, qualifier stripping and organic/extensive-to-intensive fallback? Next evidence: Source land-class definitions plus a named reviewed decision for each non-exact mapping.
- **sign and geography application:** Were paired from/to signs and geography preserved for all consumed flows, including absent-country defaults and published zero factors? Next evidence: Per-native-code source-row and quantity ledger, followed by the same-input numerical comparison.

Sources: `ef31-producer` lines 393–575, `ef31-producer` lines 1068–1080, `ef31-producer` lines 1224–1237, `ef31-producer` lines 1295–1305, `current-consensus-method-projection` lines 19–41; recovery: `original-evidence-provider-row-checks`, `original-evidence-ef31-oracle-baseline`, `ef31-producer`.

## policy-05: Water class mapping and withdrawal/return distinction

**Inherited claim:** Named water policy retaining physical direction and origin. A shared substance identity does not equate withdrawal, return, evaporation or embodied water.

**Source comparison — partial:** There are distinct historical water policies. EF 3.1 prices embodied water through its resource-water path, while the GLAM bridge excludes embodied water, returns and evaporation from that path. The source supports keeping their distinctions, not one universally accepted water interpretation.

At 4bec1691, WATER_CLASS_MAP maps embodied water to generic water, and rebuild_all allows resource/unknown-compartment water plus any name containing embodied. The GLAM bridge instead requires the natural resource compartment and explicitly explains why returns, evaporation and embodied water are not credited. The pinned JRC workbook corroborates opposite intake/return factors for cooling and turbine water; these rows are distinct resources/emissions with input/output directions.

**Evidence still needed after the comparison:** Review and name the method-specific physical boundary: withdrawal, consumption, return, evaporation and embodied water. For each class, retain the original flow definition, direction, unit, receiving context and application policy. The presence of an embodied label or a shared substance identity is insufficient evidence of resource withdrawal, and the JRC intake/return pair does not establish the treatment of every source inventory.

**Recovered original evidence**

- **original application observations:** Recovered existing water-balance receipts rather than repeating their prose: the eos_base receipt contains 2,554 ecoinvent 3.6 cooling activities, 2,297 with a return, and median return/cooling 0.9865521480160593 when recomputed from its saved rows. A BAFU census record for process 212792 records equal recorded saltwater intake and generic return, with no freshwater intake. These demonstrate why direction and origin matter; the receipts lack execution code/store hashes.
- **current implementation scope:** Pinned water-tributary code 6b2da9b7 retains roles for withdrawals, pass-through, returns, evaporation and excluded flows and per-activity consumption handling. This is a distinct method application from the historical EF/GLAM withdrawal policy.

**Still required**

- **scientific applicability:** How should each method treat embodied water, freshwater return, saltwater return, evaporation and pass-through for each source convention? Next evidence: Provider definitions and a scoped application decision with a measured per-activity balance; shared substance identity alone is insufficient.
- **current receiving evidence:** Is the current receiving store census clean under the intended two-sided method? Next evidence: Current code/input-bound census and per-root result; the recovered 9 October census is transition_clean=false, with 2,040 roots over balance.

Sources: `ef31-producer` lines 592–617, `ef31-producer` lines 1307–1330, `glam-producer` lines 200–241, `water-method-note`, `jrc-factor-source-check` at `/water_reference_rows`; recovery: `original-evidence-water-receipt-summary`, `original-evidence-water-census-20261009`, `original-evidence-water-emitter`, `original-evidence-water-bafu-roles`, `original-evidence-water-bio3-roles`.

## policy-06: Cooling/turbine water net-zero convention

**Inherited claim:** Retain the existing explicit-zero policy and its documented limitations pending scientific review. Never replace it with either a missing factor or an implied identity rule.

**Source comparison — supported:** Supported within the exact claim scope: an explicit local zero convention and its unresolved limitation are documented. This is support for preserving the convention as pending review, not support for scientifically approving zero consumption.

The 4bec1691 producer emits a literal 0.0 and a net_zero_turbine_cooling declaration for the cooling/turbine classes. Its preserved method note calls this a lower bound when cooling evaporation is not separately inventoried and says that error has not been measured. The note explicitly states GLAM inherits the local rule. Our prior scan of the hash-pinned JRC workbook records the positive and negative global intake/return pair rows.

**Evidence still needed after the comparison:** Scientific acceptance still needs an inventory census of linked intake, returns and evaporation, technology-specific evaporation evidence and a documented applicability decision. Measure the lower-bound error on the intended method and consumer. Do not treat balanced JRC pair arithmetic or agreement with an aggregate benchmark as proof that all cooling withdrawals are physically returned.

Sources: `ef31-producer` lines 574–617, `ef31-producer` lines 1307–1319, `water-method-note`, `jrc-factor-source-check` at `/water_reference_rows`.

## policy-07: GLAM regional water and recorded GLO fallback

**Inherited claim:** Preserve `water_regionalisation.json`, the selected country/GLO disposition and withdrawal policy. Keep experimental/beta designations and provider implementation metadata.

**Source comparison — partial:** The regional/default selection and its application record are supported by source. Complete provider-version lineage and scientific acceptance of the imported net-zero convention are not established for each application.

At 4bec1691, bridge_water_bafu uses the explicit country row when available, otherwise GLO with a recorded fallback reason; a published zero is preserved because the lookup tests None. It records counts and separate regional, default-fallback, net-zero, unmapped-class and unknown-unit outcomes. workbench-inputs identifies the GLAM beta version and experimental ecotoxicity caveat. The sidecar itself contains producer/rule/method records but no full provider-file digest/version binding; cooling/turbine zeroing is inherited from the EF local rule.

**Evidence still needed after the comparison:** Bind each method application to the exact provider release, file hash, method implementation and regional row. Keep region-less use separate from failed-region fallback, including the actual default factor. Preserve beta/experimental metadata through projection and registration. Decide whether the local EF net-zero convention is appropriate under each GLAM water method; historical reuse does not supply independent GLAM justification.

**Recovered original evidence**

- **provider-release identity:** All 29 local GLAM workbooks match both the historical GLAM_CHECKSUMS SHA-256 entries and the publisher MD5 values in Zenodo record 20630461, version 1.1.2026.06.24beta.
- **provider-row corroboration:** All 4,924 explicitly recorded regional/GLO-fallback water assignments match an original provider row exactly: 1,231 per method. EQ damage has 802 regional/429 fallback; EQ midpoint 952/279; HH damage 932/299; HH midpoint 952/279. Every match retains workbook hash, sheet, row, method, flow class, location and unit. Each method separately has 8 regionless assignments and 503 local policy zeros; those are not counted among the 4,924 checks.

**Still required**

- **policy versus provider:** Are the 503 pass-through zeros per method and country→GLO fallback choices accepted for this application? Next evidence: Explicit application decision plus inventory evidence; source CF equality only establishes the selected provider values.
- **complete application coverage:** What are the exact source and receiving rows for the eight regionless assignments per method and all rejected/unmapped classes? Next evidence: Complete code-level application census including deliberate absences and quantity conversions.
- **scientific scope:** Have beta/experimental implementation caveats been reviewed for each adopted category? Next evidence: Method-specific scope review; file identity does not approve experimental methods.

Sources: `glam-producer` lines 188–299, `glam-water-applications`, `workbench-inputs` lines 98–125, `water-method-note`, `method-registration` lines 88–105; recovery: `original-evidence-provider-row-checks`, `original-evidence-glam-checksums`, `original-evidence-glam-extraction-manifest`, `original-evidence-zenodo-20630461`, `glam-water-applications`.

## policy-08: Fossil resource heating values, density and composition

**Inherited claim:** Determine whether the pinned source correspondence already includes the conversion. Apply it exactly once; retain any remaining source-specific assumption as an explicit, evidenced quantity binding or held case.

**Source comparison — partial:** Applying a conversion once is supported as a candidate-projector contract, not as a demonstrated property of the historical fossil producer. The historical defaults also include calibration assumptions that need their own source evidence.

At 4bec1691, fossil_resource_cf parses explicit MJ/GJ density text or returns hard-coded defaults; the adjacent comment says selected defaults were recalibrated to BAFU implied densities. The historical overlay subsequently assigns raw JRC values by UUID and carries no quantity multiplier field. The candidate projector source at 1aa303f9 composes native-to-source and source-to-consensus multipliers, then multiplies the factor once while leaving inventory quantities unchanged.

**Evidence still needed after the comparison:** Recover source-flow quantity definitions, actual importer conversion ledgers and the calibration dataset/rationale for the defaults. Check whether the recorded source correspondence already includes heating value, density or composition, and separately verify native units. Establish parity on real pinned observations before adoption. This inspection does not demonstrate an actual historical double-conversion occurrence; neither does source code alone prove the current pipeline applies every required conversion exactly once.

**Recovered original evidence**

- **target source quantity:** JRC original flow-property rows 40003/44950/57844/70708/75246/92612 declare brown coal/crude oil/hard coal/natural gas/peat/uranium as Net calorific value, MJ; CF rows 156658–156663 are 1 per native MJ.
- **upstream conversion:** The pinned upstream BAFU overrides at 19d6cc62 explicitly state kg/m3→MJ factors: oil 43.1, hard coal 18.01, brown coal 9.41, natural gas 36, peat 9.76, uranium 560000. Exact local upstream concept associations independently retain these numbers. They are original mapping decisions, not independently validated calorific measurements. The historical Workbench derivative exposes source/target unit changes but drops conversion/match fields.
- **historical calibration:** Original commit 832a46ae states BAFU-output calibration of oil 45.8→43.3, hard coal 30.7→18.5, brown coal 9.9→9.5 and gas 40.3→36. Its AI coauthor trailer is retained. This explains the different local constants; benchmark fit does not establish the physical quantity.
- **source quantity example:** The inspected original BAFU XML process 68bb95fd-1526-388c-a01a-50b8d99534b1 has Oil, crude, Coal, hard and Coal, brown quantities in kg. The source quantities are not MJ merely because the target is MJ.

**Still required**

- **historical full pin:** Did the exact 22 September source JSON export carry these same conversion values before the Workbench derivative omitted them? Next evidence: Recover original full export with SHA-256 22b1b5f0b2e3…; the local SQLite has a different recorded run identity.
- **physical derivation:** What original supplier/calorific evidence supports each adopted NCV, particularly where upstream and local calibration differ? Next evidence: Actual referenced provider table or source-dataset energy evidence; recovered upstream comments are not measurement validation.
- **application:** For each real consumed native quantity, is conversion applied exactly once before the MJ-based factor? Next evidence: Conversion ledger and same-input source→projection→registered→served value receipt. No duplicate application is asserted without that evidence.

Sources: `ef31-producer` lines 682–780, `ef31-producer` lines 1392–1401, `overlay-producer` lines 65–75, `overlay-producer` lines 246–268, `module-source-f6274f266738a9c2` lines 140–189, `current-consensus-quantity-application` lines 48–67; recovery: `original-evidence-provider-row-checks`, `original-evidence-upstream-bafu-overrides`, `original-evidence-upstream-quantity-associations`, `original-evidence-historical-quantity-extract`, `original-evidence-bafu-quantity-example`, `original-evidence-fossil-calibration-commit`, `original-evidence-workbench-consensus-run`.

## policy-09: Mineral-resource leading-element treatment

**Inherited claim:** Preserve its quantity basis and derivation. Ore grade and element mass must not be multiplied twice or treated as interchangeable identities.

**Source comparison — partial:** The source implements a leading-element rule without multiplying ore grades. The required source-flow quantity basis remains a scientific premise, not a fact established by a kilogram unit or the existence of the code.

At 4bec1691, mineral_resource_cf selects the first comma-separated name component and uses its JRC mineral factor when an ore/grade tail is present. Its comment asserts amounts are kilograms of the leading element and cites aggregate BAFU agreement, but provides no per-flow defining document. The independently checked titanium amendments match the JRC titanium value; that numerical agreement does not resolve whether each BAFU TiO2-labelled source amount is titanium, TiO2 or another basis.

**Evidence still needed after the comparison:** For each ore family, attach the source flow/property definition, native amount basis and correspondence multiplier, plus a worked dimensional derivation. Distinguish elementary element mass, compound mass and ore mass. Only then establish that neither ore grade nor stoichiometry is omitted or counted twice. A JRC row for the bare element confirms the selected factor, not the source quantity interpretation.

The later [titanium application trace](titanium-quantity-application-2026-10-13.md)
receives the current quantities and processed factors. It finds zero applications
of 0.599 in the selected historical path, while scientific interpretation and a
qualified quantity-aware replacement remain open. The earlier questions below
are preserved as the record of this recovery stage.

**Recovered original evidence**

- **original quantity evidence:** The source BAFU XML explicitly names TiO2, 54% in ilmenite, 2.6% in crude ore, CAS 13463-67-7, unit kg, with an empty generalComment. JRC row 156706 is titanium 2.79e-08; source property row 89298 is titanium, Mass/kg. Neither equal unit labels nor a leading-element name proves equal mass bases.
- **original upstream decision:** Pinned upstream BAFU overrides for source UUIDs 52b760ca-3444-564a-a215-271d4af41250 and 73746710-2506-50d1-811a-521b48526172 explicitly require conversion_factor 0.599, cite rulings #118/#141 and state TiO2→elemental Ti. The recovered local upstream associations mark these broadMatch with qudt:conversionMultiplier 0.599. Historical Workbench derived rows retain the target but omit both conversion and match qualification.
- **historical rationale:** Commit 7d169b0f records the leading-element policy and BAFU aggregate agreement, with an AI coauthor. It establishes origin of the local rule, not that every ore/compound quantity is elemental mass. This is a concrete unresolved conflict for wb-factor-af8bc1926a017bd6 and wb-factor-cacf7c5e1102cf6c.

**Still required**

- **binding/application:** Are the two TiO2 quantities converted by 0.599 exactly once in the accepted flow correspondence and actual factor application? Next evidence: Exact pinned full correspondence plus receiving quantity ledger for the two native BAFU codes; do not silently change their existing factors from this audit.
- **scientific applicability:** Which remaining mineral flows represent elemental, compound or ore mass, and what derivation applies to each? Next evidence: Original flow-property/source documentation and a case-level reviewed quantity decision; aggregate agreement cannot settle each identity.

Sources: `ef31-producer` lines 718–742, `ef31-producer` lines 1403–1410, `jrc-factor-source-check` at `/checks/0`, `jrc-factor-source-check` at `/checks/1`; recovery: `original-evidence-provider-row-checks`, `original-evidence-upstream-bafu-overrides`, `original-evidence-upstream-quantity-associations`, `original-evidence-historical-quantity-extract`, `original-evidence-bafu-quantity-example`, `original-evidence-mineral-leading-commit`.

## policy-10: Particulate and sulfur-oxide defaults

**Inherited claim:** Preserve the chosen category/context policy and source row. Compare with consensus-resolved targets; similar names alone cannot carry a factor.

**Source comparison — partial:** The code provides explicit PM/SOx defaults, but several are proxies or benchmark-derived context choices. It does not require a consensus-resolved target for each application.

At 4bec1691, particulate_air_cf applies a size-class factor across spatial variants, uses PM10 as a proxy for the 2.5–10 micrometre fraction, returns zero for non-air particles and large particles, and assigns a PM2.5 default to remaining particulate names. particulate_sox_air_cf applies one non-urban/high-stack sulfur-dioxide factor across sulfur-oxide names. The source comment traces that context choice to inference from BAFU results, not a source-row subcompartment declaration.

**Evidence still needed after the comparison:** Record the exact JRC row and its unit/context separately from each local proxy. Recover evidence for coarse-fraction substitution, bare-PM interpretation and the shared SOx quantity basis; retain explicit non-characterization separately from a measured physical zero. Compare exact source contexts and compound quantities with consensus results, using scoped exceptions rather than promoting name-family rules into universal equivalence. The benchmark-inferred non-urban choice still needs a documented scientific decision.

**Recovered original evidence**

- **provider-row corroboration:** Recovered original PM rows: PM2.5 unspecified 2.38497e-04 (2559), non-urban/high-stack 3.01757e-06 (2562); PM10 unspecified 5.48544e-05 (2555), non-urban/high-stack 6.94042e-07 (2558). Sulfur dioxide unspecified is 8e-06 (3415, long-term; other exact contexts retained), non-urban/high-stack 9.9e-07 (3489). These source values corroborate constants, not the choice of a context.
- **original rejected hypothesis:** Commit e1653988 records that switching PM to non-urban/high-stack worsened its BAFU comparison to −88.5%, and restored the unspecified default. The preserved text records the historical hypothesis and reversal; its asserted cause remains unproved without the original diagnostic inputs/results.

**Still required**

- **calibration history:** Where are the original 28 single-flow SO2 product calculations and failed PM diagnostic outputs with exact source/input identities? Next evidence: Recover row-level calibration files or archived original run output; current code comments and git messages alone do not reproduce them.
- **scientific applicability:** What method/source evidence authorises PM size-bin proxies and the SOx chosen context/quantity convention? Next evidence: Category and source-flow definition with exact source row and reviewed treatment of unsupported bins/context.

Sources: `ef31-producer` lines 784–877, `ef31-producer` lines 1374–1390, `current-consensus-method-projection` lines 31–41; recovery: `original-evidence-provider-row-checks`, `original-evidence-pm-reversal-commit`, `original-evidence-ef31-oracle-baseline`, `ef31-producer`.

## policy-11: Climate extensions and unqualified carbon treatment

**Inherited claim:** Preserve the BAFU and bio3 extension sidecars, code coverage and scientific scope. Explicit fossil, biogenic, land-use and stock/correction semantics must survive.

**Source comparison — partial:** The extension sidecars and named values are preserved. Scientific scope and all fossil/biogenic/stock semantics are not established merely by retaining those files; bare CO2 is explicitly given a local fossil interpretation.

At 4bec1691, the BAFU extension maps land-transformation CO2 to +1, soil/biomass-stock CO2 to -1, delayed fossil CO2 correction to +1 and unqualified CO2 to +1 as a conservative fossil default. Extensions fill previously uncharacterized codes and are listed separately. The biosphere3 bridge explicitly selects a land-use-change variant for a from-stock qualifier. These are concrete implementation choices, not independent scientific approvals; the sidecars identify affected codes but do not contain all source definitions and decision evidence.

**Evidence still needed after the comparison:** Bind each extension to its original source flow, direction, quantity and method definition, including the treatment of stock changes and delayed emissions. Retain the bare-carbon fossil assumption as an explicit scoped exception with justification and removal conditions. Verify no context or qualifier is lost in normalization, overlay, registration or consumption; a preserved name and numeric sign alone do not prove the inventory semantics.

**Recovered original evidence**

- **provider scientific scope:** Recovered original JRC climate rows distinguish fossil CO2 emission 1 (1121–1126), fossil uptake 0 (160403/160689), biogenic CO2 0 (1114–1120), and land-use-change CO2 with opposite input/output signs (2547/2548). This corroborates the need to retain physical direction and category; it does not authorise stock/delay/bare-CO2 extensions.
- **upstream decision trail:** The pinned upstream BAFU override file retains distinct decisions for unqualified CO2 and source-specific carbon meanings. The original BAFU/bio3 extension sidecars continue to identify four codes each. These are maintained as local extension coverage, not relabelled as JRC-exact.

**Still required**

- **scientific extension basis:** What original method authority and inventory convention support each stock, delayed-emission, land-transformation and bare-CO2 extension value? Next evidence: Per-code source definition, sign/quantity rationale, primary method reference and scoped review.
- **receiving coverage:** Do the accepted profile and consuming inventories preserve all extension codes and their separate dispositions? Next evidence: Code/quantity/value coverage receipt spanning producer, registered factors and served inventory.

Sources: `ef31-producer` lines 1239–1260, `ef31-producer` lines 1448–1465, `bafu-climate-extensions`, `bio3-climate-extensions`, `bio3-producer` lines 15–40, `bio3-producer` lines 267–277; recovery: `original-evidence-provider-row-checks`, `original-evidence-upstream-bafu-overrides`, `bafu-climate-extensions`, `bio3-climate-extensions`.

## policy-12: IPCC, ILCD, GLAM, ecological-scarcity and AWARE implementations

**Inherited claim:** Keep their accepted provider/version/category/quantity and regional metadata. Migrate each independently; absence from the first profile is not retirement.

**Source comparison — partial:** The named method families have heterogeneous historical origins. The register does not establish a single set of scientifically accepted provider versions and policies, and AWARE is not evidenced by the preserved Workbench extraction code.

At 4bec1691, IPCC and ILCD are extracted from existing Brightway methods, while GLAM has a named beta release. Ecological-scarcity extraction tries two 2021 names and then a 2013 fallback, returns only code-to-value factors and can merge land factors inferred from published product totals. The preserved UBP note contains a later update correcting its earlier conclusion and reporting 13 added land factors. Nine IPCC additions are separately retained as historical local rules. The water note refers the AWARE convention to the water tributary rather than declaring it settled.

**Evidence still needed after the comparison:** Create one reviewed provider record per family/version, carrying actual selected method tuple, source-file identity, factor/flow units, regional policy and declared local modifications. Recover the original IPCC/ILCD import sources and the UBP supplement derivation, including the later correction; distinguish an original provider factor from an inferred supplement. Obtain the AWARE owner/version/application evidence from its own project. Missing from the candidate profile must remain unsupported, and should not be described as retirement or a zero method.

**Recovered original evidence**

- **AWARE original provider tables:** Downloaded the exact original AWARE2.0 country workbook from Zenodo 15133241 (v1.0.0); provider MD5 15a9326a27bf5686019bbf3fe3ae7936 matches, SHA-256 b8481b0fac18…. With the pinned reader, annual and monthly 519-location JSON tables and the 540-location monthly water-demand table reproduce exactly. This corroborates the committed table values, not all CF resolution/application policies or newest release adoption.
- **UBP original history:** Recovered original UBP validation report from commit 6ca04d10: 11,837 comparisons, median 0.9115205298114746 and 87.41574950942751% within 2x. This is the pre-supplement run, not proof of the later 13 inferred land factors. The exact 13-value land supplement says factors were backed out from product totals; original per-factor product/mass/residual derivation is not present there.
- **method identity:** Recovered historical extraction metadata and original GLAM release pins. The original records distinguish source extract, locally inferred supplement and newer water application. A family label cannot imply all are the same provider-approved method.

**Still required**

- **provider-specific independence:** Where are the complete accepted IPCC/ILCD/UBP provider versions, original factor tables and registration manifests for each retained method? Next evidence: Individual provider input/version/quantity ledgers; the historical exporter names live Brightway sources but does not provide all original provider bytes.
- **UBP calibration:** Which product, observed land mass, known-factor subtraction and residual justifies each of the 13 supplemented factors? Next evidence: Original calibration dataset and script/output for each value, plus explicit scientific review; do not count the pre-supplement validation as validation of those additions.
- **AWARE applicability:** Which variant, region, source water basis and fallback is adopted for each actual use? Next evidence: Application row/quantity evidence and scoped method decision; provider table roundtrip does not establish consumption accounting.

Sources: `export-producer` lines 414–527, `export-producer` lines 1044–1046, `historical-ipcc-additions` lines 14–30, `workbench-inputs` lines 98–125, `policy-ubp-validation`, `water-method-note`, `current-consensus-method-projection` lines 31–41; recovery: `original-evidence-provider-row-checks`, `original-evidence-zenodo-15133241`, `original-evidence-aware-provider-reader`, `original-evidence-ubp-original-validation`, `original-evidence-ubp-land-supplement`, `original-evidence-workbench-extraction-meta`, `original-evidence-water-registry-manifest`.

## policy-13: Method registration and served-code checks

**Inherited claim:** Reuse existing project-local key resolution and differential acceptance. Validate registered factors and served inventories separately from source output.

**Source comparison — partial:** Existing code supports project-local key resolution and a separate differential-gate policy. Neither establishes full numerical or served-inventory validation for this migration.

At 4bec1691, the registrar resolves native codes to project IDs, refuses empty/all-zero resolved sets and reads a written method back through assert_registrable. That gate checks key reachability and requested database presence; it is not numerical equality or complete inventory coverage. The differential ADR explicitly allows an already-poor baseline and judges transitions. The candidate projection documentation independently lists actual provider receiving, numerical comparison, registration and served-graph validation as outstanding.

**Evidence still needed after the comparison:** Retain separate receipts for source factors, registered keys/values and the actual served inventory generation. Compare every intended factor and any sibling factors introduced by registration, not just counts or nonempty resolution. Record the baseline and standing findings for differential acceptance. A passing structural registration or non-regression gate must not be promoted to scientific correctness, current consumer adoption or complete coverage.

**Recovered original evidence**

- **receiving project identity:** Recovered BAFU build manifest dated 2026-09-29T04:50:42+00:00, importer 0.1.10, content_sha256 045764a2d858…. It records release/raw identities, corrections and measured counts. The catalogue contract says content identity covers no method; this manifest is not an EF/GLAM factor-value readback.
- **application observations:** The independently preserved 9 October EDB_BAFU water census is not clean (2,040 roots exceed balance). The EF oracle baseline retains per-category aggregate ratios, including PM 1.868154 and freshwater ecotoxicity 2.799344; these are historical accepted comparison baselines, not universal accuracy or current application receipts.

**Still required**

- **registered factors:** Do receiving methods contain the exact intended factor values, conversions and native-flow keys after registration? Next evidence: Complete project-local value/key readback bound to the actual source/profile and code generation.
- **served inventory:** Does the intended served graph consume the same flows/quantities and satisfy the specific acceptance test? Next evidence: Current inventory/store identity plus served factor and quantity census; recovered historic build identity and differential tolerance do not establish this.
- **acceptance:** Who accepted the stated comparison scope and unresolved scientific limitations? Next evidence: Scoped reviewer/sign-off record; no approval is fabricated by this recovery.

Sources: `method-registration` lines 113–165, `method-registration` lines 180–238, `policy-method-gate` lines 65–127, `policy-differential-gate`, `current-consensus-method-projection` lines 69–88; recovery: `original-evidence-bafu-build-manifest`, `original-evidence-bafu-release`, `original-evidence-water-census-20261009`, `original-evidence-ef31-oracle-baseline`, `policy-differential-gate`, `policy-method-gate`, `method-registration`.

## Review limits

This review inspected source content and previously preserved method evidence. The original JRC workbook corroboration remains bounded by its receipt: numerical row correspondence, no independent confirmation of source-flow quantity or scientific appropriateness. Workbench comments about benchmark results, literature, validation or acceptance remain attributed historical claims unless separate evidence is linked.

The UBP method note is especially important to retain whole: its later update corrects the earlier assertion that the land gap should not be filled using product totals. The review records that chronology without making the older prose disappear or accepting the inferred factors as independently published provider data. The candidate profile and projection code are contracts; they do not authenticate real provider inputs merely by accepting their schema.

The first pass researched no new external scientific literature; the shared literature workflow and canonical library had been checked in the preceding source audit, and original physical-policy evidence still needs targeted recovery under that workflow. The second pass recovered provider files, not literature.

The source index in the receipt binds each cited new artifact to its SHA-256. Git copies retain exact revision and path; provider records retain immutable release URLs. The numerical provider check reads original Excel cells using openpyxl; it imports only the pinned pure AWARE reader functions, and performs no registration or LCA. Its GLAM check corroborates recorded CF values at the chosen class/location, not correctness of that class/location choice. Regionless and local-zero dispositions are explicitly outside that comparison.

Historical receipts establish what was recorded at that time. They do not become current acceptance evidence because their files were recovered. The 9 October water census explicitly records failure of the transition criterion. Catalogue manifest identity also excludes method values; it cannot substitute for an LCIA readback.

The canonical shared literature guide and source-value knowledge context were loaded. Library queries and published-catalog/MR checks are retained in the receipt. The original AWARE workbook/API were recovered from [Zenodo 15133241](https://zenodo.org/records/15133241); its metadata identifies [the method paper](https://doi.org/10.1111/jiec.70023). No claim of having read or scientifically validated that paper is made. The GLAM provider record is [Zenodo 20630461](https://zenodo.org/records/20630461). Central library acquisition remains a separate task if those scientific claims are to be adopted.

Raw BAFU XML and workbooks and private inventory corpora were not copied into Git; local selected-source excerpts remain subject to BAFU terms.

Every source the two passes cite is pinned by SHA-256 in the two receipts named
above; the evidence identifiers in the `Sources` lines are the names those
receipts use.
