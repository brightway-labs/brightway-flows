"""`harmonised-flows-simple.json.gz` is projected from the database.

It is the only artifact with a downstream consumer.  It used to be written
inside `if harmonised-flows.json exists`, projected from that file -- so a 2.5 GB
intermediate was load-bearing for the one thing that has to keep working, and if
it was absent the export was silently skipped rather than failing.

Sourcing it from the database is what makes every other artifact deletable, so
these tests cover the properties that must survive that: the export happens
regardless of which JSON files exist, flow order is preserved, deprecated flows
are dropped, and an identifier is resolved for both of the record shapes the
`flow_json` column actually holds.
"""

import gzip
import sqlite3
import tempfile
import unittest
from pathlib import Path

import orjson

from brightway_flows.pipeline.exporting import build_simple_export, write_simple_export

#: The shape written for a flow that came from EF 3.1.
FLOW_SHAPED = {
    "uuid": "u-1",
    "identifier": "u-1",
    "source": "EF 3.1",
    "cas_numbers": ["124-38-9"],
    "ec_numbers": [],
    "context_iri": "https://vocab.brightway.one/flow-contexts/envi-air",
    "unit": "kg",
    "unit_iri": "https://vocab.brightway.one/units/unit/KiloGM",
    "prefLabel": [{"@value": "Carbon dioxide", "@language": "en"}],
    "altLabel": [],
    "properties": {},
    "references": [],
    "concept_associations": [],
}

#: The shape the merge writes into the same column: no `uuid`, no `identifier`.
ELEMENTARY_SHAPED = {
    "elementary_flow_id": "ef-2",
    "flow_object_id": "fo-2",
    "source": "ecoinvent manual addition",
    "cas_numbers": [],
    "ec_numbers": [],
    "context_iri": "https://vocab.brightway.one/flow-contexts/envi-air",
    "unit": "kg",
    "unit_iri": "https://vocab.brightway.one/units/unit/KiloGM",
    "prefLabel": [{"@value": "Methane", "@language": "en"}],
    "altLabel": [],
    "properties": {},
    "references": [],
    "concept_associations": [],
}


def build_db(path: Path, payloads):
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE elementary_flows (uuid TEXT PRIMARY KEY, flow_object_id TEXT, "
        "flow_json TEXT)"
    )
    for index, payload in enumerate(payloads):
        conn.execute(
            "INSERT INTO elementary_flows VALUES (?, ?, ?)",
            (f"row-{index}", "fo", orjson.dumps(payload).decode() if payload else None),
        )
    conn.commit()
    conn.close()


class SimpleExportTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        self.db = self.root / "consensus-flows.sqlite3"

    def read(self, path: Path):
        return orjson.loads(gzip.decompress(path.read_bytes()))

    def test_export_is_written_with_no_json_files_present(self):
        """The regression this change exists for.

        Nothing but the database is in the directory; the export must still
        appear.  Previously it was skipped without a word.
        """
        build_db(self.db, [FLOW_SHAPED])
        out = self.root / "harmonised-flows-simple.json.gz"
        self.assertEqual(write_simple_export(self.db, out), 1)
        self.assertTrue(out.exists())
        self.assertEqual(self.read(out)["flows"][0]["identifier"], "u-1")

    def test_both_record_shapes_resolve_an_identifier(self):
        """One column, two shapes: `uuid` for EF flows, `elementary_flow_id`
        for the ones the merge created."""
        build_db(self.db, [FLOW_SHAPED, ELEMENTARY_SHAPED])
        flows = build_simple_export(self.db).flows
        self.assertEqual([f.identifier for f in flows], ["u-1", "ef-2"])

    def test_flow_order_follows_insertion_order(self):
        build_db(self.db, [ELEMENTARY_SHAPED, FLOW_SHAPED])
        self.assertEqual(
            [f.identifier for f in build_simple_export(self.db).flows], ["ef-2", "u-1"]
        )

    def test_deprecated_flows_are_excluded(self):
        deprecated = dict(FLOW_SHAPED, uuid="u-3", identifier="u-3")
        deprecated["http://www.w3.org/2002/07/owl#deprecated"] = True
        build_db(self.db, [FLOW_SHAPED, deprecated])
        self.assertEqual(
            [f.identifier for f in build_simple_export(self.db).flows], ["u-1"]
        )

    def test_rows_without_a_payload_are_skipped(self):
        build_db(self.db, [FLOW_SHAPED, None])
        self.assertEqual(len(build_simple_export(self.db).flows), 1)

    def test_a_flow_with_no_unit_is_an_error(self):
        """Units are load-bearing downstream; exporting a blank one is worse
        than failing."""
        build_db(self.db, [dict(FLOW_SHAPED, unit="")])
        with self.assertRaises(ValueError) as ctx:
            build_simple_export(self.db)
        self.assertIn("u-1", str(ctx.exception))

    def test_envelope_carries_the_schema_version(self):
        """From the constant, not a literal.  The export used to write `1`
        outright, so a bump would have left the artifact contradicting the
        schema that describes it -- and the drift guard compares schema to
        schema, so it would not have noticed."""
        from brightway_flows.domain.schema import SCHEMA_VERSION

        build_db(self.db, [FLOW_SHAPED])
        out = self.root / "simple.json.gz"
        write_simple_export(self.db, out)
        payload = self.read(out)
        self.assertEqual(payload["schema_version"], SCHEMA_VERSION)
        # `@context` leads: it is what makes the rest of the document mean
        # anything, and a reader that streams the file wants it first.
        self.assertEqual(
            list(payload),
            ["@context", "schema_version", "flows", "redirects",
             "concept_schemes", "correspondences"],
        )

    def test_published_field_set_is_unchanged(self):
        """These field names are the downstream contract.

        `@id` and `@type` joined them in #9 and #227: the same flow as an IRI,
        and what kind of thing it is.  `concept_associations` left in #229 --
        the mappings are nodes of their own now, under the correspondence for
        their source list, and a flow's are found by `xkos:targetConcept`.
        """
        build_db(self.db, [FLOW_SHAPED])
        out = self.root / "simple.json.gz"
        write_simple_export(self.db, out)
        self.assertEqual(
            list(self.read(out)["flows"][0]),
            ["identifier", "source", "cas_numbers", "ec_numbers", "context_iri",
             "unit", "unit_iri", "prefLabel", "altLabel", "properties",
             "references", "definition", "@id", "@type",
             "http://www.w3.org/2004/02/skos/core#inScheme"],
        )


