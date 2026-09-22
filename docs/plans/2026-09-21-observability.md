# observability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A local OTel stack (grafana/otel-lgtm + mcp-grafana) fed by Claude Code, Codex, bd and a beads workflow exporter, with two provisioned Grafana dashboards and agent access through Grafana's MCP server.

**Architecture:** `observability/` in agent-baseline holds the compose file, the producer env contract, the exporter (stdlib Python, systemd user timer), dashboards and canned queries. Per-machine values (endpoint, password) live in a gitignored `.env` and the shell; nix sources `env.sh`.

**Tech Stack:** docker compose, grafana/otel-lgtm, grafana/mcp-grafana, python3 stdlib, systemd user units.

**Spec:** `docs/specs/2026-09-21-observability-design.md`

## Global Constraints

- Nothing secret in tracked files (public repo): password and machine endpoint come from `observability/.env` (gitignored) and the shell.
- All ports bound to `${BIND}` (default `127.0.0.1`).
- Exporter is stdlib-only python3 (3.11+ for `tomllib`) and runs on the host (bd needs the embedded Dolt lock).
- Dashboard queries are regex-tolerant on metric names (`{__name__=~"claude_code_cost_usage.*"}`) because the OTLP→Prometheus suffixing (`_total`, unit) is decided by the collector, not us.
- Commit messages end with `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`.
- Docker 29 is present on shadowfax; all `docker compose` commands run from `~/code/agent-baseline/observability`.

---

### Task 1: Stack — compose, collector config, env contract, setup script

**Files:**
- Create: `observability/compose.yaml`, `observability/otelcol-config.yaml`, `observability/.env.example`, `observability/env.sh`, `observability/setup.sh`, `observability/grafana/dashboards.yaml`, `observability/grafana/.gitkeep`
- Modify: `.gitignore` (add `observability/.env`)

**Interfaces:**
- Produces: OTLP HTTP at `http://${BIND}:4318`, Grafana at `:3000` (admin / `$GRAFANA_ADMIN_PASSWORD`), Prometheus at `:9090`, Loki at `:3100`, mcp-grafana at `http://${BIND}:8000/mcp`; `env.sh` exporting the producer variables; `setup.sh up|down|status|install-timer`.

- [ ] **Step 1: compose.yaml**

```yaml
# agent-baseline observability stack. `setup.sh up` from this directory.
services:
  lgtm:
    image: grafana/otel-lgtm:latest
    container_name: agent-lgtm
    restart: unless-stopped
    ports:
      - "${BIND:-127.0.0.1}:3000:3000"   # Grafana
      - "${BIND:-127.0.0.1}:4317:4317"   # OTLP gRPC
      - "${BIND:-127.0.0.1}:4318:4318"   # OTLP HTTP
      - "${BIND:-127.0.0.1}:9090:9090"   # Prometheus
      - "${BIND:-127.0.0.1}:3100:3100"   # Loki
    environment:
      GF_SECURITY_ADMIN_PASSWORD: ${GRAFANA_ADMIN_PASSWORD:?set in .env}
      GF_USERS_DEFAULT_THEME: system
    volumes:
      - lgtm-data:/data
      - ./otelcol-config.yaml:/otel-lgtm/otelcol-config.yaml:ro
      - ./grafana/dashboards.yaml:/otel-lgtm/grafana/conf/provisioning/dashboards/custom.yaml:ro
      - ./grafana:/otel-lgtm/grafana/conf/provisioning/dashboards/custom:ro

  mcp-grafana:
    image: grafana/mcp-grafana:latest
    container_name: agent-mcp-grafana
    restart: unless-stopped
    depends_on: [lgtm]
    ports:
      - "${BIND:-127.0.0.1}:8000:8000"
    environment:
      GRAFANA_URL: http://lgtm:3000
      GRAFANA_USERNAME: admin
      GRAFANA_PASSWORD: ${GRAFANA_ADMIN_PASSWORD:?set in .env}
    # Least tool surface: keep search, datasource, prometheus, loki, dashboard, query.
    command: >
      -t streamable-http --address 0.0.0.0:8000
      --disable-incident --disable-write --disable-elasticsearch --disable-quickwit
      --disable-influxdb --disable-alerting --disable-oncall --disable-asserts
      --disable-sift --disable-admin --disable-pyroscope --disable-navigation
      --disable-rendering --disable-snapshot --disable-cloudwatch --disable-examples
      --disable-sql --disable-clickhouse --disable-snowflake --disable-athena
      --disable-runpanelquery --disable-graphite --disable-provisioning
      --disable-agento11y --disable-assistant --disable-docs

volumes:
  lgtm-data:
```

- [ ] **Step 2: otelcol-config.yaml** — LGTM's default plus a transform that copies the `repo` resource attribute onto every metric datapoint, so Prometheus series carry `repo=`.

```yaml
receivers:
  otlp:
    protocols:
      grpc:
        endpoint: 0.0.0.0:4317
      http:
        endpoint: 0.0.0.0:4318
        cors:
          allowed_origins:
            - http://*
  prometheus/collector:
    config:
      scrape_configs:
        - job_name: "opentelemetry-collector"
          scrape_interval: 1s
          static_configs:
            - targets: ["127.0.0.1:8888"]

extensions:
  health_check:
    endpoint: 0.0.0.0:13133
    path: "/ready"

processors:
  batch:
  # Prometheus's OTLP receiver keeps resource attributes in target_info only;
  # promote the ones we filter on to datapoint attributes.
  transform/promote:
    metric_statements:
      - context: datapoint
        statements:
          - set(attributes["repo"], resource.attributes["repo"]) where resource.attributes["repo"] != nil
          - set(attributes["service_name"], resource.attributes["service.name"]) where resource.attributes["service.name"] != nil

exporters:
  otlp_http/metrics:
    endpoint: http://127.0.0.1:9090/api/v1/otlp
    tls:
      insecure: true
  otlp_http/traces:
    endpoint: http://127.0.0.1:4418
    tls:
      insecure: true
  otlp_http/logs:
    endpoint: http://127.0.0.1:3100/otlp
    tls:
      insecure: true
  otlp_grpc/profiles:
    endpoint: http://127.0.0.1:4040
    tls:
      insecure: true

service:
  extensions: [health_check]
  pipelines:
    traces:
      receivers: [otlp]
      processors: [batch]
      exporters: [otlp_http/traces]
    metrics:
      receivers: [otlp, prometheus/collector]
      processors: [transform/promote, batch]
      exporters: [otlp_http/metrics]
    logs:
      receivers: [otlp]
      processors: [batch]
      exporters: [otlp_http/logs]
    profiles:
      receivers: [otlp]
      exporters: [otlp_grpc/profiles]
```

