#!/usr/bin/env bash
# agent-baseline apply: copy owned/seeded files, render harness configs, check env, stamp.
set -euo pipefail
here=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)

usage() {
  cat <<USAGE
usage: apply.sh [--stack go|node] [--check] [--yes] [--var NAME=VALUE]... [--self-test] [DIR]
  --stack S    layer overlays/S on top of baseline (remembered in .agent-baseline)
  --check      report drift (diff + env check); exit 1 if any; changes nothing
  --yes        take defaults for unanswered vars (required when not on a TTY)
  --var K=V    answer a var explicitly (repeatable)
  --self-test  run test/selftest.py against test/fixture in a temp dir
USAGE
}

stack="" check=0 yes=0 selftest=0 dir="."
declare -A var_cli=()
while [[ $# -gt 0 ]]; do
  case $1 in
    --stack) stack=$2; shift 2 ;;
    --check) check=1; shift ;;
    --yes) yes=1; shift ;;
    --var) var_cli[${2%%=*}]=${2#*=}; shift 2 ;;
    --self-test) selftest=1; shift ;;
    -h|--help) usage; exit 0 ;;
    -*) echo "apply.sh: unknown flag $1" >&2; usage >&2; exit 2 ;;
    *) dir=$1; shift ;;
  esac
done
(( selftest )) && exec python3 "$here/test/selftest.py" "$here"

dir=$(cd "$dir" && pwd)
git -C "$dir" rev-parse --is-inside-work-tree >/dev/null 2>&1 || { echo "apply.sh: $dir is not a git repo" >&2; exit 2; }
stamp="$dir/.agent-baseline"

# ---- stack + previous answers -------------------------------------------------
if [[ -z $stack && -f $stamp ]]; then
  stack=$(python3 -c 'import json,sys;print(json.load(open(sys.argv[1])).get("stack",""))' "$stamp")
fi
overlay_dir="$here/overlays/$stack" overlay_json=""
if [[ -n $stack ]]; then
  [[ -d $overlay_dir ]] || { echo "apply.sh: no overlay for stack '$stack'" >&2; exit 2; }
  overlay_json="$overlay_dir/overlay.json"
fi
declare -A answers=()
if [[ -f $stamp ]]; then
  while IFS=$'\t' read -r k v; do answers[$k]=$v; done < <(
    python3 -c 'import json,sys;[print(k,v,sep="\t") for k,v in json.load(open(sys.argv[1])).get("answers",{}).items()]' "$stamp")
fi

# ---- vars: baseline then overlay; cli > stamp > --yes default > prompt -------
var_specs=$(python3 - "$here/baseline/vars.json" "$overlay_json" <<'PY'
import json, os, sys
for p in sys.argv[1:]:
    if not p or not os.path.exists(p):
        continue
    doc = json.load(open(p))
    for v in (doc.get("vars", []) if isinstance(doc, dict) else doc):
        print(v["name"], v["prompt"], v.get("default", ""), sep="\t")
PY
)
while IFS=$'\t' read -r name prompt default; do
  [[ -n $name ]] || continue
  [[ $name == PROJECT_NAME && -z $default ]] && default=$(basename "$dir")
  if [[ -n ${var_cli[$name]:-} ]]; then answers[$name]=${var_cli[$name]}
  elif [[ -n ${answers[$name]:-} ]]; then :
  elif (( yes )); then answers[$name]=$default
  elif [[ -t 0 && $check == 0 ]]; then
    read -rp "$prompt [$default]: " reply </dev/tty; answers[$name]=${reply:-$default}
  else
    echo "apply.sh: unanswered var $name (use --var $name=... or --yes)" >&2; exit 2
  fi
done <<< "$var_specs"
ans_argv=(); for k in ${answers[@]+"${!answers[@]}"}; do ans_argv+=("$k=${answers[$k]}"); done

