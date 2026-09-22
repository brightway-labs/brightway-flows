# Consensus Elementary Flow Contexts

We built our consensus common set of flow contexts following the lead of [Edelen et al](https://cfpub.epa.gov/si/si_public_record_Report.cfm?LAB=NRMRL&dirEntryID=347251), who split a compartment into two halves:

* a **primary context**: a directionality, `Resource` or `Emission`, crossed
  with an environmental medium, `Air`, `Water`, `Ground` or `Biotic`;
* a **secondary context**: `Vertical Strata`, `Land Use`, `Indoor`,
  `Population Density` or `Release Height`, each with its own tree of values
  hanging under the medium it qualifies.

We are designing a system which allows for harmonisation across a large number of elementary flow lists while attempting to minimise complexity. This means that we only include context attributes when there are differing characterisation factors provided for the different attributes values. We also need to provide reasonable matches for major flow contexts from systems like SimaPro, EF, and ecoinvent.

We made the following changes:

- In our scheme, resources are limited to accounting concepts like "mass fraction of zinc" or "energy, geothermal, converted", and have the `Dimension` `Resource`. A specific type of ore like [Sphalerite](https://en.wikipedia.org/wiki/Sphalerite) is a tangible substance present in the environment, so is treated the same as other substances like carbon dioxide or nitrates - it has the `Dimension` `Environmental` and a `Media` description. We assume that these minerals will only be consumed, but that is not required.
- This different approach to resources means that directionality is not a part of context - direction instead comes from inventory model itself. Substances like carbon dioxide can be extracted from or emitted to the atmosphere, but this is the same substance and flow object definition.
- There is [no bright line between the economy and the environment](https://link.springer.com/article/10.1007/s11367-017-1398-4), and sometimes we want to characterize flows which don't have a direct environmental impact, including economic factors like value added or circular economy indicators like waste to recycling ratios. We therefore add an additional organising layer on top of Edelen's typology related to the `Dimension` of the elementary flow, and only require a `Media` where it is sensible.
- We add the `Product` media, for substances applied to or present in a product which can have direct effects on health, such as fire-retardant chemicals applied to mattresses.
- We expand the types of `Indoor` emission classes to include the differentiation given in [GLAM](https://www.lifecycleinitiative.org/activities/life-cycle-assessment-data-and-methods/global-guidance-for-life-cycle-impact-assessment-indicators-and-methods-glam/).
- Our labels for the secondary context attributes are more explicit, such as "Rural (<1000 people/square mile)", "Medium stack, <150 meters", and "Confined aquifer with fossil groundwater".

Here is our set of contexts.  A `Dimension` comes first, a `Media` under it
where one is sensible, and an attribute class — in **bold** — under the media
that needs one:

* `Environmental`
    * `Air`
        * **Indoor Air Class**
        * **Vertical Strata**
            * **Population Density**
    * `Biotic`
    * `Ground`
        * **Geography**
    * `Water`
        * **Water Body**
    * `Product`
    * `Other`
* `Resource`
    * `Air`
    * `Biotic`
    * `Ground`
    * `Water`
        * **Water Body**
* `Land Use`
    * `Occupation`
    * `Transformation`

`Economic`, `Social`, `Inventory Indicator` and `Impact Assessment Score` are
dimensions on their own: a flow filed under one takes no media and no attribute
class.

`Impact Assessment Score` is for a row whose amount is already a result. LCIA
methods ship a few: Stepwise 2006 carries `Methane, as CO2e (GWP aggr timing)`,
characterised at 1 where its own `Methane` is characterised at 29.8, so the
inventory amount is the global-warming result and not a mass of methane.
Filing such a row as an emission would let an inventory add it to the real
substance and count the same warming twice.

This typology will change as we apply this theory to real world data and users, and as LCIA methods continue to develop.

A `Resource` takes a `Media`, and one attribute class: a withdrawal of water has
to say which body it came from, so `Resource` `Water` carries a `Water Body`
like the environmental side does.  Nothing else on the `Resource` dimension
takes a subclass.

The bold entries are the classes, each with its own tree of possible values. Here are the possible values for these classes:

**Indoor Air Class**: Differentiation of indoor air emission classes. Based on GLAM indoor air emissions.

* Unknown
* Near-person
* Residential
* Industrial

**Vertical Strata**: Vertical strata for the `Environmental` domain and the `Air` media.

* Unknown _(unspecified outdoor air — no strata information available)_
* Ground level
* Low stack, <25 meters
* Medium stack, <150 meters
* High stack, >150 meters
* Aircraft cruise height
* Long-term — not a stratum. A temporal qualifier riding on this field, because
  strata is the mandatory mutually-exclusive discriminator air already has. It
  cannot be combined with a real stratum or a population density, so a source
  that knows both has to give one up.

**Population Density**: Only applies to the `Environmental` domain and the `Air` media. Not included for aircraft or long-term emissions.

* Unknown
* Urban (>1000 people/square mile)
* Rural (<1000 people/square mile)

**Geography**: Only applies to the `Environmental` domain and the `Ground` media. Follows Edelen et al. with the addition of `Silvicultural` and `Unknown` to better align with EF 3.1.

* Unknown
* Industrial — a works, a yard, a contaminated site. Both lists that ship an
  industrial soil compartment file it here. EF 3.1 has four flows here, and
  whether an emission published here carries a factor depends on which
  implementation of EF 3.1 is asked — see
  [Known limitations](../reference/limitations.md#a-forestry-or-industrial-soil-emission-is-characterised-by-one-implementation-of-ef-31-and-not-the-other).
* Residential
* Commercial
* Agricultural
* Silvicultural — land being worked for wood. This is where a source's
  `forestry` compartment goes: a pesticide sprayed on a plantation or the chain
  oil a harvester loses is an emission from the *practice*, and the practice is
  what the compartment names. EF 3.1 has no such compartment, so the JRC's own
  implementation characterises nothing here and the ecoinvent Centre's does —
  see
  [Known limitations](../reference/limitations.md#a-forestry-or-industrial-soil-emission-is-characterised-by-one-implementation-of-ef-31-and-not-the-other).
* Wetland
* Barren land
* Snow and Ice
* Grassland
* Shrubland
* Forest — tree cover, whether or not anybody works it. Pick this only when a
  source says where the land *is*, not what is being done to it; a compartment
  spelled `forestry` is `Silvicultural`.
* Non-agricultural — _deprecated on arrival._ Not a land cover class but EF 3.1's
  complement of `Emissions to agricultural soil`, present only so those two EF
  contexts stop collapsing onto one another. Do not map new sources onto it:
  prefer a real land cover class, or `Unknown`.

**Water Body**: Applies to the `Water` media on both the `Environmental` and the
`Resource` domain, and is required on each. It means the body an emission went
**to**, or the body a withdrawal was taken **from**.

* Unknown
* Surface water — the broader value: lakes and rivers are kinds of surface
  water, and this is the one to pick when the body is not narrowed to either.
* Lake
* River
* Ocean
* Unconfined aquifer
* [Confined aquifer with fossil groundwater](https://en.wikipedia.org/wiki/Aquifer)
* Waste-water treatment plant — _emissions only_
* Secondary water treatment — _emissions only_
* Long-term — _emissions only._ Not a water body: a temporal qualifier riding on
  this field, the water-side counterpart of the `Long-term` vertical strata. A
  withdrawal has no >100-year counterpart, so the three values above are
  prohibited on the `Resource` domain.

## Discussion Points

* We could add `Space` to the vertical strata.
* Three source lists share a compartment that means "in the countryside **or**
  from a tall stack", and no single value here can hold both. It is published as
  `Medium stack, <150 meters → Rural`, which is neither reading: it is the
  compartment EF 3.1's own characterisation factors treat it as. That is an
  inference from factors rather than anything a source states — see
  [Known limitations](../reference/limitations.md#one-air-compartment-names-two-situations-and-neither-is-what-gets-published).

## Allowed Context List

The set of allowed contexts is [given as a list of JSON objects](https://github.com/brightway-labs/brightway-flows/blob/main/src/brightway_flows/data/consensus-flow-contexts.json) - for example:

```json
{
  "dimension": "Environmental",
  "context_iri": "https://vocab.brightway.one/flow-contexts/envi-air-grle-ur10pesq",
  "media": "Air",
  "strata": "Ground level",
  "population_density": "Urban (>1000 people/square mile)"
}
```

There are currently **60 allowed contexts**, plus one deprecated. The list
below is the whole of it, generated from the data file rather than kept in
step by hand; `tests/test_documentation.py` fails if the two disagree.

### Contexts as a List of Strings

Because the set of context attributes is structured as a taxonomy, we can express each possible context as a list of strings, compatible with existing LCA data format such as ILCD. In this formulation, the specification of "Unknown" subclasses is optional, as "Unknown" is assumed if a value is missing.

We note that this way of expressing contexts can be less ambiguous now that indoor air contexts are prefixed with `Indoor` — for example, `['Environmental', 'Air', 'Indoor', 'Near-person']` vs `['Environmental', 'Air', 'Low stack, <25 meters']`.

Here are all contexts as a list of strings; a mapping from the [context IRIs to these values is also provided as JSON](https://github.com/brightway-labs/brightway-flows/blob/main/src/brightway_flows/data/consensus-flows-as-strings.json).

* ['Economic']
* ['Environmental', 'Air']
* ['Environmental', 'Air', 'Aircraft cruise height']
* ['Environmental', 'Air', 'Ground level']
* ['Environmental', 'Air', 'Ground level', 'Rural (<1000 people/square mile)']
* ['Environmental', 'Air', 'Ground level', 'Urban (>1000 people/square mile)']
* ['Environmental', 'Air', 'High stack, >150 meters']
* ['Environmental', 'Air', 'High stack, >150 meters', 'Rural (<1000 people/square mile)']
* ['Environmental', 'Air', 'High stack, >150 meters', 'Urban (>1000 people/square mile)']
* ['Environmental', 'Air', 'Indoor']
* ['Environmental', 'Air', 'Indoor', 'Industrial']
* ['Environmental', 'Air', 'Indoor', 'Near-person']
* ['Environmental', 'Air', 'Indoor', 'Residential']
* ['Environmental', 'Air', 'Long-term']
* ['Environmental', 'Air', 'Low stack, <25 meters']
* ['Environmental', 'Air', 'Low stack, <25 meters', 'Rural (<1000 people/square mile)']
* ['Environmental', 'Air', 'Low stack, <25 meters', 'Urban (>1000 people/square mile)']
* ['Environmental', 'Air', 'Medium stack, <150 meters']
* ['Environmental', 'Air', 'Medium stack, <150 meters', 'Rural (<1000 people/square mile)']
* ['Environmental', 'Air', 'Medium stack, <150 meters', 'Urban (>1000 people/square mile)']
* ['Environmental', 'Biotic']
* ['Environmental', 'Ground']
* ['Environmental', 'Ground', 'Agricultural']
* ['Environmental', 'Ground', 'Barren land']
* ['Environmental', 'Ground', 'Commercial']
* ['Environmental', 'Ground', 'Forest']
* ['Environmental', 'Ground', 'Grassland']
* ['Environmental', 'Ground', 'Industrial']
* ['Environmental', 'Ground', 'Non-agricultural'] — _deprecated_
* ['Environmental', 'Ground', 'Residential']
* ['Environmental', 'Ground', 'Shrubland']
* ['Environmental', 'Ground', 'Silvicultural']
* ['Environmental', 'Ground', 'Snow and Ice']
* ['Environmental', 'Ground', 'Wetland']
* ['Environmental', 'Other']
* ['Environmental', 'Product']
* ['Environmental', 'Water']
* ['Environmental', 'Water', 'Confined aquifer with fossil groundwater']
* ['Environmental', 'Water', 'Lake']
* ['Environmental', 'Water', 'Long-term']
* ['Environmental', 'Water', 'Ocean']
* ['Environmental', 'Water', 'River']
* ['Environmental', 'Water', 'Secondary water treatment']
* ['Environmental', 'Water', 'Surface water']
* ['Environmental', 'Water', 'Unconfined aquifer']
* ['Environmental', 'Water', 'Waste-water treatment plant']
* ['Impact Assessment Score']
* ['Inventory Indicator']
* ['Land Use', 'Occupation']
* ['Land Use', 'Transformation']
* ['Resource', 'Air']
* ['Resource', 'Biotic']
* ['Resource', 'Ground']
* ['Resource', 'Water']
* ['Resource', 'Water', 'Confined aquifer with fossil groundwater']
* ['Resource', 'Water', 'Lake']
* ['Resource', 'Water', 'Ocean']
* ['Resource', 'Water', 'River']
* ['Resource', 'Water', 'Surface water']
* ['Resource', 'Water', 'Unconfined aquifer']
* ['Social']

## Mapping to Other Flow List Contexts

Every mapping from another list's context strings onto these consensus
contexts lives in one file,
[`context-manual-mapping.json`](https://github.com/brightway-labs/brightway-flows/blob/main/src/brightway_flows/data/context-manual-mapping.json), whose
`default_context_mappings` rows are keyed by `source`.  It currently covers
`EF 3.1`, `ecoinvent-3.8` and `ecoinvent-3.12`.

One file, and both stages read it: the `default_context_mapping` transformer
during the transform, and the merge — filtered to the list being merged —
through `brightway_flows.context_mapping`.  So a rule added here places a
row in both stages or in neither.

The merge used to read a per-source *projection* of this file, written by
`brightway-flows contexts` into package data.  `build` never ran that
command, so editing the master moved the transform and left the merge on
whatever the projection said the last time somebody ran it by hand.  The
projections are gone.  To map a new list's compartments, add rows here under
its `source` string.

### When a compartment is not enough

Some lists put two consensus contexts in one compartment, and then say which is
which somewhere else.  The file has a rule for each way that happens, and the
more specific rule wins:

| Rows | Keyed on | Used when |
|---|---|---|
| `default_context_mappings` | the compartment | almost everything |
| `name_prefix_context_mappings` | the compartment **and** a flow-name prefix | the compartment holds two contexts and the name prefix tells them apart |
| `flow_specific_context_mappings` | one flow's `source_uuid` | nothing general says it; the row names the flow and carries its reasoning |

ecoinvent files land occupation and land transformation in one compartment,
`natural resource / land`, and distinguishes them in the name: `Occupation,
annual crop` against `Transformation, from annual crop`.  `Land use /
Occupation` and `Land use / Transformation` are siblings here, so the
compartment rule had to pick one and be wrong about the other — it said
occupation, and 122 transformation flows per version were filed as occupations
until a name rule read them.

A name rule is a claim to have read the whole compartment: if a flow lands in
one and its name matches no prefix, the build stops and names the flow rather
than falling back to the compartment's answer.  A name the list has started
using is a curation decision, not a default.

EF 3.1 gives all six of its water bodies one compartment and no prefix
separates them, which is what the per-flow rows are for.
