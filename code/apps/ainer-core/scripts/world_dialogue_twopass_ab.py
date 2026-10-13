"""对白两道路由 A/B（无需数据库）：python scripts/world_dialogue_twopass_ab.py <run_out_dir> --shots 2,8,13,15 --mids 0.6,0.4,0.8

复用已有 greybox 运行目录里的白模（shotNN/greybox_a100/pose.mp4、clay.mp4）与面部安全版切片，
状态写在 <run_out_dir>/ab_2p/state.json，可随时中断续跑。每次提交渲染前等待：本机没有 ltx25_infer 进程且 ComfyUI 队列为空。
不改 run 的数据库状态、不重建原成片。
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.worldmodel import pipeline as P  # noqa: E402

PREVIEW = "/Users/mac/AinerWorkFlow/AiComicStudio/var/chapter-01/preview-twenty-v3"


class FileCtx(P.Ctx):
    def __init__(self, out: Path, cfg: dict):
        self.db = self.run = None
        self.cfg = {**P.DEFAULTS, **cfg}
        self.out = out
        self.state_path = out / "ab_2p" / "state.json"
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.st = json.loads(self.state_path.read_text()) if self.state_path.exists() else {"shots": {}}
        self.core, self.gateway_url = P.DEFAULT_CORE, P.DEFAULT_GATEWAY
        self._log = lambda m: print(m, flush=True)
        self._frames = None

    def log(self, msg: str):
        line = time.strftime("%H:%M:%S") + " " + msg
        print(line, flush=True)
        with open(self.out / "ab_2p" / "run.log", "a", encoding="utf-8") as f:
            f.write(line + "\n")

    def save(self, progress=None, status=None):
        tmp = self.state_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.st, indent=1, ensure_ascii=False))
        tmp.replace(self.state_path)


def wait_idle(log):
    t0 = time.time()
    while True:
        busy = subprocess.run(["pgrep", "-f", "ltx25_infer"], capture_output=True).returncode == 0
        try:
            q = httpx.get("http://127.0.0.1:8188/queue", timeout=10).json()
            busy = busy or bool(q.get("queue_running") or q.get("queue_pending"))
        except Exception:  # noqa: BLE001
            pass
        if not busy:
            return
        if int(time.time() - t0) % 300 < 15:
            log("waiting: ltx25_infer running or ComfyUI queue not empty")
        time.sleep(15)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("--shots", default="2,8,13,15")
    ap.add_argument("--mids", default="0.6")
    ap.add_argument("--ab-python", default="/Users/mac/AinerWorkFlow/ATA_Toolbox/.venv/bin/python")
    a = ap.parse_args()
    cfg = {"dialogue_greybox": True, "dialogue_route": "two_pass_anchors",
           "dialogue_anchor_mids": [float(x) for x in a.mids.split(",")], "dialogue_anchor_every": 8,
           "ab_python": a.ab_python, "key_prefix": "wg2p",
           "face_safe_source": {"preview_dir": PREVIEW, "store_db": "/Users/mac/AinerWorkFlow/AiComicStudio/var/productions.sqlite3",
                                "video": f"{PREVIEW}/twenty-shots-dialogue8.mp4", "order": f"{PREVIEW}/shot-order.json"}}
    ctx = FileCtx(Path(a.out), cfg)
    orig_render = P._render

    def render(c, s, inp, key, ckpt, dst):
        if not ckpt.exists():
            wait_idle(c.log)
        return orig_render(c, s, inp, key, ckpt, dst)
    P._render = render
    for n in (int(x) for x in a.shots.split(",")):
        r = P.dialogue_ab_two_pass(ctx, {"n": n, "kind": "speech"})
        ctx.log(f"shot {n}: adopt={r['adopt']} chosen={r['chosen']}")
    print(json.dumps({n: ctx.st["shots"][n].get("dialogue_ab_2p", {}).get("chosen") for n in ctx.st["shots"]}))


if __name__ == "__main__":
    main()
