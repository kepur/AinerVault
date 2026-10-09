"""电影导演与摄影指导模块 (Cinematic Director & Cinematography Matrix).

整合开源 AI 电影导演项目规范 (AI-Cinematic-Prompt-Director, ViMax, 纳逗Pro)：
1. 摄影指导 (Director of Photography / DP):
   - 景别阶梯系统 (Shot Scales: ECU, CU, MCU, MS, FS, WS, EWS)
   - 构图与机位 (Angles & Framing: eye-level, low-angle, high-angle, dutch, OTS)
   - 光学焦段与光影质感 (Lens & Lighting: 24mm/35mm/50mm anamorphic, snow reflections, rim light)
2. 运镜指导 (Camera Movement):
   - 单镜单一主运镜原则 (One dominant camera move per shot)
   - 运动摄影语汇: handheld_tracking, slow_push_in, dolly_pull_out, low_angle_pan, static_lock_off
   - 严格消除 360 orbit / whip pan / barrel roll 等破坏潜空间的非法运镜
3. 动作物理与动力学 (Action Physics & Dynamics):
   - 动量守恒与惯性轨迹 (Momentum conservation & trajectory)
   - 碰撞与重力动力学 (Gravity, tumble, friction deceleration)
   - 材质与流体粒子表现 (Powder snow plume, carving spray, icy crystals, clothing wrinkles)
4. 画面过渡与接续剪辑 (Shot Transitions & Continuity):
   - 尾帧接续机制 (Last-Frame Chain Continuation): Shot N 首帧直接继承 Shot N-1 尾帧
   - 180度轴线原则 (180-degree rule) 与动接动切镜 (Cut-on-action)
5. 结构化纳逗Pro提示词矩阵 (Structured Cinematic Prompt Matrix):
   - 【视觉风格】 【场景设定】 【角色参考】 【画面构图】 【运镜】 【动作物理】 【音轨拟音】
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Literal

log = logging.getLogger("cinematic_director")

# ── 景别体系 (Shot Scales) ─────────────────────────────────────────────────────

SHOT_SCALES = {
    "ecu": {
        "name_cn": "大特写",
        "name_en": "Extreme close-up (ECU)",
        "framing": "Extreme close-up macro framing tightly focused on details (eyes, goggles reflections, tense expression, breath frost in cold air).",
        "camera_rec": "locked-off or extremely slow subtle push-in",
        "lens": "85mm macro lens, shallow depth of field, sharp foreground focus",
    },
    "cu": {
        "name_cn": "特写",
        "name_en": "Close-up (CU)",
        "framing": "Close-up shot of head and shoulders, showing facial emotion, helmet, and ski goggles clearly.",
        "camera_rec": "slow push-in or subtle handheld breathing",
        "lens": "50mm prime lens, beautiful soft bokeh background",
    },
    "mcu": {
        "name_cn": "中特写",
        "name_en": "Medium close-up (MCU)",
        "framing": "Medium close-up from chest up, capturing head gestures, upper torso clothing, and hands holding ski poles.",
        "camera_rec": "gentle push-in or subtle tracking",
        "lens": "50mm anamorphic lens, natural cinematic perspective",
    },
    "ms": {
        "name_cn": "中景",
        "name_en": "Medium shot (MS)",
        "framing": "Medium shot from waist up, dynamic skiing posture, leaning body angle, and ski jacket texture.",
        "camera_rec": "handheld tracking alongside or dynamic push-in",
        "lens": "35mm anamorphic prime lens, cinematic field of view",
    },
    "fs": {
        "name_cn": "全景",
        "name_en": "Full shot (FS)",
        "framing": "Full shot showing complete body from head to ski boots, showing posture, ski gear, skis carving on snow surface.",
        "camera_rec": "tracking camera moving in sync with the skier",
        "lens": "28mm wide lens, deep depth of field, clear ground action",
    },
    "ws": {
        "name_cn": "远景",
        "name_en": "Wide shot (WS)",
        "framing": "Wide establishing shot of the snowy slope and alpine landscape with the skier navigating the terrain.",
        "camera_rec": "slow pull-back or sweeping pan following the movement",
        "lens": "24mm wide-angle cinema lens, expansive mountain background",
    },
    "ews": {
        "name_cn": "大远景",
        "name_en": "Extreme wide shot (EWS)",
        "framing": "Grand panoramic mountain landscape with vast snowfields, tiny human figure carving down the slope.",
        "camera_rec": "static wide vista or very slow sweeping crane pan",
        "lens": "18mm ultra-wide lens, dramatic natural scenery",
    },
}

# ── 运镜库 (Camera Movements) ──────────────────────────────────────────────────

CAMERA_MOVES = {
    "handheld_tracking": {
        "name_cn": "手持微晃动态跟镜",
        "desc_en": "Dynamic handheld tracking camera moving forward alongside the subject, realistic slight organic shake capturing the speed.",
        "best_for": ("fs", "ms", "mcu"),
    },
    "slow_push_in": {
        "name_cn": "缓慢推镜",
        "desc_en": "Camera slowly and smoothly pushes in towards the subject, gradually intensifying emotional and dramatic focus.",
        "best_for": ("cu", "mcu", "ms"),
    },
    "dolly_pull_out": {
        "name_cn": "匀速拉镜头",
        "desc_en": "Camera slowly pulls back and widens, revealing the surrounding expansive snowy landscape and relief.",
        "best_for": ("ms", "fs", "ws"),
    },
    "low_angle_pan": {
        "name_cn": "低机位平移追拍",
        "desc_en": "Low-angle camera skimming close to the snow surface, panning smoothly to track the rapid skiing action.",
        "best_for": ("fs", "ms", "ws"),
    },
    "static_lock_off": {
        "name_cn": "锁定机位拍摄",
        "desc_en": "Static locked-off camera at eye-level, stable framing allowing natural physical tumble and movement within the frame.",
        "best_for": ("ecu", "cu", "ms"),
    },
    "action_cam_lead": {
        "name_cn": "领航前置机位",
        "desc_en": "Leading tracking camera gliding smoothly backward just ahead of the subject down the slope.",
        "best_for": ("ms", "fs"),
    },
}

# ── 动作与物理动力学规则库 (Action & Physics Dynamics) ───────────────────────────

PHYSICS_RULES = {
    "ski_gliding": {
        "name_cn": "滑雪滑行态",
        "dynamics_en": "Skis carve crisp edges into packed snow, spraying fine powder laterally. Forward momentum with low center of gravity and balanced posture.",
        "snow_fx": "fine powder snow spray slicing sideways off the ski edges",
    },
    "ski_imbalance": {
        "name_cn": "失衡绊倒物理",
        "dynamics_en": "The ski tips cross unexpectedly, causing immediate loss of balance. Body momentum pitches forward and sideways under inertia.",
        "snow_fx": "sudden burst of snow as the ski edge catches the surface",
    },
    "tumble_impact": {
        "name_cn": "扑倒翻滚物理",
        "dynamics_en": "Subject tumbles forward into deep powder snow, sliding on chest and back. Kinetic momentum gradually decelerates against soft snow resistance.",
        "snow_fx": "a billowing cloud of soft powder snow erupts into the air, particles settling over jacket and goggles",
    },
    "rest_recovery": {
        "name_cn": "静止停歇与释怀",
        "dynamics_en": "Subject comes to a gentle rest in the soft snow bank, brushing snow off gloves and jacket, letting out a relieved warm breath into the frosty air.",
        "snow_fx": "powder snow clinging to waterproof fabric, tiny ice crystals sparkling in harsh sunlight",
    },
}

MAX_SHOT_DURATION_SEC: float = 5.0
MIN_SHOT_DURATION_SEC: float = 1.0


@dataclass
class CinematicShot:
    shot_index: int
    size: str = "ms"                                      # ecu | cu | mcu | ms | fs | ws | ews
    angle: str = "eye_level"                              # eye_level | low_angle | high_angle | dutch
    camera_move: str = "handheld_tracking"                # key from CAMERA_MOVES
    transition_type: str = "cut"                          # continuation (尾帧接续) | cut (切镜)
    first_frame_desc: str = ""
    action_physics: str = ""
    audio_cues: str = ""
    duration_sec: float = 3.5
    # 结构化纳逗Pro提示词块
    visual_style: str = "自然电影级质感，高对比雪地光影，手持摄影质感，35mm电影宽银幕镜头。"
    scene_setting: str = "阳光刺眼的高山雪坡，皑皑白雪覆盖的滑雪道，远处可见连绵雪山轮廓。"
    character_ref: str = "参考 [滑雪服定妆照] [多角度定妆照] 中的人物，身穿鲜艳防风滑雪服与专业滑雪装备。"
    prompt_blocks: dict[str, str] = field(default_factory=dict)
    motion_prompt_en: str = ""
    first_frame_prompt_en: str = ""

    def __post_init__(self):
        # 硬性规范：单镜头片段时长上限绝对不可超过 5.0s
        if self.duration_sec > MAX_SHOT_DURATION_SEC:
            log.warning("分镜 %d 时长 %.1fs 超过硬性规范上限 %.1fs，强制截断限幅为 %.1fs",
                        self.shot_index, self.duration_sec, MAX_SHOT_DURATION_SEC, MAX_SHOT_DURATION_SEC)
            self.duration_sec = MAX_SHOT_DURATION_SEC
        elif self.duration_sec < MIN_SHOT_DURATION_SEC:
            self.duration_sec = MIN_SHOT_DURATION_SEC


def validate_montage_sequence(shots: list[CinematicShot]) -> list[str]:
    """电影级剪辑序列硬性规范校验器 (Cinematic Montage Lint Rules)。

    硬性规则：
    1. 【时长硬上限】：任何单镜头时长绝对不可超过 5.0 秒；
    2. 【动作转折必须分切 (Cut on Action)】：若动作未在单镜头内完整闭环（如高速运动转为摔跌），
       下一镜必须采用 'cut' 并剧烈改变景别/机位（如 WS -> CU），严禁盲目使用 'continuation' 导致同机位重复跌倒/动作顿挫；
    3. 【恢复收尾分切】：恢复姿态（如起身、站定）必须通过中景/全景分切（cut）后拉完成闭环。
    """
    errors: list[str] = []
    tumble_keywords = ("fall", "tumble", "slip", "drop", "tip", "lose balance", "摔", "倒", "倾斜")

    for idx, s in enumerate(shots):
        if s.duration_sec > MAX_SHOT_DURATION_SEC + 1e-4:
            errors.append(f"镜头 {s.shot_index} 超出 5.0s 硬性规范上限: {s.duration_sec}s > {MAX_SHOT_DURATION_SEC}s")

        if idx > 0:
            prev = shots[idx - 1]
            prev_has_tumble = any(kw in prev.action_physics.lower() for kw in tumble_keywords)
            curr_has_tumble = any(kw in s.action_physics.lower() for kw in tumble_keywords)

            # 严禁假连贯顿挫（False Continuation）：前一镜正在跌倒，后一镜又用尾帧续着跌倒
            if s.transition_type == "continuation" and prev_has_tumble and curr_has_tumble:
                errors.append(
                    f"镜头 {prev.shot_index} 与镜头 {s.shot_index} 违反剪辑规范：上一镜头跌倒未完成，"
                    f"下一镜头不得使用尾帧延续 (continuation) 重复摔倒！必须在动作转折点执行分切 (cut) 并切换景别 (如 WS->CU)。"
                )

    return errors


# ── 纳逗Pro结构化提示词格式化与翻译 ──────────────────────────────────────────────

def format_nadou_prompt_blocks(shot: CinematicShot) -> str:
    """按用户截图（纳逗Pro）标准生成分块格式文本。"""
    blocks = [
        f"【视觉风格】{shot.visual_style}",
        f"【场景设定】{shot.scene_setting}",
        f"【角色参考】{shot.character_ref}",
        f"【画面构图】{shot.first_frame_desc}",
        f"【运镜】{shot.prompt_blocks.get('运镜') or shot.camera_move}",
        f"【动作物理】{shot.action_physics}",
        f"【音频拟音】{shot.audio_cues or '环境风声与雪地音效，无对白。'}",
    ]
    return "\n\n".join(blocks)


def build_ltx_motion_prompt(shot: CinematicShot, *, is_continuation: bool = False) -> str:
    """构建最适配 LTX-2.5 扩散视频模型的英文运动提示词。

    LTX 规范：
    1. 首句明确物理动量和核心动作；
    2. 按时间轴叙述动作演变与雪地物理交互；
    3. 若为尾帧接续 (continuation)，显式声明无缝接续上一瞬间动量；
    4. 尾句为单一严格限幅的运镜指令；
    5. 附加电影画风锚点与音效指示。
    """
    scale_info = SHOT_SCALES.get(shot.size.lower(), SHOT_SCALES["ms"])
    cam_info = CAMERA_MOVES.get(shot.camera_move, CAMERA_MOVES["handheld_tracking"])

    parts = []
    if is_continuation:
        parts.append("The action continues seamlessly from the initial frame without any jump cuts.")

    if shot.action_physics:
        parts.append(shot.action_physics)

    # 运镜放在动作末尾
    parts.append(f"Camera movement: {cam_info['desc_en']}.")

    lead_motion = " ".join(parts)
    style_suffix = ("Cinematic live-action film footage, photorealistic, natural skin texture, "
                    "authentic snow dynamics and lighting reflections. No animation, no cartoon.")
    audio_part = f"Audio: {shot.audio_cues or 'crisp wind rushing past and soft snow crunching'}. No dialogue."

    return f"{lead_motion}\n\n{style_suffix}\n\n{audio_part}"


def build_first_frame_prompt(shot: CinematicShot, scene_desc: str, character_desc: str) -> str:
    """构建高质量首帧 (FLUX 图像编辑/文生图) 提示词。

    严格遵循摄影指导 (DP)：明确景别、视点、人体姿态、光影，去掉动态运镜语句。
    """
    scale_info = SHOT_SCALES.get(shot.size.lower(), SHOT_SCALES["ms"])
    angle_phrase = {
        "low_angle": "low angle from near the snow surface looking up",
        "high_angle": "high angle looking down at the snowy slope",
        "dutch": "dynamic tilted dutch angle creating tension",
        "eye_level": "eye-level cinematic angle",
    }.get(shot.angle, "eye-level")

    elements = [
        f"A cinematic {scale_info['name_en'].lower()} at {angle_phrase}.",
        f"Subject: {character_desc}.",
        f"Staging & Pose: {shot.first_frame_desc}.",
        f"Environment: {scene_desc}.",
        f"Optics & Lighting: {scale_info['lens']}, harsh crisp mountain sunlight, bright white snow reflections with natural shadows.",
        "Live-action 35mm film still, photorealistic, sharp focus, perfectly rendered hands and ski gear, no artifacts, no split screen.",
    ]
    return " ".join(elements)


# ── 导演规划系统 (Director Orchestrator) ──────────────────────────────────────

DIRECTOR_PLAN_SYSTEM = """You are a world-class cinematic film director and Director of Photography (DP) specializing in realistic, physically accurate short films (2 to 4 shots, total 10 to 15 seconds) for local diffusion models.

