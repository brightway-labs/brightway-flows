# Changes to ecoinvent 3.8

*Part of [What was changed in each source](index.md). What is still open about ecoinvent is on the issue tracker under the label [`ecoinvent`](https://github.com/brightway-labs/brightway-flows/issues?q=is%3Aissue+is%3Aopen+label%3Aecoinvent).*

ecoinvent 3.8 ships 4,421 elementary exchanges. On the 2026-08-29 build of
commit `54b0f9d` it was merged second, after ecoinvent 3.12: 4,406 of its
rows landed on a consensus flow that already existed (196 of them through
ecoinvent's own correspondence table), 13 added a new compartment under a
substance the list already had, and 2 minted a new substance. The
curated corrections to the list are in `ecoinvent-3.8-manual-fixes.json` (27
entries), the curated targets in `ecoinvent-match-overrides.json`, and the
identities of its dissolved-metal rows come from
`ecoinvent-canonical-identities.json`.

Most of what is on this page comes from one habit of the 3.8 release: it names
a metal in water, air or soil as the bare element — `Lead`, `Aluminium`,
`Copper` — and gives it the element's registry number, while every release
from 3.9.1 onwards names the same row, under the same uuid, `Lead II`,
`Aluminium III` or `Copper ion`. ecoinvent means one flow by one uuid, so the
newest release's name is taken as the vendor's current opinion of what the row
is, and 3.8's row is published under that identity. Nothing 3.8 wrote is
altered on the row itself; the newer name and number are what the matching
reads, and the row's provenance keeps 3.8's own words.

## One name, two substances

On the 2026-08-29 build of `54b0f9d` seven names in 3.8 landed on more than
one substance. Two of those — `Molybdenum` and `Carbon` — were defects and
have been corrected ([#181](https://github.com/brightway-labs/brightway-flows/issues/181), [#180](https://github.com/brightway-labs/brightway-flows/issues/180)); on the build of 2026-08-30 at
`9fbb0d5` five remain, and in each either the registry numbers 3.8 wrote
differ, or the newest release names some rows and no longer carries the
others.

**`Sodium`, eleven rows.** Eight — the four air compartments and the four soil
compartments, `235b2f02-ff98-4da9-82e2-e4246c7b7990` (air, unspecified) among
them — are `Sodium I` with the ion's number 17341-25-2 in 3.12 and are
published as `Sodium(1+)`. The other three, `460716f9-f5b8-4ee0-8198-545b24822124`
(air, lower stratosphere + upper troposphere), `73a1b292-e31d-4100-a413-304795a3656f`
(water, ground-) and `723f56f9-c68e-5692-a969-0fb2a70bce20` (water,
unspecified), are absent from 3.12, so nothing overrides 3.8's element number
7440-23-5, and they are published as `Sodium`, the metal.

**`Iron`, ten rows.** Nine air and soil rows are `Iron ion` in 3.12, which
gives them no registry number, and they are published as `Iron, Ion` — an
iron ion of unstated charge. The tenth, `e3043a7f-5347-4c7b-89ee-93f11b2f6d9b`
(water, ground-), is absent from 3.12, keeps 7439-89-6 and is published as
`Iron`, the element.

**`Calcium`, nine rows.** Eight are `Calcium II` (14127-61-8) in 3.12 and are
published as `Calcium(2+)`. `b24b66e6-633c-49bf-a6ce-1e81da0715ce` (air, lower
stratosphere + upper troposphere) is absent from 3.12 and stays `Calcium`.

**`Molybdenum`, fourteen rows — split on the 2026-08-29 build, and since
corrected.** Thirteen rows are `Molybdenum VI` in 3.12, but 3.12 left the
*element's* number 7439-98-7 on them (3.9.1 had the ion's, 16065-87-5), and a
CAS number outranks a name (see [When a name and a CAS number
disagree](../deciding/identity.md)), so all thirteen were published as
`Molybdenum`. The one row 3.12 no longer carries,
`697e8ecf-bdbe-4857-92c9-e01960c91db7` (air, lower stratosphere + upper
troposphere), was decided by 3.9.1's number and alone was published as
`Molybdenum(6+)`. The ion's number is now written on the name in the 3.10.1,
3.11 and 3.12 fixes files, and the newest-release identities are derived from
each release *with its fixes applied* — otherwise 3.12's raw number would have
been substituted back over the correction — so on the build of 2026-08-30 at `9fbb0d5` all
fourteen 3.8 rows are published as `Molybdenum(6+)` ([#181](https://github.com/brightway-labs/brightway-flows/issues/181)).

**`Carbon`, four rows in soil — split on the 2026-08-29 build, and since
corrected**, all carrying 7440-44-0. ecoinvent's own correspondence table
sends `14ea575b-5caa-4958-acf7-0bcc47f9cadf` (soil, unspecified) to EF 3.1's
`elemental carbon`, where it joins 3.8's own `Elemental carbon` row. The
agricultural, forestry and industrial rows
(`62859da4-f3c5-417b-a575-8b00d8d658b1`, `b72e46aa-9034-4dd2-856d-a43241d3b1f4`,
`7f8fd1ca-0412-4b2e-90fd-a9d294d947a3`) had no table row and were matched on
the CAS number and the name, which reached the consensus substance `Carbon`.
The curated target now covers those three uuids too — the same ones 3.12
ships — so they are published as `Elemental Carbon`, on EF's *soil,
unspecified* flow, the only soil flow EF publishes for it ([#180](https://github.com/brightway-labs/brightway-flows/issues/180)).

**`Water`, eleven rows.** The five air rows (`075e433b-4be4-448e-9510-9a5029c1ce94`,
air unspecified, and four others) are published as `Water vapour`; the six
water rows (`2404b41a-2eed-4e9d-8ab6-783946fdf5d6`, water unspecified, and
five others) as `Water`. The compartment decides.

**`Water, unspecified natural origin`, three resource rows.** The
sub-compartment decides: `831f249e-53f2-49cf-a93c-7cee105f048e` (in water) is
`Water`, `478e8437-1c21-4032-8438-872a6b5ddcdf` (in ground) is `Groundwater`,
and `2caa889e-8187-459d-963a-fa47a79c5378` (fossil well) is `Fossil groundwater`.

## An ionic charge was added or corrected

**Twenty-three bare element names published with a charge, 243 rows.** In each
case 3.8 wrote the element's name and the element's number, and the newest
release that carries the row writes the ion. The consensus list follows the
newest release and publishes the ion; the charge comes from the newer
release's registry number. For strontium and caesium the newest release
states the charge in the name but still writes the element's number, which
`ecoinvent-3.12-manual-fixes.json` corrects ([#198](https://github.com/brightway-labs/brightway-flows/issues/198)); the corrected identity
is what 3.8's rows follow.

| 3.8 name | 3.8 CAS | Newest release says | Published as | Rows |
|---|---|---|---|---|
| Aluminium | 7429-90-5 | Aluminium III, 22537-23-1 | Aluminium(3+) | 14 |
| Barium | 7440-39-3 | Barium II, 22541-12-4 | Barium(2+) | 14 |
| Beryllium | 7440-41-7 | Beryllium II, 22537-20-8 | Beryllium(2+) | 14 |
| Cadmium | 7440-43-9 | Cadmium II, 22537-48-0 | Cadmium(2+) | 9 |
| Calcium | 7440-70-2 | Calcium II, 14127-61-8 | Calcium(2+) | 8 |
| Chromium | 7440-47-3 | Chromium III, 16065-83-1 | Chromium(3+) | 9 |
| Cobalt | 7440-48-4 | Cobalt II, 22541-53-3 | Cobalt(2+) | 14 |
| Lead | 7439-92-1 | Lead II, 14280-50-3 | Lead(2+) | 14 |
| Lithium | 7439-93-2 | Lithium I, 17341-24-1 | Lithium(1+) | 3 |
| Manganese | 7439-96-5 | Manganese II, 16397-91-4 | Manganese(2+) | 14 |
| Mercury | 7439-97-6 | Mercury II, 14302-87-5 | Mercury(2+) | 14 |
| Molybdenum | 7439-98-7 | Molybdenum VI, 16065-87-5 (3.9.1's number, restored on 3.10.1–3.12 by a curated fix, [#181](https://github.com/brightway-labs/brightway-flows/issues/181)) | Molybdenum(6+) | 14 |
| Nickel | 7440-02-0 | Nickel II, 14701-22-5 | Nickel(2+) | 10 |
| Potassium | 7440-09-7 | Potassium I, 24203-36-9 | Potassium(1+) | 10 |
| Selenium | 7782-49-2 | Selenium IV, 22541-55-5 | Selenium(4+) | 14 |
| Cesium | 7440-46-2 | Caesium I, 7440-46-2 corrected to 18459-37-5 (#198) | Cesium(1+) | 5 |
| Silver | 7440-22-4 | Silver I, 14701-21-4 | Silver(1+) | 9 |
| Sodium | 7440-23-5 | Sodium I, 17341-25-2 | Sodium(1+) | 8 |
| Strontium | 7440-24-6 | Strontium II, 7440-24-6 corrected to 22537-39-9 (#198) | Strontium(2+) | 13 |
| Thallium | 7440-28-0 | Thallium I, 22537-56-0 | Thallium(1+) | 14 |
| Vanadium | 7440-62-2 | Vanadium V, 22537-31-1 | Vanadium(5+) | 9 |
| Zinc | 7440-66-6 | Zinc II, 23713-49-7 | Zinc(2+) | 9 |

The rows are the air and soil compartments, and for the elements with fewer
than 13 rows the missing compartments are ones 3.8 files under a different
name (`Cadmium, ion` in water) or ones 3.12 no longer carries. The 14th row,
where there is one, is `air / lower stratosphere + upper troposphere`, which
3.10.1 dropped and 3.9.1 decides. `Chromium VI` (18540-29-9, 14 rows) is
published as `Chromium(6+)`, which is the same statement in a different
notation and is not a change.

**Ten `X, ion` names in water given a charge, 50 rows.** 3.8 names the
dissolved form in the five water compartments `Cadmium, ion`, `Calcium, ion`,
`Chromium, ion`, `Lithium, ion`, `Nickel, ion`, `Potassium, ion`, `Silver,
ion`, `Sodium, ion`, `Vanadium, ion` and `Zinc, ion`, and on every one of them
3.8 itself wrote the specific ion's registry number — 22537-48-0 for cadmium,
14127-61-8 for calcium, and so on down the table above. The number states the
charge the name left out, and the rows are published as `Cadmium(2+)`,
`Calcium(2+)`, `Chromium(3+)`, `Lithium(1+)`, `Nickel(2+)`, `Potassium(1+)`,
`Silver(1+)`, `Sodium(1+)`, `Vanadium(5+)` and `Zinc(2+)`. `Vanadium, ion`
is the one where 3.8's own CAS number (22541-77-1) differs from the newest
release's (22537-31-1, `Vanadium V`); both are vanadium ions and the newer
one is followed.

**Six bare element names published as an ion of unstated charge, 59 rows.**
`Antimony`, `Arsenic`, `Copper`, `Iron`, `Tin` and `Titanium` in the air and
soil compartments carry the element's number in 3.8. From 3.9.1 onwards
ecoinvent names them `Antimony ion`, `Arsenic ion`, `Copper ion`, `Iron ion`,
`Tin ion` and `Titanium ion` and deletes the CAS number. The vendor deliberately
declined to say which ion, so the consensus list does the same and publishes
`Antimony, Ion`, `Arsenic, Ion`, `Copper, Ion`, `Iron, Ion`, `Tin, Ion` and
`Titanium, ion`; picking a charge would be a reinterpretation the vendor
refused.

**Six `X, ion` names whose registry number is a neutral or polyatomic species,
19 rows.** These are not charge corrections. The number 3.8 wrote settles
what the row is:

| 3.8 name | 3.8 CAS | Published as | Why |
|---|---|---|---|
| Ammonium, ion | 14798-03-9 | Ammonium | The number is the ammonium ion; the suffix was redundant |
| Chloride, ion | 16887-00-6 | Chloride | As above |
| Perchlorate, ion | 14797-73-0 | Perchlorate | As above |
| Sulfate, ion | 14996-02-2 | Sulfate | Beside 3.8's own `Sulfate` rows, 14808-79-8; both are the sulfate ion |
| Bicarbonate, ion | 71-52-3 | hydrogencarbonate | 71-52-3 is bicarbonate; the published name is the systematic one |
| Acrylate, ion | 79-10-7 | Acrylic Acid | 79-10-7 is acrylic acid, the neutral acid. The number outranks the name, so the row is published as the acid |

The last row is worth knowing about: an inventory that reports acrylate in
water under 3.8's name will find it on the acid's flow, because that is the
substance 3.8's registry number designates.

## Rows merged into one flow

77 consensus flows carry more than one 3.8 row. They fall into five groups.

### Ore-grade resource names

ecoinvent 3.8 names a mined metal once plainly (`Copper, in ground`) and once
per deposit it has data for (`Copper, 0.52% in sulfide, Cu 0.27% and Mo
8.2E-3% in crude ore, in ground`). An ore grade describes the deposit, and a
resource flow is the metal taken out of it, so every one of these lands on the
plain row's substance and the grade is kept as nothing more than the source
row's own name. 42 substances, 146 rows in all:

| Substance | 3.8 rows merged | The plain row |
|---|---|---|
| Copper | 15 | `a9ac40a0-9bea-4c48-afa7-66aa6eb90624` Copper, in ground |
| Gold | 15 | `d080e6a4-42c6-484e-b5d7-d74693aec7d9` Gold, in ground |
| Silver | 13 | `361a64cb-ab76-4a72-9ea1-c07d6a20c124` Silver, in ground |
| Molybdenum | 8 | `e5a3dff5-72dc-5287-893c-597dd4a19566` Molybdenum, in ground |
| Nickel | 6 | `974213ef-1ba0-40e5-bc7b-52ef099e9e09` Nickel, in ground |
| Lead | 4 | `fbcb9c7a-eea7-4694-ba6c-568e01d28883` Lead, in ground |
| Palladium | 4 | `edc69c63-a776-4dbf-acbf-e0368914980a` Palladium, in ground |
| Platinum | 4 | `d13b2665-505d-49e2-8edd-dc966b0342af` Platinum, in ground |
| Rhodium | 4 | `4803f22f-6950-489b-914d-fa953a8081f6` Rhodium, in ground |
| Titanium | 4 | `2f033407-6060-4e1e-868c-9f362d10fdb2` Titanium, in ground |
| Zinc | 4 | `be73218b-18af-492e-96e6-addd309d1e32` Zinc, in ground |
| Fluorine | 3 | `3048af84-1d72-5e3f-a739-b2d7fa7d4773` Fluorine, in ground |
| Iron | 3 | `8ce3ff02-7a1e-48e3-881e-3248b944f28a` Iron, in ground |
| Phosphorus | 3 | `483ae3c5-4eb0-46e4-b811-a72ad391716b` Phosphorus, in ground |
| Bromine, Cadmium, Cerium, Chromium, Cobalt, Europium, Fluorspar, Gadolinium, Gallium, Helium, Indium, Iodine, Kaolinite, Kieserite, Lanthanum, Lithium, Magnesite (published as Magnesium Carbonate), Magnesium, Manganese, Neodymium, Praseodymium, Rhenium, Samarium, Sylvite (Potassium Chloride), Tantalum, Tellurium, Tin, Zirconium | 2 each | one graded row beside `X, in ground` |

The titanium group deserves a second look. `Titanium, in ground`
(`2f033407-6060-4e1e-868c-9f362d10fdb2`) carries the element's number
7440-32-6; the three rows merged with it are titanium *dioxide* ores —
`TiO2, 54% in ilmenite, 18% in crude ore, in ground`
(`90a94ea5-bca4-483d-a591-2e886c0ff47f`) and `TiO2, 54% in ilmenite, 2.6% in
crude ore, in ground` (`78cd4852-e7b9-4301-adf7-51e730b0356a`), both
13463-67-7, and `TiO2, 95% in rutile, 0.40% in crude ore, in ground`
(`ec0fa5ce-51b4-4792-a8e8-c4ee668eddc3`), 1317-80-2, which Common Chemistry
names `Rutile`. They land on `Titanium` because ecoinvent's own
correspondence table sends them there — and they are converted on the way: a
kilogram of the oxide is 0.599 kg of titanium, and `ecoinvent-match-overrides.json`
has carried that factor on all three uuids since the ruling in
[#118](https://github.com/brightway-labs/brightway-flows/issues/118). The
published source reference carries it as the conversion multiplier. BAFU's
two rows of the same ores take the same factor, and an expectation now holds
all five rows to it ([#182](https://github.com/brightway-labs/brightway-flows/issues/182), which was opened on a misreading and closed
against that check).

??? note "All 146 ore-grade rows, by substance"

    Copper (`fe0acd60-3ddc-11dd-ae5c-0050c2490048`): `1aee4aa7-32e0-48e7-a6b5-73d8acf672d3`,
    `1b35070a-eb57-4f0f-a27f-5ba181ff0d4d`, `19988f5b-a9a6-48f3-9e8e-150b66a1bf12`,
    `79df5650-160a-4ab7-a14f-cc8162877f4a`, `ed5ace5c-a203-4816-b33b-9fe0c5f0f519`,
    `31998285-fb5c-411d-b853-ce78be2a0b49`, `c8f18160-6937-4bb9-ad0c-dffa942ca41e`,
    `b569dc97-52fe-4e39-9627-183b1002c287`, `73b7f080-b7ae-417c-b740-b4c9eabfb35a`,
    `8508a83c-6a37-4159-93cc-21a2645390ab`, `5afa470c-ab8c-4ec3-8a18-5c0bed973571`,
    `704399e3-cf6b-483d-84f5-466e91a9d17c`, `4f684798-3870-45a1-b5f2-aa3444c0b8d6`,
    `01b9f1e8-4423-5393-ba63-2067935bdb13`, `a9ac40a0-9bea-4c48-afa7-66aa6eb90624`.

    Gold (`fe0acd60-3ddc-11dd-a2bf-0050c2490048`): `ff741136-d6ee-444a-a15b-3b308e376db8`,
    `7cd1d217-70a7-4452-abc4-3b1100763d6d`, `a8896ed6-4c9d-4b06-a356-49d8cdd9e9d7`,
    `2d65a3f7-2a10-4a10-ac9e-a0cc7cd57979`, `95268685-7bea-4883-a412-119d7e88372c`,
    `8c888d2b-d608-4dac-bad5-1c2a17050838`, `3eece329-cf79-4167-93c2-b8d7d7eb5058`,
    `d28f9d42-5df5-41c3-be59-fdfa7ff57112`, `c7d38707-3b22-4fb1-b001-0c8cad496a60`,
    `4f5aad55-54d2-4628-a509-b28ef1929bb4`, `d6c7644f-0d7c-4bb3-b8bb-686ebede951e`,
    `cf3d3dbc-0e4b-402d-92a1-8ea6b4869ed5`, `16ddda12-daf4-460c-83fb-c361bdbbc9e9`,
    `60b67dea-a332-4d8d-968b-df8f3df6088a`, `d080e6a4-42c6-484e-b5d7-d74693aec7d9`.

    Silver (`172ab2d8-6556-11dd-ad8b-0800200c9a66`): `c15f6c4d-bf7a-4a7c-91c6-53aad6a630a8`,
    `bc153c00-6c93-412f-aadc-750f2fc6f9c7`, `14946240-b1ee-412c-b900-ed5728a4e684`,
    `d02343bd-b00d-4fb3-9bda-2e8183f3b012`, `d76320f7-6761-4864-92a6-660fa3453ffa`,
    `6f70e7c7-ef61-4489-b4f3-157e7e8541ef`, `781dda0c-ffeb-4664-9667-7506ce6269b9`,
    `ed8c57b5-6012-4f21-8b70-92a85923786a`, `adfff256-b19a-4083-9783-ffbc7a7cb437`,
    `cfaa80f4-8e19-4fd6-942a-eaea14812896`, `eaa3e9d4-68d6-4267-a7a5-48b141c3861e`,
    `45ed0c16-0e34-45f1-8bf9-3b1ce8489e73`, `361a64cb-ab76-4a72-9ea1-c07d6a20c124`.

    Molybdenum (`fe0acd60-3ddc-11dd-a2be-0050c2490048`): `06874cbb-2daf-4981-a55e-2c38be5b7277`,
    `5514ccd2-469f-4074-9905-529154e7f742`, `ac8571b8-b00b-479d-93cf-b9374feaee05`,
    `a76cf135-2be1-4e53-9423-9211acd100f1`, `30fed59d-d722-482f-be4f-f3d93bdd2527`,
    `719def62-0941-4264-bc54-97093d847d7a`, `eda28c96-8899-4d84-bf18-35c3f1de518e`,
    `e5a3dff5-72dc-5287-893c-597dd4a19566`.

    Nickel (`08a91e70-3ddc-11dd-96d1-0050c2490048`): `0d7f8b87-12f4-4e83-a5a2-854e2f2b47de`,
    `febbfa6e-44d4-42a0-abcd-aec8a428f75e`, `86c6e6cd-c2f5-4977-bad6-ce9cd48cf721`,
    `e47e4e5f-6528-413d-a8fb-1cd1875fbd73`, `f09c3144-a268-4bed-8ca2-63005b6ef75f`,
    `974213ef-1ba0-40e5-bc7b-52ef099e9e09`.

    Lead (`fe0acd60-3ddc-11dd-ae5d-0050c2490048`): `4f701354-38fd-40b0-8c90-4c1df36ec45a`,
    `2d9f9c6b-8dca-4641-8ff9-53cb8beabd13`, `4df0eac4-44bb-46b6-b588-e3513a1ead2f`,
    `fbcb9c7a-eea7-4694-ba6c-568e01d28883`.

    Palladium (`e2fb2bc2-6555-11dd-ad8b-0800200c9a66`): `4b8ac2cb-3fa6-4047-a9ab-183d9e63ccac`,
    `535bbc83-033b-42fe-9a68-8dc9eb420385`, `669ab0eb-c020-4b98-bfe4-e0989013121a`,
    `edc69c63-a776-4dbf-acbf-e0368914980a`.

    Platinum (`041fab30-6556-11dd-ad8b-0800200c9a66`): `3250f566-58bc-46d3-ab88-1d2e23ca3e1b`,
    `636a8446-9899-43a6-b4bf-213f25d69c88`, `68be4a67-89e0-4cfe-a089-fa8706de230e`,
    `d13b2665-505d-49e2-8edd-dc966b0342af`.

    Rhodium (`1729c889-6556-11dd-ad8b-0800200c9a66`): `7005a356-23d8-4d38-9dbc-fa75401b400e`,
    `f7360584-688a-4b6f-bc4a-db00a1e7b022`, `ba2da2fe-3420-45d1-9d1b-58b9e99714eb`,
    `4803f22f-6950-489b-914d-fa953a8081f6`.

    Titanium (`2906898f-6556-11dd-ad8b-0800200c9a66`): `78cd4852-e7b9-4301-adf7-51e730b0356a`,
    `ec0fa5ce-51b4-4792-a8e8-c4ee668eddc3`, `90a94ea5-bca4-483d-a591-2e886c0ff47f`,
    `2f033407-6060-4e1e-868c-9f362d10fdb2`.

    Zinc (`64b1ce4a-6556-11dd-ad8b-0800200c9a66`): `3faef344-9e52-47a3-a317-e17b824cc540`,
    `f8f1ba14-9934-4678-8a78-e2cf1fce7775`, `c3b2ba62-b158-47b1-8e1e-e76156e5292a`,
    `be73218b-18af-492e-96e6-addd309d1e32`.

    Fluorine (`08a91e70-3ddc-11dd-9408-0050c2490048`): `e5fadc0b-1d79-4604-ac32-fd3321f27933`,
    `355785ee-56e0-455b-aaa6-bee43c82b49c`, `3048af84-1d72-5e3f-a739-b2d7fa7d4773`.

    Iron (`08a91e70-3ddc-11dd-959a-0050c2490048`): `f77aacc3-2c22-4bda-99ab-fe1110a1b891`,
    `99c56f25-9ebb-4e6a-a3e2-e4dc61e9d697`, `8ce3ff02-7a1e-48e3-881e-3248b944f28a`.

    Phosphorus (`041f5cea-6556-11dd-ad8b-0800200c9a66`): `a64e65fe-3c33-44f1-bd2d-ab7fac07653f`,
    `9a7380d1-6e23-48ad-b35a-14bd1ecb3133`, `483ae3c5-4eb0-46e4-b811-a72ad391716b`.

    Pairs (graded row, plain row): Bromine `61341186-aac8-4088-a2b7-ba50093bab6c`,
    `45d6f26b-596b-5182-8c08-d6d975ff4efe` — Cadmium `621b1cf1-9b47-4c44-b71e-ebeb9afd9bbc`,
    `bf377e4f-3a95-4ce2-a9ba-66ee31f00f60` — Cerium `7a636bea-94c0-4774-a791-2512b7fbda94`,
    `4057f8b4-f20a-59c9-9bb7-fdeaf5ad106d` — Chromium `ef6dd09f-bddc-49b4-a207-dbaec2f07bb5`,
    `e189e2d4-3d3f-4ada-b302-91611784311f` — Cobalt `02e8658e-3c88-404c-865d-4d4934661ea6`,
    `d0779a5e-6969-4144-954e-ceb81fb83f15` — Europium `7c954971-4bce-41db-9e8b-2b2f049539d7`,
    `3d73ec21-de4d-5b68-b504-4ef59e15bd0e` — Fluorspar `de2d220b-9fe8-4c39-bef7-a76c00d6ff33`,
    `0fa4f51e-b0dc-5d11-84d3-b32f0f3c88d5` — Gadolinium `b878ca93-d699-421e-a4b6-f694dc627062`,
    `f55e2203-ef91-50bf-8f5a-119bb210522c` — Gallium `e2c5109f-9a68-4828-b824-eb2193864803`,
    `0878c1c6-4c1d-4f90-a2de-a9383855d5c6` — Helium `4c276350-de3d-4bba-90a9-0d0a9ad097c0`,
    `b6381644-4633-5bc6-9e90-c5d0514f9363` — Indium `e5cbe371-d33e-46ef-a832-a176f5e28520`,
    `7aaf1a4e-f72f-5dc6-b999-de4e99948eb8` — Iodine `7de77239-7074-4443-9dc9-4492c5e2ef35`,
    `36a3d172-7373-507f-85bd-12b8ba31a6d4` — Kaolinite `ee540366-b970-46af-94d8-4c253ded5577`,
    `81ff5c0b-c44f-534e-a55e-8fc017e33dd2` — Kieserite `38eff837-5465-47a9-a1c9-e1edd70922ef`,
    `f3380341-7f76-5423-9704-c25ccf777a39` — Lanthanum `d61418f3-c1a4-4b95-807c-06b7e1fa2915`,
    `176598c1-699c-5dd8-8c33-d269ff7f5edd` — Lithium `a9ad523f-b721-4f07-ad9f-584053f3454d`,
    `7d2c1cdd-a64a-5936-a577-5b82db0c0d1b` — Magnesite `d2bf022d-9cbf-4f19-a8ec-7f507746942b`,
    `a4bab069-74a9-5b4c-8d6e-5ca984cd9ecd` — Magnesium `752d138f-3723-42c1-bf5c-ca5316809c4c`,
    `247f3d96-7da2-5adf-a399-65745bc042fb` — Manganese `9f9f1f14-6eee-4067-b4a5-80e75fc7b295`,
    `c2586875-bb56-4b1e-84c5-5ff255a1108b` — Neodymium `c970e81e-1c4e-4f21-814c-0c25444f41d2`,
    `db0c855c-e9ef-58d9-97cc-960e646fc882` — Praseodymium `909bc093-18b2-4a7e-8131-16f68eebc193`,
    `35da65ff-7287-571d-b859-13d398ac5182` — Rhenium `a3930b4d-74da-4489-9a50-d175c25d4fe8`,
    `a2e6fb74-b047-5697-b5dd-e28cc68f29e6` — Samarium `f46130cc-dbd4-4a3b-a537-5efbcd89063f`,
    `cf791833-26bc-5207-a9bd-6ddcd8ac7625` — Sylvite `d80610f2-df83-4e2a-9dc3-f74fced6577f`,
    `b1e13de6-e0a4-56b6-b096-7ab1171d60e3` — Tantalum `5f1d740e-804d-4080-8ef9-aeaa0d8e1115`,
    `775fdf03-b0bb-5c25-b14d-107231d5b2f0` — Tellurium `7a81cd45-7f4c-40b3-989c-6a65f42df999`,
    `7b6da1f2-e191-5a77-ae06-af96201f5803` — Tin `31b4eea9-640e-4056-ac2f-0555627af18a`,
    `53d5ef26-66d8-4536-afa2-2f6b114189ba` — Zirconium `fcee6eab-e906-4ddf-bc14-2b131b937893`,
    `cd2932c5-a486-4bf1-99b8-815d8a7ce11a`.

### `[Deleted]` tombstones beside the live row

3.8 carries three rows whose name begins `[Deleted]` and which sit beside a
live row in the same compartment, with the same unit and the same registry
number. ecoinvent's own chain of correspondence tables (3.8 to 3.9 to EF 3.1)
deletes them outright; a curated target in `ecoinvent-match-overrides.json`
sends each one where its sibling goes instead, so an inventory still using the
old row is not dropped.

| Tombstone | Live sibling | Published as |
|---|---|---|
| `c5c25aa6-d630-40bd-bed7-4e718c877ef4` [Deleted]Tri-allate, soil / agricultural, 2303-17-5 | `e5fa0589-d03f-5179-bc91-5c4b69f79bac` Triallate | Triallate |
| `d07867e3-66a8-4454-babd-78dc7f9a21f8` [Deleted]Carfentrazone ethyl ester, 128639-02-1 | `91d68678-7ed7-417a-86a7-a486c7b8a973` Carfentrazone-ethyl | Carfentrazone-ethyl |
| `831f48fc-ca00-4534-9ede-730190b3bee0` [Deleted]Fluorochloridone, 61213-25-0 | `a0544534-e298-46a9-bbd2-949902ac1487` Fluorochloridone | Flurochloridone |

### Two spellings of one substance in one compartment

All in `air / unspecified` unless stated; both rows carry the same registry
number except where noted.

| Rows | Published as |
|---|---|
| `9c2a7dc9-8b1f-46ba-bc16-0d761a4f6016` Ethene · `90f722bf-cb9b-571a-88fc-34286632bdc4` Ethylene | Ethylene |
| `3fa03c96-b976-4f0f-8089-220968515ee1` Ethene, trichloro- · `a0950325-06dc-5ca0-84b6-983c9e6ccf74` Trichloroethylene | Trichloroethene |
| `3df4c2f4-c854-4493-b514-f2f3accdc307` Naphthalene · `7346ba9f-476c-4343-9f37-d1bb174eed6d` Naphtalene | Naphthalene |
| `ec420d84-577b-402e-bd90-f8a4b2310135` Methyl amine · `be13179a-7e8b-57f8-9852-137ce88a1525` Methylamine | Methylamine |
| `c941d6d0-a56c-4e6c-95de-ac685635218d` Hydrogen chloride · `c9a8073a-8a19-5b9b-a120-7d549563b67b` Hydrochloric acid | Hydrogen Chloride |
| `9547aff9-e1fc-5fad-a674-9b9a9fdb1c9c` Dichlorodimethylsilane · `d0cde0b1-afcc-5179-8895-0aacba2e15a1` Dimethyldichlorosilane | Dichloro(dimethyl)silane |
| `19d4089d-11a2-520c-84a0-b307ec625a0c` Pyrethrine · `69edbf6f-66cb-5e8f-8741-f34a16fed5ca` Pyrethrum (soil / agricultural) | Pyrethrins |
| `f9c73aca-3d5c-4072-81dd-b8e0643530a6` Quizalofop ethyl ester · `9ae11925-3df9-5fde-b7af-1627c0818347` Quizalofop-ethyl (soil / agricultural) | Quizalofop-ethyl |
| `66a6dad0-e450-4206-88e1-f823a04f8b1d` Haloxyfop- (R) Methylester, no CAS · `a058168e-9a1e-5126-80b6-2d202e746835` Haloxyfop-P-methyl, 72619-32-0 (soil / agricultural) | Haloxyfop- (R) Methylester — the unnumbered row reached the substance on its name's synonyms |
| `2a042136-80fd-4c1c-8996-65a7985497d3` Cyclohexane (for all cycloalkanes) · `18282ab8-5b46-4c56-9038-588ed28a4a95` Hydrocarbons, aliphatic, alkanes, cyclic (air / urban air close to ground) | Hydrocarbons, Aliphatic, Alkanes, Cyclic — ecoinvent itself retired the first name for the second between 2.2 and 3.12 |
| `5f7aad3d-566c-4d0d-ad59-e765f971aa0f` Methane, fossil, 74-82-8 · `b53d3744-3629-4219-be20-980865e54031` Methane, 14493-06-2 (air / urban air close to ground) | Methane (fossil) — the bare `Methane` row is placed by ecoinvent's own correspondence table. 14493-06-2 is not a registered number in Common Chemistry |
| `e7f1df40-788a-4403-81ea-e5e9e84e32d7` Cypermethrin · `b6e1f836-2b5c-4bd5-bc8c-af065ee7c230` Zeta-cypermethrin · `ce2ceed1-2503-4566-8175-f4456dbac42b` Alpha-cypermethrin · `6098e65f-3e52-5672-89b4-519dd8987d19` Beta-cypermethrin (soil / agricultural), all 52315-07-8 | Cypermethrin — ecoinvent gives the isomer-enriched products the parent's number, and the CAS number decides |
| `620d3423-2376-4fcc-bb89-2d468f8b2df8` Cypermethrin · `781bfb14-d34f-4f99-9d15-d67171d6fc24` Zeta-cypermethrin (air / non-urban air or from high stacks) | Cypermethrin |

### An ion beside its own element or its own `, ion` row

In `water / ground-` and `water / unspecified`, 3.8 sometimes carries a row
under the bare name and another under `X, ion`, with the *same* ion registry
number on both, so they were one substance in the vendor's own terms:

| Rows | Published as |
|---|---|
| `4569494e-085e-413a-8fef-63a3c419e0cf` Lithium · `09cf7c11-0269-4fc1-a5f3-47121a7882d3` Lithium, ion (water / ground-, both 17341-24-1) | Lithium(1+) |
| `56815b4f-6138-4e0b-9fac-c94fd6b102b3` Nickel · `e030108f-2125-4bcb-a73b-ad72130fcca3` Nickel, ion (water / ground-, both 14701-22-5) | Nickel(2+) |
| `c21a1397-82dc-427a-a6cb-c790ba2626f4` Potassium · `a07b8a8c-8cab-4656-a82f-310e8069e323` Potassium, ion (water / ground-, both 24203-36-9) | Potassium(1+) |
| `6d25e386-4ef9-4d40-85c6-e694f523a4da` Chloride · `c4e01cfb-2f50-52d5-8177-1518ad8b7bea` Chloride, ion (water / unspecified, both 16887-00-6) | Chloride |
| `28bca51a-6cc7-46af-961a-fd2b675a1376` Sulfate, 14808-79-8 · `f3e5bff4-5bdf-55d7-8dd9-3cac7b09e57f` Sulfate, ion, 14996-02-2 (water / unspecified) | Sulfate |
| `31eacbfc-683a-4d36-afc1-80dee42a3b94` Sulfate · `b8c794de-ac20-47f6-ae87-84d91e95da93` Sulfate, ion (water / ground-) | Sulfate |
| `14ea575b-5caa-4958-acf7-0bcc47f9cadf` Carbon · `bc86067c-20e8-46e7-8419-de1eee73ccdd` Elemental carbon (soil / unspecified, both 7440-44-0) | Elemental Carbon |

### Everything else

| Rows | Published as | Why |
|---|---|---|
| `db4566b1-bd88-427d-92da-2d25879063b9` Water, 7732-18-5 · `8bdedc25-af46-4c46-9b3a-670d0c177d8f` Fresh water (obsolete) (water / surface water) | Water, surface water | The obsolete row has no CAS number and reaches water as a material |
| `4f0f15b3-b227-4cdc-b0b3-6412d55695d5` Water · `91861063-1826-4860-9957-7c5bde5817a6` Salt water (obsolete) (water / ocean) | Water, ocean | As above |
| `67c40aae-d403-464d-9649-c12695e43ad8` Water, well, in ground (natural resource / in water) · `478e8437-1c21-4032-8438-872a6b5ddcdf` Water, unspecified natural origin (natural resource / in ground) | Groundwater | A well draws groundwater, and an unspecified intake from the ground is groundwater |
| `e4e9febc-07c1-403d-8d3a-6707bb4d96e6` (air / unspecified) · `6d89125e-e9b7-4d7e-a1fc-ada45dbd8815` (air / lower stratosphere + upper troposphere), both Carbon dioxide, from soil or biomass stock | Carbon Dioxide (land Use Change), air unspecified | ecoinvent's correspondence table sends both to EF 3.1's single land-use-change CO₂ flow; the stratosphere row loses its compartment |
| `c5de5e4d-85cf-4102-9ff1-5248d8928ba1` (water / ground-) · `d835b7aa-288b-4b3a-966b-3f64f36ed220` (water / unspecified), both 1,4-Butanediol | Butylene Glycol, water unspecified | The vendor's table maps both to the same EF 3.1 flow |
| `73b225ab-ddc4-4a38-9ed0-ceedee987424` TOC, Total Organic Carbon · `9a891f6c-937c-4226-9702-4a552973ae3f` Organic carbon (water / ground-) | Total Organic Carbon | Two names for one measurement |
| `43b2649e-26f8-400d-bc0a-a0667e850915` Gangue, bauxite, in ground · `0d218f74-181d-49b6-978c-8af836611102` Gangue, in ground | Inert Rock | Waste rock is waste rock whichever ore it came with |
| `c5aafa60-495c-461c-a1d4-b262a34c45b9` Occupation, annual crop · `8c173ca1-5f74-4a6e-89e5-dd18e0f18d1a` Occupation, arable land, unspecified use | Cropland | One land class; the same pair for `Transformation, from` (`f05cca02-ec18-4acc-9939-59658ff9a554`, `4d166779-88fd-441b-9537-f3b974e3bff7`) and `Transformation, to` (`c3f83a91-4888-41a4-add9-fd01678a1e5f`, `2f1e926a-ec96-432b-b2a6-bd5e3de2ff87`) |
| `29630a65-f38c-48a5-9744-c0121f586640` Transformation, from unspecified · `12264257-7f8b-4afe-b3cb-3ac28ca1661a` Transformation, from unknown; and `512a5356-8059-4772-a43f-42e3c4f3d299` / `36965153-1daf-452a-8089-f4b5222c46ae` for `to` | From unspecified / To unspecified | `Unknown` and `unspecified` say the same thing about a land class |

## Registry numbers corrected

Fourteen entries in `ecoinvent-3.8-manual-fixes.json` change a registry
number, and they are applied before any matching runs. Nine of them make 3.8
say what a later release already says about the same uuid: the vendor
corrected its own CAS number, and the older export is read as meaning what the
newer one states.

| Row | 3.8 number | Corrected to | Why |
|---|---|---|---|
| Uranium-238, all 10 rows (`543421e8-f0b3-45a2-b0ed-03489e878138` and nine others) | 7440-61-1 | 24678-82-8 | 7440-61-1 is uranium the element; the nuclide has its own CAS number. EF 3.1 and 3.12 carry the same error and the same correction, so the lists agree on what a becquerel of U-238 is ([#17](https://github.com/brightway-labs/brightway-flows/issues/17)) |
| `79238018-8ec1-4615-9469-2b0df95a43c3` Water, salt, sole | 7732-18-5 | removed | *Sole* is brine, a mixture; 7732-18-5 is the water molecule. A mixture does not carry the CAS number of one of its constituents |
| Nitrogen, organic bound, 5 water rows | 7727-37-9 | removed | 7727-37-9 is dinitrogen gas. Organically bound nitrogen is a measurement over many compounds and has no registry number; with the gas's number the rows would have fused with `Nitrogen` ([#57](https://github.com/brightway-labs/brightway-flows/issues/57)) |
| `3ed5f377-344f-423a-b5ec-9a9a1162b944` Gas, mine, off-gas, process, coal mining | 8006-14-2 | removed | 8006-14-2 is natural gas. ecoinvent removed it from this row in 3.10.1; with it, coal-mine gas and `Gas, natural` (`7c337428-fb1b-45c7-bbb2-2ee4d29e17ba`) were one substance ([#80](https://github.com/brightway-labs/brightway-flows/issues/80)) |
| `b157329c-4179-5491-97c4-649900954ffa` Amine oxide | 1643-20-5 | removed | 1643-20-5 is one amine oxide (dodecyldimethylamine oxide); the row is the family, which 3.9.1 renamed `Amine oxides` and gave no CAS number ([#123](https://github.com/brightway-labs/brightway-flows/issues/123)) |
| `1d8560a8-23e0-57f0-ade2-69103c953de8` Diphenylether-compound | 101-84-8 | removed | 101-84-8 is diphenyl ether itself; the row is the family of diphenyl-ether compounds, which 3.9.1 renamed and gave no CAS number (#123) |
| `e07b4402-abe3-4346-8c42-051c5983bd1e` Zirconia, as baddeleyite, in ground | 1314-23-4 | 12036-23-6 | Both are zirconium dioxide; 12036-23-6 is baddeleyite, the mineral that is mined, and is the CAS number 3.10.1 onwards use ([#118](https://github.com/brightway-labs/brightway-flows/issues/118)) |
| `3e0034cd-21d6-4582-9fbf-09c26edd05df` Stibnite, in ground | 1345-04-6 | 1317-86-8 | Both are antimony trisulfide; 1345-04-6 is the manufactured compound and 1317-86-8 is the mineral. A resource dug from the ground is the mineral, and BAFU already uses the mineral's number (#123) |
| `a4375a18-172c-4f82-90b7-bca972f75548` Granite, in ground | 219714-96-2 | removed | 219714-96-2 is penoxsulam, a rice herbicide sold under the trade name *Granite*. ecoinvent removed it in 3.11 ([#140](https://github.com/brightway-labs/brightway-flows/issues/140)) |
| Fenpropimorph (one row) | 67306-03-0 | 67564-91-4 | Both are fenpropimorph; 67564-91-4 is the racemic fungicide that is characterised, and the CAS number 3.12 uses ([#130](https://github.com/brightway-labs/brightway-flows/issues/130)) |
| `eead2933-c2be-4a53-a0bd-bd33b67e4145` Borax, in ground | 1330-43-4 | 1303-96-4 | 1330-43-4 is anhydrous sodium tetraborate; 1303-96-4 is the decahydrate, mineral borax, which is what is mined and what 3.10.1 onwards say (#140) |
| `9877ce00-65f8-4c0c-9fcf-92aa53a2c9c0` Diatomite, in ground | 7631-86-9 | 61790-53-2 | 7631-86-9 is pure silicon dioxide; 61790-53-2 is diatomite, the sedimentary rock, and is what 3.10.1 onwards say (#140) |
| `0fa4f51e-b0dc-5d11-84d3-b32f0f3c88d5` Fluorspar, in ground | 7789-75-5 | 14542-23-5 | 7789-75-5 is calcium difluoride the compound; 14542-23-5 is fluorite, the mineral, which 3.12 uses and 3.8's own `Fluorspar, 92%, in ground` already carries |
| Beta-cyfluthrin, both rows | 68359-37-5 | 1820573-27-0 | 68359-37-5 is cyfluthrin, the commercial eight-isomer mixture. These rows are the beta product — the same molecules enriched in the two most insecticidally active diastereoisomeric pairs — and PPDB registers it separately (record 74; plain cyfluthrin is record 192). ecoinvent's own transition table retired the name Cyfluthrin for these uuids in favour of Beta-cyfluthrin, while EF 3.1 ships plain cyfluthrin under the same number, so with the shared number the beta rows fused with the plain substance. The shared EC number 269-855-7 stays; every release ships the rows and takes the same correction ([#188](https://github.com/brightway-labs/brightway-flows/issues/188)) |

### Other corrections in the same file

These change something other than a registry number, and are listed because
a reader looking for the row would otherwise find a different name or unit.

| Row | Change | Why |
|---|---|---|
| Silver-110, 10 rows | Name → `Silver-110m` | Silver-110 is a 24-second ground state; what a reactor effluent inventory reports is the 250-day isomer Ag-110m. The registry number 14391-76-5 is kept; `Silver-110` is kept as an alternative name ([#24](https://github.com/brightway-labs/brightway-flows/issues/24)) |
| Ioxynil methyl ester (2436-73-9) | Name → `MCPA-methyl` | 2436-73-9 contains no iodine: it is the methyl ester of MCPA. The number is right and the name was wrong ([#46](https://github.com/brightway-labs/brightway-flows/issues/46)) |
| `c5035ce2-5ee5-431f-a287-4b25da42be74` Peat, in ground | Name → `Peat, horticulture` | EF 3.1 has two peats: fuel peat in MJ and growing-medium peat in kg. This kilogram row is the second, and under the old name it reached the first ([#89](https://github.com/brightway-labs/brightway-flows/issues/89)) |
| Zirconia, as baddeleyite, in ground | Name → `Baddeleyite` | The mineral's own name; zirconia *is* ZrO₂, so the old name said it twice (#118) |
| Amine oxide; Diphenylether-compound | Names → `Amine oxides`; `Diphenylether compounds` | The names 3.9.1 onwards use for these families (#123) |
| `3ed5f377-344f-423a-b5ec-9a9a1162b944` Gas, mine, off-gas, process, coal mining | Unit m3 → sm3 | The unit every release from 3.9 gives this row; a cubic metre of gas is not an amount until its conditions are stated |
| `fdb1b2d0-f537-401e-b845-1d93da512174`, `e489cce4-a80f-417d-9ae6-9fc14cc7dd49`, `81e07a67-28e0-4392-a553-d86e54a9b8a9` (three `Occupation,` rows) | Unit m2 → m2·a | Fifty-seven of ecoinvent's sixty occupation flows are in m2·a; these three are a slip, and ecoinvent's own table treats them as one year's occupation ([#111](https://github.com/brightway-labs/brightway-flows/issues/111)) |
| `419de9f0-ee00-4e95-9556-c8f06b17beec` Carbon dioxide, non-fossil, resource correction | Synonym `Carbon dioxide` restored | 3.8 ships no synonym and its CAS number is on four CO₂ substances; 3.12's export of the same uuid carries the synonym that settles which |
| `11a2a7b1-ab2f-47b8-9e29-6f33d5207fa6` Gypsum, in ground | Synonyms `calcium`, `sulfate`, `dihydrate` removed | The words of `Calcium sulfate dihydrate` shipped as names of their own; under `sulfate` the row reached the sulfate ion ([#119](https://github.com/brightway-labs/brightway-flows/issues/119)) |
