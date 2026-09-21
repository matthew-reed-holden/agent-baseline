#!/usr/bin/env bash
# Pours both formulas into a scratch beads repo and asserts the human/agent split.
set -euo pipefail
here=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
command -v bd >/dev/null || { echo "formulas.sh: bd not installed, skipping"; exit 0; }
tmp=$(mktemp -d); trap 'rm -rf "$tmp"' EXIT
cd "$tmp" && git init -q && bd init --non-interactive >/dev/null 2>&1
mkdir -p .beads/formulas && cp "$here"/baseline/.beads/formulas/*.formula.toml .beads/formulas/

id() { python3 -c 'import json,sys;print(json.load(sys.stdin)["id_mapping"][sys.argv[1]])' "$1"; }
titles() { python3 -c 'import json,sys;print("\n".join(sorted(i["title"] for i in json.load(sys.stdin))))'; }
fail() { echo "formulas.sh: FAIL: $*" >&2; exit 1; }

# ---- feature ---------------------------------------------------------------------
pour=$(bd mol pour feature --var name=demo --var summary="a demo" --json 2>/dev/null)
brainstorm=$(echo "$pour" | id feature.brainstorm); merge=$(echo "$pour" | id feature.merge)
review=$(echo "$pour" | id feature.review-pr)
[[ $(bd ready --exclude-label human --json | titles) == "Brainstorm demo" ]] || fail "only brainstorm should be ready: $(bd ready --json | titles)"
bd close "$brainstorm" >/dev/null
[[ -z $(bd ready --exclude-label human --json | titles) ]] || fail "nothing agent-ready after brainstorm: $(bd ready --exclude-label human --json | titles)"
bd human list 2>/dev/null | grep -q "Approve approach for demo" || fail "approve-approach not in bd human list"
bd close "$(echo "$pour" | id feature.approve-approach)" "$(echo "$pour" | id feature.spec)" "$(echo "$pour" | id feature.approve-spec)" "$(echo "$pour" | id feature.plan)" "$(echo "$pour" | id feature.implement)" >/dev/null
bd gate create --type=gh:pr --await-id 1 --timeout 168h --blocks "$merge" >/dev/null
bd close "$review" >/dev/null
bd ready --exclude-label human --json | titles | grep -q "Merge demo" && fail "merge must be blocked by the gh:pr gate"
bd gate list 2>/dev/null | grep -qi "gh:pr" || fail "gh:pr gate missing from bd gate list"

# ---- bugfix -----------------------------------------------------------------------
bug=$(bd create --title "It breaks" -t bug -p 1 --json 2>/dev/null | python3 -c 'import json,sys;print(json.load(sys.stdin)["id"])')
pour=$(bd mol pour bugfix --var bug="$bug" --json 2>/dev/null)
[[ $(bd ready --exclude-label human --json | titles | grep -c "Reproduce $bug") == 1 ]] || fail "reproduce not ready"
bd close "$(echo "$pour" | id bugfix.reproduce)" "$(echo "$pour" | id bugfix.fix)" "$(echo "$pour" | id bugfix.review-pr)" "$(echo "$pour" | id bugfix.merge)" >/dev/null
bd human list 2>/dev/null | grep -q "Verify fix for $bug" || fail "verify not in bd human list"

echo "formulas.sh: ok"
