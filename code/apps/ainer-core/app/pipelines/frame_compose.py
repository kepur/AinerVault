"""首尾帧 prompt 拼装 —— 全部来自素材库，不自由发挥。

一个镜头的画面由五层叠加而成，每层都有确定的来源：
  1  画风      style 素材的 variant          全书一份
  2  场景      location 素材的 variant       同场景所有镜头共用
  3  人物      entity_world_visual + costume 素材
  4  道具      prop 素材的 variant
  5  镜头      shot_size + camera + 导演的构图/光线 + FrameSpec.prompt（内容描述）

镜头自己只贡献「谁在哪做什么」，一切外观描述都来自素材 ——
否则同一件长袍在十个镜头里会长成十个样子。

尾帧不独立生成：以首帧成图为基底做 i2i，同 seed，strength 0.25–0.45。
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.capability.schemas import Capability
from app.capability.service import estimate_cost, submit_task
from app.ids import new_id
from app.models import (
    Asset, AssetKindSpec, AssetSpec, AssetVariant, DirectorProfile, EntityChapterState,
    EntityWorldVisual, FrameRole, FrameSpec, ReviewStatus, Scene, Shot, ShotAssetBinding,
    ShotPlan, SpecStatus, WorldEntity, WorldProfile, WorldTransform,
)
from app.pipelines.base import PipelineError, as_items, as_list
from app.pipelines.epochs import compose_epoch_prompt, resolve_epoch
from app.pipelines.shot_plan import SHOT_SIZE_PROMPT

log = logging.getLogger(__name__)


@dataclass
class ComposeResult:
    shots: int = 0
    bound: int = 0
    missing_assets: list[str] = field(default_factory=list)
    missing_entity_visual: list[str] = field(default_factory=list)
    #: 提示词里还留着的中文片段。**图像模型不认中文** ——
    #: 喂中文出来的是汉字纹样不是画面。哪条产线还欠英文渲染，看这里
    untranslated: list[dict[str, Any]] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "shots": self.shots, "bound": self.bound,
            "missing_assets": self.missing_assets,
            "missing_entity_visual": self.missing_entity_visual,
            "untranslated": self.untranslated,
        }


def _variant_index(
    db: Session, novel_id: str, profile_id: str
) -> tuple[dict[str, tuple[AssetSpec, AssetVariant]], dict[str, tuple[AssetSpec, AssetVariant]]]:
    """canonical_key → (spec, variant)，以及 kind → 首个可用的。"""
    rows = db.execute(
        select(AssetSpec, AssetVariant)
        .join(AssetVariant, AssetVariant.asset_spec_id == AssetSpec.id)
        .where(
            AssetSpec.novel_id == novel_id,
            AssetVariant.world_profile_id == profile_id,
        )
    ).all()
    by_key: dict[str, tuple[AssetSpec, AssetVariant]] = {}
    by_kind: dict[str, tuple[AssetSpec, AssetVariant]] = {}
    for spec, variant in rows:
        if variant.missing_fields:
            continue
        by_key[spec.canonical_key] = (spec, variant)
        by_kind.setdefault(spec.kind.value, (spec, variant))
    return by_key, by_kind


def _asset_urls(db: Session, ids: Sequence[str]) -> list[str]:
    if not ids:
        return []
    return [
        u for u in db.execute(
            select(Asset.url).where(Asset.id.in_(list(ids)))
        ).scalars() if u
    ]


def _entity_look(
    db: Session, entity: WorldEntity, profile_id: str, chapter_order: int | None
) -> tuple[str, list[str]]:
    """人物外观。有时期数据时以时期为准，否则回落到基础视觉 + 成长状态。

    ## 为什么时期一旦存在就独占

    时期与 EntityChapterState 描述的是同一件事，都会往提示词里加外貌。
    两条都放行的话，同一张脸会被描述两遍 —— 而两遍描述必然不完全一样，
    图像模型收到互相打架的指令，出来的脸两边都不像。
    所以有时期就只用时期，没有才走老路。

    时期路径把 invariant 放在最前面（compose_epoch_prompt 保证），
    并带上跨期共用的那张脸参考 —— 脸不漂的全部依据就是这两样。
    """
    epoch = resolve_epoch(db, entity.id, profile_id, chapter_order)
    if epoch is not None:
        anchor = epoch.identity_ref_asset_id
        text = epoch.visual_prompt or compose_epoch_prompt(
            epoch, "character", has_anchor=bool(anchor))
        refs = list(epoch.ref_asset_ids or [])
        if anchor and anchor not in refs:
            # 锚排最前：每个人物只取一张参考图，锚必须是那一张
            refs.insert(0, anchor)
        if text:
            return text.strip(), refs

    visual = db.execute(
        select(EntityWorldVisual).where(
            EntityWorldVisual.entity_id == entity.id,
            EntityWorldVisual.world_profile_id == profile_id,
        )
    ).scalars().first()

    parts: list[str] = []
    refs: list[str] = []
    if visual is not None and visual.visual_prompt:
        parts.append(visual.visual_prompt.strip())
        refs.extend(visual.ref_asset_ids or [])
    elif entity.visual_prompt:
        parts.append(entity.visual_prompt.strip())
        refs.extend(entity.ref_asset_ids or [])

    if chapter_order is not None:
        state = db.execute(
            select(EntityChapterState).where(
                EntityChapterState.entity_id == entity.id,
                EntityChapterState.chapter_order_from <= chapter_order,
            ).order_by(EntityChapterState.chapter_order_from.desc()).limit(1)
        ).scalars().first()
        if state is not None:
            if state.visual_prompt_override:
                parts.append(state.visual_prompt_override.strip())
            for k, v in (state.state_json or {}).items():
                val = str(v or "").strip()
                if val:
                    parts.append(f"{k.replace('_', ' ')}: {val}")
            refs.extend(state.ref_asset_ids or [])

    return ", ".join(p for p in parts if p), refs


#: 站位 → 英文提示词。九宫格而非坐标 —— 坐标在不同画幅下没有意义。
_POS_EN = {
    "far_left": "at the far left of frame", "left": "on the left of frame",
    "center_left": "left of centre", "center": "centred in frame",
    "center_right": "right of centre", "right": "on the right of frame",
    "far_right": "at the far right of frame",
    "foreground": "in the foreground", "background": "deep in the background",
}
_FACING_EN = {
    "to_camera": "facing camera", "away": "seen from behind",
    "profile_left": "in left profile", "profile_right": "in right profile",
    "three_quarter": "in three-quarter view",
}


def _epoch_prompts(
    db: Session, shot: Shot, profile: WorldProfile, chapter_order: int | None,
) -> list[str]:
    """这一镜绑定的素材，按当章的时期取提示词。

    走 epoch_bindings 而不是现算：绑定是分镜编译时定下的，
    出图不对时能查到当时用的是哪一期 —— 现算的话，
    改了时期区间之后就再也复现不出当初那张图为什么是那样。
    """
    from app.models import AssetEpoch, AssetSpec, EpochBinding

    # 只取素材主体：人物的时期已经由 _entity_look 出过一遍，
    # 这里再出一次就是同一张脸描述两遍
    rows = list(db.execute(
        select(EpochBinding, AssetSpec)
        .join(AssetSpec, AssetSpec.id == EpochBinding.asset_spec_id)
        .where(EpochBinding.shot_id == shot.id,
               EpochBinding.entity_id.is_(None))
    ))
    out: list[str] = []
    for binding, spec in rows:
        if not binding.asset_epoch_id:
            continue          # fallback：基准形态已在素材段里出过
        epoch = db.get(AssetEpoch, binding.asset_epoch_id)
        if epoch is None or epoch.world_profile_id != profile.id:
            continue
        text = epoch.visual_prompt or compose_epoch_prompt(epoch, spec.kind.value)
        if text:
            out.append(text.strip())
    return out


def _signage_prompt(db: Session, shot: Shot, profile: WorldProfile) -> str:
    """这一镜里出现的画面文字，连同该世界观的招牌规则。

    取译文而非原文 —— 画面属于目标世界观，招牌上该是目标语言。
    没有译文时退回原文并降级为「不要在画面上写字」：
    宁可留白，也不要把源语言的字画进目标世界观的街道。
    """
    from app.models import BlockType, ScriptBlock, TranslationBlock

    block_ids = list(shot.block_ids_json or [])
    if not block_ids:
        return ""
    rows = list(db.execute(
        select(ScriptBlock).where(
            ScriptBlock.id.in_(block_ids),
            ScriptBlock.block_type == BlockType.signage,
        )
    ).scalars())
    if not rows:
        return ""

    texts = {
        t.script_block_id: (t.translated_text or "").strip()
        for t in db.execute(
            select(TranslationBlock).where(
                TranslationBlock.script_block_id.in_([r.id for r in rows])
            )
        ).scalars()
    }
    done = [texts[r.id] for r in rows if texts.get(r.id)]
    rules = (profile.visual_json or {}).get("signage_rules") or {}
    if not done:
        return "no legible text on signage"

    bits = ["signage reads: " + " / ".join(f'"{t}"' for t in done[:3])]
    for key, label in (("script", "script"), ("style", "lettering"),
                       ("material", "sign material")):
        if rules.get(key):
            bits.append(f"{label}: {rules[key]}")
    if rules.get("avoid"):
        bits.append(f"avoid {rules['avoid']}")
    return ", ".join(bits)


def _gaze_phrase(target: str, where: dict[str, str]) -> str:
    """视线该怎么写进提示词。三种情况：

      看同镜里的人   换成几何位置。**人名对图像模型毫无意义** ——
                    「looking at 裴无咎」它读不出是谁，更读不出该往哪看
      看画面里的物   原样保留。「looking at the locked chest」是它能执行的
      其余           只说看向画外。名字或中文塞进去既没信息，
                    还会被当成图案画进画面
    """
    pos = where.get(target)
    if pos:
        return f"gaze directed at the figure {pos}"
    if target and not _CJK.search(target):
        return f"looking at {target}"
    return "gaze directed off-screen"


def _staging_prompt(db: Session, shot: Shot, frame: FrameSpec) -> str:
    """把这一镜的人物调度写成提示词。

    首帧用 expression/action，尾帧用 expression_end/action_end ——
    两者之差就是这一镜的运动，也正是尾帧 i2i 要改的那部分。
    取错了字段，首尾帧会一模一样，生成出来是两张静止的画。
    """
    from app.models import Facing, FrameRole, ShotPerformance, StagePosition, WorldEntity

    rows = list(db.execute(
        select(ShotPerformance, WorldEntity)
        .join(WorldEntity, WorldEntity.id == ShotPerformance.entity_id)
        .where(ShotPerformance.shot_id == shot.id)
    ))
    if not rows:
        return ""
    is_last = frame.role == FrameRole.last
    # 视线目标在画面里的位置。**人名对图像模型毫无意义** ——
    # 「looking at 裴无咎」它读不出是谁，更读不出该往哪看；
    # 「looking at the figure on the right」才是它能执行的指令
    where = {
        e.display_name: _POS_EN.get(p.position.value, "")
        for p, e in rows if p.position is not StagePosition.offscreen
    }
    bits: list[str] = []
    for p, e in rows:
        if p.position is StagePosition.offscreen:
            continue
        seg = [_POS_EN.get(p.position.value, ""), _FACING_EN.get(p.facing.value, "")]
        # 优先英文 —— 中文进了提示词会被当成图案画进画面。
        # 没有英文时仍带上中文：漏掉表情动作，这一镜就没有表演了，
        # 而 cjk_segments 会把它报出来，知道该补哪一条
        en = p.en_json or {}
        expr = (en.get("expression_end") if is_last else en.get("expression")) \
            or en.get("expression") \
            or (p.expression_end if is_last else p.expression) or p.expression
        act = (en.get("action_end") if is_last else en.get("action")) \
            or en.get("action") \
            or (p.action_end if is_last else p.action) or p.action
        if expr:
            seg.append(str(expr))
        if act:
            seg.append(str(act))
        if p.gaze_target:
            seg.append(_gaze_phrase(str(p.gaze_target), where))
        seg = [x for x in seg if x]
        if seg:
            bits.append(", ".join(seg))
    return "; ".join(bits)


#: 中日韩统一表意文字 + 假名 + 谚文。图像模型不认这些 ——
#: 实跑时把中文外貌描述喂给 SDXL，出来的是一整版汉字纹样，一张脸都没有。
_CJK = re.compile(r"[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uac00-\ud7af]")


def cjk_segments(prompt: str, limit: int = 8) -> list[str]:
    """提示词里还留着的非拉丁片段。

    **不是把它们删掉，是报出来。** 删掉等于悄悄丢信息：
    「站在门口，手握刀柄」删了，画面里的人就不再握刀了，
    而没有任何地方说过为什么。报出来才知道哪条产线还欠英文渲染。
    """
    out = []
    for seg in (x.strip() for x in prompt.split(", ")):
        if seg and _CJK.search(seg) and seg not in out:
            out.append(seg)
        if len(out) >= limit:
            break
    return out


def _recover_content(prompt: str) -> str:
    """从被套娃过的 prompt 里取回原始镜头内容。

    合成时新内容拼在前面，所以原句在最后一段。
    没有重复段落就说明这一行还没被合成过，整句都是内容。
    """
    segs = [s.strip() for s in prompt.split(", ") if s.strip()]
    if len(segs) == len(set(segs)):
        return prompt.strip()
    return segs[-1] if segs else prompt.strip()


def compose_frame_prompt(
    db: Session,
    shot: Shot,
    frame: FrameSpec,
    *,
    profile: WorldProfile,
    director: DirectorProfile | None,
    novel_id: str,
    chapter_order: int | None,
    scene: Scene | None,
) -> tuple[str, str, list[dict[str, Any]]]:
    """拼一帧的 (正向, 负向, 参考图)。五层来源全部可追溯。"""
    by_key, by_kind = _variant_index(db, novel_id, profile.id)
    params = frame.params_json or {}
    asset_keys: list[str] = list(params.get("asset_keys") or [])

    positive: list[str] = []
    negative: list[str] = []
    refs: list[dict[str, Any]] = []

    # ── 0 镜头内容：**排在最前** ──
    #
    # 这一句是「谁在哪做什么」，是这一镜之所以是这一镜的原因。
    # 排在后面的后果实测过：人物描述有四百字，图像模型顺着它画，
    # 出来的每一镜都是同一张肖像 —— 动作、场景、调度全都没了。
    #
    # 从 params.content 读，**不从 frame.prompt 读**。
    # frame.prompt 是本函数的产出；读它等于把上一次的合成结果
    # 当成这一次的镜头内容，每重拼一次就自我套娃一层。
    # 实跑时一个三人镜拼到 4034 字，同一批人物描述重复四遍，
    # 每遍还是不同批次抽取的旧值 —— 画面里那三个人各有四套衣服。
    content = str(params.get("content") or "").strip()
    if content:
        positive.append(content)

    # ── 1 画风（全书一份）──
    style = by_kind.get(AssetKindSpec.style.value)
    if style is not None:
        _spec, var = style
        if var.visual_prompt:
            positive.append(var.visual_prompt.strip())
        for url in _asset_urls(db, var.ref_asset_ids or [])[:1]:
            refs.append({"ref": {"url": url}, "role": "style", "weight": 0.45,
                         "tag": "world_style"})

    # ── 2 场景（同场景共用）──
    location = next(
        (by_key[k] for k in asset_keys
         if k in by_key and by_key[k][0].kind == AssetKindSpec.location),
        by_kind.get(AssetKindSpec.location.value),
    )
    if location is not None:
        _spec, var = location
        if var.visual_prompt:
            positive.append(var.visual_prompt.strip())
        for url in _asset_urls(db, var.ref_asset_ids or [])[:1]:
            refs.append({"ref": {"url": url}, "role": "scene", "weight": 0.5,
                         "tag": _spec.canonical_key})

    # ── 3 人物 ──
    for eid in (frame.entity_ids_json or [])[:3]:
        entity = db.get(WorldEntity, eid)
        if entity is None:
            continue
        look, look_refs = _entity_look(db, entity, profile.id, chapter_order)
        if look:
            positive.append(look)
        for url in _asset_urls(db, look_refs)[:1]:
            refs.append({"ref": {"url": url}, "role": "character", "weight": 0.8,
                         "tag": entity.canonical_key})

    # ── 4 服装与道具 ──
    for key in asset_keys:
        pair = by_key.get(key)
        if pair is None:
            continue
        spec, var = pair
        if spec.kind in {AssetKindSpec.style, AssetKindSpec.location}:
            continue
        if var.visual_prompt:
            positive.append(var.visual_prompt.strip())
        if var.negative_prompt:
            negative.append(var.negative_prompt.strip())
        for url in _asset_urls(db, var.ref_asset_ids or [])[:1]:
            role = "character" if spec.kind == AssetKindSpec.costume else "scene"
            refs.append({"ref": {"url": url}, "role": role, "weight": 0.6,
                         "tag": spec.canonical_key})

    # ── 4.35 时期覆盖 ──
    # 素材包给的是**基准形态**，而人物是沿时间变的：
    # 少年林凡与中年林凡不是同一套衣着兵器。
    # 有时期数据时用当章那一期的提示词覆盖基准 ——
    # 不覆盖的话主角从第一章到最后一章都是同一张脸同一身衣服。
    epoch_bits = _epoch_prompts(db, shot, profile, chapter_order)
    if epoch_bits:
        positive.extend(epoch_bits)

    # ── 4.4 画面文字 ──
    # signage 块既进译本也进画面。不带进提示词的话，
    # 生成出来的招牌要么是空白、要么是模型自己编的字 ——
    # 而档案里的 signage_rules（书写系统、字体、材质、避免什么）
    # 从建库那天起就没被用过，又是一处「存了不用」。
    # 招牌写错字体或写成源语言，是一眼可见的穿帮。
    sign = _signage_prompt(db, shot, profile)
    if sign:
        positive.append(sign)

    # ── 4.5 人物调度 ──
    # 素材包给的是**恒定属性**（长什么样、穿什么），这里给**瞬时状态**
    # （站哪、看谁、什么表情、在做什么）。两者分开来源、在提示词里拼合 ——
    # 混着存的话，「他握紧了剑」会污染角色素材，下一镜松了手也还是攥着的。
    staging = _staging_prompt(db, shot, frame)
    if staging:
        positive.append(staging)

    # ── 5 镜头语言 ──
    size = str(params.get("shot_size") or shot.shot_size or "ms")
    positive.append(SHOT_SIZE_PROMPT.get(size, "medium shot"))
    cam = shot.camera_json or {}
    if cam.get("angle"):
        positive.append(str(cam["angle"]).replace("_", " "))
    if cam.get("lens_mm"):
        positive.append(f"{cam['lens_mm']}mm lens")
    if director is not None:
        comp = director.composition_json or {}
        light = director.lighting_json or {}
        for key in ("framing", "depth"):
            if comp.get(key):
                positive.append(str(comp[key]).replace("_", " "))
        for key in ("key_ratio", "color_temp", "contrast", "grain"):
            if light.get(key):
                positive.append(f"{key.replace('_', ' ')}: {light[key]}")
        negative.extend(str(x).replace("_", " ") for x in (director.avoid_json or []))

    # 场景元信息
    if scene is not None:
        for val in (scene.time_of_day, scene.weather, scene.mood):
            if val:
                positive.append(str(val))

    negative.extend((profile.visual_json or {}).get("visual_dont") or [])
    negative.extend(["text", "watermark", "signature", "extra limbs", "deformed hands"])

    pos = ", ".join(dict.fromkeys(p for p in positive if p))
    neg = ", ".join(dict.fromkeys(str(n) for n in negative if n))
    # 同一 tag 只保留一张参考图，避免权重互相打架
    seen: set[str] = set()
    uniq_refs = []
    for r in refs:
        tag = str(r.get("tag") or "")
        if tag in seen:
            continue
        seen.add(tag)
        uniq_refs.append(r)
    return pos, neg, uniq_refs[:4]


def bind_and_compose(
    db: Session,
    plan: ShotPlan,
    transform: WorldTransform,
    *,
    shot_ids: Sequence[str] | None = None,
) -> ComposeResult:
    """为镜头绑定素材并写好首尾帧 prompt。不调 LLM、不花钱。"""
    profile = db.get(WorldProfile, transform.target_profile_id)
    if profile is None:
        raise PipelineError("目标世界观档案缺失")
    director = (
        db.get(DirectorProfile, plan.director_profile_id)
        if plan.director_profile_id else None
    )

    from app.models import Chapter, ScriptDoc

    doc = db.get(ScriptDoc, plan.script_doc_id)
    chapter = db.get(Chapter, doc.chapter_id) if doc else None
    chapter_order = chapter.order_no if chapter else None
    novel_id = chapter.novel_id if chapter else transform.novel_id

    q = select(Shot).where(Shot.shot_plan_id == plan.id).order_by(Shot.order_no)
    if shot_ids:
        q = q.where(Shot.id.in_(list(shot_ids)))
    shots = list(db.execute(q).scalars())

    by_key, _ = _variant_index(db, novel_id, profile.id)
    result = ComposeResult()

    for shot in shots:
        scene = db.get(Scene, shot.scene_id) if shot.scene_id else None
        frames = list(
            db.execute(
                select(FrameSpec).where(FrameSpec.shot_id == shot.id)
            ).scalars()
        )
        result.shots += 1

        for frame in frames:
            if frame.edited_by_human:
                continue
            params = frame.params_json or {}
            # asset_keys 是**字符串**列表（canonical_key），不是对象列表。
            # 用 as_items 取会把它们全滤掉 —— 于是 missing_assets 永远是空的，
            # 「缺素材」这道检查从来没真跑过，而它是分镜编译前最后一道闸
            for key in as_list(params.get("asset_keys")):
                if key not in by_key and key not in result.missing_assets:
                    result.missing_assets.append(key)

            if not params.get("content") and frame.prompt:
                # 存量修复：套娃之前的行只把镜头内容存在 prompt 里。
                # 已经被套过的行要取回原句 —— 它是最后那一段
                # （每次合成都把新内容拼在前面）。判断依据是有段落重复出现：
                # 分镜给的镜头内容是一句话，不会自我重复
                params = {**params, "content": _recover_content(frame.prompt)}
                frame.params_json = params
            pos, neg, refs = compose_frame_prompt(
                db, shot, frame, profile=profile, director=director,
                novel_id=novel_id, chapter_order=chapter_order, scene=scene,
            )
            frame.prompt = pos
            frame.negative_prompt = neg
            frame.ref_asset_ids = [
                r["ref"]["url"] for r in refs if r.get("ref", {}).get("url")
            ]
            merged = dict(params)
            merged["reference_images"] = refs
            frame.params_json = merged

            cjk = cjk_segments(pos)
            if cjk:
                result.untranslated.append({
                    "shot": shot.order_no, "role": frame.role.value,
                    "segments": cjk,
                })
            # **负面词同样要查。** 从前只查正向，于是文化包的 visual_dont
            # （「美式元素」「工业流水线」这类中文条目）一路直达模型 ——
            # 图像模型不认中文，这些条目既起不到排除作用，
            # 还可能被当成要画的内容。而正向那边的报表全绿，
            # 看的人有充分理由相信这一镜没有中文残留。
            cjk_neg = cjk_segments(neg)
            if cjk_neg:
                result.untranslated.append({
                    "shot": shot.order_no, "role": frame.role.value,
                    "side": "negative", "segments": cjk_neg,
                })

            for eid in frame.entity_ids_json or []:
                entity = db.get(WorldEntity, eid)
                if entity is None:
                    continue
                look, _ = _entity_look(db, entity, profile.id, chapter_order)
                if not look and entity.display_name not in result.missing_entity_visual:
                    result.missing_entity_visual.append(entity.display_name)

        # 绑定记录：镜头用了哪些素材，可回溯可人工改
        variant_ids = [
            by_key[k][1].id
            for k in ((frames[0].params_json or {}).get("asset_keys") or [])
            if k in by_key
        ] if frames else []
        existing = db.execute(
            select(ShotAssetBinding).where(ShotAssetBinding.shot_id == shot.id)
        ).scalars().first()
        if existing is None:
            db.add(ShotAssetBinding(
                id=new_id("sb"), shot_id=shot.id,
                entity_id=(frames[0].entity_ids_json or [None])[0] if frames else None,
                binding_role="subject", asset_variant_ids=variant_ids,
            ))
            result.bound += 1
        elif not existing.edited_by_human:
            existing.asset_variant_ids = variant_ids

    db.flush()
    return result


@dataclass
class FrameGenResult:
    submitted_first: int = 0
    submitted_last: int = 0
    skipped: int = 0
    blocked: list[str] = field(default_factory=list)
    estimated_cost: float | None = None
    requires_confirm: bool = False
    #: 这一批里哪些镜头只能用中性的英文变化。**不是 blocked** ——
    #: 图照样出得来，只是尾帧与首帧的差异会很小。
    #: 不报的话，「尾帧几乎没变」会被当成模型不给力，而不是缺英文渲染
    thin_derive: list[dict[str, Any]] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "submitted_first": self.submitted_first,
            "submitted_last": self.submitted_last,
            "skipped": self.skipped, "blocked": self.blocked,
            "thin_derive": self.thin_derive,
            "estimated_cost": self.estimated_cost,
            "requires_confirm": self.requires_confirm,
        }


def _plan_scope(db: Session, plan: ShotPlan) -> tuple[str | None, str | None]:
    """取该分镜所属的 novel / chapter，用于任务归属与成本归集。"""
    from app.models import Chapter, ScriptDoc

    doc = db.get(ScriptDoc, plan.script_doc_id)
    if doc is None:
        return None, None
    chapter = db.get(Chapter, doc.chapter_id)
    return (chapter.novel_id if chapter else None,
            chapter.id if chapter else None)


def generate_first_frames(
    db: Session, plan: ShotPlan, *, shot_ids: Sequence[str] | None = None,
    regenerate: bool = False, confirm_cost: bool = False,
    cost_threshold: float = 1.0,
) -> FrameGenResult:
    """提交首帧生成。尾帧要等首帧落地后才能派生，所以分两步。"""
    q = (
        select(FrameSpec, Shot)
        .join(Shot, Shot.id == FrameSpec.shot_id)
        .where(Shot.shot_plan_id == plan.id, FrameSpec.role == FrameRole.first)
        .order_by(Shot.order_no)
    )
    if shot_ids:
        q = q.where(Shot.id.in_(list(shot_ids)))
    rows = list(db.execute(q).all())

    result = FrameGenResult()
    pending = []
    for frame, shot in rows:
        if frame.asset_id and not regenerate:
            result.skipped += 1
            continue
        if not frame.prompt:
            result.blocked.append(f"镜头 {shot.order_no} 还没拼 prompt，请先绑定素材")
            continue
        pending.append((frame, shot))
    if not pending:
        return result

    est = estimate_cost(db, Capability.image_t2i, "first_frame", len(pending))
    result.estimated_cost = est
    if est is not None and est > cost_threshold and not confirm_cost:
        result.requires_confirm = True
        return result

    cfg = plan.config_json or {}
    width, height = _size_for(cfg.get("aspect_ratio") or "16:9")
    novel_id, chapter_id = _plan_scope(db, plan)

    for frame, shot in pending:
        params = frame.params_json or {}
        payload: dict[str, Any] = {
            "prompt": frame.prompt,
            "negative_prompt": frame.negative_prompt or "",
            "width": width, "height": height,
            "params": {"seed": params.get("seed")},
        }
        refs = list(params.get("reference_images") or [])
        cap = Capability.image_t2i
        anchor, refs = _split_identity_anchor(refs)
        if anchor is not None:
            # **带身份锚就走编辑能力，锚本身当底图。**
            #
            # 从前这里一律发 image.text_to_image，参考图只是随payload挂着 ——
            # 而纯文生图模型没有读参考图的通道，于是锚生成了、绑上了、
            # 交付清单里也列着，出来的脸却每张都不一样，
            # 且没有任何一处说过为什么。「存了但没注入」的又一例。
            #
            # 编辑模型的语义恰好就是这件事：给你这个人，把他放进这个场景。
            # 底图取主要人物的锚，其余人物的锚作为附加参考一并传下去。
            payload = {
                "image": anchor,
                "prompt": frame.prompt,
                "negative_prompt": frame.negative_prompt or "",
                "strength": IDENTITY_EDIT_STRENGTH,
                # 画幅必须显式带上：编辑模型不传就跟随底图，
                # 而锚是方形头肩像，出来的整批镜头会是 1:1
                "width": width, "height": height,
                "params": {"seed": params.get("seed")},
            }
            cap = Capability.image_i2i
        if refs:
            payload["reference_images"] = refs

        task = submit_task(
            db, cap, payload, purpose="first_frame",
            ref_kind="frame_spec", ref_id=frame.id,
            novel_id=novel_id, chapter_id=chapter_id, force=regenerate,
        )
        frame.gen_task_id = task.id
        frame.status = SpecStatus.generating
        result.submitted_first += 1

    db.flush()
    return result


def generate_last_frames(
    db: Session, plan: ShotPlan, *, shot_ids: Sequence[str] | None = None,
    strength: float = 0.35, regenerate: bool = False,
    confirm_cost: bool = False, cost_threshold: float = 1.0,
) -> FrameGenResult:
    """尾帧从首帧派生。首帧没落地的镜头会被跳过并报告。"""
    q = (
        select(FrameSpec, Shot)
        .join(Shot, Shot.id == FrameSpec.shot_id)
        .where(Shot.shot_plan_id == plan.id, FrameSpec.role == FrameRole.last)
        .order_by(Shot.order_no)
    )
    if shot_ids:
        q = q.where(Shot.id.in_(list(shot_ids)))
    rows = list(db.execute(q).all())

    result = FrameGenResult()
    pending: list[tuple[FrameSpec, Shot, str]] = []
    for frame, shot in rows:
        if frame.asset_id and not regenerate:
            result.skipped += 1
            continue
        first = db.execute(
            select(FrameSpec).where(
                FrameSpec.shot_id == shot.id, FrameSpec.role == FrameRole.first
            )
        ).scalars().first()
        if first is None or not first.asset_id:
            result.blocked.append(f"镜头 {shot.order_no} 的首帧还没生成")
            continue
        url = db.execute(
            select(Asset.url).where(Asset.id == first.asset_id)
        ).scalars().first()
        if not url:
            result.blocked.append(f"镜头 {shot.order_no} 的首帧图不可用")
            continue
        pending.append((frame, shot, url))
    if not pending:
        return result

    est = estimate_cost(db, Capability.image_i2i, "last_frame", len(pending))
    result.estimated_cost = est
    if est is not None and est > cost_threshold and not confirm_cost:
        result.requires_confirm = True
        return result

    novel_id, chapter_id = _plan_scope(db, plan)
    # 尾帧的画幅要和首帧一致。**不能靠跟随底图** ——
    # 首帧那边一旦是从方形身份锚编辑出来的，尾帧就会继承那个方形
    width_last, height_last = _size_for((plan.config_json or {}).get("aspect_ratio") or "16:9")
    deltas = _deltas_en(db, [s.id for _, s, _ in pending])
    for frame, shot, first_url in pending:
        params = frame.params_json or {}
        instruction, why = _derive_en(frame, deltas.get(shot.id))
        if why:
            result.thin_derive.append({"shot": shot.order_no, "why": why})
        payload: dict[str, Any] = {
            "image": {"url": first_url},
            # 同一段描述 + 变化说明；同 seed 提升连贯度
            "prompt": f"{frame.prompt or ''} ; {instruction}".strip(" ;"),
            "negative_prompt": frame.negative_prompt or "",
            "strength": strength,
            "width": width_last, "height": height_last,
            "params": {"seed": params.get("seed")},
        }
        refs = params.get("reference_images") or []
        if refs:
            payload["reference_images"] = refs

        task = submit_task(
            db, Capability.image_i2i, payload, purpose="last_frame",
            ref_kind="frame_spec", ref_id=frame.id,
            novel_id=novel_id, chapter_id=chapter_id, force=regenerate,
        )
        frame.gen_task_id = task.id
        frame.status = SpecStatus.generating
        result.submitted_last += 1

    db.flush()
    return result



def _deltas_en(db: Session, shot_ids: list[str]) -> dict[str, list[str]]:
    """各镜首尾之间变了什么，**英文**。"""
    from app.models import ShotMotion

    if not shot_ids:
        return {}
    return {
        m.shot_id: [str(x) for x in (m.deltas_en_json or []) if x]
        for m in db.execute(
            select(ShotMotion).where(ShotMotion.shot_id.in_(shot_ids))
        ).scalars()
    }


def _derive_en(frame: FrameSpec, deltas: list[str] | None) -> tuple[str, str]:
    """尾帧的「变了什么」，返回（英文指令, 需要报告的问题）。

    **优先用运动描述的 deltas_en。** `ShotMotion.deltas_en_json` 的注释写着
    「i2i 读的是这一条」，但这里从前读的是 `derive_instruction` —— 那是中文，
    由分镜编译时的模型写的（「门外脚步声由远及近，轻重分明」）。
    它被直接接在英文提示词后面送进图像模型，而图像模型不认中文：
    这一段既起不到指导作用，还可能被画成一片汉字纹样。
    设计了但没接线，又一例。

    没有 deltas_en 时**不回落到中文**。宁可给一句中性的英文，
    也不要把读不懂的文字混进提示词 —— 但要把这一镜报出来，
    否则「尾帧和首帧几乎一样」会被当成模型不给力，而不是缺英文渲染。
    """
    if deltas:
        return ", ".join(deltas), ""
    raw = (frame.derive_instruction or "").strip()
    if raw and not _CJK.search(raw):
        return raw, ""
    fallback = "slight natural progression of the moment"
    if raw:
        return fallback, f"派生指令只有中文：{raw[:40]}"
    return fallback, "这一镜没有派生指令，尾帧只能给一句中性变化"

def sync_frame_assets(db: Session, plan: ShotPlan) -> dict[str, int]:
    """把已完成任务的产图挂回 FrameSpec。回调/轮询之后调一次。"""
    from app.models import GenTask, TaskStatus

    rows = db.execute(
        select(FrameSpec).join(Shot, Shot.id == FrameSpec.shot_id)
        .where(Shot.shot_plan_id == plan.id)
    ).scalars().all()
    updated = 0
    for frame in rows:
        if not frame.gen_task_id:
            continue
        task = db.get(GenTask, frame.gen_task_id)
        if task is None or task.status != TaskStatus.succeeded:
            continue
        asset_id = db.execute(
            select(Asset.id).where(Asset.gen_task_id == task.id).limit(1)
        ).scalars().first()
        # 按**当前任务**的产图判断，不是「有没有图」。
        # 判「有图就跳过」的话，regenerate 之后挂着的还是旧图 ——
        # 重出一版花了钱，看到的却是上一版
        if asset_id and asset_id != frame.asset_id:
            frame.asset_id = asset_id
            frame.status = SpecStatus.ready
            updated += 1
    db.flush()
    return {"frames_updated": updated, "checked": len(rows)}


#: 用锚做底图时的改动幅度。身份锚是**正面素颜头肩像**，
#: 要变成一个带服装、环境、光线的完整画面，改动必然大 ——
#: 尾帧那种 0.35 会把人留在灰背景棚里。
#: 但也不能给到 1：那等于重画，脸就丢了。
IDENTITY_EDIT_STRENGTH = 0.75


def _split_identity_anchor(
    refs: list[dict[str, Any]],
) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    """挑出当底图的人物锚，返回（底图引用, 其余参考）。

    只认 character 角色 —— 风格图与构图图不能当底图，
    拿风格参考去当底图，出来的是「那张风格图被改了几笔」，不是这一镜。

    多人同框时取第一张：编辑模型按出现顺序理解主次，
    主要人物做底图、其余作附加参考，比平铺一堆图更稳。
    """
    base = next((r for r in refs
                 if isinstance(r, dict) and str(r.get("role")) == "character"
                 and isinstance(r.get("ref"), dict)), None)
    if base is None:
        return None, refs
    return base["ref"], [r for r in refs if r is not base]


def _size_for(aspect: str) -> tuple[int, int]:
    return {
        "16:9": (1280, 720), "9:16": (720, 1280),
        "4:3": (1152, 864), "1:1": (1024, 1024),
        "2.39:1": (1280, 536),
    }.get(aspect, (1280, 720))
