---
name: cnp-check
description: CNP (CiliumNetworkPolicy) のカバレッジと hubble の DROPPED フローを総合チェックする。引数に namespace / pod を渡すとそこを優先して調べる
user_invocable: true
---

# CNP チェック

## 1. カバレッジ

```bash
bash ~/.claude/skills/cnp-check/coverage.sh
```

- 非 hostNetwork の Running Pod ごとに、その Pod の endpoint の `policy-enabled` を出す
- `both` 以外が漏れ。`egress` は CCNP allow-dns だけが当たっている（ingress 未カバー）、`none` はポリシーなし、`NO-ENDPOINT` は agent に endpoint が無い
- hostNetwork の Pod は CNP の対象外なので別枠で列挙する（host firewall は無効）
- スクリプトが ERROR で終わったら結果を「問題なし」と読まない。取得方法が壊れているので直してから報告する

## 2. DROPPED フロー

集計（第 1 引数は期間、第 2 引数は任意の LogQL パイプライン）:

```bash
bash ~/.claude/skills/cnp-check/drops.sh 24h
bash ~/.claude/skills/cnp-check/drops.sh 24h '|= "<ns>"'
```

- drops.sh が Loki 不在で ERROR になったら、まず `ss -ltn | grep :3100` で 3100 の LISTEN を確かめる（壊れた forward が残っていると新規は bind 失敗で黙って死ぬ）。LISTEN が無ければ `timeout 300 kubectl -n monitoring port-forward svc/loki-gateway 3100:80 &>/dev/null &` で寿命つきの port-forward を張って再実行する。自然終了させ、kill はしない。他人が張ったものは止めない
- ERROR（hubble の行が 0）は export 停止の疑い。「drop なし」と読まない
- 出力は `パケット数 / 宛先 IP 数 / 時間幅 / 理由 送信元 -> 宛先 proto/port`。hubble は 1 パケットにつき 2 行出すので、生の行数で語らない
- 宛先に `fqdn:<name>` が付いているのは、その名前がどこかの CNP の `toFQDNs` に載っているということ。送信元自身の CNP に載っている名前なのに落ちているなら、DNS プロキシが datapath の更新を待ちきれずに応答を返している。agent ログの `Timed out waiting for datapath updates of FQDN IP information` と時刻を突き合わせる
- `reserved:world` の IP の正体は `cilium-dbg fqdn cache list`（CNP に載っている名前しか入らない）か、`openssl s_client -connect <ip>:443 </dev/null | openssl x509 -noout -subject` で引く
- 送信元の Pod が既に消えていても、時間幅とワークロード名で何の処理だったかを特定する

## 3. 報告

- カバレッジ（漏れの一覧。無ければ件数つきで「漏れなし」）
- DROPPED のパターンを「要対処 / 設計通り / 無害」に分け、根拠（CNP の該当箇所、ログ、コメント）を付ける
- 対処案。CNP を足す前に、その通信がそもそも出るべきものかを先に判断する（外への通信の止め忘れは CNP ではなく送信元の設定で止める）

## 4. 引数があるとき

指定の namespace / pod を優先する:

- `kubectl get cnp -n <ns>` と Pod のラベルを endpointSelector と照合する
- 同じ namespace の既存 CNP の書き方に合わせて追加案を出す
- `drops.sh 24h '|= "<ns>"'` で絞る

## 禁止

- 寿命の無い port-forward を張らない（他人が張ったものは止めない）
- CNP を緩めて drop を消す案を、送信元の設定を見ずに出さない
