#!/usr/bin/env python3
"""ConfigMap に入ったスクリプトの構文検査。

YAML の中の文字列は、クラスタに適用されて実行されるまで誰も構文を見ない。
horenso-verify は埋め込みのままヒアドキュメントの引用符を間違え、
存在しないインタプリタを呼び、それぞれ実 Pod が落ちて初めて分かった。

キー名の拡張子でインタプリタを選び、構文検査だけをかける（実行はしない）。
"""
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml

# 拡張子 -> 検査コマンド（ファイル名を末尾に足して実行）。
# シェルは `sh -n` ではなく shellcheck をかける。`sh -n` は文法しか見ないので、
# `cd dir` が失敗したまま次に進む種類の穴を通してしまう（実際に通していた）。
# SC3040 (POSIX sh に pipefail は無い) は除外する。これらが動く alpine:3.24 の
# busybox ash は `set -o pipefail` を受け付け、実際に効くことを実測した
# (`false | true` が非ゼロになる)。ここでは移植性の警告が当たらない。
CHECKERS = {
    ".sh": ["shellcheck", "-s", "sh", "-e", "SC3040"],
    ".bash": ["shellcheck", "-s", "bash"],
    ".mjs": ["node", "--check"],
    ".js": ["node", "--check"],
    ".py": ["python3", "-m", "py_compile"],
}

ROOTS = ["manifests", "kustomize"]


def main() -> int:
    checked = 0
    failed = []
    for root in ROOTS:
        for path in sorted(Path(root).rglob("*.y*ml")):
            try:
                docs = list(yaml.safe_load_all(path.read_text()))
            except yaml.YAMLError as e:
                print(f"::error file={path}::YAML として読めません: {e}")
                failed.append(str(path))
                continue
            for doc in docs:
                if not isinstance(doc, dict) or doc.get("kind") != "ConfigMap":
                    continue
                for key, body in (doc.get("data") or {}).items():
                    cmd = CHECKERS.get(Path(key).suffix)
                    if cmd is None or not isinstance(body, str):
                        continue
                    checked += 1
                    if shutil.which(cmd[0]) is None:
                        # 見つからないものを黙って飛ばすと、検査したつもりの
                        # 緑になる
                        print(f"::error file={path}::{key}: {cmd[0]} が無い")
                        failed.append(f"{path}:{key}")
                        continue
                    with tempfile.TemporaryDirectory() as d:
                        f = Path(d) / Path(key).name
                        f.write_text(body)
                        r = subprocess.run(
                            [*cmd, str(f)], capture_output=True, text=True
                        )
                    if r.returncode != 0:
                        # 一時ディレクトリ名は読み手の役に立たないので落とす
                        detail = (r.stderr or r.stdout).replace(str(f), key).strip()
                        print(f"::error file={path}::{key}: {detail}")
                        failed.append(f"{path}:{key}")
                    else:
                        print(f"ok  {path}  {key}")

    if failed:
        print(f"\n{len(failed)} 件が構文検査に落ちた。")
        return 1
    # 0 件は「全部通った」ではなく「何も見ていない」。検査対象が消えたことに
    # 気づけないので、黙って緑にしない
    print(f"\n{checked} 件を検査した。")
    if checked == 0:
        print("::error::検査対象が 1 件も見つからない。抽出条件が壊れていないか。")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
