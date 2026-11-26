# amicus

Give your coding agent a second opinion from a different model.

When you're about to commit to a design, stuck on a bug after two fixes, or about to call risky
work done, it helps to ask someone else. amicus lets the agent you're already working with ask
**Codex**, **Claude** or **Pi** (which reaches models from many providers) without leaving your
session. It is one [MCP](https://modelcontextprotocol.io) server: you pick the model per request,
rather than installing and learning a separate tool for each.

You can ask another model to:

- **Consult**: give a read-only second opinion on an approach, a bug or a design.
- **Review**: review your changes in git, with each finding tied to evidence.
- **Delegate**: implement a task in a throwaway git worktree and hand back a diff. amicus never
  applies it; you read it and decide.
- **Adversarial review**: attack a plan, claim or decision before you commit to it.

Long jobs can run in the background while you keep working.

## Install

You need macOS or Linux, Python 3.11 or newer, [`uv`](https://docs.astral.sh/uv/), and the CLI
for each model you want to use (`codex`, `claude`, `pi`), installed and logged in. amicus drives
those CLIs; it never talks to the providers itself and stores no credentials.

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

Start a new session afterwards. The plugin brings the server and a skill that teaches your agent
when and how to use it.

### Any other MCP client

Point your client at the same command the plugins use, pinned to a published release:

```json
{
  "mcpServers": {
    "amicus": {
      "command": "uvx",
      "args": ["--from", "git+https://github.com/briandconnelly/amicus.git@v0.17.0", "amicus-mcp"],
      "env": { "AMICUS_BACKENDS": "codex,claude" }
    }
  }
}
```

Set `AMICUS_BACKENDS` to the CLIs you have installed. Most clients take environment variables in
an `"env"` object like this one; check your client's documentation.

If your client doesn't pass a working directory, your first calls look like this:

1. Call `amicus_backends` with `detail: "full"` (free) to see which backends are installed and
   logged in, and what each one sends where.
2. Call `amicus_consult` with `backend`, `question` and an absolute `workspace_root`. Every paid
   tool needs `workspace_root` from such a client; the free discovery tools reject it.
3. If a result has `ok: false`, branch on `error.code`, and when `error.repair` is present,
   its `next_step` says what to do next.

Without the plugin you don't get its skill automatically. Set `AMICUS_SERVE_SKILL=1` (from
0.17.0) and the server offers the same skill over MCP. Claude Code loads MCP skills in public
beta from v2.1.331, though not in every setup ([ADR 0055](docs/adr/0055-the-server-serves-the-skill-only-where-the-plugin-cannot.md)
lists the exceptions); Codex can't load them yet.

## Try it

Ask in your own words:

- "Which amicus backends are installed and logged in?"
- "Get a second opinion on this approach from Codex."
- "Have Claude review my current changes."
- "Delegate this task to Codex and show me the diff."

Start with the first one. It's free, and it tells you which backends are set up before
anything is spent. A backend is the CLI amicus runs (`codex`, `claude` or `pi`); you choose a
model through it.

## What each backend can do

| | Codex | Claude | Pi |
| --- | --- | --- | --- |
| Consult, review | yes | yes | yes |
| Delegate | yes | no | yes |
| Adversarial review | no | yes | no |

These are amicus's choices, not limits of the models: Claude handles consults and reviews and has
no delegate tool, and the dedicated adversarial critic runs only on Claude. You can still ask Codex or Pi to argue against a
plan through an ordinary consult.

**Pi** has no default model, so name one per request as an exact `provider/id` (for example
`openrouter/moonshotai/kimi-k3`), or set `AMICUS_PI_MODEL`. Pi has its own setup details,
including provider keys and prepaid balances; see [`docs/PI.md`](docs/PI.md).

## What it costs, and where your data goes

- **Asking a model spends that model's quota or credit.** Discovery, previews and job management
  are free.
- **What you send goes through the CLI you picked, to the endpoint it's configured for.** A
  backend can also read files on your machine beyond the project you point it at and send them,
  so treat every call as sharing with that provider. Before your first paid call,
  `amicus_backends` with `detail: "full"` describes what each backend can send and how. On Pi,
  a `baseUrl` in its own config can change the endpoint; see
  [`docs/PI.md`](docs/PI.md#containment).
- **A delegated diff is never applied for you.** It comes back for you to review and apply
  yourself. That's a promise about the diff, not a sandbox: a Pi delegate runs shell commands
  with no sandbox. Enabling a backend that can write also changes the approval prompts your host
  shows; see [`docs/MIGRATION.md`](docs/MIGRATION.md).
- **Every paid call's full answer is saved on your machine**, after best-effort secret
  redaction, and it can quote what you sent; your inputs themselves are never written there.
  It's kept so a background job can be fetched later, until `amicus_job_consume_result` removes
  it, it expires (`AMICUS_JOB_TTL`, default 24 hours), or, once amicus has returned it, the
  per-workspace job cap evicts it to make room, so don't count on fetching a returned answer
  twice. A result nobody has fetched is never evicted; a new paid call is refused with
  `job_cap_reached` instead. An expired record is cleaned up on a later job call, so an idle
  server can hold it longer. A diff you export with
  `amicus_job_export_diff` is yours to delete. ADRs
  [0035](docs/adr/0035-a-backend-answer-is-kept-on-the-job-record.md),
  [0038](docs/adr/0038-the-job-cap-never-evicts-an-unreturned-result.md) and
  [0054](docs/adr/0054-a-delegates-diff-can-be-exported-to-a-path-the-caller-names.md) have the
  details.
- Codex, Claude and Pi run with their own session history turned off.

## Configuration

Most people set only `AMICUS_BACKENDS`, a comma-separated list of `codex`, `claude` and `pi`. If
you leave it unset, all three are enabled. Each backend also takes an optional model, reasoning
effort and binary path, and you can block requested model names with
[`AMICUS_DENY_MODELS`](docs/CONFIGURATION.md#amicus_deny_models). Every setting and its
default is in [`docs/CONFIGURATION.md`](docs/CONFIGURATION.md).

Logs go to stderr, and `AMICUS_LOG_FILE` also writes amicus's own log to a file. To lower the
risk of your prompts leaking into logs, the MCP libraries' messages are limited to warnings,
stripped of message content, and never written to that file.

## The tools

Your agent normally picks these for you. For reference, there are eighteen:

| Group | Tools |
| --- | --- |
| Discovery (free) | `amicus_backends`, `amicus_capabilities`, `amicus_models` |
| Ask a model (paid) | `amicus_consult`, `amicus_review_changes`, `amicus_delegate`, `amicus_adversarial_review` |
| Run in the background (paid) | the same four, each with an `_async` suffix |
| Preview (free) | `amicus_review_changes_dry_run`, `amicus_delegate_dry_run` |
| Jobs (free) | `amicus_job_status`, `amicus_job_result`, `amicus_job_consume_result`, `amicus_job_export_diff`, `amicus_job_list`, `amicus_job_cancel` |

`amicus_capabilities` lists every tool and error code; pass `detail: "full"` for each tool's
parameters.

## Coming from codex-in-claude, moonbridge, or claude-in-codex

amicus replaces all three. [`docs/MIGRATION.md`](docs/MIGRATION.md) maps the old tool names and
settings onto the new ones.

## Status and known limits

amicus 0.17.0 can serve the `collaborating-with-amicus` skill over the MCP skills extension
(`AMICUS_SERVE_SKILL=1`) for clients installed without the plugin. See
[`docs/MIGRATION.md`](docs/MIGRATION.md#upgrading-from-0160) for upgrade notes and
[`CHANGELOG.md`](CHANGELOG.md) for every user-visible change.

Known limits:

- A Pi delegate runs shell commands with no sandbox, and a command it leaves running in the
  background can outlive the run (#424).
- Backends from other packages can be installed but not yet enabled or called.

## Contributing

Bug reports and pull requests are welcome. [`CONTRIBUTING.md`](CONTRIBUTING.md) explains how to
set up a checkout, run the checks and find your way around the design docs.

## License

MIT. See [`LICENSE`](LICENSE).
