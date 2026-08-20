# Network Policies

All policies are CiliumNetworkPolicy (CNP) and CiliumClusterwideNetworkPolicy (CCNP). Pods with `hostNetwork: true` are not subject to network policies and are excluded.

**Caveats:**
- Do NOT add L7 HTTP rules (`rules.http`) to ingress of services using TLS passthrough (TLSRoute). Cilium attempts to parse encrypted traffic as HTTP, breaking the connection.
- The `cluster` entity in `ingressDeny` includes `host` and `remote-node`. Since deny rules take precedence over allow rules, this blocks kubelet probes. Never use `cluster` in `ingressDeny` — use `world` only. For pods with probes, prefer ingress allow-only policies (implicit default deny) over `ingressDeny`.

## Cluster-Wide Policies (CCNP)

| Policy | Selector | Egress |
|---|---|---|
| **allow-dns** | all pods (`io.cilium.k8s.policy.cluster: default`) | kube-dns:53 (UDP/TCP) with L7 DNS proxy (`matchPattern: "*"`) |

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
| Workflow pods (claude-code) | Loki gateway (monitoring) | 8080 | Log query (logcli) |
| PXE sync pods (argo) | SeaweedFS filer (seaweedfs) | 8333 | Artifact/log storage |
| Etcd backup (argo) | SeaweedFS filer (seaweedfs) | 8333 | Backup storage |
| Kanidm backup (argo) | SeaweedFS filer (seaweedfs) | 8333 | Backup storage |
| Kanidm repl-exchange (argo) | SeaweedFS filer (seaweedfs) | 8333 | Replication data |
| Argo Workflows server (argo) | SeaweedFS filer (seaweedfs) | 8333 | Archived log retrieval |
| Prometheus (monitoring) | Trivy Operator (trivy-system) | 8080 | Metrics scrape |
| Prometheus (monitoring) | Harbor (harbor) | 8001 | Metrics scrape |
| Grafana (monitoring) | Kanidm (kanidm) | 8443 | OIDC token exchange (direct, via CoreDNS rewrite) |
| ArgoCD server (argocd) | Kanidm (kanidm) | 8443 | OIDC token exchange (direct, via CoreDNS rewrite) |
| Argo Workflows server (argo) | Kanidm (kanidm) | 8443 | OIDC token exchange (direct, via CoreDNS rewrite) |
| oauth2-proxy-hubble (oauth2-proxy) | Hubble UI (kube-system) | 8081 | Reverse proxy upstream |
| oauth2-proxy-hubble (oauth2-proxy) | Kanidm (kanidm) | 8443 | OIDC token exchange |
| oauth2-proxy-seaweedfs (oauth2-proxy) | SeaweedFS filer (seaweedfs) | 8888 | Reverse proxy upstream |
| oauth2-proxy-seaweedfs (oauth2-proxy) | Kanidm (kanidm) | 8443 | OIDC token exchange |
| oauth2-proxy-rss (oauth2-proxy) | rss-ui (rss) | 80 | Reverse proxy upstream |
| oauth2-proxy-rss (oauth2-proxy) | Kanidm (kanidm) | 8443 | OIDC token exchange |
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
| notifications-controller (argocd) | argocd-deployed eventsource (argo) | 12003 | ArgoCD deployment event relay |
| Horenso (horenso) | task-dispatch-eventsource (argo) | 12002 | Task dispatch webhook |
| Workflow pods (claude-code) | task-dispatch-eventsource (argo) | 12002 | Adjudication webhook |
| Workflow pods (claude-code) | ArgoCD server (argocd) | 8080 | ArgoCD API access |
| memory (memory) | qdrant (qdrant) | 6333 | Vector database |
| memory (memory) | ollama (ollama) | 11434 | LLM inference |

## Excluded Pods (hostNetwork: true)

| Namespace | Pod | Reason |
|---|---|---|
| monitoring | node-exporter | Host metrics collection |
| monitoring | blackbox-exporter | IPv6 egress probe（ノードの VLAN 10 GUA を送信元にする必要がある。詳細は [IPv6](ipv6.md)） |
| kube-system | Cilium agent, kube-proxy | CNI / networking |
| kube-system | Tetragon agent | eBPF runtime security (hostNetwork DaemonSet) |
| kube-system | kube-apiserver, etcd, scheduler, controller-manager | Control plane static pods |
| trident | trident-node-linux | CSI node plugin |

---

## argocd (8 policies)

