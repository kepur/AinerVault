"""手动模式的接口。

和交付清单（/manifest）指向同一批数据，区别只在投影方式：
manifest 给程序，handoff 给人。所以这里除了 JSON，还出三种落地文件 ——
字幕、剪辑标记表、离线手册。
"""
from __future__ import annotations

import re

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import PlainTextResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.ids import new_id
from app.models import ShotPlan, SpecStatus
from app.pipelines import handoff as hf

router = APIRouter(prefix="/api/v2", tags=["handoff"])


def _plan(plan_id: str, db: Session) -> ShotPlan:
    plan = db.get(ShotPlan, plan_id)
    if plan is None:
        raise HTTPException(status_code=404, detail="shot plan not found")
    return plan


@router.get("/shot-plans/{plan_id}/handoff")
def get_handoff(plan_id: str, target: str = Query("generic"),
                db: Session = Depends(get_db)) -> dict:
    """轨道化时间轴 + 每格可复制的提示词。"""
    return hf.build_handoff(db, _plan(plan_id, db), target=target)


@router.get("/shot-plans/{plan_id}/handoff.srt", response_class=PlainTextResponse)
def get_srt(plan_id: str, target: str = Query("generic"),
            db: Session = Depends(get_db)) -> PlainTextResponse:
    data = hf.build_handoff(db, _plan(plan_id, db), target=target)
    return PlainTextResponse(hf.to_srt(data), media_type="text/plain; charset=utf-8")


@router.get("/shot-plans/{plan_id}/handoff.csv", response_class=PlainTextResponse)
def get_csv(plan_id: str, target: str = Query("generic"),
            db: Session = Depends(get_db)) -> PlainTextResponse:
    data = hf.build_handoff(db, _plan(plan_id, db), target=target)
    # BOM 是给 Excel 的：没有它，中文列在 Windows 上打开是乱码，
    # 而这份表的用途正是拖进剪辑软件之前先用表格核一遍
    return PlainTextResponse("﻿" + hf.to_csv(data),
                             media_type="text/csv; charset=utf-8")


@router.get("/shot-plans/{plan_id}/handoff.md", response_class=PlainTextResponse)
def get_markdown(plan_id: str, target: str = Query("generic"),
                 db: Session = Depends(get_db)) -> PlainTextResponse:
    data = hf.build_handoff(db, _plan(plan_id, db), target=target)
    return PlainTextResponse(hf.to_markdown(data),
                             media_type="text/markdown; charset=utf-8")


# ── 手搓产物回传 ─────────────────────────────────────────────────────────────
#
# **这一段原来是断的。** 导出有了（handoff.md／csv／srt 三种），
# 而人在网页上生成完图和视频之后，没有任何一处能把它们送回系统 ——
# 整个系统唯一的上传入口是导入章节文本。于是「手动模式」只走通了一半：
# 提示词拿得出去，成品回不来，回不来就合不成片。
#
# 命名约定是这个闭环的关键：导出时就写清每张该叫什么，
# 回传时按文件名认领。人不必在界面上逐个点一百多次。

#: 文件名 → (镜号, 角色)。三种写法都收 —— 人从网页下载下来的文件
#: 名字五花八门，强求一种写法等于逼人手工改一百多个文件名
_UPLOAD_NAME = re.compile(
    r"(?:shot[_-]?)?(\d{1,4})[_-]?(first|last|video|f|l|v)?\b", re.I)
_ROLE_ALIAS = {"f": "first", "l": "last", "v": "video",
               "first": "first", "last": "last", "video": "video"}


def parse_upload_name(filename: str) -> tuple[int, str] | None:
    """从文件名认领镜号与角色。认不出返回 None。

    收这几种：
      12_first.png / shot012-last.jpg / 12.mp4 / shot_12_v.mp4
    认不出的**不猜**，报回去让人自己指定 —— 猜错会把一张图挂到别的镜头上，
    而那一镜从此再也没人会去看它对不对。
    """
    stem = filename.rsplit("/", 1)[-1].rsplit(".", 1)[0]
    m = _UPLOAD_NAME.search(stem)
    if not m:
        return None
    order = int(m.group(1))
    role = _ROLE_ALIAS.get((m.group(2) or "").lower(), "")
    if not role:
        # 没写角色时按扩展名猜：视频只可能是成片，图默认首帧
        ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
        role = "video" if ext in {"mp4", "mov", "webm", "m4v"} else "first"
    return order, role


