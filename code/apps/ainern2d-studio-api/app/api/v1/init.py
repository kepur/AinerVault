from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ainern2d_shared.ainer_db_models.auth_models import User
from ainern2d_shared.ainer_db_models.governance_models import CreativePolicyStack
from ainern2d_shared.ainer_db_models.governance_models import PersonaPack, PersonaPackVersion
from ainern2d_shared.ainer_db_models.rag_models import RagCollection

from app.api.deps import get_db

router = APIRouter(prefix="/api/v1/init", tags=["init"])

_DEFAULT_TENANT_ID = "default"
_DEFAULT_PROJECT_ID = "default"


class BootstrapAllRequest(BaseModel):
    tenant_id: str = _DEFAULT_TENANT_ID
    project_id: str = _DEFAULT_PROJECT_ID
    model_provider_id: str | None = None
    force: bool = False


class BootstrapStepResult(BaseModel):
    step: str
    status: str
    detail: str | None = None


class BootstrapAllResponse(BaseModel):
    status: str
    steps: list[BootstrapStepResult]


_DEFAULT_USERS = [
    {"email": "admin@ainer.ai", "display_name": "Ainer Admin", "raw_password": "Admin@123456"},
    {"email": "editor@ainer.ai", "display_name": "Ainer Editor", "raw_password": "Editor@123456"},
    {"email": "viewer@ainer.ai", "display_name": "Ainer Viewer", "raw_password": "Viewer@123456"},
]

_DEFAULT_ROUTE_PERMISSIONS = [
    {"path_prefix": "/api/v1/auth/users", "method": "*", "required_role": "admin"},
    {"path_prefix": "/api/v1/config/", "method": "*", "required_role": "admin"},
    {"path_prefix": "/api/v1/novels", "method": "POST", "required_role": "editor"},
    {"path_prefix": "/api/v1/rag/", "method": "POST", "required_role": "editor"},
    {"path_prefix": "/api/v1/culture-packs/", "method": "POST", "required_role": "editor"},
]

