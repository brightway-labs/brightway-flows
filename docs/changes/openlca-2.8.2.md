# Changes to openLCA LCIA methods 2.8.2

*Part of [What was changed in each source](index.md). What is still open about
GreenDelta's package is on the issue tracker under the label
[`greendelta`](https://github.com/brightway-labs/brightway-flows/issues?q=is%3Aissue+is%3Aopen+label%3Agreendelta).*

GreenDelta publishes the LCIA methods it implements for openLCA as one archive,
`openLCA LCIA Methods 2.8.2 2026-07-01.zip`: 45 methods — ReCiPe 2016, CML-IA,
TRACI, IMPACT 2002+, EF 3.1 and its predecessors, IPCC, USEtox, EPS and others —
and the 61,211 elementary flows they characterise between them. This list is
those flows. The characterisation factors are not read here.

That makes it a list of what 45 methods characterise rather than of what
inventories emit. Theophylline sent to agricultural soil is on it, in 11
compartments, because a toxicity method has a number for it; a substance no
method scores is absent however often a process releases it.

The flows carry GreenDelta's own identifiers, except for 4,479 that reuse an
identifier ecoinvent 3.8 or 3.12, or EF 3.1, already ships. Most rows have a
registry number (55,630 of 61,211), written zero-padded the way SimaPro writes
it — `000058-55-9` for theophylline — and read here without the padding, so one
number reaches one substance whichever list it came from.

The compartments are ecoinvent 2's words — `Emission to air / low population
density`, `Resource / in ground` — and 21 of the 33 are the ones GreenDelta's EF
3.1 package already uses. They are placed the same way here as for that
package. Of the other twelve, two are refused (below), and four hold more than
one kind of flow so the name decides:

| Compartment | Holds | Placed as |
|---|---|---|
| `Resource / unspecified` | 1,565 water intakes, 250 land rows, ores and fuels, and a few biomass, air and hydropower rows | Water by name, land use by name, and each of the other 325 by a rule naming the row: 310 as ground resources, 5 biotic (`Energy, from wood`), 4 from air (`Carbon dioxide`, `Energy, solar, converted`), 2 from water (`Energy, from hydro power`) and 4 Eco-indicator `Land use` rows as land occupation |
| `Resource / land` | 667 land rows, 3 Eco-indicator `Land use` rows, 27 minerals (`Clay`, `Granite`, …), two water intakes | Land use by name, water by name, anything else as land occupation, as BAFU's `resources / land` is; each mineral by a rule naming the row, as a ground resource |
| `Resource / in ground` | Ores and fuels, and 266 water intakes | Water by name, the rest as ground resources |
| `Resource / in water` | 1,744 water intakes and a few dissolved minerals | Water |

The six noise rows in `Immaterial emission` go where BAFU's do.

## Waste rows refused

The 186 rows in `Waste / unspecified` (94) and `Waste / ecopoints 97, CH` (92) —
`Packaging waste`, `Slags`, `Chemical waste` and the like — are final waste
leaving the product system, which Ecological Scarcity 1997 scores, and not
exchanges with the environment. They are refused, as AGRIBALYSE's final waste is
([#189](https://github.com/brightway-labs/brightway-flows/issues/189)), and each
is published as an excluded source concept with the reason, so somebody counting
GreenDelta's rows against this list's correspondence can see a decision rather
than a gap.

## Black carbon refused

GreenDelta ships 13 rows of black carbon sorted by particle size:
`Particulates, < 2.5 um, black carbon` (5 air compartments),
`> 2.5 um, and < 10um, black carbon` (4) and `> 10 um, black carbon` (4). For
particulate matter, EF 3.1 and ECO-COSTS 2025 give them the same factors as the
plain particle flow of the same size and compartment. IPCC 2021 also gives them
a climate factor — 658.6 kg CO2-eq per kg over 100 years — that no plain
particle row has.

Placing them on PM2.5 or PM10 would put that climate factor on every PM2.5 or
PM10 emission. Whether black carbon is a substance of its own is not decided
yet ([#384](https://github.com/brightway-labs/brightway-flows/issues/384)),
so the 13 rows are refused and published as excluded with the reason.

## Gamma-chlordane refused

The package ships `Chlordane, gamma-` four times (air, agricultural soil,
unspecified soil, unspecified water) under 5566-34-7. Gamma-chlordane is the
environmental literature's name for trans-chlordane, which the package also
ships, as `Chlordane, trans-` (5103-74-2), in the same compartments; and
5566-34-7 is not a chlordane at all but a differently chlorinated indene that no
inventory reports. Stepwise 2006 ships one row of the same name and
[`stepwise-2006-additional-flows.json`](https://github.com/brightway-labs/brightway-flows/issues/167)
refuses it with that reasoning; the four rows here are refused the same way.
On the first build that merged the list (20 October 2026) they had been
published as a fifth chlordane, with no factor from any implementation.

## EF 3.1's own flows

125 rows carry an EF 3.1 identifier: GreenDelta's copy of EF's flow, renamed in
ecoinvent's spelling. `Particulates, < 10 um` in unspecified air is EF's
`particles (PM10)`, and `Copper ion` under `Resource / in ground` is EF's copper
resource. The merge sends each one to the EF 3.1 flow with that identifier,
recorded as `shared_identifier` rather than as a name-and-registry-number match.

## Particle sizes

43 of the package's particle rows are read in `particulate-flow-classes.json`.
All but one spelling are ecoinvent's, BAFU's or Stepwise's, and are read as
those lists' are. The new spelling is `Particulates, > 0.2 um, and < 2.5 um`,
read as EF 3.1's `Particles (PM0.2 - PM2.5)`.

## Location-specific rows refused

6,206 rows write a place into the name. Every one is refused and published as
excluded with the reason. They cover 372 places, from countries (`ES`, `NO`)
to regions (`RoW`, `UCTE`, `IAI Area, Africa`):

- 4,690 water rows: `Water, river, CH`, `Water, RoW`,
  `Water, cooling, unspecified natural origin, IAI Area, Africa`;
- 949 emissions to air: `Nitrogen oxides, ES`, `Ammonia, FR`,
  `Sulfur dioxide, AT`;
- 134 emissions to water: `Nitrate, DE`, `Phosphorus, DK`, and `Nitrogen, NO`,
  which is nitrogen emitted in Norway (GreenDelta's description says
  `NO = Norway`);
- 433 land rows: `Transformation, from forest, extensive, GA`,
  `Occupation, permanent crop, BR`.

The unregionalised row is kept: `Water, river`, `Nitrogen oxides`,
`Transformation, from forest, extensive`. The location-specific rows carry
factors their unregionalised row does not always agree with. Ecological
Scarcity 2013, for one, gives `Nitrogen, NO` a factor (57,000) and plain
`Nitrogen` none. These are left out with the rows.

## Factors for a place left out of BAFU's EF 3.1

The same decision applies to the factors GreenDelta states for EF 3.1, which
BAFU's source reads out of this package. `Occupation, agriculture` has one
land-use factor for no place and 400 more, one per country or region. The
package states 183,654 EF 3.1 factors; the 91,304 tied to a place are left
out, and the 92,350 for no place are read. Every one of the 33,045 flows has
one. 69,116 of those left out are land use and 12,928 water use. The JRC's own
EF 3.1 factors per country are unaffected.

## Which kind of water each water row is

Every kind of water has the same registry number, so the merge tells river
water from sea water or cooling water only by a reading in
`water-flow-materials.json`. 123 water rows are left once the location-specific
ones are refused
([#389](https://github.com/brightway-labs/brightway-flows/issues/389)). 101 of
them, under 54 names, are read:

- A name another list already ships is read the way that list reads it:
  `Water, river` is river water, `Water, salt, sole` brine, `Water, cooling,
  well` cooling water.
- A name that says what the water is, is read that way: `Water, ground` and
  `Water, process, well` are groundwater, `Water, process, salt, ocean` sea
  water, `Cooling water` returned to a river is cooling water.
- Four readings are ours rather than the name's. `Water, thermoelectric
  groundwater consumption` and its saline and surface siblings are cooling
  water: it is the water a power plant's cooling uses up, and every cooling
  name is read by its use. `Thermally polluted water` is returned cooling
  water, warm rather than contaminated. `Water, with river silt` is river water.
- Names that say nothing about the source, such as `Water`, `Water/kg` and
  `Water, process and cooling, unspecified natural origin`, are water of no
  stated kind. So is `Water, unspecified natural origin` filed `in ground`,
  for the reason BAFU's is
  ([#89](https://github.com/brightway-labs/brightway-flows/issues/89)).

Where two names are read as one kind of water, the methods in the package
score them alike, with one exception: ECO-COSTS 2025's `Baseline Water
Stress` gives some of them different factors, for example −0.0001 to the
thermoelectric rows and +0.0001 to the cooling rows. They are read as one
kind of water regardless.

Twenty-two rows are refused for good, because they are not a kind of water:

- The 11 water-stress rows, `Water, low water stress` to `Water, unspecified
  natural origin, very high water stress`. A stress class stands in for the
  watershed the water came from, as a place in the name does. Ecological
  Scarcity 2006 and 2013, ILCD 2011 and ECO-COSTS 2025 score each class
  differently — Ecological Scarcity 2013 from 24 to 22,000 — and the other
  methods score every class as plain water.
- the 11 `Water BWS` rows, `Water BWS 0%` to `Water BWS 100%`. Only ECO-COSTS
  2025 scores them, with a factor equal to the percentage in the name.

## Which land class each land row is

All 490 land rows that are kept are read in `land-flow-classes.json`. Sixteen
of them use words the other lists don't, and each was read as follows:

- `Occupation, annual crop, conservation tillage`, and `conventional` and
  `reduced`: cropland under that tillage, the class ecoinvent's
  `arable, … tillage (obsolete)` rows already have. Every method in the
  package gives them the factors of `annual crop`.
- `annual crop, non-irrigated, monotone-intensive`, in all three
  directions: cropland, non-irrigated, farmed **monotone-intensive** — a
  new intensity, beside `diverse-intensive`. Every method gives it the
  factors of `annual crop, non-irrigated` except Ecosystem Damage
  Potential, which scores it 0.74 against diverse-intensive's 0.61.
- `Transformation, to unknown (used)`: to unspecified land in use, the
  class of `Transformation, to unspecified, used`. EF 3.1 scores it
  1,914.6, which EF 3.0 gives the other spelling.
- `Transformation, from agriculture + forest`, and `to`: agroforestry,
  read as agriculture, mosaic. CORINE files agro-forestry areas (2.4.4)
  under heterogeneous agricultural areas (2.4).
- `Occupation, sparsely vegetated areas, steppe, tundra, badlands`: CORINE
  Land Cover class 3.3.3, published as a new cover, **sparsely vegetated
  area**. It is not read as grassland, because ILCD 2011, IMPACT 2002+ and
  EF 2.0 score it differently from openLCA's `Occupation, grassland`.

## Water measured by mass

Liquid water is published in cubic metres throughout this list, and the
package measures 52 of its kept water rows by mass, under 33 names — `Waste
water`, `Water` emitted to a river, `Water, cooling, well`, `Water, process,
unspecified natural origin/kg`, `Thermally polluted water` — beside cubic-metre
rows of the same kinds of water. `openlca-2.8.2-manual-fixes.json` rewrites
every one of them to cubic metres at 0.001 m³ per kg, as
`bafu-2026-v1-manual-fixes.json` did for BAFU's sixteen
([#78](https://github.com/brightway-labs/brightway-flows/issues/78)), and the
density is published on each row's concept association, so a factor the
package states per kilogram is converted by the same number. On the first
build that merged the list (20 October 2026) the two `Waste water` rows had
published a kilogram flow beside the cubic-metre one and ten of the package's
own factors were unit crossings. The first fifty rewrites took the names
beginning `Water` and `Waste water` and missed the two ending in `polluted
water`: on the six-list build of 20 October 2026 `Thermally polluted water`
was a kilogram row on the cubic-metre `Cooling water` flow, and `Chemically
polluted water` published a kilogram `Contaminated water` flow in water,
unspecified, beside BAFU's cubic-metre one in a river. The four names ending in
`/kg` keep the package's spelling; the unit field is what the build reads.

## Carbon released when land changes use

ecoinvent books the carbon released when land changes use as `Carbon dioxide,
from soil or biomass stock`, and the same for carbon monoxide and methane. The
package ships 17 of these rows, under ecoinvent's uuids and names. ecoinvent's
own rows reach EF 3.1's `(land use change)` flow of each gas through
ecoinvent's table, where EF states +1 kg CO2-eq for carbon dioxide. Nothing read
the phrase on the package's copies, so on the six-list build of 23 October
2026 (commit 5802a4c) the twelve with a registry number reached the plain gas,
and the carbon dioxide rows created four carbon dioxide emissions of unstated
origin in air, which no method characterises. GreenDelta's own +1 for the same
uuids sat on the land-use-change flows, so the release scored zero through the
package's rows and +1 through ecoinvent's.

`from soil or biomass stock` is now read as land use change, as BAFU's `land
transformation` and AGRIBALYSE's `peat oxidation` are, and every one of the 17
rows reaches the flow ecoinvent's row of the same uuid reaches
([#435](https://github.com/brightway-labs/brightway-flows/issues/435)). The
capture, `to soil or biomass stock`, keeps its own reading.

## Two numbers for one flow

The package can state two different numbers for one flow of ours in one EF 3.1
category, and GreenDelta's implementation then publishes neither: 79 times on
the six-list build of 24 October 2026 (commit 34984fd). Traced against the JRC's
own factors, most of these are two rows of the package that each carry the
factor of a *different* EF flow, reaching one flow of ours.

- **One row is the package's copy of an ecoinvent row.** Under ecoinvent's
  uuid, it carries ecoinvent's own number, and ecoinvent's implementation
  attached that row to a different EF flow than GreenDelta did: `Paraquat` to
  surface water at 17,533 (EF's paraquat dichloride) against GreenDelta's own
  190,560 (EF's paraquat). The copy's number is already published as the
  ecoinvent Centre's, so the copy gives way and GreenDelta's own row is
  published. In the MCPA pair the copy carries EF's number for MCPA and
  GreenDelta's own row the number for MCPA-sodium, so GreenDelta's published
  factor differs from the JRC's there, which is what GreenDelta states.
  [Factors](../concepts/factors.md) has the examples side by side.
- **One row was on the wrong flow.** Nine `difenzoquat` rows carry the salt's
  factors under the cation's number, and 16 `Arsenic ion` rows carry the
  element's factors under arsenate's number. Their registry numbers are
  corrected below, and each row reaches the flow its factors belong to.
- **Not settled yet.** Fenoxycarb is EF 3.1's own duplicate: EF ships it
  twice, under 72490-01-8 and 79127-80-3, with factors about 740 times apart,
  this list publishes both as substances, and GreenDelta copied both. The
  package's 18 `Fenoxycarb` rows with no number carry the 79127-80-3 entry's
  numbers and reach the 72490-01-8 substance by name. Which substance they
  belong on waits on
  [#130](https://github.com/brightway-labs/brightway-flows/issues/130), which
  asks which entry EF's numbers describe. The rest need a curated ruling
  ([#439](https://github.com/brightway-labs/brightway-flows/issues/439)).
- **Ruled: chromium(3+) in non-urban air.** Two `Chromium III` rows reach it,
  and one carries EF's numbers for elemental chromium: 4,292.06 against 333.75
  for freshwater ecotoxicity, and 7.8328e-7 against 1.7032e-9 for non-cancer
  human toxicity. Nothing else about that row says elemental chromium. Its
  formula is `Cr3+`, and every other method in the package scores it as
  chromium(3+). So the chromium(3+) number is published, in all four categories
  the two rows share
  ([#445](https://github.com/brightway-labs/brightway-flows/issues/445)).

## Rows sent to a curated target

`openlca-2.8.2-match-overrides.json` names the flow for 30 rows the merge
placed wrongly on the first build, each row citing what the package's own
characterisation factors say it means — the evidence a method package carries
where an inventory database carries exchanges
([#412](https://github.com/brightway-labs/brightway-flows/issues/412)).

- **Six plain `Carbon dioxide` rows.** Every method in the package scores the
  five air rows as fossil carbon dioxide (EF 3.1 `Climate change (fossil)` 1.0,
  IPCC 2013 `fossil`, CML, EDIP), so they go to EF's fossil flows, as BAFU's
  two unqualified rows do; the row in `Resource / unspecified` is scored as
  uptake (IPCC 2013 `CO2 uptake` 1.0, ILCD −1) and goes to EF's biogenic
  uptake from air, as BAFU's `Carbon dioxide, in air` rows do. As shipped they
  had reached carbon dioxide of unstated origin, which no other list's row does.
- **Three kilogram `Peat` rows.** EF 3.1 (adapted) scores the biotic row
  `Resource use, fossils` at 9.76 MJ/kg and every method scores all three as
  fossil fuel, so all three go to the megajoule fuel `Peat` at that factor. A
  method package's peat is the fuel; AGRIBALYSE's biotic kilogram is the
  growing medium because an agricultural database's peat is a substrate.
  The biotic row is re-filed into the ground by the manual fixes first,
  because the merge keeps a row in the compartment it names where that
  contradicts the target's (#84), and it had made a biotic megajoule peat.
  The biotic row is ecoinvent's own, under ecoinvent's uuid, and the merge
  places ecoinvent's copy on `Peat, Horticulture`; the two readings of one
  flow are left to disagree for now, recorded on #412.
- **Two unqualified biomass-energy rows and two `Anhydrite` rows.** `Energy,
  gross calorific value, in biomass` reaches the `Biomass` flow ecoinvent's,
  BAFU's and AGRIBALYSE's rows reach; `Anhydrite`, under the mineral's own
  14798-04-0, reaches the `Calcium Sulfate` that #597 reads anhydrite as. As
  shipped, each pair minted a substance of its own and the read-only lookup
  sent the other lists' rows there.
- **Sixteen `Hydrocarbons, unspecified` rows.** The bucket EF 3.1 publishes as
  `Hydrocarbons (unspecified)`, shipped with no number under ecoinvent's
  spelling; the two rows that are EF's own flows reach it by uuid, and the
  sixteen others minted a second bucket. Each goes to EF's flow in its own
  compartment, or to the flow BAFU's or ecoinvent's row already added there.
- **`Carbon dioxide, in air`.** ecoinvent's uptake row, under ecoinvent's
  uuid, goes to EF's biogenic uptake from air, where ecoinvent's own copy,
  BAFU's three and AGRIBALYSE's two go. `in air` is a compartment, not an
  origin, so no rule can read it; as shipped, the row created a plain carbon
  dioxide resource in air that nothing else fed
  ([#435](https://github.com/brightway-labs/brightway-flows/issues/435)).

One row is kept where the first build put it: the bare `Carbon` in
`Resource / in ground` (7440-44-0) is scored by the Crustal Scarcity Indicator
alone, at 140, which counts elements in the crust. It is elemental carbon as a
mineral resource, a flow no other list has, and it stays a flow of its own.

## The first build with the list

openLCA LCIA methods 2.8.2 merges last (priority 500) when a build names it;
the default build, which the other pages' numbers come from, does not name it.
The first full build to merge it ran on 20 October 2026 — ecoinvent 3.12 and
3.8, BAFU 2026 v1, Stepwise 2006, AGRIBALYSE 3.2 and this list, merge run
`76b3ec8f` — once the 23 land folds above were recorded
([#385](https://github.com/brightway-labs/brightway-flows/issues/385)). Of the
54,784 rows merged, 53,081 reach a flow another list already published: 51,207
by registry number, 861 by name, 454 by land class, 100 by kind of water, 41 by
particle size window, 119 by a uuid EF 3.1 already ships, and the rest by a
registry number together with a name or qualifier. The other 1,703 are
published as new flows over 1,095 new substances; no row is left unmatched.
The 213 copies ruled duplicates are published deprecated.

That build is not yet a documented one, so this page records no row sent
anywhere by hand, no registry number corrected, and no name split across two
substances for this list.

## One name, two substances

On the first build that merged the list (20 October 2026), rows that ship no
registry number under a spelling the list already publishes as a synonym
minted second substances under the same label: `Vanadium V` (three rows),
`Lithium I` (one) and `Titanium Ion` (fourteen) beside `Vanadium(5+)`,
`Lithium(1+)` and `Titanium, ion`. The merge refused those synonyms because an
alternative-label hit on a substance that carries a registry number is its
guard against a trade name; a synonym the ion naming standard wrote is the
substance's own name in another spelling, and the merge now accepts it for a
row that ships no number under exactly that spelling
([#412](https://github.com/brightway-labs/brightway-flows/issues/412)).

## An ionic charge was added or corrected

No row's name or number is rewritten. The package names metal ions with a
Stock numeral or the generic marker — `Cadmium II`, `Arsenic V`, `Copper
Ion` — and on 339 of those rows, under 29 names, writes the bare metal's
registry number: 7440-43-9 on `Cadmium II`, 7439-92-1 on `Lead II`
([#380](https://github.com/brightway-labs/brightway-flows/issues/380)). On
the six-list build of 21 October 2026 every one of them reached the metal by
the number, while the package's sibling rows carrying the ion's own number
reached the ion, so `Cadmium II` was two substances depending on which number
the row carried.

The merge now reads such a row as the ion its name states and sets the
metal's number aside, for every list alike
([the rule](../deciding/merging.md#an-ion-name-beside-the-bare-elements-number-is-the-ion)).
The mapping's `basis` reads `label+element-number-set-aside` and its details
name the number. Every ion below already exists in the list, so nothing is minted. The
rows carrying the ion's own number — `Cadmium II` under 22537-48-0,
`Arsenic V` under 17428-41-0 — are untouched and keep reaching the ion by the
number, and the 20 `Pyrethrin I` and `Pyrethrin II` rows are not ions and
are not read by this rule.

| Name | Rows | Number shipped | Reached on the build of 21 October | Reaches now |
|---|---:|---|---|---|
| `Aluminium III` | 10 | 7429-90-5 | `Aluminium` | `Aluminium(3+)` |
| `Antimony Ion` | 12 | 7440-36-0 | `Antimony` | `Antimony, ion` |
| `Arsenic Ion / Arsenic ion` | 16 | 7440-38-2 | `Arsenic` | `Arsenic, ion` |
| `Barium II` | 10 | 7440-39-3 | `Barium` | `Barium(2+)` |
| `Beryllium II` | 10 | 7440-41-7 | `Beryllium` | `Beryllium(2+)` |
| `Cadmium II` | 18 | 7440-43-9 | `Cadmium` | `Cadmium(2+)` |
| `Caesium I` | 4 | 7440-46-2 | `Cesium` | `Caesium(1+)` |
| `Calcium II` | 7 | 7440-70-2 | `Calcium` | `Calcium(2+)` |
| `Chromium III` | 16 | 7440-47-3 | `Chromium` | `Chromium(3+)` |
| `Cobalt II` | 10 | 7440-48-4 | `Cobalt` | `Cobalt(2+)` |
| `Copper Ion / Copper ion` | 18 | 7440-50-8 | `Copper` | `Copper, ion` |
| `Iron Ion / Iron ion` | 9 | 7439-89-6 | `Iron` | `Iron, ion` |
| `Lead II` | 15 | 7439-92-1 | `Lead` | `Lead(2+)` |
| `Lithium I` | 8 | 7439-93-2 | `Lithium` | `Lithium(1+)` |
| `Manganese II` | 10 | 7439-96-5 | `Manganese` | `Manganese(2+)` |
| `Mercury II` | 12 | 7439-97-6 | `Mercury` | `Mercury(2+)` |
| `Molybdenum VI` | 24 | 7439-98-7 | `Molybdenum` | `Molybdenum(6+)` |
| `Nickel II` | 17 | 7440-02-0 | `Nickel` | `Nickel(2+)` |
| `Palladium II` | 1 | 7440-05-3 | `Palladium` | `Palladium(2+)` |
| `Potassium I` | 2 | 7440-09-7 | `Potassium` | `Potassium(1+)` |
| `Rhodium III` | 2 | 7440-16-6 | `Rhodium` | `Rhodium(3+)` |
| `Selenium IV` | 13 | 7782-49-2 | `Selenium` | `Selenium(4+)` |
| `Silver I` | 14 | 7440-22-4 | `Silver` | `Silver(1+)` |
| `Strontium II` | 12 | 7440-24-6 | `Strontium` | `Strontium(2+)` |
| `Thallium I` | 12 | 7440-28-0 | `Thallium` | `Thallium(1+)` |
| `Tin Ion / Tin ion` | 16 | 7440-31-5 | `Tin` | `Tin, ion` |
| `Titanium Ion / Titanium ion` | 10 | 7440-32-6 | `Titanium` | `Titanium, ion` |
| `Vanadium V` | 13 | 7440-62-2 | `Vanadium` | `Vanadium(5+)` |
| `Zinc II` | 18 | 7440-66-6 | `Zinc` | `Zinc(2+)` |

## Rows merged into one flow

**Land-use rows shipped twice.** 181 land-use names are in the package more
than once with the same unit: `Occupation, annual crop` in `Resource / land`
and again in `Resource / unspecified`, and so for 175 of them. Each copy is the
same land class, and both map to the same flow. The row in `Resource / land` is
kept as the valid one. The other copy, 185 rows in all, still maps but is
published deprecated, pointing at the valid row (`source-row-duplicates.json`).
The 15 names whose class another name also reaches, `Occupation, annual crop`
among them, were ruled on 20 October 2026, when the first build with the list
showed the folds below. Two names needed a different tie-break:

- `Occupation, sea and ocean` has no `Resource / land` copy, so the
  `Resource / in water` row is kept over `Resource / unspecified`.
- `Occupation, inland waterbody, unspecified` is in `Resource / land` twice,
  with one factor each. The row kept is the one whose identifier ecoinvent 3.12
  also ships.

**Water rows shipped twice.** 25 water names are in the package more than once
with the same unit, usually in `Resource / in water` and again in
`Resource / unspecified`. Every copy reaches `Resource / water`, and the row in
`Resource / in water` is kept as the valid one; the other copies, 28 rows,
still map but are published deprecated. The copies are scored alike, except
that EF 3.1 gives the `Resource / land` copy of `Water, process, unspecified
natural origin/kg` a water-use factor of 0.0.

A deprecated copy does not weaken the valid row's match: two copies of one flow
are not two flows sharing one.

**Land classes folded.** 23 land classes are each reached by two openLCA names,
and 3 of them by three; `land-flow-groupings.json` records every fold with its
reasoning and the factors behind it. In nine, the names are EF 3.1's word
beside ecoinvent's, shipped under ecoinvent's own uuid, and in seven of those
the ecoinvent or BAFU grouping on the same flow already makes the fold:
`Occupation, annual crop` with `Occupation, arable land, unspecified use` and
both of its transformations; `unknown` with `unspecified` in both
transformations and in occupation; `agriculture, mosaic` with `heterogeneous,
agricultural` in all three directions, where `agriculture + forest`,
agroforestry, is the third name. The other fourteen are GreenDelta's own
spellings beside ecoinvent's or EF's: a plural (`lakes, artificial`, `rivers,
artificial`, `urban, green areas`) in six classes, the older `arable` beside
`annual crop` in the three tillage classes and the two organic ones, `cropland
fallow (non-use)` beside `annual crop, fallow` in the two fallow ones, and `to
unknown (used)` beside `to unspecified, used`. In 21 of the 23 the package's
factors never disagree between the names: a method either scores both alike or
scores only one. The two that disagree are the transformations from and to
`agriculture, mosaic`: EF 2.0 gives `agriculture + forest` its catch-all 134
against 121 for the others, and ILCD 2011 gives `to agriculture, mosaic` 245
against 485 for `to heterogeneous, agricultural`. Counted on the build of
20 October 2026, over the factors the package states without a place.

Beyond land use, the package ships 504 pairs of flows with the same name,
compartment and unit — usually GreenDelta's own flow beside ecoinvent's copy of
it, and in 85 of them only one of the two has an EF 3.1 factor. None of
those is ruled on yet.

## Registry numbers corrected

| openLCA name | Compartments | Number removed | Why |
|---|---|---|---|
| Nitrogen, organic bound | water: all eleven the package uses | 7727-37-9 | that is N₂, the gas that is most of the air; organically bound nitrogen is a measurement over many compounds and no CAS number names it. The gas's two synonyms, `dinitrogen` and `molecular nitrogen`, come off the same rows. Left on, the rows would fuse with nitrogen gas ([#57](https://github.com/brightway-labs/brightway-flows/issues/57)) |
| Stibnite | `Resource / in ground` | 1345-04-6 → 1317-86-8 | the row is ecoinvent's, under ecoinvent's uuid, and carries the manufactured antimony trisulfide's number where the mineral's is 1317-86-8 (IARC vol. 47); ecoinvent's own fixes rewrite it, BAFU registers its stibnite 1317-86-8, and left as shipped the row joined EF's thirteen emission flows of the compound on the build of 20 October 2026 ([#123](https://github.com/brightway-labs/brightway-flows/issues/123)) |
| Ether, 1,2,2-trifluoroethyl trifluoromethyl-, HFE-236ea2 | air: four compartments | 2356-62-9 → 84011-06-3 | 2356-62-9 is HFE-227ea's number, under which EF 3.1 registers `HFE-227EA`; EF registers `HFE-236ea2` 84011-06-3 and Stepwise 2006 writes that number on its row of this name. As shipped, the four rows reached `HFE-227EA`, and GreenDelta's two factors for one flow were reported as eight collisions |
| Arsenic V | air, soil and water: fourteen compartments | 61805-96-7 → 17428-41-0 | 61805-96-7 names no arsenic compound: Common Chemistry does not resolve it and PubChem lists it only as a second number on 1,3-dimethylthiourea. The name is EF 3.1's `arsenic (v)`, 17428-41-0, published as `Arsenic(5+)`; as shipped, the rows minted a second `Arsenic(5+)` beside it |
| HG-02 | `Emission to air / unspecified` | none → 205367-61-9 | an industry designation for a hydrofluoropolyether, which EF 3.1 shipped under the designation and `ef-3.1-manual-fixes.json` renamed; the package copies the designation with no number, and its own factors (EF 3.1 `Climate change` 5,730, IPCC 2013 2,730) are that molecule's. As shipped, the row minted a second `HG-02` |
| Tribromomethane | `Emission to air / unspecified` | none → 75-25-2 | bromoform, which the package ships twenty times under that name with the number; this one row carries the systematic name alone and bromoform's factor (0.25). As shipped, it minted a second substance |
| Helium, in natural gas, in ground | `Resource / in ground` | none → 7440-59-7 | ecoinvent's `Helium, in natural gas` under ecoinvent's uuid, copied without the number ecoinvent's table reaches helium with. As shipped, it minted a substance named for a compartment |
| Propane, Dibromopentafluoro- and five more | `Emission to air / unspecified` | none → 431-78-7, 453-00-9, 460-86-6, 666-25-1, 421-90-9, 172912-75-3 | six rows under Stepwise 2006's SimaPro spellings, copied without the numbers Stepwise's rows reach EF's substances under; the SimaPro name rewriting runs for SimaPro-shaped lists only. As shipped, each minted a substance under the SimaPro name and the lookup sent Stepwise's rows to it |
| Carbon dioxide, Carbon monoxide and Methane, from soil or biomass stock | air: indoor, and cruise height for the last two | none → 124-38-9, 630-08-0, 74-82-8 | ecoinvent's land-use-change releases under ecoinvent's uuids; the package writes the gas's number on its other rows of these names and leaves it off these five. With it, the phrase is read as land-use change and the rows reach EF's `(land use change)` flow of the gas, as ecoinvent's do; as shipped, each created a `..., From Soil Or Biomass Stock` flow no method characterises ([#435](https://github.com/brightway-labs/brightway-flows/issues/435)) |
| difenzoquat | nine compartments of air, soil and water | 49866-87-7 → 43222-48-6 | every EF 3.1 factor on these nine rows is EF's number for the methylsulphate salt in the same compartment (82.861 for freshwater ecotoxicity in unspecified air, where the cation's is 211.51), while ecoinvent's, EF's and the package's own `1,2-Dimethyl-3,5-diphenyl-1H-pyrazolium` rows carry the cation's. As shipped, the rows reached the cation and GreenDelta's two numbers collided in 18 places. The package's eleven other difenzoquat rows carry no factor, and stay on the cation their name and number name ([#439](https://github.com/brightway-labs/brightway-flows/issues/439)) |
| Arsenic ion | 16 compartments of air, soil and water | 17428-41-0 → none | arsenate's number on the generic ion, whose factors are the element's where EF states one (1,725.9 in agricultural soil, EF's `Arsenic`; `Arsenic(5+)` is 2,506.95). As shipped, the 16 rows reached `Arsenic(5+)` beside the package's `Arsenic V`, and the two numbers collided in 6 places; the package's other 26 `Arsenic ion` emissions already reach `Arsenic, ion`, as AGRIBALYSE's do ([#439](https://github.com/brightway-labs/brightway-flows/issues/439)) |

One synonym is restored rather than a number corrected: the agricultural-soil
`Epoxiconazole` row (135319-73-2, ecoinvent's uuid) is the one of the package's
six that ships without `BAS 480F`, the development code EF 3.1 registers the
fungicide under, and without it the row minted a second `Epoxiconazole` where
its five siblings reached EF's. ecoinvent's fixes make the same correction for
the two of its own rows that lack the synonym
([#826](https://github.com/brightway-labs/brightway-flows/issues/826)).

