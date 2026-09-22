"""Transformer package exports and default pipeline order."""

from brightway_flows.transformers.apply_structure_corrections import (
    ApplyStructureCorrectionsTransformer,
)
from brightway_flows.transformers.bootstrap_labels import BootstrapLabelsTransformer
from brightway_flows.transformers.chebi_altlabels import ChebiAltLabelsTransformer
from brightway_flows.transformers.check_digits import (
    CheckDigitTransformer,
    correct_cas,
    correct_ec,
)
from brightway_flows.transformers.commonchem_cas_review import (
    CommonchemCasReviewTransformer,
)
from brightway_flows.transformers.consensus_match import ConsensusMatchTransformer
from brightway_flows.transformers.dedupe_altlabels import DedupeAltLabelsTransformer
from brightway_flows.transformers.default_context_mapping import (
    DefaultContextMappingTransformer,
)
from brightway_flows.transformers.ec_cross_check import ECCrossCheckTransformer
from brightway_flows.transformers.enrich_references import (
    EnrichReferencesTransformer,
)
from brightway_flows.transformers.normalize_name_case import (
    NormalizeNameCaseTransformer,
)
from brightway_flows.transformers.opsin_iupac import OPSINTransformer
from brightway_flows.transformers.pubchem import PubChemTransformer
from brightway_flows.transformers.registry_number_from_name import (
    RegistryNumberFromNameTransformer,
)
from brightway_flows.transformers.rdkit_authoritative import (
    RDKitAuthoritativeTransformer,
)
from brightway_flows.transformers.rdkit_enrichment import (
    RDKitPreConsensusTransformer,
)
from brightway_flows.transformers.withhold_ambiguous_mass import (
    WithholdAmbiguousMassTransformer,
)
from brightway_flows.transformers.withhold_contradicted_composition import (
    WithholdContradictedCompositionTransformer,
)
from brightway_flows.transformers.rdkit_post_consensus import (
    RDKitPostConsensusTransformer,
)
from brightway_flows.transformers.strip_cross_object_altlabels import (
    StripCrossObjectAltLabelsTransformer,
)
from brightway_flows.transformers.supply_registered_composition import (
    SupplyRegisteredCompositionTransformer,
)
from brightway_flows.transformers.supply_registered_structure import (
    SupplyRegisteredStructureTransformer,
)
from brightway_flows.transformers.strip_element_symbol_altlabels import (
    StripElementSymbolAltLabelsTransformer,
)
from brightway_flows.transformers.strip_catalogue_altlabels import (
    StripCatalogueAltLabelsTransformer,
)
from brightway_flows.transformers.strip_names import StripNamesTransformer
from brightway_flows.transformers.strip_product_families import (
    StripProductFamiliesTransformer,
)
from brightway_flows.transformers.strip_qualifier_altlabels import (
    StripQualifierAltLabelsTransformer,
)
from brightway_flows.transformers.unit_normalization import (
    UnitNormalizationTransformer,
)

