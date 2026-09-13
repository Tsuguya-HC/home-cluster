# 1Password Connect Secret のローテーション

Secret `onepassword-connect`（namespace `external-secrets`）は `1password-credentials.json` と `token` の2キーを持つ。定常運用で繰り返すローテーション手順をここにまとめる（初回構築は `manual/README.md` の手順4を参照）。

## 前提

- Reloader が Secret 差し替えを検知して ESO と Connect Server を自動再起動する（`secret.reloader.stakater.com/reload` annotation。`helm-values/external-secrets/values.yaml` / `helm-values/onepassword-connect/values.yaml`）
- **Stakater Reloader の SHA 計算は Secret の全キーを連結して行うため、どちらのキーを変更しても ESO と Connect Server の両方が再起動する。**「token だけ変えれば Connect Server には影響しない」は誤り
- **作業開始前に旧 credentials.json と旧トークンを保持しておくこと。** 1Password 側で revoke/失効させた後は失敗時に戻せない。**保持は 1Password 側の一時 item（Secure Note 等）にのみ行い、ローカルのファイルには書き出さない**（このリポジトリは PUBLIC のワーキングツリー、消し忘れが誤コミット経路になる）。作業完了後はその一時 item も削除する
- **ESO / Connect Server が止まっている間も、既に生成済みの Kubernetes Secret は削除されず残る。** 影響は将来の `refreshInterval` ベースの再同期が止まることに限られ、既存ワークロードが即座に落ちるわけではない。ただし復旧を後回しにするほど、その間に必要になった別の secret 更新（新規デプロイ、別の資格情報ローテーション等）も同時に止まる

## readinessProbe は資格情報の健全性を検出できない

Connect Server の readinessProbe は `/health` への httpGet だが、1Password API は資格情報が未確立（`TOKEN_NEEDED`）でも HTTP 200 を返す（状態は body で伝える）。httpGet probe は body を見ないため、壊れた資格情報を積んだ Pod でも Ready になる。ESO 側には probe が無い。**資格情報を誤ると、両方の「最後に正常だった Pod」が自動検知ゼロで同時に消える。** 下記の手順で必ず検証すること。

## token のみのローテーション

1. 1Password の Connect Server で新規トークンを発行する（vault `home-cluster` へのスコープを既存トークンと揃える）
2. 差し替え前に ESO Pod の `creationTimestamp` を記録する:
   ```bash
   kubectl get pod -n external-secrets -l app.kubernetes.io/name=external-secrets -o jsonpath='{.items[*].metadata.creationTimestamp}'
   ```
3. Secret `onepassword-connect` の `token` キーを新トークンで差し替える
4. Reloader が ESO と Connect Server の両方を再起動する。ESO Pod の `creationTimestamp` が入れ替わったことを確認する
5. 取得が実際に通ることを確認する:
   ```bash
   kubectl annotate externalsecret -n argo argo-pg-credentials force-sync="$(date +%s)" --overwrite
   kubectl get externalsecret -n argo argo-pg-credentials
   ```
   force-sync した対象の `refreshTime` が更新されていることを確認する。他の ExternalSecret は `refreshInterval` がバラバラなので `refreshTime` が更新されなくて正常 — `kubectl get externalsecret -A` で全件 `SecretSynced` のままであること（`SecretSyncedError` が出ていないこと）だけを見る
6. 1Password 側で**旧トークンを revoke** する
7. revoke 後、もう一度同じ force-sync を実行し、取得が成功することを確認する。**これが決定的な検証**——旧トークンが失効した後で取得が成功するなら、新トークンが実際に使われている証拠になる

### 失敗時の復旧

- 手順5（revoke 前）の検証が失敗した場合: Secret の `token` を旧トークンに戻す。旧トークンはまだ有効なので復旧する
- 手順7（revoke 後）の検証が失敗した場合: 旧トークンには戻せない。1Password 側で新トークンを再発行し、Secret に入れ直した上で ESO / Connect Server を手動 `rollout restart` する

## credentials.json のローテーション

1Password は「同じ Connect Server に対して複数トークンを持てるが、各 Connect Server は自身専用のトークン集合を持つ」（[1Password 公式ドキュメント](https://support.1password.com/connect-deploy-kubernetes/)）。新しい `1password-credentials.json` を発行する操作は**新しい Connect Server デバイスを作る操作**であり、旧デバイス用のトークンは新デバイスでは通らない。**credentials.json だけを差し替えて token を据え置くと、Connect Server 再起動後に ESO の認証が全面的に通らなくなり、全 namespace の secrets 同期が停止する。**

したがって、新デバイスの credentials.json と、その新デバイス用に発行した新トークンを、**1回の操作で同時に** Secret へ書き込むこと。

1. 1Password Web UI の「Integrations > Connect Server」で新規デバイスの credentials.json を発行し、同時にその新デバイス用のトークンも発行する（vault `home-cluster` へのスコープを既存と揃える）
2. 差し替え前に ESO と Connect Server 両方の Pod の `creationTimestamp` を記録する:
   ```bash
   kubectl get pod -n external-secrets -o jsonpath='{range .items[*]}{.metadata.name}{"\t"}{.metadata.creationTimestamp}{"\n"}{end}'
   ```
   `external-secrets-webhook-*` と `external-secrets-cert-controller-*` の2 Pod は Reloader annotation の対象外なので `creationTimestamp` は変わらない（正常）
3. Secret `onepassword-connect` の `1password-credentials.json` と `token` を、新デバイスのものへ**同時に**差し替える
4. Reloader が ESO と Connect Server の両方を再起動する。両方の Pod の `creationTimestamp` が入れ替わったことを確認する
5. token のローテーションと同じ手順（上記5〜7）で force-sync による検証を行い、確認できたら旧デバイスを 1Password 側で失効させる

### 失敗時の復旧

token のローテーションと同様。旧デバイスを失効させる前に失敗が分かった場合は Secret を旧の credentials.json / token へ戻す。失効させた後に失敗が分かった場合は、1Password 側で新デバイスと新トークンを再発行して Secret を入れ直し、ESO / Connect Server を手動 `rollout restart` する。
