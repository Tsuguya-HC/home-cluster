---
name: values
description: helm-values の変更をレンダリングで検証する。チャートが読まないキー、正しい階層の特定、kubeconform までローカルで一括実行
user_invocable: true
---

# values — レンダリングで検証する

`/lint` は**ファイルを読んで**判定する。このスキルは**レンダリング結果で**判定する。両方要る。

書いてあるキーが効いているかは、values を読んでも分からない。Helm は階層を間違えたキーを、書かれていないキーと同じように黙って無視する。実例:

| どこに書いてあったか | チャートが読む場所 | 結果 |
|---|---|---|
| `scanJobsConcurrentLimit`（トップレベル） | `operator.` 配下 | 既定の 10 で約 6 か月動作（#547） |
| `encryption.strictMode.enabled` | `strictMode.egress.enabled`（1.20 で分割） | WireGuard strict mode が無効のまま |
| `registry.resources` | `registry.registry` / `registry.controller` | registry が resources 無制限 |
| `podSecurityContext`（トップレベル） | `nextcloud.podSecurityContext` | seccompProfile が Pod に届かない |

**どれも `helm lint` を通り、`/lint` の静的ルールも通る。** 唯一の判定手段はレンダリングして比較すること。

## 使い方

| 引数 | 実行するもの | 報告 |
|---|---|---|
| (なし) | `--changed origin/main` | 変わった values と、`targetRevision` が動いたチャート |
| `<chart 名>` | 引数なし（全件） | そのチャートの結果を中心に報告する |
| `--all` | 引数なし（全件） | 全 31 ファイル |

スクリプトにチャート単体を指定するオプションは無い。`/values cilium` でも全件回して該当分を読む（約 45 秒、チャートキャッシュが温いとき）。**絞り込みロジックを手で再現しないこと** — 対象の決め方はスクリプト側が持っている。

## 手順

### 1. チャートが読まないキーを検出する

```bash
python3 scripts/unread-values.py --changed origin/main   # 引数なしのとき
python3 scripts/unread-values.py                          # --all のとき
```

出力の読み方:

- `checked N values file(s), no unread keys` — 通過
- `::error file=...::<key> is never read by the chart` — **そのキーは効いていない**
- `::warning::<chart>: N line(s) are regenerated on every render` — そのチャートは毎回変わる行があり、**その行だけに効くキーは検出できない**。証明書や生成パスワードに関わるキーを触ったなら、この検査は答えを持っていないと考えること
- `checker changed - examining every chart` — スクリプト自体を変更したので全件見ている（正常）

### 2. UNREAD が出たら、正しい階層を探す

キーが無いのではなく**場所が違う**ことが多い。テンプレートが実際に読んでいるパスを直接引く:

```bash
CHART=/tmp/unread-values-charts/<app>/<version>/<chart>   # unread-values.py が pull 済み
grep -rhoE '\.Values\.[A-Za-z0-9_.]*<キー名>[A-Za-z0-9_.]*' "$CHART/templates/" | sort -u
```

2026-08-22 に直した 3 件は全部これで一発で出る:

| 検出されたキー | 出力 |
|---|---|
| `encryption.strictMode.enabled` | `.Values.encryption.strictMode.egress.enabled` ほか 3 件 |
| `registry.resources` | `.Values.registry.registry.resources` / `.Values.registry.controller.resources` |
| `podSecurityContext` | `.Values.nextcloud.podSecurityContext` ほか 2 件 |

**チャートの values.yaml を探すのは当てにならない。** harbor は `resources:` がコメントアウトされているので `grep` でも `yq '.. | select(has("resources")) | path'` でも出てこない。それでもテンプレートは読んでいる。**読む側を見ること。**

出力が空なら、そのキーはこのチャートに存在しない（trivy-operator の `scanJobNamespace` がこれ。values にもテンプレートにも env にも無かった）。消す。

パスが合っているのに UNREAD なら、そのキーは**条件付き**である可能性が高い。分岐を読む:

```
{{- if and .Values.podDisruptionBudget.enabled (gt $replicaCount 1) }}
```

この場合キーは正しく、`replicaCount: 1` だから出力に現れないだけ。消さずに `scripts/unread-values-allow.txt` へ理由付きで登録する。**理由を書けないものは登録しない。**

### 3. 直したら、届いたことを確認する

修正しただけで終わらせない。レンダリング結果に出るところまで見る:

```bash
helm template t /tmp/unread-values-charts/<app>/<version>/<chart> \
  -n <namespace> -f helm-values/<app>/values.yaml | grep -A5 '<期待する出力>'
```

コンテナの resources や securityContext なら、Deployment を取り出して確認する方が確実:

```bash
helm template t <chart> -n <ns> -f <values> | python3 -c "
import sys,yaml
for d in yaml.safe_load_all(sys.stdin):
    if d and d.get('kind')=='Deployment':
        print(d['metadata']['name'], d['spec']['template']['spec'].get('securityContext'))"
```

### 4. マニフェストの妥当性（CI と同じ検証）

```bash
helm template t <chart> -n <ns> -f <values> | kubeconform -strict -ignore-missing-schemas \
  -schema-location default \
  -schema-location 'https://raw.githubusercontent.com/datreeio/CRDs-catalog/main/{{.Group}}/{{.ResourceKind}}_{{.ResourceAPIVersion}}.json' \
  -summary
```

## 報告フォーマット

```
## values 検証: <対象>

検査: N ファイル / helm <version>

| チャート | キー | 判定 | 正しい場所 |
|---|---|---|---|
| trivy-operator | scanJobsConcurrentLimit | UNREAD | operator.scanJobsConcurrentLimit |

警告: cilium は 8 行が毎回再生成されるため、その行だけに効くキーは判定できない
```

問題がなければ `N ファイル、UNREAD なし。<チャート> は毎回変わる行が M 行あるため、証明書関連のキーは判定対象外。` と、**検査できなかった範囲まで**書くこと。

## やってはいけないこと

- **UNREAD をそのまま消さない。** 場所が違うだけか、条件で無効なだけかを手順 2 で必ず切り分ける。この検査が誤るとき出る答えは常に「読まれていない」で、それを信じて消すと動いている設定が消える
- **`checked 0 values file(s)` を通過と読まない。** 対象がゼロなら検査していない。引数なしで 0 が出たなら values を触っていないだけだが、`--all` で 0 や極端に少ない数が出たら抽出が壊れている（下限で落ちるはずだが、落ちなかった場合は特に疑う）
- **警告の出たチャートで「問題なし」と結論しない。** 検出できない範囲があることまで報告する

## 関連

- `/lint` — 静的ルール（CNP 漏れ、PSA、iSCSI nodeAffinity 等）。このスキルと**役割が違う**ので両方走らせる
- `/dev-watch` — push 後、実際に反映されたかを見る。ここまでやって初めて「効いている」が確認できる
- CI では `unread values` ジョブが同じ検査を回す。PR では変更分＋`targetRevision` が動いたチャート、push では全件