| Component | Ingress | Egress |
|---|---|---|
| **server** | ingress, cloudflared, claude-code (claude-code) → 8080 | kube-apiserver, repo-server:8081, kanidm (kanidm):8443, redis:6379 |
| **application-controller** | host → 8082 | kube-apiserver, repo-server:8081, redis:6379 |
| **repo-server** | server, app-controller → 8081 | github.com + ghcr.io + {argoproj,grafana,grafana-community,oauth2-proxy,aquasecurity,kyverno,cloudnative-pg,kubernetes-sigs,prometheus-community,seaweedfs,stakater,qdrant}.github.io + *.githubusercontent.com + charts.jetstack.io + helm.cilium.io + helm.goharbor.io + charts.external-secrets.io + external-secrets.io + helm.otwld.com:443, redis:6379 |
| **redis** | server, repo-server, app-controller → 6379 | (none) |
| **applicationset-controller** | (deny world) | kube-apiserver |
| **notifications-controller** | (deny world) | kube-apiserver, discord.com:443, horenso (horenso):3000, argocd-deployed-eventsource (argo):12003 |
| **redis-secret-init** (Job) | (deny world) | kube-apiserver |
| **cloudflared** | (deny world) | *.v2.argotunnel.com + cftunnel.com + h2.cftunnel.com + quic.cftunnel.com:443/7844 (7844 TCP+UDP), server:8080, eventsource (argo):12000, kanidm (kanidm):8443, nextcloud (nextcloud):80, harbor-nginx (harbor):8443 |

## argo (22 policies)

| Component | Ingress | Egress |
|---|---|---|
| **workflows-server** | ingress → 2746 (L7 HTTP); sensors (tofu-cloudflare, upgrade-k8s, pxe-sync), workflows-controller → 2746 | kube-apiserver, shared-pg (database):5432, kanidm (kanidm):8443, seaweedfs-filer (seaweedfs):8333 |
| **workflows-controller** | host → 6060 | kube-apiserver, shared-pg (database):5432, workflows-server:2746 |
| **eventsource** | cloudflared (argocd) → 12000 | kube-apiserver, eventbus:4222 |
| **alertmanager-eventsource** | alertmanager (monitoring) → 12001 | kube-apiserver, eventbus:4222 |
| **argocd-deployed-eventsource** | notifications-controller (argocd) → 12003 | kube-apiserver, eventbus:4222 |
| **task-dispatch-eventsource** | horenso (horenso), claude-code (claude-code) → 12002 | kube-apiserver, eventbus:4222 |
| **task-status-sync-eventsource** | (none) | kube-apiserver, eventbus:4222 |
| **task-status-sync-sensor** | (none) | kube-apiserver, eventbus:4222 |
| **task-fail-sync** (task-fail-sync=true) | (none) | horenso (horenso):3000 |
| **sensor** (tofu-cloudflare, tofu-unifi, tofu-harbor, upgrade-k8s, pxe-sync, talos-build, images-build, single-repo-build, alert-investigate, task-dispatch, renovate-webhook) | (deny world) | kube-apiserver, eventbus:4222, workflows-server:2746 |
| **talos-extension-bump-sensor** | (none) | kube-apiserver, eventbus:4222 |
| **events-controller** | host → 8081 | kube-apiserver, eventbus:8222 |
| **eventbus** | eventsource (github-webhook), alertmanager-eventsource (alertmanager-webhook), task-dispatch-eventsource (task-dispatch), task-status-sync-eventsource (task-status-sync), argocd-deployed-eventsource (argocd-deployed), sensors (tofu-cloudflare, tofu-unifi, tofu-harbor, upgrade-k8s, pxe-sync, talos-build, images-build, single-repo-build, alert-investigate, task-dispatch, task-status-sync, talos-extension-bump, renovate-webhook) → 4222; self → 6222/7777; events-controller → 8222 | self:6222/7777 |
| **workflow-pods** (backup-workflow, pxe-sync, talos-build, kanidm-repl-exchange, kanidm-backup, aqua-checksum除外) | (deny world) | kube-apiserver, HTTPS 443, kube-apiserver/remote-node/host:50000 (Talos apid — node IP は node identity を持つので toCIDR では一致しない), seaweedfs-filer (seaweedfs):8333 |
| **etcd-backup** (backup-workflow=true) | (deny world) | kube-apiserver:6443/50000 (Talos apid), *.r2.cloudflarestorage.com:443, seaweedfs-filer (seaweedfs):8333 |
| **pxe-sync** (pxe-sync=true) | (deny world) | kube-apiserver, github.com + api.github.com + *.githubusercontent.com + dl-cdn.alpinelinux.org :443, seaweedfs-filer (seaweedfs):8333, QNAP NAS (192.168.5.240):2049 (NFS) |
| **kanidm-backup** (kanidm-backup=true) | (deny world) | kube-apiserver, *.r2.cloudflarestorage.com:443, seaweedfs-filer (seaweedfs):8333 |
| **kanidm-repl-exchange** (kanidm-repl-exchange=true) | (deny world) | kube-apiserver, seaweedfs-filer (seaweedfs):8333 |
| **image-digest-audit** (image-digest-audit=true) | (none) | harbor-nginx (harbor):8443 |
| **aqua-checksum** (aqua-checksum=true) | (deny world) | github.com + api.github.com + *.githubusercontent.com :443 |
| **renovate** (renovate=true) | (none) | harbor-nginx (harbor):8443 |
| **tofu-harbor** (tofu-harbor=true) | (none) | harbor-nginx (harbor):8443 |

