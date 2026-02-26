from pydantic import BaseModel, ConfigDict


class BaseSchema(BaseModel):
    """
    通用基类模型，所有 DTO Schema 统一继承此类。
    """
    model_config = ConfigDict(
        populate_by_name=True,
        from_attributes=True,
        protected_namespaces=(),
    )
