#!/usr/bin/env python3
"""Find keys in helm-values/ that the chart's templates never read.

A misplaced key is invisible to Helm: `scanJobsConcurrentLimit` at the top
level instead of under `operator:` renders exactly like it was never written,
and the operator runs on the chart default. values.schema.json does not help —
only 7 of our charts ship one, and only cert-manager sets
additionalProperties: false, which is what would catch a wrong nesting level.

So decide by rendering. For every leaf in a values file, change the value and
render again: if the output is byte-identical, no template reads that key.
Note that this asks a different question than deleting the key would — a value
that merely repeats the chart default renders identically when deleted, but
differently when changed, and is correctly reported as live.

Changing the value is not enough on its own. A template that switches on a
specific string — `if eq .Values.database.type "internal"` — renders the same
for "external" and for a perturbed "externalzzprobe", both being "not internal",
which would report a live key as unread. So a key is only reported when it
survives both probes: perturbing it changes nothing, AND putting the chart's own
default back (deleting the key, if the chart has no default there) changes
nothing either. Either probe moving the output proves the key is read.

Ambiguity always resolves to "live" so that this stays quiet unless it is sure:
a leaf that cannot be perturbed (empty map, null, empty list) is skipped, and a
probe that makes the chart fail to render counts as proof the key is read. That
direction matters more than it looks: this check's answer is "nobody reads this",
and what someone does with that answer is delete the key. An unread verdict on a
live key ends with working configuration removed and a note saying it was
unnecessary.

The volatile-line mask is the one place that breaks that rule, because it
compares by line number and never looks at what those lines contain. An effect
landing only inside masked lines is hidden, and hidden reads as unread.

Searching the whole render for the probe value recovers the cases where the
perturbed value is emitted verbatim. It does not recover the ones where the
chart encodes the value first: pointing harbor at `certSource: auto` and
perturbing `expose.tls.auto.commonName` moves 18 lines, all of them masked, and
the probe string appears nowhere in the output because the common name is inside
a base64 certificate. Measured, not assumed.

Nothing distinguishes that from an unread key. Masked lines are regenerated on
every render, so "only masked lines moved" is exactly what an unread key
produces too. Rather than guess, charts that render non-deterministically are
named in a warning: what they can hide is one key whose entire effect is
confined to those lines.
"""

import argparse
import copy
import os
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor

import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ALLOWLIST = os.path.join(ROOT, "scripts", "unread-values-allow.txt")
CACHE = os.path.join(tempfile.gettempdir(), "unread-values-charts")

PROBE = "zzprobe"
WORKERS = min(8, (os.cpu_count() or 2) * 2)
MISSING = object()


def sources():
    apps = os.path.join(ROOT, "apps")
    for name in sorted(os.listdir(apps)):
        if not name.endswith(".yaml"):
            continue
        path = os.path.join(apps, name)
        with open(path) as fh:
            docs = [d for d in yaml.safe_load_all(fh) if d]
        for doc in docs:
            spec = doc.get("spec") or {}
            srcs = spec.get("sources") or ([spec["source"]] if "source" in spec else [])
            for src in srcs:
                if not src.get("chart"):
                    continue
                helm = src.get("helm") or {}
                files = [
                    vf.replace("$values/", "")
                    for vf in helm.get("valueFiles", [])
                    if vf and vf != "null"
                ]
                if not files:
                    continue
                yield {
                    "app": doc["metadata"]["name"],
                    "app_file": os.path.join("apps", name),
                    "chart": src["chart"],
                    "repo": src["repoURL"],
                    "version": str(src.get("targetRevision", "")),
                    "namespace": (spec.get("destination") or {}).get("namespace", "default"),
                    "release": helm.get("releaseName", doc["metadata"]["name"]),
                    "files": files,
                }


def pull(src):
    dest = os.path.join(CACHE, src["app"], src["version"])
    chart_dir = os.path.join(dest, src["chart"])
    if os.path.isdir(chart_dir):
        return chart_dir
    os.makedirs(dest, exist_ok=True)
    if src["repo"].startswith("http"):
        ref, extra = src["chart"], ["--repo", src["repo"]]
    else:
        ref, extra = f"oci://{src['repo']}/{src['chart']}", []
    run = subprocess.run(
        ["helm", "pull", ref, "--version", src["version"], "--untar", "--untardir", dest] + extra,
        capture_output=True,
        text=True,
    )
    if run.returncode:
        raise RuntimeError(f"helm pull {src['chart']}@{src['version']}: {run.stderr.strip()}")
    return chart_dir


def render(chart_dir, src, files):
    cmd = ["helm", "template", src["release"], chart_dir, "--namespace", src["namespace"]]
    for f in files:
        cmd += ["-f", f]
    run = subprocess.run(cmd, capture_output=True, text=True)
    return run.stdout.splitlines() if run.returncode == 0 else None


def volatile(a, b):
    """Line numbers that differ between two renders of identical input.

    Several charts mint a self-signed certificate or a random password at
    template time, so their output is never byte-identical to itself. Those
    lines carry no signal about our values and are excluded from every
    comparison below. A chart whose *line count* moves between two identical
    renders cannot be masked this way and is skipped outright.
    """
    if a is None or b is None or len(a) != len(b):
        return None
    return {i for i, (x, y) in enumerate(zip(a, b)) if x != y}


def same(a, b, mask):
    if a is None or b is None or len(a) != len(b):
        return False
    return all(x == y for i, (x, y) in enumerate(zip(a, b)) if i not in mask)


def leaves(node, path=()):
    for key, value in node.items():
        if isinstance(value, dict) and value:
            yield from leaves(value, path + (key,))
        else:
            yield path + (key,), value


