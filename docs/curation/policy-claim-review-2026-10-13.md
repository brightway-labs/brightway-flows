# Method-policy claim review, 13 October 2026

Cooling water provides a useful distinction: the source really does record a local zero convention and an unmeasured evaporation limitation. In contrast, the inherited sentence that a missing factor must remain absent is a requirement for migration; the historical registrar actually fills missing sibling factors. This review preserves the intended rules while identifying what the retained code does today at its pinned historical revision.

The 13 descriptions were compared with preserved Workbench sources at `4bec1691c938db6ec61a8c7e667e10c5307827c7`, candidate-projector code at `1aa303f9e1a3afff27894b30695ef79f1848fccc`, and candidate documentation at `03fd243f76aa886f971148efc217dc5c61ddf6c6`. The structured receipt is `policy-claim-review.json` in the local migration bundle. It pins the exact inherited summary and every cited source with SHA-256.

**Support means support for the precise description, not scientific approval.** One bounded preservation claim is supported; 12 are partially supported. No case received scientific sign-off, no method or inventory was changed, and no scientific build ran. A normative requirement is not marked false just because historical code fails to meet it.

| Case | Support | Main distinction |
|---|---|---|
| `policy-01` | partial | The inherited text is a migration requirement. The historical UUID index gives headline methods precedence but otherwise keeps the first row; it does not meet a general no-first-match or complete-row-provenance guarantee. |
| `policy-02` | partial | The requirement to retain exact context and keep missing factors absent is stricter than the historical pipeline. The historical producer records some context fallbacks, while the registrar also fills missing sibling factors without per-sibling provenance. |
| `policy-03` | partial | Explicit location selection is implemented in the later candidate projector, but historical emission lookup has a default-location fallback. The description must identify which generation it describes. |
| `policy-04` | partial | The historical code preserves occupation versus transformation-from/to selection and uses the same land-class resolver, but some source qualifiers and locations are deliberately generalized. The migration wording must not imply full semantic preservation has already been demonstrated. |
| `policy-05` | partial | There are distinct historical water policies. EF 3.1 prices embodied water through its resource-water path, while the GLAM bridge excludes embodied water, returns and evaporation from that path. The source supports keeping their distinctions, not one universally accepted water interpretation. |
| `policy-06` | supported | Supported within the exact claim scope: an explicit local zero convention and its unresolved limitation are documented. This is support for preserving the convention as pending review, not support for scientifically approving zero consumption. |
| `policy-07` | partial | The regional/default selection and its application record are supported by source. Complete provider-version lineage and scientific acceptance of the imported net-zero convention are not established for each application. |
| `policy-08` | partial | Applying a conversion once is supported as a candidate-projector contract, not as a demonstrated property of the historical fossil producer. The historical defaults also include calibration assumptions that need their own source evidence. |
| `policy-09` | partial | The source implements a leading-element rule without multiplying ore grades. The required source-flow quantity basis remains a scientific premise, not a fact established by a kilogram unit or the existence of the code. |
| `policy-10` | partial | The code provides explicit PM/SOx defaults, but several are proxies or benchmark-derived context choices. It does not require a consensus-resolved target for each application. |
| `policy-11` | partial | The extension sidecars and named values are preserved. Scientific scope and all fossil/biogenic/stock semantics are not established merely by retaining those files; bare CO2 is explicitly given a local fossil interpretation. |
| `policy-12` | partial | The named method families have heterogeneous historical provenance. The register does not establish a single set of scientifically accepted provider versions and policies, and AWARE is not evidenced by the preserved Workbench extraction code. |
| `policy-13` | partial | Existing code supports project-local key resolution and a separate differential-gate policy. Neither establishes full numerical or served-inventory validation for this migration. |

## policy-01: JRC headline versus organic/inorganic sub-method priority

**Inherited claim:** Keep the selected implementation and row provenance from `JrcUuidIndex`/the provider reader. A profile must not mix competing implementations by arbitrary first match.

**Source comparison — partial:** The inherited text is a migration requirement. The historical UUID index gives headline methods precedence but otherwise keeps the first row; it does not meet a general no-first-match or complete-row-provenance guarantee.

