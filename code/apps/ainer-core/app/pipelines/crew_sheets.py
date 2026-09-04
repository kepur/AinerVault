"""按工种生成镜头制作单，并用该工种自己的判据验收。

## 分工种而不是一次生成

一次让模型填完摄影灯光美术声音剪辑，它会平均用力、每项写两句 ——
而这些维度的判据完全不同：灯光要方位与光质，剪辑要秒数与切点。
分开之后每一项都能带着自己的判据与反例去生成，也能单独重跑。

## 验收用的是生成时的同一份规格

规格里的「不合格写法」在这里被反向使用：生成时告诉模型不要这么写，
验收时检查它有没有这么写。两边共用一份定义 ——
分开写会变成「按一套标准生成、按另一套验收」。

缺项与命中反例都落库，不是打日志。**缺项的单子不该进入生成** ——
下游拿到「柔和侧光」这种描述，出来的图没法用，
而那时已经花掉了图像模型的钱。
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ids import new_id
from app.models import (
    Chapter, CrewSheet, FrameRole, FrameSpec, ScriptBlock, ScriptDoc, SheetStatus,
    Shot, ShotMotion, ShotPlan, WorldProfile,
)
from app.pipelines.base import PipelineError, as_text, chat_json
from app.pipelines import screenplay as sp
from app.worldview.crew import CREW, CREW_BY_ROLE, CrewSpec

log = logging.getLogger(__name__)

#: 空洞形容词。命中即判为不合格 —— 它们看着像描述，实际不含信息。
#: 与各工种规格里的 bad 列表互补：那里是分工种的具体反例，
#: 这里是所有工种通用的「说了等于没说」。
_EMPTY_WORDS = (
    "适当", "合适", "恰当", "适宜", "相应", "一定的", "某种",
    "电影感", "高级感", "氛围感", "唯美", "精美", "考究", "讲究",
    "根据需要", "视情况", "酌情", "自然的", "和谐的", "统一的",
)
#: 短于此长度要另行判断是否合格。**不能一刀切** ——
#: 「中近景」「平视」「正面」「硬切」都是完全合格的答案，
#: 按长度筛会把它们全判成缺失，而那正是这套规格最想要的那种精确回答。
_MIN_LEN = 6


def _spec_schema(spec: CrewSpec) -> dict[str, Any]:
    """按规格的必填维度生成 schema。

    字段名取维度冒号前的部分并转成 key —— 维度表就是 schema 的唯一来源，
    加一个维度不需要另外改 schema，两边不会走偏。

    **每个维度两份**：中文给人审核，`_en` 给图像／视频模型。
    图像模型不认中文 —— 喂中文出来的是一整版汉字纹样，不是画面。
    制作单是本系统交给下游的**主要交付物**，只有中文等于交不出去。
    """
    props: dict[str, Any] = {}
    required: list[str] = []
    for dim in spec.dimensions:
        key = _dim_key(dim)
        props[key] = {"type": "string", "description": dim}
        props[f"{key}_en"] = {"type": "string",
                              "description": f"{dim}（英文，直接进提示词）"}
        required += [key, f"{key}_en"]
    return {
        "type": "object",
        "required": required,
        "properties": props,
    }


def _dim_key(dim: str) -> str:
    """「主光：从哪个方位来」→ key_light 之类的稳定键。

    用维度中文名的位置索引而不是翻译 —— 翻译会随文案改动而变，
    键一变，历史数据就对不上了。
    """
    head = dim.split("：")[0].split(":")[0].strip()
    return re.sub(r"[^\w]+", "_", head).strip("_") or "field"


#: 明确的否定答案。「无补光」「机位固定」是**做出了决定**，
#: 不是没填 —— 按长度或术语筛会把它们判成缺失，
#: 而「有没有」类的维度本来就允许回答「没有」。
_NEGATIVE = ("无", "没有", "不用", "不加", "固定", "静止", "保持", "免")


def _is_term(spec: CrewSpec, val: str) -> bool:
    """这个短答案是不是该工种的术语。

    术语表在生成时是给模型的词汇，在验收时是白名单 —— 一物两用。
    没有它，「中近景」「平视」「硬切」这类精确回答会因为太短被判缺失，
    而它们恰恰是这套规格最想要的那种答案。
    """
    v = val.strip()
    if not v:
        return False
    for words in spec.lexicon.values():
        for w in words:
            # 术语可能带修饰（「低机位仰拍」含「低机位」），包含即算
            if w and (w in v or v in w):
                return True
    return False


def _check(spec: CrewSpec, payload: dict[str, Any]) -> tuple[list[str], list[str]]:
    """按规格验收。返回 (缺的维度, 命中的空洞写法)。"""
    missing: list[str] = []
    rejected: list[str] = []
    for dim in spec.dimensions:
        key = _dim_key(dim)
        val = as_text(payload.get(key))
        if not val:
            missing.append(dim.split("：")[0].split(":")[0])
            continue
        decided = _is_term(spec, val) or any(val.startswith(n) for n in _NEGATIVE)
        if len(val) < _MIN_LEN and not decided:
            missing.append(dim.split("：")[0].split(":")[0])
            continue
        hit = [w for w in _EMPTY_WORDS if w in val]
        if hit:
            rejected.append(f"{dim.split('：')[0]}：「{val[:40]}」含空洞词 {hit}")
    return missing, rejected


def _compose(spec: CrewSpec, payload: dict[str, Any]) -> str:
    """中文那一份，给人审核。按维度顺序。"""
    bits = []
    for dim in spec.dimensions:
        head = dim.split("：")[0].split(":")[0]
        val = as_text(payload.get(_dim_key(dim)))
        if val:
            bits.append(f"{head}：{val}")
    return "；".join(bits)


def _compose_en(spec: CrewSpec, payload: dict[str, Any]) -> str:
    """英文那一份，**直接进出图提示词**。

    不带维度名前缀 —— 「Framing: medium close-up」里的 Framing
    对图像模型没有意义，它只会把这个词也画进去（或当噪声）。
    逗号分隔的短语串才是提示词的样子。

    术语先查双语表：模型现翻会得到「medium close shot」与
    「medium close-up」混用，而下游按字面匹配的工具会当成两个值。
    """
    glossary = spec.glossary()
    bits: list[str] = []
    for dim in spec.dimensions:
        val = as_text(payload.get(f"{_dim_key(dim)}_en")).strip()
        if not val:
            # 英文缺了就拿中文查表兜一下 —— 拿得到多少是多少，
            # 拿不到的由 cjk 守门报出来，而不是静默留一段中文进提示词
            cn = as_text(payload.get(_dim_key(dim))).strip()
            val = " ".join(en for term, en in glossary.items() if term in cn)
        if val:
            bits.append(val.strip().rstrip("。.；;"))
    return ", ".join(b for b in bits if b)


@dataclass
class SheetResult:
    shots: int = 0
    generated: int = 0
    skipped_locked: int = 0
    incomplete: list[dict] = field(default_factory=list)
    by_role: dict[str, int] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "shots": self.shots, "generated": self.generated,
            "skipped_locked": self.skipped_locked,
            "incomplete": self.incomplete, "by_role": self.by_role,
        }


def _shot_context(db: Session, shot: Shot, blocks: dict[str, ScriptBlock]) -> str:
    texts = [
        blocks[bid].source_text for bid in (shot.block_ids_json or [])
        if bid in blocks and blocks[bid].source_text
    ]
    head = (
        f"景别 {shot.shot_size or '未定'}　时长 {shot.duration_ms / 1000:.1f}s"
        f"　{shot.description or ''}"
    )
    return head + "\n原文：\n" + "\n".join(texts)[:1200]


def generate_sheets(
    db: Session, plan: ShotPlan, profile: WorldProfile, *,
    roles: list[str] | None = None, shot_ids: list[str] | None = None,
) -> SheetResult:
    """为分镜计划的每个镜头逐工种出单。

    后出的工种能看见先出的产出 —— 灯光要知道摄影定的机位，
    声音要知道剪辑定的时长。顺序写在 crew.CREW 里。
    """
    doc = db.get(ScriptDoc, plan.script_doc_id)
    chapter = db.get(Chapter, doc.chapter_id) if doc else None
    if chapter is None:
        raise PipelineError("分镜对应的章节不存在")

    q = select(Shot).where(Shot.shot_plan_id == plan.id).order_by(Shot.order_no)
    if shot_ids:
        q = q.where(Shot.id.in_(shot_ids))
    shots = list(db.execute(q).scalars())
    if not shots:
        raise PipelineError("该分镜计划下没有镜头")

    blocks = {
        b.id: b for b in db.execute(
            select(ScriptBlock).where(ScriptBlock.script_doc_id == doc.id)
        ).scalars()
    }
    wanted = [c for c in CREW if not roles or c.role in roles]
    existing = {
        (s.shot_id, s.role): s
        for s in db.execute(
            select(CrewSheet).where(CrewSheet.shot_id.in_([s.id for s in shots]))
        ).scalars()
    }

    axes = profile.axes_json or {}
    world = (
        f"【目标世界观】{profile.display_name}"
        f"（{axes.get('era_span')}，{axes.get('social_context')}）\n"
        f"【不得出现】{(profile.visual_json or {}).get('visual_dont')}"
    )

    result = SheetResult(shots=len(shots))
    for shot in shots:
        context = _shot_context(db, shot, blocks)
        prior: list[str] = []
        for spec in wanted:
            row = existing.get((shot.id, spec.role))
            if row is not None and (
                row.status is SheetStatus.locked or row.edited_by_human
            ):
                result.skipped_locked += 1
                if row.prompt:
                    prior.append(f"【{spec.display_name}已定】{row.prompt}")
                continue

            schema = _spec_schema(spec)
            user = world + "\n\n" + context
            if prior:
                # 先出的工种是后出工种的约束，不是参考
                user += "\n\n【同一镜已确定的部分，必须与之一致】\n" + "\n".join(prior)
            try:
                data, task = chat_json(
                    db,
                    [
                        {"role": "system",
                         "content": spec.brief(bilingual=True)
                         + "\n\n只输出 JSON 对象。"},
                        {"role": "user", "content": user},
                    ],
                    schema,
                    purpose="shot_plan",
                    novel_id=chapter.novel_id, chapter_id=chapter.id,
                    ref_kind="crew_sheet", ref_id=shot.id,
                )
            except PipelineError as exc:
                log.warning("镜头 %s 的%s出单失败：%s", shot.order_no,
                            spec.display_name, exc)
                continue

            missing, rejected = _check(spec, data)
            if row is None:
                row = CrewSheet(id=new_id("cs"), shot_id=shot.id, role=spec.role)
                db.add(row)
                existing[(shot.id, spec.role)] = row
            row.payload_json = data
            row.prompt = _compose(spec, data)
            row.prompt_en = _compose_en(spec, data)
            row.missing_json = missing or None
            row.rejected_json = rejected or None
            row.model = task.model
            row.status = SheetStatus.drafted
            result.generated += 1
            result.by_role[spec.role] = result.by_role.get(spec.role, 0) + 1
            if missing or rejected:
                result.incomplete.append({
                    "shot": shot.order_no, "role": spec.role,
                    "missing": missing, "rejected": rejected[:3],
                })
            if row.prompt:
                prior.append(f"【{spec.display_name}】{row.prompt}")
            if not row.prompt_en:
                result.incomplete.append({
                    "shot": shot.order_no, "role": spec.role,
                    "missing": ["英文提示词"], "rejected": [],
                })

    db.flush()
    return result


MOTION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["start_frame", "end_frame", "camera_move", "subject_move",
                 "secondary_motion", "physics_constraints", "lighting_change",
                 "facial_change", "continuity_constraints", "pacing", "deltas",
                 "start_frame_en", "end_frame_en", "camera_move_en",
                 "subject_move_en", "secondary_motion_en",
                 "physics_constraints_en", "lighting_change_en",
                 "facial_change_en", "continuity_constraints_en",
                 "pacing_en", "deltas_en"],
    "properties": {
        "start_frame": {"type": "string"},
        "end_frame": {"type": "string"},
        "camera_move": {"type": "string"},
        "subject_move": {"type": "string"},
        "secondary_motion": {"type": "string"},
        "physics_constraints": {"type": "string"},
        "lighting_change": {"type": "string"},
        "facial_change": {"type": "string"},
        "continuity_constraints": {"type": "string"},
        "pacing": {"type": "string"},
        "deltas": {"type": "array", "items": {"type": "string"}},
        # 英文那一份**直接交给视频模型**。视频模型与图像模型一样不认中文
        "start_frame_en": {"type": "string"},
        "end_frame_en": {"type": "string"},
        "camera_move_en": {"type": "string"},
        "subject_move_en": {"type": "string"},
        "secondary_motion_en": {"type": "string"},
        "physics_constraints_en": {"type": "string"},
        "lighting_change_en": {"type": "string"},
        "facial_change_en": {"type": "string"},
        "continuity_constraints_en": {"type": "string"},
        "pacing_en": {"type": "string"},
        "deltas_en": {"type": "array", "items": {"type": "string"}},
    },
}

MOTION_SYSTEM = """你是动作导演、场记与动画指导。你要写清这一镜的**运动**：
首帧到尾帧之间每一步如何在现实时间与空间中发生。

