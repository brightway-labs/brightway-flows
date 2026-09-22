# Matching your own list

You have a flow list — your own, a client's, a version of SimaPro nobody here
has fetched — and one question about every row of it: **which consensus flow is
this?**

You can ask, one row at a time, without building anything.

```python
from brightway_flows.lookup import FlowMatcher, FlowQuery

matcher = FlowMatcher.from_results()

answer = matcher.match(FlowQuery(
    name="Benzene, chloro-",
    context=["Emissions to air", "low. pop."],
    cas="108-90-7",
    unit="kg",
    simapro_origin=True,
))

answer.pref_label          # 'Chlorobenzene'
answer.context_display     # ('Environmental', 'Air', 'Medium stack, <150 meters',
                           #  'Rural (<1000 people/square mile)')
answer.elementary_flow_id  # 'fe0acd60-3ddc-11dd-a2e3-0050c2490048'
answer.basis               # 'cas'
```

Chlorobenzene, released from a medium stack over open country, in kilograms.
That is what your row is, in this list's words, and the identifier is what you
write down.

## Ask about the whole list at once

Reading the consensus list takes a couple of seconds and answering a row takes
under half a millisecond, so hand it everything you have:

```python
answers = matcher.match_many(
    FlowQuery(name=row["name"], context=row["compartment"],
              cas=row["cas"], unit=row["unit"], simapro_origin=True)
    for row in my_list
)
```

Two thousand six hundred rows come back in about a second.

## How much of a list gets an answer

BAFU's 2026 list is the closest thing this project has to your situation — a
SimaPro-shaped list, 2,679 rows — so it is the honest measurement. Asked cold,
with nothing but what the vendor file carries, against the build of 21 August
2026:

| what you give it | rows answered | rows placed differently from a full build |
|---|---|---|
| name, compartment and unit | 2,091 of 2,679 (78.1%) | 25 |
| …and the CAS numbers the file carries, on 1,147 of the rows | **2,391 (89.2%)** | **5** |

**A registry number is worth about eleven rows in a hundred**, and it is worth
more than that in confidence: giving one cuts the rows that land somewhere a
full build would not from 25 to 5.

Two things follow. Supply every CAS and EC number you have. And supply every
name you have — the list is searched under all of a row's names at once, so a
synonym you know is another chance to match, and costs nothing.

**Write the unit and the place in their own fields, not in the name.** SimaPro
lists flows in one flat column, so a list with that lineage often carries them in
the name instead — `Wood, unspecified, standing/m3`, `Water, AE`. Say
`simapro_origin=True` and both are read back out before anything looks the row
up, exactly as a build reads them out of the vendor's own file; the answer's
`prepared_name` says which name earned the match. That is worth four of BAFU's
rows, and the spelling you sent is still tried as well, so it can only help.

The same flag applies the lineage's curated corrections to your row, exactly as
a build applies them to a SimaPro-shaped list — `Uranium-238` sent with the
element's registry number takes the isotope's; `Uranium, 451 GJ per kg` in
kilograms becomes `Uranium` in megajoules; `Carbon dioxide, in air` is read as
the biogenic uptake it means. `preparation_steps` then includes `lineage-fix`,
and where your unit was rebased `prepared_unit` and `unit_conversion_factor`
say onto what and by how much, so a kilogram you sent and the megajoule flow
you were matched to add up.

## What the answer tells you

`matched` is true or false, and either way you get something you can act on.

