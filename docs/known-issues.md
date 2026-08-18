# 既知の問題

## Grafana datasource の循環参照（初回構築時）

Loki と Tempo の datasource provisioning で相互参照（Logs↔Traces 相関）を設定している。
Grafana 12 は provisioning 時に `datasourceUid` の存在を検証するため、空 DB からの初回構築時に片方がまだ存在せず `data source not found` で起動に失敗する可能性がある。

**該当ファイル**: `helm-values/kube-prometheus-stack/values.yaml` の `additionalDataSources`

```
Loki  → derivedFields.datasourceUid: tempo   (Tempo がまだない可能性)
Tempo → tracesToLogsV2.datasourceUid: loki   (Loki は先に作成されるので OK)
```

**発生条件**: Grafana DB が空の状態での初回起動（新規クラスタ構築、DB リセット等）

**回復手順**:

1. `additionalDataSources` の Loki から `derivedFields` ブロックを一時削除
2. push して ArgoCD sync → Grafana が起動し、両 datasource が DB に作成される
3. `derivedFields` ブロックを戻して再度 push
4. Grafana pod を再起動（`kubectl delete pod -n monitoring -l app.kubernetes.io/name=grafana`）

**補足**: `derivedFields` はフロントエンド機能のため、実際には validate されず問題なく起動する可能性もある。Grafana の将来バージョンで provisioning 時の循環参照が解消される可能性あり。

## Grafana ダッシュボードで "No data" になるパネル

kube-prometheus-stack と Cilium のダッシュボードには、シングルクラスタ環境では "No data" になるパネルがある。これらはバグではない。

### エラー・イベント発生時のみ表示されるパネル

| ダッシュボード | パネル | 理由 |
|---|---|---|
| Kubernetes / Kubelet | Storage Operation Error Rate | `storage_operation_errors_total` はエラー発生時のみ存在 |
| Hubble / Network Overview | Missing ICMP Echo Reply | クラスタ内に ICMP トラフィックがない |
| Hubble / DNS Overview | Missing DNS responses | 未応答の DNS クエリがない |

### 特定条件が必要なパネル

| ダッシュボード | パネル | 理由 |
|---|---|---|
| Hubble L7 HTTP Metrics by Workload | CPU Usage by Source | L7 HTTP トラフィックは Gateway（外部）からのみ来るため `source_workload` が空 |
| Kubernetes / Compute Resources / Multi-Cluster | 全パネル | シングルクラスタ環境。kube-prometheus-stack では個別に無効化できない |

## Prometheus の cluster ラベル（シングルクラスタ環境）

`prometheusSpec.externalLabels.cluster` は remote write、federation、alertmanager にのみ適用される。ローカルの PromQL クエリや TSDB ストレージには影響しない。

**`defaultRules.additionalRuleLabels.cluster` を使ってはいけない。** recording rule に cluster ラベルを追加すると、recording rule は `cluster=home-cluster` を持つが生メトリクスには `cluster` ラベルがないため不整合が起きる。recording rule と生メトリクスを join するダッシュボードパネル（CPU Quota, Memory Quota, Network Usage 等）が No data になる。

シングルクラスタ環境では全メトリクスから `cluster` ラベルを除外する。Grafana 変数は空に解決され、`cluster=""` で全メトリクスに一貫してマッチする。

将来マルチクラスタや Thanos/Mimir が必要になった場合は、recording rule だけでなく全スクレイプターゲットの ServiceMonitor `metricRelabelings` で `cluster` を付与すること。

## iscsi-tools extension のホストバイナリ消失（解決済み 2026-05-05）

siderolabs/extensions の `fb4eb042` ("consolidate extension services", 2026-01-30) で iscsi-tools のアーキテクチャが変更され、バイナリがホスト rootfs からコンテナ rootfs 内のみの配置に移行 → Trident CSI が iSCSI マウント不能になっていた。

**解決**: upstream `e4afe22` ("fix: iscsi-tools and multipath-tools", 2026-03-15) でホストへの iscsi バイナリ配置が復活。Issue #12951 はこの commit で CLOSED。

- 自前ミラー (`ghcr.io/tsuguya/iscsi-tools:v0.2.0-pre-consolidation`) は廃止、`ghcr.io/siderolabs/iscsi-tools:v0.2.0` に切り替え
- v1.13.0 + 上流 v0.2.0 で全ノード Trident PVC マウント動作確認済み
- 自前 mirror リポは未使用（不要なら GHCR から削除可）

## 1Password Operator → External Secrets Operator (ESO) 移行（解決済み）

1Password Operator (OnePasswordItem CRD) は生成する Secret にカスタム labels/annotations を付与できない。ArgoCD 自体の Secret（`argocd-secret` 等）を 1Password で管理する場合、ArgoCD が要求する識別ラベル（`app.kubernetes.io/part-of: argocd` 等）を Secret に付与できず、ArgoCD が自身の設定 Secret を正しく認識できない問題があった。

**対策**: External Secrets Operator (ESO) に移行。ESO の ExternalSecret CRD は `target` で生成する Secret の labels/annotations を自由に指定できるため、ArgoCD が必要とするラベルを付与可能。加えて ExternalSecret CRD 自体を ArgoCD の tracking 対象とし、専用の `secrets` Application で全 ExternalSecret を一元管理する構成に変更した。

## QNAP Trident iSCSI: ノード移動時の LUN リフォーマット

Pod がノード間を移動した際に、Trident CSI が iSCSI LUN を再フォーマットしてデータを全消失させるバグ。2026-02-27 の K8s v1.35.2 アップグレード時に SeaweedFS volume で発生。

**根本原因チェーン**:

