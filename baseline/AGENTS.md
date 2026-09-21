# {{PROJECT_NAME}}

{{PROJECT_SUMMARY}}

<!-- Keep this file short: commands, conventions and gotchas an agent needs
     on every task. Narrative belongs in docs/. -->

## Beads

All work is tracked in bd. Run `bd prime` first: it is the single source of
truth for the workflow, the push policy and the session-close protocol
(`.beads/PRIME.md`, injected automatically by the Claude Code, Codex and
OpenCode hooks). `bd ready` → `bd update <id> --claim` → work → `bd close`.

## Build & Test

<!-- The exact commands: build, unit, integration, lint, and the pre-PR gate.
     Note anything that only fails in CI. -->

## Architecture

See [docs/architecture.md](docs/architecture.md).

<!-- At most one paragraph here: where the domains live and how to find them. -->

## Conventions

<!-- Rules a reviewer would reject a PR for: layout, error handling, generated
     code, comments policy. Each bullet carries its "why". -->

## Git

- Every change goes through a PR into `{{PR_TARGET_BRANCH}}`; never commit to
  it directly. Merging is human-only.
- Always use non-interactive flags (`rm -f`, `cp -f`, `mv -f`, `apt-get -y`,
  `ssh -o BatchMode=yes`): shell aliases may add `-i` and hang the agent.

<!-- Add signing, worktree and checkout rules specific to this repo. -->
