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
    Asset, AssetKindSpec, AssetSpec, AssetVariant, CrewSheet, DirectorProfile,
    EntityChapterState, EntityWorldVisual, FrameRole, FrameSpec, ReviewStatus,
    Scene, Shot, ShotAssetBinding, ShotMotion, ShotPlan, SpecStatus, WorldEntity,
    WorldProfile, WorldTransform,
)
from app.pipelines.base import PipelineError, as_items, as_list, checkpoint, fingerprint
from app.pipelines.epochs import compose_epoch_prompt, resolve_epoch
from app.pipelines.shot_plan import SHOT_SIZE_PROMPT
from app.worldview import cinematography as cine

log = logging.getLogger(__name__)


@dataclass
class ComposeResult:
    shots: int = 0
    bound: int = 0
    missing_assets: list[str] = field(default_factory=list)
    missing_entity_visual: list[str] = field(default_factory=list)
    #: 人物有文字外观但还没有完整三视角。没有参考集仍允许预览 prompt，
    #: 但首帧生成会硬拦，避免再生产“每镜换一张脸”的废片。
    missing_character_references: list[dict[str, Any]] = field(default_factory=list)
    #: 提示词里还留着的中文片段。**图像模型不认中文** ——
    #: 喂中文出来的是汉字纹样不是画面。哪条产线还欠英文渲染，看这里
    untranslated: list[dict[str, Any]] = field(default_factory=list)
    #: 调度／制作单／运动没齐的镜头。prompt 可以预览，但不允许花钱出图。
    missing_production: list[dict[str, Any]] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "shots": self.shots, "bound": self.bound,
            "missing_assets": self.missing_assets,
            "missing_entity_visual": self.missing_entity_visual,
            "missing_character_references": self.missing_character_references,
            "untranslated": self.untranslated,
            "missing_production": self.missing_production,
        }


_VISUAL_CREW_ROLES = (
    "cinematography", "lighting", "production_design", "costume_makeup",
    "vfx", "color_grading",
)


def _production_inputs(
    db: Session, shot: Shot,
) -> tuple[list[str], ShotMotion | None, list[str]]:
    """取真正会进画面的制作信息，并报出缺口。"""
    rows = {
        s.role: s for s in db.execute(
            select(CrewSheet).where(CrewSheet.shot_id == shot.id)
        ).scalars()
    }
    prompts: list[str] = []
    missing: list[str] = []
    for role in _VISUAL_CREW_ROLES:
        sheet = rows.get(role)
        if (sheet is None or not sheet.prompt_en
                or sheet.missing_json or sheet.rejected_json):
            missing.append(role)
        else:
            prompts.append(sheet.prompt_en.strip())
    motion = db.execute(
        select(ShotMotion).where(ShotMotion.shot_id == shot.id)
    ).scalars().first()
    if (motion is None or not motion.motion_prompt_en
            or len(motion.deltas_en_json or []) < 2
            or not motion.start_frame_en or not motion.end_frame_en):
        missing.append("motion")
    return prompts, motion, missing


def _production_revision(
    prompts: Sequence[str], motion: ShotMotion | None,
) -> str:
    return fingerprint(
        *prompts,
        motion.motion_prompt_en if motion else "",
        *((motion.deltas_en_json or []) if motion else []),
        motion.start_frame_en if motion else "",
        motion.end_frame_en if motion else "",
    )


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
    assets = {a.id: a.url for a in db.execute(
        select(Asset).where(Asset.id.in_(list(ids)))
    ).scalars()}
    return [assets[i] for i in ids if assets.get(i)]



