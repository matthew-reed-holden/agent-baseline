# agent-baseline

The repo-tracked half of an AI-agent setup that works the same in Claude Code,
Codex and OpenCode. One `AGENTS.md`, one beads `PRIME.md`, one `.mcp.json` —
the harness-specific files are generated from those.

The other half (global instructions, plugin allowlist, user-scope MCP,
secrets) is per-user and lives in your dotfiles / home-manager, not here.
Rule of thumb: if an agent in a fresh clone on a machine you don't own needs
it, it belongs here.

## Use

New repo: create from this template on GitHub, then in the clone:

    ~/code/agent-baseline/apply.sh --stack go      # or node, or no --stack

Existing repo:

    ~/code/agent-baseline/apply.sh --stack node ~/code/my-repo
    ~/code/agent-baseline/apply.sh --check ~/code/my-repo   # drift + env report, exit 1 on either

First apply asks a few questions (project name, PR target branch, stack
defaults); answers are stored in `.agent-baseline` and never asked again.
`--yes` takes defaults, `--var K=V` pre-answers — use those in scripts.

Secrets are never asked for or written. Configs reference `${VAR}`; the env
check at the end of every apply tells you what to export.

## What it writes

| Mode | Files | Meaning |
|---|---|---|
| owned | `CLAUDE.md` (→ `AGENTS.md`), `.beads/PRIME.md`, `.beads/formulas/`, `.codex/hooks.json`, `.agents/skills/beads/` | overwritten on every apply |
| seeded | `AGENTS.md`, `.mcp.json`, `docs/README.md`, `agents/README.md`, overlay `.mcp.json` | created once, then yours |
| generated | `.codex/config.toml`, `opencode.json`, `.claude/agents/`, `.opencode/agents/` | from `.mcp.json` / `agents/`; don't edit |
| merged | `.claude/settings.json` | only `hooks.SessionStart`, `enabledMcpjsonServers`, `enabledPlugins` are touched; overlay plugins are added, existing ones kept |

`.beads/config.yaml` gets `agent.profile: team-maintainer` appended if absent;
`.gitignore` gets `.worktrees/` appended if absent (agents work in `.worktrees/<slug>`).

## Edit the source, not the output

Add an MCP server to `.mcp.json` (Claude Code's schema, `${VAR}` or
`${VAR:-default}` for env), re-run apply. `render.py` refuses anything a
target format can't express rather than dropping it silently — e.g. Codex
can forward an env var only under its own name, so
`"PGURL": "${DATABASE_URL}"` needs a `:-default` or a rename.

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

## Observability

`observability/` runs a local OTel stack (Grafana + Prometheus + Loki via
`otel-lgtm`) fed by Claude Code, Codex, bd and a beads workflow exporter, with
an MCP server so agents can query it. See `observability/README.md`.

## Maintain the template

- `./apply.sh --self-test`, `./test/formulas.sh` and `python3 -m unittest` before pushing.
- `baseline/.codex/hooks.json` and `baseline/.agents/skills/beads/` are
  `bd setup codex` output. Refresh after a bd upgrade: `bd setup codex` in a
  scratch repo, copy the two paths in, commit.
- New stack: `overlays/<name>/` with `overlay.json` (`plugins`, `vars`) and
  any seeded files.
