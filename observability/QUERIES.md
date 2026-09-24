# Canned queries

Prometheus (http://127.0.0.1:9090) unless marked Loki (http://127.0.0.1:3100).
Agents: use the `grafana` MCP server (`query_prometheus`, `query_loki_logs`).

Two things to know before writing new ones:

- **Claude Code counters are per `session_id` and cumulative.** Totals over a
  window are `sum(max_over_time(x[window]))`; `increase()` misses each
  session's first export.
- **Claude Code events are Loki structured metadata**, not log text: the line
  is just `claude_code.<event>`; filter with `| event_name="tool_result"`,
  `| repo="theostack-go"`, `| session_id="…"`, `| tool_name="Bash"`.

| Question | Query |
|---|---|
| Cost per repo, 24h | `sum by (repo) (max_over_time(claude_code_cost_usage_USD_total[24h]))` |
| Cost by model, 7d | `sum by (model) (max_over_time(claude_code_cost_usage_USD_total[7d]))` |
| Subagent share of spend, 7d | `sum(max_over_time(claude_code_cost_usage_USD_total{query_source="subagent"}[7d])) / sum(max_over_time(claude_code_cost_usage_USD_total[7d]))` |
| Most expensive sessions, 7d | `topk(10, sum by (session_id, repo) (max_over_time(claude_code_cost_usage_USD_total[7d])))` |
| What was asked in a session (Loki) | `{service_name="claude-code"} \| session_id="<id>" \| event_name="user_prompt"` |
| Subagent runs with model (Loki) | `{service_name="claude-code"} \| event_name="subagent_completed"` |
| Tool failures by tool, 24h (Loki) | `sum by (tool_name) (count_over_time({service_name="claude-code"} \| event_name="tool_result" \| success="false" [24h]))` |
| Forbidden `bd export -o` (Loki) | `{service_name="claude-code"} \| event_name="tool_result" \| tool_name="Bash" \| tool_input=~".*bd export.* -o .*"` |
| Shared-checkout switches (Loki) | `{service_name="claude-code"} \| event_name="tool_result" \| tool_name="Bash" \| tool_input=~".*git (checkout\|switch) .*"` |
| Molecules poured (Loki) | `sum by (repo) (count_over_time({service_name="claude-code"} \| event_name="tool_result" \| tool_input=~".*bd mol pour.*" [7d]))` |
| Human queue now | `sum by (repo) (workflow_human_queue)` |
| Where work sits | `sum by (repo, formula, step) (workflow_steps{status!="closed"})` |
| Decision answer p50 (h) | `workflow_decision_answer_seconds_p50 / 3600` |
| Slowest steps (h) | `topk(5, workflow_step_duration_seconds_p50 / 3600)` |
| Bugfix adoption | `sum by (repo, via) (workflow_bugs_closed_total)` |
| Exporter freshness (s) | `time() - workflow_exporter_last_success_timestamp_seconds` |
| Codex tokens by model, 24h (Loki) | `sum by (model) (sum_over_time({service_name="codex_exec"} \| event_name="codex.api_request" \| unwrap output_token_count [24h]))` |
