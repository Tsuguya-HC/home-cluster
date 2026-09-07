# リソース設定

## 方針

- **requests.cpu**: 実測値ベース（スケジューラがノード配置に使用）
- **requests.memory**: 実測値 + 小幅なヘッドルーム
- **limits.memory**: 実測値の約 2 倍（バースト対応、OOMKill 防止）
- **limits.cpu**: 設定しない（CPU はコンプレッシブルリソース。limit を設定すると CFS throttling が発生し、レイテンシが悪化する）

計測日: 2026-02-22（`kubectl top pods` による実測値）

## Helm Values

### ArgoCD

| コンポーネント | requests (cpu/mem) | limits (mem) | 実測 |
|---|---|---|---|
| controller | 50m / 512Mi | 1536Mi | 3-39m / 295-473Mi |
| server | 10m / 64Mi | 256Mi | 3m / 38Mi |
| repo-server | 10m / 128Mi | 1Gi | 1m / 54Mi（helm template でスパイク） |
| redis | 10m / 64Mi | 256Mi | 14m / 83Mi |
| dex | 10m / 32Mi | 128Mi | 低負荷 |
| applicationSet | 10m / 64Mi | 192Mi | 低負荷 |
| notifications | 10m / 64Mi | 128Mi | 低負荷 |

### Cilium

| コンポーネント | requests (cpu/mem) | limits (mem) | 実測 |
|---|---|---|---|
| agent (DS) | 50m / 128Mi | 512Mi | 37-77m / 142-185Mi |
| operator | 10m / 64Mi | 256Mi | 5m / 40Mi |
| envoy (DS) | 10m / 32Mi | 256Mi | 低負荷 |
| hubble-relay | 10m / 32Mi | 192Mi | 低負荷 |
| hubble-ui frontend | 10m / 32Mi | 128Mi | 合計 43m / 96Mi |
| hubble-ui backend | 10m / 32Mi | 128Mi | 同上 |

### cert-manager

| コンポーネント | requests (cpu/mem) | limits (mem) | 実測 |
|---|---|---|---|
| controller | 10m / 32Mi | 128Mi | 低負荷 |
| webhook | 10m / 32Mi | 64Mi | 低負荷 |
| cainjector | 10m / 32Mi | 128Mi | 1m / 51Mi |

### Loki

| コンポーネント | requests (cpu/mem) | limits (mem) | 実測 |
|---|---|---|---|
| singleBinary | 25m / 256Mi | 512Mi | 20-24m / 259Mi |
| gateway (nginx) | 10m / 32Mi | 64Mi | 低負荷 |
| canary (DS) | 10m / 32Mi | 64Mi | 低負荷 |
| sidecar (sc-rules) | 10m / 32Mi | 128Mi | 低負荷（64Mi で OOMKill 発生） |

### Tempo

| コンポーネント | requests (cpu/mem) | limits (mem) | 実測 |
|---|---|---|---|
| tempo | 25m / 256Mi | 512Mi | 未計測（新規導入） |

### Alloy (DS)

| コンポーネント | requests (cpu/mem) | limits (mem) | 実測 |
|---|---|---|---|
| alloy | 25m / 128Mi | 512Mi | 21-29m / 87-315Mi |
| config-reloader | 10m / 32Mi | 64Mi | 低負荷 |

### kube-prometheus-stack

| コンポーネント | requests (cpu/mem) | limits (mem) | 実測 |
|---|---|---|---|
| prometheus | 200m / 1Gi | 2Gi | 93-117m / 1225-1738Mi |
| alertmanager | 50m / 128Mi | 256Mi | 2m / 35Mi |
| operator | 10m / 32Mi | 128Mi | 4m / 23Mi |
| config-reloader | 10m / 32Mi | 64Mi | 低負荷 |
| grafana | 25m / 256Mi | 512Mi | 17-20m / 260Mi |
| grafana sidecar | 10m / 64Mi | 256Mi | 低負荷（64Mi で OOMKill 発生） |
| kube-state-metrics | 10m / 32Mi | 128Mi | 低負荷 |
| node-exporter (DS) | 10m / 32Mi | 64Mi | 低負荷 |

### Kyverno

| コンポーネント | requests (cpu/mem) | limits (mem) | 実測 |
|---|---|---|---|
| admission-controller | 50m / 128Mi | 384Mi | 未計測 |
| background-controller | 10m / 64Mi | 256Mi | 未計測 |
| reports-controller | 10m / 64Mi | 256Mi | 未計測 |
| cleanup-controller | 10m / 64Mi | 256Mi | 未計測 |

### その他

