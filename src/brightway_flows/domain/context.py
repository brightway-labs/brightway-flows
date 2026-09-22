"""Canonical consensus flow context model.

The enums, the ``check_*`` validators, and ``to_list``/``from_list`` form the
shared context definition used across Brightway tooling, so treat them as a
stable contract rather than a local implementation detail.  Serialisation
helpers specific to brightway-flows belong in ``domain.context_registry``.
"""

import functools
import itertools
from dataclasses import dataclass
from enum import StrEnum


class Dimension(StrEnum):
    ENVIRONMENTAL = "Environmental"
    # * `Resource` only includes accounting fictions, like elemental content or `energy,
    # geothermal, converted` - actual raw materials should be in "Ground"
    RESOURCE = "Resource"
    ECONOMIC = "Economic"
    SOCIAL = "Social"
    LAND_USE = "Land Use"
    # Special factors for things like resource circularity
    INVENTORY = "Inventory Indicator"
    # EPDs, etc.
    IMPACT = "Impact Assessment Score"


class Media(StrEnum):
    """The medium in which the the elementary flow expresses its effects.

    Notes:
        * `Water` can include groundwater
        * `Ground` includes soil and minerals deeper in the lithosphere
        * `Product` means that a chemical is applied to a product, like toys, food, or construction materials.
        * The `Other` category can include non-environmental flows, such as economic or social indicators, or elementary flows like land use or transformation
    """

    AIR = "Air"
    WATER = "Water"
    GROUND = "Ground"
    BIOTIC = "Biotic"
    PRODUCT = "Product"
    OTHER = "Other"


class VerticalStrata(StrEnum):
    """Vertical strata for air emissions.

    Notes:
    * Vertical strata is not required for indoor air emissions.
    * `UNKNOWN` represents unspecified outdoor air (no strata information available).
    * `Space` could be added in the future.
    * `LONG_TERM` is not a stratum. It rides on this enum because air's strata
      value is the one mandatory, mutually-exclusive discriminator the media
      already has, which lets long-term air exist without adding a temporal
      field to `Context`. It serialises to ``["Environmental", "Air",
      "Long-term"]`` -- exactly what a real temporal field would produce for
      unspecified-strata long-term air -- so the shortcut can be replaced later
      without invalidating a single stored context or IRI. The cost is that it
      cannot be combined with a real stratum or a population density, so a
      source that knows both (ecoinvent's `low population density, long-term`)
      has to give one up.
    """

    UNKNOWN = "Unknown"
    GROUND_LEVEL = "Ground level"
    LOW_STACK = "Low stack, <25 meters"
    MEDIUM_STACK = "Medium stack, <150 meters"
    HIGH_STACK = "High stack, >150 meters"
    AIRCRAFT = "Aircraft cruise height"
    LONG_TERM = "Long-term"


class LandUseClass(StrEnum):
    OCCUPATION = "Occupation"
    TRANSFORMATION = "Transformation"


class IndoorAirClass(StrEnum):
    """Differentiation of indoor air emission classes. Based on GLAM indoor air emissions."""

    UNKNOWN = "Unknown"
    NEAR_PERSON = "Near-person"
    RESIDENTIAL = "Residential"
    INDUSTRIAL = "Industrial"


class Geography(StrEnum):
    """Only applies to the `Ground` dimension."""

    # Human dominated
    UNKNOWN = "Unknown"
    INDUSTRIAL = "Industrial"
    RESIDENTIAL = "Residential"
    COMMERCIAL = "Commercial"
    AGRICULTURAL = "Agricultural"
    SILVICULTURAL = "Silvicultural"
    # Natural/terrestrial
    WETLAND = "Wetland"
    BARREN = "Barren land"
    SNOW_AND_ICE = "Snow and Ice"
    GRASSLAND = "Grassland"
    SHURBLAND = "Shrubland"
    FOREST = "Forest"
    # Deprecated on arrival. `Non-agricultural` is not a land cover class; it is
    # EF 3.1's complement of `Emissions to agricultural soil`, and it exists here
    # only so EF's `Emissions to non-agricultural soil` stops collapsing onto
    # Ground -> Unknown together with `Emissions to soil, unspecified`, which
    # discards one of the two CF sets. Do not map new
    # sources onto it: prefer a real land cover class, or UNKNOWN.
    NON_AGRICULTURAL = "Non-agricultural"


