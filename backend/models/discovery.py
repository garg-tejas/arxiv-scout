from __future__ import annotations

from pydantic import BaseModel, Field


class SteeringPreferences(BaseModel):
    include: list[str] = Field(default_factory=list)
    exclude: list[str] = Field(default_factory=list)
    emphasize: list[str] = Field(default_factory=list)


class StartTopicRequest(BaseModel):
    topic: str = Field(min_length=3, max_length=500)


class ConfirmTopicRequest(BaseModel):
    confirmed: bool = True


class UpdateApprovedPapersRequest(BaseModel):
    paper_ids: list[str] = Field(default_factory=list)


class DiscoveryNudgeRequest(BaseModel):
    text: str = Field(min_length=3, max_length=1000)
