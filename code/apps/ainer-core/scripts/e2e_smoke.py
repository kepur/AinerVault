#!/usr/bin/env python
"""端到端冒烟：十一步跑完一本书，报出每一步的断点。

**为什么需要它**：每一步单独验过，不等于串起来对。
第一次连贯跑就在第①步抓到说话人被切成句子片段、
在第⑤步抓到截断重试的异常泄漏 —— 两个都是单步测试看不出来的，
因为单步测试用的是干净的小样本，而真实语料会把边界全踩一遍。

用法：
    python scripts/e2e_smoke.py --base http://localhost:8100
    python scripts/e2e_smoke.py --pair cn_wuxia:ru_imperial --lang ru-RU

默认用仓库自带的三章测试语料（含伏笔链、称呼变体、笑点、名物、典故），
换圈层对只需改 --pair —— 冷启动的圈层对最能暴露问题。
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys
import time
import urllib.request as u

FIXTURES = pathlib.Path(__file__).parent / "fixtures"


class Runner:
    def __init__(self, base: str) -> None:
        self.base = base.rstrip("/") + "/api/v2"
        self.fails: list[tuple[str, str, dict]] = []
        self.timings: list[tuple[str, float]] = []

    def call(self, method: str, path: str, body=None, timeout: int = 3000):
        req = u.Request(
            self.base + path,
            data=json.dumps(body).encode() if body is not None else None,
            method=method, headers={"Content-Type": "application/json"},
        )
        try:
            with u.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read() or b"null")
        except u.HTTPError as e:
            return {"ERR": e.code, "body": e.read().decode()[:400]}
        except Exception as e:                       # noqa: BLE001
            return {"ERR": "NET", "body": str(e)[:200]}

    def step(self, tag: str, label: str, fn):
        t = time.time()
        r = fn()
        dt = time.time() - t
        self.timings.append((f"{tag} {label}", dt))
        bad = isinstance(r, dict) and "ERR" in r
        if bad:
            self.fails.append((tag, label, r))
        print(f"{'✗' if bad else '✓'} {tag} {label} ({dt:.0f}s) "
              f"{json.dumps(r, ensure_ascii=False)[:200]}", flush=True)
        return r


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://localhost:8100")
    ap.add_argument("--pair", default="cn_wuxia:ru_imperial",
                    help="源圈层:目标圈层 的 profile code")
    ap.add_argument("--lang", default="ru-RU")
    ap.add_argument("--title", default=None)
    ap.add_argument("--mode", choices=("prose", "script"), default="prose",
                    help="prose 译本线（规则分块，零成本）／script 成片线"
                         "（LLM 拆场景，产出时间地点天气情绪）")
    ap.add_argument("--stop-after", default=None,
                    help="跑到某一步就停，如 --stop-after ⑨。调翻译链时不必等完")
    args = ap.parse_args()

    src_code, tgt_code = args.pair.split(":")
    R = Runner(args.base)
    title = args.title or f"冒烟·{time.strftime('%m%d-%H%M')}"

    nv = R.call("POST", "/novels", {"title": title, "source_language_code": "zh-CN"})
    if "ERR" in nv:
        print("建书失败", nv)
        return 1
    chapters = sorted(FIXTURES.glob("ch*.txt"))
    if not chapters:
        print(f"没有测试语料：{FIXTURES}")
        return 1
    chs = []
    for i, f in enumerate(chapters, 1):
        c = R.call("POST", f"/novels/{nv['id']}/chapters",
                   {"title": f"第{i}章", "order_no": i,
                    "content": f.read_text(encoding="utf-8")})
        chs.append(c["id"])

    ps = {p["code"]: p["id"] for p in R.call("GET", "/world-profiles")}
    if src_code not in ps or tgt_code not in ps:
        print(f"圈层不存在：{src_code} / {tgt_code}。先调用 /worldview:seed")
        return 1
    tf = R.call("POST", f"/novels/{nv['id']}/transforms", {
        "target_language_code": args.lang,
        "source_profile_id": ps[src_code], "target_profile_id": ps[tgt_code]})
    if "ERR" in tf:
        print("建映射失败", tf)
        return 1
    R.call("POST", f"/transforms/{tf['id']}:activate")
    print(f"书 {nv['id']}　映射 {tf['id']}　{src_code} → {tgt_code}\n", flush=True)

    #: 译本线用规则分块（零成本），成片线用 LLM 拆场景 ——
    #: 后者多出时间/地点/天气/情绪，那是分镜的输入，译本用不上。
    if args.mode == "script":
        step_one = ("①", "拆剧本", lambda c: R.call(
            "POST", f"/chapters/{c}/script:generate",
            {"scene_granularity": "medium", "confirm_discard_edits": True}))
    else:
        step_one = ("①", "分块", lambda c: R.call(
            "POST", f"/chapters/{c}/prose:build", {"force": True}))

    per_chapter = [
        step_one,
        ("②", "实体+称呼", lambda c: R.call("POST", f"/chapters/{c}/entities:extract", {})),
        ("③", "装置", lambda c: R.call("POST", f"/chapters/{c}/devices:extract", {})),
        ("④", "梗", lambda c: R.call("POST", f"/chapters/{c}/memes:extract", {})),
        ("⑤", "名物", lambda c: R.call(
            "POST", f"/transforms/{tf['id']}/lexicon:survey?chapter_id={c}")),
    ]
    def stop_here(tag: str) -> bool:
        return bool(args.stop_after) and tag > args.stop_after

    for tag, label, fn in per_chapter:
        if stop_here(tag):
            break
        for i, c in enumerate(chs, 1):
            R.step(tag, f"{label} ch{i}", lambda c=c, fn=fn: fn(c))

    if not stop_here("⑥"):
        R.step("⑥", "命名+称呼定形",
               lambda: R.call("POST", f"/transforms/{tf['id']}/names:suggest", {}))
    if not stop_here("⑦"):
        R.step("⑦", "梗呈现",
               lambda: R.call("POST", f"/transforms/{tf['id']}/memes:render", {}))
    if not stop_here("⑧"):
        gate = R.step("⑧", "门禁",
                      lambda: R.call("GET", f"/transforms/{tf['id']}/preflight"))
        # 门禁不通过时**必须先审词表再翻译**。
        # 未审核的词条一条都不会进翻译提示词 —— 带 force 硬翻，
        # 等于没有名物词表，译名各章各样。
        # 第二轮端到端就是这么跑的，结果 25 条 lexicon_miss。
        # 冒烟里用批量通过代替人审：不是流程简化，是把人的那一步自动化，
        # 走的仍是同一条路径。
        if isinstance(gate, dict) and not gate.get("ready"):
            lex = R.call("GET", f"/transforms/{tf['id']}/lexicon")
            ids = [r["id"] for r in (lex if isinstance(lex, list) else [])
                   if r.get("target_term") and r.get("status") == "candidate"]
            if ids:
                R.step("⑧b", f"审核词表（{len(ids)} 条）", lambda: R.call(
                    "POST", f"/transforms/{tf['id']}/lexicon:batch-approve",
                    {"ids": ids}))
    for i, c in enumerate(chs, 1):
        if stop_here("⑨"):
            break
        R.step("⑨", f"翻译 ch{i}", lambda c=c: R.call(
            "POST", f"/chapters/{c}/translation/{args.lang}:run",
            # force 只跳过门禁的**其余**检查；词表已在 ⑧b 审过，
            # 所以这一步拿到的是真正注入了名物对照的译文
            {"only_missing": False, "force": True, "mode": "adaptive"}))
    for i, c in enumerate(chs, 1):
        if stop_here("⑩a"):
            break
        R.step("⑩a", f"违规审查 ch{i}",
               lambda c=c: R.call("POST", f"/chapters/{c}/prose:review", {}))
        R.step("⑩b", f"回译校验 ch{i}", lambda c=c: R.call(
            "POST", f"/chapters/{c}/prose:back-check", {"transform_id": tf["id"]}))
    R.step("⑩c", "跨章审计", lambda: R.call("GET", f"/transforms/{tf['id']}/audit"))

    revs = []
    for i, c in enumerate(chs, 1):
        r = R.step("⑩d", f"文化差异审查 ch{i}", lambda c=c: R.call(
            "POST", f"/chapters/{c}/culture-review/{args.lang}:run", {}))
        if isinstance(r, dict) and r.get("review_id"):
            revs.append(r["review_id"])
    for rid in revs:
        d = R.call("GET", f"/culture-reviews/{rid}")
        for f in [x for x in d.get("findings", [])
                  if x["severity"] >= 4 and x.get("proposed_text")][:3]:
            R.call("PATCH", f"/culture-findings/{f['id']}", {"verdict": "accepted"})
        R.step("⑪", f"裁决落地 {rid[-6:]}",
               lambda rid=rid: R.call("POST", f"/culture-reviews/{rid}:apply", {}))
    R.step("⑪", "沉淀模板", lambda: R.call(
        "POST", f"/transforms/{tf['id']}/lexicon:promote-template?include_candidates=true"))

    print(f"\n{'=' * 62}")
    slow = sorted(R.timings, key=lambda x: -x[1])[:5]
    print("最慢五步：" + "　".join(f"{n} {t:.0f}s" for n, t in slow))
    print(f"总耗时 {sum(t for _, t in R.timings) / 60:.1f} 分钟")
    if not R.fails:
        print("断点 0 —— 十一步全通")
        return 0
    print(f"断点 {len(R.fails)} 处：")
    for tag, label, r in R.fails:
        print(f"  ✗ {tag} {label}: {json.dumps(r, ensure_ascii=False)[:220]}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
