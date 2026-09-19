# kimi-code 0.43.1 — amicus evidence

Captured 2026-09-15 on the maintainer's machine by running the binary (`kimi --version`, `kimi --help`, `kimi provider list --json`), the same three probes as `docs/kimi-help/0.42.0/`.
No model call was made for this capture.
It was made because the maintainer's CLI moved to 0.43.1 before the 0.42 support in PR #110 merged, and the kimi live gate requires the newest supported minor.

## What the captures show

- `kimi-version.txt`: `0.43.1`.
- `kimi-help.txt`: every flag the amicus contract sends (`--prompt`, `--output-format`, `--agent-file`, `--model`, `--skills-dir`) and every flag it refuses (`--add-dir`, `-y/--yolo`, `--auto`, `--plan`, `-S/--session`, `-c/--continue`) is still advertised.
  The only difference from the 0.42.0 capture is an `[options]` placeholder on the `upgrade|update` subcommand, which amicus never invokes.
  The raw output ends with one more blank line than the earlier captures; it was trimmed so this file ends the way they do.
  `tests/test_kimi_contract.py` asserts the flags against this file and every other capture under `docs/kimi-help/`, after first proving a known-absent control flag is not matched.
- `provider-list-shape.json`: byte-identical to the 0.42.0 capture, an object with `models` and `providers` maps whose model entry carries `supportEfforts` (the shape `models.parse_catalog` reads).
  Only key names were captured; provider details (API keys, base URLs) were never written to disk.

## What is inherited, not re-verified here

The behavioural findings carried from moonbridge's 0.39.1 probes, listed in `docs/kimi-help/0.41.0/FINDINGS.md`, were not re-run as standalone probes on 0.43.1.

## Session persistence (#179, probed 2026-09-19 at zero spend)

The kimi CLI writes session files of its own, which can hold the whole prompt and any answer produced, to its session store, `~/.kimi-code/sessions/wd_<workdir>_<hash>/session_<uuid>/`, holding `state.json`, `logs/kimi-code.log`, `agents/main/file-history` and `agents/main/wire.jsonl`.
A `wire.jsonl` written on 2026-09-17 under a `wd_amicus-wt-*` directory, which is the name of an amicus delegate worktree, holds four `"role": "user"` records and two `"role": "assistant"` records.
Its contents were counted, not copied here, because rule 18 binds them.
That is one completed run; a failed or cancelled run was not observed, so nothing here says what such a run leaves behind.

No suppression mechanism was found, and the claim is scoped to what was looked at:

- `kimi --help` offers `-S/--session`, `-c/--continue`, `export`, `fork`, `vis` and `session`, and nothing that turns a session off.
- `kimi session --help` offers `list` only, so the CLI has no delete of its own either.
- The binary's strings were searched for `ephemeral`, `noSession`, `no-session`, `skipPersist`, `disablePersist`, `persistSession`, `sessionPersist` and `incognito`, after first confirming the search finds a string known to be there (`resume_hint`, six hits).
  The only product hits were UI labels and `persistSessionProfile`, which saves a session's plan and permission mode rather than gating the transcript.
- `KIMI_LOG_SESSION_FILES` reads as a switch and is not one: the binary parses it as the count of rotated session log files, default 3.
- `KIMI_CODE_HOME` and `KIMI_SHARE_DIR` appear as names only.
  What they move was not tested, since a run that creates a session spends quota, and the home directory also holds `config.toml` and the login state.

So this establishes that no documented or observed switch exists in 0.43.1, not that none exists.

amicus discloses the store rather than deleting it.
The session id reaches amicus only in the stream's last event, so a cancelled or killed run never yields one; the store's layout is undocumented, and whether `KIMI_CODE_HOME` or anything else moves it is untested, so amicus cannot be sure where a given run's session is; and the same tree holds the operator's own interactive sessions.
A cleanup that works only on the happy path would make the disclosure less true, not more.
Relocating the store per run stays open, and needs a probe against a local mock provider showing that one variable moves sessions without moving configuration or login state.

## Live gate outcome

Run once (2026-09-15, at the maintainer's request under rule 5 of `AGENTS.md`) on the PR branch at `d6a701c`, against the maintainer's real kimi 0.43.1:

```
AMICUS_REQUIRE_LIVE=1 uv run pytest -m integration --no-cov tests/test_kimi_live.py -v
```

All 6 tests passed in 55.85s.

- `test_backends_reports_kimi_ready_live` PASSED — the installed version matched the newest supported minor, `(0, 43)`, and `amicus_backends` reported no warnings.
- `test_consult_outside_a_repo_live`, `test_read_only_profile_is_enforced_live`, `test_review_changes_live`, `test_delegate_live` and `test_unknown_model_alias_is_invalid_model_live` PASSED.

This run is not rule-20 release evidence.
That evidence is recorded by `scripts/record_live_gate_evidence.py` against the release commit itself, and that record, not this file, is where the release run's outcome lives.
