# session.py — GET /session/{id}, DELETE /session/{id}
# Session retrieval and GDPR right-to-erasure delete.

import logging
from fastapi import APIRouter, HTTPException
from app.services.firestore import get_session, delete_session

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/{session_id}")
async def read_session(session_id: str):
    session = await get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail={"error": "Session not found"})
    return session


@router.delete("/{session_id}")
async def remove_session(session_id: str):
    await delete_session(session_id)
    return {"deleted": True}