- [ ] **Step 3: `.env.example`, `env.sh`, provisioning yaml, gitignore**

```bash
cd ~/code/agent-baseline/observability
cat > .env.example <<'EOF'
# copy to .env (gitignored)
GRAFANA_ADMIN_PASSWORD=change-me
BIND=127.0.0.1                      # Tailscale IP when other machines push here
REPOS=/home/you/code/repo-a /home/you/code/repo-b   # exporter targets, space-separated
EOF
cat > env.sh <<'EOF'
# Producer env contract. Source from your shell (nix: after the sops exports).
# Another machine sets OTEL_EXPORTER_OTLP_ENDPOINT to this host's Tailscale address first.
export OTEL_EXPORTER_OTLP_ENDPOINT="${OTEL_EXPORTER_OTLP_ENDPOINT:-http://localhost:4318}"
# Claude Code
export CLAUDE_CODE_ENABLE_TELEMETRY=1
export OTEL_METRICS_EXPORTER=otlp
export OTEL_LOGS_EXPORTER=otlp
export OTEL_EXPORTER_OTLP_PROTOCOL=http/protobuf
export OTEL_METRIC_EXPORT_INTERVAL=10000
export OTEL_LOGS_EXPORT_INTERVAL=5000
export OTEL_LOG_TOOL_DETAILS=1
export OTEL_LOG_USER_PROMPTS=1
# bd (explicit opt-in; bd ignores OTEL_* alone)
export BD_OTEL_ENABLED=true
export OTEL_EXPORTER_OTLP_METRICS_ENDPOINT="$OTEL_EXPORTER_OTLP_ENDPOINT/v1/metrics"
EOF
mkdir -p grafana && : > grafana/.gitkeep
cat > grafana/dashboards.yaml <<'EOF'
apiVersion: 1
providers:
  - name: agent-baseline
    folder: agent-baseline
    type: file
    disableDeletion: false
    allowUiUpdates: true
    options:
      path: /otel-lgtm/grafana/conf/provisioning/dashboards/custom
EOF
cd .. && printf 'observability/.env\n' >> .gitignore
```

- [ ] **Step 4: setup.sh**

```bash
#!/usr/bin/env bash
# up | down | status | install-timer  — run from anywhere.
set -euo pipefail
here=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
cd "$here"
[[ -f .env ]] || { echo "setup.sh: copy .env.example to .env and set GRAFANA_ADMIN_PASSWORD, REPOS" >&2; exit 2; }
case ${1:-} in
  up)
    docker compose up -d
    for i in $(seq 1 30); do curl -fs -o /dev/null http://127.0.0.1:3000/api/health && break; sleep 2; done
    echo "grafana:    http://127.0.0.1:3000  (admin / \$GRAFANA_ADMIN_PASSWORD)"
    echo "otlp http:  http://127.0.0.1:4318"
    echo "mcp:        http://127.0.0.1:8000/mcp"
    echo "producers:  source $here/env.sh   (put this in your shell init)"
    ;;
  down) docker compose down ;;
  status)
    docker compose ps
    systemctl --user status agent-baseline-exporter.timer --no-pager 2>/dev/null | head -3 || true
    ;;
  install-timer)
    mkdir -p ~/.config/systemd/user
    sed "s|@HERE@|$here|g" systemd/agent-baseline-exporter.service > ~/.config/systemd/user/agent-baseline-exporter.service
    cp -f systemd/agent-baseline-exporter.timer ~/.config/systemd/user/
    systemctl --user daemon-reload
    systemctl --user enable --now agent-baseline-exporter.timer
    systemctl --user start agent-baseline-exporter.service
    systemctl --user status agent-baseline-exporter.service --no-pager | tail -5
    ;;
  *) echo "usage: setup.sh up|down|status|install-timer" >&2; exit 2 ;;
esac
```

- [ ] **Step 5: Bring it up and verify**

```bash
cd ~/code/agent-baseline/observability && cp .env.example .env
sed -i "s|^GRAFANA_ADMIN_PASSWORD=.*|GRAFANA_ADMIN_PASSWORD=$(openssl rand -hex 12)|; s|^REPOS=.*|REPOS=$HOME/code/theostack/theostack-go $HOME/code/theostack/theostack-node|" .env
chmod +x setup.sh && ./setup.sh up
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:4318/v1/metrics      # 405 = collector listening
docker logs agent-lgtm 2>&1 | grep -iE 'transform|error' | head -5           # no config errors
curl -s -u "admin:$(grep GRAFANA_ADMIN_PASSWORD .env | cut -d= -f2)" http://127.0.0.1:3000/api/datasources | python3 -c 'import json,sys;print([d["uid"] for d in json.load(sys.stdin)])'
curl -s -X POST http://127.0.0.1:8000/mcp -H 'Content-Type: application/json' -H 'Accept: application/json, text/event-stream' -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-03-26","capabilities":{},"clientInfo":{"name":"probe","version":"0"}}}' | head -c 300; echo
```
Expected: `405`; no collector errors (if the log says the `transform` processor is unknown, the LGTM collector build lacks contrib — replace `transform/promote` in the metrics pipeline with nothing and note it in README; dashboards then split by `job` instead of `repo`); datasource uids include `prometheus` and `loki`; the MCP initialize returns a JSON-RPC result with `serverInfo`.

