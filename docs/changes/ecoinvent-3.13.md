# Changes to ecoinvent 3.13

*Part of [What was changed in each source](index.md). What is still open about ecoinvent is on the issue tracker under the label [`ecoinvent`](https://github.com/brightway-labs/brightway-flows/issues?q=is%3Aissue+is%3Aopen+label%3Aecoinvent).*

ecoinvent 3.13 was released on 2026-11-04 and ships 9,893 elementary
exchanges, 43 more than [3.12](ecoinvent-3.12.md). It is the first list
merged into the transformed EF 3.1, ahead of 3.12 and 3.8. An ecoinvent uuid
is the same in every release, so every row quoted below can be found in the
`ElementaryExchanges.xml` of 3.13 and, where the row existed then, of any
earlier release too. All four system models — cutoff, APOS, consequential and
EN15804 — ship the same 9,893 exchanges, so reading the cutoff release loses
nothing (`ecoinvent-3.13-additional-flows.json` records the comparison).

The curated corrections are in `ecoinvent-3.13-manual-fixes.json`: 24
entries, of which 5 alter a registry number, 5 a name, 11 a synonym list and
3 a unit. Twenty are 3.12's; 3.13 ships seven of 3.12's corrections itself —
see *What 3.13 corrected on its own* below — and needs four of its own, on
two rows it is the first to ship (*Rows merged into one flow*).

## One name, two substances

On the six-list build of 2026-11-04 (commit `BUILD-COMMIT`), every one of
3.13's 9,893 rows was placed — 8,837 by the matching rules, 185 by a curated
row in `ecoinvent-match-overrides.json`, and 871 by creating a flow that no
list before it had — and two names ended up on more than one substance. Both
are the compartment splits the [3.12 page](ecoinvent-3.12.md) describes as
deliberate, and nothing else: `Water` is **Water** in its six water
compartments and **Water vapour** in its five air compartments, and
`Water, unspecified natural origin` is **Groundwater** when taken from
`natural resource / in water`'s unconfined aquifer, **Fossil groundwater**
from the confined one and **Water** when the body is not said. The three
substances 3.12 published twice on the 2026-08-29 build, and corrected the
next day, stay corrected here.

Because 3.13 is merged first, it is the release that creates every
ecoinvent-only substance, and 3.12's copies of the same rows then match what
3.13 created: 855 rows that the five-list build of `5f06833` recorded as
*created* for 3.12 are recorded as *matched* now, every one of them on the
same substance. That is the whole of what moved for 3.12, apart from the
fourteen endosulfan isomer rows and the propyl propionate row, which move
because their numbers were corrected (*Numbers 3.13 corrects that this
project had not*, below).

## An ionic charge was added or corrected

422 of 3.13's rows are published under a name that carries a charge their
source name did not write out, in 37 name pairs — the same pairs as 3.12.
Thirty name a metal with a Roman numeral and are published as the ion,
`Aluminium III` as **Aluminium(3+)**, `Strontium II` as **Strontium(2+)**,
`Vanadium V` as **Vanadium(5+)**; five anions gain their charge, `Chloride`
as **Chloride(1-)**, `Sulfide` as **Sulfide(2-)**; and the six `ion` names
without a numeral — `Antimony ion`, `Arsenic ion`, `Copper ion`, `Iron ion`,
`Tin ion`, `Titanium ion` — are published as **Antimony, ion** and so on,
the spelling `domain/ion_names.py` gives an ion of unstated charge. Three of
those pairs needed a corrected registry number in 3.12 to reach the ion and
need none here: `Strontium II`, `Caesium I` and `Molybdenum VI` ship with
the ion's number in 3.13.

Five organotin rows in `water / ocean` carry a charge in 3.13's formula —
`Dibutyltin` as `C8H18Sn+2`, `Triphenyltin` as `C18H15Sn+` — and are
published without one: the adapter reads a row's registry number and not
its formula, and the published names are the vendor's. Where 3.13 states
the cation's number, `Dibutyltin` 14488-53-0 and `Triphenyltin` 668-34-8,
the substance carries it.

## Rows merged into one flow

On the build of 2026-11-04, 17 consensus flows carry more than one 3.13 row.
They are the groups the [3.12 page](ecoinvent-3.12.md) lists under the same
heading, less the endosulfan isomers: `Cypermethrin` and its two isomer
mixtures, 21 rows onto 7 flows, because ecoinvent still writes 52315-07-8 on
all three; the two groundwater rows of `1,4-Butanediol`; the two spellings of
total organic carbon; the four `Carbon` rows to soil; the carbon-stock
increase and decrease; and the paired `annual crop` / `arable land,
unspecified use` and `unknown` / `unspecified` land rows. The 21 endosulfan
rows that the 2026-08-29 build put on seven flows are on twenty-one flows
now: 3.13 gives the alpha and beta isomers their own numbers, and they reach
EF 3.1's `A-endosulfan` and `endosulfan (beta)` rows, with one flow created
for each isomer in `soil / forestry`, which EF 3.1 does not have.

One merge was wrong and is corrected here. 3.13 is the first release to ship
`Sodium stearyl fumarate` (4070-80-8) and `Monostearyl fumarate`
(1741-93-1), and writes `Fumaric acid` as a synonym on both. No list carries
either ester's number, so the label matcher read that synonym and put both
rows on EF 3.1's `fumaric acid`, 110-17-8, on the build of `a87255f`.
`ecoinvent-3.13-manual-fixes.json` takes the acid's name off both rows, and
two more catalogue fragments — `Dibasic acid`, `Sodium salt` — off the sodium
salt; each ester creates its own substance.

## What 3.13 corrected on its own

Compared row by row with 3.12, 3.13 changes a name, unit, compartment,
registry number or synonym list on 100 rows under 20 names. Seven of the
corrections stated for 3.12 are among them, and the 3.13 fixes file states
none of those:

| ecoinvent row(s) | 3.12 shipped | 3.13 ships | The 3.12 correction |
|---|---|---|---|
| `Strontium II`, 13 rows | 7440-24-6, the metal | 22537-39-9, the ion | The same number ([#198](https://github.com/brightway-labs/brightway-flows/issues/198)) |
| `Caesium I`, 5 rows | 7440-46-2, the metal | 18459-37-5, the ion | The same number (#198) |
| `Alpha-lindane`, `Beta-lindane`, `Delta-lindane`, 7 rows each | 58-89-9, gamma-lindane | 319-84-6, 319-85-7, 319-86-8 | The same three numbers ([#26](https://github.com/brightway-labs/brightway-flows/issues/26)) |
| `Molybdenum VI`, 13 rows | 7439-98-7, the metal | 16065-87-5, the ion | The same number ([#181](https://github.com/brightway-labs/brightway-flows/issues/181)) |
| `Nitrogen, organic bound`, 5 rows | 7727-37-9, dinitrogen | no number | Removed ([#57](https://github.com/brightway-labs/brightway-flows/issues/57)). 3.13 still writes `dinitrogen` and `molecular nitrogen` as synonyms, and the fixes file still removes them |

`ecoinvent-canonical-identities.json`, which reads the newest release's
name and number for every element and ion flow, is regenerated with 3.13 as
the deciding release. Every one of its 128 identities is unchanged: what the
corrected 3.12 said, 3.13 says.

### Numbers 3.13 corrects that this project had not

Three other changes correct a registry number this project had left as
shipped, and each is now stated as a correction in every earlier release
that ships the row, so that the releases the build merges agree about the
substance (#26). Each has its own issue, and the earlier releases' pages carry
the rows.

| ecoinvent row(s) | 3.12 shipped | 3.13 ships | What it changes |
|---|---|---|---|
| `Alpha-endosulfan` and `Beta-endosulfan`, 7 rows each ([#456](https://github.com/brightway-labs/brightway-flows/issues/456)) | 115-29-7, the parent | 959-98-8 and 33213-65-9, the isomers | On the build of 5f06833 all twenty-one endosulfan rows sat on one substance. EF 3.1 carries both isomers under these numbers, and the rows now reach them. |
| `Propyl propionate`, water / unspecified ([#457](https://github.com/brightway-labs/brightway-flows/issues/457)) | 623-53-0, ethyl methyl carbonate | 106-36-5, propyl propionate | On the build of 5f06833 the 3.12 row was published as `Ethyl Methyl Carbonate` on EF 3.1's flow of that carbonate. |
| `Dibutyltin`, `Diphenyltin`, `Phenyltin`, `Trioctyltin`, `Triphenyltin`, one `water / ocean` row each ([#458](https://github.com/brightway-labs/brightway-flows/issues/458)) | 1002-53-5, 1011-95-6, 2406-68-0, 869-59-0, 892-20-6 — neutral tin hydrides and compounds | 14488-53-0 and 668-34-8, the dibutyltin and triphenyltin cations; no number on the other three, with charged formulas `C12H10Sn+2`, `C6H5Sn+3`, `C24H51Sn1+` | The dissolved cations are what an emission to sea water is. The adapter does not read formulas, so the charge reaches the build only through the number, where 3.13 states one. |

### Rows added and retired

3.13 adds 50 rows, none of which an earlier release ships: 46 emissions to
`water / unspecified` and 4 to `air / unspecified`, most of them
pharmaceutical excipients, amino acids and fine-chemical intermediates. On
the build of 2026-11-04, 32 of them reach a flow EF 3.1 already has by their
registry number — `L-Cystein` lands on **L-cysteine**, `Stearyl alcohol` on
**Octadecan-1-ol** — one, `D-Mannitol`, reaches EF 3.1's **D-mannitol** by
name, and 17 create a substance no list had, among them
`Hydroxypropylmethylcellulose`, `Magnesium stearate`, `L-Histidine` and the
two fumarate esters. Among the names:
`Citric acid`, `Glycine`, `L-Histidine`, `Hydroxypropylmethylcellulose`,
`Magnesium stearate`, `Sorbitan monooleate`, `Fluorobenzene` and
`Vinyl acetate` in both compartments. Five arrive without a registry number:
`D-Mannitol`, `L-Alanyl-l-tyrosine`, `L-Tyrosin`, `Sucrose` and
`Thionyl chloride`.

It retires 7 rows, all of them `2-Propen-1-ol` (107-18-6), in seven
compartments, and keeps the two `Allyl alcohol` rows of the same number with
`2-Propen-1-ol` added as a synonym. The 3.12 build already placed both names
on one substance, published as **Allyl Alcohol**.

## Registry numbers corrected

Five entries in `ecoinvent-3.13-manual-fixes.json` change a registry number.
Each is applied before the row is matched, and each is the same correction
3.12 takes; the reasons are given in full on the [3.12 page](ecoinvent-3.12.md).

| ecoinvent row(s) | Shipped | Corrected to | Why |
|---|---|---|---|
| `Uranium-238`, 9 rows (`543421e8-f0b3-45a2-b0ed-03489e878138` and eight others), kBq | 7440-61-1 | 24678-82-8 | 7440-61-1 is uranium the element, in kilograms; the rows are the activity of one nuclide ([#17](https://github.com/brightway-labs/brightway-flows/issues/17)). |
| `Mefentrifluconazole`, soil / agricultural (`a1f19e68-e0ca-4d2b-a159-38e9036542f3`) | none | 1417782-03-6 | The row carries no identifier of any kind ([#19](https://github.com/brightway-labs/brightway-flows/issues/19)). |
| `Water, salt, sole`, natural resource / in water (`79238018-8ec1-4615-9469-2b0df95a43c3`) | 7732-18-5 | removed | Brine is a mixture, and 7732-18-5 is the water molecule. |
| `Stibnite`, natural resource / in ground (`3e0034cd-21d6-4582-9fbf-09c26edd05df`) | 1345-04-6 | 1317-86-8 | The ore takes the mineral's number, not the manufactured chemical's ([#123](https://github.com/brightway-labs/brightway-flows/issues/123)). |
| `Beta-cyfluthrin`, 8 rows | 68359-37-5 | 1820573-27-0 | 68359-37-5 is plain cyfluthrin; the beta product has its own number ([#188](https://github.com/brightway-labs/brightway-flows/issues/188)). |

### Other corrections that change what a row says

Four synonym corrections are 3.13's own: `Fumaric acid` comes off
`Sodium stearyl fumarate` and `Monostearyl fumarate`, and `Dibasic acid` and
`Sodium salt` off the former, for the reason given under *Rows merged into
one flow*. The five renames, three unit corrections and seven other synonym
corrections are 3.12's, unchanged: `Silver-110` to `Silver-110m`, `Ioxynil methyl ester` to
`MCPA-methyl`, the seven `Granite` emission rows to `Penoxsulam`,
`Zirconia, as baddeleyite` to `Baddeleyite`, `Peat` to `Peat, horticulture`;
the three `(obsolete)` arable occupation rows from m² to m²·a; `BAS 480F`
restored on two `Epoxiconazole` rows, `oxidane` taken off the brine row and
`dinitrogen` and `molecular nitrogen` taken off the organic-bound nitrogen
rows.
