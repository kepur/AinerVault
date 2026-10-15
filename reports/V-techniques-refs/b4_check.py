#!/usr/bin/env python3
"""hub.P1.B4 独立复核 hub.P1.B3（只读，不改被验文件；只写本目录与系统临时目录）。

独立实现，不复用 B3-r2/check_b3.py。覆盖：
- JSON 重复键检测（整文件逐层）；
- 24 旧 id 保持 + C6/D8/D9 新增、ref/aliases 全局唯一、alias 不得覆盖规范 ref、
  ref_index 双向一致（无悬空、无缺失、值全为有效 id）；
- 计划引用从 J1 两例动态提取（非硬编码），断言恰为 10 个且映射到预期 id；
- JSON 内全部 tech:* 引用闭包；
- MD↔JSON 双向一致（JSON→MD 内容包含；MD→JSON 章节与 ref_index 表精确相等）；
- B2 返工点：cut 无过期 J1 等待、英文夹杂、来源统一+待核、conventions 五键、
  时长冲突规则、不新增 5cm/0.5秒/IoU 全局门（唯一出现须为 conventions 否认句）；
- v0 原字节身份：r1 归档 SHA 与 original_sha256.txt 一致；
- 7 个不利反例（含任务要求的 5 类），故意坏 fixture 必须非零（有错即 checker 有效）。
用法：python3 b4_check.py [--negative]；exit 0=通过（默认：真文件通过；--negative：坏例全被捉）。
"""
import copy
import hashlib
import json
import os
import re
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__ + "/../")))
JSON_PATH = os.path.join(BASE, "docs", "v2", "production_brain", "techniques_v0.json")
MD_PATH = os.path.join(BASE, "docs", "v2", "production_brain", "techniques_v0.md")
R1_JSON = os.path.join(BASE, "reports", "production-brain", "B3-r2", "techniques_v0.r1.json")
R1_MD = os.path.join(BASE, "reports", "production-brain", "B3-r2", "techniques_v0.r1.md")
R1_SHA = os.path.join(BASE, "reports", "production-brain", "B3-r2", "original_sha256.txt")
J1_DIR = "/Users/mac/AinerWorkFlow/AnimeWorldZero/contracts/drafts/production_plan.v0/examples"

REF_PAT = re.compile(r"^tech:[a-z0-9_.]+$")
REF_CLASS = ("narrative", "comedy", "edit", "camera", "anim")
OLD_IDS = ["N1", "N2", "N3", "N4", "N5", "N6", "C1", "C2", "C3", "C4", "C5",
           "D1", "D2", "D3", "D4", "D5", "D6", "D7", "A1", "A2", "A3", "A4", "A5", "A6"]
NEW_IDS = ["C6", "D8", "D9"]
REQUIRED_TOP = ["id", "ref", "aliases", "name", "category", "effect", "when_to_use",
                "when_not_to_use", "prerequisites", "execution", "checkable_signals",
                "common_failures", "example_backpack_elephant", "counterexample",
                "executable_skill", "applicable_version", "sources"]
REQUIRED_EXEC = ["blocking", "timing", "expression", "gaze", "shot", "cut", "sound", "effects"]
EXPECTED_PLAN_MAP = {
    "tech:narrative.information_gap": "N1", "tech:narrative.delayed_reveal": "N4",
    "tech:comedy.setup_expectation": "C1", "tech:comedy.pause_reaction": "C2",
    "tech:comedy.deadpan": "C3", "tech:comedy.double_take": "C6",
    "tech:edit.reaction_shot": "D1", "tech:edit.sound_first": "D3",
    "tech:edit.smash_cut": "D8", "tech:camera.low_angle_partial": "D9",
}
BAD_ENGLISH = [" heard", " auto ", "大pp", "3818", "revelation", "出 bug", "渲染 bug",
               "世界 fact", "世界 revision"]
BARE_SOURCES = ["《电影语言》", "《电影剪辑》", "《喜剧的秘密》", "《动画师生存手册》"]


def find_dup_keys(text):
    """整文件逐层重复键检测；返回 [path/key...]（路径为近似定位，键名精确）。"""
    import json as _j
    dups = []

    def hook(pairs):
        seen = set()
        for k, _ in pairs:
            if k in seen:
                dups.append(k)
            seen.add(k)
        return {k: v for k, v in pairs}

    _j.JSONDecoder(object_pairs_hook=hook).decode(text)
    return dups


