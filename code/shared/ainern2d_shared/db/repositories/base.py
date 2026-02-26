from __future__ import annotations

from typing import Any, Generic, Optional, Sequence, TypeVar

from sqlalchemy import select
from sqlalchemy.orm import Session

from ainern2d_shared.ainer_db_models.base_model import Base

ModelT = TypeVar("ModelT", bound=Base)


class BaseRepository(Generic[ModelT]):
	model: type[ModelT]

	def __init__(self, db: Session):
		self.db = db

	def get(self, id: str) -> Optional[ModelT]:
		return self.db.get(self.model, id)

	def get_or_raise(self, id: str) -> ModelT:
		obj = self.get(id)
		if obj is None:
			raise LookupError(f"{self.model.__name__} id={id} not found")
		return obj

	def list_by(self, **filters: Any) -> Sequence[ModelT]:
		stmt = select(self.model).filter_by(**filters)
		return self.db.execute(stmt).scalars().all()

	def create(self, obj: ModelT) -> ModelT:
		self.db.add(obj)
		self.db.flush()
		return obj

	def update(self, obj: ModelT, **values: Any) -> ModelT:
		for k, v in values.items():
			setattr(obj, k, v)
		self.db.flush()
		return obj

	def delete(self, obj: ModelT) -> None:
		self.db.delete(obj)
		self.db.flush()
