"""整本分镜逐镜走 3D 导演出片：搭景 → Blender 预演 → 身份首帧（写回分镜首帧）→ LTX 2.5 成片 → 挂回镜头。

逐镜串行：提交一镜、等它挂回或失败，再下一镜。GPU 只有一张，一口气全提交只会在队列里堆着，
而 Core 重启会丢掉内存里的队列；串行时断了就从没挂回的那一镜接着跑。

用法（Core 要先起着）：
    python scripts/director_render_plan.py --plan sp_xxx [--from 3] [--to 8] [--redo]
已经挂回导演成片的镜头默认跳过（--redo 重出）。进度写在 var/director/batch_<plan>.jsonl。
"""
from __future__ import annotations

import argparse
import json
import time
import urllib.error
import urllib.request
from pathlib import Path

BASE = "http://127.0.0.1:8100/api/v2"
#: 一镜最长等多久（身份首帧可能排在别的 LTX 后面）
SHOT_TIMEOUT_S = 60 * 60
RENDER_TRIES = 3


def log(msg: str) -> None:
    print(f"[{time.strftime('%m-%d %H:%M:%S')}] {msg}", flush=True)


def call(method: str, path: str, body: dict | None = None, timeout: float = 180) -> dict:
    req = urllib.request.Request(BASE + path, method=method,
                                 data=json.dumps(body).encode() if body is not None else None,
                                 headers={"content-type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as exc:
        return {"detail": exc.read().decode(errors="replace")[:400], "status": exc.code}


def wait_shot(shot_id: str, job_id: str) -> tuple[bool, str]:
    t0 = time.time()
    last = ""
    continued = False
    while time.time() - t0 < SHOT_TIMEOUT_S:
        run = (call("GET", f"/director/shots/{shot_id}/run", timeout=30) or {}).get("run") or {}
        if run.get("blender_job_id") != job_id:
            return False, "这一镜被别处重新提交了"
        state = f"{run.get('step')}/{run.get('status')}"
        if state != last:
            log(f"    {state} {run.get('percent') or ''}")
            last = state
        if run.get("done"):
            return True, ""
        if run.get("status") in ("failed", "cancelled"):
            # Core 重启打断的串联可以接着跑一次，不重新搭景
            if run.get("can_continue") and not continued:
                call("POST", f"/director/jobs/{job_id}:continue")
                continued = True
                continue
            return False, str(run.get("error") or state)
        time.sleep(15)
    return False, "超时"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--plan", required=True)
    ap.add_argument("--from", dest="start", type=int, default=1)
    ap.add_argument("--to", dest="end", type=int, default=10 ** 6)
    ap.add_argument("--redo", action="store_true")
    ap.add_argument("--frames-only", action="store_true", help="只出分镜图（首帧），不出视频")
    a = ap.parse_args()

    board = call("GET", f"/studio/plans/{a.plan}/board", timeout=60)
    shots = [s for s in board.get("shots") or [] if a.start <= s["order_no"] <= a.end]
    out = Path(__file__).resolve().parents[1] / "var" / "director" / f"batch_{a.plan}.jsonl"
    out.parent.mkdir(parents=True, exist_ok=True)
    log(f"{len(shots)} 镜（{a.start}–{min(a.end, max((s['order_no'] for s in shots), default=0))}），记录 {out}")
    ok = bad = 0
    for s in shots:
        done = ((s.get("director") or {}).get("done") or {}).get("final_job_id") and s.get("video_url")
        if a.frames_only:
            # 看板上看不出首帧是不是预演出的，只按「有没有首帧图」判断
            done = (s.get("first") or {}).get("url") if isinstance(s.get("first"), dict) else None
        if done and not a.redo:
            log(f"镜 {s['order_no']} 已有{'分镜图' if a.frames_only else '导演成片'}，跳过")
            continue
        log(f"镜 {s['order_no']}：{(s.get('description') or '')[:40]}")
        res: dict = {}
        for t in range(1, RENDER_TRIES + 1):
            res = call("POST", f"/director/shots/{s['id']}:render", {"frames_only": a.frames_only})
            if res.get("blender_job_id"):
                break
            log(f"  搭景失败（第 {t} 次）：{str(res.get('detail'))[:160]}")
        rec = {"order_no": s["order_no"], "shot_id": s["id"], "at": time.strftime("%Y-%m-%d %H:%M:%S")}
        if not res.get("blender_job_id"):
            bad += 1
            rec.update(ok=False, error=str(res.get("detail"))[:400])
        else:
            log(f"  预演 {res['blender_job_id']} 机位 {(res.get('framing') or {}).get('camera')}")
            good, err = wait_shot(s["id"], res["blender_job_id"])
            ok, bad = ok + good, bad + (not good)
            rec.update(ok=good, blender_job_id=res["blender_job_id"], error=err or None)
            log(f"  {'✓ 挂回' if good else '✗ ' + err[:160]}")
        with out.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    log(f"完成：成功 {ok}，失败 {bad}")
    return 0 if bad == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