_DEFAULT_CULTURE_PACKS = [
    {
        "id": "en_us_global",
        "display_name": "美区/全球广告风",
        "constraints": {
            "visual_do": ["高频切换的快剪", "商业感布光", "现代美式穿搭", "高饱和度对比"],
            "visual_dont": ["廉价背景", "长镜头沉闷叙事", "低清画质"],
            "signage_rules": {"character_limit": 50, "language": "English", "font_style": "现代无衬线"},
            "costume_norms": {"color_palette": ["高对比色", "精英灰/黑"], "fabric_types": ["质感混纺", "西服面料"]},
            "prop_norms": {"material_constraints": ["科技感", "高通透玻璃"], "common_items": ["智能设备", "咖啡杯", "汽车"]},
        },
    },
    {
        "id": "zh_cn_drama",
        "display_name": "出海微短剧 (霸总/仙侠)",
        "constraints": {
            "visual_do": ["高颜值选角", "强情感冲突特写", "竖屏构图优化", "夸张的打脸反转"],
            "visual_dont": ["平淡叙事", "缓慢节奏", "群演抢戏"],
            "signage_rules": {"character_limit": 20, "language": "中文", "font_style": "黑体/宋体加粗"},
            "costume_norms": {"color_palette": ["高定总裁黑/白", "华丽古风色系"], "fabric_types": ["丝绸", "高级西服面料"]},
            "prop_norms": {"material_constraints": ["昂贵金属", "玉石"], "common_items": ["黑卡", "奢侈品", "契约书", "跑车"]},
        },
    },
    {
        "id": "ja_jp_anime",
        "display_name": "日系二次元/高质感",
        "constraints": {
            "visual_do": ["赛璐璐质感渲染", "日式街景/学校", "细腻光影", "高光特写"],
            "visual_dont": ["美式粗犷", "过度真实的瑕疵"],
            "signage_rules": {"character_limit": 40, "language": "日本語", "font_style": "明朝体"},
            "costume_norms": {"color_palette": ["低饱和度日系色", "制服配色"], "fabric_types": ["棉麻", "制服呢"]},
            "prop_norms": {"material_constraints": ["木结构", "纸质"], "common_items": ["便当", "电车", "樱花", "手机"]},
        },
    },
    {
        "id": "ar_sa_luxury",
        "display_name": "中东土豪/奢华纷争",
        "constraints": {
            "visual_do": ["极致奢华布景", "传统阿拉伯服饰融合现代豪车", "沙漠滤镜", "家族会议场景"],
            "visual_dont": ["简陋场景", "过于开放的穿着"],
            "signage_rules": {"character_limit": 60, "language": "العربية", "font_style": "传统阿拉伯书法体"},
            "costume_norms": {"color_palette": ["纯白(Kandura)", "纯黑(Abaya)", "金色高光"], "fabric_types": ["高级真丝", "羊毛"]},
            "prop_norms": {"material_constraints": ["纯金", "大理石", "水晶"], "common_items": ["猎鹰", "超级跑车", "黄金饰品"]},
        },
    },
    {
        "id": "es_mx_telenovela",
        "display_name": "拉美情感剧 (Telenovela)",
        "constraints": {
            "visual_do": ["浮夸的表情特写", "高饱和度热带色彩", "戏剧性推拉镜头", "豪宅内部"],
            "visual_dont": ["内敛的情感表达", "冷色调"],
            "signage_rules": {"character_limit": 50, "language": "Español", "font_style": "戏剧性手写体/无衬线"},
            "costume_norms": {"color_palette": ["大红", "鲜黄", "深黑", "明艳色块"], "fabric_types": ["紧身面料", "丝缎"]},
            "prop_norms": {"material_constraints": ["浮夸珠宝", "厚重家具"], "common_items": ["信件", "遗嘱", "家族合影"]},
        },
    },
    {
        "id": "vi_vn_tiktok",
        "display_name": "越南 TikTok 流量池",
        "constraints": {
            "visual_do": ["单人直面镜头", "配合热门BGM卡点", "魔性滤镜", "东南亚街头烟火气"],
            "visual_dont": ["长达1分钟不切换画面", "沉重的说教"],
            "signage_rules": {"character_limit": 30, "language": "Tiếng Việt", "font_style": "活泼的粗体广告字"},
            "costume_norms": {"color_palette": ["高明度快时尚色", "荧光点缀"], "fabric_types": ["全棉", "轻薄面料"]},
            "prop_norms": {"material_constraints": ["塑料", "不锈钢", "轻工业材质"], "common_items": ["摩托车", "街边小吃", "手机支架"]},
        },
    },
    {
        "id": "pt_br_carnival",
        "display_name": "巴西狂欢/娱乐社交",
        "constraints": {
            "visual_do": ["充满活力的群像", "海边/阳光直射", "高频互动感", "随性的手持镜头"],
            "visual_dont": ["僵硬的摆拍", "阴暗压抑的打光"],
            "signage_rules": {"character_limit": 45, "language": "Português", "font_style": "充满葡萄牙风情的海报体"},
            "costume_norms": {"color_palette": ["绿", "黄", "蓝", "热带雨林色"], "fabric_types": ["泳装材质", "轻盈透气面料"]},
            "prop_norms": {"material_constraints": ["天然草木", "冰块", "玻璃"], "common_items": ["冷饮", "乐器", "足球", "沙滩椅"]},
        },
    },
    {
        "id": "hi_in_bollywood",
        "display_name": "印度宝莱坞风",
        "constraints": {
            "visual_do": ["高频变焦与音效配合", "群体舞蹈/歌舞元素", "夸张的反重力动作", "极其鲜艳的滤镜"],
            "visual_dont": ["极简主义", "缓慢无配乐的文戏"],
            "signage_rules": {"character_limit": 60, "language": "हिन्दी", "font_style": "传统印地语字体"},
            "costume_norms": {"color_palette": ["大红", "亮黄", "明亮撞色"], "fabric_types": ["纱丽面料", "重工刺绣"]},
            "prop_norms": {"material_constraints": ["木雕", "五彩布料", "黄铜"], "common_items": ["花环", "摩托车", "传统乐器"]},
        },
    },
    {
        "id": "de_de_industry",
        "display_name": "欧洲工业/演示教育",
        "constraints": {
            "visual_do": ["冷色调", "极简对称构图", "精密机械特写", "严谨的图表叠加"],
            "visual_dont": ["混乱的背景", "夸张的特效", "多余的闲聊镜头"],
            "signage_rules": {"character_limit": 80, "language": "Deutsch", "font_style": "现代极简无衬线 / DIN字体"},
            "costume_norms": {"color_palette": ["工业灰", "白", "藏青"], "fabric_types": ["防静电面料", "挺括西装"]},
            "prop_norms": {"material_constraints": ["合金", "碳纤维", "防眩光玻璃"], "common_items": ["图纸", "全息投影", "护目镜"]},
        },
    },
    {
        "id": "ph_ph_social",
        "display_name": "菲律宾网红/社媒电商",
        "constraints": {
            "visual_do": ["带货口播", "虚拟博主/AI换脸感", "美颜滤镜", "生活小剧场引入"],
            "visual_dont": ["高深的专业术语", "缺乏互动的冷场"],
            "signage_rules": {"character_limit": 40, "language": "Filipino/English", "font_style": "网红风手写体"},
            "costume_norms": {"color_palette": ["马卡龙色", "流行快消色"], "fabric_types": ["混纺", "网纱衣"]},
            "prop_norms": {"material_constraints": ["亚克力", "LED灯牌"], "common_items": ["环形灯", "化妆品包装", "自拍杆"]},
        },
    },
]