def _entity_look(
    db: Session, entity: WorldEntity, profile_id: str, chapter_order: int | None,
    facing: str | None = None, shot_size: str | None = None,
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
        # **有锚时重新拼，不用预存的那一份。**
        #
        # compose_epoch_prompt 的 has_anchor 会略去脸的那几项 ——
        # 参考图负责「是谁」，文字再描述一遍只会抢权重。
        # 但预存的 visual_prompt 一存在，那条逻辑就永远不执行：
        # `epoch.visual_prompt or compose_...` 短路了。
        #
        # 后果很具体：镜 6 的提示词是「a man seated behind a door」
        # 加上六十个词的脸型体型衣着 —— 场景四个词、人物六十个词，
        # 模型出的是一张灰底棚拍立姿，而不是「推门而出」。
        # 写了没接线的又一例。
        #
        # 锁定的仍然用预存：那是人手写的，不该被覆盖。
        text = (epoch.visual_prompt
                if (epoch.locked or not anchor)
                else compose_epoch_prompt(epoch, "character", has_anchor=True))
        text = text or compose_epoch_prompt(
            epoch, "character", has_anchor=bool(anchor))
        # Send individual views, never the contact sheet's layout.
        from app.pipelines.identity import character_reference_asset_id
        view_ref = character_reference_asset_id(epoch, facing, shot_size)
        # The current period reference set is the character material selected
        # for production. Mixing it with an older, independently generated
        # identity portrait can introduce two different faces for one person.
        refs = [view_ref] if view_ref else ([anchor] if anchor else [])
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


def _facing_for(db: Session, shot_id: str, entity_id: str) -> str | None:
    from app.models import ShotPerformance

    row = db.execute(
        select(ShotPerformance.facing).where(
            ShotPerformance.shot_id == shot_id,
            ShotPerformance.entity_id == entity_id,
        )
    ).scalars().first()
    return row.value if row is not None else None


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
        # 背对镜头时不写表情，也不写视线落点 —— 那张脸不在画面里。
        # 「seen from behind, stern expression, cold gaze, looking at offscreen」
        # 是互相矛盾的一串指令，模型只能折中：给一张似正似背的脸，
        # 姿态含糊、五官平板，正是那种一眼假的塑料感。
        # 矛盾不会报错，它只是让每一镜都差一点。
        face_visible = p.facing is not Facing.away
        if expr and face_visible:
            seg.append(str(expr))
        if act:
            seg.append(str(act))
        if p.gaze_target and face_visible:
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

    # 镜头制作单不是后台里「可以看的报表」，而是出图的直接输入。
    # 以前八工种都已经落库，但首帧合成一条都没读，灯光、美术、服化和视效
    # 只能由生图模型自由发挥。这里只注入已通过完整性验收的英文单。
    crew_prompts, motion, _missing_production = _production_inputs(db, shot)
    positive.extend(crew_prompts)
    if motion is not None:
        endpoint = (motion.end_frame_en if frame.role == FrameRole.last
                    else motion.start_frame_en)
        if endpoint:
            positive.append(endpoint.strip())

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
        None,
    )
    if location is not None:
        _spec, var = location
        if var.visual_prompt:
            positive.append(var.visual_prompt.strip())
        for url in _asset_urls(db, var.ref_asset_ids or [])[:1]:
            refs.append({"ref": {"url": url}, "role": "scene", "weight": 0.5,
                         "tag": _spec.canonical_key})

    # ── 3 人物 ──
    #
    # **选角相貌要在这里也说一遍。**
    # 抽取那一步把族裔从不变项里剥干净了（「族裔由目标圈层统一决定，
    # 在出图那一步补上」），而「那一步」从前只有身份锚补了，分镜帧没补：
    # 六千多字的首帧提示词里一个 American 都没有。
    #
    # 模型于是照着场景自己脑补 —— 学校走廊这段场景描述译自中文原著，
    # 出来就是一屋子亚洲脸，而参考素材明明是白人。
    # 「参考素材对、分镜不对」的全部原因就在这一句的缺席。
    if frame.entity_ids_json:
        from app.pipelines.identity import cast_look

        who = cast_look(profile) if profile is not None else ""
        if who:
            positive.append(f"all characters are {who}")
    # **按表演单排序，不按 entity_names 的原序。**
    # `entity_ids_json` 抄的是模型随手列的一串名字，不带主次语义；
    # 而 `_split_identity_anchor` 却按「第一个就是这一镜的主角」取底图
    # （那条注释自己也写着「那是个巧合，不是约束」）。
    # 实跑的后果是整章 36 镜锚到了 offscreen／background 的人身上：
    # 拿一个不在画面里的角色的脸去编辑这一镜，出来仍是一张合理的图，
    # 没有任何一步报错。
    #
    # 谁是主体分镜早就写好了（speech_role + position），照着排即可 ——
    # 不需要在 WorldEntity 上另加主次字段。
    subject = shot_subject(db, shot)
    for eid in _by_staging(db, shot, frame.entity_ids_json or [], subject):
        entity = db.get(WorldEntity, eid)
        if entity is None:
            continue
        look, look_refs = _entity_look(
            db, entity, profile.id, chapter_order,
            _facing_for(db, shot.id, entity.id),
            str(params.get("shot_size") or shot.shot_size or ""),
        )
        if look:
            positive.append(look)
        for index, url in enumerate(_asset_urls(db, look_refs)[:2]):
            # **标明这是身份锚。** 服装素材的参考图也用 role="character"
            #（那是对的：衣服要贴在人身上），于是「谁当 i2i 的底图」
            # 就只由 refs 的拼装顺序决定 —— 人物段恰好排在服装段前面。
            # 那是个巧合，不是约束：以后谁调一下两段的顺序，
            # 底图就会从「这个人的脸」变成「一件衣服」，
            # 而出来的图仍然是一张合理的图，没人会发现。
            refs.append({
                "ref": {"url": url}, "role": "character",
                "weight": 0.8 if index == 0 else 0.68,
                # **identity 只打在这一镜的主体身上。**
                # 从前每个人的首张都标 identity，于是「谁是身份锚」
                # 退化成「谁排在数组前面」—— 而那个顺序来自模型随手
                # 列的 entity_names。现在主体由表演单定（见 shot_subject），
                # 标记跟着它走，供应商侧照这个标记选第二张参考图。
                "identity": index == 0 and eid == subject,
                "tag": (entity.canonical_key if index == 0
                        else f"{entity.canonical_key}.view"),
            })

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
            role = "costume" if spec.kind == AssetKindSpec.costume else "prop"
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
        # 枚举要翻成摄影师的说法再送。原样拼出来是
        # 「key ratio: hard_8:1, color temp: cool_with_warm_practicals」——
        # 模型读不懂就当噪声跳过，灯光实际上由它自己发挥，
        # 而报表上写着「已注入」。palette 更是从建库起就没被读过。
        positive.extend(cine.render_composition(director.composition_json))
        positive.extend(cine.render_lighting(director.lighting_json))
        negative.extend(cine.render_avoid(director.avoid_json))

    # 场景元信息
    if scene is not None:
        for val in (scene.time_of_day, scene.weather, scene.mood):
            if val:
                positive.append(str(val))

    negative.extend((profile.visual_json or {}).get("visual_dont") or [])
    negative.extend(["text", "watermark", "signature", "extra limbs", "deformed hands"])
    # 塑料感不是风格问题，是默认交付物：不挡就是塑料三维渲染 + AI 磨皮 +
    # 均匀无方向光。挡掉它们，再给一个成片质感锚。
    negative.extend(cine.PLASTIC_NEGATIVES)
    # 人物参考图是一张三要素设定图（正面/侧面/面部拼在一起）。
    # 不挡的话模型会连同**版式**一起抄，出来一张分格设定图而不是一个镜头。
    negative.extend(["character sheet", "turnaround sheet", "contact sheet",
                     "multi-panel", "split screen", "collage", "grid layout"])
    positive.append("One continuous cinematic frame, one camera viewpoint, no panels or borders. "
                    "Use reference images only for identity, clothing and location, never their layout. "
                    "Preserve the location geometry, doors, windows and lighting across this scene.")
    positive.append(cine.GRADE_ANCHOR)

    # **中文一个字都不能进图像提示词。** 图像模型不认中文 ——
    # 好一点的当噪声跳过，差一点的把汉字当纹样画进画面。
    # 负向里以前一直漏着「美式元素, 现代都市, 东亚建筑」这类整条中文，
    # 等于这几条约束从来没生效过，而没有任何一处会报错。
    # 丢掉的中文全部记进 result.untranslated，知道哪条产线还欠英文。
    pos = ", ".join(dict.fromkeys(p for p in positive if p and not _CJK.search(p)))
    neg = ", ".join(dict.fromkeys(
        str(n) for n in negative if n and not _CJK.search(str(n))))
    # 同一 tag 只保留一张参考图，避免权重互相打架
    seen: set[str] = set()
    uniq_refs = []
    for r in refs:
        tag = str(r.get("tag") or "")
        if tag in seen:
            continue
        seen.add(tag)
        uniq_refs.append(r)
    return pos, neg, uniq_refs


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
    # Resolve a location once per scene across the whole plan, including when
    # composing only a later shot. Conflicting explicit locations stay visible.
    scene_locations: dict[str, set[str]] = {}
    for member, spec in db.execute(
        select(Shot, FrameSpec).join(FrameSpec, FrameSpec.shot_id == Shot.id)
        .where(Shot.shot_plan_id == plan.id)
    ).all():
        for key in (spec.params_json or {}).get("asset_keys", []):
            if key in by_key and by_key[key][0].kind == AssetKindSpec.location:
                scene_locations.setdefault(member.scene_id, set()).add(key)

    for shot in shots:
        scene = db.get(Scene, shot.scene_id) if shot.scene_id else None
        frames = list(
            db.execute(
                select(FrameSpec).where(FrameSpec.shot_id == shot.id)
            ).scalars()
        )
        result.shots += 1
        crew_prompts, motion, missing_production = _production_inputs(db, shot)
        revision = _production_revision(crew_prompts, motion)
        if missing_production:
            result.missing_production.append({
                "shot": shot.order_no, "missing": missing_production,
            })

        for frame in frames:
            if frame.edited_by_human:
                continue
            params = dict(frame.params_json or {})
            keys = list(params.get("asset_keys") or [])
            locations = scene_locations.get(shot.scene_id, set())
            if len(locations) == 1 and not any(
                k in by_key and by_key[k][0].kind == AssetKindSpec.location for k in keys
            ):
                params["asset_keys"] = keys + sorted(locations)
                frame.params_json = params
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
            if frame.asset_id and params.get("reference_images") != refs:
                merged["needs_regeneration"] = True
            merged["reference_images"] = refs
            merged["production_revision"] = revision
            # 完整参考集是生成闸门，不是提示性徽章。一个镜头即使只用正脸，
            # 后续反打/侧移也一定会需要转角图；临到那时再独立生成，衣服和体型
            # 已经漂了。先把人物基础素材做完，再允许烧图像额度。
            missing_refs: list[str] = []
            from app.pipelines.identity import CHARACTER_REFERENCE_VIEWS
            for eid in frame.entity_ids_json or []:
                entity = db.get(WorldEntity, eid)
                if entity is None:
                    continue
                epoch = resolve_epoch(db, eid, profile.id, chapter_order)
                views = ((epoch.reference_set_json or {}).get("views") or {}) \
                    if epoch is not None else {}
                if any(not isinstance(views.get(view), dict)
                       or not views[view].get("asset_id")
                       for view in CHARACTER_REFERENCE_VIEWS):
                    missing_refs.append(entity.display_name)
            merged["missing_character_references"] = list(dict.fromkeys(missing_refs))
            if missing_refs:
                result.missing_character_references.append({
                    "shot": shot.order_no, "role": frame.role.value,
                    "entities": list(dict.fromkeys(missing_refs)),
                })
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
                look, _ = _entity_look(
                    db, entity, profile.id, chapter_order,
                    _facing_for(db, shot.id, entity.id),
                )
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


