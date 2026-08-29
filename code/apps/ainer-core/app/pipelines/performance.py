"""表演抽取：从原文抽出「这一刻画面里发生什么」。

抽的是**瞬时状态**，不是恒定属性。区别很实：
    恒定  沈砚身量瘦高，一道旧疤在左眉        → world_entities.appearance
    瞬时  沈砚坐在门后，腰刀横在膝上，没点灯  → shot_performance

混在一起的后果是「他握紧了剑」会污染角色基础素材，下一镜他明明松了手，
生成出来还是攥着的。所以分开存，首帧提示词把两者拼起来用。

抽取分两步，依据不同：
    对话指向  在剧本块上做 —— 谁对谁说、还有谁在场，是文本层的事实
    表演      在镜头上做 —— 一个镜头可能覆盖多个块，站位要按镜头统一
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ids import new_id
from app.models import (
    Chapter, DocStatus, Facing, ScriptBlock, ScriptDoc, Shot, ShotPerformance,
    ShotPlan, SpeechRole, StagePosition, WorldEntity,
)
from app.pipelines.base import PipelineError, chat_json, as_text

log = logging.getLogger(__name__)

# ── 第一步：对话指向 ──────────────────────────────────────────────────────────

DIALOG_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["blocks"],
    "properties": {
        "blocks": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["block_id", "present"],
                "properties": {
                    "block_id": {"type": "string"},
                    "speaker": {"type": "string"},
                    "addressees": {"type": "array", "items": {"type": "string"}},
                    "present": {"type": "array", "items": {"type": "string"}},
                    "note": {"type": "string"},
                },
            },
        }
    },
}

DIALOG_SYSTEM = """你要标注每个段落的**对话关系与在场人物**。

对每个段落给三件事：
  speaker     谁在说。叙述段落留空。
  addressees  这句话是对谁说的。可以多人（对全场说），也可以为空（自言自语）。
  present     这一刻**在场的全部角色**，包括不说话的、只是站在旁边的。

为什么 present 不能省：一段三人对话，如果只记说话的两个，
分镜会切成两人对切，第三个人凭空消失 —— 而他可能正是这段戏的重点
（沉默的那个人往往才是被看的那个）。

判断在场靠上下文：某人进过场且没有明确离开，就仍在场。
只被提及、并不在现场的人不要算（「他说起当年的师父」——师父不在场）。

