"""Command-line entry point."""

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

from . import __version__
from .core import normalize_pr, parse_pr_url, report_item
from .github import fetch_pr
from .render import render_report
from .state import load_state, save_state, state_lock


def positive(value):
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return number


def build_parser():
    parser = argparse.ArgumentParser(description="See what changed in your GitHub pull requests.")
    parser.add_argument("--version", action="version", version=f"pr-lantern {__version__}")
    commands = parser.add_subparsers(dest="command", required=True)
    check = commands.add_parser("check", help="Fetch PRs once and compare with local snapshots")
    check.add_argument("urls", nargs="*", help="GitHub PR URLs; omit to reuse the saved watchlist")
    check.add_argument("--state", type=Path, default=Path(".pr-lantern/state.json"))
    check.add_argument("--format", choices=("text", "markdown", "json"), default="text")
    check.add_argument("--stale-days", type=positive, default=14)
    check.add_argument(
        "--timeout", type=positive, default=30, help="Per-request timeout in seconds"
    )
    check.add_argument("--no-save", action="store_true", help="Compare without updating snapshots")
    check.add_argument("--output", type=Path, help="Write report to a file instead of stdout")
    check.add_argument("--fail-on-action", action="store_true")
    return parser


def run_check(args):
    if args.output and args.output.resolve() == args.state.resolve():
        raise ValueError("Report output and snapshot state must be different files")
    if args.no_save:
        return _run_check(args)
    with state_lock(args.state):
        return _run_check(args)


def write_console(text, stream):
    """Keep redirected legacy-codepage streams usable; report files stay UTF-8."""
    encoding = getattr(stream, "encoding", None)
    if encoding:
        text = text.encode(encoding, errors="backslashreplace").decode(encoding)
    stream.write(text)


def _run_check(args):
    state = load_state(args.state)
    urls = list(dict.fromkeys(parse_pr_url(url) for url in args.urls))
    if not urls:
        urls = list(state["snapshots"])
    if not urls:
        raise ValueError("No PRs to check. Pass one or more GitHub pull request URLs.")
    now = datetime.now(timezone.utc)
    report = {
        "generated_at": now.isoformat(),
        "first_run": not bool(state["snapshots"]),
        "items": [],
        "errors": [],
    }
    for url in urls:
        try:
            snapshot = normalize_pr(fetch_pr(url, timeout=args.timeout), url)
            item = report_item(snapshot, state["snapshots"].get(url), now, args.stale_days)
        except (RuntimeError, ValueError, KeyError, TypeError, AttributeError) as exc:
            report["errors"].append({"url": url, "message": str(exc)})
            continue
        report["items"].append(item)
        state["snapshots"][url] = snapshot
    rendered = render_report(report, args.format)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    else:
        write_console(rendered, sys.stdout)
    if not args.no_save and report["items"]:
        state["checked_at"] = now.isoformat()
        save_state(args.state, state)
    if report["errors"]:
        return 2
    if args.fail_on_action and any(
        item["state"] == "OPEN"
        and (
            item["review"] == "CHANGES_REQUESTED"
            or item["checks"]["failed"]
            or item["checks"]["action_required"]
        )
        for item in report["items"]
    ):
        return 1
    return 0


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        return run_check(args)
    except (OSError, ValueError) as exc:
        write_console(f"pr-lantern: {exc}\n", sys.stderr)
        return 2