- [ ] **Step 6: Commit**

```bash
cd ~/code/agent-baseline && git add -A && git commit -m "feat(observability): otel-lgtm + mcp-grafana stack, producer env contract

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 2: Workflow exporter (TDD)

**Files:**
- Create: `observability/bd-workflow-exporter.py`, `observability/test/test_exporter.py`, `observability/test/__init__.py`, `observability/systemd/agent-baseline-exporter.service`, `observability/systemd/agent-baseline-exporter.timer`

**Interfaces:**
- Python API (tested): `load_formulas(repo) -> {formula: [(step_id, regex)]}`, `derive(repo_name, beads, human, gates, formulas, now) -> list[(metric, {labels}, value)]`, `to_otlp(points, now_ns) -> dict`.
- CLI: `bd-workflow-exporter.py [--endpoint URL] [--print] REPO...`; exit 0 if at least one repo succeeded.

- [ ] **Step 1: Write the failing tests**

```python
# observability/test/test_exporter.py
import json, sys, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import importlib
ex = importlib.import_module("bd-workflow-exporter")

BASE = Path(__file__).resolve().parents[2] / "baseline"
NOW = 1_800_000_000.0  # fixed clock


def bead(id, type="task", status="open", labels=(), title="", created="2026-09-20T00:00:00Z", started=None, closed=None, updated=None):
    b = {"id": id, "issue_type": type, "status": status, "title": title, "created_at": created,
         "updated_at": updated or created}
    if labels: b["labels"] = list(labels)
    if started: b["started_at"] = started
    if closed: b["closed_at"] = closed
    return b


BEADS = [
    bead("r-mol-1", "molecule", "in_progress", title="feature"),
    bead("r-1", labels=["formula:feature"], title="Brainstorm demo", status="closed",
         created="2026-09-20T00:00:00Z", started="2026-09-20T00:10:00Z", closed="2026-09-20T01:10:00Z"),
    bead("r-2", labels=["formula:feature", "human"], title="Approve approach for demo", status="closed",
         created="2026-09-20T00:00:00Z", closed="2026-09-20T03:00:00Z"),
    bead("r-3", labels=["formula:feature"], title="Write spec for demo", status="in_progress",
         created="2026-09-20T00:00:00Z", updated="2026-09-20T03:05:00Z"),
    bead("d-1", "decision", "closed", labels=["human"], title="TTL?", created="2026-09-20T02:00:00Z", closed="2026-09-20T02:30:00Z"),
    bead("d-2", "decision", "open", labels=["human"], title="Cache?", created="2026-09-20T04:00:00Z"),
    bead("b-1", "bug", "closed", title="It breaks", closed="2026-09-19T00:00:00Z"),
    bead("b-2", "bug", "closed", title="Other", closed="2026-09-19T00:00:00Z"),
    bead("r-mol-2", "molecule", "closed", title="bugfix"),
    bead("r-9", labels=["formula:bugfix"], title="Reproduce b-1", status="closed", closed="2026-09-19T00:00:00Z"),
]
HUMAN = [BEADS[5]]
GATES = [{"id": "g-1", "await_type": "gh:pr", "status": "open"}]


def get(points, name, **labels):
    return [v for (m, l, v) in points if m == name and all(l.get(k) == val for k, val in labels.items())]


class Formulas(unittest.TestCase):
    def test_step_regexes_from_baseline(self):
        f = ex.load_formulas(BASE)
        self.assertIn("feature", f); self.assertIn("bugfix", f)
        self.assertEqual(ex.step_of("Approve approach for demo", f["feature"]), "approve-approach")
        self.assertEqual(ex.step_of("Merge fix for x-1", f["bugfix"]), "merge")
        self.assertIsNone(ex.step_of("Unrelated title", f["feature"]))


class Derive(unittest.TestCase):
    def setUp(self):
        self.f = ex.load_formulas(BASE)
        self.p = ex.derive("repo", BEADS, HUMAN, GATES, self.f, NOW)

    def test_molecules(self):
        self.assertEqual(get(self.p, "workflow_molecules", formula="feature", status="in_progress"), [1])
        self.assertEqual(get(self.p, "workflow_molecules", formula="bugfix", status="closed"), [1])

    def test_steps_and_human_flag(self):
        self.assertEqual(get(self.p, "workflow_steps", formula="feature", step="approve-approach", status="closed", human="true"), [1])
        self.assertEqual(get(self.p, "workflow_steps", formula="feature", step="spec", status="in_progress", human="false"), [1])

    def test_durations(self):
        self.assertEqual(get(self.p, "workflow_step_duration_seconds_sum", formula="feature", step="brainstorm"), [3600.0])  # closed - started
        self.assertEqual(get(self.p, "workflow_step_duration_seconds_sum", formula="feature", step="approve-approach"), [10800.0])  # closed - created
        self.assertEqual(get(self.p, "workflow_step_duration_seconds_count", formula="feature", step="brainstorm"), [1])

    def test_decisions(self):
        self.assertEqual(get(self.p, "workflow_decisions_total", status="closed"), [1])
        self.assertEqual(get(self.p, "workflow_decisions_total", status="open"), [1])
        self.assertEqual(get(self.p, "workflow_decision_answer_seconds_p50"), [1800.0])
        self.assertEqual(get(self.p, "workflow_human_queue"), [1])

    def test_bugs_via(self):
        self.assertEqual(get(self.p, "workflow_bugs_closed_total", via="bugfix"), [1])
        self.assertEqual(get(self.p, "workflow_bugs_closed_total", via="plain"), [1])

    def test_gates_stale_success(self):
        self.assertEqual(get(self.p, "workflow_gates_open", type="gh:pr"), [1])
        self.assertEqual(get(self.p, "workflow_stale_in_progress"), [1])  # r-3 updated 2026-09-20, NOW is later
        self.assertEqual(get(self.p, "workflow_exporter_last_success_timestamp_seconds"), [NOW])


