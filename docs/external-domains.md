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

- **用途**: 実行系 handler の LLM 呼び出し。経路は `llm-gateway`（Agent Router のデータプレーン）
  だけ。例外は `taskflow-openrouter-smoke` で、配線の対照実験としてここだけ意図的に直行する
- **Port**: 443

| Domain | Required | Notes |
|---|---|---|
| `openrouter.ai` | Yes | API（OpenAI 互換は `/api/v1`）。サブドメインは使わない |

## Anthropic（Max の alias）

- **用途**: `llm-gateway` の `review` / `investigate` alias と、local-dev 用の `claude-opus-5-5` / `claude-sonnet-5`（Max の OAuth トークンで Anthropic 直）
- **引く側**: Envoy データプレーン（`manifests/llm-gateway/netpol.yaml`）**だけ**。
  `claude-code` の handler も `argo` の `pluto-check` も gateway 経由で、直接は出ない。
  どれも CNP 側で直行を塞いであるので env 取り違えは drop で検出できる。ただし正しく設定して
  いても直行しうるため、handler 側で env 3 本を入れて止めている
  （根拠は `manifests/claude-code/taskflow-common.yaml`）。
  なお `argo` の**他の** workflow Pod は `workflow-pods` の `toCIDR: 0.0.0.0/0`:443 を
  持つので、ドメイン単位で許可していないだけで到達自体はできる
- **Port**: 443

| Domain | Required | Notes |
|---|---|---|
| `api.anthropic.com` | Yes | Messages API。Agent Router は Anthropic 固有ヘッダを足さないので、`anthropic-version` はクライアント（claude CLI）が送る |

**`claude-code` 側の CNP には無い。あちらに `api.anthropic.com` を足してはいけない。**
handler は全て llm-gateway 経由で、`api.anthropic.com` は 2026-09-18 に 4 箇所とも落とした。
正しく設定していても直行しうるため、handler 側で env 3 本を入れて止めている
（根拠は `manifests/claude-code/taskflow-common.yaml`）。取り違えが起きれば drop で検出される。

**`claude-code-build` には無い。あちらに `api.anthropic.com` を足してはいけない。**
`taskflow-implement.yaml` は「書かないこと」を不変条件として持っている。こちらも同じ理由で
env 3 本が要る（根拠は `manifests/claude-code/taskflow-common.yaml`）。取り違えが起きれば
drop で検出される。
