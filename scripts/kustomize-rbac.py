#!/usr/bin/env python3
"""kustomize/ の描画結果に出る RBAC の束ね方を、許可リストと突き合わせる。

kustomize の `$patch: delete` は target がどれにもマッチしなくても無言で no-op になる。
チャートやリモート base の更新でリソースの形が変われば、消したはずの
ClusterRoleBinding が描画結果に戻ってきても build は通り、kubeconform も通る（#946）。

だから描画結果そのものを見る。誰に・どの Role を・どこで束ねているか
（ClusterRoleBinding / RoleBinding）と、他の ClusterRole に rules を足し込む
集約（aggregationRule / aggregate-to-* ラベル）を列挙し、許可リストに無いものと、
許可リストにあるのに描画結果に無いものを落とす。rules の中身は見ない。
"""

import os
import subprocess
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
ALLOWLIST = ROOT / "scripts" / "kustomize-rbac-allow.txt"
AGGREGATE = "rbac.authorization.k8s.io/aggregate-to-"


def render(kdir: Path) -> list:
    r = subprocess.run(
        ["kubectl", "kustomize", "--enable-helm", str(kdir)],
        capture_output=True,
        text=True,
        check=False,
    )
    if r.returncode != 0:
        raise RuntimeError(
            f"{kdir.relative_to(ROOT)}: kubectl kustomize failed: {r.stderr.strip()}"
        )
    return [d for d in yaml.safe_load_all(r.stdout) if isinstance(d, dict)]


def entries(rel: str, docs: list):
    for d in docs:
        kind = d.get("kind")
        meta = d.get("metadata") or {}
        name = meta.get("name", "?")
        if kind in ("ClusterRoleBinding", "RoleBinding"):
            where = (
                f"{meta.get('namespace', '?')}/{name}"
                if kind == "RoleBinding"
                else name
            )
            ref = d.get("roleRef") or {}
            subjects = ",".join(
                sorted(
                    f"{s.get('kind')}:{s.get('namespace', '')}/{s.get('name')}"
                    for s in d.get("subjects") or []
                )
            )
            yield f"{rel}::{kind}::{where}::{ref.get('kind')}/{ref.get('name')}::{subjects}"
        elif kind == "ClusterRole":
            labels = sorted(
                k for k in (meta.get("labels") or {}) if k.startswith(AGGREGATE)
            )
            if labels:
                yield f"{rel}::ClusterRole::{name}::{','.join(labels)}"
            if d.get("aggregationRule"):
                yield f"{rel}::ClusterRole::{name}::aggregationRule"


def load_allowlist() -> set:
    if not ALLOWLIST.exists():
        return set()
    return {
        line.strip()
        for line in ALLOWLIST.read_text().splitlines()
        if line.strip() and not line.strip().startswith("#")
    }


def main() -> int:
    # 深さ 1 だけ。入れ子の kustomization.yaml は親が取り込む部品で、単体では適用されない
    dirs = sorted(p.parent for p in (ROOT / "kustomize").glob("*/kustomization.yaml"))
    if not dirs:
        print(
            "::error::kustomize/ の直下に kustomization.yaml が無い。探し方が壊れている"
        )
        return 1

    found = set()
    failed = False
    for kdir in dirs:
        rel = str(kdir.relative_to(ROOT))
        try:
            docs = render(kdir)
        except RuntimeError as e:
            print(f"::error::{e}")
            failed = True
            continue
        mine = set(entries(rel, docs))
        print(
            f">>> {rel}: {len(docs)} resources, {len(mine)} RBAC bindings / aggregations"
        )
        found |= mine

    allowed = load_allowlist()
    allow_rel = os.path.relpath(ALLOWLIST, ROOT)
    for entry in sorted(found - allowed):
        print(
            f"::error file={entry.split('::', 1)[0]}/kustomization.yaml::許可リストに無い RBAC: {entry}"
        )
        failed = True
    for entry in sorted(allowed - found):
        # 消えた束ね方の行を残すと、同じ名前で戻ってきたときに黙って通す
        print(f"::error file={allow_rel}::描画結果に無い。この行を消す: {entry}")
        failed = True
    if found - allowed:
        print(
            "\n意図した変更なら、誰に何をどこで与えるのかを書いて "
            f"{allow_rel} に足す。意図していないなら patch が効いていない。"
        )
    if not found and not failed:
        # 0 件は「問題なし」ではなく「何も見ていない」
        print("::error::RBAC を 1 件も拾えていない。描画か抽出が壊れている")
        return 1
    if not failed:
        print(
            f"\n{len(dirs)} 個の kustomization、{len(found)} 件はすべて許可リストどおり。"
        )
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
