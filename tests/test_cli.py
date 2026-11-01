"""CLI orchestration tests keep all state in temporary directories."""

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pr_lantern.cli import main
from pr_lantern.core import normalize_pr
from pr_lantern.state import load_state, save_state
from tests.test_core import URL, check, make_pr

OTHER_URL = "https://github.com/example/other/pull/99"


class CLITests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.state_path = Path(self.directory.name) / "state.json"

    def invoke(self, *arguments):
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            result = main(
                ["check", "--state", str(self.state_path), "--format", "json", *arguments]
            )
        return result, stdout.getvalue(), stderr.getvalue()

    @patch("pr_lantern.cli.fetch_pr")
    def test_first_run_saves_baseline_then_reuses_watchlist(self, fetch):
        fetch.return_value = make_pr()
        code, output, errors = self.invoke(URL, URL + "/")
        report = json.loads(output)
        self.assertEqual((code, errors), (0, ""))
        self.assertTrue(report["first_run"])
        self.assertEqual(report["items"][0]["changes"], [])
        self.assertEqual(fetch.call_count, 1)
        self.assertEqual(list(load_state(self.state_path)["snapshots"]), [URL])

        code, output, _ = self.invoke()
        self.assertEqual(code, 0)
        self.assertFalse(json.loads(output)["first_run"])
        self.assertEqual(fetch.call_count, 2)

    @patch("pr_lantern.cli.fetch_pr")
    def test_partial_failure_preserves_failed_and_unrequested_snapshots(self, fetch):
        previous = normalize_pr(make_pr(OTHER_URL, title="previous value"), OTHER_URL)
        untouched_url = "https://github.com/example/untouched/pull/4"
        untouched = normalize_pr(make_pr(untouched_url), untouched_url)
        save_state(
            self.state_path,
            {"version": 1, "snapshots": {OTHER_URL: previous, untouched_url: untouched}},
        )
        fetch.side_effect = [make_pr(), RuntimeError("temporary network failure")]

        code, output, _ = self.invoke(URL, OTHER_URL)
        report = json.loads(output)
        state = load_state(self.state_path)
        self.assertEqual(code, 2)
        self.assertEqual([item["url"] for item in report["items"]], [URL])
        self.assertEqual(
            report["errors"], [{"url": OTHER_URL, "message": "temporary network failure"}]
        )
        self.assertEqual(state["snapshots"][OTHER_URL], previous)
        self.assertEqual(state["snapshots"][untouched_url], untouched)
        self.assertIn(URL, state["snapshots"])

    @patch("pr_lantern.cli.fetch_pr")
    def test_no_save_reports_changes_without_updating_baseline(self, fetch):
        previous = normalize_pr(make_pr(), URL)
        save_state(self.state_path, {"version": 1, "snapshots": {URL: previous}})
        original_bytes = self.state_path.read_bytes()
        fetch.return_value = make_pr(state="MERGED")
        code, output, _ = self.invoke("--no-save")
        self.assertEqual(code, 0)
        self.assertIn("PR: OPEN → MERGED", json.loads(output)["items"][0]["changes"])
        self.assertEqual(self.state_path.read_bytes(), original_bytes)

    @patch("pr_lantern.cli.fetch_pr")
    def test_no_save_first_run_does_not_create_state(self, fetch):
        fetch.return_value = make_pr()
        self.assertEqual(self.invoke(URL, "--no-save")[0], 0)
        self.assertFalse(self.state_path.exists())

    @patch("pr_lantern.cli.fetch_pr")
    def test_action_exit_codes_distinguish_pending_and_closed_prs(self, fetch):
        cases = (
            ({"statusCheckRollup": [check("FAILURE")]}, 1),
            ({"statusCheckRollup": [check("ACTION_REQUIRED")]}, 1),
            ({"reviewDecision": "CHANGES_REQUESTED"}, 1),
            ({"statusCheckRollup": [check(None, "IN_PROGRESS")]}, 0),
            ({"statusCheckRollup": [check()]}, 0),
            ({"state": "MERGED", "statusCheckRollup": [check("FAILURE")]}, 0),
            ({"state": "CLOSED", "reviewDecision": "CHANGES_REQUESTED"}, 0),
        )
        for fields, expected in cases:
            with self.subTest(fields=fields):
                fetch.return_value = make_pr(**fields)
                self.assertEqual(self.invoke(URL, "--no-save", "--fail-on-action")[0], expected)

    @patch("pr_lantern.cli.fetch_pr")
    def test_corrupt_state_is_not_overwritten_and_no_network_call_occurs(self, fetch):
        self.state_path.write_text("{broken json", encoding="utf-8")
        code, output, errors = self.invoke(URL)
        self.assertEqual((code, output), (2, ""))
        self.assertIn("File left unchanged", errors)
        self.assertEqual(self.state_path.read_text(encoding="utf-8"), "{broken json")
        fetch.assert_not_called()

    @patch("pr_lantern.cli.fetch_pr", side_effect=RuntimeError("GitHub is unavailable"))
    def test_all_fetch_failures_leave_existing_state_unchanged(self, fetch):
        save_state(
            self.state_path, {"version": 1, "snapshots": {URL: normalize_pr(make_pr(), URL)}}
        )
        original_bytes = self.state_path.read_bytes()
        code, output, _ = self.invoke()
        self.assertEqual(code, 2)
        self.assertEqual(json.loads(output)["items"], [])
        self.assertEqual(self.state_path.read_bytes(), original_bytes)

    @patch("pr_lantern.cli.fetch_pr")
    def test_invalid_url_and_empty_watchlist_do_not_fetch(self, fetch):
        for arguments in ((), ("https://github.com/example/project/issues/12",)):
            with self.subTest(arguments=arguments):
                code, output, errors = self.invoke(*arguments)
                self.assertEqual((code, output), (2, ""))
                self.assertTrue(errors)
        fetch.assert_not_called()

    @patch("pr_lantern.cli.fetch_pr")
    def test_report_cannot_overwrite_snapshot_file(self, fetch):
        code, _, errors = self.invoke(URL, "--output", str(self.state_path))
        self.assertEqual(code, 2)
        self.assertIn("must be different files", errors)
        fetch.assert_not_called()


if __name__ == "__main__":
    unittest.main()
