# 災害復旧

R2 オフサイトバックアップからの復旧手順。

## バックアップ構成

| 対象 | 方式 | スケジュール | 保持期間 |
|------|------|-------------|---------|
| PostgreSQL (shared-pg) | CNPG barman → R2 | WAL: リアルタイム / base backup: 毎日 3:00 JST | CNPG: 7日 / R2: 14日 |
| etcd | talosctl snapshot → R2 | 毎日 4:00 JST | R2: 14日 |
| Kanidm | online_backup (PVC) + scripting backup → R2 | PVC: 毎日 4:00 JST / R2: 毎日 4:30 JST | PVC: 3世代 / R2: 14日 |

バケット: `s3://home-cluster-backup/` (Cloudflare R2, APAC)

PostgreSQL は二段階の保持: CNPG が 7日で古いバックアップカタログを整理し、R2 ライフサイクルが 14日でオブジェクトを最終削除する。

## PostgreSQL 復旧

### 前提

- `r2-backup-credentials` Secret が database namespace に存在すること
- R2 バケットにバックアップが存在すること

### 手順

1. `shared-pg.yaml` の `bootstrap` セクションを `recovery` に変更:

```yaml
apiVersion: postgresql.cnpg.io/v1
kind: Cluster
metadata:
  name: shared-pg
  namespace: database
spec:
  # ... (既存の instances, resources, storage はそのまま)
  bootstrap:
    recovery:
      source: shared-pg-backup
      # PITR する場合は targetTime を指定
      # recoveryTarget:
      #   targetTime: "2026-02-22T09:00:00Z"
  externalClusters:
    - name: shared-pg-backup
      barmanObjectStore:
        destinationPath: s3://home-cluster-backup/cnpg/
        endpointURL: https://b0832b1c20a7cada26af0ac45862ce80.r2.cloudflarestorage.com
        s3Credentials:
          accessKeyId:
            name: r2-backup-credentials
            key: credential
          secretAccessKey:
            name: r2-backup-credentials
            key: password
  # managed, backup セクションは既存のまま残す
```

2. 既存 Cluster を削除して再作成（ArgoCD が自動 sync）:

```bash
kubectl delete cluster shared-pg -n database
git add manifests/database/shared-pg.yaml && git push
```

3. リカバリ完了後、`bootstrap` を元の `initdb` に戻して push（次回の再作成時に initdb に戻らないように）。ただし CNPG は bootstrap 済みクラスタの bootstrap セクション変更を無視するため、急がなくてよい。

### 確認

```bash
kubectl get cluster shared-pg -n database
kubectl logs -n database -l cnpg.io/cluster=shared-pg --tail=20
# "recovery completed" のログを確認
```

## Kanidm 復旧

Kanidm は 2 Pod レプリケーション構成（mutual-pull）。片方のデータロスは他方から再同期で復旧可能。

### 片方のデータロス

Pod が空 DB で再起動した場合、レプリケーション証明書も再生成されるため ConfigMap の更新が必要。

1. 新しい証明書を取得:

```bash
kubectl exec -n kanidm kanidm-<N> -- kanidmd show-replication-certificate -c /config/server.toml
```

2. `manifests/kanidm/configmap-repl.yaml` のパートナー証明書を更新して push

3. Reloader が Pod をローリングリスタート後、consumer refresh で同期:

```bash
kubectl exec -n kanidm kanidm-<N> -- kanidmd refresh-replication-consumer -c /config/server.toml
```

### 両方のデータロス（R2 バックアップからリストア）

1. R2 からバックアップをダウンロード:

```bash
mc alias set r2 https://b0832b1c20a7cada26af0ac45862ce80.r2.cloudflarestorage.com <ACCESS_KEY> <SECRET_KEY>

# 最新のバックアップを確認
mc ls r2/home-cluster-backup/kanidm/

# ダウンロード
mc cp r2/home-cluster-backup/kanidm/<TIMESTAMP>.backup /tmp/kanidm-backup
```

2. Kanidm Pod を 1 レプリカにスケールダウン（StatefulSet replicas: 1）

3. バックアップをリストア:

```bash
# Pod を停止（replicas: 0）
kubectl scale statefulset kanidm -n kanidm --replicas=0

# バックアップファイルを PVC にコピー（一時 Pod 経由）
kubectl run kanidm-restore --image=alpine:3.23 -n kanidm --restart=Never \
  --overrides='{"spec":{"volumes":[{"name":"data","persistentVolumeClaim":{"claimName":"data-kanidm-0"}}],"containers":[{"name":"restore","image":"alpine:3.23","command":["sleep","3600"],"volumeMounts":[{"name":"data","mountPath":"/data"}],"securityContext":{"runAsUser":1000,"runAsGroup":1000}}]}}'

kubectl cp /tmp/kanidm-backup kanidm/kanidm-restore:/data/restore.backup

# kanidmd database restore で復元（一時 Pod 内で実行は不可 — kanidmd バイナリがない）
# 代わりに kanidm イメージで restore を実行
kubectl delete pod kanidm-restore -n kanidm
kubectl run kanidm-restore --image=docker.io/kanidm/server:1.9.1 -n kanidm --restart=Never \
  --overrides='{"spec":{"volumes":[{"name":"data","persistentVolumeClaim":{"claimName":"data-kanidm-0"}},{"name":"config","configMap":{"name":"kanidm-server-config"}}],"containers":[{"name":"restore","image":"docker.io/kanidm/server:1.9.1","command":["kanidmd","database","restore","-c","/config/server.toml","/data/restore.backup"],"volumeMounts":[{"name":"data","mountPath":"/data"},{"name":"config","mountPath":"/config","readOnly":true}],"securityContext":{"runAsUser":1000,"runAsGroup":1000}}]}}'

# restore 完了を確認
kubectl logs -n kanidm kanidm-restore
kubectl delete pod kanidm-restore -n kanidm
```

4. StatefulSet を元に戻す（replicas: 2）。kanidm-1 はレプリケーションで自動同期。
   レプリケーション証明書が不一致の場合は「片方のデータロス」の手順で証明書を更新。

## etcd 復旧

### 前提

- 全 CP ノードの Talos API にアクセスできること
- talosctl + mc がインストール済み（WSL2 で実行）
- R2 の credentials を手元に持っていること

### 手順

1. R2 からスナップショットをダウンロード:

```bash
mc alias set r2 https://b0832b1c20a7cada26af0ac45862ce80.r2.cloudflarestorage.com <ACCESS_KEY> <SECRET_KEY>

# 最新のスナップショットを確認
mc ls r2/home-cluster-backup/etcd/

# ダウンロード
mc cp r2/home-cluster-backup/etcd/<TIMESTAMP>.db /tmp/etcd-snapshot.db
```

2. **全 CP ノード**の etcd メンバーをリセット:

```bash
# 全 CP に対して etcd を停止・ワイプ
talosctl -n 192.168.10.230,192.168.10.231,192.168.10.232 reset \
  --graceful=false --reboot --system-labels-to-wipe=EPHEMERAL
```

3. 1台目の CP でスナップショットからブートストラップ:

```bash
talosctl bootstrap --recover-from=/tmp/etcd-snapshot.db -n 192.168.10.230
```

4. 残りの CP が自動的に etcd クラスタに join するのを待つ:

```bash
talosctl -n 192.168.10.230 health \
  --control-plane-nodes 192.168.10.230,192.168.10.231,192.168.10.232 \
  --worker-nodes 192.168.10.200,192.168.10.201,192.168.10.202
```

### 注意

- `talosctl bootstrap --recover-from` は**クラスタが完全に壊れた場合**のみ使う
- 既存 etcd が動いている状態では実行しない
- リカバリ後、ArgoCD が全リソースを再 sync するため一時的に Pod の再起動が発生する

## ノード IP 移行（VLAN 移行等）

全ノードの IP を一括変更する手順。etcd のピア URL がデータに記録されているため、Talos config の IP 変更だけでは etcd クラスタが壊れる。

### 前提

- 新旧どちらのサブネットにも PC から到達可能であること
- 新サブネットのゲートウェイ・DHCP が設定済みであること

### 手順

#### 1. 設定変更

```bash
# home-infra: talconfig.yaml の全ノード IP, VIP, gateway, nameservers を変更
cd home-infra
vim talconfig.yaml
make genconfig
```

#### 2. staged apply（全ノード）

再起動するまで反映されない `--mode=staged` で適用。