#: 站位 → 画面横向位置（0 左边缘，1 右边缘）。
#: 表演单里本来就有这一项，不需要再上人脸检测。
_POSITION_X = {
    "far_left": 0.12, "left": 0.24, "center_left": 0.38, "center": 0.50,
    "center_right": 0.62, "right": 0.76, "far_right": 0.88,
}
#: 这些站位说明这个人不在画面主体里，裁他没有意义
_POSITION_ABSENT = frozenset({"offscreen", "background", "off_screen"})


#: 走这条裁切路径的景别。中近景也算 —— 它同样是从宽景里挑一个人
_CLOSE_SIZES = frozenset({"ecu", "cu", "mcu"})


def _position_in_previous(db: Session, plan: ShotPlan, shot: Shot,
                          entity_id: str) -> str | None:
    """这个人在上一镜里站在哪。裁切要按那一镜的站位裁，不是按本镜的。"""
    from app.models import ShotPerformance

    prev = db.execute(select(Shot).where(
        Shot.shot_plan_id == plan.id, Shot.scene_id == shot.scene_id,
        Shot.order_no < shot.order_no).order_by(Shot.order_no.desc()).limit(1)
    ).scalars().first()
    if prev is None:
        return None
    row = db.execute(select(ShotPerformance).where(
        ShotPerformance.shot_id == prev.id,
        ShotPerformance.entity_id == entity_id)).scalars().first()
    pos = _pos_key(row.position) if row else ""
    return pos if pos in _POSITION_X else None


