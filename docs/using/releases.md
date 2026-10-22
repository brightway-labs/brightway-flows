# What changed in each release

This page is for someone who loaded one release and wants to know why rows
moved in the next. Each release lists what changed and why.

To apply the changes to a database, use the migration files published with
each release; see
[Which output do I need?](outputs.md#releasesmigrationsfrom__to-moving-a-database-from-one-release-to-the-next).
They list every identifier that changed. This page says why, grouped by what
you would notice.

## 1.1.0 — 2026-10-21

Published on [Zenodo](https://doi.org/10.5281/zenodo.23554066).

Built from the same five lists as 1.0.0: ecoinvent 3.12, ecoinvent 3.8,
BAFU 2026 v1, Stepwise 2006 1.09 and AGRIBALYSE 3.2. A count below comes from
the full build its pull request was measured on. That pull request names the
build.

1.0.0 was built on 2026-09-20 from commit `50543d9`, with uncommitted changes.
That commit is no longer in the repository, so the changes made between that
build and 22 September 2026 are not itemised here. The migration from 1.0.0
covers them along with everything else.

### The migration from 1.0.0

`1.0.0__1.1.0.zip` moves a database that loaded 1.0.0 to 1.1.0. On the trial
build of 1.1.0 (commit `15d733d`, run `20261021T2030219167640000`) it holds:

| | Created | Updated | Replaced | Deleted | Left for a person |
|---|---:|---:|---:|---:|---:|
| Substances | 2 | 143 | 3 | 0 | 0 |
| Flows | 31 | 1,729 | 22 | 0 | 0 |
| Impact categories | 0 | 44 | 0 | 0 | 0 |
| Factors | 139 | 345,997 | 0 | 0 | 0 |

Each replaced substance or flow is also listed under `delete` in its file, so
that it leaves your list of flows. It is counted once here, as replaced. The
44 updated categories and 345,997 updated factors are the renaming described
in the next section. Once the migration is applied, a database
holds 1.1.0's 8,159 substances, 97,827 flows, 138 impact categories and
727,074 factors, and every one of 1.0.0's 97,818 flows in an inventory points
at a flow 1.1.0 publishes. That was checked by applying the files to 1.0.0
with randonneur and comparing the result with 1.1.0, table by table. Nothing
is left unresolved.

### If you hold 1.0.0

- **Our own impact categories have new identifiers.** 1.0.0 published our
  implementations of EF 3.1 and Stepwise 2006 under the name
  `consensus-flow-list`. They are now published as `brightway-flows`. A
  category's identifier is made from a name that includes that word, so all 44
  categories changed identifier. The migration renames each category and moves
  its factors with it, all 345,997 of them. It does not delete them and
  recreate them
  ([#410](https://github.com/brightway-labs/brightway-flows/pull/410)).
- **The files now say which build made them.** In
  `harmonised-flows-simple.json.gz` it is `owl:versionInfo`, and in
  `lcia-factors.json.gz` it is `stats`. Each names the build run and the
  commit ([#414](https://github.com/brightway-labs/brightway-flows/pull/414)).
  1.0.0's files name neither.
- **The release carries its own record.** Besides the usual files, the
  [Zenodo record](https://doi.org/10.5281/zenodo.23554066) holds this
  release's snapshot, `release-snapshot.json.gz`, and `1.0.0__1.1.0.zip`, the
  migration from 1.0.0 to 1.1.0.

### Substances and their names

- **Ions are spelled one way.** `Lead II` and `Lead(II)` are now
  `Lead(2+)`, `Chloride` is `Chloride(1-)`, `Copper, Ion` is `Copper, ion` and
  `Cesium(1+)` is `Caesium(1+)`. All 51 ion substances follow one standard,
  and 14 of them changed label. Every other spelling stays as a synonym on the
  substances and on all 727 of their flows, so a search for `Lead II` still finds
  lead(2+) ([#402](https://github.com/brightway-labs/brightway-flows/pull/402)).
- **Rhenium(2+) no longer carries rhenium's numbers.** EF 3.1's 13
  `rhenium(2+)` emission flows shipped the metal's CAS number, 7440-15-5, and
  its EC number. Both have been removed. Four ions are now typed as cations
  rather than as imprecise mixtures: rhenium(2+), palladium(2+), rhodium(3+)
  and chromium(4+). Rhenium and rhenium(2+) have new substance identifiers.
  Their flows and factors are unchanged
  ([#406](https://github.com/brightway-labs/brightway-flows/pull/406)).
- **Fenpropimorph is one substance.** EF 3.1 published it twice:
  - 13 flows under 67564-91-4, 11 of them characterised;
  - 12 flows named `fenpropimorph` under the older number 67306-03-0, none of
    them characterised.

  BAFU's one fenpropimorph row and AGRIBALYSE's five carry the older number,
  so all six reached flows with no factors. The two substances are now one,
  under 67564-91-4, and those six rows reach characterised flows. The 12 flows
  that had no factors are deprecated onto their characterised twins.
  67306-03-0 is no longer published, so look the substance up by 67564-91-4
  ([#424](https://github.com/brightway-labs/brightway-flows/pull/424)).
- **2,3,4,5-tetrachlorobenzoyl chloride keeps the space in its name.** Its
  IUPAC name used to depend on the order in which one build happened to read
  two spellings. 1.0.0 published `…benzoylchloride`, without the space
  ([#419](https://github.com/brightway-labs/brightway-flows/pull/419)).

### Where a source row lands

- **ecoinvent 3.8's bare metals are the element.** ecoinvent 3.8 ships
  `Lead` to urban air under 7439-92-1. From 3.9.1, the same identifier is
  `Lead II`. 1.0.0 followed the identifier and published 3.8's row on
  lead(2+). Now each of 299 such rows reaches the element its CAS number names:
  lead, copper, molybdenum and others.
  - 41 of these rows now reach a characterised flow where before they reached
    an uncharacterised one.
  - 28 new flows appear, none of them characterised.
  - 6 ion flows at aircraft cruise height are gone; only these rows reached
    them.

  The full table is on [the ecoinvent 3.8 page](../changes/ecoinvent-3.8.md)
  ([#400](https://github.com/brightway-labs/brightway-flows/pull/400)).
- **AGRIBALYSE's generic arsenic ion is generic.** All 13 of its
  `Arsenic, ion` rows shipped pentavalent arsenic's number, 17428-41-0, so they
  reached arsenic(5+). They now reach `Arsenic, ion`, where ecoinvent's and
  BAFU's rows already were. Its four `Arsenic (V)` rows stay on arsenic(5+)
  ([#422](https://github.com/brightway-labs/brightway-flows/pull/422)).
- **AGRIBALYSE's coal-mine off-gas is no longer natural gas.** Its three
  `Gas, mine, off-gas, process, coal mining` rows carried natural gas's
  number, 8006-14-2, so they reached `Natural Gas`. They now reach the
  coal-mine off-gas flow
  ([#409](https://github.com/brightway-labs/brightway-flows/pull/409)).

### Units

- **AGRIBALYSE's 26 rows in another unit are converted.** Each of these rows
  reaches a flow published in a different unit, and none of them carried a
  conversion. For example, 16.7 million m³ of natural gas was published as
  16.7 million MJ, about 35 times too little. These rows are now converted as
  follows ([#409](https://github.com/brightway-labs/brightway-flows/pull/409)):
  - fuels at AGRIBALYSE's own heating values: natural gas at 34.5 MJ/m³, hard
    coal at 18.2 MJ/kg;
  - uranium at 560,000 MJ/kg;
  - radionuclides given by mass, at their specific activity;
  - water given by mass, at 0.001 m³/kg.

  Two stable isotopes are accepted with no number.
- **BAFU rows on a flow in another unit carry the factor.** BAFU often ships a
  row in becquerels that reaches a flow published in kilobecquerels. Such rows
  now carry the factor from the unit table, 0.001 in that case, and say where
  it came from:
  - 162 rows that reach an existing flow
    ([#399](https://github.com/brightway-labs/brightway-flows/pull/399));
  - 56 rows whose flow they themselves created
    ([#416](https://github.com/brightway-labs/brightway-flows/pull/416)).
- **The unit-mismatch flag means one thing.** In `consensus-flows.sqlite3`,
  `has_unit_mismatch` used to stay set on a matched row even when a curated
  factor said by how much its unit differs, such as 9.41 MJ per kilogram. It
  is now cleared there, as it already was on a row that created its flow
  ([#420](https://github.com/brightway-labs/brightway-flows/pull/420)).

### Looking up a flow

These change the answers flow lookup gives. They do not change the published
list.

- **A conversion is reported in full.** If you send a BAFU row in becquerels,
  the lookup returns the target in kilobecquerels together with the 0.001 that
  converts it. It shows each step: your unit to the unit the list shipped, then
  any multiplier the list recorded, then the target's unit. A conversion nobody
  recorded comes back empty, never as 1.0
  ([#387](https://github.com/brightway-labs/brightway-flows/pull/387)).
- **BAFU's `resources / unspecified` names no medium.** BAFU's
  `Carbon dioxide, in air` row is filed under `resources / unspecified`. A
  query for it that named BAFU was read as a resource in the ground, and so it
  found nothing. That compartment is now read as a resource with no medium.
  The eight rows the old reading was right about are ruled one by one
  ([#390](https://github.com/brightway-labs/brightway-flows/pull/390)).
- **A row is found under the name the vendor shipped.** BAFU's `t-Butylamine`
  sent without its CAS number used to find nothing, because the build had
  recorded it under the enriched name `tert-Butylamine`. Recorded decisions
  are now found under both names
  ([#423](https://github.com/brightway-labs/brightway-flows/pull/423)).

### Not visible in the published files

These changes are to how builds are checked, not to anything a build publishes:
- the recorded expectations and their baseline
  ([#391](https://github.com/brightway-labs/brightway-flows/pull/391),
  [#392](https://github.com/brightway-labs/brightway-flows/pull/392),
  [#397](https://github.com/brightway-labs/brightway-flows/pull/397));
- a test of a pinned category identifier
  ([#405](https://github.com/brightway-labs/brightway-flows/pull/405));
- the source table in [What was changed in each source](../changes/index.md)
  ([#411](https://github.com/brightway-labs/brightway-flows/pull/411));
- the tool that compares two builds, which now shows a change to a published
  conversion factor
  ([#421](https://github.com/brightway-labs/brightway-flows/pull/421)).

## 1.0.0 — 2026-09-20

The first release, published on
[Zenodo](https://doi.org/10.5281/zenodo.22857950). It merged ecoinvent 3.12,
ecoinvent 3.8, BAFU 2026 v1, Stepwise 2006 1.09 and AGRIBALYSE 3.2 onto
EF 3.1. It holds:

- 97,818 live flows;
- 2,676 redirects;
- 726,935 factors.

It cannot be rebuilt from source. Its snapshot was recorded from the database
published with it; see
[Running a transform](../operating/running.md#recording-a-release-and-writing-the-migration-to-the-next-one).
