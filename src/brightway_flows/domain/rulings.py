"""Every curated file in ``data/``, and what each one is.

Twenty-odd files there are a curator's decisions that the pipeline must honour.
They were implemented twenty times: eight packages, nine filename suffixes
(``-decisions``, ``-overrides``, ``-manual-fixes``, ``-allowlist``,
``-keep-list``, ``-groupings``, ``-routing``, ``-mapping``, ``-snapshot``), five
loaders returning a record and fifteen returning a bag, and four caching
conventions. Nothing said which files were rulings, so nothing could say whether
a new one followed any of it (#92).

This is the register. Adding a file to ``data/`` means adding a row here, and
``tests/test_ruling_convention.py`` fails otherwise -- which is the only part of
a convention that survives contact with the next change.

Three kinds, because they are genuinely different things and lumping them is
what made the mess look like one problem:

* :data:`RULINGS` -- a curator overruled the pipeline. Somebody looked at a
  case, decided, and wrote down why. These are the ones a reviewer wants listed
  in one place.
* :data:`VOCABULARIES` -- what the words mean: the context registry, the unit
  table, the material and land-use taxonomies. Authored, not decided; a curator
  does not "rule" that a kilogram is a kilogram.
* :data:`REFERENCE_DATA` -- bulk data that ships with the package because
  fetching it is slow or impossible, e.g. the EC inventory.

## Where a ruling lives

**Beside the stage that applies it, not in a ``rulings/`` package.** That was
the open question in ``plans/architecture-consistency.md``, and this is the
answer with what it gives up.

A ruling is only intelligible next to the rule it overrides.
``pipeline/collision_decisions.py`` is 370 lines and most of them are prose
explaining why deduplication cannot answer the question it answers -- prose that
means nothing away from ``pipeline/collisions.py`` and
``pipeline/deduplication.py``. The same is true of ``flow_layers/contested_cas``
beside the layering, and ``merge/unit_changes`` beside the conversions. Moving
twenty modules would break that adjacency and produce a very large diff for it.

What that gives up is a directory to browse, and this module is the compensation:
one place that lists every ruling and names the module applying it.

## What a loader looks like

Two rules, one of which most loaders already followed by accident and one of
which fifteen of them broke.

1. **Return records, or an index of them -- never a bag.** A ``dict[str, Any]``
   out of a loader is a curator's decision that nothing type-checks: spell a
   field wrong at the reading end and the answer is ``None``, so the ruling
   silently does not apply. ``contested-cas-decisions.json`` was read that way
   until #95.

   **Except where the whole decision is membership, and then it is a set.**
   ``altlabel-keep-list.json`` is a list of labels a curator has ruled are
   names, and the only question asked of it is whether a label is one of them;
   wrapping each in a record would buy nothing and make the membership test
   worse. What decides is what the reading end asks -- a *field*, or
   *membership* -- and five of the twenty loaders ask the second.

   This is not a rule about vocabularies or reference data. A vocabulary is a
   table the code looks things up in and reference data is bulk data somebody
   else published; neither is a decision with fields. Two rulings have no loader
   at all: ``*-manual-fixes.json`` and ``*-additional-flows.json`` are
   randonneur payloads applied to a vendor list before this project's records
   exist, and stay dicts for the reason rule 2 gives.

2. **Cache exactly when the path is fixed.** A loader taking an injectable
   ``path`` so a test can point it at a fixture must *not* be cached, because
   the cache would serve the first test's file to the second. A loader taking
   nothing should be, because it is read once per run and re-parsing a file per
   call is how the transform chain got slow (#296). A loader taking some other
   argument -- the list being merged -- decides for itself: the cache is keyed,
   so it is a question about how often the answer is asked for. This rule was
   already being followed by every loader that thought about it and by none that
   did not, and is stated here rather than rediscovered.

Both are checked in ``tests/test_ruling_convention.py``, over a register of
every ruling's loader, which also fails when a ruling is added with no loader
listed. The register there is the second half of this one: this module says what
each file decides, and that one says what reads it and what it hands back.

## What version a ruling file carries

Its own. Two of these files version their on-disk format --
``elementary-flow-collision-decisions.json`` and
``prepared-context-decisions.json`` -- and the two formats have nothing to do
with each other, so each module spells it ``DECISIONS_SCHEMA_VERSION`` and
neither exports it. The bare ``SCHEMA_VERSION`` belongs to
:mod:`brightway_flows.domain.schema`, and means the version of the list
this project publishes.

All three were spelled ``SCHEMA_VERSION`` until #98, which is one name for
three unrelated numbers: a reader who grepped it to find out what version the
list publishes got three answers, and the two ruling files could not be
discussed without saying which module first.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from brightway_flows.filesystem import PACKAGE_DATA_DIR


@dataclass(frozen=True)
class CuratedFile:
    """One file in ``data/``, and what reads it."""

    #: The filename, or -- for a file per source list -- the pattern with the
    #: list's key standing in for its own segment, e.g. ``*-manual-fixes.json``.
    filename: str
    #: Dotted path of the module that reads it. One module, always: two readers
    #: of one curated file is how ``context-manual-mapping.json`` came to have
    #: two path constants pointing at it.
    applied_by: str
    #: What it decides, in a sentence a curator would recognise.
    decides: str
    #: True when a source manifest in ``data/sources/`` names the file and
    #: ``applied_by`` only resolves it. Adding one of these is a manifest edit
    #: and not a Python change, which is the whole point of the manifests -- so
    #: the module that reads it never mentions it, and a check that looked for
    #: the filename in the module would be checking the wrong thing.
    named_by_manifest: bool = False

    @property
    def is_pattern(self) -> bool:
        return "*" in self.filename

    @property
    def path(self) -> Path:
        """Where the file is. Meaningless for a pattern, which names many."""
        return PACKAGE_DATA_DIR / self.filename


#: A curator looked at a case, overruled the pipeline, and wrote down why.
RULINGS: tuple[CuratedFile, ...] = (
    CuratedFile(
        "elementary-flow-collision-decisions.json",
        "brightway_flows.pipeline.collision_decisions",
        "Two live flows of one substance in one context are one flow, and this "
        "is the one to keep.",
    ),
    CuratedFile(
        "lcia-factor-rulings.json",
        "brightway_flows.lcia.rulings",
        "Two implementations of EF 3.1 state different factors for this "
        "substance and category and this says whose to publish, or only one "
        "states a factor at all and this says whether to publish it.",
    ),
    CuratedFile(
        "lcia-factor-adoptions.json",
        "brightway_flows.lcia.adoptions",
        "Only a transcription characterises this substance, and its number is "
        "another substance's -- an ion's element, a named pesticide's "
        "catch-all, a subtype of land's family, a mineral's elements weighted by "
        "the formula -- and a person signed for it: adopt, and the factors "
        "publish as `adopted`; decline, and the row stays answered on the "
        "queue. The only way a number crosses a substance boundary. Keyed on "
        "the recipient substance and bounded by the categories named; pinned to "
        "the numbers only where the reason is arithmetic.",
    ),
    CuratedFile(
        "lcia-factor-adoptions-stepwise-2006.json",
        "brightway_flows.lcia.adoptions",
        "Stepwise 2006 names no ion of the metals it characterises, so nobody "
        "states anything for `Zinc(2+)` and every ecoinvent zinc emission scores "
        "nothing (#197). Each entry is one ion a person signed to take its "
        "element's published number, context for context, in the categories "
        "named; the factors publish as `adopted` and name the element's flow. "
        "Never a recipient the publisher characterised itself -- chromium's "
        "states stay as Stepwise left them.",
    ),
    CuratedFile(
        "lcia-substance-decisions.json",
        "brightway_flows.lcia.substance_decisions",
        "This implementation names a substance in a spelling of its own and "
        "states no registry number for it, and this is the flow of ours the row "
        "is about -- or, on a declined row, the reasoning for putting its "
        "numbers nowhere. Written from the publisher's own package, where the "
        "same name resolves by identifier in the compartments it can be read "
        "in.",
    ),
    CuratedFile(
        "lcia-misattributed-factors.json",
        "brightway_flows.lcia.misattributions",
        "This factor is stated against a substance it is not about, and belongs "
        "to that one instead. Not a ruling between numbers -- the pipeline sees "
        "nothing inconsistent, because both transcriptions agree and no "
        "implementation states the factor for the right substance at all.",
    ),
    CuratedFile(
        "context-carry-rules.json",
        "brightway_flows.lcia.context_carry",
        "A flow of ours has no characterisation factor and the same substance "
        "is characterised in a neighbouring context of the same class, and "
        "this says which neighbour's number it takes, if any: silvicultural "
        "soil takes non-agricultural soil's, a river takes surface water's, "
        "the unconfined aquifer takes nobody's. One convention of ours, the "
        "same for every method, with the walls nothing crosses; decided class "
        "by class from the census of the blanks, and never from a publisher's "
        "habit or a pattern in the numbers.",
    ),
    CuratedFile(
        "particle-size-carry-rules.json",
        "brightway_flows.lcia.size_class_carry",
        "A particle flow of one size window has no characterisation factor and "
        "the same category characterises a broader window of the family in the "
        "same compartment, and this says which window's number it takes: the "
        "coarse band takes PM10's, the ultrafine cut takes PM2.5's, the above-"
        "ten fraction takes the size-unstated total's. One convention of ours, "
        "the same for every method, run inside the compartment before the "
        "compartment convention; decided window by window from the census of "
        "what each publisher states.",
    ),
    CuratedFile(
        "lcia-factor-collision-rulings.json",
        "brightway_flows.lcia.collision_rulings",
        "Two rows of one implementation reach one consensus flow and state "
        "numbers too far apart to be one number, and -- where the matching is "
        "right and the publisher scored two spellings of one thing differently "
        "-- this says whose number the consensus takes. Keyed on the substance, "
        "the category and the compartment; pinned to what every colliding row "
        "stated when it was written.",
    ),
    CuratedFile(
        "lcia-rounded-printings.json",
        "brightway_flows.lcia.precision",
        "This implementation's amount is a rounded printing of a number its own "
        "source states more precisely, and this is the precise value. Not a "
        "ruling between numbers -- nobody disagrees, the two printings are one "
        "assessment, and the rounded one only reaches the published list in the "
        "compartments where the other implementation has no flow.",
    ),
    CuratedFile(
        "preferred-label-decisions.json",
        "brightway_flows.domain.preferred_label_decisions",
        "This proposed rename of a published name is right, or it is wrong.",
    ),
    CuratedFile(
        "contested-cas-decisions.json",
        "brightway_flows.flow_layers.contested_cas",
        "Several flow names in one list carry this registry number, and this "
        "says whether they are one substance.",
    ),
    CuratedFile(
        "commonchemistry-structure-decisions.json",
        "brightway_flows.integrations.commonchemistry",
        "Common Chemistry disagrees with a candidate structure, and this says "
        "which side stands.",
    ),
    CuratedFile(
        "source-name-places.json",
        "brightway_flows.flow_layers.synonyms",
        "This source name says where the flow is rather than what the substance "
        "is, so it is not carried as another name for the substance.",
    ),
    CuratedFile(
        "prepared-context-decisions.json",
        "brightway_flows.merge.prepared_context_decisions",
        "A prepared match points at a context the target does not cover, and "
        "this says whether that is expected.",
    ),
    CuratedFile(
        "land-flow-groupings.json",
        "brightway_flows.merge.land_groupings",
        "Several of a source list's land classes are published as one consensus "
        "flow, and this says that is meant, and why.",
    ),
    CuratedFile(
        "created-flow-unit-decisions.json",
        "brightway_flows.merge.unit_changes",
        "Source rows creating one flow disagree about its unit, and this is "
        "the unit it takes.",
    ),
    CuratedFile(
        "published-units.json",
        "brightway_flows.merge.unit_changes",
        "This list publishes this quantity kind in this unit -- the "
        "kilobecquerel for an activity -- so a flow minted from a row on the "
        "same scale states it, whatever the row arrived in.",
    ),
    CuratedFile(
        "unit-change-allowlist.json",
        "brightway_flows.merge.unit_changes",
        "This match may cross units, because the conversion is known and "
        "intended.",
    ),
    CuratedFile(
        "flow-object-overrides.json",
        "brightway_flows.flow_layers.layering",
        "These flows are one substance, or this flow is not the substance the "
        "layering would group it with.",
    ),
    CuratedFile(
        "*-match-overrides.json",
        "brightway_flows.match_overrides",
        "This flow maps here -- since #141 these files are the whole "
        "prepared correspondence, appended onto the empty table every "
        "manifest declares. A decline row (\"or nowhere\") is the surviving "
        "mechanism of the table era; the four carbon rows of #334 are the "
        "only ones left, and with no table they are documentary.",
    ),
    CuratedFile(
        "*-manual-fixes.json",
        "brightway_flows.manual_fixes",
        "The vendor got this field wrong on this source flow.",
    ),
    CuratedFile(
        "ecoinvent-unmatched-pesticide-groupings.json",
        "brightway_flows.sources",
        "These unmatched source rows belong on this existing flow object.",
        named_by_manifest=True,
    ),
    *(
        CuratedFile(
            f"ecoinvent-{version}-additional-flows.json",
            "brightway_flows.additional_flows",
            "These flows are added to a source list that does not ship them, "
            "and these are the ecoinvent system models that were compared to "
            "find them.",
            named_by_manifest=True,
        )
        # One per registered ecoinvent, four of them holding no flows at all.
        # An empty file is the ruling that the version's four system models were
        # compared and agreed; without it, that is indistinguishable from nobody
        # having looked (#100).
        for version in ("3.8", "3.9.1", "3.10.1", "3.11", "3.12")
    ),
    CuratedFile(
        "stepwise-2006-additional-flows.json",
        "brightway_flows.additional_flows",
        "Stepwise 2006 ships every flow it has in the one file the adapter "
        "reads, so this file adds nothing and exists for its other half: the "
        "source rows this list examined and refused, with the reason each is "
        "published under.",
        named_by_manifest=True,
    ),
    CuratedFile(
        "agribalyse-3.2-additional-flows.json",
        "brightway_flows.additional_flows",
        "AGRIBALYSE 3.2 ships every flow it has in the one export the adapter "
        "reads, so this file adds nothing and exists for its refusals: the 43 "
        "`Final waste flows` rows, examined and deliberately not mapped -- an "
        "accounting device at the product-system boundary, not exchanges with "
        "the environment -- each published as an excluded source concept "
        "(#189).",
        named_by_manifest=True,
    ),
    CuratedFile(
        "correspondence-context-routing.json",
        "brightway_flows.correspondence_contexts",
        "This correspondence row may map to a coarser context than its source, "
        "and this says which coarsenings are permitted.",
    ),
    CuratedFile(
        "context-manual-mapping.json",
        "brightway_flows.context_mapping",
        "This source list's compartment means this consensus context.",
    ),
    CuratedFile(
        "altlabel-keep-list.json",
        "brightway_flows.transformers.strip_catalogue_altlabels",
        "This alternative label looks like a catalogue code and is a real name.",
    ),
    CuratedFile(
        "colour-index-names.json",
        "brightway_flows.transformers.strip_product_families",
        "These names are Colour Index designations, so a family rule must not "
        "read them as a product family.",
    ),
    CuratedFile(
        "chebi-roles.json",
        "brightway_flows.flow_layers.roles",
        "These ChEBI role classes are the ones worth publishing; the rest of "
        "the tree is biomedical.",
    ),
    CuratedFile(
        "curated-chebi-roles.json",
        "brightway_flows.flow_layers.roles",
        "ChEBI asserts no role for this substance, and this is what it is used "
        "for, on a published source that says so.",
    ),
    CuratedFile(
        "non-material-interventions.json",
        "brightway_flows.flow_layers.non_material",
        "These flows are not substances, and these are the families they "
        "belong to.",
    ),
    CuratedFile(
        "retired-minted-flow-ids.json",
        "brightway_flows.pipeline.redirects",
        "This project published these identifiers for flows it mints, and no "
        "longer does; each still resolves to the flow it named.",
    ),
    CuratedFile(
        "release-migration-rulings.json",
        "brightway_flows.releases.rulings",
        "Between these two releases, this identifier the migration could not "
        "resolve -- a split, a unit change, a refused redirect -- became this "
        "flow, or nothing.",
    ),
)

#: What the words mean. Authored rather than decided: nobody rules that a
#: kilogram is a kilogram.
VOCABULARIES: tuple[CuratedFile, ...] = (
    CuratedFile(
        "consensus-flow-contexts.json",
        "brightway_flows.domain.context_registry",
        "The context vocabulary: one row per valid context, keyed by IRI.",
    ),
    CuratedFile(
        "consensus-flows-as-strings.json",
        "brightway_flows.context_mapping",
        "The same contexts as the display strings a source list is matched on.",
    ),
    CuratedFile(
        "units.json",
        "brightway_flows.domain.units",
        "The unit table: notations, IRIs and conversion factors.",
    ),
    CuratedFile(
        "environmental-materials.json",
        "brightway_flows.domain.materials",
        "The material taxonomy that holds sea water apart from cooling water.",
    ),
    CuratedFile(
        "water-flow-materials.json",
        "brightway_flows.domain.materials",
        "Which material each water flow is made of, looked up rather than "
        "inferred at run time.",
    ),
    CuratedFile(
        "material-anchor-snapshot.json",
        "brightway_flows.domain.materials",
        "The published ontology terms the material taxonomy anchors to.",
    ),
    CuratedFile(
        "land-anchor-snapshot.json",
        "brightway_flows.domain.land_use_anchors",
        "The published ontology terms each land-use axis value anchors to.",
    ),
    CuratedFile(
        "land-flow-classes.json",
        "brightway_flows.domain.land_flow_classes",
        "Which land class each land flow is, looked up rather than read off a "
        "comma-separated name at run time.",
    ),
    CuratedFile(
        "particulate-size-classes.json",
        "brightway_flows.domain.particulate_size",
        "The particle size window a flow was cut at, as a pair of aerodynamic "
        "diameters rather than a phrase inside a name. Ours, and uncited: no "
        "published vocabulary carries a size band.",
    ),
    CuratedFile(
        "particulate-flow-classes.json",
        "brightway_flows.domain.particulate_size",
        "Which size window each airborne particle flow was cut at, looked up "
        "rather than read off `< 10 um` in a name at run time.",
    ),
    CuratedFile(
        "structure-corrections.json",
        "brightway_flows.domain.structure_corrections",
        "The structure and published class of a substance the pipeline cannot "
        "work out for itself, stated on a curator's authority.",
    ),
    CuratedFile(
        "aggregate-measurements.json",
        "brightway_flows.domain.aggregate_measurements",
        "Which flows measure a quantity over many substances rather than one.",
    ),
    CuratedFile(
        "lcia-impact-categories.json",
        "brightway_flows.domain.lcia.crosswalk",
        "EF 3.1: its three implementations, where each one's factors are read "
        "from, and its 25 impact categories -- what the JRC calls each one, "
        "what ecoinvent calls it under EF v3.1 and under the EF v3.0 that "
        "ecoinvent 3.8 still ships, and the unit and area of protection it is "
        "published with. One file per method.",
    ),
    CuratedFile(
        "stepwise-2006-impact-categories.json",
        "brightway_flows.domain.lcia.crosswalk",
        "Stepwise 2006: its one implementation, where its factors are read "
        "from, and its 19 impact categories -- what the export calls each one, "
        "the unit it is counted in, what that number means and whose words "
        "those are, and the area of protection and midpoint/endpoint reading "
        "it is published with. The second method file.",
    ),
)

#: Bulk data shipped with the package because fetching it is slow or impossible.
REFERENCE_DATA: tuple[CuratedFile, ...] = (
    CuratedFile(
        "ec-inventory.json.gz",
        "brightway_flows.integrations.ec_inventory",
        "The EC inventory, as a CAS-to-EC index.",
    ),
    CuratedFile(
        "ecoinvent-historical-names.json",
        "brightway_flows.merge.historical_names",
        "Every name ecoinvent retired between 2.2 and 3.12 that a name alias "
        "can honestly decide, with the newest release's name for the same "
        "flow, derived mechanically by "
        "tools/derive_ecoinvent_historical_names.py from the vendor's own "
        "correspondence and checked in for review. Measurement rather than "
        "decision: the rule reading the newest release as canonical is the "
        "element/ion rule's, carried from uuid space into name space for rows "
        "that arrive without ecoinvent uuids. Consulted by the merge only "
        "after every registry number and every shipped name has failed; the "
        "loader refuses bare elements, charge assignments and land names, "
        "which belong to merge/species.py and the land classes.",
    ),
    CuratedFile(
        "ecoinvent-canonical-identities.json",
        "brightway_flows.merge.species",
        "The newest ecoinvent release's identity for every element/ion flow an "
        "earlier release states differently, derived mechanically by "
        "tools/derive_ecoinvent_canonical_identities.py and checked in for "
        "review. Measurement rather than decision: the rule reading the newest "
        "release as canonical is plans/retire-prepared-correspondence.md §3a. "
        "The module that applies it was held inert while a prepared "
        "correspondence table still decided the same rows; every manifest "
        "declares none since #141, so the rule is live on all five ecoinvent "
        "releases.",
    ),
    CuratedFile(
        "lcia-underlying-model-factors.json",
        "brightway_flows.lcia.contradictions",
        "What USEtox 2.1 states for the substances EF 3.1's toxicity categories "
        "are derived from, where the two are more than a hundredfold apart. "
        "Measurement rather than decision: it states two numbers and no verdict, "
        "and what makes a row a question is a rule in the module that reads it.",
    ),
)

#: Every file the package ships in ``data/``, in one tuple, so a test can assert
#: the directory and the register agree in both directions.
CURATED_FILES: tuple[CuratedFile, ...] = RULINGS + VOCABULARIES + REFERENCE_DATA