def _local_path_of(db: Session, asset):
    """产物的本地文件路径。取不到就返回 None，调用方退回整张。"""
    from pathlib import Path

    from app.capability.mediastore import media_root

    url = getattr(asset, "url", "") or ""
    if "/media/" not in url:
        return None
    path = Path(media_root()) / url.rsplit("/media/", 1)[-1].split("?")[0]
    return path if path.exists() else None


def _pos_key(value) -> str:
    """站位枚举 → 查表用的字符串。

    **position 是枚举，str() 出来是 'StagePosition.center' 而不是
    'center'。** 直接拿去查表全部落空 —— 而这一层不会报错，
    只是裁切永远不触发，看起来像「这个功能没写」。
    """
    return str(getattr(value, "value", value) or "").strip().lower()


#: 台词身份的主次。**这一镜拍的是谁，分镜早就写好了** ——
#: 说话的人是主体，被说的人次之，旁听的再次，沉默的垫底。
_SPEECH_RANK = {"speaker": 0, "addressee": 1, "listener": 2, "silent": 3}


def shot_subject(db: Session, shot: Shot) -> str | None:
    """这一镜拍的是谁 —— 全流程唯一的判据。

    **答案在表演单里，不用再猜，也不该各猜各的。**
    ShotPerformance 每一条都带着 speech_role（speaker／addressee／
    listener／silent／absent）和 position，是分镜阶段就定好的事实。

    从前这件事有三套互不相干的答案，实跑的镜 2 里它们指向三个人：

        身份锚（i2i 的底图）  entity_names 的第一个   → 李爽
        特写裁切主体          站位最靠近中心           → 高个少年
        表演单写的            speaker @ center        → 高个少年
                              李爽 @ offscreen

    第一套最糟：`entity_names` 是模型随手列的一串名字，不带任何主次
    语义，而 `_split_identity_anchor` 却按「第一个就是主角」来取底图。
    于是整章 36 镜把底图锚到了画面里根本没有的人身上 —— 拿一张
    offscreen 角色的脸去编辑出这一镜，出来仍是一张合理的图，
    没有任何一步报错。

    判据：先排除不在画面里的（absent／offscreen／background），
    再按台词身份排，同级才比谁更靠近画面中心。
    """
    from app.models import ShotPerformance

    best, best_key = None, None
    for p in db.execute(select(ShotPerformance).where(
            ShotPerformance.shot_id == shot.id)).scalars():
        role = _pos_key(p.speech_role)
        pos = _pos_key(p.position)
        if role == "absent" or pos in _POSITION_ABSENT:
            continue
        x = _POSITION_X.get(pos)
        if x is None:
            # foreground 之类没有横向坐标的站位仍然在画面里，
            # 只是比不出左右 —— 当成中心参与排序，别整条丢掉
            x = 0.5
        key = (_SPEECH_RANK.get(role, 4), abs(x - 0.5))
        if best_key is None or key < best_key:
            best, best_key = p.entity_id, key
    return best


def _by_staging(db: Session, shot: Shot, entity_ids: list[str],
                subject: str | None) -> list[str]:
    """把这一镜的出场人物按表演单排序，主体排第一。

    只重排，不增删 —— 提示词里每个人的相貌段都还要照出，
    动的只是「谁当 i2i 的底图」这一个决定。
    """
    from app.models import ShotPerformance

    rank: dict[str, tuple[int, float]] = {}
    onscreen: list[str] = []
    for p in db.execute(select(ShotPerformance).where(
            ShotPerformance.shot_id == shot.id)).scalars():
        pos = _pos_key(p.position)
        x = _POSITION_X.get(pos, 0.5)
        absent = (_pos_key(p.speech_role) == "absent"
                  or pos in _POSITION_ABSENT)
        rank[p.entity_id] = (
            _SPEECH_RANK.get(_pos_key(p.speech_role), 4) + (10 if absent else 0),
            abs(x - 0.5))
        if not absent:
            onscreen.append(p.entity_id)

    # **出场名单要跟表演单对齐。** 两份是各出各的：名单抄自模型随手列的
    # `entity_names`，表演单是另一次产出，谁也没校对谁。整章 21 镜里
    # 名单上的人在表演单里压根不存在，另有几镜名单只写了一个 absent 的人。
    #
    # 而**提示词的站位句本来就出自表演单**（见 _blocking 那一段），
    # 相貌段却出自名单 —— 于是同一条提示词自相矛盾：站位写着
    # 「谢文东在画面中心」，相貌段描述的是一个这一镜里不在场的李爽。
    # 出来的图既不报错也不缺东西，只是人不对。
    #
    # 站位、朝向、表演都只有表演单有，它才是「画面里有谁」的权威。
    # 名单上多出来的人仍然保留（可能是表演单漏写），但排在在场的人后面，
    # 绝不让它当上 i2i 的底图。
    merged = list(dict.fromkeys([*onscreen, *entity_ids]))

    def key(eid: str) -> tuple[int, int, float]:
        # 主体绝对在前；表演单里没这个人的排到最后，别让它当上底图
        head, tail = rank.get(eid, (9, 9.0))
        return (0 if eid == subject else 1, head, tail)

    return sorted(merged, key=key)


