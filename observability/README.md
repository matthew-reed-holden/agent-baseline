# observability

Local OpenTelemetry stack for the agent workflows: what the harnesses spend
and do, and how the beads workflows perform. One container each for
`grafana/otel-lgtm` (collector, Prometheus, Loki, Tempo, Grafana) and
`grafana/mcp-grafana` (agents query the same data).

## Run (this machine)

    cp .env.example .env         # set GRAFANA_ADMIN_PASSWORD and REPOS
    ./setup.sh up                # stack
    ./setup.sh install-timer     # beads exporter every 5 min (systemd --user)
    source env.sh                # producers: put this line in your shell init

Grafana http://127.0.0.1:3000 (admin), dashboards *Workflows (beads)* and
*Agent activity & cost*. MCP http://127.0.0.1:8000/mcp — add as `grafana` to
your user-level MCP servers so every harness can query it.

## Producers

| Producer | Switch | Notes |
|---|---|---|
| Claude Code | `env.sh` | tool details + prompts on; responses/bodies off |
| bd | `env.sh` (`BD_OTEL_ENABLED=true`) | operational metrics (`bd_*`) |
| beads workflow exporter | timer | `workflow_*` gauges, see QUERIES.md |
| Codex | `~/.codex/config.toml`: `[otel]` `exporter = "otlp-http"`, `exporter.otlp-http.endpoint = "http://localhost:4318"`, `log_user_prompt = true` | user config; Codex ignores project-level provider keys |
| Per repo | `apply.sh` sets `env.OTEL_RESOURCE_ATTRIBUTES=repo=<name>` in `.claude/settings.json` | the `repo` label on every series |

## Another machine (e.g. the Mac)

Set `BIND=<this host's Tailscale IP>` here, `./setup.sh up`; on the other
machine `export OTEL_EXPORTER_OTLP_ENDPOINT=http://<tailscale-ip>:4318`
before `source env.sh`, and point its `grafana` MCP at `http://<tailscale-ip>:8000/mcp`.
Change the admin password once the port is not loopback-only.

## Gotchas found while building it

- Claude Code defaults to delta temporality; Prometheus's OTLP receiver drops
  delta sums. `env.sh` sets `OTEL_EXPORTER_OTLP_METRICS_TEMPORALITY_PREFERENCE=cumulative`.
- The collector promotes the `repo` resource attribute onto every datapoint
  (`otelcol-config.yaml`, `transform/promote`) so PromQL can filter on it.
- `docker compose pull` from an agent shell fails on the keyring credential
  helper; pull with `DOCKER_CONFIG=$(mktemp -d)` (public images need no auth).
- First boot on a busy host can take minutes; `setup.sh status` shows health.

## Limits (v1)

Human-step durations are measured from pour, not from when the step became
ready. Codex event names differ from Claude's; the dashboards are Claude-first.
