"""Persistence must never replace a previous snapshot with corrupt data."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pr_lantern.core import normalize_pr
from pr_lantern.state import load_state, save_state
from tests.test_core import URL, make_pr


class StateTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "cache" / "state.json"

    def test_missing_state_starts_empty(self):
        self.assertEqual(load_state(self.path), {"version": 1, "snapshots": {}})
        self.assertFalse(self.path.exists())

    def test_unicode_snapshot_round_trip(self):
        state = {"version": 1, "snapshots": {URL: normalize_pr(make_pr(title="修复 🏮"), URL)}}
        save_state(self.path, state)
        self.assertEqual(load_state(self.path), state)
        self.assertIn("修复", self.path.read_text(encoding="utf-8"))

    def test_corrupt_or_unsupported_state_is_left_unchanged(self):
        self.path.parent.mkdir()
        for content in (
            "{broken",
            "[]",
            '{"version":2,"snapshots":{}}',
            '{"version":1,"snapshots":[]}',
        ):
            with self.subTest(content=content):
                self.path.write_text(content, encoding="utf-8")
                with self.assertRaisesRegex(ValueError, "File left unchanged"):
                    load_state(self.path)
                self.assertEqual(self.path.read_text(encoding="utf-8"), content)

    def test_snapshot_url_must_match_its_dictionary_key(self):
        snapshot = normalize_pr(make_pr(), URL)
        snapshot["url"] = "https://github.com/example/project/pull/13"
        save_state(self.path, {"version": 1, "snapshots": {URL: snapshot}})
        with self.assertRaisesRegex(ValueError, "Invalid snapshot URL"):
            load_state(self.path)

    def test_corrupt_nested_data_is_rejected_without_overwriting_file(self):
        valid = normalize_pr(make_pr(), URL)
        checks = valid["checks"]
        cases = (
            {"state": "UNKNOWN"},
            {"draft": 1},
            {"checks": {**checks, "state": "unexpected"}},
            {"checks": {**checks, "state": []}},
            {"checks": {**checks, "passed": -1}},
            {"checks": {**checks, "pending": True}},
            {"checks": {**checks, "failed": "1"}},
            {"checks": {**checks, "total": 1}},
            {"checks": {key: value for key, value in checks.items() if key != "total"}},
            {"feedback": {"comment:1": []}},
            {"feedback": {"comment:1": "not a timestamp"}},
            {"feedback": {"comment:1": "2026-11-02T12:00:00"}},
        )
        for changes in cases:
            with self.subTest(changes=changes):
                state = {"version": 1, "snapshots": {URL: {**valid, **changes}}}
                save_state(self.path, state)
                original_bytes = self.path.read_bytes()
                with self.assertRaisesRegex(ValueError, "File left unchanged"):
                    load_state(self.path)
                self.assertEqual(self.path.read_bytes(), original_bytes)

    def test_failed_atomic_replace_preserves_original_and_removes_temp_file(self):
        original = {"version": 1, "snapshots": {}}
        save_state(self.path, original)
        with patch("pr_lantern.state.os.replace", side_effect=OSError("disk error")):
            with self.assertRaises(OSError):
                save_state(self.path, {"version": 1, "snapshots": {}, "checked_at": "new"})
        self.assertEqual(json.loads(self.path.read_text(encoding="utf-8")), original)
        self.assertEqual(list(self.path.parent.glob(".lantern-*")), [])


if __name__ == "__main__":
    unittest.main()
