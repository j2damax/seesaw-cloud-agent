# model_cdn.py
# Generates signed GCS URLs for GGUF model downloads.
#
# On Cloud Run, the default credentials are Compute Engine token-based credentials
# that cannot self-sign.  We refresh them and pass service_account_email + access_token
# so generate_signed_url uses the IAM signBlob API instead of a local private key.
# Requires: roles/iam.serviceAccountTokenCreator granted to the service account on itself.

import datetime
import google.auth
from google.auth.transport.requests import Request as GoogleAuthRequest
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
    credentials, _ = google.auth.default(
        scopes=["https://www.googleapis.com/auth/cloud-platform"]
    )
    credentials.refresh(GoogleAuthRequest())

    client = storage.Client(credentials=credentials)
    bucket_obj = client.bucket(bucket)
    blob = bucket_obj.blob(blob_name)

    expiration = datetime.timedelta(hours=expiry_hours)
    url = blob.generate_signed_url(
        version="v4",
        expiration=expiration,
        method="GET",
        service_account_email=credentials.service_account_email,
        access_token=credentials.token,
    )
    return url
