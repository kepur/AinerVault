from __future__ import annotations

from datetime import datetime, timezone
import re
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ainern2d_shared.ainer_db_models.governance_models import PersonaPack, PersonaPackVersion
from ainern2d_shared.ainer_db_models.preview_models import PersonaDatasetBinding, PersonaIndexBinding
from ainern2d_shared.ainer_db_models.rag_models import KbVersion, RagCollection, RagDocument

from app.api.deps import get_db

router = APIRouter(prefix="/api/v1/rag", tags=["rag"])


class RagCollectionCreateRequest(BaseModel):
    tenant_id: str
    project_id: str
    name: str
    language_code: str = "zh"
    description: str | None = None
    novel_id: str | None = None
    tags_json: list[str] = Field(default_factory=list)


class RagCollectionResponse(BaseModel):
    id: str
    tenant_id: str
    project_id: str
    name: str
    language_code: str | None = None
    description: str | None = None
    tags_json: list[str] = Field(default_factory=list)


class KbVersionCreateRequest(BaseModel):
    tenant_id: str
    project_id: str
    version_name: str
    status: str = "draft"
    recipe_id: str | None = None
    embedding_model_profile_id: str | None = None
    release_note: str | None = None


class KbVersionResponse(BaseModel):
    id: str
    collection_id: str
    version_name: str
    status: str
    recipe_id: str | None = None
    embedding_model_profile_id: str | None = None
    release_note: str | None = None


class PersonaPackCreateRequest(BaseModel):
    tenant_id: str
    project_id: str
    name: str
    description: str | None = None
    tags_json: list[str] = Field(default_factory=list)


class PersonaPackResponse(BaseModel):
    id: str
    tenant_id: str
    project_id: str
    name: str
    description: str | None = None
    tags_json: list[str] = Field(default_factory=list)


class PersonaVersionCreateRequest(BaseModel):
    tenant_id: str
    project_id: str
    version_name: str
    style_json: dict = Field(default_factory=dict)
    voice_json: dict = Field(default_factory=dict)
    camera_json: dict = Field(default_factory=dict)


class PersonaVersionResponse(BaseModel):
    id: str
    persona_pack_id: str
    version_name: str
    style_json: dict = Field(default_factory=dict)
    voice_json: dict = Field(default_factory=dict)
    camera_json: dict = Field(default_factory=dict)


class PersonaBindingRequest(BaseModel):
    tenant_id: str
    project_id: str
    dataset_collection_ids: list[str] = Field(default_factory=list)
    kb_version_ids: list[str] = Field(default_factory=list)
    binding_role: str = "primary"


class PersonaBindingResponse(BaseModel):
    persona_pack_version_id: str
    dataset_bindings: list[str] = Field(default_factory=list)
    index_bindings: list[str] = Field(default_factory=list)


class PersonaPreviewRequest(BaseModel):
    tenant_id: str
    project_id: str
    persona_pack_version_id: str
    query: str
    top_k: int = Field(default=5, ge=1, le=20)


class PersonaPreviewChunk(BaseModel):
    doc_id: str
    collection_id: str | None = None
    kb_version_id: str | None = None
    title: str | None = None
    source_type: str
    source_id: str | None = None
    score: float
    snippet: str


class PersonaPreviewResponse(BaseModel):
    persona_pack_version_id: str
    query: str
    top_k: int
    chunks: list[PersonaPreviewChunk] = Field(default_factory=list)


