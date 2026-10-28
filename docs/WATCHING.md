# Watching upstream releases

amicus depends on things that release on their own schedule: three backend CLIs and the `fastmcp` and `mcp` packages it caps to a minor line.
This page is how a new release of any of them turns into an issue without anyone having to notice it.
It reports and files; it never installs, validates, widens a cap or changes a supported set, which stay manual, in their own PRs.

## Who watches what

| Stream | Baseline it is compared with | Watched by |
| --- | --- | --- |
| `codex` | the shipped `SUPPORTED_VERSIONS` in `src/amicus/backends/codex/contract.py` | the codex routine, which opens a draft support PR for each new minor (`docs/UPGRADING-CODEX.md`) |
| `kimi` | the shipped `SUPPORTED_VERSIONS` in `src/amicus/backends/kimi/contract.py` | `watch` |
| `claude` | the newest capture under `docs/claude-help/`, because the shipped set is major-only and a patch never leaves it | `watch` |
| `fastmcp`, `mcp` | the `<X.Y` cap in `pyproject.toml`'s `[project].dependencies`, which `.github/dependabot.yml` tells Dependabot not to cross (#106) | `watch` |

Codex is not a `watch` stream.
Its routine does the zero-spend upgrade steps and writes a release-notes evaluation into a draft support PR, which this command cannot.

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

A response cut short, a malformed HTTP response or output that cannot be decoded is a failed lookup like any other, and the other streams are still read.
So is a `docs/claude-help/` that cannot be listed.

Exit status 0 means every stream was read and every issue `--file-issues` needed was found, filed or moved forward; `update` findings alone do not fail it.
Exit status 1 means at least one stream was `unknown`, one `gh` call failed, a title search may have been cut short, or the claude stream found more than one open tracking issue; argparse's usage errors exit 2.

`--json` prints `findings` (one object per stream: `stream`, `status`, `latest`, `baseline`, `key`, `title`, `labels`, `detail`) and, under `--file-issues`, `filings` (one per `update` finding: `stream`, `title`, `action`, `number`, `state`, `detail`, `moved_from`).
`action` is `filed`, `edited` (claude only), `exists`, `would_file` or `would_edit` under `--dry-run`, or `failed`; `moved_from` names the release an edited claude issue named before.

## The issue contract

Each `update` finding has a stable key, its stream and a version, and a title built from that key alone:

| Stream | Key | Title |
| --- | --- | --- |
| `kimi` | the latest release's `<major>.<minor>` | `chore(backends): track kimi <major>.<minor>` |
| `claude` | the latest release's full version | `chore(backends): track claude <version>` |
| `fastmcp`, `mcp` | the latest release's `<major>.<minor>` | `chore(deps): track <package> <major>.<minor> past the cap` |

The kimi title follows the codex tracking issues' `chore(backends): track codex <major>.<minor>`.
Claude is keyed by full version because its baseline is a capture of one version, not a minor.

### kimi, fastmcp and mcp: one issue per minor

An issue is created only when no issue, open or closed, has exactly that title.
The check is two reads, and the title must match one of their rows character for character:

- `gh issue list --state all --search 'in:title "<title>"' --limit 1000 --json title,number,state`, which finds an issue of any age.
- `gh issue list --state all --limit 100 --json title,number,state`, the newest issues read directly, because GitHub's search index can lag an issue created moments ago.

The two reads are merged one row per issue number, the direct listing's row winning, because the search index can still report an issue as open after it was closed; only then are rows filtered by state.
Without `--limit`, `gh` returns 30 rows, so the search asks for 1000, and a search that returns 1000 rows may have been cut short: it fails closed, as a failed `gh` call, and nothing is filed for that stream.
So a re-run files nothing, and closing an issue retires its title for good: a declined minor does not come back.
A new minor has a new title and is filed once.

### claude: one rolling issue

Claude releases often, so its stream keeps one open issue that moves forward rather than one per release.
The open issues whose title starts with `chore(backends): track claude ` are read the same two ways, with `--state open` on the search.

- One is open and names an older release: `gh issue comment` notes the move, then `gh issue edit` moves its title and body to the latest release.
- One is open and names the latest release, or a newer one: nothing changes.
- None is open: a new issue is filed, unless a closed issue has exactly this release's title.
- More than one is open, or the open one's title does not end in a release: the stream fails closed, and no claude issue is filed, edited or commented on.

Releases are ordered by semver precedence, so a final release is newer than its own prereleases (`2.1.400-beta.1` moves to `2.1.400`) and `beta.10` is newer than `beta.2`.
The notice goes before the title change so that a run that stops between them leaves the old title, and the rerun completes the move.
The rerun reads the issue's comments with `gh issue view --json comments` first and posts the notice only if that exact text is not already there, so a completed move carries one notice.

Close the issue once a capture at or past its release is committed under `docs/claude-help/`.
Closing re-arms the watch: the next claude release past the newest capture opens a new issue.
An open issue is moved forward even when a closed issue already has the latest release's title.

Each issue is labelled `dependencies` and `chore`, both existing labels.
Its body says the release is available upstream, never that it is supported, because nothing was installed or run.
A claude issue's body also says that it rolls forward and that closing it re-arms the watch.

## Running it on a schedule

`.github/workflows/upstream-watch.yml` runs `watch --file-issues --json --repo <this repository>` from `main` daily at 15:30 UTC, and on demand with `gh workflow run upstream-watch.yml`.
It authenticates `gh` with the job's `GITHUB_TOKEN`, which is limited to `contents: read` and `issues: write`.
A `concurrency` group queues runs rather than overlapping them, so two runs never file at once.
The JSON is in the run log and the job summary.
A non-zero exit fails the run, so an `unknown` stream or a `failed` filing shows as a failed run, never as an up-to-date one.
Its first two dispatches, runs 40608709624 and 40608881778, filed #393, #394 and #395 and then reported each as `exists`, filing and editing nothing.
A Claude Code cloud routine was tried first and dropped, because the `gh` token a routine runs with cannot use the GitHub API.
`--dry-run` shows locally what a run would file or edit without changing anything; it still runs the `gh issue list` reads.
