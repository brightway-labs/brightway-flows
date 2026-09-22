"""What a land flow is *of*: a land class, and which way it crossed the boundary.

The context says a flow is a land occupation or a land transformation.  The unit
says how much land, for how long.  Neither says **what the land is** -- `forest`,
`cropland`, `seabed` -- nor **how it is used** -- irrigated, intensive, organic,
clear-cut -- and until this module neither did any other field: both lived in a
comma-separated flow name, which is a string three source lists spell three ways.
See `plans/land-class-taxonomy.md`.

The same problem the material taxonomy solved for water, with one difference that
decides the design.  Water needed *one* new axis, so
`environmental-materials.json` could be a flat list of curated concepts.  A land
class needs fifteen, because `arable, non-irrigated, intensive` is not an atom:
it is cropland, held without irrigation, farmed intensively.  A list of concepts
would have to spell out every combination and re-state every anchor on each of
them; a value with fields states each part once and lets identity fall out of
the parts.

Two strings that decompose to the same :class:`LandUse` are the same thing, with
no crosswalk row required::

    EF        arable, non-irrigated, intensive        \\
    ecoinvent annual crop, non-irrigated, intensive   |-> (CROPLAND, rainfed, intensive)
    BAFU      annual crop, non-irrigated, intensive   /

**Direction is a field here rather than a context value.** EF 3.1 characterises
`from forest, primary` at -396.7 and `to forest, primary` at +396.7 -- a balanced
pair in one context, one unit, and (after this module) one land class.
`pipeline/deduplication.py` signs on every field of an elementary flow but six,
so the only thing keeping that pair apart today is the words `From` and `To`
inside a label, which is #31 waiting to happen.  Making direction a field makes
the two different values, which mint different flow objects, which is what holds
them apart -- and it costs no change to the context vocabulary at all.

Modelled on `domain/context.py`, deliberately: enums, a frozen dataclass,
``check_*`` validators that raise, and an enumeration built by
:func:`itertools.product` and pruned by those validators.  A reader who knows
`Context` knows this.

**The axes were read off the data, not invented.**  Every land-class string EF
3.1, ecoinvent 3.8-3.12 and BAFU 2026 v1 ship was decomposed against a candidate
axis set and the residue counted; 152 of 153 factorise with nothing left over.
``tools/build_observed_land_classes.py`` regenerates that evidence, and
``tests/test_land_use_dataclass.py`` fails if any observed class stops being
constructible.
"""

from __future__ import annotations

import functools
import itertools
from dataclasses import dataclass, fields, replace
from enum import StrEnum

from brightway_flows.domain.context import LandUseClass


class LandUseError(Exception):
    pass


class ProhibitedLandUseCombinationError(LandUseError):
    """These field values do not describe a land class anything could be."""


# ── the two required axes ────────────────────────────────────────────────────


class Direction(StrEnum):
    """Which way the land crossed the system boundary.

    Not a context value.  `Land Use / Occupation` and `Land Use / Transformation`
    keep the IRIs they have; this says which *end* of a transformation a flow is,
    which the context has never said and the flow name has always had to.
    """

    OCCUPATION = "Occupation"
    TRANSFORMATION_FROM = "Transformation, from"
    TRANSFORMATION_TO = "Transformation, to"