At Workbench 4bec1691c938db6ec61a8c7e667e10c5307827c7, JrcUuidIndex keys by EF UUID, location and category and stores the winning method name internally. Its add() selects a headline over a non-headline; otherwise the first value remains. The name index separately prefers unspecified contexts. At the later 03fd243f76aa886f971148efc217dc5c61ddf6c6 documentation pin, the candidate profile requires provider implementation/revision and one factor per target/category/location. These are contract requirements, not a received real provider profile.

**Evidence still needed:** Preserve the actual winner and every competing method row, including original method UUID, context, worksheet locator and source hash. Define and review a deterministic tie policy when more than one non-headline candidate remains. The historical overlay sidecar omits the selected method identity and row locator; our JRC source check recovers those for 292 amendments but does not establish the full provider or a scientific choice between alternatives.

Sources: [overlay-producer](/curation/evidence/overlay-producer?line=107&end=170), [ef31-producer](/curation/evidence/ef31-producer?line=104&end=109), [ef31-producer](/curation/evidence/ef31-producer?line=882&end=1015), [current-consensus-method-projection](/curation/evidence/current-consensus-method-projection?line=19&end=41), [jrc-factor-source-check](/curation/evidence/jrc-factor-source-check?pointer=%2Fselection_policy).

## policy-02: Compartment restrictions and the sub-compartment coverage repair

**Inherited claim:** Exact target context in the profile and every consumed native code in the census. A missing factor stays absent; a sibling flow cannot supply one silently.

**Source comparison — partial:** The requirement to retain exact context and keep missing factors absent is stricter than the historical pipeline. The historical producer records some context fallbacks, while the registrar also fills missing sibling factors without per-sibling provenance.

The BAFU producer restricts allowed top compartments. The biosphere3 bridge first selects the mapped sub-compartment and otherwise records an unspecified-context fallback. At the same 4bec1691 pin, register_methods.py groups nodes by name and top compartment, then copies a factor to siblings with setdefault; this can fill a missing sub-compartment factor after source production. The later candidate projector instead requires context/unit equality and exact provider selection.

**Evidence still needed:** The receipt must distinguish a source factor, an explicitly reviewed context carry and a registrar-created sibling factor. Capture every native code added by registration, its donor code, source/target contexts and policy; compare the registered result against the intended provider. Determine which historical carries should remain permitted. Source-file coverage alone cannot establish that a missing source factor stays absent in the served project.

Sources: [ef31-producer](/curation/evidence/ef31-producer?line=152&end=167), [ef31-producer](/curation/evidence/ef31-producer?line=1331&end=1421), [bio3-producer](/curation/evidence/bio3-producer?line=280&end=305), [method-registration](/curation/evidence/method-registration?line=113&end=165), [module-source-f6274f266738a9c2](/curation/evidence/module-source-f6274f266738a9c2?line=167&end=189).

## policy-03: Regional emission factors

**Inherited claim:** Explicit category/location selection. Any accepted default-region policy must be materialized and identified by the profile/application provider, not an implicit projector fallback.

**Source comparison — partial:** Explicit location selection is implemented in the later candidate projector, but historical emission lookup has a default-location fallback. The description must identify which generation it describes.

The 4bec1691 producer recognizes regional category slugs, parses a location suffix and tries that location before __none__. The overlay also prefers a located row when available, otherwise retains the default and records the chosen location_key. The candidate projector source at 1aa303f9e1a3afff27894b30695ef79f1848fccc uses an exact (target, category, selected location) key; no default-region fallback appears on that path.

**Evidence still needed:** A real provider profile and application need an explicit policy for each regional-to-default selection, including requested location, selected location and why a default is permitted. Reconcile the historical implicit fallbacks against those decisions; the candidate code contract and historical sidecar do not by themselves prove scientific acceptance or current consumer use.

Sources: [ef31-producer](/curation/evidence/ef31-producer?line=118&end=126), [ef31-producer](/curation/evidence/ef31-producer?line=1102&end=1110), [ef31-producer](/curation/evidence/ef31-producer?line=1199&end=1221), [overlay-producer](/curation/evidence/overlay-producer?line=228&end=268), [module-source-f6274f266738a9c2](/curation/evidence/module-source-f6274f266738a9c2?line=155&end=189), [current-consensus-method-projection](/curation/evidence/current-consensus-method-projection?line=57&end=67).

