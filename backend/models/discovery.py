from __future__ import annotations

from pydantic import BaseModel, Field


class StartTopicRequest(BaseModel):
    topic: str = Field(min_length=3, max_length=500)


class ConfirmTopicRequest(BaseModel):
    confirmed: bool = True
