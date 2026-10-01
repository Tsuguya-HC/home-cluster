#!/bin/sh
# 使い方: issue-json.sh REPO ISSUE OUT。{title, body, comments} を OUT に書く。
# gh は呼び出し元の環境（GH_HOST / GH_ENTERPRISE_TOKEN）をそのまま使う。
# public リポでは誰でもコメントを書けるので、絞り（issue-comments.jq）を通ったものだけ入れる。
# 絞る前の生のコメントは作業ディレクトリにしか置かず、終わったら消す。
# gh api --paginate は Link を api.github.com 直で辿り、gateway を外れて落ちるので使わない。
# 1000 件を超えるコメントは黙って欠けさせず、失敗にする。
set -eu
err() { printf '%s\n' "$1" >&2; exit 1; }

[ "$#" -eq 3 ] || err "使い方: issue-json.sh REPO ISSUE OUT"
REPO=$1 ISSUE=$2 OUT=$3

JQ_FILE=$(dirname "$0")/issue-comments.jq
if ! COMMENTS_JQ=$(cat "$JQ_FILE") || [ -z "$COMMENTS_JQ" ]; then
  err "コメントの絞り（${JQ_FILE}）を読めなかった"
fi

W=$(mktemp -d) || err "作業ディレクトリを作れなかった"
trap 'rm -rf "$W"' EXIT

gh api "repos/${REPO}/issues/${ISSUE}" > "$W/issue.json" || err "issue の本文を取得できなかった"
: > "$W/comments.jsonl"
page=1
while :; do
  gh api "repos/${REPO}/issues/${ISSUE}/comments?per_page=100&page=${page}" > "$W/page.json" \
    || err "コメントを取得できなかった（page ${page}）"
  jq "$COMMENTS_JQ" "$W/page.json" >> "$W/comments.jsonl" || err "コメントを絞れなかった（page ${page}）"
  n=$(jq length "$W/page.json") || err "コメントの件数を数えられなかった（page ${page}）"
  [ "$n" -lt 100 ] && break
  [ "$page" -lt 10 ] || err "コメントが 1000 件を超えている"
  page=$((page + 1))
done
jq -s --slurpfile c "$W/comments.jsonl" '.[0] | {title, body, comments: $c}' "$W/issue.json" > "$OUT" \
  || err "issue.json を組み立てられなかった"
