# IPv6

自宅ネットワークの IPv6 構成と運用手順。障害の切り分けは [既知の問題](known-issues.md) を参照。

> **表記**: このリポジトリは公開しているため、実際の委任プレフィックスは書かない。以下では `<PREFIX>` と表記する（例: `<PREFIX>:10::1/64`）。IPv4 の RFC1918 アドレスと違い GUA はグローバルに到達可能で、世帯を特定できる情報になるため。実値は UniFi コントローラか HGW の管理画面で確認する。

## 構成

```
KDDI (auひかり)
  │  IPoE。WAN 側はリンクローカルのみで、グローバルは持たない
  ↓
HGW (NEC Platforms / 172.16.0.1)
  │  RA で <PREFIX>:1::/64 を LAN に適用 ← ここだけは自動で動く
  │  DHCPv6-PD の委任は /64 一本のみ（長さは選べない）
  ↓  静的ルート 6 本: <PREFIX>:{2,3,4,5,10,20}::/64 → <PREFIX>:1::1
UCG Fiber
  │  WAN: DHCPv6 で <PREFIX>:1::1 を取得
  │  LAN: 各 VLAN に <PREFIX>:X::1/64 を static で手打ち + RA (SLAAC)
  ↓
VLAN 2/3/4/5/10/20
```

**IPv6 の第 4 ヘクステットは VLAN ID と同じ番号を使う。** `:1` は HGW の LAN が使用済みなので避ける。

| VLAN | 用途 | IPv6 |
|---|---|---|
| — | HGW LAN（UCG の WAN 側） | `<PREFIX>:1::/64` |
| 2 | WiFi | `<PREFIX>:2::1/64` |
| 3 | Work | `<PREFIX>:3::1/64` |
| 4 | Trusted | `<PREFIX>:4::1/64` |
| 5 | NAS | `<PREFIX>:5::1/64` |
| 10 | Cluster | `<PREFIX>:10::1/64` |
| 20 | Cilium LB | `<PREFIX>:20::1/64` |

## なぜ静的ルートが必要なのか

HGW が下位ルータへ委任するプレフィックスは **/64 が 1 本だけ**で、DHCPv6サーバ設定の画面に長さを指定する項目が存在しない（選べるのは「RA を配るか」「DHCPv6 を配るか」の組み合わせ 3 通りのみ）。UCG 側は `/48` を要求しているが降りてこない。

したがって複数 VLAN に IPv6 を配るには、

1. KDDI が回線に向けて経路広告しているブロックから /64 を手で切り出し、UCG の各 VLAN に static で割り当てる
2. **HGW に「その /64 は UCG へ投げろ」という静的ルートを入れる**（これが無いと戻りパケットが UCG に届かない）

という構成しか取れない。UCG は 6in4 トンネルに非対応なので、HE.net 等から固定 /48 を貰って迂回する手も使えない。

## UniFi 側の設定

各ネットワークで以下を設定する。

- IPv6 インターフェイスタイプ: **静的**
- IPv6 アドレス: `<PREFIX>:X::1/64`（X = VLAN ID）
- クライアントアドレス割り当て: SLAAC
- RA: 有効、優先度: 高
- 自動 DNS サーバ: 有効

**terrifi (OpenTofu provider) は IPv6 属性を持たない。** v0.9.3 時点で `terrifi_network` のスキーマに `ipv6_*` が 1 つも無いため、`home-unifi` の管理外になる。UI か UniFi API で設定する。terrifi が触らないフィールドなので `tofu plan` と競合しない。

API で操作する場合:

```sh
# 現在の設定を確認
curl -sk -H "X-API-KEY: $KEY" \
  "$URL/proxy/network/api/s/default/rest/networkconf" \
  | jq -r '.data[] | select(.purpose=="corporate")
           | "\(.name)\t\(.ipv6_interface_type)\t\(.ipv6_subnet // "-")\tra=\(.ipv6_ra_enabled)"'

# 現在の委任プレフィックス（UCG の WAN グローバルアドレス）を確認
curl -sk -H "X-API-KEY: $KEY" \
  "$URL/proxy/network/api/s/default/stat/device" \
  | jq -r '.data[] | select(.type=="udm") | .wan1.ipv6[]'
```

更新は `PUT /rest/networkconf/<id>` にオブジェクト全体を送る（GET してから該当フィールドだけ差し替える read-modify-write）。認証情報は 1Password の `unifi-tofu-credentials`。

## プレフィックスが変わったときの手順

KDDI からの委任プレフィックスは固定ではなく、回線の再接続や HGW の交換で変わることがある（過去に 1 回変わった実績あり）。変わると **HGW と UniFi の両方**を直す必要がある。

1. 新しいプレフィックスを確認する（上記の `stat/device` → `wan1.ipv6`、または HGW の LAN 側状態）
2. UniFi の 6 ネットワークの `ipv6_subnet` を新プレフィックスに更新する
3. **HGW の静的ルート 6 本を、宛先とゲートウェイの両方とも更新する**（ゲートウェイ `<PREFIX>:1::1` も変わる）
4. ノードとクライアントの SLAAC アドレスは RA で自動更新される。古いアドレスは valid lifetime（最大 24h）まで残る
5. `Ipv6EgressDown` が消えることを確認する

`:1` を HGW、`:2` 以降を VLAN に割り当てる規則を維持すれば、手順 2 は第 4 ヘクステットを流用するだけで機械的に決まる。

### HGW 側のルート追加手順（新規 VLAN を作るとき）

1. 172.16.0.1 → 詳細設定 → IPv6ルーティング設定
2. 宛先: `<PREFIX>:X::/64` / ゲートウェイ: `<PREFIX>:1::1` / インタフェース: LAN
3. **保存を忘れない**

## 監視

`blackbox-exporter` の `Probe/ipv6-egress` が、ノードの VLAN 10 GUA を送信元にして外向き HTTPS 疎通を 60 秒間隔で確認している（`Ipv6EgressDown` / `Ipv6ProbeMissing`）。

**設計上の注意**:

- **`ip_protocol_fallback: false` を外してはいけない。** 外すと v6 が死んでいても v4 にフォールバックして成功扱いになる
- **プローブは hostNetwork で動かす。** Pod ネットワークは IPv4 only なので、ノードの GUA を送信元にしないと壊れる経路を検査できない
- **UCG 自身からの疎通確認では検知できない。** UCG の WAN は `<PREFIX>:1::/64` に居て、この /64 は RA 由来で独立に動くため、VLAN 側が全滅していても正常に見える

## 制約と将来の選択肢

| 項目 | 現状 |
|---|---|
| 委任プレフィックス長 | /64 のみ。HGW 側に設定項目が無い |
| 複数 VLAN への配布 | HGW の静的ルートに依存。HGW のバグを踏む余地が残る |
| プレフィックスの固定 | 不可。KDDI 任せ |
| ND Proxy / NAT66 | UCG が非対応 |
| 6in4 トンネル（HE.net の固定 /48） | UCG が非対応。別途 Linux ルータを立てれば可能だが未検討 |
| クラスタの dual-stack | 未対応（Pod は IPv4 only）。ノードは VLAN 10 の GUA を持つ |
