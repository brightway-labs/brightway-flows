# Changes to ecoinvent 3.11

*Part of [What was changed in each source](index.md). What is still open about ecoinvent is on the issue tracker under the label [`ecoinvent`](https://github.com/brightway-labs/brightway-flows/issues?q=is%3Aissue+is%3Aopen+label%3Aecoinvent).*

ecoinvent 3.11 is extracted and curated — 9,795 rows, corrected by
`ecoinvent-3.11-manual-fixes.json` and the `ecoinvent-match-overrides.json`
shared by every ecoinvent release — and it can be merged, but it is not part
of the standard build: the 2026-08-29 build of `54b0f9d` merged
[ecoinvent 3.12](ecoinvent-3.12.md) and [ecoinvent 3.8](ecoinvent-3.8.md)
only. An ecoinvent uuid is the same in every release, so what those two pages
say about a row is what the merge would do with 3.11's copy of it. 3.11 is
the release that more than doubled the list, adding emission rows in seven
compartments for hundreds of pesticides; 3.12 ships the same rows under the
same uuids.

## One name, two substances

Which rows of a name land on which substance is measured on a build, and
this release is not in one. For the rows it shares with the merged
releases, read the same section on the [3.8](ecoinvent-3.8.md) and
[3.12](ecoinvent-3.12.md) pages. One case is corrected here before it
reaches a build, because it is the release itself that uses one name for two
substances: `Granite` names the rock once and the herbicide penoxsulam seven
times — see the last row of the *other corrections* table below.

## An ionic charge was added or corrected

Whether a row's published name carries a charge its source name did not is
measured on a build, and this release is not in one. What can be said is how
the release names dissolved metals. It names 25 metal ions with a Roman
numeral — `Aluminium III`, `Chromium VI`, `Sodium I`, `Strontium II` — and
six with the word `ion` and no charge — `Antimony ion`, `Arsenic ion`,
`Copper ion`, `Iron ion`, `Tin ion`, `Titanium ion`. Publishing
`Chromium VI` as `Chromium(6+)` is notation only and is not a change. Every
bare element name that carries a registry number carries the element's own;
none carries an ion's. No row of this release is named or numbered
differently in 3.12, so `ecoinvent-canonical-identities.json` holds no entry
for it.

## Rows merged into one flow

Which rows of this release land together on one consensus flow is measured
on a build, and this release is not in one. The
[3.8](ecoinvent-3.8.md#rows-merged-into-one-flow) and
[3.12](ecoinvent-3.12.md#rows-merged-into-one-flow) pages list the merges
for the rows those releases share with this one.

## Registry numbers corrected

Each of these is written down in `ecoinvent-3.11-manual-fixes.json` with
the evidence in full; the reasons below are condensed. ecoinvent removed the
herbicide's number from its `Granite` resource row in this release, so that
correction, which 3.8 through 3.10.1 need, is absent here.

| ecoinvent name | Rows in 3.11 | Number shipped | What it designates | Corrected to | What that designates | Why |
|---|---|---|---|---|---|---|
| `Molybdenum VI` | 13 (one per emission context) | 7439-98-7 | Molybdenum, the metal | 16065-87-5 | The hexavalent molybdenum ion, Mo⁶⁺ | The rows name the ion and write the formula `Mo+6`; release 3.9.1 registered the same thirteen uuids with the ion's number, and 3.10.1 is where the number changed to the metal's while the name stayed. With the metal's number the rows were published as `Molybdenum`, the element, on the 2026-08-29 build ([#181](https://github.com/brightway-labs/brightway-flows/issues/181)). |
| `Strontium II` | 13 (one per emission context) | 7440-24-6 | Strontium, the metal | 22537-39-9 | The divalent strontium ion, Sr²⁺ | The rows name the ion, as 3.8 and 3.12 do, and every other Roman-numeral metal carries its ion's number; with the metal's number they were published as the element ([#198](https://github.com/brightway-labs/brightway-flows/issues/198)) |
| `Caesium I` | 5 (one per water context) | 7440-46-2 | Caesium, the metal | 18459-37-5 | The monovalent caesium ion, Cs⁺ | The same slip on the caesium ion (#198) |
| `Uranium-238` | 9 (`543421e8-f0b3-45a2-b0ed-03489e878138` and eight others, in kBq) | 7440-61-1 | Uranium, the element, by mass | 24678-82-8 | The nuclide U-238 | The rows measure the activity of one nuclide; every list that ships the row (3.8 through 3.12, EF 3.1) carries the element's number and is corrected the same way, so the lists agree about what the nuclide's number is ([#17](https://github.com/brightway-labs/brightway-flows/issues/17)). |
| `Water, salt, sole` | 1 (`79238018-8ec1-4615-9469-2b0df95a43c3`, `natural resource / in water`, m³) | 7732-18-5 | The water molecule | *removed* | — | *Sole* is German for brine, a saturated salt solution; a mixture does not carry the registry number of one of its constituents. EF 3.1's copy of the flow is corrected the same way. The synonym `oxidane`, the IUPAC name of water, is removed for the same reason. |
| `Nitrogen, organic bound` | 5 (water: ground-, ground- long-term, ocean, surface water, unspecified) | 7727-37-9 | Dinitrogen, N₂, the gas | *removed* | — | Organically bound nitrogen is a measurement over many compounds rather than one compound, and with the gas's number left in place the rows fuse with the gas ([#57](https://github.com/brightway-labs/brightway-flows/issues/57)). The synonyms `dinitrogen` and `molecular nitrogen`, which ecoinvent copies onto these rows from its `Nitrogen` rows, are removed for the same reason. |
| `Stibnite` | 1 (`3e0034cd-21d6-4582-9fbf-09c26edd05df`, `natural resource / in ground`, kg) | 1345-04-6 | Antimony trisulfide, the manufactured chemical | 1317-86-8 | Stibnite, the mineral | The row is ore taken out of the ground; IARC separates the two registrations as compound and mineral, and BAFU independently registers its stibnite 1317-86-8. EF 3.1's thirteen `antimony trisulfide` rows are emissions and keep the compound's number ([#123](https://github.com/brightway-labs/brightway-flows/issues/123)). |
| `Alpha-lindane` | 7 (air: non-urban, unspecified; soil: agricultural, forestry, unspecified; water: surface, unspecified) | 58-89-9 | Gamma-lindane, the insecticide isomer | 319-84-6 | Alpha-hexachlorocyclohexane | ecoinvent writes the gamma isomer's number on all three of the other isomers; each has its own, and with the gamma number left in place the four would fuse into one substance. 3.12 ships the same seven rows under the same uuids and is corrected the same way. |
| `Beta-lindane` | 7 (same seven compartments) | 58-89-9 | Gamma-lindane | 319-85-7 | Beta-hexachlorocyclohexane | As above. |
| `Delta-lindane` | 7 (same seven compartments) | 58-89-9 | Gamma-lindane | 319-86-8 | Delta-hexachlorocyclohexane | As above. |
| `Mefentrifluconazole` | 1 (`a1f19e68-e0ca-4d2b-a159-38e9036542f3`, `soil / agricultural`, kg) | *none* | — | 1417782-03-6 | Mefentrifluconazole, BASF's triazole fungicide (Revysol) | The row carries no identifier of any kind and the trivial name cannot be parsed into a structure, so nothing could place it; PubChem's record for the substance (CID 71230671) lists the name among its synonyms and this number as its registry number ([#19](https://github.com/brightway-labs/brightway-flows/issues/19)). |
| `Beta-cyfluthrin` | 8 (soil, air and water rows, kg) | 68359-37-5 | Cyfluthrin, the commercial eight-isomer mixture | 1820573-27-0 | Beta-cyfluthrin, the product enriched in the two most insecticidally active diastereoisomeric pairs | PPDB registers the two products separately (records 74 and 192). ecoinvent's own transition table retired the name Cyfluthrin for these uuids in favour of Beta-cyfluthrin, while EF 3.1 ships plain cyfluthrin under the shared number, so the beta rows fused with the plain substance; the shared EC number 269-855-7 stays. Every release ships the rows and takes the same correction ([#188](https://github.com/brightway-labs/brightway-flows/issues/188)). |

### Other corrections

These change a name, a synonym or a unit rather than a CAS number. Two of the
synonym entries restore `BAS 480F` on the two `Epoxiconazole` rows
(`3bd32b7c-53b2-5302-a82a-61206e93c1de`, soil / unspecified;
`a9870af8-ee86-51a8-8068-9d2250dea9cf`, water / surface water) that first
appear in this release without it; the six other rows carry the synonym, and
it is the only bridge to EF 3.1's `Bas 480f`, which registers the fungicide
under a different number ([#179](https://github.com/brightway-labs/brightway-flows/issues/179); see the [3.12 page](ecoinvent-3.12.md)).

| ecoinvent name | Rows in 3.11 | Change | Why |
|---|---|---|---|
| `Silver-110` | 9, in kBq | Renamed `Silver-110m`; `Silver-110` kept as a searchable alternative name | Silver-110 is a 24.56-second ground state; the species a reactor-effluent inventory reports is the isomer Ag-110m, at 249.863 days, which is what EF 3.1's characterisation factors describe ([#24](https://github.com/brightway-labs/brightway-flows/issues/24)). The number 14391-76-5 stays: it indexes the mass number and there is no nuclide-specific number for the isomer. |
| `Ioxynil methyl ester`, 2436-73-9 | 7 (air, soil and water, the compartments this release introduces) | Renamed `MCPA-methyl`, and the old name is not kept | 2436-73-9 contains no iodine: it is methyl 2-(4-chloro-2-methylphenoxy)acetate, the methyl ester of MCPA. ecoinvent's three other ioxynil flows carry correct numbers, so the name slipped and the CAS number is kept ([#46](https://github.com/brightway-labs/brightway-flows/issues/46)). |
| `Zirconia, as baddeleyite`, 12036-23-6 | 1 (`e07b4402-abe3-4346-8c42-051c5983bd1e`) | Renamed `Baddeleyite` | Zirconia *is* zirconium dioxide, and the row is the mineral being mined; the mineral's own name is shorter and more accurate ([#118](https://github.com/brightway-labs/brightway-flows/issues/118)). |
| `Peat` | 1 (`c5035ce2-5ee5-431f-a287-4b25da42be74`, `natural resource / biotic`, kg) | Renamed `Peat, horticulture`; `Peat` kept as an alternative name | EF 3.1 has two peats: fuel peat in megajoules, and this one, dug for growing media and counted by mass. Under the bare name the kilogram row reached the megajoule flow and its own factor stopped being published ([#89](https://github.com/brightway-labs/brightway-flows/issues/89)). |
| `Gypsum`, 13397-24-5 | 1 (`11a2a7b1-ab2f-47b8-9e29-6f33d5207fa6`) | Synonyms `sulfate` and `dihydrate` removed | They are the words of the real synonym `Calcium sulfate dihydrate` split apart, and `sulfate` names a substance the list publishes, which gypsum reached by it ([#119](https://github.com/brightway-labs/brightway-flows/issues/119)). |
| `Occupation, arable, conservation tillage (obsolete)`, `… conventional tillage (obsolete)`, `… reduced tillage (obsolete)` | 3 (`fdb1b2d0-f537-401e-b845-1d93da512174`, `e489cce4-a80f-417d-9ae6-9fc14cc7dd49`, `81e07a67-28e0-4392-a553-d86e54a9b8a9`) | Unit m² → m²·a, factor 1.0 | Every other land-occupation row in ecoinvent and in EF 3.1 is an area held for a time; ecoinvent's own correspondence tables map these three at 1.0 with the comment *assumed conversion based on land use through an entire year* ([#111](https://github.com/brightway-labs/brightway-flows/issues/111)). |
| `Granite`, 219714-96-2 | 7 emission rows (air: non-urban, unspecified; soil: agricultural, forestry, unspecified; water: surface, unspecified) | Renamed `Penoxsulam`, and `Granite` is not kept as a synonym | The number is penoxsulam's and the name is its trade name; nobody emits rock to surface water. The eighth `Granite` row (`a4375a18-172c-4f82-90b7-bca972f75548`, `natural resource / in ground`, no CAS number) is the rock and is untouched — the match names the CAS number as well as the name so it cannot be caught. Keeping `Granite` as a synonym would hand the next list's rock a herbicide's match key ([#140](https://github.com/brightway-labs/brightway-flows/issues/140)). |
