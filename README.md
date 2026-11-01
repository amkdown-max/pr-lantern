# PR Lantern

A small, local command-line tool that tells you what changed on the GitHub pull requests you care about.

PR Lantern uses your existing GitHub CLI authentication, compares each PR with its last successful snapshot, and writes a readable report. It has no Python runtime dependencies and makes read-only GitHub requests.

## Install from this checkout

You need Python 3.10 or later and the [GitHub CLI](https://cli.github.com/).

```sh
gh auth login

# In the PR Lantern checkout:
pipx install .
# Or:
uv tool install .
```

This project is not yet published on PyPI. The commands above install the local checkout.

## Check a pull request

```sh
pr-lantern check https://github.com/owner/repo/pull/123
```

The first successful check establishes a baseline. Later checks report changes since that baseline or the previous successful check.

Successful snapshots are saved to `.pr-lantern/state.json` in the current directory. Run from the same directory without URLs to check the saved watchlist:

```sh
pr-lantern check
```

A new URL joins the saved watchlist after its first successful check. If that first request fails, pass the URL again when retrying.

You can check several PRs, choose a state location, and write a Markdown report:

```sh
pr-lantern check \
  https://github.com/owner/repo/pull/123 \
  https://github.com/owner/repo/pull/456 \
  --state .pr-lantern/team.json \
  --format markdown \
  --output report.md
```

For scripts, use `--format json`. To inspect a PR without advancing its saved baseline, use `--no-save`.

## What it reports

- New top-level conversation comments and submitted reviews from other accounts.
- Merges, closures, new head commits, and changes to check status.
- Current failed, cancelled, or action-required checks and requested changes that may need attention.
- Days since the latest comment or review by someone other than the PR author, falling back to the PR creation date.

The last measure is a limited signal of review silence. It does not include inline review threads or activity elsewhere. `pending` and `action_required` check states are reported separately from failures; `action_required` can include workflow approval requirements and other required actions.

Inline review comments, reactions, and changes to existing comment text are outside the v0.1 change report. A first check is explicitly a baseline, not a claim that old comments or reviews just arrived.

## Options

| Option | Default | Purpose |
| --- | --- | --- |
| `--state PATH` | `.pr-lantern/state.json` | Choose the local watchlist and snapshot file. |
| `--format text\|markdown\|json` | `text` | Choose the report format. |
| `--stale-days N` | `14` | Set the review-silence threshold. |
| `--timeout SECONDS` | `30` | Set the GitHub command timeout. |
| `--no-save` | Off | Leave the saved baseline unchanged. |
| `--output PATH` | Standard output | Write the report to a file. |
| `--fail-on-action` | Off | Return exit code 1 when an open PR needs action. |

Each invocation performs one check and exits. There is no background monitor or notification service. You can run the command from your own scheduler if you want recurring reports.

## Exit codes and failed checks

| Code | Meaning |
| --- | --- |
| `0` | All requested PRs were checked successfully. |
| `1` | All checks completed, and `--fail-on-action` found an open PR with requested changes or failed, cancelled, or action-required checks. |
| `2` | The command could not complete successfully, including a partial GitHub fetch failure. |

If one PR cannot be fetched, its last good snapshot is retained and the report includes the error. Successful PRs can still advance their snapshots. Errors are not interpreted as a PR closing, its comments disappearing, or its checks passing. Review silence and pending checks alone do not trigger exit code 1. Merged and closed PRs do not trigger it either.

Overlapping checks using the same state file are refused with exit code 2, so one check cannot overwrite another's updates. The operating system releases the lock when the process exits; the small `.lock` file can remain in place. `--no-save` checks can run alongside a writer.

Report files are UTF-8. On a terminal or redirected stream with a limited encoding, unsupported characters are shown as Unicode escape sequences.

State files and exported reports may contain private repository names, PR titles, and discussion metadata. Keep them in a suitable local location and out of shared commits. PR Lantern relies on `gh` for authentication; it does not ask for or store a GitHub token itself.

## Development

```sh
python -m pip install .
python -m unittest discover -s tests -v

# Optional style checks:
python -m pip install ruff
python -m ruff check .
```

See [the design notes](docs/design.md) for snapshot and reporting semantics.

PR Lantern is an AI-developed project, built with OpenAI Codex under a human owner's direction. That origin is disclosed so contributors can assess the implementation through its source, tests, and documented limitations.

Licensed under [MIT](LICENSE).
