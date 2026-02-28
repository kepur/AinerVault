from __future__ import annotations

from datetime import datetime, timezone
import json
import requests
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ainern2d_shared.ainer_db_models.governance_models import CreativePolicyStack
from ainern2d_shared.ainer_db_models.provider_models import ModelProvider

from app.api.deps import get_db

router = APIRouter(prefix="/api/v1/culture-packs", tags=["culture_packs"])


class CulturePackCreateRequest(BaseModel):
    tenant_id: str
    project_id: str
    culture_pack_id: str
    display_name: str
    description: str | None = None
    constraints: dict = Field(default_factory=dict)


class CulturePackVersionCreateRequest(BaseModel):
    tenant_id: str
    project_id: str
    version: str
    display_name: str
    description: str | None = None
    constraints: dict = Field(default_factory=dict)
    status: str = "active"


class CulturePackResponse(BaseModel):
    culture_pack_id: str
    version: str
    display_name: str
    description: str | None = None
    status: str
    constraints: dict = Field(default_factory=dict)


class CulturePackExportResponse(BaseModel):
    culture_pack_id: str
    version: str
    export_for_skill_02: dict = Field(default_factory=dict)
    export_for_skill_07: dict = Field(default_factory=dict)
    export_for_skill_10: dict = Field(default_factory=dict)


class CulturePackTemplate(BaseModel):
    template_id: str
    name: str
    description: str
    category: str  # historical|modern|fantasy|sci-fi|other
    visual_do: list[str] = []
    visual_dont: list[str] = []
    signage_rules: dict = Field(default_factory=dict)
    costume_norms: dict = Field(default_factory=dict)
    prop_norms: dict = Field(default_factory=dict)


class ConstraintValidationRequest(BaseModel):
    culture_pack_id: str
    visual_do: list[str] = []
    visual_dont: list[str] = []
    signage_rules: dict = Field(default_factory=dict)
    costume_norms: dict = Field(default_factory=dict)
    prop_norms: dict = Field(default_factory=dict)


class ConstraintValidationResponse(BaseModel):
    culture_pack_id: str
    is_valid: bool
    violations: list[str] = []
    warnings: list[str] = []
    suggestions: list[str] = []


@router.post("", response_model=CulturePackResponse, status_code=201)
def create_culture_pack(
    body: CulturePackCreateRequest,
    db: Session = Depends(get_db),
) -> CulturePackResponse:
    version = "v1"
    row = _create_or_update_version(
        db=db,
        tenant_id=body.tenant_id,
        project_id=body.project_id,
        culture_pack_id=body.culture_pack_id,
        version=version,
        display_name=body.display_name,
        description=body.description,
        constraints=body.constraints,
        status="active",
    )
    return _to_response(row)


@router.post("/{culture_pack_id}/versions", response_model=CulturePackResponse, status_code=201)
def create_culture_pack_version(
    culture_pack_id: str,
    body: CulturePackVersionCreateRequest,
    db: Session = Depends(get_db),
) -> CulturePackResponse:
    row = _create_or_update_version(
        db=db,
        tenant_id=body.tenant_id,
        project_id=body.project_id,
        culture_pack_id=culture_pack_id,
        version=body.version,
        display_name=body.display_name,
        description=body.description,
        constraints=body.constraints,
        status=body.status,
    )
    return _to_response(row)


@router.get("", response_model=list[CulturePackResponse])
def list_culture_packs(
    tenant_id: str = Query(...),
    project_id: str = Query(...),
    keyword: str | None = Query(default=None),
    status: str | None = Query(default=None),
    db: Session = Depends(get_db),
) -> list[CulturePackResponse]:
    rows = db.execute(
        select(CreativePolicyStack)
        .where(
            CreativePolicyStack.tenant_id == tenant_id,
            CreativePolicyStack.project_id == project_id,
            CreativePolicyStack.deleted_at.is_(None),
        )
        .order_by(CreativePolicyStack.created_at.desc())
    ).scalars().all()

    latest_by_pack: dict[str, CreativePolicyStack] = {}
    for row in rows:
        payload = row.stack_json or {}
        if payload.get("type") != "culture_pack":
            continue
        pack_id = str(payload.get("culture_pack_id") or "")
        if not pack_id:
            continue
        if keyword and keyword.strip().lower() not in pack_id.lower() and keyword.strip().lower() not in str(
            payload.get("display_name") or ""
        ).lower():
            continue
        if status and row.status != status:
            continue
        if pack_id not in latest_by_pack:
            latest_by_pack[pack_id] = row

    return [_to_response(item) for item in latest_by_pack.values()]


