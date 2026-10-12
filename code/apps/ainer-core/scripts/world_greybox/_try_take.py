import json, sys
from app.db import SessionLocal
from app.models import WorldPerformance, WorldTake
from app.worldmodel import service as ws, compile as wc, blender_run
from app.worldmodel.seeds import chapter01_corridor as ch1
n=int(sys.argv[1]); out=sys.argv[2]
db=SessionLocal()
perf=ws.performance_for_scene(db, ch1.STREET_SCENE_KEY if n in ch1.STREET_SHOTS else ch1.SCENE_KEY)
t=db.query(WorldTake).filter_by(performance_id=perf.id, order_no=n).one()
snap=ws.snapshot(db, perf.world_id, perf.world_version, [perf.region_key])
job=wc.compile_take_job(snap, ws.performance_out(perf), ws.take_out(t), out_dir=out, resolution=(640,384), actors_meta=ch1.ACTORS)
job["save_blend"]=True
m=blender_run.run(job, log_path=out+"/blender.log")
print(json.dumps({k:m[k] for k in ("outputs","timings","check")}, ensure_ascii=False))
