# Watching upstream releases

amicus depends on things that release on their own schedule: three backend CLIs and the `fastmcp` and `mcp` packages it caps to a minor line.
This page is how a new release of any of them turns into an issue without anyone having to notice it.
It reports and files; it never installs, validates, widens a cap or changes a supported set, which stay manual, in their own PRs.

## Who watches what

| Stream | Baseline it is compared with | Watched by |
| --- | --- | --- |
| `codex` | the shipped `SUPPORTED_VERSIONS` in `src/amicus/backends/codex/contract.py` | the existing codex routine, which keeps `codex-upgrade` issues (`docs/UPGRADING-CODEX.md`) |
| `kimi` | the shipped `SUPPORTED_VERSIONS` in `src/amicus/backends/kimi/contract.py` | `watch` |
| `claude` | the newest capture under `docs/claude-help/`, because the shipped set is major-only and a patch never leaves it | `watch` |
| `fastmcp`, `mcp` | the `<X.Y` cap in `pyproject.toml`'s `[project].dependencies`, which `.github/dependabot.yml` tells Dependabot not to cross (#106) | `watch` |

Codex is not a `watch` stream.
Its routine writes a release-notes evaluation into each issue, which this command cannot, and two writers of the same title would only race.

## The command

```sh
uv run python scripts/check_backend_compat.py watch [--json] [--file-issues [--dry-run]] [--repo OWNER/NAME]
```

It reads npm's `latest` dist-tag for `@moonshot-ai/kimi-code` and `@anthropic-ai/claude-code`, and PyPI's JSON API for `fastmcp` and `mcp`.
It needs no installed backend CLI and no credentials for that, and it sends no prompt, so it spends nothing.
`--file-issues` additionally needs an authenticated `gh` with permission to read and create issues.

Each stream comes back as one of three statuses:

- `update`: a release past the baseline is available upstream, with the issue title it belongs to.
- `current`: nothing past the baseline is available upstream.
- `unknown`: a lookup failed, or the baseline could not be read.

`unknown` is never read as `current`: it files nothing for that stream and makes the exit status 1.
A PyPI `latest` that is not a plain final release, such as a release candidate when no final exists, is `unknown` too.

Exit status 0 means every stream was read and every issue `--file-issues` needed was found or filed; `update` findings alone do not fail it.
Exit status 1 means at least one stream was `unknown` or one `gh` call failed; argparse's usage errors exit 2.

`--json` prints `findings` (one object per stream: `stream`, `status`, `latest`, `baseline`, `key`, `title`, `labels`, `detail`) and, under `--file-issues`, `filings` (one per `update` finding: `stream`, `title`, `action`, `number`, `state`, `detail`).
`action` is `filed`, `exists`, `would_file` under `--dry-run`, or `failed`.

## The issue contract

Each `update` finding has a stable key, its stream and a version, and a title built from that key alone:

| Stream | Key | Title |
| --- | --- | --- |
| `kimi` | the latest release's `<major>.<minor>` | `chore(backends): track kimi <major>.<minor>` |
| `claude` | the latest release's full version | `chore(backends): track claude <version>` |
| `fastmcp`, `mcp` | the latest release's `<major>.<minor>` | `chore(deps): track <package> <major>.<minor> past the cap` |

The kimi title follows the codex routine's `chore(backends): track codex <major>.<minor>`.
Claude is keyed by full version because its baseline is a capture of one version, not a minor.

An issue is created only when no issue, open or closed, has exactly that title.
The check is two reads, and the title must match one of their rows character for character:

- `gh issue list --state all --search 'in:title "<title>"' --json title,number,state`, which finds an issue of any age.
- `gh issue list --state all --limit 100 --json title,number,state`, the newest issues read directly, because GitHub's search index can lag an issue created moments ago.

So a re-run files nothing, and closing an issue retires its title for good: a declined minor does not come back.
A new minor, or a new claude release, has a new title and is filed once.

Each issue is labelled `dependencies` and `chore`, both existing labels.
Its body says the release is available upstream, never that it is supported, because nothing was installed or run.

## Running it from the scheduled routine

The scheduled routine is configured outside this repository, so this text is what the maintainer pastes into it.
Run it from a checkout of `main`, with `uv` installed and `gh` authenticated as an identity that may create issues here:

```text
In a fresh checkout of briandconnelly/amicus at main, run:

    uv run python scripts/check_backend_compat.py watch --file-issues --json

Do not file, edit, close or comment on any issue yourself: the command files at most one
issue per stream and version, and only when no open or closed issue has that exact title.
Report its JSON output. If it exits non-zero, report every finding whose status is
"unknown" and every filing whose action is "failed", and say that those streams were not
checked this run; never describe an unknown stream as up to date.
```

Before the routine is trusted, exercise it twice: the first run files one issue per `update` finding, and an immediate re-run files none.
`--dry-run` shows what a run would file without creating anything; it still runs the two `gh issue list` reads.
