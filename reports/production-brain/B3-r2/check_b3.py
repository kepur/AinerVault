#!/usr/bin/env python3
"""B3-r2 independent check: validates all entries + ref_index, negative cases fail non-zero.
Usage: python3 check_b3.py [--negative]
 - default: check current repo files, exit 0 on pass, non-zero on fail
 - --negative: run 4 intentional bad fixtures, each must fail (proves checker is effective)
"""
import json, re, sys, pathlib, copy
JSON_PATH = "/Users/mac/AinerWorkFlow/AinerHub_IDEA/docs/v2/production_brain/techniques_v0.json"
MD_PATH = "/Users/mac/AinerWorkFlow/AinerHub_IDEA/docs/v2/production_brain/techniques_v0.md"
PLAN_EX = "/Users/mac/AinerWorkFlow/AnimeWorldZero/contracts/drafts/production_plan.v0/examples"
REF_PAT = re.compile(r"^tech:[a-z0-9_.]+$")
REQUIRED_TOP = ["id","ref","aliases","name","category","effect","when_to_use","when_not_to_use","prerequisites","execution","checkable_signals","common_failures","example_backpack_elephant","counterexample","executable_skill","applicable_version","sources"]
REQUIRED_EXEC = ["blocking","timing","expression","gaze","shot","cut","sound","effects"]
PLAN10 = ["tech:narrative.information_gap","tech:narrative.delayed_reveal","tech:comedy.setup_expectation","tech:comedy.pause_reaction","tech:comedy.deadpan","tech:comedy.double_take","tech:edit.reaction_shot","tech:edit.sound_first","tech:edit.smash_cut","tech:camera.low_angle_partial"]

def check_data(d, md_text=None, label="current"):
    errs=[]
    # count/version
    if d.get("count") != len(d.get("techniques",[])):
        errs.append(f"[{label}] count {d.get('count')} != len {len(d.get('techniques',[]))}")
    if d.get("version") != "v0.1":
        errs.append(f"[{label}] version != v0.1 : {d.get('version')}")
    techs = d.get("techniques",[])
    # 24 old ids preserved
    ids = [t.get("id") for t in techs]
    if len(ids)!=len(set(ids)):
        errs.append(f"[{label}] dup ids")
    for must in ["N1","N2","N3","N4","N5","N6","C1","C2","C3","C4","C5","D1","D2","D3","D4","D5","D6","D7","A1","A2","A3","A4","A5","A6","C6","D8","D9"]:
        if must not in ids:
            errs.append(f"[{label}] missing id {must}")
    if len(techs)!=27:
        errs.append(f"[{label}] expected 27, got {len(techs)}")
    # refs
    refs=[t.get("ref","") for t in techs]
    if len(refs)!=len(set(refs)):
        errs.append(f"[{label}] dup refs")
    for t in techs:
        r=t.get("ref","")
        if not REF_PAT.match(r):
            errs.append(f"[{label}] {t.get('id')} bad ref {r!r}")
        cls=r.split(":")[1].split(".")[0] if ":" in r and "." in r else ""
        if cls not in ("narrative","comedy","edit","camera","anim"):
            errs.append(f"[{label}] {t.get('id')} bad class {cls}")
        for f in REQUIRED_TOP:
            if f not in t:
                errs.append(f"[{label}] {t.get('id')} missing field {f}")
            elif f in ("timing","verified_by","aliases"):
                pass  # null allowed for timing/verified_by, empty list allowed for aliases
            elif not t[f]:
                errs.append(f"[{label}] {t.get('id')} empty {f}")
        for f in REQUIRED_EXEC:
            if f not in t.get("execution",{}):
                errs.append(f"[{label}] {t.get('id')} missing exec {f}")
            elif not t["execution"][f]:
                errs.append(f"[{label}] {t.get('id')} empty exec {f}")
        # B2-mandated observability: N1/N2/N6/C4/D5/C3/D1 (+C1/A3 already) and 3 new must state source/responsibility + unknown
        sig="；".join(t.get("checkable_signals",[]))
        if t.get("id") in ("N1","N2","N6","C1","C3","C4","D1","D3","D5","A3","C6","D8","D9"):
            if "unknown" not in sig:
                errs.append(f"[{label}] {t.get('id')} signals lack unknown fallback")
            if ("执行数据" not in sig and "视觉审片" not in sig and "计划" not in sig):
                errs.append(f"[{label}] {t.get('id')} signals lack data source/responsibility")
        # backpack example: must mention 书包 (pre-reveal entries may not yet show elephant)
        if "书包" not in t.get("example_backpack_elephant",""):
            errs.append(f"[{label}] {t.get('id')} backpack example missing")
        # no pending cut
        if "待 awz.P3.J1" in t.get("execution",{}).get("cut",""):
            errs.append(f"[{label}] {t.get('id')} cut still pending J1")
        # no english mixing left (check whole entry dump; J-cut/L-cut/Mesh Trails/dB/fps are contract/technical terms and allowed)
        import json as _j; blob = _j.dumps(t, ensure_ascii=False)
        for bad in [" heard", " auto ", "大pp", "3818", "revelation", "出 bug", "渲染 bug", "世界 fact", "世界 revision"]:
            if bad.strip() and bad in blob:
                errs.append(f"[{label}] {t.get('id')} still has {bad!r}")
    # D3 specific
    d3=[t for t in techs if t["id"]=="D3"][0]
    if "按上述" in d3["execution"]["timing"]:
        errs.append("[label] D3 still has 按上述")
    if d3["execution"]["sound"]=="核心就是声音设计":
        errs.append("[label] D3 sound still vague")
    # C1 unify: must mention 示例 and ≥2
    c1=[t for t in techs if t["id"]=="C1"][0]
    c1blob="；".join(c1["checkable_signals"])+c1["execution"]["timing"]+c1["execution"]["sound"]
    if "≥2" not in c1blob or "示例" not in c1blob:
        errs.append(f"[{label}] C1 not unified")
    # A3 fps
    a3=[t for t in techs if t["id"]=="A3"][0]
    if "timebase.fps" not in a3["execution"]["timing"] or "timebase.fps" not in "；".join(a3["checkable_signals"]):
        errs.append(f"[{label}] A3 missing fps")
    # sources unify: no bare forms
    allsrc=sum([t.get("sources",[]) for t in techs],[])
    for bare in ["《电影语言》", "《电影剪辑》", "《喜剧的秘密》", "《动画师生存手册》"]:
        # bare exactly equals (without author) should not appear
        if bare in allsrc:
            errs.append(f"[{label}] bare source still present: {bare}")
    if not any("待核" in s for s in allsrc):
        errs.append(f"[{label}] no 待核 source mark")
    # ref_index
    ri=d.get("ref_index",{})
    if not ri:
        errs.append(f"[{label}] missing ref_index")
    else:
        # every ref+alias maps correctly, no dup keys (json already), check coverage
        for t in techs:
            if ri.get(t["ref"])!=t["id"]:
                errs.append(f"[{label}] ref_index {t['ref']} != {t['id']}")
            for a in t.get("aliases",[]):
                if ri.get(a)!=t["id"]:
                    errs.append(f"[{label}] alias {a} != {t['id']}")
        for p in PLAN10:
            if p not in ri:
                errs.append(f"[{label}] plan ref {p} unresolvable")
        if len(ri)!=27+sum(len(t.get("aliases",[])) for t in techs):
            errs.append(f"[{label}] ref_index size mismatch {len(ri)}")
    # conventions
    for k in ["timing_null_means","verified_by_null_means","duration_conflict_rule","example_durations_are_examples","validation_scope"]:
        if k not in d.get("conventions",{}):
            errs.append(f"[{label}] missing conventions.{k}")
    if "source_note" not in d:
        errs.append(f"[{label}] missing source_note")
    # MD consistency
    if md_text is not None:
        for t in techs:
            for key in ["name","effect","example_backpack_elephant","counterexample"]:
                v=t[key].strip()
                if v and v not in md_text:
                    errs.append(f"[{label}] MD missing {t['id']}.{key}")
            for s in t["checkable_signals"]:
                if s.strip() and s.strip() not in md_text:
                    errs.append(f"[{label}] MD missing {t['id']}.signal")
            for ek,ev in t["execution"].items():
                if ev.strip() and ev.strip() not in md_text:
                    errs.append(f"[{label}] MD missing {t['id']}.exec.{ek}")
            if t["ref"] not in md_text or t["id"] not in md_text:
                errs.append(f"[{label}] MD missing {t['id']}.ref")
        # MD must mention ref_index and 10 refs
        for p in PLAN10:
            if p not in md_text:
                errs.append(f"[{label}] MD missing plan ref {p}")
    return errs

