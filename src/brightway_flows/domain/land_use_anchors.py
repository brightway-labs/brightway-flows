"""Where each land-use axis *value* is anchored, in a published vocabulary.

The material taxonomy cites an authority once per concept.  This cites one per
**enum value**, and computes a land class's anchors from its fields -- so
`(CROPLAND, rainfed, intensive)` states nothing of its own, and the claim that
cropland is `ENVO:01000892` is made once instead of once per class that mentions
cropland.  About fifty anchors instead of a hundred and nineteen blocks, each
checked once, none able to disagree with another class's copy of the same claim.

**Three authorities, split by realm** (`plans/land-class-taxonomy.md` §2.2):

- **ENVO** types the terrestrial cover.  It is what the built and farmed classes
  need, because the whole built environment is one class in IUCN GET (`T7.4`,
  whose own scope note lists "buildings, paved surfaces, transport
  infrastructure, parks and gardens; excavations, bare ground and refuse areas")
  and the source lists characterise those separately.
- **IUCN GET** types the aquatic cover.  ENVO's terrestrial branch does not reach
  the sea floor or a canal; GET has `Biome_M3` deep sea floors and `EFG_F3_5`
  canals, ditches and drains.  :func:`check_cover_authority` makes the split a
  build error rather than a preference.
- **AGROVOC** types the regime -- irrigated against rainfed, intensive against
  organic, clear-felled against coppiced.  Neither of the other two says
  anything about how land is worked.

**`exactMatch` is earned, not assumed.**  Most cover anchors are `closeMatch` or
`broadMatch`, because our value is narrower or coarser than the published class;
most regime anchors are `relatedMatch`, because the AGROVOC concept is a
*practice* and our field says the land is under it.  The material taxonomy
claimed `exactMatch` sixteen times out of seventeen; this scheme claims it
rarely, and saying so is the point.

**Some values are deliberately unanchored.**  `diverse-intensive` is BAFU's
intensity and no published vocabulary carries it: ours, flagged as ours, with an
AGROVOC term request behind it -- the treatment `turbine_water` got.  Silence
here is a recorded decision, and :data:`UNANCHORED` names every one with its
reason, so a new value cannot join them by being forgotten.
"""

from __future__ import annotations

import functools
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

import orjson

from brightway_flows.domain.land_use import (
    BuiltForm,
    CropType,
    Infrastructure,
    Irrigation,
    LandCover,
    LandfillType,
    LandUse,
    ManagementIntensity,
    Origin,
    Position,
    SeabedActivity,
    SilviculturalRegime,
    Substrate,
    SuccessionalStage,
    Tillage,
    UseStatus,
    VegetationForm,
)
from brightway_flows.domain.vocabulary import (
    SKOS_BROAD_MATCH_CURIE,
    SKOS_CLOSE_MATCH_CURIE,
    SKOS_EXACT_MATCH_CURIE,
    SKOS_RELATED_MATCH_CURIE,
)
from brightway_flows.filesystem import PACKAGE_DATA_DIR

DATA_DIR = PACKAGE_DATA_DIR

#: What the three authorities say about every class this module cites, pinned.
#: Package data rather than a live lookup, for the reason `domain/materials.py`
#: gives: a suite that reached OLS4 would fail on a train, and one that reached
#: it in CI would make an EBI outage look like a broken commit.
SNAPSHOT_FILEPATH = DATA_DIR / "land-anchor-snapshot.json"


class Authority(StrEnum):
    ENVO = "envo"
    GET = "get"
    AGROVOC = "agrovoc"


class Realm(StrEnum):
    """Which authority a cover must cite, and why there are two of them."""

    TERRESTRIAL = "terrestrial"
    AQUATIC = "aquatic"


#: SKOS mapping predicates, in decreasing order of the claim they make.
#:
#: Aliased from `domain/vocabulary.py` rather than written out.  A CURIE spelled
#: here as a literal is a second declaration of a term the registry already owns,
#: which is the divergent-copies problem that module exists to stop -- and
#: `tests/test_vocabulary.py` fails on it, which is how this comment came to be
#: written.
EXACT_MATCH = SKOS_EXACT_MATCH_CURIE
CLOSE_MATCH = SKOS_CLOSE_MATCH_CURIE
BROAD_MATCH = SKOS_BROAD_MATCH_CURIE
RELATED_MATCH = SKOS_RELATED_MATCH_CURIE


