# observability — design

**Status:** approved in discussion 2026-09-21, pending spec review
**Lives in:** `agent-baseline/observability/`. Runs on shadowfax now; the Mac (OpenCode-primary) joins later by pointing its endpoint at shadowfax over Tailscale.

## Goal

Local, OpenTelemetry-based metrics and events for the agent workflows: what
the harnesses spend and do (Claude Code, Codex, bd), and how the beads
workflows perform (molecules, steps, human wait, decisions, bugfix adoption).
Viewable on a local Grafana; queryable by agents through Grafana's MCP server.

## Non-goals

OpenCode telemetry (none exists). Cloud/hosted observability. Alerting.
Per-machine values (endpoint, passwords) — those stay in nix / `.env`,
following the contract this repo defines.

## Components

```
observability/
  compose.yaml                 lgtm + mcp-grafana
  .env.example                 GRAFANA_ADMIN_PASSWORD, BIND (127.0.0.1), REPOS
  env.sh                       the producer env contract (sourced by the shell)
  setup.sh                     up | down | status | install-timer
  bd-workflow-exporter.py      beads → OTLP/JSON metrics (stdlib)
  systemd/agent-baseline-exporter.{service,timer}
  grafana/dashboards.yaml      provisioning file
  grafana/agent-activity.json  dashboard: cost, tokens, sessions, tools, subagents
  grafana/workflows.json       dashboard: molecules, steps, human queue, decisions, bugs
  QUERIES.md                   canned PromQL/LogQL for agents and humans
  README.md                    setup, the env contract, Codex [otel] block, Mac join
  test/test_exporter.py        unit tests for the metric derivation
```

### compose.yaml

- `lgtm`: `grafana/otel-lgtm`. Ports `${BIND}:3000:3000` (Grafana),
  `4317`, `4318` (OTLP), `9090` (Prometheus), `3100` (Loki). Volume
  `lgtm-data:/data`. `GF_SECURITY_ADMIN_PASSWORD=${GRAFANA_ADMIN_PASSWORD}`.
  Mounts `./grafana/dashboards.yaml` →
  `/otel-lgtm/grafana/conf/provisioning/dashboards/custom.yaml` and
  `./grafana/*.json` → `/otel-lgtm/grafana/conf/provisioning/dashboards/custom/`.
- `mcp-grafana`: `grafana/mcp-grafana`, `-t streamable-http`, published
  `${BIND}:8000:8000` (path `/mcp`). `GRAFANA_URL=http://lgtm:3000`,
  `GRAFANA_USERNAME=admin`, `GRAFANA_PASSWORD=${GRAFANA_ADMIN_PASSWORD}`.
  Every tool category disabled except `search`, `datasource`, `prometheus`,
  `loki`, `dashboard`, `query`.

### env.sh — the producer contract

```sh
export OTEL_EXPORTER_OTLP_ENDPOINT="${OTEL_EXPORTER_OTLP_ENDPOINT:-http://localhost:4318}"
# Claude Code
export CLAUDE_CODE_ENABLE_TELEMETRY=1
export OTEL_METRICS_EXPORTER=otlp OTEL_LOGS_EXPORTER=otlp
export OTEL_EXPORTER_OTLP_PROTOCOL=http/protobuf
export OTEL_METRIC_EXPORT_INTERVAL=10000 OTEL_LOGS_EXPORT_INTERVAL=5000
export OTEL_LOG_TOOL_DETAILS=1 OTEL_LOG_USER_PROMPTS=1
# bd
export BD_OTEL_ENABLED=true
export OTEL_EXPORTER_OTLP_METRICS_ENDPOINT="$OTEL_EXPORTER_OTLP_ENDPOINT/v1/metrics"
```
The Mac sets `OTEL_EXPORTER_OTLP_ENDPOINT=http://<shadowfax-tailscale>:4318`
before sourcing. Codex: README documents the `[otel]` block for
`~/.codex/config.toml` (`exporter = "otlp-http"`, endpoint, `log_user_prompt = true`).
`render.py` adds `env.OTEL_RESOURCE_ATTRIBUTES = "repo=<PROJECT_NAME>"` to
`.claude/settings.json` as a fourth owned key (value from the `.agent-baseline`
answers; falls back to the directory basename).

### bd-workflow-exporter.py

