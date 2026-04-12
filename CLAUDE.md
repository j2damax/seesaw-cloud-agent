# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

`seesaw-cloud-agent` is the optional cloud backend for the **SeeSaw wearable AI companion** — a privacy-first interactive storytelling system for children aged 3–8. This service is **Tier 2** of a three-tier architecture:

```
Tier 1: seesaw-companion-ios  (iPhone — always on-device, always private)
Tier 2: seesaw-cloud-agent    (Cloud Run — optional, for enhanced stories)
Tier 3: Gemma 4 fine-tuning   (Vertex AI — model training pipeline)
```

The cloud agent receives **only anonymous labels** (`ScenePayload`) from the iOS app — never pixels, audio, faces, or raw personal data. The privacy boundary is enforced on-device and is non-negotiable.

**Research context:** MSc dissertation — "Privacy-Preserving Edge AI Co-Creative Story Companion". The cloud path is Architecture B in the comparative evaluation (on-device vs. hybrid vs. cloud).

**GitHub:** github.com/j2damax/seesaw-cloud-agent  
**iOS repo:** github.com/j2damax/seesaw-companion-ios (branch: `gemma-4-integration`)  
**Project board:** https://github.com/users/j2damax/projects/4/views/7

## Common Commands

```bash
# Install dependencies
pip install -r requirements.txt

# Run locally
uvicorn app.main:app --reload --port 8080

# Run with environment variables
GEMINI_API_KEY=... SEESAW_API_KEY=... uvicorn app.main:app --reload --port 8080

# Deploy to Cloud Run
gcloud run deploy seesaw-cloud-agent \
  --source . \
  --region europe-west1 \
  --platform managed \
  --allow-unauthenticated \
  --set-secrets GEMINI_API_KEY=GEMINI_API_KEY:latest,SEESAW_API_KEY=SEESAW_API_KEY:latest \
  --memory 1Gi \
  --min-instances 0 \
  --max-instances 3

# Test locally
curl -X POST http://localhost:8080/story/generate \
  -H "Content-Type: application/json" \
  -H "X-SeeSaw-Key: test-key" \
  -d '{"objects":["teddy_bear","book"],"scene":["living_room"],"child_age":5,"child_name":"Vihas"}'

curl http://localhost:8080/health

# Training notebooks (run in order on Colab)
# 1. training/data_prep.ipynb
# 2. training/finetune.ipynb   (requires Vertex AI T4 GPU)
# 3. training/export_gguf.ipynb
```

## Architecture

### Privacy Boundary (Absolute — Do Not Change)

The `ScenePayload` is the **only** data that crosses from device to cloud:

```python
class ScenePayload(BaseModel):
    objects: list[str]        # YOLO label strings — no pixels
    scene: list[str]          # scene classification labels — no pixels
    transcript: str | None    # PII-scrubbed speech — no audio
    child_age: int
    child_name: str           # first name only, parent-provided
    story_history: list[StoryTurn] = []
    session_id: str | None = None
```

**Never log, store, or forward:** raw images, audio buffers, face data, bounding boxes, device identifiers.

### API Contract (Fixed — Matches iOS `CloudAgentService`)

**Do not change field names** — they are hardcoded in the iOS app's `CloudAgentService.swift`:

```
POST /story/generate  →  { story_text, question, is_ending, session_id, beat_index }
GET  /model/latest    →  { download_url, model_version, size_bytes, expires_at }
GET  /health          →  { status, version }
```

Full schema in `docs/API_REFERENCE.md`.

### Stack

- **FastAPI** — HTTP framework, Pydantic v2 validation
- **Google ADK** — `LlmAgent` + `LiteLlm` wrapping Gemini 2.0 Flash
- **Firebase Firestore** — session persistence (Native mode, europe-west2)
- **Cloud Run** — serverless container, min-instances=0, memory=1Gi
- **Cloud Storage** — GGUF model hosting, signed URLs
- **Vertex AI** — Gemma 4 1B LoRA fine-tuning (training pipeline only)

### Directory Layout

```
app/
  main.py              # FastAPI app + middleware
  config.py            # Pydantic Settings (env vars)
  routers/
    story.py           # POST /story/generate
    session.py         # GET/POST /session/{id}
    model.py           # GET /model/latest (signed GCS URL)
    health.py          # GET /health
  agents/
    story_agent.py     # Google ADK LlmAgent + Gemini 2.0 Flash
    safety_agent.py    # ShieldGemma 4 content classifier (post-sprint)
  models/
    scene_payload.py   # Mirrors iOS ScenePayload
    story_beat.py      # Mirrors iOS StoryBeat
  services/
    firestore.py       # Session CRUD
    model_cdn.py       # GCS signed URL generation
training/
  data_prep.ipynb      # TinyStories → SeeSaw format (Colab)
  finetune.ipynb       # Vertex AI LoRA fine-tuning (Colab)
  export_gguf.ipynb    # GGUF Q4_K_M export + validation (Colab)
docs/
  ARCHITECTURE.md      # Full system architecture
  PRIVACY_CONTRACT.md  # What the cloud receives and what it never receives
  API_REFERENCE.md     # Full endpoint schemas with examples
  FINE_TUNING.md       # Gemma 4 fine-tuning pipeline
  DEPLOYMENT.md        # Cloud Run + GCP setup guide
  iOS_Implementation_Guide.md  # Cross-reference to iOS steps 4.1–4.7
  VAD_Research.md      # LLM-assisted semantic turn-taking detection
```

## Key Reference Documents

- `docs/ARCHITECTURE.md` — start here for system overview
- `docs/PRIVACY_CONTRACT.md` — non-negotiable privacy rules
- `docs/API_REFERENCE.md` — exact field names (must match iOS)
- `docs/FINE_TUNING.md` — Gemma 4 training pipeline
- `docs/iOS_Implementation_Guide.md` — master sprint document (Steps 4–6)
- `docs/VAD_Research.md` — semantic turn-taking research findings

## Secrets and Environment

```bash
# Required environment variables (set via Secret Manager on Cloud Run)
GEMINI_API_KEY      # Google AI / Vertex AI key
SEESAW_API_KEY      # Shared secret with iOS app (X-SeeSaw-Key header)
GCS_BUCKET_NAME     # e.g. seesaw-models
FIRESTORE_PROJECT   # GCP project ID
```

## Sprint Task Reference

Current sprint: **T3-001 through T3-023**. See project board at https://github.com/users/j2damax/projects/4/views/7

Day 1 tasks (cloud foundation): T3-001 → T3-009  
Day 2 tasks (Gemma 4 + iOS mode 2): T3-010 → T3-019  
Post-sprint nice-to-have: T3-020 → T3-023

The API contract in `docs/API_REFERENCE.md` is fixed. Validate every implementation decision against `docs/PRIVACY_CONTRACT.md` before writing code.
