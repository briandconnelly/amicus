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

(filled in by Task 9)
