"""Behavioral tests for offline normalization and change detection."""

import copy
import unittest
from datetime import datetime, timezone

from pr_lantern.core import (
    change_events,
    normalize_pr,
    parse_pr_url,
    parse_time,
    report_item,
    summarize_checks,
)

URL = "https://github.com/example/project/pull/12"
NOW = datetime(2026, 11, 2, 12, tzinfo=timezone.utc)


def make_pr(url=URL, **changes):
    data = {
        "url": url,
        "title": "Fix the parser",
        "state": "OPEN",
        "createdAt": "2026-10-01T12:00:00Z",
        "isDraft": False,
        "author": {"login": "author"},
        "headRefOid": "old-head",
        "reviewDecision": "",
        "reviews": [],
        "comments": [],
        "statusCheckRollup": [],
    }
    data.update(changes)
    return data


def check(conclusion="SUCCESS", status="COMPLETED"):
    return {"__typename": "CheckRun", "status": status, "conclusion": conclusion}


class URLTests(unittest.TestCase):
    def test_canonical_url_and_trailing_slash(self):
        self.assertEqual(parse_pr_url(URL + "/"), URL)
        self.assertEqual(
            parse_pr_url("https://github.com/some-org/some.repo/pull/123"),
            "https://github.com/some-org/some.repo/pull/123",
        )

    def test_rejects_non_pr_or_ambiguous_urls(self):
        for value in (
            "http://github.com/example/project/pull/12",
            "https://example.com/example/project/pull/12",
            "https://github.com.evil.test/example/project/pull/12",
            "https://github.com@example.com/example/project/pull/12",
            "https://github.com/example/project/issues/12",
            "https://github.com/example/project/pull/0",
            "https://github.com/example/project/pull/012",
            "https://github.com/example/project/pull/12/files",
            "https://github.com/../project/pull/12",
            "https://github.com/example/./pull/12",
            URL + "?token=secret",
            URL + "#discussion",
            "example/project#12",
        ):
            with self.subTest(value=value), self.assertRaises(ValueError):
                parse_pr_url(value)

    def test_timestamps_normalize_offsets_and_reject_naive_values(self):
        self.assertEqual(parse_time("2026-11-02T20:00:00+08:00"), NOW)
        with self.assertRaises(ValueError):
            parse_time("2026-11-02T12:00:00")


class CheckTests(unittest.TestCase):
    def test_pending_failure_and_approval_requirements_are_distinct(self):
        examples = (
            (check("SUCCESS"), "passed", "passed"),
            (check("FAILURE"), "failed", "failed"),
            (check("ACTION_REQUIRED"), "action_required", "action_required"),
            (check(None, "QUEUED"), "pending", "pending"),
            (check("SUCCESS", "IN_PROGRESS"), "pending", "pending"),
            (check("FUTURE_UNKNOWN_STATE"), "pending", "pending"),
            (check("SKIPPED"), "none", "skipped"),
        )
        for raw, state, counter in examples:
            with self.subTest(raw=raw):
                summary = summarize_checks([raw])
                self.assertEqual(summary["state"], state)
                self.assertEqual(summary[counter], 1)
                self.assertEqual(summary["total"], 1)

    def test_mixed_legacy_statuses_and_check_runs(self):
        summary = summarize_checks(
            [
                check(),
                check("NEUTRAL"),
                check("ACTION_REQUIRED"),
                {"__typename": "StatusContext", "context": "legacy", "state": "PENDING"},
                {"__typename": "StatusContext", "context": "lint", "state": "ERROR"},
            ]
        )
        self.assertEqual(
            summary,
            {
                "state": "failed",
                "passed": 1,
                "failed": 1,
                "pending": 1,
                "action_required": 1,
                "skipped": 1,
                "total": 5,
            },
        )

    def test_empty_checks_are_not_reported_as_passed(self):
        self.assertEqual(summarize_checks(None)["state"], "none")
        self.assertEqual(summarize_checks([])["total"], 0)