`bd-workflow-exporter.py [--endpoint URL] [--once|--print] REPO...`

For each repo (run with `-C`): `bd list --status=all --limit 0 --json`,
`bd ready --json`, `bd human list --json`, `bd gate list --json` (falls back to
text parsing if `--json` is unsupported), `bd list --status=in_progress --json`.
Derives, then POSTs one OTLP/JSON `ExportMetricsServiceRequest` to
`$endpoint/v1/metrics` with resource `service.name=bd-workflow-exporter`:

| Metric (gauge) | Labels | Derivation |
|---|---|---|
| `workflow_molecules` | repo, formula, status | beads with `issue_type=molecule`; formula = title; status open/in_progress/closed |
| `workflow_steps` | repo, formula, step, status, human | beads labeled `formula:<f>`; step = title with the `{{name}}`/`{{bug}}` part stripped by matching the formula's step titles; human = has label `human` |
| `workflow_step_duration_seconds_count/_sum/_p50/_p90` | repo, formula, step, human | closed steps: `closed_at - started_at` when `started_at` set, else `closed_at - created_at` |
| `workflow_human_queue` | repo | open beads with label `human` |
| `workflow_decisions_total` | repo, status | `issue_type=decision` |
| `workflow_decision_answer_seconds_p50/_p90/_count` | repo | closed decisions: `closed_at - created_at` |
| `workflow_bugs_closed_total` | repo, via | closed bugs; via=`bugfix` if any bead labeled `formula:bugfix` has the bug id in its title/notes or the bug has a dependent molecule, else `plain` |
| `workflow_gates_open` | repo, type | `bd gate list` |
| `workflow_stale_in_progress` | repo | in_progress beads with `updated_at` older than 24h |
| `workflow_exporter_last_success_timestamp_seconds` | repo | now, on success |

`--print` writes the OTLP JSON to stdout instead of pushing (used by tests
and for debugging). Failures per repo are logged and do not stop other repos.

### systemd user timer

`agent-baseline-exporter.timer` every 5 minutes → `agent-baseline-exporter.service`
running `python3 …/bd-workflow-exporter.py $REPOS` with `EnvironmentFile=…/.env`.
`setup.sh install-timer` symlinks the units into `~/.config/systemd/user/` and
enables them. Runs on the host because bd needs the embedded Dolt lock.

### Dashboards

- **agent-activity.json**: cost per day by model (`claude_code_cost_usage`),
  tokens by `query_source`, sessions per day, tool results by `tool_name` and
  success (Loki `claude_code.tool_result`), subagent runs by model
  (`claude_code.subagent_completed`), api errors. Variable: `repo`.
- **workflows.json**: molecules by formula/status, step status matrix, step
  duration p50/p90 by step, human queue, decisions (open/closed, answer p50),
  bugs closed via bugfix vs plain, gates open, stale in-progress. Variable: `repo`.

Panels use PromQL/LogQL only; no plugins beyond what LGTM ships.

### QUERIES.md

~10 canned queries with one-line intent each: cost per repo/day; cost per
session with prompt (LogQL join on `session.id`); sessions that ran a
forbidden command (`bd export -o`, `git checkout` in main checkout);
`bd mol pour` per day; decision answer p50 over 7d; human queue now; slowest
step per formula; bugfix adoption ratio.

### nix (documented, not implemented here)

Two lines: `source ~/code/agent-baseline/observability/env.sh` in zsh init
(after sops exports), and `grafana = { url = "http://localhost:8000/mcp"; }`
in the mcp module so Claude, OpenCode and Codex all get it.

## Verification

- `test_exporter.py` (unittest): derivation from fixture JSON produces the
  expected gauges; `--print` emits valid OTLP/JSON.
- `setup.sh up` → `curl -s localhost:4318` returns 404/405 (collector up),
  Grafana login works, dashboards listed.
- `source env.sh; claude -p hi` → within 20 s
  `curl 'localhost:9090/api/v1/query?query=claude_code_session_count_total'` non-empty.
- `bd-workflow-exporter.py --once ~/code/theostack/theostack-go` →
  `workflow_molecules` queryable.
- `curl -X POST localhost:8000/mcp` with an MCP `tools/list` returns the six
  enabled categories' tools.
- Acceptance: the next poured molecule appears on the Workflows dashboard;
  `bd human list` and `workflow_human_queue` agree.
