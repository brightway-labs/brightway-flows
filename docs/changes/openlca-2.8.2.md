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
| `Resource / unspecified` | 1,565 water intakes, 250 land rows, ores and fuels | Water by name, land use by name, the rest as ground resources |
| `Resource / land` | 667 land rows, 28 minerals (`Clay`, `Granite`, …), two water intakes | Land use by name, water by name, the minerals as ground resources |
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

## Not yet merged

openLCA LCIA methods 2.8.2 is registered and extracted, and merges last
(priority 500) when a build names it. It cannot be merged yet, because two
tables that every merged list needs do not cover it
([#385](https://github.com/brightway-labs/brightway-flows/issues/385)):

- **Land classes** (`land-flow-classes.json`). 724 of its land rows are read,
  and 199 are not. Most of the 199 write a country into the name —
  `Transformation, from forest, extensive, GA` — and the rest use words the
  other lists don't: `conservation tillage`, `monotone-intensive`,
  `agriculture + forest`.
- **Water materials** (`water-flow-materials.json`). This list has no table of
  water names yet.

No documented build includes it, so this page records no merge outcomes: no row
has been sent anywhere by hand, no registry number corrected, and no name split
across two substances.

## One name, two substances

None recorded yet.

## An ionic charge was added or corrected

None recorded yet. The package names metal ions `Cadmium II` and `Arsenic V`
and writes the element's registry number on many of them
([#380](https://github.com/brightway-labs/brightway-flows/issues/380)).

## Rows merged into one flow

None recorded yet. The package ships 504 pairs of flows with the same name,
compartment and unit — usually GreenDelta's own flow beside ecoinvent's copy of
it, and in 85 of them only one of the two has an EF 3.1 factor.

## Registry numbers corrected

| openLCA name | Compartments | Number removed | Why |
|---|---|---|---|
| Nitrogen, organic bound | water: all eleven the package uses | 7727-37-9 | that is N₂, the gas that is most of the air; organically bound nitrogen is a measurement over many compounds and no CAS number names it. The gas's two synonyms, `dinitrogen` and `molecular nitrogen`, come off the same rows. Left on, the rows would fuse with nitrogen gas ([#57](https://github.com/brightway-labs/brightway-flows/issues/57)) |

One row keeps the gas's number and should not: `Nitrogen, NO` in unspecified
water is nitrogen emitted in Norway (GreenDelta's description says
`NO = Norway`), the same nutrient load with the country written into its name.
It is left until the place is split off the name, as for the land rows above.
