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
| Prometheus | https://prometheus.infra.tgy.io | oauth2-proxy-prometheus:4180 (oauth2-proxy) → kube-prometheus-stack-prometheus:9090 | Terminate (main-gateway) |
| Nextcloud | https://nc.tgy.io | nextcloud:80 (nextcloud) | Cloudflare Tunnel (cloudflared) |
| Harbor | https://registry.infra.tgy.io | harbor-nginx:8080 (harbor) | Cloudflare Tunnel (cloudflared) |
| RSS Reader | https://reader.tgy.io | oauth2-proxy-rss:4180 (oauth2-proxy) → rss-ui:80 / rss-server:80 (/api) | Terminate (main-gateway) + Cloudflare Tunnel (cloudflared) |

## 内部サービス

| サービス | エンドポイント | 備考 |
|---|---|---|
| PostgreSQL (RW) | shared-pg-rw.database.svc:5432 | CNPG 管理、2 インスタンス |
| PostgreSQL (RO) | shared-pg-ro.database.svc:5432 | リードレプリカ |
| PostgreSQL (LAN 直結、手元作業用) | pg.infra.tgy.io:443 | Passthrough (pg-gateway) → shared-pg-rw:5432。external-dns が Cloudflare に A レコード（LAN のプライベート IP 192.168.10.193）を作る。argocd.infra.tgy.io と同じ扱いで、公開 DNS に載るがインターネットからは到達不能。(a) direct TLS 必須（libpq 17+ `sslnegotiation=direct`）、(b) `sslmode=verify-full` + pg-ca-issuer の CA を信頼する必要あり。到達できない場合のフォールバックは `kubectl -n database port-forward svc/shared-pg-rw 15432:5432` |
| SeaweedFS S3 (LAN 直結、手元作業用) | s3.infra.tgy.io:443 | Terminate (main-gateway) → seaweedfs-s3:8333。pg.infra.tgy.io と同じく公開 DNS にはプライベート IP が載るだけで Tunnel には入れない。認可は S3 identity + バケット権限（identity ごとに Read / Write / List を付け分ける）。到達できない場合のフォールバックは `kubectl -n seaweedfs port-forward svc/seaweedfs-s3 18333:8333` |
| Loki | loki-gateway.monitoring.svc:80 | ログ集約 |
| Tempo (HTTP API) | tempo.monitoring.svc:3200 | 分散トレーシング（クエリ） |
| Tempo (OTLP gRPC) | tempo.monitoring.svc:4317 | トレース取り込み |
| Tempo (OTLP HTTP) | tempo.monitoring.svc:4318 | トレース取り込み。llm-gateway の extproc が GenAI のトレース（プロンプト・モデルの発言・tool の引数を含む）を送る。保持 168h |
| Prometheus | kube-prometheus-stack-prometheus.monitoring.svc:9090 | メトリクス |
| SeaweedFS (S3) | seaweedfs-filer.seaweedfs.svc:8333 | S3 互換オブジェクトストレージ |
| Valkey | valkey-master.nextcloud.svc:6379 | Nextcloud キャッシュ (Redis 互換) |

## taskflow のアーカイブ（SeaweedFS `taskflow-archive`）

taskflow のコントローラは、終わった Task の JSON と workspace の `results/`（封印された run の答え・報告・transcript）を、Task を消す前に送り役 Job でこのバケットへ PUT する（taskflow ADR-0015）。保持は 90 日（`helm-values/seaweedfs/values.yaml` の `ttl`。書き込み時に焼き込まれるので、変えても既に書いた物には効かない）。

- **置き場所**: Task の `status.archive.location`（`s3://taskflow-archive/<namespace>/<flow>/<Task UID>/`）。中身は `task.json`、`results/…`、`manifest.json`（送らなかったファイルと理由）
- **`status.archive.endpoint` はクラスタ内の Service 名**で、手元からは届かない。外からは `s3.infra.tgy.io` に読み替える
- **読む経路**:
  - ブラウザ: `https://seaweedfs.infra.tgy.io` の filer UI で `/buckets/taskflow-archive/` を開く
  - CLI: `s3.infra.tgy.io` に、Admin か、このバケットの Read と List を持つ S3 identity で。例 `aws --endpoint-url https://s3.infra.tgy.io s3 ls s3://taskflow-archive/<namespace>/<flow>/<Task UID>/`
- **読める人**: filer UI は Kanidm の `seaweedfs_users` グループ（filer UI は S3 の identity を見ないので、全バケットが見える）。S3 は Admin か Read を持つ identity の鍵を持つ人（一覧には List も要る）。送り役の identity `taskflow-archive` は Write だけで読めない
- **中身の機密度**: private のリポを扱う Task の中身（issue 本文・コード片・transcript）も入る。送り役は秘密値の固定規則に当たったファイルを送らないが、規則に無い秘密値は送られる。読める人を広げるときはこれを前提にする
- **資格情報**: Task が走る各 namespace の Secret `taskflow-archive-s3`（キー `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY`）。値は private 側の tofu が生成して Secret に直接書く。このリポには置かない
- **失敗に気づく**: `TaskFlowArchiveFailed` / `TaskFlowArchiveWithheld`（`manifests/monitoring/prometheusrule-taskflow.yaml`）。Task の `Archived` 条件と Warning Event `UploadFailed` にも出る

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
