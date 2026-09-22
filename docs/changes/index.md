# What was changed in each source

Every list that goes into the Brightway flows list is taken as its publisher
shipped it, and then some of its rows are altered before, or while, they are
matched. Most of those alterations are housekeeping — a name is title-cased, a
unit symbol is spelled the standard way, a compartment is translated into the
shared vocabulary — and none of that is recorded here. These pages record the
changes that alter *what a row says*: the ones a reader who knows the source
list would want to check.

One page per input list, the five ecoinvent releases by version number. Which
of them the standard build merges, and in what order, is the Role column —
3.12 is merged before 3.8, and the three releases between them are curated but
not merged:

| Source | Role in the build | Page |
|---|---|---|
| EF 3.1 | The base list every other list is merged into | [EF 3.1](ef-3.1.md) |
| ecoinvent 3.8 | Merged second | [ecoinvent 3.8](ecoinvent-3.8.md) |
| ecoinvent 3.9.1 | Curated, and available to merge; not part of the standard build | [ecoinvent 3.9.1](ecoinvent-3.9.1.md) |
| ecoinvent 3.10.1 | Curated, and available to merge; not part of the standard build | [ecoinvent 3.10.1](ecoinvent-3.10.1.md) |
| ecoinvent 3.11 | Curated, and available to merge; not part of the standard build | [ecoinvent 3.11](ecoinvent-3.11.md) |
| ecoinvent 3.12 | Merged first | [ecoinvent 3.12](ecoinvent-3.12.md) |
| BAFU 2026 v1 | Merged third | [BAFU 2026 v1](bafu-2026-v1.md) |
| Stepwise 2006 | Merged last | [Stepwise 2006](stepwise-2006.md) |
| AGRIBALYSE 3.2 | Registered 2026-08-31; not yet in the documented build | [AGRIBALYSE 3.2](agribalyse-3.2.md) |

## The four kinds of change these pages show

**One name, two substances.** The source uses one name for rows that the
consensus list places on two different substances. Usually a registry number forces the split — EF 3.1 writes
`1,3-benzenediamine` on twenty-six rows, thirteen with the CAS number of the
free base and thirteen with the CAS number of its hydrochloride salt; ecoinvent
3.8 writes `Sodium` on eleven rows that its own later releases rename, eight
of them to the sodium *ion* and three left as the metal — and sometimes the
compartment does: `Water` released to air is water vapour, and
`Water` released to a river is not. The page says which rows went where, and
why.

**An ionic charge was added or corrected.** A dissolved metal is an ion, and
the source either named it as the bare element, wrote `, ion` without saying
which one, or wrote a charge that its own registry number contradicts. The
page lists the rows whose published name carries a charge the source's name
did not, and where the charge came from. Writing `Chromium VI` as
`Chromium(6+)` is a change of notation only, and is not listed.

**Rows merged into one flow.** Several rows of the source land on one
consensus flow — two spellings of a name, an ore-grade suffix on a resource,
a `[Deleted]` tombstone beside the live row, a place name on the end of a
BAFU flow — so a reader following one of them back to the source will find
more than one row there. The page groups them by substance and lists every
source row.

**A registry number was corrected.** The source ships a CAS or EC number that
names the wrong substance, or a wrong number in the sense that it belongs to
a mixture rather than its constituent, or no CAS number at all where the
substance has one; the correction is written down before anything reads the
row, with the reason. Normalising a CAS number's formatting — stripping leading
zeros, checking the check digit — is not a correction and is not listed.

## What is deliberately not on these pages

- **Case and spelling.** `nitrogen dioxide` becomes `Nitrogen Dioxide`;
  `Naphtalene` lands on `Naphthalene`. A misspelling that reaches the right
  substance is listed under *rows merged* if it sat beside a correctly spelled
  row, and nowhere otherwise.
- **Units.** `kilogram` and `kg` are one unit. A row whose unit was actually
  changed — BAFU's `Energy, from coal` in MJ landing on `Hard Coal`, which EF
  3.1 also accounts in MJ — appears under *rows merged* because the rows
  merged, and the conversion is stated there.
