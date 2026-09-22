# What do we do when the formula cannot be drawn?

*Part of [How a flow is decided](index.md), and the one case at that stage where a formula and a structure cannot both be right.*

Nickel(II) acetate is a nickel atom carrying a charge of two, with two acetate
ions beside it. That is `C4H6NiO4`.

Here is how CAS registers it, under 373-02-4:

```
  name                Nickel acetate
  molecular formula   C2H4O2 · 1/2 Ni
  molecular mass      178.80
```

That reads as *acetic acid, with half a nickel for each acetic acid* — which is
the same thing said the other way round. Two acetic acids to one nickel. It is
the long-standing way chemical registries write a salt down: name the acid,
because the acid is the part with a name, then say how much metal goes with it
as a ratio. The mass confirms it: 178.80 is two acetic acids plus one nickel.

The composition is correct. The trouble starts when it is turned into a drawing.

## Half an atom cannot be drawn

The two standard ways of writing a structure down — SMILES and InChI — describe
one specific assembly of atoms. Neither has any way to write "half a nickel". So
when the registry converts its own formula into a structure, the fraction has
nowhere to go, and the ratio quietly becomes one-to-one:

```
  the formula      C2H4O2 · 1/2 Ni     two acetic acids to one nickel
  the SMILES       [Ni].O=C(O)C        one acetic acid  to one nickel
  the InChI        InChI=1S/C2H4O2.Ni/c1-2(3)4;/h1H3,(H,3,4);
  the InChIKey     XMOKRCSXICGIDD-UHFFFAOYSA-N
```

That last key is not a mistake anybody made. It is the registry's own, computed
from the registry's own structure, and it describes the right substance with its
ratio rounded off. PubChem holds the same key, having taken it from the same
place, and publishes the rounded formula `C2H4NiO2` — the `1/2` having been lost
one step earlier.

This is not one substance's quirk. **274 of the registry records this project
has fetched carry a ratio that a structure cannot hold** — 77 written as a
fraction and 197 as a whole-number multiplier:

```
  62-54-4     Calcium acetate           C2H4O2 · 1/2 Ca
  553-72-0    Zinc benzoate             C7H6O2 · 1/2 Zn
  14644-61-2  Zirconium sulfate         H2O4S  · 1/2 Zr
  14807-96-6  Talc                      H2O3Si · 3/4 Mg
  7758-16-9   Disodium pyrophosphate    H4O7P2 · 2 Na
  1113-38-8   Ammonium oxalate          C2H2O4 · 2 H3N
```

Every one of those looks, to a program comparing structures, like the registry
describing something other than the salt. It is describing the salt, in a
notation that lost the ratio on the way out.

## What this project does about it

**Ask what the substance is made of, not what it looks like.** The formula is
the field where the ratio survives, so the formula is the field to compare.

This is the third way one object ends up publishing two identities, after the
flat key beside a specific one and the acid beside its ion. The rule for a
charge difference is [An acid and its ion are two substances, not two
shapes](structures.md#an-acid-and-its-ion-are-two-substances-not-two-shapes),
and it compares keys directly, because there the two keys share a skeleton.
Here they do not: rounding the ratio off changes the skeleton as well as the charge, so
that rule sees two unrelated structures and correctly declines. Comparing
compositions is what reaches the cases it cannot.

Comparing has to allow for two things that are not disagreements:

- **The ratio is multiplied out first.** `C2H4O2 · 1/2 Ni` becomes `C4H8NiO4`
  before anything is compared, because half a nickel alongside one acetic acid
  is one nickel alongside two.
- **Hydrogen is ignored.** A salt is its acid with the acidic hydrogens gone,
  and the registry names the acid: `C4H8NiO4` for the registry, `C4H6NiO4` for
  the salt. Ignore hydrogen and both are four carbons, four oxygens and one
  nickel — one substance, described from two ends.

Where a substance publishes two formulas and the registry backs one of them, the
other is withdrawn, and so is every structure that came with it. That is step 19
of [the chain](../reference/harmonisation-steps.md).

## The same test, pointing the other way

It would be easy to read the above as "the salt's own chemistry wins over the
registry", and that reading is wrong. The test is about composition, and it cuts
both ways.

`1,4-diazabicyclooctane` — DABCO — is a small cage of two nitrogens bridged
three ways, `C6H12N2`. Its name is properly written
`1,4-diazabicyclo[2.2.2]octane`; the `[2.2.2]` says how long the three bridges
are, and without it the name does not describe a molecule. The name-reading
software does not refuse it. It reads `bicyclo` as "two of", and returns a
completely different molecule, `C14H28N2`.

The registry says `C6H12N2` for 280-57-9, and so do ChEBI and PubChem. So the
same comparison that keeps the name-derived answer for nickel acetate withdraws
it for DABCO. **Nothing is decided on which part of the pipeline produced a
value** — only on whether the registry's stated composition backs it.

## What is deliberately left alone

- **A substance publishing one formula is never touched**, even where the
  registry disagrees with it. A substance with no formula at all is worse than
  one whose formula is disputed, and the dispute is already reported.
- **Where the registry agrees with nothing the substance publishes, nothing is
  withdrawn.** That disagreement is real and belongs to a curator. On the build
  of 17 August 2026 there were ten such substances, mostly borates and
  vanadates whose published formulas disagree among themselves as well.
- **Ignoring hydrogen is allowed here and nowhere else.** It makes ethane and
  ethene indistinguishable, which would be intolerable if this were deciding
  whether two substances are the same. It is not: it asks only whether a
  *second* value on one record contradicts what the registry registered.
