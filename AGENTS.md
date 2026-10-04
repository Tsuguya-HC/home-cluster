# home-cluster

ArgoCD GitOps で管理される Kubernetes マニフェスト・Helm values。push → ArgoCD が即座に sync（selfHeal: true, prune: true）。

## ディレクトリ構成

```
apps/              # ArgoCD Application 定義（各サービス1ファイル）
argocd/            # app-of-apps.yaml（ArgoCD ブートストラップ）
helm-values/       # Helm chart の values.yaml（サービスごとにディレクトリ）
manifests/         # 生の K8s マニフェスト（namespace ごとにディレクトリ）
  infra/           # Gateway, CertManager, IP Pool, CCNP
  secrets/         # 全 ExternalSecret（専用 secrets app で管理）
  storage/         # CSI StorageClass, Backend
kustomize/         # Kustomize ベースのマニフェスト（QNAP CSI / taskflow / agent-router）
docs/              # 運用ドキュメント
```

## 変更パターン

- **新サービス**: `apps/` に Application YAML + `helm-values/` に values.yaml
- **Secrets**: `manifests/secrets/` に ExternalSecret YAML → External Secrets Operator が 1Password Connect Server 経由で Secret 自動生成（専用 `secrets` app で他 app の reconcile から隔離）
- **CNP 変更**: `manifests/<namespace>/netpol-*.yaml` + `docs/network-policies.md` を同時に更新。作業前に `docs/network-policies.md` で通信の全体像を掴み、**書くときの落とし穴は触る CNP の隣のコメント**を読むこと
- **SSO 追加**: `docs/sso.md` の手順に従う
- **新サービス（AppProject）**: `docs/argocd-projects.md` を参照。クラスタスコープリソースを使う場合は AppProject の `clusterResourceWhitelist` への追加を忘れないこと

## CiliumNetworkPolicy (CNP) 規約

全 Pod に CNP を適用（デフォルト deny）。DNS egress は CCNP (`manifests/infra/ccnp-dns.yaml`) で全 Pod に共通適用済み。新しい CNP を作るときは以下を守る:

### egress の必須ルール
```yaml
egress:
  # 1. DNS は CCNP で共通適用済み — 個別 CNP には不要
  # 2. kube-apiserver が必要なら toEntities で（必ず port: 6443 を指定）
  - toEntities:
      - kube-apiserver
    toPorts:
      - ports:
          - port: "6443"
            protocol: TCP
  # 3. 外部 HTTPS は toFQDNs で必要なドメインだけ許可
  - toFQDNs:
      - matchName: "example.com"
      - matchPattern: "*.example.com"
    toPorts:
      - ports:
          - port: "443"
            protocol: TCP
```

`toCIDR 0.0.0.0/0:443` は接続先を限定できないため、`toFQDNs` でドメイン単位で絞ること。広範なアクセスが必要な場合（ビルドジョブ等）のみ `toCIDR` を許容する。

### クロスネームスペース通信
- `io.kubernetes.pod.namespace` ラベルで namespace を指定
- ingress 側と egress 側の両方で許可が必要

### 確認手順
- `hubble observe --verdict DROPPED` で Policy denied を確認
- `http-request DROPPED` = L7 proxy drop（`toPorts` 起因）
- `Policy denied DROPPED` = L3/L4 drop

### docs/network-policies.md

**英語で、表だけ。** 各ポリシーが誰に何を許すかのカタログで、それ以外は書かない。

- 理由・経緯・落とし穴・実測の記録は書かない。それらは定義の隣（CNP のコメント）に置く
- 他の docs にある内容を写さない。ポインタも要らない
- 表のセルに収まらない説明が要るなら、それは表に書くことではない

## Helm values 規約

- コメントは「コメント」節の規則に従う
- Secret は envValueFrom + secretKeyRef で注入（ハードコード禁止）
- 不要になった設定は削除（コメントアウトで残さない）

## コメント

**書いてよいのは、その行を変える人が、知らなければ壊す制約だけ。** 判定は 2 つ。

1. **消したとき、次に触る人は壊すか。** 壊さないなら要らない。役に立たないコメントは
   読む手間の分だけ損をさせる
2. **嘘になったとき、その行を触る人は気づくか。** 気づく仕組みが無いなら書かない。
   嘘や腐った情報は、無いより悪い

片方でも通らないなら書かない。隣の定義についての制約は、定義を変える人が必ずコメントも
目にするので腐れば気づく。**視界の外のこと——upstream の挙動、他コンポーネントの構成、
個数——は、向こうが変わった瞬間に嘘になり、誰も気づかない。** 制約を書くときも、根拠に
それらを含めない（`全キーを 15 handler に伝播する` ではなく `全キーを全 handler に伝播する`）。

**この 2 条を通っても書かないもの。**

- **CI の機械チェックで固定できる命題。** kubeconform / `scripts/unread-values.py` / helm-template /
  image-existence / argo-lint / configmap-scripts / `/lint` のどれかで検査できるなら、
  コメントではなく検査を足す。再現コストの高さは記録する理由であって、コメントに置く理由ではない
- **他への参照。**「〜参照」「〜に書いてある」「〜の冒頭コメント」、および行番号。
  参照先は動いても消えても気づかれず、飛ばされた側はその 1 行では何も分からない

出典（`#NNN` / `ADR-NNNN` / upstream の URL）は書いてよい。未了の作業と受容したリスクは
コメントではなく issue か ADR に立て、番号だけ残す。

**制約は、制約する対象の隣に、そこだけで完結させる。** 同じ制約が 2 箇所に要るなら、まず
定義側の重複を疑う —— 同じ env・同じルールが 2 箇所にあるから、制約も 2 箇所に要る。定義を
寄せられるなら寄せる。寄せられないならコメントはコピーしてよい。参照に置き換えても腐り方は
同じで、読みやすさだけが失われる。

既存のコメントを一括で書き換えることはしない。**新しく書くコメントと、触ったコメントに適用する。**

## 検証

変更後は以下を確認:
1. `kubectl get pods -A` — 全 Pod が Running
2. `hubble observe --verdict DROPPED` — 意図しない drop がないこと
3. ノードリブート後も正常復帰すること
4. `/lint` — push 前の静的チェック（`/lint --all` で全ファイル監査）

## 注意事項

- push は即座に本番反映される。変更内容をよく確認してから push
- main はマージキュー経由でしか更新されない。PR のマージは `gh pr merge` でキューに入る（**`--squash` を付けるとキューが戦略を持つため拒否される**）。キューが main に対する一時 commit を作り、その上で `CI Gate` と `digest-cooldown` を取り直してから main に入れる（main より遅れた緑 PR がそのまま載ることはない）
- Cilium Gateway bug (#41970): GAMMA（mesh）HTTPRoute（`parentRefs.kind: Service`）を Service に直接貼った場合、その Service は `world` identity になり L7 proxy で 403 になる。`kind: Gateway` 経由（このクラスタの HTTPRoute は全てこちら）は該当しない