## policy-04: Land class mapping, occupation and transformation from/to

**Inherited claim:** Named, versioned land policy with source class, geography and sign retained. Preserve paired from/to treatment and test numerical changes against the accepted producer.

**Source comparison — partial:** The historical code preserves occupation versus transformation-from/to selection and uses the same land-class resolver, but some source qualifiers and locations are deliberately generalized. The migration wording must not imply full semantic preservation has already been demonstrated.

At 4bec1691, parse_bafu_land retains the kind and parses location; the same resolver serves all three kinds. land_cf selects the corresponding JRC value and keeps an explicit zero before trying GLO. LAND_CLASS_SYNONYMS contains interpretations such as organic pasture to intensive pasture and the resolver can remove trailing qualifiers. The generic result file records a code-to-factor value, not the complete original class and selected policy.

**Evidence still needed:** Attach an explicit land-class decision for each generalization, preserving the original qualified class, selected class, geography and exact factor row. Verify paired from/to coverage, signs and amounts on a pinned input generation; using one resolver does not prove all source class/kind combinations have a factor or that a pair actually occurs in inventories. Recover the evidence for intensity/organic-class interpretations and identify default-location applications.

Sources: [ef31-producer](/curation/evidence/ef31-producer?line=393&end=575), [ef31-producer](/curation/evidence/ef31-producer?line=1068&end=1080), [ef31-producer](/curation/evidence/ef31-producer?line=1224&end=1237), [ef31-producer](/curation/evidence/ef31-producer?line=1295&end=1305), [current-consensus-method-projection](/curation/evidence/current-consensus-method-projection?line=19&end=41).

## policy-05: Water class mapping and withdrawal/return distinction

**Inherited claim:** Named water policy retaining physical direction and origin. A shared substance identity does not equate withdrawal, return, evaporation or embodied water.

**Source comparison — partial:** There are distinct historical water policies. EF 3.1 prices embodied water through its resource-water path, while the GLAM bridge excludes embodied water, returns and evaporation from that path. The source supports keeping their distinctions, not one universally accepted water interpretation.

At 4bec1691, WATER_CLASS_MAP maps embodied water to generic water, and rebuild_all allows resource/unknown-compartment water plus any name containing embodied. The GLAM bridge instead requires the natural resource compartment and explicitly explains why returns, evaporation and embodied water are not credited. The pinned JRC workbook corroborates opposite intake/return factors for cooling and turbine water; these rows are distinct resources/emissions with input/output directions.

**Evidence still needed:** Review and name the method-specific physical boundary: withdrawal, consumption, return, evaporation and embodied water. For each class, retain the original flow definition, direction, unit, receiving context and application policy. The presence of an embodied label or a shared substance identity is insufficient evidence of resource withdrawal, and the JRC intake/return pair does not establish the treatment of every source inventory.

Sources: [ef31-producer](/curation/evidence/ef31-producer?line=592&end=617), [ef31-producer](/curation/evidence/ef31-producer?line=1307&end=1330), [glam-producer](/curation/evidence/glam-producer?line=200&end=241), [water-method-note](/curation/evidence/water-method-note), [jrc-factor-source-check](/curation/evidence/jrc-factor-source-check?pointer=%2Fwater_reference_rows).

## policy-06: Cooling/turbine water net-zero convention

**Inherited claim:** Retain the existing explicit-zero policy and its documented limitations pending scientific review. Never replace it with either a missing factor or an implied identity rule.

**Source comparison — supported:** Supported within the exact claim scope: an explicit local zero convention and its unresolved limitation are documented. This is support for preserving the convention as pending review, not support for scientifically approving zero consumption.

The 4bec1691 producer emits a literal 0.0 and a net_zero_turbine_cooling declaration for the cooling/turbine classes. Its preserved method note calls this a lower bound when cooling evaporation is not separately inventoried and says that error has not been measured. The note explicitly states GLAM inherits the local rule. Our prior scan of the hash-pinned JRC workbook records the positive and negative global intake/return pair rows.

