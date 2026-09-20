#!/usr/bin/env python3
"""Repair a PEM stored in a 1Password field whose newlines were lost.

Pasting a private key into the 1Password UI on Windows collapses its newlines
into spaces. The field still holds every character of the key, and the UI shows
something that looks right, but PEM is line-structured: openssl cannot read it,
and anything consuming it through External Secrets fails at the point of use
rather than at the point of entry. A GitHub App key mangled this way surfaces
as "Could not find private key" inside a workflow, which does not point back
here at all.

The damage is reversible without the original file. Base64 contains no spaces,
so the spaces are exactly where the newlines were; splitting on whitespace and
rejoining the armor words restores the key byte for byte. This verifies with
openssl before writing anything back.

Nothing here prints the key. Detection reports only lengths and whether openssl
accepts it, which is enough to tell the two states apart -- a value op returns
wrapped in double quotes still has its newlines, an unwrapped one does not.

Usage:
    scripts/fix-pem-field.py --check ITEM [ITEM...]
    scripts/fix-pem-field.py ITEM [ITEM...]
    scripts/fix-pem-field.py --from-file key.pem ITEM

`--from-file` skips the repair and loads a freshly downloaded .pem straight
into the field, which is the way to avoid the whole problem when adding a key.
"""

import argparse
import os
import subprocess
import sys
import tempfile

DEFAULT_VAULT = "home-cluster"
DEFAULT_FIELD = "private-key"


def op_read(item: str, vault: str, field: str) -> str:
    out = subprocess.run(
        ["op", "item", "get", item, "--vault", vault, "--fields", field, "--reveal"],
        capture_output=True, text=True,
    )
    if out.returncode != 0:
        raise SystemExit(f"{item}: cannot read field {field!r} ({out.stderr.strip()})")
    return out.stdout


def unquote(value: str) -> str:
    # op wraps a value in double quotes only when it spans several lines, so the
    # quotes double as the signal that the newlines survived.
    v = value.rstrip("\n")
    if len(v) >= 2 and v[0] == '"' and v[-1] == '"':
        return v[1:-1]
    return v


def nlines(text: str) -> int:
    return len(text.rstrip("\n").split("\n"))

def pem_ok(text: str) -> bool:
    with tempfile.NamedTemporaryFile("w", delete=False) as fh:
        os.chmod(fh.name, 0o600)
        fh.write(text if text.endswith("\n") else text + "\n")
        path = fh.name
    try:
        return subprocess.run(
            ["openssl", "pkey", "-in", path, "-noout"],
            capture_output=True,
        ).returncode == 0
    finally:
        shred(path)


def shred(path: str) -> None:
    if subprocess.run(["shred", "-u", path], capture_output=True).returncode != 0:
        try:
            os.unlink(path)
        except FileNotFoundError:
            pass


def rebuild(flat: str) -> str:
    """Put the newlines back. Armor words rejoin; every other token is a line."""
    tokens = flat.split()
    lines, i = [], 0
    while i < len(tokens):
        if tokens[i].startswith("-----"):
            armor = [tokens[i]]
            i += 1
            while i < len(tokens) and not armor[-1].endswith("-----"):
                armor.append(tokens[i])
                i += 1
            lines.append(" ".join(armor))
        else:
            lines.append(tokens[i])
            i += 1
    return "\n".join(lines) + "\n"


def op_write(item: str, vault: str, field: str, text: str) -> None:
    # The assignment carries the key, so it must not reach a shell: no shell=True,
    # and the caller never builds this string itself.
    out = subprocess.run(
        ["op", "item", "edit", item, "--vault", vault, f"{field}[password]={text}"],
        capture_output=True, text=True,
    )
    if out.returncode != 0:
        raise SystemExit(f"{item}: write failed ({out.stderr.strip()})")


def handle(item: str, vault: str, field: str, check_only: bool) -> bool:
    raw = op_read(item, vault, field)
    value = unquote(raw)

    if pem_ok(value):
        print(f"{item}: intact ({nlines(value)} lines)")
        return True

    if value.count("\n") > 1:
        print(f"{item}: unreadable but already multi-line — not a lost-newline case, leaving alone", file=sys.stderr)
        return False

    fixed = rebuild(value)
    if not pem_ok(fixed):
        print(f"{item}: could not be rebuilt — leaving alone", file=sys.stderr)
        return False

    if check_only:
        print(f"{item}: newlines lost, repairable ({nlines(fixed)} lines) — rerun without --check")
        return False

    op_write(item, vault, field, fixed)
    if not pem_ok(unquote(op_read(item, vault, field))):
        raise SystemExit(f"{item}: wrote it back but it still does not read")
    print(f"{item}: repaired ({nlines(fixed)} lines)")
    return True


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("items", nargs="+", metavar="ITEM")
    ap.add_argument("--vault", default=DEFAULT_VAULT)
    ap.add_argument("--field", default=DEFAULT_FIELD)
    ap.add_argument("--check", action="store_true", help="report without writing")
    ap.add_argument("--from-file", metavar="PEM", help="load this file into the field instead of repairing")
    args = ap.parse_args()

    if args.from_file:
        if len(args.items) != 1:
            raise SystemExit("--from-file takes exactly one item")
        text = open(args.from_file).read()
        if not pem_ok(text):
            raise SystemExit(f"{args.from_file}: openssl will not read this")
        op_write(args.items[0], args.vault, args.field, text)
        if not pem_ok(unquote(op_read(args.items[0], args.vault, args.field))):
            raise SystemExit(f"{args.items[0]}: wrote it but it still does not read")
        print(f"{args.items[0]}: loaded from {args.from_file} ({nlines(text)} lines)")
        return 0

    # Not all(): a generator short-circuits on the first failure and would leave
    # the remaining items unexamined while still reporting a verdict.
    results = [handle(i, args.vault, args.field, args.check) for i in args.items]
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
