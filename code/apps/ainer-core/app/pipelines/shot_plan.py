"""分镜编译：ScriptDoc + 导演包 → Shot + FrameSpec。

分工写死：
  规则负责风格分布  景别、运镜、切分密度由导演包的统计分布决定，不交给 LLM ——
                    交给 LLM 的话它会把每个镜头都写成中景平拍，分布立刻失控
  LLM 负责内容      哪几个 block 归一个镜头、镜头里发生什么、谁出场、
                    尾帧相对首帧变化了什么

时长由配音决定：这里给的是估算值，TTS 落地后回填真实时长。
"""
from __future__ import annotations

import logging
import random
from dataclasses import dataclass, field
from typing import Any, Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ids import new_id
from app.models import (
    Chapter, DirectorProfile, DocStatus, FrameRole, FrameSpec, Scene, ScriptBlock,
    ScriptDoc, Shot, ShotPlan, SpecStatus, TranslationBlock, WorldEntity,
    WorldTransform,
)
from app.models.script import BlockType
from app.worldview import resolve
from app.pipelines.base import PipelineError, as_text, chat_json, fingerprint

log = logging.getLogger(__name__)

#: 景别代码 → 给图像模型的说法
SHOT_SIZE_PROMPT: dict[str, str] = {
    "ecu": "extreme close-up",
    "cu": "close-up",
    "ms": "medium shot",
    "fs": "full shot",
    "ws": "wide shot",
    "els": "extreme long shot",
}

_MS_PER_CJK_CHAR = 210
_MS_PER_LATIN_WORD = 380

SHOT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["shots"],
    "properties": {
        "shots": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["order", "block_ids", "description",
                             "first_frame", "last_frame",
                             "first_frame_en", "last_frame_en"],
                "properties": {
                    "order": {"type": "integer"},
                    "block_ids": {"type": "array", "items": {"type": "string"}},
                    "description": {"type": "string"},
                    "entity_names": {"type": "array", "items": {"type": "string"}},
                    "asset_keys": {"type": "array", "items": {"type": "string"}},
                    "first_frame": {"type": "string"},
                    "last_frame": {"type": "string"},
                    "first_frame_en": {"type": "string"},
                    "last_frame_en": {"type": "string"},
                    "derive_instruction": {"type": "string"},
                },
            },
        }
    },
}

SHOT_SYSTEM = """你是分镜师。把剧本切成镜头，并为每个镜头写出首帧与尾帧的画面内容。

分工须知：景别、运镜、时长由系统按导演风格分配，**你不要指定这些**。
你只负责：怎么切、镜头里发生什么、谁出场、用到哪些素材、尾帧相对首帧变了什么。

要求：
1. block_ids 填该镜头覆盖的剧本块 id。相邻的、同一动作单元的块可以合成一个镜头；
   一个块也可以拆成多个镜头。所有块必须被覆盖，不能遗漏。
2. description 一句话说明镜头内容，中文，不要写景别与运镜。
3. entity_names 填出场人物的原文名。
4. asset_keys 填用到的素材 canonical_key（服装/道具/场景/氛围）。
5. first_frame 写首帧的画面内容：谁在哪、在做什么、什么状态。
   **只写内容，不写画风、不写材质细节** —— 那些由素材库提供。
6. last_frame 写尾帧的画面内容。

6b. first_frame_en / last_frame_en：把上面两句写成**英文**。
    **图像模型不认中文** —— 中文喂进去出来的是一整版汉字纹样，
    不是画面（实跑验证过）。这两句是直接拼进出图提示词的那一句。
    写成短语串，不要句子，不要出现人名（模型读不出人名是谁）：
      ✓ a man seated behind a door, sabre across his knees, eyes on the door gap
      ✗ Shen Yan sits behind the door and stares at the crack
    中文那两句是给人审核的，两份都要填。
7. derive_instruction 用一句话说明「尾帧相对首帧变了什么」，
   如「他已跨过门槛，侧身背对，雨更大了」。变化要小而明确 ——
   一个镜头内不应发生剧烈变化。"""