class WaterBody(StrEnum):
    """The water body an emission went to, or a withdrawal was taken from.

    Used on both the `Environmental` and `Resource` dimensions, and required on
    each -- see :func:`check_water_body`, which also names the three values a
    withdrawal cannot take.

    `LONG_TERM` is not a water body; it is the water-side counterpart of
    :attr:`VerticalStrata.LONG_TERM`, and carries the same trade-off.
    """

    UNKNOWN = "Unknown"
    SURFACE_WATER = "Surface water"
    LAKE = "Lake"
    RIVER = "River"
    OCEAN = "Ocean"
    UNCONFINED_AQUIFER = "Unconfined aquifer"
    CONFINED_AQUIFER = "Confined aquifer with fossil groundwater"
    WWTP = "Waste-water treatment plant"
    SECONDARY_TREATMENT = "Secondary water treatment"
    LONG_TERM = "Long-term"


class PopulationDensity(StrEnum):
    UNKNOWN = "Unknown"
    URBAN = "Urban (>1000 people/square mile)"
    RURAL = "Rural (<1000 people/square mile)"


@dataclass
class Context:
    dimension: Dimension
    media: Media | None = None
    strata: VerticalStrata | None = None
    geography: Geography | None = None
    water_body: WaterBody | None = None
    population_density: PopulationDensity | None = None
    indoor: IndoorAirClass | None = None
    land_use: LandUseClass | None = None

    def __post_init__(self) -> None:
        check_media(self)
        check_strata(self)
        check_indoor(self)
        check_population_density(self)
        check_water_body(self)
        check_geography(self)
        check_resources(self)
        check_land_use(self)

    @classmethod
    @functools.cache
    def _build_from_list_mapping(cls) -> "dict[tuple[str, ...], Context]":
        mapping: dict[tuple[str, ...], Context] = {}
        _none = [None]
        for combo in itertools.product(
            list(Dimension),
            list(Media) + _none,
            list(VerticalStrata) + _none,
            list(Geography) + _none,
            list(WaterBody) + _none,
            list(PopulationDensity) + _none,
            list(IndoorAirClass) + _none,
            list(LandUseClass) + _none,
        ):
            try:
                ctx = cls(
                    dimension=combo[0],
                    media=combo[1],
                    strata=combo[2],
                    geography=combo[3],
                    water_body=combo[4],
                    population_density=combo[5],
                    indoor=combo[6],
                    land_use=combo[7],
                )
                mapping[tuple(ctx.to_list())] = ctx
            except ProhibitedContextCombinationError:
                pass
        return mapping

    @classmethod
    def from_list(cls, values: list[str]) -> "Context":
        """Construct a Context from the list produced by :meth:`to_list`.

        Builds a mapping of all valid :class:`Context` combinations on first call
        and caches it on the class for subsequent lookups.

        :param values: A list of strings as returned by :meth:`to_list`.
        :returns: A reconstructed :class:`Context` instance.
        :raises ValueError: If no valid Context matches the given values.
        """
        ctx = cls._build_from_list_mapping().get(tuple(values))
        if ctx is None:
            raise ValueError(f"No valid Context matches: {values!r}")
        return ctx

    def to_list(self) -> list[str]:
        """Serialise this context to a list of its non-default string values.

        The list ordering is guaranteed; the order is:

        * Dimension (e.g. "Environmental", "Land Use", "Social")
            * Media (only for "Environmental" and "Resource" dimensions)
                * Vertical Strata (only for "Air" media, excluded if "Unknown")
                    * Population density (excluded if "Unknown")
                * Geography (only for "Ground" media, excluded if "Unknown")
                * Water Body (only for "Water" media, excluded if "Unknown")
            * Land Use ("Occupation" or "Transformation")
            * ``"Indoor"`` sentinel (only when an indoor air class is set),
              followed by the class name unless it is ``"Unknown"``

        Indoor air is always appended last, prefixed with the literal string
        ``"Indoor"``, which avoids a collision with the ``VerticalStrata.UNKNOWN``
        context (both would otherwise serialise to ``["Environmental", "Air"]``).

        :returns: A list of strings representing this context.
        """
        ATTRIBUTE_ORDERING = (
            "media",
            "geography",
            "land_use",
            "strata",
            "population_density",
            "water_body",
        )

        values = [self.dimension.value]
        for attr in ATTRIBUTE_ORDERING:
            val = getattr(self, attr)
            if val is None:
                continue
            if val.value != "Unknown":
                values.append(val.value)

        if self.indoor is not None:
            values.append("Indoor")
            if self.indoor.value != "Unknown":
                values.append(self.indoor.value)

        return values


