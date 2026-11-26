# Contributing to amicus

Thanks for helping. Bug reports, fixes and new ideas are all welcome.

## Reporting a bug

Open an issue at <https://github.com/briandconnelly/amicus/issues>. Include the error's `code`,
the `fingerprint` and `server_version` from `amicus_capabilities`, and the job id or request id
if you have one. The tracker is public, so leave out your prompts, the models' answers and
anything secret.

## Setting up

You need Python 3.11 or newer and [`uv`](https://docs.astral.sh/uv/).

```sh
uv sync
uv run prek install --prepare-hooks   # one-time local hooks
```

The hooks run checks locally on commit and push. The gate a change must pass, which CI runs on
every supported Python version, is defined once, as rule 2 in [`AGENTS.md`](AGENTS.md). Unit tests never
call a real backend CLI, so they spend no quota.

## Conventions

- Commit messages and PR titles follow [Conventional Commits](https://www.conventionalcommits.org/);
  `scripts/check_commit_message.py` lists the allowed types and scopes.
- Under `docs/`, Markdown is written one sentence per line.
- Decisions with lasting consequences are recorded as ADRs under `docs/adr/`.

[`AGENTS.md`](AGENTS.md) holds the full set of rules, written for coding agents but binding on
everyone working in the repository.

## Finding your way around

| Question | Read |
| --- | --- |
| What is being built and why | [`docs/superpowers/specs/2026-09-04-amicus-design.md`](docs/superpowers/specs/2026-09-04-amicus-design.md); for M8, [`docs/superpowers/specs/2026-09-15-amicus-M8-sdk-in-tree-design.md`](docs/superpowers/specs/2026-09-15-amicus-M8-sdk-in-tree-design.md) |
| How milestones are executed by agents | [`docs/superpowers/plans/2026-09-04-amicus-execution-model.md`](docs/superpowers/plans/2026-09-04-amicus-execution-model.md) |
| Architecture decisions | [`docs/adr/`](docs/adr/) |
| How a release is cut | [`docs/RELEASING.md`](docs/RELEASING.md) |
| How a new codex minor becomes supported | [`docs/UPGRADING-CODEX.md`](docs/UPGRADING-CODEX.md) |
| How new pi, claude, fastmcp and mcp releases become issues | [`docs/WATCHING.md`](docs/WATCHING.md) |
| How a `FINGERPRINT` bump regenerates its test pins | [`scripts/regenerate_fingerprint_pins.py`](scripts/regenerate_fingerprint_pins.py) (its docstring) |
| Every environment variable, its meaning and default | [`docs/CONFIGURATION.md`](docs/CONFIGURATION.md) |
| The router skill an agent loads to call amicus | [`skills/collaborating-with-amicus/`](skills/collaborating-with-amicus/) |
| Host captures and CLI evidence | [`docs/host-captures/`](docs/host-captures/), [`docs/claude-help/`](docs/claude-help/), [`docs/codex-help/`](docs/codex-help/), [`docs/kimi-help/`](docs/kimi-help/), [`docs/pi-help/`](docs/pi-help/) |
| How past milestones were built | git history; executed plans are removed once merged |