def _attach_upload(
    db: Session, plan: ShotPlan, order_no: int, role: str,
    raw: bytes, filename: str,
) -> dict:
    """把一份手搓产物挂到对应的镜头上。"""
    from app.capability.mediastore import store_bytes
    from app.models import Asset, AssetKind, AssetSource, FrameRole, FrameSpec, Shot

    shot = db.execute(
        select(Shot).where(Shot.shot_plan_id == plan.id,
                           Shot.order_no == order_no)
    ).scalars().first()
    if shot is None:
        return {"file": filename, "ok": False, "why": f"这一版分镜里没有第 {order_no} 镜"}

    is_video = role == "video"
    mime = ("video/mp4" if is_video
            else ("image/jpeg" if filename.lower().endswith((".jpg", ".jpeg"))
                  else "image/png"))
    item = store_bytes(raw, mime=mime)
    asset = db.execute(
        select(Asset).where(Asset.sha256 == item.get("sha256"))
    ).scalars().first()
    if asset is None:
        asset = Asset(
            id=new_id("as"),
            kind=AssetKind.video if is_video else AssetKind.image,
            url=item["url"], sha256=item.get("sha256"), mime=item.get("mime"),
            bytes=item.get("bytes"),
            # **uploaded，不是 generated。** 来路要分得清 ——
            # 重跑生成时不能把人手搓的产物当成自己的旧产物覆盖掉
            source=AssetSource.uploaded,
            meta_json={"uploaded_as": filename, "shot": order_no, "role": role},
        )
        db.add(asset)
        db.flush()

    if is_video:
        shot.video_asset_id = asset.id
        shot.status = SpecStatus.ready
    else:
        frame = db.execute(
            select(FrameSpec).where(
                FrameSpec.shot_id == shot.id,
                FrameSpec.role == (FrameRole.last if role == "last"
                                   else FrameRole.first),
            )
        ).scalars().first()
        if frame is None:
            return {"file": filename, "ok": False,
                    "why": f"第 {order_no} 镜没有 {role} 帧的规格，先跑一次绑定拼装"}
        frame.asset_id = asset.id
        frame.status = SpecStatus.ready
        # 人手搓的不该被下一次自动生成覆盖
        frame.edited_by_human = True
        frame.gen_task_id = None
        frame.params_json = {**(frame.params_json or {}), "needs_regeneration": False}
    db.flush()
    return {"file": filename, "ok": True, "shot": order_no, "role": role,
            "url": asset.url}


@router.post("/shot-plans/{plan_id}/handoff:upload")
async def upload_handoff(
    plan_id: str,
    files: list[UploadFile] = File(...),
    db: Session = Depends(get_db),
) -> dict:
    """把网页上生成好的首尾帧／成片批量传回来，按文件名认领镜头。

    命名：`12_first.png`、`shot012-last.jpg`、`12.mp4` 都收。
    认不出的**不猜**，原样报回去 —— 猜错会把一张图挂到别的镜头上，
    而那一镜从此再也没人会去看它对不对。

    传回来的产物标 source=uploaded 且 edited_by_human，
    重跑自动生成时不会被覆盖。
    """
    plan = _plan(plan_id, db)
    done, failed = [], []
    for f in files:
        raw = await f.read()
        if not raw:
            failed.append({"file": f.filename, "ok": False, "why": "空文件"})
            continue
        parsed = parse_upload_name(f.filename or "")
        if parsed is None:
            failed.append({"file": f.filename, "ok": False,
                           "why": "文件名里认不出镜号。请用 12_first.png 这样的写法"})
            continue
        res = _attach_upload(db, plan, parsed[0], parsed[1], raw, f.filename or "")
        (done if res["ok"] else failed).append(res)
    db.flush()
    return {"attached": len(done), "failed": len(failed),
            "items": done, "problems": failed}


@router.post("/shot-plans/{plan_id}/audio/{audio_id}:upload")
async def upload_audio(plan_id: str, audio_id: str, file: UploadFile = File(...),
                       db: Session = Depends(get_db)) -> dict:
    """Attach a specific voice/cue; inspect real duration before altering the spec."""
    import json
    import subprocess
    import tempfile
    from pathlib import Path
    from app.models import AudioSpec, Shot, Asset, AssetKind, AssetSource
    from app.capability.mediastore import store_bytes
    _plan(plan_id, db)
    spec = db.get(AudioSpec, audio_id)
    shots = list(db.execute(select(Shot).where(Shot.shot_plan_id == plan_id)).scalars())
    if spec is None or not (
        spec.shot_id in {s.id for s in shots} or
        (not spec.shot_id and spec.scene_id in {s.scene_id for s in shots if s.scene_id})
    ):
        raise HTTPException(404, "audio spec not in this plan")
    raw = await file.read()
    suffix = Path(file.filename or "").suffix.lower()
    mime = {".wav": "audio/wav", ".mp3": "audio/mpeg", ".m4a": "audio/mp4",
            ".ogg": "audio/ogg"}.get(suffix)
    if not raw or not mime:
        raise HTTPException(422, "请上传 WAV、MP3、M4A 或 OGG 音频")
    try:
        with tempfile.NamedTemporaryFile(suffix=suffix) as tmp:
            tmp.write(raw); tmp.flush()
            info = json.loads(subprocess.check_output([
                "ffprobe", "-v", "error", "-show_streams", "-show_format",
                "-of", "json", tmp.name], timeout=30))
        if not any(s.get("codec_type") == "audio" for s in info.get("streams", [])):
            raise ValueError("no audio stream")
        duration = round(float(info["format"]["duration"]) * 1000)
        if duration <= 0:
            raise ValueError("invalid duration")
    except (OSError, ValueError, KeyError, subprocess.SubprocessError) as exc:
        raise HTTPException(422, "无法验证音频及其时长，请检查文件和 ffprobe") from exc
    item = store_bytes(raw, mime=mime)
    asset = db.execute(select(Asset).where(Asset.sha256 == item["sha256"])).scalars().first()
    if asset is None:
        asset = Asset(id=new_id("as"), kind=AssetKind.audio, source=AssetSource.uploaded,
                      url=item["url"], sha256=item["sha256"], mime=item["mime"],
                      bytes=item["bytes"], meta_json={"duration_ms": duration})
        db.add(asset); db.flush()
    spec.asset_id = asset.id
    spec.duration_ms = duration
    spec.timestamps_json = None
    spec.gen_task_id = None
    spec.status = SpecStatus.ready
    spec.params_json = {**(spec.params_json or {}), "manual_upload": True,
                        "stale_audio": False}
    db.flush()
    return {"id": spec.id, "url": asset.url, "duration_ms": duration}
