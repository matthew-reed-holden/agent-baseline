# beads workflows Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the `feature` and `bugfix` beads formulas, the decision-bead rule, and the session-start gate check through agent-baseline into both theostack repos.

**Architecture:** Two thin TOML formulas under `baseline/.beads/formulas/` (owned; `apply.sh` overwrites). PRIME.md carries the rules that make agents route work through them. Session-start hooks prepend `bd gate check`. A shell test pours both formulas into a scratch beads repo and asserts the human/agent split.

**Tech Stack:** bd 1.3.0 (formulas, gates, `bd human`), bash, python3 stdlib.

**Spec:** `docs/specs/2026-09-21-beads-workflows-design.md`

## Global Constraints

- No `human` issue type exists: human steps are `type = "task"` (default) with `labels = ["human"]`; decision beads are `-t decision --labels human`.
- `bd mol pour` creates the molecule root itself; formulas use flat `[[steps]]`, no root step.
- The `gh:pr` gate is created at `review-pr` time (`bd gate create --type=gh:pr --await-id <pr> --blocks <merge id> --timeout 168h`), never statically.
- Session-start command everywhere it is expressible: `bd gate check >/dev/null 2>&1; <existing command>`.
- Commit messages end with `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`.
- Work in `~/code/agent-baseline` on `main` (unpublished-to-others repo; PRs are for the theostack repos only).

---

### Task 1: Formulas + scratch-repo test

**Files:**
- Create: `test/formulas.sh`, `baseline/.beads/formulas/feature.formula.toml`, `baseline/.beads/formulas/bugfix.formula.toml`
- Delete: `baseline/.beads/formulas/.gitkeep`
- Modify: `manifest` (`.beads/formulas/.gitkeep` line → `.beads/formulas` directory)

**Interfaces:**
- Produces: formulas named `feature` (vars `name`, `summary`) and `bugfix` (var `bug`), step ids as in the spec tables; `test/formulas.sh` exit 0 = pass, exit 0 with "skipping" when `bd` is absent.

- [ ] **Step 1: Write the failing test**

```bash
#!/usr/bin/env bash
# Pours both formulas into a scratch beads repo and asserts the human/agent split.
set -euo pipefail
here=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
command -v bd >/dev/null || { echo "formulas.sh: bd not installed, skipping"; exit 0; }
tmp=$(mktemp -d); trap 'rm -rf "$tmp"' EXIT
cd "$tmp" && git init -q && bd init --non-interactive >/dev/null 2>&1
mkdir -p .beads/formulas && cp "$here"/baseline/.beads/formulas/*.formula.toml .beads/formulas/

id() { python3 -c 'import json,sys;print(json.load(sys.stdin)["id_mapping"][sys.argv[1]])' "$1"; }
titles() { python3 -c 'import json,sys;print("\n".join(sorted(i["title"] for i in json.load(sys.stdin))))'; }
fail() { echo "formulas.sh: FAIL: $*" >&2; exit 1; }

# ---- feature ---------------------------------------------------------------------
pour=$(bd mol pour feature --var name=demo --var summary="a demo" --json 2>/dev/null)
brainstorm=$(echo "$pour" | id feature.brainstorm); merge=$(echo "$pour" | id feature.merge)
review=$(echo "$pour" | id feature.review-pr)
[[ $(bd ready --exclude-label human --json | titles) == "Brainstorm demo" ]] || fail "only brainstorm should be ready: $(bd ready --json | titles)"
bd close "$brainstorm" >/dev/null
[[ -z $(bd ready --exclude-label human --json | titles) ]] || fail "nothing agent-ready after brainstorm: $(bd ready --exclude-label human --json | titles)"
bd human list 2>/dev/null | grep -q "Approve approach for demo" || fail "approve-approach not in bd human list"
bd close "$(echo "$pour" | id feature.approve-approach)" "$(echo "$pour" | id feature.spec)" "$(echo "$pour" | id feature.approve-spec)" "$(echo "$pour" | id feature.plan)" "$(echo "$pour" | id feature.implement)" >/dev/null
bd gate create --type=gh:pr --await-id 1 --timeout 168h --blocks "$merge" >/dev/null
bd close "$review" >/dev/null
bd ready --exclude-label human --json | titles | grep -q "Merge demo" && fail "merge must be blocked by the gh:pr gate"
bd gate list 2>/dev/null | grep -qi "gh:pr" || fail "gh:pr gate missing from bd gate list"

# ---- bugfix -----------------------------------------------------------------------
bug=$(bd create --title "It breaks" -t bug -p 1 --json 2>/dev/null | python3 -c 'import json,sys;print(json.load(sys.stdin)["id"])')
pour=$(bd mol pour bugfix --var bug="$bug" --json 2>/dev/null)
[[ $(bd ready --exclude-label human --json | titles | grep -c "Reproduce $bug") == 1 ]] || fail "reproduce not ready"
bd close "$(echo "$pour" | id bugfix.reproduce)" "$(echo "$pour" | id bugfix.fix)" "$(echo "$pour" | id bugfix.review-pr)" "$(echo "$pour" | id bugfix.merge)" >/dev/null
bd human list 2>/dev/null | grep -q "Verify fix for $bug" || fail "verify not in bd human list"

echo "formulas.sh: ok"
```