class LabelsAreStrippedOfMarkupTestCase(unittest.TestCase):
    """Every published label is text, not markup (#216).

    #211 stripped `altLabel` and `definition` and left `prefLabel` carrying
    `<sub>` and `<em>` on 66 flows, because the export parsed `prefLabel` with a
    second reader of its own that never called `strip_markup` -- while the other
    two went through `coerce_label`, where the stripping lives.  Downstream reads
    all three as text.

    These pin the property rather than the one field: a label leaves the export
    stripped whichever field it is in.
    """

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        self.db = self.root / "consensus-flows.sqlite3"

    def export(self, **overrides):
        build_db(self.db, [{**FLOW_SHAPED, **overrides}])
        return build_simple_export(self.db).flows[0]

    def test_pref_label_markup_is_stripped(self):
        flow = self.export(prefLabel=[{
            "@value": "Fatty acids, C<sub>18</sub>-unsatd., trimers",
            "@language": "en",
        }])
        self.assertEqual(flow.prefLabel, "Fatty acids, C18-unsatd., trimers")

    def test_emphasis_inside_a_name_keeps_the_letter(self):
        """`<em>N</em>` is a typographic convention around a meaningful letter,
        so the tag goes and the `N` stays."""
        flow = self.export(prefLabel=[{
            "@value": "compd. with <em>N</em>,<em>N</em>-diethylpropanediamine",
            "@language": "en",
        }])
        self.assertEqual(
            flow.prefLabel, "compd. with N,N-diethylpropanediamine"
        )

    def test_alt_labels_are_stripped_the_same_way(self):
        """They already were; this keeps the two fields from drifting apart
        again, which is the whole shape of this bug."""
        flow = self.export(altLabel=[{
            "@value": "Hydrocarbons, C<sub>4-6</sub>", "@language": "en",
        }])
        self.assertEqual(flow.altLabel, ["Hydrocarbons, C4-6"])

    def test_character_references_are_resolved(self):
        flow = self.export(prefLabel=[{
            "@value": "N&#39;-nitrosomethylharnstoff", "@language": "en",
        }])
        self.assertEqual(flow.prefLabel, "N'-nitrosomethylharnstoff")


class PrefLabelSelectionTestCase(unittest.TestCase):
    """What the deleted second reader did, that still has to happen.

    Replacing it with `flow_label_value` is only safe if the selection rules
    survive, so they are asserted here rather than assumed.
    """

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        self.db = self.root / "consensus-flows.sqlite3"

    def export(self, pref):
        build_db(self.db, [{**FLOW_SHAPED, "prefLabel": pref}])
        return build_simple_export(self.db).flows[0].prefLabel

    def test_english_wins_over_declaration_order(self):
        self.assertEqual(
            self.export([
                {"@value": "Kohlendioxid", "@language": "de"},
                {"@value": "Carbon dioxide", "@language": "en"},
            ]),
            "Carbon dioxide",
        )

    def test_the_first_label_is_used_when_none_is_english(self):
        self.assertEqual(
            self.export([
                {"@value": "Kohlendioxid", "@language": "de"},
                {"@value": "Dioxyde de carbone", "@language": "fr"},
            ]),
            "Kohlendioxid",
        )

    def test_a_bare_string_is_accepted(self):
        self.assertEqual(self.export("Carbon dioxide"), "Carbon dioxide")

    def test_the_lang_spelling_is_honoured(self):
        """`@lang` as well as `@language`; the pipeline writes both, and the
        reader this replaced only looked at one of them in some branches."""
        self.assertEqual(
            self.export([
                {"@value": "Kohlendioxid", "@lang": "de"},
                {"@value": "Carbon dioxide", "@lang": "en"},
            ]),
            "Carbon dioxide",
        )

    def test_an_empty_pref_label_exports_as_empty(self):
        self.assertEqual(self.export([]), "")


if __name__ == "__main__":
    unittest.main()
