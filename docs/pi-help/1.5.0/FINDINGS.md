# pi 1.5.0 — amicus evidence

Captured 2026-11-08 on the maintainer's machine by running the binary, for milestone M9 (issue #423).
No model call was made for this capture.

## The probe on issue #423

A zero-spend probe against a fake OpenAI-compatible provider verified each flag's effect on 1.5.0.
It included a negative control: without the flags, a hostile workspace's extension ran, its tools and system prompt were applied, and a session file was written to a path the workspace chose.
With `--no-session` and the resource-suppression flags, none of that happened.
The maintainer's decisions on that issue set the default model to `openrouter/moonshotai/kimi-k3`, make `AMICUS_PI_MODEL` the default that a call's `model` overrides, and refuse a call before spending when neither is set.

## What the captures show

- `pi-version.txt`: `1.5.0`.
- `pi-help.txt`: from `pi --help` with the resource-suppression flags, because pi builds its runtime and loads resources before it handles `--help`.
  Every long flag the amicus contract sends is advertised: `--mode`, `--no-session`, the eight suppression flags, `--system-prompt`, `--append-system-prompt`, `--tools`, `--model` and `--thinking`.
  The `--thinking` line lists `off`, `minimal`, `low`, `medium`, `high`, `xhigh` and `max`, the contract's effort vocabulary.
  The help text lists environment variable names only; it holds no credential value.
- `list-models-shape.txt`: the first four lines of `pi --list-models kimi-k3` with the suppression flags.
  It shows a header row and rows of `provider`, `model`, `context`, `max-out`, `thinking` and `images` columns.
  The `thinking` column is the `yes` or `no` that bounds the efforts a model accepts.
  Only the shape was kept, and it holds no credential, home path or provider URL.
- `tests/test_pi_contract.py` asserts the flags against `pi-help.txt` after first proving a known-absent control flag is not matched, and proves a copy of the capture with `--no-session` removed fails the check.

## What the `find` comparison showed

The file list under `~/.pi` was taken before and after the three captures, and the two lists were identical.
`find ~/.pi -newer <marker>` reported two entries, `~/.pi/agent` and `~/.pi/agent/install`, both directories.
Their modification times moved, which means an entry inside `install` was created or removed during the run.
No file was added, removed or listed as newer, and no session file appeared.
Which entry churned was not identified, so this is recorded as a concern: pi touches its own install directory even under the suppression flags.

## What was not tested

- `pi auth check --model <model> --json --no-refresh` was not run for this capture, so the shape of its output is inherited from the probe on #423.
- No run was made against a real provider, so the failure texts in the contract (`Model "<id>" not found`, a provider error that exits 0) come from the probe against the fake provider.
- Other pi minors were not checked; the contract supports `(1, 5)` only.
- Whether a project `sessionDir` setting is honoured under `--no-session` in a later release was not tested.

## Live gate outcome

Not yet run.
The live gate under rule 5 is run by the maintainer on the branch head.
