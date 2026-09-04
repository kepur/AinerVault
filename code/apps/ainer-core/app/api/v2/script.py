"""剧本 API。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.ids import new_id
from app.models import (
    BlockType, Chapter, DocMode, DocStatus, Scene, ScriptBlock, ScriptDoc,
    WorldTransform,
)
from app.pipelines.base import PipelineError
from app.pipelines.script_build import build_script, count_human_edits

router = APIRouter(prefix="/api/v2", tags=["script"])


class GenerateIn(BaseModel):
    mode: str = "full"
    keep_human_edits: bool = True
    scene_granularity: str = "medium"
    model: str | None = None
    confirm_discard_edits: bool = False
    #: 给了映射就必须从该映射的已锁定译本生成目标世界剧本。
    #: 不给时仍允许源语言剧本，服务原语言制作。
    transform_id: str | None = None


class SceneIn(BaseModel):
    title: str | None = None
    time_of_day: str | None = None
    location_text: str | None = None
    weather: str | None = None
    mood: str | None = None
    summary: str | None = None


class BlockIn(BaseModel):
    block_type: str | None = None
    source_text: str | None = None
    speaker_tag: str | None = None
    speaker_entity_id: str | None = None


def _doc_payload(db: Session, doc: ScriptDoc) -> dict:
    scenes = db.execute(
        select(Scene).where(Scene.script_doc_id == doc.id).order_by(Scene.order_no)
    ).scalars().all()
    blocks = db.execute(
        select(ScriptBlock)
        .where(ScriptBlock.script_doc_id == doc.id)
        .order_by(ScriptBlock.seq_no)
    ).scalars().all()

    by_scene: dict[str | None, list[ScriptBlock]] = {}
    for b in blocks:
        by_scene.setdefault(b.scene_id, []).append(b)

    return {
        "id": doc.id,
        "chapter_id": doc.chapter_id,
        "version": doc.version,
        "status": doc.status.value,
        "stats": doc.stats_json or {},
        "generator_meta": doc.generator_meta or {},
        "scenes": [
            {
                "id": s.id, "order_no": s.order_no, "title": s.title,
                "time_of_day": s.time_of_day, "location_text": s.location_text,
                "weather": s.weather, "mood": s.mood, "summary": s.summary,
                "bg_asset_id": s.bg_asset_id, "bgm_asset_id": s.bgm_asset_id,
                "edited_by_human": s.edited_by_human,
                "blocks": [
                    {
                        "id": b.id, "seq_no": b.seq_no, "type": b.block_type.value,
                        "text": b.source_text, "speaker": b.speaker_tag,
                        "speaker_entity_id": b.speaker_entity_id,
                        "translatable": b.translatable,
                        "edited_by_human": b.edited_by_human,
                    }
                    for b in by_scene.get(s.id, [])
                ],
            }
            for s in scenes
        ],
    }


def _get_chapter(db: Session, chapter_id: str) -> Chapter:
    c = db.get(Chapter, chapter_id)
    if c is None:
        raise HTTPException(status_code=404, detail="chapter not found")
    return c


@router.get("/chapters/{chapter_id}/script")
def get_script(chapter_id: str, db: Session = Depends(get_db)) -> dict:
    _get_chapter(db, chapter_id)
    doc = db.execute(
        select(ScriptDoc)
        .where(
            ScriptDoc.chapter_id == chapter_id,
            ScriptDoc.doc_mode == DocMode.screenplay,
            ScriptDoc.status == DocStatus.active,
        )
    ).scalars().first()
    if doc is None:
        raise HTTPException(status_code=404, detail="该章节尚未生成剧本")
    return _doc_payload(db, doc)


@router.post("/chapters/{chapter_id}/script:generate")
def generate_script(
    chapter_id: str, body: GenerateIn, db: Session = Depends(get_db)
) -> dict:
    chapter = _get_chapter(db, chapter_id)

    # 人工编辑永不被静默覆盖
    if not body.keep_human_edits and not body.confirm_discard_edits:
        n = count_human_edits(db, chapter_id)
        if n:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "WOULD_DISCARD_EDITS",
                    "message": f"将丢弃 {n} 处人工编辑。确认请带 confirm_discard_edits=true。",
                    "count": n,
                },
            )
    try:
        transform = None
        if body.transform_id:
            transform = db.get(WorldTransform, body.transform_id)
            if transform is None or transform.novel_id != chapter.novel_id:
                raise HTTPException(status_code=404, detail="该小说下没有这个世界观映射")
        doc = build_script(
            db, chapter,
            transform=transform,
            granularity=body.scene_granularity,
            keep_human_edits=body.keep_human_edits,
        )
    except PipelineError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _doc_payload(db, doc)


@router.get("/chapters/{chapter_id}/script/versions")
def list_versions(chapter_id: str, db: Session = Depends(get_db)) -> list[dict]:
    _get_chapter(db, chapter_id)
    rows = db.execute(
        select(ScriptDoc)
        .where(ScriptDoc.chapter_id == chapter_id,
               ScriptDoc.doc_mode == DocMode.screenplay)
        .order_by(ScriptDoc.version.desc())
    ).scalars().all()
    return [
        {
            "id": d.id, "version": d.version, "status": d.status.value,
            "stats": d.stats_json or {}, "generator_meta": d.generator_meta or {},
            "created_at": d.created_at.isoformat(),
        }
        for d in rows
    ]


@router.post("/chapters/{chapter_id}/script/versions/{version}:activate")
def activate_version(
    chapter_id: str, version: int, db: Session = Depends(get_db)
) -> dict:
    _get_chapter(db, chapter_id)
    rows = db.execute(
        select(ScriptDoc).where(
            ScriptDoc.chapter_id == chapter_id,
            ScriptDoc.doc_mode == DocMode.screenplay,
        )
    ).scalars().all()
    target = next((d for d in rows if d.version == version), None)
    if target is None:
        raise HTTPException(status_code=404, detail=f"版本 v{version} 不存在")
    for d in rows:
        d.status = DocStatus.archived
    target.status = DocStatus.active
    db.flush()
    return _doc_payload(db, target)


# ── 场景与块的手工编辑 ─────────────────────────────────────────────────────────

@router.patch("/scenes/{scene_id}")
def update_scene(scene_id: str, body: SceneIn, db: Session = Depends(get_db)) -> dict:
    s = db.get(Scene, scene_id)
    if s is None:
        raise HTTPException(status_code=404, detail="scene not found")
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(s, k, v)
    s.edited_by_human = True
    db.flush()
    return {"id": s.id, "edited_by_human": True}


@router.patch("/blocks/{block_id}")
def update_block(block_id: str, body: BlockIn, db: Session = Depends(get_db)) -> dict:
    b = db.get(ScriptBlock, block_id)
    if b is None:
        raise HTTPException(status_code=404, detail="block not found")
    data = body.model_dump(exclude_unset=True)
    if "block_type" in data and data["block_type"]:
        try:
            b.block_type = BlockType(data["block_type"])
        except ValueError as exc:
            raise HTTPException(
                status_code=400,
                detail=f"未知块类型 {data['block_type']}，可选：{[t.value for t in BlockType]}",
            ) from exc
    if "source_text" in data and data["source_text"] is not None:
        b.source_text = data["source_text"]
    if "speaker_tag" in data:
        b.speaker_tag = data["speaker_tag"]
    if "speaker_entity_id" in data:
        b.speaker_entity_id = data["speaker_entity_id"]
    b.edited_by_human = True
    db.flush()
    return {
        "id": b.id, "type": b.block_type.value, "text": b.source_text,
        "speaker": b.speaker_tag, "translatable": b.translatable,
        "edited_by_human": True,
    }


class SplitIn(BaseModel):
    at: int   # 在原文的第 at 个字符处切分


@router.post("/blocks/{block_id}:split")
def split_block(block_id: str, body: SplitIn, db: Session = Depends(get_db)) -> dict:
    b = db.get(ScriptBlock, block_id)
    if b is None:
        raise HTTPException(status_code=404, detail="block not found")
    text = b.source_text
    if not 0 < body.at < len(text):
        raise HTTPException(status_code=400, detail=f"切分位置须在 1..{len(text) - 1}")

    head, tail = text[: body.at].strip(), text[body.at:].strip()
    if not head or not tail:
        raise HTTPException(status_code=400, detail="切分后不能产生空块")

    # 后续块序号统一后移
    later = db.execute(
        select(ScriptBlock)
        .where(ScriptBlock.script_doc_id == b.script_doc_id, ScriptBlock.seq_no > b.seq_no)
        .order_by(ScriptBlock.seq_no.desc())
    ).scalars().all()
    for x in later:
        x.seq_no += 1
    db.flush()

    b.source_text = head
    b.edited_by_human = True
    new_block = ScriptBlock(
        id=new_id("sb"), script_doc_id=b.script_doc_id, scene_id=b.scene_id,
        seq_no=b.seq_no + 1, block_type=b.block_type, source_text=tail,
        speaker_tag=b.speaker_tag, speaker_entity_id=b.speaker_entity_id,
        edited_by_human=True,
    )
    db.add(new_block)
    db.flush()
    return {"blocks": [
        {"id": b.id, "seq_no": b.seq_no, "text": b.source_text},
        {"id": new_block.id, "seq_no": new_block.seq_no, "text": new_block.source_text},
    ]}


class MergeIn(BaseModel):
    block_ids: list[str]
    separator: str = ""


@router.post("/blocks:merge")
def merge_blocks(body: MergeIn, db: Session = Depends(get_db)) -> dict:
    if len(body.block_ids) < 2:
        raise HTTPException(status_code=400, detail="至少选两个块")
    blocks = db.execute(
        select(ScriptBlock)
        .where(ScriptBlock.id.in_(body.block_ids))
        .order_by(ScriptBlock.seq_no)
    ).scalars().all()
    if len(blocks) != len(body.block_ids):
        raise HTTPException(status_code=404, detail="部分块不存在")
    docs = {b.script_doc_id for b in blocks}
    if len(docs) > 1:
        raise HTTPException(status_code=400, detail="不能跨剧本版本合并")

    head = blocks[0]
    head.source_text = body.separator.join(b.source_text for b in blocks)
    head.edited_by_human = True
    for b in blocks[1:]:
        db.delete(b)
    db.flush()

    # 重排剩余序号，保持连续
    remaining = db.execute(
        select(ScriptBlock)
        .where(ScriptBlock.script_doc_id == head.script_doc_id)
        .order_by(ScriptBlock.seq_no)
    ).scalars().all()
    for i, b in enumerate(remaining, start=1):
        b.seq_no = i
    db.flush()
    return {"id": head.id, "seq_no": head.seq_no, "text": head.source_text}