@dataclass(frozen=True, slots=True)
class Anchor:
    """One citation: which authority, which class, and how strong the claim."""

    authority: Authority
    identifier: str
    label: str
    predicate: str
    comment: str = ""

    @property
    def iri(self) -> str:
        if self.authority is Authority.ENVO:
            return f"http://purl.obolibrary.org/obo/{self.identifier}"
        if self.authority is Authority.GET:
            return f"https://w3id.org/iucn-get/{self.identifier}"
        return f"http://aims.fao.org/aos/agrovoc/{self.identifier}"


#: Which realm each cover belongs to.  Every cover appears exactly once, so a
#: new cover cannot be added without answering the question.
COVER_REALMS: dict[LandCover, Realm] = {
    LandCover.CROPLAND: Realm.TERRESTRIAL,
    LandCover.PERMANENT_CROPLAND: Realm.TERRESTRIAL,
    LandCover.PASTURE: Realm.TERRESTRIAL,
    LandCover.AGRICULTURE: Realm.TERRESTRIAL,
    LandCover.FIELD_MARGIN: Realm.TERRESTRIAL,
    LandCover.FOREST: Realm.TERRESTRIAL,
    LandCover.TROPICAL_RAINFOREST: Realm.TERRESTRIAL,
    LandCover.SHRUBLAND: Realm.TERRESTRIAL,
    LandCover.GRASSLAND: Realm.TERRESTRIAL,
    LandCover.GRASSLAND_PASTURE_MEADOW: Realm.TERRESTRIAL,
    LandCover.WETLAND: Realm.TERRESTRIAL,
    LandCover.BARREN: Realm.TERRESTRIAL,
    LandCover.SNOW_AND_ICE: Realm.TERRESTRIAL,
    LandCover.URBAN: Realm.TERRESTRIAL,
    LandCover.INDUSTRIAL: Realm.TERRESTRIAL,
    LandCover.TRAFFIC: Realm.TERRESTRIAL,
    LandCover.ARTIFICIAL: Realm.TERRESTRIAL,
    LandCover.CONSTRUCTION_SITE: Realm.TERRESTRIAL,
    LandCover.EXTRACTION_SITE: Realm.TERRESTRIAL,
    LandCover.DUMP_SITE: Realm.TERRESTRIAL,
    LandCover.SEALED: Realm.TERRESTRIAL,
    LandCover.URBAN_INDUSTRIAL_FALLOW: Realm.TERRESTRIAL,
    LandCover.UNSPECIFIED: Realm.TERRESTRIAL,
    LandCover.LAKE: Realm.AQUATIC,
    LandCover.RIVER: Realm.AQUATIC,
    LandCover.INLAND_WATER: Realm.AQUATIC,
    LandCover.WATER_BODY: Realm.AQUATIC,
    LandCover.WATERCOURSE: Realm.AQUATIC,
    LandCover.SEA: Realm.AQUATIC,
    LandCover.SEABED: Realm.AQUATIC,
}


