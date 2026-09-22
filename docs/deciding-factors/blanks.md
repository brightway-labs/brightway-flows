# What do we do when nobody characterised the flow?

*Part of [How a factor is decided](index.md). No deciding implementation states
anything for this flow — and the same substance is characterised in the context
next door. This page is the one convention that says what happens.*

Ammonium discharged to surface water is characterised at 2,493.2 CTUe/kg for
freshwater ecotoxicity, and so is ammonium to unspecified water and to the
unconfined aquifer. Ammonium discharged to a **river** carries no factor, in any
of EF 3.1's 25 categories. Not because anybody decided a river is different:
because the river is a context BAFU brought, EF's flow list has no such
compartment, and this list publishes only what somebody stated
([#159](https://github.com/brightway-labs/brightway-flows/issues/159)).

That triple — ammonium, freshwater ecotoxicity, river — is a **blank**: the flow
exists in the published list, the same category characterises the same substance
in a sibling context, and no deciding implementation states anything for it. A
blank is not a question for a curator; "should ammonium in a river count?" is
not a question about ammonium. It is a question about what our own contexts
mean, and it has one answer for every substance and every method.

Figures are from the build of 1 September 2026, run `20260901T0451332605450000`.

## How many, and where

| | EF 3.1 | Stepwise 2006 |
|---|---:|---:|
| unconfined aquifer | 3,093 | 13 |
| river | 1,029 | 285 |
| lake | 121 | 48 |
| fossil aquifer (`Water` returned there, under Water use) | 210 | — |
| surface water | — | 1,729 |
| silvicultural soil | 170 | 499 |
| industrial soil | 125 | 39 |
| non-agricultural soil | 30 | 1,273 |
| agricultural soil | — | 450 |
| air, per outdoor stratum | 43 at cruise height, 20 urban, 3 each elsewhere | ≈2,130 each for rural stack, urban ground level and cruise height; 15 each elsewhere |
| **total** | **4,859** | **10,849** |

Those are the blanks *before* the convention runs. After it, 3,336 are left for
EF 3.1 — the unconfined aquifer's 3,093, the fossil aquifer's 210 and aircraft
cruise height, each left blank by decision — and 2,591 for Stepwise 2006, of
which 2,126 are cruise height and 450 agricultural soil. The coverage page
counts what is left, not what was filled.

The shapes differ because the publishers' habits differ. EF states almost every
air stratum itself and has no groundwater, no river and no forest soil; its
blanks are in the compartments ecoinvent, BAFU and Stepwise brought. Stepwise's
SimaPro export states one air row per substance and two waters, because SimaPro
applies the *unspecified* sub-compartment's factor to any sub-compartment
without one — the software fills what the export leaves out.

## One convention, ours

`data/context-carry-rules.json` says which neighbour a blank takes its number
from, if any. It is about our contexts, so it names no method; EF 3.1 and
Stepwise 2006 are read through the same file. Each rule is one sentence a
person can read out, with the census numbers it was decided on as its comment.

**Downward — the first donor the substance is published in gives its number:**

| a blank in… | takes the number from… | because |
|---|---|---|
| silvicultural soil, industrial soil | non-agricultural soil, else unspecified soil | EF's non-agricultural soil is its forest-and-built complement of agricultural soil; ecoinvent gave forestry soil that number in 2,747 of 2,765 rows and industrial soil in 123 of 123 |
| non-agricultural soil | unspecified soil | parent to child |
| river, lake | surface water, else unspecified water | a river is surface water — our water vocabulary files it there |
| surface water | unspecified water | parent to child; the aquifer is a sibling, not a donor |
| rural medium stack, urban ground level | unspecified air | the two exposure settings the fate model distinguishes; unspecified air is the number a method states when it does not know which. Never from each other |
| ground‑level rural, low stack rural, high stack rural, high stack urban, medium stack urban | rural medium stack, else unspecified air | a high or medium stack behaves as rural whatever the density; over EF's 40 stated pairs, 90 % agreement |
| low stack urban | urban ground level, else unspecified air | a low release follows its population density; 90 % agreement |

**Upward — a parent takes its children's number only where exactly one child
is published, or every published child states the same number**, the most
precise printing kept. The four class roots — unspecified soil, unspecified
water, unspecified air and unspecified withdrawn water — each have one such
rule, and so does surface water, the one parent below a root, from river and
lake: without it a river-only number could never climb, because unspecified
water reads only its direct children. These run after the downward rules, and
only from numbers an implementation stated.

**Walls — nothing is carried into or out of:** long-term air and long-term
water, where EF states literal zero in every toxicity category and whether that
is a statement or a blanket is
[#158](https://github.com/brightway-labs/brightway-flows/issues/158)'s
question; indoor air, a different fate model; and the ocean, on the emission
side and the withdrawal side alike — chlorobenzene is 1,787.5 CTUe/kg in fresh
water and 1.532 in the sea.

## Across the size windows

Airborne particles are one family cut at seven sizes — PM0.2, PM0.2 – PM2.5,
PM2.5, PM2.5 – PM10, PM10, above PM10, and a size-unstated total — and a
method rarely states a number for all seven. EF 3.1 states PM2.5 and PM10 and
nothing for the coarse band between them; Stepwise 2006 states PM2.5, PM10 and
the total. A blank window is the same kind of blank as a blank compartment,
and `data/particle-size-carry-rules.json` is the same kind of convention:
**a window nobody characterises takes its nearest broader window's stated
number, inside the compartment**, PM0.2 from PM2.5, the coarse band from PM10,
the above-ten fraction from the size-unstated total; and the total takes its
children's number only where every child is characterised and they agree —
stricter than the compartment rule, because under EF the total's only
characterised child is PM10, and "unspecified means PM10" is the reading the
Stepwise ruling below declines. It runs before the compartment
convention, so a number carried across windows in unspecified air is then
spread into the outdoor strata like a stated one.

On the build of 2 September 2026 that gives the coarse band PM10's number under
EF 3.1 in each air compartment — 5.49e-5 in urban ground-level air — and under
Stepwise gives the two windows finer than PM2.5 its 1.0, the coarse band its
0.536, and particles above ten micrometres its 0.157: the number Stepwise
states for dust of no stated size, once the collision on that flow is ruled
(`data/lcia-factor-collision-rulings.json`; Stepwise scored `Particulates` and
`Particulates, unspecified` differently, and the plain row's number is the one
taken). Above ten micrometres under EF stays blank, because nothing above it is
characterised, and that is every publisher's answer. The concern that EF's PM10
number is a bulk figure rather than a coarse-fraction one is recorded beside the
rule on the [limitations page](../reference/limitations.md); a consumer who
shares it can read the `carried` derivation and drop the number.

## What is left blank on purpose

Four populations have no rule, and each absence is a decision the file records:

- **agricultural soil** (450 Stepwise blanks) — the compartment the fate models
  treat specially; a substance a method characterised in unspecified soil but
  not on a field stays blank there.
- **the unconfined aquifer** (3,093 EF blanks) — left blank, beside the 948
  aquifer rows ecoinvent *stated* with the surface-water number, which stand
  because they are statements ([previous page](one-voice.md)). The two sit next
  to each other on purpose, not by accident.
- **the fossil aquifer** (210) — `Water` returned to a confined fossil aquifer
  is not a return to the water cycle the deprivation model credits.
- **aircraft cruise height** (43 EF, 2,126 Stepwise) — left blank, though EF's
  own cruise-height numbers are its rural numbers in 99 % of 22,269 pairs; the
  evidence is on the record for whoever reopens it.

A blank no rule names stays blank and is **counted**, on the coverage page,
never queued: "the taxonomy has no rule for this pair" is not a question a
curator can answer per substance.

## What the convention is not

It is not a gate on the numbers. The first draft of this design carried a number
only where every characterised sibling agreed within 2 %, and the census showed
that reproduces about half of what the one publisher who filled these blanks
actually did: ecoinvent's silvicultural soil is EF's non-agricultural number
whether or not EF's agricultural number agrees with it. A directed rule — this
context takes that one's — is what both ecoinvent and SimaPro do, it fits on a
line, and a single rounded sibling cannot flip it. Robust decisions over perfect
inputs.

It is not the publishers' convention either. What ecoinvent and SimaPro did is
written beside each rule as evidence, and the rows were decided class by class
by the people who run this list, from the census tables. Where the convention
and a publisher part company — the unconfined aquifer — the convention says so.

And it never crosses a substance. `Copper, Ion` taking copper's number is not a
context question and no rule here reaches it; that is a signed entry, or nothing
([previous page](one-voice.md)).

## A blank beside a substance

There is a second kind of blank the convention cannot see. Stepwise 2006
characterises zinc emitted to water at 133.39 kg C2H3Cl-eq per kg for non-cancer
human toxicity, and this list publishes that on `Zinc`. `Zinc(2+)`, the
dissolved ion, has a flow in the very same compartment, and nothing is published
on it — not because Stepwise left a compartment out, but because its export
never names the ion at all. Every ecoinvent zinc emission lands on the ion, in
air and soil as well as water, so under this list's Stepwise implementation a
kilogram of ecoinvent zinc scores nothing
([#197](https://github.com/brightway-labs/brightway-flows/issues/197)).

The census counts these apart, as **blanks beside a substance**: a live flow of
a substance the build records as an ion of an element, no factor on it, nobody
stating one, and the element published in the same context and category. Same
context, deliberately — a blank in the compartment next door is the census
above, and a number crossing a substance and a compartment at once is two
decisions. On the build of 2 September 2026 (run `20260902T0601348875460000`):

| | pairs blank | ion substances |
|---|---:|---:|
| Stepwise 2006 | 634 | 25 |
| EF 3.1 | 168 | 15 |

Stepwise's 634 were 23 metal ions Stepwise never names — arsenic, cadmium, zinc,
lead, mercury, nickel, copper and the rest — plus 24 pairs on the chromium states,
which Stepwise does name and characterises as it chose to. EF's 168 are mostly
`Antimony, Ion` in the cancer categories, `Calcium(2+)`, `Vanadium(3+)` and
`Titanium, ion`.

Nothing here fills one. Whether an ion takes its element's number is a question
about the two substances, answered by a signed `ion-of` entry in the adoptions
file or not at all ([previous page](one-voice.md)). The 23 Stepwise ions were
signed on 2 September 2026, and the same build re-characterised with them leaves
24 pairs: the chromium states, as the publisher left them. The count is on the
coverage page so the next method shaped like Stepwise shows the gap before a
user's validation does.

A carried factor names the flow it was carried from as its `source_flow_uuid`;
the rule is the one for its context, and a context has one rule per direction,
so the pair names it. The convention replaced an earlier rule that carried one
air factor across every air sub-compartment in three well-mixed categories
([#152](https://github.com/brightway-labs/brightway-flows/issues/152)):
of the 35 factors that rule carried, 18 return through the air rules and 17 —
the indoor and long-term ones — are withdrawn by the walls.

## How to change a rule

Edit the file. A rule is a recipient, an ordered list of donors and a comment
with the numbers from `tools/count_context_blanks.py`; the loader refuses a
context the vocabulary does not have, a display name that is not the IRI's, a
wall named as donor or recipient, a recipient with two rules, or a missing
comment. `tests/test_lcia_context_carry.py` states the decisions above as data,
so a change to one is a change to a test — which is the point: the convention is
reviewable in a diff.

## Where it is written down

- `data/context-carry-rules.json` — the rules, the walls, and the reasoning.
- `/factors/coverage`, under the consensus implementation — how many blanks each
  context holds on this build, and how many pairs each ion leaves blank beside
  its element.
- `tools/count_context_blanks.py` — the census per pair of contexts: blanks,
  agreement where both are published, and which neighbour ecoinvent's restated
  numbers match; then the blanks beside each ion's element.
- `plans/lcia-consensus-decisions.md` §2 and §5 — the measurements and the
  design.
