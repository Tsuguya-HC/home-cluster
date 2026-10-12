#!/usr/bin/env python3
"""ConfigMap に入ったスクリプトの構文検査。

YAML の中の文字列は、クラスタに適用されて実行されるまで誰も構文を見ない。
horenso-verify は埋め込みのままヒアドキュメントの引用符を間違え、
存在しないインタプリタを呼び、それぞれ実 Pod が落ちて初めて分かった。

キー名の拡張子でインタプリタを選び、構文検査だけをかける（実行はしない）。

コンテナの `command: [sh, -c]` + `args:` や Argo の `script.source` に直書きされた
シェルも同じ理由で検査する（#959）。こちらは導入時点の既存指摘を
INLINE_ALLOWLIST に載せ、そこに無い指摘だけを落とす。
"""
import collections
import json
import os
import re
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

INLINE_ALLOWLIST = Path(__file__).resolve().parent / "inline-scripts-allow.txt"

# command[0] のベース名 -> CHECKERS のキー
SHELLS = {"sh": ".sh", "ash": ".sh", "dash": ".sh", "bash": ".bash"}

# Argo はシェルに渡す前に `{{...}}` を文字列として置き換える。そのまま渡すと
# shellcheck が `{` をブレース展開の書き損じとして指摘する（SC1083）。改行を
# 跨がせないのは、指摘の行番号を元の本文の行に対応させるため。
ARGO_EXPR = re.compile(r"\{\{[^{}\n]*\}\}")


def _dash_c(argv: list[str]) -> str | None:
    """`sh [opts] -c SCRIPT` の SCRIPT。-c が無ければ None（ファイルを実行する形）。"""
    i = 0
    while i < len(argv):
        a = argv[i]
        if a in ("-o", "+o"):
            i += 2
            continue
        if not a.startswith("-"):
            return None
        if "c" in a[1:]:
            return argv[i + 1] if i + 1 < len(argv) else None
        i += 1
    return None


def _inline_scripts(node, where: str):
    """node 以下のコンテナ / Argo script から (場所, CHECKERS のキー, 本文) を拾う。"""
    if isinstance(node, list):
        for v in node:
            yield from _inline_scripts(v, where)
        return
    if not isinstance(node, dict):
        return
    cmd = node.get("command")
    if isinstance(cmd, list) and cmd and isinstance(cmd[0], str):
        ext = SHELLS.get(os.path.basename(cmd[0]))
        here = f"{where}/{node.get('name', '?')}"
        if ext and isinstance(node.get("source"), str):
            yield here, ext, node["source"]
        elif ext:
            argv = [str(a) for a in cmd[1:]] + [str(a) for a in node.get("args") or []]
            body = _dash_c(argv)
            if body is not None:
                yield here, ext, body
    for v in node.values():
        yield from _inline_scripts(v, where)


def _documents(path: Path, docs: list):
    """path の各ドキュメントと、Kustomization の inline patch の中身。"""
    for doc in docs:
        if not isinstance(doc, dict):
            continue
        yield doc
        if doc.get("kind") != "Kustomization":
            continue
        for p in doc.get("patches") or []:
            if not isinstance(p, dict) or not isinstance(p.get("patch"), str):
                continue
            try:
                inner = list(yaml.safe_load_all(p["patch"]))
            except yaml.YAMLError:
                # 読めない patch は kustomize build が落とす。ここで重ねて赤にしない
                continue
            yield from (d for d in inner if isinstance(d, (dict, list)))


def _shellcheck_findings(ext: str, body: str) -> list[tuple[int, str, str, str]]:
    """[(code, level, message, 指摘行の本文)]。shellcheck 自体が動かなければ例外。"""
    cmd = [*CHECKERS[ext][:1], "-f", "json1", *CHECKERS[ext][1:], "-"]
    r = subprocess.run(
        cmd,
        input=ARGO_EXPR.sub("ARGO_EXPR", body),
        capture_output=True,
        text=True,
        check=False,
    )
    # 0 = 指摘なし、1 = 指摘あり。それ以外は検査そのものが走っていない
    if r.returncode not in (0, 1):
        raise RuntimeError(r.stderr.strip() or f"shellcheck exited {r.returncode}")
    # 閉じ忘れの指摘は本文の最終行の次を指すことがある
    lines = [*body.splitlines(), ""]
    return [
        (c["code"], c["level"], c["message"], lines[min(c["line"], len(lines)) - 1].strip())
        for c in json.loads(r.stdout)["comments"]
    ]


def _load_inline_allowlist() -> collections.Counter:
    allowed = collections.Counter()
    if not INLINE_ALLOWLIST.exists():
        return allowed
    for line in INLINE_ALLOWLIST.read_text().splitlines():
        # 本文に `#` を含む行があるので、行頭の `#` だけをコメントとして扱う
        line = line.strip()
        if line and not line.startswith("#"):
            allowed[line] += 1
    return allowed


def _check_script(key: str, body: str) -> str | None:
    """key の拡張子でチェッカーを選び body を検査する。

    チェッカーが無ければ None（対象外）。通れば ""。落ちればエラー文字列。
    """
    cmd = CHECKERS.get(Path(key).suffix)
    if cmd is None:
        return None
    if shutil.which(cmd[0]) is None:
        # 見つからないものを黙って飛ばすと、検査したつもりの緑になる
        return f"{cmd[0]} が無い"
    with tempfile.TemporaryDirectory() as d:
        f = Path(d) / Path(key).name
        f.write_text(body)
        r = subprocess.run([*cmd, str(f)], capture_output=True, text=True)
    if r.returncode != 0:
        # 一時ディレクトリ名は読み手の役に立たないので落とす
        return (r.stderr or r.stdout).replace(str(f), key).strip()
    return ""


