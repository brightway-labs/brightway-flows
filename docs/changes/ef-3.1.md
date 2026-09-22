# Changes to EF 3.1

*Part of [What was changed in each source](index.md). What is still open about EF 3.1 is on the issue tracker under the label [`ef-3.1`](https://github.com/brightway-labs/brightway-flows/issues?q=is%3Aissue+is%3Aopen+label%3Aef-3.1).*

EF 3.1 is the base list: its 93,993 rows are transformed into the consensus
list rather than merged into it, and every other source is matched against
the result. Its curated corrections live in `ef-3.1-manual-fixes.json`, which
holds 210 entries; 74 of them alter a registry number and are listed in full
below. The merge evidence — which rows were split and which were joined — is
read off the build of 2026-08-29, commit `54b0f9d`, and every uuid quoted is
EF's own.

## One name, two substances

EF 3.1 writes one name on two sets of thirteen rows, one set per compartment,
and gives the two sets different registry numbers. The number decides the
substance (see [When a name and a CAS number
disagree](../deciding/identity.md)), so each set becomes its own flow
object. Seven names split this way; an eighth, `Water`, splits on the
compartment.

| EF 3.1 name | First set | Second set | What the CAS numbers designate |
|---|---|---|---|
| `2,4-dihydroxy-n-(3-hydroxypropyl)-3,3-dimethylbutanamide` | 81-13-0 | 16485-10-2 | Common Chemistry names 81-13-0 `(+)-Panthenol`, the single (R) form, and 16485-10-2 `DL-Panthenol`, the racemic mixture of both mirror-image forms. |
| `tridemorph` | 24602-86-6 | 81412-43-3 | 24602-86-6 is `2,6-Dimethyl-4-tridecylmorpholine`, one defined molecule; 81412-43-3 is `Tridemorph`, the commercial fungicide, which Common Chemistry registers with an unspecified formula because the product is a mixture of homologues. |
| `1,3-benzenediamine` | 541-69-5 | 108-45-2 | 108-45-2 is m-phenylenediamine, the free base; 541-69-5 is its dihydrochloride salt, with two molecules of hydrogen chloride attached. |
| `3,6-dimethyl-1,4-dioxane-2,5-dione` | 4511-42-6 | 95-96-5 | 95-96-5 is `Lactide` with no stereochemistry stated; 4511-42-6 is `L-Lactide`, the (S,S) form used to make polylactic acid. Published as `Lactide` and `3,6-dimethyl-1,4-dioxane-2,5-dione`. |
| `bis(2-ethylhexyl) but-2-enedioate` | 141-02-6 | 142-16-5 | The two geometric isomers of the same ester: 141-02-6 is the fumarate (trans), 142-16-5 the maleate (cis). |
| `calcium dihydrogen phosphate` | 7758-23-8 | 7757-93-9 | 7758-23-8 is calcium dihydrogen phosphate, Ca(H2PO4)2; 7757-93-9 is calcium hydrogen phosphate, CaHPO4 — a different salt with half the phosphate. Published under those two names. |
| `methyl 2-hydroxypropanoate` | 27871-49-4 | 17392-83-5 | The two mirror-image forms of methyl lactate: 27871-49-4 is the (S) or L form, 17392-83-5 the (R) or D form. |

Each set holds the same thirteen compartments. The uuids, first set then
second, in the order the table above uses:

| Compartment | Panthenol, 81-13-0 / 16485-10-2 | Tridemorph, 24602-86-6 / 81412-43-3 |
|---|---|---|
| Air, indoor | `300b9f0a-cb7d-465c-b444-d899af6aa841` / `f6f03e17-6527-41d3-9606-072a52c25762` | `a0955f93-2bf8-48c5-8278-854932bc59a0` / — |
| Air, unspecified | `c9a7bff8-8dd3-4e4f-893f-115001b21f2f` / `142d60ba-7547-4e7f-b9bb-5c88517948ce` | `195462e1-715a-463f-8933-f7e23c892448` / `08a91e70-3ddc-11dd-904d-0050c2490048` |
| Air, unspecified (long-term) | `c97861c9-d32f-492f-a6e6-5b39406951c0` / `b88c47dd-3418-4fa1-b38b-be717e1de553` | `2d53b2c9-222f-40c9-ac2f-55be45f9899f` / `08a91e70-3ddc-11dd-904e-0050c2490048` |
| Lower stratosphere and upper troposphere | `265984d8-a1ff-4a51-947f-2a026cffd7c4` / `5f96c2ff-f455-4a31-97e7-b7b111a9b801` | `f54e71d9-b5be-4a42-84f0-2ac2d7e47be4` / `3e4dc5a8-6556-11dd-ad8b-0800200c9a66` |
| Non-urban air or from high stacks | `13dbc475-6ca8-4c33-86a5-7fc65ca87bbf` / `63bcdcf3-1aac-437a-aa17-e265b05ce251` | `0555b3b4-e553-4607-aa5b-6febca2ac454` / `08a91e70-3ddc-11dd-9050-0050c2490048` |
| Urban air close to ground | `bb35c65b-50f5-4609-ac2f-d8a2f0a537d8` / `4c85b739-77fc-4b5f-9ef8-ceb8fc86216d` | `d4939292-b130-424a-88da-e8086993108c` / `08a91e70-3ddc-11dd-904f-0050c2490048` |
| Agricultural soil | `019c7104-8a83-41b8-875c-833b324700f1` / `26ed6dbf-a069-4ace-b676-3747b7154170` | `fee4c355-9382-47e7-898b-1a2f923ca460` / `08a91e70-3ddc-11dd-904b-0050c2490048` |
| Non-agricultural soil | `14428794-83e7-4399-810a-9452c9c9d874` / `473bbb26-275a-4844-b82c-89d8da7e48de` | `8d96fb52-8e31-45c0-a50a-5b0ec3bea6a1` / `08a91e70-3ddc-11dd-9054-0050c2490048` |
| Soil, unspecified | `b64614c0-5ac8-49b1-a654-d960e79d4f69` / `5c0eebcc-74d5-4939-9818-8d2177ae48b4` | `f6fa96c3-0c15-4ca1-95b1-8eb82d0cb3d1` / `08a91e70-3ddc-11dd-904c-0050c2490048` |
| Fresh water | `b80e34a8-b3db-4ef7-8c10-2beb87c3d337` / `1d32f40e-3721-44a1-9947-04e2aa690686` | `ab8fcafd-0446-42de-ad86-f6cb68f3c3e6` / `08a91e70-3ddc-11dd-9051-0050c2490048` |
| Sea water | `421b882a-a7bd-405f-aa8a-07256b92926b` / `57395c21-684a-47bd-a356-6a4a462e2a0f` | `02ca16ce-8aef-4233-8df7-129e55709a7f` / `08a91e70-3ddc-11dd-9055-0050c2490048` |
| Water, unspecified | `c031e177-09b7-438e-89fb-eee72eaddb6c` / `77fa183a-d5d8-40fc-865b-270099fe7b44` | `20725852-8357-400d-adb7-387181b3c329` / `08a91e70-3ddc-11dd-9053-0050c2490048` |
| Water, unspecified (long-term) | `8b75eecc-7fe2-4c2f-8a27-f70358a1bf96` / `e7cab797-bdf1-4b1e-9b9f-bb6ff9a3f2a9` | `66785a20-0bd9-403e-a845-b52da4740f26` / `08a91e70-3ddc-11dd-9052-0050c2490048` |

The `tridemorph` row named for the commercial product has no indoor-air copy,
so that set is twelve rows.

| Compartment | Benzenediamine, 541-69-5 / 108-45-2 | Lactide, 4511-42-6 / 95-96-5 |
|---|---|---|
| Air, indoor | `bcfe35cb-6ffe-4951-8f37-3478bfbd8130` / `8ab6f157-e94d-49c1-8259-33a6b0358e3a` | `1c1f67b6-b7f9-4b23-a41a-bbd732b8f41f` / `51dc9808-9e8c-4b8e-860c-81a9df3aee67` |
| Air, unspecified | `3a0708b6-44e1-458e-8702-49da1a099fe8` / `fe0acd60-3ddc-11dd-b085-0050c2490048` | `9ae56956-b3f7-4bfe-bd48-2ab4270ac841` / `cd526c1a-051c-470b-9312-df61cd36396a` |
| Air, unspecified (long-term) | `d931883f-f189-47e0-a9fb-4df1b37da4e7` / `fe0acd60-3ddc-11dd-b086-0050c2490048` | `7a0c89bd-af86-4a9c-8369-ff1c9ee1b2c7` / `1a219878-9e45-42bb-9de6-efc888e0214f` |
| Lower stratosphere and upper troposphere | `ee97f00c-ec02-4a3d-b4f3-b11ac330da78` / `f214ae17-6555-11dd-ad8b-0800200c9a66` | `5598f1b4-4429-48a7-ae96-33abdda43167` / `13e44046-f872-4b9f-b919-af9a84f8c525` |
| Non-urban air or from high stacks | `5bd6768c-c9f5-4a3f-a05d-2d2d349b1445` / `fe0acd60-3ddc-11dd-b088-0050c2490048` | `b3461177-7f92-4ca1-80c3-17a821a71bc3` / `c6dc7561-6587-4db9-84e1-f9f83b1b6805` |
| Urban air close to ground | `ef83568c-1dcf-41c8-8e8e-e858e9ce8c09` / `fe0acd60-3ddc-11dd-b087-0050c2490048` | `0bbc48d2-0bf8-4684-b03a-184133a01c7c` / `ca881f5a-da61-401d-8e58-9c7ba77a5ed2` |
| Agricultural soil | `eb998f1c-ab52-4255-b859-1fa865848d7a` / `fe0acd60-3ddc-11dd-b083-0050c2490048` | `d92b9b43-7930-44c5-b69d-9e6ca789c645` / `64197612-fe13-40ba-9391-0f7b5c8162d3` |
| Non-agricultural soil | `c9fa8940-cd81-4964-b8aa-133098195452` / `fe0acd60-3ddc-11dd-b08c-0050c2490048` | `955c10b0-07cd-4408-b20c-e9568035789d` / `38f3e4c7-1a9b-431c-be16-e63e2b3f0b21` |
| Soil, unspecified | `0b0fbc84-3592-47f8-9735-17d3f38fecd8` / `fe0acd60-3ddc-11dd-b084-0050c2490048` | `e078a6ea-c14e-422e-ae54-3ff60ca5301f` / `8220824e-d3d9-4de4-a0ab-51693ac60e4c` |
| Fresh water | `df97302e-534e-4a8d-ae83-9920cd654945` / `fe0acd60-3ddc-11dd-b089-0050c2490048` | `def10e78-ff5c-4efa-ab3e-a362060ef034` / `83f48fe7-755e-4ebf-acf2-53651294abaf` |
| Sea water | `14f562b9-5272-410d-ac82-fec1cbe7f353` / `fe0acd60-3ddc-11dd-b08d-0050c2490048` | `31a0117e-c8e1-4e7d-ac9b-dac56b218da2` / `3ea26d8f-fa58-4430-ad0e-a29385035622` |
| Water, unspecified | `064591e0-b497-4575-a0e5-5f71cfa772ac` / `fe0acd60-3ddc-11dd-b08b-0050c2490048` | `160ecb11-71e5-48cd-8d99-6f6fe8238b55` / `54fae6e6-3a0b-4d61-8684-784d5f0fe68a` |
| Water, unspecified (long-term) | `2009c787-6123-4074-ba32-5934267530bc` / `fe0acd60-3ddc-11dd-b08a-0050c2490048` | `c22c2e2a-bfe5-4aa4-96e4-452ee9405313` / `9a7da893-8364-4fbe-82c9-887abde6ec6c` |

| Compartment | Ester, 141-02-6 / 142-16-5 | Calcium phosphate, 7758-23-8 / 7757-93-9 | Methyl lactate, 27871-49-4 / 17392-83-5 |
|---|---|---|---|
| Air, indoor | `1cef9329-399c-40ed-bf89-2bc020c7c590` / `9f5dd172-4ebc-4211-b85a-69b14229b9c9` | `c8fb3eeb-ea21-4835-a571-2f1cafc1a27c` / `f78f6832-92fb-42c9-ad86-ea1cc5524b80` | `c90a42f9-2951-4a8d-9caf-0a755de95be8` / `21443c15-f3a0-4537-82fd-427f06878901` |
| Air, unspecified | `66c96611-bcbc-4535-b218-f1730ef7f01a` / `f1d869cf-2475-4511-8c54-b91ffa5a33e7` | `9d19314a-e413-43e2-a081-2d3016481107` / `9dc0b1a2-7bb7-409e-b2ca-40ffc165810d` | `831444c9-3da7-4e50-a213-1673d6820418` / `70f9d3cb-c9d7-4275-82d6-730f9094638c` |
| Air, unspecified (long-term) | `cafde9fc-64f4-4a2c-b521-1e01cae91cc3` / `1c5aafa9-61dd-4cad-924c-ad40fd67e71f` | `45728a90-1c49-4c3a-9c96-8291835f5e73` / `572137b4-bbd8-4dad-83e5-5458cfb59171` | `782e6251-f11d-4e71-9316-dc71abc7fd85` / `281799c9-8109-44a3-8c84-18e45767e1bf` |
| Lower stratosphere and upper troposphere | `3bffbe64-99f1-4d99-b7ad-2354ae68c1a0` / `1f4b58dd-ff4b-4188-a297-81a1e324c9d4` | `59a6d672-cd32-4768-9af9-86b696516773` / `c2df57bc-bfe7-467a-b8f2-b1bf9f2700a4` | `2e8e0b6d-7f9e-49cb-86ca-a807a061519e` / `f699c59b-af9a-4b98-a3b2-ac7a10fa3fac` |
| Non-urban air or from high stacks | `ad75375e-6eef-41ad-bb42-62fddebc833b` / `45527bbd-a5a4-4966-8139-8f9e83cf2eb2` | `4aa049b3-a36d-42dd-a266-2173fee32253` / `4ee4c280-11b7-421c-b967-52f17a91bcac` | `9ff4e53b-4d1c-47dc-ac7f-ed1139c5dc1c` / `f0086d49-6de7-4e5a-b7db-889a41ed00fe` |
| Urban air close to ground | `7e818477-6d0a-4b59-9bf6-0af08984d366` / `e8e179a7-2858-4886-a220-b968780fcbf3` | `60abc0b3-f374-4ba4-8043-73c8c21821dd` / `2ffca6ac-fb8c-49ff-87aa-a4e5da526c21` | `4465c50f-c9c9-40eb-9c57-736d89337a5e` / `e01da1ce-3c30-4e3c-98e2-aa6f4019d491` |
| Agricultural soil | `8a11a6c8-c6df-4a91-9a1a-801bc9039511` / `2d6b0253-fbdc-45a1-a39e-676335efde21` | `293fafeb-553a-492b-b95e-c9f7c08238df` / `76cd1a4d-513f-404b-80d6-54b3401b98f3` | `2fd52568-25ec-4afd-910a-dad38768a86f` / `3d6e11a3-58a8-4ce2-a202-1df1b995bc23` |
| Non-agricultural soil | `142bfd04-9187-4904-bcde-ac72ba50ea5f` / `c5430768-5091-4464-be65-4aba52abcd11` | `7161cb91-1237-4da8-90be-b2a21288b3e3` / `891e6275-65c2-41c2-a681-ded4169c5aae` | `922225d6-bf6a-4557-9ec7-b3aca1cc4672` / `15d621ee-e14a-4a07-b031-c5e17439a771` |
| Soil, unspecified | `df115b9e-5954-410b-ae15-f9afc1aa0e5a` / `bdcaf6a6-940c-4ab4-af4f-14053beebd83` | `d472c2df-e2cd-4514-b00d-2c82c9bb1716` / `c08910ab-8ad3-419c-bf56-ce6549206e97` | `1588db63-96e4-470b-b836-f02f4d2c39cd` / `dcdb9131-9c77-4492-a900-fc0daa96b6bf` |
| Fresh water | `d195ddb8-25c6-4d9e-9272-2770b5587ff2` / `ee2c3750-d5ef-48fd-9c26-fda509bb11b4` | `3f67c7ee-2909-4fb1-8ded-0681ff674cc0` / `e7f41296-fc5e-43e5-ba56-dadbc88fcb2b` | `30bb80e6-b8fc-4e45-a755-d05aa0763b4f` / `2acf670b-abdf-4144-a21f-2e5171dc4bad` |
| Sea water | `575fc6b1-04a6-4e22-9fc2-71d21c6eddd6` / `e98bfa3d-dd39-48ce-a9af-baa46ffaf5bb` | `d41a47d9-69d2-430f-a34a-544f18ac5fa4` / `7043b365-9796-4971-89b7-060f3bc51e73` | `cac92a61-262d-481e-a0b3-420a9ff44d30` / `d8f31ffa-9d80-4b7b-92c1-c178de05b36e` |
| Water, unspecified | `c5689df9-5244-415c-b638-9db6744cd4ba` / `c331e4b4-c3d2-48d2-b62e-486791c21812` | `10344f95-9a7d-4da9-ab0a-99f81e6acfe6` / `5cb269aa-01cb-492a-b344-ba63d381e37d` | `df1dc0e1-37b9-4e83-ab7a-fbee7b4b0424` / `cc21fb56-f24d-4a86-8477-8e82d5771f29` |
| Water, unspecified (long-term) | `0cbed8ad-1c91-4649-9435-fb6ad67e669e` / `f93585fb-c81c-4e18-8747-787082d70fd1` | `dd0baea6-ff99-458e-8505-58ecaa4fd131` / `2e35e741-3510-4bcb-b48d-61881ca51ad5` | `c7e55d87-f691-47b2-bf2b-242f13d50933` / `84fc17db-ed4c-4fc9-b8e8-bc7990e2822f` |

**`Water`** carries one CAS number, 7732-18-5, on all nine of its rows, and still
splits, on the compartment: water released to air is water vapour, and water
released to a water body is liquid water. The five air rows —
`0342f5e5-b53e-4cec-9e67-fb197f24fff0` (unspecified),
`2461cd99-2340-41b0-a110-1709835dea3f` (long-term),
`5cfda72a-b91b-4f7c-a8d4-1f8265d8cd4c` (stratosphere and troposphere),
`896d1d1e-2b87-4a83-b209-11a2ea997b49` (non-urban),
`3960d174-95af-41ac-a7f3-a946cd237245` (urban) — are published as
`Water vapour`; the four water rows —
`5e50fc01-19c6-4377-a1cc-bc65a12498ea` (fresh water),
`631ecf13-0e51-4e35-8235-c6f80c60d72c` (sea water),
`a3876d9b-a3e8-4680-861a-4e08642f1392` (unspecified),
`4b3fe20b-eae3-4963-8326-d3d32fbfeeff` (long-term) — as `Water`. All nine are
in cubic metres.

## An ionic charge was added or corrected

EF 3.1 names most of its dissolved metals with a Roman numeral —
`chromium (vi)`, `arsenic (iii)`, `iron (ii)` — and the consensus list spells
the same charge as `Chromium(6+)`, `Arsenic(3+)`, `Iron(2+)`. Twenty-seven
names were re-spelled that way on the 2026-08-29 build; that is notation, and
none of them is listed here.

Six names say `ion` and give no charge, and in each case EF's own registry
number on the row is a charged ion's. The published name now carries the
charge the CAS number states. Each was approved as a ruling in
`preferred-label-decisions.json` under
[#128](https://github.com/brightway-labs/brightway-flows/issues/128),
which applies one test: the rename must remove an ambiguity rather than add a
claim. Sodium, lithium and potassium have exactly one ionic form, so the
charge asserts nothing new. Tin is the case that mattered: the list already
published `Tin(2+)`, and `Tin, ion` sat beside it without saying that it was
the other tin
([#127](https://github.com/brightway-labs/brightway-flows/issues/127)).

| EF 3.1 name | EF 3.1 CAS | Published as | Rows |
|---|---|---|---|
| `Sodium, ion` | 17341-25-2 | `Sodium(1+)` | `2ece367c-6949-4a4c-8751-db695223e0d4`, `5f69e76c-1e5b-49ef-adc6-7acfaaaea415`, `6a3f413e-8aab-4c58-93b0-1f51c9714adb`, `99c541c4-8876-4b9b-b8bc-040ac301b34c` |
| `Lithium, ion` | 17341-24-1 | `Lithium(1+)` | `426d0901-57e7-49e8-adb9-e1e05895b389`, `57d50fd6-4d20-455a-9252-43cdefade3ac`, `748783d0-10bb-4421-a42e-ce3025adab41`, `95a43437-4b54-4a75-a998-435e6f0af8f1` |
| `Potassium, ion` | 24203-36-9 | `Potassium(1+)` | `03ac80dc-56fa-487a-9a0e-ea1f6107ab00`, `05cb4f27-5c60-420a-a8f2-14d23150f55e`, `17f0762e-681b-4f6f-8693-58b95f6779a7`, `f8ffda3a-7148-4ad1-a4ce-cbe24705fcd1` |
| `Tin, ion` | 22537-50-4 | `Tin(4+)` | `19b8353d-7796-44f7-b678-a98bad221fdb`, `34bfe278-8b2a-4494-84ec-f34fc561853e`, `bc723659-833e-477b-ad27-7cad4db27d2f`, `d13a1f0c-5201-4af4-9fc2-7112887f1862` |
| `Vanadium, ion` | 22541-77-1 | `Vanadium(3+)` | `1d5fff11-1564-4c03-8882-78216947ebdf`, `8094f72c-8118-41a0-8935-07f35a646c0f`, `e8409091-b011-4861-a004-d9ee13d15921`, `f8152976-6dfb-4f09-ad89-c485d1473826` |
| `methyl mercury ion` | 22967-92-6 | `Methylmercury(1+)` | 12 rows across air, soil and water, among them `3e4cb460-6556-11dd-ad8b-0800200c9a66`, `4d9a8790-3ddd-11dd-9939-0050c2490048`, `4d9a8790-3ddd-11dd-993a-0050c2490048` |

The twenty metal-ion rows are all emissions to water: fresh water, sea water,
unspecified and unspecified long-term. Methylmercury, CH3Hg⁺, carries a
single positive charge in every case, so its rename asserts nothing the
number did not already say. `Titanium, ion` (22541-75-9) keeps its generic name
by a rejected ruling in the same file
([#143](https://github.com/brightway-labs/brightway-flows/issues/143)):
the list publishes no other titanium ion for it to be confused with.

Two charges were kept by correcting the registry number that contradicted
them. Thirteen rows named `vanadium (v)` carry 15121-26-3, which is the CAS
number of vanadium(2+); the name is right and the CAS number was wrong, so the
CAS number was changed to 22537-31-1 and the rows are published as
`Vanadium(5+)`. Thirteen rows named `cerium(3+)`
(`3558989d-d552-499a-a235-54bf69879f7d` in aircraft cruise height,
`ef6d6805-f188-4e31-8d34-a7ddc69aac48` in urban air, and eleven more) carry
7440-45-1, which is the CAS number of cerium the *element* — the number EF
also writes on its `cerium` resource row (`08a91e70-3ddc-11dd-925f-0050c2490048`).
On the 2026-08-29 build the number won, the thirteen joined the resource row
on one substance published as `Cerium`, and the charge EF wrote on purpose was
dropped along with the distinction between the ion's toxicity factors and the
element's. The ion's own number, 18923-26-7, is now written on the thirteen
rows, and the element's EC number 231-154-9 taken off them, so on
the build of 2026-08-30 at `9fbb0d5` they are published as `Cerium(3+)` ([#184](https://github.com/brightway-labs/brightway-flows/issues/184)). Both
corrections are in the table under [Registry numbers
corrected](#registry-numbers-corrected).

Two names carry `, ion` that the published name drops, and in each case EF's
own CAS number is what decided it:

- `Acrylate, ion` carries 79-10-7, acrylic acid, and is published as
  `Acrylic Acid` (three rows, including
  `94966655-8318-414b-9fcf-40be777f62de` to the ocean and
  `0eed1672-eb5d-4324-95f4-3ca787797e45` to surface water).
- `Perchlorate, ion` carries 14797-73-0, which Common Chemistry names
  `Perchlorate`, and is published under that name (four rows, including
  `429408a8-1a0a-44b0-90d0-7616a0e7e1cb` and
  `23e5a0b6-7cde-4f47-baec-87ab213cbbb8`).

## Rows merged into one flow

EF 3.1 publishes some substances twice in one compartment, usually once under
an industry code and once under the chemical name, and often with the
characterisation factors on only one of the two. Once both rows carry the
same registry number they are one substance, and a curator ruling in
`elementary-flow-collision-decisions.json` names which row survives and which
is retired onto it. There are 48 such rulings, all of them merges, over
sixteen pairs of names; the retired row keeps its uuid and points at the
survivor, so an inventory written against it still lands
([#44](https://github.com/brightway-labs/brightway-flows/issues/44),
[#73](https://github.com/brightway-labs/brightway-flows/issues/73),
[#106](https://github.com/brightway-labs/brightway-flows/issues/106),
[#191](https://github.com/brightway-labs/brightway-flows/issues/191)).

In every case where one row holds the characterisation factors, that row
survives. Where both are characterised identically, the row carrying the
registry number, the synonyms and EF's own comment survives. Where neither
carries a factor at all — the water vapour pair — the row every other list's
correspondence and override names survives.

| Published as | EF 3.1 names (survivor first) | Compartment | Survivor | Retired | Why |
|---|---|---|---|---|---|
| 2,2,3,3,3-Pentafluoropropan-1-ol | `2,2,3,3,3-Pentafluoropropan-1-ol`, `pentafluoro-1-propanol` | Urban air | `7d124d8e-e251-11e6-bf01-fe55135034f3` | `4d9a8790-3ddd-11dd-99b4-0050c2490048` | Same alcohol, 422-05-9; the systematic-name row holds the climate change factor of 34.3, the other row none. |
| | | Non-urban air | `7d124938-e251-11e6-bf01-fe55135034f3` | `4d9a8790-3ddd-11dd-99b5-0050c2490048` | |
| | | Air, long-term | `7d124794-e251-11e6-bf01-fe55135034f3` | `4d9a8790-3ddd-11dd-99b3-0050c2490048` | |
| | | Air, unspecified | `7d1245fa-e251-11e6-bf01-fe55135034f3` | `4d9a8790-3ddd-11dd-99b2-0050c2490048` | |
| 2,2,3,3,3-Pentafluoropropyl Methyl Ether | `HFE-365mcf3`, `2,2,3,3,3-Pentafluoropropyl methyl ether` | Urban air | `9ae3dcb0-e251-11e6-bf01-fe55135034f3` | `ea3de8fe-b0ad-4fb9-8843-5438f643d657` | Same ether, 378-16-5; the code row holds the climate change factor of 1.6. |
| | | Non-urban air | `9ae3db66-e251-11e6-bf01-fe55135034f3` | `5298c09a-3c23-4edd-b70c-c29c39d529cb` | |
| | | Air, long-term | `9ae3d828-e251-11e6-bf01-fe55135034f3` | `4eead42f-ddce-492c-941d-2b828e4eed3f` | |
| Perfluoropentane | `PFC-41-12`, `dodecafluoropentane` | Urban air | `a19c1554-e251-11e6-bf01-fe55135034f3` | `4d9a8790-3ddd-11dd-9064-0050c2490048` | Same C5F12, 678-26-2; the code row holds the climate change factor of 9220. |
| | | Non-urban air | `a19c143c-e251-11e6-bf01-fe55135034f3` | `4d9a8790-3ddd-11dd-9065-0050c2490048` | |
| | | Air, long-term | `a19c0db6-e251-11e6-bf01-fe55135034f3` | `4d9a8790-3ddd-11dd-9063-0050c2490048` | |
| | | Air, unspecified | `a19c0cee-e251-11e6-bf01-fe55135034f3` | `4d9a8790-3ddd-11dd-9062-0050c2490048` | |
| Octafluorocyclobutane | `PFC-318`, `FC-318` | Urban air | `a19c0c30-e251-11e6-bf01-fe55135034f3` | `4d9a8790-3ddd-11dd-935b-0050c2490048` | Two spellings of one designation, 115-25-3; the `PFC-318` row holds the climate change factor of 10200. |
| | | Non-urban air | `a19c0b5e-e251-11e6-bf01-fe55135034f3` | `4d9a8790-3ddd-11dd-935c-0050c2490048` | |
| | | Air, long-term | `a19c094c-e251-11e6-bf01-fe55135034f3` | `4d9a8790-3ddd-11dd-935a-0050c2490048` | |
| | | Air, unspecified | `a19c088e-e251-11e6-bf01-fe55135034f3` | `4d9a8790-3ddd-11dd-9359-0050c2490048` | |
| Bromomethane | `Halon-1001`, `Methyl bromide` | Aircraft cruise height | `d86cb000-6555-11dd-ad8b-0800200c9a66` | `b5e3438d-f01c-4e18-89fb-a0215d5ba067` | Both are CH3Br, 74-83-9. The `Halon-1001` row carries seven factors; the other carries six of the same seven and lacks ozone depletion (0.57), which a methyl bromide emission does cause. |
| Perfluorobutane | `PFC-31-10`, `perfluorobutane` | Urban air | `a19c07c6-e251-11e6-bf01-fe55135034f3` | `4d9a8790-3ddd-11dd-9aeb-0050c2490048` | Same C4F10, 355-25-9; the code row holds the climate change factor of 10000. |
| | | Non-urban air | `a19c0604-e251-11e6-bf01-fe55135034f3` | `4d9a8790-3ddd-11dd-9aec-0050c2490048` | |
| | | Air, long-term | `a19c0546-e251-11e6-bf01-fe55135034f3` | `4d9a8790-3ddd-11dd-9aea-0050c2490048` | |
| | | Air, unspecified | `a19c047e-e251-11e6-bf01-fe55135034f3` | `4d9a8790-3ddd-11dd-9ae9-0050c2490048` | |
| Perfluorohexane | `PFC-51-14`, `perfluorohexane` | Urban air | `a19c1a22-e251-11e6-bf01-fe55135034f3` | `08a91e70-3ddc-11dd-9484-0050c2490048` | The code row's own synonym reads `perfluorohexane, C6F14`; 355-42-0; it holds the climate change factor of 8620. |
| | | Non-urban air | `a19c196e-e251-11e6-bf01-fe55135034f3` | `08a91e70-3ddc-11dd-9485-0050c2490048` | |
| | | Air, long-term | `a19c18a6-e251-11e6-bf01-fe55135034f3` | `08a91e70-3ddc-11dd-9483-0050c2490048` | |
| | | Air, unspecified | `a19c17e8-e251-11e6-bf01-fe55135034f3` | `08a91e70-3ddc-11dd-9482-0050c2490048` | |
| Perfluoropropane | `PFC-218`, `perfluoropropane` | Urban air | `a19c03c0-e251-11e6-bf01-fe55135034f3` | `08a91e70-3ddc-11dd-986e-0050c2490048` | Same C3F8, 76-19-7; the code row holds the climate change factor of 9290. |
| | | Non-urban air | `a19c02e4-e251-11e6-bf01-fe55135034f3` | `08a91e70-3ddc-11dd-986f-0050c2490048` | |
| | | Air, long-term | `a19bffce-e251-11e6-bf01-fe55135034f3` | `08a91e70-3ddc-11dd-986d-0050c2490048` | |
| | | Air, unspecified | `a19bff06-e251-11e6-bf01-fe55135034f3` | `08a91e70-3ddc-11dd-986c-0050c2490048` | |
| Carbon tetrachloride | `CFC-10`, `Carbon tetrachloride` | Aircraft cruise height | `d86c61db-6555-11dd-ad8b-0800200c9a66` | `8a314326-e251-11e6-bf01-fe55135034f3` | Both are CCl4 and both carry the same nine factors, agreeing exactly on six and to rounding on the rest. The `CFC-10` row carries 56-23-5, EC 200-262-8 and some fifty synonyms; the other carries no identifier at all. |
| | | Urban air | `fe0acd60-3ddc-11dd-a92b-0050c2490048` | `8a314a38-e251-11e6-bf01-fe55135034f3` | |
| | | Air, long-term | `fe0acd60-3ddc-11dd-a92a-0050c2490048` | `8a31416e-e251-11e6-bf01-fe55135034f3` | |
| | | Non-urban air | `fe0acd60-3ddc-11dd-a92c-0050c2490048` | `8a314826-e251-11e6-bf01-fe55135034f3` | |
| | | Air, unspecified | `fe0acd60-3ddc-11dd-a929-0050c2490048` | `8a313fb6-e251-11e6-bf01-fe55135034f3` | |
| Hexafluoroethane | `HFC-116`, `PFC-116` | Urban air | `08a91e70-3ddc-11dd-9340-0050c2490048` | `a19bf2e0-e251-11e6-bf01-fe55135034f3` | Both carry 76-16-4 and the same six factors. `HFC-116` is wrong as chemistry — C2F6 has no hydrogen — and is still the row with the EC number, twelve synonyms, EF's comment and the ecoinvent mappings. |
| | | Air, long-term | `08a91e70-3ddc-11dd-933f-0050c2490048` | `a19bf150-e251-11e6-bf01-fe55135034f3` | |
| | | Non-urban air | `fe0acd60-3ddc-11dd-a3e5-0050c2490048` | `a19bf218-e251-11e6-bf01-fe55135034f3` | |
| | | Air, unspecified | `08a91e70-3ddc-11dd-933e-0050c2490048` | `a19bf07e-e251-11e6-bf01-fe55135034f3` | |
| 1,1,1-Trichloroethane | `HCFC-140`, `Methyl chloroform` | Urban air | `4d9a8790-3ddd-11dd-925b-0050c2490048` | `9ae45384-e251-11e6-bf01-fe55135034f3` | Both carry 71-55-6 and seven factors each. The `HCFC-140` row also carries EC 200-756-3 and 57 synonyms. |
| | | Air, long-term | `4d9a8790-3ddd-11dd-925a-0050c2490048` | `9ae44f9c-e251-11e6-bf01-fe55135034f3` | |
| | | Non-urban air | `4d9a8790-3ddd-11dd-925c-0050c2490048` | `9ae45122-e251-11e6-bf01-fe55135034f3` | |
| | | Air, unspecified | `d86cafdf-6555-11dd-ad8b-0800200c9a66` | `9ae44d44-e251-11e6-bf01-fe55135034f3` | |
| Beryllium | `beryllium`, `beryllium` | Non-urban air | `4d9a8790-3ddd-11dd-9d8e-0050c2490048` | `cd6262a9-9397-4456-beb4-86a736449186` | Two rows with the same name, number (7440-41-7), EC number and six factors. One carries EF's comment that the metallic form's number stands for all ions; the other carries nothing extra. |
| Thallium | `thallium`, `thallium` | Non-urban air | `08a91e70-3ddc-11dd-9966-0050c2490048` | `1e49a2cf-7772-46ac-8a4f-55e0e170f377` | The same shape as beryllium: 7440-28-0, four factors each side. |
| Energy, Geothermal, Converted | `Energy, geothermal, converted`, `primary energy from geothermics` | Resource, ground | `c0060563-96ea-4322-8305-61c39f2ad3cd` | `04202046-6556-11dd-ad8b-0800200c9a66` | One resource under two names; neither row carries a CAS number, a synonym or a factor. The `converted` name is the one ecoinvent and BAFU also use. Paired by `flow-object-overrides.json`. |
| Energy, Solar, Converted | `Energy, solar, converted`, `primary energy from solar energy` | Resource, air | `1c80d3da-b8c4-4275-a552-c96a709a11dd` | `04202048-6556-11dd-ad8b-0800200c9a66` | As above. |
| Water vapour | `Water`, `Water (evapotranspiration)` | Air, unspecified | `0342f5e5-b53e-4cec-9e67-fb197f24fff0` | `4b772bba-b5c1-4098-9c1d-3d9d8c74c7fa` | The same cubic metre of vapour, 7732-18-5 on both, no factor on either. EF's own comment on the retired row calls it "water vapour, but coming from growing renewables" and attributes the distinction to "some water people"; the surviving row is the one ecoinvent's tables and AGRIBALYSE's override already name, and the only compartment of five with a second copy loses it ([#191](https://github.com/brightway-labs/brightway-flows/issues/191)). |
| Energy, Kinetic (in Wind), Converted | `Energy, kinetic (in wind), converted`, `primary energy from wind power` | Resource, air | `0ab82f67-9e7e-417a-8de8-9801226a436f` | `0420204a-6556-11dd-ad8b-0800200c9a66` | As above. |
| Energy, Potential (in Hydropower Reservoir), Converted | `Energy, potential (in hydropower reservoir), converted`, `primary energy from hydro power` | Resource, water | `e89f564c-7250-4fee-b759-dc8b42fe62bf` | `04202047-6556-11dd-ad8b-0800200c9a66` | As above. `primary energy from waves` in the same compartment duplicates nothing and stays. |

The four `primary energy from …` rows come from a block of legacy ILCD
identifiers (`04202046` to `0420204a`) that EF inherited beside its newer
names. Most of the other pairs exist because the registry number on the code
row is this project's — supplied in the table below — and the moment the two
rows carried one CAS number they became one substance.

## Registry numbers corrected

Every entry in `ef-3.1-manual-fixes.json` that changes a CAS or EC number is
here, in four groups. The fix file holds the full reasoning for each.

### Numbers that named the wrong thing

| EF 3.1 row | Was | Now | Why |
|---|---|---|---|
| `uranium-238`, 13 rows | CAS 7440-61-1 | CAS 24678-82-8 | 7440-61-1 is uranium the element, by mass; the rows are the activity of the isotope U-238, whose own CAS number is 24678-82-8. ecoinvent, BAFU and Stepwise all needed the same correction. `thorium-232` (7440-29-1) and `Praseodymium-147` (7440-10-0) have the same defect and are left as shipped, because no cited nuclide-specific number exists for them. |
| `cerium(3+)`, 13 rows | CAS 7440-45-1 | CAS 18923-26-7 | 7440-45-1 is cerium the element, which EF publishes separately as its `cerium` resource row under that same number. EF writes a charge on purpose, as for `iron (iii)` and `chromium (vi)`, and this was the one dissolved metal whose number contradicted its name. The ion's number comes from PubChem (CID 114853, `cerium(3+)`) and ChEBI (CHEBI:48782), because no list here carries it; with the element's number the thirteen rows had been published as `Cerium` ([#184](https://github.com/brightway-labs/brightway-flows/issues/184)). |
| `cerium(3+)`, 13 rows | EC 231-154-9 | *removed* | The element's EC number, the companion of 7440-45-1. A dissolved cation is not a substance placed on the market, so the ion has no EC number — EF's `vanadium (v)` rows carry none — and left in place it was the element's identity surviving by a second route: thirteen EC-against-CAS mismatches on a build with the registry number corrected alone ([#184](https://github.com/brightway-labs/brightway-flows/issues/184)). |
| `vanadium (v)`, 13 rows | CAS 15121-26-3 | CAS 22537-31-1 | 15121-26-3 is vanadium(2+). EF's own naming convention says this row is the pentavalent ion, and it publishes the element separately as `vanadium` (7440-62-2). With the wrong number the thirteen rows and their factors had been published as `Vanadium(2+)` ([#49](https://github.com/brightway-labs/brightway-flows/issues/49)). |
| `borax`, 1 row | CAS 12447-40-4 | CAS 1303-96-4 | Both numbers are borax's; 12447-40-4 is the superseded one, and ChEBI and ecoinvent file the mineral under 1303-96-4 ([#110](https://github.com/brightway-labs/brightway-flows/issues/110)). |
| `Mecoprop`, all rows | CAS 7085-19-0 | CAS 93-65-2 | Same substance, older number: Common Chemistry answers a query for 7085-19-0 with the record for 93-65-2, and ecoinvent and BAFU both carry 93-65-2 ([#119](https://github.com/brightway-labs/brightway-flows/issues/119)). |
| `Mecoprop`, all rows | EC 230-386-8 | EC 202-264-4 | The EC number paired with 93-65-2 in the ECHA inventory; moving the CAS alone would have left a pairing ECHA does not make. |

### Numbers removed because they belong to something else

| EF 3.1 row | Removed | Why |
|---|---|---|
| `Nitrogen, organic bound`, 5 rows | CAS 7727-37-9 | 7727-37-9 is nitrogen gas, N2. Organic-bound nitrogen is a nutrient load — the nitrogen inside proteins, urea and the like in a discharge — and no registry number can name it. With the gas's number the five rows were fused with `dinitrogen` and renamed `Dinitrogen` ([#57](https://github.com/brightway-labs/brightway-flows/issues/57)). Nothing replaces it; the rows group by name. |
| `Borate`, 6 rows | CAS 12447-40-4 | 12447-40-4 is borax, one particular salt; borate is the ion. Sharing the CAS number put all seven rows on one substance typed as a salt and named for the ion ([#106](https://github.com/brightway-labs/brightway-flows/issues/106)). Nothing replaces it. |
| `Water, salt, sole`, `37295016-4d20-4bbc-8bf8-b344933d8980` | CAS 7732-18-5 | The row is brine — `Sole` is German for a saturated salt solution — and a mixture does not carry the CAS number of the water molecule any more than seawater carries oxygen's. |
| `Gas, mine, off-gas, process, coal mining`, `00fdc4bc-724b-4993-ad43-c70df533b092` | CAS 8006-14-2 | 8006-14-2 is natural gas. Coal-seam gas is a different substance, as EF's own comment on `Pit Methane` says; the CAS number was inherited from the ILCD reference flow, and ecoinvent removed it from its own copy of the flow at 3.10.1 ([#80](https://github.com/brightway-labs/brightway-flows/issues/80)). The same row's unit is changed from `m3` to `sm3`, a standard cubic metre, with a factor of 1.0, because a cubic metre of gas means nothing until its temperature and pressure are stated. |
| Jasmolin I (CAS 4466-14-2), 13 rows | EC 232-319-8 | 232-319-8 is the EC number of pyrethrins, the natural insecticide mixture. Jasmolin I is one constituent of that mixture, with its own CAS number and formula. |
| Jasmolin II (CAS 1172-63-0), 13 rows | EC 232-319-8 | The same mixture number on the other constituent. With it on both, the two jasmolins read as one substance and ecoinvent's `Pyrethrins` reached two flow objects. |

### Numbers supplied where EF 3.1 shipped none

Ten ordinary substances, each shipped without any identifier:

| EF 3.1 row | Supplied | Substance | Evidence |
|---|---|---|---|
| `Gas, natural`, `fe0acd60-3ddc-11dd-a6fa-0050c2490048` | CAS 8006-14-2 | Natural gas | The other half of the coal-mine correction. Common Chemistry's name for 8006-14-2 is `Natural gas`; ecoinvent carries it on `Gas, natural` from 3.9.1 on. |
| `Methylene chloride`, 22 rows | CAS 75-09-2 | Dichloromethane | The common name of CH2Cl2, which EF also ships as `dichloromethane` with the CAS number; the factors on the two sets agree to rounding ([#35](https://github.com/brightway-labs/brightway-flows/issues/35)). |
| `Methyl chloroform`, 4 rows | CAS 71-55-6 | 1,1,1-Trichloroethane | The degreasers' name for the solvent EF also ships as `HCFC-140` with the CAS number. |
| `2,2,3,3,3-Pentafluoropropan-1-ol`, 4 rows | CAS 422-05-9 | 2,2,3,3,3-Pentafluoropropanol | EF's own `pentafluoro-1-propanol` rows carry the CAS number and list this name among their synonyms. |
| `perfluoro-2-methyl-3-pentanone`, 4 rows | CAS 756-13-8 | The fire-protection fluid sold as Novec 1230 | Common Chemistry lists the name among the CAS number's synonyms; EF's identified rows name Novec 1230 in theirs. |
| `Formate`, 3 rows | CAS 71-47-6 | The formate anion, HCOO⁻ | ChEBI's number for the ion; formic acid (64-18-6) is a different EF row. |
| `Fluoroxene`, 4 rows | CAS 406-90-6 | 2,2,2-Trifluoroethyl vinyl ether, an inhalation anaesthetic | PubChem CID 9844 lists the name; the only CAS on the record. |
| `Cyhalothrin, gamma-`, 2 rows | CAS 76703-62-3 | gamma-Cyhalothrin | PubChem CID 6440554, and ecoinvent 3.12 puts the same number on its own `Gamma-cyhalothrin` rows. The plain (68085-85-8) and lambda (91465-08-6) forms are different substances. |
| `Haloxyfop- (R) Methylester`, 1 row | CAS 72619-32-0 | Haloxyfop-P-methyl, the single active mirror-image form | PubChem CID 13363033 names the (R) form specifically. |
| `C12-14 fatty alcohol`, 13 rows | EC 279-420-3 | A cut of fatty alcohols with 12 to 14 carbons | The one ECHA inventory entry for that cut, `Alcohols, C12-14`. A cut has no single structure, so an EC number is the identifier it can carry; the build then reads CAS 80206-82-2 off the same inventory entry. |

Fifty-five refrigerants, blowing agents and heat-transfer fluids that EF 3.1
names only by an industry designation — `HFC-245cb`, `PFC-218`, `HG-02` —
and ships with no formula, structure or number
([#19](https://github.com/brightway-labs/brightway-flows/issues/19)).
A designation is a complete specification, but only a table a reader can
audit turns it into a substance. Two kinds of evidence were accepted. For
thirty-five, PubChem's record for the compound lists the designation among
its own synonyms, and where the designation's digits encode a formula, the
formula was checked against the record. For the other twenty, PubChem holds
no record carrying the code, and the link is EF's own characterisation
factor: EF's `Climate change` factors are a transcription of IPCC AR6 WGI
Table 7.SM.7, which prints the designation, the structure and the GWP100 on
one line, so a flow characterised at 616 kg CO2-eq is the substance whose
row reads 616.

| EF 3.1 designation | CAS supplied | Substance | Evidence |
|---|---|---|---|
| `(E)-HFC-1225ye` | 5595-10-8 | C3HF5, the (E) isomer of 1,2,3,3,3-pentafluoropropene | PubChem CID 6329539 synonym; formula matches the code |
| `HCFC-122a` | 354-15-4 | 1,1,2-Trichloro-1,2-difluoroethane | PubChem CID 92756 synonym; formula matches |
| `HCFC-123a` | 354-23-4 | 1,2-Dichloro-1,1,2-trifluoroethane | PubChem CID 9631 synonym; the CAS number ECHA carries as EC 206-549-4 |
| `HFC-1132a` | 75-38-7 | Vinylidene fluoride | PubChem CID 6369 synonym; formula matches |
| `HFC-1141` | 75-02-5 | Fluoroethylene | PubChem CID 6339 synonym; formula matches |
| `HFO-1234yf` (EF writes `HFC-1234yf`) | 754-12-1 | 2,3,3,3-Tetrafluoropropene | PubChem CID 2776731 synonym; EF also ships the substance as `polyhaloalkene` under this number with identical factors |
| `HFC-1345zfc` | 374-27-6 | 3,3,4,4,4-Pentafluoro-1-butene | PubChem CID 78990 synonym; formula matches |
| `HFC-245cb` | 1814-88-6 | C3H3F5, 1,1,1,2,2-pentafluoropropane | PubChem CID 15747 synonym; formula matches |
| `HFC-245ea` | 24270-66-4 | 1,1,2,3,3-Pentafluoropropane | PubChem CID 9793785 synonym; formula matches |
| `HFC-245eb` | 431-31-2 | 1,1,1,2,3-Pentafluoropropane | PubChem CID 164598 synonym; formula matches |
| `HFC-329p` | 375-17-7 | C4HF9 | PubChem CID 2775798 synonym; formula matches |
| `HFE-338mmz1` | 26103-08-2 | 2-(Difluoromethoxy)-1,1,1,3,3,3-hexafluoropropane | PubChem CID 10932890 synonym; formula matches |
| `HFE-347mmy1` | 22052-84-2 | Methyl perfluoroisopropyl ether | PubChem CID 2774925 synonym; formula matches |
| `HFE-356mff2` | 333-36-8 | Bis(2,2,2-trifluoroethyl) ether | PubChem CID 9528 synonym; formula matches |
| `HFE-365mcf2` | 22052-81-9 | C4H5F5O | PubChem CID 2775947 synonym; formula matches |
| `HFE-365mcf3` | 378-16-5 | 2,2,3,3,3-Pentafluoropropyl methyl ether | PubChem CID 2776015 synonym; formula matches |
| `HG-02` | 205367-61-9 | C6H2F12O3, a fluorinated polyether | PubChem CID 9884754 synonym; code has no formula to check |
| `HG-03` | 173350-37-3 | C8H2F16O4 | PubChem CID 102264792 synonym |
| `HG-20` | 249932-25-0 | C4H2F8O3 | PubChem CID 10220579 synonym |
| `HG-21` | 249932-26-1 | C6H2F12O4 | PubChem CID 100985762 synonym |
| `PFC-1216` | 116-15-4 | Hexafluoropropylene | PubChem CID 8302 synonym; formula matches |
| `PFC-218` | 76-19-7 | Perfluoropropane | PubChem CID 6432 synonym; formula matches |
| `PFC-31-10` | 355-25-9 | Perfluorobutane | PubChem CID 9638 synonym; formula matches |
| `PFC-41-12` | 678-26-2 | Perfluoropentane | PubChem CID 12675 synonym; formula matches |
| `HFC-272ca` | 420-45-1 | 2,2-Difluoropropane | PubChem CID 67895 synonym; formula matches |
| `HFE-356mmz1` | 13171-18-1 | Hexafluoroisopropyl methyl ether | PubChem CID 25749 synonym; the record's CAS section lists this number alone |
| `PFC-116` | 76-16-4 | Hexafluoroethane | PubChem CID 6431 synonym; formula matches |
| `PFC-14` | 75-73-0 | Carbon tetrafluoride | PubChem CID 6393 synonym; formula matches |
| `PFC-318` | 115-25-3 | Octafluorocyclobutane | PubChem CID 8263 synonym |
| `PFC-51-14` | 355-42-0 | Perfluorohexane | EF's own synonym on the row reads `perfluorohexane, C6F14`; EF's `perfluorohexane` rows carry the CAS number |
| `PFC-1114` | 116-14-3 | Tetrafluoroethylene | EF's own `tetrafluoroethylene` rows carry the CAS number and the same eight methods; all 26 shared factors agree to rounding |
| `HFE-143a` | 421-14-7 | Methyl trifluoromethyl ether, CH3OCF3 | AR6 row at GWP100 616, which EF's factor states; one EF `Methyl trifluoromethyl ether` row lists `HFE-143a` as a synonym. Distinct from `HFC-143a`, 420-46-2, at 5810 |
| `HFE-216` | 1187-93-5 | Perfluoro(methyl vinyl ether), CF3OCF=CF2 | AR6 row at 0.01; EF's own rows for the substance agree on all 40 shared factors |
| `Halon-2301` | 421-06-7 | 2-Bromo-1,1,1-trifluoroethane | AR6 row at 177; ECHA's EC 207-001-7 |
| `HCFC-132c` | 1842-05-3 | 1,1-Dichloro-1,2-difluoroethane | AR6 row at 342; the only C2H2Cl2F2 in EF 3.1 |
| `HFC-227ca` | 2252-84-8 | 1,1,1,2,2,3,3-Heptafluoropropane | AR6 row at 2980; the `ea` isomer (3600) is absent from EF |
| `HFC-263fb` | 421-07-8 | 1,1,1-Trifluoropropane | AR6 row at 74.8; ECHA's EC 207-002-2 |
| `HFC-1243zf` | 677-21-4 | 3,3,3-Trifluoropropene | AR6 row (as `HFO-1243zf`) at 0.261; ECHA's EC 211-637-0 |
| `HFE-263m1` | 690-22-2 | Ethyl trifluoromethyl ether, CF3OCH2CH3 | AR6 row at 29.2. Its isomer 460-43-5 is EF's own `HFE-263fb2` |
| `PFC-61-16` | 335-57-9 | Perfluoroheptane, unbranched | AR6 row at 8410; ECHA's EC 206-392-1 |
| `PFC-71-18` | 307-34-6 | Perfluorooctane, unbranched | AR6 row at 8260; ECHA's EC 206-199-2 |
| `n-HFE-7100` | 163702-07-6 | Methyl nonafluorobutyl ether, straight chain | AR6 row at 544; the branched isomer is the next row at 437 |
| `i-HFE-7100` | 163702-08-7 | Methyl perfluoroisobutyl ether, branched | AR6 row at 437 |
| `n-HFE-7200` | 163702-05-4 | Ethyl nonafluorobutyl ether, straight chain | AR6 lists it as `HFE-569sf2` at 60.7, the factor EF carries; EF also ships the substance as `HFE-569sf2` under this number |
| `(E)-HFC-1234ze` | 29118-24-9 | (E)-1,3,3,3-Tetrafluoropropene, the trans isomer | AR6 row at 1.37. The stereo-unspecified parent, 1645-83-6, was refused because it would merge the two isomers |
| `(Z)-HFC-1234ze` | 29118-25-0 | (Z)-1,3,3,3-Tetrafluoropropene, the cis isomer | AR6 row at 0.315; PubChem CID 11116025 also lists the designation |
| `(Z)-HFC-1225ye` | 5528-43-8 | (Z)-1,2,3,3,3-Pentafluoropropene | AR6 row at 0.344; ECHA's EC 226-875-0 |
| `(Z)-HFC-1336` | 692-49-9 | cis-1,1,1,4,4,4-Hexafluoro-2-butene | AR6 row (`HFO-1336mzz(Z)`) at 2.08; EF also ships the substance as `(2z)-1,1,1,4,4,4-hexafluorobut-2-ene` under this number, agreeing on all 60 shared factors |
| `1,1′-Oxybis[2-(difluoromethoxy)-1,1,2,2-tetrafluoroethane]` (EF ships the name with its closing bracket missing) | 205367-61-9 | The same substance as `HG-02`, entered a second time | AR6's `HG-02` row at 5730, the factor EF carries; EF's `HG-02` rows carry the CAS number |
| `Perfluorodecalin (cis)` | 60433-11-6 | cis-Perfluorodecalin | AR6 row for Z-C10F18 at 7800; NIST files the CAS number as the cis form |
| `Perfluorodecalin (trans)` | 60433-12-7 | trans-Perfluorodecalin | AR6 row for E-C10F18 at 7120; NIST files the CAS number as the trans form. The isomer mixture `PFC-9-1-18` (306-94-5, GWP100 7480) stays a third substance |

One designation was deliberately left without a CAS number: `i-HFE-7200` is
163702-06-5, and EF 3.1 already carries that CAS number on `HFE-7200`, the
commercial product, which is a mixture of the n- and i- ethers. Asserting the
number would merge a mixture with one of its components.

### Numbers the build itself filled in

Besides the curated entries, the build adds a registry number to an EF
substance that shipped none where a single, checkable source states it.
Eighteen substances received one on the 2026-08-29 build:

| Substance | Number added | Where it came from |
|---|---|---|
| Furathiocarb | 65907-30-4 | Common Chemistry, exact match on the name |
| Dichromate | 13907-47-6 | Common Chemistry, exact match on the name |
| Polycyclic Aromatic Hydrocarbons | 130498-29-2 | Common Chemistry, exact match on the name |
| Thifensulfuron | 79277-67-1 | Common Chemistry, exact match on the name |
| Yttrium-90 | 10098-91-6 | Common Chemistry, exact match on the name |
| Cloransulam-methyl | 147150-35-4 | Common Chemistry, exact match on the name |
| 2,2,3,3-Tetrafluoro-1-propanol | 76-37-9 | Common Chemistry, exact match on the name |
| 2,2,3,4,4,4-Hexafluoro-1-butanol | 382-31-0 | Common Chemistry, exact match on the name |
| 2-Chloro-1,1,2-trifluoro-1-methoxyethane | 425-87-6 | Common Chemistry, exact match on the name |
| 2-Fluoroethanol | 371-62-0 | Common Chemistry, exact match on the name |
| Carbon tetrachloride | 56-23-5 | Common Chemistry, exact match on the name |
| Perfluorocyclopentene | 559-40-0 | Common Chemistry, exact match on the name |
| Quizalofop-P-ethyl | 100646-51-3 | Common Chemistry, exact match on the name |
| Tolylfluanid | 731-27-1 | Common Chemistry, exact match on the name |
| Bromomethane | 74-83-9 | Another EF 3.1 row with the same name carries it |
| Technetium-99m | 378784-45-3 | Another EF 3.1 row with the same name carries it |
| Tellurium-123m | 378784-49-7 | Another EF 3.1 row with the same name carries it |
| C12-14 Fatty Alcohol | 80206-82-2 | The ECHA inventory entry for EC 279-420-3, supplied above |

A name lookup is accepted only where the flow had no CAS number at all. It never
replaces a CAS number EF shipped, for the reason [When a name and a CAS number
disagree](../deciding/identity.md) gives: a generic name looked up returns a
generic number, and the specific one EF wrote would be lost.

### Name changes, for completeness

The remaining 137 entries in the fix file change a name, a synonym list, a
compartment or a unit rather than a CAS number, and are outside the four kinds of
change this page is about. Seventy-four rename a substance from its industry
part number to its chemical name —
`CFC-12` to `Dichlorodifluoromethane` — keeping the part number as a synonym
([#104](https://github.com/brightway-labs/brightway-flows/issues/104)).
The rest repair EF's own text: sixteen labels broken by a line wrap in the
source (`eico- safluoro` for `eicosafluoro`, and four more of the kind),
`Palladium-234m` for protactinium-234m (palladium has no isotope anywhere
near mass 234), `Praseodym-147` for `Praseodymium-147`, `silver-110` for
`silver-110m` (the long-lived isomer a reactor inventory reports),
`HFC-1234yf` for `HFO-1234yf` (the substance is an olefin), `turpentine` for
`Gum turpentine`, `dmpa` for `Zytron`, `polyhaloalkene` for
`2,3,3,3-Tetrafluoropropene`, `2-hydroxypropanoic acid` for `D-Lactic acid`,
`mecoprop-p` for `Mecoprop`, and `silicium tetrafluoride` for `silicon
tetrafluoride` — `Silicium` is the Latin name of the element, EF is the only
list here that uses it for SiF₄, and CAS, ecoinvent, BAFU and AGRIBALYSE all
write `Silicon tetrafluoride`
([#187](https://github.com/brightway-labs/brightway-flows/issues/187)) — and
a handful of others. Each entry in the fix file states its evidence.

One unit was changed: `actinium` (`08a91e70-3ddc-11dd-91b3-0050c2490048`)
ships in MJ because EF points it at the calorific-value property by a
one-digit typo in the property's identifier, and is published in kg, the unit
ecoinvent gives the same resource; nothing characterises the flow, so no
score moves.
