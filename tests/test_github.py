"""GitHub adapter tests use mocked subprocesses only."""

import json
import subprocess
import unittest
from unittest.mock import patch

from pr_lantern.github import FIELDS, fetch_pr
from tests.test_core import URL, make_pr


class GitHubTests(unittest.TestCase):
    @patch("pr_lantern.github.subprocess.run")
    def test_uses_read_only_gh_command_with_bounded_timeout(self, run):
        data = make_pr(title="Unicode 🏮")
        run.return_value = subprocess.CompletedProcess([], 0, json.dumps(data), "")
        self.assertEqual(fetch_pr(URL, timeout=7), data)
        args, kwargs = run.call_args
        self.assertEqual(args[0], ["gh", "pr", "view", URL, "--json", FIELDS])
        self.assertEqual(kwargs["timeout"], 7)
        self.assertEqual(kwargs["encoding"], "utf-8")
        self.assertNotIn("shell", kwargs)

    @patch("pr_lantern.github.subprocess.run", side_effect=FileNotFoundError())
    def test_missing_gh_has_actionable_error(self, run):
        with self.assertRaisesRegex(RuntimeError, "Install gh"):
            fetch_pr(URL)

    @patch("pr_lantern.github.subprocess.run", side_effect=subprocess.TimeoutExpired("gh", 5))
    def test_timeout_has_clear_error(self, run):
        with self.assertRaisesRegex(RuntimeError, "timed out after 5 seconds"):
            fetch_pr(URL, timeout=5)

    @patch("pr_lantern.github.subprocess.run")
    def test_nonzero_exit_and_bad_json_are_not_success(self, run):
        cases = (
            (1, "", "authentication failed", "authentication failed"),
            (1, "", "", "request failed"),
            (0, "not json", "", "invalid JSON"),
            (0, "[]", "", "unexpected response"),
        )
        for code, stdout, stderr, message in cases:
            with self.subTest(stdout=stdout, stderr=stderr):
                run.return_value = subprocess.CompletedProcess([], code, stdout, stderr)
                with self.assertRaisesRegex(RuntimeError, message):
                    fetch_pr(URL)


if __name__ == "__main__":
    unittest.main()
