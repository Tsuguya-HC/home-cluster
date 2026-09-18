# Network Policies

All policies are CiliumNetworkPolicy (CNP) and CiliumClusterwideNetworkPolicy (CCNP). Pods with `hostNetwork: true` are not subject to network policies and are excluded.

**Enforcement mode: `always`** (`helm-values/cilium/values.yaml`, since 2026-08-29). Every endpoint is default-deny in both directions even if no policy selects it. Consequences:
- A CNP that only writes `egress` leaves the pod's ingress fully denied (not open, as it was in `default` mode). Pods that must receive traffic need an explicit `ingress` allow.
- The `ingressDeny: [{fromEntities: [world]}]` marker on older sensor/job policies was only needed to enable ingress enforcement in `default` mode; it is now redundant but harmless.
- Cilium-internal identities need their own CCNPs (`cilium-health-checks`, `allow-gateway-ingress` below). Without `allow-gateway-ingress` every HTTPRoute is dropped.
- kubelet probes from the local host stay allowed (`allow-localhost=auto`).
- The chart does not restart agents on ConfigMap changes; `rollOutCiliumPods` / `operator.rollOutPods` / `envoy.rollOutPods` are enabled so Helm value changes actually reach the running pods. Verify with `cilium-dbg config | grep PolicyEnforcement`, not with the ConfigMap.

**Caveats:**
- Do NOT add L7 HTTP rules (`rules.http`) to ingress of services using TLS passthrough (TLSRoute). Cilium attempts to parse encrypted traffic as HTTP, breaking the connection.
- The `cluster` entity in `ingressDeny` includes `host` and `remote-node`. Since deny rules take precedence over allow rules, this blocks kubelet probes. Never use `cluster` in `ingressDeny` — use `world` only. For pods with probes, prefer ingress allow-only policies (implicit default deny) over `ingressDeny`.
- **L7 method/path allow-list as a stand-in for authorization**: if a backend has no auth/authz of its own, put oauth2-proxy in front for authentication, and use CNP L7 (`rules.http` with a `method` allow-list and a `path` regex anchored with `^...$` for a full match) to cover authorization — restrict which endpoints an authenticated user can reach (example: `manifests/monitoring/netpol-prometheus.yaml`, oauth2-proxy-prometheus ingress). Two things regularly trip people up when writing these:
  - Cilium's `path`/`method` are matched via Envoy's RE2 engine, which has **no negative lookahead**. "Everything except X" has to be spelled out as an explicit alternation over where the string diverges from X, not `(?!X)`. Keep this alternation as short as possible (see next point) — prefer excluding by a short, verified-unique prefix over spelling out the whole literal one character at a time (see the `/debug` exclusion in netpol-prometheus.yaml, which excludes by the single leading `d` rather than the full word, because that Prometheus version registers no other route starting with `d`).
  - Envoy's `RegexMatcher` fails to compile once RE2's `programsize` exceeds the default `re2.max_program_size.error_level` of **100**, and Cilium does not raise this limit. There is no admission webhook for this in this cluster, so `kubectl apply --dry-run=server` / kubeconform / CI all pass even when a rule is over the limit — the failure only shows up when cilium-agent turns the CNP into Envoy xDS config, silently leaving the L7 block non-functional. Character-by-character negation alternations (see previous point) blow through this fast; measure `programsize` with the `google-re2` Python binding (`re2.compile(pattern).programsize`) before relying on a hand-written negation, especially before adding `(?i)`, which also costs program size.
  - Envoy's `:path` is the path **and query string together**. A `path` regex anchored with `$` that doesn't allow for a trailing `?...` will reject every request that carries query parameters — which is most real UI traffic, for both GET and POST.

## Cluster-Wide Policies (CCNP)

