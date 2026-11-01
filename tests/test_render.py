"""Rendering behavior for complete reports and untrusted GitHub strings."""

from __future__ import annotations

import copy
import json
import re
import unittest

from pr_lantern.render import render_report


def sample_report() -> dict:
    return {
        "generated_at": "2026-11-02T08:00:00+00:00",
        "first_run": False,
        "items": [
            {
                "url": "https://github.com/example/project/pull/42",
                "repo": "example/project",
                "number": 42,
                "title": "Fix a parser edge case",
                "state": "OPEN",
                "draft": False,
                "review": "CHANGES_REQUESTED",
                "checks": {
                    "state": "action_required",
                    "passed": 2,
                    "failed": 0,
                    "pending": 0,
                    "action_required": 1,
                    "skipped": 1,
                    "total": 4,
                },
                "silence_days": 3,
                "attention": "Reply to the review",
                "changes": ["Review changed to CHANGES_REQUESTED"],
            }
        ],
        "errors": [{"url": "https://github.com/example/other/pull/1", "message": "Not found"}],
    }


class RenderReportTests(unittest.TestCase):
    def test_text_exposes_action_and_partial_error(self):
        output = render_report(sample_report(), "text")
        self.assertIn("example/project#42: Fix a parser edge case", output)
        self.assertIn("review: changes requested", output)
        self.assertIn("checks: action required", output)
        self.assertIn("2 passed, 1 action required, 1 skipped, 4 total", output)
        self.assertIn("quiet: 3d", output)
        self.assertIn("Attention: Reply to the review", output)
        self.assertIn("Changed: Review changed to CHANGES_REQUESTED", output)
        self.assertIn("Errors:\n", output)
        self.assertIn("https://github.com/example/other/pull/1: Not found", output)
        self.assertNotIn("failed", output)

    def test_markdown_escapes_cells_links_and_untrusted_newlines(self):
        report = sample_report()
        report["items"][0]["title"] = "a|b\n[x](javascript:bad) <img> &copy;"
        report["items"][0]["attention"] = "Use `x` | review\r\nnext"
        report["items"][0]["changes"] = ["a|b\n<script>"]
        report["errors"][0]["message"] = "bad|error\n<img>"
        output = render_report(report, "markdown")
        rows = [line for line in output.splitlines() if line.startswith("|")]
        self.assertEqual(len(rows), 3)
        self.assertEqual(len(re.split(r"(?<!\\)\|", rows[2])), 8)
        self.assertIn(r"a\|b \[x\]\(javascript:bad\) \<img\> &amp;copy;", output)
        self.assertIn(r"Use \`x\` \| review next", output)
        self.assertIn("## Changes", output)
        self.assertIn("## Errors", output)
        self.assertNotIn("<script>", output)
        self.assertNotIn("<img>", output)

    def test_display_formats_remove_terminal_and_bidi_controls(self):
        report = sample_report()
        report["items"][0]["title"] = "hello\x1b[2J\x00\x07\x9b31m\u202eevil"
        report["errors"][0]["message"] = "oops\x1b]0;title\x07\nsecond line"
        for format in ("text", "markdown"):
            with self.subTest(format=format):
                output = render_report(report, format)
                for control in ("\x1b", "\x00", "\x07", "\x9b", "\u202e", "\r"):
                    self.assertNotIn(control, output)
                self.assertIn("second line", output)

    def test_markdown_destination_cannot_end_link_or_inject_html(self):
        report = sample_report()
        report["items"][0]["url"] += "><img>(bad)|more"
        output = render_report(report, "markdown")
        self.assertIn("%3E%3Cimg%3E%28bad%29%7Cmore", output)
        self.assertNotIn("<img>", output)

    def test_markdown_does_not_link_unsafe_schemes(self):
        report = sample_report()
        report["items"][0]["url"] = "javascript:alert(1)"
        output = render_report(report, "markdown")
        self.assertNotIn("javascript:", output)
        self.assertIn("Fix a parser edge case", output)

    def test_json_round_trips_values_including_urls_and_controls(self):
        report = sample_report()
        report["items"][0]["title"] = "你好\x1b[31m\u202e"
        report["items"][0]["url"] += "?name=你好|a(b)"
        original = copy.deepcopy(report)
        output = render_report(report, "json")
        self.assertEqual(json.loads(output), original)
        self.assertEqual(report, original)
        self.assertNotIn("\x1b", output)
        self.assertNotIn("\u202e", output)
        self.assertIn('\n  "generated_at":', output)

    def test_baseline_empty_report_and_no_checks(self):
        report = sample_report()
        report["first_run"] = True
        report["items"][0]["state"] = "CLOSED"
        report["items"][0]["draft"] = True
        report["items"][0]["review"] = ""
        report["items"][0]["checks"]["state"] = "none"
        report["items"][0]["checks"]["total"] = 0
        for format in ("text", "markdown"):
            with self.subTest(format=format):
                output = render_report(report, format)
                self.assertIn("First run: no previous snapshot.", output)
                self.assertIn("no checks", output)
                self.assertIn("draft", output)
        report["items"] = []
        report["errors"] = []
        for format in ("text", "markdown"):
            with self.subTest(format=format):
                output = render_report(report, format)
                self.assertIn("No pull requests to report.", output)
                self.assertNotIn("Errors", output)

    def test_new_pr_baseline_is_explicit_in_an_existing_report(self):
        report = sample_report()
        report["errors"] = []
        report["items"][0]["changes"] = []
        baseline_item = copy.deepcopy(report["items"][0])
        baseline_item["number"] = 43
        baseline_item["url"] = "https://github.com/example/project/pull/43"
        baseline_item["baseline"] = True
        report["items"].append(baseline_item)
        for format in ("text", "markdown"):
            with self.subTest(format=format):
                output = render_report(report, format)
                self.assertEqual(output.count("Baseline: first check of this PR"), 1)
                self.assertNotIn("No changes since previous successful check.", output)
        markdown = render_report(report, "markdown")
        self.assertIn("## Changes", markdown)
        self.assertIn("Baseline: first check of this PR", markdown.split("## Changes")[1])

    def test_no_changes_summary_requires_successful_nonbaseline_report(self):
        report = sample_report()
        report["errors"] = []
        report["items"][0]["changes"] = []
        report["items"][0]["baseline"] = False
        summary = "No changes since previous successful check."
        for format in ("text", "markdown"):
            with self.subTest(format=format):
                self.assertIn(summary, render_report(report, format))
                for variation in ("first_run", "error", "change"):
                    modified = copy.deepcopy(report)
                    if variation == "first_run":
                        modified["first_run"] = True
                    elif variation == "error":
                        modified["errors"] = [{"url": "https://example.org", "message": "Failed"}]
                    else:
                        modified["items"][0]["changes"] = ["Merged"]
                    self.assertNotIn(summary, render_report(modified, format))

    def test_all_skipped_checks_are_not_described_as_absent(self):
        report = sample_report()
        report["items"][0]["checks"].update(
            state="none", passed=0, action_required=0, skipped=3, total=3
        )
        text = render_report(report, "text")
        self.assertIn("skipped/neutral (3 skipped, 3 total)", text)
        markdown = render_report(report, "markdown")
        self.assertIn(r"skipped/neutral \(3 skipped, 3 total\)", markdown)
        self.assertNotIn("no checks", text + markdown)

    def test_unknown_format_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "Unsupported report format"):
            render_report(sample_report(), "html")


if __name__ == "__main__":
    unittest.main()
