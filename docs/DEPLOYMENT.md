# SeeSaw Cloud Agent — Deployment Guide

**Stack:** FastAPI on Cloud Run (europe-west1), Firestore (europe-west2), Cloud Storage (europe-west2)

---

## Deployed Service (T3-001 to T3-003 — completed 2026-04-13)

| Resource | Value |
|---|---|
| **GCP Project** | `seesaw-3e396` |
| **Cloud Run URL** | `https://seesaw-cloud-agent-531853173205.europe-west1.run.app` |
| **Cloud Run region** | `europe-west1` |
| **Service account** | `seesaw-cloud-agent@seesaw-3e396.iam.gserviceaccount.com` |
| **Firestore** | Native mode, `europe-west2`, TTL active on `sessions` collection |
| **GCS buckets** | `gs://seesaw-models`, `gs://seesaw-training-data` (90-day lifecycle) |
| **Gemini model** | `gemini-2.5-flash` (billing enabled — paid tier) |
| **Artifact Registry** | `europe-west1-docker.pkg.dev/seesaw-3e396/cloud-run-source-deploy` |

**iOS app config:** Settings → Cloud Agent URL → `https://seesaw-cloud-agent-531853173205.europe-west1.run.app`

---

## Prerequisites

```bash
# Install Google Cloud CLI
brew install google-cloud-sdk   # macOS
gcloud --version                # verify

# Authenticate
gcloud auth login
gcloud auth application-default login   # required for local Firestore access

# Set project
gcloud config set project seesaw-3e396
```

---

## Day 1: GCP Project Setup (T3-001 to T3-003)

### 1. Enable Required APIs

```bash
gcloud services enable \
  run.googleapis.com \
  firestore.googleapis.com \
  storage.googleapis.com \
  secretmanager.googleapis.com \
  aiplatform.googleapis.com \
  cloudbuild.googleapis.com
```

### 2. Create Service Account

```bash
gcloud iam service-accounts create seesaw-cloud-agent \
  --display-name "SeeSaw Cloud Agent"

# Grant roles
gcloud projects add-iam-policy-binding seesaw-3e396 \
  --member="serviceAccount:seesaw-cloud-agent@seesaw-3e396.iam.gserviceaccount.com" \
  --role="roles/datastore.user"

gcloud projects add-iam-policy-binding seesaw-3e396 \
  --member="serviceAccount:seesaw-cloud-agent@seesaw-3e396.iam.gserviceaccount.com" \
  --role="roles/storage.objectViewer"

gcloud projects add-iam-policy-binding seesaw-3e396 \
  --member="serviceAccount:seesaw-cloud-agent@seesaw-3e396.iam.gserviceaccount.com" \
  --role="roles/secretmanager.secretAccessor"
```

### 3. Provision Firestore

```bash
gcloud firestore databases create \
  --location=europe-west2 \
  --type=firestore-native
```

### 4. Create Cloud Storage Buckets

```bash
gsutil mb -l europe-west2 gs://seesaw-models
gsutil mb -l europe-west2 gs://seesaw-training-data

# Set lifecycle: delete objects older than 90 days from training bucket
cat > /tmp/lifecycle.json << 'EOF'
{
  "rule": [{
    "action": {"type": "Delete"},
    "condition": {"age": 90}
  }]
}
EOF
gsutil lifecycle set /tmp/lifecycle.json gs://seesaw-training-data
```

### 5. Store Secrets in Secret Manager

> **Important:** Use `echo -n` or `printf` to avoid storing a trailing newline in the secret.
> A trailing newline causes silent auth failures in Cloud Run (secret len=65 instead of 64).

```bash
# Gemini API key — must have billing enabled on the project (paid tier required)
# gemini-2.0-flash and gemini-2.0-flash-lite are deprecated for new users — use gemini-2.5-flash
echo -n "YOUR_GEMINI_API_KEY" | gcloud secrets create GEMINI_API_KEY \
  --data-file=- --replication-policy=automatic

# SeeSaw shared API key — strip newline explicitly
openssl rand -hex 32 | tr -d '\n' | gcloud secrets create SEESAW_API_KEY \
  --data-file=- --replication-policy=automatic

# To update an existing secret version:
echo -n "NEW_VALUE" | gcloud secrets versions add GEMINI_API_KEY --data-file=-
```

### 6. Firestore TTL Index (Data Retention)

```bash
# Sessions auto-delete after 30 days
gcloud firestore fields ttls update ttl \
  --collection-group=sessions \
  --enable-ttl
```

