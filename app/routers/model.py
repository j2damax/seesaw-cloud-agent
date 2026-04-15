# model.py — GET /model/latest
# Returns a signed GCS URL for the Gemma 4 GGUF model download.
# Called by the iOS ModelDownloadManager.

import logging
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, HTTPException
from app.services.model_cdn import get_signed_model_url
from app.config import settings

logger = logging.getLogger(__name__)
router = APIRouter()

MODEL_FILENAME   = "seesaw-gemma3-1b-q8_0.gguf"
MODEL_VERSION    = "1.0.2"
MODEL_SIZE_BYTES = 1_077_509_216   # 1028 MB — measured from gs://seesaw-models/seesaw-gemma3-1b-q8_0.gguf
URL_EXPIRY_HOURS = 1


@router.get("/latest")
async def model_latest():
    """
    Returns a signed GCS URL for the Gemma 4 GGUF model.
    URL expires in 1 hour — iOS ModelDownloadManager must start the download promptly.
    """
    try:
        signed_url = await get_signed_model_url(
            bucket=settings.gcs_bucket_name,
            blob_name=MODEL_FILENAME,
            expiry_hours=URL_EXPIRY_HOURS,
        )
    except Exception as exc:
        logger.error("model_latest: GCS signing failed: %s", exc)
        raise HTTPException(status_code=503, detail="Model URL generation failed")

    expires_at = datetime.now(timezone.utc) + timedelta(hours=URL_EXPIRY_HOURS)

    return {
        "download_url":   signed_url,
        "model_version":  MODEL_VERSION,
        "size_bytes":     MODEL_SIZE_BYTES,
        "expires_at":     expires_at.isoformat().replace("+00:00", "Z"),
    }