def _closeup_subject(db: Session, shot: Shot) -> str | None:
    """特写裁的是谁。与身份锚同源 —— 见 shot_subject。"""
    return shot_subject(db, shot)


def _crop_subject_from(path, position: str, out_w: int, out_h: int):
    """从上一镜的成品里裁出这个人所在的区域。

    **宽景切特写是 i2i 做不好的事。** 整张宽景当底图时，模型要同时
    重构图和换景别，实跑的结果是它挑错了人：首领留在背景里，前景换成了
    一个没出现过的人。

    裁过去就不用它重构图了 —— 底图本身就是那个人的近景，模型只要把它
    画清楚。人在哪由表演单的站位说了算，那是分镜阶段就定好的。
    """
    from PIL import Image

    img = Image.open(path).convert("RGB")
    W, H = img.size
    cx = _POSITION_X.get(str(position or "").lower(), 0.5) * W
    # 裁一块符合输出画幅的区域，宽度取原图的 45% —— 再窄就只剩一张脸，
    # 模型失去「他站在走廊里」这个上下文，背景又会自己编
    cw = max(64, int(W * 0.45))
    ch = max(64, int(cw * out_h / max(1, out_w)))
    if ch > H:
        ch = H
        cw = max(64, int(ch * out_w / max(1, out_h)))
    left = int(min(max(0, cx - cw / 2), W - cw))
    # 纵向偏上：脸在上半部分，从正中裁会把头切掉
    top = int(min(max(0, H * 0.18), H - ch))
    return img.crop((left, top, left + cw, top + ch))