class Otlp(unittest.TestCase):
    def test_shape(self):
        doc = ex.to_otlp([("workflow_human_queue", {"repo": "r"}, 2)], 123)
        m = doc["resourceMetrics"][0]["scopeMetrics"][0]["metrics"][0]
        self.assertEqual(m["name"], "workflow_human_queue")
        dp = m["gauge"]["dataPoints"][0]
        self.assertEqual(dp["asDouble"], 2.0); self.assertEqual(dp["timeUnixNano"], "123")
        self.assertEqual(dp["attributes"], [{"key": "repo", "value": {"stringValue": "r"}}])
        json.dumps(doc)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run to see it fail**

Run: `cd ~/code/agent-baseline/observability && : > test/__init__.py && python3 -m unittest test.test_exporter 2>&1 | tail -2`
Expected: `ModuleNotFoundError: No module named 'bd-workflow-exporter'`

- [ ] **Step 3: Write the exporter**

```python
#!/usr/bin/env python3
"""beads -> OTLP/JSON workflow metrics. Stdlib only (python3.11+).

usage: bd-workflow-exporter.py [--endpoint http://localhost:4318] [--print] REPO...
"""
import argparse
import json
import os
import re
import subprocess
import sys
import time
import tomllib
import urllib.request
from datetime import datetime
from pathlib import Path

STALE_AFTER = 24 * 3600
FORMULA_LABEL = re.compile(r"^formula:(.+)$")
VAR = re.compile(r"\{\{[a-z_]+\}\}")


def bd(repo, *args):
    r = subprocess.run(["bd", "-C", repo, *args, "--json"], capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"bd {' '.join(args)}: {r.stderr.strip()[:200]}")
    return json.loads(r.stdout or "null") or []


def ts(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp() if s else None


def pct(xs, p):
    xs = sorted(xs)
    return float(xs[min(len(xs) - 1, round(p * (len(xs) - 1)))]) if xs else 0.0


def load_formulas(root):
    """{formula: [(step_id, compiled regex over the step title)]} from <root>/.beads/formulas/*.formula.toml."""
    out = {}
    for f in sorted(Path(root, ".beads", "formulas").glob("*.formula.toml")):
        doc = tomllib.loads(f.read_text())
        steps = []
        for s in doc.get("steps", []):
            pattern = "^" + "(.+)".join(re.escape(part) for part in VAR.split(s["title"])) + "$"
            steps.append((s["id"], re.compile(pattern)))
        out[doc["formula"]] = steps
    return out


def step_of(title, steps):
    for step_id, rx in steps:
        if rx.match(title):
            return step_id
    return None


def derive(repo, beads, human, gates, formulas, now):
    p = []
    def add(name, labels, value):
        p.append((name, {"repo": repo, **labels}, value))
    counts = {}
    def count(name, **labels):
        key = (name, tuple(sorted(labels.items())))
        counts[key] = counts.get(key, 0) + 1

    durations = {}   # (formula, step, human) -> [seconds]
    answers = []
    bugfix_titles = " ".join(b["title"] for b in beads if "formula:bugfix" in (b.get("labels") or []))

    for b in beads:
        labels = b.get("labels") or []
        t, st = b["issue_type"], b["status"]
        if t == "molecule":
            count("workflow_molecules", formula=b["title"], status=st)
            continue
        formula = next((m.group(1) for l in labels for m in [FORMULA_LABEL.match(l)] if m), None)
        if formula:
            step = step_of(b["title"], formulas.get(formula, [])) or "other"
            is_human = "human" in labels
            count("workflow_steps", formula=formula, step=step, status=st, human=str(is_human).lower())
            if st == "closed" and b.get("closed_at"):
                start = ts(b.get("started_at")) if not is_human and b.get("started_at") else ts(b["created_at"])
                durations.setdefault((formula, step, is_human), []).append(ts(b["closed_at"]) - start)
        if t == "decision":
            count("workflow_decisions_total", status=st)
            if st == "closed" and b.get("closed_at"):
                answers.append(ts(b["closed_at"]) - ts(b["created_at"]))
        if t == "bug" and st == "closed":
            count("workflow_bugs_closed_total", via="bugfix" if b["id"] in bugfix_titles else "plain")
        if st == "in_progress" and now - ts(b.get("updated_at") or b["created_at"]) > STALE_AFTER:
            count("workflow_stale_in_progress")

    for (name, labels), v in counts.items():
        add(name, dict(labels), v)
    for (formula, step, is_human), xs in durations.items():
        lab = {"formula": formula, "step": step, "human": str(is_human).lower()}
        add("workflow_step_duration_seconds_count", lab, len(xs))
        add("workflow_step_duration_seconds_sum", lab, float(sum(xs)))
        add("workflow_step_duration_seconds_p50", lab, pct(xs, 0.5))
        add("workflow_step_duration_seconds_p90", lab, pct(xs, 0.9))
    add("workflow_decision_answer_seconds_count", {}, len(answers))
    add("workflow_decision_answer_seconds_p50", {}, pct(answers, 0.5))
    add("workflow_decision_answer_seconds_p90", {}, pct(answers, 0.9))
    add("workflow_human_queue", {}, len(human))
    gate_counts = {}
    for g in gates:
        if g.get("status", "open") == "open":
            k = g.get("await_type") or g.get("gate_type") or "gate"
            gate_counts[k] = gate_counts.get(k, 0) + 1
    for k, v in gate_counts.items():
        add("workflow_gates_open", {"type": k}, v)
    if not any(m == "workflow_stale_in_progress" for m, _, _ in p):
        add("workflow_stale_in_progress", {}, 0)
    add("workflow_exporter_last_success_timestamp_seconds", {}, now)
    return p


def to_otlp(points, now_ns):
    by_name = {}
    for name, labels, value in points:
        by_name.setdefault(name, []).append({
            "asDouble": float(value), "timeUnixNano": str(now_ns),
            "attributes": [{"key": k, "value": {"stringValue": str(v)}} for k, v in labels.items()],
        })
    return {"resourceMetrics": [{
        "resource": {"attributes": [{"key": "service.name", "value": {"stringValue": "bd-workflow-exporter"}}]},
        "scopeMetrics": [{"scope": {"name": "bd-workflow-exporter"},
                          "metrics": [{"name": n, "gauge": {"dataPoints": dps}} for n, dps in by_name.items()]}],
    }]}


def collect(repo, now):
    root = Path(repo).resolve()
    beads = bd(repo, "list", "--status=all", "--limit", "0")
    human = bd(repo, "human", "list")
    gates = bd(repo, "gate", "list")
    return derive(root.name, beads, human, gates, load_formulas(root), now)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--endpoint", default=os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4318"))
    ap.add_argument("--print", action="store_true", help="write OTLP JSON to stdout instead of pushing")
    ap.add_argument("repos", nargs="+")
    a = ap.parse_args()
    now = time.time()
    points, ok = [], 0
    for repo in a.repos:
        try:
            points += collect(repo, now); ok += 1
        except Exception as e:  # one bad repo must not stop the others
            print(f"exporter: {repo}: {e}", file=sys.stderr)
    doc = to_otlp(points, int(now * 1e9))
    if a.print:
        json.dump(doc, sys.stdout, indent=1); print()
    else:
        req = urllib.request.Request(a.endpoint.rstrip("/") + "/v1/metrics", data=json.dumps(doc).encode(),
                                     headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=10) as r:
            print(f"exporter: pushed {len(points)} points for {ok}/{len(a.repos)} repos ({r.status})")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests**

Run: `chmod +x bd-workflow-exporter.py && python3 -m unittest test.test_exporter -v 2>&1 | tail -3`
Expected: `OK` (8 tests). If `test_durations` fails on `approve-approach`, check that human steps use `created_at` even when `started_at` exists.

- [ ] **Step 5: systemd units**

```bash
mkdir -p systemd
cat > systemd/agent-baseline-exporter.service <<'EOF'
[Unit]
Description=agent-baseline beads workflow exporter
[Service]
Type=oneshot
EnvironmentFile=@HERE@/.env
ExecStart=/bin/sh -c 'python3 @HERE@/bd-workflow-exporter.py --endpoint "${OTEL_EXPORTER_OTLP_ENDPOINT:-http://localhost:4318}" $REPOS'
EOF
cat > systemd/agent-baseline-exporter.timer <<'EOF'
[Unit]
Description=agent-baseline beads workflow exporter (5 min)
[Timer]
OnBootSec=2min
OnUnitActiveSec=5min
[Install]
WantedBy=timers.target
EOF
```

- [ ] **Step 6: Real run against both repos, then install the timer**

```bash
cd ~/code/agent-baseline/observability
python3 bd-workflow-exporter.py --print ~/code/theostack/theostack-go | python3 -c 'import json,sys;d=json.load(sys.stdin);print(len(d["resourceMetrics"][0]["scopeMetrics"][0]["metrics"]),"metrics")'
python3 bd-workflow-exporter.py ~/code/theostack/theostack-go ~/code/theostack/theostack-node
sleep 15; curl -s 'http://127.0.0.1:9090/api/v1/query?query=workflow_human_queue' | python3 -c 'import json,sys;print(json.load(sys.stdin)["data"]["result"])'
./setup.sh install-timer
```
Expected: `>= 6 metrics`; `exporter: pushed N points for 2/2 repos (200)`; the Prometheus query returns one series per repo; timer active.

- [ ] **Step 7: Commit**

```bash
cd ~/code/agent-baseline && git add -A && git commit -m "feat(observability): beads workflow exporter with systemd timer

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 3: Claude Code → stack, repo attribute in settings

