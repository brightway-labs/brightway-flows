# Characterisation factors

Kresoxim-methyl is a fungicide. Sprayed on agricultural soil, how much does it
contribute to freshwater ecotoxicity? EF 3.1 answers that, and this list
publishes **three** answers to it, because EF 3.1 is a method and a method has to
be implemented against a flow list before it is a number you can use:

| Implementation | Says |
|---|---:|
| EF 3.1 as the European Commission's JRC published it | 134.73 |
| EF 3.1 as the ecoinvent Centre implemented it | 53,540 |
| EF 3.1 as this list publishes it | 134.73, **because a curator ruled** |

397× apart, from one method. Neither team made an arithmetic mistake. EF's own
files carry kresoxim-methyl **twice** in every context — the same name and the
same CAS number, 143390-89-0, under two EC numbers — and the two rows carry
different factors. This pipeline merged them into one flow and kept one number of
the two; the ecoinvent Centre, reading the same two rows, kept the other.

So this is not two teams disagreeing about toxicology. It is one question about
EF's own duplication, answered twice, differently — and a curator answered it
here, in `data/lcia-factor-rulings.json`, with the reasoning written down. Until
they did, this list published **nothing** for it, which is the default: where two
implementations disagree and no ruling exists, the honest artifact is a question.

That is what this layer is for. It does not compute impacts, it does not average,
and it does not pick a winner where two competent teams disagree without saying
who picked and why. It puts every number on one flow list, says who said it, and
makes the disagreements findable.

## Four implementations, one method

`implemented_by` is the field the whole layer turns on. There is no correct
implementation of a method:

- **`European Commission — JRC`** — 318,774 factors over 88,907 flows. EF 3.1 is
  the base list, so these arrive already on consensus flows: an identity join,
  and one hop where the build has since merged the flow they were read off into
  another (below). 51,944 of them are a stated zero, which is a claim
  ([#47](https://github.com/brightway-labs/brightway-flows/issues/47)):
  "assessed, and zero" is not "never assessed".
- **`ecoinvent Centre`** — 26,479 factors over 7,709 flows, read from the
  workbook `fetch-lcia ecoinvent-3.12` downloads. These take two hops: the
  workbook names an ecoinvent flow, the merge says which consensus flow that
  became, and only then is there a factor about a flow of ours.
- **`GreenDelta`** — 25,266 factors over 1,509 flows, read from the openLCA
  method package `fetch-lcia bafu-2026-v1` downloads: `EF 3.1 Method (adapted)`
  from *openLCA LCIA methods 2.8.0*, as BAFU's openLCA distribution ships it.
  Their flows are found two ways. Most take the same two hops as ecoinvent's,
  through whichever release has the flow: the package identifies flows by the
  **ecoinvent** UUID it was built against, declaring compatibility with
  ecoinvent 3.6 to 3.11, so 1,144 are reached through ecoinvent 3.12, 50 through
  3.8, and 29 are EF 3.1 flows already.

  The other 381 are reached by **what the substance is**, because a method
  package is not a flow list and 558 of their rows name a substance under an
  identifier nothing here has. A curated decision first, then a registry number
  — theirs are written zero-padded, `000056-23-5` for carbon tetrachloride —
  and then an exact name, all three inside the compartment the factor was
  stated in. Never a substance alone: a freshwater number reaching a flow in air
  would be a wrong factor rather than a missing one, so the compartments are 21
  curated rows saying what each of theirs means. Where two flows of ours carry
  one registry number — `Water` and `Water vapour` both carry 7732-18-5 — the
  name settles which, and where nothing settles it the row is reported and
  matched to neither.

  **The curated decisions are 91 rows**, in
  `data/lcia-substance-decisions.json`, and 25 of them are about ions. Their
  package writes `Copper ion` where this list publishes `Copper, Ion`, and
  `Cadmium II` where it publishes `Cadmium(2+)`, with no registry number to fall
  back on. Nothing about the
  strings settles that, but their own file does: each of those names appears in
  it once per compartment, nine to thirteen times, and most of those copies
  carry an ecoinvent UUID that already resolves — to `Copper, Ion` seven times
  out of twelve, and never to a second substance of ours. A row carries that
  reading into the compartments where their identifier does not resolve, and
  records the count it rests on. Seven of the 25 are declined instead: they are
  metals emitted to a lake, where this list publishes only the element-named
  flows BAFU brought, and the finding that reports each one carries the
  reasoning.

  **The other 66 are a land class or a kind of water.** Three of their
  compartments — `Resource / land`, `Resource / in water` and `Resource /
  unspecified` — name a place where this list names an action, so nothing about
  `Occupation, agriculture` reaches a flow: the word *Occupation* is our context
  and never our label, and *agriculture* is the land class. What says which
  class is BAFU's own list. The package is distributed inside BAFU's database
  and names its flows as BAFU names them, and this project has already read
  every one of those names, once, into `data/land-flow-classes.json` and
  `data/water-flow-materials.json`. Their file agrees where it can — 76 of their
  `Resource / land` flows carry an ecoinvent UUID that resolves, 23 to land
  occupation and 53 to land transformation and none anywhere else — and so do
  the numbers: 640 of the 1,528 factors these rows carry are bit-identical to
  what the JRC states for the same flow, category and country, and none of the
  1,528 disagrees
  ([#166](https://github.com/brightway-labs/brightway-flows/issues/166)).

  **195 of their rows write the country into the flow name**, and are set
  aside rather than matched. `Water, well, CH` is stated beside `Water, well`,
  and the site-generic row already carries one water-use factor for each of
  209 countries, Switzerland's among them; a factor's place is its geography,
  so the coded row is the same number written a second time. Before this rule
  47 `Water, XX` rows reached `Water` in Environmental → Water → River by their
  registry number and put 47 countries' numbers on one flow under no country,
  which the build reported as a collision. Each row set aside is reported with
  the reason, the way a declined decision is, and counted apart from the nine
  curated declines. Where a set has no site-generic member the `GLO` row stands
  for it: `Water, unspecified natural origin, GLO` reaches `Water` in Resource →
  Water → Unknown by a curated decision, which is where BAFU's 78 rows of those
  names already go. Three rows have neither — `Water, well, RER` under
  `Resource / in ground`, where their `Water, well` is not — and nothing of
  them is published
  ([#166](https://github.com/brightway-labs/brightway-flows/issues/166)).

  913 of their factors reach nothing on the build of 2026-08-29: the 195 rows
  above carry 376 of them, and the rest are the ties and unit crossings
  [#165](https://github.com/brightway-labs/brightway-flows/issues/165)
  reports.

  **It is here to be compared with, and it decides nothing.** The consensus
  implementation is derived from the JRC's and ecoinvent's alone
  ([#157](https://github.com/brightway-labs/brightway-flows/issues/157)): a
  number of GreenDelta's is never evidence for a number of ours, never a
  candidate in a curator's queue, and publishing it changes no factor this list
  states. What it does is put a third reading of EF 3.1 in the difference
  report, where a disagreement is a question somebody can look at.
- **`brightway-flows`** — 324,629 factors on the 2026-08-24 build, and every
  one of them is one of the other two's. 21,770 are `agreed` — both
  implementations stated the same number, so there is nothing to decide —
  297,544 are `sole`, where only one of them spoke at all, and 32 are `ruled`: a
  curator looked at a disagreement and said which number to publish.

  Two more take a number only ecoinvent states, and both say so on the factor.
  **4,402 are `restated`**: the number is one this list already publishes in the
  same impact category, so publishing it decides nothing new. Mostly that is a
  compartment EF's flow list does not have — no silvicultural soil, no
  industrial soil, no groundwater — where ecoinvent characterises the missing
  compartment with the value it states for the nearest one EF does have, a value
  this list already publishes for the same substance, allowing for the last few
  digits a unit conversion can move. **The `adopted` factors are the ones a
  person signed for**, in `data/lcia-factor-adoptions.json`: a substance taking
  *another substance's* number, with the relationship named on the entry. EF
  characterises copper and has no `Copper, Ion` flow; ecoinvent ships the ion
  and gives it copper's numbers; the entry says `ion-of`, and the ion's factors
  publish as `adopted`. Ten ions, two conjugate pairs and 53 land classes taking
  their family's number were signed on 2026-09-01, beside the file's first two
  populations: 62 pesticides whose numbers are a
  catch-all's, accepted as a population because ecoinvent's own correspondence
  routes them into `Insecticides, unspecified` and its implementation
  characterises them there, while this list publishes them under their own
  names; and 23 minerals — sodium chloride, gypsum, potassium chloride, borax —
  that EF's flow list carries and the JRC never priced, whose ecoinvent number
  is the JRC's own element factors weighted by the mineral's formula, checked
  ([#155](https://github.com/brightway-labs/brightway-flows/issues/155)).

  Where the implementations disagree, or where ecoinvent states a number of its
  own that nothing else in the list carries anywhere, this publishes nothing and
  asks. On the 2026-08-24 build that is 34 open questions over 128 factors where
  the two implementations contradict each other, and 37 over 39 where only
  ecoinvent speaks — the second down from the 5,326 factors that queue would
  hold with no rules at all.

Each implementation has its own 25 impact categories, so EF 3.1 accounts for 100
of the published set. All of them are *long term*: excluding a source list's
long-term compartments is that list's convention, not this one's, and a list that
published both a long and a short set would be publishing a choice it has no
basis to make.

## Two methods, and nothing that assumes either

EF 3.1 is a method this list characterises against, and it is not the method this
list is about. Everything above is written per method: a method states its own
categories, its own reference unit for each, its own implementations, which of
them decide anything, and where each of their factors is read from — and it
states all of that in a file of its own. `data/lcia-impact-categories.json` is EF
3.1's. Adding a second method is adding a second file, and there is now a second
file.

**Stepwise 2006** is it: `data/stepwise-2006-impact-categories.json`, 19
categories under two implementations rather than 25 under four. Two, because one
publisher renders it — 2.-0 LCA consultants, whose SimaPro export is the whole
of it — so there is nothing to cross-check and every consensus factor of it is
`sole`. That is the shape a method with one publisher has, and it needed no case
of its own: the method's own publisher decides, ours does not, and the derivation
that reconciles four implementations of EF reconciles one of Stepwise.

So the published set is 138 categories: EF 3.1's 25 times four, and Stepwise
2006's 19 times two.

**What a Stepwise number means is written in its method file, with whose words
those are.** An EF 3.1 category's `indicator` is transcribed from a publisher:
acidification's is the JRC's `Accumulated Exceedance (AE)`. Stepwise's export
gives a category a name and a unit and nothing else, so there is nothing to
transcribe. But Stepwise takes most of its categories from EDIP 2003 and
IMPACT 2002+, whose documentation names each indicator, and documents the rest
itself. So Stepwise's acidification publishes `Area of unprotected ecosystem
(UES)` — EDIP 2003's words for what `m2 UES` counts — and the category's
`meta.indicator_source` names EDIP 2003 and quotes it. That key appears only
where the words are not a publisher's own; where nobody's words exist at all,
`indicator` is `null`.

**Two methods share the flow list and nothing else.** That is not a modesty
about the code, it is a fact about the science: Stepwise 2006 also has a category
called `Acidification`, counted in `m2 UES` from a different model, and it is not
EF's. So no category name, no category slug, no reference unit and no curated
ruling crosses from one method to the other. A ruling written about
kresoxim-methyl under EF's freshwater ecotoxicity says which method it is about,
and is read for that method alone; a question in a factor queue is named by its
method as well as its substance and its category; every row of the difference
report and the coverage summary says which method it is a row of; and every
number a run counts about a method — how many factors an implementation stated,
how many the curators have ruled on — is counted under that method's name.

**Whether an implementation decides is on its row**, not in a list in the code.
GreenDelta's says `decides: false` and is published, transcribed and compared
like the rest; the JRC's and ecoinvent's say `decides: true` and are what the
consensus implementation is derived from. The method's own publisher always
decides, and ours never does, because ours is the thing being decided.

The one thing that *is* shared is this list's own name: `brightway-flows` is
the implementation this list publishes for every method it characterises, because
it is the same people saying it. Which method a row of ours belongs to is said by
the category it is under, not by the name on it.

## A factor about a flow this build merged away

Two files come out of one build, and they have to agree about which flows exist.
`harmonised-flows-simple.json.gz` publishes only live flows and files every
deprecated identifier under `redirects`, saying what replaced it and why.
`lcia-factors.json.gz` used to go on publishing factors against those
identifiers — 1,674 of them over 166 flows on the 2026-08-25 build — so a
consumer that loaded both saw numbers about flows the flow list does not have
([#163](https://github.com/brightway-labs/brightway-flows/issues/163)).

The factors now follow the build's own redirects, and follow exactly the ones it
tells a consumer to follow:

- **`identity-merge`** is the same flow reached twice, so a factor about one copy
  is a factor about the flow. 151 identifiers, and their numbers move onto the
  survivor.
- **`context-collapse`** is not: two source contexts our vocabulary cannot tell
  apart, whose factors may legitimately differ
  ([#1](https://github.com/brightway-labs/brightway-flows/issues/1)).
  15 identifiers, 80 factors, every one of them the same number the survivor
  already publishes — they are reported as `redirect-refused` and not carried
  across.

Where a redirected factor meets one the surviving flow states itself, **the
flow's own number stands**. That pair was settled when the build collapsed the
two flows: the more precise number was kept and the other written onto it as a
superseded value
([#63](https://github.com/brightway-labs/brightway-flows/issues/63)), which
is where kresoxim-methyl's 53,540 against 134.73 is on the record. Asking again
here would publish neither and withdraw 132 factors the build has already
decided.

Where the surviving flow states **nothing** for that category and place, the
number is carried onto it and the factor names the retired identifier as its
`source_flow_uuid`. 72 factors, over three substances, and each one is a
`redirect-followed` finding — because this is the one case where following a
redirect adds a factor rather than restating one, and deduplication deliberately
leaves it open: it settles a number two rows both publish and unions nothing.
## What makes two numbers comparable

Almost all of the work is here, and none of it is arithmetic.

**The category.** The JRC calls it `Ecotoxicity, freshwater`; ecoinvent calls it
`ecotoxicity: freshwater`. One category, two names, and nothing in either file
says so — the method's own file, `data/lcia-impact-categories.json` for EF 3.1,
is what does: one row per category with every implementation's words and ours.
Comparing on either publisher's own name compares nothing with nothing: every
factor comes out `sole`, no factor is ever `agreed`, and the counts look entirely
plausible. Comparing across two *methods* on the strength of a shared name would
be the same mistake one level up, which is why nothing does.

**The flow.** A factor is about a flow, so a factor can only be as good as the
merge that placed it. 9,848 of ecoinvent 3.12's source flows reach a consensus
flow, and of the 7,960 its workbook characterises exactly **two** do not — a
question for the merge, not for this layer, and a finding rather than a silent
loss.

**The place.** EF states a geography on 42,871 of its factors — 223 codes, mostly
ISO 3166-1 alpha-2 — and `Land use` gives one flow 213 of them, from `-522.81` in
`ES-CA` to `-227.0` in `YE`. Two places are two factors, which is why the
identity of a factor is the triple **(impact category, flow, geography)** and not
a pair. ecoinvent's workbook states no place at all, so on the raw count every
located EF factor looks "dropped" by its implementation; that is two file
formats, not a gap in anybody's science.

**The unit.** A factor stated per kilogram, on a flow published per megajoule, is
not a number you can use. Those are converted by the flow's own property — a
uranium factor of 560,000 per kg over 560,000 MJ/kg is 1.0 per MJ, which is the
JRC's own number for the megajoule flow, so the conversion is checkable rather
than asserted.

The conversion comes from the row itself where the row has one, and otherwise
from the build: every multiplier the merge recorded is indexed by the flow and
the pair of units it joins, so a factor reached by a name or by a curated
decision can use the number a merged list already established for that same
flow. GreenDelta's water use factors are stated per kilogram and this list
publishes water per cubic metre; BAFU's own kilogram water rows carry 0.001 m³
per kg onto the very same flows, and 213 factors are published on that
([#170](https://github.com/brightway-labs/brightway-flows/issues/170)). A
flow whose rows state two different multipliers for one pair of units — natural
gas, at 34.5 and 36.0 MJ per cubic metre — is not converted, because the
evidence is that there is more than one answer. Where no conversion exists at
all the factor is not published and the crossing is a finding.

**The sign.** Taking a cubic metre of water out of a French river costs +6.98
under EF 3.1's water use; putting a cubic metre back is −6.98. A process that
withdraws and returns the same water scores about nothing, which is the point of
the pair — and which half a factor is, is not written on the factor. It is the
direction of the flow: water taken from the environment is a resource, water put
back is an emission.

GreenDelta's package states both halves positive. Their 1,438 withdrawals are
right; all 416 of their factors on water emitted to water are the returning half
with the minus sign missing, so as shipped, giving the water back would *add* to
a water-use score. The magnitudes are the JRC's exactly — on the 1,046 that can
be compared, every one agrees to the digit — so this list reads the sign off the
direction their own package states, rather than publishing a number that says
the opposite of what it means
([#172](https://github.com/brightway-labs/brightway-flows/issues/172)).

Water use is the only EF category counted as a pair like this, and the rule is
about water returned to *water*. Water evaporated to air is a real loss from the
catchment and counts positively — the ecoinvent Centre states +42.95 for water
vapour in every air compartment. Land transformation looks like a pair and is
not: *from forest* and *to forest* are two flows rather than two directions of
one, and GreenDelta's 5,733 negative land-use factors are right as they stand.

## Where they disagree, nothing is published until somebody rules

Two implementations, one triple, two numbers. There is no faithful third number,
so this list publishes none and asks. That is the `contested-factor` queue: on
the 2026-08-24 build, 38 questions over 152 factors, of which **34 are still
open**, each carrying what a ruling needs — where each flow came from, what
this pipeline did to it, and every number anybody states about it, including
the ones a merge already declined.

The mirror case is `proposed-factor`, the factors ecoinvent states for flows the
JRC does not characterise. Most never reach the queue: where the number is one
this list already publishes for the same substance in a neighbouring compartment
it is published as `restated`, because nobody is proposing anything, and where
it is another substance's number — the way an ion carries its element's — a
person's signed entry in `data/lcia-factor-adoptions.json` publishes it as
`adopted` or declines it on the record. What reaches the queue is a number of
ecoinvent's own: 40 questions
over 48 factors on the 2026-08-24 build, of which 37 are still open and 33 of
those are rocks and minerals ecoinvent prices for `Resource use, minerals and
metals` and EF never did — granite, gypsum, talc. Adopting one means publishing
a factor the method's own publisher never stated, about science only ecoinvent
has spoken to. That is a decision, and it is asked rather than taken.

Twenty-three of those minerals were then approved
([#155](https://github.com/brightway-labs/brightway-flows/issues/155)),
and the reasoning is worth having in one place because it is checkable. The JRC
prices the *elements* in the crust — chlorine at 2.71e-5, sulfur at 1.93e-4,
boron at 4.27e-3 kg Sb-eq per kg — and ecoinvent's implementation report (v3.12,
Table 20) prices a mineral as those factors weighted by mass share. Sodium
chloride is 60.7% chlorine: 0.607 × 2.71e-5 + 0.393 × 5.5e-8 = 1.646e-5, which
is ecoinvent's number to four digits. Gypsum is 18.6% sulfur and calcium carries
nothing: 3.59e-5, again ecoinvent's number. Where the formula reproduces the
number the mineral is those elements in the crust and the JRC has already priced
it, so the number is adopted and published as `adopted`; where it does not —
feldspar, olivine, and eight rocks with no formula to check — the question stays
open. What that population *records* is different from the pesticides': the
number it was made about, so that a revised number from ecoinvent is a new
question rather than an automatic yes. The mechanism is the same one a ruling's
`ruled_about` uses.

A ruling is consulted before the twin is, and that order is what lets a
curator overrule a restatement. The twin once had a second half that read a
matching number on *any* flow of the category as the same number — retired on
2026-09-01 in favour of the signed entries above
([#156](https://github.com/brightway-labs/brightway-flows/issues/156)),
because the same digits carried lindane's numbers onto its manufacturing
contaminants — and once it read the same *quantity*: EF 3.1 counts water
consumption as withdrawal less return, +42.95 on every water taken and −42.95
on every water given back, and the ecoinvent Centre counts it as what
evaporates, 42.95 on `Water` to air and nothing on the rest. Every withdrawal
of the category carries 42.95, so the air factor was restated off them — and
scoring 500 ecoinvent datasets both ways found water use doubled on nearly all
of them, the same cubic metres counted at each end of the process. The
`decline` on water vapour (#154) is a ruling about an accounting convention
rather than a number, and it is filed on the proposed queue because that is the
question the row would have asked had the twin not answered it first.

None of the three queues blocks anything. A factor nobody has ruled on is simply
not in the consensus implementation, and both publishers' numbers are published
regardless.

## Carbon dioxide, and the one rule underneath it

Three carbon dioxides are published, and a reader meeting them for the first time
usually reads them as three kinds of carbon:

| substance | emitted to air | taken from air |
|---|---:|---:|
| `Carbon Dioxide (biogenic)` | 0 | 0 |
| `Carbon Dioxide (fossil)` | +1 | 0 |
| `Carbon Dioxide (land use change)` | +1 | **−1** |

That reading breaks immediately. Land-use-change carbon *is* biological in origin
— it was in trees and in soil organic matter — so how can biogenic carbon be
neutral and this be charged the same as coal?

Because **"biogenic" here is not a claim about where the carbon atom came from.**
The JRC's own sentence has the answer in its plural: *"the biogenic carbon uptakes
**and** emissions were considered neutral"*. It is a statement about a matched
pair. One rule, applied three times:

> A carbon flow is neutral if and only if its counterpart falls inside the study
> period.

A crop grows and is burnt: both halves are in the study, so they cancel and both
are 0. A forest is cleared: that carbon was fixed decades ago and the cleared land
will not take it back, so there is nothing to cancel against and the emission is
charged in full. Fossil carbon is the same case with a longer gap. EF says as much
on the flow itself — land-use-change CO₂ is "treated as fossil CO₂" — and so does
ecoinvent, in almost the same words: it "came from the atmosphere to the stock much
earlier than the scope of any LCA, like fossil carbon".

So the names describe three *residence times*, not three chemistries, and the one
that trips people is `(land use change)`, which names an event where the other two
name an origin.

A fourth substance follows from the same rule and is not EF's:
**`Carbon Dioxide, To Soil Or Biomass Stock`**, carbon entering a long-lived land
pool, credited −1 as `derivation: ruled` on the ecoinvent Centre's number. EF's
carbon model has no row for it — a removal is only expressible there as a resource
from air — so it is adopted deliberately rather than carried in, and the ruling
says whose number it is and what it rests on. The evidence is in
`plans/carbon-accounting.md`.

## One air factor covers every air sub-compartment, where the gas is well mixed

Sulphuryl difluoride is the gas a house is tented with for termites. At the end of
a fumigation the whole charge is vented to the open air, over a suburb, and it
lasts about 36 years up there. Until recently this list said that kilogram was
worth **4,630 kg CO₂-eq released from a rural stack and nothing at all released
over the suburb** — a claim neither of its sources makes.

Nobody decided that. ecoinvent has a flow for two air sub-compartments and EF 3.1
has six, so four of the six had no factor from anyone, and this list published
what an implementation stated for the flow in front of it. ecoinvent's own report
states the opposite rule in §7.3.1:

> The IPCC only supplies values for air emissions, without specifying the
> sub-compartment. The same CF is assigned to an exchange emitted to air for all
> the sub-compartments.

This list does not follow ecoinvent's rule, or SimaPro's, or anybody else's: it
has **one convention of its own** for every context nobody characterised, the
same for every method, in `data/context-carry-rules.json`. Where a substance has
a flow in a context that **no deciding implementation states anything for**,
and the convention names a neighbour for that context, the number this list
already publishes for the substance in that neighbour is carried in, as
`derivation: carried`, with the flow it came from as `source_flow_uuid`. The
rural stack and the urban ground level take unspecified air's number; the other
outdoor strata take the rural stack's; a river takes surface water's;
silvicultural and industrial soil take non-agricultural soil's. Indoor air,
long-term air and water and the ocean are walls nothing crosses, so the
fumigant's indoor factor is **not** carried — that is a different fate model,
and the earlier rule that carried it in three well-mixed categories
([#152](https://github.com/brightway-labs/brightway-flows/issues/152)) was
retired when the convention replaced it. Each rule carries the census numbers
it was decided on; [How a factor is decided](../deciding-factors/blanks.md)
walks through them.

**What it will not do**, each of them counted rather than assumed:

- **Fill a compartment somebody speaks about.** Where an implementation states a
  number the merge withheld — a contested or contradicted question — the
  compartment belongs to a queue, and filling it would answer that question by
  accident. This is why the pass runs last, after every ruling.
- **Choose between numbers.** Where a substance's own air compartments carry more
  than one value, there is no "the" number to carry and the substance is skipped.
- **Publish onto a withdrawn flow.** A deprecated flow is a redirect, not
  somewhere to put a number.

It is also not the inheritance rule [#84](https://github.com/brightway-labs/brightway-flows/issues/84)
removed, and the difference is the same one `restated` turns on: that rule
invented a narrow context's number from a broader one nobody had characterised.
This carries a number between compartments the indicator itself says are one
statement. Where that is not true of a category, the category is not in the file.

## Where the model underneath says something else

Biphenyl is two benzene rings joined together. It is used to make dyes and
plastics, and as a fungicide on citrus fruit — an ordinary industrial chemical.
EF 3.1 says that a kilogram of it emitted into city air causes **0.2 cases of
disease**, so a tonne causes two hundred. Ranked against every substance EF
characterises for non-cancer human toxicity in that compartment — 3,380 of them —
biphenyl comes third, above mercury and just below a rodenticide designed to be
lethal in milligrams.

EF 3.1's three toxicity categories are USEtox 2.1. The JRC's own report says so
and describes the adjustments made on top of it. USEtox 2.1 says that kilogram of
biphenyl causes **0.00000014** cases.

| Emitted to | EF 3.1 | USEtox 2.1 | apart |
|---|---:|---:|---:|
| urban air close to ground | 0.19957 | 0.00000014 | 1,400,000× |
| fresh water | 0.0044065 | 0.00000025 | 17,500× |
| non-agricultural soil | 0.0008987 | 0.0000000015 | 615,000× |
| agricultural soil | 0.00089871 | 0.0000000093 | 96,600× |
| sea water | 0.00015794 | 0.000000017 | 9,200× |

Both columns are in comparative toxic units for humans, which count disease cases
per kilogram emitted.

Neither published implementation can see this. The JRC's says 0.19957 because EF
3.1 says 0.19957; the ecoinvent Centre's says the same, because it transcribed the
same file. Two copies of one file agreeing is not evidence about the file — and
`agreed` would call it agreement, which is the one case where comparing two
implementations gets the answer wrong.

So there is a third queue. `contradicted-factor` holds **8 questions over 110
factors**, from the four substances where USEtox 2.1 is more than a hundredfold
away **in every compartment** — biphenyl, o-phenylphenol, which is biphenyl with a
hydroxyl group added, benfluralin and the 2,4/2,6-toluenediisocyanate mixture. The
narrowest is benfluralin at 133× and the widest biphenyl at 1,381,461×. What the
queue asks is not which of two readings is right but whether the method's number
should be published at all, and until somebody answers, the consensus
implementation publishes nothing for that substance and category — in every
context, not only the six compared, because the number that is out is the
substance's. EF's factor for biphenyl in *indoor* air is 17.194 CTUh, and
withholding the six compared numbers while publishing that one would leave the
worst of them in the list.

**Three things are deliberately not in it.** The metals — all 27 disagree with
USEtox completely, and by design: the JRC report says EF replaced USEtox's metal
factors with ones derived from EU data sources and tabulates each change, copper
falling by 100% and silver rising by 813%. Any substance that disagrees in one
compartment and not another, which is the two models routing an emission
differently rather than disagreeing about the substance.

And **freshwater ecotoxicity, whatever the gap** — which is 34 of the 38 pairs
that were measured. For human toxicity the two publications count the same thing:
cases of disease per kilogram, one stated directly and one as the years of healthy
life those cases cost, so a gap is the method departing from the model it cites.
For a river they do not. The workbook publishes LC-Impact's ecosystem-quality
result, a potentially *disappeared* fraction of species, beside marine and
terrestrial numbers EF has no counterpart for at all; EF's CTUe is a potentially
*affected* fraction. Those are two ideas of what damage to a river means, and the
third constant is fitted between them rather than converting within one. It shows
in the agreement: over the substances not in dispute, 55.3% of the cancer factors
and 32.5% of the non-cancer ones land within 1% of the model, against 20.0% of the
ecotoxicity ones, whose middle half runs from 0.45× to 1.06× where cancer's runs
from 0.9996× to 1.043×. A hundredfold gap measured across that says the two were
never the same number, which is true of every substance and is a finding about
none of them. The rows stay in the evidence file; nothing is asked about them.

**The evidence is a file and the rule is code.**
`data/lcia-underlying-model-factors.json` states what USEtox 2.1 gives, per
substance, category and compartment, converted from LC-Impact's damage unit into
EF's midpoint one by three constants that are measured rather than assumed — where
the two files agree the ratio between them is exactly 11.5, 2.7 and 0.0175906. It
states no verdict. Which categories are compared, and whether a row in one of them
is a contradiction, is decided on each run against the numbers **that build**
states, so a re-transcription that brings the two together publishes the substance
again with nobody editing the file.

And this changes nothing about what the JRC published. EF 3.1 states 0.19957, and
this list goes on publishing 0.19957 under the JRC's name, in the same table and
the same file as before. What changed is that this list no longer says it too.

### A ruling is a file, and it carries its reasoning

`data/lcia-factor-rulings.json` answers a queue item by its own key — the queue,
the substance and the category, not a flow, so it survives a rebuild and goes on
answering when EF publishes the same substance in a fourteenth context.

**Two verdicts, and neither names a source list.** `publish` names the
implementation whose number this list takes; `decline` takes nobody's. A verdict
per implementation — `jrc`, `ecoinvent` — reads well with exactly two of them and
cannot express a third, and every source list that ships factors is one. A factor
published from a ruling carries `derivation: ruled`, distinguishable from
`agreed`, which is the pipeline finding nothing to decide.

A second curated file, `data/lcia-factor-adoptions.json`, answers about
a *substance* rather than about a question, and publishes as `adopted`. It holds
two populations, and they differ in what they record. The pesticides whose only
characterisation is a catch-all's — because ecoinvent's correspondence put them in
one and this list took them out again — deliberately do not record the numbers
they were written about: if ecoinvent revises the bucket's factor, the revised
number is still the bucket's number reaching a named pesticide. The minerals whose
number is the JRC's element factors weighted by the formula do record it, in
`adopted_about`, because the arithmetic was checked against today's element
factors and a revised number is a new question. Every entry carries one or the
other, and the loader refuses one with neither.

Four things the mechanism refuses:

- **A ruling with no comment.** Every one is a statement about somebody else's
  published science, and one with no reasoning is unreviewable. The loader raises.
- **A ruling that publishes an implementation the question is not about**, and a
  `decline` that names one anyway.
- **A ruling with no `ruled_about`.** It records what every implementation stated
  when it was made, and one without it is a ruling the staleness check below could
  never fail — which is the same as not having the check.
- **A ruling written about numbers that have moved.** A row stating something
  else asks again rather than being settled by a decision taken about something
  else. So does a row where an implementation has appeared or gone silent: a third
  implementation changes what "which of these is right" means.

**Eight substances are ruled today, over fourteen rulings, and not one of them
is a verdict on somebody's toxicology.** Kresoxim-methyl is EF's duplication
above: four rulings on the contested-factor queue, publishing the JRC's number
in all 24 rows. `Carbon Dioxide, To Soil Or Biomass Stock` is two rulings on the
proposed queue, publishing the ecoinvent Centre's −1 for a removal EF's carbon
model cannot express, and sulphuryl difluoride is two more, adopting AR6's own
GWP100 for a gas EF never characterised. Sulfur hexafluoride is two contested
rulings taking the method's own table. Coal mine off-gas is one more proposed
adoption, and the clearest case of the four: EF's own rule is that the CF is 1
MJ/MJ for every fossil resource, and EF files this fossil fuel among the
material resources in standard cubic metres, where no indicator reaches it — so
the 36 adopted is that rule times the flow's heating value
([#161](https://github.com/brightway-labs/brightway-flows/issues/161)). The remaining three are the `decline`s,
and each is a compartment or a convention rather than a number: carnallite,
where ecoinvent alone characterises a salt taken from the sea for crustal
depletion; water vapour, where publishing ecoinvent's evaporation factor beside
the JRC's withdrawal-minus-return factors counted every consumed cubic metre
twice; and horticultural peat, where ecoinvent's 9.76 is fuel peat's calorific
value on a flow EF files as a renewable material from the biosphere
([#160](https://github.com/brightway-labs/brightway-flows/issues/160)).
Where a ruling names an implementation it is never because of *whose*
implementation it is — there is no such rule, and a draft of this design that
had one was rewritten to remove it.

**A ruling can also be withdrawn, and one was.** Two vanadium rulings stood
here until 2026-08-18 on the argument that a decimal point moving while five
significant figures stay put — `1.3532e-06` against `1.3532e-05`, and ten more
pairs like it — is a unit slip rather than a model. The digits were real and
the conclusion was wrong. EF 3.1 ships **two** vanadium flows in every context,
`vanadium`
(7440-62-2) and `vanadium (v)`, and states the smaller number for the first and
the larger for the second in the same compartment: the factor of ten is EF's
own speciation factor for vanadium(V), which is exactly why the mantissa
survives it. ecoinvent's implementation was reading the right EF row all along,
and this project was comparing it against the wrong one, because the
correspondence sent ecoinvent's `Vanadium V` rows to the element. With the
routing corrected the two implementations agree to every digit and there is
nothing left to rule
([#108](https://github.com/brightway-labs/brightway-flows/issues/108)). A
comparison between two implementations is only ever as good as the mapping that
decides which two rows are the same question.

**An answered question stays on its page**, as `info` rather than `blocking`, with
the verdict and the reasoning on it. The queue is a work list; a settled row is
the record.

## Read the source before ruling on the transcription

Three greenhouse gases arrived at the contested queue together, all three
apparently the same defect — the JRC's EF 3.1 and ecoinvent's implementation of
the same method stating different numbers for one substance in one category. Two
implementations of one method, disagreeing: a transcription problem, surely, and
whoever transcribed later is presumably right.

They are three different things, and only reading IPCC AR6 itself tells them
apart. This is the worked example for a habit rather than a rule: **a
disagreement between two transcriptions is evidence about the transcriptions
only after you have looked at what they were transcribing.**

| | the JRC says | ecoinvent says | apart |
|---|---:|---:|---:|
| Trichlorofluoromethane (CFC-11) | 6,230 | 6,226 | 0.06% |
| 1,1,1,2-Tetrafluoroethane (HFC-134a) | 1,530 | 1,526 | 0.26% |
| Sulfur hexafluoride | 25,200 | 24,300 | 3.6% |

### AR6 prints the same assessment twice

CFC-11 and HFC-134a are one number each, printed at two precisions in two places
in the same report.

- **Chapter 7, Table 7.15**, *Emission metrics for selected species*, states
  CFC-11's hundred-year global warming potential as `6226 ±2297` and HFC-134a's
  as `1526 ±577`.
- **Table 7.SM.7**, in the chapter's supplementary material, prints `6230` and
  `1530` — the same values at three significant figures. Its own caption calls
  it the full table and Chapter 7's points at it.

The JRC transcribed the supplement; ecoinvent transcribed the chapter. Nobody
made a mistake and nobody is more current. Where both implementations state a
number the merge already resolves it — 0.06% apart is well inside
`FACTOR_TOLERANCE`, so the row is `agreed` and the more precise value is kept —
but in the two air compartments ecoinvent's flow list does not have, aircraft
cruise height and indoor air, the JRC was alone and the rounded number went out
as `sole`. The list published 6,230 for CFC-11 released at cruise height and
6,226 for CFC-11 released anywhere else: one substance, one category, two
numbers, and nothing on the page to say they were the same number.

That is what `data/lcia-rounded-printings.json` fixes, and its whole content is
those four rows (two substances × two climate categories). A refined factor says
`derivation: refined`, which is neither `agreed` nor `sole`, because neither
happened: nobody agreed with anybody, and the value published is not the one the
lone implementation stated.

**It is deliberately not a tolerance rule, and the measurement says why.** On the
2026-08-25 build, 97 (substance, category) groups publish two values that agree
within 2%. Ninety-three of them are freshwater ecotoxicity, where the two values
differ because the *compartments* differ and both numbers are computed and
correct — `Alanycarb` at 134,083 in silvicultural soil and 135,091 in unspecified
soil is a model saying two things about two places. Nothing in the numbers
distinguishes those from a rounding. Only the documents do, so a row is written
by hand and cites the two printings.

One trap for anybody checking the arithmetic: 7.SM.7's CFC-11 row reads `5560`,
not `6230`, because that row uses the unadjusted radiative efficiency of 0.259 W
m⁻² ppb⁻¹. The 12% difference is the tropospheric adjustment, which §7.3.2
assesses as non-zero for CFC-11 and which Table 7.15 includes — 6226/5560 = 1.12.
Both implementations use the adjusted value. The rounding is the only difference
between them.

### Sulfur hexafluoride is two lifetimes, not two printings

The same shape and a different cause, which is why the same fix would have been
wrong.

AR6's Table 7.SM.7 gives SF₆ a lifetime of 3,200 years, a radiative efficiency of
0.567 W m⁻² ppb⁻¹ and GWP-20/100/500 of 18,300 / 25,200 / 34,100. That is the
JRC's number, and it is the published report: the same in the final government
distribution, in the report on ipcc.ch today, and in the authors' machine-readable
supplement, which has not changed since September 2021. The February 2022 errata
amends one row of Table 7.15 — methane — and nothing else in the chapter.

ecoinvent's v3.12 report (§7.3.4, Table 9) moves SF₆ to 18,200 / 24,300 / 29,000
and calls the change negligible. It is not a rounding, and it is not a corrected
printing. Hold AR6's radiative efficiency and replace the 3,200-year lifetime with
one near 1,000 years:

| horizon | AR6 (τ = 3,200 yr) | recomputed at τ ≈ 1,000 yr | ecoinvent 3.12 |
|---|---:|---:|---:|
| GWP-20 | 18,300 | 18,175 | 18,200 |
| GWP-100 | 25,200 | 24,358 | 24,300 |
| GWP-500 | 34,100 | 28,986 | 29,000 |

Three horizons, three significant figures, one substituted input. A shorter
lifetime is what a decade of measurements suggests: WMO's 2022 Ozone Assessment
annex lists SF₆ at the 3,200-year lifetime with an alternative range of 850–1,280
years (Ray et al. 2017; Kovács et al. 2017), and its own metrics — 18,400 /
24,700 / 29,800 — sit about 1.6% above ecoinvent's, which is the ratio of WMO's
radiative efficiency to AR6's.

So this is not two teams reading one table differently. It is ecoinvent updating
an input the method's own publisher has not updated, and the ruling publishes the
JRC's 25,200 — because this list publishes EF 3.1, and EF 3.1's climate change
category *is* that table. Adopting a lifetime AR6 did not adopt would make our EF
3.1 something other than EF 3.1, silently, in the column a practitioner reads as
EF's. The ruling says in as many words that this is not a claim about which
number is better science; ecoinvent's is newer and probably closer, it stays
published under ecoinvent's name, and `ruled_about` ends the ruling if AR7 adopts
it.

### What each case needed

| case | what the two numbers are | what settled it |
|---|---|---|
| CFC-11, HFC-134a | one assessment, two printings | `lcia-rounded-printings.json`, `derivation: refined` |
| Sulfur hexafluoride | two atmospheric lifetimes | a ruling, publishing the method's own table |
| Sulphuryl difluoride | a number only ecoinvent states, AR6's own | a ruling, adopting it ([#151](https://github.com/brightway-labs/brightway-flows/issues/151)) |

Same queue, same symptom, three answers. What made them separable was reading
Table 7.15 beside Table 7.SM.7 and doing the lifetime arithmetic — perhaps two
hours of work, against a rule that would have picked "the newer number" for all
three and been wrong twice.

### Where to check any of this

The documents, and how to get at them, because the retrieval is the annoying
part:

- **AR6 WGI Chapter 7** and its **Supplementary Material** —
  `https://www.ipcc.ch/report/ar6/wg1/downloads/report/IPCC_AR6_WGI_Chapter_07.pdf`
  and `…_Chapter_07_Supplementary_Material.pdf`. Table 7.15 is in the chapter,
  Table 7.SM.7 in the supplement. `www.ipcc.ch` returns HTTP 403 to most
  automated fetchers; `curl` with an ordinary browser user-agent works.
- **The machine-readable supplement**, which is what ecoinvent's report cites for
  the metrics —
  `https://raw.githubusercontent.com/chrisroadmap/ar6/main/data_output/7sm/metrics_supplement_cleaned.csv`.
  One row per gas, columns for lifetime, radiative efficiency and every GWP and
  GTP horizon.
- **The AR6 errata** —
  `https://www.ipcc.ch/site/assets/uploads/2022/02/AR6_WGI_Errata_20220202.pdf`.
  Worth checking before calling any printed value superseded.
- **WMO's 2022 Ozone Assessment annex**, for lifetimes and metrics the IPCC has
  not reassessed —
  `https://csl.noaa.gov/assessments/ozone/2022/downloads/Annex_2022OzoneAssessment.pdf`.
- **ecoinvent's own report**, `LCIA Implementation 3.12.pdf`, shipped with the
  release and cached by `fetch-lcia` beside the workbook. §7.3.1 says where their
  IPCC numbers come from and states the rule that one air factor covers every air
  sub-compartment; §7.3.4 and Table 9 list every climate factor that changed since
  3.11; §15.3.1 and Table 19 do the same for their EF implementation.

## The difference report is a deliverable

Not a backlog. `lcia-differences.json` is a published, citable artifact whose
audience is the implementation teams and anybody comparing implementations,
and **its headline is the agreement**: over the four-list build of 2026-08-29
the published implementations of EF 3.1 agree *exactly* — same float, full
precision — on **36,065 of the 36,744** triples more than one of them states.
98.2%.

| | triples |
|---|---:|
| identical | 36,065 |
| differ, within 2% | 423 |
| differ, 2%–2× | 116 |
| differ, 2×–10× | 46 |
| differ, 10×–100× | 46 |
| differ, over 100× | 36 |
| differ across zero or a sign | 12 |

Every one of those triples is EF 3.1's. Stepwise 2006 has one published
implementation, so nobody is beside it to agree or disagree, and all 9,624 of
its factors are counted below rather than banded.

That 98.2% is what makes the other 1.8% readable as signal rather than noise, and
it is not a number anybody could quote before: until the implementations are on
one flow list, the triples cannot be formed.

**A band is not a verdict.** 679 differences between competent teams are
mostly modelling choices. The 36 over 100× are worth a conversation, not a
correction.

Where only one implementation speaks there is no comparison to record, so those
are counted rather than listed — 293,104 of EF 3.1's, which is a fact about
differently sized flow lists rather than a difference between two readings, and
Stepwise's 9,624 on top of them.

A second report sits beside it: **coverage across sibling contexts**, per
implementation rather than between them. Where does one of them characterise a
substance in one context and skip the context beside it? It is a summary by
compartment and by category and names no flow, deliberately: asked as a list it
is 6,885 rows, and the largest populations are substances with no global-warming
potential, where absence is the right answer and nobody should be asked to fill
it in.

The same page counts this list's own **blanks**: a flow that exists here, whose
substance is characterised in a neighbouring context of the same class — the
soils, the fresh waters, the air strata — and for which no deciding
implementation states anything. Ammonium to a river was one, with ammonium to
surface water characterised next door, until the convention in
`data/context-carry-rules.json` carried the surface-water number in. What the
page counts is what is left after the convention has run: on the 2026-09-01
build 3,336 flows for EF 3.1, 3,093 of them the unconfined aquifer, and 2,591
for Stepwise 2006, 2,126 of them aircraft cruise height — each a context the
convention leaves blank by decision. Whether a blank takes a neighbour's number,
and which, is that convention, written by people from these counts rather than
a rule that reads them — [How a factor is
decided](../deciding-factors/blanks.md) walks through it, and
`tools/count_context_blanks.py` prints the census per pair of contexts, with
what each publisher did where it characterised both.

And it counts the blanks beside a **substance**: an ion with a flow in a
compartment, nothing published on it, and its element characterised in the same
compartment and category — zinc's ion emitted to water, where every ecoinvent
zinc emission lands, beside Stepwise's zinc to water at 133.39
([#197](https://github.com/brightway-labs/brightway-flows/issues/197)).
On the 2026-09-02 build that was 634 pairs over 25 ions for Stepwise 2006 and
168 over 15 for EF 3.1. Whether an ion takes its element's number is a signed
entry in the method's adoptions file, substance by substance: 23 Stepwise ions
were signed that day in `data/lcia-factor-adoptions-stepwise-2006.json`, each
taking its element's published number in the same compartment as `adopted`,
and the 24 pairs left are chromium's, which Stepwise characterises itself.

## Where to find all of this

| Want | Look |
|---|---|
| One flow's factors, all four implementations | The flow's page in the [review application](../operating/review-app.md), or `lcia_characterization_factors` |
| The categories, and how much each implementation fills | `/factors` in the review application |
| Where the implementations disagree | `/factors/differences`, or [`lcia-differences.json`](../using/outputs.md) |
| Where *two named* implementations of one category disagree | `/factors/category/<method>/<version>/<slug>/differences` in the review application |
| Every number, as a file | [`lcia-factors.json.gz`](../using/outputs.md) |
| Questions waiting on a curator, and the ones answered | `/queue/contested-factor`, `/queue/proposed-factor` and `/queue/contradicted-factor` |
| What the model a method is derived from states | `data/lcia-underlying-model-factors.json`, and the queue row itself |
| Why a `ruled` factor is the number it is | `data/lcia-factor-rulings.json`, and the queue row itself |
| What `characterise` found and did not resolve | `/factors/findings/…` |

Two things to know before querying:

- **`elementary_flows.lcia_factor_count` is the JRC's non-zero factors**, and
  keeps that meaning now that there are four implementations, so a query written
  before `characterise` existed still answers what it always answered. The
  per-implementation count is `lcia_flow_factor_counts`, a view over the factors
  themselves so the two cannot drift apart.
- **`lcia_methods` on the flow record is where the JRC's factors come *from***,
  not a place to read a factor. It is the raw ILCD entry, with no category record
  behind it — no unit, no area of protection, no statement of who implemented it.
  It stays because it is a published field with readers.

## What this layer does not do

- **Decide which published implementation is right.** Not this list's question.
  The consensus implementation answers a different one: what should *this list*
  say?
- **Aggregate factors into a score.** This publishes factors. It does not do
  LCIA.
- **Any method but EF 3.1.** ecoinvent's workbook ships 45; the crosswalk covers
  one, in four implementations.
- **Any short-timeframe set**, ours or ecoinvent's.