class LandCover(StrEnum):
    """What the land is, before anything is said about how it is used.

    The anthropogenic covers are much finer than any ecosystem typology would
    make them, and deliberately so: `traffic area` and `dump site` and
    `construction site` are one class in IUCN GET (`T7.4`), and the source lists
    characterise them differently.  See `plans/land-class-taxonomy.md` §2.2 for
    which authority anchors which, and why the split runs on the realm.
    """

    # ── cultivated ──
    CROPLAND = "Cropland"
    PERMANENT_CROPLAND = "Permanent cropland"
    PASTURE = "Pasture"
    AGRICULTURE = "Agriculture"
    FIELD_MARGIN = "Field margin"
    # ── vegetated, not cultivated ──
    FOREST = "Forest"
    TROPICAL_RAINFOREST = "Tropical rainforest"
    SHRUBLAND = "Shrubland"
    GRASSLAND = "Grassland"
    #: EF 3.1's `grassland/pasture/meadow`, which is neither of the two covers
    #: it names but the union of them.
    #:
    #: EF ships all three -- `grassland`, `pasture/meadow` and
    #: `grassland/pasture/meadow` -- as separate flows in all three directions,
    #: so the third is a class the list draws and not a spelling of either
    #: neighbour.  Grassland is not meadow: a meadow is mown and a pasture is
    #: grazed, which is why ENVO files both under `area of pastureland or
    #: hayfields` and files grassland somewhere else entirely.  Folding this
    #: onto `GRASSLAND` asserted that grassland takes in both, which is the one
    #: thing the three-way split says it does not.
    #:
    #: ecoinvent draws the same line on a different axis -- `grassland,
    #: natural` against `pasture, man made` -- so the distinction is not EF's
    #: alone, and this cover is the coarser class neither of them names.
    GRASSLAND_PASTURE_MEADOW = "Grassland, pasture or meadow"
    WETLAND = "Wetland"
    # ── unvegetated ──
    BARREN = "Barren land"
    SNOW_AND_ICE = "Snow and ice"
    # ── water and sea floor ──
    LAKE = "Lake"
    RIVER = "River"
    INLAND_WATER = "Inland water body"
    WATER_BODY = "Water body"
    WATERCOURSE = "Watercourse"
    SEA = "Sea"
    SEABED = "Seabed"
    # ── built and worked ──
    URBAN = "Urban"
    INDUSTRIAL = "Industrial area"
    TRAFFIC = "Traffic area"
    ARTIFICIAL = "Artificial area"
    CONSTRUCTION_SITE = "Construction site"
    EXTRACTION_SITE = "Mineral extraction site"
    DUMP_SITE = "Dump site"
    SEALED = "Sealed soil"
    URBAN_INDUSTRIAL_FALLOW = "Urban or industrial fallow"
    # ── the source said nothing ──
    UNSPECIFIED = "Unspecified"


# ── the qualifier axes ───────────────────────────────────────────────────────


class Irrigation(StrEnum):
    IRRIGATED = "Irrigated"
    RAINFED = "Non-irrigated"


class ManagementIntensity(StrEnum):
    """How hard the land is worked.

    `Organic` is a management *system* rather than a rung on an intensity ladder,
    but every source list writes it in this slot -- `annual crop, organic` sits
    beside `annual crop, non-irrigated, intensive` -- so it is one value of one
    axis rather than an axis of its own that is never combined with this one.

    `DIVERSE_INTENSIVE` is BAFU's, and is the only value in this module with no
    published class anywhere to cite (§6.1).

    `INTEGRATED` is Stepwise 2006's, inherited from ecoinvent 2: Swiss
    integrated production, a farming system between organic and conventional
    with mandated ecological compensation.  It is a value and not a spelling of
    one already here -- Stepwise gives `Occupation, arable, integrated` a
    nature-occupation factor of 0.0 and `Occupation, arable, organic` -0.04, so
    the method itself distinguishes them.
    """

    INTENSIVE = "Intensive"
    DIVERSE_INTENSIVE = "Diverse-intensive"
    INTEGRATED = "Integrated"
    EXTENSIVE = "Extensive"
    ORGANIC = "Organic"


class UseStatus(StrEnum):
    """Whether the land is being used, and how far from unused it is."""

    USED = "Used"
    UNUSED = "Not used"
    FALLOW = "Fallow"
    GRAZED = "Grazed"


class Origin(StrEnum):
    """Whether the cover is there by nature or by construction."""

    NATURAL = "Natural"
    ARTIFICIAL = "Artificial"
    MAN_MADE = "Man-made"


class SuccessionalStage(StrEnum):
    PRIMARY = "Primary"
    SECONDARY = "Secondary"


class SilviculturalRegime(StrEnum):
    SHORT_ROTATION = "Short rotation"
    NORMAL_ROTATION = "Normal rotation"
    CLEAR_CUTTING = "Clear-cutting"


class VegetationForm(StrEnum):
    """How the stand is grown or what physiognomy it has."""

    SCLEROPHYLLOUS = "Sclerophyllous"
    FLOODED = "Flooded"
    UNDER_GLASS = "Under glass"


class BuiltForm(StrEnum):
    """What is on the ground, where the ground is built or worked."""

    CONTINUOUS = "Continuously built"
    DISCONTINUOUS = "Discontinuously built"
    BUILT_UP = "Built up"
    VEGETATED = "Vegetated"
    GREEN_SPACE = "Green space"
    INFRASTRUCTURE = "Infrastructure"
    MOSAIC = "Mosaic"


