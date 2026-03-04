from app.api.deps import get_db
from ainern2d_shared.ainer_db_models.content_models import Chapter, Novel
from ainern2d_shared.ainer_db_models.provider_models import ModelProvider
from app.api.v1.novels import _ENTITY_EXTRACTION_PROMPT, _expand_with_provider, _load_provider_settings
import re as _re
import json

db = next(get_db())
chapters = db.query(Chapter).filter(Chapter.novel_id=="novel_b831875078b348ffa5569429fdb4105c").all()
content_parts = []
for ch in chapters:
    text = (ch.raw_text or "").strip()
    if text:
        content_parts.append("=== 第" + str(ch.chapter_no) + "章 " + str(ch.title or "") + " ===\n" + text[:3000])

combined_content = "\n\n".join(content_parts[:5])
print("Combined length:", len(combined_content))

provider = db.query(ModelProvider).filter(ModelProvider.name=="deepseek").first()
print("Provider:", getattr(provider, "name", "None"))
if not provider:
    print("Provider not found!")
    exit(1)

settings = _load_provider_settings(db, tenant_id="default", project_id="default", provider_id=provider.id)
prompt = _ENTITY_EXTRACTION_PROMPT.format(content=combined_content)

for attempt in range(1):
    content, _, _ = _expand_with_provider(
        provider=provider,
        provider_settings=settings,
        prompt=prompt,
        max_tokens=2000,
    )
    print("----- RAW CONTENT BEGIN -----")
    print(content)
    print("----- RAW CONTENT END -----")
    json_match = _re.search(r"\{.*\}", content, _re.DOTALL)
    if json_match:
        try:
            extracted = json.loads(json_match.group())
            print("Successfully extracted JSON!")
            print(json.dumps(extracted, ensure_ascii=False, indent=2))
        except Exception as e:
            print("JSON parse error:", e)
    else:
        print("No JSON match.")
