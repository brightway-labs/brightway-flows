# Source capture and description comparison, 13 October 2026

The inherited requirement that a missing factor must stay absent is stricter
than the historical registrar, which copies factors to siblings. The review
keeps the requirement and documents that behaviour beside it, rather than
presenting the intended migration contract as an established property of the
old code. This page records what the local evidence bundle could show about its
own sources on 13 October 2026, and which of its inherited descriptions had been
compared with those sources by the end of the day.

Two audits ran on the same bundle that day, and their counts differ because the
second added sources. Each count below says which run it comes from.

| Count | Earlier run (`provenance-enrichment-review.json`) | Later run (`claim-review-validation.json`) |
|---|---:|---:|
| Records in the bundle | 5,488 in 53 packages | 5,488 in 53 packages |
| Preserved source documents | 91 | 105 |
| Documents matching their declared pinned Git object | 75 | 84 |
| Documents keeping a stated origin-verification limit | 16 (by subtraction) | 21 |
| Records reconciled with a source record, mechanism or scoped comparison | 5,431 | 5,475 |
| Inherited descriptions with no source comparison yet | 44 | 0 |
| Records that index documentation rather than a source | 13 | 13 |

The later run is the one to read. The 14 documents it added are the receipts of
the description comparison itself — `remaining-claim-review.json` for 31
descriptions and `policy-claim-review.json` for the 13 method policies — and
the comparison is what moved the 44 unassessed descriptions to zero: five are
supported within the precise record or implementation scope their comparison
states, and 39 are partially supported. None receives scientific approval, and
the original summaries and evidence remain preserved. All 5,479 original entries
and their fields are unchanged from the register the audit started from; the
nine further records are the historical IPCC rules recovered from the pinned
source, which [Primary basis of the historical BAFU IPCC
additions](historical-ipcc-primary-basis-2026-10-14.md) reads.

Source-record capture establishes where a value came from, not that it is
scientifically right. Every one of the 105 source hashes matches its retained
bytes. A document that matches a pinned Git object is one whose text can be
shown to be the committed text; the 21 that keep a stated limit are provider
files and web captures for which no such object exists.

## Independent checks that ran with the audit

- The independent workbook check matched all 292 recorded factor amendments to
  selected rows in the pinned JRC workbook, as [Source evidence audit, 13
  October 2026](source-evidence-audit-2026-10-13.md) describes.
- The external provider CSV was retrieved from its pinned public revision and
  matched byte for byte.
- Three selected external assertions carry differing source and target units
  (`m2` against `m2*a`) and appear in the conflicting-evidence filter.
- Recovered evidence includes the ledger-digest-matched lookup reproduction
  and native-comparison receipts, the pinned upstream quantity decisions and
  factor rulings, and every occurrence of each legacy evidence tag. The
  numerical summaries keep their original scope: 2,679 lookup requests with
  2,678 known quantity factors and one unknown; 293,747 declared observations
  with 21 unlinked and 83,869 historical aliases. The native receipt says that
  actual body coverage has not been recomputed, and its overlapping review
  flags are not confirmed defects. Code-occurrence counts are distinct from
  execution counts.

Scientific identity, quantity applicability, policy acceptance and current
application remain open wherever the evidence is absent.

## What the application shows and refuses

Navigation counts and source statistics are calculated from the selected
register and the cited source records; historical totals keep their run and
counting basis. For each compared record the interface shows the exact claim,
the conclusion, the supporting source scope and the remaining work, behind a
description-support filter. A comparison cannot create scientific sign-off or
clear an independent source conflict. The importer rejects missing citations,
changed summary digests, changed source hashes, unresolved anchors and
duplicate claim records, and a changed register, source, membership or procedure
invalidates the audit instead of displaying an old success.
