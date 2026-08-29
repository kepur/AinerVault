"""源圈层归属 —— 这一场戏属于哪个世界。

## 为什么需要它

多数小说只有一个源圈层，这一层用不上。但有一类小说不是：

    穿越      前一场在唐代长安，后一场在当代写字楼
    双线      一条线在战场，一条线在三十年后的法庭
    梦境／回忆 现实与幻境交替

它们的问题不是「翻译难」，是**同一个词在两个世界里不是一个意思**：

    先生   古代场 = 老师      现代场 = Mr.
    大人   古代场 = my lord   现代场 = adult
    一里   古代场 = 500 米    现代场 = 500 米（但读者的直觉不同）

靠 (映射, 源词) 唯一是分不开的：后写的覆盖先写的，
而覆盖掉哪一个取决于挖掘顺序 —— **两次跑可能译出两个词**。

所以词表条目要能挂源圈层，而查词表时要知道「当前这段属于哪个世界」。
后者就是这一层：给每一场戏定一个源圈层。

## 为什么按场而不是按章

穿越的切换点**就是场景切换**：一场戏不会横跨两个世界，
而一章里可以来回切好几次。按章定会让整章用同一套词表，
切换后的那半章全错。

## 只在真有多个源圈层时才跑

单圈层的小说跑这一步是纯浪费 —— 每一场都会得到同一个答案。
所以入口先看 transform 有没有配额外源圈层，没有就直接返回。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    Chapter, Scene, ScriptBlock, ScriptDoc, WorldProfile, WorldTransform,
)
from app.pipelines.base import PipelineError, as_items, as_text, chat_json

log = logging.getLogger(__name__)

ASSIGN_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["scenes"],
    "properties": {
        "scenes": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["scene_id", "profile_code", "evidence"],
                "properties": {
                    "scene_id": {"type": "string"},
                    "profile_code": {"type": "string"},
                    "evidence": {"type": "string"},
                    "uncertain": {"type": "boolean"},
                },
            },
        }
    },
}

ASSIGN_SYSTEM = """这本小说横跨多个世界（穿越／双线／梦境）。
你要判断每一场戏发生在**哪一个**。

判断依据是场景里的**实物与制度**，不是语气：

  ✓ 出现了手机、公司、地铁、身份证 → 现代
  ✓ 出现了衙门、马车、铜钱、科举 → 古代
  ✓ 人物的身份称谓（「陛下」vs「老板」）
  ✓ 度量与货币（「三两银子」vs「三百块」）

  ✗ 「语气比较文雅所以是古代」—— 现代人也可以说文雅的话
  ✗ 「气氛紧张所以是战场」—— 气氛不是世界

**拿不准就标 uncertain=true，不要猜。** 猜错的后果是整场戏用错词表：
现代场里的「先生」被译成 teacher，而那一场里他是个 Mr.。
标了不确定的场会回落到主源圈层，且会报出来让人看一眼 ——
漏判可以补，错判会一路传到译文里，且沿途没有任何一处会报错。

