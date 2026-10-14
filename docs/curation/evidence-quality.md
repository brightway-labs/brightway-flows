# Evidence quality and provenance

A recorded titanium factor matches JRC worksheet row 156706. That establishes
where its numerical value came from. Applying it to an ilmenite inventory still
requires evidence that the inventory amount represents the titanium quantity
expected by the method. The review record needs both facts.

Curation shows **source capture**, **scientific basis**, **reproduction** and
**scientific review** separately. A source record matched by the audit can still
have unresolved scientific questions. A historical report saying “fixed” is a
reported claim until its inputs and execution can be reproduced.

## Read an entry

The evidence section gives the derivation, exact source pointers, recovered
metadata, and specific missing evidence. Provider mapper and verifier, Git
change author and co-author, discovery author, and scientific reviewer are
different roles. A recorded agent co-author credit describes a code change;
it does not establish who created a provider mapping imported by that code.
Absent attribution remains unknown.

Source rows expose identifiers, units, compartments, method implementations,
locations and dates where those fields exist. Historical counts name the run
and counting basis. A classification total describes the original report,
including repeated rows; it does not turn one case into that many distinct
current defects. Recorded factor differences are arithmetic on historical
values and do not measure inventory impact.

Use **Evidence needed** to filter packages or cases by source trace, scope,
scientific basis, reproduction, attribution, review or conflicting evidence.
Module pages aggregate these needs over linked cases. The numbers count records
requiring evidence; they establish no priority or approval.

Use **Description support** to find claims that have been compared with their
sources. Each comparison quotes the exact description and gives the supported
scope, source passages and unresolved questions. A coding agent's comparison
can confirm what a pinned code or ruling record says; it is separate from
scientific review. A proposed migration requirement remains a requirement even
when the old implementation uses a fallback it would prohibit.

The comparison is bound to the exact description and cited source hashes.
Editing the claim or changing a source requires a new comparison; rerunning
the capture audit cannot silently reuse the old judgement. The
[method-policy review](policy-claim-review-2026-10-13.md) shows examples of
historical sibling-factor and default-region behavior that need this distinction.

When original evidence is recovered later, a dated update preserves the earlier
comparison and records what is now established and what remains open. Filters
use the current comparison. A superseded description is shown with its
correction at the top of the case; the original text remains available in the
history. Closing a metadata-receiving gap cannot clear quantity, dimensional
conflict or scientific-review gaps. The
[original evidence recovery](original-evidence-recovery-2026-10-13.md) shows
this for the mine-gas observations and complete native comparison.

Quantity application checks name their exact observations, methods and store
snapshots. A passed import or conversion-mechanism check cannot clear an
independent failed consumer check, supply scientific approval or advance a
case's lifecycle. Case identity, cited source hashes and check membership are
validated before display. The [titanium trace](titanium-quantity-application-2026-10-13.md)
shows a passed import trace and a failed once-only application check together.

## Make a contribution reviewable

For each claim, contribute the following evidence when applicable:

- The original source observation, exact flow definition and identifiers,
  source version, quantity, compartment and geography.
- An authoritative passage or method row supporting the correction, with a
  stable source link, locator and preserved digest. Explain assumptions,
  alternative interpretations and counterexamples.
- A reproducible command, code revision, input hashes and expected/observed
  outputs. A regression test should distinguish the intended correction from
  plausible alternatives rather than repeat a literal table entry.
- A named scientific reviewer, date, scope, verdict, exact revision and review
  link. Record release adoption and consumer application with their own receipts.

Cooling-water conventions require intake, return and evaporation evidence.
Calibrated heating values require calibration inputs and bounds. A name-only
external mapping requires review of the original units, context and substance
class before it becomes a general synonym.

## Reproduce the capture audit

The audit writes a sibling `provenance-audit.json` beside the chosen register:

```sh
uv run python tools/audit_curation_provenance.py \
  --register /path/to/register.json \
  --repository https://gitlab.com/eos-lci/lci-workbench=/path/to/workbench
```

It compares literals without executing source code, exact historical JSON rows,
provider CSV selections, source locators, preserved hashes and supplied Git
objects. External references it cannot verify remain explicitly unassessed.
The receipt is bound to the register, procedure and all preserved source bytes;
changing any of these invalidates the displayed result until the audit is rerun.

The separate JRC check preserves the exact workbook digest, worksheet row,
method UUID/name, source classes and selection policy. Its numerical comparison
does not validate identity, quantity, policy or scientific acceptance. The
[13 October source audit](source-evidence-audit-2026-10-13.md) records its scope
and concrete unresolved findings. No scientific build is executed by Curation.