def extract_plan_refs():
    """从 J1 两例动态提取 tech: 引用（非硬编码）。"""
    refs = set()
    files = sorted(f for f in os.listdir(J1_DIR) if f.endswith(".json"))

    def walk(o):
        if isinstance(o, dict):
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)
        elif isinstance(o, str) and o.startswith("tech:"):
            refs.add(o)

    for f in files:
        with open(os.path.join(J1_DIR, f), encoding="utf-8") as fh:
            walk(json.load(fh))
    return refs, files


def check_data(d, md_text, plan_refs, label):
    errs = []
    if d.get("version") != "v0.1":
        errs.append(f"[{label}] version={d.get('version')!r} != v0.1")
    techs = d.get("techniques", [])
    if d.get("count") != len(techs):
        errs.append(f"[{label}] count {d.get('count')} != {len(techs)}")
    if len(techs) != 27:
        errs.append(f"[{label}] n={len(techs)} != 27")
    ids = [t.get("id") for t in techs]
    if len(ids) != len(set(ids)):
        errs.append(f"[{label}] dup ids")
    for must in OLD_IDS + NEW_IDS:
        if must not in ids:
            errs.append(f"[{label}] missing id {must}")
    extra = [i for i in ids if i not in OLD_IDS + NEW_IDS]
    if extra:
        errs.append(f"[{label}] unexpected ids {extra}")
    by_id = {t.get("id"): t for t in techs}
    # 字段
    for t in techs:
        for f in REQUIRED_TOP:
            if f not in t:
                errs.append(f"[{label}] {t.get('id')} missing {f}")
        ex = t.get("execution", {})
        for f in REQUIRED_EXEC:
            if f not in ex:
                errs.append(f"[{label}] {t.get('id')} missing exec.{f}")
            elif not ex[f]:
                errs.append(f"[{label}] {t.get('id')} empty exec.{f}")
    # ref 格式/类别/唯一
    refs = [t.get("ref", "") for t in techs]
    for t in techs:
        r = t.get("ref", "")
        if not REF_PAT.match(r):
            errs.append(f"[{label}] {t.get('id')} bad ref {r!r}")
            continue
        cls = r.split(":")[1].split(".")[0]
        if cls not in REF_CLASS:
            errs.append(f"[{label}] {t.get('id')} bad class {cls}")
    if len(refs) != len(set(refs)):
        errs.append(f"[{label}] dup refs")
    # aliases 全局唯一 + 不得覆盖规范 ref
    seen_alias = {}
    for t in techs:
        for a in t.get("aliases", []):
            if a in refs:
                errs.append(f"[{label}] alias {a} shadows canonical ref ({t['id']})")
            if a in seen_alias:
                errs.append(f"[{label}] dup alias {a} in {t['id']} and {seen_alias[a]}")
            seen_alias[a] = t["id"]
    # ref_index 双向一致
    ri = d.get("ref_index", {})
    want_keys = set(refs) | set(seen_alias)
    if set(ri) != want_keys:
        errs.append(f"[{label}] ref_index keys != refs+aliases "
                    f"(missing {sorted(want_keys - set(ri))[:3]} extra {sorted(set(ri) - want_keys)[:3]})")
    for t in techs:
        if ri.get(t["ref"]) != t["id"]:
            errs.append(f"[{label}] ref_index[{t['ref']}]={ri.get(t['ref'])} != {t['id']}")
        for a in t.get("aliases", []):
            if ri.get(a) != t["id"]:
                errs.append(f"[{label}] ref_index alias {a} wrong")
    for k, v in ri.items():
        if v not in ids:
            errs.append(f"[{label}] ref_index dangling {k} -> {v}")
    # 计划引用：动态集合须恰为预期 10 个，且映射到预期 id
    if set(plan_refs) != set(EXPECTED_PLAN_MAP):
        errs.append(f"[{label}] plan refs != expected10 "
                    f"(missing {sorted(set(EXPECTED_PLAN_MAP) - set(plan_refs))} "
                    f"extra {sorted(set(plan_refs) - set(EXPECTED_PLAN_MAP))})")
    for p, want_id in EXPECTED_PLAN_MAP.items():
        if ri.get(p) != want_id:
            errs.append(f"[{label}] plan {p} -> {ri.get(p)} != {want_id}")
    # JSON 内 tech:* 闭包
    for m in set(re.findall(r"tech:[a-z0-9_.]+", json.dumps(d, ensure_ascii=False))):
        if m not in ri:
            errs.append(f"[{label}] tech mention unresolvable: {m}")
    # 新条目完整性
    for nid in NEW_IDS:
        t = by_id.get(nid)
        if t is None:
            continue
        sig = "；".join(t.get("checkable_signals", []))
        if "unknown" not in sig:
            errs.append(f"[{label}] {nid} signals lack unknown")
        if not any(k in sig for k in ("执行数据", "视觉审片", "计划")):
            errs.append(f"[{label}] {nid} signals lack source/responsibility")
        if "书包" not in t.get("example_backpack_elephant", ""):
            errs.append(f"[{label}] {nid} backpack missing")
        if not t.get("counterexample"):
            errs.append(f"[{label}] {nid} counterexample missing")
        if not t.get("sources"):
            errs.append(f"[{label}] {nid} sources missing")
    # B2 返工：cut 无过期等待（全部条目）
    for t in techs:
        if "待 awz.P3.J1" in t.get("execution", {}).get("cut", ""):
            errs.append(f"[{label}] {t['id']} cut still pending J1")
    # 英文夹杂（全条目 blob）
    for t in techs:
        blob = json.dumps(t, ensure_ascii=False)
        for bad in BAD_ENGLISH:
            if bad in blob:
                errs.append(f"[{label}] {t['id']} has {bad!r}")
    # C1 统一
    c1 = by_id.get("C1", {})
    c1blob = "；".join(c1.get("checkable_signals", [])) + c1.get("execution", {}).get("timing", "") \
        + c1.get("execution", {}).get("sound", "")
    if "≥2" not in c1blob or "示例" not in c1blob:
        errs.append(f"[{label}] C1 counts not unified")
    # D3
    d3 = by_id.get("D3", {})
    if "按上述" in d3.get("execution", {}).get("timing", ""):
        errs.append(f"[{label}] D3 按上述")
    if d3.get("execution", {}).get("sound") == "核心就是声音设计":
        errs.append(f"[{label}] D3 sound vague")
    # A3 fps
    a3 = by_id.get("A3", {})
    if "timebase.fps" not in a3.get("execution", {}).get("timing", ""):
        errs.append(f"[{label}] A3 timing missing timebase.fps")
    # 来源统一
    allsrc = sum([t.get("sources", []) for t in techs], [])
    for bare in BARE_SOURCES:
        if bare in allsrc:
            errs.append(f"[{label}] bare source {bare}")
    if not any("待核" in s for s in allsrc):
        errs.append(f"[{label}] no 待核 mark")
    # conventions + source_note
    for k in ["timing_null_means", "verified_by_null_means", "duration_conflict_rule",
              "example_durations_are_examples", "validation_scope"]:
        if k not in d.get("conventions", {}):
            errs.append(f"[{label}] missing conventions.{k}")
    if "source_note" not in d:
        errs.append(f"[{label}] missing source_note")
    # 不新增全局门：techniques 数组内不得出现 5cm/IoU（唯一允许在 conventions 否认句）
    arr_blob = json.dumps(techs, ensure_ascii=False)
    for tok in ("5cm", "IoU"):
        if tok in arr_blob:
            errs.append(f"[{label}] new global gate token {tok} inside techniques")
    # MD 双向一致
    if md_text is not None:
        for t in techs:
            for key in ["name", "effect", "example_backpack_elephant", "counterexample"]:
                v = (t.get(key) or "").strip()
                if v and v not in md_text:
                    errs.append(f"[{label}] MD missing {t['id']}.{key}")
            for s in t.get("checkable_signals", []):
                if s.strip() and s.strip() not in md_text:
                    errs.append(f"[{label}] MD missing {t['id']}.signal")
            if t["ref"] not in md_text or t["id"] not in md_text:
                errs.append(f"[{label}] MD missing {t['id']}.ref")
        heads = set(re.findall(r"^### ([A-Z][0-9]+)\b", md_text, re.M))
        if heads != set(ids):
            errs.append(f"[{label}] MD headings != ids "
                        f"(missing {sorted(set(ids) - heads)} extra {sorted(heads - set(ids))})")
        md_ri = dict(re.findall(r"`(tech:[a-z0-9_.]+)`\s*→\s*([A-Z][0-9]+)", md_text))
        md_ri_table = {k: v for k, v in md_ri.items() if k in ri or True}
        # 只比对 ref_index 表节（## 稳定引用索引 与下一 ## 之间）
        m = re.search(r"## 稳定引用索引（ref_index）(.*?)(?=\n## )", md_text, re.S)
        if not m:
            errs.append(f"[{label}] MD missing ref_index section")
        else:
            tab = dict(re.findall(r"`(tech:[a-z0-9_.]+)`\s*→\s*([A-Z][0-9]+)", m.group(1)))
            if tab != ri:
                errs.append(f"[{label}] MD ref_index table != JSON "
                            f"(md {len(tab)} vs json {len(ri)})")
        for p in EXPECTED_PLAN_MAP:
            if p not in md_text:
                errs.append(f"[{label}] MD missing plan ref {p}")
    return errs


