# Titanium: catalog quantity trace

Recorded 2026-10-13. Read-only source comparison by a coding agent; no scientific sign-off.

For the two TiO2 cases, the inspected importer stages and native project exchanges preserve the original XML mass. The unit label changes from `kg` to `kilogram`; there is no observed `0.599` multiplication in those quantities. This resolves the import-side double-conversion question for the selected observations. It does not establish that a downstream characterization method applies the correspondence correctly. [Trace receipt](/curation/evidence/titanium-catalog-quantity-trace)

| Curation case | Published BAFU UUID | Native `bafu_biosphere` code |
| --- | --- | --- |
| `wb-factor-af8bc1926a017bd6` — ilmenite | `52b760ca-3444-564a-a215-271d4af41250` | `e33e1426905cc904d15d53d9bcc25730` |
| `wb-factor-cacf7c5e1102cf6c` — rutile | `73746710-2506-50d1-811a-521b48526172` | `11528e8656d6e49cba72d1501a237a31` |

## Original source to native identity

The original XML for activity `214934`, `process_68bb95fd-1526-388c-a01a-50b8d99534b1.xml`, contains both flows. Its SHA-256 is `e1f27b4326b81c70431c9d619c208292ae514835a483572e3356e63a12d2bbba`. Both exchanges declare `kg` and the TiO2 name and CAS number. Their zero-based exchange ordinals, `1194` and `713`, agree with the saved pilot source observations. The private excerpt preserves their exact attributes and amounts; those amounts are deliberately absent from this tracked report. [Original XML evidence](/curation/evidence/titanium-catalog-source-xml)

The original BAFU:2025 SimaPro CSV, which the catalog release uses for its native flow definitions, contains the two names under `Raw materials`, with `kg` as unit. The importer's `md5(name + "|" + source section)` formula reproduces both native codes exactly. The complete CSV hash agrees with the release pin, `9b48bf6310fab6eff2a75bbeaaba92c5ce7cca01efb84964ef585e4d4aebaeab`. This verifies the inspected definitions and deterministic code derivation; it does not independently validate their chemistry. [CSV evidence](/curation/evidence/titanium-catalog-source-csv)

## Saved execution and stored quantities

The actual `physical-v3-attempt3` pilot captures identify importer commit `1451690d6f634fef191be8c167159df1e8c3da3a`. Its source export connects the original XML coordinates to the requested published URIs and native flow codes. The selected observation IDs are `08b9a98dec4c1218d42a8b88b484b54adc70753c014ceb2b1cd59a97d48f091f` and `d2a9725150c99a78d25870199910139e7323ff891dbeba18c18c487f6d929f54`. The complete source-observations and native-metadata export files match their manifest hashes. Both parsed and post-link captures retain the original amount; neither observation is in the physical unit conversion ledger. [Saved pilot captures](/curation/evidence/titanium-catalog-pilot-captures)

Eight stored exchanges were checked: two in the `bafu_2026` project's `bafu_2026` database; four across `EDB_BAFU`'s separate `bafu_2026` and `bafu` databases; and two in the pilot's database. Every selected stored amount equals its original XML amount after float parsing, with a ratio of `1`. The stored flow definitions remain TiO2 in `kg`. Each store was queried through SQLite `mode=ro`, `query_only=ON`, in a read transaction. Selected row hashes, database metadata and file identities are recorded; file identities and SQLite data versions were unchanged during the reads. No whole-store hash or immutable historical snapshot is claimed. [Stored observations](/curation/evidence/titanium-catalog-stored-observations)

## Code corroboration and limits

Canonical catalog code at `3a40a91957ddb2427c6d1e3b3c111244aee2f6f6` reads the selected uncertainty-zero XML `meanValue` directly into `amount`. A bounded execution of the independent parser reproduces the original amounts. The native mapper retains the TiO2 name, collapses resource categories and leaves amount unchanged. The inspected `bw2io` normalizer changes unit spelling only; its isolated pure function preserves both amounts. The importer's native-flow matching uses name and categories. The TiO2 aliases elsewhere in `create_ubp_2021` concern CF-name matching, not inventory conversion. Exact code hashes and the actual pilot's separate revision are preserved. [Code review and pure probes](/curation/evidence/titanium-catalog-code-review)

This is a trace of two real observations in one original activity, not a census of every occurrence. Current code is not asserted to be the exact historical code that populated the older project copies. The newer `EDB_BAFU/bafu` rows and the older `EDB_BAFU/bafu_2026` rows are reported separately. No imports, inventory edits, method registrations or LCA calculations were performed. Method projection, whether `0.599` is scientifically appropriate, and independent acceptance of the two mappings remain separate review questions. [Scope and limitations](/curation/evidence/titanium-catalog-quantity-trace)
