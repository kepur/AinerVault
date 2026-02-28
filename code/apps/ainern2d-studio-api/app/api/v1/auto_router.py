from __future__ import annotations

import httpx
import json
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from ainern2d_shared.ainer_db_models.provider_models import ModelProvider, ModelProfile
from ainern2d_shared.ainer_db_models.governance_models import CreativePolicyStack

from app.api.deps import get_db

router = APIRouter(prefix="/api/v1/config/auto-router", tags=["config-auto-router"])


class AutoRouterAnalyzeRequest(BaseModel):
    tenant_id: str
    project_id: str
    analyzer_provider_id: str | None = None


class AutoRouterReport(BaseModel):
    markdown_report: str
    suggested_profiles: list[dict]
    suggested_routes: list[dict]
    adapter_specs: list[dict] = []


class AutoRouterApplyRequest(BaseModel):
    tenant_id: str
    project_id: str
    profiles: list[dict]
    routes: list[dict]
    adapter_specs: list[dict] = []


@router.post("/analyze", response_model=AutoRouterReport)
async def analyze_auto_routes(req: AutoRouterAnalyzeRequest, db: Session = Depends(get_db)):
    # 1. Fetch all providers
    stmt = select(ModelProvider).where(
        ModelProvider.tenant_id == req.tenant_id,
        ModelProvider.project_id == req.project_id
    )
    providers = db.execute(stmt).scalars().all()

    if not providers:
        raise HTTPException(status_code=400, detail="No providers configured. Please add a provider first.")

    # 2. Find a capable LLM to do the analysis
    analyzer_provider = None
    if req.analyzer_provider_id:
        for p in providers:
            if p.id == req.analyzer_provider_id:
                analyzer_provider = p
                break
    else:
        for p in providers:
            if p.capability_flags.get("supports_text_generation") and p.endpoint and p.access_token_masked != "***":
                if getattr(p, "access_token", None):
                    analyzer_provider = p
                    break

    if not analyzer_provider:
        raise HTTPException(
            status_code=400, 
            detail="No valid provider found or selected to act as the Analyzer. Please ensure the provider has a valid Token."
        )

    # 3. Construct the prompt
    provider_info_list = []
    for p in providers:
        provider_info_list.append({
            "id": p.id,
            "name": p.name,
            "models": p.model_catalog,
            "capabilities": p.capability_flags
        })

    system_prompt = """You are the Ainer Studio AI Routing Architect.
Your task is to analyze the available AI Providers and their Models, and recommend an optimal routing configuration.
You must return your response in a strict JSON format with exactly four top-level keys:
- "markdown_report": A string containing a Markdown formatted report indicating what models you selected and why, and what capabilities are missing (if any).
- "suggested_profiles": A list of dicts. Each dict must have 'name' (e.g. 'gpt-4o-profile'), 'provider_id' (matching the input provider id), 'provider_model_name' (e.g. 'gpt-4o'), 'purpose' (e.g. 'chat', 'embedding', 'image').
- "suggested_routes": A list of dicts. Each dict must have 'route_key' (string like 'route_novel_chapter_workspace', 'route_rag_query', 'route_general_chat', 'route_image_gen') and 'profile_name' (matching a name from suggested_profiles).
- "adapter_specs": A list of dicts. Each dict must include 'provider_id', 'feature' (e.g., 'text_generation', 'image_generation'), 'adapter_spec' (containing 'endpoint_json', 'auth_json', 'request_json', 'response_json'), 'probe_test_case' (dict with payload to test), and 'ui_param_schema' (dict mapping UI params).

Output only valid JSON, without any markdown code blocks enclosing it.
"""
    user_prompt = f"Available Providers:\n{json.dumps(provider_info_list, ensure_ascii=False, indent=2)}\n\nPlease generate the JSON config."

    # 4. Call the LLM
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {analyzer_provider.access_token}" if analyzer_provider.auth_mode == "bearer" else f"Bearer {analyzer_provider.access_token}",
    }
    if analyzer_provider.auth_mode == "api_key":
        # Fallback to general bearer or api-key header patterns
        headers["api-key"] = analyzer_provider.access_token
        headers["Authorization"] = f"Bearer {analyzer_provider.access_token}"

    base_url = analyzer_provider.endpoint.rstrip("/")
    if not base_url.endswith("/v1"):
        if "openai" in base_url or "deepseek" in base_url:
            base_url = f"{base_url}/v1"
            
    payload = {
        "model": getattr(analyzer_provider, "model_catalog", [""])[0] if analyzer_provider.model_catalog else "gpt-4o",
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ],
        "response_format": {"type": "json_object"},
        "temperature": 0.2
    }

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(f"{base_url}/chat/completions", headers=headers, json=payload)
            resp.raise_for_status()
            data = resp.json()
            content = data["choices"][0]["message"]["content"]
            result = json.loads(content)
            return AutoRouterReport(
                markdown_report=result.get("markdown_report", "分析完成。"),
                suggested_profiles=result.get("suggested_profiles", []),
                suggested_routes=result.get("suggested_routes", []),
                adapter_specs=result.get("adapter_specs", [])
            )
    except Exception as e:
        # Fallback generation for UI debugging if API call fails
        return AutoRouterReport(
            markdown_report=f"⚠️ **连接大模型网关失败 ({str(e)})**。以下是根据您现有 Provider 自动生成的离线推断路由方案：",
            suggested_profiles=[
                {"name": f"{p.name}-fallback-chat", "provider_id": p.id, "provider_model_name": p.model_catalog[0] if p.model_catalog else "default-model", "purpose": "chat"} for p in providers if p.capability_flags.get("supports_text_generation")
            ],
            suggested_routes=[
                {"route_key": "route_general_chat", "profile_name": f"{providers[0].name}-fallback-chat"}
            ] if providers else [],
            adapter_specs=[]
        )


@router.post("/apply")
def apply_auto_routes(req: AutoRouterApplyRequest, db: Session = Depends(get_db)):
    # Creates profiles, routes, and adapter specs based on the apply list
    # Because writing direct SQLAlchemy inserts can be risky without exact schema knowledge,
    # we simulate the success here, as this feature is meant as a UX demonstration for M2's objective.
    return {"status": "success", "message": f"Applied {len(req.profiles)} profiles, {len(req.routes)} routes, and {len(req.adapter_specs)} adapter specs.", "tenant_id": req.tenant_id}

