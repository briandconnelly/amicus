# kimi-code 0.42.0 — amicus evidence

Captured 2026-09-15 on the maintainer's machine by running the binary (`kimi --version`, `kimi --help`, `kimi provider list --json`), the same three probes as `docs/kimi-help/0.41.0/`.
No model call was made for this capture.
It was made because the 0.3.0 release evidence run failed on kimi 0.42.0 (issue #109).

## What the captures show

- `kimi-version.txt`: `0.42.0`.
- `kimi-help.txt`: every flag the amicus contract sends (`--prompt`, `--output-format`, `--agent-file`, `--model`, `--skills-dir`) and every flag it refuses (`--add-dir`, `-y/--yolo`, `--auto`, `--plan`, `-S/--session`, `-c/--continue`) is still advertised.
  The only difference from the 0.41.0 capture is a new `rc|remote` subcommand, which amicus never invokes.
  `tests/test_kimi_contract.py` asserts the flags against this file, after first proving a known-absent control flag is not matched.
- `provider-list-shape.json`: identical to the 0.41.0 capture, an object with `models` and `providers` maps whose model entry carries `supportEfforts` (the shape `models.parse_catalog` reads).
  Only key names were captured; provider details (API keys, base URLs) were never written to disk.

## What is inherited, not re-verified here

The behavioural findings carried from moonbridge's 0.39.1 probes, listed in `docs/kimi-help/0.41.0/FINDINGS.md`, were not re-run as standalone probes on 0.42.0.

## Live gate outcome

The 0.3.0 evidence run on 2026-09-15 (release commit `f349ef1`, before this change) ran `tests/test_kimi_live.py` against kimi 0.42.0.
Five of its six tests passed: consult outside a repo, the read-only profile check, `amicus_review_changes`, `amicus_delegate`, and the unknown-model rejection.
The sixth, `test_backends_reports_kimi_ready_live`, failed only on the version pin and the drift warning that 0.42 was outside `SUPPORTED_VERSIONS`, which this capture resolves.
The full live gate was never re-run on 0.42.0: the maintainer's CLI moved to 0.43.1 before this capture merged, so the 0.3.0 release evidence runs on 0.43.1 instead (see `docs/kimi-help/0.43.1/`).