- [ ] **Step 2: Run it to see it fail**

Run: `cd ~/code/agent-baseline && chmod +x test/formulas.sh && ./test/formulas.sh`
Expected: non-zero, `bd mol pour` complaining the formula `feature` is not found (the `id` helper then fails on empty JSON).

- [ ] **Step 3: Write `baseline/.beads/formulas/feature.formula.toml`**

```toml
formula = "feature"
description = "Feature loop: brainstorm > approve > spec > approve > plan > implement > review+PR > merge (gh:pr gate) > verify > wrap up"
version = 1
type = "workflow"

[vars.name]
description = "Short slug for the feature; used in titles and doc filenames"
required = true
pattern = "^[a-z0-9][a-z0-9-]*$"

[vars.summary]
description = "One sentence: what the feature does, for whom"
required = true

[[steps]]
id = "brainstorm"
title = "Brainstorm {{name}}"
labels = ["formula:feature"]
description = """
{{summary}}

Use the brainstorming skill: explore the repo, ask one question at a time, propose 2-3 approaches with a recommendation.
Every question that needs a human decision becomes a decision bead blocking this step
(`bd create -t decision --labels human --parent <this id> --title "..." --description "context, options, my lean"` then
`bd dep add <this id> <decision id>`); then stop or take other ready work. Never assume.
Done: `bd update <this id> --design "<classification + chosen approach>"`, then close. The approval step becomes visible to the human.
"""

[[steps]]
id = "approve-approach"
title = "Approve approach for {{name}}"
labels = ["formula:feature", "human"]
needs = ["brainstorm"]
description = """
Human: `bd show <brainstorm id>` and read the design field. Close this bead to approve.
To ask for changes: comment here and `bd reopen` the brainstorm step instead of closing.
"""

[[steps]]
id = "spec"
title = "Write spec for {{name}}"
labels = ["formula:feature"]
needs = ["approve-approach"]
description = """
Write docs/specs/<YYYY-MM-DD>-{{name}}-design.md from the approved approach: goal, non-goals, architecture,
components, data flow, error handling, testing. Self-review for placeholders, contradictions, ambiguity.
Commit on the feature branch. `bd update <this id> --notes "spec: <path>"`. Questions -> decision beads. Close.
"""

[[steps]]
id = "approve-spec"
title = "Approve spec for {{name}}"
labels = ["formula:feature", "human"]
needs = ["spec"]
description = """
Human: review the spec at the path in the spec step's notes. Close to approve; comment and reopen `spec` for changes.
"""

[[steps]]
id = "plan"
title = "Write plan for {{name}}"
labels = ["formula:feature"]
needs = ["approve-spec"]
description = """
Use the writing-plans skill -> docs/plans/<YYYY-MM-DD>-{{name}}.md; commit; `bd update <this id> --notes "plan: <path>"`.
Create one bead per plan task as a child of the implement step:
`bd create --title "Task N: <name>" --description "<what it builds + how to verify>" -t task --parent <implement id>`
and `bd dep add <later task> <earlier task>` wherever order matters. Close this step.
"""

[[steps]]
id = "implement"
title = "Implement {{name}}"
type = "epic"
labels = ["formula:feature"]
needs = ["plan"]
description = """
Work the children of this epic (`bd ready --exclude-label human`), via subagent-driven development or inline; TDD; one commit per task.
Decisions -> decision beads. Close each child as it lands. Close this epic when every child is closed.
"""

[[steps]]
id = "review-pr"
title = "Review and open PR for {{name}}"
labels = ["formula:feature"]
needs = ["implement"]
description = """
1. requesting-code-review against the spec and plan; fix what it finds.
2. Quality gates from AGENTS.md -> Build & Test.
3. `bd export --include-memories > .beads/issues.jsonl`; commit; `bd dolt push`; `git push -u origin <branch>`.
4. `gh pr create` (target branch: AGENTS.md -> Git). `bd update <this id> --notes "pr: <url>"`.
5. `bd gate create --type=gh:pr --await-id <pr number> --timeout 168h --blocks <merge step id>`.
Close this step.
"""

[[steps]]
id = "merge"
title = "Merge {{name}}"
labels = ["formula:feature"]
needs = ["review-pr"]
description = """
Blocked by the gh:pr gate until a human merges the PR; `bd gate check` (session start, or by hand) resolves it.
Then confirm (`gh pr view <n> --json state,mergeCommit`), `bd update <this id> --notes "merged: <sha>"`, close.
"""

[[steps]]
id = "verify"
title = "Verify {{name}} in the real app"
labels = ["formula:feature", "human"]
needs = ["merge"]
description = """
Human: check the feature where it runs (staging/prod). Close with a comment on what you saw.
If it is wrong: `bd create -t bug ...` (or reopen implement children) and leave this open.
"""

[[steps]]
id = "wrap-up"
title = "Wrap up {{name}}"
labels = ["formula:feature"]
needs = ["verify"]
description = """
File follow-up beads for anything deferred (`--parent` / `bd dep add` as appropriate). `bd remember` anything durable learned.
Confirm docs (architecture.md, runbooks) reflect the change. `bd export --include-memories > .beads/issues.jsonl`; commit;
`bd dolt push`; push. Close this step, then the molecule root (`bd mol current`).
"""
```