def check_media(context: Context) -> None:
    if context.dimension not in (Dimension.ENVIRONMENTAL, Dimension.RESOURCE) and context.media:
        raise ProhibitedContextCombinationError(
            "Media is only used for environmental and resource flows"
        )
    if context.dimension in (Dimension.ENVIRONMENTAL, Dimension.RESOURCE) and not context.media:
        raise ProhibitedContextCombinationError(
            "Environmental and resource flows require a media"
        )


def check_strata(context: Context) -> None:
    if context.media == Media.AIR and context.dimension == Dimension.ENVIRONMENTAL and not (context.strata or context.indoor):
        raise ProhibitedContextCombinationError(
            "The dimension `Air` requires a vertical strata or indoor air class value"
        )
    if context.media == Media.AIR and context.strata and context.indoor:
        raise ProhibitedContextCombinationError(
            "Indoor air and vertical strata are disjoint"
        )
    if context.media != Media.AIR and context.strata:
        raise ProhibitedContextCombinationError(
            "Vertical strata values are only allowed in the `Air` dimension"
        )
    if context.media == Media.AIR and context.strata in (VerticalStrata.AIRCRAFT, VerticalStrata.UNKNOWN, VerticalStrata.LONG_TERM) and context.population_density:
        raise ProhibitedContextCombinationError(
            "Population density values aren't allowed for aircraft, unknown strata, or long-term emissions"
        )
    if context.media == Media.AIR and context.strata in (VerticalStrata.GROUND_LEVEL, VerticalStrata.LOW_STACK, VerticalStrata.MEDIUM_STACK, VerticalStrata.HIGH_STACK) and not context.population_density:
        raise ProhibitedContextCombinationError(
            "Population density values required for these air emissions"
        )
    if context.media == Media.AIR and context.dimension == Dimension.RESOURCE and context.strata:
        raise ProhibitedContextCombinationError(
            "Resources don't have a vertical strata"
        )


def check_indoor(context: Context) -> None:
    if context.media != Media.AIR and context.indoor:
        raise ProhibitedContextCombinationError(
            "Indoor air class is only allowed in the `Air` dimension"
        )
    if context.indoor and context.population_density:
        raise ProhibitedContextCombinationError(
            "Population density values aren't allowed for indoor air emissions"
        )
    if context.indoor and context.strata:
        raise ProhibitedContextCombinationError(
            "No vertical strata value used for indoor emissions"
        )
    if context.indoor and context.dimension == Dimension.RESOURCE:
        raise ProhibitedContextCombinationError(
            "Resources don't have indoor air classes"
        )


def check_population_density(context: Context) -> None:
    if context.media != Media.AIR and context.population_density:
        raise ProhibitedContextCombinationError(
            "Population density values are only allowed in the `Air` dimension"
        )
    if context.media == Media.AIR and context.dimension == Dimension.ENVIRONMENTAL and context.strata in (VerticalStrata.AIRCRAFT, VerticalStrata.LONG_TERM) and context.population_density:
        raise ProhibitedContextCombinationError(
            "Population density values aren't allowed for aircraft or long-term emissions"
        )
    if context.media == Media.AIR and context.dimension == Dimension.RESOURCE and context.population_density:
        raise ProhibitedContextCombinationError(
            "Population density values aren't allowed for resources"
        )


#: Water bodies that cannot be withdrawn *from*, and so are prohibited on the
#: `Resource` dimension.  Both treatment values name a stage in somebody's
#: effluent handling rather than a body in the world, and `LONG_TERM` is a
#: temporal qualifier on a release: an extraction has no >100-year counterpart.
#: Kept as data rather than an `if` chain so the reason is attached to the list.
_EMISSION_ONLY_WATER_BODIES = frozenset(
    {
        WaterBody.WWTP,
        WaterBody.SECONDARY_TREATMENT,
        WaterBody.LONG_TERM,
    }
)


