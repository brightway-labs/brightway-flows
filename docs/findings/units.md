# Units and the conditions of measurement

*Part of [What we have found](index.md), the class where the unit on a row does not say enough: at what conditions, of what substance, standing for what.*

## A cubic metre of gas is not a quantity

ecoinvent 3.8 ships coal-mine off-gas in `m3`. From 3.9 onwards, the same flow
under the same identifier is in `Sm3` — standard cubic metres. **The substance did
not change; the older export simply did not say at what conditions its cubic metre
was measured.** A gas volume varies by roughly a fifth between 0 °C and 60 °C at
constant pressure, so a number carried across without the qualifier is a number
with an unstated error bar. EF 3.1's copy of the same flow still says `m3`.

## What a unit can fail to say

A number without its unit is not a measurement, and for some quantities the unit
alone is not enough either — a volume of gas needs the temperature and pressure it
was measured at. Source lists are inconsistent about both, in ways that do not
announce themselves.

## A kilogram of ore is not a kilogram of metal

The other way a unit can be insufficient is that it does not say **what is being
weighed**. ecoinvent measures some resources as the mineral that comes out of the
ground; EF 3.1 measures the element the mineral is made of. Both are in kilograms,
so nothing in the units says a conversion is needed, and mapping the two at parity
credits an inventory with a kilogram of metal for every kilogram of ore.

**The correspondence table knows this, and applies it to one pair and not the
other.** GLAD's file has a `ConversionFactor` column and uses it: rows 4856 to
4861 send ecoinvent's three `TiO2, … in ground` flows to EF's elemental `titanium`
with a factor of **0.6**, which is titanium's share of TiO₂ by mass (47.867 /
79.866 = 0.599). Rows 5364 and 5365 send `zirconia, as baddeleyite, in ground` to
elemental `zirconium` with **no factor at all** — and baddeleyite is ZrO₂, of
which zirconium is 91.224 / 123.22 = **0.740** by mass. The same substitution,
the same table, stated once and omitted once.

**ecoinvent's own characterisation numbers show the size of it**, because
ecoinvent states its resource-depletion factor on both weighing bases:

| ecoinvent flow | factor stated | per one kilogram of |
|---|---:|---|
| `Zirconium` | 5.44e-06 | zirconium metal |
| `Zirconia, as baddeleyite` | 4.0273e-06 | baddeleyite |

`4.0273e-06 / 0.74033 = 5.4399e-06`, which is ecoinvent's own zirconium number to
four figures. It is one number stated twice, on two weighing bases, and read as a
35% disagreement by anything that compares them as though both meant the same
kilogram. Gypsum is the same story with water in place of oxygen: ecoinvent gives
`Calcium sulfate` 4.5462e-05 and `Gypsum` 3.5949e-05, and the dry salt is
136.14 / 172.17 = 79.1% of the hydrate's weight — `4.5462e-05 × 0.79073 =
3.5946e-05`.

**What it cost was this project's own**, and is recorded here because the source
fact is what set it up: both ecoinvent flows of each pair were mapped onto EF's
single flow, the model holds one factor per flow and category, so two numbers
arrived where one could be kept and **neither was published**. Calcium sulfate
carried no resource-depletion factor at all, and zirconium's was published as the
JRC's alone although ecoinvent had stated it twice and agreed. The decision is to
publish each substance with the number its own publisher stated about it —
baddeleyite is published as the mineral it is — and, where a conversion genuinely
is the answer, to state it on the mapping row with both units named and apply it
even when both units are `kg`
([#118](https://github.com/brightway-labs/brightway-flows/issues/118)).

## The name says what the kilogram stands for, and the unit does not

A third way a unit can be insufficient: the row is measured in one quantity and
*named* for another. Stepwise 2006 ships uranium as a raw-material resource
three times, and every one of them in kilograms:

| the file ships | in | its `Non-renewable energy` factor |
|---|---|---:|
| `Uranium, 451 GJ per kg` | kg | 4.51 × 10⁵ MJ |
| `Uranium, 560 GJ per kg` | kg | 5.60 × 10⁵ MJ |
| `Uranium, 2291 GJ per kg` | kg | 2.29 × 10⁶ MJ |

All three carry 7440-61-1 and the formula `U`: **one substance, three rows, and
what separates them is an assumption about the fuel cycle** — 451 GJ/kg is the
net once-through figure of the ETH-era data, 560 GJ/kg the gross content, and
2,291 GJ/kg a cycle with reprocessing, which extracts about four times what a
once-through cycle does and is still under 3% of complete fission. The
conversion is stated in the name and nowhere a machine reads, and the method's
own factor is that same number: the row is a kilogram of uranium *standing for*
an amount of energy.

Read as shipped, a kilogram in one row and a kilogram in another differ by a
factor of five in what they mean, and none of them is the kilogram this list
publishes uranium in — the resource is published in megajoules, EF 3.1's basis.
So the three rows are rebased onto MJ, each by the factor **its own name
states** rather than by a single project default, which would restate the 451
row by 24%, and renamed to `Uranium` with the vendor's spelling kept as a
synonym. The correction is written once for the whole SimaPro lineage rather
than per list, because the habit came with ecoinvent 2's flows and arrives in
every list that inherited them
([#147](https://github.com/brightway-labs/brightway-flows/issues/147)).

## The rest of the class, per source list

| source list | what was found | flows |
|---|---|---:|
| **ecoinvent** (all releases) | three land-occupation flows in **m²** where the other 57 in the same compartment are in **m²·a** — an area beside 57 area-times | 3 |
| **ecoinvent 3.8** | coal-mine off-gas in `m3`, relabelled `Sm3` from 3.9 on | 1 |
| **GLAD's mapping** | an ore mass sent to an elemental mass with the conversion stated for titanium (rows 4856–4861) and omitted for zirconium (rows 5364–5365) | 2 pairs |
| **EF 3.1** | the same flow, still `m3` | 1 |
| **BAFU 2026 v1** | the same substance in the same compartment shipped **twice, once in Bq and once in kBq** | 159 pairs |
| **BAFU 2026 v1** | water measured by **mass** where the rest of the list measures water by volume — standing timber, discharges to river and ocean, waste water, polluted water, process water, embodied water | 16 |
| **Stepwise 2006** | one substance shipped three times in kilograms, each name stating a different energy content the kilogram stands for | 3 |

BAFU's water rows are the clearest case of a unit being an accident rather than a
decision. Four `Water` discharge rows are in kilograms while **110 rows of the same
four compartments are in cubic metres**; standing timber is shipped `/kg` in two
compartments and `/m3` in a third, and across the 11,947 datasets of the 2026 v1
archive the volume rows are used 134 times and the two mass rows once each, for
0.0499 kg and 1.9 × 10⁻¹¹ kg. Publishing a substance whose unit depends on which
vendor row happened to create it is what the corrections here prevent; each states
its conversion factor, and for liquid water that factor is the density, 1000 kg/m³
([#78](https://github.com/brightway-labs/brightway-flows/issues/78),
[#67](https://github.com/brightway-labs/brightway-flows/issues/67)).
