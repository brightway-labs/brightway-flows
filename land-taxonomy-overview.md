# Land in the Brightway flows list

*What a land flow now says, how the classes are organised, and where they are anchored. Counts of the taxonomy itself come from the curated files and are exact; counts of what a build produces name the run they came from.*

---

## 1. Why this was needed

Every LCI database ships a long list of land flows: *arable, non-irrigated, intensive*, *Occupation, annual crop*, *Transformation, from forest, primary*, *Occupation, heterogeneous, agricultural*. A land flow is not a substance. It is a piece of ground, held in a use, for a time — and the list had nowhere to record most of that.

A land flow says five things:

| What it says | Example | Where it used to live |
|---|---|---|
| How much land, for how long | 1 m²·a | the unit — fine |
| Which side of the boundary | occupation, or transformation | the context — fine |
| **Which way the transformation runs** | *from* forest, or *to* forest | **only inside the flow's name** |
| **What the land is** | forest, cropland, seabed, urban | **nowhere** |
| **How the land is used** | irrigated, intensive, organic, clear-cut | **nowhere** |

Three of the five had no field, so all three lived in a comma-separated flow name. Two problems followed.

**One piece of land was three flow objects.** EF 3.1 writes *arable, non-irrigated, intensive*; ecoinvent writes *annual crop, non-irrigated, intensive*; the Swiss BAFU list writes ecoinvent's spelling with its own prefix. They are the same ground under three names, and because the list compares fields rather than names, it had no field to compare — so it published three substances. Not one of BAFU's 123 land rows matched anything at all.

**A balanced pair of factors was held apart by two words.** EF 3.1 characterises *from forest, primary* at −396.7 and *to forest, primary* at +396.7. Same context, same unit, same land. The only thing keeping them from looking identical to the list was the words *from* and *to* inside a label — and the deduplication that decides whether two flows are one signs on every semantic field and not on the label. That is the shape of a defect that has already happened once, to water, where it inflated a water use result by about a factor of 434.

The fix is to give each of the three its own field, so that two names describing one piece of land simply *are* one thing, and two directions simply are not.

---

## 2. A land class is a value with fields, not a string

The water taxonomy needed one new axis — what kind of water — so a flat list of concepts was enough. Land needs **seventeen**, because `arable, non-irrigated, intensive` is not an atom: it is cropland, held without irrigation, farmed intensively. Spelling out every combination would restate every citation on each one; a value with fields states each part once and lets identity fall out of the parts.

Two axes are required:

- the **direction** — occupation, transformation *from*, or transformation *to*;
- the **cover** — what the land is, before anything is said about its use. There are 30: cropland, permanent cropland, pasture, forest, tropical rainforest, shrubland, grassland, wetland, barren land, snow and ice, lake, river, seabed, urban, industrial area, traffic area, dump site, and so on.

A cover is drawn as finely as the source lists draw it, and no more finely. Three of them are worth knowing about together, because they look like one thing and are not: **grassland** is grassland; **pasture** is land that is mown or grazed, which is a single class in ENVO — *area of pastureland or hayfields* — and is what EF means by its `pasture/meadow`; and **grassland, pasture or meadow** is the union of the two, which EF ships as a class of its own in all three directions and which no published vocabulary carries as a single term. Grassland is not meadow, and reading the union as plain grassland would say that it is.

Fifteen are optional qualifiers, and each is a different question about the ground:

| Axis | Asks | Values include |
|---|---|---|
| irrigation | is it watered | irrigated, non-irrigated |
| origin | is it there by nature or by construction | natural, artificial, man-made |
| use status | is it being used | used, not used, fallow, grazed |
| intensity | how hard is it worked | intensive, diverse-intensive, extensive, organic |
| vegetation form | how is the stand grown | sclerophyllous, flooded, under glass |
| stage | how far through succession | primary, secondary |
| substrate | what does the site sit on | benthic |
| position | where is the wetland | coastal, inland |
| built form | what is on the ground | continuously built, green space, mosaic |
| infrastructure | which network | rail, road, embankment |
| landfill | which kind of tip | inert material, residual material, sanitary, slag |
| activity | what is being done to the sea floor | mining, oil drilling, dredging |
| crop type | which permanent crop | fruit |
| silviculture | on what rotation | short, normal, clear-cutting |
| tillage | how is the soil worked | conservation, conventional, reduced |

