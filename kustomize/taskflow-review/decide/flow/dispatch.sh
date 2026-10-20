#!/bin/sh
# 作る Task の名前は implement-<判断の Task 名>。同名が既にあれば作らない（二重起動の防止）。
set -euf

NS=claude-code-build
OWNER=Tsuguya-HC
L=decide.tgy.io
STATUS=流す
DIRECTORY=flow
: "${WINDOW_SECONDS:?}" "${MAX_PER_RUN:?}" "${MAX_PER_DAY:?}" "${MAX_PER_DAY_APP:?}" "${ISSUER_USER_ID:?}"

KEY=$(cat /github-gateway-key/key)
[ -n "$KEY" ] || { echo "GitHub の鍵が空だった。" >&2; exit 1; }
# 鍵は argv に載せない。
export GH_HOST=gh-ro.infra.tgy.io GH_ENTERPRISE_TOKEN="$KEY"

kubectl -n "$NS" get tasks.flow.tgy.io -o json > /tmp/tasks.json
now=$(date -u +%s)

# 1 日の上限は作った Task の数で数える。implement の Task の TTL が 1 日より短いと数え漏れる。
jq --arg l "$L" --argjson now "$now" '[.items[]
  | select(.metadata.labels[$l + "/stage"] == "flow")
  | select((.metadata.creationTimestamp | fromdateiso8601) > $now - 86400)]
  | {all: length, app: (map(select(.metadata.labels[$l + "/author"] == "app")) | length)}' /tmp/tasks.json > /tmp/today.json
today=$(jq .all /tmp/today.json)
today_app=$(jq .app /tmp/today.json)

