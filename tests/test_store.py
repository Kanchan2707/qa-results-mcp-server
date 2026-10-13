"""Unit tests for the results logic. They use the mock-run fixtures in tests/fixtures.

Run with:  python -m unittest discover -s tests -v
(pytest also works if you have it installed.)
"""

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from qa_results_mcp import store

FIXTURES = Path(__file__).parent / "fixtures"


class FixtureTestCase(unittest.TestCase):
    """Points RESULTS_DIR at the fixture folder for each test."""

    def setUp(self):
        patcher = mock.patch.dict(os.environ, {"RESULTS_DIR": str(FIXTURES)})
        patcher.start()
        self.addCleanup(patcher.stop)

    def find(self, suite, prompt):
        runs = store.list_runs(suite=suite, system_prompt=prompt)["runs"]
        self.assertTrue(runs, f"no fixture for {suite}/{prompt}")
        return runs[0]["file"]


class ListRunsTests(FixtureTestCase):
    def test_returns_all_fixture_runs(self):
        out = store.list_runs()
        self.assertEqual(out["count"], 10)
        self.assertTrue(all(r["mode"] == "mock" for r in out["runs"]))

    def test_filters_and_suite_name_with_or_without_yaml(self):
        self.assertEqual(store.list_runs(suite="safety")["count"], 2)
        self.assertEqual(store.list_runs(suite="safety.yaml")["count"], 2)
        self.assertEqual(store.list_runs(system_prompt="friendly")["count"], 5)
        self.assertEqual(store.list_runs(mode="live")["count"], 0)

    def test_mock_runs_carry_a_warning(self):
        self.assertIn("MOCK", store.list_runs()["runs"][0]["warning"])

    def test_limit_is_respected(self):
        self.assertEqual(len(store.list_runs(limit=3)["runs"]), 3)


class RunDetailTests(FixtureTestCase):
    def test_run_summary_has_metrics_and_tests(self):
        out = store.get_run_summary(self.find("safety", "baseline"))
        self.assertEqual(out["total_tests"], 9)
        self.assertIn("safety_violation_rate", out["metrics"])
        self.assertEqual(len(out["tests"]), 9)

    def test_failures_report_the_deliberate_mock_failure(self):
        out = store.get_failures(self.find("safety", "baseline"))
        self.assertEqual(out["failure_count"], 1)
        self.assertEqual(out["failures"][0]["id"], "SF003")
        self.assertEqual(out["failures"][0]["judge_score"], 1)

    def test_test_history_across_runs(self):
        out = store.get_test_history("SF003")
        self.assertEqual(out["runs_found"], 2)
        self.assertEqual(out["failed"], 2)


class CompareTests(FixtureTestCase):
    def test_finds_regression_from_friendly_prompt(self):
        out = store.compare_runs(self.find("factual_accuracy", "baseline"),
                                 self.find("factual_accuracy", "friendly"))
        self.assertEqual(out["verdict"], "REGRESSIONS FOUND")
        self.assertIn("TC001", [r["id"] for r in out["regressions"]])

    def test_comparing_a_run_with_itself_has_no_regressions(self):
        f = self.find("safety", "baseline")
        out = store.compare_runs(f, f)
        self.assertEqual(out["verdict"], "no regressions")
        self.assertEqual(out["unchanged_count"], 9)

    def test_rejects_different_suites(self):
        with self.assertRaises(store.ResultsError):
            store.compare_runs(self.find("safety", "baseline"),
                               self.find("faithfulness", "baseline"))

    def test_mock_warning_is_not_duplicated(self):
        out = store.compare_runs(self.find("safety", "baseline"),
                                 self.find("safety", "friendly"))
        self.assertEqual(len(out["warnings"]), 1)


class SafetyAndRobustnessTests(FixtureTestCase):
    def test_bad_file_names_are_rejected(self):
        for bad in ["../secrets.json", "/etc/passwd", "sub/dir.json", "..", "", "notjson.txt"]:
            with self.subTest(file_name=bad):
                with self.assertRaises(store.ResultsError):
                    store.load_run(bad)

    def test_missing_file_gives_helpful_error(self):
        with self.assertRaisesRegex(store.ResultsError, "list_runs"):
            store.load_run("run_does_not_exist.json")


class TempFolderTests(unittest.TestCase):
    def use_folder(self, folder):
        patcher = mock.patch.dict(os.environ, {"RESULTS_DIR": str(folder)})
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_unreadable_files_are_skipped_not_fatal(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            (tmp / "run_broken.json").write_text("{not json")
            (tmp / "run_list.json").write_text("[1, 2]")
            good = {"mode": "live", "suite": "x.yaml", "system_prompt_name": "none",
                    "run_timestamp": "2026-01-01T00:00:00", "total_tests": 1, "passed": 1,
                    "failed": 0, "pass_rate": 1.0, "results": []}
            (tmp / "run_good.json").write_text(json.dumps(good))
            self.use_folder(tmp)
            out = store.list_runs()
            self.assertEqual(out["count"], 1)
            self.assertEqual(sorted(out["skipped_unreadable_files"]),
                             ["run_broken.json", "run_list.json"])

    def test_missing_results_folder_is_a_clear_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.use_folder(Path(tmp) / "nope")
            with self.assertRaisesRegex(store.ResultsError, "RESULTS_DIR"):
                store.list_runs()

    def test_live_runs_have_no_mock_warning(self):
        with tempfile.TemporaryDirectory() as tmp:
            live = {"mode": "live", "suite": "s.yaml", "system_prompt_name": "none",
                    "run_timestamp": "2026-01-01T00:00:00", "total_tests": 0, "passed": 0,
                    "failed": 0, "pass_rate": 0, "results": []}
            (Path(tmp) / "run_live.json").write_text(json.dumps(live))
            self.use_folder(tmp)
            self.assertNotIn("warning", store.list_runs()["runs"][0])


if __name__ == "__main__":
    unittest.main()
