#!/usr/bin/env bash
# CiliumEndpoint の external-identifiers には namespace / pod 名が入らないので、Pod IP で突き合わせる。
set -euo pipefail

tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT

kubectl get pods -A -o json | jq -r '.items[]
  | select(.status.phase == "Running")
  | [(.status.podIP // ""), .metadata.namespace, .metadata.name, (.spec.hostNetwork // false | tostring),
     (.metadata.ownerReferences[0] | if . == null or .kind == "Node" then null
        elif .kind == "ReplicaSet" then .name | sub("-[a-z0-9]+$"; "") else .name end) // .metadata.name]
  | @tsv' > "$tmp/pods.tsv"

agents=$(kubectl get pods -n kube-system -l k8s-app=cilium -o jsonpath='{.items[*].metadata.name}')
for pod in $agents; do
  kubectl exec -n kube-system "$pod" -c cilium-agent -- cilium-dbg endpoint list -o json \
    | jq -r '.[] | select(.status.networking.addressing[0].ipv4 != null)
        | [.status.networking.addressing[0].ipv4, (.status.policy.realized."policy-enabled" // "none")] | @tsv' >> "$tmp/eps.tsv"
done

eps=$(wc -l < "$tmp/eps.tsv")
pods=$(awk -F'\t' '$4 == "false"' "$tmp/pods.tsv" | wc -l)
echo "agents=$(wc -w <<< "$agents") endpoints=$eps pods(non-hostNetwork)=$pods"
if [ "$eps" -eq 0 ] || [ "$pods" -eq 0 ]; then
  echo "ERROR: 検査対象が 0 件。取得方法が壊れている" >&2
  exit 1
fi

awk -F'\t' 'NR == FNR { ep[$1] = $2; next }
  $4 == "false" { print $2 "/" $3 "\tpolicy=" (($1 in ep) ? ep[$1] : "NO-ENDPOINT") }' \
  "$tmp/eps.tsv" "$tmp/pods.tsv" > "$tmp/cov.tsv"

echo "--- policy-enabled"
cut -f2 "$tmp/cov.tsv" | sort | uniq -c
echo "--- both 以外"
grep -v 'policy=both$' "$tmp/cov.tsv" || echo "(なし)"
echo "--- hostNetwork（CNP 対象外）"
awk -F'\t' '$4 == "true" { print $2 "/" $5 }' "$tmp/pods.tsv" | sort | uniq -c