**Files:**
- Modify: `render.py` (`merge_settings`), `test/test_render.py`, `test/selftest.py`, `apply.sh` (pass project name to render)

**Interfaces:**
- `render.py render DIR [--overlay F] [--project NAME]` → `.claude/settings.json` gets `env.OTEL_RESOURCE_ATTRIBUTES = "repo=<NAME>"` (fourth owned key; other `env` entries preserved).

- [ ] **Step 1: Tests first**

In `test/test_render.py` `Settings.test_merge_preserves_foreign_keys`, write the file with `"env": {"FOO": "1"}` and call `r.merge_settings(p, ["b","a"], ["p@x"], project="demo")`; add:
```python
            self.assertEqual(s["env"], {"FOO": "1", "OTEL_RESOURCE_ATTRIBUTES": "repo=demo"})
```
In `test/selftest.py` after the settings asserts add:
```python
assert s["env"]["OTEL_RESOURCE_ATTRIBUTES"] == "repo=fixture", s
```
Run: `cd ~/code/agent-baseline && python3 -m unittest 2>&1 | tail -1` → `FAILED`.

- [ ] **Step 2: Implement**

`render.py`:
```python
def merge_settings(path, mcp_names, plugins, project=None):
    ...
    d["enabledPlugins"] = {**d.get("enabledPlugins", {}), **{p: True for p in plugins}}  # add, never drop
    if project:
        d["env"] = {**d.get("env", {}), "OTEL_RESOURCE_ATTRIBUTES": f"repo={project}"}
```
and in `main`: `project = argv[argv.index("--project") + 1] if "--project" in argv else None`, pass `project=project`.

`apply.sh` pipeline: change the render call to
```bash
  python3 "$here/render.py" render "$t" ${overlay_json:+--overlay "$overlay_json"} --project "${answers[PROJECT_NAME]:-$(basename "$dir")}"
```
(`--check` copies use the same answers, so the value is stable.)

Run: `python3 -m unittest 2>&1 | tail -1 && ./apply.sh --self-test` → `OK`, `selftest: ok`.

- [ ] **Step 3: Verify a real Claude Code session lands in Prometheus**