class Substrate(StrEnum):
    """What the site sits on, where that is not the land surface.

    One value, because one distinction is made: BAFU files industrial areas and
    dump sites on the sea floor, which is a site of the same kind in a different
    realm rather than a different kind of site.
    """

    BENTHIC = "Benthic"


class Infrastructure(StrEnum):
    """What the traffic area carries.

    `RAIL_EMBANKMENT` is the half `RAIL_ROAD_EMBANKMENT` folds in.  ecoinvent 2
    drew the embankment beside a railway and the one beside a road as two
    classes, ecoinvent 3 publishes the pair as one, and Stepwise 2006 -- a
    SimaPro method file carrying ecoinvent 2's names -- still ships both.  The
    road half was already here; this is the other one.
    """

    RAIL_NETWORK = "Rail network"
    ROAD_NETWORK = "Road network"
    RAIL_ROAD_EMBANKMENT = "Rail and road embankment"
    RAIL_EMBANKMENT = "Rail embankment"
    ROAD_EMBANKMENT = "Road embankment"


class LandfillType(StrEnum):
    INERT_MATERIAL = "Inert material landfill"
    RESIDUAL_MATERIAL = "Residual material landfill"
    SANITARY = "Sanitary landfill"
    SLAG_COMPARTMENT = "Slag compartment"


class SeabedActivity(StrEnum):
    MINING = "Mining"
    OIL_DRILLING = "Oil drilling"
    DRILLING_AND_MINING = "Drilling and mining"
    SEDIMENT_DUMPING = "Sediment dumping"
    DREDGING = "Dredging"


class Position(StrEnum):
    COASTAL = "Coastal"
    INLAND = "Inland"


class CropType(StrEnum):
    FRUIT = "Fruit"
    VINE = "Vine"


class Tillage(StrEnum):
    """ecoinvent's three obsolete tillage classes, and nothing else.

    Retained because the obsolete flows are still shipped and still have to land
    somewhere; a source that states a tillage regime states it *instead of* an
    intensity, which is what :func:`check_tillage` says.
    """

    CONSERVATION = "Conservation tillage"
    CONVENTIONAL = "Conventional tillage"
    REDUCED = "Reduced tillage"


#: Every optional axis, as ``attribute -> enum``.  The order is the order a
#: label reads in and the *reverse* of the order :meth:`LandUse.broader` drops
#: them in, so the two cannot disagree about which qualifier is the general one.
QUALIFIER_AXES: dict[str, type[StrEnum]] = {
    "irrigation": Irrigation,
    "origin": Origin,
    "use_status": UseStatus,
    "intensity": ManagementIntensity,
    "vegetation_form": VegetationForm,
    "stage": SuccessionalStage,
    "substrate": Substrate,
    "position": Position,
    "built_form": BuiltForm,
    "infrastructure": Infrastructure,
    "landfill": LandfillType,
    "activity": SeabedActivity,
    "crop_type": CropType,
    "silviculture": SilviculturalRegime,
    "tillage": Tillage,
}


