# beads workflows — design

**Status:** approved in discussion 2026-09-21, pending spec review
**Lives in:** agent-baseline (`baseline/.beads/formulas/`, `baseline/.beads/PRIME.md`, hooks); reaches repos via `apply.sh`.

## Goal

Route all non-trivial work through beads so the state of the work — steps,
questions, decisions, approvals, PR links, learnings — is persistent and
visible from any machine and any harness. Two formulas encode the loops that
are already used consistently: `feature` and `bugfix`. Humans gate at
approach, spec, merge and verification, and agents ask instead of assuming
at any point via `decision` beads.

## Non-goals (deferred until `feature` has run end to end)

Release-week wisp (node), smoke-matrix wisp (go), cross-repo linking of
backend/frontend halves, `bd swarm` / merge slots, thick formulas that
replace the superpowers skills.

## Principles

- **Thin formulas.** A step's description says *what* the step produces,
  which skill to use, and where to record the result on the bead. The
  skills (brainstorming, writing-plans, subagent-driven-development,
  requesting-code-review) own the how; they are installed in all three
  harnesses.
- **Beads are the state.** Approach in `--design`, spec/plan/PR paths in
  `--notes`, learnings in `bd remember`, questions as `decision` beads.
  If it is not on a bead it did not happen.
- **Ask, don't assume.** Any choice that changes behaviour, scope, cost or
  design becomes a `decision` bead that blocks the current step; the agent
  stops or moves to other ready work. Non-blocking "FYI I chose X" is a
  `--notes` line, no bead.

## The decision channel

```
bd create -t decision --labels human --title "<the question>" \
  --description "<context, options, my lean and why>" --parent <current bead>
bd dep add <current bead> <decision bead>        # current step is now blocked
# stop, or bd ready for other work

# human, any machine:
bd human list
bd human respond <decision id> "<answer>"        # comments + closes → step unblocks
```

`bd human list` selects on the `human` label, so decision beads and human
steps both carry it. Decisions are ordinary beads: synced
by `bd dolt push`, exported to the JSONL, visible to every later agent via
`bd show`.

## Formula: `feature` (poured, persistent)

`bd mol pour feature --var name=<slug> --var summary="<one sentence>"`

| id | title | type | needs | gate | description (thin) |
|---|---|---|---|---|---|
| `brainstorm` | Brainstorm {{name}} | task | — | — | Use brainstorming. Open questions → decision beads blocking this step. Record classification and chosen approach with `bd update --design`. |
| `approve-approach` | Approve approach for {{name}} | task, label `human` | brainstorm | — | Close when the design field on `brainstorm` is the approach you want. Comment changes instead of closing. |
| `spec` | Write spec for {{name}} | task | approve-approach | — | `docs/specs/<YYYY-MM-DD>-{{name}}-design.md`; path in `--notes`. Questions → decision beads. |
| `approve-spec` | Approve spec for {{name}} | task, label `human` | spec | — | Close when the spec is right. |
| `plan` | Write plan for {{name}} | task | approve-spec | — | Use writing-plans → `docs/plans/<date>-{{name}}.md`; path in `--notes`. Create one child bead per plan task under `implement` (`bd create --parent <implement id>`), with `bd dep add` between tasks that must be sequential. |
| `implement` | Implement {{name}} | epic | plan | — | Subagent-driven development over the children, TDD. Decisions → decision beads. Done when every child is closed. |
| `review-pr` | Review and open PR for {{name}} | task | implement | — | requesting-code-review; fix findings; `bd export --include-memories > .beads/issues.jsonl`; `bd dolt push`; `git push`; `gh pr create` → PR URL in `--notes`. |
| `merge` | Merge {{name}} | task | review-pr | `gh:pr` (created in review-pr), 168h | Human merges the PR. `bd gate check` (session start, or by hand) closes the gate. Step body: confirm merged, note merge SHA. |
| `verify` | Verify {{name}} in the real app | task, label `human` | merge | — | Check on staging/prod. Close with what you saw; reopen `implement` children or file bugs otherwise. |
| `wrap-up` | Wrap up {{name}} | task | verify | — | File follow-up beads for anything deferred, `bd remember` durable learnings, ensure docs updated, close the molecule root. |

