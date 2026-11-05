# TiO₂ to titanium: where the 0.599 is applied, and where it is not

!!! note "This page is about a consumer of this list, not about this list"

    What follows traces the two BAFU titanium-dioxide rows through the
    **external Workbench path** — the EDB_BAFU, bafu_2026 and bafu_fresh
    Brightway projects and the Workbench's own EF 3.1 characterisation
    overlay — and finds that path applying the oxide-to-metal factor zero
    times. **This project is not that path.** Here the two rows `TiO2, 54% in
    ilmenite, 2.6% in crude ore` and `TiO2, 95% in rutile, 0.40% in crude ore`
    are sent to elemental titanium at 0.599 kg Ti per kg TiO₂ by
    `bafu-2026-v1-match-overrides.json`, and the mapping publishes that
    factor beside the row; see [what was changed in BAFU 2026
    v1](../changes/bafu-2026-v1.md#ore-grade-names). The
    finding below is that the Workbench's historical characterisation did not
    pick that factor up — a processing defect on the consumer side, recorded
    here because the consumer's register holds the cases.

The inspected Workbench EF mineral path applies **0.599 zero times** for the two
TiO₂ flows. Original quantities remain TiO₂ mass; the registered and processed
factors retain the bare titanium value, 2.79e-08 per kilogram of titanium. That
is a mismatch with the upstream oxide-to-element correspondence this list
publishes. Whether 0.599 is the accepted scientific interpretation of the
original supplier quantity remains a separate review question. No quantity or
factor was changed by this trace.

The four scoped checks (evidence `quantity-application-checks`) are attached to
the mineral policy (case `policy-09`) and to both individual factor cases:
ilmenite (case `wb-factor-af8bc1926a017bd6`) and rutile (case
`wb-factor-cacf7c5e1102cf6c`).

## From the BAFU XML to the native flow

Recorded 2026-10-13, as a read-only source comparison by a coding agent.

| Curation case | Published BAFU UUID | Native `bafu_biosphere` code |
| --- | --- | --- |
| `wb-factor-af8bc1926a017bd6` — ilmenite | `52b760ca-3444-564a-a215-271d4af41250` | `e33e1426905cc904d15d53d9bcc25730` |
| `wb-factor-cacf7c5e1102cf6c` — rutile | `73746710-2506-50d1-811a-521b48526172` | `11528e8656d6e49cba72d1501a237a31` |

The original XML for BAFU activity `214934`
(`process_68bb95fd-1526-388c-a01a-50b8d99534b1.xml`) contains both flows. Both
exchanges declare `kg`, the TiO₂ name and CAS 13463-67-7, titanium dioxide's
number. Their zero-based exchange ordinals, 1194 and 713, agree with the saved
pilot source observations. The private excerpt preserves their exact attributes
and amounts; the amounts are deliberately absent from this tracked report
(evidence `titanium-catalog-source-xml`).

The original BAFU:2025 SimaPro CSV, which the catalog release uses for its
native flow definitions, lists the two names under `Raw materials` in `kg`. The
importer's `md5(name + "|" + source section)` formula reproduces both native
codes exactly, and the complete CSV hash agrees with the release pin. This
verifies the inspected definitions and the code derivation; it does not
independently validate their chemistry (evidence `titanium-catalog-source-csv`).

The saved `physical-v3-attempt3` pilot captures connect the original XML
coordinates to the requested published URIs and native flow codes. Both parsed
and post-link captures retain the original amount; neither observation is in
the physical-unit conversion ledger (evidence `titanium-catalog-pilot-captures`).

Eight stored exchanges were read: two in the `bafu_2026` project's `bafu_2026`
database, four across EDB_BAFU's separate `bafu_2026` and `bafu` databases, and
two in the pilot's database. Every stored amount equals its original XML amount
after float parsing, ratio 1. The stored flow definitions remain TiO₂ in `kg`.
Each store was read through SQLite `mode=ro`, `query_only=ON`, in a read
transaction, and file identities and data versions were unchanged during the
reads (evidence `titanium-catalog-stored-observations`).

The catalog code at its pinned revision reads the uncertainty-zero XML
`meanValue` directly into `amount`; a bounded execution of the independent
parser reproduces the original amounts. The native mapper keeps the TiO₂ name,
collapses resource categories and leaves the amount unchanged; the `bw2io`
normaliser changes the unit spelling from `kg` to `kilogram` and nothing else.
The TiO₂ aliases elsewhere in `create_ubp_2021` concern CF-name matching, not
inventory conversion (evidence `titanium-catalog-code-review`).

So on the import side there is **no 0.599 multiplication in the quantities**.
That settles the double-conversion question for the selected observations: the
inventory amount is TiO₂ mass, once. It does not establish that a downstream
characterisation method applies the correspondence.

## From the native flow to a characterised result

| Step | Observed behaviour | Evidence |
| --- | --- | --- |
| Original source and import | Two real observations from BAFU dataset 214934 remain TiO₂ in kg; eight stored flows preserve their original amounts. | `titanium-catalog-quantity-trace` |
| Historical correspondence extract | Retains the target titanium identity but omits the conversion and match-relation fields this list publishes. | `original-evidence-historical-quantity-extract` |
| Historical EF overlay | Replaying the two targets and the JRC row writes 2.79e-08 on each native TiO₂ code without multiplying by 0.599. | `titanium-workbench-quantity-trace`, `titanium-code-ef31-consensus-overlay` |
| Current registration | EDB_BAFU and bafu_2026 both register 2.79e-08 in the mineral half and union methods. bafu_fresh has no inspected method under this family, so it supplies no verdict. | `titanium-workbench-quantity-trace` |
| Processed inventory and method arrays | Six selected inventory coefficients retain source amounts after exact float32 casting. The processed factors equal float32 casts of the unscaled registered values. | `titanium-processed-quantity-trace` |
| Direct characterisation | The installed LCIA multiplication, isolated from project opening and supply-chain solving, multiplies these coefficients by the unscaled factors. All twelve once-only checks fail. | `titanium-processed-quantity-trace`, `titanium-processed-procedure` |

The registered-factor check alone could have missed stale processed arrays.
Reading both shows the same scale, and the small differences between SQLite or
pickle values and processed values are exactly explained by their float32 data
types; they do not resemble a 0.599 conversion.

Conditional on the upstream quantity interpretation, the required composition
is `native amount × 1 × 0.599 × 2.79e-08`, which would put the factor per
original source kilogram at `1.67121e-08`. That is conditional arithmetic, not
an adopted factor or a product impact. Neither inventory amounts nor existing
CFs were rewritten.

## What the newer consensus routine does with the same rows

The completed comparison for
`catalog-source-binding-physical-unit-pilot-20261013-v3-attempt3` contains 223
actual observations for these two published source rows. Their public point
decisions all give native-to-source factor 1; their exact upstream
correspondences retain 0.599. The projector's quantity-composition helper
returns 0.599 for every one of the 223 rows — it applies the source multiplier
once, on the factor, and does not rewrite inventory quantities (evidence
`titanium-workbench-quantity-trace`, `titanium-code-consensus-methods`).

This probe supplied no invented mineral selection or scientific policy. The
inspected saved climate profile does not contain `resource_minerals`, and the
helper holds all 223 rows without a native factor. It is a bounded replay of the
quantity helper, not a complete accepted mineral projection or proof of
consumer adoption, and it does not assert that no other mineral profile exists
elsewhere.

## What remains to resolve

- Establish the original supplier quantity convention and scientifically accept
  the two broad TiO₂-to-titanium correspondences for the intended method. The
  original XML identifies TiO₂ and kg but carries no quantity-basis explanation;
  its source reference is a locator, not a checked derivation.
- Receive an actual mineral profile with exact provider row, target context,
  target quantity basis, relation policy and source-generation selections.
- Carry the evidenced multiplier through the quantity-aware application: keep
  inventory quantities unchanged when scaling the native CF, then verify the
  factor and contribution at the actual consumer. Reuse the conversion this
  list publishes instead of introducing another local TiO₂ matching or
  conversion rule.
- Qualify other mineral, ore and compound flows separately. This trace does
  not settle the general leading-element treatment or every occurrence in an
  inventory.
- Recover original registration execution lineage where needed. Current file
  and store readback establishes observed behaviour; it does not prove which
  historical script invocation populated every project copy.

The Workbench trace identifies code revision `03fd243f`; the historical
adoption report carries run `20260922T2037421996740000`. These are distinct
generations. Current processed packages and metadata were byte-stable during
receiving. No whole-store identity, supply-chain calculation, stochastic
acceptance or release qualification is claimed. The mineral policy remains
partially supported overall, with this application failure recorded beside the
narrower passed checks; the local `titanium-quantity-trace/validation.json`
binds the register, aggregate audit and quantity-check receipt digests.
