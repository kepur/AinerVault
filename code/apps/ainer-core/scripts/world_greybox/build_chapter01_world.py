"""建第一章空间世界 + 整场一次表演 + 20 个 take（幂等）。用法：python -m scripts.world_greybox.build_chapter01_world"""
import json

from app.db import SessionLocal
from app.worldmodel import service as ws
from app.worldmodel.seeds import chapter01_corridor as ch1

if __name__ == "__main__":
    db = SessionLocal()
    try:
        r = ch1.build(db)
        db.commit()
        snap = ws.snapshot(db, r["world_id"])
        perf = ws.performance_for_scene(db, ch1.SCENE_KEY)
        print(json.dumps({**r, "regions": [x["key"] for x in snap["regions"]], "chunks": len(snap["chunks"]),
                          "instances": len(snap["instances"]), "landmarks": len(snap["landmarks"]),
                          "facts": len(snap["facts"]), "check_rounds": len(perf.check_report["rounds"]),
                          "check_ok": perf.check_report["ok"], "performance_rev": perf.rev}, ensure_ascii=False))
    finally:
        db.close()