class SnapshotTests(unittest.TestCase):
    def test_self_comments_and_pending_reviews_do_not_reset_silence(self):
        raw = make_pr(
            comments=[
                {"id": "own", "author": {"login": "author"}, "createdAt": "2026-11-02T11:00:00Z"},
                {
                    "id": "other",
                    "author": {"login": "maintainer"},
                    "createdAt": "2026-10-20T12:00:00Z",
                },
            ],
            reviews=[
                {
                    "id": "draft",
                    "author": {"login": "maintainer"},
                    "state": "PENDING",
                    "submittedAt": "2026-11-01T12:00:00Z",
                },
                {
                    "id": "self",
                    "author": {"login": "author"},
                    "state": "COMMENTED",
                    "submittedAt": "2026-11-02T12:00:00Z",
                },
            ],
        )
        snapshot = normalize_pr(raw, URL)
        self.assertEqual(snapshot["feedback"], {"comment:other": "2026-10-20T12:00:00Z"})
        self.assertEqual(snapshot["last_feedback_at"], "2026-10-20T12:00:00Z")
        self.assertEqual(report_item(snapshot, None, NOW, 14)["silence_days"], 13)

    def test_first_snapshot_is_a_baseline_not_a_change(self):
        snapshot = normalize_pr(make_pr(), URL)
        item = report_item(snapshot, None, NOW, 14)
        self.assertEqual(item["changes"], [])
        self.assertEqual(item["attention"], "Awaiting feedback (32 days)")
        self.assertNotIn("head", item)
        self.assertNotIn("feedback", item)

    def test_detects_new_feedback_and_state_changes_once(self):
        before = normalize_pr(make_pr(isDraft=True), URL)
        current = normalize_pr(
            make_pr(
                state="MERGED",
                reviewDecision="APPROVED",
                headRefOid="new-head",
                statusCheckRollup=[check()],
                comments=[
                    {"id": "c1", "author": {"login": "other"}, "createdAt": "2026-11-02T10:00:00Z"}
                ],
                reviews=[
                    {
                        "id": "r1",
                        "author": {"login": "other"},
                        "state": "APPROVED",
                        "submittedAt": "2026-11-02T11:00:00Z",
                    }
                ],
            ),
            URL,
        )
        self.assertEqual(
            change_events(before, current),
            [
                "PR: OPEN → MERGED",
                "Review: none → APPROVED",
                "Head commit changed",
                "Ready for review",
                "Checks: none → passed",
                "1 new comment from others",
                "1 new review from others",
            ],
        )
        self.assertEqual(change_events(copy.deepcopy(current), current), [])

    def test_closed_or_merged_state_takes_priority_over_old_failures(self):
        for state, label in (("MERGED", "Merged"), ("CLOSED", "Closed")):
            snapshot = normalize_pr(
                make_pr(
                    state=state,
                    reviewDecision="CHANGES_REQUESTED",
                    statusCheckRollup=[check("FAILURE")],
                ),
                URL,
            )
            with self.subTest(state=state):
                self.assertEqual(report_item(snapshot, None, NOW, 14)["attention"], label)

    def test_action_requirement_is_not_labeled_a_test_failure(self):
        snapshot = normalize_pr(make_pr(statusCheckRollup=[check("ACTION_REQUIRED")]), URL)
        item = report_item(snapshot, None, NOW, 14)
        self.assertEqual(item["attention"], "Check workflow action requirements")
        self.assertEqual(item["checks"]["failed"], 0)

    def test_rejects_mismatched_url_and_unknown_pr_state(self):
        with self.assertRaises(ValueError):
            normalize_pr(make_pr("https://github.com/example/other/pull/12"), URL)
        with self.assertRaises(ValueError):
            normalize_pr(make_pr(state="UNKNOWN"), URL)


if __name__ == "__main__":
    unittest.main()
