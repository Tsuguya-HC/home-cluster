#!/usr/bin/env python3
"""観点出し（#1081）: 実装フェーズが作った PR の事実を Jev に渡し、どの観点のレビューを起動するかを
ディレクトリで答える。LLM のエージェントは起動しない。

state の形（title / description / files / name_status / numstat / hunk_headers / flags）と
roles.json の閾値は、2026-09-25 の計測（#1081 のコメント）と対になっている。state を変えるなら
閾値を測り直すこと。
"""
import http.client
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

WORKSPACE = Path("/workspace")
RESULTS = Path("/results")
CONF = Path("/etc/review-planner")
SRC = Path("/tmp/src")
GH_KEY_FILE = Path("/github-gateway-key/key")
GW = "gh-ro.infra.tgy.io"
URL = "https://openrouter.ai/api/alpha/decisions"
MODEL = "typesafe/jev-1.13"
# Jev の上限は 32k トークン。計測と同じ切り詰め方。
DESCRIPTION_CHARS = 4000
HUNK_CHARS = 30000
HUNK_CHARS_RETRY = 8000

FLAG_PATTERNS = {
    "touches_tests": r"(^|/)(tests?|__tests__)/|_test\.|\.test\.|\.spec\.",
    "touches_deps": r"(^|/)(Cargo\.(toml|lock)|package\.json|pnpm-lock\.yaml|go\.(mod|sum)|requirements.*\.txt|pyproject\.toml|uv\.lock)$",
    "touches_ci": r"^\.github/",
    "touches_docs": r"\.md$|(^|/)docs/",
    "touches_security_config": r"netpol|ciliumnetworkpolicy|rbac|role|secret|securitypolicy|kyverno|policy",
}
TEST_PATH = re.compile(FLAG_PATTERNS["touches_tests"], re.I)
# ui は Jev に聞かず機械で決める: 画面を持つリポで、画面に触れたか、応答の形を変えたか。
UI_PATH = re.compile(r"(^|/)(ui|web|frontend)/|\.(tsx|jsx|vue|svelte|css|html)$")
RESPONSE_SHAPE = re.compile(r"Serialize|json!\(")


def escalate(msg):
    (WORKSPACE / "escalate" / "report.md").write_text(msg + "\n")
    sys.exit(0)


def run(*args, env=None, cwd=None, timeout=None):
    return subprocess.run(args, capture_output=True, text=True, check=True, env=env, cwd=cwd, timeout=timeout).stdout


def git(*args, timeout=None):
    return run("git", "-C", str(SRC), *args, timeout=timeout)


def read_input():
    try:
        spec = json.loads(os.environ.get("FLOW_INPUT") or "{}")
    except json.JSONDecodeError:
        escalate("spec.input が JSON として読めない。観点出しは行っていない。")
    repo, issue = str(spec.get("repo", "")), str(spec.get("issue", ""))
    m = re.fullmatch(r"Tsuguya-HC/([A-Za-z0-9._-]+)", repo)
    if not m or m.group(1) in (".", ".."):
        escalate("spec.input.repo の形が不正か、Tsuguya-HC 配下ではない。観点出しは行っていない。")
    if not issue.isdigit():
        escalate("spec.input.issue が数字ではない。観点出しは行っていない。")
    return repo, issue


def find_pr(repo):
    # 棚の番号は数値順に読む（辞書順では 10 が 2 より前に来る）。差し戻しの後は最後のものが最新。
    runs = sorted((p for p in RESULTS.glob("*/done/pr-url") if p.parent.parent.name.isdigit()),
                  key=lambda p: int(p.parent.parent.name))
    if not runs:
        escalate("レビュー対象の PR が棚（results/*/done/pr-url）に見つからない。観点出しは行っていない。")
    url = runs[-1].read_text().strip()
    m = re.fullmatch(rf"https://github\.com/{re.escape(repo)}/pull/(\d+)", url)
    if not m:
        escalate(f"棚の PR の URL が不正（{url}）。観点出しは行っていない。")
    return url, m.group(1)