- **Contexts.** Every source's compartment vocabulary is mapped onto the
  consensus one, and that mapping is described in
  [Flow contexts](../concepts/contexts.md) rather than here.
- **Names that lost the contest for the published label.** When ecoinvent's
  `Ethene` and EF's `Ethylene` are one substance, one name is the label and
  the other is a synonym. That is a naming decision, described in [Names that
  belong to something else](../deciding/synonyms.md), and it does not alter
  what the source row says.

## Where the evidence on these pages comes from

Two places, and each page says which.

The **curated corrections** are in the source's own fix file, bundled with
the package under `src/brightway_flows/data/` — `ef-3.1-manual-fixes.json`,
`ecoinvent-3.8-manual-fixes.json`, `bafu-2026-v1-manual-fixes.json`, and so
on. Every entry there carries the reason in full; the pages here condense
it. A test (`tests/test_documentation.py`) checks that every registry-number
correction in a fix file is on that source's page, so the two cannot drift
apart silently.

The **merge outcomes** — which rows landed together, and which rows of one
name were split — are read off a build, and a build's numbers change when a
rule changes. Unless a page says otherwise, the build is the one made on
2026-08-29 from commit `54b0f9d`, which merged ecoinvent 3.12, ecoinvent 3.8,
BAFU 2026 v1 and Stepwise 2006, in that order, into the transformed EF 3.1.
Writing these pages against that build turned up eight inconsistencies —
duplicate substances minted for one BAFU and two ecoinvent names, an ion
published as its element on three lists, one mistaken reading — and they were
filed as [#177](https://github.com/brightway-labs/brightway-flows/issues/177) to [#184](https://github.com/brightway-labs/brightway-flows/issues/184) and fixed the next day. Where a page describes
one of them it gives both states, and the corrected state is the build of
2026-08-30 at `9fbb0d5`, on which 43 rows are decided differently from
`54b0f9d`, every one of them a row those issues name.

## What is still open

These pages record what was changed. What has *not* been settled for a list is
on the issue tracker, where every open issue carries the list it is about:
[EF 3.1](https://github.com/brightway-labs/brightway-flows/issues?q=is%3Aissue+is%3Aopen+label%3Aef-3.1), [ecoinvent](https://github.com/brightway-labs/brightway-flows/issues?q=is%3Aissue+is%3Aopen+label%3Aecoinvent), [BAFU](https://github.com/brightway-labs/brightway-flows/issues?q=is%3Aissue+is%3Aopen+label%3Abafu),
[Stepwise 2006](https://github.com/brightway-labs/brightway-flows/issues?q=is%3Aissue+is%3Aopen+label%3Astepwise), [AGRIBALYSE 3.2](https://github.com/brightway-labs/brightway-flows/issues?q=is%3Aissue+is%3Aopen+label%3Aagribalyse), [GreenDelta's EF 3.1 for openLCA](https://github.com/brightway-labs/brightway-flows/issues?q=is%3Aissue+is%3Aopen+label%3Agreendelta).
The full set of labels, by topic and by who has to answer, is listed under
[Known limitations](../reference/limitations.md#open-questions-by-source-list-and-by-topic).

## Finding the original row

- **EF 3.1 and ecoinvent** ship a uuid on every row, and the pages quote it.
  An ecoinvent uuid is the same across releases, so a row quoted on the 3.8
  page can be looked up in 3.12's `ElementaryExchanges.xml` as well.
- **BAFU 2026 v1 and Stepwise 2006 ship no identifier.** The uuids this
  project gives their rows are derived from the name, the compartment, the
  sub-compartment and the unit as the vendor wrote them — and, for BAFU, the
  country suffix — so they are stable across builds but are not the
  vendor's. The pages quote the name, the original compartment and the unit
  instead, which is what a reader needs to find the row in the ecoSpold
  archive or the SimaPro method file.
