#!/bin/sh
# 作る Task の名前は intake-<issue の id>。同名が既にあれば作らない（二重起動の防止）。
set -euf

NS=claude-code-build
OWNER=Tsuguya-HC
L=decide.tgy.io
: "${WINDOW_SECONDS:?}" "${NOT_BEFORE:?}" "${MAX_PER_RUN:?}" "${MAX_PER_DAY:?}" "${ISSUER_USER_ID:?}"

KEY=$(cat /github-gateway-key/key)
[ -n "$KEY" ] || { echo "GitHub の鍵が空だった。" >&2; exit 1; }
# 鍵は argv に載せない。
export GH_HOST=gh-ro.infra.tgy.io GH_ENTERPRISE_TOKEN="$KEY"

kubectl -n "$NS" get tasks.flow.tgy.io -o json > /tmp/tasks.json
now=$(date -u +%s)
not_before=$(jq -rn --arg t "$NOT_BEFORE" '$t | fromdateiso8601')
since=$((now - WINDOW_SECONDS))
[ "$since" -ge "$not_before" ] || since=$not_before
since_iso=$(jq -rn --argjson s "$since" '$s | todate')

# 1 日の上限は作った Task の数で数える。Task の TTL が 1 日より短いと数え漏れる。
today=$(jq --arg l "$L/stage" --argjson now "$now" '[.items[]
  | select(.metadata.labels[$l] == "intake")
  | select((.metadata.creationTimestamp | fromdateiso8601) > $now - 86400)] | length' /tmp/tasks.json)

# Link ヘッダは api.github.com を指し gateway の外に出るので、--paginate は使わない。
: > /tmp/found.jsonl
page=1
while :; do
  gh api -X GET search/issues -f q="org:${OWNER} is:issue archived:false created:>=${since_iso}" \
    -f sort=created -f order=asc -f per_page=100 -f page="$page" > /tmp/page.json
  if [ "$(jq '.incomplete_results' /tmp/page.json)" = true ]; then
    echo "検索の結果が不完全だった（page ${page}）。取りこぼした issue は次の回に拾う。" >&2
  fi
  jq -c '.items[]' /tmp/page.json >> /tmp/found.jsonl
  [ "$(jq '.items | length' /tmp/page.json)" -eq 100 ] || break
  page=$((page + 1))
  if [ "$page" -gt 10 ]; then
    echo "窓の中の issue が検索で引ける 1000 件を越えた。" >&2
    exit 1
  fi
done

# 非公開の org メンバーは、members の権限を持たない鍵からは author_association が OWNER / MEMBER に見えない。
# 見えなかった人は、そのリポに write 以上の権限があるかで判定する（public リポは誰でも read が返る）。
: > /tmp/writers
jq -r --argjson since "$since" --slurpfile tasks /tmp/tasks.json '
  [$tasks[0].items[].metadata.name] as $have
  | select(.pull_request == null and (.created_at | fromdateiso8601) >= $since)
  | select(("intake-" + (.id | tostring)) as $n | any($have[]; . == $n) | not)
  | select(.user.type == "User" and (.author_association | IN("OWNER", "MEMBER", "COLLABORATOR") | not))
  | "\(.repository_url | capture("/repos/(?<r>[^/]+/[^/]+)$").r) \(.user.login)"' /tmp/found.jsonl | sort -u > /tmp/pairs
while read -r repo login; do
  case "$repo" in
    "$OWNER"/*[!-A-Za-z0-9._]* | "$OWNER"/ | "$OWNER"/*/* | "$OWNER"/. | "$OWNER"/..) continue ;;
    "$OWNER"/?*) ;;
    *) continue ;;
  esac
  case "$login" in '' | *[!-A-Za-z0-9]*) continue ;; esac
  if ! perm=$(gh api "repos/${repo}/collaborators/${login}/permission" --jq '.permission' 2> /tmp/perm.err); then
    if grep -q 'HTTP 404' /tmp/perm.err; then
      echo "${repo} の ${login} の権限は 404 だった。write 以上ではないとして扱う。"
      continue
    fi
    cat /tmp/perm.err >&2
    echo "${repo} の ${login} の権限を引けなかった。" >&2
    exit 1
  fi
  printf '%s %s %s\n' "$repo" "$login" "$perm" >> /tmp/writers
done < /tmp/pairs
writers=$(jq -Rn '[inputs | split(" ") | select(.[2] | IN("admin", "maintain", "write")) | {repo: .[0], login: .[1], permission: .[2]}]' /tmp/writers)

# 作者の判定。REST で引き直した issue にも同じものをかける。
# 作者を判定するのは、まだ Task が無い issue だけ（権限を引いたのもそれだけ）。
jq -s -c --argjson since "$since" --argjson issuer "$ISSUER_USER_ID" --argjson writers "$writers" --slurpfile tasks /tmp/tasks.json '
  include "author"; . as $all
  | [$tasks[0].items[].metadata.name] as $have
  | [.[] | select(.pull_request == null and (.created_at | fromdateiso8601) >= $since)] as $issues
  | [$issues[] | select(("intake-" + (.id | tostring)) as $n | any($have[]; . == $n) | not)] as $new
  | {
      found: ($all | length),
      prs: ([$all[] | select(.pull_request != null)] | length),
      existing: (($issues | length) - ($new | length)),
      authors: ([$new[] | select(author($issuer; $writers) == null) | "\(.user.login)(\(.author_association))"] | group_by(.) | map("\(.[0])×\(length)")),
      issues: [$new[] | select(author($issuer; $writers) != null)
        | {id, number, created_at, repo: repo}]
    }' -L /decide-lib /tmp/found.jsonl > /tmp/summary.json