```bash
source ~/code/agent-baseline/observability/env.sh
cd ~/code/theostack/theostack-go && OTEL_RESOURCE_ATTRIBUTES=repo=theostack-go claude -p 'reply with the single word ok' --model haiku
sleep 20
curl -s 'http://127.0.0.1:9090/api/v1/label/__name__/values' | python3 -c 'import json,sys;print([n for n in json.load(sys.stdin)["data"] if n.startswith("claude_code")])'
curl -s 'http://127.0.0.1:9090/api/v1/query?query={__name__=~"claude_code_cost_usage.*",repo="theostack-go"}' | python3 -c 'import json,sys;print(len(json.load(sys.stdin)["data"]["result"]),"series with repo label")'
curl -s -G 'http://127.0.0.1:3100/loki/api/v1/query_range' --data-urlencode 'query={service_name="claude-code"} |= "claude_code.api_request"' --data-urlencode 'limit=1' | python3 -c 'import json,sys;print(len(json.load(sys.stdin)["data"]["result"]),"log streams")'
```
Expected: a list of `claude_code_*` names; `>= 1 series with repo label` (if 0, the transform processor did not apply — see Task 1 Step 5 fallback); `1 log streams` (if 0, run the same query with only `{service_name="claude-code"}`, read one raw line, and note where the event name lives — body or an attribute such as `event_name` — then adjust the `|=` filters in Task 4 and QUERIES.md to match). **Record the exact metric names printed** — Task 4's dashboards use regexes, but README's QUERIES.md should quote the real names.

- [ ] **Step 4: Commit**