#: Which qualifiers each cover may take.
#:
#: This is what keeps the enumeration finite and the model honest: `silviculture`
#: is a question about a forest and `landfill` is a question about a dump site,
#: and neither is ever asked of the other.  Read off the 119 land classes the
#: three lists actually ship -- a cover admits an axis here because some source
#: states that axis of that cover.  A cover absent from this mapping takes no
#: qualifiers at all.
COVER_AXES: dict[LandCover, frozenset[str]] = {
    LandCover.CROPLAND: frozenset(
        {"irrigation", "intensity", "use_status", "vegetation_form", "tillage"}
    ),
    LandCover.PERMANENT_CROPLAND: frozenset({"irrigation", "intensity", "crop_type"}),
    LandCover.PASTURE: frozenset({"intensity", "origin"}),
    LandCover.AGRICULTURE: frozenset({"built_form"}),
    LandCover.FOREST: frozenset(
        {"intensity", "origin", "stage", "silviculture", "use_status"}
    ),
    LandCover.GRASSLAND: frozenset({"origin", "use_status"}),
    # Nothing. EF states this cover three times -- once per direction -- and
    # qualifies it with nothing at all, which is what makes it the coarse class:
    # a source that had a use status or an intensity to state would have stated
    # one of the two finer covers instead.
    LandCover.GRASSLAND_PASTURE_MEADOW: frozenset(),
    LandCover.SHRUBLAND: frozenset({"vegetation_form"}),
    LandCover.WETLAND: frozenset({"position", "use_status"}),
    LandCover.BARREN: frozenset({"use_status"}),
    LandCover.SNOW_AND_ICE: frozenset({"use_status"}),
    LandCover.LAKE: frozenset({"origin", "use_status"}),
    LandCover.RIVER: frozenset({"origin", "use_status"}),
    # No `INLAND_WATER` entry: ecoinvent's `inland waterbody, unspecified` is
    # the only thing said of it, and an `unspecified use` is the absence of a
    # `use_status` rather than a value of one.
    LandCover.WATER_BODY: frozenset({"origin"}),
    LandCover.WATERCOURSE: frozenset({"origin"}),
    LandCover.SEABED: frozenset({"origin", "use_status", "built_form", "activity"}),
    LandCover.URBAN: frozenset({"built_form"}),
    LandCover.INDUSTRIAL: frozenset({"built_form", "substrate"}),
    LandCover.TRAFFIC: frozenset({"infrastructure"}),
    LandCover.DUMP_SITE: frozenset({"landfill", "substrate"}),
    LandCover.URBAN_INDUSTRIAL_FALLOW: frozenset({"use_status"}),
    LandCover.UNSPECIFIED: frozenset({"origin", "use_status"}),
}


