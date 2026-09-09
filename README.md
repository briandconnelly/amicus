# amicus

Give your coding agent a second opinion from a different model.

amicus is one MCP server that fronts **Codex**, **Kimi** and **Claude**. The backend is a
parameter, not a separate installation — so instead of running three servers and learning three
tool surfaces, you ask for a consult, a review, or a delegated task and say which model should
answer.

- **Consult** — a read-only second opinion on an approach, a bug, or a design.
- **Review** — a structured review of changes gathered from git, with findings tied to evidence.
- **Delegate** — a task implemented in a throwaway git worktree, returned as a diff you review.
  It is never applied to your working tree.
- **Adversarial review** — a fixed critic aimed at a plan, claim, or decision.

Long-running calls can be started in the background and polled, so a broad review does not block
your session.

## Install

### Claude Code

```text
/plugin marketplace add briandconnelly/amicus
/plugin install amicus@amicus
```

### Codex

```sh
codex plugin marketplace add briandconnelly/amicus
codex plugin add amicus@amicus
```

Start a new session afterwards so the host loads the bundled skill and tools.

### Any other MCP client

The plugins launch the server from a published release tag, pinned in
[`.mcp.json`](.mcp.json). Point your client at the same command:

```json
{
  "mcpServers": {
    "amicus": {
      "command": "uvx",
      "args": ["--from", "git+https://github.com/briandconnelly/amicus.git@v0.1.0", "amicus-mcp"]
    }
  }
}
```

### Requirements

- Python 3.11 or newer, and [`uv`](https://docs.astral.sh/uv/).
- The CLI for each backend you enable, installed and authenticated: `codex`, `kimi`, `claude`.
  amicus drives those CLIs; it does not talk to the providers itself, and it stores no credentials.

## Using it

Choose which backends are available with `AMICUS_BACKENDS` — a comma-separated list of `codex`,
`kimi` and `claude`. Only the backends you name are enabled.

Then just ask, in your own words:

- "Get a second opinion on this approach from another model."
- "Have another model review my current changes."
- "Delegate this task to another model and show me the proposed diff."

In Claude Code there are also slash commands:

| Command | What it does |
| --- | --- |
| `/amicus:consult` | Ask another model for a read-only second opinion |
| `/amicus:review` | Have another model review your git changes |
| `/amicus:delegate` | Delegate a coding task; get back a reviewable diff |
| `/amicus:adversarial` | Run a fixed adversarial critic against a plan, claim, or decision |
| `/amicus:dry-run` | Preview what a review or delegate call would send — free, no model call |
| `/amicus:jobs` | Poll, fetch, list, or cancel a background job |
| `/amicus:status` | Check which backends are enabled, installed, and authenticated |

Start with `/amicus:status` — it tells you which backends are actually usable before you spend
anything.

## The tools

Eighteen tools, in five groups. Everything paid has a free way to inspect it first.

| Group | Tools |
| --- | --- |
| Discovery — free | `amicus_backends`, `amicus_capabilities`, `amicus_models` |
| Verbs — paid | `amicus_consult`, `amicus_review_changes`, `amicus_delegate`, `amicus_adversarial_review` |
| Previews — free | `amicus_dry_run` (review), `amicus_delegate_dry_run` |
| Background twins — paid | the four verbs again, each with an `_async` suffix |
| Jobs — free | `amicus_job_status`, `amicus_job_result`, `amicus_job_consume_result`, `amicus_job_list`, `amicus_job_cancel` |

Not every backend does everything:

| Verb | Codex | Kimi | Claude |
| --- | --- | --- | --- |
| `consult`, `review_changes` | yes | yes | yes |
| `delegate` | yes | yes | no |
| `adversarial_review` | no | no | yes |

Asking a backend for something it does not support returns a `feature_unsupported` error naming
the backend and the feature, rather than failing obscurely.

## Safety

- **A delegated diff is never applied.** It runs in a throwaway git worktree and comes back for
  you to read and apply yourself.
- **Every verb call spends the selected backend's quota.** The dry runs and the discovery and job
  tools do not.
- **Enabling a backend that can write** makes the tool surface carry that backend's approval
  annotations — see [`docs/MIGRATION.md`](docs/MIGRATION.md).
- **Your prompts go to whichever provider you selected**, through that provider's own CLI. Each
  backend discloses how it carries your text — visible on `amicus_backends`.

## Configuration

`AMICUS_BACKENDS` is the one most people set. Beyond it, each backend takes an optional model,
reasoning effort, and binary path (`AMICUS_CODEX_MODEL`, `AMICUS_KIMI_REASONING_EFFORT`,
`AMICUS_CLAUDE_BIN`, and so on), and there are limits for timeouts, job retention and payload
sizes. The full list is the `env_vars` array in [`.mcp.json`](.mcp.json).

## Coming from codex-in-claude, moonbridge, or claude-in-codex

amicus replaces all three. [`docs/MIGRATION.md`](docs/MIGRATION.md) maps the old tool names onto
the new ones.

## Status and known limits

0.1.0 is the first release. The server's wire contract is exercised by the test suite and by host
captures against Claude Code and Codex, but:

- 0.1.0 is the first release published from a tag, so the tagged publish path runs for the first
  time with it.
- Two router-skill evaluation scenarios are unresolved — S6 (diff-safety wording) and S7 (approval
  friction) — recorded in [`docs/adr/0012-m6-packaging-decisions.md`](docs/adr/0012-m6-packaging-decisions.md).
  Neither is a defect in the server's wire contract.
- A third-party backend distribution loads through the `amicus.backends` entry-point group, but
  cannot yet be enabled or called: `AMICUS_BACKENDS` and the `backend` parameter accept only the
  in-tree ids.

## Development

```sh
uv sync
uv run prek install --prepare-hooks   # one-time local hooks
```

The gate is defined once, in `AGENTS.md` (Rules, item 2); CI runs it on every supported Python
version.

| Question | Read |
| --- | --- |
| What is being built and why | `docs/superpowers/specs/2026-09-04-amicus-design.md` |
| How milestones are executed by agents | `docs/superpowers/plans/2026-09-04-amicus-execution-model.md` |
| Architecture decisions | `docs/adr/` |
| How a release is cut | `docs/RELEASING.md` |
| Deprecating the sibling projects | `docs/DEPRECATING-SIBLINGS.md` |
| The router skill an agent loads to call amicus | `skills/collaborating-with-amicus/` |
| Host captures and CLI evidence | `docs/host-captures/`, `docs/claude-help/`, `docs/kimi-help/` |
| How past milestones were built | git history — executed plans are removed once merged |

## License

MIT. See [`LICENSE`](LICENSE).
