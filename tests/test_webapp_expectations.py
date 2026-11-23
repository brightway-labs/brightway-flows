"""`/expectations`: the expectations files and their recorded statuses, as pages.

What is pinned here is that the section is a *reading* of `expectations/` and
keeps no record of its own:

- **An expectation's state is the baseline's status for it**, with the two
  things a status does not say -- agreed-pending, and written after the recorded
  build.  One the build meets is met even while the file still says `pending`,
  and one that has lost its subject is unresolved even while it does.
- **A file is as bad as its worst expectation.**  One unmet expectation among
  met ones is an unmet file, or the work list hides exactly the files worth
  opening.
- **The real directory loads.**  Every file a pull request adds becomes a page
  with no further step, so a file the page cannot show has to fail here.
- **No database is needed**, as for the documentation, and a directory that is
  not there is a page saying where it was looked for.
"""

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import orjson

from brightway_flows.assessment.expectations import EXPECTATIONS_DIR, load_expectations
from brightway_flows.webapps.app import create_app
from brightway_flows.webapps.app.filters import code_spans
from brightway_flows.webapps.app.queries import expectations


def _expectation(identifier, issue=None, pending=False, **subject):
    entry = {
        "id": identifier,
        "title": f"The row for `{identifier}` lands on a flow that already exists",
        "subject": {"kind": "source_row", "list": "bafu", "name": "Water"} | subject,
        "expect": {"outcome": "matched"},
        "comment": f"Measured for {identifier}.",
    }
    if issue is not None:
        entry["issue"] = issue
    if pending:
        entry["pending"] = True
    return entry


def _write(directory, name, description, entries):
    (directory / name).write_bytes(orjson.dumps({
        "schema_version": 1,
        "description": description,
        "expectations": entries,
    }))


