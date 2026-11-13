"""`/cases`: the expectations files and their recorded statuses, as pages.

What is pinned here is that the section is a *reading* of `expectations/` and
keeps no record of its own:

- **A claim's state is the baseline's status for it**, with the two things a
  status does not say -- agreed-pending, and written after the recorded build.
  A claim the build meets is met even while the file still says `pending`.
- **A case is as bad as its worst claim.**  One unmet claim among met ones is
  an unmet case, or the work list hides exactly the files worth opening.
- **The real directory loads.**  Every file a pull request adds becomes a page
  with no further step, so a file the page cannot show has to fail here.
- **No database is needed**, as for the documentation.
"""

import tempfile
import unittest
from pathlib import Path

import orjson

from brightway_flows.assessment.expectations import EXPECTATIONS_DIR, load_expectations
from brightway_flows.webapps.app import create_app
from brightway_flows.webapps.app.queries import cases


def _expectation(identifier, issue=None, pending=False, **subject):
    entry = {
        "id": identifier,
        "title": f"The row for {identifier} lands on a flow that already exists",
        "subject": {"kind": "source_row", "list": "bafu", "name": "Water"} | subject,
        "expect": {"outcome": "matched"},
        "comment": f"Measured for {identifier}.",
    }
    if issue is not None:
        entry["issue"] = issue
    if pending:
        entry["pending"] = True
    return entry


def _write(directory, name, description, expectations):
    (directory / name).write_bytes(orjson.dumps({
        "schema_version": 1,
        "description": description,
        "expectations": expectations,
    }))