When it matched: `elementary_flow_id` is the identifier, `pref_label` and
`context_display` are the substance and the compartment in this list's words,
`unit` is what it is measured in, and `basis` says what the match rested on —
`cas`, `ec`, `label`, `cas+qualifier`, `cas+designation` for a shared CAS
settled by the industry designation the row's name ends in — `Ether, …,
HFE-347mcc3` — `simapro-name-pattern` for a name this project derived from
SimaPro's habits, or `historical-name` for a name ecoinvent retired after 2.2 —
`Basalt, in ground`, `Sulfate, ion` — that the vendor's own crosswalk says
became a substance this list holds.

When it did not, `selector_reason` says why, and `candidates` names every
substance the row could have been, with what each is called. That is what a
`multiple-flow-object-candidates` answer is for. A row carrying 7732-18-5 and a
name none of them answers to reaches twelve substances at once — turbine water,
fossil groundwater, rainwater, water, sea water, green water, water vapour, river
water, cooling water, lake water, groundwater and fresh water — because every
kind of water is H₂O. You get all twelve by name, which is what choosing between
them takes.

**It never guesses.** Where it cannot tell, it says so. On BAFU's 2,679 rows it
placed 2,391 and declined 288; it did not put a single row somewhere it could
not defend.

## Compartments in your own words

Your compartments are yours. You do not have to translate them.

`["Emissions to air", "low. pop."]` is what a SimaPro export writes, and it is
understood, because BAFU has already written down what those 26 compartments
mean. So has ecoinvent for its 26, EF 3.1 for its 37, GreenDelta's openLCA
method package for its 21, and Stepwise 2006 for its 10 — and AGRIBALYSE 3.2 for its 22,
eighteen of which are BAFU's spellings again, because both lists carry
SimaPro's export vocabulary. Between them, 122
compartment names are recognised.

Stepwise's ten are a SimaPro *method* file's vocabulary — `Air /
(unspecified)`, `Water / groundwater, long-term`, `Raw / (unspecified)` — which
until that list was registered only the table below had. Two of them,
`Soil / agricultural` and `Water / ocean`, are ecoinvent's spellings exactly,
and the two lists agree about what they mean; every other compartment string in
this project is written by one vendor and no other.

It was eleven. The eleventh was `Social / (unspecified)`, where Stepwise files
three counts of injured people, and those rows are refused: an injury is not an
emission and not a resource, so it is not something this list carries. A
compartment nothing is filed under is a compartment nobody has to translate.

**And SimaPro's own spellings on top of those.** A list exported from SimaPro
carries SimaPro's compartments whatever the flows in it came from, and most of
those are nobody's list: `Raw / in ground`, `Airborne emissions / low. pop.`,
`Waterborne emissions / river`, `Final waste flows /`. Another 43 spellings are
read. The published `SimaPro-2025-ecoinvent-3.12-context` table is where the
vocabulary started, but it is not where all of it lives: the spellings that
refuse to name a medium, the bare method-file compartments and the `Raw
materials` medium rows were reported by callers and written down by hand, and
the table carries none of them — so this section cannot be regenerated from
the table without silently losing those rows. It was 46 until AGRIBALYSE was
registered: the bare `Emissions to air`, `Emissions to soil` and `Emissions to
water` headings are the empty-subcompartment spelling a `{processes}` export
writes, and once that list ruled them they became its rows rather than this
table's. Where a
list has already ruled on a spelling that list's answer is used, so
`Emissions to water / river` is river water and not the coarser surface water
that table would give it.

The one exception is a spelling that refuses to name a medium. `Raw /
(unspecified)` says *this is a resource* and declines to say which kind, and
this project publishes no bare `Resource` context to answer it with. Stepwise
files 134 rows there — ores, standing timber, land occupation and an uptake
from air — and its own rules take the exceptions out by name and then say
`ground` for what is left, which is true of that list and not of the
compartment. So a caller who names Stepwise gets `ground`, and a caller who
does not gets the dimension and no medium, which is all the compartment
actually says. BAFU's `resources / unspecified` is read the same way, for the
same reason: BAFU's rule says `ground` for what is left once its land rows are
taken out by name, and BAFU files `Carbon dioxide, in air` there.

`answer.context_resolution` says how yours was read:

| | |
|---|---|
| `given` | you supplied a consensus context IRI, and it was used |
| `named-list` | you said `source_label="ecoinvent-3.12"` and that list's own rules placed it |
| `any-list` | one of the 122 recognised compartment names |
| `simapro` | a compartment SimaPro writes and no list spells |
| `dimension-only` | you said which *kind* of compartment and not which one — see below |
| `consensus-strings` | you wrote this project's own words — `["Environmental", "Air", "Indoor"]` |
| `ambiguous` | the compartment holds two contexts and your flow's name picks neither |
| `unresolved` | none of the above |

An unresolved compartment does not stop the match. What it does is take away the
strongest signal: the substance is still identified, and the flow of it is then
chosen on the unit alone — which settles a substance that has only one flow, and
honestly reports a tie for one that has several. It is never filled in with a
guess, because the compartment is what decides whether a release to a lake is
published as a release to groundwater, and that is not a question to answer by
approximation.

### "A resource, and I am not saying which kind"

`Raw` with nothing after it — however you write the nothing: `Raw/`,
`["Raw", "(unspecified)"]`, `["Raw", "unspecified"]`, `["Raw", ""]` — says the
row is a resource and declines to say whether it came out of the ground, the
water, the air or a living thing. `Raw materials` and `Resources` say the same
thing and are read the same way. `Resources` is the one most callers hold: a
process export writes `Raw` as the compartment and `Resources` as the section
heading, and `bw_simapro_csv` builds its context from the heading, so every
resource row it produces arrives spelled that way. It used to be read as
`Resource → Ground`, and an uptake of carbon dioxide from the air asked about
under that heading could never reach the air resource of its own substance.

The three spellings stay together once the medium *is* said, too. `Raw / in
air`, `Raw materials / in air` and `Resources / in air` are one statement, and
for a while only two of the three were read: an uptake of oxygen asked about
under `Raw materials / in air` resolved to no compartment at all, while the
same row spelled `Raw / in air` resolved to the air resource — a gap no caller
can predict, because which spelling a row carries depends on the export path
and not on the row. The four medium rows are now read under every spelling,
`in ground` included, where a land occupation or transformation is still told
apart from the ores by its name rather than filed as a ground resource.

There is no consensus context for that, and putting one in would be worse than
leaving it out: a flow filed as `Resource → Ground` loses every biotic, water
and air flow of its own substance before anything is scored, and standing wood
is biotic. So the *dimension* is used and the medium is left to the substance.
That is enough to keep an emission to air out of the running, and for 209 of the
222 substances that have a resource flow at all there is only one to choose
from, so the substance settles it. The thirteen that have more than one come
back as a tie, which is the honest answer for them.

If your compartments are not recognised and you know what they mean, the
shortest fix is to say so once per compartment with `context_iri`.

## Water and land: curated answers your name can reach

Lake water, river water, sea water, cooling water and rainwater are all H₂O and
all carry 7732-18-5, so the registry number reaches twelve substances at once.
Which one a row is was decided by a curator, one vendor row at a time, in a
table keyed on the vendor's own row identifier — which your row does not have.
The same is true of land: `Occupation, arable` is cropland because somebody
wrote that down, not because a rule read the name.

But every row of both tables also records the vendor's spelling, and no vendor
disagrees with another about most of them: BAFU and five ecoinvent releases all
call `Water, lake` lake water, and no two of the land table's 1,517 rows
disagree about any of its 496 names. So the lookup consults both tables under
your row's name, and

```python
FlowQuery(name="Occupation, arable", context=["Raw", "land"],
          unit="m2a", simapro_origin=True)
