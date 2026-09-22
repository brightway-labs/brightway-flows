"""The land-class parser: a build-time aid, and never a run-time rule.

`domain/land_use.py` says its axes were read off the data.  This is the reading:
the tables that decompose a vendor's land-class string -- `arable, non-irrigated,
intensive` -- into the axes of a :class:`~brightway_flows.domain.land_use.LandUse`.

**Deliberately outside `src/`.**  It gets a curator to 152 of 153 strings; it
does not get to decide, unsupervised, that `heterogeneous, agricultural` is
`agriculture, mosaic`.  A parser that ran at build time would make every one of
those readings a silent rule, which is the discipline
`tools/build_water_flow_materials.py` follows for the same reason: no algorithm
reads `Water, salt, sole` and knows it is brine.  See
`plans/land-class-taxonomy.md` §3.2 and §3.8.

Two tools read it, and that is why it is a module rather than a block inside
one.  `build_observed_land_classes.py` writes the evidence for the dataclass --
which classes the lists ship -- and `build_land_flow_classes.py` writes the
curated assignment of each source flow to one of them.  The two must decompose a
name identically or the evidence would be for a different taxonomy from the one
the assignment uses, and a second copy of a 150-row table is how that happens.
"""

from __future__ import annotations

from typing import Any

from brightway_flows.simapro_names import split_geography_suffix
from brightway_flows.domain.land_use import (
    BuiltForm,
    CropType,
    Direction,
    Infrastructure,
    Irrigation,
    LandCover,
    LandfillType,
    LandUse,
    ManagementIntensity,
    Origin,
    Position,
    ProhibitedLandUseCombinationError,
    SeabedActivity,
    SilviculturalRegime,
    Substrate,
    SuccessionalStage,
    Tillage,
    UseStatus,
    VegetationForm,
)


#: Excluded rather than parsed: four EF flows measuring a *volume* -- a
#: repository, a reservoir, an underground deposit -- filed under land
#: occupation.  No surface classification has a word for the inside of a
#: mountain, and folding them in would make this module's root claim false.
#: They are #72's.
VOLUME_PREFIX = "volume occupied"

#: The head of a name, to a cover.  Several covers are spelled more than one way
#: and that is the point: `arable` and `annual crop` are one cover.
COVERS: dict[str, LandCover] = {
    "arable": LandCover.CROPLAND,
    "arable land": LandCover.CROPLAND,
    "annual crop": LandCover.CROPLAND,
    "cropland": LandCover.CROPLAND,
    "permanent crop": LandCover.PERMANENT_CROPLAND,
    "permanent crops": LandCover.PERMANENT_CROPLAND,
    "pasture": LandCover.PASTURE,
    "pasture/meadow": LandCover.PASTURE,
    "pasture and meadow": LandCover.PASTURE,
    "grassland": LandCover.GRASSLAND,
    # Its own cover, not a spelling of the one before it.  EF ships all three of
    # `grassland`, `pasture/meadow` and `grassland/pasture/meadow` in all three
    # directions, so the third is a class EF draws; reading it as plain
    # grassland asserted that grassland takes in mown and grazed land, which is
    # the one thing the three-way split denies.  Grassland is not meadow.
    "grassland/pasture/meadow": LandCover.GRASSLAND_PASTURE_MEADOW,
    "agriculture": LandCover.AGRICULTURE,
    "heterogeneous": LandCover.AGRICULTURE,
    "field margin/hedgerow": LandCover.FIELD_MARGIN,
    "field margins/hedgerows": LandCover.FIELD_MARGIN,
    "forest": LandCover.FOREST,
    "occup. as forest land": LandCover.FOREST,
    "tropical rain forest": LandCover.TROPICAL_RAINFOREST,
    "shrub land": LandCover.SHRUBLAND,
    "wetland": LandCover.WETLAND,
    "wetlands": LandCover.WETLAND,
    "bare area": LandCover.BARREN,
    "snow and ice": LandCover.SNOW_AND_ICE,
    "lake": LandCover.LAKE,
    "lakes": LandCover.LAKE,
    "river": LandCover.RIVER,
    "rivers": LandCover.RIVER,
    "inland water bodies": LandCover.INLAND_WATER,
    "inland waterbody": LandCover.INLAND_WATER,
    "water bodies": LandCover.WATER_BODY,
    "water courses": LandCover.WATERCOURSE,
    "sea and ocean": LandCover.SEA,
    "seabed": LandCover.SEABED,
    "urban": LandCover.URBAN,
    "industrial area": LandCover.INDUSTRIAL,
    "traffic area": LandCover.TRAFFIC,
    "artificial areas": LandCover.ARTIFICIAL,
    "construction site": LandCover.CONSTRUCTION_SITE,
    "mineral extraction site": LandCover.EXTRACTION_SITE,
    "dump site": LandCover.DUMP_SITE,
    "sealed soil": LandCover.SEALED,
    "urban/industrial fallow": LandCover.URBAN_INDUSTRIAL_FALLOW,
    "unspecified": LandCover.UNSPECIFIED,
    "unknown": LandCover.UNSPECIFIED,
}