```bash
for entry in cp-11:<旧IP> cp-12:<旧IP> cp-13:<旧IP> wn-01:<旧IP> wn-02:<旧IP> wn-03:<旧IP>; do
  name="${entry%%:*}"; ip="${entry##*:}"
  talosctl apply-config --mode=staged \
    -f clusterconfig/home-cluster-${name}.cluster.internal.yaml \
    -n "$ip" -e "$ip"
done
```

#### 3. ネットワーク切り替え + 電源サイクル

1. スイッチのポート VLAN を変更
2. 全ノードの電源を抜き差し（N100 ミニ PC に IPMI はない）

#### 4. etcd 復旧

ノードが新 IP で起動するが、etcd のピア URL に旧 IP が残っているためクォーラムが取れない。

**cp-13 を単独 etcd クラスタとして起動（データ保持）:**

```bash
talosctl -n <cp-13新IP> -e <cp-13新IP> patch machineconfig --patch 'cluster:
  etcd:
    extraArgs:
      force-new-cluster: "true"'

talosctl -n <cp-13新IP> -e <cp-13新IP> reboot
# etcd Health OK を確認
talosctl -n <cp-13新IP> -e <cp-13新IP> service etcd
```

**cp-13 から force-new-cluster フラグを除去:**

```bash
talosctl apply-config \
  -f clusterconfig/home-cluster-cp-13.cluster.internal.yaml \
  -n <cp-13新IP> -e <cp-13新IP>
```

**cp-11, cp-12 を 1 台ずつ再参加させる（重要: 必ず 1 台ずつ）:**

```bash
# cp-11
talosctl -n <cp-11新IP> -e <cp-11新IP> reset \
  --graceful=false --reboot --system-labels-to-wipe=EPHEMERAL
# etcd 3/3 Health OK を確認してから次へ

# cp-12
talosctl -n <cp-12新IP> -e <cp-12新IP> reset \
  --graceful=false --reboot --system-labels-to-wipe=EPHEMERAL
```

> **注意**: EPHEMERAL ワイプは kubelet データも消えるが、CP ノードでは問題ない。
> etcd メンバーは必ず 1 台ずつ追加する（2 台同時だとクォーラムが不安定になる）。

#### 5. ローカル設定・マニフェスト更新

```bash
# talosconfig の endpoints/nodes
sed -i 's/<旧IP>/<新IP>/g' ~/.talos/config

# kubeconfig の server (VIP)
sed -i 's/<旧VIP>/<新VIP>/g' ~/.kube/config

# home-cluster の IP 参照箇所を更新して push
# (ip-pool, etcd endpoints, CNP, CoreDNS, Argo WF 等)
```

#### 6. CoreDNS 再起動

ConfigMap 変更だけでは反映されない。

```bash
kubectl rollout restart deployment coredns -n kube-system
```

### 影響を受けるリソース

| リポジトリ | ファイル | 内容 |
|-----------|---------|------|
| home-infra | talconfig.yaml | ノード IP, VIP, gateway, nameservers |
| home-infra | pxe/dnsmasq.conf | PXE サブネット |
| home-cluster | manifests/infra/ip-pool.yaml | Cilium LB IP プール |
| home-cluster | helm-values/kube-prometheus-stack/values.yaml | etcd endpoints |
| home-cluster | manifests/argo/etcd-backup.yaml | talosctl 先 CP IP |
| home-cluster | manifests/argo/node-shutdown-wft.yaml | 全ノード IP マッピング |
| home-cluster | manifests/argo/netpol-workflow-pods.yaml | CNP egress IP |
| home-cluster | manifests/kube-system/coredns-configmap.yaml | split-horizon DNS |
| ローカル | ~/.talos/config | endpoints, nodes |
| ローカル | ~/.kube/config | server (VIP) |

> home-cloudflare は Tunnel ベースのため IP 直参照なし、変更不要。

## NAS IP 変更時の iSCSI 復旧

NAS の IP が変わった場合（VLAN 移行、NAS 買い替え等）、Trident backend の Secret 更新だけでは不十分。旧 IP が 3 箇所に残る。

### 前提

- 1Password の `qnap-backend-secret` の `storageAddress` を新 IP に更新済み
- ESO が Secret を同期済み（`kubectl annotate es qnap-backend-secret -n trident force-sync=$(date +%s) --overwrite`）
- 新 IP で QNAP の iSCSI サービスに到達可能