| サービス | コンポーネント | requests (cpu/mem) | limits (mem) | 実測 |
|---|---|---|---|---|
| external-dns | | 10m / 32Mi | 128Mi | 低負荷 |
| metrics-server | | 10m / 32Mi | 128Mi | 低負荷 |
| cnpg | operator | 10m / 64Mi | 256Mi | 4m / 38Mi |
| external-secrets | operator | 10m / 64Mi | 256Mi | 未計測 |
| external-secrets | webhook | 10m / 32Mi | 128Mi | 低負荷 |
| external-secrets | certController | 10m / 32Mi | 128Mi | 低負荷 |
| argo-workflows | controller | 10m / 64Mi | 256Mi | 2m / 19Mi |
| argo-workflows | server | 10m / 64Mi | 256Mi | 1m / 21Mi |
| argo-events | controller | 10m / 64Mi | 256Mi | 2m / 27Mi |
| seaweedfs | master ×3 | 25m / 64Mi | 256Mi | 未計測 |
| seaweedfs | volume | 50m / 128Mi | 512Mi | 未計測 |
| seaweedfs | filer | 25m / 128Mi | 512Mi | 未計測 |
| trivy-operator | operator | 50m / 100Mi | 256Mi | 低負荷 |
| kanidm | server ×2 | 50m / 128Mi | 256Mi | 未計測 |
| harbor | nginx | 10m / 32Mi | 128Mi | 未計測 |
| harbor | core | 50m / 128Mi | 512Mi | 未計測 |
| harbor | portal | 10m / 32Mi | 128Mi | 未計測 |
| harbor | registry | 50m / 128Mi | 512Mi | 未計測 |
| harbor | jobservice | 10m / 64Mi | 256Mi | 未計測 |
| harbor | exporter | 10m / 32Mi | 128Mi | 未計測 |
| nextcloud | nextcloud | 100m / 256Mi | 1Gi | 未計測 |
| reloader | controller | 10m / 32Mi | 128Mi | 低負荷 |
| spin-operator | controller | 10m / 64Mi | 128Mi | 低負荷 |

## CRD マニフェスト

### Argo Events

| コンポーネント | requests (cpu/mem) | limits (mem) | 実測 |
|---|---|---|---|
| EventBus (JetStream) main | 10m / 32Mi | 128Mi | 8-13m / 17-26Mi |
| EventBus metrics | 10m / 32Mi | 64Mi | 低負荷 |
| EventBus reloader | 10m / 32Mi | 64Mi | 低負荷 |
| EventSource | 10m / 32Mi | 64Mi | 1m / 16Mi |
| Sensor | 10m / 32Mi | 64Mi | 7m / 19-20Mi |

### CNPG

| コンポーネント | requests (cpu/mem) | limits (mem) | 実測 |
|---|---|---|---|
| shared-pg | 10m / 128Mi | 512Mi | 3-24m / 96-124Mi |

## WorkflowTemplate コンテナ

| テンプレート | コンテナ | requests (cpu/mem) | limits (mem) |
|---|---|---|---|
| tofu-cloudflare | main (opentofu) | 50m / 128Mi | 512Mi |
| tofu-cloudflare-plan | main (opentofu) | 50m / 128Mi | 512Mi |
| pluto-check | detect-in-cluster | 10m / 32Mi | 128Mi |
| pluto-check | detect-helm | 10m / 32Mi | 128Mi |
| pluto-check | ai-fix (node + claude) | 100m / 256Mi | 1Gi |
| pluto-check | fail-if-deprecated | 10m / 16Mi | 64Mi |
| upgrade-k8s | validate/upgrade/remaining/verify | 10m / 64Mi | 256Mi |
| discord-notify | send (curl) | 10m / 16Mi | 64Mi |
| node-shutdown | resolve-nodes | 10m / 16Mi | 64Mi |
| node-shutdown | shutdown-nodes (talosctl) | 10m / 32Mi | 64Mi |
| talos-secureboot-build | plan-build | 10m / 64Mi | 128Mi |
| talos-secureboot-build | run-imager | 100m / 512Mi | 2Gi |
| talos-secureboot-build | push-installer | 50m / 256Mi | 1Gi |
| talos-secureboot-build | push-iso | 50m / 256Mi | 1Gi |
| talos-secureboot-build | finalize-release | 10m / 64Mi | 128Mi |
| claude-code | setup (init) | 10m / 64Mi | 256Mi |
| claude-code | claude-code (main) | 100m / 512Mi | 4Gi |
| image-build | detect-changes | 10m / 64Mi | 256Mi |
| image-build | buildkit-build | 100m / 512Mi | 4Gi |

### QNAP CSI (trident)

Chart が resources をハードコード (cpu limit 20m) しており values で上書き不可。
Helm source をやめ rendered manifests + Kustomize patch で CPU limit を除去（`kustomize/qnap-csi/`）。

| コンポーネント | requests (cpu/mem) | limits (mem) | 実測 |
|---|---|---|---|
| trident-operator | 10m / 40Mi | 80Mi | 1m / 77Mi |

## OOMKill 調整履歴

| 日付 | コンポーネント | 変更前 | 変更後 | 原因 |
|---|---|---|---|---|
| 2026-02-22 | argocd repo-server | 512Mi | 1Gi | helm template rendering で大量メモリ使用 |
| 2026-02-22 | loki sidecar (sc-rules) | 64Mi | 128Mi | 起動時メモリ超過 |
| 2026-02-22 | grafana sidecar (sc-dashboard/datasources) | 64Mi | 256Mi | 起動時メモリ超過 |
| 2026-02-22 | argocd controller | 768Mi | 1536Mi | 18回 OOMKill、全 Application の state キャッシュでメモリ不足 |