@dataclass(frozen=True, slots=True)
class LandUse:
    """One land class, in one direction across the boundary.

    ``None`` means *the source did not say*, and is not the same as a value
    called unspecified: ecoinvent's `arable land, unspecified use` and EF's
    `arable` both leave `use_status` unset, and are therefore the same value.
    A stated *unspecified* is the absence of a statement, not a statement.
    """

    direction: Direction
    cover: LandCover
    irrigation: Irrigation | None = None
    origin: Origin | None = None
    use_status: UseStatus | None = None
    intensity: ManagementIntensity | None = None
    vegetation_form: VegetationForm | None = None
    stage: SuccessionalStage | None = None
    substrate: Substrate | None = None
    position: Position | None = None
    built_form: BuiltForm | None = None
    infrastructure: Infrastructure | None = None
    landfill: LandfillType | None = None
    activity: SeabedActivity | None = None
    crop_type: CropType | None = None
    silviculture: SilviculturalRegime | None = None
    tillage: Tillage | None = None

    def __post_init__(self) -> None:
        check_cover_admits_axes(self)
        check_tillage(self)
        check_vegetation_form(self)
        check_silviculture(self)
        check_successional_stage(self)
        check_unused_land_is_unmanaged(self)

    # ── reading it ──

    def qualifiers(self) -> dict[str, StrEnum]:
        """The optional axes this value states, in label order."""
        return {
            name: value
            for name in QUALIFIER_AXES
            if (value := getattr(self, name)) is not None
        }

    @property
    def land_use_class(self) -> LandUseClass:
        """The context value this direction belongs in.

        The bridge to `domain/context.py`, and the reason this module adds no
        context value: a flow's context and its land class must agree about
        occupation versus transformation, and one of them derives from the other
        rather than both being asserted.
        """
        if self.direction is Direction.OCCUPATION:
            return LandUseClass.OCCUPATION
        return LandUseClass.TRANSFORMATION

    @property
    def key(self) -> str:
        """A stable identifier for this value, built only from its fields.

        Two spellings of one land class produce one key, which is the whole
        point.  Sorted by :data:`QUALIFIER_AXES` order rather than by field
        order so that adding an axis cannot renumber the keys of values that do
        not use it.
        """
        parts = [_slug(self.direction.name), _slug(self.cover.name)]
        parts += [
            f"{name}={_slug(value.name)}" for name, value in self.qualifiers().items()
        ]
        return "/".join(parts)

    @property
    def label(self) -> str:
        """A human-readable name: what the context does not already say.

        The context carries `Land Use → Occupation` or `Land Use →
        Transformation`, so naming either in the label repeats it.  What the
        context has never carried is **which end** of a transformation a flow
        is -- that is §1.7, and the whole reason `direction` is a field -- so
        the `from` or `to` is here and has to be.

        That rule is why an occupation reads `Cropland, non-irrigated,
        intensive` and a transformation reads `From forest, primary`.  It used
        to write `Transformation, from forest, primary`, dropping the redundant
        word for one direction and keeping it for the other two, which was EF
        3.1's convention for occupations and the SimaPro-lineage lists' for
        transformations -- one rule each, and no rule between them.
        """
        qualifiers = ", ".join(value.value.lower() for value in self.qualifiers().values())
        cover = self.cover.value
        base = f"{cover}, {qualifiers}" if qualifiers else cover
        if self.direction is Direction.OCCUPATION:
            return base
        preposition = "From" if self.direction is Direction.TRANSFORMATION_FROM else "To"
        return f"{preposition} {base[0].lower() + base[1:]}"

    # ── walking up ──

    def broader(self) -> "LandUse | None":
        """This value with its most specific stated qualifier dropped.

        ``None`` at the root, which is a bare ``(direction, cover)``.  Dropping
        a field is how `skos:broader` is *generated* rather than curated: every
        edge in the published scheme comes from here, so no edge can be
        published as an authority's that the authority does not assert.

        Which qualifier is "most specific" is :data:`QUALIFIER_AXES` read
        backwards -- a `tillage` regime is dropped before an `intensity`, and an
        `intensity` before the `irrigation` it refines.
        """
        for name in reversed(QUALIFIER_AXES):
            if getattr(self, name) is not None:
                return replace(self, **{name: None})
        return None

    def broader_chain(self) -> list["LandUse"]:
        """This value and its ancestors, nearest first, ending at the root."""
        chain: list[LandUse] = []
        current: LandUse | None = self
        while current is not None:
            chain.append(current)
            current = current.broader()
        return chain

    # ── serialising it ──

    def to_dict(self) -> dict[str, str]:
        """The stated fields only, as plain strings, for an I/O boundary."""
        stated = {"direction": self.direction.name, "cover": self.cover.name}
        stated.update(
            {name: value.name for name, value in self.qualifiers().items()}
        )
        return stated

    @classmethod
    def from_key(cls, key: str) -> "LandUse":
        """The value :attr:`key` names, read back.

        The exact inverse of :attr:`key`, and the reason it exists: the key is
        what the published record carries -- it is the local name of the class's
        IRI and the value of its classification block -- so anything reading a
        built list back has the key and not the fields.  Parsing it here rather
        than at each reading end means one spelling of the format, checked by
        `tests/test_land_use_dataclass.py` against every enumerated value.

        This is not the land-class parser of `tools/`, which reads a *vendor's*
        name and decides what it means.  This reads a string this project wrote
        from fields it already had, and no judgement is involved.

        :raises LandUseError: on a key naming a direction, cover or axis this
            module does not declare, rather than returning a value with a field
            quietly dropped.
        """
        parts = [part for part in str(key or "").split("/") if part]
        if len(parts) < 2:
            raise LandUseError(f"not a land class key: {key!r}")
        payload = {"direction": _unslug(parts[0]), "cover": _unslug(parts[1])}
        for part in parts[2:]:
            name, _, value = part.partition("=")
            if not value:
                raise LandUseError(f"{key!r} has a qualifier with no value: {part!r}")
            payload[name] = _unslug(value)
        try:
            return cls.from_dict(payload)
        except KeyError as error:
            raise LandUseError(f"{key!r} names no such value: {error}") from error

    @classmethod
    def from_dict(cls, payload: dict[str, str]) -> "LandUse":
        """Rebuild a value from :meth:`to_dict`.

        :raises LandUseError: on a field this module does not declare, rather
            than ignoring it -- a typo in a curated file is a row that would
            otherwise silently lose a qualifier.
        """
        known = {field.name for field in fields(cls)}
        unknown = set(payload) - known
        if unknown:
            raise LandUseError(f"not land-use axes: {sorted(unknown)}")
        kwargs: dict[str, StrEnum] = {
            "direction": Direction[payload["direction"]],
            "cover": LandCover[payload["cover"]],
        }
        for name, enum in QUALIFIER_AXES.items():
            if name in payload:
                kwargs[name] = enum[payload[name]]
        return cls(**kwargs)


def _slug(name: str) -> str:
    return name.lower().replace("_", "-")


