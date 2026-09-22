# Changes to ecoinvent 3.12

*Part of [What was changed in each source](index.md). What is still open about ecoinvent is on the issue tracker under the label [`ecoinvent`](https://github.com/brightway-labs/brightway-flows/issues?q=is%3Aissue+is%3Aopen+label%3Aecoinvent).*

ecoinvent 3.12 ships 9,850 elementary exchanges, and it is the first list
merged into the transformed EF 3.1 on the build of 2026-08-29 (commit
`54b0f9d`). Three defects that build showed were corrected the next day, and
where a passage below says so the corrected state is the build of 2026-08-30
at `9fbb0d5`. Its rows carry a uuid that is the same in every ecoinvent release,
so every row quoted below can be found in the `ElementaryExchanges.xml` of
3.12 and, where the row existed then, of any earlier release too.

The curated corrections are in `ecoinvent-3.12-manual-fixes.json`: 24 entries
in all, of which 9 alter a registry number, 5 a name, 7 a synonym list and 3 a
unit. Where a row is sent somewhere ecoinvent's own correspondence table to EF
3.1 would not send it, the target is in `ecoinvent-match-overrides.json`,
which applies to every ecoinvent release because the uuids are shared. The
splits and merges below are what the build did with the corrected rows.

## One name, two substances

On the 2026-08-29 build of `54b0f9d` five names in ecoinvent 3.12 ended up on
more than one consensus substance. Two of those splits are deliberate and
follow the compartment. The other three were the same substance published
twice, and all three were corrected the next day ([#178](https://github.com/brightway-labs/brightway-flows/issues/178), [#179](https://github.com/brightway-labs/brightway-flows/issues/179),
[#180](https://github.com/brightway-labs/brightway-flows/issues/180)): on the build of 2026-08-30 at `9fbb0d5` only the two compartment splits remain.
The corrected three are kept here, in the past tense, so that a reader of
either build finds the rows.

### Deliberate: the compartment decides

**`Water`** (CAS 7732-18-5, 11 rows, m3). Water released to air is water
vapour; water released to a river or the sea is liquid water. The consensus
list keeps those apart, so the five air rows land on **Water vapour** and the
six water rows on **Water**.

| ecoinvent uuid | ecoinvent context | Published as |
|---|---|---|
| `075e433b-4be4-448e-9510-9a5029c1ce94` | air / unspecified | Water vapour |
| `5d368100-b1bc-4456-8420-e469edccf349` | air / urban air close to ground | Water vapour |
| `09872080-d143-4fb1-a3a5-647b077107ff` | air / non-urban air or from high stacks | Water vapour |
| `f977a02e-3564-4798-843c-9fb9a18bc18b` | air / low population density, long-term | Water vapour |
| `f14b59ff-d438-442d-8bad-b53694b8263a` | air / lower stratosphere + upper troposphere | Water vapour |
| `2404b41a-2eed-4e9d-8ab6-783946fdf5d6` | water / unspecified | Water |
| `db4566b1-bd88-427d-92da-2d25879063b9` | water / surface water | Water |
| `4f0f15b3-b227-4cdc-b0b3-6412d55695d5` | water / ocean | Water |
| `51254820-3456-4373-b7b4-056cf7b16e01` | water / ground- | Water |
| `06d4812b-6937-4d64-8517-b69aabce3648` | water / ground-, long-term | Water |
| `2256a142-8242-4b4f-b9aa-a167803989ca` | water / fossil well | Water |

**`Water, unspecified natural origin`** (7732-18-5, 3 rows, m3). The name
says nothing about where the water is taken from; the sub-compartment does,
and the consensus list names water resources by their origin. So the three
rows become three resources.

| ecoinvent uuid | ecoinvent context | Published as |
|---|---|---|
| `831f249e-53f2-49cf-a93c-7cee105f048e` | natural resource / in water | Water (Resource → Water) |
| `478e8437-1c21-4032-8438-872a6b5ddcdf` | natural resource / in ground | Groundwater |
| `2caa889e-8187-459d-963a-fa47a79c5378` | natural resource / fossil well | Fossil groundwater |

### One substance published twice, since corrected

**`Carbon`** (7440-44-0, 7 rows, kg). ecoinvent's plain `Carbon` emissions
are soot — elemental carbon, or black carbon — and this project sends them to
the consensus **Elemental Carbon** substance by a curated target
([#141](https://github.com/brightway-labs/brightway-flows/issues/141)).
The target had been written for the four rows ecoinvent's own correspondence
table covers. The other three rows, all to soil, had no table entry and were
matched on their registry number instead, and 7440-44-0 is also the CAS number
on EF 3.1's `Carbon` — so on the 2026-08-29 build they landed there, and the
same ecoinvent name, with the same number, was published as two substances.
The curated target now covers all seven uuids, in `ecoinvent-match-overrides.json`
([#180](https://github.com/brightway-labs/brightway-flows/issues/180)). EF 3.1 publishes elemental carbon in soil only as *soil,
unspecified*, so the three soil rows are published on that flow: a
sub-compartment given up for the right substance, and the expectation file
for the issue says so.

| ecoinvent uuid | ecoinvent context | Published as, 2026-08-29 | Published as, 2026-08-30 |
|---|---|---|---|
| `57af157e-2054-407d-949b-8cc9c2aa4655` | air / urban air close to ground | Elemental Carbon | Elemental Carbon |
| `14ea575b-5caa-4958-acf7-0bcc47f9cadf` | soil / unspecified | Elemental Carbon | Elemental Carbon |
| `36609913-7c42-457a-89cc-00e2d9f0f867` | water / ground- | Elemental Carbon | Elemental Carbon |
| `3ff3231e-3c38-5a47-a6fd-821d11c599e0` | water / unspecified | Elemental Carbon | Elemental Carbon |
| `62859da4-f3c5-417b-a575-8b00d8d658b1` | soil / agricultural | Carbon | Elemental Carbon, in soil (unspecified) |
| `b72e46aa-9034-4dd2-856d-a43241d3b1f4` | soil / forestry | Carbon | Elemental Carbon, in soil (unspecified) |
| `7f8fd1ca-0412-4b2e-90fd-a9d294d947a3` | soil / industrial | Carbon | Elemental Carbon, in soil (unspecified) |

Whether EF's own `Carbon` (7440-44-0) and its `Elemental carbon` (no number)
are one substance is not decided by this, and BAFU's five `Carbon` rows still
land on EF's `Carbon`.

**`Epoxiconazole`** (135319-73-2, 8 rows, kg). EF 3.1 carries this fungicide
under BASF's development code, `Bas 480f`, with the registry number
106325-08-0 — a CAS number CAS has since replaced by 133855-98-8, the racemate
that is the commercial product. ecoinvent's 135319-73-2 is the CAS number for the
compound with its stereochemistry unspecified, and it appears on no EF 3.1
row. Six of ecoinvent's rows also carry the synonym `BAS 480F`, and those six
reach EF's substance on that name. The two rows without the synonym had
nothing left to match on and, on the 2026-08-29 build, minted a second
substance, **Epoxiconazole** — the same fungicide twice, and which copy a row
reached depended on whether ecoinvent had happened to write the synonym. The
synonym is now restored on those two uuids in `ecoinvent-3.12-manual-fixes.json`
(and in the 3.11 file, where the rows first appear), so on the build of 2026-08-30 at `9fbb0d5`
all eight take the route the six already took ([#179](https://github.com/brightway-labs/brightway-flows/issues/179)). That EF labels the
substance by a development code rather than the name every inventory uses is
a separate question, still open on the issue.

| ecoinvent uuid | ecoinvent context | Published as |
|---|---|---|
| `d9b5eafe-587a-5643-80a7-6d221551816f` | air / unspecified | Bas 480f |
| `fe09f756-99f3-5dbb-b8a8-0896cc409887` | air / non-urban air or from high stacks | Bas 480f |
| `1afedfb8-dfbd-4722-a5fc-f678c593d907` | soil / agricultural | Bas 480f |
| `b38209dd-14b6-5c16-8718-639ed15fe3c0` | soil / forestry | Bas 480f |
| `2759c5ea-c684-5b4a-94ca-9a448bd78159` | water / ground- | Bas 480f |
| `4fdfe72b-e003-505b-a7c2-c86cf877acf7` | water / unspecified | Bas 480f |
| `3bd32b7c-53b2-5302-a82a-61206e93c1de` | soil / unspecified | Epoxiconazole on 2026-08-29; Bas 480f since the synonym was restored |
| `a9870af8-ee86-51a8-8068-9d2250dea9cf` | water / surface water | Epoxiconazole on 2026-08-29; Bas 480f since the synonym was restored |

**`Hydrocarbons, unspecified`** (no registry number, 9 rows, kg). Seven rows
are in ecoinvent's correspondence table and go to EF 3.1's
**Hydrocarbons (unspecified)**. The two that are not — `air / unspecified`
(`3fdc4e95-dc17-5f9f-9ddc-251ecd7c66c0`) and `soil / agricultural`
(`614d5544-9edf-5b76-90e8-e9c7b98a8084`) — carry no CAS number and a name that
differs from EF's only in punctuation, and on the 2026-08-29 build they minted
a second substance, **Hydrocarbons, Unspecified**, a duplicate of the first
that BAFU's five rows of the same name then joined. Two curated targets in
`ecoinvent-match-overrides.json` now send those two uuids to EF's flows in
their own contexts, and five more send BAFU's rows there, so on
the build of 2026-08-30 at `9fbb0d5` the duplicate is no longer minted ([#178](https://github.com/brightway-labs/brightway-flows/issues/178)). A synonym
written on EF's rows was tried first and moved nothing: a base-list row's
synonyms are deleted before the merge builds its name index. The seven rows
that reached EF are `f9abb851-8731-4c5b-b057-863996a1f94a` (air, non-urban),
`042e5892-cd59-4e95-949e-cacce0e6a590` (soil, unspecified),
`9d508263-9cfd-444a-b1de-73f2bcf39c02` (groundwater),
`5e08c84c-69a2-4f0b-b3b3-6b7f0925712b` (groundwater, long-term),
`049a1473-3a62-4121-982b-5d15d0f2c683` (ocean),
`49c42751-1b0b-4ab1-8e70-032e991ce6fd` (surface water) and
`e620a933-c348-4e7e-8893-ab0a0f681c7e` (water, unspecified).

## An ionic charge was added or corrected

ecoinvent 3.12 writes the charge of a dissolved metal as a Roman numeral —
`Chromium VI`, `Sodium I` — and the consensus list writes it as `Chromium(6+)`
and `Sodium(1+)`. That is a change of notation and nothing else: 20 names on
265 rows, and every one of them carries the ion's own registry number, so the
charge was ecoinvent's and the list only respelled it. Two more names state a
charge under the *element's* number, `Strontium II` and `Caesium I`; they are
corrected to the ions' numbers below, the way `Molybdenum VI` was (#198).

Two more names state a charge and were, until #198, published as the bare
metal: `Rhodium III` (16065-89-7, one row) and `Palladium II` (16065-88-6, six
rows). EF 3.1 holds neither ion, so the number found nothing and the vendor's
own bare synonym reached the element. The merge now refuses the element for a
name that states a charge, and the seven rows mint their ions, `Rhodium(3+)`
and `Palladium(2+)`, spelled by a curated name the way the minted generic ions
are. The same uuids were `Palladium` and `Rhodium` in 3.8, so 3.8's rows
follow 3.12's identity, as `Zinc` follows `Zinc II`.

What is listed here is the opposite case: six metals ecoinvent names as an
ion **without** a charge, and publishes without a registry number.

| ecoinvent name | Rows | Published as |
|---|---|---|
| `Antimony ion` | 13 | Antimony, Ion |
| `Arsenic ion` | 13 | Arsenic, Ion |
| `Copper ion` | 14 | Copper, Ion |
| `Iron ion` | 13 | Iron, Ion |
| `Tin ion` | 13 | Tin, Ion |
| `Titanium ion` | 13 | Titanium, ion |

Between 3.8 and 3.9.1 ecoinvent renamed these flows from the bare element
(`Copper`, `Iron`) to `Copper ion`, `Iron ion`, and at the same time deleted
the registry number that had been on them — the element's, which was wrong for
a dissolved species. The vendor's newest name is taken as its current opinion
of what the flow is: a metal ion whose oxidation state the inventory did not
record. Picking a charge for it would be this project's guess rather than
ecoinvent's statement, so the list publishes the generic ion — written
`X, Ion` — and keeps the charge unstated. `Titanium ion` is the worked example
in [When a name and a CAS number disagree](../deciding/identity.md): EF 3.1 ships
the same name with a CAS number that says Ti⁴⁺, and the name is kept generic there
too, because it is the string both vendors write and ecoinvent's rows reach the
substance by exactly that label
([#143](https://github.com/brightway-labs/brightway-flows/issues/143)).
One charge was confirmed by correcting a number. ecoinvent names its
dissolved molybdenum `Molybdenum VI` on thirteen rows, writes the formula
`Mo+6` and the synonyms `Molybdenum (+6)` and `Molybdenum ion` on them, and
from 3.10.1 on registers every one as 7439-98-7 — molybdenum the *metal*;
3.9.1 shipped the same thirteen uuids under the same name with the ion's own
number, 16065-87-5. A stated number outranks a name, so on the 2026-08-29
build all thirteen were published as `Molybdenum`, the element. The name is
believed, as for EF's `vanadium (v)` and BAFU's `Cadmium II`, and the vendor's
own earlier release says the same: the ion's number is written on the name in
`ecoinvent-3.12-manual-fixes.json` (and the 3.10.1 and 3.11 files), and on
the build of 2026-08-30 at `9fbb0d5` the thirteen are published as `Molybdenum(6+)`, where EF
3.1 publishes `molybdenum (vi)` in the same thirteen contexts ([#181](https://github.com/brightway-labs/brightway-flows/issues/181)).
Worth reporting to ecoinvent.

## Rows merged into one flow

On the 2026-08-29 build, 25 consensus flows carry more than one ecoinvent 3.12
row. They fall into seven groups.

**Endosulfan and its two isomers — 21 rows onto 7 flows.** ecoinvent ships
`Endosulfan`, `Alpha-endosulfan` and `Beta-endosulfan` in the same seven
compartments, and writes the parent's registry number, 115-29-7, on all
twenty-one rows. A shared registry number is how this list decides that two
rows are one substance, so all three names land on **Endosulfan** in each
compartment. The isomer distinction ecoinvent's names draw is lost: the alpha
isomer has its own CAS number (959-98-8) and so does the beta (33213-65-9), and
ecoinvent did not use them.

| Compartment | Endosulfan | Alpha-endosulfan | Beta-endosulfan |
|---|---|---|---|
| air / unspecified | `ed84e123-f704-5c1a-b52a-bd4a27def80a` | `4e4bd37e-839c-5e33-8c37-69dd63c57453` | `b2af6c1e-8540-5494-a91d-cd6e270479fa` |
| air / non-urban air or from high stacks | `dd0a0cee-cba0-5adf-87ae-f9bd91979597` | `b046066c-54ef-517c-96f3-bffddde1d750` | `3d241cae-7ad8-5d5f-9aec-b98cc8e1bc35` |
| soil / agricultural | `69da88e0-7fb1-4223-bb2d-b6e86e2af891` | `2071e5b1-69b0-55b1-82fc-21aea09a2361` | `8be2ef7a-d350-5209-a251-972532c9a9f3` |
| soil / forestry | `b981ae01-8397-5664-a410-0c8c55219202` | `3acdd91b-21f1-50cc-8b84-5f67d2d356df` | `abff2fad-62c9-5cec-8616-b35c7cf43169` |
| soil / unspecified | `2127c1cf-0b87-58b0-a3ec-7608098a8f2f` | `a31c8d9a-9b9c-5cb2-8e1f-1e545fdd58ac` | `a7e6bc76-7e72-5b5c-88f9-28ee4188a1c9` |
| water / surface water | `bb33c6ad-9715-5802-a73d-4c9d4f05103a` | `8e9ba4c9-1b26-5af0-9ff1-f40a72d2ae53` | `f55785c8-247a-58fe-9764-cb4371e84cfd` |
| water / unspecified | `30c16c5d-8aac-5889-aa9a-9727f36d61ca` | `34ed0abd-61ef-53cc-bca1-cacd0928bb47` | `9c426aaa-f6fa-5a91-b93c-3d920c5ef63d` |

**Cypermethrin and its two isomer mixtures — 21 rows onto 7 flows.** The same
situation: `Cypermethrin`, `Beta-cypermethrin` and `Zeta-cypermethrin` all
carry 52315-07-8 in ecoinvent, so all three land on **Cypermethrin**.

| Compartment | Cypermethrin | Beta-cypermethrin | Zeta-cypermethrin |
|---|---|---|---|
| air / unspecified | `0cedf8cd-2ac1-54af-80c7-26ccb70fe195` | `285bebd4-81e6-576d-8b56-3a51d92db28e` | `165fc785-1083-588f-95a0-8a93d3c67cd8` |
| air / non-urban air or from high stacks | `620d3423-2376-4fcc-bb89-2d468f8b2df8` | `394e7e6f-e87b-5a5f-a003-8c31f7b132ae` | `781bfb14-d34f-4f99-9d15-d67171d6fc24` |
| soil / agricultural | `e7f1df40-788a-4403-81ea-e5e9e84e32d7` | `6098e65f-3e52-5672-89b4-519dd8987d19` | `b6e1f836-2b5c-4bd5-bc8c-af065ee7c230` |
| soil / forestry | `24a29bd2-ec92-5fd1-adea-f763a63bea78` | `2530d733-aaee-5116-895d-1160ce5d6262` | `5b4b5113-777b-5fde-bbde-50bb3db36069` |
| soil / unspecified | `66470fdb-706f-542e-9132-3476f241f968` | `f9106c60-ccdd-5219-a436-3cb42cf3a057` | `98885074-2e44-57d4-8301-1e8244122880` |
| water / surface water | `30cecb7a-5d6e-5da8-84a5-89eacb2c1f67` | `ab5e8823-e98a-5922-9afc-d2e5bc7bfeb6` | `434fd8c1-93a7-5a9f-a104-2d200be534c5` |
| water / unspecified | `d12347c3-71b1-5900-9386-39df6d0004dc` | `6923130e-7ae7-5ba1-9bca-a24b3fc849e9` | `f2ad6cc2-0763-5360-ae1e-78b4fbcb032c` |

**Two names for allyl alcohol — 4 rows onto 2 flows.** `Allyl alcohol` and
`2-Propen-1-ol` are the common and the systematic name of one compound, and
ecoinvent gives both 107-18-6. In `air / unspecified`,
`c8d084b4-a980-49a3-a385-8476ed020c6b` and
`f8828e44-6c1e-50ee-afa4-1b2f2a89590c` land on one flow; in
`water / unspecified`, `3dbfcc62-4898-48a7-969b-74270615e36e` and
`0d8d3729-7b68-5669-bc51-fa692e31c561` on another. Published as **Allyl
Alcohol**.

**Two spellings of total organic carbon — 2 rows onto 1 flow.** `Organic
carbon` (`9a891f6c-937c-4226-9702-4a552973ae3f`) and `TOC, Total Organic
Carbon` (`73b225ab-ddc4-4a38-9ed0-ceedee987424`), both in groundwater, both
without a CAS number, land on **Total Organic Carbon** in the unconfined aquifer.

**Two groundwater rows of 1,4-butanediol — 2 rows onto 1 flow.** ecoinvent's
correspondence table sends the whole `1,4-Butanediol` family (110-63-4) to a
different substance, the epichlorohydrin adduct 2425-79-8, and this project
overrides every row of it back to EF 3.1's `butylene glycol`, which is the
same number ([#140](https://github.com/brightway-labs/brightway-flows/issues/140)).
EF 3.1 has no groundwater flow for it, so the `water / ground-` row
(`c5de5e4d-85cf-4102-9ff1-5248d8928ba1`) is sent to the same
unspecified-water flow as the `water / unspecified` row
(`d835b7aa-288b-4b3a-966b-3f64f36ed220`), and the two share it.

**Carbon into and out of a soil or biomass stock — 2 rows onto 1 flow.**
`Carbon, organic, increase in soil or biomass stock`
(`9c77a9ae-fcb2-48ed-ae10-4dda59dd6c61`) and `Carbon, organic, decrease in
soil or biomass stock` (`8c2fe757-6866-4ed2-9f89-81012ad774a0`), both
resources `in ground` in kilograms, are mapped by ecoinvent's own
correspondence table onto EF 3.1's single `Carbon, organic, in soil or
biomass stock`. The direction is in the sign of the amount in an inventory,
so the table treats the two as one flow, and the list follows it.

**Groundwater under two names — 2 rows onto 1 flow.** `Water, unspecified
natural origin` taken `in ground` (`478e8437-1c21-4032-8438-872a6b5ddcdf`)
and `Water, well, in ground` (`67c40aae-d403-464d-9649-c12695e43ad8`), which
ecoinvent files under `natural resource / in water` despite its name, are
both groundwater, and both land on **Groundwater**.

**Land use under two names — 10 rows onto 5 flows.** ecoinvent carries an
older and a newer spelling of the same land class side by side, and the
consensus land vocabulary names the class once:

| ecoinvent rows | Published as |
|---|---|
| `Occupation, annual crop` (`c5aafa60-495c-461c-a1d4-b262a34c45b9`), `Occupation, arable land, unspecified use` (`8c173ca1-5f74-4a6e-89e5-dd18e0f18d1a`) | Cropland (occupation) |
| `Transformation, from annual crop` (`f05cca02-ec18-4acc-9939-59658ff9a554`), `Transformation, from arable land, unspecified use` (`4d166779-88fd-441b-9537-f3b974e3bff7`) | From cropland |
| `Transformation, to annual crop` (`c3f83a91-4888-41a4-add9-fd01678a1e5f`), `Transformation, to arable land, unspecified use` (`2f1e926a-ec96-432b-b2a6-bd5e3de2ff87`) | To cropland |
| `Transformation, from unknown` (`12264257-7f8b-4afe-b3cb-3ac28ca1661a`), `Transformation, from unspecified` (`29630a65-f38c-48a5-9744-c0121f586640`) | From unspecified |
| `Transformation, to unknown` (`36965153-1daf-452a-8089-f4b5222c46ae`), `Transformation, to unspecified` (`512a5356-8059-4772-a43f-42e3c4f3d299`) | To unspecified |

## Registry numbers corrected

Twelve entries in `ecoinvent-3.12-manual-fixes.json` change a registry number.
Each is applied before the row is matched, so the row reaches the substance
the corrected number names.

| ecoinvent row(s) | Shipped | Corrected to | Why |
|---|---|---|---|
| `Uranium-238`, 9 rows (`543421e8-f0b3-45a2-b0ed-03489e878138` and eight others), kBq | 7440-61-1 | 24678-82-8 | 7440-61-1 is the CAS number for uranium the element, in kilograms. The rows are the activity of one isotope, U-238, which has its own CAS number. EF 3.1 makes the same slip and is corrected the same way, so the two lists agree ([#17](https://github.com/brightway-labs/brightway-flows/issues/17)). |
| `Alpha-lindane`, 7 rows | 58-89-9 | 319-84-6 | 58-89-9 is gamma-lindane, the insecticide. The alpha isomer of hexachlorocyclohexane has its own CAS number, and with the gamma number the row would have fused with lindane itself ([#26](https://github.com/brightway-labs/brightway-flows/issues/26)). |
| `Beta-lindane`, 7 rows | 58-89-9 | 319-85-7 | The same slip on the beta isomer. |
| `Delta-lindane`, 7 rows | 58-89-9 | 319-86-8 | The same slip on the delta isomer. |
| `Mefentrifluconazole`, soil / agricultural (`a1f19e68-e0ca-4d2b-a159-38e9036542f3`) | none | 1417782-03-6 | The row carries no identifier of any kind, and the trade-style name cannot be parsed into a structure, so nothing could place it. The number is the one PubChem records for BASF's triazole fungicide (Revysol) ([#19](https://github.com/brightway-labs/brightway-flows/issues/19)). |
| `Water, salt, sole`, natural resource / in water (`79238018-8ec1-4615-9469-2b0df95a43c3`) | 7732-18-5 | removed | *Sole* is brine, a saturated salt solution, and 7732-18-5 is the CAS number of the water molecule. A mixture does not carry the CAS number of one of its constituents; with it, brine would be published with water's chemistry. The synonym `oxidane`, the IUPAC name of water, is removed from the same row for the same reason. |
| `Nitrogen, organic bound`, 5 water rows | 7727-37-9 | removed | 7727-37-9 is N₂, the inert gas that makes up most of the air. Organically bound nitrogen is a nutrient load measured as nitrogen, spread over many compounds, and no registry number can name it. With the gas's number the rows fused with `Nitrogen` and were published as dinitrogen ([#57](https://github.com/brightway-labs/brightway-flows/issues/57)). The synonyms `dinitrogen` and `molecular nitrogen`, which ecoinvent added to these rows from 3.9.1 on, come off with it. |
| `Molybdenum VI`, 13 emission rows (one per context) | 7439-98-7 | 16065-87-5 | 7439-98-7 is molybdenum the metal. The rows name the hexavalent ion, write the formula `Mo+6`, and carried the ion's own number in release 3.9.1; every other metal ion in 3.12 carries its ion's number. With the metal's number the thirteen were published as `Molybdenum`, the element ([#181](https://github.com/brightway-labs/brightway-flows/issues/181)). |
| `Strontium II`, 13 emission rows (one per context) | 7440-24-6 | 22537-39-9 | 7440-24-6 is strontium the metal. The rows name the divalent ion, as 3.8 and every release from 3.10.1 do, and every other Roman-numeral metal carries its ion's number; with the metal's number the thirteen were published as `Strontium` while AGRIBALYSE's same-named rows sat on `Strontium(2+)` ([#198](https://github.com/brightway-labs/brightway-flows/issues/198)). |
| `Caesium I`, 5 water rows | 7440-46-2 | 18459-37-5 | The same slip on the monovalent caesium ion: 7440-46-2 is the metal, 18459-37-5 the ion, and the five water rows were published as `Cesium` beside AGRIBALYSE's `Cesium (I)` rows on `Cesium(1+)` (#198). |
| `Stibnite`, natural resource / in ground (`3e0034cd-21d6-4582-9fbf-09c26edd05df`) | 1345-04-6 | 1317-86-8 | Both numbers are antimony trisulfide, Sb₂S₃, but CAS registers the manufactured chemical and the mineral separately, and 1345-04-6 is the chemical. This row is ore dug out of the ground, so it takes the mineral's number — the one BAFU already uses for its stibnite, and the one that keeps the ore apart from EF 3.1's thirteen emission rows of the compound ([#123](https://github.com/brightway-labs/brightway-flows/issues/123)). |
| `Beta-cyfluthrin`, 8 rows | 68359-37-5 | 1820573-27-0 | 68359-37-5 is cyfluthrin, the commercial eight-isomer mixture. These rows are the beta product — the same molecules enriched in the two most insecticidally active diastereoisomeric pairs — and PPDB registers it separately (record 74; plain cyfluthrin is record 192). ecoinvent's own transition table retired the name Cyfluthrin for these uuids in favour of Beta-cyfluthrin, while EF 3.1 ships plain cyfluthrin under the same number, so with the shared number the beta rows fused with the plain substance. The shared EC number 269-855-7 stays; every release ships the rows and takes the same correction ([#188](https://github.com/brightway-labs/brightway-flows/issues/188)). |

### Other corrections that change what a row says

Five entries rename a row, three change a unit, and two restore a synonym —
`BAS 480F` on the two `Epoxiconazole` rows that ship without it ([#179](https://github.com/brightway-labs/brightway-flows/issues/179),
above). Most renames are
housekeeping — `Zirconia, as baddeleyite` becomes `Baddeleyite`, the mineral's
own name, and `Peat` becomes `Peat, horticulture` so that the kilogram row of
growing-medium peat stops landing on EF 3.1's megajoule row of fuel peat
([#89](https://github.com/brightway-labs/brightway-flows/issues/89)).
Three change the substance the row names, and belong here:

| ecoinvent row(s) | Shipped as | Corrected to | Why |
|---|---|---|---|
| `Silver-110`, 9 rows, kBq | Silver-110 | Silver-110m | Silver-110 is a ground state that decays in 25 seconds; what a reactor-effluent inventory reports is the metastable isomer Ag-110m, with a half-life of 250 days. EF 3.1 writes the same bare name and is corrected the same way ([#24](https://github.com/brightway-labs/brightway-flows/issues/24)). The registry number 14391-76-5 stays, and `Silver-110` is kept as a searchable alternative name. |
| `Ioxynil methyl ester`, 7 rows, 2436-73-9 | Ioxynil methyl ester | MCPA-methyl | 2436-73-9 contains no iodine, and every ioxynil compound does. The number is the methyl ester of MCPA, a different herbicide; ecoinvent's other three ioxynil rows all carry correct numbers, which is what says the name slipped rather than the CAS number ([#46](https://github.com/brightway-labs/brightway-flows/issues/46)). |
| `Granite`, 7 emission rows, 219714-96-2 | Granite | Penoxsulam | Nobody emits rock to surface water. The number is penoxsulam, a rice herbicide sold under the trade name *Granite*, and the name is the product label. The eighth `Granite` row (`a4375a18-172c-4f82-90b7-bca972f75548`, natural resource / in ground, no CAS number) is the rock and is left alone ([#140](https://github.com/brightway-labs/brightway-flows/issues/140)). |

The three unit corrections are the `(obsolete)` arable occupation rows —
conservation, conventional and reduced tillage (`fdb1b2d0-f537-401e-b845-1d93da512174`,
`e489cce4-a80f-417d-9ae6-9fc14cc7dd49`, `81e07a67-28e0-4392-a553-d86e54a9b8a9`)
— which ecoinvent ships in m² while its other 57 occupation flows, and every
one of EF 3.1's, are in m²·a. They are read as one year's occupation, with a
factor of 1.0, which is the conversion ecoinvent's own correspondence tables
state for them.
