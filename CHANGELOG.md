# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- One MCP server for three second-opinion backends — `codex`, `kimi` and `claude` — with the backend as a tool parameter rather than a separate server (M0–M4).
- Synchronous verbs: `amicus_consult`, `amicus_review_changes`, `amicus_delegate`, `amicus_adversarial_review`, and their dry-run twins.
- Discovery surface: `amicus_backends`, `amicus_capabilities`, `amicus_models`, and the MCP resources that back them.
- A jobs surface: `_async` twins of the paid verbs, `amicus_job_status`, `amicus_job_result`, `amicus_job_consume_result`, `amicus_job_list`, `amicus_job_cancel`, with idempotency keys, restart survival and task-id lookup (M2).
- `task=True` on the four paid synchronous tools behind the `AMICUS_TASKS` flag (M5).
- Packaging for both hosts: a `.claude-plugin/` manifest, a `.codex-plugin/` manifest, an `amicus-mcp` console script, and the `collaborating-with-amicus` skill (M6).
- Release automation: a tag- and dispatch-triggered publish workflow with trusted publishing to TestPyPI and PyPI.

### Known limitations

- The tagged publish path to pypi.org has never run. Only the TestPyPI dispatch path has been exercised.
- Eval scenario S6 in `skills/collaborating-with-amicus/tests/scenarios.md` has one validated pass, with a tool-surface-pinning follow-up carried to M7; S7 (real-host approval friction) failed its one recorded run. See their `status` fields and ADR 0012.

[Unreleased]: https://github.com/briandconnelly/amicus/commits/main
