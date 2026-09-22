"""Characterisation: what a flow is worth under an impact category, and to whom.

The third layer of the list.  A flow object is a substance, an elementary flow
is that substance in a context, and a characterisation is a statement about one
of those flows and one impact category, made by somebody -- and the somebody is
the part that has never been recorded.

``plans/lcia-factors.md`` is the design.  ``characterise`` publishes every method
registered in ``domain.lcia.crosswalk`` -- EF 3.1 today, as the JRC published it
and as the ecoinvent Centre implemented it, plus this list's own derived from the
two.  A method is a file, and nothing in this package names one.

| Module | Responsibility |
|---|---|
| ``pipeline`` | ``characterise``: the order the steps below run in, once per method |
| ``categories`` | the ``ImpactCategory`` objects of every implementation, and the IRI and id of each |
| ``sources`` | where one implementation's factors are read from |
| ``matching`` | getting a factor onto a consensus flow, and what two arriving costs |
| ``contradictions`` | what the model a method is derived from says, where it says something else |
| ``report`` | what could not be done, as rows |
| ``store`` | the LCIA tables, in the file ``build`` wrote |
"""

from brightway_flows.lcia.categories import (
    consensus_categories_for,
    impact_categories_for,
    impact_category_id,
    impact_category_iri,
    published_impact_categories,
    published_method,
)
from brightway_flows.lcia.pipeline import characterise

__all__ = [
    "characterise",
    "consensus_categories_for",
    "impact_categories_for",
    "impact_category_id",
    "impact_category_iri",
    "published_impact_categories",
    "published_method",
]
