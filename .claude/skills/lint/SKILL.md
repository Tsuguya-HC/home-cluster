---
name: lint
description: push 前の静的チェック。変更ファイルの CNP 漏れ、iSCSI 制約、セキュリティ違反等を検出
user_invocable: true
---

# Lint — push 前の静的チェック

変更ファイルを静的解析し、home-cluster 固有の制約違反を検出する。push は即座に本番反映されるため、コミット前に必ず実行すること。

## モード（`$ARGUMENTS` で切り替え）

| 引数 | 対象 |
|------|------|
| (なし) | `git diff --name-only HEAD`（未コミット変更） |
| `--staged` | `git diff --cached --name-only`（ステージ済み） |
| `--all` | リポジトリ全体のフル監査 |

## 実行手順

1. 対象ファイル一覧を取得する
2. 各ファイルの内容を Read で読み取る（`--all` の場合は `apps/`, `helm-values/`, `manifests/` 配下を Glob で列挙）
3. 下記ルールを全て適用する
4. 報告フォーマットに従って結果を出力する

---

## Tier 1 — Critical（忘れると障害直結）

### Rule 1: iSCSI nodeAffinity

**対象**: `qnap-iscsi` StorageClass を参照する values/manifest（`storageClassName: qnap-iscsi` または `storageClass: qnap-iscsi`）

**チェック**: PVC を使うワークロードに nodeSelector または nodeAffinity で worker ノード（`wn-*`）への配置指定があるか確認する。CP ノード（`cp-*`）には iSCSI ドライバがないため、nodeAffinity なしだと CP にスケジュールされて Pod が起動しない。

**判定**:
- Helm values: `nodeSelector` または `affinity` の設定があること
- 生マニフェスト: Deployment/StatefulSet の spec に nodeSelector/nodeAffinity があること
- tolerations のみでは不十分（配置制約にならない）

### Rule 2: CNP カバレッジ

**対象**: 新しいワークロードを追加するファイル（`apps/*.yaml` の新規作成、または Deployment/StatefulSet/DaemonSet の追加）

**チェック**: そのワークロードの namespace に対応する CNP が存在するか確認する。
- `manifests/<namespace>/netpol-*.yaml` が存在すること
- 既存 namespace に新しい Pod を追加する場合も、その Pod をカバーする endpointSelector を持つ CNP があるか確認する

**例外**: hostNetwork=true の Pod は CNP 対象外（node-exporter, CSI nodeplugin, Cilium agent 等）

### Rule 3: 機密値スキャン

**対象**: 全変更ファイル

**チェック**: 以下のパターンを検出する（PUBLIC リポジトリに機密値をコミットしてはならない）:
- `password:`, `token:`, `apiKey:`, `secret:` に続く平文値（`secretKeyRef`, `valueFrom`, `secretName` への参照は OK）
- `data:` 配下の base64 エンコード値（Kind: Secret のマニフェスト）
- ハードコードされた Bearer トークン、API キー、接続文字列
- `.env` ファイルや `credentials` を含むファイル名

**例外**:
- OnePasswordItem CRD（これは Secret への参照）
- `secretKeyRef`, `secretName`, `existingSecret` 等の参照
- 空文字列やプレースホルダー（`changeme`, `CHANGE_ME`, `TODO` 等）

### Rule 4: PSA compliance

**対象**: helm-values/ および manifests/ のワークロード定義

**チェック**: restricted PSA に準拠しているか（16/19 namespace が restricted enforce）:
- `runAsNonRoot: true`
- `allowPrivilegeEscalation: false`
- `seccompProfile.type: RuntimeDefault` または `Localhost`
- `capabilities.drop: ["ALL"]`
- `readOnlyRootFilesystem: true`（推奨）

**例外**:
- `kube-system`, `monitoring`, `trident` namespace は privileged enforce
- `allowPrivilegeEscalation` は container レベルのフィールド（pod レベルに書くとエラー）

### Rule 5: readOnlyRootFilesystem + /tmp

**対象**: `readOnlyRootFilesystem: true` が設定されたワークロード

**チェック**: `/tmp` への emptyDir マウントがあるか。多くのプロセスが `/tmp` に一時ファイル（*.sock 等）を書き込むため、emptyDir がないとクラッシュする。

