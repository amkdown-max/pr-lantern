"""Legacy Windows code pages must not prevent successful checks."""

import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pr_lantern.cli import main, write_console
from pr_lantern.state import load_state
from tests.test_core import URL, make_pr


class ConsoleTests(unittest.TestCase):
    def encoded_stream(self, encoding):
        buffer = io.BytesIO()
        # These assertions test encoding; keep platform newline translation separate.
        stream = io.TextIOWrapper(buffer, encoding=encoding, errors="strict", newline="")
        self.addCleanup(stream.close)
        return stream, buffer

    def test_legacy_code_page_escapes_unrepresentable_characters(self):
        stream, buffer = self.encoded_stream("cp1252")
        write_console("café → 修复\n", stream)
        stream.flush()
        self.assertEqual(buffer.getvalue().decode("cp1252"), "café \\u2192 \\u4fee\\u590d\n")

    def test_utf8_output_preserves_unicode(self):
        stream, buffer = self.encoded_stream("utf-8")
        text = "café → 修复 🏮\n"
        write_console(text, stream)
        stream.flush()
        self.assertEqual(buffer.getvalue().decode("utf-8"), text)

    def test_stream_without_an_encoding_preserves_unicode(self):
        stream = io.StringIO()
        text = "修复 → merged\n"
        write_console(text, stream)
        self.assertEqual(stream.getvalue(), text)

    def test_cli_saves_original_title_with_legacy_redirected_stdout(self):
        title = "café → 修复"
        stream, buffer = self.encoded_stream("cp1252")
        with tempfile.TemporaryDirectory() as directory:
            state_path = Path(directory) / "state.json"
            with (
                patch("pr_lantern.cli.fetch_pr", return_value=make_pr(title=title)),
                patch("pr_lantern.cli.sys.stdout", stream),
            ):
                result = main(["check", URL, "--state", str(state_path)])
            stream.flush()
            self.assertEqual(result, 0)
            self.assertEqual(load_state(state_path)["snapshots"][URL]["title"], title)
        output = buffer.getvalue().decode("cp1252")
        self.assertIn("café \\u2192 \\u4fee\\u590d", output)

    def test_cli_error_is_safe_on_legacy_redirected_stderr(self):
        stream, buffer = self.encoded_stream("cp1252")
        with (
            patch("pr_lantern.cli.run_check", side_effect=ValueError("修复 → retry")),
            patch("pr_lantern.cli.sys.stderr", stream),
        ):
            result = main(["check", URL])
        stream.flush()
        self.assertEqual(result, 2)
        self.assertEqual(
            buffer.getvalue().decode("cp1252"), "pr-lantern: \\u4fee\\u590d \\u2192 retry\n"
        )


if __name__ == "__main__":
    unittest.main()
