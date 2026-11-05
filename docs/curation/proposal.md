# Proposed Curation workspace

Status: proposed workflow for maintainer review.

## Purpose

An engineer importing BAFU radiation exchanges finds a quantity recorded in Bq
where the receiving flow uses kBq — the 159 pairs BAFU 2026 v1 ships twice,
recorded in [Units and the conditions of
measurement](../findings/units.md#the-rest-of-the-class-per-source-list) and in
[what was changed in BAFU 2026 v1](../changes/bafu-2026-v1.md). Matching the
flow's identity does not establish that its amount was converted. The engineer
needs the original unit evidence, the proposed conversion, the code that
applies it and a measured check of how often it runs. A reviewer must also see
which source and code revision the check actually covers, and what remains
unverified.

The response proposed here is a navigable path from what Checks and
contributors find to the proposals and the correction modules that answer it,
with evidence, authorship, dates, decision history, validation and
revision-specific sign-off visible together; the
[decision record](../adr/0001-connect-curation-evidence.md) states the
boundary with Checks.

## Included in this design

- Search, sortable table columns and grouping by record kind, stage, source or
  author. Filters compose into shareable URLs and work without JavaScript.
- Finding classes remain distinct from individual correction cases. A class
  is not automatically one actionable or approved correction.
- Proposals link to public GitHub issues, discussions or pull requests.
- Packages and cases show their implementations in context. The shared module
  reference includes every registered ruling and supporting input reader, transformer step and actual or
  proposed case link, plus recorded external code grouped by origin and path.
  Versions, roles and evidence remain distinct. Full files, source descriptions,
  code history and discoverable tests are available without executing corrections.
- Case detail retains withdrawn conclusions. Validation, scientific review
  and release adoption remain separate and name the relevant revision.
- Browser-local shortlists and notes organise personal review. Shared changes
  are proposed by editing the versioned register through a repository change.
- Selected real public cases demonstrate the interface. Missing attribution
  and sign-off stay visibly unknown. No approval is inferred from authorship,
  issue closure, passing tests or a module's presence in source.

The original inspected code baseline is
`19d6cc6268e59e18fcbb47bfec0f440fb0f6a353`; this contribution is prepared
against upstream `ad57820097aba07e8846c4234e5336ef088429f4`. The public example
register retains its historical lookup candidate at
`f77270f6bee3649fcf2ca3196455200022670b64` (PR #387). Later observations and
candidate revisions carry their own receipts in the consumer's register.

## Decisions for maintainers

1. Does **Curation** describe this surface clearly alongside Checks?
2. Are the distinction between finding classes and cases, and the proposed
   case fields, useful for ongoing work?
3. What constitutes scientific sign-off, and how should maintainers resolve
   differing reviews? This preview records evidence; it grants no authority.
4. Should GitHub events generate proposals for register updates, or should
   curation remain explicitly maintained through reviewed changes?

## Subsequent work

The separate local evidence bundle now contains individual historical rules,
factor amendments, observations and later integration changes, grouped into review
packages. Its own receipt reconciles the preserved inputs; those private records
are not included in this public example register. Further partner contributions
and unregistered processing passes need explicit inventory and review. Connect machine-readable check output
to stable case identifiers. Define qualifying build receipts and release
adoption evidence. Add reviewed register-update automation only after agreeing
on the authority and conflict rules. None of these gaps is represented as
completed by this preview.
