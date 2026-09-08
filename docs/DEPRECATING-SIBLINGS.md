# Deprecating the sibling servers

Every step below is the maintainer's to run by hand, in the sibling repositories themselves, because AGENTS.md rule 17 forbids any agent from editing a sibling checkout.
No agent executes this checklist; it exists so the maintainer does not have to reconstruct the steps from memory.

## Ordering constraint

Do not run any step in this checklist before amicus is actually published to `pypi.org`.
As of 2026-09-08, `https://pypi.org/pypi/amicus/json` returns 404; amicus has been published to TestPyPI only, not to pypi.org.
Every step below points a user at the `amicus` package or its README, so running it early sends users to a package that does not exist yet.

## The three siblings

amicus replaces `codex-in-claude`, `moonbridge`, and `claude-in-codex`.
It does not replace `pontonier`: that repository is the shared backend SDK amicus depends on (`pontonier==0.9.0` in `pyproject.toml`), and it is not deprecated.

All three siblings are live on PyPI today: `codex-in-claude` (latest `0.22.0`), `moonbridge` (latest `0.16.0`), and `claude-in-codex` (latest `0.9.0`), confirmed by `GET https://pypi.org/pypi/<name>/json` returning HTTP 200 for each on 2026-09-08.

### `codex-in-claude`

1. Add a deprecation notice to the top of `README.md`, above the badges, pointing at `amicus` and at `docs/MIGRATION.md`'s "From `codex-in-claude`" section.
2. Decide the PyPI action: `codex-in-claude`'s classifiers currently declare `Development Status :: 4 - Beta` (`pyproject.toml`).
   Change that classifier to `Development Status :: 7 - Inactive` and publish a final release so the change reaches PyPI; do not yank any existing release, because yanking would break every pinned install (the `.mcp.json` in this repo pins `codex-in-claude==0.22.0`, and the plugin marketplace launches from that exact pin).
3. Update the plugin-marketplace listing: `.claude-plugin/marketplace.json` and `.claude-plugin/plugin.json` both describe the plugin as "Call OpenAI Codex from Claude Code for delegation, review, and second opinions."
   Either archive the repository (which leaves the marketplace entry installable but frozen) or update both descriptions to say the plugin is deprecated in favor of amicus.
4. Update the "Related projects" section of `README.md` (currently lines 336-340), which cross-links `claude-in-codex`; point that link at amicus's repository instead, or note there that both mirror-image servers are superseded by amicus.
5. Point users at amicus's install instructions and at `docs/MIGRATION.md`'s "From `codex-in-claude`" section for the tool-name and environment-variable mapping.

### `moonbridge`

1. Add a deprecation notice to the top of `README.md` (above its own badge and "Why Moonbridge?" section), pointing at `amicus` and at `docs/MIGRATION.md`'s "From `moonbridge`" section.
2. Decide the PyPI action: `moonbridge`'s classifiers currently declare `Development Status :: 4 - Beta` (`pyproject.toml`, local checkout).
   The locally checked-out `pyproject.toml` shows version `0.3.0`, but `pypi.org/pypi/moonbridge/json` reports the latest published release as `0.16.0` — the local checkout is behind whatever is on `origin/main`; reconcile that before editing anything, and confirm the current classifier on the actual latest release rather than trusting the local file.
   Change the classifier to `Development Status :: 7 - Inactive` and publish a final release; do not yank existing releases, because the `.mcp.json` in this repo pins a release tag (`git+https://github.com/briandconnelly/moonbridge.git@v0.3.0`) and the marketplace launches from that pin.
3. Moonbridge has two plugin-marketplace listings, unlike the other two siblings: `.claude-plugin/marketplace.json` for Claude Code and `.agents/plugins/marketplace.json` for Codex.
   Update or archive both, not just one.
4. Point users at amicus's install instructions and at `docs/MIGRATION.md`'s "From `moonbridge`" section.

### `claude-in-codex`

1. Add a deprecation notice to the top of `README.md`, above the badges, pointing at `amicus` and at `docs/MIGRATION.md`'s "From `claude-in-codex`" section.
2. Decide the PyPI action: `claude-in-codex`'s classifiers currently declare `Development Status :: 3 - Alpha` (`pyproject.toml`), one stage earlier than the other two siblings.
   Change the classifier to `Development Status :: 7 - Inactive` and publish a final release; do not yank existing releases, because both `.mcp.json` (root) and `plugins/claude-in-codex/.mcp.json` pin the release tag `git+https://github.com/briandconnelly/claude-in-codex.git@v0.9.0`.
3. `claude-in-codex` has no `.claude-plugin/` directory; it is a Codex-only plugin, listed at `.agents/plugins/marketplace.json`.
   Update or archive that single listing; there is no separate Claude Code marketplace entry to touch.
4. Point users at amicus's install instructions and at `docs/MIGRATION.md`'s "From `claude-in-codex`" section.
   Note that `claude-in-codex` is Codex-only and review-only (Claude never gets write tools); amicus's Claude backend is also review-only today, so this mapping needs no behavior caveat beyond what `docs/MIGRATION.md` already states.

## Pinned references that would break

`pontonier`'s own release process depends on all three siblings staying checked out and runnable: `docs/releasing.md` (in the `pontonier` checkout) runs `scripts/check_consumers.sh` against `../codex-in-claude`, `../moonbridge`, and `../claude-in-codex` as a compatibility gate before every pontonier release.
Archiving or gutting any of the three sibling checkouts will break that script; update `pontonier`'s release runbook (a change to the `pontonier` repository, out of scope for amicus) before or alongside this deprecation, so a future pontonier release does not stall on missing consumers.

`pontonier`'s own `README.md` and `pyproject.toml` describe the three siblings as its consumers by name; update those references once the siblings are archived, so pontonier's own documentation does not point at dead projects.

Each sibling's `.mcp.json` pins an exact version (`codex-in-claude==0.22.0`) or an exact git tag (`moonbridge@v0.3.0`, `claude-in-codex@v0.9.0`).
Anyone who installed a sibling's plugin before this deprecation keeps working from that pin; the deprecation notice and classifier change do not by themselves break an existing installation, so there is no urgency to yank.

## Where users are pointed instead

Point every sibling's README, marketplace listing, and cross-link at the `amicus` package on PyPI and at this repository's `docs/MIGRATION.md`, which already maps each sibling's tools and environment variables to their amicus equivalents.
Do this only after amicus's `pypi.org` listing exists, per the ordering constraint above.
