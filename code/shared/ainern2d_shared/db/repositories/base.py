from __future__ import annotations

from sqlalchemy.orm import Session


class BaseRepository:
	def __init__(self, db: Session):
		self.db = db
