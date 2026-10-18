#!/usr/bin/env python3
"""filer.s3.createBuckets と、その写しの s3.annotations の一致を検査する（#1411）。

バケットを作るのは chart の bucket hook（ArgoCD の PostSync）だけで、hook は sync が
走ったときにしか動かない。自動 sync は hook 以外に差分があるときしか走らず、
createBuckets を変えても描画が変わるのは hook の Job だけなので、push しても hook は
走らない。そこで一覧の写しを seaweedfs-s3 Service の annotation に置き、一覧が
変わったら Service も変わるようにしている。Service の metadata なので Pod は再起動しない。

Helm の values は自分の checksum を作れないので、写しは手で揃えるしかない。
揃っていなければここで落とす。写しは 1 行 1 バケットの JSON。
"""
import json
import os
import sys

import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VALUES = os.path.join(ROOT, "helm-values", "seaweedfs", "values.yaml")
KEY = "tgy.io/create-buckets"


def expected_text(buckets: list) -> str:
    return "".join(json.dumps(b, ensure_ascii=False) + "\n" for b in buckets)


def check(values: dict) -> list[str]:
    buckets = ((values.get("filer") or {}).get("s3") or {}).get("createBuckets")
    if not isinstance(buckets, list) or not buckets:
        return ["filer.s3.createBuckets is missing or empty"]
    if not all(isinstance(b, dict) for b in buckets):
        return ["filer.s3.createBuckets must be a list of maps"]

    copy = ((values.get("s3") or {}).get("annotations") or {}).get(KEY)
    if not isinstance(copy, str):
        return [f"s3.annotations[{KEY!r}] is missing"]

    lines = [ln for ln in copy.splitlines() if ln.strip()]
    try:
        parsed = [json.loads(ln) for ln in lines]
    except json.JSONDecodeError as e:
        return [f"s3.annotations[{KEY!r}] has a line that is not JSON: {e}"]

    if parsed != buckets:
        return [f"s3.annotations[{KEY!r}] does not match filer.s3.createBuckets"]
    return []


def main() -> int:
    path = sys.argv[1] if len(sys.argv) > 1 else VALUES
    with open(path) as f:
        values = yaml.safe_load(f) or {}

    errors = check(values)
    if not errors:
        print(f"{os.path.relpath(path, ROOT)}: s3.annotations[{KEY!r}] matches filer.s3.createBuckets")
        return 0

    for e in errors:
        print(f"::error file={os.path.relpath(path, ROOT)}::{e}")
    buckets = ((values.get("filer") or {}).get("s3") or {}).get("createBuckets")
    if isinstance(buckets, list) and buckets and all(isinstance(b, dict) for b in buckets):
        print(
            "\nWithout this copy, changing createBuckets changes only the hook Job, "
            "ArgoCD sees no diff, and the bucket hook never runs (#1411).\n"
            f"Set s3.annotations[{KEY!r}] to:\n"
        )
        print(f"    {KEY}: |")
        for ln in expected_text(buckets).splitlines():
            print(f"      {ln}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
