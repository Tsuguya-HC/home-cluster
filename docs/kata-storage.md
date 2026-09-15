# Kata のストレージ経路

RuntimeClass `kata` の Pod で「どこに書くか」は速度がひと桁変わる。実測（2026-09-14、wn-03 /
kata-containers 3.32.0 / Cloud Hypervisor / ubuntu:24.04、5000 個の小ファイルを cp → 全部 read →
rm）と、その帰結として使う型をここに置く。

## 経路別の実測

| 置き場 | Kata copy5000 / rm | runc copy5000 / rm |
|---|---|---|
| rootfs | 0.93s / 0.40s | 0.38s / 0.18s |
| emptyDir | 0.98s / 0.40s | 0.32s / 0.17s |
| emptyDir `medium: Memory` | 0.84s / 0.40s | 0.37s / 0.16s |
| qnap-nfs PVC | **4.70s / 3.57s** | 3.11s / 1.18s |
| qnap-iscsi PVC (Filesystem) | 0.90s / 0.45s | — |
| **`volumeMode: Block`** | **0.14s / 0.06s** | 0.38s / 0.13s |

読み取れること:

- **Kata の `emptyDir` は tmpfs ではなく virtiofs**（ゲストの `/proc/mounts` が `none /ed virtiofs`）。
  ホストと共有されないだけで、実体は virtiofs 越しのホストディレクトリ。`medium: Memory` への
  差し替えはゲストメモリを払う割に素の小ファイル I/O ではほとんど速くならない
- Kata が runc に対して負けている分は、ほぼ全部 virtiofs 層（rootfs で 2.4 倍）
- **一番遅いのは NFS**。virtiofs のペナルティより NFS のペナルティの方が大きい
- `volumeMode: Block` だけが virtiofs を通らず、runc より速い

## 重い I/O をする handler の型

`volumeMode: Block` の PVC は Kata がゲストに virtio-blk で挿す（ゲストから `/dev/vdb` に見える）。
ファイルシステムはゲストの中にあるので、

- virtiofs を一切通らない（速い）
- ゲストメモリを食わない（tmpfs と違う）
- **QNAP が転けてもホスト kernel の XFS は巻き込まれない** — 2026-05-23 の iSCSI 障害
  （ホスト XFS が log shutdown し、Talos では drain → reboot 以外に復旧手段が無くなった）の
  壊れ方をしない。Kata の VM 境界が iSCSI の一番危ない壊れ方を閉じ込める

代わりに **ゲスト内で mkfs と mount が要る**。ここは `privileged: true` でよい。

**ゲスト内で権限を絞っても得るものは無い。** Kata のゲスト特権はホストに及ばず
（containerd 側が `privileged_without_host_devices = true`）、守っているのは VM 境界であって
capability ではない。そして PSA から見れば `privileged` も `SYS_ADMIN` 単体も同じく baseline 超えなので、
絞っても置ける namespace は変わらない。実際 `SYS_ADMIN` だけに絞ると `chown` が
EPERM（CAP_CHOWN 無し）→ `setpriv` が EPERM（CAP_SETUID/SETGID 無し）と 2 回転ぶだけで、
admission 上の得は何も無い。

```yaml
spec:
  runtimeClassName: kata
  containers:
    - name: agent
      securityContext:
        privileged: true          # VM の中の話。ホストには及ばない
        runAsUser: 0              # mount のため。作業本体は下で 65533 に降りる
      volumeDevices:
        - name: scratch
          devicePath: /dev/scratch
      command: [bash, -c]
      args:
        - |
          set -eu
          # root_owner で FS 作成時に所有者を焼く（あとで chown しなくて済む）
          mkfs.ext4 -q -F -E lazy_itable_init=0,lazy_journal_init=0,root_owner=65533:65533 /dev/scratch
          mkdir -p /scratch
          mount -o noatime /dev/scratch /scratch
          # 作業本体を 65533 で回すのは taskflow の配線の要件（workspace 直下が 0555、ADR-0005）で、
          # ホストを守るためではない。ホストを守っているのは VM 境界
          exec setpriv --reuid 65533 --regid 65533 --clear-groups \
                       --inh-caps=-all --no-new-privs -- bash /path/to/real-work.sh
  volumes:
    - name: scratch
      ephemeral:                  # Pod と同じ寿命。消えるときに PVC ごと消える
        volumeClaimTemplate:
          spec:
            accessModes: [ReadWriteOnce]
            storageClassName: qnap-iscsi
            volumeMode: Block
            resources: {requests: {storage: 10Gi}}
```

同じ Pod の中で `/scratch`（virtio-blk）と `/tmp`（rootfs = virtiofs）を比べた実測:

```
/scratch  copy5000= 0.57s  read= 0.03s  rm= 0.05s
/tmp      copy5000= 1.16s  read= 0.80s  rm= 0.39s
```

（`copy5000` はコピー元が virtiofs 上にあるので読み側が律速している。書き込みだけを見ている
`rm` と `read` の差 — 8 倍と 26 倍 — の方が virtio-blk の実力に近い。）

`mkfs` のコストは 10GiB で 0.86 秒。起動のたびに払う固定費として見込んでおく。

## 制約

- **フェーズ間の引き渡しには使えない。** ファイルシステムがゲスト内にあるので、ホストからも、
  同じ Pod の他コンテナ（publish サイドカー）からも読めない。taskflow の `flow-workspace` は
  従来どおり PVC (Filesystem) のまま。**重い作業は Block、渡すものは workspace** と分ける
- `claude-code` namespace は PSA `baseline` なので、この Pod は admission で落ちる（baseline が許す
  capability の追加は `NET_BIND_SERVICE` だけ）。実証は `image-build`（PSA `privileged`）で行った。
  handler を置くなら namespace を分ける — taskflow のコントローラは `taskflow-system` にいて
  ClusterRole + ClusterRoleBinding なので、別 namespace の TaskHandler / TaskFlow / Task も扱える。
  `claude-code` の enforce を下げると Block を使わない他の handler まで巻き添えになる（`docs/pod-security.md`）。
  この分離は実際に `claude-code-build`（PSA `privileged`）として作ってあり、`implementer` handler
  （`manifests/claude-code-build/taskflow-implement.yaml`）がこの型を使っている
- RWO なので Pod と 1 対 1。`ephemeral` にしておけば Pod の寿命と一致する

## やらないこと

- **`flow-workspace` を qnap-iscsi の Filesystem モードに変える。** 速度は rootfs 並になるが、
  ホスト kernel に XFS を戻すということで、短命 PVC は attach/detach が多いぶん露出はむしろ増える。
  2026-05 に全 PVC を NFS へ逃がした判断を巻き戻すことになる
- **virtiofs のノード側チューニング。** DAX は Cloud Hypervisor にも同梱の rust virtiofsd にも無く
  (`virtio_fs_cache_size = 0`、`configuration-qemu.toml` も同じ)、`--thread-pool-size` を上げても
  実測で 28%、桁は変わらない。ノード config は extension が焼く read-only なので、
  `/etc/cri/conf.d/*.part` を `machine.files` で足して別 ConfigPath に向ける必要があり、
  home-infra の保守項目が増える割に見返りが薄い