def perturb(value):
    if isinstance(value, bool):
        return not value
    if isinstance(value, (int, float)):
        return value + 7
    if isinstance(value, str):
        return value + PROBE
    if isinstance(value, list) and value and all(isinstance(v, str) for v in value):
        return value + [PROBE]
    return None


def with_leaf(values, path, new):
    out = copy.deepcopy(values)
    node = out
    for key in path[:-1]:
        node = node[key]
    if new is MISSING:
        del node[path[-1]]
    else:
        node[path[-1]] = new
    return out


def default_at(chart_values, path):
    node = chart_values
    for key in path:
        if not isinstance(node, dict) or key not in node:
            return MISSING
        node = node[key]
    return node


def check(src, targets):
    chart_dir = pull(src)
    abs_files = [os.path.join(ROOT, f) for f in src["files"]]

    base = render(chart_dir, src, abs_files)
    if base is None:
        raise RuntimeError(f"{src['app']}: baseline render failed")
    mask = volatile(base, render(chart_dir, src, abs_files))
    if mask is None:
        return None

    with open(os.path.join(chart_dir, "values.yaml")) as fh:
        chart_values = yaml.safe_load(fh) or {}

    def unchanged(absolute, values, path, new):
        with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False) as tmp:
            yaml.safe_dump(with_leaf(values, path, new), tmp)
            probe_file = tmp.name
        try:
            swapped = [probe_file if p == absolute else p for p in abs_files]
            out = render(chart_dir, src, swapped)
        finally:
            os.unlink(probe_file)
        if out is None:
            return False
        # same() skips the masked lines outright, so an effect that lands
        # inside one of them is invisible to it. PROBE cannot appear in a
        # render that did not read the key, so finding it anywhere is proof
        # the key is live — whichever line it landed on.
        if any(PROBE in line for line in out):
            return False
        return same(base, out, mask)

    def probe(rel, absolute, values, path, new):
        if not unchanged(absolute, values, path, new):
            return None
        # Second probe: restore the chart's own default (or remove the key when
        # the chart has none there). This is what separates a genuinely unread
        # key from one the chart compares against a fixed string.
        if not unchanged(absolute, values, path, default_at(chart_values, path)):
            return None
        return rel, ".".join(str(p) for p in path)

    jobs = []
    for rel, absolute in zip(src["files"], abs_files):
        if rel not in targets:
            continue
        with open(absolute) as fh:
            values = yaml.safe_load(fh) or {}
        for path, value in leaves(values):
            new = perturb(value)
            if new is not None:
                jobs.append((rel, absolute, values, path, new))

    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        results = pool.map(lambda a: probe(*a), jobs)
    return [r for r in results if r], len(mask)


def load_allowlist():
    allowed = {}
    if not os.path.exists(ALLOWLIST):
        return allowed
    with open(ALLOWLIST) as fh:
        for line in fh:
            line = line.split("#", 1)[0].strip()
            if not line:
                continue
            path, _, key = line.partition("::")
            allowed.setdefault(path.strip(), set()).add(key.strip())
    return allowed


def changed_files(base_ref):
    run = subprocess.run(
        ["git", "diff", "--name-only", f"{base_ref}...HEAD"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    run.check_returncode()
    return set(run.stdout.split())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--changed", metavar="BASE_REF", help="only charts touched since BASE_REF")
    args = ap.parse_args()

    touched = changed_files(args.changed) if args.changed else None
    allowed = load_allowlist()

    unread, skipped, masked = {}, [], {}
    for src in sources():
        # A chart bump is exactly when upstream renames or restructures a key,
        # so a changed apps/ file pulls in all of that chart's values files.
        if touched is not None:
            bump = src["app_file"] in touched
            targets = set(src["files"]) if bump else {f for f in src["files"] if f in touched}
            if not targets:
                continue
        else:
            targets = set(src["files"])

        result = check(src, targets)
        if result is None:
            skipped.append(src["app"])
            continue
        found, mask_size = result
        if mask_size:
            masked[src["app"]] = mask_size
        for rel in targets:
            unread.setdefault(rel, set())
        for rel, key in found:
            unread[rel].add(key)

    new = sorted(
        (rel, key)
        for rel, keys in unread.items()
        for key in keys
        if key not in allowed.get(rel, set())
    )
    # An allowlist entry that no longer reproduces means the key was fixed (or
    # the chart started reading it), and the entry is now hiding a future
    # regression at that exact path. Only files this run examined can say that,
    # so --changed never reports stale entries for files it skipped.
    stale = sorted(
        (rel, key)
        for rel, keys in unread.items()
        for key in allowed.get(rel, set())
        if key not in keys
    )

    for app in skipped:
        print(f"::warning::{app}: render is not line-stable, cannot check its values")
    for app, lines in sorted(masked.items()):
        print(
            f"::warning::{app}: {lines} line(s) are regenerated on every render and are "
            "excluded from the comparison; a key whose only effect lands in them reads as unread"
        )

    if new:
        print("Keys no template reads:")
        for rel, key in new:
            print(f"::error file={rel}::{key} is never read by the chart")
        print(
            "\nEither the key is nested wrong / renamed upstream, or it is a leftover.\n"
            f"If it is deliberate, add it to {os.path.relpath(ALLOWLIST, ROOT)} with a reason."
        )
    if stale:
        print("\nAllowlist entries that no longer reproduce — delete them:")
        for rel, key in stale:
            print(f"::error file={os.path.relpath(ALLOWLIST, ROOT)}::{rel}::{key}")
    if not new and not stale:
        print(f"checked {len(unread)} values file(s), no unread keys")
    return 1 if new or stale else 0


if __name__ == "__main__":
    sys.exit(main())