def _continuity_anchor(db: Session, plan: ShotPlan, shot: Shot) -> Asset | None:
    """Use an earlier finished frame from this plan and scene as the set anchor."""
    if not shot.scene_id:
        return None
    target = db.execute(select(FrameSpec).where(
        FrameSpec.shot_id == shot.id, FrameSpec.role == FrameRole.first
    )).scalars().first()
    target_cast = set(target.entity_ids_json or []) if target else set()
    rows = db.execute(select(FrameSpec).join(Shot, Shot.id == FrameSpec.shot_id).where(
        Shot.shot_plan_id == plan.id, Shot.scene_id == shot.scene_id,
        Shot.order_no < shot.order_no, FrameSpec.role == FrameRole.first,
        FrameSpec.status == SpecStatus.ready, FrameSpec.asset_id.isnot(None),
    ).order_by(Shot.order_no)).scalars()
    for frame in rows:
        # A reverse shot of another speaker must keep that speaker's identity.
        # Single-reference editors otherwise turn the previous speaker into them.
        if not target_cast.issubset(set(frame.entity_ids_json or [])):
            continue
        if not (frame.params_json or {}).get("needs_regeneration"):
            asset = db.get(Asset, frame.asset_id)
            if asset and asset.url:
                return asset
    return None


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
        if frame.asset_id and not regenerate and not (frame.params_json or {}).get("needs_regeneration"):
            result.skipped += 1
            continue
        if not frame.prompt:
            result.blocked.append(f"镜头 {shot.order_no} 还没拼 prompt，请先绑定素材")
            continue
        crew_prompts, motion, missing = _production_inputs(db, shot)
        if missing:
            result.blocked.append(
                f"镜头 {shot.order_no} 缺生产前置：{'、'.join(missing)}"
            )
            continue
        current_revision = _production_revision(crew_prompts, motion)
        if (frame.params_json or {}).get("production_revision") != current_revision:
            result.blocked.append(
                f"镜头 {shot.order_no} 的制作单或运动已变更，请先重新「绑定素材并拼 prompt」"
            )
            continue
        missing_refs = list(
            (frame.params_json or {}).get("missing_character_references") or [])
        if missing_refs:
            result.blocked.append(
                f"镜头 {shot.order_no} 缺人物三视角参考：{'、'.join(missing_refs)}")
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
            "params": {"seed": params.get("seed"),
                       "style": _plan_style(db, plan)},
        }
        refs = list(params.get("reference_images") or [])
        cap = Capability.image_t2i
        scene_head = False
        continuity = _continuity_anchor(db, plan, shot)
        if continuity:
            anchor = {"url": continuity.url}
            crop_note = None
            # **特写用上一镜里那个人的局部，不用整张宽景。**
            #
            # 整张宽景当底图时，模型要同时重构图和换景别 —— 实跑的结果是
            # 它挑错了人：首领留在了背景里，前景换成一个没出现过的人。
            # 裁过去就不必重构图，底图本身就是那个人的近景。
            # 他站在哪由表演单的站位说了算，那是分镜阶段就定好的，
            # 不需要再上人脸检测。
            size = str(params.get("shot_size") or shot.shot_size or "").lower()
            if size in _CLOSE_SIZES:
                who = _closeup_subject(db, shot)
                prev_pos = _position_in_previous(db, plan, shot, who) if who else None
                src = _local_path_of(db, continuity)
                if prev_pos and src is not None:
                    try:
                        from io import BytesIO

                        from app.capability import mediastore

                        crop = _crop_subject_from(src, prev_pos, width, height)
                        buf = BytesIO()
                        crop.save(buf, format="JPEG", quality=94)
                        item = mediastore.store_bytes(buf.getvalue(), mime="image/jpeg")
                        anchor = {"url": item["url"]}
                        crop_note = f"{prev_pos}@上一镜"
                    except Exception as exc:      # noqa: BLE001 —— 裁不了就用整张
                        log.warning("特写裁切失败，退回整张连贯锚：%s", exc)
            if params.get("continuity_only"):
                refs = []
            else:
                refs = [r for r in refs if r.get("role") != "scene"]
            frame.params_json = {**params, "continuity_anchor_asset_id": continuity.id,
                                 "continuity_anchor_url": continuity.url,
                                 "continuity_crop": crop_note}
        else:
            # **场景首镜也走「底图＋身份参考」，不再拿人物肖像当底图。**
            # 底图给场景，脸给参考图 —— 和连贯镜同一条路子。
            anchor, refs = _split_scene_anchor(refs)
            scene_head = anchor is not None
            if anchor is None:
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
            # **两种底图语义不同，参数不能共用。**
            #   身份锚：一张人物肖像 —— 语义是「把这个人放进这个场景」，
            #           整段场景描述 + 高强度是对的
            #   连贯锚：上一镜的画面 —— 里面已经有正确的场景、人和光，
            #           要动的只是机位和这一拍的动作
            #
            # 从前两种都发整段画面描述、都用 0.75，于是连贯锚被整张重画：
            # 镜 2 从走廊换成了临街的另一条走廊，人也换成了一个没出现过的
            # 金发少年 —— 而连贯锚明明传进去了。
            if continuity:
                shot_text = str((params.get("content") or "")).strip() or frame.prompt or ""
                prompt_text = (
                    f"Reframe this same scene to: {shot_text}. "
                    "Keep the same location and set, the same people with identical "
                    "faces, hair and clothing, and the same lighting. "
                    "Change only the framing and the described action.")
                strength_used = CONTINUITY_EDIT_STRENGTH
            elif scene_head:
                # 底图是这个场景的空景，要做的是把人摆进去。
                # **祈使句**，和连贯镜一致 —— 供应商自述写着
                # 「提示词要写成指令，而不是画面描述」。
                prompt_text = (
                    "Keep this location exactly as it is — same architecture, "
                    "fixtures, furniture and lighting — and stage this shot in it. "
                    "Give each person the face, hair and clothing of the "
                    f"reference images. {_instruct_head(frame.prompt)}")
                strength_used = SCENE_EDIT_STRENGTH
            else:
                prompt_text = frame.prompt
                strength_used = IDENTITY_EDIT_STRENGTH
            payload = {
                "image": anchor,
                "prompt": prompt_text,
                "negative_prompt": frame.negative_prompt or "",
                "strength": strength_used,
                # 画幅必须显式带上：编辑模型不传就跟随底图，
                # 而锚是方形头肩像，出来的整批镜头会是 1:1
                "width": width, "height": height,
                "params": {"seed": params.get("seed"),
                           "style": _plan_style(db, plan),
                           "ref_megapixels": 0.4},
            }
            cap = Capability.image_i2i
        if refs:
            payload["reference_images"] = refs
        if params.get("style") or cfg.get("style"):
            payload["style"] = params.get("style") or cfg["style"]

        task = submit_task(
            db, cap, payload, purpose="first_frame",
            ref_kind="frame_spec", ref_id=frame.id,
            novel_id=novel_id, chapter_id=chapter_id, force=regenerate,
        )
        frame.gen_task_id = task.id
        from app.models import TaskStatus
        frame.status = (SpecStatus.ready if task.status == TaskStatus.succeeded
                        else SpecStatus.generating)
        if task.status == TaskStatus.succeeded:
            frame.params_json = {**(frame.params_json or {}), "needs_regeneration": False}
        result.submitted_first += 1
        checkpoint(db)   # 这一张已经付过费了，先落库

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
    motion_by_shot = {
        m.shot_id: m for m in db.execute(
            select(ShotMotion).where(
                ShotMotion.shot_id.in_([shot.id for _frame, shot in rows] or [""])
            )
        ).scalars()
    }
    for frame, shot in rows:
        if (shot.camera_json or {}).get("frame_mode") == "first_only":
            result.skipped += 1
            continue
        if frame.asset_id and not regenerate and not (frame.params_json or {}).get("needs_regeneration"):
            result.skipped += 1
            continue
        first = db.execute(
            select(FrameSpec).where(
                FrameSpec.shot_id == shot.id, FrameSpec.role == FrameRole.first
            )
        ).scalars().first()
        if first is None or not first.asset_id or (first.params_json or {}).get("needs_regeneration"):
            result.blocked.append(f"镜头 {shot.order_no} 的首帧还没生成")
            continue
        url = db.execute(
            select(Asset.url).where(Asset.id == first.asset_id)
        ).scalars().first()
        if not url:
            result.blocked.append(f"镜头 {shot.order_no} 的首帧图不可用")
            continue
        motion = motion_by_shot.get(shot.id)
        if (motion is None or not motion.motion_prompt_en
                or len(motion.deltas_en_json or []) < 2
                or not motion.start_frame_en or not motion.end_frame_en):
            result.blocked.append(
                f"镜头 {shot.order_no} 没有通过验收的英文物理运动；"
                "不生成一张凭模型猜的尾帧"
            )
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
    # 这一批要发给谁，决定尾帧提示词怎么写
    prompt_style = PROMPT_STYLE_DESCRIBE
    try:
        from app.capability.service import resolve_one

        route = resolve_one(db, Capability.image_i2i, "last_frame")
        prompt_style = str((route.default_params or {}).get(
            "prompt_style") or PROMPT_STYLE_DESCRIBE)
    except Exception as exc:          # noqa: BLE001 —— 解析不出就按老写法
        log.warning("取不到尾帧路由的提示词风格，按描述式发：%s", exc)
    for frame, shot, first_url in pending:
        params = frame.params_json or {}
        instruction, why = _derive_en(frame, deltas.get(shot.id))
        if why:
            result.thin_derive.append({"shot": shot.order_no, "why": why})
        payload: dict[str, Any] = {
            "image": {"url": first_url},
            # 写法由路由声明：祈使句式只说改什么，描述式给整段画面。
            # 同 seed 提升连贯度
            "prompt": _last_frame_prompt(frame.prompt or "", instruction, prompt_style),
            "negative_prompt": frame.negative_prompt or "",
            "strength": strength,
            "width": width_last, "height": height_last,
            "params": {"seed": params.get("seed"),
                       "style": _plan_style(db, plan),
                       "ref_megapixels": 0.4},
        }
        refs = ([] if params.get("continuity_only") else
                params.get("reference_images") or [])
        if refs:
            payload["reference_images"] = refs
        style = params.get("style") or (plan.config_json or {}).get("style")
        if style:
            payload["style"] = style

        task = submit_task(
            db, Capability.image_i2i, payload, purpose="last_frame",
            ref_kind="frame_spec", ref_id=frame.id,
            novel_id=novel_id, chapter_id=chapter_id, force=regenerate,
        )
        frame.gen_task_id = task.id
        from app.models import TaskStatus
        frame.status = (SpecStatus.ready if task.status == TaskStatus.succeeded
                        else SpecStatus.generating)
        if task.status == TaskStatus.succeeded:
            frame.params_json = {**(frame.params_json or {}), "needs_regeneration": False}
        result.submitted_last += 1
        checkpoint(db)   # 同上

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