```

comes back as cropland, `basis="land_class"`, with
`selector_details["curated_name_table"]` saying which table answered. The name
is looked up after preparation, so `Water, unspecified natural origin/kg`
finds the entry for `Water, unspecified natural origin`. On the build of
1 September 2026 (`20260901T0451332605450000`) this answers 425 of the 425
recorded land rows and 309 of the 326 recorded water rows, where before it
answered 93 and 201.

Three rules keep the shortcut honest. A name the tables read two ways is
settled by your compartment or not at all — `Water, unspecified natural
origin` is fossil groundwater at a fossil well, groundwater in the ground and
plain water in surface water, and a caller who writes `Raw` and refuses to
name a medium gets no material rather than a guess. A compartment you did
resolve is never crossed: the tables answer at the rung your compartment
reaches — its resolved context, or its dimension where that is all you said —
and never from a coarser one, so `Water, lake`, curated entirely in water
resource compartments, says nothing about a discharge into a river, and a lead
emission that happens to carry that name still matches lead by its stated CAS.
A curated entry may add a way for your row to match and never takes one away —
a row the fill places nowhere is asked again as if the tables had no entry.
And a value you state yourself always wins:

```python
FlowQuery(name="Water, lake", context=["resources", "in water"],
          unit="m3", material="lake_water")
