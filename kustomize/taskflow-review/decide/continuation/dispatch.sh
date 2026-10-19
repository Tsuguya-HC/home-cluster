#!/bin/sh
# 終わった implement の Task ごとに、続きの判断の Task を 1 本作る（#1399）。
# 作る Task の名前は decide-<implement の Task 名>。同名が既にあれば作らない（二重起動の防止）。
set -eu

NS=claude-code-build
OWNER=Tsuguya-HC
: "${WINDOW_SECONDS:?}" "${MAX_PER_RUN:?}"

KEY=$(cat /github-gateway-key/key)
[ -n "$KEY" ] || { echo "GitHub の鍵が空だった。" >&2; exit 1; }
# 鍵は argv に載せない。
export GH_HOST=gh-ro.infra.tgy.io GH_ENTERPRISE_TOKEN="$KEY"

kubectl -n "$NS" get tasks.flow.tgy.io -o json > /tmp/tasks.json
now=$(date -u +%s)

jq -r --argjson now "$now" --argjson window "$WINDOW_SECONDS" '
  [.items[] | select(.spec.flow == "decide") | .metadata.name] as $have
  | [.items[]
      | select(.spec.flow == "implement" and .status.expiresAt != null)
      | select(("decide-" + .metadata.name) as $n | any($have[]; . == $n) | not)
      | {name: .metadata.name, end: ([.status.history[]?.finishedAt // empty] | max)}
      | select(.end != null and (.end | fromdateiso8601) > $now - $window)]
  | sort_by(.end) | .[].name' /tmp/tasks.json > /tmp/candidates

created=0
failed=0
while read -r name; do
  if [ "$created" -ge "$MAX_PER_RUN" ]; then
    echo "1 回の上限 ${MAX_PER_RUN} 本に達した。残りは次の回に回す。"
    break
  fi
  jq --arg n "$name" '.items[] | select(.metadata.name == $n)' /tmp/tasks.json > /tmp/source.json
  repo=$(jq -r '.spec.input.repo // empty' /tmp/source.json)
  issue=$(jq -r '.spec.input.issue // empty | tostring' /tmp/source.json)
  uid=$(jq -r '.metadata.uid' /tmp/source.json)
  phase=$(jq -r '.status.phase' /tmp/source.json)

  # repo と issue は URL に入る。形を確かめてからしか使わない。
  case "$repo" in
    "$OWNER"/*[!-A-Za-z0-9._]* | "$OWNER"/ | "$OWNER"/*/* | "$OWNER"/. | "$OWNER"/..)
      echo "${name}: spec.input.repo の形が不正。作らない。"; continue ;;
    "$OWNER"/?*) ;;
    *) echo "${name}: spec.input.repo が ${OWNER} 配下ではない。作らない。"; continue ;;
  esac
  case "$issue" in
    '' | *[!0-9]*) echo "${name}: spec.input.issue が数字ではない。作らない。"; continue ;;
  esac

  branch="agent/issue-${issue}-$(printf '%s' "${uid%%-*}" | tr -cd 'A-Za-z0-9' | cut -c1-16)"
  if ! pr=$(gh api "repos/${repo}/pulls?head=${OWNER}:${branch}&state=all" --jq '.[0].number // empty'); then
    echo "${name}: ${repo} の PR を引けなかった。" >&2
    failed=1
    continue
  fi
  # PR が無くてよいのは途中で止まった Task だけ。完了した Task で見つからないなら、ブランチ名の
  # 引き方が実装役とずれている。
  if [ -z "$pr" ]; then
    if [ "$phase" = TaskFailed ]; then
      echo "${name}: PR が無い（${branch}）。作らない。"
    else
      echo "${name}: ${phase} で終わったのに PR（${branch}）が見つからない。" >&2
      failed=1
    fi
    continue
  fi

  jq --arg pr "$pr" '{
      apiVersion: "flow.tgy.io/v1alpha1",
      kind: "Task",
      metadata: {name: ("decide-" + .metadata.name), namespace: "claude-code-build"},
      spec: {flow: "decide", input: {repo: .spec.input.repo, issue: (.spec.input.issue | tonumber), pr: ($pr | tonumber), status: .status}}
    }' /tmp/source.json > /tmp/task.json
  # 入力は handler に env FLOW_INPUT で渡る。1 つの env の上限（128KiB）を越えると Pod が起動できない。
  size=$(jq -c '.spec.input' /tmp/task.json | wc -c)
  if [ "$size" -gt 120000 ]; then
    echo "${name}: 入力が ${size} バイトで env に入らない。作らない。" >&2
    failed=1
    continue
  fi

  if out=$(kubectl create -f /tmp/task.json -o name 2>&1); then
    echo "${name}: ${out} を作った（${repo}#${pr}）。"
    created=$((created + 1))
  else
    case "$out" in
      *AlreadyExists* | *"already exists"*) echo "${name}: 続きの判断の Task は既にある。" ;;
      *) echo "${name}: ${out}" >&2; failed=1 ;;
    esac
  fi
done < /tmp/candidates

[ "$failed" -eq 0 ]