@router.post("/collections", response_model=RagCollectionResponse, status_code=201)
def create_collection(body: RagCollectionCreateRequest, db: Session = Depends(get_db)) -> RagCollectionResponse:
    row = RagCollection(
        id=f"rag_collection_{uuid4().hex}",
        tenant_id=body.tenant_id,
        project_id=body.project_id,
        trace_id=f"tr_rag_collection_{uuid4().hex[:12]}",
        correlation_id=f"cr_rag_collection_{uuid4().hex[:12]}",
        idempotency_key=f"idem_rag_collection_{body.name}_{uuid4().hex[:8]}",
        novel_id=body.novel_id,
        name=body.name,
        version="v1",
        language_code=body.language_code,
        description=body.description,
        tags_json=body.tags_json,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return RagCollectionResponse(
        id=row.id,
        tenant_id=row.tenant_id,
        project_id=row.project_id,
        name=row.name,
        language_code=row.language_code,
        description=row.description,
        tags_json=row.tags_json or [],
    )


@router.get("/collections", response_model=list[RagCollectionResponse])
def list_collections(
    tenant_id: str = Query(...),
    project_id: str = Query(...),
    keyword: str | None = Query(default=None),
    language_code: str | None = Query(default=None),
    db: Session = Depends(get_db),
) -> list[RagCollectionResponse]:
    stmt = select(RagCollection).where(
        RagCollection.tenant_id == tenant_id,
        RagCollection.project_id == project_id,
        RagCollection.deleted_at.is_(None),
    )
    if language_code:
        stmt = stmt.where(RagCollection.language_code == language_code)
    if keyword:
        like_value = f"%{keyword.strip()}%"
        stmt = stmt.where(RagCollection.name.ilike(like_value))
    rows = db.execute(stmt.order_by(RagCollection.created_at.desc())).scalars().all()
    return [
        RagCollectionResponse(
            id=row.id,
            tenant_id=row.tenant_id,
            project_id=row.project_id,
            name=row.name,
            language_code=row.language_code,
            description=row.description,
            tags_json=row.tags_json or [],
        )
        for row in rows
    ]


@router.post("/collections/{collection_id}/kb-versions", response_model=KbVersionResponse, status_code=201)
def create_kb_version(
    collection_id: str,
    body: KbVersionCreateRequest,
    db: Session = Depends(get_db),
) -> KbVersionResponse:
    collection = db.get(RagCollection, collection_id)
    if collection is None:
        raise HTTPException(status_code=404, detail="collection not found")

    row = KbVersion(
        id=f"kb_version_{uuid4().hex}",
        tenant_id=body.tenant_id,
        project_id=body.project_id,
        trace_id=f"tr_kb_{uuid4().hex[:12]}",
        correlation_id=f"cr_kb_{uuid4().hex[:12]}",
        idempotency_key=f"idem_kb_{collection_id}_{body.version_name}_{uuid4().hex[:8]}",
        collection_id=collection_id,
        version_name=body.version_name,
        status=body.status,
        recipe_id=body.recipe_id,
        embedding_model_profile_id=body.embedding_model_profile_id,
        release_note=body.release_note,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return KbVersionResponse(
        id=row.id,
        collection_id=row.collection_id,
        version_name=row.version_name,
        status=row.status,
        recipe_id=row.recipe_id,
        embedding_model_profile_id=row.embedding_model_profile_id,
        release_note=row.release_note,
    )


@router.get("/collections/{collection_id}/kb-versions", response_model=list[KbVersionResponse])
def list_kb_versions(
    collection_id: str,
    status: str | None = Query(default=None),
    db: Session = Depends(get_db),
) -> list[KbVersionResponse]:
    stmt = select(KbVersion).where(
        KbVersion.collection_id == collection_id,
        KbVersion.deleted_at.is_(None),
    )
    if status:
        stmt = stmt.where(KbVersion.status == status)
    rows = db.execute(stmt.order_by(KbVersion.created_at.desc())).scalars().all()
    return [
        KbVersionResponse(
            id=row.id,
            collection_id=row.collection_id,
            version_name=row.version_name,
            status=row.status,
            recipe_id=row.recipe_id,
            embedding_model_profile_id=row.embedding_model_profile_id,
            release_note=row.release_note,
        )
        for row in rows
    ]


@router.post("/persona-packs", response_model=PersonaPackResponse, status_code=201)
def create_persona_pack(body: PersonaPackCreateRequest, db: Session = Depends(get_db)) -> PersonaPackResponse:
    row = PersonaPack(
        id=f"persona_pack_{uuid4().hex}",
        tenant_id=body.tenant_id,
        project_id=body.project_id,
        trace_id=f"tr_persona_pack_{uuid4().hex[:12]}",
        correlation_id=f"cr_persona_pack_{uuid4().hex[:12]}",
        idempotency_key=f"idem_persona_pack_{body.name}_{uuid4().hex[:8]}",
        name=body.name,
        description=body.description,
        tags_json=body.tags_json,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return PersonaPackResponse(
        id=row.id,
        tenant_id=row.tenant_id,
        project_id=row.project_id,
        name=row.name,
        description=row.description,
        tags_json=row.tags_json or [],
    )


@router.get("/persona-packs", response_model=list[PersonaPackResponse])
def list_persona_packs(
    tenant_id: str = Query(...),
    project_id: str = Query(...),
    keyword: str | None = Query(default=None),
    db: Session = Depends(get_db),
) -> list[PersonaPackResponse]:
    stmt = select(PersonaPack).where(
        PersonaPack.tenant_id == tenant_id,
        PersonaPack.project_id == project_id,
        PersonaPack.deleted_at.is_(None),
    )
    if keyword:
        like_value = f"%{keyword.strip()}%"
        stmt = stmt.where(PersonaPack.name.ilike(like_value))
    rows = db.execute(stmt.order_by(PersonaPack.created_at.desc())).scalars().all()
    return [
        PersonaPackResponse(
            id=row.id,
            tenant_id=row.tenant_id,
            project_id=row.project_id,
            name=row.name,
            description=row.description,
            tags_json=row.tags_json or [],
        )
        for row in rows
    ]


@router.post("/persona-packs/{persona_pack_id}/versions", response_model=PersonaVersionResponse, status_code=201)
def create_persona_version(
    persona_pack_id: str,
    body: PersonaVersionCreateRequest,
    db: Session = Depends(get_db),
) -> PersonaVersionResponse:
    pack = db.get(PersonaPack, persona_pack_id)
    if pack is None:
        raise HTTPException(status_code=404, detail="persona pack not found")

    row = PersonaPackVersion(
        id=f"persona_ver_{uuid4().hex}",
        tenant_id=body.tenant_id,
        project_id=body.project_id,
        trace_id=f"tr_persona_ver_{uuid4().hex[:12]}",
        correlation_id=f"cr_persona_ver_{uuid4().hex[:12]}",
        idempotency_key=f"idem_persona_ver_{persona_pack_id}_{body.version_name}_{uuid4().hex[:8]}",
        persona_pack_id=persona_pack_id,
        version_name=body.version_name,
        style_json=body.style_json,
        voice_json=body.voice_json,
        camera_json=body.camera_json,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return PersonaVersionResponse(
        id=row.id,
        persona_pack_id=row.persona_pack_id,
        version_name=row.version_name,
        style_json=row.style_json or {},
        voice_json=row.voice_json or {},
        camera_json=row.camera_json or {},
    )


@router.get("/persona-packs/{persona_pack_id}/versions", response_model=list[PersonaVersionResponse])
def list_persona_versions(persona_pack_id: str, db: Session = Depends(get_db)) -> list[PersonaVersionResponse]:
    rows = db.execute(
        select(PersonaPackVersion)
        .where(
            PersonaPackVersion.persona_pack_id == persona_pack_id,
            PersonaPackVersion.deleted_at.is_(None),
        )
        .order_by(PersonaPackVersion.created_at.desc())
    ).scalars().all()
    return [
        PersonaVersionResponse(
            id=row.id,
            persona_pack_id=row.persona_pack_id,
            version_name=row.version_name,
            style_json=row.style_json or {},
            voice_json=row.voice_json or {},
            camera_json=row.camera_json or {},
        )
        for row in rows
    ]


@router.post("/persona-versions/{persona_pack_version_id}/bindings", response_model=PersonaBindingResponse)
def bind_persona_resources(
    persona_pack_version_id: str,
    body: PersonaBindingRequest,
    db: Session = Depends(get_db),
) -> PersonaBindingResponse:
    version = db.get(PersonaPackVersion, persona_pack_version_id)
    if version is None:
        raise HTTPException(status_code=404, detail="persona version not found")

    dataset_ids: list[str] = []
    for collection_id in body.dataset_collection_ids:
        row = db.execute(
            select(PersonaDatasetBinding).where(
                PersonaDatasetBinding.tenant_id == body.tenant_id,
                PersonaDatasetBinding.project_id == body.project_id,
                PersonaDatasetBinding.persona_pack_version_id == persona_pack_version_id,
                PersonaDatasetBinding.collection_id == collection_id,
                PersonaDatasetBinding.deleted_at.is_(None),
            )
        ).scalars().first()
        if row is None:
            row = PersonaDatasetBinding(
                id=f"pdb_{uuid4().hex}",
                tenant_id=body.tenant_id,
                project_id=body.project_id,
                trace_id=f"tr_pdb_{uuid4().hex[:12]}",
                correlation_id=f"cr_pdb_{uuid4().hex[:12]}",
                idempotency_key=f"idem_pdb_{persona_pack_version_id}_{collection_id}",
                persona_pack_version_id=persona_pack_version_id,
                collection_id=collection_id,
                binding_role=body.binding_role,
                weight=1.0,
            )
            db.add(row)
        dataset_ids.append(collection_id)

    index_ids: list[str] = []
    for kb_version_id in body.kb_version_ids:
        row = db.execute(
            select(PersonaIndexBinding).where(
                PersonaIndexBinding.tenant_id == body.tenant_id,
                PersonaIndexBinding.project_id == body.project_id,
                PersonaIndexBinding.persona_pack_version_id == persona_pack_version_id,
                PersonaIndexBinding.kb_version_id == kb_version_id,
                PersonaIndexBinding.deleted_at.is_(None),
            )
        ).scalars().first()
        if row is None:
            row = PersonaIndexBinding(
                id=f"pib_{uuid4().hex}",
                tenant_id=body.tenant_id,
                project_id=body.project_id,
                trace_id=f"tr_pib_{uuid4().hex[:12]}",
                correlation_id=f"cr_pib_{uuid4().hex[:12]}",
                idempotency_key=f"idem_pib_{persona_pack_version_id}_{kb_version_id}",
                persona_pack_version_id=persona_pack_version_id,
                kb_version_id=kb_version_id,
                priority=100,
                retrieval_policy_json={"binding_role": body.binding_role},
            )
            db.add(row)
        index_ids.append(kb_version_id)

    db.commit()
    return PersonaBindingResponse(
        persona_pack_version_id=persona_pack_version_id,
        dataset_bindings=dataset_ids,
        index_bindings=index_ids,
    )


@router.post("/persona-preview", response_model=PersonaPreviewResponse)
def persona_preview(body: PersonaPreviewRequest, db: Session = Depends(get_db)) -> PersonaPreviewResponse:
    version = db.get(PersonaPackVersion, body.persona_pack_version_id)
    if version is None:
        raise HTTPException(status_code=404, detail="persona version not found")

    dataset_bindings = db.execute(
        select(PersonaDatasetBinding).where(
            PersonaDatasetBinding.tenant_id == body.tenant_id,
            PersonaDatasetBinding.project_id == body.project_id,
            PersonaDatasetBinding.persona_pack_version_id == body.persona_pack_version_id,
            PersonaDatasetBinding.deleted_at.is_(None),
        )
    ).scalars().all()
    index_bindings = db.execute(
        select(PersonaIndexBinding).where(
            PersonaIndexBinding.tenant_id == body.tenant_id,
            PersonaIndexBinding.project_id == body.project_id,
            PersonaIndexBinding.persona_pack_version_id == body.persona_pack_version_id,
            PersonaIndexBinding.deleted_at.is_(None),
        )
    ).scalars().all()

    collection_ids = [item.collection_id for item in dataset_bindings]
    kb_version_ids = [item.kb_version_id for item in index_bindings]

    docs_stmt = select(RagDocument).where(
        RagDocument.tenant_id == body.tenant_id,
        RagDocument.project_id == body.project_id,
        RagDocument.deleted_at.is_(None),
    )
    if collection_ids:
        docs_stmt = docs_stmt.where(RagDocument.collection_id.in_(collection_ids))
    if kb_version_ids:
        docs_stmt = docs_stmt.where(RagDocument.kb_version_id.in_(kb_version_ids))
    docs = db.execute(docs_stmt).scalars().all()

    tokens = [tok for tok in re.split(r"\W+", body.query.lower()) if tok]

    scored: list[tuple[float, RagDocument]] = []
    for doc in docs:
        text = (doc.content_text or "").lower()
        if not tokens:
            score = 0.0
        else:
            score = float(sum(text.count(token) for token in tokens))
        if score <= 0:
            continue
        scored.append((score, doc))
    scored.sort(key=lambda item: item[0], reverse=True)

    chunks: list[PersonaPreviewChunk] = []
    for score, doc in scored[: body.top_k]:
        snippet = (doc.content_text or "")[:240]
        chunks.append(
            PersonaPreviewChunk(
                doc_id=doc.id,
                collection_id=doc.collection_id,
                kb_version_id=doc.kb_version_id,
                title=doc.title,
                source_type=doc.source_type.value if hasattr(doc.source_type, "value") else str(doc.source_type),
                source_id=doc.source_id,
                score=score,
                snippet=snippet,
            )
        )

    return PersonaPreviewResponse(
        persona_pack_version_id=body.persona_pack_version_id,
        query=body.query,
        top_k=body.top_k,
        chunks=chunks,
    )


@router.delete("/collections/{collection_id}")
def delete_collection(
    collection_id: str,
    tenant_id: str = Query(...),
    project_id: str = Query(...),
    db: Session = Depends(get_db),
) -> dict[str, str]:
    row = db.execute(
        select(RagCollection).where(
            RagCollection.id == collection_id,
            RagCollection.tenant_id == tenant_id,
            RagCollection.project_id == project_id,
            RagCollection.deleted_at.is_(None),
        )
    ).scalars().first()
    if row is None:
        raise HTTPException(status_code=404, detail="REQ-VALIDATION-001: collection not found")
    row.deleted_at = datetime.now(timezone.utc)
    db.commit()
    return {"status": "deleted", "id": collection_id}


@router.delete("/persona-packs/{persona_pack_id}")
def delete_persona_pack(
    persona_pack_id: str,
    tenant_id: str = Query(...),
    project_id: str = Query(...),
    db: Session = Depends(get_db),
) -> dict[str, str]:
    row = db.execute(
        select(PersonaPack).where(
            PersonaPack.id == persona_pack_id,
            PersonaPack.tenant_id == tenant_id,
            PersonaPack.project_id == project_id,
            PersonaPack.deleted_at.is_(None),
        )
    ).scalars().first()
    if row is None:
        raise HTTPException(status_code=404, detail="REQ-VALIDATION-001: persona pack not found")
    row.deleted_at = datetime.now(timezone.utc)
    db.commit()
    return {"status": "deleted", "id": persona_pack_id}