# ---- copy ------------------------------------------------------------------------
subst() {  # $1 src  $2 dst : copy with {{VAR}} substitution
  python3 - "$1" "$2" ${ans_argv[@]+"${ans_argv[@]}"} <<'PY'
import re, sys
src, dst = sys.argv[1], sys.argv[2]
ans = dict(a.split("=", 1) for a in sys.argv[3:])
text = open(src).read()
open(dst, "w").write(re.sub(r"\{\{([A-Z_][A-Z0-9_]*)\}\}", lambda m: ans.get(m.group(1), m.group(0)), text))
PY
}
copy_one() {  # $1 src  $2 dst  $3 owned|seeded
  local src=$1 dst=$2 mode=$3
  mkdir -p "$(dirname "$dst")"
  if [[ -L $src ]]; then ln -sfn "$(readlink "$src")" "$dst"
  elif [[ -d $src ]]; then
    if [[ $mode == owned ]]; then rm -rf "$dst"; cp -r "$src" "$dst"
    elif [[ ! -e $dst ]]; then cp -r "$src" "$dst"; fi
  elif [[ $mode == owned ]]; then cp -f "$src" "$dst"
  elif [[ ! -e $dst ]]; then subst "$src" "$dst"; fi
}
overlay_files() { [[ -n $stack ]] && find "$overlay_dir" -type f ! -name overlay.json -print0 || true; }

pipeline() {  # $1 target dir: copy + render
  local t=$1 path mode f
  while read -r path mode; do
    [[ -z $path || $path == \#* ]] && continue
    copy_one "$here/baseline/$path" "$t/$path" "$mode"
  done < "$here/manifest"
  while IFS= read -r -d '' f; do copy_one "$f" "$t/${f#"$overlay_dir/"}" seeded; done < <(overlay_files)
  if [[ -f $t/.beads/config.yaml ]] && ! grep -q '^agent.profile:' "$t/.beads/config.yaml"; then
    printf '\n# Agents commit/push feature branches and open PRs; merging is human-only (.beads/PRIME.md).\nagent.profile: team-maintainer\n' >> "$t/.beads/config.yaml"
  fi
  if ! grep -qsx '\.worktrees/\?' "$t/.gitignore"; then
    printf '\n# agent worktrees (PRIME.md -> Worktrees)\n.worktrees/\n' >> "$t/.gitignore"
  fi
  python3 "$here/render.py" render "$t" ${overlay_json:+--overlay "$overlay_json"}
}

# every path the pipeline may write, for --check
paths=(.codex/config.toml opencode.json .claude/settings.json .beads/config.yaml .gitignore .claude/agents .opencode/agents)
while read -r path mode; do [[ -z $path || $path == \#* ]] || paths+=("$path"); done < "$here/manifest"
while IFS= read -r -d '' f; do paths+=("${f#"$overlay_dir/"}"); done < <(overlay_files)

# ---- check ---------------------------------------------------------------------
if (( check )); then
  tmp=$(mktemp -d); trap 'rm -rf "$tmp"' EXIT
  for p in "${paths[@]}"; do
    [[ -e $dir/$p || -L $dir/$p ]] || continue
    mkdir -p "$tmp/$(dirname "$p")"; cp -a "$dir/$p" "$tmp/$p"
  done
  pipeline "$tmp"
  drift=0
  for p in "${paths[@]}"; do
    [[ -e $dir/$p || -L $dir/$p || -e $tmp/$p || -L $tmp/$p ]] || continue
    diff -ruN --no-dereference "$dir/$p" "$tmp/$p" || drift=1
  done
  echo "env check:"; python3 "$here/render.py" envcheck "$dir" || drift=1
  (( drift )) && { echo "apply.sh: drift detected" >&2; exit 1; }
  echo "apply.sh: up to date"; exit 0
fi

# ---- apply -----------------------------------------------------------------------
pipeline "$dir"
echo "env check:"; python3 "$here/render.py" envcheck "$dir" || true
python3 - "$stamp" "$(git -C "$here" rev-parse --short HEAD)" "$stack" ${ans_argv[@]+"${ans_argv[@]}"} <<'PY'
import datetime, json, sys
stamp, sha, stack, *answers = sys.argv[1:]
json.dump({"template": sha, "stack": stack, "answers": dict(a.split("=", 1) for a in answers),
           "applied_at": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")},
          open(stamp, "w"), indent=2)
open(stamp, "a").write("\n")
PY
echo "apply.sh: applied baseline $(git -C "$here" rev-parse --short HEAD)${stack:+ (+$stack)} to $dir"