def fetch(repo, pr, issue, key):
    # 鍵は argv に載せない。
    git_env = dict(os.environ, GIT_CONFIG_COUNT="1", GIT_CONFIG_KEY_0=f"http.https://{GW}/.extraheader",
                   GIT_CONFIG_VALUE_0=f"Authorization: token {key}")
    gh_env = dict(os.environ, GH_HOST=GW, GH_ENTERPRISE_TOKEN=key)
    try:
        run("git", "clone", "--quiet", f"https://{GW}/{repo}.git", str(SRC), env=git_env, timeout=180)
        run("git", "-C", str(SRC), "fetch", "--quiet", "origin", f"refs/pull/{pr}/head:pr", env=git_env, timeout=180)
        base = git("merge-base", "origin/main", "pr", timeout=180).strip()
        pr_json = json.loads(run("gh", "api", f"repos/{repo}/pulls/{pr}", env=gh_env, timeout=60))
        issue_json = json.loads(run("gh", "api", f"repos/{repo}/issues/{issue}", env=gh_env, timeout=60))
    except subprocess.TimeoutExpired as e:
        escalate(f"PR #{pr} の取り込みが時間切れ（{' '.join(e.cmd[:3])}、{e.timeout:.0f}秒）。観点出しは行っていない。")
    except subprocess.CalledProcessError as e:
        escalate(f"PR #{pr} の取り込みに失敗した（{' '.join(e.cmd[:3])}）。観点出しは行っていない。\n\n{e.stderr[-1000:]}")
    return base, pr_json, issue_json


def build_state(base, pr_json, issue_json):
    names = git("diff", "--name-status", base, "pr", timeout=60).strip().splitlines()
    files = [ln.split("\t")[-1] for ln in names]
    numstat = git("diff", "--numstat", base, "pr", timeout=60).strip().splitlines()
    hunks = [ln for ln in git("diff", "-U0", base, "pr", timeout=60).splitlines() if ln.startswith("@@") or ln.startswith("+++ ")]
    flags = {k: any(re.search(p, f, re.I) for f in files) for k, p in FLAG_PATTERNS.items()}
    return {
        # 実装フェーズの PR の題は「Implement #N」で何も言わないので、issue の題を使う。
        "title": issue_json.get("title") or "",
        "description": (pr_json.get("body") or "")[:DESCRIPTION_CHARS],
        "files": files,
        "name_status": names,
        "numstat": numstat,
        "hunk_headers": "\n".join(hunks)[:HUNK_CHARS],
        "flags": flags,
    }, files


