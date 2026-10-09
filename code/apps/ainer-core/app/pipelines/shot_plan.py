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

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.ids import new_id
from app.models import (
    Chapter, DirectorProfile, DocStatus, FrameRole, FrameSpec, Scene, ScriptBlock,
    ScriptDoc, Shot, ShotPlan, SpecStatus, TranslationBlock,
    WorldProfile, WorldTransform,
)
from app.models.script import BlockType
from app.worldview import resolve
from app.worldview import profile_resolve
from app.pipelines.base import PipelineError, as_text, chat_json, fingerprint
from app.pipelines.entity_surfaces import load_entity_surfaces

from app.pipelines import screenplay as sp

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
                             "first_frame_en", "last_frame_en", "motion"],
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
                    "motion": {"type": "string", "enum": ["animate", "camera", "hold"]},
                },
            },
        }
    },
}

SHOT_SYSTEM = """你是分镜师。把剧本切成镜头，并为每个镜头写出首帧与尾帧的画面内容。

分工须知：景别、运镜、时长由系统按导演风格分配，**你不要指定这些**。
你只负责：怎么切、镜头里发生什么、谁出场、用到哪些素材、尾帧相对首帧变了什么。
这是无旁白电影：narration 块必须落实为观众看得见的动作、反应、环境变化、
建立镜头或视觉转场，绝不能写成“旁白说明”或让字幕代替画面。

要求：
1. block_ids 填该镜头覆盖的剧本块 id。相邻的、同一动作单元的块可以合成一个镜头；
   一个块也可以拆成多个镜头。所有块必须被覆盖，不能遗漏。
2. description 一句话说明镜头内容，中文，不要写景别与运镜。
3. entity_names 只能从 entity_catalog.name 中逐字选择。目标世界制作必须填目标文化名，
   系统会把它回绑到原小说的稳定人物实体。
4. asset_keys 填用到的素材 canonical_key（服装/道具/场景/氛围）。
5. first_frame 写首帧的画面内容：谁在哪、在做什么、什么状态。
   **只写内容，不写画风、不写材质细节** —— 那些由素材库提供。
6. last_frame 写尾帧的画面内容。motion="hold" 或 "camera" 时留空字符串 ——
   这两类没有派生尾帧，硬写一个只会让出帧环节白跑一次。

6b. first_frame_en / last_frame_en：把上面两句写成**英文**。
    **图像模型不认中文** —— 中文喂进去出来的是一整版汉字纹样，
    不是画面（实跑验证过）。这两句是直接拼进出图提示词的那一句。
    写成短语串，不要句子，不要出现人名（模型读不出人名是谁）：
      ✓ a man seated behind a door, sabre across his knees, eyes on the door gap
      ✗ Shen Yan sits behind the door and stares at the crack
    中文那两句是给人审核的，两份都要填。
7. motion 必须先分成三类，再决定尾帧和 derive_instruction：

   **"hold" = 人物、物件和摄影机都不动。**

   画面在这段时间里没有物理变化：
      ✓ 对白镜里听的一方，镜头就停在他脸上
      ✓ 情绪停顿，人一动不动，靠时间本身施压
      ✓ 空镜定场：屋脊、雨帘、一盏灯
   标 hold 的镜头**不写 derive_instruction，尾帧留空**。
   系统直接用首帧保持，不调用视频模型。

   **"camera" = 主体没有首尾状态变化，但镜头仍然是动态的。**
   用于 3—8 秒对白中的口型、呼吸、眨眼，以及推近、横摇、轻微手持：
      ✓ 他说完一句话，摄影机缓慢推近，听者在背景中轻微移焦
      ✓ 无对白的人物静坐，摄影机从侧面缓慢横移揭示门口
   camera 不生成尾帧，last_frame / last_frame_en 留空；derive_instruction 必填，
   写清连续运镜、口型或微表演。系统用首帧驱动视频模型，不能标成 hold。

   **"animate" = 主体或关键物件有明确的首尾状态变化。**
   此时 derive_instruction 必填，一句话说明「尾帧相对首帧变了什么」。
   **必须是一个看得见的物理动作** —— 人或物在画面里的位移、开合、抬落：
      ✓ 他向前走两步，推开药匣子
      ✓ 他站起身，手按上刀柄
      ✓ 门被推开一半，雨水泼进门槛
      ✗ 脚步声由远及近          ← 声音的变化，画面上什么都不变
      ✗ 他依然静坐              ← 明说没有变化
      ✗ 他收起笑容              ← 表情微变，五秒内看不出来

   **关键分界：**写不出主体首尾变化，但有持续运镜、说话口型或微表演时标 camera；
   主体与摄影机都不动才标 hold。不要为了凑 animate 编一句假动作。
   从前这里要求「宁可少一个镜头」，结果是逼出「他收起笑容」这类假动作 ——
   首尾帧生成出来几乎一样，视频模型插不出东西，白烧八十秒，
   成片里还是一张静止画面。标 hold 是诚实的做法，且省掉那八十秒。

   **但 hold 不是偷懒的出口。** 真静态镜控制在**四成以内**：
   一场戏里连着三镜以上都是 hold，成片就是幻灯片。
   有人在走、在递、在开门、在动手的，一律 animate。
   拿不准时优先 animate —— 真动起来比停着安全。

   **每一镜的变化说明必须互不相同。** 几镜共用同一句，
   意味着那几镜的尾帧长得一样，剪在一起像同一个画面播了几遍。
8. 一句对白超过约五秒时，要用说话人、听者反应、手部／关键道具细节、环境压力
   等不同机位覆盖，不能整句只给一张脸。所有补镜必须来自剧本已经存在的人物、
   物件、空间与情绪，不得新造情节。
9. 首尾帧必须写清主体相对位置、接触关系、重心与动作阶段；人物不能凭空换边，
   道具不能换手，门窗衣物头发与光源变化都必须有可见原因。"""


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
    #: 上一版分镜上已生成、这一版用不上的画面。**要报出来** ——
    #: 那是已经花掉的钱，而重编译不会有任何别的迹象说它作废了
    orphaned_assets: dict[str, Any] = field(default_factory=dict)
    #: 变化说明看不见、已被换成中性说法的镜头。**要报出来** ——
    #: 这个数字等于「有几镜的首尾帧不会有实质差别」，
    #: 而那正是成片看起来像幻灯片的直接原因
    #:
    #: 注意：模型主动标 motion="hold" 的镜头**不进这个列表**。
    #: 那是「这一镜就该是静的」的明示判断，和「编了个看不见的动作」
    #: 是两回事 —— 前者按静态镜走快路径，后者仍然要挡住重写。
    static_derives: list[dict] = field(default_factory=list)
    #: 模型判定为静态、走定格/缓推而不出视频的镜头。**要报出来** ——
    #: 静态镜省掉尾帧 27s + 视频 80s，但比例失控就成幻灯片了。
    #: 列表长度 / shots 就是静态占比，超过四成该回去看提示词是不是太松。
    held_shots: list[dict] = field(default_factory=list)
    #: 只有首帧，但仍要由视频模型完成连续运镜／口型／微表演的镜头。
    camera_shots: list[dict] = field(default_factory=list)
    #: 静态镜被分到摇/手持/环绕、已收窄成定格的镜头。**要报出来** ——
    #: 这个数字等于「导演的运镜比例实际被削了多少」，
    #: 数字一大说明静态镜占比过高，该回去看分镜而不是调导演包
    coerced_moves: list[dict] = field(default_factory=list)
    #: 模型漏填、按对白说话人补进去的出场人物。**要报出来** ——
    #: 这个数字等于「有几镜的画面里张嘴的是另一张脸」，
    #: 而台词、配音、时间轴全都对，只有把画面和台词摆在一起才看得出来
    speaker_added: list[dict] = field(default_factory=list)
    #: 因为太长被切成多机位的镜头。**要报出来** —— 这几段是
    #: 「同一段内容换角度覆盖」，不是新增情节；剪的人要知道哪几个镜头
    #: 本来是一条，才不会当成连续动作去接
    split_for_length: list[dict] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "shot_plan_id": self.shot_plan_id, "version": self.version,
            "shots": self.shots, "scenes": self.scenes,
            "total_duration_ms": self.total_duration_ms,
            "size_distribution": self.size_distribution,
            "move_distribution": self.move_distribution,
            "uncovered_blocks": self.uncovered_blocks,
            "static_derives": self.static_derives,
            "held_shots": self.held_shots,
            "camera_shots": self.camera_shots,
            "coerced_moves": self.coerced_moves,
            "held_ratio": (round(len(self.held_shots) / self.shots, 3)
                           if self.shots else 0.0),
            "speaker_added": self.speaker_added,
            "split_for_length": self.split_for_length,
            "orphaned_assets": self.orphaned_assets,
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



