# ArgoCD Projects

ArgoCD AppProject でアプリケーションをドメインごとに分離し、各プロジェクトが操作できるリソースとネームスペースを制限している。

## プロジェクト一覧

| Project | 説明 | Namespaces | Apps 数 |
|---------|------|------------|---------|
| platform | コアプラットフォーム (ArgoCD, Cilium, Tetragon, Spin Operator, Reloader) | argocd, kube-system, cilium-secrets, spin-operator | 8 |
| networking | ネットワーク (cert-manager, external-dns, Gateway) | `*` | 4 |
| monitoring | Observability (Prometheus, Loki, Alloy, Tempo) | monitoring, kube-system | 5 |
| argo | Argo エコシステム (Events, Workflows, CI/CD パイプライン) | argo, default, talos-build, image-build, claude-code | 7 |
| security | Secret 管理・セキュリティ (ESO, OAuth2 Proxy, Kanidm, Trivy, Kyverno) | `*` | 8 |
| apps | ユーザー向けアプリケーション (Nextcloud, Harbor) | nextcloud, harbor | 2 |
| storage | ストレージ (SeaweedFS, CNPG, QNAP CSI, NFS) | cnpg-system, database, nfs-provisioner, seaweedfs, trident | 6 |
| ai | AI/ML インフラ (Qdrant, Ollama, TaskFlow) | qdrant, ollama, taskflow-system | 3 |

## クラスタスコープリソースの許可 (clusterResourceWhitelist)

各プロジェクトは namespaced リソースに加え、クラスタスコープリソースの許可リストを持つ。
ここに無いリソースを Application がデプロイしようとすると **sync が失敗する**。

### 共通 (全プロジェクト)

| Kind | Group |
|------|-------|
| CustomResourceDefinition | `*` |
| ClusterRole | `*` |
| ClusterRoleBinding | `*` |

### プロジェクト固有

| Project | Kind | Group | 用途 |
|---------|------|-------|------|
| platform | ValidatingWebhookConfiguration | `*` | Cilium, ArgoCD |
| platform | MutatingWebhookConfiguration | `*` | Cilium |
| platform | ValidatingAdmissionPolicy | admissionregistration.k8s.io | Cilium Gateway API (1.20+) |
| platform | ValidatingAdmissionPolicyBinding | admissionregistration.k8s.io | Cilium Gateway API (1.20+) |
| platform | APIService | `*` | metrics-server |
| platform | GatewayClass | `*` | Cilium Gateway API |
| platform | Namespace | `*` | kube-system config |
| platform | RuntimeClass | node.k8s.io | Spin Operator (SpinKube) |
| platform | TracingPolicy | cilium.io | Tetragon セキュリティポリシー |
| networking | ValidatingWebhookConfiguration | `*` | cert-manager |
| networking | MutatingWebhookConfiguration | `*` | cert-manager |
| networking | ValidatingAdmissionPolicy | admissionregistration.k8s.io | Gateway API safe-upgrades (v1.5+) |
| networking | ValidatingAdmissionPolicyBinding | admissionregistration.k8s.io | Gateway API safe-upgrades (v1.5+) |
| networking | Namespace | `*` | cert-manager, external-dns |
| networking | ClusterIssuer | `*` | cert-manager |
| networking | CiliumClusterwideNetworkPolicy | `*` | DNS 共通ポリシー等 |
| networking | CiliumL2AnnouncementPolicy | `*` | L2 ARP |
| networking | CiliumLoadBalancerIPPool | `*` | LB IP プール |
| monitoring | ValidatingWebhookConfiguration | `*` | kube-prometheus-stack |
| monitoring | MutatingWebhookConfiguration | `*` | kube-prometheus-stack |
| security | Namespace | core | ESO, Kanidm, Trivy 等 |
| security | ClusterSecretStore | external-secrets.io | ESO ClusterSecretStore |
| security | ValidatingWebhookConfiguration | admissionregistration.k8s.io | ESO |
| security | `*` | aquasecurity.github.io | Trivy CRDs |
| security | MutatingWebhookConfiguration | admissionregistration.k8s.io | Kyverno |
| security | `*` | kyverno.io | Kyverno ClusterPolicy 等 |
| storage | ValidatingWebhookConfiguration | `*` | CNPG |
| storage | MutatingWebhookConfiguration | `*` | CNPG |
| storage | Namespace | `*` | ストレージ ns |
| storage | StorageClass | `*` | QNAP CSI |
| storage | PersistentVolume | core | ストレージ |
| storage | CSIDriver | `*` | QNAP CSI |
| storage | TridentOrchestrator | `*` | QNAP Trident |
| ai | ValidatingWebhookConfiguration | admissionregistration.k8s.io | taskflow の TaskFlow 構造検査 webhook |

## 新しいサービスを追加するとき

1. **プロジェクトを選ぶ** — 上の一覧からドメインが合うプロジェクトに入れる
2. **namespace を確認** — プロジェクトの `destinations` に対象 namespace があるか確認、なければ追加
3. **sourceRepo を確認** — Helm chart の場合、リポジトリ URL がプロジェクトの `sourceRepos` にあるか確認、なければ追加
4. **クラスタスコープリソースを確認** — Helm chart や マニフェストがクラスタスコープリソース（CRD 以外）をデプロイする場合、`clusterResourceWhitelist` に追加

## クラスタスコープリソースの追加手順

新しいクラスタスコープリソースが必要になった場合：

1. `manifests/argocd/appproject-<project>.yaml` を編集
2. `clusterResourceWhitelist` にリソースの `group` と `kind` を追加
3. push して ArgoCD が AppProject を更新した後、対象アプリが sync されることを確認

```yaml
# 例: platform プロジェクトに TracingPolicy を追加
clusterResourceWhitelist:
  - group: cilium.io
    kind: TracingPolicy
```

リソースがクラスタスコープかどうかは `kubectl api-resources --namespaced=false` で確認できる。

## ファイル配置

```
manifests/argocd/
├── appproject-apps.yaml
├── appproject-platform.yaml
├── appproject-networking.yaml
├── appproject-monitoring.yaml
├── appproject-argo.yaml
├── appproject-security.yaml
├── appproject-storage.yaml
└── appproject-ai.yaml
```