**Evidence still needed:** Scientific acceptance still needs an inventory census of linked intake, returns and evaporation, technology-specific evaporation evidence and a documented applicability decision. Measure the lower-bound error on the intended method and consumer. Do not treat balanced JRC pair arithmetic or agreement with an aggregate benchmark as proof that all cooling withdrawals are physically returned.

Sources: [ef31-producer](/curation/evidence/ef31-producer?line=574&end=617), [ef31-producer](/curation/evidence/ef31-producer?line=1307&end=1319), [water-method-note](/curation/evidence/water-method-note), [jrc-factor-source-check](/curation/evidence/jrc-factor-source-check?pointer=%2Fwater_reference_rows).

## policy-07: GLAM regional water and recorded GLO fallback

**Inherited claim:** Preserve `water_regionalisation.json`, the selected country/GLO disposition and withdrawal policy. Keep experimental/beta designations and provider implementation metadata.

**Source comparison — partial:** The regional/default selection and its application record are supported by source. Complete provider-version lineage and scientific acceptance of the imported net-zero convention are not established for each application.

At 4bec1691, bridge_water_bafu uses the explicit country row when available, otherwise GLO with a recorded fallback reason; a published zero is preserved because the lookup tests None. It records counts and separate regional, default-fallback, net-zero, unmapped-class and unknown-unit outcomes. workbench-inputs identifies the GLAM beta version and experimental ecotoxicity caveat. The sidecar itself contains producer/rule/method records but no full provider-file digest/version binding; cooling/turbine zeroing is inherited from the EF local rule.

**Evidence still needed:** Bind each method application to the exact provider release, file hash, method implementation and regional row. Keep region-less use separate from failed-region fallback, including the actual default factor. Preserve beta/experimental metadata through projection and registration. Decide whether the local EF net-zero convention is appropriate under each GLAM water method; historical reuse does not supply independent GLAM justification.

Sources: [glam-producer](/curation/evidence/glam-producer?line=188&end=299), [glam-water-applications](/curation/evidence/glam-water-applications), [workbench-inputs](/curation/evidence/workbench-inputs?line=98&end=125), [water-method-note](/curation/evidence/water-method-note), [method-registration](/curation/evidence/method-registration?line=88&end=105).

## policy-08: Fossil resource heating values, density and composition

**Inherited claim:** Determine whether the pinned source correspondence already includes the conversion. Apply it exactly once; retain any remaining source-specific assumption as an explicit, evidenced quantity binding or held case.

**Source comparison — partial:** Applying a conversion once is supported as a candidate-projector contract, not as a demonstrated property of the historical fossil producer. The historical defaults also include calibration assumptions that need their own source evidence.

At 4bec1691, fossil_resource_cf parses explicit MJ/GJ density text or returns hard-coded defaults; the adjacent comment says selected defaults were recalibrated to BAFU implied densities. The historical overlay subsequently assigns raw JRC values by UUID and carries no quantity multiplier field. The candidate projector source at 1aa303f9e1a3afff27894b30695ef79f1848fccc composes native-to-source and source-to-consensus multipliers, then multiplies the factor once while leaving inventory quantities unchanged.

**Evidence still needed:** Recover source-flow quantity definitions, actual importer conversion ledgers and the calibration dataset/rationale for the defaults. Check whether the recorded source correspondence already includes heating value, density or composition, and separately verify native units. Establish parity on real pinned observations before adoption. This inspection does not demonstrate an actual historical double-conversion occurrence; neither does source code alone prove the current pipeline applies every required conversion exactly once.

Sources: [ef31-producer](/curation/evidence/ef31-producer?line=682&end=780), [ef31-producer](/curation/evidence/ef31-producer?line=1392&end=1401), [overlay-producer](/curation/evidence/overlay-producer?line=65&end=75), [overlay-producer](/curation/evidence/overlay-producer?line=246&end=268), [module-source-f6274f266738a9c2](/curation/evidence/module-source-f6274f266738a9c2?line=140&end=189), [current-consensus-quantity-application](/curation/evidence/current-consensus-quantity-application?line=48&end=67).

## policy-09: Mineral-resource leading-element treatment