def ask_jev(state, roles, key):
    questions = {
        r["name"]: {"type": "noul", "instructions": r["jev"]["instructions"],
                    "criteria": {"true": r["jev"]["true"], "false": r["jev"]["false"]}}
        for r in roles
    }
    err = None
    # timeout の値を smoke の実測で決め直すための記録。判定には使わない。
    start = time.monotonic()
    attempts = 0
    for _ in range(3):
        attempts += 1
        body = json.dumps({"model": MODEL, "state": state, "questions": questions}).encode()
        req = urllib.request.Request(URL, data=body, headers={
            "Authorization": f"Bearer {key}", "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                answers = json.load(r)["answers"]
            return {n: float(answers[n]["noul"]) for n in questions}, None, time.monotonic() - start, attempts
        except urllib.error.HTTPError as e:
            detail = e.read().decode(errors="replace")[:500]
            if e.code == 400 and "max_tokens" in detail and state["hunk_headers"] and len(state["hunk_headers"]) > HUNK_CHARS_RETRY:
                state = dict(state, hunk_headers=state["hunk_headers"][:HUNK_CHARS_RETRY])
                continue
            if e.code < 500 and e.code != 429:
                return None, f"HTTP {e.code}: {detail}", time.monotonic() - start, attempts
            err = f"HTTP {e.code}: {detail}"
        # URLError・TimeoutError・接続リセット等はすべて OSError の子。IncompleteRead は
        # http.client.HTTPException で OSError の子ではないので別に挙げる。
        except (OSError, http.client.HTTPException, KeyError, ValueError, TypeError) as e:
            err = f"{type(e).__name__}: {e}"
    return None, err, time.monotonic() - start, attempts


def pick_ui(files, base):
    tracked = git("ls-files", timeout=60).splitlines()
    if not any(UI_PATH.search(f) for f in tracked):
        return False, "画面を持たないリポ"
    touched = [f for f in files if UI_PATH.search(f) and not TEST_PATH.search(f)]
    if touched:
        return True, f"画面のファイルに触れた（{', '.join(touched[:5])}）"
    added = []
    current = ""
    for ln in git("diff", "-U0", base, "pr", timeout=60).splitlines():
        if ln.startswith("+++ "):
            current = ln[6:] if ln.startswith("+++ b/") else ""
        elif ln.startswith("+") and current and not TEST_PATH.search(current) and RESPONSE_SHAPE.search(ln):
            added.append(current)
    if added:
        return True, f"応答の形に関わる行を足した（{', '.join(sorted(set(added))[:5])}）"
    return False, "画面にも応答の形にも触れていない"


def main():
    repo, issue = read_input()
    pr_url, pr = find_pr(repo)
    gh_key = GH_KEY_FILE.read_text().strip()
    base, pr_json, issue_json = fetch(repo, pr, issue, gh_key)
    roles = json.loads((CONF / "roles.json").read_text())["roles"]
    try:
        state, files = build_state(base, pr_json, issue_json)
    except subprocess.TimeoutExpired as e:
        escalate(f"PR #{pr} の事実の組み立てが時間切れ（{' '.join(e.cmd[:3])}、{e.timeout:.0f}秒）。観点出しは行っていない。")
    if not files:
        escalate(f"PR #{pr} の diff が空。観点出しは行っていない。")

    probs, err, jev_seconds, jev_attempts = ask_jev(state, roles, os.environ["JEV_API_KEY"])
    selected = {}
    lines = []
    for r in roles:
        if probs is None:
            selected[r["name"]] = "Jev に聞けなかったので起動した"
            lines.append(f"- {r['name']}: 起動（Jev に聞けなかった）")
            continue
        p = probs[r["name"]]
        hit = p >= r["threshold"]
        if hit:
            selected[r["name"]] = f"Jev の yes の確率 {p:.2f} が閾値 {r['threshold']} 以上"
        lines.append(f"- {r['name']}: {'起動' if hit else '見送り'}（p={p:.2f}、閾値 {r['threshold']}）")
    try:
        ui, ui_reason = pick_ui(files, base)
    except subprocess.TimeoutExpired as e:
        escalate(f"画面判定が時間切れ（{' '.join(e.cmd[:3])}、{e.timeout:.0f}秒）。観点出しは行っていない。")
    if ui:
        selected["ui"] = ui_reason
    lines.append(f"- ui: {'起動' if ui else '見送り'}（{ui_reason}）")

    summary = "\n".join([
        f"# 観点出し: PR #{pr}",
        "",
        f"- PR: {pr_url}",
        "- 常に走る: general / documented / tests",
        "" if probs is not None else f"- **Jev に聞けなかった**ので、Jev で選ぶ観点は全部起動した: {err}",
        "",
        "## 観点ごとの判定",
        "",
        *lines,
        "",
        "## 変更したファイル（numstat）",
        "",
        "```",
        *state["numstat"][:100],
        "```",
    ])
    record = {"pr": pr_url, "probabilities": probs, "error": err,
              "jev_seconds": round(jev_seconds, 2), "jev_attempts": jev_attempts,
              "thresholds": {r["name"]: r["threshold"] for r in roles},
              "ui": {"selected": ui, "reason": ui_reason}, "selected": sorted(selected)}

    triggers = {r["name"]: r["trigger"] for r in roles}
    for name, why in selected.items():
        d = WORKSPACE / name
        (d / "report.md").write_text("\n".join([
            summary, "",
            "## この観点が選ばれた理由", "",
            why,
            *([f"\n入口の条件: {triggers[name]}"] if name in triggers else []),
            "",
        ]))
    (WORKSPACE / "general" / "report.md").write_text(summary + "\n")
    (WORKSPACE / "general" / "selection.json").write_text(json.dumps(record, ensure_ascii=False, indent=1) + "\n")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        # escalate() 自体は SystemExit で抜けるので、ここでは通り抜けて report.md を残す。
        # 想定していない例外で何も書かずに落ちるのを防ぐ最後の網。
        escalate(f"観点出しが予期しない例外で失敗した: {type(e).__name__}: {str(e)[:300]}")
