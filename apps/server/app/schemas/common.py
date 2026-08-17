import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class Msg(BaseModel):
    detail: str


class IdOut(ORMModel):
    id: uuid.UUID
    created_at: datetime | None = None