**Which qualifiers a cover may take is written down.** `silviculture` is a question about a forest and `landfill` is a question about a dump site, and neither is ever asked of the other. That is what keeps the space finite and the model honest, and it is checked: a combination no cover admits raises rather than being published.

Some combinations are ruled out for reasons that are about the world rather than about the data. A tillage regime is stated *instead of* an intensity, never as well. A paddy field and a greenhouse have already answered the irrigation question. A primary forest is not on a short rotation; it is on no rotation.

**`None` means the source did not say, and is not a value called *unspecified*.** ecoinvent's *arable land, unspecified use* and EF's *arable* both leave the use status unset, and are therefore the same class. A stated *unspecified* is the absence of a statement, not a statement.

### Two spellings, one class, no crosswalk row

That is the whole of the design:

```
EF 3.1     arable, non-irrigated, intensive          ┐
ecoinvent  annual crop, non-irrigated, intensive     ├──▶ (Occupation, Cropland, non-irrigated, intensive)
BAFU       annual crop, non-irrigated, intensive     ┘
```

The three decompose to one value, which produces one identifier, which mints one flow object. Nothing has to say that they are the same, because they are not two things that were matched — they are one thing spelled three ways.

And in the other direction:

```
from forest, primary   ──▶ (Transformation from, Forest, primary)   −396.7
to forest, primary     ──▶ (Transformation to,   Forest, primary)   +396.7
```

Different values, so different objects, so the pair cannot collapse. Direction is a field precisely so that correctness stops resting on two labels being spelled differently.

---

## 3. What appears in the list

The axes *permit* many thousands of combinations. The list publishes the ones a source flow actually lands on, which is **345 land classes**, reached by **1,517 source flows**:

| Source list | Land flows assigned |
|---|---|
| EF 3.1 | 226 |
| ecoinvent 3.8, 3.9.1, 3.10.1, 3.11, 3.12 | 182 each |
| BAFU 2026 v1 | 152 |
| Stepwise 2006 | 28 of 41 |

By direction: 114 occupations, 110 transformations *from*, 115 transformations *to*. By how much they state: 85 classes name only a direction and a cover, 177 add one qualifier, 77 add two.

