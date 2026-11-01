"""Normalize GitHub responses and compare snapshots without network access."""

import re
from datetime import datetime, timezone
from urllib.parse import urlsplit


def parse_pr_url(value):
    """Accept a public GitHub PR link and return its canonical URL."""
    parts = urlsplit(value)
    match = re.fullmatch(r"/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)/pull/([1-9][0-9]*)/?", parts.path)
    if (
        parts.scheme != "https"
        or parts.netloc != "github.com"
        or not match
        or parts.query
        or parts.fragment
    ):
        raise ValueError("Expected https://github.com/OWNER/REPO/pull/NUMBER")
    owner, repo, number = match.groups()
    if owner in (".", "..") or repo in (".", ".."):
        raise ValueError("Invalid GitHub repository name")
    return f"https://github.com/{owner.lower()}/{repo.lower()}/pull/{int(number)}"


def parse_time(value):
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise ValueError("GitHub timestamps must include a timezone")
    return result.astimezone(timezone.utc)


def summarize_checks(checks):
    counts = dict(passed=0, failed=0, pending=0, action_required=0, skipped=0)
    for check in checks or []:
        if check.get("__typename") == "StatusContext" or "context" in check:
            result = str(check.get("state", "PENDING")).upper()
        elif str(check.get("status", "")).upper() != "COMPLETED":
            result = "PENDING"
        else:
            result = str(check.get("conclusion") or "PENDING").upper()
        if result == "SUCCESS":
            counts["passed"] += 1
        elif result in {"NEUTRAL", "SKIPPED"}:
            counts["skipped"] += 1
        elif result == "ACTION_REQUIRED":
            counts["action_required"] += 1
        elif result in {"FAILURE", "ERROR", "TIMED_OUT", "CANCELLED", "STARTUP_FAILURE", "STALE"}:
            counts["failed"] += 1
        else:
            # New or unknown provider states must not be presented as successful.
            counts["pending"] += 1
    total = sum(counts.values())
    state = next(
        (key for key in ("failed", "action_required", "pending") if counts[key]),
        "passed" if counts["passed"] else "none",
    )
    return {"state": state, **counts, "total": total}


def normalize_pr(data, requested_url):
    url = parse_pr_url(data["url"])
    if url != parse_pr_url(requested_url):
        raise ValueError("GitHub returned a different PR URL")
    parts = urlsplit(url).path.split("/")
    author = (data.get("author") or {}).get("login")
    feedback = {}
    for kind, entries in (("comment", data.get("comments")), ("review", data.get("reviews"))):
        for entry in entries or []:
            who = (entry.get("author") or {}).get("login")
            if who == author and author is not None:
                continue
            if kind == "review" and entry.get("state") == "PENDING":
                continue
            when = entry.get("submittedAt") or entry.get("createdAt")
            if when:
                parse_time(when)
                identifier = entry.get("id") or f"{who}:{when}:{entry.get('state', '')}"
                feedback[f"{kind}:{identifier}"] = when
    created_at = data["createdAt"]
    parse_time(created_at)
    last_feedback_at = max([created_at, *feedback.values()], key=parse_time)
    state = data["state"].upper()
    if state not in {"OPEN", "CLOSED", "MERGED"}:
        raise ValueError(f"Unknown pull request state: {state}")
    return {
        "url": url,
        "repo": "/".join(parts[1:3]),
        "number": int(parts[4]),
        "title": data["title"],
        "state": state,
        "draft": bool(data.get("isDraft")),
        "review": data.get("reviewDecision") or "",
        "head": data.get("headRefOid") or "",
        "checks": summarize_checks(data.get("statusCheckRollup")),
        "created_at": created_at,
        "last_feedback_at": last_feedback_at,
        "feedback": feedback,
    }


def change_events(previous, current):
    if previous is None:
        return []
    changes = []
    for key, label in (("state", "PR"), ("review", "Review")):
        if previous.get(key) != current[key]:
            changes.append(f"{label}: {previous.get(key) or 'none'} → {current[key] or 'none'}")
    if previous.get("head") != current["head"]:
        changes.append("Head commit changed")
    if previous.get("draft") != current["draft"]:
        changes.append("Marked as draft" if current["draft"] else "Ready for review")
    before_checks = previous.get("checks", {}).get("state", "none")
    if before_checks != current["checks"]["state"]:
        changes.append(f"Checks: {before_checks} → {current['checks']['state']}")
    unseen = current["feedback"].keys() - previous.get("feedback", {}).keys()
    for kind in ("comment", "review"):
        count = sum(key.startswith(kind + ":") for key in unseen)
        if count:
            changes.append(f"{count} new {kind}{'s' if count != 1 else ''} from others")
    return changes


def report_item(snapshot, previous, now, stale_days):
    age = max(0, (now - parse_time(snapshot["last_feedback_at"])).days)
    if snapshot["state"] == "MERGED":
        attention = "Merged"
    elif snapshot["state"] == "CLOSED":
        attention = "Closed"
    elif snapshot["review"] == "CHANGES_REQUESTED":
        attention = "Address requested changes"
    elif snapshot["checks"]["failed"]:
        attention = "Inspect failing or cancelled checks"
    elif snapshot["checks"]["action_required"]:
        attention = "Check workflow action requirements"
    elif snapshot["draft"]:
        attention = "Draft"
    elif snapshot["checks"]["pending"]:
        attention = "Checks running or queued"
    elif snapshot["review"] == "APPROVED":
        attention = "Approved; check merge requirements"
    elif age >= stale_days:
        attention = f"Awaiting feedback ({age} days)"
    else:
        attention = "Awaiting review"
    return {
        **{key: value for key, value in snapshot.items() if key not in {"feedback", "head"}},
        "silence_days": age,
        "attention": attention,
        "baseline": previous is None,
        "changes": change_events(previous, snapshot),
    }
