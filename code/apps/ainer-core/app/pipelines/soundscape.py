"""声景编译 —— 把声音制作单变成可生成的音频规格。

## 它修的是一处「存了没人读」

声音那一份制作单里，每一镜都写清了环境底噪、音效点、画外声、配乐。
但音频编译（audio_compose）走的是另一条路：它去找**音频素材**，
找不到就静默跳过。于是全库跑下来，AudioSpec 里只有对白和旁白 ——
环境音、音效、配乐一条都没有，而制作单里明明写着。

这一层把制作单读出来，变成 AudioSpec。

## 三类声音的挂载点不同

    环境底噪／配乐   挂**场景**。同一场戏的房间是同一个房间，
                    每镜各生成一段环境音，接起来会听见底噪在跳
    音效点／画外声   挂**镜头**，还要带时间点 ——
                    「油布被掀开的窸窣」出在第 2 秒还是第 5 秒，
                    是这一声有没有对上画面的全部区别

## 提示词要英文

音频生成模型（Stable Audio、AudioGen、MusicGen）都只认英文。
与图像那边同一个理由，也同一套办法：制作单出中英两份，
中文给人审，英文进提示词。

## 环境音不做「每镜一段」

同一场戏只出一段环境床，长度按全场时长。
分镜生成会得到几段底噪各不相同的音频，剪在一起像换了个房间 ——
而观众对空间的连续性极其敏感，比对画面还敏感。
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ids import new_id
from app.models import (
    AudioKind, AudioSpec, Chapter, CrewSheet, Scene, ScriptDoc, Shot, ShotPlan,
    SpecStatus, WorldProfile, WorldTransform,
)
from app.pipelines.base import PipelineError, as_text
from app.pipelines.crew_sheets import _dim_key
from app.worldview.crew import CREW_BY_ROLE

log = logging.getLogger(__name__)

SOUND = CREW_BY_ROLE["sound"]
#: 声音制作单里各维度对应的 key
K_AMBIENCE = _dim_key(SOUND.dimensions[0])   # 环境底噪
K_SFX = _dim_key(SOUND.dimensions[1])        # 音效点
K_OFFSCREEN = _dim_key(SOUND.dimensions[3])  # 画外声
K_SILENCE = _dim_key(SOUND.dimensions[4])    # 静默
K_MUSIC = _dim_key(SOUND.dimensions[5])      # 配乐

#: 「不要配乐」「无环境音」这类**明确的否定**。它们是决定，不是缺项 ——
#: 当成缺项处理会得到一段谁也没要的背景音乐，而静默常常是设计的一部分
_NONE = ("无", "不用", "不加", "没有", "none", "no music", "silence",
         "not required", "n/a")

#: 从音效点描述里抠时间。「第 2 秒」「00:03」「2s」都要能认。
#: 认不出就不给时间点 —— **宁可没有也不要编一个**：
#: 编错的时间点会让音效对不上画面，而那比没有音效更刺耳
_TIME_PATTERNS = (
    re.compile(r"第\s*([\d.]+)\s*秒"),
    re.compile(r"\b([\d.]+)\s*s\b", re.I),
    re.compile(r"\b(\d{1,2}):(\d{2})\b"),
)


def _is_none(text: str) -> bool:
    t = (text or "").strip().lower()
    return bool(t) and any(t.startswith(n) for n in _NONE)


def _at_ms(text: str) -> int | None:
    """从描述里取时间点，取不到返回 None。"""
    for pat in _TIME_PATTERNS:
        m = pat.search(text or "")
        if not m:
            continue
        if m.re.groups == 2:
            return (int(m.group(1)) * 60 + int(m.group(2))) * 1000
        try:
            return int(float(m.group(1)) * 1000)
        except ValueError:
            continue
    return None


def _split_cues(text: str) -> list[str]:
    """音效点常常一栏写好几条，拆开才能各自定时。

    按分号与换行拆 —— 不按逗号：「油布被掀开的窸窣，很轻」
    里的逗号是修饰，拆了会得到半句话。
    """
    parts = re.split(r"[；;\n]+", text or "")
    return [p.strip(" 、,") for p in parts if p.strip(" 、,")]


@dataclass
class SoundscapeResult:
    scenes: int = 0
    ambience: int = 0
    music: int = 0
    sfx: int = 0
    offscreen: int = 0
    silence: list[dict[str, Any]] = field(default_factory=list)
    no_sheet: list[int] = field(default_factory=list)
    no_english: list[int] = field(default_factory=list)
    untimed: list[str] = field(default_factory=list)
    #: 没能做的事，以及为什么。**报「0 段环境音」而不说原因，
    #: 会让人以为这一场真的不需要环境音**
    not_done: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "scenes": self.scenes, "ambience": self.ambience,
            "music": self.music, "sfx": self.sfx, "offscreen": self.offscreen,
            "silence": self.silence, "no_sheet": self.no_sheet,
            "no_english": self.no_english, "untimed": self.untimed,
            "not_done": self.not_done,
        }


def _payload_en(sheet: CrewSheet, key: str) -> tuple[str, str]:
    """取某一维度的 (中文, 英文)。"""
    data = sheet.payload_json or {}
    return as_text(data.get(key)).strip(), as_text(data.get(f"{key}_en")).strip()


def compile_soundscape(
    db: Session, plan: ShotPlan, transform: WorldTransform,
) -> SoundscapeResult:
    """把声音制作单编译成 AudioSpec。"""
    profile = db.get(WorldProfile, transform.target_profile_id)
    if profile is None:
        raise PipelineError("目标世界观档案缺失")
    doc = db.get(ScriptDoc, plan.script_doc_id)
    chapter = db.get(Chapter, doc.chapter_id) if doc else None
    if chapter is None:
        raise PipelineError("分镜对应的章节不存在")
    lang = plan.target_language_code or transform.target_language_code

    shots = list(db.execute(
        select(Shot).where(Shot.shot_plan_id == plan.id).order_by(Shot.order_no)
    ).scalars())
    if not shots:
        raise PipelineError("分镜没有镜头")

    sheets = {
        s.shot_id: s for s in db.execute(
            select(CrewSheet).where(
                CrewSheet.shot_id.in_([s.id for s in shots]),
                CrewSheet.role == "sound",
            )
        ).scalars()
    }
    existing = {
        (a.shot_id, a.scene_id, a.kind): a for a in db.execute(
            select(AudioSpec).where(
                AudioSpec.shot_id.in_([s.id for s in shots])
            )
        ).scalars()
    }
    scene_existing = {
        (a.scene_id, a.kind): a for a in db.execute(
            select(AudioSpec).where(AudioSpec.shot_id.is_(None))
        ).scalars() if a.scene_id
    }

    result = SoundscapeResult()

    # ── 场景级：环境床与配乐 ──
    # 取该场第一个有制作单的镜头。**同一场只出一段** ——
    # 每镜各生成一段环境音，剪在一起会听见底噪在跳，
    # 而观众对空间的连续性比对画面还敏感
    by_scene: dict[str, list[Shot]] = {}
    for sh in shots:
        if sh.scene_id:
            by_scene.setdefault(sh.scene_id, []).append(sh)
    result.scenes = len(by_scene)
    if not by_scene:
        # 环境床与配乐是**场景级**的：同一场戏的房间是同一个房间。
        # 散文线（prose:build）按规则分块，不产生场次 —— 于是没有挂载点。
        # 静默返回 0 会让人以为这一场真的不需要环境音
        result.not_done.append(
            "镜头没有绑场次，环境床与配乐无处可挂 —— 它们是场景级的，"
            "同一场戏的房间是同一个房间，按镜生成会听见底噪在跳。"
            "散文线（prose:build）不分场，跑一次剧本转换（script:generate）后再来")

    for sid, members in by_scene.items():
        scene = db.get(Scene, sid)
        total_ms = sum(s.duration_ms or 0 for s in members) or 20000
        sheet = next((sheets[s.id] for s in members if s.id in sheets), None)
        if sheet is None:
            continue
        for key, kind, counter in (
            (K_AMBIENCE, AudioKind.ambience, "ambience"),
            (K_MUSIC, AudioKind.bgm, "music"),
        ):
            cn, en = _payload_en(sheet, key)
            if not cn or _is_none(cn) or _is_none(en):
                continue
            if not en:
                result.no_english.append(members[0].order_no)
            prompt = en or cn
            ctx = " ".join(x for x in (
                scene.location_text if scene else None,
                scene.time_of_day if scene else None,
                scene.weather if scene else None,
            ) if x)
            row = scene_existing.get((sid, kind))
            params = {
                "prompt": prompt, "duration_ms": total_ms,
                "source": "sound_sheet", "context": ctx,
                # 中文留着给人审 —— 出问题时要能看懂当初写的是什么
                "prompt_cn": cn,
            }
            if row is None:
                db.add(AudioSpec(
                    id=new_id("au"), shot_id=None, scene_id=sid, kind=kind,
                    text=prompt, language_code=lang, params_json=params,
                    duration_ms=total_ms, status=SpecStatus.pending,
                ))
            else:
                row.text = prompt
                row.params_json = params
                row.duration_ms = total_ms
            setattr(result, counter, getattr(result, counter) + 1)

    # ── 镜头级：音效点与画外声 ──
    for sh in shots:
        sheet = sheets.get(sh.id)
        if sheet is None:
            result.no_sheet.append(sh.order_no)
            continue
        cn_s, en_s = _payload_en(sheet, K_SILENCE)
        if cn_s and not _is_none(cn_s):
            # 静默不生成音频，但必须记下来 —— 它是设计的一部分，
            # 混音时要知道这一段是**故意**没有声音，而不是漏了
            result.silence.append({"shot": sh.order_no, "note": cn_s[:100]})

        for key, kind, counter in (
            (K_SFX, AudioKind.sfx, "sfx"),
            (K_OFFSCREEN, AudioKind.sfx, "offscreen"),
        ):
            cn, en = _payload_en(sheet, key)
            if not cn or _is_none(cn):
                continue
            if not en:
                result.no_english.append(sh.order_no)
            cues_cn = _split_cues(cn)
            cues_en = _split_cues(en) if en else []
            for i, cue_cn in enumerate(cues_cn):
                cue_en = cues_en[i] if i < len(cues_en) else ""
                at = _at_ms(cue_cn)
                if at is None:
                    at = _at_ms(cue_en)
                if at is None and kind is AudioKind.sfx:
                    result.untimed.append(f"镜{sh.order_no}：{cue_cn[:40]}")
                prompt = cue_en or cue_cn
                key_tuple = (sh.id, None, kind)
                row = existing.get(key_tuple) if i == 0 else None
                params = {
                    "prompt": prompt, "prompt_cn": cue_cn,
                    "source": "sound_sheet",
                    "cue_index": i, "offscreen": counter == "offscreen",
                    # 时间点是这一声有没有对上画面的全部区别。
                    # 取不到就留空 —— 宁可没有也不要编一个
                    "at_ms": at,
                }
                if row is None:
                    db.add(AudioSpec(
                        id=new_id("au"), shot_id=sh.id, scene_id=sh.scene_id,
                        kind=kind, text=prompt, language_code=lang,
                        params_json=params, status=SpecStatus.pending,
                    ))
                else:
                    row.text = prompt
                    row.params_json = params
                setattr(result, counter, getattr(result, counter) + 1)

    if result.no_sheet:
        result.not_done.append(
            f"{len(result.no_sheet)} 个镜头没有声音制作单，这些镜的音效一条都没出 —— "
            f"先跑一次逐工种出单（crew-sheets:generate）")
    if result.untimed:
        result.not_done.append(
            f"{len(result.untimed)} 条音效没有时间点，混音时只能靠人对 —— "
            f"制作单的「音效点」维度要写清出在第几秒")
    db.flush()
    return result
