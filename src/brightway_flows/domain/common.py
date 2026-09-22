from dataclasses import dataclass, field
from typing import Any

from brightway_flows.domain.vocabulary import (
    PROV_HAD_PRIMARY_SOURCE_CURIE,
    PROV_WAS_ATTRIBUTED_TO_CURIE,
    PROV_WAS_DERIVED_FROM_CURIE,
    PROV_WAS_GENERATED_BY_CURIE,
)


@dataclass
class Provenance:
    was_generated_by: str
    was_attributed_to: str
    id: str | None = None
    types: list[str] = field(default_factory=list)
    had_primary_source: list[str] = field(default_factory=list)
    was_derived_from: str | None = None

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            PROV_WAS_GENERATED_BY_CURIE: self.was_generated_by,
            PROV_WAS_ATTRIBUTED_TO_CURIE: self.was_attributed_to,
        }
        if self.id:
            payload["@id"] = self.id
        if self.types:
            payload["@type"] = self.types
        if self.had_primary_source:
            payload[PROV_HAD_PRIMARY_SOURCE_CURIE] = self.had_primary_source
        if self.was_derived_from:
            payload[PROV_WAS_DERIVED_FROM_CURIE] = self.was_derived_from
        return payload

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "Provenance":
        """The inverse of :meth:`to_dict`.

        For a record that is read back as well as written -- a characterisation
        factor carries its provenance through a file and into the next run, and
        rebuilding it as a record is what keeps the field from being a dict
        inside the pipeline.

        Raises on a key it does not know, rather than dropping it.  This is the
        inverse of a method whose output is published: a key silently lost here
        is a key silently missing from the next artifact, which is the failure
        mode a round trip exists to rule out.
        """
        known = {
            PROV_WAS_GENERATED_BY_CURIE,
            PROV_WAS_ATTRIBUTED_TO_CURIE,
            PROV_HAD_PRIMARY_SOURCE_CURIE,
            PROV_WAS_DERIVED_FROM_CURIE,
            "@id",
            "@type",
        }
        unknown = sorted(set(payload) - known)
        if unknown:
            raise ValueError(
                f"Provenance payload has keys this record cannot hold: "
                f"{', '.join(unknown)}."
            )
        types = payload.get("@type") or []
        return cls(
            was_generated_by=str(payload.get(PROV_WAS_GENERATED_BY_CURIE) or ""),
            was_attributed_to=str(payload.get(PROV_WAS_ATTRIBUTED_TO_CURIE) or ""),
            id=payload.get("@id"),
            types=list(types) if isinstance(types, list) else [types],
            had_primary_source=list(
                payload.get(PROV_HAD_PRIMARY_SOURCE_CURIE) or []
            ),
            was_derived_from=payload.get(PROV_WAS_DERIVED_FROM_CURIE),
        )