---

## Local Development (T3-002)

```bash
# Setup venv
cd /path/to/seesaw-cloud-agent
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# Create .env (already gitignored)
cat > .env << 'EOF'
GEMINI_API_KEY=your-gemini-key
SEESAW_API_KEY=your-seesaw-key
GCS_BUCKET_NAME=seesaw-models
FIRESTORE_PROJECT=seesaw-3e396
EOF

# ADC is required for local Firestore access
gcloud auth application-default login

# Run
python -m uvicorn app.main:app --reload --port 8080

# Test health
curl http://localhost:8080/health

# Test story generation
curl -X POST http://localhost:8080/story/generate \
  -H "Content-Type: application/json" \
  -H "X-SeeSaw-Key: your-seesaw-key" \
  -d '{
    "objects": ["teddy_bear", "book", "sofa"],
    "scene": ["living_room"],
    "child_age": 5,
    "child_name": "Vihas"
  }'
```

### Known Dependency Notes (Python 3.14 + google-adk 0.2.0)

- `uvicorn` must be `>=0.34.0` (google-adk requires it; original pin of 0.30.0 conflicts)
- `deprecated` and `litellm` must be added explicitly — not pulled in by google-adk on Python 3.14
- google-adk 0.2.0 uses `Runner` + `InMemorySessionService` pattern; `agent.run_async(user_message=...)` is removed

---

## Deploy to Cloud Run (T3-003)

```bash
# Deploy (builds container using Cloud Build automatically)
gcloud run deploy seesaw-cloud-agent \
  --source . \
  --region europe-west1 \
  --platform managed \
  --allow-unauthenticated \
  --service-account seesaw-cloud-agent@seesaw-3e396.iam.gserviceaccount.com \
  --set-secrets GEMINI_API_KEY=GEMINI_API_KEY:latest,SEESAW_API_KEY=SEESAW_API_KEY:latest \
  --set-env-vars GCS_BUCKET_NAME=seesaw-models,FIRESTORE_PROJECT=seesaw-3e396 \
  --memory 1Gi \
  --cpu 1 \
  --min-instances 0 \
  --max-instances 3 \
  --timeout 60

# Get the Cloud Run URL
gcloud run services describe seesaw-cloud-agent \
  --region europe-west1 \
  --format "value(status.url)"
```

---

## Post-Deploy Verification

**Verified: 2026-04-13** — all four checks pass against the live Cloud Run service (revision `seesaw-cloud-agent-00005-497`).

```bash
export CLOUD_URL="https://seesaw-cloud-agent-531853173205.europe-west1.run.app"
export API_KEY="$(gcloud secrets versions access latest --secret=SEESAW_API_KEY)"

# 1. Health check
curl $CLOUD_URL/health
```
```json
{"status":"ok","version":"1.0.0"}
```

```bash
# 2. Auth rejection (wrong key)
curl -s -X POST $CLOUD_URL/story/generate \
  -H "Content-Type: application/json" \
  -H "X-SeeSaw-Key: wrong-key" \
  -d '{"objects":["teddy_bear"],"scene":["living_room"],"child_age":5,"child_name":"Vihas"}'
```
```json
{"error":"Unauthorized"}
```

```bash
# 3. Story generation (full end-to-end)
curl -s -X POST $CLOUD_URL/story/generate \
  -H "Content-Type: application/json" \
  -H "X-SeeSaw-Key: $API_KEY" \
  -d '{"objects":["teddy_bear","book"],"scene":["living_room"],"child_age":5,"child_name":"Vihas"}'
```
```json
{
  "story_text": "Vihas, you're in the cozy living room, and guess who's waiting for you? Your soft teddy bear is sitting right there, looking so comfy! It seems like the teddy bear has found a wonderful book, just perfect for an afternoon adventure together.",
  "question": "What kind of story do you think the teddy bear wants to read, Vihas?",
  "is_ending": false,
  "session_id": "7f33b5bd-b6d7-48e6-afcc-f44ac36cd6c3",
  "beat_index": 0
}
```

```bash
# 4. Model URL (returns signed GCS URL + metadata)
curl -s $CLOUD_URL/model/latest -H "X-SeeSaw-Key: $API_KEY"
```
```json
{
  "download_url": "https://storage.googleapis.com/seesaw-models/seesaw-gemma3-1b-q4km.gguf?X-Goog-Algorithm=...",
  "model_version": "1.0.0",
  "size_bytes": 814261088,
  "expires_at": "2026-04-13T14:24:03Z"
}
```

