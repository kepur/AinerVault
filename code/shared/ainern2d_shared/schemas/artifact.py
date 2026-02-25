from typing import Optional, Dict, Any
from pydantic import BaseModel, ConfigDict, Field


class ArtifactResponse(BaseModel):
    """
    标准产物 DTO (对应 artifacts 库表)。
    """
    model_config = ConfigDict(from_attributes=True)
    
    id: str = Field(..., description="产物全局一唯一 ID")
    run_id: str = Field(..., description="产生它的 Run ID")
    shot_id: Optional[str] = Field(None, description="如果是单镜头的产物，此项有值")
    type: str = Field(..., description="video, audio, image, plan, text")
    path: str = Field(..., description="对象存储的 URI, 比如 s3://bucket/key.mp4")
    
    # Metadata for file checks
    size_bytes: Optional[int] = None
    mime_type: Optional[str] = None
    checksum: Optional[str] = None
    
    # 衍生额外属性
    meta_info: Optional[Dict[str, Any]] = Field(default_factory=dict)