def _hash_password(raw_password: str) -> str:
    import hashlib
    digest = hashlib.sha256(f"ainer::{raw_password}".encode("utf-8")).hexdigest()
    return f"sha256${digest}"


@router.post("/bootstrap-all", response_model=BootstrapAllResponse)
def bootstrap_all(
    body: BootstrapAllRequest,
    db: Session = Depends(get_db),
) -> BootstrapAllResponse:
    steps: list[BootstrapStepResult] = []

    # Step 1: Create default users
    try:
        created_count = 0
        for u in _DEFAULT_USERS:
            existing = db.execute(
                select(User).where(
                    User.tenant_id == body.tenant_id,
                    User.email == u["email"],
                    User.deleted_at.is_(None),
                )
            ).scalars().first()
            if existing is None or body.force:
                if existing is None:
                    user = User(
                        id=f"user_{uuid4().hex}",
                        tenant_id=body.tenant_id,
                        project_id=body.project_id,
                        email=u["email"],
                        display_name=u["display_name"],
                        password_hash=_hash_password(u["raw_password"]),
                    )
                    db.add(user)
                    created_count += 1
        db.flush()
        steps.append(BootstrapStepResult(step="default_users", status="ok", detail=f"created {created_count} users"))
    except Exception as exc:
        db.rollback()
        steps.append(BootstrapStepResult(step="default_users", status="error", detail=str(exc)))

    # Step 2: Write route permissions
    try:
        written = 0
        for perm in _DEFAULT_ROUTE_PERMISSIONS:
            name = f"route_permission:{perm['path_prefix']}:{perm['method']}"
            existing = db.execute(
                select(CreativePolicyStack).where(
                    CreativePolicyStack.tenant_id == body.tenant_id,
                    CreativePolicyStack.project_id == body.project_id,
                    CreativePolicyStack.name == name,
                    CreativePolicyStack.deleted_at.is_(None),
                )
            ).scalars().first()
            payload = {
                "type": "route_permission",
                "path_prefix": perm["path_prefix"],
                "method": perm["method"],
                "required_role": perm["required_role"],
            }
            if existing is None:
                row = CreativePolicyStack(
                    id=f"perm_{uuid4().hex}",
                    tenant_id=body.tenant_id,
                    project_id=body.project_id,
                    trace_id=f"tr_perm_{uuid4().hex[:12]}",
                    correlation_id=f"cr_perm_{uuid4().hex[:12]}",
                    idempotency_key=f"idem_perm_{uuid4().hex[:8]}",
                    name=name,
                    status="active",
                    stack_json=payload,
                )
                db.add(row)
                written += 1
        db.flush()
        steps.append(BootstrapStepResult(step="route_permissions", status="ok", detail=f"written {written} permissions"))
    except Exception as exc:
        steps.append(BootstrapStepResult(step="route_permissions", status="error", detail=str(exc)))

    # Step 3: Create default culture packs
    try:
        packs_created = 0
        for pack in _DEFAULT_CULTURE_PACKS:
            name = f"culture_pack:{pack['id']}:v1"
            existing = db.execute(
                select(CreativePolicyStack).where(
                    CreativePolicyStack.tenant_id == body.tenant_id,
                    CreativePolicyStack.project_id == body.project_id,
                    CreativePolicyStack.name == name,
                    CreativePolicyStack.deleted_at.is_(None),
                )
            ).scalars().first()
            if existing is None:
                payload = {
                    "type": "culture_pack",
                    "culture_pack_id": pack["id"],
                    "version": "v1",
                    "display_name": pack["display_name"],
                    "description": f"Default culture pack: {pack['display_name']}",
                    "constraints": pack["constraints"],
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                }
                row = CreativePolicyStack(
                    id=f"culture_pack_{uuid4().hex}",
                    tenant_id=body.tenant_id,
                    project_id=body.project_id,
                    trace_id=f"tr_culture_{uuid4().hex[:12]}",
                    correlation_id=f"cr_culture_{uuid4().hex[:12]}",
                    idempotency_key=f"idem_culture_{pack['id']}_v1_{uuid4().hex[:8]}",
                    name=name,
                    status="active",
                    stack_json=payload,
                )
                db.add(row)
                packs_created += 1
        db.flush()
        steps.append(BootstrapStepResult(step="culture_packs", status="ok", detail=f"created {packs_created} packs"))
    except Exception as exc:
        steps.append(BootstrapStepResult(step="culture_packs", status="error", detail=str(exc)))

    # Step 4: Create default RAG collection
    try:
        existing_coll = db.execute(
            select(RagCollection).where(
                RagCollection.tenant_id == body.tenant_id,
                RagCollection.project_id == body.project_id,
                RagCollection.name == "default_knowledge",
                RagCollection.deleted_at.is_(None),
            )
        ).scalars().first()
        if existing_coll is None:
            coll = RagCollection(
                id=f"coll_{uuid4().hex}",
                tenant_id=body.tenant_id,
                project_id=body.project_id,
                name="default_knowledge",
                language_code="zh",
                description="Default knowledge collection",
            )
            db.add(coll)
            db.flush()
            detail = f"created collection: {coll.id}"
        else:
            detail = f"already exists: {existing_coll.id}"
        steps.append(BootstrapStepResult(step="rag_collection", status="ok", detail=detail))
    except Exception as exc:
        steps.append(BootstrapStepResult(step="rag_collection", status="error", detail=str(exc)))

    # Step 5: Create default Persona Pack
    try:
        existing_persona = db.execute(
            select(PersonaPack).where(
                PersonaPack.tenant_id == body.tenant_id,
                PersonaPack.project_id == body.project_id,
                PersonaPack.name == "director_default",
                PersonaPack.deleted_at.is_(None),
            )
        ).scalars().first()
        if existing_persona is None:
            persona = PersonaPack(
                id=f"persona_{uuid4().hex}",
                tenant_id=body.tenant_id,
                project_id=body.project_id,
                name="director_default",
                description="Default director persona",
            )
            db.add(persona)
            db.flush()
            persona_version = PersonaPackVersion(
                id=f"pv_{uuid4().hex}",
                tenant_id=body.tenant_id,
                project_id=body.project_id,
                persona_pack_id=persona.id,
                version_name="v1",
                style_json={"style": "cinematic", "tone": "neutral"},
                voice_json={},
                camera_json={"default_angle": "medium", "movement": "smooth"},
            )
            db.add(persona_version)
            db.flush()
            detail = f"created persona: {persona.id}"
        else:
            detail = f"already exists: {existing_persona.id}"
        steps.append(BootstrapStepResult(step="persona_pack", status="ok", detail=detail))
    except Exception as exc:
        steps.append(BootstrapStepResult(step="persona_pack", status="error", detail=str(exc)))

    db.commit()

    all_ok = all(s.status == "ok" for s in steps)
    return BootstrapAllResponse(
        status="completed" if all_ok else "partial",
        steps=steps,
    )