- [ ] **Step 4: Write `baseline/.beads/formulas/bugfix.formula.toml`**

```toml
formula = "bugfix"
description = "Bug loop: reproduce (failing test) > fix > review+PR > merge (gh:pr gate) > verify > wrap up"
version = 1
type = "workflow"

[vars.bug]
description = "The bug bead this molecule fixes, e.g. theostack-go-3yxo"
required = true
pattern = "^[A-Za-z0-9_.-]+$"

[[steps]]
id = "reproduce"
title = "Reproduce {{bug}}"
labels = ["formula:bugfix"]
description = """
`bd show {{bug}}`. Link the bug to this molecule: `bd dep add {{bug}} <molecule root id>` (`bd mol current` shows the root).
Use systematic-debugging: write the failing test that captures the bug; commit it on a branch.
If the fix needs design, file a decision bead ("this is a feature - pour `feature`?") blocking this step and stop.
`bd update <this id> --notes "repro: <test path>"`. Close.
"""

[[steps]]
id = "fix"
title = "Fix {{bug}}"
labels = ["formula:bugfix"]
needs = ["reproduce"]
description = """
Minimal change that makes the failing test pass (TDD). Behaviour/scope choices -> decision beads. Close.
"""

[[steps]]
id = "review-pr"
title = "Review and open PR for {{bug}}"
labels = ["formula:bugfix"]
needs = ["fix"]
description = """
1. requesting-code-review; fix what it finds. 2. Quality gates from AGENTS.md -> Build & Test.
3. `bd export --include-memories > .beads/issues.jsonl`; commit; `bd dolt push`; `git push -u origin <branch>`.
4. `gh pr create` (target: AGENTS.md -> Git); `bd update <this id> --notes "pr: <url>"`.
5. `bd gate create --type=gh:pr --await-id <pr number> --timeout 168h --blocks <merge step id>`. Close.
"""

[[steps]]
id = "merge"
title = "Merge fix for {{bug}}"
labels = ["formula:bugfix"]
needs = ["review-pr"]
description = """
Blocked by the gh:pr gate until a human merges. After `bd gate check` resolves it: confirm with `gh pr view`, note the SHA, close.
"""

[[steps]]
id = "verify"
title = "Verify fix for {{bug}}"
labels = ["formula:bugfix", "human"]
needs = ["merge"]
description = """
Human: confirm the bug is gone where it was reported. Close with what you saw; if not fixed, comment and reopen `fix`.
"""

[[steps]]
id = "wrap-up"
title = "Wrap up {{bug}}"
labels = ["formula:bugfix"]
needs = ["verify"]
description = """
`bd close {{bug}} --reason "fixed in <pr url>"`. `bd remember` if the root cause generalises.
`bd export --include-memories > .beads/issues.jsonl`; commit; `bd dolt push`; push. Close this step, then the molecule root.
"""
```