@router.get("/{culture_pack_id}/versions", response_model=list[CulturePackResponse])
def list_culture_pack_versions(
    culture_pack_id: str,
    tenant_id: str = Query(...),
    project_id: str = Query(...),
    db: Session = Depends(get_db),
) -> list[CulturePackResponse]:
    rows = _query_culture_pack_rows(
        db=db,
        tenant_id=tenant_id,
        project_id=project_id,
        culture_pack_id=culture_pack_id,
    )
    return [_to_response(item) for item in rows]


@router.get("/{culture_pack_id}/export", response_model=CulturePackExportResponse)
def export_culture_pack(
    culture_pack_id: str,
    tenant_id: str = Query(...),
    project_id: str = Query(...),
    version: str | None = Query(default=None),
    db: Session = Depends(get_db),
) -> CulturePackExportResponse:
    rows = _query_culture_pack_rows(
        db=db,
        tenant_id=tenant_id,
        project_id=project_id,
        culture_pack_id=culture_pack_id,
    )
    if not rows:
        raise HTTPException(status_code=404, detail="culture pack not found")

    selected = rows[0]
    if version:
        for row in rows:
            payload = row.stack_json or {}
            if payload.get("version") == version:
                selected = row
                break

    payload = selected.stack_json or {}
    constraints = payload.get("constraints") or {}
    return CulturePackExportResponse(
        culture_pack_id=culture_pack_id,
        version=str(payload.get("version") or "v1"),
        export_for_skill_02={
            "culture_candidates": [culture_pack_id],
            "routing_constraints": constraints,
        },
        export_for_skill_07={
            "binding_constraints": constraints,
        },
        export_for_skill_10={
            "prompt_culture_layer": constraints,
        },
    )


@router.delete("/{culture_pack_id}")
def delete_culture_pack(
    culture_pack_id: str,
    tenant_id: str = Query(...),
    project_id: str = Query(...),
    db: Session = Depends(get_db),
) -> dict[str, str]:
    rows = _query_culture_pack_rows(
        db=db,
        tenant_id=tenant_id,
        project_id=project_id,
        culture_pack_id=culture_pack_id,
    )
    if not rows:
        raise HTTPException(status_code=404, detail="REQ-VALIDATION-001: culture pack not found")
    now = datetime.now(timezone.utc)
    for row in rows:
        row.deleted_at = now
    db.commit()
    return {"status": "deleted", "culture_pack_id": culture_pack_id}


@router.get("/templates", response_model=list[CulturePackTemplate])
def list_culture_pack_templates() -> list[CulturePackTemplate]:
    """Return predefined culture pack templates for users to select from."""
    return _get_culture_pack_templates()


@router.post("/validate", response_model=ConstraintValidationResponse)
def validate_culture_pack_constraints(
    body: ConstraintValidationRequest,
) -> ConstraintValidationResponse:
    """Validate culture pack constraints for visual rules, naming conventions, signage rules."""
    violations: list[str] = []
    warnings: list[str] = []
    suggestions: list[str] = []

    # Validate visual_do and visual_dont don't overlap
    visual_do_set = set(str(v).lower() for v in body.visual_do)
    visual_dont_set = set(str(v).lower() for v in body.visual_dont)
    overlap = visual_do_set & visual_dont_set
    if overlap:
        violations.append(f"Visual rules contain conflicting constraints: {', '.join(overlap)}")

    # Validate signage rules structure
    signage_rules = body.signage_rules or {}
    if signage_rules:
        required_fields = {"character_limit", "language", "font_style"}
        missing_fields = required_fields - set(signage_rules.keys())
        if missing_fields:
            warnings.append(f"Signage rules missing fields: {', '.join(missing_fields)}")

    # Validate costume norms
    costume_norms = body.costume_norms or {}
    if costume_norms:
        if "color_palette" in costume_norms:
            colors = costume_norms.get("color_palette") or []
            if not isinstance(colors, list) or len(colors) == 0:
                violations.append("Costume color_palette must be a non-empty list")

    # Validate prop norms
    prop_norms = body.prop_norms or {}
    if prop_norms:
        if "material_constraints" in prop_norms:
            materials = prop_norms.get("material_constraints") or []
            if not isinstance(materials, list) or len(materials) == 0:
                warnings.append("Prop material_constraints should specify allowed materials")

    # Generate suggestions
    if len(body.visual_do) == 0:
        suggestions.append("Consider adding specific visual guidelines to visual_do")
    if len(body.visual_dont) == 0:
        suggestions.append("Consider adding specific prohibitions to visual_dont")
    if not costume_norms:
        suggestions.append("Consider defining costume_norms for consistency")
    if not prop_norms:
        suggestions.append("Consider defining prop_norms for consistency")

    is_valid = len(violations) == 0
    return ConstraintValidationResponse(
        culture_pack_id=body.culture_pack_id,
        is_valid=is_valid,
        violations=violations,
        warnings=warnings,
        suggestions=suggestions,
    )