class FixtureTestCase(unittest.TestCase):
    """Three files and a baseline that knows about some of their expectations."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.directory = Path(self._tmp.name)
        _write(self.directory, "0381-bafu-water-names.json",
               "BAFU ships water under a dozen names, `Water` among them.\n\n"
               "What settles it is the material.",
               [_expectation("water-met", 381), _expectation("water-unmet", 381)])
        _write(self.directory, "0400-pending-work.json",
               "Agreed, and not done yet.",
               [_expectation("still-open", 400, pending=True),
                _expectation("done-but-flagged", 400, pending=True)])
        _write(self.directory, "an-invariant.json",
               "Written after the recorded build.",
               [_expectation("brand-new", **{"list": "ecoinvent"})])
        self.write_baseline({"water-met": "met", "water-unmet": "unmet",
                             "still-open": "unmet", "done-but-flagged": "met"})
        self.loaded = expectations.load_files(self.directory)
        app = create_app(self.directory / "missing.sqlite3",
                         expectations_path=self.directory)
        app.config["TESTING"] = True
        self.client = app.test_client()

    def write_baseline(self, statuses):
        (self.directory / "baseline.json").write_bytes(orjson.dumps({
            "schema_version": 1,
            "recorded": {"pipeline_run_id": "20261021T0956", "sources": ["bafu-2026-v1"],
                         "timestamp": "2026-10-21T09:56:52+00:00"},
            "measures": {},
            "expectations": statuses,
        }))

    def body(self, path, status=200):
        response = self.client.get(path)
        self.assertEqual(response.status_code, status, path)
        return response.get_data(as_text=True)


class StateTestCase(FixtureTestCase):
    def states(self, file_id, directory=None):
        loaded = expectations.load_files(directory) if directory else self.loaded
        return {e.id: e.state for e in loaded.get(file_id).expectations}

    def test_an_expectation_takes_the_status_the_baseline_records(self):
        self.assertEqual(
            self.states("0381-bafu-water-names"),
            {"water-met": expectations.State.MET, "water-unmet": expectations.State.UNMET},
        )

    def test_an_agreed_open_expectation_is_pending_rather_than_unmet(self):
        self.assertEqual(self.states("0400-pending-work")["still-open"],
                         expectations.State.PENDING)

    def test_a_met_expectation_is_met_even_while_the_file_says_pending(self):
        self.assertEqual(self.states("0400-pending-work")["done-but-flagged"],
                         expectations.State.MET)

    def test_pending_excuses_an_error_as_assess_does(self):
        self.write_baseline({"still-open": "error", "done-but-flagged": "met"})
        self.assertEqual(self.states("0400-pending-work", self.directory)["still-open"],
                         expectations.State.PENDING)

    def test_pending_does_not_hide_an_expectation_that_lost_its_subject(self):
        """`unresolved` means rewrite the expectation, which is a different job
        from the open work `pending` stands for -- `0726-every-pair-within-2x`
        on the build recorded 2026-11-23 is the one this was found on."""
        self.write_baseline({"still-open": "unresolved", "done-but-flagged": "met"})
        self.assertEqual(self.states("0400-pending-work", self.directory)["still-open"],
                         expectations.State.UNRESOLVED)

    def test_an_expectation_newer_than_the_recorded_build_has_no_status(self):
        self.assertEqual(self.states("an-invariant"),
                         {"brand-new": expectations.State.UNRECORDED})

    def test_a_file_is_as_bad_as_its_worst_expectation(self):
        self.assertEqual(
            {file.id: file.state for file in self.loaded.files},
            {"0381-bafu-water-names": expectations.State.UNMET,
             "0400-pending-work": expectations.State.PENDING,
             "an-invariant": expectations.State.UNRECORDED},
        )

    def test_a_status_this_code_does_not_know_raises(self):
        self.write_baseline({"water-met": "mostly"})
        with self.assertRaises(ValueError):
            expectations.load_files(self.directory)

    def test_an_unknown_status_raises_for_a_pending_expectation_too(self):
        self.write_baseline({"still-open": "mostly"})
        with self.assertRaises(ValueError):
            expectations.load_files(self.directory)

    def test_no_baseline_is_every_expectation_unrecorded_or_pending(self):
        (self.directory / "baseline.json").unlink()
        loaded = expectations.load_files(self.directory)
        self.assertEqual(loaded.recorded, {})
        self.assertEqual(set(loaded.state_counts),
                         {expectations.State.UNRECORDED, expectations.State.PENDING})

    def test_every_state_has_a_meaning(self):
        self.assertEqual(set(expectations.STATE_MEANINGS), set(expectations.State))


class FileTestCase(FixtureTestCase):
    def test_a_file_is_known_by_its_name_as_written(self):
        file = self.loaded.get("0381-bafu-water-names")
        self.assertEqual(file.filename, "0381-bafu-water-names.json")
        self.assertEqual(file.paragraphs,
                         ("BAFU ships water under a dozen names, `Water` among them.",
                          "What settles it is the material."))

    def test_a_file_knows_its_issues_and_its_source_lists(self):
        self.assertEqual(self.loaded.get("0381-bafu-water-names").issues, (381,))
        self.assertEqual(self.loaded.get("an-invariant").issues, ())
        self.assertEqual(self.loaded.lists, ["bafu", "ecoinvent"])


class SelectTestCase(FixtureTestCase):
    def ids(self, **filters):
        return [file.id for file in expectations.select(self.loaded.files, **filters)]

    def test_the_default_order_puts_what_the_build_does_not_do_first(self):
        self.assertEqual(self.ids(), ["0381-bafu-water-names", "0400-pending-work",
                                      "an-invariant"])

    def test_an_issue_number_finds_its_file(self):
        self.assertEqual(self.ids(query="#400"), ["0400-pending-work"])

    def test_search_reads_the_expectations_as_well_as_the_file(self):
        self.assertEqual(self.ids(query="measured for BRAND-new"), ["an-invariant"])

    def test_state_and_source_list_filter(self):
        self.assertEqual(self.ids(state="pending"), ["0400-pending-work"])
        self.assertEqual(self.ids(source="ecoinvent"), ["an-invariant"])

    def test_a_sort_can_be_reversed_and_an_unknown_one_is_the_default(self):
        self.assertEqual(self.ids(sort="-file")[0], "an-invariant")
        self.assertEqual(self.ids(sort="nonsense"), self.ids())


class CodeSpansTestCase(unittest.TestCase):
    def test_backticks_become_code(self):
        self.assertEqual(str(code_spans("A row named `Water` lands")),
                         "A row named <code>Water</code> lands")

    def test_everything_is_escaped_inside_a_span_and_out(self):
        self.assertEqual(str(code_spans("a < b, and `<script>`")),
                         "a &lt; b, and <code>&lt;script&gt;</code>")

    def test_an_asterisk_is_an_asterisk(self):
        self.assertEqual(str(code_spans("every *.json file")), "every *.json file")


class PagesTestCase(FixtureTestCase):
    def test_the_index_lists_every_file_without_a_database(self):
        body = self.body("/expectations/")
        for file in self.loaded.files:
            self.assertIn(f'href="/expectations/{file.id}"', body)

    def test_the_index_names_the_build_the_statuses_came_from(self):
        body = self.body("/expectations/")
        self.assertIn("20261021T0956", body)
        self.assertIn("bafu-2026-v1", body)

    def test_the_state_chips_count_what_the_search_selects(self):
        body = self.body("/expectations/?q=water")
        self.assertRegex(body, r'chip__label">unmet</span>\s*<span class="chip__value">1<')
        self.assertNotIn('chip__label">pending<', body)

    def test_a_filter_narrows_the_table(self):
        body = self.body("/expectations/?state=pending")
        self.assertIn('href="/expectations/0400-pending-work"', body)
        self.assertNotIn('href="/expectations/an-invariant"', body)

    def test_a_file_links_its_issue_and_itself(self):
        body = self.body("/expectations/0381-bafu-water-names")
        self.assertIn("/issues/381", body)
        self.assertIn("/blob/main/expectations/0381-bafu-water-names.json", body)
        self.assertIn("The row for <code>water-unmet</code> lands on a flow", body)

    def test_a_description_is_paragraphs_with_its_code_set_as_code(self):
        body = self.body("/expectations/0381-bafu-water-names")
        self.assertIn("<p>BAFU ships water under a dozen names, <code>Water</code> "
                      "among them.</p>", body)
        self.assertIn("<p>What settles it is the material.</p>", body)

    def test_an_unknown_file_is_not_found(self):
        self.body("/expectations/no-such-file", status=404)

    def test_a_page_beyond_the_end_is_the_last_page(self):
        self.assertIn('href="/expectations/an-invariant"',
                      self.body("/expectations/?page=99"))


class MissingDirectoryTestCase(unittest.TestCase):
    """An installed package has no `expectations/`, and says so."""

    def client(self, **arguments):
        app = create_app(Path("/nonexistent.sqlite3"), **arguments)
        app.config["TESTING"] = True
        return app.test_client()

    def test_a_missing_directory_is_a_page_naming_where_it_looked(self):
        client = self.client(expectations_path=Path("/no/such/expectations"))
        for path in ("/expectations/", "/expectations/0381-bafu-water-names"):
            with self.subTest(path=path):
                response = client.get(path)
                self.assertEqual(response.status_code, 200)
                body = response.get_data(as_text=True)
                self.assertIn("/no/such/expectations", body)
                self.assertIn("BRIGHTWAY_FLOWS_EXPECTATIONS_DIR", body)
                self.assertNotIn("matches these filters", body)

    def test_the_environment_names_the_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            _write(Path(tmp), "0001-somewhere-else.json", "Elsewhere.",
                   [_expectation("elsewhere", 1)])
            with mock.patch.dict(os.environ, {"BRIGHTWAY_FLOWS_EXPECTATIONS_DIR": tmp}):
                body = self.client().get("/expectations/").get_data(as_text=True)
        self.assertIn('href="/expectations/0001-somewhere-else"', body)


class CheckedInDirectoryTestCase(unittest.TestCase):
    """`expectations/` as committed: every file is listed, and every one a page."""

    @classmethod
    def setUpClass(cls):
        cls.loaded = expectations.load_files(EXPECTATIONS_DIR)
        app = create_app(Path("/nonexistent.sqlite3"), expectations_path=EXPECTATIONS_DIR)
        app.config["TESTING"] = True
        cls.client = app.test_client()

    def test_every_expectations_file_is_listed_once(self):
        names = {expectation.source_file for expectation in load_expectations()}
        self.assertEqual(len(self.loaded.files), len(names))
        self.assertEqual(sum(len(file.expectations) for file in self.loaded.files),
                         len(load_expectations()))

    def test_every_file_renders(self):
        self.assertEqual(self.client.get("/expectations/").status_code, 200)
        for file in self.loaded.files:
            with self.subTest(file=file.id):
                self.assertEqual(
                    self.client.get(f"/expectations/{file.id}").status_code, 200)


if __name__ == "__main__":
    unittest.main()