#: 尾帧提示词的两种写法。**哪一种由路由声明，不按模型名写死。**
PROMPT_STYLE_DESCRIBE = "describe"      # 整段画面描述（文生图式的编辑模型）
PROMPT_STYLE_INSTRUCT = "instruct"      # 只说改什么（祈使句式的编辑模型）


def _last_frame_prompt(scene_prompt: str, instruction: str, style: str) -> str:
    """尾帧发给编辑模型的那一句。

    **本机 FLUX-edit 的自述原话：「提示词要写成祈使句指令
    （Change the background to ...），而不是画面描述」。**
    而这里从前发的是 `整段画面描述 ; 变化说明` —— 描述在前、变化只是
    尾巴上的一小截，编辑模型听前面那一大段。

    两种结局正好对应实跑看到的两种毛病：
      · 描述和底图基本吻合 → 它几乎不改 → 尾帧≈首帧 → 视频是 PPT
      · 它照描述重画一遍   → 人物位置与长相重组 → 画面漂移

    祈使句式只说「改什么、别动什么」，改动量正好是分镜算出来的那一点，
    LTXV 才有东西可插值。
    """
    instruction = (instruction or "").strip(" ;.")
    if style != PROMPT_STYLE_INSTRUCT:
        return f"{scene_prompt or ''} ; {instruction}".strip(" ;")
    if not instruction:
        return "Keep the image unchanged."
    # 「别动什么」和「改什么」一样重要 —— 不写死的话编辑模型会顺手
    # 把脸、衣服、机位一起重画，那就是漂移
    return (f"{instruction}. "
            "Keep the same people with identical faces, hair and clothing, "
            "the same location, the same camera angle and framing, "
            "and the same lighting. Change nothing else.")


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
        if asset_id and (asset_id != frame.asset_id or frame.status != SpecStatus.ready
                         or (frame.params_json or {}).get("needs_regeneration")):
            frame.asset_id = asset_id
            frame.status = SpecStatus.ready
            frame.params_json = {**(frame.params_json or {}), "needs_regeneration": False}
            updated += 1
    db.flush()
    return {"frames_updated": updated, "checked": len(rows)}


#: 用锚做底图时的改动幅度。身份锚是**正面素颜头肩像**，
#: 要变成一个带服装、环境、光线的完整画面，改动必然大 ——
#: 尾帧那种 0.35 会把人留在灰背景棚里。
#: 但也不能给到 1：那等于重画，脸就丢了。
IDENTITY_EDIT_STRENGTH = 0.75
#: 连贯锚的重绘强度。**比身份锚低得多** —— 那一张里已经有正确的场景、
#: 正确的人、正确的光，要动的只是机位和这一拍的动作。
#: 0.75 等于整张重画：实跑时镜 2 从走廊换成了临街的另一条走廊，
#: 人也换成了一个没出现过的金发少年。
CONTINUITY_EDIT_STRENGTH = 0.42
#: 场景锚的重绘强度。场景图里场景是对的、但一个人也没有，
#: 要往里加人 —— 比「换机位」动得多，比「把一张肖像铺成整场戏」动得少。
#:
#: **本机 FLUX.2 编辑根本不读这个值。** 它靠 ReferenceLatent 把参考图
#: 当条件注入，没有「重绘幅度」这个概念（工作流自述：「不是靠重绘幅度
#: 去蒙，而是把原图作为参考条件注入」），网关的参数映射里也没有 strength。
#: 留着是给按强度工作的云端供应商；本机上两条分支的真实差别只有提示词。
SCENE_EDIT_STRENGTH = 0.60