用原文里的称呼填，不要改写。判断不出的留空，不要编。"""


@dataclass
class DialogResult:
    blocks: int = 0
    with_addressee: int = 0
    max_present: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {"blocks": self.blocks, "with_addressee": self.with_addressee,
                "max_present": self.max_present}


def _blocks_of(db: Session, chapter: Chapter) -> list[ScriptBlock]:
    doc = db.execute(
        select(ScriptDoc).where(
            ScriptDoc.chapter_id == chapter.id, ScriptDoc.status == DocStatus.active
        )
    ).scalars().first()
    if doc is None:
        raise PipelineError("该章节还没有 active 剧本")
    return list(
        db.execute(
            select(ScriptBlock).where(ScriptBlock.script_doc_id == doc.id)
            .order_by(ScriptBlock.seq_no)
        ).scalars()
    )


def resolve_dialogue(
    db: Session, chapter: Chapter, *, batch_size: int = 20
) -> DialogResult:
    """标注对话指向与在场人物。

    分批时**带上前一批的尾部**：在场判断依赖上文（谁进过场、谁走了），
    切断上下文会让每批的第一个段落都判成「只有说话人在场」。
    """
    blocks = _blocks_of(db, chapter)
    if not blocks:
        raise PipelineError("章节没有正文")

    names = sorted({
        e.display_name for e in db.execute(
            select(WorldEntity).where(WorldEntity.novel_id == chapter.novel_id)
        ).scalars()
    })
    result = DialogResult()
    by_id = {b.id: b for b in blocks}

    for i in range(0, len(blocks), batch_size):
        batch = blocks[i : i + batch_size]
        # 回看 4 块作为上下文，只标注本批
        lookback = blocks[max(0, i - 4) : i]
        payload = {
            "context": [
                {"block_id": b.id, "speaker": b.speaker_tag, "text": b.source_text}
                for b in lookback
            ],
            "annotate": [
                {"block_id": b.id, "type": b.block_type.value,
                 "speaker": b.speaker_tag, "text": b.source_text}
                for b in batch
            ],
        }
        data, _ = chat_json(
            db,
            [
                {"role": "system", "content": DIALOG_SYSTEM},
                {"role": "user", "content": (
                    (f"【已知角色】{', '.join(names)}\n\n" if names else "")
                    + "context 只是上文，不要标注；只标注 annotate 里的段落。\n\n"
                    + json.dumps(payload, ensure_ascii=False, indent=1)
                )},
            ],
            DIALOG_SCHEMA,
            purpose="speakers",
            novel_id=chapter.novel_id, chapter_id=chapter.id,
            ref_kind="dialogue", ref_id=chapter.id,
        )
        for item in data.get("blocks") or []:
            b = by_id.get(str(item.get("block_id") or ""))
            if b is None:
                continue
            addr = [str(x).strip() for x in (item.get("addressees") or []) if str(x).strip()]
            present = [str(x).strip() for x in (item.get("present") or []) if str(x).strip()]
            # 说话人必然在场。模型偶尔漏掉，补上比信它更省事
            spk = (item.get("speaker") or b.speaker_tag or "").strip()
            if spk and spk not in present:
                present.append(spk)
            if spk and not b.speaker_tag:
                b.speaker_tag = spk[:128]
            b.addressee_tags = addr or None
            b.present_tags = present or None
            result.blocks += 1
            if addr:
                result.with_addressee += 1
            result.max_present = max(result.max_present, len(present))

    db.flush()
    return result


# ── 第二步：表演 ──────────────────────────────────────────────────────────────

PERF_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["shots"],
    "properties": {
        "shots": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["shot_id", "cast"],
                "properties": {
                    "shot_id": {"type": "string"},
                    "cast": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "required": ["entity", "speech_role", "position"],
                            "properties": {
                                "entity": {"type": "string"},
                                "speech_role": {
                                    "type": "string",
                                    "enum": [r.value for r in SpeechRole],
                                },
                                "position": {
                                    "type": "string",
                                    "enum": [p.value for p in StagePosition],
                                },
                                "facing": {
                                    "type": "string",
                                    "enum": [f.value for f in Facing],
                                },
                                "gaze_target": {"type": "string"},
                                "expression": {"type": "string"},
                                "expression_end": {"type": "string"},
                                "action": {"type": "string"},
                                "action_end": {"type": "string"},
                                "props": {"type": "array", "items": {"type": "string"}},
                            },
                        },
                    },
                },
            },
        }
    },
}

PERF_SYSTEM = """你要为每个镜头标注**这一刻画面里发生什么**。

给每个在场角色标：
  speech_role  speaker 正在说／addressee 被对着说／listener 在场旁听／
               silent 在场但与这段无关／absent 被提及但不在场
  position     画面站位：far_left…far_right、foreground 前景、
               background 背景深处、offscreen 在场但不入画
  facing       朝向：to_camera 正脸／away 背影／profile_left|right 侧脸／
               three_quarter 四分之三侧
  gaze_target  看向谁或什么。**两个人对视时视线必须相向** ——
               一个看左一个也看左，观众会觉得他们没在交流。
  expression / expression_end   首帧与尾帧的表情
  action / action_end           首帧与尾帧的动作
  props        手上或身上的关键道具

三条硬要求：

1. **首尾必须不同，否则这一镜没有表演。**
   expression 和 expression_end 一样、action 和 action_end 一样，
   生成出来就是两张静止的画。首尾之差就是这一镜的运动。
   确实静止的镜头（空镜、定场）可以相同，但对话镜头几乎不会。

2. **站位要跨镜连贯。** 同一场戏里，A 在左 B 在右，
   下一镜不能变成 A 在右 —— 那是穿帮，观众会立刻出戏。
   除非中间有明确的走位动作，那就把它写进 action。

3. **只写原文支持的。** 原文没写表情就根据情境合理推断，
   但不要编出原文明确否定的东西（原文说「面无表情」就不要给他一个微笑）。

