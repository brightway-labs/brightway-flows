"""A factor is per unit of a flow, and the two lists do not always agree on the unit.

ecoinvent states the energy content of uranium as a mass and this list publishes it
as an energy:

```
Uranium, Resource → Ground, MJ      Resource use, fossils
  the JRC          1.0        per MJ
  ecoinvent  560,000          per kg
```

Both are right. 560,000 MJ/kg is uranium's energy content, and the two numbers are
one statement about one substance in two units -- which is why the JRC's 1.0 and
ecoinvent's 560,000 are not a disagreement to report but a conversion to perform.

**The multiplier is the merge's, not this pass's.**  A conversion factor is a
statement about a *pair* -- 9.41 is not a fact about brown coal until it is 9.41 MJ
per kg -- and the merge already recorded the ones its correspondence tables state,
on the source reference as `qudt:conversionMultiplier` (#260,
`merge.conversions`).  Nothing here re-derives one: a factor whose units cross and
whose pair states no multiplier gets no factor and a finding, because the
alternative is publishing a mass where an energy was asked for.

Measured over the build: **eight** of the 9,848 ecoinvent 3.12 flows that reach a
consensus flow carry factors and cross a unit, and all eight state a multiplier --
four `kg → MJ` (uranium at 560,000, hard coal at 43.4, brown coal at 9.41, wood at
18.01), one `sm3 → MJ` (natural gas at 36.0) and three `m2 → m2.a` at 1.0, which is
the time-dimension crossing #272 exists to admit.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class UnitCrossing:
    """What a source row and the flow it was merged onto measure, and the factor
    between them where one is stated."""

    source_unit: str
    target_unit: str
    multiplier: float | None = None

    @property
    def crosses(self) -> bool:
        """Whether the two units differ at all.

        Compared as text because both come from the same table: the source
        reference records the unit the row shipped and the flow records the unit
        it publishes, and both are canonical notations by the time they are
        stored.
        """
        return bool(self.source_unit) and bool(self.target_unit) and (
            self.source_unit != self.target_unit
        )

    @property
    def convertible(self) -> bool:
        return not self.crosses or bool(self.multiplier)

    def convert(self, amount: float) -> float:
        """*amount*, per unit of the source flow, as an amount per unit of ours.

        The multiplier says one unit of the source flow is *multiplier* units of
        ours, so a factor per source unit is that factor divided by it: ecoinvent's
        560,000 CTUe per kg of uranium is 1.0 per MJ, which is what the JRC states
        for the same flow -- the check that the direction is the right way round.

        **A stated multiplier is applied whether or not the unit names differ**,
        which is the whole of #118.  A conversion is a statement about a *pair* of
        flows and the merge has already decided the pair needs one; re-deciding
        here, on a string comparison, threw away every conversion between two
        amounts of the same kind.  A kilogram of baddeleyite is 740 grams of
        zirconium and a kilogram of gypsum is 791 grams of the dry salt: both are
        `kg -> kg`, both change what is being measured, and `units.json` implies
        neither.  `ecoinvent-match-overrides.json` says as much in its own
        description -- *changing what is being measured, as an ore mass to an
        elemental mass does* -- and a curator could write the number, have the
        merge record it, and watch the factor pass ignore it.

        :attr:`crosses` is unchanged, because it answers a different question:
        whether publishing this number without a multiplier would put a mass where
        an energy was asked for.  That guard still wants the names.

        :raises ValueError: if the units cross and no multiplier is stated. The
            caller is expected to have asked :attr:`convertible` first; this is the
            guard that keeps a number from being published in a unit nobody asked
            for.
        """
        if self.multiplier:
            return amount / self.multiplier
        if self.crosses:
            raise ValueError(
                f"A factor stated per {self.source_unit} cannot be published per "
                f"{self.target_unit}: the merge recorded no conversion for the "
                "pair."
            )
        return amount
