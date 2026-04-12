# model_cdn.py
# Generates signed GCS URLs for GGUF model downloads.

import datetime
from google.cloud import storage


async def get_signed_model_url(
    bucket: str,
    blob_name: str,
    expiry_hours: int = 1,
) -> str:
    """
    Returns a signed GCS URL for the given blob, valid for `expiry_hours`.
    The URL allows GET without GCS authentication — required for iOS URLSession download.
    """
    client = storage.Client()
    bucket_obj = client.bucket(bucket)
    blob = bucket_obj.blob(blob_name)

    expiration = datetime.timedelta(hours=expiry_hours)
    url = blob.generate_signed_url(
        version="v4",
        expiration=expiration,
        method="GET",
    )
    return url
