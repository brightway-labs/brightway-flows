"""The single definition point for every vocabulary IRI used by this project.

Two problems this solves:

1. **Divergent copies.** The CAS classification IRI was defined in five modules,
   ``chemrof/molecular_formula`` in five, ``FullySpecifiedAtom`` in four. Nothing
   stopped one copy from drifting. There is now one definition per term, and
   ``tests/test_vocabulary.py`` fails if a module re-declares one.

2. **Verbose call sites.** Pipeline code can refer to a term by a short, readable
   name (``Term.MOLECULAR_FORMULA``) while the full IRI stays a serialisation
   concern resolved through :data:`IRIS`.

The exported ``JSONLD_CONTEXT`` is *generated* from the registry, so a term
cannot be emitted without being declared -- the failure mode where an undeclared
term makes a JSON-LD document expand to nothing.

Every IRI here is taken from its publishing authority, never inferred. See
``AGENTS.md``: do not invent or infer predicate IRIs.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class Namespace(StrEnum):
    """Namespace IRIs, used for prefix declarations in ``JSONLD_CONTEXT``."""

    # Bibliographic Ontology.  SKOS and XKOS have no construct for publication
    # status, and BIBO's is what py-semantic-taxonomy settled on.
    BIBO = "http://purl.org/ontology/bibo/"
    # Semantic Science Integrated Ontology (CHEMINF descriptors).
    CHEMINF = "http://semanticscience.org/resource/"
    # ChemROF -- https://w3id.org/chemrof (redirects to chemkg.github.io/chemrof).
    CHEMROF = "https://w3id.org/chemrof/"
    DCTERMS = "http://purl.org/dc/terms/"
    # AGROVOC -- the FAO thesaurus.  Types the *accounting* category where ENVO
    # types the material: `green water` is a water-footprint boundary rather
    # than a kind of stuff, and no OBO ontology carries it.  A SKOS thesaurus
    # rather than an OWL ontology, and **not indexed by OLS**, so it needs its
    # own resolver -- see `tools/resolve_material_anchors.py`.
    AGROVOC = "http://aims.fao.org/aos/agrovoc/"
    # The OBO PURL namespace, which is where ENVO, RO and ChEBI accessions all
    # live.  ENVO types the environmental material -- what the stuff is -- for
    # the taxonomy in `environmental-materials.json`; RO supplies `has role`
    # (see `Term.HAS_ROLE`) and ChEBI supplies the role classes it points at.
    #
    # Named `OBO` and not `RO`, deliberately.  The registered `ro` prefix is
    # `http://purl.obolibrary.org/obo/RO_`, not the directory above it, so
    # declaring `ro: .../obo/` would make our `ro:RO_0000087` re-expand to
    # `.../obo/RO_RO_0000087` for any consumer merging our context with a
    # registry-conformant one.  `obo:` for the whole namespace with the
    # accession as the local name is the convention OBO graphs themselves use.
    OBO = "http://purl.obolibrary.org/obo/"
    OWL = "http://www.w3.org/2002/07/owl#"
    PROV = "http://www.w3.org/ns/prov#"
    QUDT = "http://qudt.org/schema/qudt/"
    RDFS = "http://www.w3.org/2000/01/rdf-schema#"
    SKOS = "http://www.w3.org/2004/02/skos/core#"
    # XKOS -- namespace per the XKOS specification.
    XKOS = "http://rdf-vocabulary.ddialliance.org/xkos#"
    XSD = "http://www.w3.org/2001/XMLSchema#"

    # The only namespace here this project *defines* rather than borrows: the
    # relations, and the one class, that this list needs and no published
    # vocabulary provides.
    # Minting was avoided while the cost was only that a key did not expand; it
    # stopped being acceptable when `context_iri` -- the compartment, the field
    # an LCA practitioner filters on first -- was the one thing in the export
    # contributing no triples.  The class was held off on the same terms, and
    # for the same reason stopped being affordable: while `Chemical Oxygen
    # Demand` had no type, rules reading a registry number gave it one (#68).
    #
    # Under `vocab.brightway.one` because that authority already names the
    # contexts these point at.  A minted IRI is a promise: it has to keep
    # meaning the same thing, and it has to resolve.  Serving them is a
    # deployment task rather than a code one; `docs/reference/jsonld.md` says
    # what has to be published at each.
    BRIGHTWAY = "https://vocab.brightway.one/terms/"


class MintedNamespace(StrEnum):
    """IRI namespaces this project mints.

    Note the split authority: contexts, units, and source-list flows live under
    ``vocab.brightway.one`` while consensus elementary flows live under
    ``vocab.brightway.dev``.  That split is pre-existing and is recorded here
    rather than silently normalised, because changing a minted IRI changes every
    identifier already published.
    """

    FLOW_CONTEXTS = "https://vocab.brightway.one/flow-contexts/"
    UNITS = "https://vocab.brightway.one/units/unit/"
    EF31_FLOW = "https://vocab.brightway.one/ef/3.1/flow/"
    #: BAFU versions by export rather than by year: 2026 v1 is followed by a v2
    #: in the same year, and they are different releases of the list.
    BAFU_2026_V1_FLOW = "https://vocab.brightway.one/bafu/2026-v1/flow/"
    #: Stepwise by method and by file revision: `2006` is the method and `1.09`
    #: is the export of it, and a later revision of the same method is a
    #: different release of the list in the way BAFU's v2 is.
    STEPWISE_2006_1_09_FLOW = "https://vocab.brightway.one/stepwise/2006-1.09/flow/"
    #: AGRIBALYSE by release: 3.2 is ADEME's own version string, and the
    #: export itself states none, so the manifest's version is the claim.
    AGRIBALYSE_3_2_FLOW = "https://vocab.brightway.one/agribalyse/3.2/flow/"
    SIMAPRO_102_FLOW = "https://vocab.brightway.one/simapro/professional/10.2/flow/"
    ECOINVENT_FLOW_TEMPLATE = "https://vocab.brightway.one/ecoinvent/{version}/flow/"
    CONSENSUS_ELEMENTARY_FLOW = "https://vocab.brightway.dev/elementary-flows/"
    #: The material taxonomy's own concepts.  Under `vocab.brightway.one`
    #: because that authority already names the contexts, and a minted IRI is
    #: a promise: `turbine_water` has no published class in ENVO or AGROVOC
    #: and an ENVO term request goes with it.
    ENVIRONMENTAL_MATERIAL = "https://vocab.brightway.one/environmental-materials/"
    #: The land classes, beside the materials and under the same authority.
    #:
    #: Minted for the same reason and with one difference that matters: a
    #: material concept is a curated node with a curated parent, and a land
    #: class is a *value* whose identity and whose place in the hierarchy both
    #: fall out of its fields.  So the local name is `LandUse.key` --
    #: `occupation/cropland/irrigation=rainfed/intensity=intensive` -- and two
    #: spellings of one class cannot mint two IRIs, because they do not produce
    #: two keys.  `diverse-intensive` is the only value in the scheme with no
    #: published class anywhere to cite, and an AGROVOC term request goes with
    #: it, which is the promise this namespace stands for.
    LAND_CLASS = "https://vocab.brightway.one/land-classes/"
    #: The substance layer, under the same authority as the flows that occur of
    #: it and named for what it holds.  Minted for the same reason
    #: `Namespace.BRIGHTWAY` was: `chemrof:has_element` -- the one link this
    #: project publishes between two of its own objects -- had a bare
    #: `flow_object_id` for a value, which expands to a string literal.  A
    #: consumer reading `"fo-0bfffb5e4dadc218"` cannot follow it, and the
    #: ontology declares the slot's range as a class, not a name.
    #:
    #: The target is not a node in the export yet: the flow-object layer is not
    #: published, so this resolves to a substance the document only refers to.
    #: That is a link waiting for its object rather than a literal that can
    #: never become one, and the identifier is the same either way.
    FLOW_OBJECT = "https://vocab.brightway.dev/flow-objects/"
    #: The values `originQualifier` points at, so a qualifier is a concept
    #: rather than a bare string.  Local names are `qualifiers.ORIGIN_QUALIFIERS`.
    ORIGIN_QUALIFIER_VALUES = "https://vocab.brightway.one/origin-qualifiers/"
    #: The values `deprecationReason` points at, for the same reason
    #: `ORIGIN_QUALIFIER_VALUES` exists: a reason a consumer is expected to
    #: branch on is a controlled term, and a bare string invites a second
    #: spelling of it.  Local names are `DEPRECATION_REASONS`.
    DEPRECATION_REASON_VALUES = "https://vocab.brightway.one/deprecation-reasons/"

    # ── Concept schemes ──────────────────────────────────────────────────────
    # A `skos:ConceptScheme` needs an IRI, and the flow prefixes above already
    # name the collections these schemes are: each is that prefix with the
    # trailing `flow/` segment dropped.  Derived rather than freely invented, so
    # a reader who has one can work out the other.
    CONSENSUS_SCHEME = "https://vocab.brightway.dev/elementary-flows"
    EF31_SCHEME = "https://vocab.brightway.one/ef/3.1"
    BAFU_2026_V1_SCHEME = "https://vocab.brightway.one/bafu/2026-v1"
    STEPWISE_2006_1_09_SCHEME = "https://vocab.brightway.one/stepwise/2006-1.09"
    AGRIBALYSE_3_2_SCHEME = "https://vocab.brightway.one/agribalyse/3.2"
    SIMAPRO_102_SCHEME = "https://vocab.brightway.one/simapro/professional/10.2"
    ECOINVENT_SCHEME_TEMPLATE = "https://vocab.brightway.one/ecoinvent/{version}"

    #: The identifiers the review database's PROV trail is built from -- one
    #: entity per flow version, one agent per transformer, one activity per
    #: field change.  A third authority again (`data.brightway.dev`), carried
    #: over verbatim from the `provenance.json` these rows replaced so an
    #: identifier minted by an older run and one minted from a table row are the
    #: same string.  Declared here because it was the one namespace this project
    #: mints that lived outside the registry; see #233.
    REVIEW_PROVENANCE = "https://data.brightway.dev/brightway-flows/"

    # ── Correspondences ──────────────────────────────────────────────────────
    # New paths, under the authority that already names the consensus list --
    # the correspondence is this project's assertion, not the source list's.
    CORRESPONDENCE = "https://vocab.brightway.dev/correspondences/"
    ASSOCIATION = "https://vocab.brightway.dev/concept-associations/"

    # ── Characterisation ─────────────────────────────────────────────────────
    # An LCIA method, and an impact category of one.  Under
    # `vocab.brightway.one` because that authority already names the units the
    # categories are expressed in.
    #
    # An impact category's local name is
    # `{method}/{version}/{implemented_by}/{timeframe}/{category}` -- five
    # segments, because a category is not identified by less.  EF 3.1's
    # `Acidification` is published three times, once as the JRC states it, once
    # as the ecoinvent Centre implements it and once as this list's own
    # judgement, and those are three different sets of numbers that a reader
    # must be able to ask for separately.  `timeframe` is `long` on all of them
    # today (`plans/lcia-factors.md` §2.4) and is in the path anyway, so that a
    # set which excludes long-term emissions can be added later without moving
    # an identifier that is already published.
    LCIA_METHOD = "https://vocab.brightway.one/lcia/method/"
    LCIA_IMPACT_CATEGORY = "https://vocab.brightway.one/lcia/impact-category/"


class Datatype(StrEnum):
    """XSD datatypes for the terms whose values are not strings.

    A ChemROF slot declares a range -- ``molecular_mass`` is a ``float``,
    ``elemental_charge`` an ``integer`` -- and until now every one of them was
    serialised as a string (``"398.54"``, ``"0"``).  A consumer expanding that
    gets a plain literal where the ontology promised a number.

    The value is the local name within :attr:`Namespace.XSD`; the CURIE written
    into ``JSONLD_CONTEXT`` is built from it.
    """

    DOUBLE = "double"
    INTEGER = "integer"
    #: Not a ChemROF range: `dcterms:created` is a timestamp, and an untyped
    #: one expands to a plain string rather than a date.
    DATETIME = "dateTime"


class Term(StrEnum):
    """Short, readable names for the vocabulary terms this project emits.

    The value is the short name used in code and in ``JSONLD_CONTEXT``; the full
    IRI is looked up in :data:`IRIS`.
    """

    # ── ChemROF properties ───────────────────────────────────────────────────
    MOLECULAR_FORMULA = "molecular_formula"
    #: ChemROF: "a string encoding of a molecular graph, **no chiral or
    #: isotopic information**".  Only structures that carry neither belong here;
    #: the rest go to :attr:`ISOMERIC_SMILES_STRING`.
    SMILES_STRING = "smiles_string"
    #: ChemROF: "a SMILES string that distinguishes between isomeric forms.
    #: E.g. [13C] for carbon-13", declared `is_a: smiles_string`.  The slot for
    #: the 1,167 flow objects this project stores with stereochemistry (`@`,
    #: `/`, `\`) or an isotopic label, which `smiles_string` says it does not
    #: carry.
    ISOMERIC_SMILES_STRING = "isomeric_smiles_string"
    INCHI2D_STRING = "inchi2d_string"
    INCHI2D_KEY_STRING = "inchi2d_key_string"
    MOLECULAR_MASS = "molecular_mass"
    MONOISOTOPIC_MASS = "monoisotopic_mass"
    FORMAL_CHARGE = "formal_charge"
    IUPAC_NAME = "IUPAC_name"
    ATOMIC_NUMBER = "atomic_number"
    ELEMENTAL_CHARGE = "elemental_charge"
    NEUTRON_NUMBER = "neutron_number"
    #: Published as a float number of years, which the slot's declared range --
    #: `NumberOfYears`, defined as `xsd:int` -- does not permit.  Americium-241
    #: is 432.6 years and Krypton-85 is 10.7; there is no integer that is
    #: either, so the choice was a wrong number, no number, or this.  Reported
    #: upstream; see `docs/reference/semantic-types.md`.
    HALF_LIFE = "half_life"
    # Declared by ChemROF on exactly the two classes this project needs it for:
    # `MonoatomicIon` and `Isotope`.  It replaces the home-grown
    # `properties.relationships.parent_element_flow_object_id`.
    HAS_ELEMENT = "has_element"
    DECAY_MODE = "decay_mode"
    NUCLEON_NUMBER = "nucleon_number"
    SYMBOL = "symbol"

    # ── ChemROF classes ──────────────────────────────────────────────────────
    # Every one of these is verified present and *concrete* in the ChemROF
    # LinkML source (`chemkg/chemrof`, `src/chemrof/schema/chemrof.yaml`).  The
    # abstract ones -- `ChemicalEntity`, `PolyatomicEntity`, `ChemicalMixture`,
    # `PreciseChemicalMixture`, `MoleculeByChargeState`, `ChemicalGroupingClass`
    # -- are deliberately absent: instantiating an abstract class is a modelling
    # error, and a reasoner derives them from the concrete leaf anyway.
    #: `FullySpecifiedAtom` requires atomic number, charge *and* neutron number
    #: to be stated.  This project's element objects take their neutron number
    #: from the most abundant isotope, which is an approximation and not a
    #: statement -- so `ChemicalElement`, "generic form of an atom, with
    #: unspecified neutron or charge", is what they actually are.  It also makes
    #: `has_element` well-formed: ChemROF gives that slot the range
    #: `ChemicalElement`, and `FullySpecifiedAtom` is its sibling, not its
    #: subclass.
    CHEMICAL_ELEMENT = "ChemicalElement"
    #: Kept declared though nothing emits it: it names what this project claimed
    #: its elements were until #234, and a reader of an older artifact needs the
    #: term to resolve.
    FULLY_SPECIFIED_ATOM = "FullySpecifiedAtom"
    MONOATOMIC_ION = "MonoatomicIon"
    ATOM_CATION = "AtomCation"
    ATOM_ANION = "AtomAnion"
    MOLECULE = "Molecule"
    NEUTRAL_MOLECULE = "NeutralMolecule"
    ZWITTERION = "Zwitterion"
    ALLOTROPE = "Allotrope"
    POLYATOMIC_ION = "PolyatomicIon"
    MOLECULAR_CATION = "MolecularCation"
    MOLECULAR_ANION = "MolecularAnion"
    CHEMICAL_SALT = "ChemicalSalt"
    MOLECULAR_COMPLEX = "MolecularComplex"
    IMPRECISE_CHEMICAL_MIXTURE = "ImpreciseChemicalMixture"
    ISOTOPE = "Isotope"
    RADIONUCLIDE = "Radionuclide"
    MATERIAL = "Material"
    MOLECULE_GROUPING_CLASS = "MoleculeGroupingClass"
    ATOM_GROUPING_CLASS = "AtomGroupingClass"

    # ── CHEMINF classifications ──────────────────────────────────────────────
    CAS_REGISTRY_NUMBER = "cas_registry_number"
    EC_NUMBER = "ec_number"

    # ── SKOS ─────────────────────────────────────────────────────────────────
    CONCEPT = "Concept"
    CONCEPT_SCHEME = "ConceptScheme"
    IN_SCHEME = "inScheme"
    PREF_LABEL = "prefLabel"
    ALT_LABEL = "altLabel"
    DEFINITION = "definition"
    EXACT_MATCH = "exactMatch"
    CLOSE_MATCH = "closeMatch"
    #: The hierarchical link *within* a scheme, as distinct from `broadMatch`
    #: below, which is the mapping link *between* two.  SKOS makes `broadMatch`
    #: a sub-property of this one and says the mapping properties are "by
    #: convention only used to link concepts in different concept schemes"
    #: (SKOS Reference, S41 and section 10).
    #:
    #: Undeclared until now because nothing in this project had a scheme of its
    #: own with internal structure: every hierarchy it published belonged to
    #: somebody else and was reached by a mapping.  `environmental-materials.json`
    #: is the first, and `lake water broader surface water` is a statement inside
    #: it rather than about ENVO -- which is what lets the scheme assert an edge
    #: ENVO declines to make without asserting anything about ENVO.
    BROADER = "broader"
    #: The intra-scheme associative link, as `broader` is the intra-scheme
    #: hierarchical one.  `relatedMatch` below is its mapping counterpart and
    #: leaves the scheme; using it between two of our own concepts would be
    #: the mistake `broader` was declared to avoid, wearing a different name.
    RELATED = "related"
    BROAD_MATCH = "broadMatch"
    #: The other half of `broadMatch`.  Absent until a correspondence table
    #: could say the source concept was the *broader* of the two -- GLAD maps
    #: 342 SimaPro flows onto more than one consensus flow, and `broadMatch`
    #: pointed the wrong way for every one of them.
    NARROW_MATCH = "narrowMatch"
    RELATED_MATCH = "relatedMatch"

    # ── OWL / DCTERMS ────────────────────────────────────────────────────────
    VERSION_INFO = "versionInfo"
    DEPRECATED = "deprecated"
    IS_REPLACED_BY = "isReplacedBy"
    IDENTIFIER = "identifier"
    SOURCE = "source"
    #: When the run that produced this document happened, and what produced it.
    #: PyST requires both on a `ConceptScheme` and on a `Correspondence`.
    #: `created` is a wall-clock stamp, so it is the one field in the export
    #: that differs between two runs over identical inputs; `tools/verify_run.py`
    #: treats it as volatile for exactly that reason.
    CREATED = "created"
    CREATOR = "creator"

    # ── BIBO ─────────────────────────────────────────────────────────────────
    # SKOS and XKOS define no construct for publication status.
    STATUS = "status"

    # ── QUDT / RDFS ──────────────────────────────────────────────────────────
    HAS_UNIT = "hasUnit"
    # 1-to-N allocation between corresponding concepts.  Not what QUDT wrote it
    # for, but its domain and range fit and allocation is close enough to unit
    # conversion; py-semantic-taxonomy uses it the same way.
    CONVERSION_MULTIPLIER = "conversionMultiplier"
    LABEL = "label"
    SEE_ALSO = "seeAlso"

    # ── XKOS ─────────────────────────────────────────────────────────────────
    # XKOS defines no property for the type or strength of a mapping; the
    # specification says so explicitly.  A `mapType` term is therefore absent by
    # design -- the match is expressed with the SKOS mapping property itself
    # (skos:exactMatch / skos:broadMatch / ...) on the source concept.
    CONCEPT_ASSOCIATION = "ConceptAssociation"
    SOURCE_CONCEPT = "sourceConcept"
    TARGET_CONCEPT = "targetConcept"
    CORRESPONDENCE = "Correspondence"
    COMPARES = "compares"
    # `xkos:madeOf` links a Correspondence to its ConceptAssociations.  #9
    # removed it because there was no correspondence to put on its left; this
    # release builds one, so it is back and its domain is satisfied.
    MADE_OF = "madeOf"

    #: What a substance is *used for*, as opposed to what it is: herbicide,
    #: fertilizer, environmental contaminant.  `RO:0000087 has role`, which is
    #: the relation ChEBI's own distribution uses for exactly this, so the
    #: assertions we publish and the assertions we read are the same relation.
    #:
    #: Borrowed rather than minted, and deliberately not modelled as a parent:
    #: `parent_flow_object_id` already means the undifferentiated substance a
    #: qualified flow was split from, and it is single-valued.  A role is not.
    #: Sulfluramid is an insecticide *and* an acaricide.
    HAS_ROLE = "hasRole"

    # ── Minted by this project ───────────────────────────────────────────────
    #: The compartment a flow is exchanged with, as a flow-context IRI.
    FLOW_CONTEXT = "flowContext"
    #: Why a substance is held apart from one it shares a CAS number with:
    #: biogenic against fossil carbon, or a water-footprint category.  An LCA
    #: distinction with no equivalent in any chemical ontology, because it is
    #: about where a substance came from and not about what it is.
    ORIGIN_QUALIFIER = "originQualifier"
    #: The other half of `originQualifier`: the undifferentiated substance the
    #: qualified one was split from, as a flow-object IRI.  `originQualifier`
    #: says *why* a substance is held apart; this says *what from*.  Published
    #: without it, `biogenic` names a distinction whose other side a consumer
    #: can only reach by CAS lookup -- which returns the siblings too.
    #:
    #: Minted rather than borrowed, after checking the alternatives.  ChemROF's
    #: `alternate_form_of` is the right shape and is declared `abstract: true`,
    #: so it is not instantiable; its concrete children (`isotope_of`,
    #: `has_element`, `conjugate_base_of`, ...) are all chemical relations, and
    #: this is not one -- biogenic CO2 is the same molecule as fossil CO2.
    #: `subtype_of` is class-level (`domain: OwlClass`, `range: OwlClass`) and
    #: these are instances.  `skos:broader` has `skos:Concept` for both domain
    #: and range, and would assert that a flow object is a concept -- the
    #: *flows* are published as concepts, the substances are not.  So this is
    #: ours, for the same reason `originQualifier` had to be.
    BASE_SUBSTANCE = "baseSubstance"
    #: The non-material intervention a flow is one occurrence of, as a
    #: flow-object IRI.  `baseSubstance`'s counterpart for what is not a
    #: substance: BAFU's six traffic-noise rows are noise from an aircraft, a
    #: lorry, a passenger train, and the thing they are all noise *of* has no
    #: flow of its own until this list mints one (#70).
    #:
    #: A second term rather than a wider reading of `baseSubstance`, because
    #: that term says "substance" and means it.  Publishing `Noise, Road,
    #: Lorry, Average` as having a base *substance* would assert exactly what
    #: the six flows do not have -- and the reason they cannot be typed as
    #: chemistry at all is that noise is not matter.  The alternatives
    #: `baseSubstance` already ruled out rule this one out for the same
    #: reasons: `skos:broader` would make a flow object a concept, and every
    #: concrete ChemROF relation is chemical.  So this is ours too.
    BASE_INTERVENTION = "baseIntervention"
    #: Why a flow was deprecated, as an IRI from the minted deprecation-reason
    #: vocabulary.  `owl:deprecated` says a flow is gone and
    #: `dcterms:isReplacedBy` says where to, but neither says whether the two
    #: flows were ever the same thing -- and that is the difference between a
    #: redirect worth following and one worth refusing (#39).  OWL and DCTERMS
    #: define no property for it, so it is minted here.
    DEPRECATION_REASON = "deprecationReason"
    #: What an aggregate measurement sums over, as a flow-object IRI naming the
    #: grouping class whose members it counts.  `AOX, Adsorbable Organic
    #: Halogen as Cl` and `Adsorbable Organic Halogen Compounds` are the same
    #: molecules measured two ways -- one as a class of substances, one as a
    #: mass of chlorine -- and nothing in the published list said so.
    #:
    #: Distinct from `expressedAs`, which says what the *number* is reported in
    #: terms of.  AOX has both and they are different objects; COD has neither.
    SUMS_OVER = "sumsOver"
    #: The substance an aggregate measurement's mass is reported in terms of,
    #: as a flow-object IRI.  `Benzene (as BTEX)` is a mass of four compounds
    #: reported as though it were benzene; `AOX ... as Cl` is a mass of
    #: organohalogens reported as chlorine.
    #:
    #: **Not `baseSubstance`.**  That predicate means the undifferentiated
    #: substance a qualified one was *split from*, and it is published only
    #: beside `originQualifier`.  Nothing split BTEX off benzene, and COD's
    #: oxygen is not in the discharge at all -- it is what a laboratory's
    #: oxidant would consume.  Reusing the term would have made a published
    #: definition mean two things, one of which is false.
    #:
    #: The link is the whole reason a consumer can be told what the row relates
    #: to without being told the row *is* it, which is the mistake #68 exists
    #: to prevent.
    EXPRESSED_AS = "expressedAs"
    #: A quantity a source list reports as an elementary flow whose value is
    #: fixed by the analytical procedure that produces it, summing over many
    #: chemical entities or over none.  `Chemical Oxygen Demand`,
    #: `Benzene (as BTEX)`, `Particles (PM2.5)`, `Acidity, Unspecified`.
    #:
    #: The one class here that is not borrowed, and it is a class rather than a
    #: reason string because a reason is not published: an object left untyped
    #: says nothing a consumer can filter on, and these have to be excluded
    #: from any query for substances.  ChemROF has no term for it -- the
    #: closest, `ImpreciseChemicalMixture`, is "a macroscopic polyatomic
    #: entity", which is a portion of matter you could hold, and a kilogram of
    #: chemical oxygen demand is not one: the oxygen it counts is not in the
    #: discharge, it is what a laboratory's oxidant would consume (#68).
    #:
    #: Deliberately outside the ChemROF hierarchy rather than beneath
    #: `ChemicalEntity`.  Being outside it is the statement.
    AGGREGATE_MEASUREMENT = "AggregateMeasurement"
    #: A source-list flow this project looked at and deliberately did not map,
    #: hung off the `xkos:Correspondence` for that list beside `xkos:madeOf`.
    #:
    #: Without it, a source flow with no association and a source flow nobody
    #: examined are the same absence -- which is how #115 was raised: a consumer
    #: counting ecoinvent 3.8's master data against the associations found three
    #: fewer and had no way to tell an oversight from a decision.  XKOS has no
    #: term for it, because a `ConceptAssociation` is by definition a pair and
    #: this is the assertion that no pair exists, so it is minted here.
    #:
    #: Deliberately hung off the correspondence rather than published as a
    #: concept of its own: the exclusion is this project's judgement about the
    #: comparison, not a statement about the source list, which goes on shipping
    #: the flow whatever this list decides.
    EXCLUDED_SOURCE_CONCEPT = "excludedSourceConcept"
    #: Why one `excludedSourceConcept` is excluded, as prose.  A literal rather
    #: than an IRI from a controlled vocabulary: the reasons so far are each
    #: specific to one vendor's defect in one release, and a five-value
    #: enumeration invented from three cases would put more weight on the
    #: classification than the evidence carries.  Promote it when a category
    #: recurs.
    EXCLUSION_REASON = "exclusionReason"

    # ── PROV ─────────────────────────────────────────────────────────────────
    WAS_GENERATED_BY = "wasGeneratedBy"
    WAS_ATTRIBUTED_TO = "wasAttributedTo"
    HAD_PRIMARY_SOURCE = "hadPrimarySource"
    WAS_DERIVED_FROM = "wasDerivedFrom"


# Local name within its namespace, where it differs from Term's short name.
# CHEMINF terms are opaque accession numbers, so they always differ.
_LOCAL_NAME: dict[Term, str] = {
    Term.CAS_REGISTRY_NUMBER: "CHEMINF_000446",
    Term.EC_NUMBER: "CHEMINF_000447",
    Term.HAS_ROLE: "RO_0000087",
}

_NAMESPACE_OF: dict[Term, Namespace] = {
    **{
        term: Namespace.CHEMROF
        for term in (
            Term.MOLECULAR_FORMULA, Term.SMILES_STRING,
            Term.ISOMERIC_SMILES_STRING, Term.INCHI2D_STRING,
            Term.INCHI2D_KEY_STRING, Term.MOLECULAR_MASS, Term.MONOISOTOPIC_MASS,
            Term.FORMAL_CHARGE, Term.IUPAC_NAME, Term.ATOMIC_NUMBER,
            Term.ELEMENTAL_CHARGE, Term.NEUTRON_NUMBER, Term.HALF_LIFE,
            Term.HAS_ELEMENT,
            Term.DECAY_MODE, Term.NUCLEON_NUMBER, Term.SYMBOL,
            Term.CHEMICAL_ELEMENT, Term.FULLY_SPECIFIED_ATOM,
            Term.MONOATOMIC_ION, Term.ATOM_CATION,
            Term.ATOM_ANION, Term.MOLECULE, Term.NEUTRAL_MOLECULE,
            Term.ZWITTERION, Term.ALLOTROPE, Term.POLYATOMIC_ION,
            Term.MOLECULAR_CATION, Term.MOLECULAR_ANION, Term.CHEMICAL_SALT,
            Term.MOLECULAR_COMPLEX, Term.IMPRECISE_CHEMICAL_MIXTURE,
            Term.ISOTOPE, Term.RADIONUCLIDE, Term.MATERIAL,
            Term.MOLECULE_GROUPING_CLASS, Term.ATOM_GROUPING_CLASS,
        )
    },
    **{term: Namespace.CHEMINF for term in (Term.CAS_REGISTRY_NUMBER, Term.EC_NUMBER)},
    Term.HAS_ROLE: Namespace.OBO,
    **{
        term: Namespace.SKOS
        for term in (
            Term.PREF_LABEL, Term.ALT_LABEL, Term.DEFINITION, Term.EXACT_MATCH,
            Term.CLOSE_MATCH, Term.BROADER, Term.RELATED, Term.BROAD_MATCH,
            Term.NARROW_MATCH,
            Term.RELATED_MATCH,
            Term.CONCEPT, Term.CONCEPT_SCHEME, Term.IN_SCHEME,
        )
    },
    **{term: Namespace.OWL for term in (Term.DEPRECATED, Term.VERSION_INFO)},
    Term.STATUS: Namespace.BIBO,
    **{
        term: Namespace.DCTERMS
        for term in (
            Term.IS_REPLACED_BY, Term.IDENTIFIER, Term.SOURCE,
            Term.CREATED, Term.CREATOR,
        )
    },
    **{
        term: Namespace.QUDT
        for term in (Term.HAS_UNIT, Term.CONVERSION_MULTIPLIER)
    },
    **{term: Namespace.RDFS for term in (Term.LABEL, Term.SEE_ALSO)},
    **{
        term: Namespace.XKOS
        for term in (
            Term.CONCEPT_ASSOCIATION, Term.SOURCE_CONCEPT, Term.TARGET_CONCEPT,
            Term.CORRESPONDENCE, Term.COMPARES, Term.MADE_OF,
        )
    },
    **{
        term: Namespace.BRIGHTWAY
        for term in (
            Term.FLOW_CONTEXT, Term.ORIGIN_QUALIFIER, Term.BASE_SUBSTANCE,
            Term.BASE_INTERVENTION, Term.DEPRECATION_REASON,
            Term.SUMS_OVER, Term.EXPRESSED_AS, Term.AGGREGATE_MEASUREMENT,
            Term.EXCLUDED_SOURCE_CONCEPT, Term.EXCLUSION_REASON,
        )
    },
    **{
        term: Namespace.PROV
        for term in (
            Term.WAS_GENERATED_BY, Term.WAS_ATTRIBUTED_TO,
            Term.HAD_PRIMARY_SOURCE, Term.WAS_DERIVED_FROM,
        )
    },
}

#: Terms whose values are numbers, and the XSD type they carry.
#:
#: Taken from the range each slot declares in the ChemROF LinkML schema
#: (``src/chemrof/schema/chemrof.yaml``): ``Count`` and ``integer`` map to
#: ``xsd:integer``, ``float`` to ``xsd:double``.  A term absent here is a
#: string and needs no declaration.
#:
#: Two things read this: ``build_jsonld_context`` writes ``@type`` into the term
#: definition, and ``domain.property_values`` coerces the stored value so what
#: is published is a JSON number rather than a quoted one.
TERM_DATATYPE: dict[Term, Datatype] = {
    Term.MOLECULAR_MASS: Datatype.DOUBLE,
    Term.MONOISOTOPIC_MASS: Datatype.DOUBLE,
    Term.ATOMIC_NUMBER: Datatype.INTEGER,
    Term.NEUTRON_NUMBER: Datatype.INTEGER,
    Term.ELEMENTAL_CHARGE: Datatype.INTEGER,
    Term.FORMAL_CHARGE: Datatype.INTEGER,
    Term.NUCLEON_NUMBER: Datatype.INTEGER,
    Term.HALF_LIFE: Datatype.DOUBLE,
    Term.CREATED: Datatype.DATETIME,
}

#: The terms whose values are human-readable text rather than data, declared in
#: the context with `@language` so the literals expand tagged.
#:
#: PyST rejects an untagged string literal, and every one of these is emitted as
#: a bare string: `prefLabel` and the members of `altLabel` and `definition` are
#: resolved to one language before export -- English preferred -- and the tag is
#: dropped in the process.  Declaring the language on the *term* restores it on
#: expansion without putting `{"@value": ..., "@language": "en"}` in the
#: document, so no consumer reading these as strings breaks.
#:
#: This is a claim about the export, not about the pipeline: the resolution
#: prefers English but falls back to whatever a source list supplies, so a
#: definition that exists only in another language is tagged `en` wrongly.  That
#: is the same assumption the resolution already makes, now stated in the
#: output.  Carrying the real tag through would mean publishing these as
#: language-tagged objects, which is a shape change and a schema bump.
#:
#: A term cannot be in both this and `TERM_DATATYPE`: `@language` and `@type`
#: are mutually exclusive in a JSON-LD term definition.  Guarded in
#: `tests/test_vocabulary.py`.
LANGUAGE_TAGGED_TERMS: frozenset[Term] = frozenset({
    Term.PREF_LABEL,
    Term.ALT_LABEL,
    Term.DEFINITION,
})

#: The language those terms are tagged with.
EXPORT_LANGUAGE = "en"

#: The terms that name a *class* rather than a property, in the order a reader
#: meets them: atoms, then ions, then molecules, then mixtures, then the rest.
#:
#: Declared once here so the review apps' type filter is generated from the
#: registry.  It was a hand-written list of five, which is how it came to offer
#: `"consensus"` -- a value naming nothing -- for 98.6% of objects.
CLASS_TERMS: tuple[Term, ...] = (
    Term.CHEMICAL_ELEMENT,
    Term.MONOATOMIC_ION,
    Term.ATOM_CATION,
    Term.ATOM_ANION,
    Term.ISOTOPE,
    Term.RADIONUCLIDE,
    Term.MOLECULE,
    Term.NEUTRAL_MOLECULE,
    Term.ZWITTERION,
    Term.ALLOTROPE,
    Term.POLYATOMIC_ION,
    Term.MOLECULAR_CATION,
    Term.MOLECULAR_ANION,
    Term.CHEMICAL_SALT,
    Term.MOLECULAR_COMPLEX,
    Term.IMPRECISE_CHEMICAL_MIXTURE,
    Term.MATERIAL,
    Term.MOLECULE_GROUPING_CLASS,
    Term.ATOM_GROUPING_CLASS,
    # Last, and the only one here this project mints.  A reader who has got
    # this far through the chemistry has met every class that is a substance;
    # this is the one that says the row is not one.
    Term.AGGREGATE_MEASUREMENT,
)

IRIS: dict[Term, str] = {
    term: f"{_NAMESPACE_OF[term].value}{_LOCAL_NAME.get(term, term.value)}"
    for term in Term
}

TERM_BY_IRI: dict[str, Term] = {iri_value: term for term, iri_value in IRIS.items()}


def iri(term: Term) -> str:
    """Return the full IRI for *term*."""
    return IRIS[term]


def term_for_iri(value: str) -> Term | None:
    """Return the :class:`Term` for a full IRI, or ``None`` if unregistered."""
    return TERM_BY_IRI.get(value)


def curie(term: Term) -> str:
    """Return the prefixed form of *term*, e.g. ``skos:prefLabel``.

    The published documents key `concept_associations` with CURIEs -- `xkos:`,
    `qudt:` -- so a term written there in expanded form makes one object mix two
    conventions.  Generated from the registry rather than written out, for the
    same reason the IRIs are: a term cannot be emitted without being declared.

    ``JSONLD_CONTEXT`` is what makes these resolvable; it declares every prefix
    this can produce.
    """
    return f"{_NAMESPACE_OF[term].name.lower()}:{_LOCAL_NAME.get(term, term.value)}"


def datatype_curie(datatype: Datatype) -> str:
    """Return the CURIE for *datatype*, e.g. ``xsd:double``."""
    return f"{Namespace.XSD.name.lower()}:{datatype.value}"


#: Keys of the published export that are not term short names, and what they
#: mean.  Without these the export is JSON that merely *looks* like JSON-LD:
#: an undeclared key is dropped on expansion, and it takes its value with it.
#:
#: Two aliases carry the document's shape rather than a predicate:
#:
#: - ``flows`` -> ``@graph``.  The export is a list of nodes, which is what a
#:   graph container is.  Aliasing avoids minting a predicate for it.
#: - ``properties`` -> ``@nest``.  The nesting is a convenience of the file
#:   format, not a statement about the substance: ``molecular_formula`` is a
#:   property *of the flow*, not of some intermediate "properties" node.
#:   ``@nest`` says exactly that, and needs JSON-LD 1.1.
#:
#: Deliberately absent.  These stay in the JSON, so a plain-JSON reader is
#: unaffected, and are dropped on expansion:
#:
#: - ``unit`` -- the IRI form, ``unit_iri``, expands as ``qudt:hasUnit``; the
#:   string beside it is a convenience duplicate.
#: - ``schema_version`` -- metadata about the file, not about the flows.
#:
#: ``concept_associations`` is gone from the flow entirely: the associations are
#: now nodes of their own, collected by an ``xkos:Correspondence``.  Find the
#: ones for a flow by its ``xkos:targetConcept``.
#:
#: See ``docs/reference/jsonld.md``.
#: ``identifier`` and ``source`` are absent because they are already covered:
#: :attr:`Term.IDENTIFIER` and :attr:`Term.SOURCE` have exactly those short
#: names, so the loop over ``Term`` declares them.
_EXPORT_KEY_TERMS: dict[str, Any] = {
    # All three are `@included`, and none is `@graph`.  `flows` was `@graph`
    # while it was the only thing in the document producing triples -- a node
    # object carrying nothing but `@graph` is a plain graph container, so its
    # contents landed in the default graph.  Add a second top-level key and the
    # document object becomes a *named* node, its `@graph` becomes a named
    # graph, and the flows end up in a blank-node-named graph while the
    # correspondences stay in the default one.  A consumer querying the default
    # graph would then see the correspondences and none of the flows.
    # `@included` keeps every node in the default graph whatever else is added.
    "flows": "@included",
    "concept_schemes": "@included",
    "correspondences": "@included",
    # `redirects` is `@included` for the same reason the other three are: its
    # entries are nodes about identifiers this document does not otherwise
    # describe, and they belong in the default graph with everything else.
    "redirects": "@included",
    "properties": "@nest",
    "cas_numbers": {"@id": IRIS[Term.CAS_REGISTRY_NUMBER], "@container": "@set"},
    "ec_numbers": {"@id": IRIS[Term.EC_NUMBER], "@container": "@set"},
    "unit_iri": {"@id": IRIS[Term.HAS_UNIT], "@type": "@id"},
    "context_iri": {"@id": IRIS[Term.FLOW_CONTEXT], "@type": "@id"},
    "origin_qualifier": {"@id": IRIS[Term.ORIGIN_QUALIFIER], "@type": "@id"},
    # The survivor's UUID, as a plain string beside the `dcterms:isReplacedBy`
    # IRI that already names it -- so a consumer holding UUIDs gets its answer
    # without doing string surgery on an IRI.  Mapped to `null`, which is how
    # JSON-LD says a key carries no statement: minting a predicate for "the
    # UUID at the other end of a link this document already publishes" would
    # put a second, weaker name on `dcterms:isReplacedBy`, and the redirect
    # records are the one place in the export where the JSON shape and the
    # graph shape are allowed to differ, because the JSON shape is the lookup
    # table #39 asked for.
    "replaced_by_identifier": None,
    "parent_flow_object_id": {
        "@id": IRIS[Term.BASE_SUBSTANCE], "@type": "@id",
    },
    "parent_intervention_id": {
        "@id": IRIS[Term.BASE_INTERVENTION], "@type": "@id",
    },
    "references": {
        "@id": IRIS[Term.SEE_ALSO], "@type": "@id", "@container": "@set",
    },
    # A set of *nodes*, not of literals: each row is `{"@id": ..., "rdfs:label":
    # ...}`, so the ChEBI class is a reference something else can say more
    # about.  No `@type: @id` here -- that coerces a plain string, and these are
    # already objects carrying their own `@id`.
    IRIS[Term.HAS_ROLE]: {"@container": "@set"},
}


def build_jsonld_context() -> dict[str, Any]:
    """Build the ``@context`` mapping from the registry.

    Includes namespace prefixes (so CURIEs such as ``prov:wasGeneratedBy``
    expand), short-name term definitions with their XSD datatype where they have
    one or their ``@language`` where they are text (:data:`LANGUAGE_TAGGED_TERMS`),
    and the published export's own key names.  Generating this rather than
    maintaining it by hand is what keeps it complete: a term cannot be emitted
    without being declared here.

    ``@version: 1.1`` is required by the ``@nest`` alias and is not optional.
    """
    context: dict[str, Any] = {"@version": 1.1}
    context.update(
        {namespace.name.lower(): namespace.value for namespace in Namespace}
    )
    for term in Term:
        datatype = TERM_DATATYPE.get(term)
        if datatype is not None:
            context[term.value] = {
                "@id": IRIS[term],
                "@type": datatype_curie(datatype),
            }
        elif term in LANGUAGE_TAGGED_TERMS:
            context[term.value] = {
                "@id": IRIS[term],
                "@language": EXPORT_LANGUAGE,
            }
        else:
            context[term.value] = IRIS[term]
    context.update(_EXPORT_KEY_TERMS)
    return context


JSONLD_CONTEXT: dict[str, Any] = build_jsonld_context()


# ── Canonical constants ──────────────────────────────────────────────────────
# Import these instead of re-declaring the literal. The names match those that
# were previously duplicated across modules, so call sites are unchanged.

RO_HAS_ROLE_IRI = IRIS[Term.HAS_ROLE]
CHEMINF_CAS_REGISTRY_NUMBER = IRIS[Term.CAS_REGISTRY_NUMBER]
CHEMINF_EC_NUMBER = IRIS[Term.EC_NUMBER]

CHEMROF_ATOMIC_NUMBER = IRIS[Term.ATOMIC_NUMBER]
CHEMROF_ELEMENTAL_CHARGE = IRIS[Term.ELEMENTAL_CHARGE]
CHEMROF_FORMAL_CHARGE = IRIS[Term.FORMAL_CHARGE]
CHEMROF_CHEMICAL_ELEMENT = IRIS[Term.CHEMICAL_ELEMENT]
CHEMROF_FULLY_SPECIFIED_ATOM = IRIS[Term.FULLY_SPECIFIED_ATOM]
CHEMROF_INCHI2D_KEY_STRING = IRIS[Term.INCHI2D_KEY_STRING]
CHEMROF_INCHI2D_STRING = IRIS[Term.INCHI2D_STRING]
CHEMROF_IUPAC_NAME = IRIS[Term.IUPAC_NAME]
CHEMROF_MOLECULAR_FORMULA = IRIS[Term.MOLECULAR_FORMULA]
CHEMROF_MOLECULAR_MASS = IRIS[Term.MOLECULAR_MASS]
CHEMROF_MONOATOMIC_ION = IRIS[Term.MONOATOMIC_ION]
CHEMROF_MONOISOTOPIC_MASS = IRIS[Term.MONOISOTOPIC_MASS]
CHEMROF_NEUTRON_NUMBER = IRIS[Term.NEUTRON_NUMBER]
CHEMROF_SMILES_STRING = IRIS[Term.SMILES_STRING]
CHEMROF_ISOMERIC_SMILES_STRING = IRIS[Term.ISOMERIC_SMILES_STRING]
CHEMROF_HAS_ELEMENT = IRIS[Term.HAS_ELEMENT]
CHEMROF_DECAY_MODE = IRIS[Term.DECAY_MODE]
CHEMROF_NUCLEON_NUMBER = IRIS[Term.NUCLEON_NUMBER]
CHEMROF_HALF_LIFE = IRIS[Term.HALF_LIFE]
CHEMROF_SYMBOL = IRIS[Term.SYMBOL]

DCTERMS_IS_REPLACED_BY = IRIS[Term.IS_REPLACED_BY]
OWL_DEPRECATED = IRIS[Term.DEPRECATED]
QUDT_HAS_UNIT = IRIS[Term.HAS_UNIT]

SKOS_BROADER_IRI = IRIS[Term.BROADER]
SKOS_RELATED_IRI = IRIS[Term.RELATED]
SKOS_BROAD_MATCH_IRI = IRIS[Term.BROAD_MATCH]
SKOS_CLOSE_MATCH_IRI = IRIS[Term.CLOSE_MATCH]
SKOS_DEFINITION_IRI = IRIS[Term.DEFINITION]
SKOS_EXACT_MATCH_IRI = IRIS[Term.EXACT_MATCH]
SKOS_PREF_LABEL_IRI = IRIS[Term.PREF_LABEL]
SKOS_RELATED_MATCH_IRI = IRIS[Term.RELATED_MATCH]
SKOS_IN_SCHEME_IRI = IRIS[Term.IN_SCHEME]
SKOS_CONCEPT_IRI = IRIS[Term.CONCEPT]

# Keys inside `concept_associations`, which is written with CURIEs throughout.
# The IRI forms above stay: they key the *record*, where every vocabulary field
# is expanded.  The two levels differ, and this is the seam.
SKOS_BROAD_MATCH_CURIE = curie(Term.BROAD_MATCH)
SKOS_CLOSE_MATCH_CURIE = curie(Term.CLOSE_MATCH)
SKOS_EXACT_MATCH_CURIE = curie(Term.EXACT_MATCH)
SKOS_NARROW_MATCH_CURIE = curie(Term.NARROW_MATCH)
SKOS_PREF_LABEL_CURIE = curie(Term.PREF_LABEL)
SKOS_RELATED_MATCH_CURIE = curie(Term.RELATED_MATCH)
SKOS_IN_SCHEME_CURIE = curie(Term.IN_SCHEME)
SKOS_CONCEPT_CURIE = curie(Term.CONCEPT)
SKOS_CONCEPT_SCHEME_CURIE = curie(Term.CONCEPT_SCHEME)

XKOS_CONCEPT_ASSOCIATION_CURIE = curie(Term.CONCEPT_ASSOCIATION)
XKOS_CORRESPONDENCE_CURIE = curie(Term.CORRESPONDENCE)
XKOS_COMPARES_CURIE = curie(Term.COMPARES)
XKOS_MADE_OF_CURIE = curie(Term.MADE_OF)
XKOS_SOURCE_CONCEPT_CURIE = curie(Term.SOURCE_CONCEPT)
XKOS_TARGET_CONCEPT_CURIE = curie(Term.TARGET_CONCEPT)

QUDT_HAS_UNIT_CURIE = curie(Term.HAS_UNIT)
QUDT_CONVERSION_MULTIPLIER_CURIE = curie(Term.CONVERSION_MULTIPLIER)
OWL_VERSION_INFO_CURIE = curie(Term.VERSION_INFO)
OWL_DEPRECATED_CURIE = curie(Term.DEPRECATED)
DCTERMS_IS_REPLACED_BY_CURIE = curie(Term.IS_REPLACED_BY)
DCTERMS_CREATED_CURIE = curie(Term.CREATED)
DCTERMS_CREATOR_CURIE = curie(Term.CREATOR)

# `rdfs:label` names the property entry itself -- "molecular formula" beside the
# value -- and is the most written CURIE in the project, in sixteen places
# before #233.
RDFS_LABEL_CURIE = curie(Term.LABEL)
RDFS_SEE_ALSO_CURIE = curie(Term.SEE_ALSO)

# The four keys `Provenance.to_dict()` writes, and which its readers look up
# again.  Both sides of that round trip are here, so a rename moves both.
PROV_WAS_GENERATED_BY_CURIE = curie(Term.WAS_GENERATED_BY)
PROV_WAS_ATTRIBUTED_TO_CURIE = curie(Term.WAS_ATTRIBUTED_TO)
PROV_HAD_PRIMARY_SOURCE_CURIE = curie(Term.HAD_PRIMARY_SOURCE)
PROV_WAS_DERIVED_FROM_CURIE = curie(Term.WAS_DERIVED_FROM)

BRIGHTWAY_FLOW_CONTEXT = IRIS[Term.FLOW_CONTEXT]
BRIGHTWAY_ORIGIN_QUALIFIER = IRIS[Term.ORIGIN_QUALIFIER]
BRIGHTWAY_BASE_SUBSTANCE = IRIS[Term.BASE_SUBSTANCE]
BRIGHTWAY_BASE_INTERVENTION = IRIS[Term.BASE_INTERVENTION]
BRIGHTWAY_SUMS_OVER = IRIS[Term.SUMS_OVER]
BRIGHTWAY_EXPRESSED_AS = IRIS[Term.EXPRESSED_AS]
BRIGHTWAY_AGGREGATE_MEASUREMENT = IRIS[Term.AGGREGATE_MEASUREMENT]

# CURIEs, not IRIs: both are written inside the correspondence, whose every
# other key -- `xkos:madeOf`, `skos:prefLabel`, `qudt:hasUnit` -- is a CURIE.
# A node that mixed the two conventions would expand the same either way and
# read as though the odd key came from somewhere else.
BRIGHTWAY_EXCLUDED_SOURCE_CONCEPT_CURIE = curie(Term.EXCLUDED_SOURCE_CONCEPT)
BRIGHTWAY_EXCLUSION_REASON_CURIE = curie(Term.EXCLUSION_REASON)
ORIGIN_QUALIFIER_IRI_PREFIX = MintedNamespace.ORIGIN_QUALIFIER_VALUES.value


def origin_qualifier_iri(qualifier: str) -> str:
    """The minted IRI for one origin qualifier, e.g. ``biogenic``."""
    return f"{ORIGIN_QUALIFIER_IRI_PREFIX}{qualifier}"


BRIGHTWAY_DEPRECATION_REASON = IRIS[Term.DEPRECATION_REASON]
DEPRECATION_REASON_IRI_PREFIX = MintedNamespace.DEPRECATION_REASON_VALUES.value

#: Why a flow was deprecated, as local names under
#: :attr:`MintedNamespace.DEPRECATION_REASON_VALUES`.
#:
#: Every deprecation this project makes comes from one place -- the duplicate
#: pass in `pipeline/deduplication.py`, which merges flows whose every semantic
#: field agrees -- but "agrees" is evaluated *after* the source contexts have
#: been mapped onto the consensus vocabulary, so two different source contexts
#: that collapse onto one consensus context produce two flows that look
#: identical.  Which of the two happened is the whole question for a consumer:
#: a redirect between flows that were always the same flow is safe to follow,
#: and one between flows the context vocabulary could not tell apart is a
#: merge of two things that may legitimately disagree (#1, #36).
DEPRECATION_REASONS: dict[str, str] = {
    #: The deprecated flow and its survivor came from the same source
    #: context(s): the same flow reached the list more than once.
    "identity-merge": "identity-merge",
    #: They came from different source contexts that map to the same consensus
    #: context.  Following the redirect merges two source-level distinctions.
    "context-collapse": "context-collapse",
    #: Neither side records a source context, so the two cannot be told apart.
    #: Present so the field is always populated; a consumer should treat it as
    #: unsafe rather than as either of the above.
    "unclassified": "unclassified",
    #: Nothing about the flow changed; this project changed how it names the
    #: flows it mints, and the old name is retired onto the new one (#102).
    #: Always safe to follow -- the two sides are one flow, not two flows judged
    #: to be the same -- which is why it is a fourth reason and not an
    #: `identity-merge` with a footnote.
    "identifier-scheme-change": "identifier-scheme-change",
    #: The source row this flow was minted from is one this list has decided
    #: not to map, so the flow is gone and **nothing replaces it** (#115).  The
    #: only reason whose record carries no `dcterms:isReplacedBy`, and the
    #: reason that field is optional: every other one names a survivor because
    #: the flow moved, and this one has no survivor to name because the flow
    #: should never have been minted.
    #:
    #: A consumer holding such an identifier has no redirect to follow and
    #: should drop the exchange.  Which row was withdrawn, and why, is on the
    #: source list's `xkos:Correspondence` under `brightway:excludedSourceConcept`.
    "source-row-withdrawn": "source-row-withdrawn",
}


def deprecation_reason_iri(reason: str) -> str:
    """The minted IRI for one deprecation reason, e.g. ``context-collapse``."""
    if reason not in DEPRECATION_REASONS:
        raise ValueError(
            f"{reason!r} is not a declared deprecation reason. Declared: "
            f"{', '.join(sorted(DEPRECATION_REASONS))}"
        )
    return f"{DEPRECATION_REASON_IRI_PREFIX}{reason}"
BIBO_STATUS_CURIE = curie(Term.STATUS)

#: The three publication states BIBO defines that this project uses.  Everything
#: it publishes is `accepted`: a flow that a curator has not settled is not in
#: the export at all.  The other two are here because the review workflow will
#: need them, and because a status vocabulary with one value invites someone to
#: invent a second one somewhere else.
BIBO_STATUS_ACCEPTED = f"{Namespace.BIBO.value}status/accepted"
BIBO_STATUS_DRAFT = f"{Namespace.BIBO.value}status/draft"
BIBO_STATUS_REJECTED = f"{Namespace.BIBO.value}status/rejected"

CONSENSUS_ELEMENTARY_FLOW_IRI_PREFIX = MintedNamespace.CONSENSUS_ELEMENTARY_FLOW.value
FLOW_OBJECT_IRI_PREFIX = MintedNamespace.FLOW_OBJECT.value


def flow_object_iri(flow_object_id: str) -> str:
    """The minted IRI for one flow object, e.g. ``fo-0bfffb5e4dadc218``."""
    return f"{FLOW_OBJECT_IRI_PREFIX}{flow_object_id}"


EF31_FLOW_IRI_PREFIX = MintedNamespace.EF31_FLOW.value
SIMAPRO_102_FLOW_IRI_PREFIX = MintedNamespace.SIMAPRO_102_FLOW.value
UNIT_IRI_PREFIX = MintedNamespace.UNITS.value
UNIT_IRI_GM_PER_MOL = f"{UNIT_IRI_PREFIX}GM-PER-MOL"
UNIT_IRI_NUM = f"{UNIT_IRI_PREFIX}NUM"
#: `chemrof:half_life` is a number of years, so the value carries the unit
#: that says so rather than leaving a reader to infer it from the slot name.
UNIT_IRI_YEAR = f"{UNIT_IRI_PREFIX}YR"


@dataclass(frozen=True)
class SourceScheme:
    """One source list, as a `skos:ConceptScheme`.

    `flow_prefix` is what a source concept's IRI starts with, and is how the
    export works out which scheme an association's source belongs to -- the
    associations are built per flow and carry only IRIs, so the scheme has to be
    recovered from the IRI itself.
    """

    slug: str
    scheme_iri: str
    flow_prefix: str
    label: str
    version: str


#: The source lists whose flows this project publishes correspondences to.
#:
#: ecoinvent is absent: its associations are written by the merge into
#: `flow_json` under IRIs it mints per version, and the export resolves those
#: through `ecoinvent_source_scheme` rather than from this fixed tuple.
SOURCE_SCHEMES: tuple[SourceScheme, ...] = (
    SourceScheme(
        slug="ef-3.1",
        scheme_iri=MintedNamespace.EF31_SCHEME.value,
        flow_prefix=MintedNamespace.EF31_FLOW.value,
        label="Environmental Footprint 3.1",
        version="3.1",
    ),
    SourceScheme(
        slug="bafu-2026-v1",
        scheme_iri=MintedNamespace.BAFU_2026_V1_SCHEME.value,
        flow_prefix=MintedNamespace.BAFU_2026_V1_FLOW.value,
        label="BAFU 2026 v1",
        version="2026-v1",
    ),
    SourceScheme(
        slug="stepwise-2006-1.09",
        scheme_iri=MintedNamespace.STEPWISE_2006_1_09_SCHEME.value,
        flow_prefix=MintedNamespace.STEPWISE_2006_1_09_FLOW.value,
        label="Stepwise 2006 v1.09",
        version="2006-1.09",
    ),
    SourceScheme(
        slug="agribalyse-3.2",
        scheme_iri=MintedNamespace.AGRIBALYSE_3_2_SCHEME.value,
        flow_prefix=MintedNamespace.AGRIBALYSE_3_2_FLOW.value,
        label="AGRIBALYSE 3.2",
        version="3.2",
    ),
    SourceScheme(
        slug="simapro-10.2",
        scheme_iri=MintedNamespace.SIMAPRO_102_SCHEME.value,
        flow_prefix=MintedNamespace.SIMAPRO_102_FLOW.value,
        label="SimaPro Professional 10.2",
        version="10.2",
    ),
)


def source_scheme(slug: str) -> SourceScheme:
    """The registered scheme named *slug*, e.g. ``simapro-10.2``.

    A manifest names the scheme its mappings target by slug, so a typo there has
    to fail where the manifest is read rather than produce associations that
    `build_correspondences` later drops as belonging to no scheme.

    :raises ValueError: if no registered scheme has that slug.
    """
    for scheme in SOURCE_SCHEMES:
        if scheme.slug == slug:
            return scheme
    known = ", ".join(sorted(row.slug for row in SOURCE_SCHEMES))
    raise ValueError(f"Unknown concept scheme {slug!r}. Registered schemes: {known}")


def ecoinvent_source_scheme(version: str) -> SourceScheme:
    """The `SourceScheme` for one ecoinvent release."""
    return SourceScheme(
        slug=f"ecoinvent-{version}",
        scheme_iri=MintedNamespace.ECOINVENT_SCHEME_TEMPLATE.value.format(version=version),
        flow_prefix=ecoinvent_flow_iri_prefix(version),
        label=f"ecoinvent {version}",
        version=version,
    )


def ecoinvent_flow_iri_prefix(version: str) -> str:
    """Return the minted IRI prefix for ecoinvent flows of *version*."""
    return MintedNamespace.ECOINVENT_FLOW_TEMPLATE.value.format(version=version)


#: An ecoinvent flow IRI, with its release captured.  Read from the IRI rather
#: than from a list of versions passed in: a caller sees only what the merge
#: wrote, and a release it was not told about would otherwise be dropped as
#: belonging to no scheme.
_ECOINVENT_FLOW_IRI = re.compile(
    re.escape(MintedNamespace.ECOINVENT_FLOW_TEMPLATE.value).replace(
        re.escape("{version}"), r"(?P<version>[^/]+)"
    )
)


def scheme_for_flow_iri(source_iri: str) -> SourceScheme | None:
    """Which source list does *source_iri* belong to?

    Longest prefix wins, so a scheme whose prefix is a prefix of another's
    cannot claim a flow that belongs to the more specific one.

    Here rather than in the export because it is asked twice: the export groups
    mappings into one correspondence per scheme, and
    :mod:`brightway_flows.pipeline.match_strength` counts how many of a
    scheme's flows share a consensus flow.  Both answers have to come from the
    same reading of the IRI, or a mapping could be weakened under one scheme and
    published under another.
    """
    best: SourceScheme | None = None
    for scheme in SOURCE_SCHEMES:
        if source_iri.startswith(scheme.flow_prefix) and (
            best is None or len(scheme.flow_prefix) > len(best.flow_prefix)
        ):
            best = scheme
    if best is not None:
        return best
    match = _ECOINVENT_FLOW_IRI.match(source_iri)
    return ecoinvent_source_scheme(match.group("version")) if match else None