COVER_ANCHORS: dict[LandCover, Anchor] = {
    # ── terrestrial: ENVO ──
    LandCover.CROPLAND: Anchor(
        Authority.ENVO, "ENVO_01000892", "area of cropland", EXACT_MATCH
    ),
    LandCover.PASTURE: Anchor(
        Authority.ENVO,
        "ENVO_01000891",
        "area of pastureland or hayfields",
        EXACT_MATCH,
        "EF writes this cover `pasture/meadow`, which is the same pair.",
    ),
    LandCover.AGRICULTURE: Anchor(
        Authority.ENVO,
        "ENVO_01000311",
        "cultivated environment",
        BROAD_MATCH,
        "`agriculture, mosaic` is a patchwork of cultivation, not a cultivation type.",
    ),
    LandCover.FIELD_MARGIN: Anchor(
        Authority.ENVO,
        "ENVO_00000046",
        "hedge",
        CLOSE_MATCH,
        "A field margin is often but not always a hedge.",
    ),
    LandCover.FOREST: Anchor(
        Authority.ENVO, "ENVO_00000111", "forested area", EXACT_MATCH
    ),
    LandCover.TROPICAL_RAINFOREST: Anchor(
        Authority.ENVO,
        "ENVO_01000228",
        "tropical moist broadleaf forest biome",
        CLOSE_MATCH,
        "ENVO's class is a biome; ours is a stand of it.",
    ),
    LandCover.SHRUBLAND: Anchor(
        Authority.ENVO, "ENVO_00000300", "scrubland area", EXACT_MATCH
    ),
    LandCover.GRASSLAND: Anchor(
        Authority.ENVO, "ENVO_00000106", "grassland area", EXACT_MATCH
    ),
    #: Related, and deliberately not an equivalence or a subsumption.
    #:
    #: This cover is the union of grassland and of pastureland-or-hayfields, and
    #: ENVO has no class for it.  The two nearest candidates were both checked
    #: against OLS4 rather than guessed: `area of gramanoid or herbaceous
    #: vegetation` (ENVO_01000888) subsumes `area of pastureland or hayfields`
    #: and does **not** subsume `grassland area`, so it is not the union; and
    #: `vegetated area` (ENVO_01001305) does subsume both, and also forest,
    #: cropland and wetland, so as a published type it would say almost nothing
    #: about the land.
    #:
    #: So the citation is `relatedMatch` to the grassland class this cover is
    #: nearest to, which claims no containment in either direction and leaves a
    #: type a consumer can still group on.  An `exactMatch` here would assert
    #: that ENVO's grassland area takes in hayfields, which is exactly the
    #: statement EF's three-way split denies.
    LandCover.GRASSLAND_PASTURE_MEADOW: Anchor(
        Authority.ENVO,
        "ENVO_00000106",
        "grassland area",
        RELATED_MATCH,
        "EF writes this cover `grassland/pasture/meadow`: the union of "
        "grassland and of pastureland or hayfields, which ENVO carries as two "
        "classes under different parents and does not carry together.",
    ),
    LandCover.WETLAND: Anchor(
        Authority.ENVO, "ENVO_00000043", "wetland area", EXACT_MATCH
    ),
    LandCover.BARREN: Anchor(
        Authority.ENVO, "ENVO_01000752", "area of barren land", EXACT_MATCH
    ),
    LandCover.SNOW_AND_ICE: Anchor(
        Authority.ENVO, "ENVO_01000746", "area of perennial ice or snow", EXACT_MATCH
    ),
    LandCover.URBAN: Anchor(
        Authority.ENVO, "ENVO_01001269", "area of developed space", EXACT_MATCH
    ),
    LandCover.INDUSTRIAL: Anchor(
        Authority.ENVO,
        "ENVO_01000886",
        "area of developed space with high usage intensity",
        CLOSE_MATCH,
        "Industry is one kind of high-intensity developed space, not the whole.",
    ),
    LandCover.TRAFFIC: Anchor(
        Authority.ENVO,
        "ENVO_00000010",
        "transport feature",
        BROAD_MATCH,
        "ENVO's class is the feature; ours is the land it occupies.",
    ),
    LandCover.ARTIFICIAL: Anchor(
        Authority.ENVO,
        "ENVO_01001200",
        "anthropised terrestrial environmental zone",
        BROAD_MATCH,
        "EF's `artificial areas` is CORINE's level 1, coarser than urban.",
    ),
    LandCover.CONSTRUCTION_SITE: Anchor(
        Authority.ENVO,
        "ENVO_01001813",
        "construction",
        RELATED_MATCH,
        "ENVO has the process; our cover is land under it.",
    ),
    LandCover.EXTRACTION_SITE: Anchor(
        Authority.ENVO,
        "ENVO_00000284",
        "quarry",
        CLOSE_MATCH,
        "A mineral extraction site may be a mine rather than a quarry.",
    ),
    LandCover.DUMP_SITE: Anchor(
        Authority.ENVO, "ENVO_00000533", "landfill", EXACT_MATCH
    ),
    LandCover.SEALED: Anchor(
        Authority.AGROVOC,
        "c_f9554e7c",
        "soil sealing",
        RELATED_MATCH,
        "No ENVO class for sealed ground; AGROVOC has the process that makes it.",
    ),
    LandCover.URBAN_INDUSTRIAL_FALLOW: Anchor(
        Authority.AGROVOC,
        "c_6",
        "abandoned land",
        CLOSE_MATCH,
        "EF's `urban/industrial fallow`. AGROVOC's class does not say the "
        "abandoned use was urban or industrial, which ours does.",
    ),
    LandCover.PERMANENT_CROPLAND: Anchor(
        Authority.AGROVOC,
        "c_23fa0b98",
        "permanent crops",
        EXACT_MATCH,
        "ENVO has `orchard`, which excludes vineyards and other permanent crops.",
    ),
    # ── aquatic: IUCN GET ──
    LandCover.LAKE: Anchor(
        Authority.GET, "Biome_F2", "Lakes biome", EXACT_MATCH
    ),
    LandCover.RIVER: Anchor(
        Authority.GET, "Biome_F1", "Rivers and streams biome", EXACT_MATCH
    ),
    LandCover.INLAND_WATER: Anchor(
        Authority.GET,
        "Realm_F",
        "Freshwater",
        BROAD_MATCH,
        "`inland water bodies` does not say lake or river, so neither do we.",
    ),
    LandCover.WATER_BODY: Anchor(
        Authority.GET,
        "Realm_F",
        "Freshwater",
        BROAD_MATCH,
        "EF's `water bodies` names no kind of water body, so neither do we.",
    ),
    LandCover.WATERCOURSE: Anchor(
        Authority.GET,
        "EFG_F3_5",
        "Canals, ditches and drains",
        EXACT_MATCH,
        "Observed only as `water courses, artificial`, which is this group.",
    ),
    LandCover.SEA: Anchor(
        Authority.GET,
        "Realm_M",
        "Marine",
        BROAD_MATCH,
        "BAFU's `sea and ocean` is the realm, not a biome within it.",
    ),
    LandCover.SEABED: Anchor(
        Authority.GET,
        "Biome_M3",
        "Deep sea floors biome",
        CLOSE_MATCH,
        "Our seabed also covers the shelf, which GET files under `Biome_M1`.",
    ),
}