**Inherited claim:** Preserve its quantity basis and derivation. Ore grade and element mass must not be multiplied twice or treated as interchangeable identities.

**Source comparison — partial:** The source implements a leading-element rule without multiplying ore grades. The required source-flow quantity basis remains a scientific premise, not a fact established by a kilogram unit or the existence of the code.

At 4bec1691, mineral_resource_cf selects the first comma-separated name component and uses its JRC mineral factor when an ore/grade tail is present. Its comment asserts amounts are kilograms of the leading element and cites aggregate BAFU agreement, but provides no per-flow defining document. The independently checked titanium amendments match the JRC titanium value; that numerical agreement does not resolve whether each BAFU TiO2-labelled source amount is titanium, TiO2 or another basis.

**Evidence still needed:** For each ore family, attach the source flow/property definition, native amount basis and correspondence multiplier, plus a worked dimensional derivation. Distinguish elementary element mass, compound mass and ore mass. Only then establish that neither ore grade nor stoichiometry is omitted or counted twice. A JRC row for the bare element confirms the selected factor, not the source quantity interpretation.

Sources: [ef31-producer](/curation/evidence/ef31-producer?line=718&end=742), [ef31-producer](/curation/evidence/ef31-producer?line=1403&end=1410), [jrc-factor-source-check](/curation/evidence/jrc-factor-source-check?pointer=%2Fchecks%2F0), [jrc-factor-source-check](/curation/evidence/jrc-factor-source-check?pointer=%2Fchecks%2F1).

## policy-10: Particulate and sulfur-oxide defaults

**Inherited claim:** Preserve the chosen category/context policy and source row. Compare with consensus-resolved targets; similar names alone cannot carry a factor.

**Source comparison — partial:** The code provides explicit PM/SOx defaults, but several are proxies or benchmark-derived context choices. It does not require a consensus-resolved target for each application.

At 4bec1691, particulate_air_cf applies a size-class factor across spatial variants, uses PM10 as a proxy for the 2.5–10 micrometre fraction, returns zero for non-air particles and large particles, and assigns a PM2.5 default to remaining particulate names. particulate_sox_air_cf applies one non-urban/high-stack sulfur-dioxide factor across sulfur-oxide names. The source comment traces that context choice to inference from BAFU results, not a source-row subcompartment declaration.

**Evidence still needed:** Record the exact JRC row and its unit/context separately from each local proxy. Recover evidence for coarse-fraction substitution, bare-PM interpretation and the shared SOx quantity basis; retain explicit non-characterization separately from a measured physical zero. Compare exact source contexts and compound quantities with consensus results, using scoped exceptions rather than promoting name-family rules into universal equivalence. The benchmark-inferred non-urban choice still needs a documented scientific decision.

Sources: [ef31-producer](/curation/evidence/ef31-producer?line=784&end=877), [ef31-producer](/curation/evidence/ef31-producer?line=1374&end=1390), [current-consensus-method-projection](/curation/evidence/current-consensus-method-projection?line=31&end=41).

## policy-11: Climate extensions and unqualified carbon treatment

**Inherited claim:** Preserve the BAFU and bio3 extension sidecars, code coverage and scientific scope. Explicit fossil, biogenic, land-use and stock/correction semantics must survive.

**Source comparison — partial:** The extension sidecars and named values are preserved. Scientific scope and all fossil/biogenic/stock semantics are not established merely by retaining those files; bare CO2 is explicitly given a local fossil interpretation.

At 4bec1691, the BAFU extension maps land-transformation CO2 to +1, soil/biomass-stock CO2 to -1, delayed fossil CO2 correction to +1 and unqualified CO2 to +1 as a conservative fossil default. Extensions fill previously uncharacterized codes and are listed separately. The biosphere3 bridge explicitly selects a land-use-change variant for a from-stock qualifier. These are concrete implementation choices, not independent scientific approvals; the sidecars identify affected codes but do not contain all source definitions and decision evidence.

**Evidence still needed:** Bind each extension to its original source flow, direction, quantity and method definition, including the treatment of stock changes and delayed emissions. Retain the bare-carbon fossil assumption as an explicit scoped exception with justification and removal conditions. Verify no context or qualifier is lost in normalization, overlay, registration or consumption; a preserved name and numeric sign alone do not prove the inventory semantics.

