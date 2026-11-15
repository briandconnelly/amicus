# ADR 0049: the plugin ships no slash commands

**Status:** Accepted (2026-11-14)

Supersedes the per-verb commands decision in [ADR 0012](0012-m6-packaging-decisions.md), which otherwise stands.

## Context

ADR 0012 gave the Claude Code plugin eight commands under `commands/amicus/`, one per verb with the backend as an argument, beside the `collaborating-with-amicus` skill.
The Codex plugin never had them: its manifest declares the skill and the server only.
Each command restated a summary of the skill's discovery and routing rules and named the skill's routing section without telling the model to load the skill.

Claude Code has since merged custom commands into skills.
Its documentation calls commands the older format and says skills supersede them for new work.
In practice a plugin's command is offered to the model as an invocable entry beside the plugin's skill.

Host runs on Claude Code 2.1.325 with Opus, recorded for issue #479, showed what that does.
In five runs with the plugin loaded as shipped, no run invoked the skill or read a file under it.
The two cold-start runs invoked `/amicus:consult` and the delegate run invoked `/amicus:delegate`, each through the Skill tool.
The delegate run met a host refusal and reported it without the annotation policy that `options-and-errors.md` asks for, because that file was never read.
The same requests were then run against a copy of the plugin with `commands/` removed and nothing else changed.
The cold-start run and three delegate runs all invoked the skill and read `active-workflows.md` before the paid call.
Two of the three delegate runs went on to read `options-and-errors.md` after the refusal and stated the annotation policy apart from the observed refusal; the third did neither.
A delegate request made for real against a stub backend read `reviewing-a-returned-diff.md` before the call and answered in its response contract.
One run on Codex CLI 0.169.0, which has no commands, loaded the skill and its required reading for the same delegate request.
Each count is of single runs on one model per host, graded by the agent that ran them.

Removing the commands does not make the skill load when no request triggers it.
A delegate result pasted into a prompt, with an instruction to apply it, loaded nothing in three runs of three with the commands gone, and each run tried to write the file.

## Decision

**The plugin ships the skill and no commands, on every host.**
`commands/` and the `commands` key in `.claude-plugin/plugin.json` are removed, with the test that held each paid verb to a command.
A packaging test now asserts that neither manifest declares commands.

**A user-invocable shortcut, if one is wanted later, is a skill that cannot be invoked by the model.**
It is not added here.
Whether a plugin command honours `disable-model-invocation` is not documented, and it was not tested.

## Consequences

Users of Claude Code lose `/amicus:consult` and its siblings and ask in their own words instead.
The plugin's behaviour on Claude Code and on Codex now comes from the same two surfaces, the skill and the server.
Every rule a command restated has one home again, in the skill.
An obligation that must hold when the skill is not loaded has to be carried by the server, in its instructions, a tool description or a result; that is a separate decision and is not made here.
