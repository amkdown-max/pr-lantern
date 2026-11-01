"""Overlapping writers must fail before fetching or replacing state."""

import contextlib
import io
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pr_lantern.cli import main
from pr_lantern.state import load_state, state_lock
from tests.test_core import URL, make_pr

_CHILD_CHECK = """
import sys
from unittest.mock import patch
from pr_lantern.cli import main

with patch('pr_lantern.cli.fetch_pr', side_effect=AssertionError('Unexpected GitHub fetch')):
    raise SystemExit(main(['check', sys.argv[1], '--state', sys.argv[2]]))
"""


class ConcurrencyTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.state_path = Path(self.directory.name) / "state.json"

    def invoke(self, *arguments):
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            result = main(["check", URL, "--state", str(self.state_path), *arguments])
        return result, stdout.getvalue(), stderr.getvalue()

    def test_another_process_cannot_check_the_same_state_while_locked(self):
        with state_lock(self.state_path):
            result = subprocess.run(
                [sys.executable, "-c", _CHILD_CHECK, URL, str(self.state_path)],
                capture_output=True,
                text=True,
                timeout=15,
                check=False,
            )

        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertEqual(result.stdout, "")
        self.assertIn("Another check is using this state file", result.stderr)
        self.assertFalse(self.state_path.exists())

        with patch("pr_lantern.cli.fetch_pr", return_value=make_pr()):
            code, _, errors = self.invoke()
        self.assertEqual((code, errors), (0, ""))
        self.assertIn(URL, load_state(self.state_path)["snapshots"])

    @patch("pr_lantern.cli.fetch_pr", return_value=make_pr())
    def test_lock_is_released_when_reporting_raises(self, fetch):
        with patch("pr_lantern.cli.render_report", side_effect=ValueError("render failed")):
            code, output, errors = self.invoke()
        self.assertEqual((code, output), (2, ""))
        self.assertIn("render failed", errors)
        self.assertFalse(self.state_path.exists())

        code, _, errors = self.invoke()
        self.assertEqual((code, errors), (0, ""))
        self.assertEqual(fetch.call_count, 2)
        self.assertIn(URL, load_state(self.state_path)["snapshots"])

    @patch("pr_lantern.cli.fetch_pr", return_value=make_pr())
    def test_no_save_can_read_while_a_writer_holds_the_lock(self, fetch):
        with state_lock(self.state_path):
            code, _, errors = self.invoke("--no-save")
        self.assertEqual((code, errors), (0, ""))
        fetch.assert_called_once()
        self.assertFalse(self.state_path.exists())


if __name__ == "__main__":
    unittest.main()
