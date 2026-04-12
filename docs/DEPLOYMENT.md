# SeeSaw Cloud Agent — Deployment Guide

**Stack:** FastAPI on Cloud Run (europe-west1), Firestore (europe-west2), Cloud Storage (europe-west2)

---

## Prerequisites

```bash
# Install Google Cloud CLI
brew install google-cloud-sdk   # macOS
gcloud --version                # verify

# Authenticate
gcloud auth login
gcloud auth application-default login

# Set project
gcloud config set project seesaw-research
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
gcloud projects add-iam-policy-binding seesaw-research \
  --member="serviceAccount:seesaw-cloud-agent@seesaw-research.iam.gserviceaccount.com" \
  --role="roles/datastore.user"

gcloud projects add-iam-policy-binding seesaw-research \
  --member="serviceAccount:seesaw-cloud-agent@seesaw-research.iam.gserviceaccount.com" \
  --role="roles/storage.objectViewer"

gcloud projects add-iam-policy-binding seesaw-research \
  --member="serviceAccount:seesaw-cloud-agent@seesaw-research.iam.gserviceaccount.com" \
  --role="roles/secretmanager.secretAccessor"
```

### 3. Provision Firestore

```bash
gcloud firestore databases create \
  --location=europe-west2 \
  --type=firestore-native
```

### 4. Create Cloud Storage Bucket

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

```bash
# Gemini API key (from https://aistudio.google.com/app/apikey)
echo -n "YOUR_GEMINI_API_KEY" | gcloud secrets create GEMINI_API_KEY \
  --data-file=- --replication-policy=automatic

# SeeSaw shared API key (generate a random string)
openssl rand -hex 32 | gcloud secrets create SEESAW_API_KEY \
  --data-file=- --replication-policy=automatic
```

---

## Local Development

```bash
# Clone and setup
cd /Users/jayampathyicloud.com/SeeSaw/code/seesaw-cloud-agent
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# Set environment variables
export GEMINI_API_KEY="your-key"
export SEESAW_API_KEY="your-secret"
export GCS_BUCKET_NAME="seesaw-models"
export FIRESTORE_PROJECT="seesaw-research"

# Run
uvicorn app.main:app --reload --port 8080

# Test health
curl http://localhost:8080/health

# Test story generation
curl -X POST http://localhost:8080/story/generate \
  -H "Content-Type: application/json" \
  -H "X-SeeSaw-Key: your-secret" \
  -d '{
    "objects": ["teddy_bear", "book", "sofa"],
    "scene": ["living_room"],
    "child_age": 5,
    "child_name": "Vihas"
  }'
```

---

## Deploy to Cloud Run

```bash
# Deploy (builds container using Cloud Build automatically)
gcloud run deploy seesaw-cloud-agent \
  --source . \
  --region europe-west1 \
  --platform managed \
  --allow-unauthenticated \
  --service-account seesaw-cloud-agent@seesaw-research.iam.gserviceaccount.com \
  --set-secrets GEMINI_API_KEY=GEMINI_API_KEY:latest,SEESAW_API_KEY=SEESAW_API_KEY:latest \
  --set-env-vars GCS_BUCKET_NAME=seesaw-models,FIRESTORE_PROJECT=seesaw-research \
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

The URL will be like: `https://seesaw-cloud-agent-abc123-ew.a.run.app`

**Set this URL in the iOS app:** Settings → Cloud Agent URL

---

## Post-Deploy Verification

```bash
export CLOUD_URL="https://seesaw-cloud-agent-abc123-ew.a.run.app"
export API_KEY="your-secret"  # from Secret Manager

# Health check
curl $CLOUD_URL/health

# Story generation (full end-to-end)
curl -X POST $CLOUD_URL/story/generate \
  -H "Content-Type: application/json" \
  -H "X-SeeSaw-Key: $API_KEY" \
  -d '{"objects":["teddy_bear"],"scene":["living_room"],"child_age":5,"child_name":"Vihas"}'
```

---

## Firestore TTL Index (Data Retention)

Create a TTL policy so sessions auto-delete after 30 days:

```bash
gcloud firestore fields ttls update ttl \
  --collection-group=sessions \
  --enable-ttl
```

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
4. Set **Cloud Agent URL** to your Cloud Run URL
5. (Optional) Set **Cloud Agent Key** to your `SEESAW_API_KEY`
6. Capture a scene and tap "Generate Story"
7. Verify a story plays — check Cloud Run logs and Firestore console

---

## Environment Variables Reference

| Variable | Source | Example |
|----------|--------|---------|
| `GEMINI_API_KEY` | Secret Manager | `AIzaSy...` |
| `SEESAW_API_KEY` | Secret Manager | `a3f9b2c1...` (64 hex chars) |
| `GCS_BUCKET_NAME` | Cloud Run env | `seesaw-models` |
| `FIRESTORE_PROJECT` | Cloud Run env | `seesaw-research` |

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
