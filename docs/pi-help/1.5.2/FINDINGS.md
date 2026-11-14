# pi 1.5.2 — amicus evidence

Captured 2026-11-14 on the maintainer's machine by running the binary, to check the latest pi release against the 1.5.0 contract.
No model call was made for the captures; the live suite below did spend quota.

## What the captures show

- `pi-version.txt`: `1.5.2`.
- `pi-help.txt`: from `pi --help` with the resource-suppression flags, as for 1.5.0.
  Against `../1.5.0/pi-help.txt` it differs in one line: `pi auth` is now described as "Log in or out, print credentials, or check provider readiness".
  Every flag the amicus contract sends is still advertised with the same text, and the `--thinking` vocabulary is unchanged.
- `list-models-shape.txt`: the first four lines of `pi --list-models kimi-k3` with the suppression flags.
  The columns are unchanged; trailing whitespace was stripped.
- `pi auth --help` on 1.5.2 lists `pi auth login <provider>` and `pi auth logout <provider>`, which 1.5.0 lacked.
  amicus's login hint still names `/login` and the API-key variable, which work on both releases.

## The live suite

`tests/test_pi_live.py`, run as `AMICUS_REQUIRE_LIVE=1 AMICUS_PI_MODEL=openrouter/moonshotai/kimi-k3 uv run pytest -m integration --no-cov tests/test_pi_live.py`, passed all four tests on pi 1.5.2.
This is a compatibility check, not rule-20 release evidence.

## What was not tested

- The zero-spend probe on issue #423 was not repeated on 1.5.2, so the flags' effects are inferred from the unchanged help and the passing live suite.
- No `find` comparison of `~/.pi` was taken for this capture.
