# External Domain Requirements

CNP egress (`toFQDNs`) 設定時のリファレンス。各外部サービスが必要とするドメインとポートをまとめる。

## 1Password Connect Server

- **Source**: https://support.1password.com/ports-domains/
- **Port**: 443

| Domain | Required | Notes |
|---|---|---|
| `*.1password.com` | Yes | Core API |
| `*.1passwordusercontent.com` | Yes | Vault data (attachments, profile images) |
| `*.1passwordservices.com` | No | Telemetry, subscription management — Connect Server では不要 |

## Docker Hub（OCI Helm チャート）

- **用途**: `oci://docker.io/envoyproxy` の `gateway-helm` / `ai-gateway-helm` 系（Envoy Gateway / Agent Router）
- **引く側**: ArgoCD repo-server（`manifests/argocd/netpol-repo-server.yaml`）
- **Port**: 443
- **実測**: 2026-09-17

| Domain | Required | Notes |
|---|---|---|
| `registry-1.docker.io` | Yes | Registry API（`docker.io` はクライアント側でここへ正規化される） |
| `auth.docker.io` | Yes | Bearer トークンの発行。401 の `WWW-Authenticate` realm がここを指す |
| `production.cloudfront.docker.com` | Yes | blob の実体。manifest 取得後に 307 で飛ぶ |

`ghcr.io`（spin-operator）は単一ホストで完結するので、OCI = 1 ドメインという先入観を持ちやすい。
Docker Hub は 3 つに割れており、**欠けても「認証エラー」ではなく単に引けない**ので、
Application が Unknown のまま止まる形で出る。

## OpenRouter

- **用途**: 実行系 handler の LLM 呼び出し。今は `llm-gateway`（Agent Router のデータプレーン）と
  `claude-code-build` の openrouter-broker サイドカーの 2 経路があり、handler の切り替えが済めば前者だけになる
- **Port**: 443

| Domain | Required | Notes |
|---|---|---|
| `openrouter.ai` | Yes | API（OpenAI 互換は `/api/v1`）。サブドメインは使わない |

## Anthropic（Max の alias）

- **用途**: `llm-gateway` の `review` / `investigate` alias（Max の OAuth トークンで Anthropic 直）
- **引く側**: Envoy データプレーン（`manifests/llm-gateway/netpol.yaml`）。`claude-code` の
  handler は gateway 経由なので直接は出ない。ただし `argo` の `pluto-check` は未切り替えで、
  `manifests/argo/netpol-workflow-pods.yaml` の `toCIDR: 0.0.0.0/0`:443 から直接引いている
- **Port**: 443

| Domain | Required | Notes |
|---|---|---|
| `api.anthropic.com` | Yes | Messages API。Agent Router は Anthropic 固有ヘッダを足さないので、`anthropic-version` はクライアント（claude CLI）が送る |

**`claude-code` 側の CNP には無い。あちらに `api.anthropic.com` を足してはいけない。**
handler は全て llm-gateway 経由で、`api.anthropic.com` は 2026-09-18 に 4 箇所とも落とした。
env が効かず Anthropic に直行したら drop されて落ちる、という形で取り違えを検出している。

**`claude-code-build` には無い。あちらに `api.anthropic.com` を足してはいけない。**
`taskflow-implement.yaml` は「書かないこと」を不変条件として持っており、env が効かず
Anthropic に飛んだら drop されて落ちる、という設計で取り違えを検出している。
