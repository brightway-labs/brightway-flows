# What we have found

Harmonising several flow lists means reading them against each other, and against
the chemical registries, one substance at a time. That work turns up errors. A
flow is named after a chemical it is not; two flows that are one substance are
published as two; a registry number belongs to a relative of the substance
carrying it; a compartment does not mean what its name says. Some of these have
been in published, widely used lists for over a decade, and they are invisible as
long as each list is only ever read on its own terms.

These pages record what has been found **in the source data** — in EF 3.1, in
ecoinvent, in BAFU, in the SimaPro-era method files this project answers
lookups about, and in the correspondence tables that connect them. Mistakes
this project made in its own processing are not findings and are not here; where
the published output is still known to be wrong for any reason, that is recorded
in [Known limitations](../reference/limitations.md).

Findings are grouped by kind, because the kind is the useful part: a class of
error tells you what to go and check in a list this project has never read. **Each
kind is a page below**, and each page opens with a worked example before it states
the class — the data as shipped, what is wrong with it, the evidence for the
judgement, the decision taken, and what the error cost, counted per source list.

!!! note "How the counts are read"

    A **flow** is one row of a source list: one substance in one compartment. So
    a substance a list ships in seven compartments is seven flows, and an error
    that reaches only its emissions to air is counted in those flows and not the
    others.

    Counts are measured from a named build, not estimated, and they are counts of
    *rows in the source lists*, not of consensus substances. Where an error in one
    list damages a second list that is itself correct, both sides are counted and
    the table says which is which.

## The classes, and where they were found

| class of error | EF 3.1 | ecoinvent | BAFU 2026 v1 | GLAD's mapping |
|---|---|---|---|---|
| [Name and registry number name different chemicals](names-and-numbers.md) | 5 flows renumbered, 13 misnumbered | 21 lindane rows | 5 flows: the name states the ion, the number is the metal | rows 1756–1760, correct when written |
| [A named substance mapped onto a catch-all](catch-alls.md) | no flow for 34 pesticides, nor for 3 other named chemicals | — | — | **42 rows, 38 substances**, all marked proxy |
| [A class published as one of its members](class-as-member.md) | no flow for any of the three classes | 2 class flows numbered as a member in 3.8; 3 flows published as something else, in 3.8 and in 3.12 | 1 flow, damaged by the other side | rows 312, 1672, 4458 |
| [The identifier stayed and the substance changed](identifier-reuse.md) | 5 flows renumbered 3.0 → 3.1 | 13 vanadium + 1 flupyrsulfuron uuids | — | 15 rows made wrong by those edits |
| [A relative's common name](relatives.md) | 53 flows, 5 substances | — | — | 3 rows forced by EF's coverage |
| [Two rows, one name, one compartment](duplicate-rows.md) | 171 pairs: 67 duplicates, 104 collisions | 0 | 0 | — |
| [The name is a part number](part-numbers.md) | 118 substances; 714 flows still code-named, 50 with no identifier | 0 | 0 | — |
| [A nuclide named or numbered as something else](nuclides.md) | 60 flows | 27 (3.12) / 30 (3.8) | 30 flows | — |
| [The compartment names two situations](compartments.md) | 7,308 flows | 1,237 (3.12) / 390 (3.8); 182 land flows in one compartment | 256 flows | — |
| [Units and conditions of measurement](units.md) | 1 flow | 4 flows; 2 ore-against-element pairs | 159 unit pairs, 16 water rows | conversion stated on one ore pair, omitted on another |
| [A registry number that is not this substance's](registry-numbers.md) | 26 flows | 26 flows | 5 flows | — |
| [A factor that is not this substance's](factors.md) | 228 factors vs the model; 5 renumbered flows | 1 crustal factor on a salt taken from the sea | — | — |
| [Flows that are not substances](not-substances.md) | 180 aggregate, 12 waste heat | 40–45 aggregate, 13 waste heat, 182 land | 41 aggregate, 14 waste heat, 152 land, 6 noise | — |

A dash means the error does not occur there, which is usually structural rather
than lucky: BAFU has no correspondence table, so no table can misroute its rows.

**Stepwise 2006 has no column**, and two findings in these pages are its. It is a
merged source list now
([#164](https://github.com/brightway-labs/brightway-flows/issues/164),
[#169](https://github.com/brightway-labs/brightway-flows/issues/169)) and
not only a list somebody sends to [the lookup](../using/matching-your-own-list.md);
what it has not had is a pass counting every class above over its rows, which is
what a column would be. It is an ecoinvent-2-era SimaPro method file, so what
ships in it is a *lineage's* habit rather than one vendor's, and the counts it
does have are stated in the sections themselves.

!!! warning "Which mapping table is being talked about"

    Findings about mapping belong to the **published** correspondence file — GLAD's
    [ecoinvent 3.7 → ILCD EF 3.0 workbook](https://github.com/One-Click-LCA/GLAD-ElementaryFlowResources/blob/master/Mapping/Output/Mapped_files/ecoinventEFv3.7-ILCD-EFv3.0.xlsx),
    5,394 rows, cited here by its own row numbers.

    That is *not* the table a build reads. This project reads GLAD's mapping
    carried forward to ecoinvent 3.11 and EF 3.1 and extended with further matches
    of its own; where a row in that extension is wrong, the mistake is this
    project's and is not recorded in these pages. Every mapping row cited in them
    has been checked back against GLAD's file, and several claims were withdrawn
    when they turned out to belong to the extension rather than to GLAD.

    Two things follow that are worth stating plainly. GLAD marks its
    approximations: 35 of the 35 pesticide rows say `PROXY` in their own
    `MapType` column. And a mapping can be **correct when written and wrong when
    read**, because both source lists have changed what a flow identifier means —
    which is [a finding in its own
    right](identifier-reuse.md).

---

*These pages are added to as findings are written up; the classes above are the
ones recorded so far, not the whole of what the review queues hold.*
