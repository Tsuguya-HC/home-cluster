#!/usr/bin/env python3
# taskflow の CRD から .github/schemas/flow.tgy.io/*.json（kubeconform 用）を再生成する。
# kubeconform 同梱の openapi2jsonschema.py と同じ出力（strict: properties を持つ階層すべてに
# additionalProperties: false、x-kubernetes-* 除去、indent=1、ensure_ascii=False、末尾改行なし）。
# 旧 CRD から生成した結果が既存ファイルとバイト一致することを 2026-09-05 に確認済み。
#
#   scripts/crd2schema.py ../taskflow/config/crd/bases/flow.tgy.io_taskhandlers.yaml .github/schemas/flow.tgy.io
#
# CRD の description はそのまま schema に入るので、taskflow 側で types のコメントを変えただけでも
# ここを再生成する（CI の kubeconform はこの schema を見る）。
import json, sys, yaml
def strip(o):
    if isinstance(o, dict):
        return {k: strip(v) for k, v in o.items() if not k.startswith("x-kubernetes-")}
    if isinstance(o, list):
        return [strip(v) for v in o]
    return o
def additional_false(o):
    # strict: properties を持つあらゆる階層に additionalProperties: false を末尾に足す
    if isinstance(o, dict):
        for v in o.values(): additional_false(v)
        if "properties" in o: o["additionalProperties"] = False
    elif isinstance(o, list):
        for v in o: additional_false(v)
    return o
crd_path, out_dir = sys.argv[1], sys.argv[2]
for doc in yaml.safe_load_all(open(crd_path)):
    if not doc or doc.get("kind") != "CustomResourceDefinition": continue
    group = doc["spec"]["group"]; kind = doc["spec"]["names"]["kind"].lower()
    for v in doc["spec"]["versions"]:
        s = additional_false(strip(v["schema"]["openAPIV3Schema"]))
        s["$schema"] = "http://json-schema.org/schema#"
        out = f"{out_dir}/{kind}_{v['name']}.json"
        open(out, "w").write(json.dumps(s, indent=1, ensure_ascii=False, sort_keys=False))
        print(out)
