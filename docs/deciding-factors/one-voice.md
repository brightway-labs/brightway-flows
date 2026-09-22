# What do we do when only one transcription speaks?

*Part of [How a factor is decided](index.md). The method's own publisher is
silent about a flow, and one transcription states a number for it — this page
is whether that number becomes ours.*

EF 3.1's flow list has no silvicultural soil, no industrial soil, no
groundwater, and no `Copper, Ion`. ecoinvent's has all of them, and the
ecoinvent Centre's implementation of EF 3.1 characterises them: metaldehyde in
forestry soil, chlorobenzene in groundwater, copper's ion in surface water. So
this list holds thousands of flows for which exactly one deciding implementation
speaks, and it is not the method's own.

That is a different situation from the JRC speaking alone. The reference's own
number for a flow is the method; adopting it is not a decision, and 296,719 of
EF's consensus factors are `sole` for that reason. A transcription's number for
a flow the method's publisher never characterised is a claim about what the
method *would* say, and adopting it is.

Figures are from the build of 1 September 2026, run `20260901T0451332605450000`.

## The number this list already carries

Metaldehyde is the poison in slug pellets. EF characterises it in agricultural
soil at 5.6369 CTUe/kg for freshwater ecotoxicity, in non-agricultural soil at
5.637, in unspecified soil at 5.6369. ecoinvent adds a row for forestry soil,
which resolves to our silvicultural context, and states 5.637 there.

Nobody is proposing new science. ecoinvent has carried EF's own number onto a
compartment EF's list cannot express, and this list can see that, because it
already publishes the same substance at that number in the category next door.
Where that is so — the same substance, the same category, another context,
within the same 2 % that separates a rounding from a disagreement — the factor is
published as **`restated`**. The amount is always the transcription's own stated
row; nothing is inherited or interpolated, and the derivation names the fact that
made it publishable.

That is the whole of the 3,818 restated factors: roughly 2,750 in silvicultural
soil, 950 in the unconfined aquifer and 120 in industrial soil. The census of the
blanks ([next page](blanks.md)) says which neighbour each one matches, and the
answer is consistent enough to be a rule: ecoinvent gave forestry and industrial
soil EF's *non-agricultural* number in 2,747 of 2,765 silvicultural rows and 123
of 123 industrial, and groundwater EF's *surface water* number in 948 of 948.

## The population a curator accepted