Sources: [ef31-producer](/curation/evidence/ef31-producer?line=1239&end=1260), [ef31-producer](/curation/evidence/ef31-producer?line=1448&end=1465), [bafu-climate-extensions](/curation/evidence/bafu-climate-extensions), [bio3-climate-extensions](/curation/evidence/bio3-climate-extensions), [bio3-producer](/curation/evidence/bio3-producer?line=15&end=40), [bio3-producer](/curation/evidence/bio3-producer?line=267&end=277).

## policy-12: IPCC, ILCD, GLAM, ecological-scarcity and AWARE implementations

**Inherited claim:** Keep their accepted provider/version/category/quantity and regional metadata. Migrate each independently; absence from the first profile is not retirement.

**Source comparison — partial:** The named method families have heterogeneous historical provenance. The register does not establish a single set of scientifically accepted provider versions and policies, and AWARE is not evidenced by the preserved Workbench extraction code.

At 4bec1691, IPCC and ILCD are extracted from existing Brightway methods, while GLAM has a named beta release. Ecological-scarcity extraction tries two 2021 names and then a 2013 fallback, returns only code-to-value factors and can merge land factors inferred from published product totals. The preserved UBP note contains a later update correcting its earlier conclusion and reporting 13 added land factors. Nine IPCC additions are separately retained as historical local rules. The water note refers the AWARE convention to the water tributary rather than declaring it settled.

**Evidence still needed:** Create one reviewed provider record per family/version, carrying actual selected method tuple, source-file identity, factor/flow units, regional policy and declared local modifications. Recover the original IPCC/ILCD import sources and the UBP supplement derivation, including the later correction; distinguish an original provider factor from an inferred supplement. Obtain the AWARE owner/version/application evidence from its own project. Missing from the candidate profile must remain unsupported, and should not be described as retirement or a zero method.

Sources: [export-producer](/curation/evidence/export-producer?line=414&end=527), [export-producer](/curation/evidence/export-producer?line=1044&end=1046), [historical-ipcc-additions](/curation/evidence/historical-ipcc-additions?line=14&end=30), [workbench-inputs](/curation/evidence/workbench-inputs?line=98&end=125), [policy-ubp-validation](/curation/evidence/policy-ubp-validation), [water-method-note](/curation/evidence/water-method-note), [current-consensus-method-projection](/curation/evidence/current-consensus-method-projection?line=31&end=41).

## policy-13: Method registration and served-code checks

**Inherited claim:** Reuse existing project-local key resolution and differential acceptance. Validate registered factors and served inventories separately from source output.

**Source comparison — partial:** Existing code supports project-local key resolution and a separate differential-gate policy. Neither establishes full numerical or served-inventory validation for this migration.

At 4bec1691, the registrar resolves native codes to project IDs, refuses empty/all-zero resolved sets and reads a written method back through assert_registrable. That gate checks key reachability and requested database presence; it is not numerical equality or complete inventory coverage. The differential ADR explicitly allows an already-poor baseline and judges transitions. The candidate projection documentation independently lists actual provider receiving, numerical comparison, registration and served-graph validation as outstanding.

**Evidence still needed:** Retain separate receipts for source factors, registered keys/values and the actual served inventory generation. Compare every intended factor and any sibling factors introduced by registration, not just counts or nonempty resolution. Record the baseline and standing findings for differential acceptance. A passing structural registration or non-regression gate must not be promoted to scientific correctness, current consumer adoption or complete coverage.

Sources: [method-registration](/curation/evidence/method-registration?line=113&end=165), [method-registration](/curation/evidence/method-registration?line=180&end=238), [policy-method-gate](/curation/evidence/policy-method-gate?line=65&end=127), [policy-differential-gate](/curation/evidence/policy-differential-gate), [current-consensus-method-projection](/curation/evidence/current-consensus-method-projection?line=69&end=88).

## Review limits

This review inspected source content and previously preserved method evidence. The original JRC workbook corroboration remains bounded by its receipt: numerical row correspondence, no independent confirmation of source-flow quantity or scientific appropriateness. Workbench comments about benchmark results, literature, validation or acceptance remain attributed historical claims unless separate evidence is linked.