#: A qualifier token, to the axis and value it states.  ``None`` for a token
#: that states the *absence* of a value: `unspecified use` is what a source
#: writes when it has nothing to say, and having nothing to say is `None`.
QUALIFIERS: dict[str, tuple[str, Any]] = {
    "irrigated": ("irrigation", Irrigation.IRRIGATED),
    "non-irrigated": ("irrigation", Irrigation.RAINFED),
    "intensive": ("intensity", ManagementIntensity.INTENSIVE),
    "diverse-intensive": ("intensity", ManagementIntensity.DIVERSE_INTENSIVE),
    "integrated": ("intensity", ManagementIntensity.INTEGRATED),
    "extensive": ("intensity", ManagementIntensity.EXTENSIVE),
    "organic": ("intensity", ManagementIntensity.ORGANIC),
    "used": ("use_status", UseStatus.USED),
    "not used": ("use_status", UseStatus.UNUSED),
    "non-use": ("use_status", UseStatus.UNUSED),
    "fallow": ("use_status", UseStatus.FALLOW),
    "for livestock grazing": ("use_status", UseStatus.GRAZED),
    "unspecified use": ("use_status", None),
    "unspecified": ("use_status", None),
    "natural": ("origin", Origin.NATURAL),
    "artificial": ("origin", Origin.ARTIFICIAL),
    "man made": ("origin", Origin.MAN_MADE),
    "primary": ("stage", SuccessionalStage.PRIMARY),
    "secondary": ("stage", SuccessionalStage.SECONDARY),
    "short-cycle": ("silviculture", SilviculturalRegime.SHORT_ROTATION),
    "normal": ("silviculture", SilviculturalRegime.NORMAL_ROTATION),
    "clear-cutting": ("silviculture", SilviculturalRegime.CLEAR_CUTTING),
    "sclerophyllous": ("vegetation_form", VegetationForm.SCLEROPHYLLOUS),
    "flooded crop": ("vegetation_form", VegetationForm.FLOODED),
    "flooded crops": ("vegetation_form", VegetationForm.FLOODED),
    "greenhouse": ("vegetation_form", VegetationForm.UNDER_GLASS),
    "benthos": ("substrate", Substrate.BENTHIC),
    "coastal": ("position", Position.COASTAL),
    "inland": ("position", Position.INLAND),
    "continuously built": ("built_form", BuiltForm.CONTINUOUS),
    "discontinuously built": ("built_form", BuiltForm.DISCONTINUOUS),
    "built up": ("built_form", BuiltForm.BUILT_UP),
    "vegetation": ("built_form", BuiltForm.VEGETATED),
    "green area": ("built_form", BuiltForm.GREEN_SPACE),
    "green areas": ("built_form", BuiltForm.GREEN_SPACE),
    "infrastructure": ("built_form", BuiltForm.INFRASTRUCTURE),
    "marine infrastructure": ("built_form", BuiltForm.INFRASTRUCTURE),
    "mosaic": ("built_form", BuiltForm.MOSAIC),
    "agricultural": ("built_form", BuiltForm.MOSAIC),
    "rail network": ("infrastructure", Infrastructure.RAIL_NETWORK),
    "road network": ("infrastructure", Infrastructure.ROAD_NETWORK),
    "rail/road embankment": ("infrastructure", Infrastructure.RAIL_ROAD_EMBANKMENT),
    "rail embankment": ("infrastructure", Infrastructure.RAIL_EMBANKMENT),
    "road embankment": ("infrastructure", Infrastructure.ROAD_EMBANKMENT),
    "inert material landfill": ("landfill", LandfillType.INERT_MATERIAL),
    "residual material landfill": ("landfill", LandfillType.RESIDUAL_MATERIAL),
    "sanitary landfill": ("landfill", LandfillType.SANITARY),
    "slag compartment": ("landfill", LandfillType.SLAG_COMPARTMENT),
    "mining": ("activity", SeabedActivity.MINING),
    "oil drilling": ("activity", SeabedActivity.OIL_DRILLING),
    "drilling and mining": ("activity", SeabedActivity.DRILLING_AND_MINING),
    "sediment dumping": ("activity", SeabedActivity.SEDIMENT_DUMPING),
    "fisheries for dredging": ("activity", SeabedActivity.DREDGING),
    "fruit": ("crop_type", CropType.FRUIT),
    "vine": ("crop_type", CropType.VINE),
    "conservation tillage (obsolete)": ("tillage", Tillage.CONSERVATION),
    "conventional tillage (obsolete)": ("tillage", Tillage.CONVENTIONAL),
    "reduced tillage (obsolete)": ("tillage", Tillage.REDUCED),
}

