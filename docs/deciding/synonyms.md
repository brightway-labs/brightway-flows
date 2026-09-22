# What do we do with a name that belongs to something else?

*Part of [How a flow is decided](index.md), at the stage where the published name and the synonyms beside it are settled.*

## The cross-object synonym strip: a name belongs to one substance

Two cleanup passes remove synonyms that create false equivalences:

- Any synonym matching the *preferred* name of a **different** flow object is
  removed. A substance cannot legitimately be called by another substance's
  preferred name. Flows of the same substance in different contexts share a
  preferred name and never trigger this.
- Element symbols (`Rn`, `[Rn]`) belong exclusively to the pure element. When
  they appear on isotopes or compounds they are wrong. The pure element is
  identified by having exactly one molecular formula value equal to the bare
  symbol — isotopes carry extra values like `["Rn", "[222Rn]"]` and so are not
  mistaken for it.

  | Flow object | Preferred name | Synonyms before | After |
  |---|---|---|---|
  | `fo-37b9…` | Radon | `Rn`, `[Rn]`, `niton`, … | unchanged — this is the element |
  | `fo-3320…` | Radon-222 | `(222)Rn`, `[Rn]`, `Alphatron`, … | `[Rn]` removed |

Both run before consensus matching, so the scoring step sees cleaned label sets.

## The catalogue strip: a product code is not a name

Common Chemistry and ChEBI file every string anyone has attached to a CAS
number, and nothing in either payload separates chemistry from commerce. Along
with `octadecanoic acid`, stearic acid arrives carrying `F 1000`, `S 300`,
`Prifrac 2981`, `Radiacid 0152` and `NSC 147337`. **18.3% of published
alternative labels — 368,720 of 2,012,182 — are one of three shapes:**

| Shape | Examples | Rows |
|---|---|---|
| Supplier grade | `S 100`, `A 1`, `F 1000`, `P-30` | 243,048 |
| Trade name and product number | `Garlon 480`, `Polytal 4641`, `Dow Corning 777` | 80,357 |
| Database accession | `NSC 147337`, `AKOS000118800`, `C.I. 77120`, `UN 3077` | 45,315 |

These are not merely noise. A grade code is shared between unrelated products:
a merge once resolved Propylene Carbonate to **Talc**, because both carried a
`K 3` alternative label and a label index cannot weigh what it cannot read.

Removing them costs little. The filter takes 368,720 labels and leaves **104**
flows with none at all, out of 89,045 carrying any.

### Why shape rather than agreement

The obvious alternative is the rule used everywhere else on this page: publish
only what two sources agree on. It was measured against a full build and
rejected.

| Rule | Alternative labels kept | Flows left with none |
|---|---|---|
| Publish everything a source supplies | 2,012,182 | 0 |
| Require Common Chemistry **and** ChEBI | 127,358 (6.3%) | — |
| Require any 2 of Common Chemistry / ChEBI / PubChem | 160,243 (8.0%) | 31,002 |
| Shape filter (what runs) | 1,643,462 (81.7%) | 104 |

Agreement fails here for a reason specific to names. Common Chemistry and ChEBI
agree on **5.8%** of published strings — not because the other 94% are wrong,
but because one ships CAS-index inversions and trade names while the other
ships IUPAC and biochemical shorthand. The rule therefore removes `oxidane`,
`trans-2,4-hexadienal`, `H(2)O` and Common Chemistry's own primary name for a
substance alongside the grade codes, and would add 2,598 back.

Consensus measures whether two registries share a vocabulary. It does not
measure whether a string is a name. For identity claims — which substance, which
CAS — agreement is the right instrument and is used. For *labels*, shape is.

### When the shape test is wrong

It is a heuristic, and there are two ways to overrule it.

**A whole convention belongs in the patterns**, in
`transformers/strip_catalogue_altlabels.py`. Two are already exempt:

