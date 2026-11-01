"""Read-only GitHub access through the user's existing gh authentication."""

import json
import subprocess

FIELDS = ",".join(
    [
        "url",
        "title",
        "state",
        "createdAt",
        "isDraft",
        "author",
        "headRefOid",
        "reviewDecision",
        "reviews",
        "comments",
        "statusCheckRollup",
    ]
)


def fetch_pr(url, timeout=30):
    try:
        result = subprocess.run(
            ["gh", "pr", "view", url, "--json", FIELDS],
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=timeout,
            check=False,
        )
    except FileNotFoundError as exc:
        raise RuntimeError("GitHub CLI is missing. Install gh and run gh auth login.") from exc
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"GitHub request timed out after {timeout} seconds.") from exc
    if result.returncode:
        message = result.stderr.strip()[:500] or "GitHub CLI request failed."
        raise RuntimeError(message)
    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError("GitHub CLI returned invalid JSON.") from exc
    if not isinstance(data, dict):
        raise RuntimeError("GitHub CLI returned an unexpected response.")
    return data
