"""Human-readable and machine-readable pull request reports."""

from __future__ import annotations

import json
import re
import unicodedata
from typing import Any
from urllib.parse import quote, urlsplit

_MARKDOWN_SPECIAL = re.compile(r"([\\`*_{}\[\]()#+.!|<>])")


def _text(value: Any) -> str:
    """Keep display values on one line without terminal or bidi controls."""
    characters = []
    for character in str(value):
        if character.isspace():
            characters.append(" ")
        elif unicodedata.category(character) not in {"Cc", "Cf", "Cs"}:
            characters.append(character)
    return " ".join("".join(characters).split())


def _markdown(value: Any) -> str:
    text = _text(value).replace("&", "&amp;")
    return _MARKDOWN_SPECIAL.sub(r"\\\1", text)


def _link(label: str, url: str) -> str:
    """Render safe HTTP(S) links without allowing Markdown syntax in URLs."""
    clean_url = _text(url)
    try:
        parsed = urlsplit(clean_url)
    except ValueError:
        return _markdown(label)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return _markdown(label)
    destination = quote(clean_url, safe="/:#?&=%@+~._-")
    return f"[{_markdown(label)}](<{destination}>)"


def _reference(item: dict[str, Any]) -> str:
    return f"{item['repo']}#{item['number']}"


def _state(item: dict[str, Any]) -> str:
    state = _text(item["state"])
    return f"{state} (draft)" if item["draft"] else state


def _review(item: dict[str, Any]) -> str:
    return _text(item["review"]).replace("_", " ").lower() or "none"


def _checks(checks: dict[str, Any]) -> str:
    state = _text(checks["state"]).replace("_", " ")
    if state == "none":
        if checks["total"]:
            return f"skipped/neutral ({checks['skipped']} skipped, {checks['total']} total)"
        return "no checks"
    counts = []
    for key in ("passed", "failed", "pending", "action_required", "skipped"):
        count = checks.get(key, 0)
        if count:
            counts.append(f"{count} {key.replace('_', ' ')}")
    counts.append(f"{checks['total']} total")
    return f"{state} ({', '.join(counts)})"


def _unchanged(report: dict[str, Any]) -> bool:
    return (
        not report["first_run"]
        and not report["errors"]
        and not any(item.get("baseline") or item["changes"] for item in report["items"])
    )


def _render_text(report: dict[str, Any]) -> str:
    lines = [f"PR Lantern | {_text(report['generated_at'])}"]
    if report["first_run"]:
        lines.append("First run: no previous snapshot.")
    elif _unchanged(report):
        lines.append("No changes since previous successful check.")
    if not report["items"]:
        lines.append("No pull requests to report.")
    for item in report["items"]:
        lines.extend(
            [
                "",
                f"{_text(_reference(item))}: {_text(item['title'])}",
                f"  {_state(item)} | review: {_review(item)}"
                f" | checks: {_checks(item['checks'])}"
                f" | quiet: {_text(item['silence_days'])}d",
                f"  {_text(item['url'])}",
            ]
        )
        if item.get("baseline") and not report["first_run"]:
            lines.append("  Baseline: first check of this PR")
        if item["attention"]:
            lines.append(f"  Attention: {_text(item['attention'])}")
        for change in item["changes"]:
            lines.append(f"  Changed: {_text(change)}")
    if report["errors"]:
        lines.extend(["", "Errors:"])
        for error in report["errors"]:
            lines.append(f"  {_text(error['url'])}: {_text(error['message'])}")
    return "\n".join(lines) + "\n"


def _render_markdown(report: dict[str, Any]) -> str:
    lines = ["# PR Lantern", "", f"Generated: {_markdown(report['generated_at'])}"]
    if report["first_run"]:
        lines.extend(["", "First run: no previous snapshot."])
    elif _unchanged(report):
        lines.extend(["", "No changes since previous successful check."])
    if report["items"]:
        lines.extend(
            [
                "",
                "| Pull request | State | Review | Checks | Quiet | Attention |",
                "| --- | --- | --- | --- | --- | --- |",
            ]
        )
        for item in report["items"]:
            label = f"{_reference(item)}: {item['title']}"
            cells = [
                _link(label, item["url"]),
                _markdown(_state(item)),
                _markdown(_review(item)),
                _markdown(_checks(item["checks"])),
                f"{_markdown(item['silence_days'])}d",
                _markdown(item["attention"]) or "—",
            ]
            lines.append("| " + " | ".join(cells) + " |")
    else:
        lines.extend(["", "No pull requests to report."])
    changed_items = [
        item
        for item in report["items"]
        if item["changes"] or (item.get("baseline") and not report["first_run"])
    ]
    if changed_items:
        lines.extend(["", "## Changes", ""])
        for item in changed_items:
            descriptions = []
            if item.get("baseline") and not report["first_run"]:
                descriptions.append("Baseline: first check of this PR")
            descriptions.extend(_markdown(change) for change in item["changes"])
            changes = "; ".join(descriptions)
            lines.append(f"- {_link(_reference(item), item['url'])}: {changes}")
    if report["errors"]:
        lines.extend(["", "## Errors", ""])
        for error in report["errors"]:
            lines.append(f"- {_link(error['url'], error['url'])}: {_markdown(error['message'])}")
    return "\n".join(lines) + "\n"


def render_report(report: dict, format: str) -> str:
    """Return a newline-terminated report in text, markdown, or JSON format."""
    if format == "json":
        # Escape control and non-ASCII characters without changing their data values.
        return json.dumps(report, ensure_ascii=True, indent=2) + "\n"
    if format == "text":
        return _render_text(report)
    if format == "markdown":
        return _render_markdown(report)
    raise ValueError(f"Unsupported report format: {format!r}")
