"""API+DB smoke tests for SKILL 23~30 product layer."""
from __future__ import annotations

import os
import sys
from unittest.mock import patch as mock_patch
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import delete

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../../../shared"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../"))

from ainern2d_shared.ainer_db_models.auth_models import Project, ProjectMember, User
from ainern2d_shared.ainer_db_models.content_models import (
    Artifact,
    Chapter,
    Novel,
    Shot,
    TimelineSegment,
)
from ainern2d_shared.ainer_db_models.enum_models import ArtifactType, EntityType, RenderStage, RunStatus
from ainern2d_shared.ainer_db_models.governance_models import (
    CreativePolicyStack,
    PersonaPack,
    PersonaPackVersion,
    ShotDslCompilation,
)
from ainern2d_shared.ainer_db_models.knowledge_models import Entity
from ainern2d_shared.ainer_db_models.pipeline_models import (
    Job,
    RenderRun,
    RunCheckpoint,
    RunPatchRecord,
    WorkflowEvent,
)
from ainern2d_shared.ainer_db_models.preview_models import (
    EntityContinuityProfile,
    EntityInstanceLink,
    PersonaDatasetBinding,
    PersonaIndexBinding,
)
from ainern2d_shared.ainer_db_models.provider_models import ModelProfile, ModelProvider
from ainern2d_shared.ainer_db_models.rag_models import KbVersion, RagCollection, RagDocument
from ainern2d_shared.db.session import SessionLocal


