"""The backend SDK amicus's backends are built on.

Copied in M8 from pontonier v0.9.0 (commit 185b16cd7a3c7cb86b07f2a8ca58d1527372aa1d,
https://github.com/briandconnelly/pontonier), which amicus no longer depends on; ADR 0029
records why. ADR 0030 keeps here what a backend imports and moves what only the server uses
to the amicus package that owns it. Four layers: ``amicus.sdk.core`` (the subprocess
runtime, stream capping, redaction, path-alias sanitizing and a bounded JSON reader),
``amicus.sdk.backend`` (the backend protocol and contract, FROZEN at
``CONTRACT_API_VERSION = 1``: required members are stable, and new behavior lands as
defaulted fields or optional capability protocols), ``amicus.sdk.conventions`` (error
vocabulary, annotations, preflight) and ``amicus.sdk.testing`` (the conformance kit a
plugin must pass before the registry will use it). ``amicus.sdk.core`` never imports the
other three.
"""
