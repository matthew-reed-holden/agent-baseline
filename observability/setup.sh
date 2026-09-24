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
  mcp-token)  # Viewer service account for mcp-grafana; appends GRAFANA_MCP_TOKEN to .env
    set -a; . ./.env; set +a
    sa=$(curl -fs -u "admin:$GRAFANA_ADMIN_PASSWORD" -H 'Content-Type: application/json' -X POST http://127.0.0.1:3000/api/serviceaccounts -d '{"name":"mcp-grafana","role":"Viewer"}' | python3 -c 'import json,sys;print(json.load(sys.stdin)["id"])')
    tok=$(curl -fs -u "admin:$GRAFANA_ADMIN_PASSWORD" -H 'Content-Type: application/json' -X POST "http://127.0.0.1:3000/api/serviceaccounts/$sa/tokens" -d '{"name":"mcp"}' | python3 -c 'import json,sys;print(json.load(sys.stdin)["key"])')
    sed -i '/^GRAFANA_MCP_TOKEN=/d' .env; printf 'GRAFANA_MCP_TOKEN=%s\n' "$tok" >> .env
    docker compose up -d mcp-grafana
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
  *) echo "usage: setup.sh up|mcp-token|down|status|install-timer" >&2; exit 2 ;;
esac
