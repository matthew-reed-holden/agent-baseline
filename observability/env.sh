# Producer env contract. Source from your shell (nix: after the sops exports).
# Another machine sets OTEL_EXPORTER_OTLP_ENDPOINT to this host's Tailscale address first.
export OTEL_EXPORTER_OTLP_ENDPOINT="${OTEL_EXPORTER_OTLP_ENDPOINT:-http://localhost:4318}"
# Claude Code
export CLAUDE_CODE_ENABLE_TELEMETRY=1
export OTEL_METRICS_EXPORTER=otlp
export OTEL_LOGS_EXPORTER=otlp
export OTEL_EXPORTER_OTLP_PROTOCOL=http/protobuf
export OTEL_METRIC_EXPORT_INTERVAL=10000
# Prometheus's OTLP receiver drops delta-temporality sums; Claude Code defaults to delta.
export OTEL_EXPORTER_OTLP_METRICS_TEMPORALITY_PREFERENCE=cumulative
export OTEL_LOGS_EXPORT_INTERVAL=5000
export OTEL_LOG_TOOL_DETAILS=1
export OTEL_LOG_USER_PROMPTS=1
# bd (explicit opt-in; bd ignores OTEL_* alone)
export BD_OTEL_ENABLED=true
export OTEL_EXPORTER_OTLP_METRICS_ENDPOINT="$OTEL_EXPORTER_OTLP_ENDPOINT/v1/metrics"
# repo label for every process launched from here (Claude, Codex, bd):
# the git toplevel's basename, recomputed on every cd. Outside a repo it is unset.
_agent_repo_attr() {
  # the main clone's .git is shared by every worktree (.worktrees/<slug> or ../repo-slug)
  local common; common=$(git rev-parse --path-format=absolute --git-common-dir 2>/dev/null)
  if [[ -n $common ]]; then common=${common%/.git}; export OTEL_RESOURCE_ATTRIBUTES="repo=${common##*/}"
  else unset OTEL_RESOURCE_ATTRIBUTES; fi
}
if [[ -n ${ZSH_VERSION:-} ]]; then
  autoload -Uz add-zsh-hook && add-zsh-hook chpwd _agent_repo_attr
fi
_agent_repo_attr