| Check | Status |
|---|---|
| `GET /health` | Pass |
| Wrong API key → `{"error":"Unauthorized"}` | Pass |
| `POST /story/generate` → full story beat + Firestore session written | Pass |
| `GET /model/latest` → signed GCS URL, `size_bytes=814261088` | Pass |

---

## Monitoring

```bash
# View Cloud Run logs
gcloud logging read \
  "resource.type=cloud_run_revision AND resource.labels.service_name=seesaw-cloud-agent" \
  --limit=50 \
  --format="table(timestamp,textPayload)"

# View error logs only
gcloud logging read \
  "resource.type=cloud_run_revision AND severity>=ERROR" \
  --limit=20
```

---

## iOS Configuration (T3-008)

After Cloud Run is deployed and verified:

1. Open the iOS SeeSaw app
2. Go to Settings
3. Set **Story Mode** to "Cloud"
4. Set **Cloud Agent URL** to `https://seesaw-cloud-agent-531853173205.europe-west1.run.app`
5. Set **Cloud Agent Key** to the value of `SEESAW_API_KEY` from Secret Manager
6. Capture a scene and tap "Generate Story"
7. Verify a story plays — check Cloud Run logs and Firestore console

---

## Environment Variables Reference

| Variable | Source | Value |
|----------|--------|-------|
| `GEMINI_API_KEY` | Secret Manager | Gemini API key (billing-enabled, paid tier) |
| `SEESAW_API_KEY` | Secret Manager | 64-char hex shared secret (no trailing newline) |
| `GCS_BUCKET_NAME` | Cloud Run env | `seesaw-models` |
| `FIRESTORE_PROJECT` | Cloud Run env | `seesaw-3e396` |

---

## Troubleshooting

### 401 Unauthorized on all authenticated endpoints
**Cause:** `SEESAW_API_KEY` secret was stored with a trailing newline (common when using `openssl rand | gcloud secrets create` without `tr -d '\n'`), making the stored value 65 bytes instead of 64.  
**Fix:**
```bash
gcloud secrets versions access latest --secret=SEESAW_API_KEY | tr -d '\n' | \
  gcloud secrets versions add SEESAW_API_KEY --data-file=-
```

### 503 `Model URL generation failed` on `GET /model/latest`
**Cause:** `generate_signed_url` on Cloud Run fails with `you need a private key to sign credentials` because Compute Engine credentials are token-only.  
**Fix (code):** Pass `service_account_email` + `access_token` to `generate_signed_url` so it uses the IAM `signBlob` API (already applied in `app/services/model_cdn.py`).  
**Fix (IAM):** Grant the service account `roles/iam.serviceAccountTokenCreator` on itself:
```bash
gcloud iam service-accounts add-iam-policy-binding \
  seesaw-cloud-agent@seesaw-3e396.iam.gserviceaccount.com \
  --member="serviceAccount:seesaw-cloud-agent@seesaw-3e396.iam.gserviceaccount.com" \
  --role="roles/iam.serviceAccountTokenCreator"
```

### 404 model not found
**Cause:** `gemini-2.0-flash` and `gemini-2.0-flash-lite` are deprecated for new API users.  
**Fix:** Use `gemini-2.5-flash` in `app/agents/story_agent.py`.

### 429 quota exceeded
**Cause:** Gemini API free-tier daily quota exhausted. Free-tier keys are project-scoped and don't benefit from enabling billing after the key was created.  
**Fix:** Create a new API key at aistudio.google.com/app/apikey after billing is enabled, or wait for quota reset at midnight UTC.

### ADK `run_async() got unexpected keyword argument 'user_message'`
**Cause:** google-adk 0.2.0 removed the `agent.run_async(user_message=...)` shorthand.  
**Fix:** Use `Runner` + `InMemorySessionService` pattern (see `app/agents/story_agent.py`).

---

## Cost Estimate

| Service | Usage | Monthly cost |
|---------|-------|-------------|
| Cloud Run | 100 requests/day, 1Gi, 1 CPU | ~$0–$2 |
| Firestore | 1,000 reads + 500 writes/day | ~$0 (free tier) |
| Cloud Storage | 2 GB stored (GGUF model) | ~$0.05 |
| Gemini API | 100 requests/day @ $0.075/1M tokens | ~$0.05 |
| **Total** | | **< $5/month** |

Research prototype — no production SLA required.

