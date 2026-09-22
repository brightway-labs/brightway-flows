"""A merge updates the published export from the database.

This replaces `test_merge_harmonised_update.py`, which asserted that the merge
updated `harmonised-flows.json` and then projected the export from it. That file
is gone: it was a 2.5 GB denormalised duplicate whose only remaining job was to
be the source of a 200 KB export, and the export now comes from the database.

What has to stay true is the part with a downstream consumer: after a merge, the
export reflects every non-deprecated flow, including the ones the merge created.
"""

import gzip
import sqlite3
import tempfile
import unittest
from pathlib import Path

import orjson

from brightway_flows.pipeline.exporting import build_simple_export, write_simple_export


def flow_payload(uuid: str, source: str = "EF 3.1", **overrides) -> dict:
    payload = {
        "uuid": uuid,
        "identifier": uuid,
        "source": source,
        "cas_numbers": [],
        "ec_numbers": [],
        "context_iri": "https://vocab.brightway.one/flow-contexts/envi-air",
        "unit": "kg",
        "unit_iri": "https://vocab.brightway.one/units/unit/KiloGM",
        "prefLabel": [{"@value": f"Flow {uuid}", "@language": "en"}],
        "altLabel": [],
        "properties": {},
        "references": [],
        "concept_associations": [],
        "lcia_methods": [{"method": "data"}],
    }
    payload.update(overrides)
    return payload


class ExportAfterMergeTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        self.db = self.root / "consensus-flows.sqlite3"
        conn = sqlite3.connect(self.db)
        conn.execute(
            "CREATE TABLE elementary_flows (uuid TEXT PRIMARY KEY, flow_json TEXT)"
        )
        conn.commit()
        conn.close()

    def add(self, payload: dict):
        conn = sqlite3.connect(self.db)
        conn.execute(
            "INSERT INTO elementary_flows VALUES (?, ?)",
            (payload.get("uuid") or payload["elementary_flow_id"],
             orjson.dumps(payload).decode()),
        )
        conn.commit()
        conn.close()

    def test_flows_the_merge_created_reach_the_export(self):
        self.add(flow_payload("u-1"))
        self.add(flow_payload("ef-2", source="ecoinvent algorithm addition"))
        identifiers = [f.identifier for f in build_simple_export(self.db).flows]
        self.assertEqual(identifiers, ["u-1", "ef-2"])

    def test_lcia_methods_are_stripped(self):
        """The published export is the list without characterisation factors."""
        self.add(flow_payload("u-1"))
        out = self.root / "simple.json.gz"
        write_simple_export(self.db, out)
        payload = orjson.loads(gzip.decompress(out.read_bytes()))
        self.assertNotIn("lcia_methods", payload["flows"][0])

    def test_concept_associations_survive_as_a_correspondence(self):
        """The merge's mappings still reach the export -- somewhere else.

        They used to hang off the flow under an undeclared key. They are now
        `xkos:ConceptAssociation` nodes collected by the `xkos:Correspondence`
        for their source list, which is the shape XKOS actually defines.
        """
        association = {
            "@type": "xkos:ConceptAssociation",
            "xkos:sourceConcept": {
                "@id": "https://vocab.brightway.one/ecoinvent/3.12/flow/x"
            },
            "xkos:targetConcept": {
                "@id": "https://vocab.brightway.dev/elementary-flows/u-1"
            },
        }
        self.add(flow_payload("u-1", concept_associations=[association]))
        export = build_simple_export(self.db)
        self.assertEqual(len(export.correspondences), 1)
        correspondence = export.correspondences[0]
        self.assertEqual(
            correspondence.jsonld_id,
            "https://vocab.brightway.dev/correspondences/ecoinvent-3.12",
        )
        self.assertEqual(len(correspondence.made_of), 1)
        self.assertEqual(
            correspondence.made_of[0].source_concept, association["xkos:sourceConcept"]
        )

    def test_an_ecoinvent_release_is_read_from_the_flow_iri(self):
        """The export is told no version list; it reads the release off the IRI."""
        self.add(flow_payload("u-1", concept_associations=[{
            "xkos:sourceConcept": {
                "@id": "https://vocab.brightway.one/ecoinvent/3.8/flow/x"
            },
            "xkos:targetConcept": {
                "@id": "https://vocab.brightway.dev/elementary-flows/u-1"
            },
        }]))
        export = build_simple_export(self.db)
        self.assertEqual(
            [c.jsonld_id for c in export.correspondences],
            ["https://vocab.brightway.dev/correspondences/ecoinvent-3.8"],
        )

    def test_deprecated_flows_do_not_reach_the_export(self):
        self.add(flow_payload("u-1"))
        self.add(flow_payload(
            "u-2", **{"http://www.w3.org/2002/07/owl#deprecated": True}))
        self.assertEqual(
            [f.identifier for f in build_simple_export(self.db).flows], ["u-1"]
        )


if __name__ == "__main__":
    unittest.main()
