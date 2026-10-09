"""关键帧挑图：一镜出几张候选，让本机视觉模型对着定妆照和画面要求挑一张。

挑图标准借 HKUDS/ViMax 的 best_image_selector（MIT）：
角色一致（脸、发型、体型、服装和定妆照对得上）> 人数和站位对 > 动作和细节符合描述 > 没有畸形（多出手脚、人重复、脸糊）。

实跑拦得住的坏图：三个人画成四个（被霸凌者出现两次）、地上多躺一个人、举手的姿势画成四只手。
图片按 data URL 内联发给模型（LM Studio 的 OpenAI 兼容接口），先缩到长边 640，省时间。
"""
from __future__ import annotations

import base64
import io
import logging
from pathlib import Path
from typing import Any, Sequence

from app.pipelines.director_review import ReviewError, _chat, parse_json

log = logging.getLogger("ainer-core")

PURPOSE = "frame_select"
LONG_SIDE = 640

SYSTEM = """You are a professional visual assessment expert for film keyframes.
You get reference portraits of the characters (each with a short description), then several candidate keyframes, then the target description.
Pick the candidate that best satisfies, in this order of priority:
1. Character consistency with the references: face, hairstyle and hair colour, body shape, outfit.
2. Exactly the right people: the right number of people, nobody duplicated, no extra people, nobody missing.
3. Anatomy: no extra arms, hands or legs, no melted faces, no people merged into each other.
4. The described action, pose, expression and specific details (e.g. where the blood is), and the described positions in frame.
5. A clean single film frame: no borders, text, split screen or collage.
If none is good, still pick the least bad one and say what is wrong.
Output ONLY a JSON object: {"best": <candidate index>, "reason": "<one sentence in Chinese>", "problems": ["<中文：各候选的硬伤>"]}"""


def _media_path(url: str) -> Path | None:
    """本库 /media 地址 → 本地文件。"""
    from app.capability.mediastore import media_root

    i = url.find("/media/")
    if i < 0:
        return None
    fname = url[i + len("/media/"):].split("?")[0]
    p = Path(media_root()) / fname
    if p.exists():
        return p
    fallback = Path(__file__).resolve().parents[2] / "var" / "media" / fname
    return fallback if fallback.exists() else None


def data_url(url: str) -> str:
    """把图缩到长边 LONG_SIDE 后编码成 data URL；不是本库地址就原样返回（让模型自己去取）。"""
    from PIL import Image

    p = _media_path(url)
    if p is None:
        return url
    im = Image.open(p).convert("RGB")
    s = LONG_SIDE / max(im.size)
    if s < 1:
        im = im.resize((round(im.width * s), round(im.height * s)))
    buf = io.BytesIO()
    im.save(buf, format="JPEG", quality=88)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


def build_message(refs: Sequence[tuple[str, str]], candidates: Sequence[str], target: str) -> list[dict[str, Any]]:
    """多模态 user 消息：参考图（带说明）→ 候选图（编号从 0 起）→ 目标描述。"""
    parts: list[dict[str, Any]] = []
    for i, (desc, url) in enumerate(refs):
        parts.append({"type": "text", "text": f"Reference image {i}: {desc}"})
        parts.append({"type": "image_url", "image_url": {"url": data_url(url)}})
    for i, url in enumerate(candidates):
        parts.append({"type": "text", "text": f"Candidate {i}:"})
        parts.append({"type": "image_url", "image_url": {"url": data_url(url)}})
    parts.append({"type": "text", "text": f"Target description:\n{target}\n\n"
                                         f"There are exactly {len(candidates)} candidates, indexed 0 to {len(candidates) - 1}."})
    return parts


def pick(db, refs: Sequence[tuple[str, str]], candidates: Sequence[str], target: str) -> dict[str, Any]:
    """挑一张。返回 {"best": int, "reason": str, "problems": [...], "model": str}；模型不可用时退回第 0 张并写明原因。"""
    if len(candidates) < 2:
        return {"best": 0, "reason": "只有一张候选", "problems": [], "model": ""}
    try:
        text, model = _chat(db, SYSTEM, build_message(refs, candidates, target), purpose=PURPOSE,
                            max_tokens=4000, temperature=0.0)
        data = parse_json(text)
        best = int(data.get("best"))
        if not 0 <= best < len(candidates):
            raise ReviewError(f"挑了不存在的候选 {best}")
        return {"best": best, "reason": str(data.get("reason") or "")[:300],
                "problems": [str(x)[:200] for x in data.get("problems") or [] if x][:6], "model": model}
    except Exception as exc:                          # noqa: BLE001 —— 挑图失败不该让这一镜失败：用第一张
        log.warning("关键帧挑图失败，用第一张：%s", exc)
        return {"best": 0, "reason": f"挑图没做成，用了第一张：{exc}"[:300], "problems": [], "model": ""}