def _previous_assets(db: Session, script_doc_id: str) -> dict[str, Any]:
    """上一版分镜上已经生成的画面有多少。

    只数不动 —— 判断「旧图还对不对得上新镜」需要看切分怎么变的，
    那不是这里能定的。这里只负责让人知道有这么一笔。
    """
    from app.models import FrameRole, FrameSpec

    prev = db.execute(
        select(ShotPlan).where(ShotPlan.script_doc_id == script_doc_id)
        .order_by(ShotPlan.version.desc()).limit(1)
    ).scalars().first()
    if prev is None:
        return {"total": 0}
    sids = [s for (s,) in db.execute(
        select(Shot.id).where(Shot.shot_plan_id == prev.id)).all()]
    if not sids:
        return {"total": 0}
    frames = list(db.execute(
        select(FrameSpec).where(FrameSpec.shot_id.in_(sids),
                                FrameSpec.asset_id.isnot(None))).scalars())
    videos = db.execute(
        select(func.count()).select_from(Shot)
        .where(Shot.shot_plan_id == prev.id, Shot.video_asset_id.isnot(None))
    ).scalar() or 0
    first = sum(1 for f in frames if f.role == FrameRole.first)
    last = sum(1 for f in frames if f.role == FrameRole.last)
    total = first + last + videos
    return {
        "total": total, "from_version": prev.version, "from_plan": prev.id,
        "first_frames": first, "last_frames": last, "videos": videos,
        "why": (f"v{prev.version} 上已生成 {first} 张首帧、{last} 张尾帧、"
                f"{videos} 支视频，新版用不上 —— 镜头切分变了，"
                f"旧图未必对得上新镜，所以不自动迁移。"
                f"要沿用就回到 v{prev.version}，要重出就是这笔钱重花一遍"),
    }

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
        if tf is not None:
            transform = tf
            tf_id = tf.id
    if tf_id is None:
        # **剧本自己记着它是从哪个映射生成的，就用那个。**
        # 不接这一句的后果：调用方没传 target_language 时 transform_id 留空，
        # 而八工种、配乐、绑定拼装全读这一列，一律 409
        # 「分镜计划没有关联世界观档案」—— 可那个 id 一直躺在
        # generator_meta 里，只是没人把它写进列。
        own = (script_doc.generator_meta or {}).get("transform_id")
        if own:
            tf = db.get(WorldTransform, str(own))
            if tf is not None and tf.novel_id == chapter.novel_id:
                transform = tf
                tf_id = tf.id
    if transform is not None:
        if transform.novel_id != chapter.novel_id:
            raise PipelineError("分镜映射不属于当前小说")
        target_language = target_language or transform.target_language_code
        script_transform = (script_doc.generator_meta or {}).get("transform_id")
        if script_transform != transform.id:
            raise PipelineError(
                "当前剧本不是从这个已锁定译本生成的，不能直接进入目标世界分镜。"
                "请回到「剧本转换」，选当前映射重新生成剧本"
            )

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
    #: 静态镜做不出摇/手持/环绕，被收窄成定格的记录
    coerced_moves: list[dict] = []

    version = int(
        db.execute(
            select(ShotPlan.version).where(ShotPlan.script_doc_id == script_doc.id)
            .order_by(ShotPlan.version.desc()).limit(1)
        ).scalar() or 0
    ) + 1

    # **重编译会把上一版已经生成的画面全部孤儿化。**
    #
    # 新版的 Shot / FrameSpec 都是新行，旧版那些图和视频还挂在旧 shot 上 ——
    # 库里在、资源库里看得到，但新时间线一张都用不上。
    # 实跑撞过一次：v4 有 30 张首帧、28 张尾帧、12 支 i2v，
    # 我在 v6 上渲染，出来 34 镜全黑，而全程没有任何一处提示。
    #
    # 不自动迁移 —— 镜头切分变了，旧图未必还对得上新镜。
    # 但**必须报出来**：那是一笔已经花掉的钱，人得知道它作废了。
    prev_cost = _previous_assets(db, script_doc.id)

    plan = ShotPlan(
        id=new_id("sp"), script_doc_id=script_doc.id, version=version,
        status=DocStatus.draft, target_language_code=target_language,
        transform_id=transform.id if transform else None,
        director_profile_id=director.id,
        config_json={
            "aspect_ratio": aspect_ratio, "director_code": director.code,
            "avg_shot_ms": avg_shot_ms, "planned_shots": total_shots,
            "production_source": (script_doc.generator_meta or {}).get(
                "production_source", "original"),
            "production_transform_id": (script_doc.generator_meta or {}).get(
                "transform_id"),
        },
    )
    db.add(plan)
    db.flush()

    entity_index = load_entity_surfaces(
        db, chapter.novel_id,
        transform_id=transform.id if transform else None,
    )
    entities = entity_index.by_surface

    result = ShotPlanResult(shot_plan_id=plan.id, version=version)
    if prev_cost["total"]:
        result.orphaned_assets = prev_cost
    covered: set[str] = set()
    order_no = 0

    for scene, scene_blocks, _dur, count in scene_plan:
        raw_shots = []
        for part, part_count in _chunk_scene(scene_blocks, count):
            raw_shots.extend(_ask_llm_for_shots(
                db, script_doc, scene, part, part_count, director,
                transform=transform, entity_catalog=entity_index.catalog(),
                version=version,
            ))
        # 语义约束不能只写在提示词里。模型一旦把整场对白都标成 hold，
        # 后面每层都只会忠实地做成幻灯片。真静态镜最多四成；超出的
        # 镜头提升为 camera，由连续运镜／口型承担动态，同时仍不伪造尾帧。
        hold_budget = max(1, int(len(raw_shots) * 0.4)) if raw_shots else 0
        held_seen = 0
        for item in raw_shots:
            kind = str(item.get("motion") or "animate").strip().lower()
            if kind not in {"animate", "camera", "hold"}:
                kind = "animate"
            if kind == "hold":
                held_seen += 1
                if held_seen > hold_budget:
                    kind = "camera"
                    item["derive_instruction"] = (
                        as_text(item.get("derive_instruction")).strip()
                        or "摄影机缓慢推近，人物保持自然呼吸、眨眼或对白口型"
                    )
            item["motion"] = kind
        valid_ids = {b.id for b in scene_blocks}
        for item in raw_shots:
            block_ids = [b for b in (item.get("block_ids") or []) if b in valid_ids]
            covered.update(block_ids)
            shot_blocks = [b for b in scene_blocks if b.id in block_ids]
            span = _estimate_ms(db, shot_blocks, target_language, tf_id) or avg_shot_ms
            # 打斗镜切得密，对话镜可以长 —— 判据看这一镜的描述与原文
            action = sp.is_action_beat(
                item.get("description"),
                *[b.source_text for b in shot_blocks],
            )
            motion_kind = str(item.get("motion") or "animate").strip().lower()
            held = motion_kind == "hold"
            camera_only = motion_kind == "camera"
            slices = _coverage_slices(
                span,
                cap=(sp.HELD_MAX_MS if held else
                     sp.ACTION_MAX_MS if action and not camera_only else
                     sp.STATIC_MAX_MS),
            )
            if len(slices) > 1:
                result.split_for_length.append({
                    "from_shot": order_no + 1, "span_ms": span,
                    "into": len(slices),
                    "action": action,
                    "why": f"{span / 1000:.0f} 秒超过"
                           f"{'动态' if action else '静态'}上限，切成 "
                           f"{len(slices)} 个机位覆盖同一段",
                })
            # 下面这一层就是「同一段内容的第 n 个机位」。
            # 景别与运镜由分配器逐个给，所以每个机位天然不同 ——
            # 那正是覆盖的做法：说话人正面、听者反应、手部特写。
            # 内容共用父镜的首尾帧描述：模型只为整段写了一份，
            # 硬给每个机位编一份不同的等于凭空造情节。
            for slice_idx, dur in enumerate(slices):
                order_no += 1
                size = size_alloc.take() or "ms"
                move = move_alloc.take() or "static"
                # **定格镜只能定格或缓推。** 摇镜、手持、环绕要真实的三维位移，
                # 一张静帧给不出来 —— 下游走的是 ffmpeg，能做的只有这两样。
                # 导演包的分布里有 pan/handheld，照发给静态镜，
                # 分镜单上就会写着「摇」而成片是定格，两边对不上。
                # 这里收窄并报出来，让人知道导演的运镜比例被削了多少。
                if held and move not in ("static", "push_in"):
                    coerced_moves.append({"shot": order_no, "from": move})
                    move = "static"
                if camera_only and move == "static":
                    coerced_moves.append({
                        "shot": order_no, "from": "static", "to": "push_in",
                        "why": "camera 镜必须有连续运镜或微表演",
                    })
                    move = "push_in"

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
                        "motion_kind": motion_kind,
                        **({"frame_mode": "first_only"} if
                           (held or camera_only) else {}),
                        **({"held_reason": "分镜判定为真正静态镜"} if held else {}),
                    },
                    description=str(item.get("description") or "") or None,
                    status=SpecStatus.pending,
                )
                db.add(shot)
                db.flush()

                names = [str(n) for n in (item.get("entity_names") or [])]
                entity_ids = [entities[n].id for n in names if n in entities]
                # **说话人必须在场。**
                #
                # entity_names 是模型的判断，而这一镜覆盖的对白块上写着
                # speaker_tag —— 那是上一步定下来的事实，不是判断。
                # 两者冲突时以事实为准：坏蛋实跑里镜 2 的台词是 Tyler Kao 说的
                #（speaker_tag 写得清清楚楚），模型却把出场人物填成了 Brad Lee，
                # 于是首帧提示词描述的是另一个人 —— 画面里张嘴的那张脸是错的，
                # 而台词、配音、时间轴全都对。这种错只有把画面和台词摆在一起
                # 才看得出来，报表上一片正常。
                for b in shot_blocks:
                    if b.block_type is not BlockType.dialogue:
                        continue
                    who = b.speaker_entity_id or (
                        entities[b.speaker_tag].id
                        if b.speaker_tag in entities else None)
                    if who and who not in entity_ids:
                        entity_ids.append(who)
                        result.speaker_added.append({
                            "shot": order_no, "speaker": b.speaker_tag,
                            "why": "台词的说话人不在模型给的出场人物里，已补上",
                        })
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
                # **中文那份也要存。** 模型两份都给了，这里只取英文
                # 就把审核用的那份丢在响应里了 —— 人看后台时只剩英文，
                # 校不出「他推开门」被写成了 pushes open the window
                first_cn = as_text(item.get("first_frame")).strip()
                last_cn = as_text(item.get("last_frame")).strip()

                db.add(FrameSpec(
                    id=new_id("fs"), shot_id=shot.id, role=FrameRole.first,
                    prompt=first_content or None,
                    entity_ids_json=entity_ids,
                    params_json={**shared, "content": first_content,
                                 "content_cn": first_cn or None},
                    derive_from_first=False, status=SpecStatus.pending,
                ))
                # **变化说明必须是看得见的动作。**
                #
                # 提示词里已经写死了（含反例），但模型仍会写出「眉头微皱」
                # 「呼吸略显急促」这类 —— 五秒的镜头里那些看不出来，
                # 首尾帧于是几乎相同，i2v 无从插值，成片里就是一张静止画面。
                #
                # 判出来后保留原话并报出，不用「姿态轻微移动」这种假动作糊住。
                # 后续动作导演会依据剧本、调度与八工种单，补齐完成该动作
                # 所需的最小物理过程；在那之前，出帧与出视频都会被硬门禁挡住。
                derive = as_text(item.get("derive_instruction")) or None
                if held:
                    # 主动标 hold 的不过这道门禁。门禁是用来抓「编了个看不见的
                    # 动作」的，而这里模型明说了这一镜不动 —— 那是判断，不是失误。
                    result.held_shots.append({
                        "shot": shot.order_no,
                        "description": str(item.get("description") or ""),
                    })
                    derive = None
                elif camera_only:
                    result.camera_shots.append({
                        "shot": shot.order_no,
                        "description": str(item.get("description") or ""),
                        "move": move,
                    })
                    vis_ok, vis_why = sp.is_camera_motion(derive)
                    if not vis_ok:
                        result.static_derives.append({
                            "shot": shot.order_no, "instruction": derive,
                            "why": "camera 镜缺连续运镜／口型／微表演：" + vis_why,
                        })
                else:
                    vis_ok, vis_why = sp.is_visible_change(derive)
                    if not vis_ok:
                        result.static_derives.append({
                            "shot": shot.order_no, "instruction": derive, "why": vis_why,
                        })

                db.add(FrameSpec(
                    id=new_id("fs"), shot_id=shot.id, role=FrameRole.last,
                    prompt=last_content or None,
                    entity_ids_json=entity_ids,
                    params_json={**shared, "content": last_content,
                                 "content_cn": last_cn or None},
                    derive_from_first=True,
                    derive_instruction=derive,
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

    result.coerced_moves = coerced_moves

    db.flush()
    return result


#: 一次调用最多要几个镜头。
#:
#: 每个镜头要吐 description + first_frame + last_frame + 可见差异 + 出场人物
#: + 素材键，四五百 token 起步。一场三十多个镜头就是一万五以上，
#: 而截断重试把预算抬到 8192 之后仍然两轮都截断 ——
#: 报出来是「输出太多」，根因是**这一层从来没在场内分过批**。
#:
#: 上游把场记按节拍拆细之后这个坑才浮出来：块从 91 变成 113，
#: 镜头数跟着涨，一次性生成就再也装不下。
#: 拆细是对的（首尾帧之间跨半小时会漂），代价是这里必须分批。
_SHOTS_PER_CALL = 10


#: 一镜的时长上限。超过就切机位 —— 一个画面停五秒以上，观众会觉得卡住。
#: 首尾帧插值本身也撑不住更长：超过五秒开始变慢动作糊影。
_SHOT_MAX_MS = 5000
_SHOT_MIN_MS = 1200


def _coverage_slices(dur: int, *, cap: int = _SHOT_MAX_MS) -> list[int]:
    """一镜太长就切成几个机位，返回每个机位的时长。

    **上限按内容分档，不是一刀切。** 对话只有嘴唇在动，八秒一个镜头
    完全够，五秒切一刀反而是把同一个画面切成两半 —— 观众看到的是
    同一张脸接同一张脸。而打斗的信息密度完全不同：一次出击、一次格挡、
    一次踉跄各自都该是一个镜头，两秒就得切。
    档位由 screenplay.STATIC_MAX_MS / ACTION_MAX_MS 定，调用方按
    is_action_beat 选。

    **切的是机位，不是内容。** 一句十五秒的台词没法缩短，能做的是
    换角度覆盖它：说话人正面、听者反应、手部特写。这是剪辑里
    「coverage」本来的意思，不是把台词砍掉。

    平均分而不是「切满上限再留个零头」—— 后者会留下一个一秒的尾巴，
    剪在一起像卡了一下。
    """
    if dur <= cap:
        return [max(dur, _SHOT_MIN_MS)]
    n = -(-dur // cap)
    base, extra = divmod(dur, n)
    return [max(base + (1 if i < extra else 0), _SHOT_MIN_MS) for i in range(n)]


def _chunk_scene(
    blocks: list["ScriptBlock"], count: int,
) -> list[tuple[list["ScriptBlock"], int]]:
    """把一场切成几批，每批不超过 _SHOTS_PER_CALL 个镜头。

    按**块**切而不是按镜头切 —— 镜头是模型待会儿才划的，这里还不知道
    它会怎么划。块边界天然安全：一个镜头只会覆盖相邻的块，
    不会跨到另一批去。

    批次内的目标镜头数按块数比例分，余数给前面几批 ——
    前面通常是建场镜，切得密一点更合理。
    """
    if count <= _SHOTS_PER_CALL or len(blocks) <= 1:
        return [(blocks, count)]
    n = -(-count // _SHOTS_PER_CALL)          # 向上取整
    n = min(n, len(blocks))
    per_block = -(-len(blocks) // n)
    out: list[tuple[list["ScriptBlock"], int]] = []
    base, extra = divmod(count, n)
    for i in range(n):
        part = blocks[i * per_block : (i + 1) * per_block]
        if not part:
            break
        out.append((part, base + (1 if i < extra else 0)))
    # 块没分完（per_block 取整导致）就并进最后一批，绝不能丢块
    used = sum(len(b) for b, _ in out)
    if used < len(blocks):
        last_blocks, last_count = out[-1]
        out[-1] = (last_blocks + blocks[used:], last_count)
    return out


def _ask_llm_for_shots(
    db: Session, script_doc: ScriptDoc, scene: Scene | None,
    blocks: Sequence[ScriptBlock], target_count: int, director: DirectorProfile,
    *, transform: WorldTransform | None = None,
    entity_catalog: list[dict[str, object]] | None = None,
    version: int = 1,
) -> list[dict]:
    scene_info = ""
    if scene is not None:
        bits = [scene.title, scene.time_of_day, scene.location_text,
                scene.weather, scene.mood]
        scene_info = " / ".join(b for b in bits if b)

    target_world: dict[str, Any] | None = None
    if transform is not None:
        profile = db.get(WorldProfile, transform.target_profile_id)
        if profile is None:
            raise PipelineError("目标世界观档案不存在")
        target_world = profile_resolve.resolve(db, profile)

    payload = {
        # 版本进输入：每次重新编译都是显式的「我要新结果」，
        # 不该命中上一版的缓存
        "plan_version": version,
        "scene": scene_info,
        "target_shot_count": target_count,
        "production_language": script_doc.language_source,
        "target_world": target_world,
        "transform_policy": (transform.policy_json or {}) if transform else None,
        "entity_catalog": entity_catalog or [],
        "blocks": [
            {"id": b.id, "type": b.block_type.value,
             "speaker": b.speaker_tag, "production_text": b.source_text}
            for b in blocks
        ],
    }
    guidance = (
        f"【导演风格】{director.display_name}：{director.summary or ''}\n"
        f"【本场目标镜头数】{target_count}（按该导演的平均镜长推算，可 ±1）\n"
        "【生产语义】blocks.production_text 是已锁定的目标世界剧本；"
        "人名、称谓、时代、道具与空间必须服从 target_world，不得翻回或猜回原世界"
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