evidence 引用场景里那个决定性的实物或制度，一句话。
不要写「根据上下文判断」—— 那不是证据。"""


@dataclass
class AssignResult:
    scenes: int = 0
    assigned: int = 0
    uncertain: list[dict[str, Any]] = field(default_factory=list)
    by_profile: dict[str, int] = field(default_factory=dict)
    skipped_single: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "scenes": self.scenes, "assigned": self.assigned,
            "uncertain": self.uncertain, "by_profile": self.by_profile,
            "skipped_single": self.skipped_single,
        }


def source_profiles(db: Session, transform: WorldTransform) -> list[WorldProfile]:
    """这次映射涉及的全部源圈层，主源在前。"""
    ids = [transform.source_profile_id]
    ids += [str(x) for x in (transform.extra_source_profiles_json or [])
            if str(x) != transform.source_profile_id]
    rows = {
        p.id: p for p in db.execute(
            select(WorldProfile).where(WorldProfile.id.in_(ids))
        ).scalars()
    }
    return [rows[i] for i in ids if i in rows]


def profile_for_block(
    db: Session, transform: WorldTransform, block: ScriptBlock,
) -> str | None:
    """这一段文本属于哪个源圈层。

    查词表时用它消歧。场没标就回落到主源圈层 ——
    **不能返回 None**：None 的语义是「只用通用条目」，
    而那会把所有挂了圈层的条目全部排除掉，等于词表突然少了一半。
    """
    if block.scene_id:
        scene = db.get(Scene, block.scene_id)
        if scene is not None and scene.source_profile_id:
            return scene.source_profile_id
    return transform.source_profile_id


def assign_scenes(
    db: Session, transform: WorldTransform, chapter: Chapter, *,
    force: bool = False,
) -> AssignResult:
    """给一章里的每一场戏定源圈层。"""
    profiles = source_profiles(db, transform)
    result = AssignResult()
    if len(profiles) < 2:
        # 单圈层的小说跑这一步是纯浪费 —— 每一场都会得到同一个答案
        result.skipped_single = True
        return result

    doc = db.execute(
        select(ScriptDoc).where(ScriptDoc.chapter_id == chapter.id)
        .order_by(ScriptDoc.version.desc())
    ).scalars().first()
    if doc is None:
        raise PipelineError("该章节还没有剧本，先跑一次剧本转换")

    scenes = list(db.execute(
        select(Scene).where(Scene.script_doc_id == doc.id)
        .order_by(Scene.order_no)
    ).scalars())
    if not scenes:
        raise PipelineError(
            "该章节没有分场 —— 源圈层是按场判的，"
            "散文线的分块没有场次信息。先跑剧本转换（script:generate）")
    result.scenes = len(scenes)

    todo = [s for s in scenes if force or not s.source_profile_id]
    if not todo:
        return result

    blocks: dict[str, list[ScriptBlock]] = {}
    for b in db.execute(
        select(ScriptBlock).where(ScriptBlock.script_doc_id == doc.id)
        .order_by(ScriptBlock.seq_no)
    ).scalars():
        if b.scene_id:
            blocks.setdefault(b.scene_id, []).append(b)

    roster = "\n".join(
        f"  {p.code}｜{p.display_name}"
        + (f"（{(p.axes_json or {}).get('era_span') or ''} "
           f"{(p.axes_json or {}).get('social_context') or ''}）")
        for p in profiles
    )
    by_code = {p.code: p.id for p in profiles}

    payload = []
    for s in todo:
        text = "".join(b.source_text or "" for b in blocks.get(s.id, []))[:700]
        payload.append({
            "scene_id": s.id, "title": s.title or "",
            "location": s.location_text or "", "text": text,
        })

    data, _task = chat_json(
        db,
        [{"role": "system", "content": ASSIGN_SYSTEM},
         {"role": "user", "content":
          f"【可选的源圈层】\n{roster}\n\n【场次】\n"
          + "\n".join(
              f"[{p['scene_id']}] {p['title']}｜{p['location']}\n  {p['text']}"
              for p in payload)}],
        ASSIGN_SCHEMA, purpose="extract", novel_id=chapter.novel_id,
        chapter_id=chapter.id, ref_kind="source_world", ref_id=chapter.id,
        max_tokens=4096,
    )

    valid = {s.id: s for s in todo}
    for item in as_items(data, "scenes"):
        sid = as_text(item.get("scene_id")).strip()
        scene = valid.get(sid)
        if scene is None:
            continue
        code = as_text(item.get("profile_code")).strip()
        pid = by_code.get(code)
        if item.get("uncertain") or not pid:
            # 拿不准的回落到主源圈层，并报出来 ——
            # 静默回落的话，一场用错词表的戏会一路走到译文，没人知道
            result.uncertain.append({
                "scene": scene.title or scene.id,
                "said": code or "（没给）",
                "evidence": as_text(item.get("evidence"))[:120],
            })
            continue
        scene.source_profile_id = pid
        result.assigned += 1
        result.by_profile[code] = result.by_profile.get(code, 0) + 1

    db.flush()
    return result
