"""The backend SDK amicus's backends are built on, and the lifecycle they run under.

Copied in M8 from pontonier v0.9.0 (commit 185b16cd7a3c7cb86b07f2a8ca58d1527372aa1d,
https://github.com/briandconnelly/pontonier), which amicus no longer depends on; ADR 0029
records why. Four layers: ``amicus.sdk.core`` (jobs, idempotency, worktrees, diff
gathering, redaction, the subprocess runtime, workspace resolution), ``amicus.sdk.backend``
(the backend protocol and contract, FROZEN at ``CONTRACT_API_VERSION = 1``: required members
are stable, and new behavior lands as defaulted fields or optional capability protocols),
``amicus.sdk.conventions`` (error vocabulary, annotations, fingerprint, preflight, prompt
framings) and ``amicus.sdk.testing`` (the conformance kit, which the registry runs on every
plugin it loads). ``amicus.sdk.core`` never imports the other three.
"""
