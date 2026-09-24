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
