# kimi-code 0.41.0 — amicus M3 evidence

Captured 2026-09-06 on the maintainer's machine by running the binary (`kimi --version`, `kimi --help`, `kimi provider list --json`).
No model call was made for this capture.

## What the captures show

- `kimi-version.txt`: `0.41.0`.
- `kimi-help.txt`: every flag the amicus contract sends (`--prompt`, `--output-format`, `--agent-file`, `--model`, `--skills-dir`) and every flag it refuses (`--add-dir`, `-y/--yolo`, `--auto`, `--plan`, `-S/--session`, `-c/--continue`) is still advertised.
  `tests/test_kimi_contract.py` asserts this against the file, after first proving a known-absent control flag is not matched.
- `provider-list-shape.json`: the payload is an object with `models` and `providers` maps; a model entry carries `supportEfforts` (the shape `models.parse_catalog` reads).
  Only key names were captured; provider details (API keys, base URLs) were never written to disk.

## What is inherited, not re-verified here

The behavioural findings in moonbridge's `docs/kimi-help/0.39.1/M0-FINDINGS.md` (the read-only `--agent-file` profile removes Bash and Write; a worktree does not contain kimi; an unrecognized `KIMI_MODEL_THINKING_EFFORT` is silently ignored; a SIGKILLed run leaves orphaned Bash children; the argv ceiling near 950k chars) are carried into the amicus contract unchanged.
They were not re-run as standalone probes on 0.41.0.
The live gate (`tests/test_kimi_live.py`, run once in this milestone) re-checks the one guarantee it can observe from the answer: a read-only consult asked to list its tools names no Bash, Write or Edit tool.
Its outcome is recorded below after the run.

## Live gate outcome

Run once (2026-09-06, per Task 9), against the maintainer's real kimi 0.41.0 with one configured provider (`runpod`, model `moonshotai/Kimi-K3`):

```
AMICUS_REQUIRE_LIVE=1 uv run pytest -m integration --no-cov tests/test_kimi_live.py -v
```

All 6 tests passed in 109.78s.

- `test_backends_reports_kimi_ready_live` PASSED — `amicus_backends` reported `available=True`, `installed=True`, `authenticated=True`, a `version` starting `0.41`, and no warnings; `amicus_models` reported `source="live"` with a non-empty model list.
- `test_consult_outside_a_repo_live` PASSED — a consult with `workspace_root` outside a git repo succeeded with `ok=True`, a non-empty summary, a session id, a job id, and `meta.security_warnings == [NO_REPO_WARNING]`.
- `test_read_only_profile_is_enforced_live` PASSED — asked to list its exact tool names, the model's reply, split and lowercased, excluded `bash`, `write`, `edit`, `shell` and included at least one of `read`, `glob`, `grep`.
  The test asserts only on the parsed name set and did not print the raw reply, and no failure occurred, so the assertion's own pass is the only evidence this run produced: the literal comma-separated list the model returned was not captured to a log, and a second live call to capture it verbatim was not made, since the maintainer authorized exactly one live run for this milestone.
- `test_review_changes_live` PASSED — `amicus_review_changes` returned `ok=True`, `review_status="completed"`, a verdict in the allowed set, and `meta.context_summary.files_changed == 1`.
- `test_delegate_live` PASSED — `amicus_delegate` returned `ok=True` with a non-empty diff, left the working-tree file unchanged, and left no worktree registered afterward.
- `test_unknown_model_alias_is_invalid_model_live` PASSED — kimi was spawned with the unknown model alias.
  kimi itself rejected the alias before making any model call.
  amicus classified kimi's rejection as `error.code == "invalid_model"`.
  There is no amicus-side pre-spend gate for `model`; the live catalog is authoritative only for what `amicus_models` lists, and ADR 0009 decision 3's pre-spend gate covers `reasoning_effort`, not `model`.

No failure envelope was produced; the release-blocker and model-quality-retry procedures were not triggered.
