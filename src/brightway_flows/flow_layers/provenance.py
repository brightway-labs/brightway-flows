"""Provenance for the values the element and ion enrichments write.

The activity name is a published string: it appears as `prov:wasGeneratedBy` on
every property those two passes write, and `pipeline.engine` names it when it
re-attributes them.  It keeps its `flow_layers.` prefix, which is now the
package rather than the module.
"""

from __future__ import annotations

from typing import Any

from brightway_flows.domain.common import Provenance

#: `prov:wasGeneratedBy` for element, isotope and monoatomic-ion enrichment.
ELEMENT_ENRICHMENT_GENERATED_BY = "flow_layers.pubchem_element_enrichment"


def _element_property_provenance(
    *,
    source_urls: list[str],
    derived_from: str,
) -> dict[str, Any]:
    return Provenance(
        was_generated_by=ELEMENT_ENRICHMENT_GENERATED_BY,
        was_attributed_to="brightway-flows",
        had_primary_source=source_urls,
        was_derived_from=derived_from,
    ).to_dict()
