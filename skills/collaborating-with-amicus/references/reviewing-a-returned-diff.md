# Reviewing a returned diff

`amicus_delegate` and `amicus_delegate_async` implement a task in a throwaway git worktree seeded
from the current branch's tracked state (`HEAD` plus replayable uncommitted tracked changes;
untracked files are never copied) and return the resulting `diff`. Delegation is available for
`codex` and `kimi` in v1; Claude stays review-only.

## The diff is never applied

amicus does not touch your working tree. The `diff` field in the result is a proposal, not a
change that already happened. Never run `git apply`, patch, or otherwise merge it into your tree
before you have reviewed it.

## What to check before applying

1. **Does it do what the task asked, and nothing more?** Read the diff against the original task
   text. Delegate runs have no network egress — an install, a remote git operation, `gh`, or a
   publish step cannot have happened inside the run, so a diff that references one is suspicious.
2. **Does it touch files outside the intended scope?** A delegate task should be self-contained;
   a diff that edits unrelated files is a sign the task was under-specified or the model
   over-reached.
3. **Does it compile / pass checks?** The delegate result is an unverified claim like any other
   amicus result — `summary` and `findings` describe what the backend did, not proof that it
   works. Apply the diff to a disposable branch or worktree and run this project's actual checks
   before merging it into real work.
4. **Is the diff internally consistent?** Check `diffstat` against the diff itself for a sanity
   check on scope before reading line by line.

## Applying it

Once you've reviewed the diff and are satisfied it is correct and in scope, apply it yourself
(e.g. `git apply`, or hand it to your own patch-application tooling) to your actual working tree.
amicus's job is done at "returned diff" — it does not offer an apply step, by design, so that a bad
or unwanted diff never touches your tree without a human or agent decision in between.