class FixtureTestCase(unittest.TestCase):
    """Three files and a baseline that knows about some of their claims."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.directory = Path(self._tmp.name)
        _write(self.directory, "0381-bafu-water-names.json",
               "BAFU ships water under a dozen names.",
               [_expectation("water-met", 381), _expectation("water-unmet", 381)])
        _write(self.directory, "0400-pending-work.json",
               "Agreed, and not done yet.",
               [_expectation("still-open", 400, pending=True),
                _expectation("done-but-flagged", 400, pending=True)])
        _write(self.directory, "an-invariant.json",
               "Written after the recorded build.",
               [_expectation("brand-new", **{"list": "ecoinvent"})])
        (self.directory / "baseline.json").write_bytes(orjson.dumps({
            "schema_version": 1,
            "recorded": {"pipeline_run_id": "20261021T0956", "sources": ["bafu-2026-v1"],
                         "timestamp": "2026-10-21T09:56:52+00:00"},
            "measures": {},
            "expectations": {"water-met": "met", "water-unmet": "unmet",
                             "still-open": "unmet", "done-but-flagged": "met"},
        }))
        self.loaded = cases.load_cases(self.directory)
        app = create_app(self.directory / "missing.sqlite3",
                         expectations_path=self.directory)
        app.config["TESTING"] = True
        self.client = app.test_client()

    def body(self, path, status=200):
        response = self.client.get(path)
        self.assertEqual(response.status_code, status, path)
        return response.get_data(as_text=True)


class StateTestCase(FixtureTestCase):
    def states(self, case_id):
        return {claim.id: claim.state for claim in self.loaded.get(case_id).claims}

    def test_a_claim_takes_the_status_the_baseline_records(self):
        self.assertEqual(self.states("0381-bafu-water-names"),
                         {"water-met": cases.State.MET, "water-unmet": cases.State.UNMET})

    def test_an_agreed_open_claim_is_pending_rather_than_unmet(self):
        self.assertEqual(self.states("0400-pending-work")["still-open"], cases.State.PENDING)

    def test_a_met_claim_is_met_even_while_the_file_says_pending(self):
        self.assertEqual(self.states("0400-pending-work")["done-but-flagged"],
                         cases.State.MET)

    def test_a_claim_newer_than_the_recorded_build_has_no_status(self):
        self.assertEqual(self.states("an-invariant"), {"brand-new": cases.State.UNRECORDED})

    def test_a_case_is_as_bad_as_its_worst_claim(self):
        self.assertEqual(
            {case.id: case.state for case in self.loaded.cases},
            {"0381-bafu-water-names": cases.State.UNMET,
             "0400-pending-work": cases.State.PENDING,
             "an-invariant": cases.State.UNRECORDED},
        )

    def test_a_status_this_code_does_not_know_raises(self):
        baseline = orjson.loads((self.directory / "baseline.json").read_bytes())
        baseline["expectations"]["water-met"] = "mostly"
        (self.directory / "baseline.json").write_bytes(orjson.dumps(baseline))
        with self.assertRaises(ValueError):
            cases.load_cases(self.directory)

    def test_no_baseline_is_every_claim_unrecorded_or_pending(self):
        (self.directory / "baseline.json").unlink()
        loaded = cases.load_cases(self.directory)
        self.assertEqual(loaded.recorded, {})
        self.assertEqual(set(loaded.state_counts),
                         {cases.State.UNRECORDED, cases.State.PENDING})


class CaseTestCase(FixtureTestCase):
    def test_a_case_is_named_for_its_file(self):
        case = self.loaded.get("0381-bafu-water-names")
        self.assertEqual(case.title, "Bafu water names")
        self.assertEqual(case.filename, "0381-bafu-water-names.json")
        self.assertEqual(case.summary, "BAFU ships water under a dozen names.")
        self.assertEqual(self.loaded.get("an-invariant").title, "An invariant")

    def test_a_case_knows_its_issues_and_its_source_lists(self):
        self.assertEqual(self.loaded.get("0381-bafu-water-names").issues, (381,))
        self.assertEqual(self.loaded.get("an-invariant").issues, ())
        self.assertEqual(self.loaded.lists, ["bafu", "ecoinvent"])


class SelectTestCase(FixtureTestCase):
    def ids(self, **filters):
        return [case.id for case in cases.select(self.loaded.cases, **filters)]

    def test_the_default_order_puts_what_the_build_does_not_do_first(self):
        self.assertEqual(self.ids(), ["0381-bafu-water-names", "0400-pending-work",
                                      "an-invariant"])

    def test_an_issue_number_finds_its_case(self):
        self.assertEqual(self.ids(query="#400"), ["0400-pending-work"])

    def test_search_reads_the_claims_as_well_as_the_file(self):
        self.assertEqual(self.ids(query="measured for BRAND-new"), ["an-invariant"])

    def test_state_and_source_list_filter(self):
        self.assertEqual(self.ids(state="pending"), ["0400-pending-work"])
        self.assertEqual(self.ids(source="ecoinvent"), ["an-invariant"])

    def test_a_sort_can_be_reversed_and_an_unknown_one_is_the_default(self):
        self.assertEqual(self.ids(sort="-case")[0], "an-invariant")
        self.assertEqual(self.ids(sort="nonsense"), self.ids())


class PagesTestCase(FixtureTestCase):
    def test_the_index_lists_every_case_without_a_database(self):
        body = self.body("/cases/")
        for case in self.loaded.cases:
            self.assertIn(f'href="/cases/{case.id}"', body)

    def test_the_index_names_the_build_the_statuses_came_from(self):
        body = self.body("/cases/")
        self.assertIn("20261021T0956", body)
        self.assertIn("bafu-2026-v1", body)

    def test_the_state_chips_count_what_the_search_selects(self):
        body = self.body("/cases/?q=water")
        self.assertRegex(body, r'chip__label">unmet</span>\s*<span class="chip__value">1<')
        self.assertNotIn('chip__label">pending<', body)

    def test_a_filter_narrows_the_table(self):
        body = self.body("/cases/?state=pending")
        self.assertIn('href="/cases/0400-pending-work"', body)
        self.assertNotIn('href="/cases/an-invariant"', body)

    def test_a_case_links_its_issue_and_its_file(self):
        body = self.body("/cases/0381-bafu-water-names")
        self.assertIn("/issues/381", body)
        self.assertIn("/blob/main/expectations/0381-bafu-water-names.json", body)
        self.assertIn("The row for water-unmet lands on a flow", body)

    def test_an_unknown_case_is_not_found(self):
        self.body("/cases/no-such-file", status=404)

    def test_a_page_beyond_the_end_is_the_last_page(self):
        self.assertIn('href="/cases/an-invariant"', self.body("/cases/?page=99"))


class CheckedInDirectoryTestCase(unittest.TestCase):
    """`expectations/` as committed: every file is a case, and every case a page."""

    @classmethod
    def setUpClass(cls):
        cls.loaded = cases.load_cases(EXPECTATIONS_DIR)
        app = create_app(Path("/nonexistent.sqlite3"))
        app.config["TESTING"] = True
        cls.client = app.test_client()

    def test_every_expectations_file_is_one_case(self):
        files = {expectation.source_file for expectation in load_expectations()}
        self.assertEqual(len(self.loaded.cases), len(files))
        self.assertEqual(sum(len(case.claims) for case in self.loaded.cases),
                         len(load_expectations()))

    def test_every_case_renders(self):
        self.assertEqual(self.client.get("/cases/").status_code, 200)
        for case in self.loaded.cases:
            with self.subTest(case=case.id):
                self.assertEqual(self.client.get(f"/cases/{case.id}").status_code, 200)


if __name__ == "__main__":
    unittest.main()