def _query_culture_pack_rows(
    *,
    db: Session,
    tenant_id: str,
    project_id: str,
    culture_pack_id: str,
) -> list[CreativePolicyStack]:
    rows = db.execute(
        select(CreativePolicyStack)
        .where(
            CreativePolicyStack.tenant_id == tenant_id,
            CreativePolicyStack.project_id == project_id,
            CreativePolicyStack.deleted_at.is_(None),
        )
        .order_by(CreativePolicyStack.created_at.desc())
    ).scalars().all()
    out: list[CreativePolicyStack] = []
    for row in rows:
        payload = row.stack_json or {}
        if payload.get("type") != "culture_pack":
            continue
        if payload.get("culture_pack_id") != culture_pack_id:
            continue
        out.append(row)
    return out


def _create_or_update_version(
    *,
    db: Session,
    tenant_id: str,
    project_id: str,
    culture_pack_id: str,
    version: str,
    display_name: str,
    description: str | None,
    constraints: dict,
    status: str,
) -> CreativePolicyStack:
    name = f"culture_pack:{culture_pack_id}:{version}"
    row = db.execute(
        select(CreativePolicyStack).where(
            CreativePolicyStack.tenant_id == tenant_id,
            CreativePolicyStack.project_id == project_id,
            CreativePolicyStack.name == name,
            CreativePolicyStack.deleted_at.is_(None),
        )
    ).scalars().first()

    payload = {
        "type": "culture_pack",
        "culture_pack_id": culture_pack_id,
        "version": version,
        "display_name": display_name,
        "description": description,
        "constraints": constraints,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }

    if row is None:
        row = CreativePolicyStack(
            id=f"culture_pack_{uuid4().hex}",
            tenant_id=tenant_id,
            project_id=project_id,
            trace_id=f"tr_culture_{uuid4().hex[:12]}",
            correlation_id=f"cr_culture_{uuid4().hex[:12]}",
            idempotency_key=f"idem_culture_{culture_pack_id}_{version}_{uuid4().hex[:8]}",
            name=name,
            status=status,
            stack_json=payload,
        )
        db.add(row)
    else:
        row.status = status
        row.stack_json = payload

    db.commit()
    db.refresh(row)
    return row


def _to_response(row: CreativePolicyStack) -> CulturePackResponse:
    payload = row.stack_json or {}
    return CulturePackResponse(
        culture_pack_id=str(payload.get("culture_pack_id") or ""),
        version=str(payload.get("version") or "v1"),
        display_name=str(payload.get("display_name") or row.name),
        description=payload.get("description"),
        status=row.status,
        constraints=payload.get("constraints") or {},
    )