#: 发给编辑模型的提示词预算。契约写的是 max_prompt_chars=2000。
#: 从前场景首镜把整段 7162 字的提示词原样发出去 —— 超限 3.5 倍，
#: 而这一路上没有任何一步截断或报错，多出来的部分去哪了无从得知。
_PROMPT_BUDGET = 1900


def _instruct_head(prompt: str, budget: int = _PROMPT_BUDGET) -> str:
    """按逗号边界把提示词裁到预算内。

    提示词是按重要性排的（这一镜是什么 → 机位 → 调度 → 光 → 制作单
    → 相貌），所以从尾部裁掉的是最可替代的那部分 —— 而相貌这一轮
    由身份参考图负责，本来就不该再靠文字描述去赌。
    """
    text = (prompt or "").strip()
    if len(text) <= budget:
        return text
    cut = text[:budget]
    comma = cut.rfind(", ")
    return (cut[:comma] if comma > budget // 2 else cut).rstrip(" ,")


def _split_scene_anchor(
    refs: list[dict[str, Any]],
) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    """场景首镜的底图取**场景图**，人物留作身份参考。

    从前这里取的是主体的人物肖像当底图，等于让模型把一张头肩像铺成
    一整场戏：场景全靠文字重新长出来，而人物的细节反被重画掉。
    实跑里高个少年的多色染发在镜 1 被画成了纯红，同一个人在镜 2
    （连贯锚＋身份参考）却还原得一丝不差 —— 差别就在这里。

    场景图当底图没这个问题：场景是现成的，脸由第二张参考带进来，
    和连贯镜走的是同一条路子。取不到场景图才退回旧路径。
    """
    def usable(r: Any) -> bool:
        return isinstance(r, dict) and isinstance(r.get("ref"), dict)

    base = next((r for r in refs if usable(r) and str(r.get("role")) == "scene"),
                None)
    if base is None:
        return None, refs
    return base["ref"], [r for r in refs if r is not base]


def _split_identity_anchor(
    refs: list[dict[str, Any]],
) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    """挑出当底图的人物锚，返回（底图引用, 其余参考）。

    只认 character 角色 —— 风格图与构图图不能当底图，
    拿风格参考去当底图，出来的是「那张风格图被改了几笔」，不是这一镜。

    多人同框时取第一张：编辑模型按出现顺序理解主次，
    主要人物做底图、其余作附加参考，比平铺一堆图更稳。
    """
    def usable(r: Any) -> bool:
        return isinstance(r, dict) and isinstance(r.get("ref"), dict)

    # 先找明确标了 identity 的；找不到才回落到「第一个 character」。
    # 回落这一支是为了旧数据 —— 那时的 refs 还没有这个标记
    base = next((r for r in refs if usable(r) and r.get("identity")), None)
    if base is None:
        base = next((r for r in refs if usable(r)
                     and str(r.get("role")) == "character"), None)
    if base is None:
        return None, refs
    return base["ref"], [r for r in refs if r is not base]


#: 各画幅在「短边 = 480」这一档的尺寸。本机模型的原生档位是 832×480，
#: 不是 854×480 —— 报一个它没有的尺寸只会被它自己对齐回去，
#: 而对齐之后首帧与尾帧未必落在同一个尺寸上
#: 工作台现在报的档位是 800×480 / 512×768 / 1536×768 / 1280×720。
#: **报一个它没有的尺寸只会被它自己对齐回去**，而对齐之后首帧与尾帧
#: 未必落在同一个结果上 —— 那正是 i2v 拉伸或裁切的由来
_SIZE_480 = {
    "16:9": (800, 480), "9:16": (480, 800),
    "4:3": (640, 480), "1:1": (512, 512), "2.39:1": (1152, 480),
}
_SIZE_720 = {
    "16:9": (1280, 720), "9:16": (720, 1280),
    "4:3": (1152, 864), "1:1": (1024, 1024), "2.39:1": (1280, 536),
}


def _render_style(profile) -> str:
    """这一版是写实还是动漫，由档案说了算。见 identity.render_style。"""
    from app.pipelines.identity import render_style
    return render_style(profile)


def _plan_style(db: Session, plan: ShotPlan) -> str:
    """出帧那两个函数手上没有档案，从计划顺着映射取一次。

    取不到就按写实 —— 宁可锚错一次画风，也不要不锚：
    不锚的话提示词里的 character sheet 这类词会把它推向动漫，
    而那正是上一批素材出成动漫风的原因。
    """
    try:
        tf = db.get(WorldTransform, plan.transform_id) if plan.transform_id else None
        prof = db.get(WorldProfile, tf.target_profile_id) if tf else None
        return _render_style(prof)
    except Exception as exc:          # noqa: BLE001
        log.warning("取不到出图画风，按写实处理：%s", exc)
        return "photoreal"


def _size_for(aspect: str) -> tuple[int, int]:
    """画幅 → 像素。**短边由配置定，不在这里写死。**

    从前 1280×720 散在四处（帧、素材参考、成片、接口默认），想整体
    降一档要改四个地方，漏一处就出现一批尺寸不一致的素材 —— 而尺寸
    不一致的首尾帧喂给 i2v，出来的是拉伸或裁切。
    """
    from app.config import get_settings

    table = (_SIZE_480 if int(get_settings().render_short_side) <= 480
             else _SIZE_720)
    return table.get(aspect, table["16:9"])
