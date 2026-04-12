# firestore.py
# Firestore CRUD for session and beat persistence.
# Schema: sessions/{session_id}/beats/{beat_index}

import logging
from datetime import datetime, timedelta, timezone
from google.cloud import firestore

logger = logging.getLogger(__name__)

_db: firestore.AsyncClient | None = None


def _get_db() -> firestore.AsyncClient:
    global _db
    if _db is None:
        _db = firestore.AsyncClient()
    return _db


async def create_session(
    session_id: str,
    child_age: int,
    objects: list[str],
    scene: list[str],
) -> None:
    """Creates or merges a session document. Does not overwrite existing beats."""
    db = _get_db()
    ttl = datetime.now(timezone.utc) + timedelta(days=30)
    await db.collection("sessions").document(session_id).set(
        {
            "child_age":  child_age,
            "objects":    objects,
            "scene":      scene,
            "created_at": firestore.SERVER_TIMESTAMP,
            "ttl":        ttl,          # TTL policy auto-deletes after 30 days
        },
        merge=True,
    )


async def append_beat(session_id: str, beat_index: int, beat: dict) -> None:
    db = _get_db()
    await (
        db.collection("sessions")
        .document(session_id)
        .collection("beats")
        .document(str(beat_index))
        .set(
            {
                "beat_index": beat_index,
                "story_text": beat["story_text"],
                "question":   beat["question"],
                "is_ending":  beat["is_ending"],
                "timestamp":  firestore.SERVER_TIMESTAMP,
            }
        )
    )


async def get_beat_count(session_id: str) -> int:
    """Returns the number of beats already stored for this session."""
    db = _get_db()
    beats = db.collection("sessions").document(session_id).collection("beats")
    docs = beats.stream()
    count = 0
    async for _ in docs:
        count += 1
    return count


async def get_session(session_id: str) -> dict | None:
    db = _get_db()
    doc = await db.collection("sessions").document(session_id).get()
    if not doc.exists:
        return None
    data = doc.to_dict()

    # Fetch beats
    beats = []
    beats_ref = db.collection("sessions").document(session_id).collection("beats")
    async for beat_doc in beats_ref.order_by("beat_index").stream():
        beats.append(beat_doc.to_dict())

    return {
        "session_id":  session_id,
        "child_age":   data.get("child_age"),
        "objects":     data.get("objects", []),
        "beat_count":  len(beats),
        "created_at":  data.get("created_at"),
        "beats":       beats,
    }


async def delete_session(session_id: str) -> None:
    """Deletes a session and all its beats (GDPR right to erasure)."""
    db = _get_db()
    # Delete beats subcollection first
    beats_ref = db.collection("sessions").document(session_id).collection("beats")
    async for beat_doc in beats_ref.stream():
        await beat_doc.reference.delete()
    # Delete session document
    await db.collection("sessions").document(session_id).delete()
    logger.info("delete_session: session=%s deleted", session_id[:8])