Input: The creator's concept, target shots count, character details, and location.

Your core mission:
1. PHYSICAL LAWS & REALISM:
   - Respect momentum conservation, gravity, and material physics.
   - For sports/action (e.g. skiing, running): Speed carries forward; crossing skis leads to pitch forward and tumbles into powder snow spray.
   - NEVER create sudden impossible morphs or instantaneous teleportation.
2. CINEMATOGRAPHIC GRAMMAR:
   - Vary shot sizes deliberately: Shot 1 Setup (Medium Shot MS or Close-Up CU) -> Shot 2 Climax/Impact (Full Shot FS or Low Angle MCU) -> Shot 3 Resolution/Reaction (Close-Up CU or Wide Shot WS).
   - Each shot MUST have ONE primary camera movement (e.g. handheld tracking, slow push-in, low angle pan, static lock-off). NEVER use orbits, spins, or whip pans.
3. TRANSITION & CONTINUITY (画面过渡与接续):
   - For sequential actions (e.g. losing balance in Shot 1 -> tumbling in Shot 2), mark transition as "continuation". Shot 2 will directly inherit Shot 1's LAST FRAME as its starting frame!
   - For perspective jumps (e.g. wide tumble -> tight close-up of face laughing in snow), mark transition as "cut".
4. OUTPUT FORMAT:
   Return ONLY a valid JSON object matching this schema:
   {
     "title": "Short Film Title in Chinese",
     "style": "电影级真实质感，高对比雪地光影...",
     "scene": "English description of the scene without people, <= 60 words",
     "character": "English description of the character outfit, gear, and look, <= 50 words",
     "audio_ambient": "English description of ambient sound (wind, snow rustle)",
     "shots": [
       {
         "shot_index": 1,
         "size": "ms|cu|fs|ecu|ws",
         "angle": "eye_level|low_angle|high_angle|dutch",
         "camera_move": "handheld_tracking|slow_push_in|dolly_pull_out|low_angle_pan|static_lock_off",
         "transition": "cut|continuation",
         "first_frame": "Precise English static snapshot (pose, position, framing, gear), <= 60 words",
         "action_physics": "English description of motion and physics (momentum, ski carving, powder snow plumes), <= 60 words",
         "audio": "Specific sound cues for this shot",
         "seconds": 3.5
       }
     ]
   }
