"""The records a characterisation is made of, and the methods they are built from.

One import site for both halves of
:mod:`~brightway_flows.domain.lcia.records` -- what a publisher stated, and
what this list publishes -- plus
:mod:`~brightway_flows.domain.lcia.crosswalk`, which reads one file per
method: its implementations, and what each of them calls each category.
"""

from brightway_flows.domain.lcia.crosswalk import (
    CONSENSUS_IMPLEMENTATION,
    FactorRoute,
    FactorSpec,
    ImpactCategoryDefinition,
    ImplementationRole,
    LCIAMethodDefinition,
    MethodImplementation,
    StatedCategoryName,
    impact_categories,
    lcia_method,
    lcia_methods,
)
from brightway_flows.domain.lcia.records import (
    AreaOfProtection,
    CharacterizationFactor,
    ImpactCategory,
    ImpactCategoryCharacterizationFactorMismatch,
    ImpactTimeframe,
    LCIAError,
    LCIAMethod,
    MidpointEndpoint,
    StatedCategory,
    StatedFactor,
    SupersededValue,
    UncertaintyLevel,
)

__all__ = [
    # What a publisher stated.
    "StatedCategory",
    "StatedFactor",
    "SupersededValue",
    # What this list publishes.
    "AreaOfProtection",
    "CharacterizationFactor",
    "ImpactCategory",
    "ImpactTimeframe",
    "LCIAMethod",
    "MidpointEndpoint",
    "UncertaintyLevel",
    # The methods, and the crosswalk between their implementations.
    "CONSENSUS_IMPLEMENTATION",
    "FactorRoute",
    "FactorSpec",
    "ImpactCategoryDefinition",
    "ImplementationRole",
    "LCIAMethodDefinition",
    "MethodImplementation",
    "StatedCategoryName",
    "impact_categories",
    "lcia_method",
    "lcia_methods",
    # Errors.
    "ImpactCategoryCharacterizationFactorMismatch",
    "LCIAError",
]
