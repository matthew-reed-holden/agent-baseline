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
