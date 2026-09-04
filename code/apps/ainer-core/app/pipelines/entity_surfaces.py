"""生产链里的人物称呼索引。

目标世界译本会把「沈砚」写成 ``Ethan Ashford``，昵称与敬称也会一起变化。
后续剧本、分镜、表演和配音若各自只认源文名，就会把同一个人当成新角色。
这里把源名、别名、源称谓、目标名和目标称谓统一回绑到 WorldEntity。

同一字面若属于两个人则不进入 ``by_surface``。静默挑第一个比不解析更危险：
错绑会一路污染身份锚、服装和音色，而未解析至少会被质量门禁看见。
"""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import EntityAppellation, EntityWorldName, WorldEntity


@dataclass(frozen=True)
class EntitySurfaceIndex:
    entities: tuple[WorldEntity, ...]
    by_surface: dict[str, WorldEntity]
    surfaces_by_entity: dict[str, tuple[str, ...]]
    canonical_by_entity: dict[str, str]
    ambiguous: tuple[str, ...]

    def catalog(self) -> list[dict[str, object]]:
        """给模型看的生产姓名表；name 始终优先使用当前目标世界名。"""
        return [
            {
                "name": self.canonical_by_entity[e.id],
                "accepted_surfaces": list(self.surfaces_by_entity[e.id]),
                "summary": (e.summary or "")[:80],
            }
            for e in self.entities
            if e.kind.value == "character"
        ]


def load_entity_surfaces(
    db: Session, novel_id: str, *, transform_id: str | None = None,
) -> EntitySurfaceIndex:
    entities = tuple(db.execute(
        select(WorldEntity).where(WorldEntity.novel_id == novel_id)
    ).scalars())
    if not entities:
        return EntitySurfaceIndex((), {}, {}, {}, ())

    entity_ids = [e.id for e in entities]
    target_names: dict[str, str] = {}
    if transform_id:
        for row in db.execute(
            select(EntityWorldName).where(
                EntityWorldName.transform_id == transform_id,
                EntityWorldName.entity_id.in_(entity_ids),
            )
        ).scalars():
            name = (row.target_name or "").strip()
            if name:
                target_names[row.entity_id] = name

    appellations: dict[str, list[str]] = {e.id: [] for e in entities}
    for row in db.execute(
        select(EntityAppellation).where(EntityAppellation.entity_id.in_(entity_ids))
    ).scalars():
        source = (row.source_surface or "").strip()
        if source:
            appellations[row.entity_id].append(source)
        if transform_id and row.transform_id == transform_id:
            target = (row.target_surface or "").strip()
            if target:
                appellations[row.entity_id].append(target)

    surfaces_by_entity: dict[str, tuple[str, ...]] = {}
    buckets: dict[str, list[WorldEntity]] = {}
    canonical: dict[str, str] = {}
    for entity in entities:
        preferred = target_names.get(entity.id) or (entity.display_name or "").strip()
        canonical[entity.id] = preferred
        raw = [
            preferred,
            entity.display_name,
            *(entity.aliases_json or []),
            *appellations.get(entity.id, []),
        ]
        surfaces = tuple(dict.fromkeys(
            str(value).strip() for value in raw if str(value or "").strip()
        ))
        surfaces_by_entity[entity.id] = surfaces
        for surface in surfaces:
            buckets.setdefault(surface, []).append(entity)

    by_surface = {
        surface: owners[0]
        for surface, owners in buckets.items()
        if len({owner.id for owner in owners}) == 1
    }
    ambiguous = tuple(sorted(
        surface for surface, owners in buckets.items()
        if len({owner.id for owner in owners}) > 1
    ))
    return EntitySurfaceIndex(
        entities, by_surface, surfaces_by_entity, canonical, ambiguous,
    )
