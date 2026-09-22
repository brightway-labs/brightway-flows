# A characterisation factor that does not belong to the substance it is on

*Part of [What we have found](index.md), the class where the row is right about the substance and the number on it was computed for something else.*

## The method disagrees with the model it says it implements

EF 3.1's three toxicity categories are USEtox 2.1 — the JRC's report says so, and
describes the small deliberate adjustments made on top. For the two human-health
categories the LC-Impact result workbook is a second copy of the same model, and
comparing the two is what turns "this number looks large" into a measurement:
both count expected cases of disease per kilogram, one directly and one as the
years of healthy life those cases cost, and the constant between them is the
model's own severity factor. That is what makes the comparison trustworthy at all,
and it is why only human toxicity is compared — the workbook's freshwater
ecotoxicity numbers are LC-Impact's own ecosystem-quality result, a potentially
*disappeared* fraction of species where EF's CTUe is a potentially *affected*
fraction, so a ratio between them measures the distance between two models rather
than anything about the substance.

**For four substances — biphenyl, o-phenylphenol, benfluralin and the 2,4/2,6-toluenediisocyanate
mixture — the two are more than a hundredfold apart in every compartment.** The worst is
[biphenyl](https://commonchemistry.cas.org/detail?cas_rn=92-52-4), two benzene
rings joined together, used in dyes, plastics and as a citrus fungicide:

| emitted to | EF 3.1 (CTUh) | USEtox 2.1 | apart |
|---|---:|---:|---:|
| urban air close to ground | 0.19957 | 1.44e-07 | **1,381,000×** |
| non-urban air or high stacks | 0.014939 | 2.48e-08 | 602,000× |
| non-agricultural soil | 0.0008987 | 1.46e-09 | 615,000× |
| agricultural soil | 0.00089871 | 9.30e-09 | 96,600× |
| fresh water | 0.0044065 | 2.51e-07 | 17,600× |
| sea water | 0.00015794 | 1.71e-08 | 9,200× |

Both columns count expected disease cases per kilogram emitted. EF 3.1 is
therefore saying that **a kilogram of biphenyl into city air causes 0.2 cases of
disease** — a tonne would cause two hundred. Ranked against the other 3,380
substances EF characterises for non-cancer human toxicity in that compartment,
biphenyl comes **third**, above mercury, and just below a rodenticide designed to
be lethal in milligrams. Seventh on the same list is 2-phenylphenol, which is
biphenyl with a hydroxyl group added, 170,000× above USEtox. Two close relatives
both anomalous is unlikely to be coincidence.

A substance ranked third of 3,380 dominates any inventory that contains it, and
the error is invisible in a result: it looks like a genuine hotspot
([#107](https://github.com/brightway-labs/brightway-flows/issues/107)).

**What is deliberately *not* in that list**, because a difference is not
automatically a defect:

- **The metals.** All 27 disagree with USEtox — typically 25–75× — and the JRC
  report says why: EF 3.1 replaced USEtox's metal factors with ones derived from EU
  data and tabulates every change. That is a decision, and it is documented.
- **Differences in one compartment but not another.** Those are the two models
  routing an emission differently. A substance only counts here if *every*
  compartment disagrees, which no fate difference explains.
- **Freshwater ecotoxicity, however wide the gap.** 34 further pairs were measured
  and none of them is a finding: the two publications are not counting the same
  thing there, and the constant between them is fitted across two models rather
  than converting within one. Over the substances not in dispute, 55.3% of the
  cancer factors and 32.5% of the non-cancer ones land within 1% of the model,
  against 20.0% of the ecotoxicity ones. A number that is far from a differently
  defined number is not evidence that it is wrong.

## Where a naming error stops being cosmetic

The factor is where a naming error stops being cosmetic. Every class on the
pages before this one changes which substance a row is; this class changes the
number that row contributes to a result. Four shapes turn up on this page, and each
of them was found a different way.

## Two implementations of the same method disagree

EF 3.1 is published by the JRC and re-implemented by others, and the
re-implementations do not always agree. Over the four-list build of 2026-08-29
the published implementations agree exactly — same float, full precision — on
36,065 of the 36,744 triples more than one of them states, and the 679 that
differ are what this class is about. Thirty-six of them are more than 100× apart.
The clearest is EF's duplicated kresoxim-methyl: EF ships the substance twice
under two EC numbers, each row with its own factors, and
the two implementations read different rows — 134.73 against 15,445 for
freshwater ecotoxicity in one compartment. That one carries a ruling, and the
ruling publishes one of the two numbers rather than pronouncing on anybody's
ecotoxicology.

**A claim withdrawn, and why it is kept here.** Until 2026-08-18 this section
reported a second case: ecoinvent's implementation giving `Vanadium V` a
human-toxicity factor **exactly ten times** the JRC's — `1.3532e-05` against
`1.3532e-06`, and ten more pairs, the ratio 10.0000 in every one. The argument
was that a modelling choice about vanadium speciation would not preserve the
mantissa to five significant figures across six compartments, and that
preserving the digits while moving the decimal point is what a unit slip does.

The digits were right and the conclusion was wrong. **EF 3.1 ships two vanadium
flows in every context** — `vanadium`, 7440-62-2, and `vanadium (v)` — and
states the smaller number for the first and the larger for the second, in its
own workbook, in the same compartment. The factor of ten is EF's own speciation
factor for vanadium(V), derived as ten times the element's, which is precisely
why the mantissa survives it. ecoinvent's implementation was reading the right
EF row all along; this project was comparing it against the wrong one, because
the correspondence table sent ecoinvent's `Vanadium V` rows to the element.
With the routing corrected the two agree to every digit, and the two rulings
that had been written about it were withdrawn
([#49](https://github.com/brightway-labs/brightway-flows/issues/49),
[#108](https://github.com/brightway-labs/brightway-flows/issues/108)).

The general lesson is worth more than the finding was: **a comparison between
two implementations is only as good as the mapping that decides which two rows
are the same question.** A ratio computed across a wrong pairing looks exactly
like a finding, and looks more like one the cleaner it is.

## The factor was computed for a different substance

This is [the trichloroethane case](names-and-numbers.md#an-ozone-depleting-solvent-published-as-a-carcinogen)
seen from the factor side: EF's five mislabelled flows carry 1,1,2's toxicity
numbers and 1,1,1's ozone-depletion factor, because the toxicity method was keyed
to the registry number and the ozone method to the name. Where two implementations
are compared, this shows up on its own: putting the nine ecoinvent rows on the
right chemical made **seven factor questions disappear** — twenty-four factors on
which the ecoinvent Centre had been characterising 1,1,1-trichloroethane's rows
against the JRC's numbers for a different chemical.

## The factor belongs to the substance and not to the place it was taken from

The three above are about the substance. This one is right about the substance
and wrong about the compartment, which is harder to see because nothing in the
number looks odd.

`Resource use, minerals and metals` is abiotic depletion measured against
**ultimate reserves**, and the reserve is the continental crust: an element's
crustal concentration times the mass of the crust. The ocean is not in it, and
EF 3.1 says so in its own flow list — it holds `Non-renewable element resources
from water` as a compartment of its own, and characterises nothing in it. Both
independent implementations read it that way: the JRC gives bromine from the
ground 0.00439 and bromine from water nothing, and the ecoinvent Centre gives
`Magnesium, in ground` 2.02 × 10⁻⁹ and every `in water` element flow nothing.

**One flow breaks the pattern, and it is derived rather than stated.**
Carnallite is the Dead Sea salt ecoinvent's Israeli magnesium takes 9.5 kg of
per kilogram of metal, filed from water by ecoinvent and by EF 3.1 alike. The
ecoinvent Centre characterises it at 1.0375 × 10⁻⁵ where the JRC states
nothing — and the number is chlorine's *crustal* factor scaled by carnallite's
chlorine content: KMgCl₃·6H₂O is 106.35 / 277.84 = 38.3% chlorine by mass, and
2.71 × 10⁻⁵ × 0.383 = 1.04 × 10⁻⁵. The v3.12 implementation report (Table 20)
describes the rule: a mineral's factor is composed from its formula. The rule
reads the formula and does not read the compartment, so it fires on a salt
dissolved in the sea — and the same implementation, one row away, gives
chlorine from that same compartment nothing.

**The decision, and it is the exception in these findings.** The factor is declined
in `lcia-factor-rulings.json`, so this list publishes no minerals-and-metals
number for carnallite taken from water, while the ecoinvent Centre's statement
of 1.04 × 10⁻⁵ stays published under their name
([#137](https://github.com/brightway-labs/brightway-flows/issues/137),
[#148](https://github.com/brightway-labs/brightway-flows/issues/148)). A
decline withholds this list's own number and erases nobody's.

**What this project does with the other three.** Nothing, mostly, and
deliberately: this list publishes what implementers state. A factor is not
overruled because it looks wrong; it is recorded, compared against the other
implementation and against the underlying model, and where they contradict each
other the disagreement is published as a question rather than silently
resolved. The four USEtox cases are recorded with both numbers and no verdict.
The carnallite decline is not a counter-example: a factor only one
implementation states is published by nobody until somebody answers for it, and
the ruling is that answer written down rather than left to stand by accident.

**What it cost, by implementation:**

| source | factors involved |
|---|---|
| **EF 3.1 (JRC)** | 4 substances, 110 factors withheld, >100× from the model it implements in every compartment |
| **EF 3.1 (JRC)** | 1 substance published twice, 24 factors over 4 categories where the two implementations read different rows |
| **EF 3.1 (JRC)** | 5 flows carrying another isomer's toxicity factors, and one ozone factor on the wrong substance |
| **ecoinvent's EF 3.1** | 1 flow given a crustal depletion factor for a salt taken from the sea, composed from the mineral's formula |
