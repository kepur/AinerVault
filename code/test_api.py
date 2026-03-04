import sys
sys.path.append("/workspace/apps/ainern2d-studio-api")
import os
from app.api.deps import get_db
from ainern2d_shared.ainer_db_models.content_models import Chapter, Novel
from ainern2d_shared.ainer_db_models.provider_models import ModelProvider
from app.api.v1.novels import extract_novel_entities, EntityExtractionRequest

db = next(get_db())
provider = db.query(ModelProvider).filter(ModelProvider.name=="deepseek").first()

print("Testing direct call to extract_novel_entities...")

req = EntityExtractionRequest(
    tenant_id="default",
    project_id="default",
    model_provider_id=provider.id,
    chapter_ids=None
)

try:
    res = extract_novel_entities(
        novel_id="novel_b831875078b348ffa5569429fdb4105c",
        body=req,
        db=db
    )
    print("Success. Total Entities:", res.entities_count)
    print("Preview JSON:")
    print(res.preview)
    print("Raw Output length:", len(res.raw_response))
except Exception as e:
    import traceback
    print("Failed to run extract_novel_entities:")
    traceback.print_exc()

