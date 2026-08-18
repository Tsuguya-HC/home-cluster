# Manual Bootstrap Steps

ArgoCD (GitOps) 管理外で、手動実行が必要な手順をまとめる。
クラスタ再構築時はこの順序で実行すること。

## 前提条件

- Talos Linux ノードが起動済み（VIP: 192.168.10.229）
- `talosctl` / `kubectl` が VIP に接続可能
- 1Password vault `home-cluster` に構築前アイテムが作成済み（[1Password Items](#1password-items) 参照）

## 1. Gateway API CRDs

Cilium は Gateway API CRDs を同梱しないため、先にインストールする。
TLSRoute（ArgoCD TLS Passthrough に使用）は experimental channel に含まれる。

初回ブートストラップ時のみ手動インストールが必要（ArgoCD がまだ存在しないため）。
day-2 以降は `apps/gateway-api-crds.yaml` の ArgoCD Application が管理する。
バージョンは同ファイルの `targetRevision` が source of truth。

```bash
# 初回ブートストラップ時のみ実行（バージョンは apps/gateway-api-crds.yaml の targetRevision に合わせる）
kubectl apply -f https://github.com/kubernetes-sigs/gateway-api/releases/download/v1.2.1/experimental-install.yaml
```

> **重要**: TLSRoute CRD は Cilium operator 起動前にインストールすること。
> 後からインストールした場合は Cilium operator の再起動が必要。

## 2. Cilium (CNI)

Talos はデフォルト CNI を持たないため、ArgoCD より先に Cilium を手動インストールする。
ArgoCD デプロイ後は app-of-apps が Cilium の管理を引き継ぐ。

```bash
helm repo add cilium https://helm.cilium.io
helm install cilium cilium/cilium \
  --namespace kube-system \
  --version 1.19.0 \
  -f helm-values/cilium/values.yaml
```

## 3. ArgoCD

CNI が動いた後、ArgoCD 本体を手動インストールし、app-of-apps を適用する。
以降は ArgoCD が自身を含む全 Application を管理する。

```bash
helm repo add argo https://argoproj.github.io/argo-helm
helm install argocd argo/argo-cd \
  --namespace argocd --create-namespace \
  --version 9.4.2 \
  -f helm-values/argocd/values.yaml

# AppProject を先に作成（app-of-apps が project: platform を参照するため）
kubectl apply -f manifests/argocd/appproject-*.yaml

kubectl apply -f argocd/app-of-apps.yaml
```

## 4. 1Password Connect Server Credentials

1Password Connect Server の credentials を手動で作成する。
credentials は git 管理外とし、1Password Web UI の「Integrations > Connect Server」で発行する。

```bash
kubectl create namespace external-secrets
kubectl create secret generic onepassword-connect \
  --namespace external-secrets \
  --from-file=1password-credentials.json="<PATH_TO_CREDENTIALS_JSON>" \
  --from-literal=token="<CONNECT_SERVER_ACCESS_TOKEN>"
```

app-of-apps が `apps/external-secrets.yaml` を検出し、ESO と Connect Server を自動デプロイする。
ESO が起動すると、ClusterSecretStore 経由でクラスタ内の Connect Server に接続し、
`manifests/secrets/` の ExternalSecret から各 namespace に Secret を自動生成する。
ExternalSecret は専用の `secrets` ArgoCD Application で管理され、他 app の reconcile から隔離する。

## 以降は自動

上記 4 ステップ完了後、ArgoCD が app-of-apps 経由で全サービスを自動デプロイする:
cert-manager, external-dns, SeaweedFS, CNPG, Grafana, Loki, Argo Workflows 等。

DNS レコードも external-dns が Gateway の HTTPRoute / TLSRoute から自動作成する（Cloudflare）。

S3 ストレージ（Loki、Tempo、Argo Workflows）は SeaweedFS が提供し、クレデンシャルは 1Password → ExternalSecret で各 namespace にデプロイ。

---

## 1Password Items

クラスタが参照する 1Password vault アイテム一覧。
構築前に作成できるものと、クラスタ稼働後に作成が必要なものがある。

### 構築前に作成（外部サービスの認証情報）

#### コアインフラ

| Item | Deployed Namespaces | Keys | 用途 |
|---|---|---|---|
| cloudflare-api-token | cert-manager, external-dns | api-token | DNS-01 challenge, DNS レコード管理 |
| cloudflared-tunnel-token | argocd | credential | Cloudflare Tunnel (GitHub webhook relay) |

#### 認証

| Item | Deployed Namespaces | Keys | 用途 |
|---|---|---|---|
| kanidm-grafana-oauth | monitoring | clientID, clientSecret | Kanidm OIDC (Grafana) |
| github-repo-creds | argocd | url, type, password | ArgoCD private repo 認証 |

#### データベース

| Item | Deployed Namespaces | Keys | 用途 |
|---|---|---|---|
| shared-pg-credentials | database | username, password | CNPG shared-pg superuser |
| grafana-pg-credentials | database, monitoring | username, password | Grafana DB ユーザー |
| argo-pg-credentials | database, argo | username, password | Argo Workflows DB ユーザー |

#### Nextcloud

| Item | Deployed Namespaces | Keys | 用途 |
|---|---|---|---|
| nextcloud-admin-credentials | nextcloud | username, password | Nextcloud 管理者 |
| nextcloud-pg-credentials | database, nextcloud | username, password | Nextcloud DB ユーザー |
| nextcloud-s3-credentials | nextcloud | username, password | SeaweedFS S3 認証 |
| nextcloud-kanidm-oauth | nextcloud | password | Kanidm OIDC clientSecret |

#### ストレージ

| Item | Deployed Namespaces | Keys | 用途 |
|---|---|---|---|
| qnap-backend-secret | trident | username, password, storageAddress, https, port | QNAP NAS CSI |

#### Argo Workflows 自動化

| Item | Deployed Namespaces | Keys | 用途 |
|---|---|---|---|
| talosconfig | argo | talosconfig | Talos ノード操作 |
| cloudflare-tofu-credentials | argo | CLOUDFLARE_API_TOKEN | OpenTofu Cloudflare provider |
| github-app-private-key | argo, image-build, talos-build, claude-code | private-key | GitHub App (tgy-cluster-bot) 認証 |
| home-cloudflare-github-webhook | argo | secret | GitHub webhook 検証 |
| home-harbor-github-webhook | argo | credential | GitHub webhook 検証 (home-harbor) |

### 構築後に作成（クラスタ内サービスに依存）

#### Kanidm 初期設定

> **R2 バックアップが存在する場合**: 手動セットアップの代わりに `docs/disaster-recovery.md` の「両方のデータロス（R2 バックアップからリストア）」手順でリストアできる。ユーザー・グループ・OAuth2 クライアントが全て復元されるため、以下の手動手順は不要。

Kanidm pod が Running になった後（初回構築 or バックアップなしの場合）:

1. admin / idm_admin のパスワード復旧:
   ```bash
   kubectl -n kanidm exec -it deploy/kanidm -- kanidmd recover-account admin -c /config/server.toml
   kubectl -n kanidm exec -it deploy/kanidm -- kanidmd recover-account idm_admin -c /config/server.toml
   ```

2. kanidm CLI でログイン:
   ```bash
   kanidm login --name idm_admin --url https://idm.tgy.io
   ```

3. ユーザー・グループ作成、OAuth2 クライアント設定:
   → `docs/sso.md` の手順に従う

4. Grafana の custom claim 設定:
   ```bash
   kanidm system oauth2 update-claim-map grafana grafana_role grafana_users Admin --url https://idm.tgy.io
   kanidm system oauth2 update-claim-map-join grafana grafana_role csv --url https://idm.tgy.io
   ```

5. Grafana の kanidm-grafana-oauth を 1Password に保存:
   → 1Password vault `home-cluster` に API Credential (clientID + clientSecret) を作成（item title: `kanidm-grafana-oauth`）

6. Argo Workflows の kanidm-argo-workflows-oauth を 1Password に保存:
   → `docs/sso.md` の Argo Workflows セクションの手順で Kanidm クライアント作成
   → clientSecret を取得し、1Password vault `home-cluster` に API Credential (clientID + clientSecret) を作成（item title: `kanidm-argo-workflows-oauth`）

#### Nextcloud OIDC 設定

Nextcloud pod が Running になった後:

1. SeaweedFS s3.conf に nextcloud 認証情報を追加（`seaweedfs-s3-config` 1Password item を更新）
2. Kanidm OAuth2 クライアント作成:
   ```bash
   kanidm system oauth2 create nextcloud "Nextcloud" https://nc.tgy.io
   kanidm system oauth2 add-redirect-url nextcloud https://nc.tgy.io/apps/user_oidc/code
   kanidm system oauth2 prefer-short-username nextcloud
   kanidm group create nextcloud_users
   kanidm group add-members nextcloud_users <users>
   kanidm system oauth2 update-scope-map nextcloud nextcloud_users openid profile email
   ```
3. clientSecret を取得し 1Password に保存:
   ```bash
   kanidm system oauth2 show-basic-secret nextcloud
   ```
4. user_oidc インストール・設定（CNP に appstore/github egress を一時追加してから）:
   ```bash
   kubectl exec -n nextcloud deploy/nextcloud -c nextcloud -- php occ app:install user_oidc
   kubectl exec -n nextcloud deploy/nextcloud -c nextcloud -- php occ user_oidc:provider kanidm \
     --clientid="nextcloud" \
     --clientsecret="<secret>" \
     --discoveryuri="https://idm.tgy.io/oauth2/openid/nextcloud/.well-known/openid-configuration"
   kubectl exec -n nextcloud deploy/nextcloud -c nextcloud -- php occ config:app:set --type=string --value=0 user_oidc allow_multiple_user_backends
   ```
5. SSO ログイン後、OIDC ユーザーを管理者に追加:
   ```bash
   kubectl exec -n nextcloud deploy/nextcloud -c nextcloud -- php occ user:list
   kubectl exec -n nextcloud deploy/nextcloud -c nextcloud -- php occ group:adduser admin <oidc-user-id>
   ```
