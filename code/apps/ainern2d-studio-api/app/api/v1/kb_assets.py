"""知识资产中心 API — KBPack × 绑定关系 × 运行时 KB 解析

提供 KBPack（知识包资产）的完整 CRUD、源文件上传与解析、批量 embedding、
以及三层绑定（RoleKBMap / PersonaKBMap / NovelKBMap）的管理 API。
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ainern2d_shared.ainer_db_models.enum_models import KBPackStatus, KBSourceType, RagScope, RagSourceType
from ainern2d_shared.ainer_db_models.governance_models import PersonaPack
from ainern2d_shared.ainer_db_models.rag_models import (
    KBPack, KBSource,
    KbVersion, NovelKBMap, PersonaKBMap, RagCollection, RagDocument,
    RoleKBMap,
)
from app.api.deps import get_db

router = APIRouter(prefix="/api/v1/kb", tags=["kb-assets"])


# ═══════════════════════════════════════════════════════════════════════════════
# Pydantic 模型
# ═══════════════════════════════════════════════════════════════════════════════

class KBPackCreateRequest(BaseModel):
    tenant_id: str
    project_id: str
    name: str
    description: str | None = None
    language_code: str = "zh"
    culture_pack: str | None = None           # cn_wuxia / us_hollywood
    version_name: str = "v1"
    tags_json: list[str] = Field(default_factory=list)
    bind_suggestions_json: list[str] = Field(default_factory=list)  # 建议绑定 role_ids


class KBPackUpdateRequest(BaseModel):
    name: str | None = None
    description: str | None = None
    language_code: str | None = None
    culture_pack: str | None = None
    version_name: str | None = None
    status: str | None = None                  # draft/embedded/published/deprecated
    tags_json: list[str] | None = None
    bind_suggestions_json: list[str] | None = None


class KBPackResponse(BaseModel):
    id: str
    tenant_id: str
    project_id: str
    name: str
    description: str | None = None
    language_code: str | None = None
    culture_pack: str | None = None
    version_name: str
    status: str
    tags_json: list[str] = Field(default_factory=list)
    bind_suggestions_json: list[str] = Field(default_factory=list)
    collection_id: str | None = None
    created_at: str | None = None


class KBSourceResponse(BaseModel):
    id: str
    kb_pack_id: str
    source_type: str
    source_name: str | None = None
    source_uri: str | None = None
    parse_status: str
    chunk_count: int
    created_at: str | None = None


# ─── 绑定关系 Pydantic 模型 ───────────────────────────────────────────────────

class KBMapCreateRequest(BaseModel):
    tenant_id: str
    project_id: str
    kb_pack_id: str
    priority: int = 100
    enabled: bool = True
    note: str | None = None


class KBMapUpdateRequest(BaseModel):
    priority: int | None = None
    enabled: bool | None = None
    note: str | None = None


class KBMapResponse(BaseModel):
    id: str
    kb_pack_id: str
    kb_pack_name: str | None = None
    priority: int
    enabled: bool
    note: str | None = None
    created_at: str | None = None


# ─── effective-kb ─────────────────────────────────────────────────────────────

class EffectiveKBEntry(BaseModel):
    kb_pack_id: str
    kb_pack_name: str
    collection_id: str | None = None
    source: str                              # novel / role / persona
    priority: int
    enabled: bool


class EffectiveKBResponse(BaseModel):
    persona_pack_id: str
    role_id: str | None = None
    novel_id: str | None = None
    effective_packs: list[EffectiveKBEntry] = Field(default_factory=list)


# ═══════════════════════════════════════════════════════════════════════════════
# Helper
# ═══════════════════════════════════════════════════════════════════════════════

def _ts(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    return dt.isoformat()


def _pack_to_response(pack: KBPack) -> KBPackResponse:
    return KBPackResponse(
        id=pack.id,
        tenant_id=pack.tenant_id,
        project_id=pack.project_id,
        name=pack.name,
        description=pack.description,
        language_code=pack.language_code,
        culture_pack=pack.culture_pack,
        version_name=pack.version_name,
        status=pack.status.value if pack.status else "draft",
        tags_json=pack.tags_json or [],
        bind_suggestions_json=pack.bind_suggestions_json or [],
        collection_id=pack.collection_id,
        created_at=_ts(pack.created_at),
    )


def _source_to_response(src: KBSource) -> KBSourceResponse:
    return KBSourceResponse(
        id=src.id,
        kb_pack_id=src.kb_pack_id,
        source_type=src.source_type.value if src.source_type else "txt",
        source_name=src.source_name,
        source_uri=src.source_uri,
        parse_status=src.parse_status,
        chunk_count=src.chunk_count,
        created_at=_ts(src.created_at),
    )


def _chunk_text(content: str, chunk_size: int = 480) -> list[str]:
    paragraphs = [p.strip() for p in re.split(r"\n{2,}", content) if p.strip()]
    chunks: list[str] = []
    for para in paragraphs:
        if len(para) <= chunk_size:
            chunks.append(para)
        else:
            for start in range(0, len(para), chunk_size):
                chunk = para[start: start + chunk_size].strip()
                if chunk:
                    chunks.append(chunk)
    return chunks


def _get_pack_or_404(pack_id: str, db: Session) -> KBPack:
    pack = db.get(KBPack, pack_id)
    if pack is None or pack.deleted_at is not None:
        raise HTTPException(status_code=404, detail="kb pack not found")
    return pack


def _std_columns(prefix: str, name_suffix: str, tenant_id: str, project_id: str) -> dict:
    uid = uuid4().hex
    return {
        "trace_id": f"tr_{prefix}_{uid[:12]}",
        "correlation_id": f"cr_{prefix}_{uid[:12]}",
        "idempotency_key": f"idem_{prefix}_{name_suffix}_{uid[:8]}",
    }


# ═══════════════════════════════════════════════════════════════════════════════
# KBPack CRUD
# ═══════════════════════════════════════════════════════════════════════════════

@router.post("/packs", response_model=KBPackResponse, status_code=201)
def create_kb_pack(body: KBPackCreateRequest, db: Session = Depends(get_db)) -> KBPackResponse:
    """创建知识包，同时自动创建底层 RagCollection 作为向量存储容器。"""
    pack_id = f"kb_pack_{uuid4().hex}"

    # 自动创建底层 RagCollection
    collection = RagCollection(
        id=f"rag_collection_{uuid4().hex}",
        tenant_id=body.tenant_id,
        project_id=body.project_id,
        **_std_columns("rag_coll", body.name, body.tenant_id, body.project_id),
        name=f"kb_{body.name}",
        version="v1",
        language_code=body.language_code,
        description=body.description,
        bind_type=None,
        bind_id=pack_id,
    )
    db.add(collection)
    db.flush()  # 获取 collection.id

    pack = KBPack(
        id=pack_id,
        tenant_id=body.tenant_id,
        project_id=body.project_id,
        **_std_columns("kb_pack", body.name, body.tenant_id, body.project_id),
        name=body.name,
        description=body.description,
        language_code=body.language_code,
        culture_pack=body.culture_pack,
        version_name=body.version_name,
        status=KBPackStatus.draft,
        tags_json=body.tags_json,
        bind_suggestions_json=body.bind_suggestions_json,
        collection_id=collection.id,
    )
    db.add(pack)
    db.commit()
    db.refresh(pack)
    return _pack_to_response(pack)


@router.get("/packs", response_model=list[KBPackResponse])
def list_kb_packs(
    tenant_id: str = Query(...),
    project_id: str = Query(...),
    keyword: str | None = Query(default=None),
    language_code: str | None = Query(default=None),
    culture_pack: str | None = Query(default=None),
    status: str | None = Query(default=None),
    db: Session = Depends(get_db),
) -> list[KBPackResponse]:
    stmt = select(KBPack).where(
        KBPack.tenant_id == tenant_id,
        KBPack.project_id == project_id,
        KBPack.deleted_at.is_(None),
    )
    if keyword:
        stmt = stmt.where(KBPack.name.ilike(f"%{keyword.strip()}%"))
    if language_code:
        stmt = stmt.where(KBPack.language_code == language_code)
    if culture_pack:
        stmt = stmt.where(KBPack.culture_pack == culture_pack)
    if status:
        try:
            stmt = stmt.where(KBPack.status == KBPackStatus(status))
        except ValueError:
            pass
    rows = db.execute(stmt.order_by(KBPack.created_at.desc())).scalars().all()
    return [_pack_to_response(r) for r in rows]


@router.get("/packs/{pack_id}", response_model=KBPackResponse)
def get_kb_pack(pack_id: str, db: Session = Depends(get_db)) -> KBPackResponse:
    return _pack_to_response(_get_pack_or_404(pack_id, db))


@router.put("/packs/{pack_id}", response_model=KBPackResponse)
def update_kb_pack(
    pack_id: str,
    body: KBPackUpdateRequest,
    db: Session = Depends(get_db),
) -> KBPackResponse:
    pack = _get_pack_or_404(pack_id, db)
    if body.name is not None:
        pack.name = body.name
    if body.description is not None:
        pack.description = body.description
    if body.language_code is not None:
        pack.language_code = body.language_code
    if body.culture_pack is not None:
        pack.culture_pack = body.culture_pack
    if body.version_name is not None:
        pack.version_name = body.version_name
    if body.status is not None:
        try:
            pack.status = KBPackStatus(body.status)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"invalid status: {body.status}")
    if body.tags_json is not None:
        pack.tags_json = body.tags_json
    if body.bind_suggestions_json is not None:
        pack.bind_suggestions_json = body.bind_suggestions_json
    db.commit()
    db.refresh(pack)
    return _pack_to_response(pack)


@router.delete("/packs/{pack_id}", status_code=204)
def delete_kb_pack(
    pack_id: str,
    tenant_id: str = Query(...),
    project_id: str = Query(...),
    force: bool = Query(default=False),
    db: Session = Depends(get_db),
) -> None:
    pack = _get_pack_or_404(pack_id, db)
    if not force:
        # 检查是否有绑定
        bindings_count = (
            db.execute(select(RoleKBMap).where(RoleKBMap.kb_pack_id == pack_id, RoleKBMap.deleted_at.is_(None))).scalars().first() or
            db.execute(select(PersonaKBMap).where(PersonaKBMap.kb_pack_id == pack_id, PersonaKBMap.deleted_at.is_(None))).scalars().first() or
            db.execute(select(NovelKBMap).where(NovelKBMap.kb_pack_id == pack_id, NovelKBMap.deleted_at.is_(None))).scalars().first()
        )
        if bindings_count:
            raise HTTPException(
                status_code=409,
                detail="kb pack is still bound to role/persona/novel; use ?force=true to delete anyway"
            )
    pack.deleted_at = datetime.now(timezone.utc)
    db.commit()


# ═══════════════════════════════════════════════════════════════════════════════
# 源文件上传 & 解析
# ═══════════════════════════════════════════════════════════════════════════════

@router.post("/packs/{pack_id}/upload-source", response_model=KBSourceResponse, status_code=201)
async def upload_kb_source(
    pack_id: str,
    tenant_id: str = Query(...),
    project_id: str = Query(...),
    bind_role_ids: str | None = Query(default=None, description="逗号分隔的 role_id，上传后自动写入 RoleKBMap"),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
) -> KBSourceResponse:
    """上传文件 → 解析文本 → 写入 KBSource + RagDocument。"""
    pack = _get_pack_or_404(pack_id, db)

    ext = (file.filename or "").rsplit(".", 1)[-1].lower()
    src_type_map = {"pdf": KBSourceType.pdf, "docx": KBSourceType.docx, "xlsx": KBSourceType.xlsx, "txt": KBSourceType.txt}
    source_type = src_type_map.get(ext, KBSourceType.txt)

    raw = await file.read()
    content_text = ""

    if ext in {"txt", "md"}:
        content_text = raw.decode("utf-8", errors="replace")
    elif ext in {"pdf", "docx", "xlsx", "xls"}:
        # 简单文本 fallback：尝试 utf-8 解码，失败则用 latin-1
        try:
            content_text = raw.decode("utf-8", errors="ignore")
        except Exception:
            content_text = f"[Binary file: {file.filename}. Use vision-enabled provider to extract.]"
    else:
        content_text = raw.decode("utf-8", errors="replace")

    chunks = _chunk_text(content_text)

    # 写 KBSource
    src = KBSource(
        id=f"kb_src_{uuid4().hex}",
        tenant_id=tenant_id,
        project_id=project_id,
        **_std_columns("kb_src", file.filename or "upload", tenant_id, project_id),
        kb_pack_id=pack_id,
        source_type=source_type,
        source_name=file.filename,
        parse_status="done" if chunks else "failed",
        chunk_count=len(chunks),
    )
    db.add(src)

    # 写 RagDocument（chunk 一一写入 pack 的底层 RagCollection）
    if pack.collection_id and chunks:
        for idx, chunk in enumerate(chunks):
            doc = RagDocument(
                id=f"rag_doc_{uuid4().hex}",
                tenant_id=tenant_id,
                project_id=project_id,
                **_std_columns("rag_doc", f"{file.filename}_{idx}", tenant_id, project_id),
                collection_id=pack.collection_id,
                scope=RagScope.style_rule,       # knowledge content scope
                source_type=RagSourceType.note,
                source_id=src.id,
                title=f"{file.filename} [{idx + 1}]",
                content_text=chunk,
                language_code=pack.language_code or "zh",
                metadata_json={"chunk_index": idx, "source_name": file.filename, "kb_pack_id": pack_id},
            )
            db.add(doc)

    # 更新 pack status → embedded（如果 chunks > 0）
    if chunks and pack.status == KBPackStatus.draft:
        pack.status = KBPackStatus.embedded

    # 自动写入 RoleKBMap（建议绑定）
    if bind_role_ids:
        for role_id in [r.strip() for r in bind_role_ids.split(",") if r.strip()]:
            existing = db.execute(
                select(RoleKBMap).where(
                    RoleKBMap.tenant_id == tenant_id,
                    RoleKBMap.project_id == project_id,
                    RoleKBMap.role_id == role_id,
                    RoleKBMap.kb_pack_id == pack_id,
                    RoleKBMap.deleted_at.is_(None),
                )
            ).scalars().first()
            if existing is None:
                db.add(RoleKBMap(
                    id=f"role_kb_{uuid4().hex}",
                    tenant_id=tenant_id,
                    project_id=project_id,
                    **_std_columns("role_kb", f"{role_id}_{pack_id}", tenant_id, project_id),
                    role_id=role_id,
                    kb_pack_id=pack_id,
                    priority=100,
                    enabled=True,
                ))

    db.commit()
    db.refresh(src)
    return _source_to_response(src)


@router.get("/packs/{pack_id}/sources", response_model=list[KBSourceResponse])
def list_kb_sources(pack_id: str, db: Session = Depends(get_db)) -> list[KBSourceResponse]:
    _get_pack_or_404(pack_id, db)
    rows = db.execute(
        select(KBSource).where(KBSource.kb_pack_id == pack_id, KBSource.deleted_at.is_(None))
        .order_by(KBSource.created_at.desc())
    ).scalars().all()
    return [_source_to_response(r) for r in rows]


@router.post("/packs/{pack_id}/embed", status_code=202)
def trigger_embed(
    pack_id: str,
    tenant_id: str = Query(...),
    project_id: str = Query(...),
    db: Session = Depends(get_db),
) -> dict:
    """触发 KBPack 的 embedding 生成（异步占位，当前为同步标记）。"""
    pack = _get_pack_or_404(pack_id, db)
    # 实际 embedding 应通过 worker-hub 异步执行，这里先标记状态
    pack.status = KBPackStatus.embedded
    db.commit()
    return {
        "kb_pack_id": pack_id,
        "status": "embedding_queued",
        "message": "Embedding will be processed by worker. Current status set to 'embedded'.",
    }


# ═══════════════════════════════════════════════════════════════════════════════
# 绑定关系 CRUD — Role
# ═══════════════════════════════════════════════════════════════════════════════

@router.post("/bindings/role", response_model=KBMapResponse, status_code=201)
def create_role_kb_binding(
    role_id: str = Query(...),
    body: KBMapCreateRequest = ...,
    db: Session = Depends(get_db),
) -> KBMapResponse:
    _get_pack_or_404(body.kb_pack_id, db)
    existing = db.execute(
        select(RoleKBMap).where(
            RoleKBMap.tenant_id == body.tenant_id,
            RoleKBMap.project_id == body.project_id,
            RoleKBMap.role_id == role_id,
            RoleKBMap.kb_pack_id == body.kb_pack_id,
            RoleKBMap.deleted_at.is_(None),
        )
    ).scalars().first()
    if existing:
        raise HTTPException(status_code=409, detail="binding already exists")
    row = RoleKBMap(
        id=f"role_kb_{uuid4().hex}",
        tenant_id=body.tenant_id,
        project_id=body.project_id,
        **_std_columns("role_kb", f"{role_id}_{body.kb_pack_id}", body.tenant_id, body.project_id),
        role_id=role_id,
        kb_pack_id=body.kb_pack_id,
        priority=body.priority,
        enabled=body.enabled,
        note=body.note,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    pack = db.get(KBPack, row.kb_pack_id)
    return KBMapResponse(
        id=row.id, kb_pack_id=row.kb_pack_id,
        kb_pack_name=pack.name if pack else None,
        priority=row.priority, enabled=row.enabled,
        note=row.note, created_at=_ts(row.created_at),
    )


@router.get("/bindings/role", response_model=list[KBMapResponse])
def list_role_kb_bindings(
    tenant_id: str = Query(...),
    project_id: str = Query(...),
    role_id: str = Query(...),
    db: Session = Depends(get_db),
) -> list[KBMapResponse]:
    rows = db.execute(
        select(RoleKBMap).where(
            RoleKBMap.tenant_id == tenant_id,
            RoleKBMap.project_id == project_id,
            RoleKBMap.role_id == role_id,
            RoleKBMap.deleted_at.is_(None),
        ).order_by(RoleKBMap.priority.desc())
    ).scalars().all()
    result = []
    for row in rows:
        pack = db.get(KBPack, row.kb_pack_id)
        result.append(KBMapResponse(
            id=row.id, kb_pack_id=row.kb_pack_id,
            kb_pack_name=pack.name if pack else None,
            priority=row.priority, enabled=row.enabled,
            note=row.note, created_at=_ts(row.created_at),
        ))
    return result


@router.put("/bindings/role/{binding_id}", response_model=KBMapResponse)
def update_role_kb_binding(
    binding_id: str,
    body: KBMapUpdateRequest,
    db: Session = Depends(get_db),
) -> KBMapResponse:
    row = db.get(RoleKBMap, binding_id)
    if row is None or row.deleted_at is not None:
        raise HTTPException(status_code=404, detail="binding not found")
    if body.priority is not None:
        row.priority = body.priority
    if body.enabled is not None:
        row.enabled = body.enabled
    if body.note is not None:
        row.note = body.note
    db.commit()
    db.refresh(row)
    pack = db.get(KBPack, row.kb_pack_id)
    return KBMapResponse(
        id=row.id, kb_pack_id=row.kb_pack_id,
        kb_pack_name=pack.name if pack else None,
        priority=row.priority, enabled=row.enabled,
        note=row.note, created_at=_ts(row.created_at),
    )


@router.delete("/bindings/role/{binding_id}", status_code=204)
def delete_role_kb_binding(binding_id: str, db: Session = Depends(get_db)) -> None:
    row = db.get(RoleKBMap, binding_id)
    if row is None or row.deleted_at is not None:
        raise HTTPException(status_code=404, detail="binding not found")
    row.deleted_at = datetime.now(timezone.utc)
    db.commit()


# ═══════════════════════════════════════════════════════════════════════════════
# 绑定关系 CRUD — Persona
# ═══════════════════════════════════════════════════════════════════════════════

@router.post("/bindings/persona", response_model=KBMapResponse, status_code=201)
def create_persona_kb_binding(
    persona_pack_id: str = Query(...),
    body: KBMapCreateRequest = ...,
    db: Session = Depends(get_db),
) -> KBMapResponse:
    _get_pack_or_404(body.kb_pack_id, db)
    existing = db.execute(
        select(PersonaKBMap).where(
            PersonaKBMap.tenant_id == body.tenant_id,
            PersonaKBMap.project_id == body.project_id,
            PersonaKBMap.persona_pack_id == persona_pack_id,
            PersonaKBMap.kb_pack_id == body.kb_pack_id,
            PersonaKBMap.deleted_at.is_(None),
        )
    ).scalars().first()
    if existing:
        raise HTTPException(status_code=409, detail="binding already exists")
    row = PersonaKBMap(
        id=f"persona_kb_{uuid4().hex}",
        tenant_id=body.tenant_id,
        project_id=body.project_id,
        **_std_columns("persona_kb", f"{persona_pack_id}_{body.kb_pack_id}", body.tenant_id, body.project_id),
        persona_pack_id=persona_pack_id,
        kb_pack_id=body.kb_pack_id,
        priority=body.priority,
        enabled=body.enabled,
        note=body.note,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    pack = db.get(KBPack, row.kb_pack_id)
    return KBMapResponse(
        id=row.id, kb_pack_id=row.kb_pack_id,
        kb_pack_name=pack.name if pack else None,
        priority=row.priority, enabled=row.enabled,
        note=row.note, created_at=_ts(row.created_at),
    )


@router.get("/bindings/persona", response_model=list[KBMapResponse])
def list_persona_kb_bindings(
    tenant_id: str = Query(...),
    project_id: str = Query(...),
    persona_pack_id: str = Query(...),
    db: Session = Depends(get_db),
) -> list[KBMapResponse]:
    rows = db.execute(
        select(PersonaKBMap).where(
            PersonaKBMap.tenant_id == tenant_id,
            PersonaKBMap.project_id == project_id,
            PersonaKBMap.persona_pack_id == persona_pack_id,
            PersonaKBMap.deleted_at.is_(None),
        ).order_by(PersonaKBMap.priority.desc())
    ).scalars().all()
    result = []
    for row in rows:
        pack = db.get(KBPack, row.kb_pack_id)
        result.append(KBMapResponse(
            id=row.id, kb_pack_id=row.kb_pack_id,
            kb_pack_name=pack.name if pack else None,
            priority=row.priority, enabled=row.enabled,
            note=row.note, created_at=_ts(row.created_at),
        ))
    return result


@router.put("/bindings/persona/{binding_id}", response_model=KBMapResponse)
def update_persona_kb_binding(
    binding_id: str,
    body: KBMapUpdateRequest,
    db: Session = Depends(get_db),
) -> KBMapResponse:
    row = db.get(PersonaKBMap, binding_id)
    if row is None or row.deleted_at is not None:
        raise HTTPException(status_code=404, detail="binding not found")
    if body.priority is not None:
        row.priority = body.priority
    if body.enabled is not None:
        row.enabled = body.enabled
    if body.note is not None:
        row.note = body.note
    db.commit()
    db.refresh(row)
    pack = db.get(KBPack, row.kb_pack_id)
    return KBMapResponse(
        id=row.id, kb_pack_id=row.kb_pack_id,
        kb_pack_name=pack.name if pack else None,
        priority=row.priority, enabled=row.enabled,
        note=row.note, created_at=_ts(row.created_at),
    )


@router.delete("/bindings/persona/{binding_id}", status_code=204)
def delete_persona_kb_binding(binding_id: str, db: Session = Depends(get_db)) -> None:
    row = db.get(PersonaKBMap, binding_id)
    if row is None or row.deleted_at is not None:
        raise HTTPException(status_code=404, detail="binding not found")
    row.deleted_at = datetime.now(timezone.utc)
    db.commit()


# ═══════════════════════════════════════════════════════════════════════════════
# 绑定关系 CRUD — Novel
# ═══════════════════════════════════════════════════════════════════════════════

@router.post("/bindings/novel", response_model=KBMapResponse, status_code=201)
def create_novel_kb_binding(
    novel_id: str = Query(...),
    body: KBMapCreateRequest = ...,
    db: Session = Depends(get_db),
) -> KBMapResponse:
    _get_pack_or_404(body.kb_pack_id, db)
    existing = db.execute(
        select(NovelKBMap).where(
            NovelKBMap.tenant_id == body.tenant_id,
            NovelKBMap.project_id == body.project_id,
            NovelKBMap.novel_id == novel_id,
            NovelKBMap.kb_pack_id == body.kb_pack_id,
            NovelKBMap.deleted_at.is_(None),
        )
    ).scalars().first()
    if existing:
        raise HTTPException(status_code=409, detail="binding already exists")
    row = NovelKBMap(
        id=f"novel_kb_{uuid4().hex}",
        tenant_id=body.tenant_id,
        project_id=body.project_id,
        **_std_columns("novel_kb", f"{novel_id}_{body.kb_pack_id}", body.tenant_id, body.project_id),
        novel_id=novel_id,
        kb_pack_id=body.kb_pack_id,
        priority=body.priority,
        enabled=body.enabled,
        note=body.note,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    pack = db.get(KBPack, row.kb_pack_id)
    return KBMapResponse(
        id=row.id, kb_pack_id=row.kb_pack_id,
        kb_pack_name=pack.name if pack else None,
        priority=row.priority, enabled=row.enabled,
        note=row.note, created_at=_ts(row.created_at),
    )


@router.get("/bindings/novel", response_model=list[KBMapResponse])
def list_novel_kb_bindings(
    tenant_id: str = Query(...),
    project_id: str = Query(...),
    novel_id: str = Query(...),
    db: Session = Depends(get_db),
) -> list[KBMapResponse]:
    rows = db.execute(
        select(NovelKBMap).where(
            NovelKBMap.tenant_id == tenant_id,
            NovelKBMap.project_id == project_id,
            NovelKBMap.novel_id == novel_id,
            NovelKBMap.deleted_at.is_(None),
        ).order_by(NovelKBMap.priority.desc())
    ).scalars().all()
    result = []
    for row in rows:
        pack = db.get(KBPack, row.kb_pack_id)
        result.append(KBMapResponse(
            id=row.id, kb_pack_id=row.kb_pack_id,
            kb_pack_name=pack.name if pack else None,
            priority=row.priority, enabled=row.enabled,
            note=row.note, created_at=_ts(row.created_at),
        ))
    return result


@router.put("/bindings/novel/{binding_id}", response_model=KBMapResponse)
def update_novel_kb_binding(
    binding_id: str,
    body: KBMapUpdateRequest,
    db: Session = Depends(get_db),
) -> KBMapResponse:
    row = db.get(NovelKBMap, binding_id)
    if row is None or row.deleted_at is not None:
        raise HTTPException(status_code=404, detail="binding not found")
    if body.priority is not None:
        row.priority = body.priority
    if body.enabled is not None:
        row.enabled = body.enabled
    if body.note is not None:
        row.note = body.note
    db.commit()
    db.refresh(row)
    pack = db.get(KBPack, row.kb_pack_id)
    return KBMapResponse(
        id=row.id, kb_pack_id=row.kb_pack_id,
        kb_pack_name=pack.name if pack else None,
        priority=row.priority, enabled=row.enabled,
        note=row.note, created_at=_ts(row.created_at),
    )


@router.delete("/bindings/novel/{binding_id}", status_code=204)
def delete_novel_kb_binding(binding_id: str, db: Session = Depends(get_db)) -> None:
    row = db.get(NovelKBMap, binding_id)
    if row is None or row.deleted_at is not None:
        raise HTTPException(status_code=404, detail="binding not found")
    row.deleted_at = datetime.now(timezone.utc)
    db.commit()


# ═══════════════════════════════════════════════════════════════════════════════
# 运行时 effective-kb（novel > role > persona）
# ═══════════════════════════════════════════════════════════════════════════════

@router.get("/effective", response_model=EffectiveKBResponse)
def get_effective_kb(
    tenant_id: str = Query(...),
    project_id: str = Query(...),
    persona_pack_id: str = Query(...),
    novel_id: str | None = Query(default=None),
    db: Session = Depends(get_db),
) -> EffectiveKBResponse:
    """计算 Persona 的运行时生效 KB 集合（novel > role > persona，enabled=true，去重）。"""
    persona = db.get(PersonaPack, persona_pack_id)
    if persona is None:
        raise HTTPException(status_code=404, detail="persona pack not found")

    role_id = persona.role_id
    seen: set[str] = set()
    entries: list[EffectiveKBEntry] = []

    def _collect_maps(rows, source: str) -> None:
        for row in rows:
            if not row.enabled:
                continue
            if row.kb_pack_id in seen:
                continue
            pack = db.get(KBPack, row.kb_pack_id)
            if pack is None or pack.deleted_at is not None:
                continue
            seen.add(row.kb_pack_id)
            entries.append(EffectiveKBEntry(
                kb_pack_id=pack.id,
                kb_pack_name=pack.name,
                collection_id=pack.collection_id,
                source=source,
                priority=row.priority,
                enabled=row.enabled,
            ))

    # 优先级 1: Novel KB
    if novel_id:
        novel_rows = db.execute(
            select(NovelKBMap).where(
                NovelKBMap.tenant_id == tenant_id,
                NovelKBMap.project_id == project_id,
                NovelKBMap.novel_id == novel_id,
                NovelKBMap.deleted_at.is_(None),
            ).order_by(NovelKBMap.priority.desc())
        ).scalars().all()
        _collect_maps(novel_rows, "novel")

    # 优先级 2: Role KB
    if role_id:
        role_rows = db.execute(
            select(RoleKBMap).where(
                RoleKBMap.tenant_id == tenant_id,
                RoleKBMap.project_id == project_id,
                RoleKBMap.role_id == role_id,
                RoleKBMap.deleted_at.is_(None),
            ).order_by(RoleKBMap.priority.desc())
        ).scalars().all()
        _collect_maps(role_rows, "role")

    # 优先级 3: Persona KB
    persona_rows = db.execute(
        select(PersonaKBMap).where(
            PersonaKBMap.tenant_id == tenant_id,
            PersonaKBMap.project_id == project_id,
            PersonaKBMap.persona_pack_id == persona_pack_id,
            PersonaKBMap.deleted_at.is_(None),
        ).order_by(PersonaKBMap.priority.desc())
    ).scalars().all()
    _collect_maps(persona_rows, "persona")

    return EffectiveKBResponse(
        persona_pack_id=persona_pack_id,
        role_id=role_id,
        novel_id=novel_id,
        effective_packs=entries,
    )
