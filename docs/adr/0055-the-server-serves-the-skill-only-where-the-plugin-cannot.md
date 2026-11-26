# ADR 0055: the server serves the skill only where the plugin cannot

**Status:** Accepted (2026-11-25)

Amends the packaging in [ADR 0012](0012-m6-packaging-decisions.md) and [ADR 0049](0049-the-plugin-ships-no-slash-commands.md), which otherwise stand.

## Context

The `collaborating-with-amicus` skill reaches a host only through the plugin, which ships it from `skills/` on Claude Code and on Codex.
An install made with `claude mcp add`, or through README's "Any other MCP client" example, gets the server and no skill.

The MCP extension `io.modelcontextprotocol/skills` (SEP-2640, protocol revision 2026-07-28) lets a server serve skills over the Resources primitive, through `skills/list`, `skills/get` and `resources/read`.
A host fetches a skill's body only when the skill is selected, and pins approval to a `sha256` digest of each file, so any change to the skill revokes approval.
FastMCP 4.2 implements the extension, and amicus already requires `fastmcp>=4.1.4,<4.3`.

Claude Code supports the extension in public beta from v2.1.331, and names a served skill `<server>:<skill>`; from the plugin's server it would be `plugin_amicus_amicus:collaborating-with-amicus`.
It does not load served skills under `claude -p`, the Agent SDK, cloud sessions, GitHub Actions, API-key or Console login, a custom `ANTHROPIC_BASE_URL` or `apiKeyHelper`, cloud-provider connections, or HIPAA and zero-data-retention settings.
It leaves them off for Team and Enterprise organizations until an admin enables them, and requires a recent model.
It caps a skill at 100 KB per text file and 400 KB in all.
In manual and `acceptEdits` modes it asks for approval again whenever a skill's files change, and an allow rule cannot pre-approve a plugin's server.

Codex does not support the extension.
The community implementations list for `ext-skills`, read on 2026-11-25, marks "ChatGPT and Codex" as `planned`, and notes that skill import at plugin submission was rolled back in November 2026; the official client matrix has no Codex row.

The skill's own fallback, `references/server-down-fallback.md`, is for a server that is down, which is exactly when a served skill cannot be read.

The shipped skill is `SKILL.md` and `references/`, about 135 KB, with no file over 22 KB.
`tests/scenarios.md` is 152 KB and is not part of what a host needs.

## Decision

**The plugin keeps shipping the skill from `skills/`, on both hosts.**
It remains the carrier for every install made through a plugin.

**The server serves the same skill over `io.modelcontextprotocol/skills` only when `AMICUS_SERVE_SKILL=1`.**
It serves `SKILL.md` and `references/` from the package, and never `tests/`.
README's "Any other MCP client" section tells a user without the plugin to set it.

**A plugin's server never serves the skill, whatever its environment holds.**
Leaving the variable unset in the plugin's `.mcp.json` is not enough: a host can hand the server an inherited environment, and `env_vars_list()` in `src/amicus/packaging.py` passes every declared `AMICUS_*` name through.
So the plugin's `.mcp.json` launches the server with an argv flag that turns serving off and outranks the variable, and a packaging test asserts that both manifests' server entries carry it.
The flag is `--no-serve-skill`; any other argument is ignored, as releases up to 0.16.0 ignored every argument.

**The served files are the files the plugin ships.**
A test asserts that every served file is byte-identical to its copy under `skills/collaborating-with-amicus/`, and that the served set fits the Claude Code limits above.

**The served skill is outside the fingerprint.**
The default surface, with the variable unset, is unchanged, so every fingerprint and `surface_digest` pin stays the baseline and `FINGERPRINT_COVERS` gains nothing.
An app with the skill enabled has its own live `surface_digest`, because the skill's resources are among the records it hashes; no test pins that digest, and focused tests check only that it differs from the default and that the served resource URIs and file bytes match the plugin's copy.

## Consequences

An install made without the plugin can get the skill on Claude Code, inside the limits listed above.
The skill becomes a second copy inside the wheel, held to the plugin's copy by a test rather than by one path.
The host-capture evidence behind ADRs 0016, 0048 and 0049 covers the plugin skill only; the served skill's triggering is unmeasured until it is captured.
A user who opts in under manual approval re-approves the skill after every release that changes it.
Replacing the plugin's copy with the served one is not decided here; it is revisited when the extension leaves beta on Claude Code and Codex supports it.