position 用九宫格而不是坐标：坐标在不同画幅下无意义，
九宫格能直接变成提示词里的一句话。"""


@dataclass
class PerfResult:
    shots: int = 0
    performances: int = 0
    static_shots: list[dict] = field(default_factory=list)
    position_jumps: list[dict] = field(default_factory=list)
    unresolved: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "shots": self.shots, "performances": self.performances,
            "static_shots": self.static_shots,
            "position_jumps": self.position_jumps,
            "unresolved": self.unresolved,
        }


def extract_performance(
    db: Session, plan: ShotPlan, *, batch_size: int = 6
) -> PerfResult:
    """为一个分镜计划的每个镜头抽表演信息。"""
    shots = list(
        db.execute(
            select(Shot).where(Shot.shot_plan_id == plan.id).order_by(Shot.order_no)
        ).scalars()
    )
    if not shots:
        raise PipelineError("该分镜计划下没有镜头")

    doc = db.get(ScriptDoc, plan.script_doc_id)
    chapter = db.get(Chapter, doc.chapter_id) if doc else None
    if chapter is None:
        raise PipelineError("分镜对应的章节不存在")

    entities = list(
        db.execute(
            select(WorldEntity).where(WorldEntity.novel_id == chapter.novel_id)
        ).scalars()
    )
    # 名字 → 实体。别名一并收，模型用原文称呼填
    by_name: dict[str, WorldEntity] = {}
    for e in entities:
        for n in [e.display_name, *(e.aliases_json or [])]:
            if n:
                by_name.setdefault(str(n), e)

    blocks = {b.id: b for b in _blocks_of(db, chapter)}
    existing = {
        (p.shot_id, p.entity_id): p
        for p in db.execute(
            select(ShotPerformance).where(
                ShotPerformance.shot_id.in_([s.id for s in shots])
            )
        ).scalars()
    }

    result = PerfResult(shots=len(shots))
    #: 上一镜每个角色的站位，用于跳变检测
    last_pos: dict[str, StagePosition] = {}

    for i in range(0, len(shots), batch_size):
        batch = shots[i : i + batch_size]
        payload = []
        for s in batch:
            texts = [
                blocks[bid].source_text for bid in (s.block_ids_json or [])
                if bid in blocks
            ]
            present: list[str] = []
            for bid in (s.block_ids_json or []):
                for n in (blocks[bid].present_tags or []) if bid in blocks else []:
                    if n not in present:
                        present.append(n)
            payload.append({
                "shot_id": s.id, "order": s.order_no,
                "shot_size": s.shot_size, "duration_ms": s.duration_ms,
                "description": s.description,
                "present": present,
                "text": "\n".join(texts)[:1200],
            })
        data, _ = chat_json(
            db,
            [
                {"role": "system", "content": PERF_SYSTEM},
                {"role": "user", "content": (
                    f"【角色表】{', '.join(sorted(by_name))}\n\n"
                    + json.dumps({"shots": payload}, ensure_ascii=False, indent=1)
                )},
            ],
            PERF_SCHEMA,
            purpose="shot_plan",
            novel_id=chapter.novel_id, chapter_id=chapter.id,
            ref_kind="performance", ref_id=plan.id,
        )
        _absorb(db, data.get("shots") or [], batch, by_name, existing,
                last_pos, result)

    db.flush()
    return result


def is_position_jump(
    prev: StagePosition | None, cur: StagePosition, *, moved: bool
) -> bool:
    """同一角色在相邻镜之间的站位是否跳变。

    跳变 = 位置变了，但这一镜里没有走位动作来解释它。
    动画放到这里，人会凭空出现在画面另一边 —— 观众立刻出戏。

    两种情况不算跳变：
      画外进出   offscreen ↔ 任意位置是正常的入画出画，不是跳变
      有走位     action 与 action_end 不同说明这一镜里人在动，位置变了合理
    """
    if prev is None or prev is cur:
        return False
    if StagePosition.offscreen in (prev, cur):
        return False
    return not moved


def _absorb(
    db: Session, items: list[dict], batch: list[Shot],
    by_name: dict[str, WorldEntity],
    existing: dict[tuple[str, str], ShotPerformance],
    last_pos: dict[str, StagePosition], result: PerfResult,
) -> None:
    valid = {s.id: s for s in batch}
    for item in items:
        shot = valid.get(str(item.get("shot_id") or ""))
        if shot is None:
            continue
        static_all = True
        for c in item.get("cast") or []:
            name = as_text(c.get("entity"))
            entity = by_name.get(name)
            if entity is None:
                if name and name not in result.unresolved:
                    result.unresolved.append(name)
                continue
            try:
                role = SpeechRole(c.get("speech_role") or "listener")
                pos = StagePosition(c.get("position") or "center")
            except ValueError:
                role, pos = SpeechRole.listener, StagePosition.center
            try:
                facing = Facing(c.get("facing") or "three_quarter")
            except ValueError:
                facing = Facing.three_quarter

            row = existing.get((shot.id, entity.id))
            if row is None:
                row = ShotPerformance(
                    id=new_id("sp"), shot_id=shot.id, entity_id=entity.id
                )
                db.add(row)
                existing[(shot.id, entity.id)] = row
            elif row.edited_by_human:
                continue

            row.speech_role = role
            row.position = pos
            row.facing = facing
            row.gaze_target = as_text(c.get("gaze_target"))[:128] or None
            row.expression = as_text(c.get("expression"))[:128] or None
            row.expression_end = as_text(c.get("expression_end"))[:128] or None
            row.action = as_text(c.get("action"))[:2000] or None
            row.action_end = as_text(c.get("action_end"))[:2000] or None
            row.props_json = [
                str(x).strip() for x in (c.get("props") or []) if str(x).strip()
            ] or None

            # 站位跳变：同一角色相邻镜位置突变且动作里没写走位
            prev = last_pos.get(entity.id)
            moved = bool(row.action_end and row.action_end != row.action)
            jumped = is_position_jump(prev, pos, moved=moved)
            row.position_jump = jumped
            if jumped:
                result.position_jumps.append({
                    "shot": shot.order_no, "entity": entity.display_name,
                    "from": prev.value, "to": pos.value,
                })
            if pos is not StagePosition.offscreen:
                last_pos[entity.id] = pos

            if (row.expression != row.expression_end) or (row.action != row.action_end):
                static_all = False
            result.performances += 1

        if static_all and (item.get("cast") or []):
            result.static_shots.append({
                "shot": shot.order_no,
                "note": "首尾表情与动作完全相同 —— 生成出来会是两张静止的画",
            })


def build_frame_brief(db: Session, shot: Shot) -> str:
    """把一个镜头的表演拼成提示词片段，供首/尾帧组装调用。

    恒定属性（外貌、服装）由素材包提供，这里只给瞬时状态 ——
    两者在提示词里拼接，各自可独立重跑而不互相污染。
    """
    rows = list(
        db.execute(
            select(ShotPerformance, WorldEntity)
            .join(WorldEntity, WorldEntity.id == ShotPerformance.entity_id)
            .where(ShotPerformance.shot_id == shot.id)
        )
    )
    if not rows:
        return ""
    pos_cn = {
        StagePosition.far_left: "画面最左", StagePosition.left: "画面左侧",
        StagePosition.center_left: "中偏左", StagePosition.center: "画面中央",
        StagePosition.center_right: "中偏右", StagePosition.right: "画面右侧",
        StagePosition.far_right: "画面最右", StagePosition.foreground: "前景",
        StagePosition.background: "背景深处", StagePosition.offscreen: "画外",
    }
    facing_cn = {
        Facing.to_camera: "正对镜头", Facing.away: "背对镜头",
        Facing.profile_left: "左侧脸", Facing.profile_right: "右侧脸",
        Facing.three_quarter: "四分之三侧",
    }
    lines = []
    for p, e in rows:
        if p.position is StagePosition.offscreen:
            continue
        bits = [f"{e.display_name}：{pos_cn[p.position]}，{facing_cn[p.facing]}"]
        if p.expression:
            bits.append(f"表情 {p.expression}")
        if p.action:
            bits.append(f"动作 {p.action}")
        if p.gaze_target:
            bits.append(f"看向 {p.gaze_target}")
        if p.props_json:
            bits.append(f"持 {'、'.join(p.props_json)}")
        lines.append("  " + "；".join(bits))
    return "【人物调度】\n" + "\n".join(lines) if lines else ""
