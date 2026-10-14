# TiO₂ to titanium: quantity application trace

The inspected current EF mineral path applies **0.599 zero times** for the two
TiO₂ flows. Original quantities remain TiO₂ mass; the registered and processed
factors retain the bare titanium value. This is a mismatch with the pinned
upstream oxide-to-element correspondence. Whether that correspondence is the
accepted scientific interpretation of the original supplier quantity remains
a separate review question. No quantity or factor was changed.

The [four scoped checks](/curation/evidence/quantity-application-checks) are
attached to the [mineral policy](/curation/cases/policy-09) and both individual
factor cases:
[ilmenite](/curation/cases/wb-factor-af8bc1926a017bd6) and
[rutile](/curation/cases/wb-factor-cacf7c5e1102cf6c).

## What the actual path contains

| Step | Observed behavior | Receiving evidence |
| --- | --- | --- |
| Original source and import | Two real observations from BAFU dataset 214934 remain TiO₂ in kg; eight stored flows preserve their original amounts. | [Catalog trace](/curation/evidence/titanium-catalog-quantity-trace) |
| Historical correspondence extract | Retains the target titanium identity but omits conversion and match-relation fields. | [Pinned derivative](/curation/evidence/original-evidence-historical-quantity-extract) |
| Historical EF overlay | Replaying the actual two targets and JRC row writes 2.79e-08 on each native TiO₂ code without multiplying by 0.599. | [Workbench trace](/curation/evidence/titanium-workbench-quantity-trace), [overlay source](/curation/evidence/titanium-code-ef31-consensus-overlay) |
| Current registration | EDB_BAFU and bafu_2026 both register 2.79e-08 in the mineral half and union methods. bafu_fresh has no inspected method under this family, so it supplies no factor verdict. | [Registered readback](/curation/evidence/titanium-workbench-quantity-trace) |
| Processed inventory and method arrays | Six selected inventory coefficients retain source amounts after exact float32 casting. The processed factors equal float32 casts of the unscaled registered values. | [Processed vectors](/curation/evidence/titanium-processed-quantity-trace) |
| Direct characterisation | The installed LCIA multiplication method, isolated from project opening and supply-chain solving, multiplies these real coefficients by the unscaled factors. All twelve once-only checks fail. | [Calculation trace](/curation/evidence/titanium-processed-quantity-trace), [procedure](/curation/evidence/titanium-processed-procedure) |

The registered-factor check alone could have missed stale processed arrays.
Reading both shows the same scale. The small differences between SQLite/pickle
values and processed values are exactly explained by their float32 data types;
they do not resemble a 0.599 conversion.

Conditional on the upstream quantity interpretation, the required composition
is:

`native amount × 1 × 0.599 × 2.79e-08`.

The corresponding factor per original source kg would be `1.67121e-08`.
That number is conditional arithmetic, not an adopted factor or a full product
impact. Neither inventory amounts nor existing CFs were rewritten.

## What the new consensus routine establishes

The completed comparison for
`catalog-source-binding-physical-unit-pilot-20261013-v3-attempt3` contains 223
actual observations for these two published source rows. Their public point decisions all give
native-to-source factor 1. Their exact upstream correspondences retain 0.599.
The existing projector's quantity-composition helper returns 0.599 for every
one of those 223 rows. It applies the source multiplier once in this mechanism;
it does not rewrite inventory quantities.
[Real-row replay](/curation/evidence/titanium-workbench-quantity-trace),
[projector source](/curation/evidence/titanium-code-consensus-methods).

This probe deliberately supplied no invented mineral selection or scientific
policy. The inspected saved climate profile does not contain resource_minerals,
and the helper holds all 223 rows without a native factor. It is a bounded
quantity-helper replay, not a complete accepted mineral projection or proof
of consumer adoption. The trace does not assert that no other mineral profile
exists elsewhere.

## What remains to resolve

- Establish the original supplier quantity convention and scientifically accept
  the two broad TiO₂-to-titanium correspondences for the intended method.
  The original XML identifies TiO₂ and kg but carries no explicit quantity-basis
  explanation. Its source reference is a locator, not a checked scientific
  derivation.
- Receive an actual mineral profile with exact provider row, target context,
  target quantity basis, relation policy and source-generation selections.
- Carry the evidenced multiplier through the quantity-aware application. Keep
  inventory quantities unchanged when scaling the native CF, then verify the
  factor and contribution at the actual consumer. Reuse the upstream conversion
  instead of introducing another local TiO₂ matching or conversion rule.
- Qualify other mineral/ore/compound flows separately. This trace does not settle
  the general leading-element treatment or every occurrence in an inventory.
- Recover original registration execution lineage where needed. Current file
  and store readback establishes observed behavior; it does not prove which
  historical script invocation populated every project copy.

The [catalog report](titanium-catalog-quantity-trace-2026-10-13.md) records exact
source coordinates, importer generations and private local custody. The
Workbench trace identifies code revision
`03fd243f76aa886f971148efc217dc5c61ddf6c6`; the historical adoption report carries
run `20260922T2037421996740000`. These are distinct generations. Current
processed packages and metadata were byte-stable during receiving. No
immutable whole-store identity, supply-chain calculation, stochastic acceptance
or release qualification is claimed.

All original Curation cases and their earlier evidence comparisons remain
preserved. The mineral policy remains partially supported overall, with this
application failure recorded explicitly beside the narrower passed checks.

## Verification

The actual local register retains all 5,488 original cases and 53 review
packages. Four scoped execution checks are attached to the policy and the two
individual factor cases, with two passed components, one failed current
application check and one blocked mineral application. The earlier description
comparisons remain preserved; 36 descriptions remain partial overall.

The three updated case pages, both titanium reports and 15 evidence routes
were checked through the application. The selected suite passed 219 tests and
1,755 subtests; the three triage-state tests, required lint checks and whitespace
checks also passed. Browser visual automation remains unavailable under its
URL policy; no new visual inspection is claimed. The preview is available on
port 5188. The local `titanium-quantity-trace/validation.json` binds the current
register, aggregate audit and quantity-check receipt digests.