jq -c '.issues[]' /tmp/summary.json > /tmp/candidates

echo "24 時間に作った Task ${today} 本 / 窓 ${since_iso} から検索 $(jq .found /tmp/summary.json) 件（うち PR $(jq .prs /tmp/summary.json) 件は外す）/ Task 作成済み $(jq .existing /tmp/summary.json) 件 / 未作成で対象 $(wc -l < /tmp/candidates) 件。"
if [ "$(jq '.authors | length' /tmp/summary.json)" -gt 0 ]; then
  echo "作者で外した: $(jq -r '.authors | join(", ")' /tmp/summary.json)"
fi

created=0
failed=0
: > /tmp/skipped
while read -r line; do
  repo=$(printf '%s' "$line" | jq -r '.repo')
  number=$(printf '%s' "$line" | jq -r '.number')
  id=$(printf '%s' "$line" | jq -r '.id')
  if [ "$created" -ge "$MAX_PER_RUN" ] || [ $((today + created)) -ge "$MAX_PER_DAY" ]; then
    printf '%s#%s\n' "$repo" "$number" >> /tmp/skipped
    continue
  fi

  # repo と issue は URL に入る。形を確かめてからしか使わない。
  case "$repo" in
    "$OWNER"/*[!-A-Za-z0-9._]* | "$OWNER"/ | "$OWNER"/*/* | "$OWNER"/. | "$OWNER"/..)
      echo "${repo}#${number}: リポ名の形が不正。作らない。"; continue ;;
    "$OWNER"/?*) ;;
    *) echo "${repo}#${number}: ${OWNER} 配下ではない。作らない。"; continue ;;
  esac
  case "$number" in '' | *[!0-9]*) echo "${repo}#${number}: 番号が数字ではない。作らない。"; continue ;; esac
  case "$id" in '' | *[!0-9]*) echo "${repo}#${number}: id が数字ではない。作らない。"; continue ;; esac

  # 記録する state と updated_at は作る時点のもの。検索の索引は遅れるので REST で引き直す。
  if ! gh api "repos/${repo}/issues/${number}" > /tmp/issue.json; then
    echo "${repo}#${number}: issue を引けなかった。" >&2
    failed=1
    continue
  fi
  kind=$(jq -r --argjson issuer "$ISSUER_USER_ID" --argjson writers "$writers" -L /decide-lib 'include "author"; author($issuer; $writers) // empty' /tmp/issue.json)
  if [ "$(jq -r '.id' /tmp/issue.json)" != "$id" ] || [ "$(jq '.pull_request != null' /tmp/issue.json)" = true ] || [ -z "$kind" ]; then
    echo "${repo}#${number}: 引き直すと対象から外れた。作らない。"
    continue
  fi

  jq -n -L /decide-lib --slurpfile tasks /tmp/tasks.json --slurpfile issue /tmp/issue.json --argjson writers "$writers" \
    --arg repo "$repo" --argjson number "$number" --arg kind "$kind" --arg l "$L" '
    include "author";
    $issue[0] as $i
    | [$tasks[0].items[]
        | select(.spec.flow == "implement")
        | select((.spec.input.repo // "" | ascii_downcase) == ($repo | ascii_downcase))
        | select((.spec.input.issue // "" | tostring) == ($number | tostring))
        | .metadata.name] as $impl
    | {
        apiVersion: "flow.tgy.io/v1alpha1",
        kind: "Task",
        metadata: {
          name: ("intake-" + ($i.id | tostring)),
          namespace: "claude-code-build",
          labels: {
            ($l + "/stage"): "intake",
            ($l + "/author"): $kind,
            ($l + "/issue-state"): $i.state,
            ($l + "/implement"): ($impl | length > 0 | tostring)
          },
          annotations: {
            ($l + "/repo"): $repo,
            ($l + "/issue"): ($number | tostring),
            ($l + "/issue-state"): $i.state,
            ($l + "/issue-updated-at"): $i.updated_at,
            ($l + "/author"): ([$i.user.login, $i.author_association, ($i | permission($writers) // empty)] | join(" ")),
            ($l + "/implement-tasks"): ($impl | join(","))
          }
        },
        spec: {flow: "decide", input: {repo: $repo, issue: $number}}
      }' > /tmp/task.json

  if out=$(kubectl create -f /tmp/task.json -o name 2>&1); then
    echo "${repo}#${number}: ${out} を作った（$(jq -r --arg l "$L" '.metadata.labels | [.[$l + "/author"], .[$l + "/issue-state"], "implement=" + .[$l + "/implement"]] | join(" ")' /tmp/task.json)）。"
    created=$((created + 1))
  else
    case "$out" in
      *AlreadyExists* | *"already exists"*) echo "${repo}#${number}: 入口の判断の Task は既にある。" ;;
      *) echo "${repo}#${number}: ${out}" >&2; failed=1 ;;
    esac
  fi
done < /tmp/candidates

if [ -s /tmp/skipped ]; then
  echo "上限（1 回 ${MAX_PER_RUN} 本 / 1 日 ${MAX_PER_DAY} 本）で作らなかった: $(wc -l < /tmp/skipped) 件 $(paste -sd ' ' /tmp/skipped)"
fi

[ "$failed" -eq 0 ]
