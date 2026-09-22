# Changes to Stepwise 2006

*Part of [What was changed in each source](index.md). What is still open about Stepwise 2006 is on the issue tracker under the label [`stepwise`](https://github.com/brightway-labs/brightway-flows/issues?q=is%3Aissue+is%3Aopen+label%3Astepwise).*

Stepwise 2006 arrives as a SimaPro method file, `Stepwise2006_v1.09.csv`, so
its flows are the rows its characterisation factors name: 6,064 of them, of
which 6,055 are merged and nine are refused (listed at the end of this page).
It is merged last, after ecoinvent 3.12, ecoinvent 3.8 and BAFU 2026 v1, on
the build of 2026-08-29 from commit `54b0f9d`.

The file ships no identifier of any kind. Every row on this page is therefore
named the way the method file writes it — name, compartment and
sub-compartment, unit — and that is how to find it in the CSV. The uuids this
project gives Stepwise rows are derived from those same fields and are not
quoted here.

Corrections to the file's own rows are in `stepwise-2006-manual-fixes.json`.
Because Stepwise inherits ecoinvent 2's spellings and ecoinvent 2's data
habits, it also receives every correction in
`simapro-lineage-manual-fixes.json`, which is applied to each SimaPro-shaped
list. Thirteen rows are sent to a chosen target by
`stepwise-2006-match-overrides.json`, twelve of them because a kilogram or a
cubic metre of a fuel has to land on a flow EF 3.1 accounts in megajoules.

In one line: two registry numbers were corrected (one removed, one replaced),
no ionic charge was added, 51 rows were merged into 14 consensus flows, and no
name was split across two substances.

## One name, two substances

None. On the 2026-08-29 build no Stepwise name reaches two consensus
substances. That is what a method file should do: it carries one row per name
per compartment, with one registry number for the name wherever it appears,
so there is nothing on a row for the merge to read differently from one
compartment to the next.

## An ionic charge was added or corrected

None. Stepwise writes a charge wherever it means an ion, in the SimaPro
spelling: `Chromium III` and `Chromium VI`, six rows each, are published as
`Chromium(3+)` and `Chromium(6+)`, which is the same charge in the consensus
list's notation. `Ammonium, ion` (six rows, CAS 14798-03-9) is published as
`Ammonium`; the ion is what the name and the CAS number both say, and the
consensus name leaves the word off because ammonium is only ever an ion.

## Rows merged into one flow

Fifty-one Stepwise rows land on fourteen consensus flows, so a reader who
follows one of those flows back to the method file finds more than one row
there. Every case is one of four kinds.

### A plain row beside its qualified twin

Stepwise ships four carbon dioxide rows into unspecified air, all carrying
124-38-9: `Carbon dioxide, fossil`, `Carbon dioxide, biogenic`, `Carbon
dioxide, land transformation`, and a bare `Carbon dioxide`. The method itself
says what the bare row is: it is characterised at 1.0 under `Global warming,
fossil` and under nothing else, exactly like the fossil row. So the bare row is
sent to the fossil substance by `stepwise-2006-match-overrides.json`
([#175](https://github.com/brightway-labs/brightway-flows/issues/175)),
and the two rows are one flow.

| Stepwise rows | Compartment | Unit | Published as |
|---|---|---|---|
| `Carbon dioxide`; `Carbon dioxide, fossil` | `Air / (unspecified)` | kg | Carbon Dioxide (fossil), Environmental → Air → Unknown |

### Two spellings of one substance

| Stepwise rows | Compartment | Unit | Published as | Why |
|---|---|---|---|---|
| `Nitric oxide`; `Nitrogen monoxide` | `Air / (unspecified)` | kg | Nitric oxide | Both rows carry 10102-43-9, and both names mean NO. |
| `Particulates`; `Particulates, unspecified` | `Air / (unspecified)` | kg | Particles (unspecified size) | Neither row carries a CAS number; both name dust of no stated size. |
| `Particulates, < 10 um`; `Particulates, < 10 um (mobile)`; `Particulates, < 10 um (stationary)` | `Air / (unspecified)` | kg | Particles (PM10) | One size window, stated three ways; `(mobile)` and `(stationary)` say what emitted the particles, and Stepwise gives all three the same factor. Until the build of 2 September 2026 the first two minted substances of their own, because the table of size windows had not been told the list was registered ([#196](https://github.com/brightway-labs/brightway-flows/issues/196)). |
| `Zinc`; `Zinc, fume or dust` | `Air / (unspecified)` | kg | Zinc | Both rows carry 7440-66-6. Fume and dust say how the metal left the stack, and the consensus list does not distinguish zinc in air by its physical form. |

### A fuel by mass and by energy

EF 3.1 accounts fossil fuels and uranium as resources by their energy content,
in megajoules, because that is what the `Resource use, fossils` indicator
counts. Stepwise ships each of these fuels twice — once as an energy row, in
MJ, which lands directly, and once as a mass row, in kg, which
`stepwise-2006-match-overrides.json` sends onto the same flow with a
conversion factor. The factor used is always Stepwise's own: the method file
states a higher heating value for the substance and states a `Non-renewable
energy` factor for the row, and for every fuel but natural gas the two agree
([#171](https://github.com/brightway-labs/brightway-flows/issues/171)).

| Stepwise rows | Compartment | Units | Published as | Conversion applied to the mass row |
|---|---|---|---|---|
| `Coal, hard`; `Energy, from coal` | `Raw / (unspecified)` | kg; MJ | Hard Coal, Resource → Ground, MJ | 19.1 MJ/kg |
| `Coal, brown`; `Energy, from coal, brown` | `Raw / (unspecified)` | kg; MJ | Brown Coal, Resource → Ground, MJ | 9.9 MJ/kg |
| `Oil, crude`; `Energy, from oil` | `Raw / (unspecified)` | kg; MJ | Crude Oil, Resource → Ground, MJ | 45.8 MJ/kg |

These are gross (higher) heating values, which is why they sit above the
18.01, 9.41 and 43.4 MJ/kg that ecoinvent's and BAFU's kilograms of the same
fuels take onto the same flows. Stepwise's own lower heating values — 8.75
for brown coal, 43.2 for crude oil — sit among the other lists' numbers, so
the gap is the basis and not a disagreement about the fuel.

Natural gas is seven rows, and six of them state their own energy content in
their name:

| Stepwise row | Unit | Conversion | Where the CAS number comes from |
|---|---|---|---|
| `Gas, natural/m3` | m3 | 40.3 MJ/m3 | The method's `Non-renewable energy` factor for the row. The substance block gives 38.3 (higher) and 34.5 (lower) MJ/m3, so this is the one fuel where Stepwise's two statements about itself disagree; the factor is what the method multiplies an inventoried cubic metre by, and it is taken. It is 12% above the 36.0 MJ/m3 ecoinvent's and BAFU's standard cubic metres take onto the same flow. |
| `Gas, natural, 30.3 MJ per kg` | kg | 30.3 MJ/kg | The name, the lower heating value and the factor all agree. |
| `Gas, natural, 46.8 MJ per kg` | kg | 46.8 MJ/kg | As above. |
| `Gas, natural, feedstock, 46.8 MJ per kg` | kg | 46.8 MJ/kg | As above. `feedstock` says what the gas is used for; EF 3.1 has one natural gas resource whichever it is. |
| `Gas, natural, 35 MJ per m3` | m3 | 35.0 MJ/m3 | As above, by volume. |
| `Gas, natural, feedstock, 35 MJ per m3` | m3 | 35.0 MJ/m3 | As above. |
| `Gas, natural, 36.6 MJ per m3` | m3 | 36.6 MJ/m3 | As above. |

All seven are published as Natural Gas, Resource → Ground, in MJ.

Uranium is four rows in `Raw / (unspecified)`, all in kilograms and all
carrying 7440-61-1, and all four land on Uranium, Resource → Ground, in MJ.
One is the plain `Uranium` row, sent there by the overrides at 560,000 MJ/kg —
the gross fission energy content of natural uranium, the CAS number ecoinvent's
and BAFU's uranium rows already take onto this flow. The other three are the
rows whose names state their own value, and those are rebased by
`simapro-lineage-manual-fixes.json` before the merge reads them: the unit is
changed from kg to MJ at the factor the name states, and the name is then
shortened to `Uranium` so the row reaches the substance (the original
spelling is kept as a synonym).

| Stepwise row | Unit shipped | Rebased to | Factor | Why this factor |
|---|---|---|---|---|
| `Uranium, 451 GJ per kg` | kg | MJ | 451,000 MJ/kg | The name's own CAS number: the net once-through figure of the ETH-era data. Stepwise's `Non-renewable energy` factor for the row is exactly this. Using the 560,000 default instead would restate the vendor's quantity by 24%. |
| `Uranium, 560 GJ per kg` | kg | MJ | 560,000 MJ/kg | The name's number and the project's default for uranium mass rows are the same figure. |
| `Uranium, 2291 GJ per kg` | kg | MJ | 2,291,000 MJ/kg | The name's number: a fuel cycle with reprocessing. Stepwise's own factor prints 2.29e6, the same quantity to three figures. |

Every one of these is fission energy content, never a heating value.

### An ore grade in the name

Stepwise inherits ecoinvent 2's habit of writing the grade of the deposit into
a resource flow's name: `Copper, 0.52% in sulfide, Cu 0.27% and Mo 8.2E-3% in
crude ore`. The grade is a property of the mine and says nothing about what
the metal is; every such row carries the metal's own registry number, and so
lands on the metal.

| Metal | Rows in `Raw / (unspecified)`, kg | CAS on every row | Published as |
|---|---|---|---|
| Copper | 12 | 7440-50-8 | Copper, Resource → Ground |
| Molybdenum | 8 | 7439-98-7 | Molybdenum, Resource → Ground |
| Nickel | 6 | 7440-02-0 | Nickel, Resource → Ground |
| Zinc | 3 | 7440-66-6 | Zinc, Resource → Ground |
| Lead | 2 | 7439-92-1 | Lead, Resource → Ground |

??? note "All 31 rows"

    **Copper:** `Copper`; `Copper, 0.52% in sulfide, Cu 0.27% and Mo 8.2E-3% in crude ore`; `Copper, 0.59% in sulfide, Cu 0.22% and Mo 8.2E-3% in crude ore`; `Copper, 0.97% in sulfide, Cu 0.36% and Mo 4.1E-2% in crude ore`; `Copper, 0.99% in sulfide, Cu 0.36% and Mo 8.2E-3% in crude ore`; `Copper, 1.13% in sulfide, Cu 0.76% and Ni 0.76% in crude ore`; `Copper, 1.18% in sulfide, Cu 0.39% and Mo 8.2E-3% in crude ore`; `Copper, 1.42% in sulfide, Cu 0.81% and Mo 8.2E-3% in crude ore`; `Copper, 2.19% in sulfide, Cu 1.83% and Mo 8.2E-3% in crude ore`; `Copper, Cu 0.38%, Au 9.7E-4%, Ag 9.7E-4%, Zn 0.63%, Pb 0.014%, in ore`; `Copper, Cu 3.2E+0%, Pt 2.5E-4%, Pd 7.3E-4%, Rh 2.0E-5%, Ni 2.3E+0% in ore`; `Copper, Cu 5.2E-2%, Pt 4.8E-4%, Pd 2.0E-4%, Rh 2.4E-5%, Ni 3.7E-2% in ore`.

    **Molybdenum:** `Molybdenum`; `Molybdenum, 0.010% in sulfide, Mo 8.2E-3% and Cu 1.83% in crude ore`; `Molybdenum, 0.014% in sulfide, Mo 8.2E-3% and Cu 0.81% in crude ore`; `Molybdenum, 0.016% in sulfide, Mo 8.2E-3% and Cu 0.27% in crude ore`; `Molybdenum, 0.022% in sulfide, Mo 8.2E-3% and Cu 0.22% in crude ore`; `Molybdenum, 0.022% in sulfide, Mo 8.2E-3% and Cu 0.36% in crude ore`; `Molybdenum, 0.025% in sulfide, Mo 8.2E-3% and Cu 0.39% in crude ore`; `Molybdenum, 0.11% in sulfide, Mo 0.41% and Cu 0.36% in crude ore`.

    **Nickel:** `Nickel`; `Nickel, 1.13% in sulfide, Ni 0.76% and Cu 0.76% in crude ore`; `Nickel, 1.13% in sulfides, 0.76% in crude ore`; `Nickel, 1.98% in silicates, 1.04% in crude ore`; `Nickel, Ni 2.3E+0%, Pt 2.5E-4%, Pd 7.3E-4%, Rh 2.0E-5%, Cu 3.2E+0% in ore`; `Nickel, Ni 3.7E-2%, Pt 4.8E-4%, Pd 2.0E-4%, Rh 2.4E-5%, Cu 5.2E-2% in ore`.

    **Zinc:** `Zinc`; `Zinc 9%, Lead 5%, in sulfide`; `Zinc, Zn 0.63%, Au 9.7E-4%, Ag 9.7E-4%, Cu 0.38%, Pb 0.014%, in ore`.

    **Lead:** `Lead`; `Lead, Pb 0.014%, Au 9.7E-4%, Ag 9.7E-4%, Zn 0.63%, Cu 0.38%, in ore`.

### Nine rows that are refused

These rows are in the method file and are neither merged nor published. They
are recorded in `stepwise-2006-additional-flows.json` so that their absence
is a decision and not an oversight.

| Stepwise row | Compartment | Unit | Why it is refused |
|---|---|---|---|
| `Chlordane, gamma-` | `Air / (unspecified)`; `Soil / (unspecified)`; `Soil / agricultural`; `Water / (unspecified)`; `Water / groundwater`; `Water / groundwater, long-term` — six rows | kg | Gamma-chlordane is not something an inventory reports on its own. In the literature the name means trans-chlordane, which Stepwise ships as `Chlordane, trans-` (5103-74-2) in the same six compartments with the same factors. The number on these rows, 5566-34-7, is not a chlordane at all — it names a different octachloro compound nobody inventories. Mapping onto trans-chlordane would state one factor twice in one compartment; publishing under 5566-34-7 would add a substance nobody means. Nothing is lost: every factor is already published against `Chlordane, trans-` ([#167](https://github.com/brightway-labs/brightway-flows/issues/167)). |
| `Injuries, fatal`; `Injuries, non-fatal, at work`; `Injuries, non-fatal, road` | `Social / (unspecified)` | p (persons) | An injury is neither an emission nor a resource. These rows count people hurt, under a compartment that says nothing about the environment; publishing them beside carbon dioxide and cadmium would say the two are the same kind of thing ([#173](https://github.com/brightway-labs/brightway-flows/issues/173)). |

## Registry numbers corrected

Two, both before anything reads the row — and a third entry in the lineage
file that Stepwise happens not to trigger.

| Stepwise rows | Compartment | Unit | Number shipped | Corrected to | Why |
|---|---|---|---|---|---|
| `Tetramethyl ammonium hydroxide` — no Stepwise row | — | kg | *none* | 75-59-2 | The lineage file writes the substance's number onto any SimaPro-shaped row spelled this way, because BAFU and AGRIBALYSE both ship the two-word spelling bare of it and each minted a duplicate of `Tetramethylammonium hydroxide`. Stepwise ships no such row, so the entry is inert here; it is listed because the file applies to this list. |
| `Nitrogen, organic bound` — five rows | `Water / (unspecified)`; `Water / groundwater`; `Water / groundwater, long-term`; `Water / ocean`; `Water / river` | kg | 7727-37-9 | *removed* | 7727-37-9 is dinitrogen, N₂, the inert gas that is most of the air. Organically bound nitrogen is not a compound: it is the nitrogen locked inside the organic matter of a discharge, reported as a mass of nitrogen, and no registry number can name it. A shared number is how this list decides two things are one substance, so left alone these rows would fuse with the gas and be published as `Dinitrogen`. Removed rather than replaced because there is nothing to replace it with; without it the rows group by name onto the same substance the other lists' organic-bound rows reach. Stepwise's own method treats the two as different — it gives organic-bound nitrogen to the ocean an aquatic eutrophication factor of 2.6 against 3.1 for nitrogen. Stepwise's six `Nitrogen` rows keep the CAS number, which is theirs ([#57](https://github.com/brightway-labs/brightway-flows/issues/57)). In `stepwise-2006-manual-fixes.json`. |
| `Uranium-238` — two rows | `Air / (unspecified)`; `Water / (unspecified)` | kBq | 7440-61-1 | 24678-82-8 | 7440-61-1 is uranium the element, a mass; the row is the activity of one isotope, in becquerels, and the isotope's own CAS number is 24678-82-8, which ecoinvent ships on every `Uranium-238` row and the consensus substance carries. A stated number outranks a name it disagrees with, so with the element's number Stepwise's two rows reached `Uranium` and `Uranium Alpha` and matched neither ([#147](https://github.com/brightway-labs/brightway-flows/issues/147)). With the isotope's number both land on Uranium-238. The same habit is in BAFU, so the fix is in `simapro-lineage-manual-fixes.json` and applies to rows of any SimaPro-shaped list that carry the element's number. |

The lineage file also renames one Stepwise row without touching its CAS number:
`Carbon dioxide, in air` (`Raw / (unspecified)`, kg, 124-38-9) becomes
`Carbon dioxide, biogenic, in air`. Carbon dioxide taken from the air is
what growing biomass takes up, and this is where ecoinvent's row of exactly
this name goes through its own correspondence table and where BAFU's three
rows are sent. Without the word the CAS number reaches all nine carbon dioxides
at once; with it the row lands on Carbon Dioxide (biogenic), Resource → Air.
The vendor's spelling is kept as a synonym.