这份描述有两个用处，都很实：
  尾帧靠它做 i2i，知道该改画面的哪一部分而不是整张重画
  视频模型靠它知道怎么动

必须写死：
  start_frame  起幅。镜头开始的那一瞬间，画面是什么样
  end_frame    落幅。结束的那一瞬间是什么样
  camera_move  相机怎么动。**静止也要明写「机位固定」** ——
               不写，视频模型会自己加运动
  subject_move 主体怎么动
  secondary_motion 衣摆、头发、烟雾、雨、尘土、道具的跟随运动与滞后。
                   没有就明写哪些保持静止，不让模型自加风与粒子
  physics_constraints 脚与地面的受力、重心转移、手与道具的接触、惯性与遍历路径
  lighting_change 只能由光源、遮挡、人或机位的位移导致；原因没变就明写光位、色温不变
  facial_change 眼神落点、眨眼、下颌与面部肌肉的微小过程；不得改脸型、年龄、五官
  continuity_constraints 上一动作的落点、轴线、视线、道具所在手与服装必须锁定

deltas 逐项列出首尾之间**变化了什么**：
  「表情从平静变为警觉」「右手从膝上移到刀柄」「门缝的光变宽」
这是 i2i 的直接依据。写「场景发生变化」等于没写。

pacing 写速度与节奏曲线：匀速／先慢后快／急停／缓入缓出。

