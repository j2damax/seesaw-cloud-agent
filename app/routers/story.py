# story.py — POST /story/generate
# Primary endpoint consumed by the iOS CloudAgentService.
# Field names in the response are fixed — they match CloudAgentService.swift's StoryResponse decoder.

import uuid
import logging
from fastapi import APIRouter, HTTPException

from app.models.scene_payload import ScenePayload
from app.models.story_beat import StoryBeatResponse
from app.agents.story_agent import generate_story_beat
from app.services.firestore import create_session, append_beat, get_beat_count

logger = logging.getLogger(__name__)
router = APIRouter()

MAX_TURNS = 8


@router.post("/generate", response_model=StoryBeatResponse)
async def generate_story(payload: ScenePayload):
    """
    Generate the next story beat from a ScenePayload.

    Privacy contract: this endpoint never logs transcript content, child_name,
    or any raw media. Only object/scene counts are logged for observability.
    """
    session_id = payload.session_id or str(uuid.uuid4())

    # Determine turn count to decide if this is the final beat
    beat_index = await get_beat_count(session_id)
    is_final_beat = beat_index >= MAX_TURNS - 1

    logger.info(
        "generate_story: session=%s objects=%d scene=%d turn=%d final=%s",
        session_id[:8],  # log only prefix for pseudonymity
        len(payload.objects),
        len(payload.scene),
        beat_index,
        is_final_beat,
    )

    try:
        beat = await generate_story_beat(
            objects=payload.objects,
            scene=payload.scene,
            child_name=payload.child_name,
            child_age=payload.child_age,
            transcript=payload.transcript,
            story_history=[t.model_dump() for t in payload.story_history],
            is_final_beat=is_final_beat,
        )
    except Exception as exc:
        logger.error("generate_story: agent error: %s", exc)
        raise HTTPException(status_code=503, detail={"error": "Story generation failed", "detail": str(exc)})

    # Persist to Firestore
    await create_session(session_id, payload.child_age, payload.objects, payload.scene)
    await append_beat(session_id, beat_index, beat)

    return StoryBeatResponse(
        story_text=beat["story_text"],
        question=beat["question"],
        is_ending=beat["is_ending"],
        session_id=session_id,
        beat_index=beat_index,
    )