Stepwise 2006 is the only list with a number smaller than what it ships, and the thirteen missing rows are all one question. Each names the state the land was in **before**: `Occupation, sealed, on grassland` is a paved square metre that used to be grassland, `Occupation, forest, on arable land` a forest planted where a field was, and eight rows of the form `Occupation, accelerated denaturalisation, primary forest to intensive forest` name a state the land came from and one it is moving towards. Every axis below describes the land as it is, so there is nothing here to write those with, and Stepwise's are the numbers that turn on it — the same paving costs 0.7 on grassland and 0.2 on arable land. The thirteen are published under Stepwise's own names and recorded as unreadable in `tests/data/observed-land-classes.json`, rather than folded onto `sealed soil` as though the four were one class. Whether the axes should gain a previous state is [#176](https://github.com/brightway-labs/brightway-flows/issues/176).

The four EF flows measuring a **volume** — a repository, a reservoir, an underground deposit, filed under land occupation — are deliberately left out. No surface classification has a word for the inside of a mountain, and folding them in would make the taxonomy's root claim false. They are handled separately.

**The assignment is curated, one row per source flow.** `data/land-flow-classes.json` holds all 1,517, with the vendor's uuid, name, context and unit taken mechanically from the shipped files and the class as the curated part. A parser drafts it; it does not decide it. That distinction is the point: a parser gets a curator to 152 of 153 strings, and it does not get to decide, unsupervised, that *heterogeneous, agricultural* is agricultural mosaic. It is the same discipline the water taxonomy follows, where no algorithm reads *Water, salt, sole* and knows it is brine.

### The hierarchy is generated, not curated

Dropping a class's most specific stated qualifier gives its parent:

```
Cropland, non-irrigated, intensive
  └── Cropland, non-irrigated
        └── Cropland
```

Every edge in the published scheme comes from that rule, so the whole hierarchy is this project's by construction and **no edge can be published as an authority's that the authority does not assert**. The water taxonomy had to record, on each of its edges, whether ENVO stated it or we did; here there is nothing to tell apart.

A class hangs off the nearest ancestor the build actually carries. Nothing is minted to fill a gap: a class no source flow reaches is not published, so if the list has *Cropland, non-irrigated, intensive* and *Cropland* but nothing in between, the first hangs directly off the second.

---

## 4. Where the classes are anchored

Nothing here is invented. Each axis **value** cites a published class once — not each of the 336 classes that mention it — and a class's citations are computed from its fields. Two classes sharing a field share that field's citation exactly, and cannot drift apart. That is 50 citations instead of 336 blocks.

Three authorities, split by what each can actually type:

- **ENVO**, the Environment Ontology, types the **terrestrial** cover — 22 of the 29. It is what the built and farmed classes need, because the entire built environment is a single class in the alternative and the source lists characterise a traffic area, a dump site and a construction site differently.
- **IUCN GET**, the Global Ecosystem Typology, types the **aquatic** cover — the remaining 7. ENVO's terrestrial branch does not reach the sea floor or a canal; GET has a deep sea floors biome and a class for canals, ditches and drains.
- **AGROVOC**, the FAO's vocabulary, types the **regime** — irrigated against rainfed, intensive against organic, clear-felled against coppiced. Neither of the other two says anything about how land is worked.

Which authority a cover cites follows its realm, and is a **build error rather than a curator's preference**: a terrestrial cover anchored to GET, or an aquatic one to ENVO, stops the build.

**`exactMatch` is earned, not assumed.** Of the 50 citations, 14 claim to *be* the class they cite; 10 are close matches, 8 are broad ones — our value is narrower or coarser than the published class — and 17 are related matches, because the AGROVOC concept is a *practice* and our field says the land is under it. The water taxonomy claimed an exact equivalence sixteen times out of seventeen. This one claims it rarely, and saying so is the point.

**One value in the whole scheme is ours and is flagged as ours.** BAFU's *diverse-intensive* has no published class anywhere to cite, and an AGROVOC term request goes with it. Every other axis value is either anchored or has its silence recorded with a reason, so a new value cannot join the unanchored ones by being forgotten.

---

## 5. What this changes about the published list

*Measured on the full build of 19 August 2026 — EF 3.1 as the base, with ecoinvent 3.12, ecoinvent 3.8 and BAFU 2026 v1 merged — against a build of the same inputs at the commit this branch left `main`.*

### What moved

| | before | after |
|---|---|---|
| Land flow objects | 362 | **296** |
| Land flows | 362 | 297 |
| BAFU land rows reaching a flow the list already had | 8 | **87** |
| BAFU land rows creating a flow of their own | 144 | **65** |
| Land flows published as a BAFU addition | 125 | **60** |
| Flow objects in the whole list | 8,060 | 7,994 |
| Elementary flows in the whole list | 96,619 | 96,554 |

**The headline is BAFU.** Before this, eight of its 152 land rows reached a flow
the list already had. The other 144 each minted a new one — 144 duplicates of
ground EF 3.1 already published, because a land class had no field and BAFU's
spelling could not be recognised as EF's. Now 87 reach EF's flows. The 65 that
still create a flow are classes EF genuinely does not carry.

Where several BAFU rows now arrive at one flow, the fold is **written down**
rather than discovered: fifteen entries, each with its reason. Twelve are one
class that BAFU files in two or three compartments; two are a Swiss row and an
unregionalised one; and one is BAFU carrying both EF's word and ecoinvent's for
the same ground.

**ecoinvent is untouched** — 342 prepared matches, 11 algorithm matches and 11
creations, exactly as before. Its correspondence table still governs its land
rows, so the change is confined to BAFU and to EF's own internal duplicates.

### What the criteria say

Eight acceptance criteria were set before any of this was written. Seven hold.

- **No context IRI changed.** Two land context IRIs before, the same two after.
- **95 balanced `from`/`to` pairs are published and not one has a dead half** —
  which is what the whole design exists to guarantee.
- **No land flow object carries a chemical type**, where two BAFU forests used
  to be published as classes of molecules; and none has both a land slot and a
  resource slot.
- **Every `skos:broader` edge is generated**, all 206 of them, and not one
  carries a source attribution — because there is nothing to attribute.
- **`exactMatch` is earned**: of the citations published, 196 are exact, 60
  close, 35 broad and 141 related.
- **The four volume occupations are untouched**, in the contexts and units they
  were already in.

The one that does not hold, in its literal wording, is *"not one land flow is
retired by deduplication"*. **One is.** EF 3.1 ships `Occup. as Forest land`
beside `forest`; they are one land class, and the first carries **no
characterisation factor at all** while the second carries 213. So the empty
spelling is retired onto the one with the factors, and a consumer holding the
old identifier is redirected rather than stranded.

That is worth stating plainly rather than reading the criterion generously. The
retirement the criterion is *about* — a balanced pair collapsing, which is how
a water use result was once inflated by a factor of 434 — does not happen: all
95 pairs are live.

**Three further retirements were caught this way and were a real defect in this
work, not in the list.** EF ships `grassland`, `pasture/meadow` **and**
`grassland/pasture/meadow`, and the first reading of the axes folded the third
onto the first — retiring three of EF's flows and asserting that grassland takes
in mown and grazed land. It does not: a meadow is mown and a pasture is grazed,
which is why ENVO files both under *area of pastureland or hayfields* and files
grassland somewhere else entirely, and why ecoinvent draws the same line as
`grassland, natural` against `pasture, man made`. The union is now a cover of
its own and the three flows are published in their own right.

The evidence that settled it is worth keeping: `grassland` and
`grassland/pasture/meadow` carry 426 characterisation factors each with **every
value identical**, which is what first suggested they were one class — but
`pasture/meadow` carries 427, and **not one** of the 426 it shares with
grassland has the same amount. Identical characterisation is not identity, and a
factor set that distinguishes two classes elsewhere is evidence that it would
have distinguished these if they differed.

---

## 6. What a land flow object now carries

Each of the 336 classes is a flow object, and it carries:

- **its class**, as a stable key built only from its fields — `occupation/cropland/irrigation=rainfed/intensity=intensive`. Two spellings of one class produce one key, which is the whole point, and adding a new axis cannot renumber the keys of classes that do not use it.
- **its name**, built from the same fields rather than inherited from whichever source list reached it first. Before this, the object standing for natural forest could be published as *Occup. As Forest Land* because that name sorted first.
- **its type**: the ENVO or GET environmental class for its cover, and the AGROVOC practices for its regime. It carries **no chemical class at all**, which is correct and was not sayable before — the typing rules could only decline to answer, and two BAFU forests were published as classes of molecules.
- **its parent**, as `brightway:baseIntervention`. Not `baseSubstance`: that term means the undifferentiated *substance* a qualified flow was split from, and it says substance because it means it. A land class has no base substance for the same reason noise has none.

---

## 7. What this deliberately does not do

**The context vocabulary is untouched.** No value is added to it and no IRI changes. `Land Use → Occupation` and `Land Use → Transformation` are exactly what they were. Direction is a field on the class rather than a new context value, and that is why: a flow's context and its land class must agree about occupation versus transformation, and one of them should derive from the other rather than both being asserted.

**The volume occupations are not land classes** and are not touched here.

**A land class is not a place.** The taxonomy says what the land is and how it is worked; where it is remains the geography, which a separate mechanism reads out of a flow name into a `location` field. Where that has split a place off a BAFU name, the assignment records both, so the Swiss row and the unregionalised row stay two flows sharing one land class.

---

## 8. In short

A land flow used to say two things in fields and three things in a string. It now says all five in fields. Three source lists that spelled one piece of ground three ways reach one flow object, without a crosswalk row saying so, because the three spellings decompose to one value. And a balanced pair of characterisation factors is held apart by a field rather than by two words inside a label.