@dataclass
class ShotPlanResult:
    shot_plan_id: str = ""
    version: int = 0
    shots: int = 0
    scenes: int = 0
    total_duration_ms: int = 0
    size_distribution: dict[str, int] = field(default_factory=dict)
    move_distribution: dict[str, int] = field(default_factory=dict)
    uncovered_blocks: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "shot_plan_id": self.shot_plan_id, "version": self.version,
            "shots": self.shots, "scenes": self.scenes,
            "total_duration_ms": self.total_duration_ms,
            "size_distribution": self.size_distribution,
            "move_distribution": self.move_distribution,
            "uncovered_blocks": self.uncovered_blocks,
        }


class _Allocator:
    """按导演包的统计分布分配景别与运镜。

    用余额法而非独立随机：每次取当前欠得最多的那一档。
    独立随机在几十个镜头的小样本下会严重偏离目标分布 ——
    静观式导演可能一个固定镜头都没分到。
    """

    def __init__(self, distribution: dict[str, float], total: int, seed: int) -> None:
        self.total = max(total, 1)
        clean = {k: max(float(v), 0.0) for k, v in (distribution or {}).items()}
        s = sum(clean.values())
        self.target = {k: v / s for k, v in clean.items()} if s > 0 else {}
        self.issued: dict[str, int] = {k: 0 for k in self.target}
        self._rng = random.Random(seed)
        self._n = 0

    def take(self) -> str:
        if not self.target:
            return ""
        self._n += 1
        deficits = {
            k: self.target[k] * self._n - self.issued.get(k, 0) for k in self.target
        }
        best = max(deficits.values())
        candidates = [k for k, v in deficits.items() if abs(v - best) < 1e-9]
        pick = candidates[0] if len(candidates) == 1 else self._rng.choice(candidates)
        self.issued[pick] = self.issued.get(pick, 0) + 1
        return pick


def _text_duration_ms(text: str, is_cjk: bool = True) -> int:
    t = (text or "").strip()
    if not t:
        return 0
    if is_cjk:
        return len([c for c in t if not c.isspace()]) * _MS_PER_CJK_CHAR
    return max(len(t.split()), 1) * _MS_PER_LATIN_WORD


def _estimate_ms(
    db: Session, blocks: Sequence[ScriptBlock], lang: str | None,
    transform_id: str | None = None,
) -> int:
    """按配音估算时长。有译文用译文，没有用原文。动作块不配音但占画面时间。"""
    if not blocks:
        return 0
    trans: dict[str, str] = {}
    if transform_id:
        trans = {
            t.script_block_id: t.translated_text or ""
            for t in db.execute(
                select(TranslationBlock).where(
                    TranslationBlock.script_block_id.in_([b.id for b in blocks]),
                    TranslationBlock.transform_id == transform_id,
                )
            ).scalars()
        }
    is_cjk = not lang or lang[:2].lower() in {"zh", "ja", "ko"}
    total = 0
    for b in blocks:
        if b.block_type in {BlockType.scene_break, BlockType.action}:
            total += 1200
            continue
        total += _text_duration_ms(trans.get(b.id) or b.source_text or "", is_cjk)
    return total


