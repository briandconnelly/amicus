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
