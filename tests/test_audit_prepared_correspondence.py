"""The correspondence audit flags a confused substance and excuses a scheme.

The prepared table routes rows two ways this project accepts -- dissolved
metals by compartment onto the ion or the element, and ore-content resource
flows onto EF's elemental resources -- and those must not drown the thing the
audit exists to catch: a row landing on a flow object that is a *different
substance* from the one its own registry number names, while that number
resolves cleanly elsewhere (#130, #140).

The cases here are the shapes the 2026-08-22 scan found in the real build, cut
to one row each.  The one worth singling out is tin: ``Tin, Ion`` states the
CAS of tin(4+) and the table lands it on ``Tin(2+)``.  Both labels are charged
forms of one element, so a speciation whitelist written as "same element" would
excuse it -- and it is exactly a substance confusion.  The whitelist therefore
demands that exactly one side be the bare element, and this file is where that
stays true.
"""

import importlib.util
import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path


def _load_tool():
    """`tools/` is not a package; the tool is a script, loaded here by path."""
    path = (
        Path(__file__).resolve().parent.parent
        / "tools"
        / "audit_prepared_correspondence.py"
    )
    spec = importlib.util.spec_from_file_location("audit_prepared_correspondence", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not load the audit tool from {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules["audit_prepared_correspondence"] = module
    spec.loader.exec_module(module)
    return module


tool = _load_tool()


def _cas_payload(*numbers: str) -> str:
    return json.dumps({tool.CAS_CLASSIFICATION_IRI: {"@value": list(numbers)}})


#: (flow_object_id, label, classifications_json)
OBJECTS = (
    ("fo-metaldehyde-full", "Metaldehyde", _cas_payload("108-62-3")),
    ("fo-metaldehyde-stub", "Metaldehyde", _cas_payload("9002-91-9")),
    ("fo-nickel", "Nickel", _cas_payload("7440-02-0")),
    ("fo-nickel-ion", "Nickel(2+)", _cas_payload("14701-22-5")),
    ("fo-tin-2", "Tin(2+)", _cas_payload("22541-90-8")),
    ("fo-tin-4", "Tin(4+)", _cas_payload("22537-50-4")),
    ("fo-aluminium", "Aluminium", _cas_payload("7429-90-5")),
    ("fo-bauxite", "Bauxite", _cas_payload("1318-16-7")),
    ("fo-borate", "Borate", ""),
    ("fo-thiocyanate", "Thiocyanate", _cas_payload("302-04-5")),
    ("fo-thiocyanate-ion", "Thiocyanate, Ion", _cas_payload("71048-69-6")),
)

#: (source_name, source_cas, source_uuid, flow_object_id) -- one prepared row each.
ROWS = (
    # The #130 shape: the row's CAS lives on the characterised twin.
    ("Metaldehyde", "108-62-3", "u-metaldehyde", "fo-metaldehyde-stub"),
    # An ion row landing on the bare element: a substance confusion since the
    # speciation whitelist retired (plan section 3a).
    ("Nickel II", "14701-22-5", "u-nickel-ii", "fo-nickel"),
    # The tin slip: two charged forms of one element.
    ("Tin, Ion", "22537-50-4", "u-tin-ion", "fo-tin-2"),
    # A polyatomic ion has no elemental form: this is #130's twin.
    ("Thiocyanate", "302-04-5", "u-thiocyanate", "fo-thiocyanate-ion"),
    # Ore-grade translation names its grade in the flow name.
    ("Aluminium, 24% In Bauxite, 11% In Crude Ore, In Ground", "1318-16-7",
     "u-bauxite-ore", "fo-aluminium"),
    # Agreement, a stated CAS this list has nowhere, and no CAS at all.
    ("Nickel", "7440-02-0", "u-nickel", "fo-nickel"),
    ("Kieserite, In Ground", "14567-64-7", "u-kieserite", "fo-borate"),
    ("Occupation, Annual Crop", "", "u-occupation", "fo-borate"),
)


class AuditTestCase(unittest.TestCase):
    def setUp(self):
        directory = self.enterContext(tempfile.TemporaryDirectory())
        self.db_path = Path(directory) / "consensus-flows.sqlite3"
        db = sqlite3.connect(self.db_path)
        db.execute(
            "CREATE TABLE flow_objects (flow_object_id TEXT, pref_label_value TEXT,"
            " classifications_json TEXT)"
        )
        db.execute(
            "CREATE TABLE merge_outcomes (source_name TEXT, source_cas TEXT,"
            " source_uuid TEXT, flow_object_id TEXT, list_version TEXT,"
            " matching_method TEXT)"
        )
        db.executemany("INSERT INTO flow_objects VALUES (?, ?, ?)", OBJECTS)
        db.executemany(
            "INSERT INTO merge_outcomes VALUES (?, ?, ?, ?, '3.12', 'prepared')",
            ROWS,
        )
        # A non-prepared row must not be audited at all.
        db.execute(
            "INSERT INTO merge_outcomes VALUES ('Metaldehyde', '108-62-3',"
            " 'u-metaldehyde', 'fo-metaldehyde-stub', '3.12', 'algorithm')"
        )
        db.commit()
        db.close()
        # Hermetic: the empty signature set, so the shipped override files'
        # own signatures cannot reach a synthetic build's classification.
        self.by_name = {
            group.source_name: group
            for group in tool.load_groups(self.db_path, signed=frozenset())
        }

    def test_every_prepared_row_is_binned_and_nothing_else_is(self):
        self.assertEqual(len(self.by_name), len(ROWS))
        # The algorithm row did not inflate the prepared Metaldehyde group.
        self.assertEqual(self.by_name["Metaldehyde"].rows, 1)

    def test_the_twin_shape_is_contradicted(self):
        group = self.by_name["Metaldehyde"]
        self.assertEqual(group.category, tool.CONTRADICTED)
        self.assertIn("'Metaldehyde'", group.detail)

    def test_an_element_ion_confusion_is_contradicted_not_excused(self):
        # The speciation whitelist retired with the tables it excused (plan
        # section 3a): the compartment routing it described was the vendor's
        # modelling, and a curated row of ours that lands an element-numbered
        # row on the ion's object is a decision to write down or a defect to
        # fix, never a scheme.
        self.assertEqual(self.by_name["Nickel II"].category, tool.CONTRADICTED)

    def test_two_charged_forms_of_one_element_flag(self):
        self.assertEqual(self.by_name["Tin, Ion"].category, tool.CONTRADICTED)

    def test_a_polyatomic_ion_pair_flags(self):
        self.assertEqual(self.by_name["Thiocyanate"].category, tool.CONTRADICTED)

    def test_an_ore_grade_row_is_whitelisted_by_its_own_name(self):
        group = self.by_name["Aluminium, 24% In Bauxite, 11% In Crude Ore, In Ground"]
        self.assertEqual(group.category, tool.ORE_GRADE)

    def test_agreement_and_the_undecidable_rows_do_not_flag(self):
        self.assertEqual(self.by_name["Nickel"].category, tool.AGREES)
        self.assertEqual(
            self.by_name["Kieserite, In Ground"].category, tool.CAS_UNPLACED
        )
        self.assertEqual(
            self.by_name["Occupation, Annual Crop"].category, tool.NO_CAS
        )

    def test_a_signed_contradiction_is_acknowledged(self):
        """The signature turns a finding into a reviewed decision.

        Signed in the override file with `not_the_stated_substance`, read
        here as an injected set so the test owns its fixture whole.
        """
        by_name = {
            group.source_name: group
            for group in tool.load_groups(
                self.db_path, signed=frozenset({"u-metaldehyde"})
            )
        }
        self.assertEqual(by_name["Metaldehyde"].category, tool.ACKNOWLEDGED)
        # The signature reaches only its own uuid: everything else still flags.
        self.assertEqual(by_name["Tin, Ion"].category, tool.CONTRADICTED)

    def test_half_a_signature_is_a_drifted_file(self):
        """A group is acknowledged only when every row of it signs.

        Two releases of one decision, one signed and one not, is not a
        reviewed decision -- it is a file that moved after the review.
        """
        db = sqlite3.connect(self.db_path)
        db.execute(
            "INSERT INTO merge_outcomes VALUES ('Metaldehyde', '108-62-3',"
            " 'u-metaldehyde-38', 'fo-metaldehyde-stub', '3.8', 'prepared')"
        )
        db.commit()
        db.close()
        by_name = {
            group.source_name: group
            for group in tool.load_groups(
                self.db_path, signed=frozenset({"u-metaldehyde"})
            )
        }
        self.assertEqual(by_name["Metaldehyde"].category, tool.CONTRADICTED)

    def test_a_signature_on_an_agreeing_row_is_stale(self):
        """Both directions of drift are findings.

        `Nickel` agrees with its stated number, so a signature on it signs a
        contradiction that does not exist -- the mirror image of an unsigned
        contradiction, and `--strict` fails on it the same way.
        """
        signed = frozenset({"u-nickel"})
        groups = tool.load_groups(self.db_path, signed=signed)
        stale = tool.stale_signatures(groups, signed)
        self.assertEqual(stale, [("u-nickel", "Nickel")])
        # A signed uuid the build never placed is not stale: a build merging
        # fewer lists cannot answer, and silence is not agreement.
        absent = frozenset({"u-not-in-this-build"})
        self.assertEqual(
            tool.stale_signatures(tool.load_groups(self.db_path, signed=absent),
                                  absent),
            [],
        )

    def test_strict_exits_two_on_a_contradiction_and_zero_without(self):
        self.assertEqual(tool.main([str(self.db_path), "--strict"]), 2)
        clean = sqlite3.connect(self.db_path)
        clean.execute(
            "DELETE FROM merge_outcomes WHERE source_name IN"
            " ('Metaldehyde', 'Tin, Ion', 'Thiocyanate', 'Nickel II')"
        )
        clean.commit()
        clean.close()
        self.assertEqual(tool.main([str(self.db_path), "--strict"]), 0)

    def test_report_names_the_contradictions(self):
        text = tool.report(list(self.by_name.values()))
        self.assertIn("Tin, Ion", text)
        self.assertIn("Nickel II", text)
        # The one surviving whitelist stays out of the default report ...
        self.assertNotIn("Bauxite", text)
        # ... and appears when asked for.
        self.assertIn(
            "Bauxite", tool.report(list(self.by_name.values()), show_all=True)
        )


if __name__ == "__main__":
    unittest.main()
