# home-cluster

ArgoCD GitOps で管理するホーム Kubernetes クラスタの構成リポジトリ。

## Stack

| Category | Tool |
|----------|------|
| OS | Talos Linux (SecureBoot + TPM disk encryption) |
| CNI | Cilium (kube-proxy replacement) |
| GitOps | ArgoCD |
| Storage | SeaweedFS, QNAP CSI |
| Monitoring | Prometheus, Grafana, Loki, Tempo, Alloy |
| Certificates | cert-manager (Let's Encrypt) |
| DNS | external-dns (Cloudflare) |
| IdP | Kanidm |
| Secrets | External Secrets Operator (1Password Connect) |
| Database | CloudNativePG |
| CI/CD | Argo Workflows, Argo Events |
| Gateway | Cilium Gateway API |
| Registry | Harbor |
| Security | Tetragon, Trivy Operator, Kyverno (cosign image verification) |
| Wasm | Spin Operator (SpinKube) |

## Nodes

| Node | Hardware | RAM |
|------|----------|-----|
| cp-11〜13 | AOOSTAR N1 Pro (Intel N150) | 12GB |
| wn-01 | TRIGKEY G4 (Intel N100) | 32GB |
| wn-02 | NiPoGi AK2Plus (Intel N100) | 32GB |
| wn-03 | MINISFORUM UM790Pro (AMD 7940HS) | 64GB |

## Structure

```
apps/          # ArgoCD Application definitions
helm-values/   # Helm chart values
manifests/     # Raw K8s manifests
kustomize/     # Kustomize-based manifests (QNAP CSI)
docs/          # Operational docs
manual/        # Manual bootstrap steps
```

## Documentation

- [Bootstrap手順](manual/README.md) — クラスタ再構築時の手動ステップ
- [サービス一覧](docs/services.md) — 外部/内部エンドポイント
- [SSO設定](docs/sso.md) — Kanidm OIDC 設定・新サービス追加手順
- [ネットワークポリシー](docs/network-policies.md) — CNP/CCNP 全ポリシー一覧
- [Pod Security](docs/pod-security.md) — PSA 設定・namespace 一覧
- [ArgoCD Projects](docs/argocd-projects.md) — AppProject 構成・新サービス追加時の確認
- [リソース設定](docs/resource-limits.md) — requests/limits 一覧と実測値
- [SecureBoot](docs/secureboot.md) — Talos SecureBoot + TPM ディスク暗号化
- [災害復旧](docs/disaster-recovery.md) — PostgreSQL, etcd, Kanidm の復旧手順
- [IPv6](docs/ipv6.md) — 委任プレフィックス構成・変更時の手順・監視
- [既知の問題](docs/known-issues.md) — 初回構築時の注意点など