Sixty-two named pesticides reach this list under their own names, because it
declines the catch-all mapping ecoinvent's correspondence table gives them —
`Insecticides, unspecified` and its siblings
([#76](https://github.com/brightway-labs/brightway-flows/issues/76)).
ecoinvent's implementation characterises them as the bucket, so each proposes
the bucket's numbers on a flow the JRC never characterised. A curator accepted
that as a population: the fact that makes the numbers acceptable is a fact about
*these substances*, written down once in
`data/lcia-factor-adoptions.json` rather than ruled sixty-two times.
Twenty-three minerals — gypsum, sodium chloride, borax — are the file's second
population, where ecoinvent's number is the JRC's element factors weighted by
the mineral's formula and the arithmetic was checked
([#155](https://github.com/brightway-labs/brightway-flows/issues/155)).
Those 899 factors carry `derivation: adopted`, and the 435 signed on 2026-09-01 -- the ions, the two conjugates and the land classes below -- carry the same word.

An entry is deliberately *not* pinned to a number where its reason is a relationship: a
revised bucket factor is still the bucket's factor reaching a named pesticide.
The minerals' entries are pinned, because their reason is the arithmetic.

## The number another substance carries

`Copper, Ion` is a substance this list has only because ecoinvent shipped it.
The JRC characterises copper, not its ion; ecoinvent gives the ion copper's own
numbers, 46.47592828149169 CTUe/kg in surface water; and that number stands
published on copper. Until 2026-09-01 the ion's factor was published as
`restated` on that strength alone: some flow of the category carried the very
same digits
([#145](https://github.com/brightway-labs/brightway-flows/issues/145)).

The evidence that rule read was the amount, and the amount is the same shape
whether the donor is copper for its ion or lindane for its manufacturing
contaminants. EF characterises α‑, β‑ and δ‑hexachlorocyclohexane for
freshwater ecotoxicity and holds them 21–34× away from lindane; for non-cancer
human toxicity it characterises only lindane. ecoinvent filled the gap with
lindane's number, 0.00019937 CTUh/kg from unspecified air, and this list
published it on all three isomers under their own names — because the digits
matched
([#131](https://github.com/brightway-labs/brightway-flows/issues/131)).
Nobody had decided that. On the build of 1 September, **311 factors over 75
substances** reached their flow by matching another substance's number: 120 an
ion taking its element's, 108 a stereo-relative taking its parent's, 14 a named
substance taking a catch-all's, 69 with no recorded relationship at all.

The rule is gone
([#156](https://github.com/brightway-labs/brightway-flows/issues/156)).
**No number crosses from one substance to another without a signature**,
however obvious the pair, and the signatures are `data/lcia-factor-adoptions.json`:
one entry per recipient, naming the donor, the relationship in one word — `ion-of`,
`salt-of`, `conjugate-of`, `catch-all`, `land-family`, `formula-weighted`,
`substitute` — the categories covered, and a verdict, `adopt` or `decline`, with
a comment. Copper's ion is an `ion-of` entry, signed; so are nine other ions, the
acrylate anion and flupyrsulfuron-methyl's sodium salt with the mass correction
stated, and 53 land classes taking their family's number. The three
hexachlorocyclohexanes, tetrachlorvinphos, lambda-cyhalothrin and (R)-mecoprop
are `substitute` entries with the verdict **decline** and #131's table as the
reasoning, and 2,4-D ester, dimethyl hexynediol and fenpropimorph are declined
`catch-all` entries; their rows stay on the proposed-factor page answered rather
than asking. `tools/count_identity_crossings.py` lists every candidate pair with
the relationship the build records, so an entry is written from evidence rather
than from memory — and an entry never overwrites a value: it answers a row the
reference is silent about, and nothing else.

## The number nobody stated for the recipient

Everything above answers a row a transcription stated. Stepwise 2006 has one
implementation, and its export names no ion of any metal but chromium. Zinc
emitted to water is characterised at 133.39 kg C2H3Cl-eq per kg for non-cancer
human toxicity, published on `Zinc`; `Zinc(2+)`, the dissolved ion, has a flow in
the same compartment and nobody states anything for it, so it is never asked
about. Every ecoinvent zinc emission lands on the ion — the air and soil rows
too, because ecoinvent's own correspondence table sends its metal to EF's
`Zinc II` — so under this list's Stepwise implementation a kilogram of ecoinvent
zinc scored nothing
([#197](https://github.com/brightway-labs/brightway-flows/issues/197)).

The signature for that case says something slightly different: not "publish the
transcription's number" but "this substance takes its donor's *published*
number, context for context". An entry in the Stepwise adoptions file,
`data/lcia-factor-adoptions-stepwise-2006.json`, carries `number_from: donor`,
and the pass that reads it copies zinc's water number onto the ion's water flow,
zinc's air number onto its air flow, and so on, as `adopted`, each naming the
zinc flow it took the number from. It runs before the convention, so the ion's
river, lake and forestry-soil flows then take the number from the ion's own rows
the way zinc's do. On the build of 2 September 2026 that is 299 adopted factors
over 23 ions of 16 elements, and the convention carries a further 338 from them.

What it refuses is the point. A recipient the method's own publisher
characterised anywhere is refused whole: Stepwise names `Chromium III` and gives
it no ecotoxicity number while giving the metal one, and that silence is the
publisher's decision, so no entry is written for the chromium states and the
pass would refuse one. It never overwrites a published triple, never copies a
number that was itself carried or adopted, and refuses a pair whose units
differ. Stepwise's model does not tell a metal's oxidation states apart, so the
23 entries include EF 3.1's own speciated flows — `Antimony(3+)` and
`Antimony(5+)`, `Arsenic(3+)` and `Arsenic(5+)`, `Copper(2+)`, `Iron(2+)` and
`Iron(3+)` — which no inventory merged today emits.

## What is left is a question

A transcription's number that none of the above vouches for is a
`proposed-factor`: nothing is published, and the row asks. On this build the
queue is 64 questions over 158 factors, 48 of them answered on the record -- the declines above and the earlier rulings -- and 16 open: ten rocks
EF's flow list never contained, each with one ecoinvent number for mineral
resource use
([#132](https://github.com/brightway-labs/brightway-flows/issues/132)),
kresoxim-methyl in silvicultural soil, where ecoinvent states 53,540 against
a soil number this list publishes as 134.73, and fenoxycarb's two rows, which are
[#130](https://github.com/brightway-labs/brightway-flows/issues/130)'s twin
substance and wait for the merge rather than for a signature.

For a number that is genuinely one publisher's own, with no donor and no
neighbour, the standard is an attributable source: sulphuryl difluoride's
global warming potential was published because IPCC AR6 states it, and a rock's
depletion factor will be published when somebody can say where it came from —
or declined on the record.

## Where it is written down

- `lcia_characterization_factors.derivation` — `sole`, `restated`, `adopted`.
- `/queue/proposed-factor` — the open questions and the ruled ones.
- `data/lcia-factor-adoptions.json` — the two populations, and the one
  substance it names as refused (fenpropimorph, whose numbers are mostly the
  bucket's and partly ecoinvent's own).
- `data/lcia-factor-adoptions-stepwise-2006.json` — the 23 Stepwise ions taking
  their element's published number where nobody stated one.
- `data/lcia-factor-rulings.json` — proposed rows a curator answered one at a
  time.