def _unslug(slug: str) -> str:
    """The enum member name a slug came from.

    The inverse of :func:`_slug`, and it holds because every member name in
    this module is upper snake case: no value contains a hyphen of its own, so
    turning every hyphen back into an underscore cannot join two words that
    were separate.  `tests/test_land_use_dataclass.py` checks that over every
    enumerated value rather than leaving it as a claim about naming.
    """
    return slug.upper().replace("-", "_")


# ── the rules ────────────────────────────────────────────────────────────────


def check_cover_admits_axes(land_use: LandUse) -> None:
    """Every stated qualifier is one this cover is asked about."""
    admitted = COVER_AXES.get(land_use.cover, frozenset())
    stated = set(land_use.qualifiers())
    if not stated <= admitted:
        raise ProhibitedLandUseCombinationError(
            f"{land_use.cover.value} is not qualified by "
            f"{sorted(stated - admitted)}"
        )


def check_tillage(land_use: LandUse) -> None:
    """A tillage regime is stated instead of an intensity, never as well as one.

    ecoinvent's three obsolete `arable, * tillage` classes say how the soil is
    worked in the slot where its other cropland classes say how hard.
    """
    if land_use.tillage and (land_use.intensity or land_use.irrigation):
        raise ProhibitedLandUseCombinationError(
            "a tillage regime replaces the intensity and irrigation, "
            f"but {land_use.tillage.value} is stated with them"
        )


def check_vegetation_form(land_use: LandUse) -> None:
    """A paddy and a greenhouse have already answered the water question."""
    waterlogged = (VegetationForm.FLOODED, VegetationForm.UNDER_GLASS)
    if land_use.vegetation_form in waterlogged and land_use.irrigation:
        raise ProhibitedLandUseCombinationError(
            f"{land_use.vegetation_form.value} cropland states its own water "
            f"regime, so {land_use.irrigation.value} adds a second"
        )


def check_silviculture(land_use: LandUse) -> None:
    """Only a stand under management has a rotation.

    Every silvicultural regime the lists state is stated of `forest, intensive`.
    A primary forest is not on a short rotation; it is on no rotation.
    """
    if land_use.silviculture and land_use.intensity is not ManagementIntensity.INTENSIVE:
        raise ProhibitedLandUseCombinationError(
            f"{land_use.silviculture.value} is a regime of intensively managed "
            "forest, and the intensity is not stated"
        )


def check_successional_stage(land_use: LandUse) -> None:
    """Succession and management intensity describe a stand two different ways."""
    if land_use.stage and (land_use.intensity or land_use.silviculture):
        raise ProhibitedLandUseCombinationError(
            f"a {land_use.stage.value.lower()} forest is described by its "
            "succession rather than by how it is managed"
        )


def check_unused_land_is_unmanaged(land_use: LandUse) -> None:
    """Land recorded as not used has no management intensity."""
    if land_use.use_status is UseStatus.UNUSED and land_use.intensity:
        raise ProhibitedLandUseCombinationError(
            f"{land_use.cover.value} is recorded as not used, so it has no "
            f"{land_use.intensity.value.lower()} management"
        )


# ── the enumeration ──────────────────────────────────────────────────────────


@functools.cache
def all_land_uses() -> tuple[LandUse, ...]:
    """Every legal :class:`LandUse`, enumerated once and cached.

    Built the way `Context._build_from_list_mapping` builds its own: take the
    product, construct, and keep what does not raise.  Per *cover* rather than
    over all axes at once, because a flat product of sixteen axes is nine
    figures of combinations that are almost all nonsense -- `COVER_AXES` says
    which questions each cover is asked, and that is what makes this finite.

    This is the *legal* space, not the published one.  A concept earns a flow
    object when a source flow lands on it; see `plans/land-class-taxonomy.md`
    §3.6.
    """
    found: list[LandUse] = []
    for cover in LandCover:
        axes = sorted(COVER_AXES.get(cover, frozenset()))
        choices = [list(QUALIFIER_AXES[name]) + [None] for name in axes]
        for direction in Direction:
            for combination in itertools.product(*choices):
                try:
                    found.append(
                        LandUse(
                            direction=direction,
                            cover=cover,
                            **dict(zip(axes, combination, strict=True)),
                        )
                    )
                except ProhibitedLandUseCombinationError:
                    pass
    return tuple(found)


@functools.cache
def land_uses_by_key() -> dict[str, LandUse]:
    """The enumeration, keyed by :attr:`LandUse.key`."""
    return {land_use.key: land_use for land_use in all_land_uses()}
