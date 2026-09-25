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
      "args": ["--from", "git+https://github.com/briandconnelly/amicus.git@v0.6.0", "amicus-mcp"]
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
| `/amicus:delegate-async` | Delegate a long coding task in the background; get a job id to poll with `/amicus:jobs` |
| `/amicus:adversarial` | Run a fixed adversarial critic against a plan, claim, or decision |
| `/amicus:dry-run` | Preview what a review or delegate call would send — free, no model call |
| `/amicus:jobs` | Poll, fetch, list, or cancel a background job |
| `/amicus:status` | Check which backends are enabled, installed, and authenticated |

Start with `/amicus:status` — it tells you which backends are actually usable before you spend
anything.

## The tools

Eighteen tools, in five groups. Discovery, previews and job
management are free; the verbs and their background twins invoke the selected backend and spend
its quota.

| Group | Tools |
| --- | --- |
| Discovery — free | `amicus_backends`, `amicus_capabilities`, `amicus_models` |
| Verbs — paid | `amicus_consult`, `amicus_review_changes`, `amicus_delegate`, `amicus_adversarial_review` |
| Previews — free | `amicus_review_changes_dry_run` (review), `amicus_delegate_dry_run` |
| Background twins — paid | the four verbs again, each with an `_async` suffix |
| Jobs — free | `amicus_job_status`, `amicus_job_result`, `amicus_job_consume_result`, `amicus_job_list`, `amicus_job_cancel` |

Not every backend does everything:

| Verb | Codex | Kimi | Claude |
| --- | --- | --- | --- |
| `consult`, `review_changes` | yes | yes | yes |
| `delegate` | yes | yes | no |
| `adversarial_review` | no | no | yes |

A `no` is amicus's routing policy, not a model limitation. Claude is review-only, and the
dedicated adversarial-review verb is scoped to Claude. To ask Codex or Kimi for an adversarial
review, use `consult` or `review_changes` and supply the stance yourself; the dedicated verb adds
a fixed critic stance and the `target` and `evidence` inputs.

Asking a tool for a backend outside its `backend` enum, in-tree or not, is rejected before any
spend as an `invalid_arguments` error whose `details.allowed_values` lists the backends that tool
accepts (the enum is that set). `feature_unsupported` is only a defensive check: it is returned
if the named backend's declared features lack the verb, which no backend a tool's enum accepts
does today.

## Safety

- **A delegated diff is never applied.** It runs in a throwaway git worktree and comes back for
  you to read and apply yourself.
- **Every verb call spends the selected backend's quota.** The dry runs and the discovery and job
  tools do not.
- **Enabling a backend that can write** makes the tool surface carry that backend's approval
  annotations — see [`docs/MIGRATION.md`](docs/MIGRATION.md).
- **Your prompts go to whichever provider you selected**, through that provider's own CLI. Each
  backend discloses how it carries your text — visible on `amicus_backends`.
- **A paid call's whole answer stays on disk** in the job record under `AMICUS_STATE_DIR`,
  whatever `detail` delivered it and after only best-effort secret redaction, until it expires
  (`AMICUS_JOB_TTL`, default 24h; an expired record is removed on a later job call, not by a
  daemon), `amicus_job_consume_result` removes it or, once amicus has returned it, the
  per-workspace cap evicts it. The cap never evicts a result nobody has fetched that was
  recorded since delivery tracking (#244), whichever release recorded it. When only running jobs
  and such results remain, a new paid call is refused with `job_cap_reached` instead ([ADR 0038](docs/adr/0038-the-job-cap-never-evicts-an-unreturned-result.md)). It can
  quote what you sent. Your inputs themselves are never written there ([ADR 0035](docs/adr/0035-a-backend-answer-is-kept-on-the-job-record.md)).
- **Kimi keeps its own copy.** The kimi CLI writes its own session files (observed under
  `~/.kimi-code/sessions`), which can hold the whole prompt and any answer produced. amicus found
  no documented way to switch that off and does not delete them, and none of the retention controls above reach it; Codex and Claude
  run with their session persistence disabled.

## Configuration

`AMICUS_BACKENDS` is the one most people set. Beyond it, each backend takes an optional model,
reasoning effort, and binary path (`AMICUS_CODEX_MODEL`, `AMICUS_KIMI_REASONING_EFFORT`,
`AMICUS_CLAUDE_BIN`, and so on), and there are limits for timeouts, job retention and payload
sizes. The full list is the `env_vars` array in [`.mcp.json`](.mcp.json).

Logging goes to stderr, and `AMICUS_LOG_FILE` mirrors amicus's own records to a file. To reduce
the risk of prompt text leaking through dependency logs, `fastmcp` and `mcp` records are limited
to WARNING or higher on stderr, reduced to non-message diagnostics, and never written to that
file (ADR 0023).

## Coming from codex-in-claude, moonbridge, or claude-in-codex

amicus replaces all three. [`docs/MIGRATION.md`](docs/MIGRATION.md) maps the old tool names onto
the new ones.

## Status and known limits

0.6.0 is the current release. The discovery surface moved from `amicus/0.1/schema-39` to
`amicus/0.1/schema-43`, and `RESULT_FORMAT` did not move, so a job result 0.5.0 stored can still be
read. Two changes ask something of a caller: `amicus_job_consume_result` now deletes a failed,
cancelled or timed-out job's record and reports `state_changed` where it reported `not_done`, and
an answer the output capture cut is `answer_unavailable` rather than a shorter or earlier answer.
One change asks something of an operator: a `CODEX_HOME` that is not an absolute path is now
refused. [`docs/MIGRATION.md`](docs/MIGRATION.md#upgrading-from-050) explains how to upgrade, and
[`CHANGELOG.md`](CHANGELOG.md) lists every user-visible change.

One known limit: a third-party backend distribution can load through the `amicus.backends`
entry-point group, but cannot yet be enabled or called. `AMICUS_BACKENDS` and the `backend`
parameter accept only the three in-tree ids.

## Development

```sh
uv sync
uv run prek install --prepare-hooks   # one-time local hooks
```

The gate is defined once, in `AGENTS.md` (Rules, item 2); CI runs it on every supported Python
version.

| Question | Read |
| --- | --- |
| What is being built and why | `docs/superpowers/specs/2026-09-04-amicus-design.md`; for M8, `docs/superpowers/specs/2026-09-15-amicus-M8-sdk-in-tree-design.md` |
| How milestones are executed by agents | `docs/superpowers/plans/2026-09-04-amicus-execution-model.md` |
| Architecture decisions | `docs/adr/` |
| How a release is cut | `docs/RELEASING.md` |
| Deprecating the sibling projects | `docs/DEPRECATING-SIBLINGS.md` |
| The router skill an agent loads to call amicus | `skills/collaborating-with-amicus/` |
| Host captures and CLI evidence | `docs/host-captures/`, `docs/claude-help/`, `docs/kimi-help/` |
| How past milestones were built | git history — executed plans are removed once merged |

## License

MIT. See [`LICENSE`](LICENSE).