运动必须成为「因果触发 → 主动作 → 次级反应 → 稳定落幅」。
若剧本只给了起点和结果，可补齐**完成该动作所必需的最小过程**，
但不得新增情节、道具、人物或突然变化的光源。

英文 `_en` 字段是直接交给图像／视频模型的可执行提示词，不是摘要；
与中文必须同等完整。结尾明确禁止：teleportation, body morphing,
extra limbs, foot sliding, object penetration, texture boiling, lighting flicker, identity drift。

不合格的写法：
  ✗ 「镜头缓缓移动」—— 从哪到哪
  ✗ 「人物有所动作」—— 什么动作
  ✗ 「画面富有张力」—— 那不是运动"""


_MOTION_DETAIL_FIELDS = (
    "camera_move", "subject_move", "secondary_motion", "physics_constraints",
    "lighting_change", "facial_change", "continuity_constraints", "pacing",
)


def _motion_issues(data: dict[str, Any]) -> list[str]:
    """运动单的可执行性验收。只用形式化判据，不再调一次模型。"""
    issues: list[str] = []
    for key in _MOTION_DETAIL_FIELDS:
        if not as_text(data.get(key)).strip():
            issues.append(f"缺 {key}")
        if not as_text(data.get(f"{key}_en")).strip():
            issues.append(f"缺 {key}_en")
    start = as_text(data.get("start_frame")).strip()
    end = as_text(data.get("end_frame")).strip()
    if not start or not end:
        issues.append("起幅或落幅为空")
    elif start == end:
        issues.append("起幅与落幅相同")
    if not as_text(data.get("start_frame_en")).strip() \
            or not as_text(data.get("end_frame_en")).strip():
        issues.append("缺英文起幅或落幅")

    deltas = [as_text(x).strip() for x in (data.get("deltas") or []) if as_text(x).strip()]
    deltas_en = [as_text(x).strip() for x in (data.get("deltas_en") or []) if as_text(x).strip()]
    if len(deltas) < 2:
        issues.append("首尾可见差异少于 2 项")
    if len(deltas_en) < 2:
        issues.append("英文首尾可见差异少于 2 项")
    visible, why = sp.is_visible_change(
        as_text(data.get("subject_move")) + "；" + as_text(data.get("camera_move"))
    )
    if not visible:
        issues.append(f"主体与相机都没有可见位移：{why}")
    english = " ".join(
        as_text(data.get(f"{key}_en")) for key in _MOTION_DETAIL_FIELDS
    ) + " " + " ".join(deltas_en)
    if re.search(r"[\u3400-\u9fff]", english):
        issues.append("英文运动提示词混入中文")
    return issues


def generate_motion(
    db: Session, plan: ShotPlan, *, shot_ids: list[str] | None = None,
) -> dict[str, Any]:
    """为每个镜头生成运动描述。"""
    doc = db.get(ScriptDoc, plan.script_doc_id)
    chapter = db.get(Chapter, doc.chapter_id) if doc else None
    if chapter is None:
        raise PipelineError("分镜对应的章节不存在")

    q = select(Shot).where(Shot.shot_plan_id == plan.id).order_by(Shot.order_no)
    if shot_ids:
        q = q.where(Shot.id.in_(shot_ids))
    shots = list(db.execute(q).scalars())
    blocks = {
        b.id: b for b in db.execute(
            select(ScriptBlock).where(ScriptBlock.script_doc_id == doc.id)
        ).scalars()
    }
    existing = {
        m.shot_id: m for m in db.execute(
            select(ShotMotion).where(ShotMotion.shot_id.in_([s.id for s in shots]))
        ).scalars()
    }
    sheets: dict[str, list[CrewSheet]] = {}
    for s in db.execute(
        select(CrewSheet).where(CrewSheet.shot_id.in_([x.id for x in shots]))
    ).scalars():
        sheets.setdefault(s.shot_id, []).append(s)

    made = 0
    thin: list[dict] = []
    for shot in shots:
        row = existing.get(shot.id)
        if row is not None and (row.edited_by_human
                                or row.status is SheetStatus.locked):
            continue
        ctx = _shot_context(db, shot, blocks)
        crew_ctx = "\n".join(
            f"【{CREW_BY_ROLE[s.role].display_name}】{s.prompt}"
            for s in sheets.get(shot.id, []) if s.prompt and s.role in CREW_BY_ROLE
        )
        try:
            data, _ = chat_json(
                db,
                [
                    {"role": "system", "content": MOTION_SYSTEM + "\n\n只输出 JSON。"},
                    {"role": "user",
                     "content": ctx + ("\n\n【本镜已定】\n" + crew_ctx if crew_ctx else "")},
                ],
                MOTION_SCHEMA,
                purpose="shot_plan",
                novel_id=chapter.novel_id, chapter_id=chapter.id,
                ref_kind="shot_motion", ref_id=shot.id,
            )
        except PipelineError as exc:
            log.warning("镜头 %s 的运动描述失败：%s", shot.order_no, exc)
            continue

        if row is None:
            row = ShotMotion(id=new_id("sm"), shot_id=shot.id)
            db.add(row)
            existing[shot.id] = row
        row.start_frame = as_text(data.get("start_frame"))[:2000] or None
        row.end_frame = as_text(data.get("end_frame"))[:2000] or None
        row.camera_move = as_text(data.get("camera_move"))[:1000] or None
        row.subject_move = as_text(data.get("subject_move"))[:1000] or None
        row.pacing = as_text(data.get("pacing"))[:128] or None
        deltas = [d for d in (as_text(x) for x in (data.get("deltas") or [])) if d]
        row.deltas_json = deltas or None
        row.start_frame_en = as_text(data.get("start_frame_en"))[:2000] or None
        row.end_frame_en = as_text(data.get("end_frame_en"))[:2000] or None
        row.deltas_en_json = [
            d for d in (as_text(x) for x in (data.get("deltas_en") or [])) if d
        ] or None
        labels = {
            "camera_move": "相机", "subject_move": "主体",
            "secondary_motion": "次级运动", "physics_constraints": "物理约束",
            "lighting_change": "光影", "facial_change": "面部",
            "continuity_constraints": "连续性", "pacing": "节奏",
        }
        row.motion_prompt = "；".join(
            f"{labels[key]}：{as_text(data.get(key)).strip()}"
            for key in _MOTION_DETAIL_FIELDS if as_text(data.get(key)).strip()
        ) or None
        # 视频模型读的是这一条。把主动作、受力、惯性、光影、脸部与
        # 连续性都放进去；只放 camera+subject 会把剩下的自由度全丢给视频模型猜。
        row.motion_prompt_en = ". ".join(
            as_text(data.get(f"{key}_en")).strip().rstrip(".;")
            for key in _MOTION_DETAIL_FIELDS
            if as_text(data.get(f"{key}_en")).strip()
        ) or None

        issues = _motion_issues(data)
        thin.extend({"shot": shot.order_no, "why": issue} for issue in issues)
        if not issues:
            # 分镜阶段的 derive_instruction 只是初判；动作导演把调度、
            # 制作单与物理过程都纳入后，这份通过验收的差异才是尾帧权威。
            last = db.execute(
                select(FrameSpec).where(
                    FrameSpec.shot_id == shot.id,
                    FrameSpec.role == FrameRole.last,
                )
            ).scalars().first()
            if last is not None and not last.edited_by_human:
                last.derive_instruction = "；".join(deltas)
        row.status = SheetStatus.drafted
        made += 1

    db.flush()
    return {
        "shots": len(shots), "generated": made,
        "quality_ready": max(0, made - len({x["shot"] for x in thin})),
        "thin": thin,
    }


# ── 场记：跨镜连续性 ─────────────────────────────────────────────────────────

def _shot_facts(
    db: Session, shot: Shot, sheets: dict[str, CrewSheet],
) -> dict[str, Any]:
    """把一个镜头的各方数据摊成连续性检查要的形状。

    灯光来自 crew_sheets，站位视线道具来自 shot_performances ——
    两处数据本来就分开存，检查时才需要合到一起。
    """
    from app.models import ShotPerformance, StagePosition, WorldEntity

    light = sheets.get("lighting")
    payload = (light.payload_json or {}) if light else {}
    facts: dict[str, Any] = {
        "order": shot.order_no,
        # 键名来自灯光规格的维度，这里按语义取而不是按位置
        "key_light": as_text(payload.get("主光")),
        "color_temp": as_text(payload.get("色温与色彩倾向")),
        "positions": {}, "facing": {}, "gaze": {}, "props": {}, "actions": {},
    }
    rows = list(db.execute(
        select(ShotPerformance, WorldEntity)
        .join(WorldEntity, WorldEntity.id == ShotPerformance.entity_id)
        .where(ShotPerformance.shot_id == shot.id)
    ))
    for p, e in rows:
        if p.position is StagePosition.offscreen:
            continue          # 画外的人不参与构图连续性
        name = e.display_name
        facts["positions"][name] = p.position.value
        facts["facing"][name] = p.facing.value
        if p.gaze_target:
            facts["gaze"][name] = p.gaze_target
        if p.props_json:
            facts["props"][name] = list(p.props_json)
        facts["actions"][name] = " ".join(
            x for x in (p.action, p.action_end) if x
        )
    return facts


def check_continuity(db: Session, plan: ShotPlan) -> dict[str, Any]:
    """场记检查。按场景分组，只在同一场内相邻比对。

    换了场当然可以换光换位置 —— 不分组的话，
    每个场景切换都会报一次「光位跳变」，告警立刻变成噪声。
    """
    from app.worldview import continuity as ct

    shots = list(db.execute(
        select(Shot).where(Shot.shot_plan_id == plan.id).order_by(Shot.order_no)
    ).scalars())
    if not shots:
        raise PipelineError("该分镜计划下没有镜头")

    sheets: dict[str, dict[str, CrewSheet]] = {}
    for row in db.execute(
        select(CrewSheet).where(CrewSheet.shot_id.in_([s.id for s in shots]))
    ).scalars():
        sheets.setdefault(row.shot_id, {})[row.role] = row

    by_scene: dict[str, list[dict[str, Any]]] = {}
    for s in shots:
        key = s.scene_id or "__no_scene__"
        by_scene.setdefault(key, []).append(
            _shot_facts(db, s, sheets.get(s.id, {}))
        )

    issues: list[ct.Issue] = []
    for group in by_scene.values():
        issues.extend(ct.check_scene(group))

    out = ct.summarize(issues)
    out["scenes"] = len(by_scene)
    out["shots"] = len(shots)
    # 检查不了的地方要说出来 —— 没有灯光单就查不出光位跳变，
    # 报「0 处问题」会让人以为查过了
    out["not_checked"] = [
        f"镜 {s.order_no}：缺灯光单，光位与色温未检查"
        for s in shots if "lighting" not in sheets.get(s.id, {})
    ] + [
        f"镜 {s.order_no}：缺人物调度，翻轴与视线未检查"
        for s in shots
        if not _shot_facts(db, s, sheets.get(s.id, {}))["positions"]
    ]
    return out
