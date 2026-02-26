from __future__ import annotations

import random
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from ainern2d_shared.ainer_db_models.content_models import Chapter, Scene, Shot
from ainern2d_shared.ainer_db_models.enum_models import RunStatus
from ainern2d_shared.schemas.entity import EntityPack
from ainern2d_shared.schemas.timeline import ShotPlan, ShotPlanItem


class ShotPlanGenerator:
    def __init__(self, db: Session) -> None:
        self.db = db

    def generate(self, run_id: str, chapter_id: str, entity_pack: EntityPack) -> ShotPlan:
        chapter = self.db.get(Chapter, chapter_id)
        if chapter is None:
            raise LookupError(f"Chapter id={chapter_id} not found")

        scenes = (
            self.db.execute(
                select(Scene).filter_by(
                    tenant_id=chapter.tenant_id,
                    project_id=chapter.project_id,
                    novel_id=chapter.novel_id,
                )
            )
            .scalars()
            .all()
        )

        existing_shots = (
            self.db.execute(select(Shot).filter_by(chapter_id=chapter_id))
            .scalars()
            .all()
        )
        existing_map = {(s.scene_id, s.shot_no): s for s in existing_shots}

        entity_desc = "; ".join(
            f"{e.display_name}({e.entity_type})" for e in entity_pack.entities
        )

        items: list[ShotPlanItem] = []
        shot_no = 1
        for scene in scenes:
            key = (scene.id, shot_no)
            if key not in existing_map:
                duration_ms = random.randint(3000, 8000)
                prompt = self._build_prompt(scene, entity_desc)
                shot = Shot(
                    id=f"shot_{uuid4().hex}",
                    tenant_id=chapter.tenant_id,
                    project_id=chapter.project_id,
                    chapter_id=chapter_id,
                    scene_id=scene.id,
                    shot_no=shot_no,
                    duration_ms=duration_ms,
                    status=RunStatus.queued,
                    prompt_json={"prompt": prompt},
                )
                self.db.add(shot)
                self.db.flush()
            else:
                shot = existing_map[key]
                duration_ms = shot.duration_ms or random.randint(3000, 8000)
                prompt = (shot.prompt_json or {}).get("prompt", "")

            items.append(
                ShotPlanItem(
                    shot_id=shot.id,
                    scene_id=scene.id,
                    prompt=prompt,
                    duration_ms=duration_ms,
                )
            )
            shot_no += 1

        return ShotPlan(run_id=run_id, shots=items)

    @staticmethod
    def _build_prompt(scene: Scene, entity_desc: str) -> str:
        parts = []
        if scene.description:
            parts.append(scene.description)
        parts.append(f"Scene: {scene.label}")
        if entity_desc:
            parts.append(f"Entities: {entity_desc}")
        return ". ".join(parts)