def check_water_body(context: Context) -> None:
    """Where the water came from, or where it went.

    `water_body` is required on both water dimensions and means a different
    thing on each: on `Environmental` it is the body receiving the emission, on
    `Resource` the body the withdrawal was taken from.  Requiring it on
    `Resource` rather than merely permitting it is what keeps `to_list()`
    injective -- the serialisation drops `"Unknown"`, so an optional field would
    let `Resource / Water / Unknown` and `Resource / Water / None` produce the
    same key for two different contexts.

    Withdrawals were previously denied the field entirely, which left every
    source's water resources on one context: EF 3.1 gives all six of its bodies
    the single compartment `Resources / Resources from water / Renewable
    material resources from water`, so lake water and sea water and groundwater
    arrived indistinguishable.  See `plans/water-taxonomy.md`.
    """
    if context.media == Media.WATER and context.dimension in (
        Dimension.ENVIRONMENTAL,
        Dimension.RESOURCE,
    ) and not context.water_body:
        raise ProhibitedContextCombinationError(
            "The dimension `Water` requires a water body value"
        )
    if context.dimension not in (
        Dimension.ENVIRONMENTAL,
        Dimension.RESOURCE,
    ) and context.water_body:
        raise ProhibitedContextCombinationError(
            "Water body specification only allowed for environmental and resource dimensions"
        )
    if context.media != Media.WATER and context.water_body:
        raise ProhibitedContextCombinationError(
            "Water body specification only allowed for `Water` dimension"
        )
    if context.dimension == Dimension.RESOURCE and context.water_body in _EMISSION_ONLY_WATER_BODIES:
        raise ProhibitedContextCombinationError(
            f"`{context.water_body.value}` is not a body water is withdrawn from"
        )


def check_geography(context: Context) -> None:
    if context.media != Media.GROUND and context.geography:
        raise ProhibitedContextCombinationError(
            "Geography specification only allowed for `Ground` dimension"
        )
    if context.dimension != Dimension.ENVIRONMENTAL and context.geography:
        raise ProhibitedContextCombinationError(
            "Geography specification only allowed for `Ground` dimension"
        )
    if context.media == Media.GROUND and context.dimension == Dimension.ENVIRONMENTAL and not context.geography:
        raise ProhibitedContextCombinationError(
            "Geography specification required for `Ground` dimension"
        )
    if context.media == Media.GROUND and context.dimension == Dimension.RESOURCE and context.geography:
        raise ProhibitedContextCombinationError(
            "Geography specification not allowed for resources"
        )


def check_resources(context: Context) -> None:
    if context.dimension == Dimension.RESOURCE and context.media in (Media.PRODUCT, Media.OTHER):
        raise ProhibitedContextCombinationError(
            "Resources limited to physical environmental media"
        )


def check_land_use(context: Context) -> None:
    if context.dimension != Dimension.LAND_USE and context.land_use:
        raise ProhibitedContextCombinationError(
            "Land use type only for land use dimension"
        )
    if context.dimension == Dimension.LAND_USE and not context.land_use:
        raise ProhibitedContextCombinationError(
            "Land use type required for land use dimension"
        )


def counts_a_non_material_intervention(dimension: str, media: str) -> bool:
    """Whether a ``(dimension, media)`` pair counts a burden that is not matter.

    True for exactly one pair: ``Environmental / Other``.  Every other medium of
    ``Environmental`` receives a substance, and :class:`Media` documents ``Other``
    as the medium for what is not a release into air, water or ground.

    BAFU files traffic noise there, under a compartment it calls ``non material
    emissions``, measured per person-kilometre and per tonne-kilometre (#70).
    Noise travels through air but is not carried by anything emitted into it:
    what the inventory counts is sound against the transport that made it.

    Lives here rather than beside either of its callers because both ask the
    same question of a context and must not answer it differently: the semantic
    typing decides whether an object can be chemistry at all, and the flow
    layering decides whether it belongs to an intervention family.
    """
    return dimension == Dimension.ENVIRONMENTAL and media == Media.OTHER


class ContextError(Exception):
    pass


class ProhibitedContextCombinationError(ContextError):
    """The combination of these values is not allowed."""

    pass
