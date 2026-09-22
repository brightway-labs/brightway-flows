# Changes to AGRIBALYSE 3.2

*Part of [What was changed in each source](index.md). What is still open about
AGRIBALYSE 3.2 is on the issue tracker under the label
[`agribalyse`](https://github.com/brightway-labs/brightway-flows/issues?q=is%3Aissue+is%3Aopen+label%3Aagribalyse).*

AGRIBALYSE is ADEME's French agricultural database. It arrives as a SimaPro
process export, `AGB32_final.CSV` — 20,440 processes, 6,535,117 exchanges
with the environment — so its flows are the rows those exchanges name:
5,528 of them, of which 5,485 reach matching. The other 43 — the
`Final waste flows` compartment — are extracted and then refused on the
record ([#189](https://github.com/brightway-labs/brightway-flows/issues/189)):
a SimaPro final-waste row is an accounting device at the product-system
boundary, not an exchange with the environment, and the consensus vocabulary
has no waste compartment. Each refusal is published on this list's
correspondence under `brightway:excludedSourceConcept`, so a consumer
counting the vendor's rows against the associations sees a decision, not an
oversight.

The file ships no flow identifier of any kind (`Export platform IDs: No`).
Every row is therefore named the way the export writes it — name,
compartment and sub-compartment, unit — and the uuids this project gives
AGRIBALYSE rows are derived from those same fields. The unit is the one the
trailing substance blocks inventory the flow in, not the unit of any single
exchange: the 324 radionuclides are inventoried in kBq whatever scale a
process happened to state.

Because AGRIBALYSE's names carry SimaPro's habits — `Water, river, FR`,
`Gas, natural/m3` — the list is registered with `simapro_origin`, so it
receives every correction in `simapro-lineage-manual-fixes.json`, the
unit-suffix splitter and the SimaPro name rules, exactly as BAFU 2026 v1
and Stepwise 2006 do. The geography splitter is different: this page used
to say the list received it too, and no build ran it for any list but BAFU,
whose extractor calls it itself (#192). Since the list's manifest says
`simapro.geography_split: "load"`, the split runs as the flows are loaded —
`Water, river, FR` goes forward as `Water, river` in `FR`, the uuid and the
vendor file untouched, and the shipped spelling kept as a name the merge
and the published list still answer to. Its compartments go out as the vendor
wrote them; where they belong is stated in `context-manual-mapping.json`,
whose rules for this list agree with BAFU's on the eighteen compartments the
two spell identically.

## Not yet merged

AGRIBALYSE 3.2 is registered and extracted, and merges last (priority 400)
when a build names it. No documented shared build includes it yet, so this
page records no merge outcomes: no row has been sent anywhere by hand, no
registry number corrected, and no name split across two substances.
Measured with the read-only lookup against the 2026-08-30 build of
`f113244`, 4,077 of its 5,528 distinct flows already resolve to a consensus
flow (73.8%; 75.4% weighted by exchange traffic). The remainder are
catalogued in the issues under the label above — land classes, water
materials, river ties, and a small set of spelling variants.

## Particle rows read into a size window

AGRIBALYSE ships 27 airborne-particle rows, and every one is read into one of
the seven size windows the list publishes (`Particles (PM10)`, `Particles
(PM2.5)`, and so on). Twenty-five are BAFU's spellings and take BAFU's
readings. Two are the list's own, and were read on 2 September 2026
([#196](https://github.com/brightway-labs/brightway-flows/issues/196)):

| AGRIBALYSE row | Compartment | Published as | Why |
|---|---|---|---|
| `Particulates, diesel soot` | `Emissions to air` | Particles (PM0.2 - PM2.5) | Diesel exhaust particles are fine particulate, almost entirely below 2.5 µm and above the 0.2 µm ultrafine cut. |
| `Particulates, SPM` | `Emissions to air` | Particles (unspecified size) | Suspended particulate matter is a sampling term that states no cut, so it joins `Particulates` and `Particulates, unspecified`. |

Both minted a substance of their own, with no factor, on the first five-list
builds. A particle row that no reading covers now stops the merge instead of
doing that quietly.

## Carbon dioxide that did not say where it came from

`Glutamate {CN} U` releases 1.9175 tonnes of `Carbon dioxide` to air — the
whole carbon dioxide of a Chinese monosodium glutamate plant. The row names no
origin: not fossil, not biogenic, not land transformation, registry number
124-38-9 and nothing else. Carbon dioxide of unstated origin is a substance EF
3.1 ships, but no method characterises it, so those tonnes scored nothing for
climate change ([#194](https://github.com/brightway-labs/brightway-flows/issues/194)).

AGRIBALYSE ships the plain row twice, and the two are decided separately,
because their datasets have nothing in common:

| AGRIBALYSE row | compartment | datasets | published as | why |
|---|---|---:|---|---|
| `Carbon dioxide` | `Emissions to air` | 56, 46 non-zero | Carbon Dioxide (fossil) | industrial carbon dioxide: the glutamate plant, then 1,610 kg vented by `Atlantic Herring, NEA, Pelagic Trawl, average, at landing {NL}` against a purchased 1,610 kg of `Carbon dioxide, liquid {RER}`, then fire-extinguisher charges. BAFU's two plain rows (#139) and Stepwise's (#175) are on the same flow |
| `Carbon dioxide` | `Emissions to air / low. pop.` | 28, 18 non-zero | Carbon Dioxide (biogenic) | every non-zero dataset is biological decay: seven composts, from `Compost, of sludge and green waste (amendment) {RER}` at 29.6 kg down to green waste at 0.27 kg, and three straw-retting datasets at 18.1, 14.7 and 10.2 kg |

A third row did state an origin, and this project was not reading it.
`Carbon dioxide, peat oxidation` reached the same unstated-origin substance,
because `peat oxidation` was not one of the phrases the list recognises as
saying where carbon came from. It is now, and it is read as a land use change:
draining a peatland and letting the peat oxidise is a change of land use, and
AGRIBALYSE books it as one — its own `Peat degradation emissions on grassland,
per kg CO2 {GLO}` ships the release as `Carbon dioxide, land transformation`,
and its soil carbon datasets say their land-transformation row is "excluding
peat degradation", the same accounting split out rather than a different kind
of carbon. Under EF the total climate-change score is the same either way; what
the reading decides is whether the mass lands in *Climate change-Fossil* or in
*Climate change-Land use and land use change*.

Reading the phrase rather than curating the row answers `Methane, peat
oxidation` in the same line — six datasets with the same defect, which #194 does
not mention. Those three names are every name carrying the phrase across EF 3.1,
all five ecoinvent releases, BAFU 2026-v1, Stepwise 2006 and AGRIBALYSE 3.2.

The third, `Dinitrogen monoxide, peat oxidation`, is the one the rule cannot
finish, and it is worth reading before writing a rule of the same shape. The
reading is right about it — the nitrous oxide comes off the same drained peat —
but EF ships no nitrous oxide of land-use-change origin to move it to, and
qualifying the name is by itself enough to take the row off the flow it was
already on. Its registry number, 10024-97-2, reaches two substances: nitrous
oxide, and the correction flow for nitrous oxide emitted after a hundred years.
What separated them was the row's own name sitting on nitrous oxide as a
synonym, put there by the row itself; a name that carries an origin is filed
elsewhere, the synonym is not carried, and a row that was correctly placed is
published nowhere. So this one is sent by hand, in
`agribalyse-3.2-match-overrides.json`, to the flow it already had.

## Registry numbers corrected

AGRIBALYSE's flow list is SimaPro's copy of EF 3.1's, and on a few names it
carries a number EF's own row had wrong or that names the element where the
name states an ion. `agribalyse-3.2-manual-fixes.json` corrects each, keyed on
the name and the number the vendor wrote, so a row already carrying the right
number is left alone.

| AGRIBALYSE name | number shipped | corrected to | which is |
|---|---|---|---|
| `Lithium (I)` | 7439-93-2 | 17341-24-1 | the element's number on the lithium(1+) ion; six rows, which reached bare `Lithium` while ecoinvent's `Lithium I` reached the ion ([#198](https://github.com/brightway-labs/brightway-flows/issues/198)) |
| `Potassium (I)` | 7440-09-7 | 24203-36-9 | the element's number on the potassium(1+) ion; twelve rows, the same shape |
| `Antimony, ion` | 7440-36-0 | removed | the element's number on a generic ion, which no number names; eleven rows, which reached bare `Antimony` and now reach the numberless `Antimony, Ion` ecoinvent's rows minted (#198) |
| `Chromium, ion` | 7440-47-3 | removed | the same; thirteen rows, which mint `Chromium, Ion` beside the charged chromium ions, since no list publishes a generic one |
| `Copper, ion` | 7440-50-8 | removed | the same; fifteen rows, now on `Copper, Ion` |
| `Iron, ion` | 7439-89-6 | removed | the same; twelve rows, now on `Iron, Ion` |
| `Tin, ion` | 7440-31-5 | removed | the same; twelve rows, now on `Tin, Ion` |
| `Titanium, ion` | 7440-32-6 | removed | the same; twelve rows, now on EF 3.1's own `Titanium, ion` |

The file holds the earlier corrections too — `Vanadium (V)` and `Arsenic (V)`
under the wrong ions' numbers, and the bare graded-ore rows given their
elements' numbers (#190).

## Curated targets

`agribalyse-3.2-match-overrides.json` sends a row where the merge would not
put it on its own. Beside the water and energy rows described above, three
rows named `Carbon, organic, in soil or biomass stock` go to EF 3.1's
`Carbon, Organic, In Soil Or Biomass Stock`
([#195](https://github.com/brightway-labs/brightway-flows/issues/195)).
The rows carry the element's number, 7440-44-0, which #116 ruled groups
nothing, and without the target they fell through to the tail of their name
and minted a `Carbon` resource in the ground under elemental carbon: 2,278
datasets read as digging the element out of the ground, `Mine
infrastructure, phosphate rock {GLO}` alone 31,640 kg of it. ecoinvent's and
BAFU's rows of the same name are on the stock flow, ecoinvent's Increase row by
the same kind of target.

The three differ only in the compartment the exporter wrote. The `in ground`
one is ecoinvent's, carried through 2,307 datasets. The bare `Resources` one is
AGRIBALYSE's own soil carbon accounting, and it puts both directions on a single
row — positive when carbon leaves the soil, negative when it is stored, as the
vendor writes on the row itself — so it is folded into one flow the way
ecoinvent's Increase and Decrease rows are (#116). The third occurs once, in
`Peat degradation emissions on grassland, per kg CO2 {GLO} - Adapted from
WFLDB`, and that dataset shows why none of the three is an emission: it already
emits the carbon. Beside the 0.2727 kg on the stock row it ships 1 kg of `Carbon
dioxide, land transformation`, and 0.2727 kg is 12/44 of that — the same carbon,
booked a second time for the resource accounting, which the dataset's own comment
says it is doing. Every dataset carrying a stock row does this: 0.017 kg of stock
carbon against 0.0623 kg of CO2 in the annual-crops land use change dataset,
−0.0110 kg against 0.0403 kg of `Carbon dioxide, to soil or biomass stock` in the
permanent-meadows one, always 44/12 apart (`AGB32_final.CSV`). Sending a stock
row to a CO2 flow would count that carbon twice. EF 3.1 characterises the stock
flow at nothing, which is what a ledger entry should score.

## Finding the original row

The pages' convention for a list without vendor identifiers applies: rows
are quoted by name, compartment and unit as `AGB32_final.CSV` writes them,
and the project's uuids are stable across builds but are not ADEME's.