**判定**:
- `volumeMounts` に `mountPath: /tmp` があること
- 対応する `volumes` に `emptyDir` があること

---

## Tier 2 — Important（ベストプラクティス違反）

### Rule 6: SA token automount

**対象**: Deployment / StatefulSet / DaemonSet

**チェック**: `automountServiceAccountToken` の設定を確認する。Kubernetes API にアクセスしないワークロードは `false` にすべき（攻撃面の削減）。

**報告**: 明示的に設定されていない場合は info レベルで報告する（デフォルト true のため）。API アクセスが必要なワークロード（ArgoCD, Cilium, cert-manager 等）は例外。

### Rule 7: リソース設定

**対象**: helm-values/ のリソース設定

**チェック**:
- `requests.memory` が設定されていること
- `limits.memory` が設定されていること
- `limits.cpu` が設定されていないこと（CFS throttling 回避。CPU は request のみで十分）

### Rule 8: ArgoCD Application 規約

**対象**: `apps/*.yaml`

**チェック**:
- `syncPolicy.automated.prune: true`
- `syncPolicy.automated.selfHeal: true`
- `syncPolicy.syncOptions` に `ServerSideApply=true` が含まれること
- `metadata.namespace: argocd`（Application リソースは argocd namespace に属する）

### Rule 9: CNP ルール品質

**対象**: `netpol-*.yaml` および `ccnp-*.yaml`

**チェック**:
- `ingress: []`（空配列）を使っていないか → ingress ポリシーが有効化されない
- `ingressDeny` に `host` や `remote-node` が含まれていないか → kubelet probe がブロックされる
- DNS egress ルール（port 53 への toEndpoints/toCIDR）が個別 CNP に含まれていないか → CCNP で共通適用済みのため重複
- `toCIDR: 0.0.0.0/0` + port 443 がないか → `toFQDNs` でドメイン限定すべき

---

## Tier 3 — Info（Chart 固有の落とし穴）

**この Tier の限界**: ここは「values を読んで」チャート固有の罠を当てにいくルールで、既知のものしか当たらない。書いてあるキーが実際にチャートに届いているかは、読んでも分からない（Helm は階層を間違えたキーを黙って無視する）。実際 Rule 11 は nextcloud の securityContext を見ているが、`podSecurityContext` がトップレベルにあって丸ごと無視されていた件は捕まえられなかった。

helm-values を触ったら **`/values` を併せて実行する**。あちらはレンダリング結果で判定するので、未知の罠にも当たる。

### Rule 10: SeaweedFS quirks

**対象**: `helm-values/seaweedfs/`

**チェック**:
- `tolerations` が multiline string（`|` リテラルブロック）で書かれているか（Helm テンプレートの制約）
- `securityContext` に `enabled: true` があるか（これがないと securityContext が適用されない）
- `extraVolumes` / `extraVolumeMounts` も multiline string であること

### Rule 11: Nextcloud quirks

**対象**: `helm-values/nextcloud/`

**チェック**:
- `defaultConfigs.s3.config.php: false` が設定されているか（カスタム objectstore config との重複を防ぐ）
- securityContext が pod レベルで設定されているか（`allowPrivilegeEscalation` は container レベルフィールドなので pod レベルに書くとエラー）

---

## 報告フォーマット

結果を以下の形式で報告する:

### 問題が見つかった場合

各 Tier ごとに表形式で報告:

```
## Critical

| ファイル | 行 | ルール | 指摘内容 |
|----------|-----|--------|----------|
| helm-values/foo/values.yaml | 42 | iSCSI nodeAffinity | qnap-iscsi PVC を使用しているが nodeSelector/nodeAffinity なし |

## Important

| ファイル | 行 | ルール | 指摘内容 |
|----------|-----|--------|----------|
| apps/foo.yaml | 15 | ArgoCD Application 規約 | selfHeal: true が未設定 |

## Info

| ファイル | 行 | ルール | 指摘内容 |
|----------|-----|--------|----------|
| (なし) | | | |
```

### 問題がない場合

```
全 N ファイル、11 ルールのチェックを通過。問題なし。
```
