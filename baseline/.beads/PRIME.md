# Beads Workflow Context

> Run `bd prime` after compaction, clear, or a new session. Hooks do this automatically in Claude Code, Codex and OpenCode.

## Policy: team-maintainer, PR-only

Agents **may**: create/claim/close beads, commit on a **feature branch**, `bd dolt push`, `git push` that branch, open a PR.
Agents **may not**: commit to or merge into `main`/`dev`, merge PRs, force-push, delete branches. Merging is a human decision, always.

## Where issue state lives — read before your first `bd` command

- The Dolt database in `.beads/embeddeddolt/` (gitignored, shared by every worktree of this clone) is the source of truth.
- `bd dolt push` / `bd dolt pull` sync it to `refs/dolt/data` on the git remote (`sync.remote` in `.beads/config.yaml`). A custom ref, not a branch: no CI, no branch protection, invisible to `git branch`. Fresh machine: `bd bootstrap`. Takes minutes with no progress output.
- `.beads/issues.jsonl` is a tracked **export** for diffs and viewers, not the sync channel.
- **JSONL ahead of Dolt is the dangerous direction.** If the checked-out JSONL may be newer than Dolt (a hand-off from a session whose `bd dolt push` failed, or you just checked out someone else's branch), run `bd import .beads/issues.jsonl` **before any other `bd` command**. bd's periodic backup piggybacks on any `bd` invocation and overwrites the file with Dolt's older view.
- Export with a redirect, never `-o`: `bd export --include-memories > .beads/issues.jsonl`. `-o` silently drops memories.
- `bd dolt push` holds the embedded-Dolt lock; a concurrent `bd` write (including the pre-commit hook's export in any worktree) blocks it. If bd hangs, `pgrep -af bd` before assuming a crash.
- `bd doctor` is unsupported in embedded mode; use `bd doctor --check=conventions`.

## Core rules

- Use beads for ALL task tracking. No TodoWrite, TaskCreate, or markdown TODO lists.
- Create or claim a bead BEFORE writing code: `bd update <id> --claim`.
- `bd remember "insight"` for durable knowledge; `bd memories <keyword>` to search. No MEMORY.md files.
- Epic rollup notes go stale: `bd show` the member issue before acting on what an epic says about it.
- Never `bd edit` (opens $EDITOR and blocks).

## Session close protocol — run before saying "done"

```
[ ] bd close <ids> --reason "..."                    # or bd update <id> --notes for partial work
[ ] bd create ... for follow-up work you discovered
[ ] quality gates                                    # AGENTS.md → Build & Test
[ ] bd export --include-memories > .beads/issues.jsonl
[ ] git add -A && git commit                         # feature branch; include the JSONL
[ ] bd dolt push
[ ] git push -u origin <branch>
[ ] gh pr create                                     # target branch: AGENTS.md → Git
[ ] hand off: PR link + what is left
```

If `bd dolt push` fails (HTTP 403 in remote sessions), say so in the hand-off: the committed JSONL is then the only channel and the next machine must `bd import` first.

## Essential commands

```bash
bd ready                         # unblocked work
bd show <id>                     # details + deps
bd update <id> --claim           # claim (atomic)
bd create --title="..." --description="why + what" -t task|bug|feature|chore|epic -p 0-4 [--parent=<id>]
bd update <id> --notes="..." | --design="..." | --status=...
bd close <id...> --reason="..."
bd dep add <issue> <depends-on>  # issue is blocked by depends-on
bd blocked | bd stale | bd orphans | bd preflight
bd search <query> | bd list --status=open --label=<l>
bd human <id>                    # flag a decision for a human
bd formula list | bd mol pour <formula> --var k=v   # structured workflows
bd gate list | bd gate resolve <id>                  # async waits (human, timer, gh:pr)
bd todo add "..." | bd todo | bd todo done <id>      # scratch tasks
```