```bash
git add -A && git commit -m "feat: repo resource attribute in .claude/settings.json env

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 4: Dashboards

**Files:**
- Create: `observability/grafana/workflows.json`, `observability/grafana/agent-activity.json`

- [ ] **Step 1: workflows.json**

```json
{
  "uid": "agent-workflows", "title": "Workflows (beads)", "schemaVersion": 39, "version": 1, "editable": true,
  "time": {"from": "now-7d", "to": "now"}, "refresh": "1m", "tags": ["agent-baseline"],
  "templating": {"list": [{"name": "repo", "type": "query", "datasource": {"type": "prometheus", "uid": "prometheus"},
    "query": "label_values(workflow_human_queue, repo)", "refresh": 2, "includeAll": true, "multi": true, "current": {"text": "All", "value": "$__all"}}]},
  "panels": [
    {"id": 1, "type": "stat", "title": "Waiting on a human", "gridPos": {"x": 0, "y": 0, "w": 6, "h": 4},
     "datasource": {"type": "prometheus", "uid": "prometheus"},
     "targets": [{"refId": "A", "expr": "sum(workflow_human_queue{repo=~\"$repo\"})"}]},
    {"id": 2, "type": "stat", "title": "Open decisions", "gridPos": {"x": 6, "y": 0, "w": 6, "h": 4},
     "datasource": {"type": "prometheus", "uid": "prometheus"},
     "targets": [{"refId": "A", "expr": "sum(workflow_decisions_total{repo=~\"$repo\",status=\"open\"})"}]},
    {"id": 3, "type": "stat", "title": "Decision answer p50 (h)", "gridPos": {"x": 12, "y": 0, "w": 6, "h": 4},
     "datasource": {"type": "prometheus", "uid": "prometheus"}, "fieldConfig": {"defaults": {"decimals": 1}},
     "targets": [{"refId": "A", "expr": "max(workflow_decision_answer_seconds_p50{repo=~\"$repo\"}) / 3600"}]},
    {"id": 4, "type": "stat", "title": "Stale in-progress (>24h)", "gridPos": {"x": 18, "y": 0, "w": 6, "h": 4},
     "datasource": {"type": "prometheus", "uid": "prometheus"},
     "targets": [{"refId": "A", "expr": "sum(workflow_stale_in_progress{repo=~\"$repo\"})"}]},
    {"id": 5, "type": "timeseries", "title": "Molecules by formula and status", "gridPos": {"x": 0, "y": 4, "w": 12, "h": 8},
     "datasource": {"type": "prometheus", "uid": "prometheus"},
     "targets": [{"refId": "A", "expr": "sum by (formula, status) (workflow_molecules{repo=~\"$repo\"})", "legendFormat": "{{formula}} {{status}}"}]},
    {"id": 6, "type": "bargauge", "title": "Step duration p50 (h)", "gridPos": {"x": 12, "y": 4, "w": 12, "h": 8},
     "datasource": {"type": "prometheus", "uid": "prometheus"}, "options": {"orientation": "horizontal", "displayMode": "gradient"},
     "fieldConfig": {"defaults": {"decimals": 1}},
     "targets": [{"refId": "A", "instant": true, "expr": "max by (formula, step, human) (workflow_step_duration_seconds_p50{repo=~\"$repo\"}) / 3600", "legendFormat": "{{formula}}/{{step}}{{human}}"}]},
    {"id": 7, "type": "table", "title": "Where work sits (open + in progress steps)", "gridPos": {"x": 0, "y": 12, "w": 12, "h": 8},
     "datasource": {"type": "prometheus", "uid": "prometheus"},
     "targets": [{"refId": "A", "instant": true, "format": "table", "expr": "sum by (repo, formula, step, status, human) (workflow_steps{repo=~\"$repo\",status!=\"closed\"})"}],
     "transformations": [{"id": "organize", "options": {"excludeByName": {"Time": true}}}]},
    {"id": 8, "type": "piechart", "title": "Bugs closed: bugfix formula vs plain", "gridPos": {"x": 12, "y": 12, "w": 6, "h": 8},
     "datasource": {"type": "prometheus", "uid": "prometheus"},
     "targets": [{"refId": "A", "instant": true, "expr": "sum by (via) (workflow_bugs_closed_total{repo=~\"$repo\"})", "legendFormat": "{{via}}"}]},
    {"id": 9, "type": "stat", "title": "Gates open", "gridPos": {"x": 18, "y": 12, "w": 6, "h": 8},
     "datasource": {"type": "prometheus", "uid": "prometheus"},
     "targets": [{"refId": "A", "expr": "sum by (type) (workflow_gates_open{repo=~\"$repo\"})", "legendFormat": "{{type}}"}]}
  ]
}
```

- [ ] **Step 2: agent-activity.json**

```json
{
  "uid": "agent-activity", "title": "Agent activity & cost", "schemaVersion": 39, "version": 1, "editable": true,
  "time": {"from": "now-7d", "to": "now"}, "refresh": "1m", "tags": ["agent-baseline"],
  "templating": {"list": [{"name": "repo", "type": "query", "datasource": {"type": "prometheus", "uid": "prometheus"},
    "query": "label_values({__name__=~\"claude_code_cost_usage.*\"}, repo)", "refresh": 2, "includeAll": true, "multi": true, "current": {"text": "All", "value": "$__all"}}]},
  "panels": [
    {"id": 1, "type": "stat", "title": "Cost, last 24h (USD)", "gridPos": {"x": 0, "y": 0, "w": 6, "h": 4},
     "datasource": {"type": "prometheus", "uid": "prometheus"}, "fieldConfig": {"defaults": {"decimals": 2, "unit": "currencyUSD"}},
     "targets": [{"refId": "A", "expr": "sum(increase({__name__=~\"claude_code_cost_usage.*\",repo=~\"$repo\"}[24h]))"}]},
    {"id": 2, "type": "stat", "title": "Sessions, last 24h", "gridPos": {"x": 6, "y": 0, "w": 6, "h": 4},
     "datasource": {"type": "prometheus", "uid": "prometheus"},
     "targets": [{"refId": "A", "expr": "sum(increase({__name__=~\"claude_code_session_count.*\",repo=~\"$repo\"}[24h]))"}]},
    {"id": 3, "type": "stat", "title": "Subagent share of cost (24h)", "gridPos": {"x": 12, "y": 0, "w": 6, "h": 4},
     "datasource": {"type": "prometheus", "uid": "prometheus"}, "fieldConfig": {"defaults": {"unit": "percentunit", "decimals": 0}},
     "targets": [{"refId": "A", "expr": "sum(increase({__name__=~\"claude_code_cost_usage.*\",repo=~\"$repo\",query_source=\"subagent\"}[24h])) / sum(increase({__name__=~\"claude_code_cost_usage.*\",repo=~\"$repo\"}[24h]))"}]},
    {"id": 4, "type": "stat", "title": "Commits / PRs (24h)", "gridPos": {"x": 18, "y": 0, "w": 6, "h": 4},
     "datasource": {"type": "prometheus", "uid": "prometheus"},
     "targets": [{"refId": "A", "expr": "sum(increase({__name__=~\"claude_code_commit_count.*\",repo=~\"$repo\"}[24h]))", "legendFormat": "commits"},
                 {"refId": "B", "expr": "sum(increase({__name__=~\"claude_code_pull_request_count.*\",repo=~\"$repo\"}[24h]))", "legendFormat": "PRs"}]},
    {"id": 5, "type": "timeseries", "title": "Cost per day by model", "gridPos": {"x": 0, "y": 4, "w": 12, "h": 8},
     "datasource": {"type": "prometheus", "uid": "prometheus"}, "fieldConfig": {"defaults": {"unit": "currencyUSD"}},
     "options": {"legend": {"displayMode": "table", "placement": "right"}},
     "targets": [{"refId": "A", "expr": "sum by (model) (increase({__name__=~\"claude_code_cost_usage.*\",repo=~\"$repo\"}[1d]))", "legendFormat": "{{model}}"}]},
    {"id": 6, "type": "timeseries", "title": "Tokens per hour by type", "gridPos": {"x": 12, "y": 4, "w": 12, "h": 8},
     "datasource": {"type": "prometheus", "uid": "prometheus"},
     "targets": [{"refId": "A", "expr": "sum by (type) (increase({__name__=~\"claude_code_token_usage.*\",repo=~\"$repo\"}[1h]))", "legendFormat": "{{type}}"}]},
    {"id": 7, "type": "timeseries", "title": "Tool results per hour (Loki)", "gridPos": {"x": 0, "y": 12, "w": 12, "h": 8},
     "datasource": {"type": "loki", "uid": "loki"},
     "targets": [{"refId": "A", "expr": "sum by (tool_name) (count_over_time({service_name=\"claude-code\"} |= \"claude_code.tool_result\" | logfmt | keep tool_name [1h]))", "legendFormat": "{{tool_name}}"}]},
    {"id": 8, "type": "logs", "title": "Subagent runs (model, tokens)", "gridPos": {"x": 12, "y": 12, "w": 12, "h": 8},
     "datasource": {"type": "loki", "uid": "loki"}, "options": {"wrapLogMessage": true, "dedupStrategy": "none"},
     "targets": [{"refId": "A", "expr": "{service_name=\"claude-code\"} |= \"claude_code.subagent_completed\""}]}
  ]
}
```

- [ ] **Step 3: Load and check**

```bash
cd ~/code/agent-baseline/observability && for f in grafana/*.json; do python3 -c "import json,sys;json.load(open(sys.argv[1]))" "$f" && echo "ok $f"; done
docker compose restart lgtm && sleep 15
curl -s -u "admin:$(grep GRAFANA_ADMIN_PASSWORD .env | cut -d= -f2)" 'http://127.0.0.1:3000/api/search?type=dash-db' | python3 -c 'import json,sys;print([d["uid"] for d in json.load(sys.stdin)])'
```
Expected: both JSON files parse; the search lists `agent-workflows` and `agent-activity`. Open http://127.0.0.1:3000/d/agent-workflows — the "Waiting on a human" stat shows a number (0 is fine); if the Loki panels show "parse error", change `| logfmt` to `| json` (the exact log encoding depends on the Loki OTLP mapping — check one raw line in Explore first).

- [ ] **Step 4: Commit**

```bash
cd ~/code/agent-baseline && git add -A && git commit -m "feat(observability): workflows and agent-activity dashboards

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 5: QUERIES.md, README, nix notes, push

**Files:**
- Create: `observability/QUERIES.md`, `observability/README.md`
- Modify: `README.md` (one "Observability" paragraph pointing at `observability/README.md`)

- [ ] **Step 1: QUERIES.md** — replace `claude_code_cost_usage.*` with the exact names recorded in Task 3 Step 3 where you can.

```markdown
# Canned queries

Prometheus (http://127.0.0.1:9090) unless marked Loki (http://127.0.0.1:3100).
Agents: use the `grafana` MCP server (`query_prometheus`, `query_loki_logs`) with these.

| Question | Query |
|---|---|
| Cost per repo, last 24h | `sum by (repo) (increase({__name__=~"claude_code_cost_usage.*"}[24h]))` |
| Cost by model, 7d | `sum by (model) (increase({__name__=~"claude_code_cost_usage.*"}[7d]))` |
| Subagent share of spend | `sum(increase({__name__=~"claude_code_cost_usage.*",query_source="subagent"}[7d])) / sum(increase({__name__=~"claude_code_cost_usage.*"}[7d]))` |
| Which subagents ran on which model (Loki) | `{service_name="claude-code"} \|= "claude_code.subagent_completed"` |
| Sessions that ran a forbidden bd export (Loki) | `{service_name="claude-code"} \|= "claude_code.tool_result" \|= "bd export" \|= " -o "` |
| Sessions that switched a shared checkout (Loki) | `{service_name="claude-code"} \|= "claude_code.tool_result" \|~ "git (checkout\|switch) "` |
| Molecules poured per day (Loki) | `sum(count_over_time({service_name="claude-code"} \|= "bd mol pour" [1d]))` |
| What I asked, with cost (Loki) | `{service_name="claude-code"} \|= "claude_code.user_prompt"` then `\|= "claude_code.api_request"` on the same `session.id` |
| Human queue now | `sum by (repo) (workflow_human_queue)` |
| Decision answer p50 (h) | `workflow_decision_answer_seconds_p50 / 3600` |
| Slowest step per formula (h) | `topk(3, workflow_step_duration_seconds_p50 / 3600)` |
| Bugfix adoption | `sum by (via) (workflow_bugs_closed_total)` |
| Stale in-progress beads | `workflow_stale_in_progress` |
| Exporter alive (s since last success) | `time() - workflow_exporter_last_success_timestamp_seconds` |
```

- [ ] **Step 2: observability/README.md**

```markdown
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

## Limits (v1)

Human-step durations are measured from pour, not from when the step became
ready. Codex event names differ from Claude's; the dashboards are Claude-first.
```

- [ ] **Step 3: Root README paragraph, push**

Append to `README.md` before "## Maintain the template":
```markdown
## Observability

`observability/` runs a local OTel stack (Grafana + Prometheus + Loki via
`otel-lgtm`) fed by Claude Code, Codex, bd and a beads workflow exporter, with
an MCP server so agents can query it. See `observability/README.md`.
```
```bash
cd ~/code/agent-baseline && ./apply.sh --self-test && python3 -m unittest 2>&1 | tail -1 && (cd observability && python3 -m unittest test.test_exporter 2>&1 | tail -1) && git add -A && git commit -m "docs(observability): README, canned queries

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>" && git push
```

---

### Task 6: Rollout — repo attribute PRs, nix touchpoints handed off

- [ ] **Step 1: Apply to both repos** (fresh `.worktrees/` branches from `origin/main` / `origin/dev`, per PRIME):

```bash
cd ~/code/theostack && export SSH_AUTH_SOCK=~/.1password/agent.sock && source ~/.zshrc.mcp-secrets
git -C theostack-go fetch -q origin main && git -C theostack-go worktree add -q .worktrees/otel -b chore/otel-repo-attr origin/main
git -C theostack-node fetch -q origin dev && git -C theostack-node worktree add -q .worktrees/otel -b chore/otel-repo-attr origin/dev
for r in go node; do (cd theostack-$r/.worktrees/otel && ~/code/agent-baseline/apply.sh . | tail -1 && git status --short && git add -A && git commit -q -m "chore: OTEL_RESOURCE_ATTRIBUTES repo label for Claude Code telemetry

Applies agent-baseline $(git -C ~/code/agent-baseline rev-parse --short HEAD).

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>" && git push -q -u origin chore/otel-repo-attr && gh pr create --base $([ $r = go ] && echo main || echo dev) --title "chore: repo label for agent telemetry" --body "Adds \`env.OTEL_RESOURCE_ATTRIBUTES=repo=theostack-$r\` to \`.claude/settings.json\` so Claude Code metrics carry the repo. Applies agent-baseline \`$(git -C ~/code/agent-baseline rev-parse --short HEAD)\`.

🤖 Generated with [Claude Code](https://claude.com/claude-code)"); done
```
Expected: each diff is `.agent-baseline` + `.claude/settings.json` (one `env` key); two PR URLs.

- [ ] **Step 2: Hand off the two nix lines** (not implemented here): in `home-manager/linux/default.nix` zsh init, after the sops exports: `[ -f "$HOME/code/agent-baseline/observability/env.sh" ] && source "$HOME/code/agent-baseline/observability/env.sh"`; and in the Claude MCP activation block + `_mixins/development/mcp/default.nix`: `grafana = { url = "http://localhost:8000/mcp"; }`.

- [ ] **Step 3: End-to-end acceptance**

After `home-manager switch` and a restart of Claude Code: open a session in theostack-go, run any bd command, then check the *Agent activity* dashboard shows the session under `repo=theostack-go` and the *Workflows* dashboard shows the human queue; ask Claude "using the grafana MCP, what did I spend today per model?" and get a PromQL-backed answer.