The UBP method note is especially important to retain whole: its later update corrects the earlier assertion that the land gap should not be filled using product totals. The review records that chronology without making the older prose disappear or accepting the inferred factors as independently published provider data. The candidate profile and projection code are contracts; they do not authenticate real provider inputs merely by accepting their schema.

No new external scientific literature was researched. The shared literature workflow and canonical library were checked in the preceding source audit; original physical-policy evidence still needs targeted recovery under that workflow.

## Source pins

| Document | SHA-256 |
|---|---|
| [bafu-climate-extensions](/curation/evidence/bafu-climate-extensions) | `3ccb4d7a45ce1b45a593545c421e1d507a31f4830009fba9f263e959f2f37581` |
| [bio3-climate-extensions](/curation/evidence/bio3-climate-extensions) | `cb7b7942ca01173b5b83594f137c9df652a12c628857401a26bfd0921fc2c496` |
| [bio3-producer](/curation/evidence/bio3-producer) | `8f0560b8fcebae4be7d134d9df5a77c5be8c0ee78be9b8310b16f25255e57937` |
| [current-consensus-method-projection](/curation/evidence/current-consensus-method-projection) | `8f2c49ddd8f7b59e5772c9d86a8ccb104d74bab23bd2ac8712e2630a96213507` |
| [current-consensus-quantity-application](/curation/evidence/current-consensus-quantity-application) | `3174c4ceddfcbf10eaa512a9bcb72d26b35aafb7de705dd7dd893f1b3cede4d1` |
| [ef31-producer](/curation/evidence/ef31-producer) | `4028da655cd3f2df6aae20ac7fd48cbb984f4de853ad8c3e0ca3ba6a86585649` |
| [export-producer](/curation/evidence/export-producer) | `bf4a191760fc56bd0b2367f12c8da15ec1440d790eabba633e86f57b013938ff` |
| [glam-producer](/curation/evidence/glam-producer) | `e79583dc7c76d37d19cb7d35c2b68e8e8e3f04808234b4537ae1886cbe6fce51` |
| [glam-water-applications](/curation/evidence/glam-water-applications) | `a595f6b347966a505e93f48213358546669fc3959ce7e6d0ae6295335e59f99b` |
| [historical-ipcc-additions](/curation/evidence/historical-ipcc-additions) | `9ea30ff7d690bdccff94a7bc8c6bb462733a6ab9e237be5a023e971a6bb4a7c1` |
| [jrc-factor-source-check](/curation/evidence/jrc-factor-source-check) | `77f18c1535e7de3d3ddf80ed80b67428c95c3581125431556222bc89542e4c29` |
| [method-registration](/curation/evidence/method-registration) | `d3ca323fd660fb3d74dd8ff2b8d9080c94965abeb7db5e3112ec9e276922f518` |
| [module-source-f6274f266738a9c2](/curation/evidence/module-source-f6274f266738a9c2) | `94535b0224f2d23e11daf4ec18771a7b76b53cfdcb8c66610088fd8f40fb47d5` |
| [overlay-producer](/curation/evidence/overlay-producer) | `145afb3d2901945236d06c0860ad1ed5ba0096aad7ea16a9e1d3455c276dffed` |
| [policy-differential-gate](/curation/evidence/policy-differential-gate) | `f763b03de49f7eeeb5d8ac29f3268e283de7b93001e77c0e3e7f14c4e01d5e04` |
| [policy-method-gate](/curation/evidence/policy-method-gate) | `439c99fc4c137be08545c1bbdf374d7ec65ffcf9e1eeb155158710016d2d8dbb` |
| [policy-ubp-validation](/curation/evidence/policy-ubp-validation) | `b440e6eb3ff2e03ec2ede41de6bb74dc11149f6a25e64315ad805a9649c053b9` |
| [water-method-note](/curation/evidence/water-method-note) | `5d8b87685123d245d5c97a9e0a18e47fefda65f34d57779a1e713c0f04952a6e` |
| [workbench-inputs](/curation/evidence/workbench-inputs) | `09b14d40708e887c2a11857b11b2a2ee450cbb1eaea1bd77520b4a6c86a16b19` |
