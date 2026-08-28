"""按语言定位世界观映射。

语言码不足以唯一确定译本 —— 「维多利亚英国」与「摄政英国」都是 en-GB，
「西部拓荒」与「禁酒令时期」都是 en-US。所以下游一律按 transform_id 取译文，
只有入口（API 路径、后台选择器）还用语言码，在这里换成 transform。

同一 (小说, 语言) 下允许存在多个映射，但只能有一个 active ——
active 就是「这个语言当前对外的那一版」。要切版本就改 active，
不需要把译文搬来搬去。
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import TransformStatus, WorldTransform


def active_transform(
    db: Session, novel_id: str, language_code: str
) -> WorldTransform | None:
    """取该语言当前生效的映射。多版并存时取 version 最大的 active。"""
    return db.execute(
        select(WorldTransform).where(
            WorldTransform.novel_id == novel_id,
            WorldTransform.target_language_code == language_code,
            WorldTransform.status == TransformStatus.active,
        ).order_by(WorldTransform.version.desc())
    ).scalars().first()


def transform_ids_for(
    db: Session, novel_id: str, language_code: str
) -> list[str]:
    """该语言下所有映射的 id，按 active 优先。

    读取路径用它兜底：老数据的 transform 可能已被停用，
    按 active 一刀切会让已有译文突然读不出来。
    """
    rows = list(
        db.execute(
            select(WorldTransform).where(
                WorldTransform.novel_id == novel_id,
                WorldTransform.target_language_code == language_code,
            ).order_by(
                (WorldTransform.status == TransformStatus.active).desc(),
                WorldTransform.version.desc(),
            )
        ).scalars()
    )
    return [t.id for t in rows]