Vars: `name` (required, pattern `^[a-z0-9][a-z0-9-]*$`), `summary` (required).
Steps are flat top-level `[[steps]]`; `bd mol pour` creates the molecule root
itself (type `molecule`, titled with the formula name). Every step carries
`labels = ["formula:feature"]`; human steps add `"human"`. The `gh:pr` gate is
created at `review-pr` time with `bd gate create --type=gh:pr --await-id <pr>
--blocks <merge id> --timeout 168h`, because the PR number is unknown at pour.

## Formula: `bugfix` (poured, persistent)

`bd mol pour bugfix --var bug=<bug bead id>`

| id | title | type | needs | gate | description |
|---|---|---|---|---|---|
| `reproduce` | Reproduce {{bug}} | task | — | — | Read `bd show {{bug}}`. Write the failing test that captures it (systematic-debugging). If it needs design: decision bead "this is a feature — pour `feature`?" |
| `fix` | Fix {{bug}} | task | reproduce | — | Minimal change that makes the test pass; TDD. |
| `review-pr` | Review and open PR for {{bug}} | task | fix | — | as in `feature` |
| `merge` | Merge fix for {{bug}} | task | review-pr | `gh:pr` (created in review-pr), 168h | as in `feature` |
| `verify` | Verify fix for {{bug}} | task, label `human` | merge | — | as in `feature` |
| `wrap-up` | Wrap up {{bug}} | task | verify | — | Close `{{bug}}` with `--reason` pointing at the PR; `bd remember` if the root cause generalises; close the molecule root. |

Vars: `bug` (required, pattern `^[a-z0-9-]+-[a-z0-9.]+$`).
Flat steps as in `feature`, labels `["formula:bugfix"]`. In `reproduce` the
agent runs `bd dep add {{bug}} <molecule root id>` so the bug shows as blocked
by its fix; `wrap-up` closes the bug.

## PRIME.md additions

Under **Core rules**:

- Decision rule (text above under Principles) with the four-line recipe.
- Pour by shape: architectural work → `bd mol pour feature …`; a bug bead →
  `bd mol pour bugfix --var bug=<id>`; a bounded change → one plain bead.
  `bd mol current` / `bd ready --mol <id>` to see where you are.
- Gates: `bd gate check` runs at session start; run it by hand after a
  merge to unblock the next step now. `bd human list` is the human queue.

Agents find work with `bd ready --exclude-label human`; they never claim a
`human`-labeled bead.

Under **Essential commands**: `bd ready --exclude-label human`, `bd mol current`, `bd human list|respond`,
`bd create -t decision --labels human`.

There is no `human` issue type (`bd types`); "human step" throughout means
`type = "task"` with `labels = ["human"]`, which is what `bd human list`
filters on.

## Hooks

Session-start command becomes `bd gate check >/dev/null 2>&1; bd prime --hook-json`:

- Claude Code: `render.py` `merge_settings` writes that command.
- Codex: `baseline/.codex/hooks.json` SessionStart entry edited to the same
  command (the one deliberate divergence from raw `bd setup codex` output;
  README's refresh step re-applies it).
- OpenCode: `opencode-beads` runs only `bd prime`; the PRIME.md rule covers
  it.

## Files

```
baseline/.beads/formulas/feature.formula.toml
baseline/.beads/formulas/bugfix.formula.toml
baseline/.beads/PRIME.md          (rules + commands added)
baseline/.codex/hooks.json        (session-start command)
render.py                         (session-start command)
test/formulas.sh                  (bd cook --dry-run both; assert human steps + gh:pr gate; skip if no bd)
README.md                         (formulas section; hooks.json divergence note)
```

`manifest` already owns `.beads/formulas/` (directory, replaced whole), so
`apply.sh` needs no change.

## Verification

- `test/formulas.sh` green; `apply.sh --self-test` and unit tests still green.
- In a scratch repo with `bd init`: `bd mol pour feature --var name=x --var summary=y`
  creates 1 root + 10 steps, `bd ready` shows only `brainstorm`, closing it
  shows nothing agent-ready and `bd human list` shows `approve-approach`.
- `bd gate list` shows the `gh:pr` gate blocking `merge`.
- Applied to both theostack repos: `bd formula list` shows both formulas;
  `bd prime` shows the new rules; `apply.sh --check` exits 0.
- Acceptance: the next architectural task in either repo is poured, and the
  first decision bead gets answered with `bd human respond`.
