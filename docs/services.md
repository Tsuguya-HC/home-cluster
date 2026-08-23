# サービス一覧

## 外部公開 (*.infra.tgy.io)

Gateway で TLS 終端（cert-manager + Let's Encrypt）。HTTP は HTTPS にリダイレクト（301）。
ArgoCD のみ TLS Passthrough（専用 argocd-gateway、ArgoCD 自身が TLS 終端）。

| サービス | URL | バックエンド | TLS |
|---|---|---|---|
| Kanidm | https://idm.tgy.io | kanidm:443 (kanidm) | Passthrough (kanidm-gateway) |
| ArgoCD | https://argocd.infra.tgy.io | argocd-server (argocd) | Passthrough (argocd-gateway) |
| Grafana | https://grafana.infra.tgy.io | kube-prometheus-stack-grafana:80 (monitoring) | Terminate (main-gateway) |
| Hubble UI | https://hubble.infra.tgy.io | oauth2-proxy-hubble:4180 (oauth2-proxy) → hubble-ui:8081 | Terminate (main-gateway) |
| Argo Workflows | https://argo.infra.tgy.io | argo-workflows-server:2746 (argo) | Terminate (main-gateway) |
| SeaweedFS UI | https://seaweedfs.infra.tgy.io | oauth2-proxy-seaweedfs:4180 (oauth2-proxy) → seaweedfs-filer:8888 | Terminate (main-gateway) |
| Nextcloud | https://nc.tgy.io | nextcloud:80 (nextcloud) | Cloudflare Tunnel (cloudflared) |
| Harbor | https://registry.infra.tgy.io | harbor-nginx:8080 (harbor) | Cloudflare Tunnel (cloudflared) |
| RSS Reader | https://reader.tgy.io | oauth2-proxy-rss:4180 (oauth2-proxy) → rss-ui:80 / rss-server:80 (/api) | Terminate (main-gateway) + Cloudflare Tunnel (cloudflared) |

## 内部サービス

| サービス | エンドポイント | 備考 |
|---|---|---|
| PostgreSQL (RW) | shared-pg-rw.database.svc:5432 | CNPG 管理、2 インスタンス |
| PostgreSQL (RO) | shared-pg-ro.database.svc:5432 | リードレプリカ |
| Loki | loki-gateway.monitoring.svc:80 | ログ集約 |
| Tempo (HTTP API) | tempo.monitoring.svc:3200 | 分散トレーシング（クエリ） |
| Tempo (OTLP gRPC) | tempo.monitoring.svc:4317 | トレース取り込み |
| Tempo (OTLP HTTP) | tempo.monitoring.svc:4318 | トレース取り込み |
| Prometheus | kube-prometheus-stack-prometheus.monitoring.svc:9090 | メトリクス |
| SeaweedFS (S3) | seaweedfs-filer.seaweedfs.svc:8333 | S3 互換オブジェクトストレージ |
| Valkey | valkey-master.nextcloud.svc:6379 | Nextcloud キャッシュ (Redis 互換) |

## データベース (shared-pg)

| データベース | オーナー | 利用サービス |
|---|---|---|
| grafana | grafana | Grafana (kube-prometheus-stack) |
| argo | argo | Argo Workflows |
| nextcloud | nextcloud | Nextcloud |
| harbor | harbor | Harbor |
| seaweedfs | seaweedfs | SeaweedFS filer (メタデータストア) |

クレデンシャルはサービスごとに 1Password → ExternalSecret (ESO) で各 namespace にデプロイ。

| 1Password アイテム | ユーザー | Secret 名 | Namespace |
|---|---|---|---|
| Shared PostgreSQL | app | shared-pg-credentials | database |
| Grafana PostgreSQL | grafana | grafana-pg-credentials | database, monitoring |
| Argo PostgreSQL | argo | argo-pg-credentials | database, argo |
| Nextcloud PostgreSQL | nextcloud | nextcloud-pg-credentials | database, nextcloud |
| Harbor PostgreSQL | harbor | harbor-pg-credentials | database, harbor |
| seaweedfs-pg-credentials | seaweedfs | seaweedfs-pg-credentials | database, seaweedfs |
