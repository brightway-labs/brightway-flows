# File schemas

Field-by-field reference for the record shapes the pipeline reads and writes.
For advice on *which* output you want, see
[Which output do I need?](../using/outputs.md).

Files live in the data directory — `~/Library/Application Support/brightway-flows/`
on macOS, overridable with `BRIGHTWAY_FLOWS_DATA_DIR`.

!!! warning "Three of these are record shapes, not files"

    `elementary-flows.json`, `flow-objects.json` and `harmonised-flows.json`
    are **no longer written**. The records they described are: they are what
    `consensus-flows.sqlite3` stores in `flow_objects.flow_object_json` and
    `elementary_flows.flow_json`, and their JSON Schemas are still generated
    and still enforced. The `ElementaryFlow` record is no longer stored: it
    was a second copy of `flow_json`, identical on every shared key in all
    94,433 rows, and `pipeline.sqlite.elementary_flow_record` projects it.

    The sections below are kept under their old filenames because that is what
    the schema files are called and what an older data directory contains. Read
    them as descriptions of the record, and see
    [Which output do I need?](../using/outputs.md) for where it now lives.

!!! tip "Machine-readable schemas are the authority"

    JSON Schemas for the published artifacts are checked in under
    `src/brightway_flows/data/schemas/`:

    - `elementary-flows.schema.json`
    - `flow-objects.schema.json`
    - `harmonised-flows.schema.json`
    - `harmonised-flows-simple.schema.json`
    - `lcia-factors.schema.json`
    - `lcia-differences.schema.json`
    - `unit-process-scores.schema.json` — the one artifact this project
      *reads* rather than writes: a brightway export of a sample of unit
      processes, their inventories, the factors applied and the scores,
      written by `tools/export_unit_process_scores.py`
    - `release-snapshot.schema.json` — `releases/<version>.json.gz`, one
      release as `release-migrations` compares it, written by
      `release-snapshot`
    - `release-migration-unresolved.schema.json` — the `unresolved.json`
      beside a pair's migration files. The three migration files themselves
      are randonneur datapackages, validated by randonneur on writing and on
      reading; see [Which output do I need?](../using/outputs.md#releasesmigrationsfrom__to-moving-a-database-from-one-release-to-the-next)

    They are generated from the record classes by `domain/schema.py`, and
    `tests/test_schemas.py` fails if the checked-in copies drift from those
    classes or if a real artifact does not validate. **Prefer them over this
    page when the two disagree** — and please fix this page when they do.

    This page exists to explain what the fields *mean*, which a schema cannot.

### `schema_version`

Every wrapped file carries `schema_version`, currently `7` for the flow
artifacts. It is the signal a reader uses to tell "this artifact does not have
the field I want" from "this artifact is older than that field":
`domain.schema.check_schema_version` raises on a version it cannot read, rather
than letting a caller merge against fields that have moved.

**The two LCIA artifacts are versioned separately**, by `LCIA_SCHEMA_VERSION`,
currently `1`. `lcia-factors.json.gz` and `lcia-differences.json` describe
characterisation factors rather than flows, and a flow-list bump has nothing to
say about a factor; a reader of one passes `expected=LCIA_SCHEMA_VERSION` to
`check_schema_version`. That one number covers both the files and the `lcia_*`
tables, because both are renderings of the same records.

**The score artifact is versioned separately again**, by
`ARTIFACT_SCHEMA_VERSION` in `domain/lcia/unit_process_scores.py`, currently
`1`, for the same reason: it is written by brightway rather than by this
project, and neither of the other two numbers has anything to say about it.
Its loader, `load_score_artifact`, is the one production caller of
`check_schema_version` — it is the one artifact this project reads back.

Bump it only when a change would break a reader. Adding an optional field to a
record does not; adding a top-level key to a document does, because the
documents are `additionalProperties: False`.

---

## `elementary-flows.json`

Written by `build`.

```json
{
  "schema_version": 1,
  "stats": { … },
  "elementary_flows": [ <ElementaryFlow>, … ]
}
```

### ElementaryFlow

| Field | Type | Description |
|---|---|---|
| `elementary_flow_id` | string (UUID) | Identifier for this substance-in-context |
| `flow_object_id` | string (`fo-<16 hex>`) | The substance this flow is an occurrence of |
| `source` | string | Source label, e.g. `"EF 3.1"` |
| `context` | object | Structured consensus context |
| `context_iri` | string (IRI) | Canonical context identifier — **the authoritative form** |
| `unit` | string \| null | Canonical unit notation, e.g. `"kg"` |
| `unit_iri` | string (IRI) \| null | Canonical unit identifier |
| `lcia_methods` | list[object] | Characterisation factors carried from the source list. Each states the method, the category and the number; 42,871 of EF 3.1's 319,575 also state a `geography`, the place the number applies to |
| `general_comment` | string \| null | Free text from the source list |
| `cas_match_labels` | object | CAS number → SKOS match-quality IRI |
| `concept_associations` | list[ConceptAssociation] | Links to source-list flows. Absent when unset |
| `owl:deprecated` | boolean | Present only on deprecated flows |
| `dcterms:isReplacedBy` | string (IRI) | Present only on deprecated flows |
| `is_replaced_by_uuid` | string | Present only on deprecated flows |

Required on every record: `elementary_flow_id`, `flow_object_id`, `source`,
`context`, `context_iri`, `unit`, `unit_iri`, `lcia_methods`,
`general_comment`, `cas_match_labels`. The remaining four are **omitted** when
unset rather than serialised as `null`, so an active flow does not carry empty
deprecation keys.

Source-specific keys not listed here are round-tripped verbatim at the top
level, so an unrecognised input field is preserved rather than dropped.

`cas_match_labels` maps each CAS number to how confidently it matched —
`skos:exactMatch`, `skos:closeMatch`, or `skos:relatedMatch`.

**Invariant:** `(flow_object_id, context_iri)` is unique across all
non-deprecated elementary flows.

!!! warning "`source_refs` is not in this file"

    Elementary flows carry `source_refs` in memory, but the writer strips it —
    the same applies to `harmonised-flows.json`. Per-source detail is available
    from the `elementary_flow_sources` table in `consensus-flows.sqlite3` and,
    for merged flows, from the merge report.

    This is a known gap between the record classes and the published files, not
    a documentation error: the field is required by the class and absent from
    the artifact. The generated schemas reflect the artifact.

!!! info "`elementary_flow_sources` is the only home for a flow's references"

    Not just the published files: **no** stored payload carries `source_refs`
    either. `elementary_flows.flow_json` held a copy until #30, and it was the
    build-time answer — the merge appends a matched flow's new reference to
    `elementary_flow_sources` and to nothing else, so on the 2026-08-07 build
    7,794 of 94,433 stored copies were short: the payload named the base list's
    single source where the table named two to 38. None was ever wrong the other
    way: no payload held a reference the table lacked.

    Read references from the table. A payload is not a fallback for it.

Every record in this file now has the same shape, whichever path produced it.
Flows added by the merge used to be built as raw dicts and omitted fields that
transform-created flows carried; they are now built through the record classes,
so one schema covers both.

### SourceRef

Not present in the published layered file — see the warning above. This is the
shape it has in memory, in the `elementary_flow_sources` SQLite table, and in
the merge report.

```json
{
  "list_name": "EF",
  "list_version": "3.1",
  "source_flow_uuid": "0000b186-aea3-4c0a-b0c2-c284de7cdf92",
  "source_flow_name": "…",
  "source_metadata": {
    "input_file": "/…/ef-31-flows.json",
    "input_dataset": "EF 3.1",
    "original_context": ["Emissions", "Emissions to air", "Emissions to air, indoor"]
  }
}
```

`source_flow_name` and `original_context` are verbatim as the source list wrote
them, not normalised — after the list's own curated corrections, which are the
only rewrites that reach this field: a `name` fix in its `*-manual-fixes.json`
(`Silver-110` → `Silver-110m`, `Granite` → `Penoxsulam`), and for a
SimaPro-derived list the unit suffix its names carry (`Gas, natural/m3` →
`Gas, natural`). On the 2026-08-24 build that is 58 rows across the three
merged lists, each traceable to one such correction. This is the one place
the vendor's own string for a row is published, and it is what a consumer
holding the vendor's inventory has to search by. It has always held for EF
3.1's rows; the merged lists published the name *enrichment* gave the row
instead — `Zinc(2+)` for BAFU's `Zinc II`, `Chlorobenzene` for
`Benzene, chloro-` — for about 5,300 rows until
[#149](https://github.com/brightway-labs/brightway-flows/issues/149),
which keeps the vendor's name on the merge row beside the enriched one it
matches on and publishes the vendor's.

### ConceptAssociation

```json
{
  "@type": "xkos:ConceptAssociation",
  "xkos:sourceConcept": {
    "@id": "https://vocab.brightway.one/ef/3.1/flow/<uuid>",
    "http://www.w3.org/2004/02/skos/core#prefLabel": "<source flow name>",
    "context": "Emissions/Emissions to air/Emissions to air, indoor",
    "qudt:hasUnit": {"@id": "https://vocab.brightway.one/units/unit/KiloGM"},
    "http://www.w3.org/2004/02/skos/core#exactMatch": {"@id": "<target IRI>"}
  },
  "xkos:targetConcept": {"@id": "<target IRI>"},
  "provenance": { … },
  "qudt:conversionMultiplier": 9.41
}
```

**There is no `xkos:mapType`.** XKOS defines no property for the type or
strength of a mapping — the specification says so explicitly. The match kind is
carried on the source concept as the SKOS mapping property itself. Readers
should look for whichever of `skos:exactMatch`, `skos:closeMatch`,
`skos:broadMatch` or `skos:relatedMatch` is present.

`skos:broadMatch` is used for manual ecoinvent additions, where one consensus
flow groups several source flows. Everything else uses `skos:exactMatch`.

#### `qudt:conversionMultiplier`

Multiply an amount of the **source** flow by it to get the amount of the
**target** flow.

It is published **only where `units.json` could not already have supplied the
factor**. Litres to cubic metres, tonnes to kilograms, MJ to J: those are
properties of the units themselves, carried on the unit via
`conversion_multiplier` and `reference_unit_iri`, and restating them per
mapping would be a second copy of a fact that has a home. Two kinds of
conversion have no such home, and both are here.

**Crossing quantity kinds.** Mass to Energy, Volume to Mass. There is no
unit-table factor to defer to, because how many megajoules a kilogram is
depends on the substance. Six ecoinvent flows:

| ecoinvent flow | | consensus flow | 3.8 | 3.9.1 onwards |
|---|---|---|---:|---:|
| `Coal, brown, in ground` (kg) | → | Brown Coal (MJ) | 9.41 | 9.41 |
| `Coal, hard, unspecified, in ground` (kg) | → | Hard Coal (MJ) | 18.01 | 18.01 |
| `Oil, crude, in ground` (kg) | → | Crude Oil (MJ) | **42.3** | **43.4** |
| `Gas, natural, in ground` | → | Natural Gas (MJ) | **34.5** per m3 | **36.0** per Sm3 |
| `Uranium, in ground` (kg) | → | Uranium (MJ) | 560000.0 | 560000.0 |
| `Water, salt, ocean` (m3) | → | Sea Water (kg) | 1025.0 | 1025.0 |

`Gas, mine, off-gas, process, coal mining` is deliberately **not** here. The
published table sent it to `natural gas` at 36.0, and it is a different
substance — gas drawn off a coal seam while the coal is being mined, which EF
3.1 says itself on the flow beside it — so it now mints a flow of its own and
there is no pair to convert across.

Two of them have two numbers because ecoinvent revised them. A heating value is
something somebody measured, and ecoinvent remeasured crude oil and natural gas
at release 3.9 following Meili et al. (2021), rebuilding its oil and gas
datasets on the new figures. Converting a 3.8 inventory with the later number
would use a heating value that release never had. So the correspondence row
stays single — the flow it maps to is the same flow in every release — while the
factor states which releases it was checked against, and which take another
number. A release nobody has checked is refused rather than given the default,
so the next ecoinvent means reading its implementation report rather than
inheriting a value by silence.

Every ecoinvent number above is read from that release's own `LCIA
Implementation` workbook, under `energy resources: non-renewable`. The characterisation factor
there is 1 MJ per MJ for a flow already in megajoules, so on a kilogram flow it
is the energy content, which is why the workbook answers the question at all.

A factor can differ between *lists* for the same reason it can differ between
releases: it describes a pair, not a substance. BAFU's `Oil, crude` converts at
43.1 MJ/kg, the ratio implied by the one dataset in its own archive that states
both a mass of crude oil and the energy from it, where ecoinvent's converts at
43.4. BAFU's eight:

| BAFU 2026 v1 flow | | consensus flow | Multiplier |
|---|---|---|---:|
| `Coal, brown` (kg) | → | Brown Coal (MJ) | 9.41 |
| `Coal, hard` (kg) | → | Hard Coal (MJ) | 18.01 |
| `Oil, crude` (kg) | → | Crude Oil (MJ) | 43.1 |
| `Peat` (kg) | → | Peat (MJ) | 9.76 |
| `Uranium` (kg) | → | Uranium (MJ) | 560000.0 |
| `Gas, natural/m3` (m3) | → | Natural Gas (MJ) | 36.0 |
| `Gas, natural` (Sm3) | → | Natural Gas (MJ) | 36.0 |
| `Water, salt, ocean` (m3) | → | Sea Water (kg) | 1025.0 |

Stepwise 2006 reaches the same energy-content flows from its own masses and
volumes, and states its own numbers for them. Twelve rows, every one taken from
Stepwise's own export — the higher heating value in its substance block, which
is also the factor its `Non-renewable energy` category gives the flow, and for
six of the gas rows the energy content the row's own name states:

| Stepwise 2006 flow | | consensus flow | Multiplier |
|---|---|---|---:|
| `Coal, hard` (kg) | → | Hard Coal (MJ) | 19.1 |
| `Coal, brown` (kg) | → | Brown Coal (MJ) | 9.9 |
| `Oil, crude` (kg) | → | Crude Oil (MJ) | 45.8 |
| `Peat` (kg) | → | Peat (MJ) | 9.9 |
| `Uranium` (kg) | → | Uranium (MJ) | 560000.0 |
| `Gas, natural/m3` (m3) | → | Natural Gas (MJ) | 40.3 |
| `Gas, natural, 30.3 MJ per kg` (kg) | → | Natural Gas (MJ) | 30.3 |
| `Gas, natural, 46.8 MJ per kg` (kg) | → | Natural Gas (MJ) | 46.8 |
| `Gas, natural, feedstock, 46.8 MJ per kg` (kg) | → | Natural Gas (MJ) | 46.8 |
| `Gas, natural, 35 MJ per m3` (m3) | → | Natural Gas (MJ) | 35.0 |
| `Gas, natural, feedstock, 35 MJ per m3` (m3) | → | Natural Gas (MJ) | 35.0 |
| `Gas, natural, 36.6 MJ per m3` (m3) | → | Natural Gas (MJ) | 36.6 |

Hard coal is 19.1 MJ/kg here against ecoinvent's and BAFU's 18.01 on the same
flow, and brown coal 9.9 against 9.41. Stepwise's are the gross calorific values
its own export states — its lower heating value for brown coal is 8.75 — which
is what the difference is, and why the number belongs to the pair rather than to
the substance.

AGRIBALYSE 3.2 carries two mass-measured fuel rows whose names state their own
energy content — the same self-stating shape as Stepwise's gas rows, and the
old ecoinvent 2 habit of writing the heating value into the flow name. The
factor is read off the name (332 GJ is 332,000 MJ) and was checked against
release 3.2 only:

| AGRIBALYSE 3.2 flow | | consensus flow | Multiplier |
|---|---|---|---:|
| `Wood and wood waste, 9.5 MJ per kg` (kg) | → | Wood (MJ) | 9.5 |
| `Uranium oxide, 332 GJ per kg, in ore` (kg) | → | Uranium (MJ) | 332000.0 |

AGRIBALYSE also measures six of its water rows in the unit the consensus flow
does not use — five intakes in kilograms where the water flows are cubic
metres, and rainwater in cubic metres where the rainwater flow is kilograms.
Fresh water converts at its density (a tonne to the cubic metre, so 0.001 one
way and 1000 the other); the ocean cooling intake converts at sea water's
1,024.6 kg/m³, which is where 0.000976 comes from. AGRIBALYSE's eight rows
that cross a unit are these six and the two fuel rows above:

| AGRIBALYSE 3.2 flow | | consensus flow | Multiplier |
|---|---|---|---:|
| `Water, cooling, salt, ocean` (kg) | → | Cooling water (m3) | 0.000976 |
| `Water, cooling, unspecified natural origin/kg` (kg) | → | Cooling water (m3) | 0.001 |
| `Water, cooling, well` (kg) | → | Cooling water (m3) | 0.001 |
| `Water, process, drinking` (kg) | → | Water (m3) | 0.001 |
| `Water, unspecified natural origin/kg` (kg) | → | Water (m3) | 0.001 |
| `Water, rain` (m3) | → | Rainwater (kg) | 1000.0 |

**Changing what is measured.** ecoinvent gives the ore; EF 3.1 gives the metal.
Both sides are in kilograms, so the units raise no objection at all, and the
unit table's answer for the pair — 1.0 — is the wrong one. 0.599 is titanium's
share of titanium dioxide by mass (47.867 / 79.866):

| ecoinvent flow | | consensus flow | Multiplier |
|---|---|---|---:|
| `TiO2, 54% in ilmenite, 2.6% in crude ore` (kg) | → | Titanium (kg) | 0.599 |
| `TiO2, 54% in ilmenite, 18% in crude ore` (kg) | → | Titanium (kg) | 0.599 |
| `TiO2, 95% in rutile, 0.40% in crude ore` (kg) | → | Titanium (kg) | 0.599 |

BAFU ships two of the same three ores, under its own capitalisation, and they
take the same number:

| BAFU 2026 v1 flow | | consensus flow | Multiplier |
|---|---|---|---:|
| `TiO2, 54% In Ilmenite, 2.6% In Crude Ore` (kg) | → | Titanium (kg) | 0.599 |
| `TiO2, 95% In Rutile, 0.40% In Crude Ore` (kg) | → | Titanium (kg) | 0.599 |

ecoinvent replaced the ore flows with elemental `Titanium` at 3.10.1, so its
three appear in 3.8 and 3.9.1 only. `Barite, 15% in crude ore` is deliberately
**not** here: it maps onto EF 3.1's `baryte`, which is the same compound, so no
conversion applies. It would need one only against elemental `barium`, which is
not the target this project takes.

**Crossing a time dimension**, and only where a curator said so. Three obsolete
ecoinvent land-occupation flows are shipped in m² where the other fifty-seven
`Occupation,` flows of the same compartment are in m²·a:

| ecoinvent flow | Shipped | Published | Multiplier |
|---|---|---|---:|
| `Occupation, arable, conservation tillage (obsolete)` | m2 | m2·a | 1.0 |
| `Occupation, arable, conventional tillage (obsolete)` | m2 | m2·a | 1.0 |
| `Occupation, arable, reduced tillage (obsolete)` | m2 | m2·a | 1.0 |

A factor across a time dimension asserts a **duration**, which is a modelling
choice rather than a fact about the land. Every ecoinvent correspondence table
states 1.0 for these, commented "Assumed conversion based on land use through
an entire year" — and the merge **refuses** a time-crossing factor that arrives
from a table, so that assumption is never inherited silently.

**The factor is on the row rather than on a mapping**, and that is the whole of
what changed at
[#111](https://github.com/brightway-labs/brightway-flows/issues/111). These
three used to be folded onto EF 3.1's unqualified `arable`, carrying the 1.0 on
the mapping and losing the tillage regime. That mapping is declined, each flow
is published under its own name, and the 1.0 moved onto a manual fix in every
`ecoinvent-<version>-manual-fixes.json` that rebases the row's own unit from m2
to m2·a — with the reasoning attached: the occupation lasted one year. It is
still the only conversion this project states across a time dimension. An
inventory using these flows for a shorter or longer occupation is
mischaracterised by exactly the ratio, which is why ecoinvent made them
obsolete.

**One source list, one flow, two units.** A list can ship the same flow twice
in two spellings of one scale. BAFU does: `Noise, Road, Lorry, Average` in
kilometres and again in metres, and the same for the passenger car. Both rows
land on one consensus flow, because `(flow_object_id, context_iri)` is unique,
and the flow has to declare one unit.

It declares the unit this list **publishes** that quantity kind in, where
`published-units.json` states one — the kilobecquerel for an activity. Every
radionuclide flow EF 3.1 ships is in kilobecquerels, and BAFU ships many of its
becquerel rows a second time in kilobecquerels, the same substance in the same
compartment; before the convention was written down, whichever spelling minted
the flow first became the published unit, so a flow could stand in becquerels
beside kilobecquerel flows of the same substance — Iodine-131 discharged to a
river, against the same iodine everywhere else (#142). The convention applies
to a lone row as well as to a disagreeing pair: a single
becquerel row still mints a kilobecquerel flow, because the published unit is
a statement about the list rather than an arbitration between rows. It only
ever restates a unit along its own scale — a becquerel to a kilobecquerel,
never a kilogram to a cubic metre.

Where no published unit is stated, it declares the one `units.json` makes the
**reference unit** for that quantity kind — the metre for a length — so the
answer does not depend on which row the merge read first. It used to: the
lorry came out in metres and the passenger car in kilometres, from one list,
on one day.

Where none of the units offered is a reference unit either, the tables have no
opinion and a curator writes one into `created-flow-unit-decisions.json`,
naming the row whose unit wins. BAFU's `Heat, waste` is the case that exists:
megajoules against kilowatt-hours, where the coherent unit for an energy is
the joule and BAFU offers neither. Its entry chooses megajoules, because that
is what BAFU itself writes in the other thirteen compartments it ships the
flow in. Where neither a decision, a published unit nor a reference unit
settles it, the first row stands and the run says so — and the row is listed
under **Checks → Unit disagreements** as needing a decision.

Either way, a row whose own unit is not the one the flow states is flagged
`has_unit_mismatch` on its merge outcome, which means on a creation exactly what
it means on a match: this source row is measured in something other than the
flow it landed on. Which of the two situations produced it is the outcome's own
`outcome` column.

Each row keeps its own unit where its own unit belongs: on its source ref and
on its `qudt:hasUnit`. No multiplier is published for the difference, by the
rule above — kilometres to metres is exactly what the unit table already says.
A group whose units share no reference unit is left as it arrived and reported,
because choosing there would be picking rather than deciding.

**One source list, one resource, two quantity kinds.** The harder version of
the same case, where the two units are not one scale. BAFU ships standing wood
by volume and again by mass, and no reference unit joins a cubic metre to a
kilogram. There the list is rebased by hand, in that list's manual fixes, and
the fix states the factor:

| BAFU flow | | consensus flow | Multiplier |
|---|---|---|---:|
| `Wood, unspecified, standing/kg` (kg) | → | Wood, Unspecified, Standing (m3) | 0.00204 |

0.49 oven-dry tonnes per cubic metre of fresh volume, a 50:50 mix of *Picea
abies* and *Fagus sylvatica* from Table 4.14 of the 2006 IPCC Guidelines. The
mapping states `kg`, because that is the unit BAFU's amounts are in; the flow
is in m³, because that is what every other standing-wood flow in every list
uses. This is the only kind of multiplier that does not come from a
correspondence table — BAFU publishes none — and it is why one can be authored
on a fix at all. See
[Rebasing a row onto another unit](../operating/sources.md#rebasing-a-row-onto-another-unit).

Read the multiplier with the units on both ends: `qudt:hasUnit` on the source
concept, and the target flow's own `unit`. The number is bare, so a consumer
that assumes one pairing gets the others wrong — 36.0 is per standard cubic
metre, not per kilogram, and 1025.0 is a density rather than a calorific value.

**Absence does not mean 1.0.** It means no factor was stated. A pair whose
units disagree and which carries no multiplier is either a reviewed exception
in `unit-change-allowlist.json` or a defect; treating it as parity is the
fossil-depletion underestimate of
[#33](https://github.com/brightway-labs/brightway-flows/issues/33).
One such case exists today, documented rather than converted: ecoinvent's
`Manganese-55` (kBq) onto elemental manganese in kg — seven pairs across the
contexts and releases that ship it — where 55Mn is manganese's stable isotope
and so has no activity to convert by. No ecoinvent 3.8 dataset uses the flow, so
nothing an inventory carries is affected.

**Which absences the build looks for.** Not every unit disagreement needs a
curator: most are a becquerel against a kilobecquerel, one quantity at two
scales, which `units.json` converts by itself. The population that needs one is
a mapping whose two units have different `quantity_kind_iri` — a mass onto an
energy, a volume onto a standard volume, an activity onto a mass. Every one of
those is listed in `unit-change-allowlist.json` with a comment saying why the
crossing is right; one that is not is logged `unit_crossing_without_a_ruling`
while the build runs and counted in `merge.unit_crossings_unrecorded`, which
`expectations/0805-every-quantity-kind-crossing-is-recorded.json` holds at
nothing. It warns rather than refuses
([#171](https://github.com/brightway-labs/brightway-flows/issues/171)):
refusing would make a new source list unmergeable until every crossing it
happens to produce had been argued, and a crossing is usually the vendor's
accounting convention rather than a defect.

**Where the numbers come from.** The ecoinvent values are the **EF 3.1 LCIA
method as implemented by the ecoinvent Centre**; BAFU's and Stepwise's are each
that list's own, read out of its own archive. The ecoinvent ones reached this
project through the `randonneur_data`
correspondence tables while those were loaded; the tables are retired
([#141](https://github.com/brightway-labs/brightway-flows/issues/141)) and
each factor now lives on its own reviewed row in
`ecoinvent-match-overrides.json`, with the pair of units it converts between.
They are not in the JRC's own EF 3.1 distribution: every one of the target
flow datasets in `EF-v3.1.zip` carries a single flow-property `meanValue` of
`1.0`, and no characterisation factor in its LCIA methods has these values.
The ecoinvent implementation is where they exist.

What none of them states is a **basis** — a calorific value is net or gross,
and 26 MJ/kg dry-ash-free is a different claim from 26 MJ/kg as-received.
Uranium's is documented as a gross (HHV) fission energy content; the coal and
oil values say nothing either way. Giving the field a unit, an explicit basis
and provenance is tracked in
[#3](https://github.com/brightway-labs/brightway-flows/issues/3).

It never appears on a flow or a flow object. A factor is a statement about a
pair — 9.41 is not a fact about brown coal until it is 9.41 MJ per kg — so it
belongs to the mapping and to nothing else.

Source IRI prefixes:

| Source | Prefix |
|---|---|
| EF 3.1 | `https://vocab.brightway.one/ef/3.1/flow/` |
| SimaPro Professional 10.2 | the SimaPro 10.2 flow prefix |
| Consensus target | `https://vocab.brightway.dev/elementary-flows/` |

### stats

Counts from the run that produced the file, present on both layered files:

`flow_object_count`, `elementary_flow_count`, `override_hits`,
`cas_conflict_guard_hits`, `nuclide_object_hits`, `nuclide_object_count`,
`element_flow_object_count_added`, `element_flow_object_names_added`,
`element_flow_object_count_enriched`,
`element_flow_object_count_ignored_unlinked`,
`isotope_flow_object_count_added`, `isotope_kbq_candidate_flow_object_count`,
`isotope_kbq_matched_flow_object_count`,
`isotope_kbq_unmatched_flow_object_count`, `isotope_kbq_unmatched_reasons`,
`isotope_kbq_withheld_flow_object_count`, `isotope_kbq_withheld_reasons`,
`isotope_rows_unparsed_count`, `isotope_unlinked_element_count`,
`isotope_unlinked_elements`,
`short_lived_isotopes_not_in_consensus_count`,
`monoatomic_ion_flow_object_count_marked`,
`monoatomic_ion_charge_detected_count`, `monoatomic_ion_cas_updates`,
`monoatomic_ion_ec_updates`, `duplicate_elementary_group_count`,
`deprecated_elementary_flow_count`.

The isotope counts split three ways rather than into matched and unmatched. A
label that is not a nuclide name is the expected outcome for an aggregate; a
nuclide the tables have never heard of is a correction waiting to be written;
and a record that failed its own consistency checks is neither. One number
covered all three, which is how 37 wrong records and one unresolvable label sat
behind the same figure. `isotope_kbq_unmatched_reasons` and
`isotope_kbq_withheld_reasons` are objects keyed by reason, and
`isotope_unlinked_elements` is keyed by element name. See
[What kind of thing is this flow?](semantic-types.md#how-a-nuclide-is-identified).

---

## `flow-objects.json`

Written by `build`.

```json
{
  "schema_version": 1,
  "stats": { … },
  "flow_objects": [ <FlowObject>, … ]
}
```

### FlowObject

| Field | Type | Description |
|---|---|---|
| `flow_object_id` | string (`fo-<16 hex>`) | Stable identifier, a hash of the identity that produced it |
| `prefLabel` | list[LangString] | Preferred name(s), `{"@value": "…", "@language": "en"}` |
| `altLabel` | list[LangString] | Synonyms |
| `properties` | object keyed by IRI | Chemical properties; see below |
| `references` | list | External database references |
| `created_from` | object | How this object was assembled |
| `classifications` | object | Registry numbers (CAS, EC, KEGG, Gmelin) with resource URLs and per-value provenance |
| `origin_qualifier` | string \| null | See below. `null` for base substances |
| `parent_flow_object_id` | string \| null | The base substance, for qualified flows. `null` for base substances |
| `skos:definition` | list | Prose definitions. Omitted when unset |
| `@type` | list[string] | Semantic types, e.g. `chemrof:FullySpecifiedAtom`. Omitted when unset |

`origin_qualifier` is one of `biogenic`, `fossil`, `land_use_change`,
`biogenic_resource_correction`, `biogenic_100yr`, `green_water`,
`blue_water`, `grey_water`,
`alpha_emitters`, `delayed_emission_correction`,
`biogenic_delayed_emission_correction`, `fossil_delayed_emission_correction`.
See [Flow objects and elementary flows](../concepts/two-layers.md).

Property keys are ChemROF IRIs:

| IRI | Meaning |
|---|---|
| `https://w3id.org/chemrof/molecular_formula` | Molecular formula |
| `https://w3id.org/chemrof/molecular_mass` | Molecular mass |
| `https://w3id.org/chemrof/elemental_charge` | Charge; non-zero identifies an ion |
| `https://w3id.org/chemrof/atomic_number` | Present on elements |
| `https://w3id.org/chemrof/inchi2d_string` | InChI |
| `https://w3id.org/chemrof/inchi2d_key_string` | InChIKey |
| `https://w3id.org/chemrof/smiles_string` | SMILES |
| `https://w3id.org/chemrof/iupac_name` | IUPAC name |

Property values are wrapped as `{"@value": …}` with provenance alongside. A
value may be a list where several sources contributed — see
[Known limitations](limitations.md), which explains why that is a problem worth
knowing about.

---

## `harmonised-flows-simple.json.gz`

Written by `build`, updated by `build`. Gzip-compressed. **The
published export** — this is what downstream consumers should read.

```json
{
  "@context": { … },
  "schema_version": 5,
  "flows": [ <SimpleFlow>, … ],
  "redirects": [ <FlowRedirect>, … ],
  "concept_schemes": [ <ConceptScheme>, … ],
  "correspondences": [ <Correspondence>, … ]
}
```

Six top-level keys, all required. `concept_schemes` and `correspondences` hold
the mappings to other flow lists, which moved out of the flows in schema
version 4; see [JSON-LD](jsonld.md).

Deprecated flows are excluded from `flows`. Every flow has the same fields
regardless of source.

### FlowRedirect

One per deprecated flow: which surviving flow its identifier resolves to, and
whether the two were ever the same flow. Added in schema version 5 (#39).

| Field | Type | Description |
|---|---|---|
| `identifier` | string (UUID) | The deprecated identifier a consumer is holding |
| `replaced_by_identifier` | string (UUID) | The surviving flow, as a bare UUID. **Terminal** — if a replacement were itself deprecated later this is still the end of the chain, not the next hop. **Absent on a withdrawal**, which has no survivor; optional since schema version 7 |
| `@id` | string (IRI) | The deprecated flow as an IRI |
| `http://purl.org/dc/terms/isReplacedBy` | object | `{"@id": …}` — the same survivor as an IRI. Absent on a withdrawal, for the same reason |
| `http://www.w3.org/2002/07/owl#deprecated` | boolean | Always `true` |
| `https://vocab.brightway.one/terms/deprecationReason` | object | `{"@id": …}` — one of `context-collapse`, `identity-merge`, `unclassified`, `identifier-scheme-change`, `source-row-withdrawn` under `https://vocab.brightway.one/deprecation-reasons/` |

The key is always present, and empty rather than absent when nothing was
deprecated: a missing `redirects` would leave a consumer unable to tell "nothing
was deprecated" from "an export written before redirects existed", which is the
ambiguity the key exists to remove.

!!! warning "The reason is not decoration — read it before following a redirect"

    `identity-merge` means every source list both flows came from put them in
    the same context: the same flow reached the list twice, and following the
    redirect resolves an identifier rather than crossing a distinction. On the
    2026-08-12 build that is all 130 redirects.

    `context-collapse` means a list both came from put them in *different*
    contexts that map to one consensus context. The flows compared equal because
    the consensus context vocabulary cannot tell them apart, but their
    characterisation factors legitimately disagree — see
    [limitations](limitations.md) and #36. A consumer that follows one of these
    and overwrites is layering a second arbitrary choice on the first; the
    honest response is to detect it and refuse.

    `unclassified` means the two share no source list that records a context, so
    they could not be compared. Treat it as unsafe, not as either of the above.

    `identifier-scheme-change` is not a merge. The two sides are one flow: this
    list renamed a flow it minted, from the source row that reached the
    compartment first to the substance and the compartment, and the old name
    redirects to the new one. Always safe to follow.

    `source-row-withdrawn` has **no other side at all**, and its record carries
    no `dcterms:isReplacedBy`. The flow was minted from a source row this list
    has since decided not to map, so the substance did not move — it was never a
    substance of this list. Drop the exchange; do not fall back to matching by
    name. Which row was withdrawn, and why, is on that list's
    `xkos:Correspondence` under `brightway:excludedSourceConcept`.

    None of the first three is a statement about the factors themselves: a source
    list that published one place twice with different numbers yields an
    identity merge whose factors still disagree
    ([#1](https://github.com/brightway-labs/brightway-flows/issues/1)).

    The reason is decided from `elementary_flow_sources`, which is where a
    flow's references live (#30) — not from the flow payload, whose copy was
    short on 7,794 of 94,433 flows before it was removed.

### SimpleFlow

| Field | Type | Description |
|---|---|---|
| `identifier` | string (UUID) | Always present. The ILCD UUID for EF flows; the `elementary_flow_id` for flows added during a merge |
| `source` | string | e.g. `"EF 3.1"`, `"ecoinvent algorithm addition"` |
| `cas_numbers` | list[string] | |
| `ec_numbers` | list[string] | |
| `context_iri` | string (IRI) | |
| `unit` | string | Required — export fails if any flow lacks one |
| `unit_iri` | string (IRI) | |
| `prefLabel` | string | Plain string, language resolved (English preferred) |
| `altLabel` | list[string] | Plain strings, deduplicated case-insensitively |
| `properties` | object | Keyed by the **full ChemROF IRI** (`https://w3id.org/chemrof/molecular_formula`), read as plain JSON. Values unwrapped from `@value`, so a string or a number rather than an object. The `@context` declares a short name per term and maps this key to `@nest`, so a JSON-LD processor that compacts the document sees `molecular_formula` on the flow itself and no `properties` key at all |
| `references` | list[string] | Reference IRIs |
| `definition` | list[string] | Definition text |
| `https://vocab.brightway.one/terms/originQualifier` | object \| null | `{"@id": …}` naming why this substance is held apart from one it shares a CAS number with. Omitted for the unqualified substance, which is most of them |
| `https://vocab.brightway.one/terms/baseSubstance` | object \| null | `{"@id": …}` naming the substance it was held apart *from*, as a flow-object IRI. Omitted wherever `originQualifier` is, and where the qualified object has no CAS number to resolve a parent through |
| `http://purl.obolibrary.org/obo/RO_0000087` | list[object] \| null | What the substance is *used for*, as `RO:0000087 has role` onto ChEBI role classes. Each row is `{"@id": …, "rdfs:label": …}`; the definition and per-assertion provenance the flow-object layer carries are dropped here. A list, because a role is many-valued — sulfluramid is an insecticide *and* an acaricide. **Omitted**, not empty, where ChEBI has nothing to say: `[]` would read as "checked, and it bears none" |

No `concept_associations`: the links to source-list flows left the flow in
schema version 4 and are the top-level `concept_schemes` and `correspondences`,
one correspondence per source list.

Present in `harmonised-flows.json` but **not** here: `lcia_methods`, `uuid`,
`elementary_flow_id`, `name`, `context`, `general_comment`, `synonyms`,
`cas_match_labels`, `flow_object_id`, `_sources`, `input_datasets`.

Note the shape difference from the layered files: labels are plain strings
rather than language-tagged objects, and property values are unwrapped from
their `{"@value": …}` envelope, losing the provenance that goes with it.
Property keys are **not** shortened — they are the same ChemROF IRIs the layered
records use. This file is built for consumption, not for round-tripping.

---

## `harmonised-flows.json`

**No longer a file.** Every flow after all processing, before layering. It was
written as a flat list — several gigabytes, and a denormalised duplicate of
`elementary-flows.json` joined to `flow-objects.json` — until #5. The record
is still produced and still the one the published export is projected from: it
is the `flow_json` column of `elementary_flows` in `consensus-flows.sqlite3`,
read by `pipeline.sqlite.read_published_flow_payloads`.

That column no longer holds the whole record. The keys describing the
*substance* rather than the occurrence — `altLabel`, `properties`, `references`,
`prefLabel`, `@type`, the SKOS definition, and `RO:0000087` roles — are stored
once per flow object in
`flow_object_payloads`, because 94,433 flows share 7,730 objects and a copy each
came to 1.57 GiB. `read_published_flow_payloads` joins them back, and a key a
flow still carries wins over the object's, so the record it returns is what the
column used to hold. Reading `flow_json` directly, without that join, now gives
a partial record.

The section keeps the old filename because that is what the schema file is
called; see the warning at the top of this page.

```json
{ … }   -- one object per row, in `elementary_flows.flow_json`
```

Selected fields:

| Field | Type | Description |
|---|---|---|
| `uuid` | string | Source flow UUID |
| `identifier` | string | Canonical identifier |
| `name` | string \| null | Flow name |
| `source` | string | Dataset label |
| `cas_numbers`, `ec_numbers` | list[string] | Registry numbers |
| `context` | list \| object | Source strings until context resolution, structured after |
| `context_iri` | string (IRI) | Resolved consensus context |
| `unit`, `unit_iri` | string | |
| `synonyms` | list[string] | Legacy synonym field from the source |
| `lcia_methods` | list[object] | Characterisation factors; a `geography` key where the source states one |
| `input_datasets` | list[string] | Datasets this row came from |
| `prefLabel`, `altLabel` | list[LangString] | Labels after enrichment |
| `flow_object_id` | string | Set during layering |
| `properties` | object keyed by IRI | |
| `references` | list | |
| `concept_associations` | list[ConceptAssociation] | |
| `skos:definition` | list | Omitted when unset |
| `owl:deprecated`, `dcterms:isReplacedBy`, `is_replaced_by_uuid` | | Omitted when unset |
| `cas_match_labels` | object | CAS → SKOS match quality |
| `cas_number_sources` | object | CAS → structured provenance |
| `general_comment` | string | |
| `_sources` | object | Field name → the processing step that last wrote it. Transform state — [skip it](#the-underscore-keys-are-transform-state-readers-should-skip-them) |
| `_transformed` | boolean | Has the transformer chain already run over this flow? Transform state — [skip it](#the-underscore-keys-are-transform-state-readers-should-skip-them) |
| `_provided` | object | What the source list shipped, before any transformer. Transform state — [skip it](#the-underscore-keys-are-transform-state-readers-should-skip-them) |

Unrecognised source keys are preserved at the top level.

Required on every record: `_provided`, `_sources`, `_transformed`, `altLabel`,
`cas_numbers`, `concept_associations`, `context`, `context_iri`, `ec_numbers`,
`flow_object_id`, `identifier`, `input_datasets`, `lcia_methods`, `properties`,
`references`, `source`, `synonyms`, `unit_iri`, `uuid`.

### The underscore keys are transform state — readers should skip them

`_provided`, `_sources` and `_transformed` are the transform stage's working
state, and the underscore is the signal: they are in `flow_json` because that
column is where the transform keeps its records, not because anything reading a
flow wants them. The published export drops all three — `_strip_lcia_from_flows`
in `pipeline/exporting.py` projects an explicit field list, and none of the
three is on it — and the review webapp, which hands `flow_json` to its templates
wholesale, renders none of them either.

**If you are reading `flow_json` for the flow record, ignore every key that
starts with an underscore.** What does read them is the pipeline itself — the
transformer chain and the merge, which run over these records rather than
consume them — and that is exactly what makes them working state. A reader that
treats them as part of the record is reading the pipeline's notes-to-self.

They are not free. Measured on the 2026-08-07 build, across all 94,433 rows,
after #28 hoists the substance body into `flow_object_payloads`:

| Key | MiB | % of `flow_json` |
|---|---:|---:|
| `_provided` | 61.6 | 17.6 |
| `_sources` | 34.4 | 9.8 |
| `_transformed` | 1.7 | 0.5 |
| **Total** | **97.7** | **27.9** |

So a bit over a quarter of the 350.7 MiB the column holds is state no reader
wants. That is the trade this page is recording rather than fixing: the keys
stay where the pipeline writes them, and readers skip them (#29). Whether they
belong in a table of their own, or on disk at all, is still open there.

### `_transformed` and `_provided`

The chain is ordered for a single pass over raw input and is not idempotent:
`normalize_name_case` runs fifth and re-title-cases labels that
`consensus_match` sets at fourteenth.
`_transformed` records that the chain has finished with a flow, so a later stage
— the merge, which shows the transformers the consensus flows alongside each new
source list — can hand both to the same loop without either re-transforming the
consensus or having to say which side is which.

`_provided` holds `name`, `synonyms`, `context`, `cas_numbers`, `ec_numbers` and
`unit` as the source list gave them. The pipeline *replaces* as well as adds:
`bootstrap_labels` moves `name` into `prefLabel` and then purges `name` and
`synonyms`, `default_context_mapping` rewrites `context` into a consensus
context dict, and the CAS transformers substitute a different registry number
for the one the list gave. Without this there is no way back to the input, and
the merge — which matches on the source list's own names and keys its context
lookup on the source list's own strings — has nothing to read.

It is not a copy of the input row: it holds what would otherwise be destroyed.

### `_sources`

`_sources` maps a field name to the transformer that last wrote it. Unlike the
other two it has no reader: `apply_transformers` writes it
(`pipeline/engine.py`), and nothing in `src/` reads it back — not the merge, not
the export, not the webapp. The only code that looks at it is the test asserting
it gets written.

It is also already stored elsewhere, twice over. The same loop that sets
`flow.pipeline_sources[field]` appends a `ChangeEvent` for that identical edit,
which is what `changelog` and `changelog_flows` are written from: `changelog`
holds the `transformer` and `field` of every edit, `changelog_flows` holds which
flows it landed on. `_sources` is that join with everything but the last write
per field thrown away — 34.4 MiB restating, less completely, what 273,384
changelog rows already say.

That makes it the weakest of the three: the argument for keeping `_provided` is
that the input is otherwise unrecoverable, and for `_transformed` that the chain
reads it within the run, but neither applies here. It stays because #29 chose
to document this state rather than move it, and dropping a persisted field is a
schema change; it is the part of that issue most likely to be revisited.

**`source_refs` is stripped from this file on write**, exactly as it is from
`elementary-flows.json`. For source traceability use the
`elementary_flow_sources` table in `consensus-flows.sqlite3`, or the merge
report for merged flows.

As with the layered file, every record now has the same shape regardless of
whether the transform or the merge produced it.

---

## Source list flows — input format

The shape `ef-31-flows.json` and every `SourceList.flows_path` are read in.
There is no separate "additional input" any more: a list is a `--source`, and
the same normaliser reads both sides. See
[Choosing sources](../operating/sources.md).

Either shape is accepted:

```json
[ <InputFlow>, … ]
```

```json
{"flows": [ <InputFlow>, … ]}
```

(`flow_data` is also accepted as the wrapper key.)

### InputFlow

| Field | Required | Description |
|---|---|---|
| `uuid` | **yes** | Rows without one are dropped |
| `name` | yes | Flow name |
| `source` | yes | Dataset label; the list name and version are derived from it |
| `context` | yes | List of strings or a structured context object |
| `unit` | yes | Must resolve against the unit vocabulary |
| `cas_numbers`, `ec_numbers`, `synonyms`, `prefLabel`, `altLabel`, `properties` | no | Used if present |

Non-object rows are ignored. A base file yielding no valid rows fails the run.

---

## `consensus-flows.sqlite3`

A denormalised cache rebuilt on every transform, backing the review
applications. Not a durable artifact — do not edit it.

| Table | Contents |
|---|---|
| `flow_objects` | One row per substance, with JSON columns for labels, classifications, properties and references, plus `origin_qualifier`, `parent_flow_object_id`, `flow_type` |
| `elementary_flows` | One row per occurrence, with context split into `context_dimension`, `context_media`, `context_strata`, `context_indoor`, `context_population_density`, `context_geography`, `context_water_body`, `context_land_use`, plus `is_deprecated`, `replaced_by_uuid`, `lcia_factor_count`, `consensus_change_count`. Its `flow_json` also carries the transform's own working state under underscore-prefixed keys, which a reader should [skip](#the-underscore-keys-are-transform-state-readers-should-skip-them) |
| `flow_object_payloads` | The substance-level keys of `flow_json` — labels, properties, references — stored once per flow object rather than once per elementary flow. A key is here only where every flow of that object agreed on it; one that disagreed keeps its own copy on the flow, and wins when the two are merged. `properties` cannot disagree — a flow's chemistry is derived from its substance (#53) — so that key is here for every object |
| `elementary_flow_sources` | Flattened `source_refs`, and the only home for them: `flow_json` does not carry the field, because the merge appends here and to no payload (#30) |
| `changelog` | The change log, every transformer, **one row per edit**: `change_index`, `transformer`, `flow_object_id`, `field`, old and new values, `comment`. Replaces the `consensus_changes` table, which held only the `consensus_match` slice |
| `changelog_flows` | Which elementary flows each edit landed on: `change_index`, `elementary_flow_uuid`, `flow_name`, `entity_version`. An edit to a substance lands on every flow sharing it, so this is where the flow-level view comes from. `entity_version` is the edit's position in *that flow's* history, which is not the same order as `change_index` |
| `provenance_activities` | A **view**, not a table: one PROV-O activity per (edit, flow), composed from `changelog` and `changelog_flows`. Every column was already in one of those two |
| `filter_option_counts` | Precomputed facet counts for the `/flows` filters |
| `flow_objects_fts`, `elementary_flows_fts` | FTS5 full-text indexes |

Query examples are in [Recipes](../using/recipes.md).
