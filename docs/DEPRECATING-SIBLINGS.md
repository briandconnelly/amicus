# Deprecating the sibling servers

The deprecation is complete.
amicus replaces `codex-in-claude`, `moonbridge` and `claude-in-codex`, and all three, together with `pontonier`, are deprecated, have shipped a final release and are archived on GitHub.
This document records that end state and the decisions behind it; it is no longer a checklist, and nothing in it is waiting on anyone.

The steps were the maintainer's to run by hand, in the sibling repositories themselves, because AGENTS.md rule 17 forbids any agent from editing a sibling checkout.

## End state

Each row was confirmed on 2026-10-07 from the GitHub repository (`isArchived`, the latest release and the README's deprecation notice) and, where the maintainer publishes the package, from `https://pypi.org/pypi/<name>/json`.

| Project | Final release | GitHub | PyPI |
| --- | --- | --- | --- |
| `codex-in-claude` | `v0.24.0` (2026-10-04) | archived, README deprecation notice | `0.24.0`, `Development Status :: 7 - Inactive`, no release yanked |
| `moonbridge` | `v0.4.0` (2026-10-04) | archived, README deprecation notice | never published under this name; see below |
| `claude-in-codex` | `v0.10.0` (2026-10-06) | archived, README deprecation notice | `0.10.0`, `Development Status :: 7 - Inactive`, no release yanked |
| `pontonier` | `v0.9.1` (2026-10-06) | archived, README deprecation notice | `0.9.1`, `Development Status :: 7 - Inactive`, no release yanked |

Every deprecation notice points at amicus.
Installed versions keep running from the exact version or git tag their `.mcp.json` pins; they get no further fixes or releases.

## Why no release was yanked

A yank signals "broken, do not use" on PyPI's own listing, which is not the message a deprecation intends.
It would not have broken a pinned install either: under PEP 592 a yanked release is still selected when a requirement pins that exact version.
So each published sibling took the `Development Status :: 7 - Inactive` classifier in a final release instead, and every earlier release stays installable.

## `moonbridge` and the PyPI name collision

`briandconnelly/moonbridge` was never published to PyPI, because the distribution name `moonbridge` there belongs to an unrelated project: `info.author_email` "Phaedrus <hello@mistystep.io>" and `info.project_urls.Repository` `https://github.com/misty-step/moonbridge`.
Users installed it from a pinned git tag with `uvx` (`git+https://github.com/briandconnelly/moonbridge.git@v0.4.0` for the final release) and through its two plugin-marketplace listings, `.claude-plugin/marketplace.json` for Claude Code and `.agents/plugins/marketplace.json` for Codex.

Issue #15 asked whether to rename it; the decision is to leave the name as it is, with the collision documented here.
A rename would only help a project that publishes again, and moonbridge is archived at its final release.
Its deprecation notice points at amicus's GitHub repository, never at anything PyPI-shaped, so a user who searches PyPI for "moonbridge" and finds the `misty-step` project was never sent there by this project.
The PyPI package named `moonbridge` is not the maintainer's to act on, so nothing was changed on it.
The parallel question about the name `amicus` was decided separately, by ADR 0013.

## `pontonier`

amicus carries pontonier's code as `amicus.sdk` and no longer depends on it (ADR 0029).
That ADR kept pontonier published only for the three siblings until they were archived, and pontonier's own release gate ran `scripts/check_consumers.sh` against all three checkouts.
With all three archived, pontonier shipped a final `0.9.1` and was archived in turn, so that gate will never run again.

## Where users are pointed instead

Every sibling's README points at amicus, and this repository's `docs/MIGRATION.md` maps each sibling's tools and environment variables to their amicus equivalents.