REGIME_ANCHORS: dict[StrEnum, Anchor] = {
    Irrigation.IRRIGATED: Anchor(
        Authority.AGROVOC, "c_3952", "irrigated farming", RELATED_MATCH
    ),
    Irrigation.RAINFED: Anchor(
        Authority.AGROVOC, "c_6436", "rainfed farming", RELATED_MATCH
    ),
    ManagementIntensity.INTENSIVE: Anchor(
        Authority.AGROVOC, "c_3906", "intensive farming", RELATED_MATCH
    ),
    ManagementIntensity.EXTENSIVE: Anchor(
        Authority.AGROVOC, "c_2763", "extensive farming", RELATED_MATCH
    ),
    ManagementIntensity.ORGANIC: Anchor(
        Authority.AGROVOC, "c_15911", "organic agriculture", RELATED_MATCH
    ),
    UseStatus.FALLOW: Anchor(Authority.AGROVOC, "c_34007", "fallow", RELATED_MATCH),
    UseStatus.GRAZED: Anchor(Authority.AGROVOC, "c_25243", "grazing", RELATED_MATCH),
    SuccessionalStage.PRIMARY: Anchor(
        Authority.AGROVOC,
        "c_28112",
        "primary forests",
        CLOSE_MATCH,
        "AGROVOC's concept is the forest; ours is the successional stage of "
        "one, which is why this axis is stated of `forest` rather than being "
        "a cover of its own.",
    ),
    SuccessionalStage.SECONDARY: Anchor(
        Authority.AGROVOC,
        "c_28144",
        "secondary forests",
        CLOSE_MATCH,
        "As `PRIMARY`.",
    ),
    SilviculturalRegime.CLEAR_CUTTING: Anchor(
        Authority.AGROVOC, "c_16170", "clearfelling", RELATED_MATCH
    ),
    SilviculturalRegime.SHORT_ROTATION: Anchor(
        Authority.AGROVOC,
        "c_1872",
        "coppicing",
        CLOSE_MATCH,
        "Coppice is the common short-rotation system, not the only one.",
    ),
    VegetationForm.UNDER_GLASS: Anchor(
        Authority.AGROVOC, "c_3377", "greenhouse crops", RELATED_MATCH
    ),
    VegetationForm.FLOODED: Anchor(
        Authority.AGROVOC,
        "c_34891",
        "rice fields",
        CLOSE_MATCH,
        "Rice is the flooded crop the lists mean; the class is not only rice.",
    ),
    Substrate.BENTHIC: Anchor(
        Authority.AGROVOC, "c_877", "benthic environment", RELATED_MATCH
    ),
    Infrastructure.RAIL_NETWORK: Anchor(
        Authority.ENVO, "ENVO_00000065", "railway", RELATED_MATCH
    ),
    Infrastructure.ROAD_NETWORK: Anchor(
        Authority.ENVO, "ENVO_00000064", "road", RELATED_MATCH
    ),
    LandfillType.SANITARY: Anchor(
        Authority.AGROVOC,
        "c_35171",
        "landfills",
        BROAD_MATCH,
        "AGROVOC has landfills as a class and not the four acceptance "
        "categories the lists split them into; this is the nearest, and it is "
        "the parent of all four rather than the one they mean.",
    ),
    SeabedActivity.MINING: Anchor(
        Authority.AGROVOC, "c_49983", "mining", RELATED_MATCH
    ),
    SeabedActivity.DRILLING_AND_MINING: Anchor(
        Authority.AGROVOC,
        "c_49983",
        "mining",
        BROAD_MATCH,
        "ecoinvent's `seabed, drilling and mining` names two activities and "
        "AGROVOC has one of them, so the citation covers less than the value.",
    ),
    SeabedActivity.DREDGING: Anchor(
        Authority.AGROVOC, "c_50c7fa97", "dredging", RELATED_MATCH
    ),
    CropType.FRUIT: Anchor(
        Authority.AGROVOC, "c_3120", "fruit crops", RELATED_MATCH
    ),
    CropType.VINE: Anchor(
        Authority.AGROVOC,
        "c_15203",
        "vineyards",
        RELATED_MATCH,
        "AGRIBALYSE's `permanent crop, vine` (#351) states the crop; AGROVOC's "
        "concept is the land planted with it, the same relation FRUIT's "
        "`fruit crops` anchor records.",
    ),
}