- [ ] **Step 5: Manifest: own the directory, drop the placeholder**

```bash
cd ~/code/agent-baseline
git rm -q baseline/.beads/formulas/.gitkeep
sed -i 's|^\.beads/formulas/\.gitkeep    owned|.beads/formulas             owned|' manifest
grep -n formulas manifest
```
Expected: `.beads/formulas             owned`.

- [ ] **Step 6: Run the test**

Run: `./test/formulas.sh`
Expected: `formulas.sh: ok`. If `bd mol pour` warns about unregistered types, that means a `type = "human"` slipped in — there must be none.

- [ ] **Step 7: Self-test still passes (formulas dir is now owned as a directory)**

Run: `./apply.sh --self-test`
Expected: `selftest: ok` — the assertion on `.beads/formulas/.gitkeep` fails now; change that line in `test/selftest.py` to
`assert (tmp / ".beads" / "formulas" / "feature.formula.toml").exists()` and rerun.

- [ ] **Step 8: Commit**

```bash
git add -A && git commit -m "feat: feature and bugfix formulas with scratch-repo test

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 2: PRIME.md rules, session-start gate check, README

**Files:**
- Modify: `baseline/.beads/PRIME.md`, `baseline/.codex/hooks.json`, `render.py`, `test/test_render.py`, `test/selftest.py`, `README.md`

**Interfaces:**
- Produces: session-start commands `bd gate check >/dev/null 2>&1; bd prime --hook-json` (Claude, written by `merge_settings`) and `bd gate check >/dev/null 2>&1; bd codex-hook SessionStart` (Codex, vendored file).

- [ ] **Step 1: Update the unit test and self-test expectations**

In `test/test_render.py`, `Settings.test_merge_preserves_foreign_keys`, change the hook assertion to:
```python
            self.assertEqual(s["hooks"]["SessionStart"][0]["hooks"][0]["command"], "bd gate check >/dev/null 2>&1; bd prime --hook-json")
```
In `test/selftest.py`, change the matching assertion to the same string.

Run: `python3 -m unittest 2>&1 | tail -1` → `FAILED (failures=1)`.

- [ ] **Step 2: `render.py` — the new command**

Replace in `merge_settings`:
```python
        {"matcher": "", "hooks": [{"type": "command", "command": "bd gate check >/dev/null 2>&1; bd prime --hook-json"}]}
```
Run: `python3 -m unittest 2>&1 | tail -1` → `OK`.

- [ ] **Step 3: Codex hooks.json**

```bash
cd ~/code/agent-baseline && python3 - <<'EOF'
import json
p='baseline/.codex/hooks.json'; d=json.load(open(p))
h=d['hooks']['SessionStart'][0]['hooks'][0]
assert h['command']=='bd codex-hook SessionStart', h
h['command']='bd gate check >/dev/null 2>&1; bd codex-hook SessionStart'
json.dump(d,open(p,'w'),indent=2); open(p,'a').write('\n')
EOF
grep -n 'gate check' baseline/.codex/hooks.json
```
Expected: one line.

- [ ] **Step 4: PRIME.md**

Apply with python (exact anchors):
```bash
cd ~/code/agent-baseline && python3 - <<'EOF'
p='baseline/.beads/PRIME.md'; t=open(p).read()
old="""- Epic rollup notes go stale: `bd show` the member issue before acting on what an epic says about it.
- Never `bd edit` (opens $EDITOR and blocks).
"""
new="""- Epic rollup notes go stale: `bd show` the member issue before acting on what an epic says about it.
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
"""
assert old in t; t=t.replace(old,new)
old2="""bd ready                         # unblocked work
"""
new2="""bd ready --exclude-label human   # unblocked agent work (human-labeled beads are the human's)
bd mol current                   # where am I in the current molecule
bd human list | bd human respond <id> "..."   # the human's queue; answering closes the bead
bd create -t decision --labels human --parent <id> --title "..." --description "..."   # ask, don't assume
"""
assert old2 in t; t=t.replace(old2,new2)
old3="bd formula list | bd mol pour <formula> --var k=v   # structured workflows\n"
new3="bd formula list | bd mol pour feature|bugfix --var k=v   # structured workflows (see Pour by shape)\n"
assert old3 in t; t=t.replace(old3,new3)
open(p,'w').write(t)
EOF
grep -c 'decision' baseline/.beads/PRIME.md
```
Expected: `4` or more.

- [ ] **Step 5: README — formulas section + hooks note**

Append after the "## Edit the source, not the output" section:
```markdown
## Workflows