def _get_culture_pack_templates() -> list[CulturePackTemplate]:
    """Return predefined culture pack templates for various cultural settings."""
    return [
        CulturePackTemplate(
            template_id="template_ancient_british",
            name="Ancient British",
            description="Medieval British setting with period-appropriate architecture and customs",
            category="historical",
            visual_do=[
                "Stone castles and timber-framed buildings",
                "Medieval armor and chainmail",
                "Natural earth tones and heraldic symbols",
                "Round arches and pointed arches",
            ],
            visual_dont=[
                "Modern technology or vehicles",
                "Electric lighting",
                "Contemporary clothing",
                "Plastic or synthetic materials",
            ],
            signage_rules={
                "character_limit": 50,
                "language": "English (Middle English acceptable)",
                "font_style": "Gothic or calligraphic",
                "material": "Wood, stone, or metal",
            },
            costume_norms={
                "color_palette": ["Black", "Gold", "Red", "Green", "Brown", "Grey"],
                "fabric_types": ["Wool", "Linen", "Silk"],
                "social_class_indicators": "Fabric quality and color saturation",
            },
            prop_norms={
                "material_constraints": ["Wood", "Metal", "Stone", "Leather"],
                "common_items": ["Swords", "Shields", "Torches", "Wooden furniture"],
            },
        ),
        CulturePackTemplate(
            template_id="template_modern_japan",
            name="Modern Japan",
            description="Contemporary Japanese urban setting with modern aesthetics",
            category="modern",
            visual_do=[
                "Modern high-rise buildings and architecture",
                "Neon signs and LED displays",
                "Contemporary fashion and accessories",
                "Clean lines and minimalist design",
                "Traditional Japanese elements mixed with modern",
            ],
            visual_dont=[
                "Historical samurai aesthetics in non-historical context",
                "Overly stereotypical representations",
                "Obsolete technology",
            ],
            signage_rules={
                "character_limit": 100,
                "language": "Japanese (Hiragana, Katakana, Kanji)",
                "font_style": "Modern sans-serif or stylized fonts",
                "material": "Plastic, metal, LED, neon",
            },
            costume_norms={
                "color_palette": ["Black", "White", "Navy", "Grey", "Pastels"],
                "fabric_types": ["Cotton", "Polyester", "Denim", "Silk"],
                "social_class_indicators": "Brand logos and fabric quality",
            },
            prop_norms={
                "material_constraints": ["Plastic", "Metal", "Glass", "Fabric"],
                "common_items": ["Mobile phones", "Convenience store items", "Bicycles"],
            },
        ),
        CulturePackTemplate(
            template_id="template_cyberpunk",
            name="Cyberpunk",
            description="High-tech dystopian future setting with advanced technology",
            category="sci-fi",
            visual_do=[
                "Neon lighting and holographic displays",
                "Futuristic cybernetic enhancements",
                "High-tech materials like chrome and carbon fiber",
                "Urban sprawl with vertical cities",
                "Glowing circuitry and LED patterns",
            ],
            visual_dont=[
                "Nature and natural materials",
                "Warm, organic lighting",
                "Historical references",
                "Low-tech solutions",
            ],
            signage_rules={
                "character_limit": 80,
                "language": "Mixed tech jargon and neolanguage",
                "font_style": "Bold, angular, futuristic digital fonts",
                "material": "LED, holographic, plasma screens",
            },
            costume_norms={
                "color_palette": ["Black", "Neon Pink", "Cyan", "Purple", "Silver"],
                "fabric_types": ["Synthetic", "Leather", "Metallic"],
                "social_class_indicators": "Technology augmentation level",
            },
            prop_norms={
                "material_constraints": ["Metal", "Glass", "Synthetic", "Circuitry"],
                "common_items": ["Data pads", "Weapons with energy cells", "Hacking tools"],
            },
        ),
        CulturePackTemplate(
            template_id="template_wuxia",
            name="Chinese Wuxia",
            description="Martial arts and ancient Chinese setting",
            category="historical",
            visual_do=[
                "Traditional Chinese architecture with curved roofs",
                "Silk robes and martial arts costumes",
                "Calligraphic decorations and Chinese art",
                "Bamboo forests and misty mountains",
                "Lanterns and traditional lighting",
            ],
            visual_dont=[
                "Western architectural styles",
                "Modern materials or technology",
                "Contemporary fashion",
            ],
            signage_rules={
                "character_limit": 30,
                "language": "Chinese (Traditional or Simplified)",
                "font_style": "Calligraphic or brush-style",
                "material": "Wood, silk, paper",
            },
            costume_norms={
                "color_palette": ["Red", "Gold", "Black", "White", "Purple", "Blue"],
                "fabric_types": ["Silk", "Linen", "Cotton"],
                "social_class_indicators": "Martial school rank and embroidery quality",
            },
            prop_norms={
                "material_constraints": ["Wood", "Metal", "Leather", "Stone"],
                "common_items": ["Martial arts weapons", "Scrolls", "Tea sets"],
            },
        ),
    ]


class CulturePackLlmExtractRequest(BaseModel):
    tenant_id: str
    project_id: str
    model_provider_id: str
    world_description: str
    culture_pack_id: str | None = None
    display_name: str | None = None


class CulturePackLlmExtractResponse(BaseModel):
    culture_pack_id: str
    version: str
    display_name: str
    constraints: dict = Field(default_factory=dict)
    status: str