```

`material` takes a published material concept id and `land_class` a published
land-use key, so a row the tables have never seen — or one you know the tables
are wrong about — is still yours to place.

## One thing it cannot work out from a name

**Which particle size band.** `Particulates, < 10 um` is PM10 — every particle
below ten micrometres — and `Particulates, > 2.5 um, and < 10um` is the coarse
fraction between 2.5 and 10. The two are spelled almost identically, are
characterised very differently, and carry no registry number between them.
There is no curated per-name table here, deliberately: a particle name reaching
PM10 because it resembles PM10's is exactly the accident #153 removed. If you
know the window, say so:

```python
FlowQuery(name="Particulates, < 10 um", context=["emissions to air", "unspecified"],
          unit="kg", size_class="pm10")
```

The published ids are `pm0_2`, `pm0_2_to_pm2_5`, `pm2_5`, `pm2_5_to_pm10`,
`pm10`, `above_pm10`, and `unsized` for a row that states no cut at all. If you
leave it out, a particle row has only its name to be found by, which is what
sent one vendor's coarse fraction to the flow named PM10 before this field
existed.

The size-class ids, like the material concept ids and land-use keys of the
previous section, come from a published vocabulary — documented words rather
than private ones.

## If your list has already been merged

If your rows come from a list this project has merged — EF 3.1, an ecoinvent
release, BAFU — then the decision has already been made about each of them, and
it can be looked up rather than derived again:

```python
answer = matcher.match(FlowQuery(
    name="Benzoylprop-ethyl",
    list_key="ecoinvent-3.12",
    identifier="c9fc157a-ac5d-5614-a8a2-0060c81baeb3",
))
answer.tier        # 'recorded'
answer.pref_label  # 'Ethyl N-benzoyl-N-(3,4-dichlorophenyl)-DL-alaninate'
```

Which is also the argument for using it where you can. ecoinvent calls that
herbicide `Benzoylprop-ethyl` and this list publishes it under its systematic
name; the identifier does not care, and a name would have had to be recognised
first.

This route is exact, and it includes the decisions a curator made by hand, which
the matching rules would not reproduce on their own. All 9,850 rows of ecoinvent
3.12 answer this way, and so do all 94,040 rows of EF 3.1 itself.

`answer.tier` is on every answer and says which happened: `recorded` for a
decision already made about your exact row, `algorithm` for one worked out now.

### A row spelled like one somebody already decided

Usually you have no identifiers — your rows came through a SimaPro export, not
from the vendor's own file — but many of them are spelled exactly like rows a
merged list ships. `Oxygen` as a resource from air is recorded onto the same
flow by BAFU, ecoinvent 3.12 and ecoinvent 3.8. Opting in lets those decisions
answer:

```python
matcher = FlowMatcher.from_results(recorded_by_name=True)