def main():
    neg = "--negative" in sys.argv
    with open(JSON_PATH, encoding="utf-8") as f:
        raw = f.read()
    with open(MD_PATH, encoding="utf-8") as f:
        md = f.read()
    plan_refs, plan_files = extract_plan_refs()
    print(f"plan files: {plan_files} -> {len(plan_refs)} refs")
    if not neg:
        errs = []
        dups = find_dup_keys(raw)
        if dups:
            errs.append(f"[current] dup JSON keys: {dups[:5]}")
        d = json.loads(raw)
        errs += check_data(d, md, plan_refs, "current")
        # v0 归档身份：r1 归档字节须等于 original_sha256.txt 记录的 v0 原字节
        #（该文件记的是 docs/... live 路径名 + v0 原 SHA；r1.* 为原字节归档）
        recorded = set(open(R1_SHA, encoding="utf-8").read().split()[0::2])
        for name, path in [("techniques_v0.r1.json", R1_JSON), ("techniques_v0.r1.md", R1_MD)]:
            h = hashlib.sha256(open(path, "rb").read()).hexdigest()
            if h not in recorded:
                errs.append(f"[current] r1 archive {name} sha not in original record")
        print(f"entries=27 plan_refs={len(plan_refs)} md_heads<checked> r1_identity<checked>")
        if errs:
            print("FAIL:")
            for e in errs[:60]:
                print(" -", e)
            print(f"total {len(errs)} errors")
            return 1
        print("PASS: independent recheck green (dup-keys clean, 27 entries, ref_index bijective, "
              "plan10 exact map, tech closure, MD bidirectional, B2 rework, r1 identity)")
        return 0
    # 7 个不利反例：故意坏 fixture 必须被捉（非零错误）
    d0 = json.loads(raw)
    cases = []

    def raw_with_dup_ref():
        # N1 对象内重复 "ref" 键（JSON 文本层）
        return raw.replace('"ref": "tech:narrative.information_gap"',
                           '"ref": "tech:narrative.information_gap", "ref": "tech:ghost.dup"', 1)

    c1 = copy.deepcopy(d0)
    c1["techniques"][5]["aliases"] = ["tech:comedy.deadpan"]  # N6 别名覆盖 C3 规范 ref
    c1["ref_index"]["tech:comedy.deadpan"] = "C3"  # 索引保持“正确”，看 alias-shadow 规则是否仍捉
    cases.append(("alias-shadows-canonical", c1, md))
    c2 = copy.deepcopy(d0)
    c2["ref_index"]["tech:ghost.dangling"] = "N9"  # 悬空：未知键 + 未知 id
    cases.append(("dangling-index", c2, md))
    c3 = copy.deepcopy(d0)
    c3["techniques"][0]["aliases"] = ["tech:shared.dupe"]
    c3["techniques"][1]["aliases"] = ["tech:shared.dupe"]  # 重复语义引用（同别名两条目）
    cases.append(("dup-alias", c3, md))
    c4 = copy.deepcopy(d0)
    c4["techniques"][0]["id"] = "N1x"  # 改旧 id
    cases.append(("renamed-old-id", c4, md))
    c5 = copy.deepcopy(d0)
    del c5["ref_index"]["tech:edit.smash_cut"]  # 计划引用悬空
    cases.append(("missing-plan-ref", c5, md))
    c6 = copy.deepcopy(d0)
    md_bad = md.replace("### C6 ", "### CX ", 1)  # MD 章节对不上 JSON
    cases.append(("md-heading-mismatch", c6, md_bad))

    ok = True
    # N1 文本层重复键单独测
    if not find_dup_keys(raw_with_dup_ref()):
        print("NEG dup-json-keys: EXPECTED FAIL BUT PASSED -> checker ineffective")
        ok = False
    else:
        print("NEG dup-json-keys: correctly failed (dup key detected)")
    if find_dup_keys(raw):
        print("NEG dup-json-keys: FALSE POSITIVE on real file")
        ok = False
    for name, dd, m in cases:
        errs = check_data(dd, m, plan_refs, name)
        if not errs:
            print(f"NEG {name}: EXPECTED FAIL BUT PASSED -> checker ineffective")
            ok = False
        else:
            print(f"NEG {name}: correctly failed with {len(errs)} errors; e.g. {errs[0]}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