def main():
    neg = "--negative" in sys.argv
    d=json.load(open(JSON_PATH,encoding="utf-8"))
    md=open(MD_PATH,encoding="utf-8").read()
    if not neg:
        errs=check_data(d, md, "current")
        print(f"count={d.get('count')} version={d.get('version')} n={len(d.get('techniques',[]))} ref_index={len(d.get('ref_index',{}))}")
        print(f"plan10 resolvable: {sum(1 for p in PLAN10 if p in d.get('ref_index',{}))}/10")
        if errs:
            print("FAIL:")
            for e in errs[:60]:
                print(" -",e)
            print(f"total {len(errs)} errors")
            return 1
        print("PASS: all 27 entries + ref_index + MD consistent")
        return 0
    else:
        # 4 intentional bad fixtures, each must fail
        cases=[]
        d1=copy.deepcopy(d); d1["techniques"][0]["ref"]="bad ref with space"
        cases.append(("bad-ref-format",d1,None))
        d2=copy.deepcopy(d); d2["techniques"][1]["ref"]=d2["techniques"][0]["ref"]
        # also fix ref_index to duplicate? checker checks dup refs via list, so keep ref_index stale to also trigger
        cases.append(("dup-ref",d2,None))
        d3=copy.deepcopy(d); del d3["ref_index"]["tech:edit.smash_cut"]
        cases.append(("missing-plan-ref",d3,None))
        d4=copy.deepcopy(d); md_bad=md.replace(d["techniques"][0]["effect"], "###DELETED###")
        cases.append(("md-inconsistent",d,md_bad))
        ok=True
        for name, dd, m in cases:
            mtext = m if m is not None else md
            # for dup case, need to recompute? check_data uses dd as is
            errs=check_data(dd, mtext, name)
            if not errs:
                print(f"NEG {name}: EXPECTED FAIL BUT PASSED -> checker ineffective")
                ok=False
            else:
                print(f"NEG {name}: correctly failed with {len(errs)} errors; e.g. {errs[0]}")
        return 0 if ok else 1

if __name__=="__main__":
    sys.exit(main())