@pytest.mark.skipif(
    not os.getenv("DATABASE_URL"),
    reason="requires DATABASE_URL for API+DB smoke",
)
def test_skill_23_24_28_auth_chapter_task_snapshot_flow():
    suffix = uuid4().hex[:8]
    tenant_id = f"t_p23_{suffix}"
    project_id = f"proj_p23_{suffix}"

    from app.api.deps import get_db
    from app.api.v1.auth import router as auth_router
    from app.api.v1.novels import router as novels_router
    from app.api.v1.projects import router as projects_router
    from app.api.v1.tasks import router as tasks_router

    def _override_get_db():
        local = SessionLocal()
        try:
            yield local
        finally:
            local.close()

    app = FastAPI()
    app.include_router(auth_router)
    app.include_router(projects_router)
    app.include_router(novels_router)
    app.include_router(tasks_router)
    app.dependency_overrides[get_db] = _override_get_db

    try:
        with TestClient(app) as client:
            register = client.post(
                "/api/v1/auth/register",
                json={
                    "username": f"u_{suffix}",
                    "password": "pw",
                    "email": f"u_{suffix}@ainer.test",
                },
            )
            assert register.status_code == 201
            user_id = register.json()["user_id"]

            login = client.post(
                "/api/v1/auth/login",
                json={"username": f"u_{suffix}@ainer.test", "password": "pw"},
            )
            assert login.status_code == 200
            assert login.json()["user_id"] == user_id

            project = client.post(
                "/api/v1/projects",
                json={
                    "slug": f"slug-{suffix}",
                    "name": f"proj-{suffix}",
                    "description": "skill23-24",
                    "tenant_id": tenant_id,
                },
            )
            assert project.status_code == 201
            created_project_id = project.json()["project_id"]
            assert created_project_id

            acl_upsert = client.put(
                f"/api/v1/auth/projects/{created_project_id}/acl/{user_id}",
                json={"tenant_id": tenant_id, "role": "editor"},
            )
            assert acl_upsert.status_code == 200
            acl_list = client.get(
                f"/api/v1/auth/projects/{created_project_id}/acl",
                params={"tenant_id": tenant_id},
            )
            assert acl_list.status_code == 200
            assert any(item["user_id"] == user_id for item in acl_list.json())

            novel = client.post(
                "/api/v1/novels",
                json={
                    "tenant_id": tenant_id,
                    "project_id": created_project_id,
                    "title": f"novel-{suffix}",
                    "summary": "s",
                    "default_language_code": "zh",
                },
            )
            assert novel.status_code == 201
            novel_id = novel.json()["id"]

            chapter = client.post(
                f"/api/v1/novels/{novel_id}/chapters",
                json={
                    "tenant_id": tenant_id,
                    "project_id": created_project_id,
                    "chapter_no": 1,
                    "language_code": "zh",
                    "title": "ch1",
                    "markdown_text": "这是一个测试章节，包含足够长的文本用于预览规划与任务创建。\n\n角色进入场景并开始对话。",
                },
            )
            assert chapter.status_code == 201
            chapter_id = chapter.json()["id"]

            chapter_update = client.put(
                f"/api/v1/chapters/{chapter_id}",
                json={
                    "markdown_text": "这是更新后的章节文本，继续保持足够长度。\n\n角色冲突升级并切换场景。",
                    "revision_note": "patch-1",
                },
            )
            assert chapter_update.status_code == 200

            revisions = client.get(f"/api/v1/chapters/{chapter_id}/revisions")
            assert revisions.status_code == 200
            assert len(revisions.json()) >= 1

            preview = client.post(
                f"/api/v1/chapters/{chapter_id}/preview-plan",
                json={
                    "tenant_id": tenant_id,
                    "project_id": created_project_id,
                    "target_output_language": "zh-CN",
                    "genre": "wuxia",
                    "story_world_setting": "historical",
                },
            )
            assert preview.status_code == 200
            preview_payload = preview.json()
            assert preview_payload["skill_01_status"] in {"ready_for_routing", "review_required"}
            assert preview_payload["scene_count"] >= 1

            submit = client.post(
                f"/api/v1/chapters/{chapter_id}/tasks",
                json={
                    "tenant_id": tenant_id,
                    "project_id": created_project_id,
                    "requested_quality": "standard",
                    "language_context": "zh-CN",
                    "payload": {
                        "culture_pack_id": "cn_wuxia",
                        "persona_pack_version_id": "persona_A_v1",
                    },
                },
            )
            assert submit.status_code == 202
            run_id = submit.json()["run_id"]

            snapshot = client.get(f"/api/v1/runs/{run_id}/snapshot")
            assert snapshot.status_code == 200
            snap = snapshot.json()["snapshot"]
            assert "providers" in snap
            assert "requested_payload" in snap
    finally:
        app.dependency_overrides.clear()
        _cleanup_scope(tenant_id, project_id)