jq -c --arg l "$L" --arg status "$STATUS" --arg dir "$DIRECTORY" --argjson now "$now" --argjson window "$WINDOW_SECONDS" '
  [.items[].metadata.name] as $have
  | [.items[]
      | select(.spec.flow == "decide" and (.metadata.name | startswith("intake-")))
      | select(.metadata.labels[$l + "/author"] // "" | IN("human", "app"))
      | (.status.history // [])[-1] as $last
      | select(.status.phase == $status and $last.directory == $dir and $last.finishedAt != null)
      | select(($last.finishedAt | fromdateiso8601) > $now - $window)
      | {
          name: .metadata.name,
          uid: .metadata.uid,
          repo: (.spec.input.repo // "" | tostring),
          issue: (.spec.input.issue // "" | tostring),
          author: .metadata.labels[$l + "/author"],
          updated: (.metadata.annotations[$l + "/issue-updated-at"] // ""),
          archive: (.status.archive.location // ""),
          end: $last.finishedAt,
          exists: (("implement-" + .metadata.name) as $n | any($have[]; . == $n))
        }]
  | sort_by(.end)
  | {existing: map(select(.exists)) | length, candidates: map(select(.exists | not))}' /tmp/tasks.json > /tmp/summary.json
jq -c '.candidates[]' /tmp/summary.json > /tmp/candidates

echo "24 時間に作った Task ${today} 本（うち起票 App の issue ${today_app} 本）/ 窓 ${WINDOW_SECONDS} 秒に ${STATUS} で終わった入口の判断のうち implement 作成済み $(jq .existing /tmp/summary.json) 件 / 未作成 $(wc -l < /tmp/candidates) 件。"

# Link ヘッダは api.github.com を指し gateway の外に出るので、--paginate は使わない。
fetch_all() {
  : > /tmp/all.jsonl
  _page=1
  while :; do
    gh api -X GET "$1" -f per_page=100 -f page="$_page" > /tmp/page.json || return 1
    jq -c '.[]' /tmp/page.json >> /tmp/all.jsonl
    [ "$(jq 'length' /tmp/page.json)" -eq 100 ] || break
    _page=$((_page + 1))
    if [ "$_page" -gt 10 ]; then
      echo "$1 が 1000 件を越えた。" >&2
      return 1
    fi
  done
  jq -s '.' /tmp/all.jsonl
}

created=0
created_app=0
failed=0
: > /tmp/skipped
while read -r line; do
  name=$(printf '%s' "$line" | jq -r '.name')
  repo=$(printf '%s' "$line" | jq -r '.repo')
  number=$(printf '%s' "$line" | jq -r '.issue')
  author=$(printf '%s' "$line" | jq -r '.author')
  updated=$(printf '%s' "$line" | jq -r '.updated')
  id=${name#intake-}
  if [ "$created" -ge "$MAX_PER_RUN" ] || [ $((today + created)) -ge "$MAX_PER_DAY" ] \
    || { [ "$author" = app ] && [ $((today_app + created_app)) -ge "$MAX_PER_DAY_APP" ]; }; then
    printf '%s(%s#%s %s)\n' "$name" "$repo" "$number" "$author" >> /tmp/skipped
    continue
  fi

  # repo と issue は URL に入る。形を確かめてからしか使わない。
  case "$repo" in
    "$OWNER"/*[!-A-Za-z0-9._]* | "$OWNER"/ | "$OWNER"/*/* | "$OWNER"/. | "$OWNER"/..)
      echo "${name}: spec.input.repo の形が不正。作らない。"; continue ;;
    "$OWNER"/?*) ;;
    *) echo "${name}: spec.input.repo が ${OWNER} 配下ではない。作らない。"; continue ;;
  esac
  case "$number" in '' | 0* | *[!0-9]*) echo "${name}: spec.input.issue が数字ではない。作らない。"; continue ;; esac
  case "$id" in '' | *[!0-9]*) echo "${name}: 名前の id が数字ではない。作らない。"; continue ;; esac

  if ! gh api "repos/${repo}/issues/${number}" > /tmp/issue.json; then
    echo "${name}: ${repo}#${number} を引けなかった。" >&2
    failed=1
    continue
  fi
  if [ "$(jq -r '.id' /tmp/issue.json)" != "$id" ] || [ "$(jq '.pull_request != null' /tmp/issue.json)" = true ]; then
    echo "${name}: ${repo}#${number} の id が判断の Task と違う。作らない。"
    continue
  fi
  if [ "$(jq -r '.state' /tmp/issue.json)" != open ]; then
    echo "${name}: ${repo}#${number} は閉じている。作らない。"
    continue
  fi
  if [ "$(jq -r '.updated_at' /tmp/issue.json)" != "$updated" ]; then
    echo "${name}: ${repo}#${number} は判断の後に更新された（$(jq -r '.updated_at' /tmp/issue.json)、判断の材料は ${updated}）。作らない。"
    continue
  fi

  # 非公開の org メンバーは、members の権限を持たない鍵からは author_association が OWNER / MEMBER に見えない。
  # 見えなかった人は、そのリポに write 以上の権限があるかで判定する（public リポは誰でも read が返る）。
  writers='[]'
  if [ "$(jq '.user.type == "User" and (.author_association | IN("OWNER", "MEMBER", "COLLABORATOR") | not)' /tmp/issue.json)" = true ]; then
    login=$(jq -r '.user.login' /tmp/issue.json)
    case "$login" in '' | *[!-A-Za-z0-9]*) echo "${name}: 作者の login の形が不正。作らない。"; continue ;; esac
    if perm=$(gh api "repos/${repo}/collaborators/${login}/permission" --jq '.permission' 2> /tmp/perm.err); then
      writers=$(jq -n --arg r "$repo" --arg u "$login" --arg p "$perm" '[{repo: $r, login: $u, permission: $p} | select(.permission | IN("admin", "maintain", "write"))]')
    elif ! grep -q 'HTTP 404' /tmp/perm.err; then
      cat /tmp/perm.err >&2
      echo "${name}: ${repo} の ${login} の権限を引けなかった。" >&2
      failed=1
      continue
    fi
  fi
  kind=$(jq -r --argjson issuer "$ISSUER_USER_ID" --argjson writers "$writers" -L /decide-lib 'include "author"; author($issuer; $writers) // empty' /tmp/issue.json)
  if [ "$kind" != "$author" ]; then
    echo "${name}: ${repo}#${number} の作者の判定が入口の判断（${author}）と違う（${kind:-対象外}）。作らない。"
    continue
  fi

  impl=$(jq -r --arg repo "$repo" --arg number "$number" '[.items[]
    | select(.spec.flow == "implement")
    | select((.spec.input.repo // "" | ascii_downcase) == ($repo | ascii_downcase))
    | select((.spec.input.issue // "" | tostring) == $number)
    | .metadata.name] | join(",")' /tmp/tasks.json)
  if [ -n "$impl" ]; then
    echo "${name}: ${repo}#${number} の implement の Task がある（${impl}）。作らない。"
    continue
  fi

  # 実装役のブランチの PR。head: の検索はブランチ名の前方一致。
  if ! gh api -X GET search/issues -f q="repo:${repo} is:pr head:agent/issue-${number}-" -f per_page=100 > /tmp/search.json; then
    echo "${name}: ${repo} の PR を検索できなかった。" >&2
    failed=1
    continue
  fi
  if [ "$(jq '.incomplete_results' /tmp/search.json)" = true ]; then
    echo "${name}: ${repo} の PR の検索の結果が不完全だった。作らない。" >&2
    failed=1
    continue
  fi
  prs=$(jq -r '[.items[] | "#\(.number)(\(.state))"] | join(" ")' /tmp/search.json)
  if [ -n "$prs" ]; then
    echo "${name}: ${repo}#${number} の実装役のブランチの PR がある（${prs}）。作らない。"
    continue
  fi

  # issue を閉じる・参照する PR。画面から紐付けた PR は connected、題・本文・コメントで触れた PR は
  # cross-referenced として timeline に残る。cross-referenced は題と本文で触れたものだけ数える
  # （コメントで触れただけの PR まで数えると、起票の報告を受けた issue が流れない）。
  if ! fetch_all "repos/${repo}/issues/${number}/timeline" > /tmp/timeline.json; then
    echo "${name}: ${repo}#${number} の timeline を引けなかった。" >&2
    failed=1
    continue
  fi
  refs=$(jq -r --arg repo "$repo" --arg n "$number" '
    ($repo | ascii_downcase) as $r
    | def names_issue:
        ((.title // "") + "\n" + (.body // "") | ascii_downcase) as $text
        | ((.repository.full_name // "" | ascii_downcase) == $r and ($text | test("#" + $n + "([^0-9]|$)")))
          or ($text | test("(^|[^a-z0-9._-])" + ($r | gsub("\\."; "\\.")) + "(#|/issues/)" + $n + "([^0-9]|$)"));
      [.[]
        | select(.event == "connected"
            or (.event == "cross-referenced" and .source.issue.pull_request != null and (.source.issue | names_issue)))
        | if .event == "connected" then "connected" else "\(.source.issue.repository.full_name // "")#\(.source.issue.number)" end]
    | unique | join(" ")' /tmp/timeline.json)
  if [ -n "$refs" ]; then
    echo "${name}: ${repo}#${number} を閉じる・参照する PR がある（${refs}）。作らない。"
    continue
  fi

  jq -n --argjson src "$line" --slurpfile issue /tmp/issue.json \
    --argjson writers "$writers" --arg kind "$kind" --arg l "$L" -L /decide-lib '
    include "author";
    $issue[0] as $i
    | {
        apiVersion: "flow.tgy.io/v1alpha1",
        kind: "Task",
        metadata: {
          name: ("implement-" + $src.name),
          namespace: "claude-code-build",
          labels: {
            ($l + "/stage"): "flow",
            ($l + "/decision"): $src.name,
            ($l + "/author"): $kind
          },
          annotations: {
            ($l + "/decision"): $src.name,
            ($l + "/decision-uid"): $src.uid,
            ($l + "/decision-archive"): $src.archive,
            ($l + "/decided-at"): $src.end,
            ($l + "/repo"): $src.repo,
            ($l + "/issue"): $src.issue,
            ($l + "/issue-updated-at"): $i.updated_at,
            ($l + "/author"): ([$i.user.login, $i.author_association, ($i | permission($writers) // empty)] | join(" "))
          }
        },
        spec: {flow: "implement", input: {repo: $src.repo, issue: ($src.issue | tonumber)}}
      }' > /tmp/task.json

  if out=$(kubectl create -f /tmp/task.json -o name 2>&1); then
    echo "${name}: ${out} を作った（${repo}#${number} ${kind}）。"
    created=$((created + 1))
    [ "$kind" != app ] || created_app=$((created_app + 1))
  else
    case "$out" in
      *AlreadyExists* | *"already exists"*) echo "${name}: implement の Task は既にある。" ;;
      *) echo "${name}: ${out}" >&2; failed=1 ;;
    esac
  fi
done < /tmp/candidates

if [ -s /tmp/skipped ]; then
  echo "上限（1 回 ${MAX_PER_RUN} 本 / 1 日 ${MAX_PER_DAY} 本、うち起票 App の issue ${MAX_PER_DAY_APP} 本）で作らなかった: $(wc -l < /tmp/skipped) 件 $(paste -sd ' ' /tmp/skipped)"
fi

[ "$failed" -eq 0 ]