## monitoring (12 policies)

| Component | Ingress | Egress |
|---|---|---|
| **prometheus** | grafana, tempo, claude-code (claude-code) → 9090 | kube-apiserver, alertmanager:9093/8080, kube-state-metrics:8080, operator:10250, grafana:3000, smartctl-exporter:9633, tempo:3200 (scrape), coredns (kube-system):9153, tetragon-operator (kube-system):2113, seaweedfs (seaweedfs):9327, trivy-operator (trivy-system):8080, harbor (harbor):8001, host/remote-node:10250/9100/9115/2379/2381/10257/10259/9965/2112 |
| **alertmanager** | prometheus → 9093/8080 | discord.com:443, discordapp.com:443, alertmanager-eventsource (argo):12001 |
| **grafana** | ingress → 3000 (L7 HTTP); prometheus → 3000 | kube-apiserver, prometheus:9090, loki-gateway:8080, tempo:3200, shared-pg (database):5432, kanidm (kanidm):8443 |
| **kube-state-metrics** | prometheus → 8080 | kube-apiserver |
| **prometheus-operator** | kube-apiserver/remote-node, prometheus → 10250 | kube-apiserver |
| **loki** | loki-gateway, loki-canary → 3100 | kube-apiserver, seaweedfs-filer (seaweedfs):8333, self:7946 (memberlist) |
| **loki-gateway** | grafana, alloy, loki-canary, claude-code (claude-code) → 8080 | loki:3100 |
| **loki-canary** | host → 3500 | loki-gateway:8080, loki:3100 |
| **alloy** | host → 12345 | kube-apiserver, loki-gateway:8080 |
| **tempo** | grafana, prometheus → 3200 | seaweedfs-filer (seaweedfs):8333, prometheus:9090 (metrics remote_write) |
| **smartctl-exporter** | prometheus → 9633 | (none, ローカルの /dev のみ参照) |
| **prometheus-admission** (Job) | (deny world) | kube-apiserver |

## talos-build (1 policy)

| Component | Ingress | Egress |
|---|---|---|
| **talos-build** (talos-build=true) | (deny world) | kube-apiserver, ghcr.io + github.com + api.github.com + uploads.github.com + *.githubusercontent.com + dl-cdn.alpinelinux.org + discord.com :443, seaweedfs-filer (seaweedfs):8333 |

## claude-code (1 policy)

| Component | Ingress | Egress |
|---|---|---|
| **claude-code** (claude-code=true) | (deny world) | kube-apiserver, api.anthropic.com + github.com + api.github.com + *.githubusercontent.com + index.crates.io + static.crates.io + registry.npmjs.org + discord.com + gitmcp.io :443, seaweedfs-filer (seaweedfs):8333, loki-gateway (monitoring):8080, prometheus (monitoring):9090, horenso (horenso):3000, task-dispatch-eventsource (argo):12002, argocd-server (argocd):8080 |

## image-build (1 policy)

| Component | Ingress | Egress |
|---|---|---|
| **image-build** (image-build=true) | (deny world) | kube-apiserver, 0.0.0.0/0:443, harbor-nginx (harbor):8443 (internal push), seaweedfs-filer (seaweedfs):8333 |

## seaweedfs (4 policies)

