# story_beat.py
# Mirrors the iOS StoryBeat struct + adds cloud-specific fields.
# Field names match what CloudAgentService.swift decodes — do not rename.

from pydantic import BaseModel


class StoryBeatResponse(BaseModel):
    story_text: str      # iOS decodes as storyText via keyDecodingStrategy.convertFromSnakeCase
    question: str
    is_ending: bool
    session_id: str
    beat_index: int