@pytest.mark.skipif(
    not os.getenv("DATABASE_URL"),
    reason="requires DATABASE_URL for API+DB smoke",
)
def test_skill_25_26_27_29_30_config_rag_culture_assets_timeline_patch_flow():
    suffix = uuid4().hex[:8]
    tenant_id = f"t_p25_{suffix}"
    project_id = f"proj_p25_{suffix}"

    from app.api.deps import get_db
    from app.api.v1.assets import router as assets_router
    from app.api.v1.config_center import router as config_router
    from app.api.v1.culture_packs import router as culture_router
    from app.api.v1.rag_console import router as rag_router
    from app.api.v1.timesline import router as timeline_router

    db = SessionLocal()
    try:
        # Seed base content/run data for asset+timeline APIs.
        novel_id = f"novel_{suffix}"
        chapter_id = f"chapter_{suffix}"
        shot_id = f"shot_{suffix}"
        run_id = f"run_{suffix}"
        artifact_id = f"artifact_{suffix}"

        db.add(
            Novel(
                id=novel_id,
                tenant_id=tenant_id,
                project_id=project_id,
                trace_id=f"tr_{suffix}",
                correlation_id=f"cr_{suffix}",
                idempotency_key=f"idem_novel_{suffix}",
                title="seed novel",
                summary="seed",
            )
        )
        db.commit()

        db.add(
            Chapter(
                id=chapter_id,
                tenant_id=tenant_id,
                project_id=project_id,
                trace_id=f"tr_{suffix}",
                correlation_id=f"cr_{suffix}",
                idempotency_key=f"idem_chapter_{suffix}",
                novel_id=novel_id,
                chapter_no=1,
                language_code="zh",
                raw_text="seed chapter text",
            )
        )
        db.commit()

        db.add(
            Shot(
                id=shot_id,
                tenant_id=tenant_id,
                project_id=project_id,
                trace_id=f"tr_{suffix}",
                correlation_id=f"cr_{suffix}",
                idempotency_key=f"idem_shot_{suffix}",
                chapter_id=chapter_id,
                shot_no=1,
                status=RunStatus.queued,
                prompt_json={},
            )
        )
        db.commit()

        entity_id = f"entity_{suffix}"
        db.add(
            Entity(
                id=entity_id,
                tenant_id=tenant_id,
                project_id=project_id,
                trace_id=f"tr_{suffix}",
                correlation_id=f"cr_{suffix}",
                idempotency_key=f"idem_entity_{suffix}",
                novel_id=novel_id,
                type=EntityType.person,
                label="hero",
                canonical_label="hero",
                traits_json={"costume": "black"},
            )
        )
        db.commit()

        db.add(
            RenderRun(
                id=run_id,
                tenant_id=tenant_id,
                project_id=project_id,
                trace_id=f"tr_{suffix}",
                correlation_id=f"cr_{suffix}",
                idempotency_key=f"idem_run_{suffix}",
                chapter_id=chapter_id,
                status=RunStatus.running,
                stage=RenderStage.plan,
                progress=20,
            )
        )
        db.commit()

        db.add(
            EntityInstanceLink(
                id=f"eil_{suffix}",
                tenant_id=tenant_id,
                project_id=project_id,
                trace_id=f"tr_{suffix}",
                correlation_id=f"cr_{suffix}",
                idempotency_key=f"idem_eil_{suffix}",
                entity_id=entity_id,
                run_id=run_id,
                shot_id=shot_id,
                scene_id=None,
                instance_key="hero_main",
                source_skill="skill_21",
                confidence=0.93,
                meta_json={"source": "test"},
            )
        )
        db.commit()

        db.add(
            Artifact(
                id=artifact_id,
                tenant_id=tenant_id,
                project_id=project_id,
                trace_id=f"tr_{suffix}",
                correlation_id=f"cr_{suffix}",
                idempotency_key=f"idem_artifact_{suffix}",
                run_id=run_id,
                shot_id=shot_id,
                type=ArtifactType.shot_video,
                uri=f"s3://bucket/{artifact_id}.mp4",
                checksum="abc",
                size_bytes=123,
                media_meta_json={"kind": "video"},
            )
        )
        db.add(
            TimelineSegment(
                id=f"seg_{suffix}",
                tenant_id=tenant_id,
                project_id=project_id,
                trace_id=f"tr_{suffix}",
                correlation_id=f"cr_{suffix}",
                idempotency_key=f"idem_seg_{suffix}",
                run_id=run_id,
                shot_id=shot_id,
                track="video",
                start_ms=0,
                end_ms=2500,
                artifact_id=artifact_id,
                meta_json={"scene_id": "SC01"},
            )
        )
        db.add(
            RagDocument(
                id=f"rag_doc_{suffix}",
                tenant_id=tenant_id,
                project_id=project_id,
                trace_id=f"tr_{suffix}",
                correlation_id=f"cr_{suffix}",
                idempotency_key=f"idem_rag_doc_{suffix}",
                collection_id=None,
                kb_version_id=None,
                novel_id=novel_id,
                scope="chapter",
                source_type="note",
                source_id=chapter_id,
                language_code="zh",
                title="seed",
                content_text="wuxia hero sword tavern night",
                metadata_json={},
            )
        )
        db.commit()

        def _override_get_db():
            local = SessionLocal()
            try:
                yield local
            finally:
                local.close()

        app = FastAPI()
        app.include_router(config_router)
        app.include_router(rag_router)
        app.include_router(culture_router)
        app.include_router(assets_router)
        app.include_router(timeline_router)
        app.dependency_overrides[get_db] = _override_get_db

        try:
            with TestClient(app) as client:
                provider = client.post(
                    "/api/v1/config/providers",
                    json={
                        "tenant_id": tenant_id,
                        "project_id": project_id,
                        "name": "openai",
                        "endpoint": "https://api.openai.com/v1",
                        "auth_mode": "api_key",
                        "enabled": True,
                        "access_token": "test_token_value",
                        "model_catalog": ["gpt-4o-mini", "text-embedding-3-large"],
                        "capability_flags": {
                            "supports_text_generation": True,
                            "supports_embedding": True,
                            "supports_multimodal": True,
                            "supports_image_generation": False,
                            "supports_video_generation": False,
                            "supports_tts": False,
                            "supports_stt": False,
                            "supports_tool_calling": True,
                            "supports_reasoning": True,
                        },
                    },
                )
                assert provider.status_code == 200
                provider_id = provider.json()["id"]
                assert provider.json()["access_token_masked"]
                provider_list = client.get(
                    "/api/v1/config/providers",
                    params={"tenant_id": tenant_id, "project_id": project_id},
                )
                assert provider_list.status_code == 200
                assert any(item["id"] == provider_id for item in provider_list.json())

                class _FakeHTTPResponse:
                    status = 200

                    def __enter__(self):
                        return self

                    def __exit__(self, exc_type, exc, tb):
                        return False

                with mock_patch("app.api.v1.config_center.urlopen", return_value=_FakeHTTPResponse()):
                    probe = client.post(
                        f"/api/v1/config/providers/{provider_id}/test-connection",
                        json={
                            "tenant_id": tenant_id,
                            "project_id": project_id,
                            "probe_path": "/models",
                            "timeout_ms": 2000,
                        },
                    )
                assert probe.status_code == 200
                assert probe.json()["connected"] is True
                assert probe.json()["status_code"] == 200

                profile = client.post(
                    "/api/v1/config/profiles",
                    json={
                        "tenant_id": tenant_id,
                        "project_id": project_id,
                        "provider_id": provider_id,
                        "purpose": "planner",
                        "name": "gpt-4o-mini",
                        "params_json": {"temperature": 0.2, "api_key": "secret"},
                    },
                )
                assert profile.status_code == 200
                profile_id = profile.json()["id"]
                profile_list = client.get(
                    "/api/v1/config/profiles",
                    params={"tenant_id": tenant_id, "project_id": project_id},
                )
                assert profile_list.status_code == 200
                assert any(item["id"] == profile_id for item in profile_list.json())
                assert profile.json()["capability_tags"] == []

                role_profile = client.put(
                    "/api/v1/config/role-profiles/director",
                    json={
                        "tenant_id": tenant_id,
                        "project_id": project_id,
                        "role_id": "director",
                        "prompt_style": "cinematic structured output",
                        "default_skills": ["shot_planner", "dialogue_director"],
                        "default_knowledge_scopes": ["director_basic", "project_novel"],
                        "default_model_profile": profile_id,
                        "permissions": {
                            "can_import_data": True,
                            "can_publish_task": True,
                            "can_edit_global_knowledge": False,
                            "can_manage_model_router": False,
                        },
                        "enabled": True,
                        "schema_version": "1.0",
                    },
                )
                assert role_profile.status_code == 200
                assert role_profile.json()["role_id"] == "director"

                skill_registry = client.put(
                    "/api/v1/config/skill-registry/shot_planner",
                    json={
                        "tenant_id": tenant_id,
                        "project_id": project_id,
                        "skill_id": "shot_planner",
                        "input_schema": {"type": "object", "properties": {"chapter_id": {"type": "string"}}},
                        "output_schema": {"type": "object", "properties": {"shot_plan": {"type": "array"}}},
                        "required_knowledge_scopes": ["director_basic", "visual_grammar"],
                        "default_model_profile": profile_id,
                        "tools_required": ["search", "embedding"],
                        "ui_renderer": "timeline",
                        "init_template": "director_bootstrap_v1",
                        "enabled": True,
                        "schema_version": "1.0",
                    },
                )
                assert skill_registry.status_code == 200
                assert skill_registry.json()["skill_id"] == "shot_planner"

                route_map = client.put(
                    "/api/v1/config/feature-route-maps/route_scene_board",
                    json={
                        "tenant_id": tenant_id,
                        "project_id": project_id,
                        "route_id": "route_scene_board",
                        "path": "/studio/scene-board",
                        "component": "StudioSceneBoardPage",
                        "feature_id": "shot_planner",
                        "allowed_roles": ["director", "script_supervisor"],
                        "ui_mode": "timeline",
                        "depends_on": ["rag", "embedding", "minio"],
                        "enabled": True,
                        "schema_version": "1.0",
                    },
                )
                assert route_map.status_code == 200
                assert route_map.json()["route_id"] == "route_scene_board"

                role_profile_list = client.get(
                    "/api/v1/config/role-profiles",
                    params={"tenant_id": tenant_id, "project_id": project_id},
                )
                assert role_profile_list.status_code == 200
                assert any(item["role_id"] == "director" for item in role_profile_list.json())

                skill_registry_list = client.get(
                    "/api/v1/config/skill-registry",
                    params={"tenant_id": tenant_id, "project_id": project_id},
                )
                assert skill_registry_list.status_code == 200
                assert any(item["skill_id"] == "shot_planner" for item in skill_registry_list.json())

                route_map_list = client.get(
                    "/api/v1/config/feature-route-maps",
                    params={"tenant_id": tenant_id, "project_id": project_id, "role_id": "director"},
                )
                assert route_map_list.status_code == 200
                assert any(item["route_id"] == "route_scene_board" for item in route_map_list.json())

                resolved = client.post(
                    "/api/v1/config/role-studio/resolve",
                    json={
                        "tenant_id": tenant_id,
                        "project_id": project_id,
                        "role_id": "director",
                        "skill_id": "shot_planner",
                        "context": {},
                    },
                )
                assert resolved.status_code == 200
                assert resolved.json()["role_profile"]["role_id"] == "director"
                assert resolved.json()["skill_profile"]["skill_id"] == "shot_planner"
                assert resolved.json()["resolved_model_profile"]["id"] == profile_id
                assert "director_basic" in resolved.json()["resolved_knowledge_scopes"]
                assert any(item["route_id"] == "route_scene_board" for item in resolved.json()["visible_routes"])

                routing = client.put(
                    "/api/v1/config/stage-routing",
                    json={
                        "tenant_id": tenant_id,
                        "project_id": project_id,
                        "routes": {"skill_01": "planner", "skill_10": "planner"},
                        "fallback_chain": {"planner": ["fallback_a", "fallback_b"]},
                        "feature_routes": {"embedding": "embedding", "text_generation": "planner"},
                    },
                )
                assert routing.status_code == 200
                assert "feature_routes" in routing.json()

                feature_matrix = client.get(
                    "/api/v1/config/feature-matrix",
                    params={"tenant_id": tenant_id, "project_id": project_id},
                )
                assert feature_matrix.status_code == 200
                assert any(item["feature_key"] == "embedding" for item in feature_matrix.json()["items"])

                language_settings = client.put(
                    "/api/v1/config/language-settings",
                    json={
                        "tenant_id": tenant_id,
                        "project_id": project_id,
                        "default_source_language": "zh-CN",
                        "default_target_languages": ["en-US", "ja-JP"],
                        "enabled_languages": [
                            {
                                "language_code": "zh-CN",
                                "label": "简体中文",
                                "locales": ["zh-CN"],
                                "direction": "ltr",
                                "enabled": True,
                            },
                            {
                                "language_code": "en-US",
                                "label": "English",
                                "locales": ["en-US", "en-GB"],
                                "direction": "ltr",
                                "enabled": True,
                            },
                            {
                                "language_code": "ar-SA",
                                "label": "Arabic",
                                "locales": ["ar-SA"],
                                "direction": "rtl",
                                "enabled": True,
                            },
                        ],
                        "translation_notes": "support en/ja/ar",
                        "glossary": {"wuxia": {"en-US": "martial heroes"}},
                        "schema_version": "1.0",
                    },
                )
                assert language_settings.status_code == 200

                language_get = client.get(
                    "/api/v1/config/language-settings",
                    params={"tenant_id": tenant_id, "project_id": project_id},
                )
                assert language_get.status_code == 200
                assert language_get.json()["default_source_language"] == "zh-CN"
                assert "ja-JP" in language_get.json()["default_target_languages"]

                tg_upsert = client.put(
                    "/api/v1/config/telegram-settings",
                    json={
                        "tenant_id": tenant_id,
                        "project_id": project_id,
                        "enabled": True,
                        "bot_token": "1234:token-for-test",
                        "chat_id": "-1001001",
                        "thread_id": "18",
                        "parse_mode": "Markdown",
                        "notify_events": ["run.failed", "job.failed"],
                        "schema_version": "1.0",
                    },
                )
                assert tg_upsert.status_code == 200
                tg_get = client.get(
                    "/api/v1/config/telegram-settings",
                    params={"tenant_id": tenant_id, "project_id": project_id},
                )
                assert tg_get.status_code == 200
                assert tg_get.json()["enabled"] is True
                assert tg_get.json()["chat_id"] == "-1001001"

                health = client.get(
                    "/api/v1/config/health",
                    params={"tenant_id": tenant_id, "project_id": project_id},
                )
                assert health.status_code == 200
                assert health.json()["provider_count"] >= 1

                collection = client.post(
                    "/api/v1/rag/collections",
                    json={
                        "tenant_id": tenant_id,
                        "project_id": project_id,
                        "name": f"kb_{suffix}",
                        "language_code": "zh",
                    },
                )
                assert collection.status_code == 201
                collection_id = collection.json()["id"]
                collection_list = client.get(
                    "/api/v1/rag/collections",
                    params={
                        "tenant_id": tenant_id,
                        "project_id": project_id,
                        "keyword": f"kb_{suffix}",
                    },
                )
                assert collection_list.status_code == 200
                assert any(item["id"] == collection_id for item in collection_list.json())

                kb_version = client.post(
                    f"/api/v1/rag/collections/{collection_id}/kb-versions",
                    json={
                        "tenant_id": tenant_id,
                        "project_id": project_id,
                        "version_name": "v1",
                        "status": "released",
                    },
                )
                assert kb_version.status_code == 201
                kb_version_id = kb_version.json()["id"]
                kb_list = client.get(
                    f"/api/v1/rag/collections/{collection_id}/kb-versions",
                    params={"status": "released"},
                )
                assert kb_list.status_code == 200
                assert any(item["id"] == kb_version_id for item in kb_list.json())

                persona_pack = client.post(
                    "/api/v1/rag/persona-packs",
                    json={
                        "tenant_id": tenant_id,
                        "project_id": project_id,
                        "name": f"director_A_{suffix}",
                    },
                )
                assert persona_pack.status_code == 201
                persona_pack_id = persona_pack.json()["id"]
                persona_list = client.get(
                    "/api/v1/rag/persona-packs",
                    params={
                        "tenant_id": tenant_id,
                        "project_id": project_id,
                        "keyword": f"director_A_{suffix}",
                    },
                )
                assert persona_list.status_code == 200
                assert any(item["id"] == persona_pack_id for item in persona_list.json())

                persona_ver = client.post(
                    f"/api/v1/rag/persona-packs/{persona_pack_id}/versions",
                    json={
                        "tenant_id": tenant_id,
                        "project_id": project_id,
                        "version_name": "v1",
                        "style_json": {"tone": "cinematic"},
                    },
                )
                assert persona_ver.status_code == 201
                persona_ver_id = persona_ver.json()["id"]

                binding = client.post(
                    f"/api/v1/rag/persona-versions/{persona_ver_id}/bindings",
                    json={
                        "tenant_id": tenant_id,
                        "project_id": project_id,
                        "dataset_collection_ids": [collection_id],
                        "kb_version_ids": [kb_version_id],
                    },
                )
                assert binding.status_code == 200

                # Seed a scoped RAG doc and run preview query.
                db2 = SessionLocal()
                try:
                    db2.execute(
                        delete(RagDocument).where(
                            RagDocument.tenant_id == tenant_id,
                            RagDocument.project_id == project_id,
                            RagDocument.source_id == chapter_id,
                        )
                    )
                    db2.add(
                        RagDocument(
                            id=f"rag_doc_bound_{suffix}",
                            tenant_id=tenant_id,
                            project_id=project_id,
                            trace_id=f"tr_{suffix}",
                            correlation_id=f"cr_{suffix}",
                            idempotency_key=f"idem_rag_doc_bound_{suffix}",
                            collection_id=collection_id,
                            kb_version_id=kb_version_id,
                            novel_id=novel_id,
                            scope="chapter",
                            source_type="note",
                            source_id=chapter_id,
                            language_code="zh",
                            title="bound",
                            content_text="wuxia sword duel in tavern",
                            metadata_json={},
                        )
                    )
                    db2.commit()
                finally:
                    db2.close()

                preview = client.post(
                    "/api/v1/rag/persona-preview",
                    json={
                        "tenant_id": tenant_id,
                        "project_id": project_id,
                        "persona_pack_version_id": persona_ver_id,
                        "query": "sword tavern",
                        "top_k": 3,
                    },
                )
                assert preview.status_code == 200
                assert len(preview.json()["chunks"]) >= 1

                culture = client.post(
                    "/api/v1/culture-packs",
                    json={
                        "tenant_id": tenant_id,
                        "project_id": project_id,
                        "culture_pack_id": "cn_wuxia",
                        "display_name": "中式武侠",
                        "constraints": {"visual_do": ["ink"], "visual_dont": ["neon"]},
                    },
                )
                assert culture.status_code == 201
                culture_list = client.get(
                    "/api/v1/culture-packs",
                    params={
                        "tenant_id": tenant_id,
                        "project_id": project_id,
                        "keyword": "wuxia",
                    },
                )
                assert culture_list.status_code == 200
                assert any(item["culture_pack_id"] == "cn_wuxia" for item in culture_list.json())

                export = client.get(
                    "/api/v1/culture-packs/cn_wuxia/export",
                    params={"tenant_id": tenant_id, "project_id": project_id},
                )
                assert export.status_code == 200
                assert export.json()["export_for_skill_02"]["culture_candidates"] == ["cn_wuxia"]

                assets = client.get(
                    f"/api/v1/projects/{project_id}/assets",
                    params={"tenant_id": tenant_id},
                )
                assert assets.status_code == 200
                assert len(assets.json()) >= 1
                assets_filtered = client.get(
                    f"/api/v1/projects/{project_id}/assets",
                    params={"tenant_id": tenant_id, "keyword": artifact_id},
                )
                assert assets_filtered.status_code == 200
                assert any(item["id"] == artifact_id for item in assets_filtered.json())

                anchor = client.post(
                    f"/api/v1/assets/{artifact_id}/anchor",
                    json={
                        "tenant_id": tenant_id,
                        "project_id": project_id,
                        "anchor_name": "hero-reference",
                        "notes": "keep costume",
                    },
                )
                assert anchor.status_code == 200
                assert anchor.json()["anchored"] is True

                anchor_list = client.get(
                    f"/api/v1/projects/{project_id}/anchors",
                    params={"tenant_id": tenant_id},
                )
                assert anchor_list.status_code == 200
                assert len(anchor_list.json()) >= 1
                anchored_assets = client.get(
                    f"/api/v1/projects/{project_id}/assets",
                    params={"tenant_id": tenant_id, "anchored": True},
                )
                assert anchored_assets.status_code == 200
                assert any(item["id"] == artifact_id for item in anchored_assets.json())

                binding_consistency = client.get(
                    f"/api/v1/projects/{project_id}/asset-bindings",
                    params={"tenant_id": tenant_id, "run_id": run_id, "entity_type": "person"},
                )
                assert binding_consistency.status_code == 200
                assert any(item["entity_id"] == entity_id for item in binding_consistency.json())

                timeline = client.get(f"/api/v1/runs/{run_id}/timeline")
                assert timeline.status_code == 200
                assert timeline.json()["total_duration_ms"] >= 2500

                patch = client.post(
                    f"/api/v1/runs/{run_id}/timeline/patch",
                    json={
                        "tenant_id": tenant_id,
                        "project_id": project_id,
                        "shot_id": shot_id,
                        "patch_text": "improve lighting and camera move",
                        "track": "prompt",
                    },
                )
                assert patch.status_code == 200
                assert patch.json()["status"] == "queued"

                delete_persona = client.delete(
                    f"/api/v1/rag/persona-packs/{persona_pack_id}",
                    params={"tenant_id": tenant_id, "project_id": project_id},
                )
                assert delete_persona.status_code == 200

                delete_collection = client.delete(
                    f"/api/v1/rag/collections/{collection_id}",
                    params={"tenant_id": tenant_id, "project_id": project_id},
                )
                assert delete_collection.status_code == 200

                delete_culture = client.delete(
                    "/api/v1/culture-packs/cn_wuxia",
                    params={"tenant_id": tenant_id, "project_id": project_id},
                )
                assert delete_culture.status_code == 200

                delete_asset_resp = client.delete(
                    f"/api/v1/assets/{artifact_id}",
                    params={"tenant_id": tenant_id, "project_id": project_id},
                )
                assert delete_asset_resp.status_code == 200

                delete_profile = client.delete(
                    f"/api/v1/config/profiles/{profile_id}",
                    params={"tenant_id": tenant_id, "project_id": project_id},
                )
                assert delete_profile.status_code == 200

                delete_provider_resp = client.delete(
                    f"/api/v1/config/providers/{provider_id}",
                    params={"tenant_id": tenant_id, "project_id": project_id},
                )
                assert delete_provider_resp.status_code == 200
        finally:
            app.dependency_overrides.clear()
    finally:
        db.close()
        _cleanup_scope(tenant_id, project_id)


def _cleanup_scope(tenant_id: str, project_id: str) -> None:
    db = SessionLocal()
    try:
        models = [
            WorkflowEvent,
            Job,
            RunPatchRecord,
            RunCheckpoint,
            TimelineSegment,
            Artifact,
            ShotDslCompilation,
            RenderRun,
            EntityInstanceLink,
            Entity,
            Shot,
            Chapter,
            Novel,
            EntityContinuityProfile,
            PersonaIndexBinding,
            PersonaDatasetBinding,
            PersonaPackVersion,
            PersonaPack,
            KbVersion,
            RagDocument,
            RagCollection,
            ModelProfile,
            ModelProvider,
            CreativePolicyStack,
            ProjectMember,
            Project,
            User,
        ]
        for model in models:
            db.execute(
                delete(model).where(
                    model.tenant_id == tenant_id,
                    model.project_id == project_id,
                )
            )
        db.commit()
    finally:
        db.close()
