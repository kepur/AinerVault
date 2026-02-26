from typing import Any, Dict, List, Optional
from pydantic import BaseModel, ConfigDict, Field


class BaseSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class EntityItem(BaseSchema):
    entity_id: str
    entity_type: str
    display_name: str
    aliases: List[str] = Field(default_factory=list)
    attributes: Dict[str, Any] = Field(default_factory=dict)
    confidence: Optional[float] = None


class EntityPack(BaseSchema):
    pack_id: str
    run_id: str
    language: str = "zh-CN"
    entities: List[EntityItem] = Field(default_factory=list)
    schema_version: str = "1.0"