#: Every axis value with no anchor, and why.  Listed rather than left implicit:
#: silence about a value should be a decision someone made, and a new value that
#: nobody anchored should fail :func:`check_every_value_is_decided` rather than
#: join this set by default.
UNANCHORED: dict[StrEnum, str] = {
    LandCover.UNSPECIFIED: (
        "Not a cover. The source said nothing, and citing a class for that "
        "would turn silence into a claim."
    ),
    ManagementIntensity.DIVERSE_INTENSIVE: (
        "BAFU's, and Swiss agricultural LCA's. No published vocabulary carries "
        "it; ours, with an AGROVOC term request behind it (plan §6.1)."
    ),
    ManagementIntensity.INTEGRATED: (
        "Swiss integrated production, which Stepwise 2006 carries from "
        "ecoinvent 2 as `arable, integrated`. The same shape as "
        "`DIVERSE_INTENSIVE`: a farming system Swiss agricultural LCA names "
        "and no published vocabulary has a class for. AGROVOC's nearest terms "
        "are about integrated pest and nutrient management, which is a "
        "practice inside the system rather than the system, so citing one "
        "would say something narrower than the lists mean."
    ),
    SilviculturalRegime.NORMAL_ROTATION: (
        "BAFU's `forest, intensive, normal`: a rotation of ordinary length, "
        "which is a statement about the other two rather than a named regime."
    ),
    VegetationForm.SCLEROPHYLLOUS: (
        "A leaf physiognomy. ENVO has sclerophyllous *biomes* but no class for "
        "the trait as a qualifier of a shrubland area."
    ),
    UseStatus.USED: "The complement of `not used`, and no vocabulary names it.",
    UseStatus.UNUSED: (
        "`natural (non-use)` in ecoinvent's spelling. AGROVOC's `protected "
        "areas` is a designation rather than the absence of use."
    ),
    Origin.NATURAL: "Whether a cover is there by nature is ours to say.",
    Origin.ARTIFICIAL: "As above.",
    Origin.MAN_MADE: "As above; ecoinvent's spelling of `artificial` for pasture.",
    Position.COASTAL: "Where a wetland sits, which no wetland vocabulary splits.",
    Position.INLAND: "As above.",
    BuiltForm.CONTINUOUS: "CORINE's `continuous urban fabric` has no SKOS class.",
    BuiltForm.DISCONTINUOUS: "As above.",
    BuiltForm.BUILT_UP: "BAFU's split of an industrial area into built and green.",
    BuiltForm.VEGETATED: "As above.",
    BuiltForm.GREEN_SPACE: "EF's `urban, green areas`.",
    BuiltForm.INFRASTRUCTURE: "A structure on a site, not a kind of site.",
    BuiltForm.MOSAIC: "A patchwork, which is a spatial pattern rather than a class.",
    Infrastructure.RAIL_ROAD_EMBANKMENT: "An embankment carrying either or both.",
    Infrastructure.RAIL_EMBANKMENT: "As above; the railway half on its own.",
    Infrastructure.ROAD_EMBANKMENT: "As above.",
    LandfillType.INERT_MATERIAL: "A waste-acceptance class, not an environmental one.",
    LandfillType.RESIDUAL_MATERIAL: "As above.",
    LandfillType.SLAG_COMPARTMENT: "As above.",
    SeabedActivity.OIL_DRILLING: "AGROVOC has neither offshore drilling nor its site.",
    SeabedActivity.SEDIMENT_DUMPING: "As above.",
    Tillage.CONSERVATION: "ecoinvent's, and obsolete in ecoinvent.",
    Tillage.CONVENTIONAL: "As above.",
    Tillage.REDUCED: "As above.",
}