- Refrigerant, halocarbon and halon designations — `HFC-134a`, `Halon 1211`,
  `Fluorocarbon 113`, `R-600a`. EF 3.1 identifies 55 flows by designation
  alone, with no CAS, no formula and no structure
  ([#19](https://github.com/brightway-labs/brightway-flows/issues/19));
  deleting these would be a data loss. `R-600a` with a hyphen is isobutane as a
  refrigerant, so `R` is admitted only hyphenated — `R 300` with a space is a
  grade of stearic acid.
- Congener numbering — `PCB 118`, `BDE 47`. None appear in the current build;
  the exemption is pre-emptive.

**A single string belongs in the keep list**, `altlabel-keep-list.json`, which
is data rather than code:

```json
{
  "keep": [
    {"value": "Some Label 400", "comment": "why this is a name and not a grade"}
  ]
}
```

Matching is case- and whitespace-insensitive, an entry applies to every flow
carrying that label, and `comment` is mandatory — an entry without one is
ignored and logged, because an unexplained exemption is one nobody can
re-evaluate later. The file ships empty: when it was written, no string the
filter removes was any flow object's preferred name, so nothing was known to
need overruling.

The strip step also names every value it removes in its change-log comment, so
`/changes` filtered to `strip_catalogue_altlabels` is where you find a label
worth keeping.

Some cases neither mechanism can fix, and the patterns are deliberately shy
about them. The trade-name test requires a three-digit product number, so
`Tween 80` survives — it is a brand, but so is the *form* of `Pigment Yellow
74` and `Vitamin B12`, and no shape test tells those apart.

## When the evidence is not in the label

`Silicon Dioxide` published 4,003 synonyms after the shape filter had taken 38%
of what Common Chemistry supplied, and they were almost entirely commercial:
173 beginning `Snowtex`, 126 `Aerosil`, 75 `Nipsil`
([#27](https://github.com/brightway-labs/brightway-flows/issues/27)).
`Snowtex 30` is shorter than the trade-name pattern requires and matches no
registry prefix, and no prefix list will ever hold it — brand tokens are
open-ended.

The signal is repetition on one object. 173 labels sharing a leading token is a
supplier catalogue; a chemical vocabulary does not behave that way. Two
formulations of the gate were measured against the build and failed:

| Gate | Why it fails |
|---|---|
| Leading token is a chemical word | `Methyl Violet 10B`, `Pigment Blue 15:3` lead with chemical words and are product codes |
| Token appears on few other objects | `Nissan` spans 56 objects; `R` (103), `S` (74), `A` (73) are grade prefixes, not vocabulary |

What separates them is what the number is doing. In a name the digits are bound
into the chemistry — `Sodium 2-mercaptopyridine 1-oxide`. In a product code they
dangle — `Snowtex 30`. A hyphen between *digits* is a catalogue range
(`Cataloid S 1-50`), so only adjacency to lower-case chemistry counts.

The rule runs only above 100 alternative labels. The median object carries 9
and the mean 17, while the 96 above 100 hold 23.9% of every synonym in the
list — so the gate buys the concentrated part of the problem without exposing
`Tween 80` to a rule it would fail. It removes 8,643 labels from 69 objects.

Where shape genuinely cannot decide, a register does. `Ponceau 4R` is a name
and `Acetoquinone Blue R` is a product, and the strings are the same shape;
ChEBI is consulted at run time and the public part of the Colour Index ships as
data. This is agreement used as an *exemption* — it may only keep a label,
never publish one — which is what makes it safe here after being rejected as
the primary filter above. It rescues 13 labels, `Ponceau 4R`, `Tween 20`,
`Polysorbate 20`, `Laureth 4` and `Laureth 9` among them.

The documented gap is `Methyl Violet 10B`. It appears in no open register —
not ChEBI, not Wikidata, and Colour Index International itself is
subscription-only — so it survives on the size gate alone, crystal violet
carrying 96 labels against a threshold of 100. The keep list is the mechanism
for a string in that position.