| Policy | Selector | Ingress | Egress |
|---|---|---|---|
| **allow-dns** | all pods (`io.cilium.k8s.policy.cluster: default`) | — | kube-dns:53 (UDP/TCP) with L7 DNS proxy (`matchPattern: "*"`) |
| **cilium-health-checks** | `reserved:health` (cilium-health endpoint) | remote-node | remote-node |
| **allow-gateway-ingress** | `reserved:ingress` (Gateway API Envoy) | world, cluster | cluster (per-backend restriction is each backend CNP's job) |

All regular pods can reach kube-dns for DNS resolution. Individual CNPs below do not repeat this rule. The selector excludes Cilium internal endpoints (e.g. Gateway) to avoid breaking `enforce_policy_on_l7lb`. L7 DNS rules enable Cilium DNS proxy for Hubble DNS metrics visibility.

## Cross-Namespace Communication

| From (namespace) | To (namespace) | Port | Purpose |
|---|---|---|---|
| Grafana (monitoring) | shared-pg (database) | 5432 | Dashboard state |
| Prometheus (monitoring) | CoreDNS (kube-system) | 9153 | Metrics scrape |
| Prometheus (monitoring) | Tetragon operator (kube-system) | 2113 | Metrics scrape |
| Prometheus (monitoring) | SeaweedFS (seaweedfs) | 9327 | Metrics scrape |
| Loki (monitoring) | SeaweedFS filer (seaweedfs) | 8333 | S3 storage |
| Tempo (monitoring) | SeaweedFS filer (seaweedfs) | 8333 | S3 storage |
| Argo Workflows controller (argo) | shared-pg (database) | 5432 | Workflow archive |
| Argo Workflows server (argo) | shared-pg (database) | 5432 | Workflow archive |
| CloudNative-PG (cnpg-system) | shared-pg (database) | 8000 | Health probes |
| Cloudflared (argocd) | EventSource (argo) | 12000 | GitHub webhook relay |
| Cloudflared (argocd) | Kanidm (kanidm) | 8443 | Cloudflare Tunnel → Kanidm |
| Workflow pods (argo) | SeaweedFS filer (seaweedfs) | 8333 | Artifact/log storage |
| Workflow pods (talos-build) | SeaweedFS filer (seaweedfs) | 8333 | Artifact/log storage |
| Workflow pods (image-build) | SeaweedFS filer (seaweedfs) | 8333 | Artifact/log storage |
| Workflow pods (claude-code) | SeaweedFS filer (seaweedfs) | 8333 | Artifact/log storage |
| Workflow pods (rss) | SeaweedFS filer (seaweedfs) | 8333 | Artifact/log storage |
| Workflow pods (claude-code) | Loki gateway (monitoring) | 8080 | Log query (logcli) |
| Workflow pods (claude-code-build) | Envoy data plane (llm-gateway) | 10080 | LLM API（alias 経由）**次段階。handler 側 egress は未実装** |
| Workflow pods (claude-code) | Envoy data plane (llm-gateway) | 10080 | LLM API（alias 経由）。claude-code の全 handler |
| Envoy data plane (llm-gateway) | Envoy Gateway (envoy-gateway-system) | 18000 | xDS |
| Envoy Gateway (envoy-gateway-system) | Agent Router (envoy-ai-gateway-system) | 1063 | extension server gRPC（xDS 変換） |
| Prometheus (monitoring) | Agent Router (envoy-ai-gateway-system) | 8080 | Metrics scrape |
| taskflow-cnp-check (claude-code) | Loki gateway (monitoring) | 8080 | Log query (cnp-check investigation) |
| PXE sync pods (argo) | SeaweedFS filer (seaweedfs) | 8333 | Artifact/log storage |
| Etcd backup (argo) | SeaweedFS filer (seaweedfs) | 8333 | Backup storage |
| Kanidm backup (argo) | SeaweedFS filer (seaweedfs) | 8333 | Backup storage |
| Kanidm repl-exchange (argo) | SeaweedFS filer (seaweedfs) | 8333 | Replication data |
| Argo Workflows server (argo) | SeaweedFS filer (seaweedfs) | 8333 | Archived log retrieval |
| Prometheus (monitoring) | Trivy Operator (trivy-system) | 8080 | Metrics scrape |
| Prometheus (monitoring) | Harbor (harbor) | 8001 | Metrics scrape |
| Prometheus (monitoring) | cert-manager controller/webhook/cainjector (cert-manager) | 9402 | Metrics scrape |
| Prometheus (monitoring) | taskflow-controller (taskflow-system) | 8443 | Metrics scrape |
| kube-apiserver | taskflow-controller (taskflow-system) | 9443 | TaskFlow admission webhook (failurePolicy: Fail) |
| Grafana (monitoring) | Kanidm (kanidm) | 8443 | OIDC token exchange (direct, via CoreDNS rewrite) |
| ArgoCD server (argocd) | Kanidm (kanidm) | 8443 | OIDC token exchange (direct, via CoreDNS rewrite) |
| Argo Workflows server (argo) | Kanidm (kanidm) | 8443 | OIDC token exchange (direct, via CoreDNS rewrite) |
| oauth2-proxy-hubble (oauth2-proxy) | Hubble UI (kube-system) | 8081 | Reverse proxy upstream |
| oauth2-proxy-hubble (oauth2-proxy) | Kanidm (kanidm) | 8443 | OIDC token exchange |
| oauth2-proxy-seaweedfs (oauth2-proxy) | SeaweedFS filer (seaweedfs) | 8888 | Reverse proxy upstream |
| oauth2-proxy-seaweedfs (oauth2-proxy) | Kanidm (kanidm) | 8443 | OIDC token exchange |
| oauth2-proxy-rss (oauth2-proxy) | rss-ui (rss) | 80 | Reverse proxy upstream (static UI) |
| oauth2-proxy-rss (oauth2-proxy) | rss-server (rss) | 80 | Reverse proxy upstream (/api) |
| oauth2-proxy-rss (oauth2-proxy) | Kanidm (kanidm) | 8443 | OIDC token exchange |
| oauth2-proxy-prometheus (oauth2-proxy) | Prometheus (monitoring) | 9090 | Reverse proxy upstream |
| oauth2-proxy-prometheus (oauth2-proxy) | Kanidm (kanidm) | 8443 | OIDC token exchange |
| Nextcloud (nextcloud) | shared-pg (database) | 5432 | Database |
| Nextcloud (nextcloud) | SeaweedFS filer (seaweedfs) | 8333 | S3 object storage |
| Nextcloud (nextcloud) | Kanidm (kanidm) | 8443 | OIDC token exchange (direct, via CoreDNS rewrite) |
| Cloudflared (argocd) | Nextcloud (nextcloud) | 80 | Cloudflare Tunnel → Nextcloud |
| Cloudflared (argocd) | Harbor nginx (harbor) | 8443 | Cloudflare Tunnel → Harbor |
| Workflow pods (image-build) | Harbor nginx (harbor) | 8443 | Internal image push |
| Kyverno (kyverno) | Harbor nginx (harbor) | 8443 | Image signature verification |
| scan-jobs (trivy-system) | Harbor nginx (harbor) | 8443 | Image scan from Harbor registry |
| image-digest-audit pods (argo) | Harbor nginx (harbor) | 8443 | Image digest audit |
| Renovate (argo) | Harbor nginx (harbor) | 8443 | Self-hosted Renovate digest lookup (tools/*) |
| tofu-harbor (argo) | Harbor nginx (harbor) | 8443 | registry.infra.tgy.io resolves to Harbor ClusterIP |
| SeaweedFS filer (seaweedfs) | shared-pg (database) | 5432 | Filer metadata (postgres2) |
| Harbor core (harbor) | shared-pg (database) | 5432 | Harbor database |
| Harbor jobservice (harbor) | shared-pg (database) | 5432 | Job metadata |
| Harbor exporter (harbor) | shared-pg (database) | 5432 | Metrics collection |
| Alertmanager (monitoring) | alertmanager-eventsource (argo) | 12001 | Alertmanager webhook relay |
| Harbor registry (harbor) | SeaweedFS filer (seaweedfs) | 8333 | S3 image storage |
| Harbor core (harbor) | Kanidm (kanidm) | 8443 | OIDC token exchange |
| Horenso (horenso) | shared-pg (database) | 5432 | Horenso database |
| shared-pg (database) | Cloudflare R2 (external) | 443 | CNPG barman backup/WAL archiving |
| CloudNative-PG (cnpg-system) | rss-pg (rss) | 8000 | Health probes |
| Workflow pods (claude-code) | Prometheus (monitoring) | 9090 | Metrics query |
| Workflow pods (claude-code) | Horenso (horenso) | 3000 | Task dispatch |
| notifications-controller (argocd) | Horenso (horenso) | 3000 | Alertmanager notifications |
| task-fail-sync pods (argo) | Horenso (horenso) | 3000 | Task failure notification |
| horenso-maintenance (argo) | Horenso (horenso) | 3000 | Daily maintenance report |
| notifications-controller (argocd) | argocd-deployed eventsource (argo) | 12003 | ArgoCD deployment event relay |
| Horenso (horenso) | task-dispatch-eventsource (argo) | 12002 | Task dispatch webhook |
| Workflow pods (claude-code) | task-dispatch-eventsource (argo) | 12002 | Adjudication webhook |
| Workflow pods (claude-code) | ArgoCD server (argocd) | 8080 | ArgoCD API access |
| memory (memory) | qdrant (qdrant) | 6333 | Vector database |
| memory (memory) | ollama (ollama) | 11434 | LLM inference |
| Workflow pods (claude-code) | memory (memory) | 3000 | Memory API access |
| Collector pods (trading) | SeaweedFS filer (seaweedfs) | 8333 | Market data ingestion |
| aqua-checksum (argo) | SeaweedFS filer (seaweedfs) | 8333 | Workflow step log/artifact upload |
| Collector pods (trading) | shared-pg (database) | 5432 | Market data ingestion |
| Reporter pods (trading) | shared-pg (database) | 5432 | Weekly report (read-only) |
| Prometheus (monitoring) | Argo Workflows controller (argo) | 9090 | Metrics scrape |
| Cloudflared (argocd) | oauth2-proxy-rss (oauth2-proxy) | 4180 | Cloudflare Tunnel → RSS |

## Excluded Pods (hostNetwork: true)

| Namespace | Pod | Reason |
|---|---|---|
| monitoring | node-exporter | Host metrics collection |
| monitoring | blackbox-exporter | IPv6 egress probe（ノードの VLAN 10 GUA を送信元にする必要がある。詳細は [IPv6](ipv6.md)） |
| kube-system | Cilium agent | CNI / networking（`kubeProxyReplacement: true` のため kube-proxy Pod は存在しない） |
| kube-system | Tetragon agent | eBPF runtime security (hostNetwork DaemonSet) |
| kube-system | kube-apiserver, etcd, scheduler, controller-manager | Control plane static pods |
| trident | trident-node-linux | CSI node plugin |

---

## argocd (8 policies)

| Component | Ingress | Egress |
|---|---|---|
| **server** | ingress, cloudflared, claude-code (claude-code) → 8080 | kube-apiserver, repo-server:8081, kanidm (kanidm):8443, redis:6379 |
| **application-controller** | host → 8082 | kube-apiserver, repo-server:8081, redis:6379 |
| **repo-server** | server, app-controller → 8081 | github.com + api.github.com + ghcr.io + {argoproj,grafana,grafana-community,oauth2-proxy,aquasecurity,kyverno,cloudnative-pg,kubernetes-sigs,prometheus-community,seaweedfs,stakater,qdrant}.github.io + *.githubusercontent.com + charts.jetstack.io + helm.cilium.io + helm.goharbor.io + charts.external-secrets.io + external-secrets.io + helm.otwld.com + registry-1.docker.io + auth.docker.io + production.cloudfront.docker.com:443, redis:6379 |
| **redis** | server, repo-server, app-controller → 6379 | (none) |
| **applicationset-controller** | (deny world) | kube-apiserver |
| **notifications-controller** | (deny world) | kube-apiserver, discord.com:443, horenso (horenso):3000, argocd-deployed-eventsource (argo):12003 |
| **redis-secret-init** (Job) | (deny world) | kube-apiserver |
| **cloudflared** | (deny world) | *.v2.argotunnel.com + cftunnel.com + h2.cftunnel.com + quic.cftunnel.com:443/7844 (7844 TCP+UDP), server:8080, eventsource (argo):12000, kanidm (kanidm):8443, nextcloud (nextcloud):80, harbor-nginx (harbor):8443, oauth2-proxy-rss (oauth2-proxy):4180 |

Docker Hub の 3 ホスト（`registry-1` / `auth` / `production.cloudfront`）は `oci://docker.io/envoyproxy` の
チャート（Agent Router / Envoy Gateway）用。Docker Hub は API・トークン・blob が別ホストに割れており、
blob は 307 で cloudfront に飛ぶ（2026-09-17 実測）。**1 つでも欠けるとチャートを引けず、
Application が Unknown のまま一度もレンダリングされない**（ghcr.io は単一ホストで済むので前例が無い）。

## argo (23 policies)

| Component | Ingress | Egress |
|---|---|---|
| **workflows-server** | ingress → 2746 (L7 HTTP); sensors (tofu-cloudflare, upgrade-k8s, pxe-sync), workflows-controller → 2746 | kube-apiserver, shared-pg (database):5432, kanidm (kanidm):8443, seaweedfs-filer (seaweedfs):8333 |
| **workflows-controller** | host → 6060; prometheus (monitoring) → 9090 (metrics, TLS) | kube-apiserver, shared-pg (database):5432, workflows-server:2746 |
| **eventsource** | cloudflared (argocd) → 12000 | kube-apiserver, eventbus:4222 |
| **alertmanager-eventsource** | alertmanager (monitoring) → 12001 | kube-apiserver, eventbus:4222 |
| **argocd-deployed-eventsource** | notifications-controller (argocd) → 12003 | kube-apiserver, eventbus:4222 |
| **task-dispatch-eventsource** | horenso (horenso), claude-code (claude-code) → 12002 | kube-apiserver, eventbus:4222 |
| **task-status-sync-eventsource** | (deny world) | kube-apiserver, eventbus:4222 |
| **task-status-sync-sensor** | (deny world) | kube-apiserver, eventbus:4222 |
| **task-fail-sync** (task-fail-sync=true) | (deny world) | horenso (horenso):3000 |
| **horenso-maintenance** (horenso-maintenance=true, CronWorkflow 4:30 JST) | (none) | horenso (horenso):3000 |
| **sensor** (tofu-cloudflare, tofu-unifi, tofu-harbor, upgrade-k8s, pxe-sync, talos-build, images-build, single-repo-build, alert-investigate, task-dispatch, renovate-webhook, aqua-checksum, pr-review-dispatch) | (deny world) | kube-apiserver, eventbus:4222, workflows-server:2746 |
| **talos-extension-bump-sensor** | (deny world) | kube-apiserver, eventbus:4222 |
| **events-controller** | host → 8081 | kube-apiserver, eventbus:8222 |
| **eventbus** | eventsource (github-webhook), alertmanager-eventsource (alertmanager-webhook), task-dispatch-eventsource (task-dispatch), task-status-sync-eventsource (task-status-sync), argocd-deployed-eventsource (argocd-deployed), sensors (tofu-cloudflare, tofu-unifi, tofu-harbor, upgrade-k8s, pxe-sync, talos-build, images-build, single-repo-build, alert-investigate, task-dispatch, task-status-sync, talos-extension-bump, renovate-webhook, aqua-checksum, pr-review-dispatch) → 4222; self → 6222/7777; events-controller → 8222 | self:6222/7777 |
| **workflow-pods** (backup-workflow, pxe-sync, talos-build, kanidm-repl-exchange, kanidm-backup, aqua-checksum除外) | (deny world) | kube-apiserver, HTTPS 443, kube-apiserver/remote-node/host:50000 (Talos apid — node IP は node identity を持つので toCIDR では一致しない), seaweedfs-filer (seaweedfs):8333 |
| **pluto-check-llm-gateway** (SA `pluto-checker`) | — | llm-gateway-envoy (llm-gateway):10080 |
| **etcd-backup** (backup-workflow=true) | (deny world) | kube-apiserver:6443/50000 (Talos apid), *.r2.cloudflarestorage.com:443, seaweedfs-filer (seaweedfs):8333 |
| **pxe-sync** (pxe-sync=true) | (deny world) | kube-apiserver, github.com + api.github.com + *.githubusercontent.com + dl-cdn.alpinelinux.org :443, seaweedfs-filer (seaweedfs):8333, QNAP NAS (192.168.5.240):2049 (NFS) |
| **kanidm-backup** (kanidm-backup=true) | (deny world) | kube-apiserver, *.r2.cloudflarestorage.com:443, seaweedfs-filer (seaweedfs):8333 |
| **kanidm-repl-exchange** (kanidm-repl-exchange=true) | (deny world) | kube-apiserver, seaweedfs-filer (seaweedfs):8333 |
| **image-digest-audit** (image-digest-audit=true) | (none) | harbor-nginx (harbor):8443 |
| **aqua-checksum** (aqua-checksum=true) | (none) | kube-apiserver, github.com + api.github.com + *.githubusercontent.com + discord.com + tuf-repo-cdn.sigstore.dev + get.helm.sh :443, seaweedfs-filer (seaweedfs):8333 |
| **renovate** (renovate=true) | (none) | harbor-nginx (harbor):8443 |
| **tofu-harbor** (tofu-harbor=true) | (none) | harbor-nginx (harbor):8443 |

## monitoring (12 policies)

| Component | Ingress | Egress |
|---|---|---|
| **prometheus** | grafana, tempo, claude-code (claude-code), kube-apiserver/remote-node (service proxy, RBAC services/proxy で制御) → 9090; oauth2-proxy-prometheus (oauth2-proxy) → 9090 (L7 HTTP: GET は `/debug`（大文字小文字を無視、programsize 24/100）を除いて許可、POST は query/query_range/query_exemplars/series/labels/format_query/parse_query のみ許可の allowlist（クエリ文字列付きも可、programsize 74/100）。他の POST・`/-/reload`・`/-/quit`・`/api/v1/write`・`/api/v1/admin/*`・`/debug/pprof/*` は拒否。allowlist は Prometheus のバージョンに紐づく手書きリストなので chart 更新時に見直すこと。見直しの合図は Renovate 側から出る — renovate.jsonc の packageRule が kube-prometheus-stack の minor/major 更新 PR の本文に確認事項を出す（chart patch は Prometheus の patch しか運ばない実測に基づき対象外）。緊急切り戻し手順は known-issues.md 参照) | kube-apiserver, alertmanager:9093/8080, kube-state-metrics:8080, operator:10250, grafana:3000, smartctl-exporter:9633, argo-workflows-controller (argo):9090, taskflow-controller (taskflow-system):8443, cert-manager controller/webhook/cainjector (cert-manager):9402, tempo:3200 (scrape), coredns (kube-system):9153, tetragon-operator (kube-system):2113, seaweedfs (seaweedfs):9327, trivy-operator (trivy-system):8080, ai-gateway-controller (envoy-ai-gateway-system):8080, harbor (harbor):8001, host/remote-node:10250/9100/9115/2379/2381/10257/10259/9965/2112 |
| **alertmanager** | prometheus → 9093/8080 | discord.com:443, discordapp.com:443, alertmanager-eventsource (argo):12001 |
| **grafana** | ingress → 3000 (L7 HTTP); prometheus → 3000 | kube-apiserver, prometheus:9090, loki-gateway:8080, tempo:3200, shared-pg (database):5432, kanidm (kanidm):8443 |
| **kube-state-metrics** | prometheus → 8080 | kube-apiserver |
| **prometheus-operator** | kube-apiserver/remote-node, prometheus → 10250 | kube-apiserver |
| **loki** | loki-gateway, loki-canary → 3100 | kube-apiserver, seaweedfs-filer (seaweedfs):8333, self:7946 (memberlist) |
| **loki-gateway** | grafana, alloy, loki-canary, claude-code (claude-code), taskflow-cnp-check (claude-code) → 8080 | loki:3100 |
| **loki-canary** | host → 3500 | loki-gateway:8080, loki:3100 |
| **alloy** | host → 12345 | kube-apiserver, loki-gateway:8080 |
| **tempo** | grafana, prometheus → 3200 | seaweedfs-filer (seaweedfs):8333, prometheus:9090 (metrics remote_write) |
| **smartctl-exporter** | prometheus → 9633 | (none, ローカルの /dev のみ参照) |
| **prometheus-admission** (Job) | (deny world) | kube-apiserver |

## talos-build (1 policy)

| Component | Ingress | Egress |
|---|---|---|
| **talos-build** (talos-build=true) | (deny world) | kube-apiserver, ghcr.io + github.com + api.github.com + uploads.github.com + *.githubusercontent.com + dl-cdn.alpinelinux.org + discord.com :443, seaweedfs-filer (seaweedfs):8333 |

## claude-code (7 policies)

| Component | Ingress | Egress |
|---|---|---|
| **claude-code** (claude-code=true) | (deny world) | kube-apiserver, llm-gateway (llm-gateway):10080, github.com + api.github.com + *.githubusercontent.com + index.crates.io + static.crates.io + registry.npmjs.org + discord.com + gitmcp.io :443, seaweedfs-filer (seaweedfs):8333, loki-gateway (monitoring):8080, prometheus (monitoring):9090, horenso (horenso):3000, task-dispatch-eventsource (argo):12002, argocd-server (argocd):8080 |
| **task-submitter** (task-submitter=true) | (deny world) | kube-apiserver, discord.com:443, seaweedfs-filer (seaweedfs):8333 |
| **taskflow-pr-review** (taskflow-pr-review=true) | (書かない = 全 deny) | github.com + api.github.com :443, llm-gateway (llm-gateway):10080 |
| **taskflow-cnp-check** (taskflow-cnp-check=true) | (書かない = 全 deny) | kube-apiserver:6443, github.com + api.github.com :443, llm-gateway (llm-gateway):10080, loki-gateway (monitoring):8080 |
| **taskflow-cnp-report** (taskflow-cnp-report=true) | (書かない = 全 deny) | discord.com + github.com + api.github.com :443, llm-gateway (llm-gateway):10080 |
| **taskflow-openrouter-smoke** (taskflow-openrouter-smoke=true) | (書かない = 全 deny) | openrouter.ai:443 |
| **taskflow-llm-gateway-smoke** (taskflow-llm-gateway-smoke=true) | (書かない = 全 deny) | llm-gateway (llm-gateway):10080（Service の port は 80、CNP は backend の 10080） |

`task-submitter` は Task を 1 つ作るだけの CronWorkflow の Pod。apiserver のほかに要る 2 つは
コントローラの workflowDefaults が全 Workflow に注入するもの（archiveLogs の保存先と
discord-notify の exit hook）で、これが無いと起票自体は通っても Workflow が Error になる。

`taskflow-pr-review` は**攻撃者が書ける入力（PR の diff）を読む** Pod なので、`claude-code=true` の
共有ポリシーには相乗りさせない（設計 §8）。apiserver も Loki も store も開いておらず、
到達できるのは GitHub と llm-gateway だけ（推論は gateway 経由。この Pod は LLM の
資格情報を持たない）。

**この Pod にだけ `discord.com` を開けていない**のは意図的で、他の claude-code Pod との違いはここ。
Cilium の identity は Pod 単位なので、通知サイドカーのために開けた egress はエージェントの
コンテナからも到達できる。Discord の webhook は誰でも作れて誰でも読めるため、開いていれば
注入されたエージェントが**攻撃者自身が受信ログを読める宛先**を手に入れる。initContainer の
`parts` が作る GitHub App の installation token や、読んだ private リポの中身がそこへ出ていく。
LLM の資格情報を handler から外した（#942）後もこの理由は変わらない — 抜ける物が
`CLAUDE_CODE_OAUTH_TOKEN` から他の資格情報とデータに移っただけで、`github.com` /
llm-gateway は攻撃者が受信ログを読めないのでこの性質が無い。
この flow は通知サイドカーを持たず、人間への通知は framework が終端で出す Warning Event /
`Ready=False` / metric から引く。

`taskflow-cnp-check` / `taskflow-cnp-report` は cnp-check flow の 2 フェーズに 1 枚ずつ。
割った理由は工程ではなく**到達範囲**で、フェーズごとに要るものだけを開ける。

- **調査**（`taskflow-cnp-check`）は点検対象を読むので apiserver と Loki が要る。
  **Discord は開けない** — 通知サイドカーは終端の 報告 にしかなく、Cilium の identity は
  Pod 単位なので、開けた穴はエージェントのコンテナからも使える（上の taskflow-pr-review と
  同じ理由。攻撃者が受信ログを読める宛先を与えないという話で、LLM トークンの有無ではない）
- **報告**（`taskflow-cnp-report`）は材料を workspace PVC 越しに受け取るので、
  ネットワークで要るのは推論 API と通知先だけ。**apiserver も Loki も開けない** —
  「材料に無いことは確かめようがない」を、プロンプトの約束ではなく到達可能性で支えている
- どちらも `github.com` / `api.github.com` を持つ。initContainer の `parts` が private の
  parts リポから skill / CLAUDE.md 断片を引き、GitHub App の installation token を作るため。
  init と agent は同じ identity なので agent からも届くが、GitHub は攻撃者が受信ログを
  読めない宛先（上の taskflow-pr-review と同じ整理）。**残存リスク**: agent 自身は GitHub を
  使わないのに到達できるので、攻撃者が用意した public な GitHub コンテンツを追加の指示として
  読み込める経路（fetch 方向）が残る。特に 報告 は前フェーズの LLM 出力＝信頼できない入力を
  材料にする Pod。これは pr-review で受容済みのパターンの拡張として受け入れる。狭めるなら
  init と agent の identity を分ける（Pod を分ける）しかなく、今はやらない

1 フェーズだった頃は共有の `claude-code=true` に相乗りしており、1 つの Pod が
apiserver・Loki・Discord・GitHub・npm・crates・SeaweedFS・Prometheus・horenso・ArgoCD を
まとめて持っていた。

2 つの smoke はどちらも「配管だけを確かめる」flow で、**出口に書かないもの**が主眼。
`taskflow-openrouter-smoke` は api.anthropic.com を書かないので、env が効かず Anthropic に
飛んだら drop されて落ちる。`taskflow-llm-gateway-smoke`（#942）は **openrouter.ai を書かない**
ので、gateway を経由せず Pod が直接出ようとしたら落ちる — 「外に出ているのは gateway だけ」を
緑/赤で判定できる形にしてある。後者の handler は資格情報を一切持たない。

## claude-code-build (1 policy)

| Component | Ingress | Egress |
|---|---|---|
| **taskflow-implement** (taskflow-implement=true) | (書かない = 全 deny) | openrouter.ai + github.com + api.github.com + *.githubusercontent.com + index.crates.io + static.crates.io + registry.npmjs.org :443 |

`claude-code` とは別 namespace（PSA が `privileged`。Kata ゲスト内で `volumeMode: Block` を
mkfs するため、docs/pod-security.md）にしてあるので CNP も分けて持つ。推論は Anthropic ではなく
OpenRouter で、**`api.anthropic.com` は開けていない** — env が効かず Anthropic へ落ちる取り違えを
緑で通さないため（`taskflow-openrouter-smoke.yaml` と同じ考え方）。`index.crates.io` /
`static.crates.io` / `registry.npmjs.org` は依存の取得用で、対応する言語を足すときはここも
足す必要がある（宛先が無いと失敗ではなくハングする）。

実際に openrouter.ai へ喋るのは `openrouter-broker` サイドカーだけで、`agent` コンテナは
127.0.0.1:8787 しか知らない設計（`manifests/claude-code-build/taskflow-implement.yaml`）。
それでも openrouter.ai の egress を agent 用に別途絞ることはできない — **CNP は Pod 単位
（同一 identity）で、同じ Pod 内のコンテナを分離できない**ため。将来「なぜ agent にまだ
openrouter.ai への直接到達があるのか」を漏れと誤診しないための記録。

## image-build (2 policies)

| Component | Ingress | Egress |
|---|---|---|
| **image-build** (image-build=true) | (deny world) | kube-apiserver, 0.0.0.0/0:443, harbor-nginx (harbor):8443 (internal push), seaweedfs-filer (seaweedfs):8333 |
| **workflow-pods** (workflows.argoproj.io/workflow が付き image-build=true が付かない Pod) | (deny world) | kube-apiserver, seaweedfs-filer (seaweedfs):8333, discord.com:443 |

`workflow-pods` は「ラベルを持たないまま投入されたワークフローが**自分の失敗を報告できる**」ための
最小限であって、任意のワークフローを動かすためのものではない。ビルドに要る egress は
`image-build` 側にある。

## seaweedfs (4 policies)

| Component | Ingress | Egress |
|---|---|---|
| **master** | master/volume/filer/bucket-hook → 9333/19333; prometheus (monitoring) → 9327 | master (self):9333/19333, volume:8080/18080, filer:8888/18888 |
| **volume** | master/filer/volume (self) → 8080/18080; prometheus (monitoring) → 9327 | master:9333/19333, volume (self):8080/18080 |
| **filer** | loki (monitoring), tempo (monitoring), workflow-pods (argo), workflow-pods (talos-build), workflow-pods (image-build), workflow-pods (claude-code), workflow-pods (rss), workflows-server (argo), etcd-backup (argo), pxe-sync (argo), kanidm-backup (argo), kanidm-repl-exchange (argo), aqua-checksum (argo), nextcloud (nextcloud), harbor-registry (harbor), collector (trading), ingress (main-gateway: s3.infra.tgy.io) → 8333; filer/master/bucket-hook/oauth2-proxy-seaweedfs (oauth2-proxy) → 8888/18888; prometheus (monitoring) → 9327 | master:9333/19333, volume:8080/18080, filer (self):8888/18888, shared-pg (database):5432 |
| **bucket-hook** (Job) | (deny world) | master:9333/19333, filer:8888/18888 |

## kube-system (6 policies)

| Component | Ingress | Egress |
|---|---|---|
| **coredns** | cluster/host/remote-node → 53; prometheus (monitoring) → 9153 | host:53 (upstream), kube-apiserver |
| **hubble-relay** | host → 4222; hubble-ui → 4245 | host/remote-node:4244, kube-apiserver:6443 |
| **hubble-ui** | oauth2-proxy-hubble (oauth2-proxy)/host → 8081 | kube-apiserver, hubble-relay:4245 |
| **metrics-server** | host/remote-node/kube-apiserver → 10250 | kube-apiserver, host/remote-node:10250 |
| **reloader** | host → 9090 (probes) | kube-apiserver |
| **tetragon-operator** | prometheus (monitoring) → 2113 | kube-apiserver |

## database (1 policy)

| Component | Ingress | Egress |
|---|---|---|
| **shared-pg** | grafana (monitoring), argo-workflows-controller (argo), argo-workflows-server (argo), nextcloud (nextcloud), harbor-core (harbor), harbor-exporter (harbor), harbor-jobservice (harbor), seaweedfs-filer (seaweedfs), horenso (horenso), trading (collector), trading (reporter) → 5432; ingress (pg-gateway: pg.infra.tgy.io TLS passthrough, 192.168.10.193:443 → shared-pg-rw:5432, direct-TLS clients only。**注意**: `pg_hba` の既定は `host all all all scram-sha-256` で、Envoy 中継のためクライアントの送信元 IP が見えず経路を区別できない。この ingress ルールは shared-pg の全ロール（grafana / argo / nextcloud / seaweedfs / horenso / trading / app）に到達可能にする。段階 2（クライアント証明書）までの暫定であり、反映後に `pg_stat_activity.client_addr` で Envoy 側の送信元アドレスを実測し、`pg_hba` で経路を分けられるか確認すること) → 5432; self → 5432/8000 (replication); cloudnative-pg (cnpg-system), host → 8000 (probes) | kube-apiserver, self:5432/8000, *.r2.cloudflarestorage.com:443 (backup) |

## cert-manager (4 policies)

| Component | Ingress | Egress |
|---|---|---|
| **controller** | host → 9403; prometheus (monitoring) → 9402 (metrics) | kube-apiserver, acme-v02.api.letsencrypt.org:443, api.cloudflare.com:443, external DNS 53 (propagation check) |
| **cainjector** | (deny world); prometheus (monitoring) → 9402 (metrics) | kube-apiserver |
| **webhook** | kube-apiserver/remote-node → 10250; host → 6080; prometheus (monitoring) → 9402 (metrics) | kube-apiserver |
| **startupapicheck** (Job) | (deny world) | kube-apiserver |

## external-dns (1 policy)

| Component | Ingress | Egress |
|---|---|---|
| **external-dns** | host → 7979 | kube-apiserver, api.cloudflare.com:443 |

## cnpg-system (1 policy)

| Component | Ingress | Egress |
|---|---|---|
| **cloudnative-pg** | kube-apiserver/host/remote-node → 9443 | kube-apiserver, shared-pg (database):8000, rss-pg (rss):8000 |

## external-secrets (2 policies)

| Component | Ingress | Egress |
|---|---|---|
| **external-secrets** | kube-apiserver/remote-node → 10250 | kube-apiserver, onepassword-connect:8080 |
| **onepassword-connect** | external-secrets → 8080; remote-node → 8080/8081 (probes) | *.1password.com:443, *.1passwordusercontent.com:443 |

## kyverno (5 policies)

| Component | Ingress | Egress |
|---|---|---|
| **admission-controller** | kube-apiserver/host/remote-node → 9443 | kube-apiserver, harbor-nginx (harbor):8443, *.sigstore.dev:443, registry.infra.tgy.io:443 |
| **background-controller** | (deny all) | kube-apiserver, harbor-nginx (harbor):8443 |
| **reports-controller** | (deny all) | kube-apiserver, harbor-nginx (harbor):8443, *.sigstore.dev:443, registry.infra.tgy.io:443 |
| **cleanup-controller** | kube-apiserver/host/remote-node → 9443 | kube-apiserver |
| **migrate-resources** (Job) | (none) | kube-apiserver |

## kanidm (1 policy)

| Component | Ingress | Egress |
|---|---|---|
| **kanidm** | ingress → 8443 (TLS Passthrough); cloudflared (argocd) → 8443; grafana (monitoring) → 8443; argocd-server (argocd) → 8443; argo-workflows-server (argo) → 8443; oauth2-proxy-hubble (oauth2-proxy) → 8443; oauth2-proxy-seaweedfs (oauth2-proxy) → 8443; oauth2-proxy-rss (oauth2-proxy) → 8443; oauth2-proxy-prometheus (oauth2-proxy) → 8443; nextcloud (nextcloud) → 8443; harbor-core (harbor) → 8443; self → 8444 (replication) | self:8444 (replication), kube-apiserver |

## oauth2-proxy (4 policies)

| Component | Ingress | Egress |
|---|---|---|
| **oauth2-proxy-hubble** | ingress → 4180 (L7 HTTP) | hubble-ui (kube-system):8081, kanidm (kanidm):8443 |
| **oauth2-proxy-seaweedfs** | ingress → 4180 (L7 HTTP) | seaweedfs-filer (seaweedfs):8888, kanidm (kanidm):8443 |
| **oauth2-proxy-rss** | ingress, cloudflared (argocd) → 4180 (L7 HTTP) | rss-ui (rss):80, rss-server (rss):80, kanidm (kanidm):8443 |
| **oauth2-proxy-prometheus** | ingress → 4180 (L7 HTTP) | prometheus (monitoring):9090, kanidm (kanidm):8443 |

## trivy-system (4 policies)

| Component | Ingress | Egress |
|---|---|---|
| **trivy-operator** | prometheus (monitoring) → 8080; host → 9090 (probes) | trivy-server:4954 (readiness check before creating scan jobs), kube-apiserver, mirror.gcr.io + registry-1.docker.io + auth.docker.io + production.cloudflare.docker.com + ghcr.io + registry.k8s.io + *.pkg.dev + quay.io + *.quay.io + public.ecr.aws :443 |
| **scan-jobs** (managed-by: trivy-operator) | deny world | 0.0.0.0/0:443 — registry CDN backends (S3, R2, CloudFront, etc.) are too numerous and dynamic for toFQDNs. Ephemeral pods, HTTPS only; harbor-nginx (harbor):8443; trivy-server:4954 |
| **trivy-server** | scan-jobs, trivy-operator → 4954; host → 4954 (probes) | mirror.gcr.io:443 (vuln DB) |
| **node-collector** (app: node-collector) | deny world | kube-apiserver |

## nfs-provisioner (1 policy)

| Component | Ingress | Egress |
|---|---|---|
| **nfs-provisioner** | deny world | kube-apiserver, 192.168.5.240:2049 (QNAP NFS) |

## harbor (8 policies)

| Component | Ingress | Egress |
|---|---|---|
| **nginx** | ingress, cloudflared (argocd), image-build (image-build), host/remote-node, kyverno (admission/background/reports-controller), scan-jobs (trivy-system), image-digest-audit (argo), renovate (argo), tofu-harbor (argo) → 8443; prometheus (monitoring) → 8001 | core:8080, portal:8080 |
| **core** | nginx, jobservice, exporter, trivy → 8080; prometheus (monitoring) → 8001 | shared-pg (database):5432, redis:6379, registry:5000/8080, portal:8080, jobservice:8080, trivy:8080, kanidm (kanidm):8443, kube-apiserver |
| **portal** | nginx, core → 8080 | (none) |
| **registry** | core, jobservice → 5000/8080; prometheus (monitoring) → 8001 | seaweedfs-filer (seaweedfs):8333, redis:6379 |
| **jobservice** | core → 8080; prometheus (monitoring) → 8001 | core:8080, redis:6379, registry:5000/8080, trivy:8080, shared-pg (database):5432 |
| **redis** | core, registry, jobservice, exporter, trivy → 6379 | (none) |
| **trivy** | core, jobservice → 8080; prometheus (monitoring) → 8001 | core:8080, redis:6379, ghcr.io + *.githubusercontent.com + registry.infra.tgy.io + mirror.gcr.io + check.trivy.dev :443/80 |
| **exporter** | prometheus (monitoring) → 8001 | core:8080, redis:6379, shared-pg (database):5432 |

## nextcloud (2 policies)

| Component | Ingress | Egress |
|---|---|---|
| **nextcloud** | ingress, cloudflared (argocd) → 80 | kube-apiserver, shared-pg (database):5432, seaweedfs-filer (seaweedfs):8333, kanidm (kanidm):8443, valkey:6379, *.nextcloud.com:443 (app store/updates), github.com:443 + *.githubusercontent.com:443 + *.github.com:443 (app store downloads) |
| **valkey** | nextcloud → 6379 | (none) |

## rss (8 policies)

| Component | Ingress | Egress |
|---|---|---|
| **rss-pg** | self → 5432/8000; rss-server/rss-ui/rss-fetcher/rss-cleaner/rss-migration → 5432; cloudnative-pg (cnpg-system), host → 8000 (probes) | kube-apiserver, self:5432/8000 |
| **rss-server** | oauth2-proxy-rss (oauth2-proxy) → 80 | rss-pg:5432 |
| **rss-ui** | oauth2-proxy-rss (oauth2-proxy) → 80 | rss-pg:5432 |
| **rss-fetcher** | rss-cron → 80 | rss-pg:5432, world:443 |
| **rss-cleaner** | rss-cron → 80 | rss-pg:5432 |
| **rss-cron** | (deny world) | rss-fetcher:80, rss-cleaner:80, kube-apiserver:6443, seaweedfs-filer (seaweedfs):8333 |
| **rss-workflow-exit** (workflows.argoproj.io/on-exit=true) | (deny world) | kube-apiserver:6443, seaweedfs-filer (seaweedfs):8333, discord.com:443 |
| **rss-migration** (Job) | (deny world) | rss-pg:5432 |

## horenso (1 policy)

| Component | Ingress | Egress |
|---|---|---|
| **horenso** | ingress/host/remote-node → 3000; argocd-notifications-controller (argocd) → 3000; claude-code (claude-code) → 3000; task-fail-sync (argo) → 3000; horenso-maintenance (argo) → 3000 | shared-pg (database):5432, discord.com + *.discord.com:443, task-dispatch-eventsource (argo):12002 |

## spin-operator (1 policy)

| Component | Ingress | Egress |
|---|---|---|
| **spin-operator** | kube-apiserver/host/remote-node → 9443 (webhook) | kube-apiserver |

## trident (2 policies)

| Component | Ingress | Egress |
|---|---|---|
| **controller** | host/remote-node → 8443 (CSI node registration) | kube-apiserver, 192.168.5.240:8080 (QNAP NAS) |
| **operator** | (deny world) | kube-apiserver |

## memory (1 policy)

| Component | Ingress | Egress |
|---|---|---|
| **memory** | ingress/host/remote-node → 3000; claude-code (claude-code) → 3000 | qdrant (qdrant):6333, ollama (ollama):11434 |

## qdrant (1 policy)

| Component | Ingress | Egress |
|---|---|---|
| **qdrant** | memory (memory) → 6333/6334 | (none) |

## ollama (1 policy)

| Component | Ingress | Egress |
|---|---|---|
| **ollama** | memory (memory) → 11434 | registry.ollama.ai + *.ollama.com + *.r2.cloudflarestorage.com:443 |

## taskflow-system (1 policy)

| Component | Ingress | Egress |
|---|---|---|
| **taskflow-controller** | host/remote-node → 8081 (probes); kube-apiserver/host/remote-node → 9443 (TaskFlow admission webhook); prometheus (monitoring) → 8443 (metrics, TLS + authn/authz) | kube-apiserver |

9443 は TaskFlow の構造検査 webhook（taskflow #17 / ADR-0006）。`fromEntities` に
`kube-apiserver` / `host` / `remote-node` の 3 つを並べているのは、このクラスタの他の
admission webhook（kyverno / cnpg / spin-operator、いずれも 9443）と同じ書き方に揃えているため。
この webhook は `failurePolicy: Fail` なので、
**ここを閉じると TaskFlow の作成・更新が全部拒否され、ArgoCD の sync が止まる**。

**どの identity で届くかは 2026-09-07 に実測した**（taskflow #107）。admission リクエストは
identity 6 = `reserved:remote-node` **だけ**で届き、`reserved:kube-apiserver` を持つ identity 7
では一度も来ない（hostNetwork の apiserver が CP ノードの cilium_host に SNAT され、
`kube-apiserver` ラベルが落ちるため）。外して確かめた結果、`remote-node` だけなら書き込みは
全部通り、`kube-apiserver` だけにすると `POLICY_DENIED` で drop されて書き込みは
`context deadline exceeded` で失敗する。**この行を支えているのは `remote-node`** で、
`kube-apiserver` はその部分集合なので残しても境界は広がらない。

`host` は Pod が CP ノードに乗る場合のための行だが、CP には `node-role.kubernetes.io/control-plane:NoSchedule`
taint があり taskflow-controller に toleration が無いので、現状は効いていない。

CNP を絞って測るときは、apiserver が張り済みの TCP 接続がそのまま通り続けることに注意する。
絞った直後に通っても許可の証拠にならない。Pod を入れ替えて接続を張り直させてから測ること
（2026-09-07 の実測でこれを踏み、`kube-apiserver` だけでも足りていると一度誤結論を出しかけた）。

この webhook が拒否側に倒れたときの症状と切り分けは [known-issues.md](known-issues.md) の
「TaskFlow 構造検査 webhook」節にある（caBundle 注入窓とコントローラ不在の 2 つ）。

## llm-gateway (1 policy)

| Component | Ingress | Egress |
|---|---|---|
| **llm-gateway-envoy** | claude-code-build / claude-code → 10080; argo (SA `pluto-checker` のみ) → 10080; host/remote-node → 19003 (probes) | envoy-gateway (envoy-gateway-system):18000, openrouter.ai + api.anthropic.com:443 |

Agent Router のデータプレーン（issue #942）。alias（`x-ai-eg-model`）で上流と実モデルが決まる。

**`claude-code` namespace の handler は全て gateway 経由**（2026-09-18 に達成）。
`api.anthropic.com` への直行も `claude-code-token` の参照もあの namespace には残っていない。

`argo` の `pluto-check` も 2026-09-18 に gateway 経由へ切り替えた。**Anthropic に直行するよう
設定された Pod はもう無い。**

ただし `pluto-check` だけは**クラスタが経路を強制していない**。他の 2 namespace は env が壊れて
直行に倒れると CNP で drop されて落ちる（＝取り違えが緑で通らない）が、argo の `workflow-pods` は
`toCIDR: 0.0.0.0/0`:443 を持ち、これは他の workflow Pod が使うので外せない。今は資格情報が無いので
どのみち失敗するが、**「gateway 経由である」ことは設定の話であって到達性の話ではない**。
揃えるなら `pluto-check` を `workflow-pods` の除外リストへ移して専用 CNP を持たせることになるが、
exit hook の discord-notify が同じ Pod ラベルを共有する問題を先に片付ける必要がある。

残る外部 LLM への直行は `claude-code-build` の `taskflow-implement` で、openrouter-broker
サイドカー経由で `openrouter.ai` に出る。それを倒すまで「外部 LLM への egress は llm-gateway
だけ」とは言えない。

**ingress は `claude-code` / `claude-code-build` については namespace 単位で開けている。つまり
この 2 つに Pod を足すと、その Pod は alias を名乗るだけで gateway の上流に到達できる。**
`argo` だけは SA（`pluto-checker`）で絞ってある — あの namespace には claude CLI 以外の
ワークロード（renovate / tofu-harbor / 各種 backup）が常駐しており、`workflow-pods` の
除外リストにも入っていないので、namespace 単位で開けるとそれら全部が Max の alias に届く。 #942 の第一段階では
その先は OpenRouter だけ（従量課金で、最悪でもコスト増）だったが、Max の alias
（`review` / `investigate`）を足した時点で、**同じ境界の裏に個人の Max サブスクリプションが入った**
（アカウント単位の OAuth で、異常な利用パターンは停止のリスクがある）。

Anthropic は subscription OAuth を「Claude Code の system prompt が先頭にあるか」でゲートしており、
claude CLI 以外がこの alias を叩いても*枠切れを装った 429* になるだけだが、**成否をクラスタ側で
制御できているわけではない**。`claude-code` / `claude-code-build` に claude CLI 以外の
ワークロードを足すときは、Max の alias に到達できることを承知した上で置くこと。

**絞りたくなったら今すぐできる。** Cilium は Pod の ServiceAccount を
`io.cilium.k8s.policy.serviceaccount` としてアイデンティティラベルに入れており（実測）、
flow ごとに専用 SA が既に割り当たっている（`agent-pr-reviewer` / `agent-llm-gateway-smoke` 等）。
namespace 単位の ingress を既知 SA の allowlist に置き換えるのは **CNP 側だけで完結**し、
taskflow 側の変更は要らない。`argo` は 2026-09-18 にこの形で入れた（`pluto-checker` のみ）。
残る 2 namespace も同じ形にできる。

Envoy の Pod がこの namespace に立つのは `helm-values/envoy-gateway/values.yaml` で
`deploy.type: GatewayNamespace` にしているため。**Envoy Gateway の既定は
`ControllerNamespace`** で、そのままだとデータプレーンが `envoy-gateway-system` 側に立ち、
この CNP は何も選択しない（＝ Pod は Running のまま外に出られない）。

同じ values の `watch.namespaces` は `envoy-gateway-system` と `llm-gateway` の 2 つだけで、
**この Envoy Gateway は他の namespace の Gateway / HTTPRoute / EnvoyProxy をエラーも出さずに
無視する**（`Cache.DefaultNamespaces` に代入されるだけで、コントローラ namespace も自動では
足されない）。別の namespace に Gateway を足すときは、ここに namespace を追加しないと
「作ったのに何も起きない」になる。

`10080` は listener port 80 に対して Envoy Gateway が実際に listen する port（特権 port を
避けて 1xxxx へずらす）。Service の port は 80 なので、CNP だけ数字が食い違って見える。

## envoy-gateway-system (2 policies)

| Component | Ingress | Egress |
|---|---|---|
| **envoy-gateway** | llm-gateway → 18000 (xDS); kube-apiserver/host/remote-node → 9443 (topologyInjector webhook) | kube-apiserver, agent-router (envoy-ai-gateway-system):1063 |
| **envoy-gateway-certgen** | (none) | kube-apiserver |

`certgen` は chart の pre-install / pre-upgrade フック Job（ArgoCD の PreSync）で、Pod ラベルが
`app: certgen` しかないためコントローラ用の CNP では選択されない。policy enforcement が always の
このクラスタでは **選択されないエンドポイントは egress も deny** なので、専用の CNP が無いと
PreSync が落ちて Application が一度も sync しない。

**この CNP 自身も `argocd.argoproj.io/hook: PreSync` + `sync-wave: "-2"` で PreSync フック
として入れている。** 通常リソースとして置くと適用が Sync フェーズ＝ Job より後になり、
初回は永久に収束しない。kyverno / seaweedfs の hook Job 用 CNP は post-install（PostSync）
なので通常リソースで足りており、**そのまま真似ると成立しない**。

## envoy-ai-gateway-system (1 policy)

| Component | Ingress | Egress |
|---|---|---|
| **agent-router-controller** | kube-apiserver/host/remote-node → 9443 (Pod mutator webhook); envoy-gateway (envoy-gateway-system) → 1063 (extension server gRPC); prometheus (monitoring) → 8080 (metrics, 素の HTTP) | kube-apiserver |

9443 の Pod mutator が届かないと Envoy の Pod に extproc が注入されず、**AI のルートを
持たないまま起動する**（Pod は Running なので気づきにくい）。taskflow-system と同じく、
実際にどの identity で届くかは hubble で確かめること。