answer = matcher.match(FlowQuery(
    name="Oxygen", context=["Raw", "in air"], unit="kg", simapro_origin=True,
))
answer.tier  # 'recorded-by-name'
```

It is opt-in because it is a judgement — that your row *is* the row somebody
decided — rather than a fact, and `tier` says so on every answer it produced.

The key is your row's name and the place your compartment resolves to, not
anybody's spelling of it, so BAFU's `resources / in air` and your `Raw / in
air` reach the same decision. On the build of 1 September 2026, 15,757 distinct
name-and-place keys hold one recorded flow, and most of what a name alone
would call a collision is not one: `Carbon dioxide` reaches eight flows by
name and one per place. Exactly one key is read — the one your compartment
reached. A compartment that resolved to a place is answered at that place or
not at all: a name recorded only as an air emission says nothing about your
water row, and the algorithm decides it instead. If your compartment names
only a dimension — `Raw` and nothing after it — you are answered where every
recorded row of that dimension agrees, and if it could not be read at all,
only where the name has one recorded flow everywhere. It never crosses a
boundary you named.

Forty-two keys hold two flows, and those are genuine disagreements —
`Carbon dioxide` in unspecified air is fossil carbon to BAFU and Stepwise and
land-use-change carbon to ecoinvent, because ecoinvent spells fossil out as
`Carbon dioxide, fossil` and marks this variant by identifier alone. A
disagreement declines rather than being arbitrated — unless you have said
whose vocabulary your list speaks, which is the one fact the tie is missing:

```python
answer = matcher.match(FlowQuery(
    name="Carbon dioxide", context=["Emissions to air", ""], unit="kg",
    cas="124-38-9", simapro_origin=True, source_label="stepwise-2006-1.09",
))
answer.pref_label                                          # 'Carbon Dioxide (fossil)'
answer.selector_details["arbitrated_by_source_label"]      # 'stepwise-2006-1.09'
answer.selector_details["recorded_alternatives"]           # what ecoinvent said instead
```

`source_label` already steers how your compartments are read; naming it here
additionally makes the named list's own recorded rulings win its ties, and the
answer says so, with the competing flows listed so the choice can be audited.
One spelling serves both: a registered list is recognised by its key
(`stepwise-2006-1.09`), its bare name (`stepwise`), or the label its published
flows carry (`EF 3.1`), and the same spelling that reaches its compartment
rules reaches its rulings. Where every list already agrees, the label changes
nothing about the flow you get — it only makes the answer's `recorded_list`
name your own list's row rather than an arbitrary agreeing one. Thirty-three
of the forty-two disagreements are settleable this way.

## What it will not do

**It will not create anything.** When a build finds no consensus flow for a row,
it makes one. This says `matched=False` and tells you why. Whether your row
deserves a flow of its own is your decision and a curator's, not a lookup's, and
making it is what adding your list as a source list is for.

**It answers for one build, and only that one.** `answer.build` names the run and
the revision. The consensus list moves — flows are deprecated, substances are
split — so an identifier you store and never re-ask about will drift.
`answer.is_deprecated` and `answer.replaced_by` are there for exactly this, and
the published `redirects` block is how you catch up.

**It will match less often than a build would**, and by a route worth
understanding. A build checks a vendor's registry number against Common
Chemistry before it trusts it; this does not, because it makes no network calls.
BAFU ships `Nitrogen, organic bound` with CAS 7727-37-9, which is the number for
dinitrogen — N₂ in the air, not nitrogen bound up in organic matter. Given that
number, the lookup follows it and lands on dinitrogen. The build knew better,
because it had checked. Four of the five rows where a cold BAFU list is placed
differently are that one substance.

So: the lookup believes the number you give it. That is usually right and is why
a CAS is worth eleven rows in a hundred — and when a row comes back as a
substance you did not expect, the number on your row is the first thing to look
at.

## It writes nothing

The database is opened read-only, no flow is created, no identifier minted,
nothing queued for review. You can run it against a build somebody else is
reading, and you can run it while a build is in progress — in which case it
refuses to answer rather than answer from half a list.