| Component | Ingress | Egress |
|---|---|---|
| **master** | master/volume/filer/bucket-hook → 9333/19333; prometheus (monitoring) → 9327 | master (self):9333/19333, volume:8080/18080, filer:8888/18888 |
| **volume** | master/filer/volume (self) → 8080/18080; prometheus (monitoring) → 9327 | master:9333/19333, volume (self):8080/18080 |
| **filer** | loki (monitoring), tempo (monitoring), workflow-pods (argo), workflow-pods (talos-build), workflow-pods (image-build), workflow-pods (claude-code), workflows-server (argo), etcd-backup (argo), pxe-sync (argo), kanidm-backup (argo), kanidm-repl-exchange (argo), nextcloud (nextcloud), harbor-registry (harbor) → 8333; filer/master/bucket-hook/oauth2-proxy-seaweedfs (oauth2-proxy) → 8888/18888; prometheus (monitoring) → 9327 | master:9333/19333, volume:8080/18080, filer (self):8888/18888, shared-pg (database):5432 |
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
| **shared-pg** | grafana (monitoring), argo-workflows-controller (argo), argo-workflows-server (argo), nextcloud (nextcloud), harbor-core (harbor), harbor-exporter (harbor), harbor-jobservice (harbor), seaweedfs-filer (seaweedfs), horenso (horenso) → 5432; self → 5432/8000 (replication); cloudnative-pg (cnpg-system), host → 8000 (probes) | kube-apiserver, self:5432/8000, *.r2.cloudflarestorage.com:443 (backup) |

## cert-manager (4 policies)

| Component | Ingress | Egress |
|---|---|---|
| **controller** | host → 9403 | kube-apiserver, acme-v02.api.letsencrypt.org:443, api.cloudflare.com:443, external DNS 53 (propagation check) |
| **cainjector** | (deny world) | kube-apiserver |
| **webhook** | kube-apiserver/remote-node → 10250; host → 6080 | kube-apiserver |
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
| **kanidm** | ingress → 8443 (TLS Passthrough); cloudflared (argocd) → 8443; grafana (monitoring) → 8443; argocd-server (argocd) → 8443; argo-workflows-server (argo) → 8443; oauth2-proxy-hubble (oauth2-proxy) → 8443; oauth2-proxy-seaweedfs (oauth2-proxy) → 8443; oauth2-proxy-rss (oauth2-proxy) → 8443; nextcloud (nextcloud) → 8443; harbor-core (harbor) → 8443; self → 8444 (replication) | self:8444 (replication), kube-apiserver |

## oauth2-proxy (3 policies)

| Component | Ingress | Egress |
|---|---|---|
| **oauth2-proxy-hubble** | ingress → 4180 (L7 HTTP) | hubble-ui (kube-system):8081, kanidm (kanidm):8443 |
| **oauth2-proxy-seaweedfs** | ingress → 4180 (L7 HTTP) | seaweedfs-filer (seaweedfs):8888, kanidm (kanidm):8443 |
| **oauth2-proxy-rss** | ingress → 4180 (L7 HTTP) | rss-ui (rss):80, kanidm (kanidm):8443 |

## trivy-system (3 policies)

| Component | Ingress | Egress |
|---|---|---|
| **trivy-operator** | prometheus (monitoring) → 8080; host → 9090 (probes) | kube-apiserver, mirror.gcr.io + registry-1.docker.io + auth.docker.io + production.cloudflare.docker.com + ghcr.io + registry.k8s.io + *.pkg.dev + quay.io + *.quay.io + public.ecr.aws :443 |
| **scan-jobs** (managed-by: trivy-operator) | deny world | 0.0.0.0/0:443 — registry CDN backends (S3, R2, CloudFront, etc.) are too numerous and dynamic for toFQDNs. Ephemeral pods, HTTPS only; harbor-nginx (harbor):8443 |
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

## rss (7 policies)

| Component | Ingress | Egress |
|---|---|---|
| **rss-pg** | self → 5432/8000; rss-server/rss-ui/rss-fetcher/rss-cleaner/rss-migration → 5432; cloudnative-pg (cnpg-system), host → 8000 (probes) | kube-apiserver, self:5432/8000 |
| **rss-server** | oauth2-proxy-rss (oauth2-proxy) → 80 | rss-pg:5432 |
| **rss-ui** | oauth2-proxy-rss (oauth2-proxy) → 80 | rss-pg:5432 |
| **rss-fetcher** | rss-cron → 80 | rss-pg:5432, world:443 |
| **rss-cleaner** | rss-cron → 80 | rss-pg:5432 |
| **rss-cron** | (none) | rss-fetcher:80, rss-cleaner:80 |
| **rss-migration** (Job) | (none) | rss-pg:5432 |

## horenso (1 policy)

| Component | Ingress | Egress |
|---|---|---|
| **horenso** | ingress/host/remote-node → 3000; argocd-notifications-controller (argocd) → 3000; claude-code (claude-code) → 3000; task-fail-sync (argo) → 3000 | shared-pg (database):5432, discord.com + *.discord.com:443, task-dispatch-eventsource (argo):12002 |

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
