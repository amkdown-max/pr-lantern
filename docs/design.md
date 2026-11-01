# Design

PR Lantern answers one question: **what changed on these pull requests since my last successful check?** It is a local CLI, with Python 3.10+ and `gh` as its only runtime requirements.

## One invocation

1. Read the local state file, if present.
2. Use the supplied PR URLs, or the watchlist already recorded in that state file.
3. Fetch current PR metadata, top-level comments, submitted reviews, and checks through the authenticated GitHub CLI.
4. Normalize each successful response and compare it with that PR's last successful snapshot.
5. Render a text, Markdown, or JSON report.
6. Save successful snapshots unless `--no-save` was set.

GitHub access is read-only. The tool does not post comments, request reviews, rerun workflows, merge PRs, or change branches. It does not run continuously or send background notifications.

## Snapshot semantics

The first successful fetch records a baseline. Existing comments, reviews, and commits are not reported as new activity on that first run.

Later reports compare normalized data rather than raw response ordering. New top-level comments and submitted reviews are identified by their GitHub identities. PR state, merge status, head commit, and check status are compared with the previous successful values.

A fetch failure leaves the affected PR's last good snapshot intact. If other PRs succeed, those snapshots can still advance. This avoids turning missing data into false changes. A partial failure remains visible in the report and exits with code 2, even if other PRs also need action.

`--no-save` performs the same comparison without advancing the baseline. Repeating that check can therefore report the same changes again.

The default state path is relative to the current working directory. Use an explicit `--state` path when invoking the tool from different directories or a scheduler.

## Review silence

`silence_days` measures the age of the latest top-level comment or submitted review by an account other than the PR author. If none exists, it measures age since the PR was created. The default threshold is 14 days and can be changed with `--stale-days`.

This is a narrow observation, not proof that a maintainer is inactive or that the project is abandoned. Inline review discussions, activity in other issues, chat, and unpublished review work are not included. Bot comments from a different account can also reset this signal.

## Checks and attention

Pending checks, checks requiring action, failed checks, and successful checks have different meanings. In particular, GitHub's `action_required` state is not automatically a test failure; it may require workflow approval or another action.

The default exit status describes whether PR Lantern completed the check. `--fail-on-action` is an opt-in for scripts: after a fully successful fetch, an open PR with requested changes or failed, cancelled, or action-required checks produces exit code 1. These check states retain their separate meanings in the report. Pending checks and review silence alone do not trigger exit code 1; neither do merged or closed PRs.

## v0.1 boundaries

- Top-level conversation comments and submitted reviews are covered; inline review threads are not.
- Changes to existing comment text and reactions are not activity events.
- The head SHA can show that code changed, but the tool does not analyze the patch or judge its correctness.
- No hosted storage, GitHub webhook receiver, background daemon, or notification delivery is required.
- The report describes fetched GitHub state at one point in time. A later event appears on the next successful check.

The local snapshot is intentionally simple and inspectable. It can contain private-repository metadata, so users should treat it and exported reports as project data rather than commit them by default.

## Development and licensing

The implementation uses the Python standard library and calls the installed `gh` executable. Tests should use recorded or synthetic responses rather than live credentials. CI exercises Python 3.10, 3.12, and 3.14 on Ubuntu, plus Python 3.12 on Windows.

The project was developed with OpenAI Codex under human direction and is licensed under [MIT](../LICENSE). This disclosure does not replace review of the implementation or its tests.