class LandAnchorError(Exception):
    pass


def anchors_for(land_use: LandUse) -> list[Anchor]:
    """Every citation *land_use* makes, computed from its fields.

    A land class asserts nothing of its own: it is cropland because its `cover`
    is, and rainfed because its `irrigation` is.  Two classes sharing a field
    therefore share that field's citation exactly, and cannot drift apart.
    """
    found = []
    cover_anchor = COVER_ANCHORS.get(land_use.cover)
    if cover_anchor is not None:
        found.append(cover_anchor)
    for value in land_use.qualifiers().values():
        anchor = REGIME_ANCHORS.get(value)
        if anchor is not None:
            found.append(anchor)
    return found


def check_cover_authority() -> None:
    """A terrestrial cover cites ENVO; an aquatic one cites GET.

    The realm decides, not a curator's preference.  ENVO's terrestrial branch
    does not reach a sea floor and GET's `T7.4` is the whole built environment
    at once, so a cover citing the wrong side of that line is a mistake rather
    than a judgement call -- and this makes it a build error.

    AGROVOC is admitted on the terrestrial side for the two covers where ENVO
    has nothing (`permanent cropland`, `sealed soil`); it is never admitted for
    an aquatic cover, because GET covers the water completely.
    """
    for cover, anchor in COVER_ANCHORS.items():
        realm = COVER_REALMS[cover]
        if realm is Realm.AQUATIC and anchor.authority is not Authority.GET:
            raise LandAnchorError(
                f"{cover.name} is aquatic and must cite IUCN GET, "
                f"not {anchor.authority.value}"
            )
        if realm is Realm.TERRESTRIAL and anchor.authority is Authority.GET:
            raise LandAnchorError(
                f"{cover.name} is terrestrial; GET has one class for the whole "
                "built environment, so it cannot type this cover"
            )


def check_every_value_is_decided() -> None:
    """Every enum value is either anchored or explicitly recorded as ours.

    The failure this prevents is a new axis value shipping with no citation
    because nobody thought about it, which looks exactly like a value we decided
    to leave unanchored.
    """
    from brightway_flows.domain.land_use import QUALIFIER_AXES

    undecided = [
        value
        for enum in (LandCover, *QUALIFIER_AXES.values())
        for value in enum
        if value not in COVER_ANCHORS
        and value not in REGIME_ANCHORS
        and value not in UNANCHORED
    ]
    if undecided:
        raise LandAnchorError(
            "no anchor and no recorded reason for: "
            + ", ".join(f"{value.__class__.__name__}.{value.name}" for value in undecided)
        )


@functools.cache
def anchor_snapshot() -> dict[str, Any]:
    """What ENVO, GET and AGROVOC actually say about every class cited here.

    :raises FileNotFoundError: if the snapshot is absent.  Not optional -- with
        no snapshot nothing is checked, which would look like a clean run that
        verified everything.
    """
    if not SNAPSHOT_FILEPATH.exists():
        raise FileNotFoundError(
            f"Land anchor snapshot not found at {SNAPSHOT_FILEPATH}. "
            "Run `uv run python tools/resolve_land_anchors.py`."
        )
    return orjson.loads(SNAPSHOT_FILEPATH.read_bytes())


def cited_identifiers() -> dict[Authority, set[str]]:
    """Every identifier this module cites, by authority."""
    cited: dict[Authority, set[str]] = {authority: set() for authority in Authority}
    for anchor in (*COVER_ANCHORS.values(), *REGIME_ANCHORS.values()):
        cited[anchor.authority].add(anchor.identifier)
    return cited
