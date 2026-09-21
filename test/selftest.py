#!/usr/bin/env python3
"""apply.sh self-test: apply test/fixture into a temp dir and assert the outcome."""
import json, os, shutil, subprocess, sys, tempfile
from pathlib import Path

here = Path(sys.argv[1]).resolve()
tmp = Path(tempfile.mkdtemp())
shutil.copytree(here / "test" / "fixture", tmp, dirs_exist_ok=True)
subprocess.run(["git", "init", "-q"], cwd=tmp, check=True)
env = {k: v for k, v in os.environ.items() if k not in ("DATABASE_URL", "API_TOKEN")}


def apply(*args):
    return subprocess.run([str(here / "apply.sh"), *args, str(tmp)], env=env, capture_output=True, text=True)


r = apply("--stack", "go", "--yes", "--var", "PROJECT_NAME=fixture", "--var", "PROJECT_SUMMARY=A fixture.")
assert r.returncode == 0, r.stdout + r.stderr

# seeded: AGENTS.md created with vars; existing .mcp.json left alone (overlay seed skipped)
a = (tmp / "AGENTS.md").read_text()
assert a.startswith("# fixture\n\nA fixture.\n") and "{{" not in a and "PR into `main`" in a, a
assert set(json.loads((tmp / ".mcp.json").read_text())["mcpServers"]) == {"db", "api"}
assert (tmp / "docs" / "README.md").exists() and (tmp / "agents" / "README.md").exists()

# owned
assert os.readlink(tmp / "CLAUDE.md") == "AGENTS.md"
assert "PR-only" in (tmp / ".beads" / "PRIME.md").read_text()
assert (tmp / ".beads" / "formulas" / ".gitkeep").exists()
assert (tmp / ".codex" / "hooks.json").exists() and (tmp / ".agents" / "skills" / "beads" / "SKILL.md").exists()
assert "agent.profile: team-maintainer" in (tmp / ".beads" / "config.yaml").read_text()

# merged settings: foreign key preserved, owned keys set
s = json.loads((tmp / ".claude" / "settings.json").read_text())
assert s["permissions"] == {"allow": ["Bash(go test *)"]}, s
assert s["enabledMcpjsonServers"] == ["api", "db"] and s["enabledPlugins"] == {"gopls-lsp@claude-plugins-official": True}
assert s["hooks"]["SessionStart"][0]["hooks"][0]["command"] == "bd prime --hook-json"

# generated
c = (tmp / ".codex" / "config.toml").read_text()
assert 'bearer_token_env_var = "API_TOKEN"' in c and 'POSTGRES_CONNECTION_STRING = "postgres://localhost:5432/postgres"' in c and "[features]" in c, c
o = json.loads((tmp / "opencode.json").read_text())["mcp"]
assert o["db"]["environment"]["POSTGRES_CONNECTION_STRING"] == "{env:DATABASE_URL}" and o["db"]["command"][0] == "npx"
assert o["api"]["headers"]["Authorization"] == "Bearer {env:API_TOKEN}"

# stamp
st = json.loads((tmp / ".agent-baseline").read_text())
assert st["stack"] == "go" and st["answers"]["PROJECT_SUMMARY"] == "A fixture." and st["answers"]["DATABASE_URL_DEFAULT"]

# --check: env missing -> exit 1 naming it; env present -> clean
r = apply("--check"); assert r.returncode == 1 and "✗ API_TOKEN" in r.stdout, r.stdout + r.stderr
env["API_TOKEN"] = "y"
r = apply("--check"); assert r.returncode == 0 and "up to date" in r.stdout, r.stdout + r.stderr

# --check: a hand edit to a generated file is drift
(tmp / "opencode.json").write_text("{}\n")
r = apply("--check"); assert r.returncode == 1 and "opencode.json" in r.stdout, r.stdout + r.stderr

# re-apply repairs it and asks nothing (answers come from the stamp)
r = apply(); assert r.returncode == 0 and "mcp" in (tmp / "opencode.json").read_text(), r.stdout + r.stderr

# hard error from render.py surfaces with a non-zero exit
bad = json.loads((tmp / ".mcp.json").read_text()); bad["mcpServers"]["db"]["env"] = {"PGURL": "${DATABASE_URL}"}
(tmp / ".mcp.json").write_text(json.dumps(bad))
r = apply(); assert r.returncode != 0 and "db: env PGURL" in r.stderr, r.stdout + r.stderr

# non-TTY without answers or --yes is an error
shutil.rmtree(tmp); tmp.mkdir(); shutil.copytree(here / "test" / "fixture", tmp, dirs_exist_ok=True)
subprocess.run(["git", "init", "-q"], cwd=tmp, check=True)
r = apply(); assert r.returncode == 2 and "unanswered var PROJECT_NAME" in r.stderr, r.stdout + r.stderr

shutil.rmtree(tmp)
print("selftest: ok")