"""


def plan_cinematic_film(db: Any, idea: str, shots_count: int = 3, *,
                        character_look: str = "", scene_desc: str = "") -> dict[str, Any]:
    """使用大模型调用专业导演系统进行物理化、影视级分镜规划。"""
    from app.pipelines.director_review import _chat, parse_json

    user_payload = {
        "idea": idea,
        "shots_count": max(2, min(4, shots_count)),
        "character_hint": character_look,
        "scene_hint": scene_desc,
    }

    import json
    text, model_name = _chat(db, DIRECTOR_PLAN_SYSTEM, json.dumps(user_payload, ensure_ascii=False),
                             max_tokens=6000, temperature=0.4)
    data = parse_json(text)

    parsed_shots: list[CinematicShot] = []
    raw_shots = data.get("shots") or []
    for i, s in enumerate(raw_shots[:shots_count]):
        if not isinstance(s, dict):
            continue
        size = str(s.get("size") or "ms").lower()
        if size not in SHOT_SCALES:
            size = "ms"
        cam = str(s.get("camera_move") or "handheld_tracking").lower()
        if cam not in CAMERA_MOVES:
            cam = "handheld_tracking"
        trans = "continuation" if str(s.get("transition")).lower() == "continuation" and i > 0 else "cut"
        sec = max(2.0, min(5.0, float(s.get("seconds") or 3.5)))

        c_shot = CinematicShot(
            shot_index=i + 1,
            size=size,
            angle=str(s.get("angle") or "eye_level").lower(),
            camera_move=cam,
            transition_type=trans,
            first_frame_desc=str(s.get("first_frame") or "").strip()[:500],
            action_physics=str(s.get("action_physics") or "").strip()[:500],
            audio_cues=str(s.get("audio") or "").strip()[:200],
            duration_sec=sec,
            visual_style=str(data.get("style") or "自然电影级质感，高对比雪地光影，手持摄影质感。"),
            scene_setting=str(data.get("scene") or "高山雪坡雪道，远处可见雪山轮廓。"),
            character_ref=f"参考定妆照中的人物，穿着滑雪装备与滑雪服。",
            prompt_blocks={
                "运镜": CAMERA_MOVES.get(cam, {}).get("name_cn", cam),
            },
        )
        c_shot.motion_prompt_en = build_ltx_motion_prompt(c_shot, is_continuation=(trans == "continuation"))
        parsed_shots.append(c_shot)

    if not parsed_shots:
        raise RuntimeError("导演规划未能拆解出有效镜头")

    return {
        "title": str(data.get("title") or "影视成片")[:40],
        "style": str(data.get("style") or "自然电影级质感"),
        "scene": str(data.get("scene") or "Snowy alpine slope")[:500],
        "character": str(data.get("character") or "Skier in bright ski suit")[:400],
        "audio_ambient": str(data.get("audio_ambient") or "Rushing wind and crunching snow")[:300],
        "shots": parsed_shots,
        "model": model_name,
    }
