# scene_payload.py
# Mirrors the iOS ScenePayload struct exactly.
# Field names match what CloudAgentService.swift sends — do not rename.

from pydantic import BaseModel, Field


class StoryTurn(BaseModel):
    role: str    # "model" or "user"
    text: str


class ScenePayload(BaseModel):
    objects: list[str] = Field(..., description="YOLO-detected object labels")
    scene: list[str] = Field(..., description="Scene classification labels")
    transcript: str | None = Field(None, description="PII-scrubbed child speech")
    child_age: int = Field(..., ge=2, le=12)
    child_name: str = Field(..., min_length=1, max_length=50)
    story_history: list[StoryTurn] = Field(default_factory=list)
    session_id: str | None = None
