#!/bin/sh
# レビューの枝と仕分けの fetch init が共有する、PR の取り込み（#1081）。
# /tmp に clone・diff・PR と issue の本文を置く。GitHub の鍵はこの init にしか渡らない。
# 失敗しても exit 0 で /tmp/fetch-error に書くこと。init が落ちると Pod が上がらず、
# escalate に理由を書く者がいなくなる。
set -eu
fail() { printf '%s\n' "$1" > /tmp/fetch-error; exit 0; }

# この値は URL にもプロンプトにも入る。形を確かめてからしか使わない。
REPO=$(printf '%s' "${FLOW_INPUT:-}" | jq -r '.repo // empty' 2>/dev/null || true)
case "$REPO" in
  Tsuguya-HC/*[!-A-Za-z0-9._]* | Tsuguya-HC/ | Tsuguya-HC/*/* | Tsuguya-HC/. | Tsuguya-HC/..)
    fail "spec.input.repo の形が不正。レビューは行っていない。" ;;
  Tsuguya-HC/?*) ;;
  *) fail "spec.input.repo は Tsuguya-HC 配下だけを指定できる。レビューは行っていない。" ;;
esac
ISSUE=$(printf '%s' "${FLOW_INPUT:-}" | jq -r '.issue // empty' 2>/dev/null || true)
case "$ISSUE" in
  '' | *[!0-9]*) fail "spec.input.issue が数字ではない。レビューは行っていない。" ;;
esac

# 対象の PR は、実装フェーズが棚に残した done/pr-url。棚の番号は数値順に読む
# （辞書順では 10 が 2 より前に来る）。差し戻しの後は最後のものが最新。
PR_URL=
for f in $(printf '%s\n' /results/*/done/pr-url | sort -t/ -k3,3n); do
  [ -f "$f" ] || continue
  PR_URL=$(head -1 "$f")
done
case "$PR_URL" in
  "https://github.com/${REPO}/pull/"*) PR=${PR_URL##*/} ;;
  *) fail "レビュー対象の PR が棚（results/*/done/pr-url）に見つからない。レビューは行っていない。" ;;
esac
case "$PR" in
  '' | *[!0-9]*) fail "棚の PR の URL が不正（${PR_URL}）。レビューは行っていない。" ;;
esac

KEY=$(cat /github-gateway-key/key) || fail "GitHub の鍵を読めなかった。レビューは行っていない。"
[ -n "$KEY" ] || fail "GitHub の鍵が空だった。レビューは行っていない。"
GW=gh-ro.infra.tgy.io
# 鍵は argv に載せない（-c ではなく GIT_CONFIG_* で渡す）。
GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0="http.https://${GW}/.extraheader" \
  GIT_CONFIG_VALUE_0="Authorization: token ${KEY}" \
  git clone --quiet "https://${GW}/${REPO}.git" /tmp/src \
  || fail "${REPO} を clone できなかった。レビューは行っていない。"
git -C /tmp/src config core.hooksPath /dev/null \
  || fail "hooksPath の設定に失敗した。レビューは行っていない。"
GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0="http.https://${GW}/.extraheader" \
  GIT_CONFIG_VALUE_0="Authorization: token ${KEY}" \
  git -C /tmp/src fetch --quiet origin "refs/pull/${PR}/head:pr" \
  || fail "PR #${PR} の head を取得できなかった。レビューは行っていない。"
BASE=$(git -C /tmp/src merge-base origin/main pr) \
  || fail "PR #${PR} と origin/main の merge-base が取れなかった。レビューは行っていない。"
git -C /tmp/src diff "$BASE" pr > /tmp/pr.diff \
  || fail "PR #${PR} の diff を作れなかった。レビューは行っていない。"

GH_HOST="$GW" GH_ENTERPRISE_TOKEN="$KEY" gh api "repos/${REPO}/pulls/${PR}" > /tmp/pr-raw.json \
  || fail "PR #${PR} を取得できなかった。レビューは行っていない。"
jq '{title, body, changed_files, additions, deletions}' < /tmp/pr-raw.json > /tmp/pr.json 2>/dev/null \
  || fail "PR #${PR} の本文を読めなかった。レビューは行っていない。"
GH_HOST="$GW" GH_ENTERPRISE_TOKEN="$KEY" gh api "repos/${REPO}/issues/${ISSUE}" > /tmp/issue-raw.json \
  || fail "issue #${ISSUE} を取得できなかった。レビューは行っていない。"
jq '{title, body}' < /tmp/issue-raw.json > /tmp/issue.json 2>/dev/null \
  || fail "issue #${ISSUE} の本文を読めなかった。レビューは行っていない。"
rm -f /tmp/pr-raw.json /tmp/issue-raw.json

# 前の周回の仕分けが差し戻した内容（仕分けだけが読む）。fix/ は仕分けの語彙。
mkdir -p /tmp/previous-triage \
  || fail "/tmp/previous-triage を作れなかった。レビューは行っていない。"
for f in $(printf '%s\n' /results/*/fix/report.md | sort -t/ -k3,3n); do
  [ -f "$f" ] || continue
  n=${f#/results/}; n=${n%%/*}
  cp "$f" "/tmp/previous-triage/${n}.md" \
    || fail "前回の仕分け結果をコピーできなかった（${f}）。レビューは行っていない。"
done
rmdir /tmp/previous-triage 2>/dev/null || true

# agent はここに書かれた値だけを使う（検証済み）。
printf '%s\n' "$REPO" > /tmp/repo || fail "/tmp/repo を書けなかった。レビューは行っていない。"
printf '%s\n' "$PR" > /tmp/pr-number || fail "/tmp/pr-number を書けなかった。レビューは行っていない。"