DEFAULT_TRANSFORMERS = [
    BootstrapLabelsTransformer,
    DefaultContextMappingTransformer,
    UnitNormalizationTransformer,
    StripNamesTransformer,
    NormalizeNameCaseTransformer,
    CommonchemCasReviewTransformer,
    # After the Common Chemistry fill-in, so a number that service settled on
    # is never overruled by a name; before the check digits, so a number this
    # step introduces is validated like any other; and well before
    # `enrich_references`, which is what a registry number is *for* -- a flow
    # that reaches it without one gets no structure, no formula and no
    # references (#71).
    RegistryNumberFromNameTransformer,
    CheckDigitTransformer,
    ECCrossCheckTransformer,
    EnrichReferencesTransformer,
    RDKitPreConsensusTransformer,
    ChebiAltLabelsTransformer,
    StripCrossObjectAltLabelsTransformer,
    StripElementSymbolAltLabelsTransformer,
    ConsensusMatchTransformer,
    OPSINTransformer,
    RDKitAuthoritativeTransformer,
    RDKitPostConsensusTransformer,
    # After every writer that *derives* a composition, because it only fills a
    # hole and "there is no formula" is not settled until they have all run.
    # Before `withhold_contradicted_composition`, so what it supplies is judged
    # by the same rule as everything else rather than slipped in behind it --
    # it agrees with the registry by construction, and a step whose output is
    # exempt from the check is a step nobody can catch (#129).
    SupplyRegisteredCompositionTransformer,
    # Beside its sibling above and immediately after it, because the two answer
    # the same question about the same numbers: the composition step publishes
    # what CAS says a substance is *made of*, this one what CAS says it *is*.
    # Both must follow every step that derives a structural value, so that each
    # only ever fills a hole rather than pre-empting a derivation, and both must
    # precede `withhold_contradicted_composition`, so what they publish is
    # judged by the same rule as everything else (#129, #71).
    #
    # The cost of being this late is that no RDKit step remains to compute a
    # mass or a SMILES from the InChI this one supplies, and that is accepted:
    # a step placed early enough to get them would be overruling derivations
    # rather than filling holes.
    SupplyRegisteredStructureTransformer,
    # After every writer of a structural value -- the registry's, ChEBI's,
    # PubChem's, the name reader's and all three RDKit steps -- because it
    # judges what the record ends up publishing, and a value arriving after it
    # would be judged by nothing.  Before `withhold_ambiguous_mass`, so a mass
    # withdrawn here is not first weighed as though the record still held the
    # formula it belongs to (#310).
    WithholdContradictedCompositionTransformer,
    # Last of the structural steps, and after the two that judge evidence,
    # because it is not evidence: a curated structure is asserted on a
    # curator's authority and a decision a later derivation could reverse
    # would not be one (#129).
    ApplyStructureCorrectionsTransformer,
    WithholdAmbiguousMassTransformer,
    StripQualifierAltLabelsTransformer,
    # After every writer of an alternative label, because the catalogue codes it
    # removes are written by `chebi_altlabels` and `consensus_match`, and before
    # the dedupe so the deduplicated list is the published one.
    StripCatalogueAltLabelsTransformer,
    # After the per-label shapes, because the family rule counts what survives
    # them: a family whose members are already gone is not a family, and the
    # `MIN_OBJECT_LABELS` gate has to read the same list the build publishes.
    StripProductFamiliesTransformer,
    DedupeAltLabelsTransformer,
    # `PubChemReadableNameTransformer` ran here, nineteenth, and #21 removed it:
    # a PubChem record title taken from a single source with no agreement
    # requirement, applied to 17,942 published labels a run with no ruling and no
    # queue, and last in line so its label was the one that shipped.  Enabling
    # `PubChemTransformer` below would reintroduce the same thing by another
    # name -- it replaces a preferred label with PubChem's name for the flow's
    # CAS, which is what the `entropy` rule did before #222 removed it.
    # PubChemTransformer,  # Enable when you want automatic name replacement.
]

__all__ = [
    "DEFAULT_TRANSFORMERS",
    "BootstrapLabelsTransformer",
    "DefaultContextMappingTransformer",
    "StripNamesTransformer",
    "NormalizeNameCaseTransformer",
    "CommonchemCasReviewTransformer",
    "RegistryNumberFromNameTransformer",
    "CheckDigitTransformer",
    "ECCrossCheckTransformer",
    "EnrichReferencesTransformer",
    "OPSINTransformer",
    "RDKitAuthoritativeTransformer",
    "RDKitPreConsensusTransformer",
    "RDKitPostConsensusTransformer",
    "WithholdAmbiguousMassTransformer",
    "WithholdContradictedCompositionTransformer",
    "SupplyRegisteredCompositionTransformer",
    "SupplyRegisteredStructureTransformer",
    "ApplyStructureCorrectionsTransformer",
    "ChebiAltLabelsTransformer",
    "StripCrossObjectAltLabelsTransformer",
    "StripQualifierAltLabelsTransformer",
    "StripCatalogueAltLabelsTransformer",
    "StripProductFamiliesTransformer",
    "StripElementSymbolAltLabelsTransformer",
    "ConsensusMatchTransformer",
    "DedupeAltLabelsTransformer",
    "PubChemTransformer",
    "UnitNormalizationTransformer",
    "correct_cas",
    "correct_ec",
]
