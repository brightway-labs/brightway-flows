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

None recorded yet.

## An ionic charge was added or corrected

None recorded yet. The package names metal ions `Cadmium II` and `Arsenic V`
and writes the element's registry number on many of them
([#380](https://github.com/brightway-labs/brightway-flows/issues/380)).

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

One synonym is restored rather than a number corrected: the agricultural-soil
`Epoxiconazole` row (135319-73-2, ecoinvent's uuid) is the one of the package's
six that ships without `BAS 480F`, the development code EF 3.1 registers the
fungicide under, and without it the row minted a second `Epoxiconazole` where
its five siblings reached EF's. ecoinvent's fixes make the same correction for
the two of its own rows that lack the synonym
([#826](https://github.com/brightway-labs/brightway-flows/issues/826)).