def build_shot_plan(
    db: Session,
    script_doc: ScriptDoc,
    *,
    director: DirectorProfile,
    transform: WorldTransform | None = None,
    target_language: str | None = None,
    activate: bool = True,
    aspect_ratio: str = "16:9",
) -> ShotPlanResult:
    """编译分镜。规则定风格分布，LLM 定内容。"""
    chapter = db.get(Chapter, script_doc.chapter_id)
    if chapter is None:
        raise PipelineError("剧本对应的章节不存在")

    # 时长按译文长度估。译文按映射取 —— 同语言可能有多版，
    # 按语言取会拿错版本，估出来的时长跟实际配音对不上。
    tf_id = transform.id if transform else None
    if tf_id is None and target_language:
        tf = resolve.active_transform(db, chapter.novel_id, target_language)
        tf_id = tf.id if tf else None

    scenes = list(
        db.execute(
            select(Scene).where(Scene.script_doc_id == script_doc.id)
            .order_by(Scene.order_no)
        ).scalars()
    )
    blocks = list(
        db.execute(
            select(ScriptBlock).where(ScriptBlock.script_doc_id == script_doc.id)
            .order_by(ScriptBlock.seq_no)
        ).scalars()
    )
    if not blocks:
        raise PipelineError("剧本没有内容块，无法编译分镜")

    camera = director.camera_json or {}
    editing = director.editing_json or {}
    avg_shot_ms = int(editing.get("avg_shot_ms") or 4500)

    by_scene: dict[str | None, list[ScriptBlock]] = {}
    for b in blocks:
        by_scene.setdefault(b.scene_id, []).append(b)

    scene_plan: list[tuple[Scene | None, list[ScriptBlock], int, int]] = []
    total_shots = 0
    for scene in (scenes or [None]):
        sid = scene.id if scene else None
        scene_blocks = by_scene.get(sid) or []
        if not scene_blocks:
            if scene is not None:
                continue
            scene_blocks = blocks
        dur = _estimate_ms(db, scene_blocks, target_language, tf_id)
        count = max(1, round(dur / avg_shot_ms)) if dur else max(1, len(scene_blocks) // 2)
        scene_plan.append((scene, scene_blocks, dur, count))
        total_shots += count

    seed = int(fingerprint(script_doc.id, director.code)[:8], 16) % (2**31)
    size_alloc = _Allocator(camera.get("shot_sizes") or {}, total_shots, seed)
    move_alloc = _Allocator(camera.get("movement") or {}, total_shots, seed + 1)

    version = int(
        db.execute(
            select(ShotPlan.version).where(ShotPlan.script_doc_id == script_doc.id)
            .order_by(ShotPlan.version.desc()).limit(1)
        ).scalar() or 0
    ) + 1

    plan = ShotPlan(
        id=new_id("sp"), script_doc_id=script_doc.id, version=version,
        status=DocStatus.draft, target_language_code=target_language,
        transform_id=transform.id if transform else None,
        director_profile_id=director.id,
        config_json={
            "aspect_ratio": aspect_ratio, "director_code": director.code,
            "avg_shot_ms": avg_shot_ms, "planned_shots": total_shots,
        },
    )
    db.add(plan)
    db.flush()

    entities = {
        e.display_name: e
        for e in db.execute(
            select(WorldEntity).where(WorldEntity.novel_id == chapter.novel_id)
        ).scalars()
    }

    result = ShotPlanResult(shot_plan_id=plan.id, version=version)
    covered: set[str] = set()
    order_no = 0

    for scene, scene_blocks, _dur, count in scene_plan:
        raw_shots = _ask_llm_for_shots(
            db, script_doc, scene, scene_blocks, count, director, version=version
        )
        valid_ids = {b.id for b in scene_blocks}
        for item in raw_shots:
            order_no += 1
            block_ids = [b for b in (item.get("block_ids") or []) if b in valid_ids]
            covered.update(block_ids)

            size = size_alloc.take() or "ms"
            move = move_alloc.take() or "static"
            shot_blocks = [b for b in scene_blocks if b.id in block_ids]
            dur = _estimate_ms(db, shot_blocks, target_language, tf_id) or avg_shot_ms

            shot = Shot(
                id=new_id("sh"), shot_plan_id=plan.id,
                scene_id=scene.id if scene else None,
                order_no=order_no, block_ids_json=block_ids,
                duration_ms=max(dur, 1200), shot_size=size,
                camera_json={
                    "move": move,
                    "speed": float(camera.get("speed", 0.4)),
                    "lens_mm": camera.get("lens_mm"),
                    "angle": camera.get("angle_bias"),
                },
                description=str(item.get("description") or "") or None,
                status=SpecStatus.pending,
            )
            db.add(shot)
            db.flush()

            names = [str(n) for n in (item.get("entity_names") or [])]
            entity_ids = [entities[n].id for n in names if n in entities]
            asset_keys = [str(k) for k in (item.get("asset_keys") or [])]
            shared = {"asset_keys": asset_keys, "shot_size": size,
                      "seed": (seed + order_no) % (2**31)}
            # 镜头内容存进 params.content 而不是只存 prompt：
            # prompt 是合成的**产出**，会被反复覆写。
            # 只存在 prompt 里的话，第二次合成会把上一次的产出
            # 当成镜头内容读回去，一层层套下去
            # 出图用英文，审核用中文。没有英文时退回中文 ——
            # 少了这一句画面就没有内容了，而 cjk_segments 会把它报出来
            first_content = (as_text(item.get("first_frame_en")).strip()
                             or as_text(item.get("first_frame")).strip())
            last_content = (as_text(item.get("last_frame_en")).strip()
                            or as_text(item.get("last_frame")).strip())

            db.add(FrameSpec(
                id=new_id("fs"), shot_id=shot.id, role=FrameRole.first,
                prompt=first_content or None,
                entity_ids_json=entity_ids,
                params_json={**shared, "content": first_content},
                derive_from_first=False, status=SpecStatus.pending,
            ))
            db.add(FrameSpec(
                id=new_id("fs"), shot_id=shot.id, role=FrameRole.last,
                prompt=last_content or None,
                entity_ids_json=entity_ids,
                params_json={**shared, "content": last_content},
                derive_from_first=True,
                derive_instruction=str(item.get("derive_instruction") or "") or None,
                status=SpecStatus.pending,
            ))

            result.shots += 1
            result.total_duration_ms += shot.duration_ms
            result.size_distribution[size] = result.size_distribution.get(size, 0) + 1
            result.move_distribution[move] = result.move_distribution.get(move, 0) + 1

    result.scenes = len([s for s, _b, _d, _c in scene_plan if s])
    result.uncovered_blocks = [
        b.id for b in blocks
        if b.id not in covered and b.block_type != BlockType.scene_break
    ]
    plan.stats_json = result.as_dict()

    if activate:
        for old in db.execute(
            select(ShotPlan).where(
                ShotPlan.script_doc_id == script_doc.id,
                ShotPlan.status == DocStatus.active,
                ShotPlan.id != plan.id,
            )
        ).scalars():
            old.status = DocStatus.archived
        plan.status = DocStatus.active

    db.flush()
    return result


def _ask_llm_for_shots(
    db: Session, script_doc: ScriptDoc, scene: Scene | None,
    blocks: Sequence[ScriptBlock], target_count: int, director: DirectorProfile,
    *, version: int = 1,
) -> list[dict]:
    scene_info = ""
    if scene is not None:
        bits = [scene.title, scene.time_of_day, scene.location_text,
                scene.weather, scene.mood]
        scene_info = " / ".join(b for b in bits if b)

    payload = {
        # 版本进输入：每次重新编译都是显式的「我要新结果」，
        # 不该命中上一版的缓存
        "plan_version": version,
        "scene": scene_info,
        "target_shot_count": target_count,
        "blocks": [
            {"id": b.id, "type": b.block_type.value,
             "speaker": b.speaker_tag, "text": b.source_text}
            for b in blocks
        ],
    }
    guidance = (
        f"【导演风格】{director.display_name}：{director.summary or ''}\n"
        f"【本场目标镜头数】{target_count}（按该导演的平均镜长推算，可 ±1）"
    )
    data, _ = chat_json(
        db,
        [
            {"role": "system", "content": SHOT_SYSTEM},
            {"role": "user", "content": guidance + "\n\n" + _dump(payload)},
        ],
        SHOT_SCHEMA,
        purpose="shot_plan",
        chapter_id=script_doc.chapter_id,
        ref_kind="shot_plan", ref_id=script_doc.id,
    )
    return sorted(data.get("shots") or [], key=lambda s: int(s.get("order") or 0))


def _dump(payload: Any) -> str:
    import json
    return json.dumps(payload, ensure_ascii=False, indent=1)