_CULTURE_PACK_LLM_PROMPT = """从以下世界观描述中提取文化包数据，以JSON格式输出，不要输出其他内容。

输出格式：
{{
  "visual_do": ["视觉风格允许元素1", "允许元素2"],
  "visual_dont": ["视觉禁止元素1", "禁止元素2"],
  "signage_rules": {{"character_limit": 50, "language": "语言描述", "font_style": "字体风格", "material": "材质"}},
  "costume_norms": {{"color_palette": ["颜色1", "颜色2"], "fabric_types": ["面料1"], "social_class_indicators": "描述"}},
  "prop_norms": {{"material_constraints": ["材质1", "材质2"], "common_items": ["道具1", "道具2"]}}
}}

世界观描述：
{world_description}
"""


def _load_culture_pack_provider_settings(
    db: Session,
    *,
    tenant_id: str,
    project_id: str,
    provider_id: str,
) -> dict:
    row = db.execute(
        select(CreativePolicyStack).where(
            CreativePolicyStack.tenant_id == tenant_id,
            CreativePolicyStack.project_id == project_id,
            CreativePolicyStack.name == f"provider_settings:{provider_id}",
            CreativePolicyStack.deleted_at.is_(None),
        )
    ).scalars().first()
    if row is None:
        return {}
    return dict(row.stack_json or {})


@router.post("/llm-extract", response_model=CulturePackLlmExtractResponse)
def llm_extract_culture_pack(
    body: CulturePackLlmExtractRequest,
    db: Session = Depends(get_db),
) -> CulturePackLlmExtractResponse:
    if not body.world_description.strip():
        raise HTTPException(status_code=400, detail="world_description is required")

    provider = db.get(ModelProvider, body.model_provider_id)
    if provider is None or provider.deleted_at is not None:
        raise HTTPException(status_code=404, detail="model provider not found")
    if provider.tenant_id != body.tenant_id or provider.project_id != body.project_id:
        raise HTTPException(status_code=403, detail="model provider scope mismatch")

    provider_settings = _load_culture_pack_provider_settings(
        db,
        tenant_id=body.tenant_id,
        project_id=body.project_id,
        provider_id=provider.id,
    )

    endpoint = (provider.endpoint or "").strip().rstrip("/")
    token = str(provider_settings.get("access_token") or "").strip()
    model_catalog = list(provider_settings.get("model_catalog") or [])
    model_name = model_catalog[0] if model_catalog else "gpt-4o-mini"

    if not endpoint or not token:
        raise HTTPException(status_code=422, detail="provider endpoint/token not configured")

    prompt = _CULTURE_PACK_LLM_PROMPT.format(world_description=body.world_description[:4000])

    try:
        response = requests.post(
            f"{endpoint}/chat/completions",
            json={
                "model": model_name,
                "messages": [
                    {"role": "system", "content": "你是专业的世界观设计师，擅长提取文化约束规则。"},
                    {"role": "user", "content": prompt},
                ],
                "temperature": 0.3,
                "max_tokens": 1500,
            },
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            timeout=90.0,
        )
        if response.status_code < 200 or response.status_code >= 300:
            raise ValueError(f"provider_http_status_{response.status_code}")

        parsed = response.json() if response.text else {}
        choices = parsed.get("choices") or []
        content = str((choices[0].get("message") or {}).get("content") or "").strip() if choices else ""

        import re as _re
        json_match = _re.search(r'\{.*\}', content, _re.DOTALL)
        if json_match:
            constraints = json.loads(json_match.group())
        else:
            constraints = {}
    except (requests.RequestException, ValueError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=502, detail=f"LLM call failed: {exc}") from exc

    # Determine pack ID and name
    culture_pack_id = body.culture_pack_id or f"llm_pack_{uuid4().hex[:8]}"
    display_name = body.display_name or f"LLM Generated Pack ({culture_pack_id})"
    version = "v1"

    row = _create_or_update_version(
        db=db,
        tenant_id=body.tenant_id,
        project_id=body.project_id,
        culture_pack_id=culture_pack_id,
        version=version,
        display_name=display_name,
        description=body.world_description[:500],
        constraints=constraints,
        status="active",
    )

    return CulturePackLlmExtractResponse(
        culture_pack_id=culture_pack_id,
        version=version,
        display_name=display_name,
        constraints=constraints,
        status="active",
    )
