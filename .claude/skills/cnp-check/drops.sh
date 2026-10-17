#!/usr/bin/env bash
# 使い方: drops.sh [since=24h] [LogQL のパイプライン（例: '|= "<ns>"'）]
# hubble export は 1 パケットにつき drop (event_type 1) と policy verdict (event_type 5) の 2 行を出すので、
# drop 行だけを数える。
# k8s の生成名の接尾辞は母音を含まない文字集合なので、wl() は loki-write のような名前を削らない。
set -euo pipefail

since=${1:-24h}
filter=${2:-}
export LOKI_ADDR=${LOKI_ADDR:-http://localhost:3100}

up=
for _ in $(seq 10); do
  curl -sf -m 5 "$LOKI_ADDR/loki/api/v1/labels" > /dev/null && { up=1; break; }
  sleep 1
done
if [ -z "$up" ]; then
  echo "ERROR: $LOKI_ADDR に Loki が無い（port-forward を確認）" >&2
  exit 1
fi

count() { logcli instant-query -q "sum(count_over_time({job=\"hubble\"} $1 [$since]))" | jq -r '.[0].value[1] // "0"'; }

all=$(count "")
if [ "$all" = "0" ]; then
  echo "ERROR: hubble の行が 0（since=$since）。export 停止の可能性" >&2
  exit 1
fi
total=$(count "$filter")
echo "lines=$total (since=$since, 全体=$all)"
if [ "$total" = "0" ]; then
  echo "フィルタに一致する行なし" >&2
  exit 0
fi

lines=$(logcli query -q "{job=\"hubble\"} $filter" --limit="$total" --since="$since" --forward -o jsonl \
  | jq -r '.line | fromjson | .flow | select(.event_type.type == 1) |
      def rnd: sub("(-[bcdfghjklmnpqrstvwxz2456789]{7,10})?-[bcdfghjklmnpqrstvwxz2456789]{5}$"; "");
      def wl(e): (e.workloads[0].name // e.pod_name // "") | sub("-[0-9]{9,}$"; "") | rnd | sub("-[0-9]+-[0-9a-f]{8}$"; "") | rnd;
      def ep(e): if e.namespace then "\(e.namespace)/\(wl(e))"
                 else (e.labels // []) | map(select(test("^(reserved|cidr|fqdn):"))) | join(",") end;
      def port: (if .l4.TCP then "tcp/\(.l4.TCP.destination_port)"
                 elif .l4.UDP then "udp/\(.l4.UDP.destination_port)"
                 elif .l4.ICMPv4 then "icmp\(.l4.ICMPv4.type)/\(.l4.ICMPv4.code)" else "?" end);
      [(.drop_reason_desc // (.drop_reason | tostring)), ep(.source), ep(.destination), port, .IP.destination, .time[0:16]] | @tsv')
drops=$(grep -c . <<< "$lines" || true)
echo "drops=$drops"
if [ "$drops" -eq 0 ]; then
  echo "WARN: lines>0 だが drop 行が 0。スキーマ変化の可能性（event_type.type==1 を確認）" >&2
  exit 0
fi
awk -F'\t' '{ k = $1 "\t" $2 " -> " $3 " " $4; c[k]++; if (!((k, $5) in s)) { s[k, $5] = 1; n[k]++; ip[k] = $5 }
      if (!(k in f)) f[k] = $6; l[k] = $6 }
    END { for (k in c) printf "%5d pkts %3d IPs e.g.%-15s %s~%s  %s\n", c[k], n[k], ip[k], f[k], l[k], k }' \
  <<< "$lines" | sort -rn
