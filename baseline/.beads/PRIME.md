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
- **Ask, don't assume.** Any choice that changes behaviour, scope, cost or design is a `decision` bead
  that blocks your current step - then stop, or take other ready work. Non-blocking "FYI I chose X" is a
  `--notes` line. Recipe:
  ```
  bd create -t decision --labels human --parent <current> --title "<question>" --description "<context, options, my lean>"
  bd dep add <current> <decision id>
  ```
  The human answers with `bd human respond <id> "..."`, which closes it and unblocks you.
- **Pour by shape.** Architectural work: `bd mol pour feature --var name=<slug> --var summary="..."`.
  A bug bead: `bd mol pour bugfix --var bug=<id>`. A bounded change: one plain bead, no formula.
  `bd mol current` shows where you are; `bd ready --exclude-label human` is how agents find work -
  never claim a bead labeled `human`, those are the human's steps.
- **Gates.** `bd gate check` runs at session start; run it by hand after a merge to unblock the next step now.
- **Worktrees.** Work in a worktree you created, branched from `origin/<base>` (`git worktree add ../<repo>-<slug> -b <branch> origin/<base>`),
  never from the current HEAD: a stale checkout produces a stale worktree with none of this. Never `git checkout`/`switch`
  in a checkout you did not create - another session may be working in it.

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
bd ready --exclude-label human   # unblocked agent work (human-labeled beads are the human's)
bd mol current                   # where am I in the current molecule
bd human list | bd human respond <id> "..."   # the human's queue; answering closes the bead
bd create -t decision --labels human --parent <id> --title "..." --description "..."   # ask, don't assume
bd show <id>                     # details + deps
bd update <id> --claim           # claim (atomic)
bd create --title="..." --description="why + what" -t task|bug|feature|chore|epic -p 0-4 [--parent=<id>]
bd update <id> --notes="..." | --design="..." | --status=...
bd close <id...> --reason="..."
bd dep add <issue> <depends-on>  # issue is blocked by depends-on
bd blocked | bd stale | bd orphans | bd preflight
bd search <query> | bd list --status=open --label=<l>
bd human <id>                    # flag a decision for a human
bd formula list | bd mol pour feature|bugfix --var k=v   # structured workflows (see Pour by shape)
bd gate list | bd gate resolve <id>                  # async waits (human, timer, gh:pr)
bd todo add "..." | bd todo | bd todo done <id>      # scratch tasks
```
