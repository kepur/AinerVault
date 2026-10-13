"""后台 worker：python -m app.worldmodel.pipeline_worker <run_id> [--force 1,18] [--only 3]"""
from __future__ import annotations

import argparse
import sys

from app.db import SessionLocal
from app.worldmodel import pipeline


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("run_id")
    ap.add_argument("--force", default="")
    ap.add_argument("--only", default="")
    a = ap.parse_args()
    ints = lambda s: {int(x) for x in s.split(",") if x}  # noqa: E731
    db = SessionLocal()
    try:
        pipeline.execute(db, a.run_id, only=ints(a.only) or None, force=ints(a.force), log=lambda m: print(m, flush=True))
        return 0
    except Exception as e:  # noqa: BLE001
        print("FAILED", e, flush=True)
        return 1
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