### 手順

#### 1. Trident controller 再起動

```bash
kubectl rollout restart deployment trident-controller -n trident
```

#### 2. ワーカーノード再起動（ゴースト iSCSI デバイス除去）

旧 IP のデバイスが transport-offline で残り、multipath エラーの原因になる。

```bash
# 確認
for node in 192.168.10.200 192.168.10.201 192.168.10.202; do
  echo "=== $node ==="
  talosctl -n $node read /proc/partitions | grep "^   8" | while read maj min blocks name; do
    state=$(talosctl -n $node read /sys/block/$name/device/state 2>/dev/null)
    echo "  $name: $state"
  done
done

# transport-offline があるノードを再起動
talosctl -n <IP> reboot
```

#### 3. VolumeAttachment の旧 IP をクリア

VolumeAttachment の `attachmentMetadata.p2` に旧 IP が残っている場合、VA を削除して再 publish させる。

```bash
# 旧 IP が残っている VA を特定
kubectl get volumeattachments -o json | python3 -c "
import json,sys
d = json.load(sys.stdin)
for item in d['items']:
    pv = item['spec']['source'].get('persistentVolumeName','')
    ctx = item.get('status',{}).get('attachmentMetadata',{})
    if ctx.get('p2') == '<旧IP>':
        print(item['metadata']['name'], pv)"

# 該当 VA を削除（Pod も再作成が必要）
kubectl delete volumeattachment <name>
```

#### 4. iscsiadm ノードデータベースの旧エントリ削除

各ワーカーの trident-node Pod 経由で旧ポータルエントリを削除。

```bash
for node in wn-01 wn-02 wn-03; do
  TPOD=$(kubectl get pods -n trident -l app=node.csi.trident.qnap.io \
    --field-selector spec.nodeName=$node -o jsonpath='{.items[0].metadata.name}')
  for iqn in $(kubectl exec -n trident $TPOD -c trident-main -- \
    iscsiadm -m node 2>/dev/null | grep "<旧IP>" | awk '{print $2}'); do
    kubectl exec -n trident $TPOD -c trident-main -- \
      iscsiadm -m node -T "$iqn" -p "<旧IP>:3260" --op=delete
  done
done
```

#### 5. Trident トラッキングファイル更新

`/var/lib/trident/tracking/*.json` の `iscsiPortals` に旧 IP が残っている場合、書き換える。

```bash
for node in 192.168.10.200 192.168.10.201 192.168.10.202; do
  for f in $(talosctl -n $node ls /var/lib/trident/tracking/ | grep json | awk '{print $2}'); do
    talosctl -n $node read /var/lib/trident/tracking/$f | grep -q '<旧IP>' && echo "$node: $f"
  done
done

# trident-node Pod 経由で書き換え
kubectl exec -n trident <trident-node-pod> -c trident-main -- \
  busybox sed -i 's/<旧IP>/<新IP>/g' /host/var/lib/trident/tracking/<pvc>.json
```

#### 6. trident-node 再起動 + Pod 再作成

```bash
kubectl rollout restart daemonset trident-node-linux -n trident
# 各 Pod を削除して再マウントさせる
```

#### 7. NFS PV の再作成

NFS PV の `spec.nfs.server` は immutable。PV + PVC を削除して ArgoCD に再作成させる。

```bash
kubectl delete pv <nfs-pv-name>
kubectl patch pv <nfs-pv-name> -p '{"metadata":{"finalizers":null}}'  # stuck の場合
# ArgoCD selfHeal が新 IP で再作成
```

### 影響を受けるリソース

| リソース | 旧 IP の参照箇所 |
|----------|----------------|
| Secret `qnap-backend-secret` | storageAddress (1Password → ESO) |
| VolumeAttachment | attachmentMetadata.p2 |
| Trident tracking JSON | iscsiPortals 配列 |
| iscsiadm node DB | portal エントリ |
| NFS PV | spec.nfs.server (immutable) |
| CNP (各 namespace) | toCIDR の NAS IP |
| home-infra pxe/ | dnsmasq.conf, boot.ipxe |
| home-cloudflare dns.tf | nas.tgy.io A レコード |
