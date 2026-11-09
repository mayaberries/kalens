from typing import Optional
from datetime import datetime
from pydantic import BaseModel, ConfigDict, field_validator


class CoreModel(BaseModel):
    """
    Any common logic to be shared by all models goes here.
    """
    pass


class InputModel(CoreModel):
    """
    Base for new request bodies. Unknown fields are a 422 instead of being
    silently dropped. Existing input models still extend CoreModel: moving
    them changes what the library accepts, which is a contract change.
    """
    model_config = ConfigDict(extra="forbid")


class DateTimeModelMixin(BaseModel):
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    @field_validator("created_at", "updated_at", mode="before")
    @classmethod
    def default_datetime(cls, value: datetime) -> datetime:
        return value or datetime.now()


class IDModelMixin(BaseModel):
    id: str