def main() -> int:
    checked = 0
    failed = []
    inline = []
    for root in ROOTS:
        for path in sorted(Path(root).rglob("*.y*ml")):
            try:
                docs = list(yaml.safe_load_all(path.read_text()))
            except yaml.YAMLError as e:
                print(f"::error file={path}::YAML として読めません: {e}")
                failed.append(str(path))
                continue
            for doc in _documents(path, docs):
                meta = doc.get("metadata") if isinstance(doc, dict) else None
                name = meta.get("name", "?") if isinstance(meta, dict) else "?"
                kind = doc.get("kind", "?") if isinstance(doc, dict) else "patch"
                inline += [(path, *s) for s in _inline_scripts(doc, f"{kind}/{name}")]
            for doc in docs:
                if not isinstance(doc, dict) or doc.get("kind") != "ConfigMap":
                    continue
                for key, body in (doc.get("data") or {}).items():
                    if not isinstance(body, str):
                        continue
                    result = _check_script(key, body)
                    if result is None:
                        continue
                    checked += 1
                    if result:
                        print(f"::error file={path}::{key}: {result}")
                        failed.append(f"{path}:{key}")
                    else:
                        print(f"ok  {path}  {key}")

    # kustomization.yaml の configMapGenerator[].files は ConfigMap の data を
    # 直に書かず、ディスク上のファイルを参照する。上のループは YAML に埋め込まれた
    # 文字列しか見ないので、ここを辿らないと fetch-pr.sh や plan.py のようなファイルは
    # 検査対象から漏れたまま緑になる。
    for root in ROOTS:
        for kfile in sorted(Path(root).rglob("kustomization.yaml")):
            try:
                kdoc = yaml.safe_load(kfile.read_text())
            except yaml.YAMLError as e:
                print(f"::error file={kfile}::YAML として読めません: {e}")
                failed.append(str(kfile))
                continue
            if not isinstance(kdoc, dict):
                continue
            for gen in kdoc.get("configMapGenerator") or []:
                if not isinstance(gen, dict):
                    continue
                for entry in gen.get("files") or []:
                    if not isinstance(entry, str):
                        continue
                    # `key=path` 形式にも対応（無ければ key はファイル名）。
                    key, sep, rel = entry.partition("=")
                    if not sep:
                        rel, key = key, Path(key).name
                    src = kfile.parent / rel
                    if not src.is_file():
                        print(
                            f"::error file={kfile}::configMapGenerator files: "
                            f"{entry} が指すファイルが無い"
                        )
                        failed.append(f"{kfile}:{entry}")
                        continue
                    result = _check_script(key, src.read_text())
                    if result is None:
                        continue
                    checked += 1
                    if result:
                        print(f"::error file={src}::{key}: {result}")
                        failed.append(f"{src}:{key}")
                    else:
                        print(f"ok  {src}  {key}")

    # 許可リストは指摘ごとに `<file>::SC<code>::<指摘行の本文>` で照合する。行番号を
    # 使わないのは、上に行を足しただけで既存の指摘が全部「新しい指摘」になるから。
    # 同じ本文の行が複数あれば件数で数えるので、許可済みの行をコピーしても落ちる。
    found = collections.Counter()
    detail = collections.defaultdict(list)
    if shutil.which("shellcheck") is None:
        print("::error::shellcheck が無い")
        failed.append("shellcheck")
    else:
        for path, where, ext, body in inline:
            try:
                findings = _shellcheck_findings(ext, body)
            except RuntimeError as e:
                print(f"::error file={path}::{where}: {e}")
                failed.append(f"{path}:{where}")
                continue
            for code, level, message, text in findings:
                entry = f"{path}::SC{code}::{text}"
                found[entry] += 1
                detail[entry].append(f"{where}: SC{code} ({level}): {message}")
            if not findings:
                print(f"ok  {path}  {where}")
    allowed = _load_inline_allowlist()
    new = found - allowed
    stale = allowed - found
    for entry in sorted(new):
        path = entry.split("::", 1)[0]
        for d in detail[entry]:
            print(f"::error file={path}::{d}")
        print(f"    {entry}")
        failed.append(entry)
    for entry in sorted(stale):
        # 直った指摘の行を残すと、同じ行に戻ってきた指摘を黙って通す
        print(
            f"::error file={os.path.relpath(INLINE_ALLOWLIST)}::"
            f"もう再現しない（{stale[entry]} 件）。この行を消す: {entry}"
        )
        failed.append(entry)
    if new:
        print(
            "\n直すか、意図して残すなら理由を書いて "
            f"{os.path.relpath(INLINE_ALLOWLIST)} に上の `    ` で始まる行を足す。"
        )

    if failed:
        print(f"\n{len(failed)} 件が構文検査に落ちた。")
        return 1
    # 0 件は「全部通った」ではなく「何も見ていない」。検査対象が消えたことに
    # 気づけないので、黙って緑にしない
    print(
        f"\n{checked} 件を検査した。インラインのシェル {len(inline)} 本"
        f"（許可リスト済みの指摘 {sum(found.values())} 件）。"
    )
    if checked == 0 or not inline:
        print("::error::検査対象が 1 件も見つからない。抽出条件が壊れていないか。")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