1. K8s アップグレード等で API server が再起動
2. Trident コントローラーが API 接続断で再起動、ブートストラップ中にバックエンドが一時不可
3. Pod が別ノードに再スケジュール（liveness probe 失敗等）
4. 移動先ノードに前回の stale iSCSI セッションが残存（portal 情報が空 `:3260`）
5. FSType チェック失敗 → Trident がデバイスを ext4 で再フォーマット → **データ全消失**

**対策: nodeSelector / nodeAffinity でノード固定**

Pod がノード間を移動しなければ stale iSCSI セッション問題は発生しない。iSCSI PVC を持つ全ワークロードを現在稼働中のノードに固定する。

| ワークロード | 固定先 | 方式 |
|---|---|---|
| kanidm | wn-02, wn-03 | nodeAffinity (StatefulSet 2 replicas) |
| seaweedfs volume/filer | wn-02 | nodeSelector |
| prometheus | wn-02 | nodeSelector |
| loki | wn-03 | nodeSelector |
| tempo | wn-01 | nodeSelector |

**レプリケーション HA を持つワークロードの方針**:

Kanidm のようにレプリケーションでデータ冗長性を持つワークロードは、可能であれば iSCSI を使わずローカルディスク（Local PV）を使う。これにより QNAP CSI 依存を完全排除できる。ノード障害時はもう片方の Pod がサービス継続し、復旧後にレプリケーションで再同期。

**レプリケーションなしのワークロード**:

nodeSelector で固定し PDB で voluntary eviction を防止。ノード障害時は復旧を待つ。

**注意事項**:

- 新たに iSCSI PVC を使うワークロードを追加する際は必ず nodeSelector を設定すること
- K8s アップグレード前に iSCSI ワークロードの配置を確認（`kubectl get pods -o wide`）
- emptyDir は Pod 削除でデータ消失するため、DB 系ワークロードにはレプリケーション併用でも不適（レプリケーション証明書も消失するため手動復旧が必要になる）

## QNAP CSI (trident-operator) CPU limit ハードコード

QNAP CSI Helm chart (v1.6.0) は `bundle.yaml` テンプレート内で `resources.limits.cpu: 20m` をハードコードしており、values で上書きできない。この制限により CPUThrottlingHigh アラートが発生する。

**対策**: Helm source をやめ、`helm template` でレンダリングした manifests を `kustomize/qnap-csi/` に配置。Kustomize JSON patch で CPU limit を除去。

```
kustomize/qnap-csi/
├── kustomization.yaml              # JSON patch: limits.cpu を除去
├── upstream.yaml                   # helm template 出力 (v1.6.0)
└── crds/tridentorchestrator_crd.yaml
```

**アップグレード手順**:

1. 新バージョンの chart を clone
2. `helm template qnap-trident <chart-path> -n trident -f <values> --kube-version 1.32.0` で再レンダリング
3. `upstream.yaml` を差し替え、CRD に変更があれば `crds/` も更新
4. push → ArgoCD sync（Kustomize patch が自動適用される）

## HGW の IPv6 静的ルートが再起動後に「表示されるが未適用」になる

auひかり HGW (NEC Platforms, 172.16.0.1) は、IPv6 ルーティング設定のエントリを NVRAM に保持しているが、**起動時にルーティングテーブルへ反映しないことがある**。UI は設定ファイルの内容を表示するため、6 本のエントリが正常に並んでいるように見えたまま機能しない。

**発生実績**: 2026-07-11 03:34 の電源断（HGW と UCG が同時に再起動）→ 2026-08-17 に発見。約 5 週間、全 VLAN の IPv6 が外部と通らない状態だった。

**症状の見分け方**:

| 観測 | 結果 |
|---|---|
| HGW LAN の `:1::/64`（RA 由来） | 正常。UCG 自身からの外部疎通も OK |
| VLAN の `:2`〜`:20`（静的に切った /64） | 外部と通らない |
| HGW / UniFi の設定値 | 一切変化なし。UI 上は完全に正常 |
| HGW のログ | IPv6 関連のエントリが 1 行も出ない |
| クライアント体感 | v6 を優先して毎回タイムアウト → v4 にフォールバックするので「なんか遅い」だけ |

**切り分け（決定的）**: UniFi UI → Cloud Gateway Fiber → ツール → シェルで、送信元を変えて ping する。

```sh
ping -c3 2606:4700:4700::1111                       # src :1::1 → 通る
ping -c3 -I <PREFIX>:4::1 <HGW の LAN GUA>          # → 0/3
```

同一リンク宛なのに送信元を VLAN プレフィックスにした瞬間に落ちる、という形で「HGW が追加 /64 を折り返せていない」と一発で特定できる。`tracert -6` が hop1 (UCG) 以降オールスターになるのも同じ理由。

**復旧手順**:

1. 172.16.0.1 → 詳細設定 → IPv6ルーティング設定
2. **エントリを 1 本だけ**「編集」→ 内容を変えずに「保存」
3. 1 本の保存でルーティングテーブル全体が再適用され、他のエントリも同時に有効化される

**HGW を再起動してはいけない**。原因が「再起動時にルートが適用されなかったこと」なので、再起動は修復ではなく同じ障害を再発させる操作になる。

**構成の詳細**: [IPv6](ipv6.md) を参照。

**検知**: `blackbox-exporter` + `Probe/ipv6-egress` で監視している（`Ipv6EgressDown`）。ノードの VLAN 10 GUA を送信元にした HTTPS 疎通を見ているため、この障害を検知できる。`ip_protocol_fallback: false` を外すと v4 にフォールバックして常に成功扱いになるので変更しないこと。