#: Names the vendors write as one token that mean two.  Applied before the
#: split, so the general rule below does not need an exception for each.
REWRITES: tuple[tuple[str, str], ...] = (
    # `(non-use)` is glued onto whatever precedes it: `lake, natural (non-use)`
    # is a natural lake that is not used, which is two statements.
    (" (non-use)", ", non-use"),
    # ...except where the glued pair is the whole qualifier, and says one thing
    # twice: a fallow cropland is by definition not in use.
    ("cropland fallow, non-use", "cropland, fallow"),
)


def strip_direction(name: str) -> tuple[Direction, str]:
    """Split a source name into its direction and its land-class string.

    EF writes the direction as a bare `from `/`to ` and leaves occupation
    unmarked; the SimaPro-lineage lists write `Occupation, ` and
    `Transformation, from `.  Both say the same thing in the same place -- the
    name -- which is why neither can be read off the context.
    """
    lowered = name.lower().strip()
    for prefix, direction in (
        ("occupation, ", Direction.OCCUPATION),
        ("transformation, from ", Direction.TRANSFORMATION_FROM),
        ("transformation, to ", Direction.TRANSFORMATION_TO),
        ("from ", Direction.TRANSFORMATION_FROM),
        ("to ", Direction.TRANSFORMATION_TO),
    ):
        if lowered.startswith(prefix):
            return direction, lowered[len(prefix) :]
    return Direction.OCCUPATION, lowered


def parse(direction: Direction, land_class: str) -> tuple[LandUse | None, list[str]]:
    """Read one land-class string, and report what no axis claimed."""
    text = land_class
    for old, new in REWRITES:
        text = text.replace(old, new)
    parts = [part.strip() for part in text.split(",")]

    cover = None
    rest: list[str] = []
    for width in (3, 2, 1):  # longest head first: `pasture and meadow` before `pasture`
        head = ", ".join(parts[:width])
        if head in COVERS:
            cover, rest = COVERS[head], parts[width:]
            break
    if cover is None:
        return None, parts

    stated: dict[str, Any] = {}
    residue: list[str] = []
    for token in rest:
        if token not in QUALIFIERS:
            residue.append(token)
            continue
        axis, value = QUALIFIERS[token]
        if value is None:
            continue
        if axis in stated and stated[axis] is not value:
            residue.append(f"{token} (clashes on {axis})")
            continue
        stated[axis] = value
    if residue:
        return None, residue
    try:
        return LandUse(direction=direction, cover=cover, **stated), []
    except ProhibitedLandUseCombinationError as error:
        return None, [f"rejected: {error}"]


def without_geography(name: str) -> tuple[str, str | None]:
    """*name* with any trailing place taken off, and the place.

    #290 does this at extraction, so a freshly fetched BAFU file already has
    `Occupation, traffic area, rail network` and a `location` of `CH`.  It is
    done again here because **the fixture must not depend on which extraction
    happens to be on disk**: a vendor file fetched by a checkout that predates
    #290 still has the place in the name, and a land class that appears or
    disappears with the age of a download is not evidence of anything.

    Two of the eleven base labels #290 whitelists are land classes, and both are
    BAFU's Swiss rail rows, so this is not a hypothetical.  Nothing is lost by
    the fold: `location` is part of #290's identity seed, so the Swiss row and
    the unregionalised row stay two flows sharing one land class.
    """
    split = split_geography_suffix(name)
    return split if split else (name, None)