`baseline/.beads/formulas/` ships two formulas, owned (re-applied on every
apply): `feature` (brainstorm → **approve** → spec → **approve** → plan →
implement → review+PR → merge via `gh:pr` gate → **verify** → wrap up) and
`bugfix` (reproduce → fix → review+PR → merge → **verify** → wrap up). Bold
steps carry the `human` label: `bd human list` is the human's queue, and
agents find work with `bd ready --exclude-label human`. Questions become
`decision` beads that block the step (`bd human respond` answers them).
Rules live in `.beads/PRIME.md`; `test/formulas.sh` pours both into a scratch
repo.

Session start runs `bd gate check` before `bd prime` in Claude Code and
Codex — `baseline/.codex/hooks.json` differs from raw `bd setup codex` output
by exactly that prefix; re-apply it when refreshing the vendored file.
```
And in "Maintain the template", add `./test/formulas.sh` to the first bullet.

- [ ] **Step 6: Everything green, commit**

Run: `python3 -m unittest 2>&1 | tail -1 && ./apply.sh --self-test && ./test/formulas.sh`
Expected: `OK`, `selftest: ok`, `formulas.sh: ok`.

```bash
git add -A && git commit -m "feat: decision rule, pour-by-shape, session-start gate check

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
git push
```

---

### Task 3: Roll out to both theostack repos

**Files:** generated/owned files in each repo via `apply.sh`; no hand edits.

- [ ] **Step 1: Worktrees on fresh branches**

```bash
cd ~/code/theostack && export SSH_AUTH_SOCK=~/.1password/agent.sock
git -C theostack-go fetch -q origin main && git -C theostack-go worktree add -q ../theostack-go-workflows -b chore/beads-workflows origin/main
git -C theostack-node fetch -q origin dev && git -C theostack-node worktree add -q ../theostack-node-workflows -b chore/beads-workflows origin/dev
```

- [ ] **Step 2: Apply and verify — go**

```bash
cd ~/code/theostack/theostack-go-workflows && source ~/.zshrc.mcp-secrets
~/code/agent-baseline/apply.sh . && git status --short
bd formula list | grep -E 'feature|bugfix'
bd prime --no-memories | grep -c 'Ask, don'
grep -c 'gate check' .claude/settings.json .codex/hooks.json
~/code/agent-baseline/apply.sh --check .
```
Expected: `git status` shows `.beads/PRIME.md`, `.beads/formulas/*`, `.claude/settings.json`, `.codex/hooks.json`, `.agent-baseline`; both formulas listed; `1`; `1` and `1`; `apply.sh: up to date`.

- [ ] **Step 3: Commit, push, PR — go**

```bash
git add -A && git commit -m "chore: beads workflows - feature/bugfix formulas, decision rule, gate check at session start

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
git push -u origin chore/beads-workflows
gh pr create --base main --title "chore: beads workflows (feature/bugfix formulas, decision rule, gate check)" --body "Applies agent-baseline $(git -C ~/code/agent-baseline rev-parse --short HEAD): \`.beads/formulas/{feature,bugfix}.formula.toml\`, PRIME.md rules (ask-don't-assume via decision beads, pour by shape, \`bd ready --exclude-label human\`), session-start \`bd gate check\` in Claude and Codex hooks. Spec: agent-baseline/docs/specs/2026-09-21-beads-workflows-design.md.

🤖 Generated with [Claude Code](https://claude.com/claude-code)"
```

- [ ] **Step 4: Same for node** (base `dev`, worktree `theostack-node-workflows`)

Repeat Steps 2–3 in `~/code/theostack/theostack-node-workflows` with `--base dev`.

- [ ] **Step 5: Acceptance dry-run in the go repo (no pour, no side effects)**

Run: `cd ~/code/theostack/theostack-go-workflows && bd mol pour feature --var name=scratch-index --var summary="Scripture reverse index" --dry-run | head -20`
Expected: a preview listing the ten steps with `scratch-index` substituted; nothing created.
