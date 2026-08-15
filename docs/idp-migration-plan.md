# IdP Migration Plan: Kanidm → Ory (Kratos + Hydra)

Status: 検討段階（未着手）

## 動機

- Kanidm のレプリケーション方式 (mutual-pull, 証明書交換) が煩雑
- UI カスタマイズ性が低い

## 構成

| コンポーネント | 役割 | 備考 |
|---|---|---|
| Kratos | 認証 (パスキーオンリー) | DB: shared-pg (CNPG) |
| Hydra | OAuth2/OIDC プロバイダ | DB: shared-pg (CNPG) |
| UI (自作) | ログイン + ポータル | SvelteKit、Harbor に push |

## レプリケーション

- Kratos/Hydra は stateless、データは PostgreSQL
- CNPG ストリーミングレプリケーションで HA（アプリ層のレプリケーション不要）

## 認証方式

- パスキー (WebAuthn/Passkeys) のみ、パスワードなし
- Kratos がネイティブサポート

## OIDC 連携対象（全て移行必要）

- ArgoCD (OIDC)
- Grafana (generic_oauth)
- Argo Workflows (OIDC confidential client)
- Hubble UI (oauth2-proxy → OIDC)
- Nextcloud (user_oidc)

## ポータル UI

### ログイン画面
- ロゴ + 「パスキーでログイン」ボタン

### ログイン後ダッシュボード
- サービス一覧: アイコングリッドで各サービスへのリンク
- クラスタ状況: Grafana iframe 埋め込み (CPU, Memory, Pod 数等)
  - `allow_embedding = true` + `cookie_samesite = none` を grafana.ini に設定
- パスキー管理: 登録済みデバイス一覧、追加・削除 (Kratos self-service settings)
### 管理画面（管理者ロールで表示）
- ユーザー管理: 一覧・追加・削除・パスキーリセット (Kratos Admin API)
- 招待メール送信: 新規ユーザーに登録リンクをメール通知 (Kratos SMTP)
- OIDC クライアント管理: サービスの追加・削除・設定変更 (Hydra Admin API)
  - クライアント作成時に 1Password Item を自動作成 (Connect API)
    - Hydra → client_id/client_secret 取得 → 1Password Connect API → Item 作成
    - ESO が自動で K8s Secret 生成（手作業ゼロ）
  - クライアント削除時に 1Password Item も自動削除
  - ExternalSecret YAML 雛形の生成・コピー機能
- ゲストアクセス (勉強会・デモ用):
  - 管理画面でトークン付きURL + QRコード生成 (有効期限設定、デフォルト24h)
  - 共有ゲストアカウント1つを事前作成 (Kratos, metadata: {role: guest})
  - リンクアクセス時: トークン検証 → 共有ゲストアカウントのセッション発行 → OIDC 連携
  - パスキーもメールも不要、QRスキャンだけでログイン完了
  - 勉強会終了後: 管理画面からセッション一括失効
  - ゲスト権限 (Hydra ID トークンに role=guest クレーム):
    - Grafana: role_attribute_path → Viewer (readonly)
    - ArgoCD: RBAC policy → readonly
    - Hubble UI: 閲覧可
    - Nextcloud: ゲストロールのログイン拒否
    - Argo Workflows: SSO RBAC → readonly

## メール送信

- Kratos 内蔵の SMTP 機能で招待・リカバリメール送信
- 外部サービス: Resend (無料枠 月3,000通、ホームラボなら十分)

## アーキテクチャ

```
ユーザー → UI (SvelteKit)
              ├── ログイン画面: ロゴ + パスキーボタン
              ├── ポータル: サービス一覧, パスキー管理, Grafana embed
              └── 管理画面: ユーザー管理, 招待メール, OIDCクライアント管理
                    │
                    ├── Kratos Public API (認証フロー)
                    ├── Kratos Admin API (ユーザー・招待管理)
                    ├── Hydra Public API (OIDC フロー)
                    ├── Hydra Admin API (クライアント管理)
                    ├── 1Password Connect API (クライアント作成時に Item 自動作成)
                    └── shared-pg (CNPG)

外部:
  Resend API ← Kratos SMTP
```

## 未決事項

- Kanidm → Kratos のユーザーデータ移行方法
- UI フレームワーク最終決定 (SvelteKit 有力)
- Grafana 埋め込みの認証方式 (クッキー共有 or Service Account Token)
- Kratos ↔ Hydra 連携設定の詳細
- Resend ドメイン設定 (tgy.io の DNS レコード追加)
- 管理者ロールの判定方法 (Kratos metadata or Hydra claims)
