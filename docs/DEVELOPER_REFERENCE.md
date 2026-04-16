# SeeSaw Cloud Agent — Complete Developer Reference

**Project:** Privacy-Preserving Edge AI Co-Creative Story Companion  
**Tier:** 2 of 3 — Cloud Backend (Architecture B in the MSc comparative evaluation)  
**Author:** Jayampathy Balasuriya  
**Dissertation:** MSc — "Privacy-Preserving Edge AI Co-Creative Story Companion"  
**Status:** Deployed and verified — 2026-04-13  
**Live URL:** `https://seesaw-cloud-agent-531853173205.europe-west1.run.app`

---

## Table of Contents

1. [Project Context](#1-project-context)
2. [System Architecture](#2-system-architecture)
3. [Implementation Deep-Dive](#3-implementation-deep-dive)
4. [Privacy Architecture](#4-privacy-architecture)
5. [Fine-Tuning Pipeline (Tier 3)](#5-fine-tuning-pipeline-tier-3)
6. [Test Suite](#6-test-suite)
7. [Step-by-Step Setup Guide](#7-step-by-step-setup-guide)
8. [Deployment Verification](#8-deployment-verification)
9. [API Reference](#9-api-reference)
10. [Monitoring and Operations](#10-monitoring-and-operations)
11. [Troubleshooting Reference](#11-troubleshooting-reference)
12. [Known Limitations](#12-known-limitations)
13. [Learnings and Engineering Decisions](#13-learnings-and-engineering-decisions)
14. [Future Work](#14-future-work)
15. [MSc Thesis, Presentation and Viva Guide](#15-msc-thesis-presentation-and-viva-guide)

---

## 1. Project Context

### What SeeSaw Is

SeeSaw is a wearable AI companion for children aged 3–8. A child wears a device (or uses an iPhone) that sees the world through a camera. The device detects objects in the child's environment (teddy bears, books, crayons) and uses an AI model to weave those objects into an interactive, personalised story. The child participates — they answer questions, their spoken words shape the narrative.

The entire system is built with one inviolable constraint: **raw media never leaves the device**. No pixels, no audio, no faces — ever.

### Three-Tier Architecture

```
Tier 1: seesaw-companion-ios     (iPhone — always on-device, always private)
Tier 2: seesaw-cloud-agent       (Cloud Run — THIS REPO — optional, enhanced stories)
Tier 3: Gemma fine-tuning        (Vertex AI — model training pipeline)
```

### Three Story Architectures (Comparative Evaluation)

The MSc dissertation evaluates three architectures side-by-side:

| Architecture | Engine | Network | Raw Data Sent |
|---|---|---|---|
| **A — On-Device** | Apple Foundation Models 3B (Neural Engine) | No | No |
| **B — Cloud (this repo)** | Gemini 2.5 Flash via Cloud Run | Yes | No |
| **C — Gemma On-Device** | Fine-tuned Gemma 3 1B GGUF via MediaPipe | No (after download) | No |

**Research question:** Can a fully on-device model (Architecture A or C) match cloud-quality stories (Architecture B) while transmitting zero PII?

**Null hypothesis H₀:** Architecture A produces story beats rated statistically equivalent in quality to B and C, while transmitting zero PII.

### Repository Map

| Repo | Purpose |
|---|---|
| `github.com/j2damax/seesaw-cloud-agent` | This repo — cloud backend |
| `github.com/j2damax/seesaw-companion-ios` (branch: `gemma-4-integration`) | iOS app — all three architectures |
| `github.com/j2damax/seesaw-yolo-model` | Custom YOLO11n 44-class object detection |
| Project board | https://github.com/users/j2damax/projects/4/views/7 |

---

## 2. System Architecture

### End-to-End Data Flow

```
[Child's environment]
        │
        ▼
┌─────────────────────────────────────────────────────┐
│  iPhone — Six-Stage Privacy Pipeline                │
│                                                     │
│  1. VNDetectFaceRectanglesRequest → face boxes      │
│  2. CIGaussianBlur σ≥30           → blurred frame   │
│  3. YOLO11n CoreML (44 classes)   → object labels   │
│  4. VNClassifyImageRequest        → scene labels    │
│  5. SFSpeechRecognizer (on-device) → raw transcript │
│  6. PIIScrubber (regex)           → scrubbed text   │
│                                                     │
│  Raw data: allocated → processed → discarded        │
│  Output:  ScenePayload (labels + scrubbed text)     │
└─────────────────┬───────────────────────────────────┘
                  │ POST /story/generate
                  │ Header: X-SeeSaw-Key
                  │ Body: ScenePayload JSON
                  ▼
┌─────────────────────────────────────────────────────┐
│  Cloud Run — seesaw-cloud-agent (THIS REPO)         │
│                                                     │
│  FastAPI                                            │
│    ↓ verify_api_key middleware                      │
│    ↓ Pydantic ScenePayload validation               │
│    ↓ story_agent.py                                 │
│       Google ADK LlmAgent                          │
│       LiteLlm → Gemini 2.5 Flash                   │
│       build_user_prompt()                          │
│       parse JSON response                           │
│    ↓ firestore.py (session + beat persistence)      │
│    → StoryBeatResponse JSON                         │
│                                                     │
│  Also: GET /model/latest → signed GCS URL          │
└─────────────────┬───────────────────────────────────┘
                  │ training artifacts
                  ▼
┌─────────────────────────────────────────────────────┐
│  Vertex AI — Fine-Tuning Pipeline (Tier 3)          │
│                                                     │
│  TinyStories + iOS beats → data_prep.ipynb          │
│  → finetune.ipynb (LoRA, T4, ~27 min, ~$6)         │
│  → export_gguf.ipynb (Q8_0 GGUF, ~1 GB)            │
│  → gs://seesaw-models/seesaw-gemma3-1b-q8_0.gguf   │
└─────────────────────────────────────────────────────┘
```

### Cloud Agent Directory Layout

```
seesaw-cloud-agent/
├── app/
│   ├── main.py              # FastAPI app + CORS + API key middleware
│   ├── config.py            # Pydantic Settings (env vars / Secret Manager)
│   ├── routers/
│   │   ├── story.py         # POST /story/generate  ← primary endpoint
│   │   ├── session.py       # GET/DELETE /session/{id}
│   │   ├── model.py         # GET /model/latest (signed GCS URL)
│   │   └── health.py        # GET /health (unauthenticated)
│   ├── agents/
│   │   └── story_agent.py   # Google ADK LlmAgent + Gemini 2.5 Flash
│   ├── models/
│   │   ├── scene_payload.py # Input model — mirrors iOS ScenePayload exactly
│   │   └── story_beat.py    # Output model — mirrors iOS StoryBeatResponse
│   └── services/
│       ├── firestore.py     # Session CRUD + beat subcollection
│       └── model_cdn.py     # GCS V4 signed URL generation
├── tests/
│   ├── conftest.py          # Fixtures, mocks, TestClient
│   ├── test_health.py       # 3 tests
│   ├── test_story.py        # 13 tests
│   ├── test_session.py      # 6 tests
│   ├── test_auth.py         # 5 tests
│   ├── test_model.py        # 5 tests
│   ├── test_privacy.py      # 6 tests
│   └── test_live.py         # live smoke tests (opt-in, hit real Cloud Run)
├── training/
│   ├── data_prep.ipynb      # TinyStories + iOS beat preparation (Colab)
│   ├── finetune.ipynb       # LoRA fine-tuning on Vertex AI T4
│   └── export_gguf.ipynb    # GGUF export + GCS upload
├── docs/                    # All reference documentation
├── Dockerfile               # python:3.12-slim, port 8080
├── requirements.txt         # Runtime dependencies
├── requirements-test.txt    # Test dependencies
└── pytest.ini               # asyncio_mode=auto, live marker
```

### GCP Infrastructure

| Service | Purpose | Region |
|---|---|---|
| Cloud Run | FastAPI container (serverless) | europe-west1 |
| Firestore (Native) | Session + beat persistence | europe-west2 |
| Cloud Storage | GGUF model hosting | europe-west2 |
| Secret Manager | API keys (no env file in prod) | europe-west1 |
| Artifact Registry | Container images | europe-west1 |
| Vertex AI | Gemma 3 LoRA fine-tuning | us-central1 |

---

## 3. Implementation Deep-Dive

### 3.1 FastAPI Application (`app/main.py`)

The entry point configures three concerns:

**CORS middleware** — allows iOS app requests from any origin. No browser clients exist in production; this is purely for iOS `URLSession` compatibility.

**API key middleware** — every request except `GET /health` must carry `X-SeeSaw-Key` matching the `SEESAW_API_KEY` environment variable. The middleware fires before routers, so no route logic runs for unauthenticated requests. Health is excluded so Cloud Run's liveness probe works without credentials.

**Router registration** — four routers at `/story`, `/session`, `/model`, and root level (`/health`).

```python
# The middleware check — runs on every non-health request
@app.middleware("http")
async def verify_api_key(request: Request, call_next):
    if request.url.path != "/health":
        provided_key = request.headers.get("X-SeeSaw-Key", "")
        if provided_key != settings.seesaw_api_key:
            return JSONResponse({"error": "Unauthorized"}, status_code=401)
    return await call_next(request)
```

### 3.2 Configuration (`app/config.py`)

`pydantic-settings` `BaseSettings` reads from environment variables first, then falls back to `.env`. All secrets are injected by Cloud Run from Secret Manager — the `.env` file is only used locally and is gitignored.

```python
class Settings(BaseSettings):
    gemini_api_key: str = ""
    seesaw_api_key: str = ""
    gcs_bucket_name: str = "seesaw-models"
    firestore_project: str = ""
    app_version: str = "1.0.0"
```

### 3.3 Input/Output Models

**`ScenePayload`** (`app/models/scene_payload.py`) mirrors the iOS `CloudAgentService` request struct exactly. Field names cannot change without coordinating an iOS app update.

```python
class StoryTurn(BaseModel):
    role: str    # "model" or "user"
    text: str

class ScenePayload(BaseModel):
    objects: list[str]               # YOLO label strings — no pixels
    scene: list[str]                 # scene classification labels
    transcript: str | None           # PII-scrubbed speech
    child_age: int                   # validated: 2 ≤ age ≤ 12
    child_name: str                  # validated: 1–50 chars
    story_history: list[StoryTurn]   # rolling conversation context
    session_id: str | None = None    # UUID; generated server-side if omitted
```

**`StoryBeatResponse`** (`app/models/story_beat.py`) mirrors the iOS `StoryResponse` Codable struct. iOS uses `.convertFromSnakeCase` key decoding, so `story_text` → `storyText`, `beat_index` → `beatIndex` etc.

```python
class StoryBeatResponse(BaseModel):
    story_text: str    # 2–3 sentences, 40–80 words
    question: str      # one open-ended question, max 15 words
    is_ending: bool    # true on final beat or warm conclusion
    session_id: str    # echoed or newly generated UUID
    beat_index: int    # 0-indexed turn counter
```

### 3.4 Story Router (`app/routers/story.py`)

The primary endpoint. Key behaviours:

**Session management** — if `session_id` is absent from the request, a new UUID is generated. The session ID is then echoed in the response, enabling iOS to send it back on subsequent turns for continuity.

**Turn counting** — `get_beat_count()` queries Firestore before calling the agent. This determines `beat_index` and whether this is the final beat (when `beat_index >= MAX_TURNS - 1`, i.e., turn 7 of 0–7).

**Final beat signalling** — when `is_final_beat=True` is passed to the agent, the system prompt instructs Gemini to bring the story to a warm conclusion, and `is_ending` is forced to `True` regardless of what the model returns.

**Privacy logging** — only the first 8 characters of the session ID are logged (pseudonymity). Object/scene counts are logged, but not their values. Transcript and child name are never logged.

**Firestore writes** — `create_session()` stores `child_age`, `objects`, `scene` only. `append_beat()` stores the generated story text. Transcript and child name are never persisted.

```python
MAX_TURNS = 8   # beat_index 0–7; final beat at index 7

@router.post("/generate", response_model=StoryBeatResponse)
async def generate_story(payload: ScenePayload):
    session_id = payload.session_id or str(uuid.uuid4())
    beat_index = await get_beat_count(session_id)
    is_final_beat = beat_index >= MAX_TURNS - 1
    # ... agent call, firestore write ...
```

### 3.5 Story Agent (`app/agents/story_agent.py`)

The agent uses Google ADK's `LlmAgent` backed by `LiteLlm` calling `gemini/gemini-2.5-flash`.

**System prompt** (`STORY_SYSTEM_PROMPT`) defines the "Whisper" persona: a gentle storytelling companion that speaks directly _with_ the child (second-person "you"), uses the child's name only for praise, never mentions technology or cameras, and always outputs strict JSON.

**Prompt construction** (`build_user_prompt`) assembles a context string from:
- Child name and age
- Objects visible (YOLO labels)
- Scene classification
- Child's last speech (if any)
- Rolling 6-turn story history window
- Final beat instruction (if applicable)

**Session isolation** — each call creates a fresh `InMemorySessionService` session with a new UUID. There is no state leakage between concurrent requests.

**JSON parsing** — the model is instructed to output only JSON. The parser strips accidental markdown code fences (` ```json ... ``` `) and provides a fallback question if `question` is missing.

```python
# Model and runner setup — stateless per-request
_story_agent = LlmAgent(
    name="seesaw_story_agent",
    model=LiteLlm(model="gemini/gemini-2.5-flash"),
    instruction=STORY_SYSTEM_PROMPT,
)
_runner = Runner(app_name="seesaw", agent=_story_agent, session_service=_session_service)
```

### 3.6 Firestore Service (`app/services/firestore.py`)

**Schema:**
```
sessions/{session_id}
  child_age:  int
  objects:    [str]
  scene:      [str]
  created_at: timestamp
  ttl:        timestamp (30 days from creation — auto-deleted by TTL policy)
  
  beats/{beat_index}
    beat_index: int
    story_text: str
    question:   str
    is_ending:  bool
    timestamp:  timestamp
```

**Key operations:**
- `create_session()` — uses `merge=True` so re-sending the same session ID doesn't overwrite existing beats
- `get_beat_count()` — streams the beats subcollection and counts documents (avoids loading all data)
- `delete_session()` — deletes beats subcollection first, then the session document (Firestore does not cascade-delete subcollections)
- `get_session()` — orders beats by `beat_index` for correct display order

**Client lifecycle** — `AsyncClient` is lazily initialised as a module-level singleton. This avoids creating a new Firestore connection on every request.

### 3.7 Model CDN Service (`app/services/model_cdn.py`)

Generates V4 signed GCS URLs for the GGUF model download. This required a non-obvious workaround for Cloud Run.

**The problem:** The standard `blob.generate_signed_url()` call requires a private key to sign the URL. Cloud Run uses Compute Engine token-based credentials, which do not have a private key available. The default call raises `you need a private key to sign credentials`.

**The solution:** Refresh the credentials to get an access token, then pass both `service_account_email` and `access_token` to `generate_signed_url()`. This causes the library to use the IAM `signBlob` API (an HTTP call) instead of local RSA signing. This requires granting `roles/iam.serviceAccountTokenCreator` to the service account on itself (see Section 11).

```python
credentials, _ = google.auth.default(
    scopes=["https://www.googleapis.com/auth/cloud-platform"]
)
credentials.refresh(GoogleAuthRequest())

url = blob.generate_signed_url(
    version="v4",
    expiration=datetime.timedelta(hours=expiry_hours),
    method="GET",
    service_account_email=credentials.service_account_email,
    access_token=credentials.token,   # ← forces IAM signBlob path
)
```

---

## 4. Privacy Architecture

### The Core Invariant

```
∀ session s: s.rawDataTransmitted == false
```

This is not a policy — it is an architectural constraint. The iOS `CloudAgentService` only sends `ScenePayload`, a struct of label strings and scrubbed text. The code path to transmit raw pixels or audio does not exist.

### Six-Stage iOS Privacy Pipeline

| Stage | Technology | Output |
|---|---|---|
| 1. Face Detection | `VNDetectFaceRectanglesRequest` | Bounding boxes |
| 2. Face Blur | `CIGaussianBlur` σ≥30 | Blurred JPEG |
| 3. Object Detection | YOLO11n CoreML (44 classes) | Label strings only |
| 4. Scene Classification | `VNClassifyImageRequest` | Scene category strings |
| 5. Speech-to-Text | `SFSpeechRecognizer` (on-device) | Raw transcript |
| 6. PII Scrubbing | `PIIScrubber` regex patterns | Redacted transcript |

Raw data (JPEG frames, audio buffers) is allocated in memory, processed, and discarded. It is never written to disk or network.

### What the Cloud Receives vs. What It Never Receives

| Field | What It Is | What It Is NOT |
|---|---|---|
| `objects` | YOLO class label strings | Pixel coords, crops, face embeddings |
| `scene` | VNClassify category strings | Frames, video, depth maps |
| `transcript` | PIIScrubber-redacted text | Raw audio, unredacted speech |
| `child_age` | Integer | Birthdate |
| `child_name` | First name (parent-entered) | Full name, family name |
| `session_id` | UUID (generated per session) | Device ID, Apple ID, IP address |

**Never transmitted (verifiable by iOS code audit):** raw JPEG/pixel buffers, PCM/AAC audio, face bounding boxes, device identifiers (IDFA/IDFV), IP address (not logged server-side), unredacted transcripts.

### Server-Side Privacy Enforcement

**Firestore storage** — transcript and child_name are never written. Only `objects`, `scene`, `child_age`, and generated story text are stored.

**Logging** — session IDs are truncated to 8 characters. Transcript content and child names are never logged (enforced and tested in `test_privacy.py`).

**Retention** — 30-day TTL on all session documents (Firestore TTL policy on `ttl` field).

**GDPR right to erasure** — `DELETE /session/{id}` deletes all beats and the session document. Response is idempotent (200 even for non-existent sessions).

### Auditability

- `StorySessionRecord.rawDataTransmitted: Bool` is hardcoded `false` in iOS — visible in the Story Timeline UI
- `StorySessionRecord.totalPiiTokensRedacted: Int` counts PII events per session
- Privacy contract tests in `tests/test_privacy.py` structurally verify these guarantees

### Compliance

| Regulation | How It Is Met |
|---|---|
| GDPR Art.5(1)(c) data minimisation | Only semantic labels transmitted |
| GDPR right to erasure | `DELETE /session/{id}` endpoint |
| GDPR data residency | Cloud Run europe-west1, Firestore europe-west2 |
| COPPA under-13 | No persistent child identifiers, session UUIDs only |
| COPPA §312.3 | No behavioural advertising, no third-party data sharing |

---

## 5. Fine-Tuning Pipeline (Tier 3)

### Overview

Tier 3 produces a Gemma 3 1B model fine-tuned for children's storytelling. It is served via `GET /model/latest` as a GGUF file for iOS on-device inference (Architecture C).

### Dataset Preparation (`training/data_prep.ipynb`)

| Source | Count | Purpose |
|---|---|---|
| `roneneldan/TinyStories` (HuggingFace) | 12,000 sampled → ~8,000 after filtering | Base story fluency |
| `StoryBeatRecord` exports from iOS app | ~125 records × 5 (weighted upsampling) | Domain-specific gold examples |

Safety filtering removes violent, horror, or adult-themed stories before training.

All examples are formatted into Gemma 3 chat template:
```
<start_of_turn>user
{scene context}\n<end_of_turn>
<start_of_turn>model
{"story_text": "...", "question": "...", "is_ending": false}<end_of_turn>
```

Output: 8,000-example JSONL uploaded to `gs://seesaw-models/training-data/seesaw_beats_train.jsonl`.

### Fine-Tuning Configuration (`training/finetune.ipynb`)

| Parameter | Value |
|---|---|
| Base model | `google/gemma-3-1b-it` (HuggingFace) |
| Method | LoRA (PEFT 0.14) |
| LoRA r | 16 |
| LoRA alpha | 32 |
| Target modules | q, k, v, o projections |
| Trainable parameters | ~8M / 1B (~0.8%) |
| Hardware | Vertex AI custom job, NVIDIA T4 GPU |
| Epochs | 3 |
| Batch size | 4 × grad_accum=4 (effective batch=16) |
| Learning rate | 2e-4, cosine schedule, 5% warmup |
| Training time | ~27 minutes |
| Cost | ~$6 USD |

### Training Metrics

| Epoch | Training Loss | Validation Loss |
|---|---|---|
| 1 | 0.5126 | 0.5115 |
| 2 | 0.4769 | 0.4960 |
| 3 | 0.4687 | **0.4945** |

Train/validation losses track closely — no overfitting. Best model loaded at epoch 3 checkpoint.  
Target threshold: < 1.5. Achieved: **0.4945** (well within target).

### GGUF Export (`training/export_gguf.ipynb`)

```
gs://seesaw-models/checkpoints/seesaw-gemma3-v1/
  ↓ PEFT merge_and_unload() — merge LoRA adapters into base weights
  ↓ llama.cpp b8777 convert_hf_to_gguf.py (with Gemma 3 architecture patches)
  ↓ llama-quantize Q8_0  ← NOT Q4_K_M (see limitation below)
  → seesaw-gemma3-1b-q8_0.gguf  (1,077,509,216 bytes / 1,028 MB)
  ↓ gsutil cp → gs://seesaw-models/seesaw-gemma3-1b-q8_0.gguf
```

**Critical quantisation note:** MediaPipe LlmInference 0.10.33 supports only Q4_0, Q8_0, and F16. Q4_K_M (K-quant) fails with "Error building tflite model" at `model_data.cc:424`. The initial export used Q4_K_M; it was re-exported as Q8_0. See Section 12 for details.

### Model Metadata (validated via `gguf.GGUFReader`)

| Property | Value |
|---|---|
| Architecture | `gemma3` |
| Context length | 32,768 tokens |
| Quantisation | Q8_0 |
| File size | 1,077,509,216 bytes (1,028 MB) |
| GCS location | `gs://seesaw-models/seesaw-gemma3-1b-q8_0.gguf` |
| iOS load | MediaPipe Tasks GenAI `LlmInference` |

### Colab Commands (Tier 3 Quick Reference)

```bash
# Re-export from fine-tuned checkpoint (if F16 GGUF available)
!./llama-quantize seesaw-gemma3-1b-f16.gguf seesaw-gemma3-1b-q8_0.gguf Q8_0

# Re-export directly from HuggingFace checkpoint
!python convert_hf_to_gguf.py /content/seesaw-gemma3-1b \
    --outfile seesaw-gemma3-1b-q8_0.gguf \
    --outtype q8_0

# Upload to GCS
!gsutil cp seesaw-gemma3-1b-q8_0.gguf gs://seesaw-models/seesaw-gemma3-1b-q8_0.gguf

# Verify metadata
python3 - <<'EOF'
from gguf import GGUFReader
r = GGUFReader("seesaw-gemma3-1b-q8_0.gguf")
for k in r.fields:
    if "arch" in k or "context" in k:
        print(k, r.fields[k].parts[-1])
EOF
```

---

## 6. Test Suite

### Overview

38 tests across 7 modules. All tests use `TestClient` (synchronous), mock all external dependencies (Gemini, Firestore, GCS), and run without network access.

```bash
# Run all unit tests
pytest tests/ -m "not live" -v

# Run with coverage
pytest tests/ -m "not live" --cov=app --cov-report=term-missing

# Run live smoke tests (requires real Cloud Run service)
SEESAW_API_KEY=<key> SEESAW_LIVE_TEST=1 pytest tests/test_live.py -v -m live
```

### Test Modules

| Module | Tests | What It Covers |
|---|---|---|
| `test_health.py` | 3 | 200 response, correct body, no-auth access |
| `test_story.py` | 13 | Validation (422 on bad input), response shape, session ID generation, beat index increment, final beat forcing |
| `test_session.py` | 6 | Session retrieval, 404 for unknown, delete returns 200, idempotent delete, post-delete 404 |
| `test_auth.py` | 5 | All protected routes reject missing or wrong API key with 401 |
| `test_model.py` | 5 | Response shape, model version, exact size_bytes, ISO 8601 expiry format |
| `test_privacy.py` | 6 | Transcript not in Firestore, child name not in Firestore, transcript not logged, child name not logged, session ID truncated in logs, objects/scene are stored |
| `test_live.py` | varies | End-to-end smoke tests against live Cloud Run (opt-in) |

### Key Test Results

```
tests/test_auth.py ....                                   [  5 tests pass]
tests/test_health.py ...                                  [  3 tests pass]
tests/test_model.py .....                                 [  5 tests pass]
tests/test_privacy.py ......                              [  6 tests pass]
tests/test_session.py ......                              [  6 tests pass]
tests/test_story.py .............                         [ 13 tests pass]

Total: 38 passed, 0 failed
```

### Test Architecture Notes

**Fixture isolation** — `conftest.py` sets environment variables before importing the app, because `pydantic-settings` reads env vars at import time. Importing app before setting env vars would load wrong values from `.env`.

**Mock strategy** — agent calls (`generate_story_beat`) and all Firestore operations are patched at the router's import namespace, not at the module definition level. This is the correct Python mock patching location.

**Privacy tests** — `test_privacy.py` uses `caplog` to inspect actual log output and `call_args` to inspect what was passed to `create_session`. These tests provide dissertation evidence that privacy guarantees are structurally enforced, not just intended.

---

## 7. Step-by-Step Setup Guide

### Prerequisites

```bash
# Google Cloud CLI
brew install google-cloud-sdk   # macOS
gcloud --version                # verify ≥ 500.0.0

# Python 3.12+ (3.14.1 used in development)
python3 --version

# Authenticate
gcloud auth login
gcloud auth application-default login   # required for local Firestore
gcloud config set project seesaw-3e396
```

### Step 1: Clone and Install

```bash
git clone https://github.com/j2damax/seesaw-cloud-agent.git
cd seesaw-cloud-agent

python3 -m venv .venv
source .venv/bin/activate

pip install -r requirements.txt
pip install -r requirements-test.txt
```

**Dependency notes (Python 3.14 + google-adk 0.2.0):**
- `uvicorn` must be `>=0.34.0` — google-adk requires it; `0.30.0` conflicts
- `deprecated` and `litellm` must be listed explicitly — not auto-pulled on Python 3.14
- google-adk 0.2.0 uses `Runner` + `InMemorySessionService`; `agent.run_async(user_message=...)` was removed

### Step 2: Configure Local Environment

```bash
cat > .env << 'EOF'
GEMINI_API_KEY=your-gemini-api-key
SEESAW_API_KEY=your-seesaw-api-key
GCS_BUCKET_NAME=seesaw-models
FIRESTORE_PROJECT=seesaw-3e396
EOF
```

Get your Gemini API key from https://aistudio.google.com/app/apikey (billing must be enabled — free tier uses deprecated models).

### Step 3: GCP Project Setup (one-time)

```bash
# Enable required APIs
gcloud services enable \
  run.googleapis.com \
  firestore.googleapis.com \
  storage.googleapis.com \
  secretmanager.googleapis.com \
  aiplatform.googleapis.com \
  cloudbuild.googleapis.com

# Create service account
gcloud iam service-accounts create seesaw-cloud-agent \
  --display-name "SeeSaw Cloud Agent"

# Grant roles
for role in datastore.user storage.objectViewer secretmanager.secretAccessor; do
  gcloud projects add-iam-policy-binding seesaw-3e396 \
    --member="serviceAccount:seesaw-cloud-agent@seesaw-3e396.iam.gserviceaccount.com" \
    --role="roles/$role"
done

# Grant self-signing for GCS signed URLs (CRITICAL — see troubleshooting)
gcloud iam service-accounts add-iam-policy-binding \
  seesaw-cloud-agent@seesaw-3e396.iam.gserviceaccount.com \
  --member="serviceAccount:seesaw-cloud-agent@seesaw-3e396.iam.gserviceaccount.com" \
  --role="roles/iam.serviceAccountTokenCreator"
```

### Step 4: Provision Firestore

```bash
# Create Firestore database (Native mode, EU)
gcloud firestore databases create \
  --location=europe-west2 \
  --type=firestore-native

# Enable TTL policy (auto-delete sessions after 30 days)
gcloud firestore fields ttls update ttl \
  --collection-group=sessions \
  --enable-ttl
```

### Step 5: Create Cloud Storage Buckets

```bash
gsutil mb -l europe-west2 gs://seesaw-models
gsutil mb -l europe-west2 gs://seesaw-training-data

# Set 90-day lifecycle on training data bucket
cat > /tmp/lifecycle.json << 'EOF'
{"rule": [{"action": {"type": "Delete"}, "condition": {"age": 90}}]}
EOF
gsutil lifecycle set /tmp/lifecycle.json gs://seesaw-training-data
```

### Step 6: Store Secrets

```bash
# IMPORTANT: Use echo -n or printf — a trailing newline makes SEESAW_API_KEY 65 bytes
# and causes silent 401 failures (secret length 65 ≠ 64)
echo -n "YOUR_GEMINI_API_KEY" | gcloud secrets create GEMINI_API_KEY \
  --data-file=- --replication-policy=automatic

openssl rand -hex 32 | tr -d '\n' | gcloud secrets create SEESAW_API_KEY \
  --data-file=- --replication-policy=automatic

# Read the key (needed for iOS configuration)
gcloud secrets versions access latest --secret=SEESAW_API_KEY
```

### Step 7: Run Locally

```bash
source .venv/bin/activate
python -m uvicorn app.main:app --reload --port 8080

# In another terminal — verify health
curl http://localhost:8080/health

# Test story generation
curl -X POST http://localhost:8080/story/generate \
  -H "Content-Type: application/json" \
  -H "X-SeeSaw-Key: $(grep SEESAW_API_KEY .env | cut -d= -f2)" \
  -d '{
    "objects": ["teddy_bear", "book", "sofa"],
    "scene": ["living_room"],
    "child_age": 5,
    "child_name": "Vihas"
  }'
```

### Step 8: Run Tests

```bash
pytest tests/ -m "not live" -v
```

Expected: 38 passed, 0 failed.

### Step 9: Deploy to Cloud Run

```bash
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

# Get deployed URL
gcloud run services describe seesaw-cloud-agent \
  --region europe-west1 \
  --format "value(status.url)"
```

The `--source .` flag triggers Cloud Build to containerise using the Dockerfile automatically.

### Step 10: Configure iOS App

1. Open SeeSaw app → Settings
2. Set **Story Mode** to "Cloud"
3. Set **Cloud Agent URL** to `https://seesaw-cloud-agent-531853173205.europe-west1.run.app`
4. Set **Cloud Agent Key** to the value of `SEESAW_API_KEY` from Secret Manager

---

## 8. Deployment Verification

**Verified: 2026-04-13** (revision `seesaw-cloud-agent-00005-497`)

```bash
export CLOUD_URL="https://seesaw-cloud-agent-531853173205.europe-west1.run.app"
export API_KEY="$(gcloud secrets versions access latest --secret=SEESAW_API_KEY)"

# Check 1: Health (no auth required)
curl $CLOUD_URL/health
# Expected: {"status":"ok","version":"1.0.0"}

# Check 2: Auth rejection
curl -s -X POST $CLOUD_URL/story/generate \
  -H "Content-Type: application/json" \
  -H "X-SeeSaw-Key: wrong-key" \
  -d '{"objects":["teddy_bear"],"scene":["living_room"],"child_age":5,"child_name":"Vihas"}'
# Expected: {"error":"Unauthorized"}

# Check 3: Story generation (full end-to-end)
curl -s -X POST $CLOUD_URL/story/generate \
  -H "Content-Type: application/json" \
  -H "X-SeeSaw-Key: $API_KEY" \
  -d '{"objects":["teddy_bear","book"],"scene":["living_room"],"child_age":5,"child_name":"Vihas"}'
# Expected: {"story_text":"...","question":"...","is_ending":false,"session_id":"...","beat_index":0}
```

**Actual verified response (2026-04-13):**
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
# Check 4: Model URL (signed GCS link)
curl -s $CLOUD_URL/model/latest -H "X-SeeSaw-Key: $API_KEY"
# Expected: {"download_url":"https://storage.googleapis.com/...","model_version":"1.0.2","size_bytes":1077509216,"expires_at":"...Z"}
```

### Verified Deployment Summary

| Check | Status |
|---|---|
| `GET /health` | Pass — `{"status":"ok","version":"1.0.0"}` |
| Wrong API key → 401 | Pass — `{"error":"Unauthorized"}` |
| `POST /story/generate` → full story beat | Pass — Firestore session written |
| `GET /model/latest` → signed GCS URL | Pass — `size_bytes=1077509216` |

---

## 9. API Reference

All endpoints except `/health` require `X-SeeSaw-Key` header matching `SEESAW_API_KEY`.

**Base URL:** `https://seesaw-cloud-agent-531853173205.europe-west1.run.app`

### `POST /story/generate`

Generates the next story beat. Primary endpoint consumed by iOS `CloudAgentService`.

**Request body:**
```json
{
  "objects": ["teddy_bear", "book"],
  "scene": ["living_room"],
  "transcript": "I love this bear",
  "child_age": 5,
  "child_name": "Vihas",
  "story_history": [
    {"role": "model", "text": "You found a magical bear..."},
    {"role": "user",  "text": "I think the bear is hungry"}
  ],
  "session_id": "optional-uuid"
}
```

**Validation:** `child_age` must be 2–12. `child_name` must be 1–50 chars. `objects` and `scene` are required. Invalid input → 422.

**Response body:**
```json
{
  "story_text": "2-3 sentence story beat, 40-80 words",
  "question": "One open-ended question, max 15 words",
  "is_ending": false,
  "session_id": "uuid-echoed-or-generated",
  "beat_index": 0
}
```

**Story ends** when `is_ending: true`. This occurs when `beat_index >= 7` (MAX_TURNS-1) or when Gemini naturally concludes the narrative.

**Errors:** 401 (wrong key), 422 (validation), 503 (Gemini unavailable).

### `GET /model/latest`

Returns a 1-hour signed GCS URL for the GGUF model download. iOS `ModelDownloadManager` calls this before starting a background download.

**Response body:**
```json
{
  "download_url": "https://storage.googleapis.com/seesaw-models/seesaw-gemma3-1b-q8_0.gguf?X-Goog-Algorithm=...",
  "model_version": "1.0.2",
  "size_bytes": 1077509216,
  "expires_at": "2026-04-13T15:24:03Z"
}
```

The URL expires after 1 hour. iOS must begin the download before expiry.

### `GET /session/{session_id}`

Retrieves a session and its beats. Intended for a future parent dashboard.

**Response:** session document + ordered list of beats. Returns 404 if session not found.

### `DELETE /session/{session_id}`

Deletes session and all beats. GDPR right-to-erasure endpoint. Idempotent — always returns 200.

```json
{"deleted": true}
```

### `GET /health`

Unauthenticated liveness probe (Cloud Run uses this).

```json
{"status": "ok", "version": "1.0.0"}
```

---

## 10. Monitoring and Operations

### View Cloud Run Logs

```bash
# All logs (last 50)
gcloud logging read \
  "resource.type=cloud_run_revision AND resource.labels.service_name=seesaw-cloud-agent" \
  --limit=50 \
  --format="table(timestamp,textPayload)"

# Errors only
gcloud logging read \
  "resource.type=cloud_run_revision AND severity>=ERROR" \
  --limit=20

# Stream live logs
gcloud alpha run services logs tail seesaw-cloud-agent --region europe-west1
```

### Service Inspection

```bash
# Current revision and URL
gcloud run services describe seesaw-cloud-agent \
  --region europe-west1 \
  --format "table(status.url,status.latestReadyRevisionName)"

# View all revisions
gcloud run revisions list --service seesaw-cloud-agent --region europe-west1
```

### Update a Secret

```bash
# Update SEESAW_API_KEY (e.g. to rotate the key)
openssl rand -hex 32 | tr -d '\n' | \
  gcloud secrets versions add SEESAW_API_KEY --data-file=-

# Re-deploy to pick up the new secret version
gcloud run deploy seesaw-cloud-agent --region europe-west1 \
  --set-secrets GEMINI_API_KEY=GEMINI_API_KEY:latest,SEESAW_API_KEY=SEESAW_API_KEY:latest
```

### Cost Estimate

| Service | Scenario | Monthly Cost |
|---|---|---|
| Cloud Run | Idle (0 requests) | $0 |
| Cloud Run | 100 req/day, 1Gi, 1 CPU | ~$2 |
| Firestore | 1,000 reads + 500 writes/day | ~$0 (free tier) |
| Cloud Storage | 2 GB stored | ~$0.05 |
| Gemini API | 100 req/day @ $0.075/1M tokens | ~$0.05 |
| **Total (active)** | | **< $5/month** |

---

## 11. Troubleshooting Reference

### 401 Unauthorized on all authenticated endpoints

**Symptom:** Every request with a key returns `{"error":"Unauthorized"}`.  
**Root cause:** `SEESAW_API_KEY` stored with a trailing newline — 65 bytes instead of 64. This happens when `gcloud secrets create` reads from a pipe that includes `\n`.  
**Fix:**
```bash
gcloud secrets versions access latest --secret=SEESAW_API_KEY | tr -d '\n' | \
  gcloud secrets versions add SEESAW_API_KEY --data-file=-
```

### 503 `Model URL generation failed` on `GET /model/latest`

**Symptom:** `{"detail":"Model URL generation failed"}` from Cloud Run.  
**Root cause:** Cloud Run Compute Engine credentials cannot self-sign; `generate_signed_url()` needs a private key.  
**Fix (IAM — run once):**
```bash
gcloud iam service-accounts add-iam-policy-binding \
  seesaw-cloud-agent@seesaw-3e396.iam.gserviceaccount.com \
  --member="serviceAccount:seesaw-cloud-agent@seesaw-3e396.iam.gserviceaccount.com" \
  --role="roles/iam.serviceAccountTokenCreator"
```
Code fix already applied in `app/services/model_cdn.py` (passes `access_token` to force IAM signBlob path).

### 404 Model Not Found / `gemini-2.0-flash` deprecated

**Symptom:** Gemini API returns 404 or "model not found".  
**Root cause:** `gemini-2.0-flash` and `gemini-2.0-flash-lite` are deprecated for new API users.  
**Fix:** Use `gemini/gemini-2.5-flash` in `app/agents/story_agent.py`.

### 429 Quota Exceeded

**Symptom:** `429 quota exceeded` from Gemini API.  
**Root cause:** Free-tier daily quota exhausted. Free-tier keys created before billing was enabled do not automatically gain paid-tier quota.  
**Fix:** Create a new API key at aistudio.google.com/app/apikey after billing is enabled. Alternatively, wait for quota reset at midnight UTC.

### ADK `run_async() got unexpected keyword argument 'user_message'`

**Root cause:** google-adk 0.2.0 removed `agent.run_async(user_message=...)` shorthand.  
**Fix:** Use `Runner` + `InMemorySessionService` pattern as implemented in `story_agent.py`.

### `Error building tflite model` on iOS (Gemma MediaPipe)

**Root cause:** MediaPipe LlmInference 0.10.33 does not support Q4_K_M (K-quant) quantisation.  
**Fix:** Re-export GGUF as Q8_0 (see Section 5) and update `AppConfig.gemma4DirectDownloadURL`.

### Gemma model state lost between Xcode debug runs

**Root cause:** `Gemma4StoryService.modelState` is in-memory only. The GGUF file in `Documents/` survives reinstalls, but the state is not restored at launch.  
**Fix (applied in iOS):** Call `checkInstalledModel()` in `AppDependencyContainer.init()` via an async `Task`.

---

## 12. Known Limitations

### 12.1 Quantisation Compatibility (Q4_K_M → Q8_0)

**Issue:** The initial GGUF export used Q4_K_M quantisation (smaller file, ~777 MB). MediaPipe LlmInference 0.10.33 only supports Q4_0, Q8_0, and F16. K-quant variants fail at model load time (`model_data.cc:424`).

**Impact:** Re-export was required as Q8_0 (~1,028 MB). The larger file size increases download time for users.

**Lesson:** Always check the target runtime's quantisation support before training-time export decisions.

### 12.2 MediaPipe + Gemma 3 Architecture Risk

**Issue:** MediaPipe 0.10.33 was released before Gemma 3 (March 2025). Even with a supported quantisation format, the Gemma 3 architecture may not be fully supported.

**Status:** Q8_0 export addresses the quantisation issue. The architecture compatibility risk remains until confirmed with a device test.

**Mitigation:** Architecture A (Apple Foundation Models) and Architecture B (cloud) are fully operational fallbacks.

### 12.3 Cloud Run Cold Start Latency

**Issue:** With `min-instances=0`, the first request after an idle period incurs a cold start of 25–35 seconds.

**Impact:** Unacceptable for interactive use. For the dissertation evaluation, cold starts are treated as a deployment configuration artefact and warm-instance latency (~1.5–3s) is used as the representative measurement.

**Mitigation options:** Set `--min-instances=1` (adds ~$5/month), use Cloud Run Warmup Requests, or accept cold starts as a research prototype constraint.

### 12.4 Gemini JSON Output Reliability

**Issue:** Gemini occasionally wraps JSON output in markdown code fences (` ```json ... ``` `), despite the system prompt instructing JSON-only output.

**Mitigation:** `generate_story_beat()` strips markdown fences before parsing. A fallback question string is used if `question` is missing from the parsed JSON.

### 12.5 Story History Window

**Issue:** The rolling 6-turn context window in `build_user_prompt()` means early story beats are dropped in long sessions. This can cause narrative inconsistency (e.g., forgetting a character introduced in turn 1 by turn 9).

**Mitigation:** MAX_TURNS is capped at 8, so the window covers the full session in practice.

### 12.6 No Rate Limiting

**Issue:** The API key middleware prevents unauthenticated access but does not rate-limit authenticated requests. A valid key holder could exhaust Gemini quota or incur costs.

**Mitigation:** Acceptable for a research prototype with a fixed key shared only with the iOS app. Production deployment would require per-client rate limiting (e.g., Cloud Armor or a token bucket in Redis).

### 12.7 Synchronous Firestore Beat Count

**Issue:** `get_beat_count()` streams all beat documents to count them. For an 8-beat session, this reads 8 documents on every `/story/generate` call.

**Impact:** Negligible at research scale. In production, a counter field on the session document (incremented atomically with `firestore.Increment`) would be more efficient.

### 12.8 Single Gemini API Key

**Issue:** One API key is shared across all requests. Key rotation requires a Cloud Run re-deploy.

**Mitigation:** Secret Manager versioning enables zero-downtime rotation. Cloud Run picks up `latest` on each deploy.

---

## 13. Learnings and Engineering Decisions

### 13.1 Google ADK Runner Pattern

The initial implementation attempted to call `agent.run_async(user_message=...)` which was available in google-adk 0.1.x but removed in 0.2.0. The correct pattern in 0.2.0 is:

```python
# Create a session, then run via Runner
session_service.create_session(app_name="seesaw", user_id=user_id, session_id=session_id)
new_message = types.Content(role="user", parts=[types.Part(text=prompt)])
async for event in runner.run_async(user_id=user_id, session_id=session_id, new_message=new_message):
    if event.is_final_response():
        raw = event.content.parts[0].text.strip()
```

Each request uses a fresh ephemeral `InMemorySessionService` session, preventing state leakage between concurrent users.

### 13.2 GCS Signed URL on Cloud Run

Compute Engine token-based credentials cannot call `generate_signed_url()` directly (no private key). The workaround — refreshing credentials and passing `access_token` to force the IAM `signBlob` API — is non-obvious and not well-documented. The `roles/iam.serviceAccountTokenCreator` grant on the service account itself is the required IAM configuration.

### 13.3 Secret Trailing Newline Trap

Piping `openssl rand` output to `gcloud secrets create` without `| tr -d '\n'` stores a 65-byte secret that silently fails all auth checks. The `echo -n` or explicit `tr -d '\n'` pattern must be used. This is documented in Section 7 and the troubleshooting guide.

### 13.4 Privacy as Architecture, Not Policy

The original intent was to rely on developer discipline to avoid transmitting raw data. The final implementation makes this architecturally impossible: the iOS `CloudAgentService` only accepts `ScenePayload`, a struct of label strings. There is no code path to attach pixels or audio. The privacy guarantee is therefore verifiable by code audit rather than requiring trust in runtime behaviour.

### 13.5 Second-Person Narration

Early story outputs used third-person narration ("Vihas found a bear..."). User research and domain knowledge indicated that second-person ("You found a bear...") is more engaging for young children — it draws them into the story rather than making them an observer. The system prompt was revised to enforce second-person throughout, with the child's name used only for praise.

### 13.6 pydantic-settings Import Order

`pydantic-settings` reads environment variables when `Settings()` is instantiated, which happens at Python import time when `from app.config import settings` is executed. Tests that set env vars after importing the app see wrong values. `conftest.py` must set env vars before any `from app.*` import. This is documented in `conftest.py` comments.

### 13.7 Firestore Subcollection Delete

Firestore does not cascade-delete subcollections when a parent document is deleted. The `delete_session()` function must explicitly stream and delete all beat documents before deleting the session document, or they become orphaned (accessible by path but invisible in queries).

### 13.8 Q4_K_M vs Q8_0 — Quantisation Decision

The initial GGUF export chose Q4_K_M as the industry-standard "best compression with minimal quality loss" quantisation. However, MediaPipe LlmInference 0.10.33 (released before llama.cpp K-quant support matured) only supports Q4_0, Q8_0, and F16. The re-export to Q8_0 added ~250 MB to the download but resolved the "Error building tflite model" failure. Always verify target runtime quantisation support before committing to a quantisation format.

---

## 14. Future Work

### 14.1 ShieldGemma Safety Agent (T3-020)

`app/agents/safety_agent.py` is a stub. The architecture anticipates a post-generation content classifier using ShieldGemma 4 to catch any inappropriate content that bypasses Gemini's built-in safety filters. This is a post-sprint nice-to-have for production hardening.

### 14.2 Architecture C Full Integration Test

Architecture C (Gemma 3 on-device via MediaPipe) has been implemented in iOS but requires a device test with the Q8_0 GGUF to confirm the architecture is fully compatible with MediaPipe 0.10.33. This is a prerequisite for the comparative evaluation.

### 14.3 Parent Dashboard

`GET /session/{id}` is implemented and returns the full story history. A web-based parent dashboard could use this endpoint to let parents review the stories their children generated. This is out of scope for the dissertation but a natural product direction.

### 14.4 Rate Limiting and Multi-Tenancy

Current auth is a single shared API key. A production system would need per-child API keys (or JWT tokens), per-key rate limiting, and request attribution for billing and abuse detection.

### 14.5 Streaming Story Response

The current implementation waits for the full Gemini response before returning. A streaming SSE (Server-Sent Events) response would allow iOS to begin TTS while the model is still generating, reducing perceived latency.

### 14.6 Firestore Counter Optimisation

Replace the streaming beat-count query with a `firestore.Increment` counter on the session document. This reduces read operations from O(beats) to O(1) per story request.

### 14.7 min-instances=1 for Evaluation

For the formal dissertation evaluation (N=20 children), set `--min-instances=1` to eliminate cold starts and ensure consistent warm latency measurements. Reset to 0 after evaluation to reduce costs.

### 14.8 Evaluation Tooling

A cloud-side request logging system (session count, latency percentiles, object label distribution) would support quantitative analysis of Architecture B usage patterns during the evaluation.

### 14.9 Semantic VAD (Voice Activity Detection)

`docs/VAD_Research.md` documents research into LLM-assisted semantic turn-taking — detecting when a child has finished speaking based on meaning rather than silence duration. This is an enhancement to the iOS audio pipeline, not the cloud agent, but the cloud agent could participate by analysing partial transcripts.

---

## 15. MSc Thesis, Presentation and Viva Guide

This section maps the implementation to the dissertation structure and identifies the key contributions to showcase.

### 15.1 Core Research Contribution

> **"Privacy-Preserving Edge AI Co-Creative Story Companion"**
>
> This project demonstrates that a fully on-device AI story companion can match (or approach) cloud-quality story generation while transmitting zero raw personal data — specifically for children aged 3–8.

The cloud backend (this repo) is Architecture B in the comparative evaluation. It is not the "answer" — it is the quality benchmark against which on-device architectures are measured.

### 15.2 Thesis Chapter Mapping

| Thesis Chapter | Key Content from This Repo |
|---|---|
| **Chapter 2: Literature Review** | Privacy-preserving ML, edge AI vs. cloud AI, COPPA/GDPR for children's tech, LLM fine-tuning with LoRA |
| **Chapter 3: System Design** | Three-tier architecture diagram, six-stage privacy pipeline, ScenePayload as the privacy boundary, comparative evaluation design |
| **Chapter 4: Implementation** | FastAPI + ADK agent design, Firestore schema, GCS signed URL pattern, LoRA training configuration, GGUF export pipeline |
| **Chapter 5: Evaluation** | Latency measurements (cold vs. warm), training metrics (eval_loss 0.4945), Friedman test on Likert story quality ratings |
| **Chapter 6: Discussion** | Privacy architecture analysis, quantisation compatibility discovery (Q4_K_M → Q8_0), limitations, future work |

### 15.3 Key Figures for Dissertation

| Figure | Value | Source |
|---|---|---|
| Fine-tuning eval_loss (final epoch) | **0.4945** | `training/finetune.ipynb` output |
| Trainable parameters (LoRA) | **~8M / 1B (0.8%)** | LoRA r=16, 18 layers, q/k/v/o |
| Training time (Vertex AI T4) | **~27 minutes** | Colab output |
| Training cost | **~$6 USD** | Vertex AI billing |
| GGUF file size (Q8_0) | **1,028 MB** (1,077,509,216 bytes) | `gsutil ls -lh` |
| Cloud warm latency | **~1.5–3s** | Observed in Cloud Run tests |
| Cloud cold-start latency | **~25–35s** | Cloud Run min-instances=0 |
| Monthly cloud cost (idle) | **$0** | Cloud Run scales to zero |
| Monthly cloud cost (active) | **< $5** | 100 req/day estimate |
| Privacy invariant | **rawDataTransmitted = false** | iOS `StorySessionRecord` |
| Test suite | **38 tests, 0 failures** | pytest output |

### 15.4 Privacy Architecture — Key Thesis Points

1. **Structural enforcement, not policy** — the privacy boundary is enforced architecturally (the `ScenePayload` struct only admits label strings), not by runtime checks or developer discipline.

2. **Auditability** — `rawDataTransmitted: Bool = false` is hardcoded in iOS and visible in the UI. `totalPiiTokensRedacted` provides per-session quantitative PII evidence.

3. **Privacy tests as dissertation evidence** — `tests/test_privacy.py` provides six automated tests proving that transcript content and child names are never logged or stored. These can be run during a viva to demonstrate the claim.

4. **Compliance posture** — GDPR data minimisation (Art.5(1)(c)), right to erasure (`DELETE /session/{id}`), 30-day TTL, EU data residency, COPPA no-persistent-identifier compliance.

### 15.5 Comparative Evaluation Design (Present in Viva)

```
N = 20 children, ages 4–8, parental informed consent
Each child: all three architectures in counterbalanced order (Latin square, 3×3)

Primary metric:   Likert-scale story quality rating (1–5) by parent/carer observer
Secondary metrics: response latency (in-app), totalPiiTokensRedacted per session

Statistical test: Friedman test (non-parametric, paired, N<30)
Post-hoc:         Wilcoxon signed-rank

Null hypothesis H₀: Architecture A (Apple FM) produces story ratings statistically
                    equivalent to B (cloud) and C (Gemma 3), while transmitting zero PII.
```

**Architecture B is the quality ceiling** — Gemini 2.5 Flash is a much larger model than either on-device alternative. If H₀ is rejected with A or C producing statistically lower ratings, the research validates the architectural trade-off. If H₀ is not rejected, the paper demonstrates that on-device models have reached parity at this task.

### 15.6 Technical Novelty Points

Highlight these in the presentation and viva:

1. **Six-stage privacy pipeline as pre-processing** — face blur before object detection ensures no face data reaches the ML models, even transiently. This is more rigorous than post-hoc redaction.

2. **ScenePayload as a formal privacy contract** — the data model is the enforcement mechanism. Changes to what the cloud receives require a coordinated iOS + cloud change, creating an audit trail.

3. **LoRA fine-tuning at ~0.8% parameters** — adapting a 1B-parameter model for a specific domain with 8,000 training examples and only 8M trainable parameters is a demonstration of efficient domain adaptation.

4. **GGUF as the on-device delivery format** — the training → LoRA → merge → GGUF export → Cloud Storage → iOS `URLSession` download → MediaPipe inference pipeline is a complete end-to-end deployment story.

5. **Privacy tests as evaluation artefacts** — `test_privacy.py` is not just software quality assurance; it is a mechanism for claiming and verifying privacy properties in the dissertation.

### 15.7 Anticipated Viva Questions and Answers

**Q: Why not encrypt the labels in ScenePayload?**  
A: Label strings ("teddy_bear", "living_room") are already semantic abstractions with no direct link to PII. Encryption would add latency and complexity without meaningfully improving privacy — the privacy guarantee comes from _not transmitting raw media_, not from encrypting what is transmitted. HTTPS in transit is sufficient for label-level data.

**Q: How do you know rawDataTransmitted is actually false?**  
A: Three layers of evidence: (1) iOS code audit — `CloudAgentService.swift` only sends `ScenePayload`, a struct of label strings; (2) `StorySessionRecord.rawDataTransmitted` is hardcoded `false` and visible in the UI; (3) automated privacy tests in `test_privacy.py` verify the cloud side never stores transcript or child name.

**Q: Why did you choose Gemma 3 1B for Architecture C instead of a larger model?**  
A: Gemma 4 has no 1B variant — the smallest Gemma 4 is E2B MoE, which is incompatible with MediaPipe. Gemma 3 1B is the largest model that fits in on-device RAM with acceptable inference latency (~3–5s), is compatible with MediaPipe LlmInference, and supports LoRA fine-tuning on a T4 GPU within cost constraints.

**Q: What is the actual quality difference between Architecture A, B, and C?**  
A: This is the empirical research question. Architecture B (Gemini 2.5 Flash) is expected to produce highest quality (largest model, cloud-scale compute). Architecture A (Apple Foundation Models 3B) should outperform Architecture C (Gemma 3 1B, fine-tuned but smaller base). The comparative evaluation (N=20) will test whether these differences are statistically significant on Likert story quality ratings.

**Q: How does the system handle a child asking about something not in the YOLO taxonomy?**  
A: The `transcript` field carries the child's PII-scrubbed speech. If a child mentions an object not detected by YOLO (e.g., "I have a dinosaur"), the transcript is incorporated into the prompt and Gemini can weave it into the narrative. The story adapts to what the child says, not just what the camera detects.

**Q: Why is the Firestore TTL 30 days?**  
A: Session data is used for multi-turn story continuity within a session. Cross-session data (e.g., a parent reviewing last week's story) is served by the iOS app's `StoryTimelineStore` (local SwiftData), not Firestore. 30 days provides a buffer for delayed sync while satisfying GDPR data minimisation.

**Q: What happens when Cloud Run is cold-started during an evaluation?**  
A: For the formal evaluation, `min-instances=1` will be set to eliminate cold starts. Warm latency (~1.5–3s) is the representative performance figure. Cold-start latency is a deployment configuration artefact, not a model quality measure, and will be excluded from latency analysis.

### 15.8 Repository Artefacts for Thesis Appendix

| Artefact | Location | Purpose |
|---|---|---|
| Cloud agent source | `github.com/j2damax/seesaw-cloud-agent` | Architecture B implementation |
| Training notebooks | `training/data_prep.ipynb`, `finetune.ipynb`, `export_gguf.ipynb` | Complete Tier 3 pipeline |
| Fine-tuned checkpoint | `gs://seesaw-models/checkpoints/seesaw-gemma3-v1/` | Model weights |
| Production GGUF | `gs://seesaw-models/seesaw-gemma3-1b-q8_0.gguf` | Deployed Architecture C model |
| Privacy contract | `docs/PRIVACY_CONTRACT.md` | Formal privacy specification |
| API reference | `docs/API_REFERENCE.md` | Endpoint contract (iOS-fixed) |
| Deployment record | `docs/DEPLOYMENT.md` | GCP infrastructure evidence |
| This document | `docs/DEVELOPER_REFERENCE.md` | Full developer + thesis reference |
| iOS source | `github.com/j2damax/seesaw-companion-ios` (branch: `gemma-4-integration`) | All three architectures |

### 15.9 Slide Deck Structure (Suggested)

1. **Problem** — children's AI companions and the privacy paradox (engaging experience requires data; data requires trust)
2. **Research question** — can on-device AI match cloud quality at zero PII cost?
3. **System overview** — three-tier architecture diagram + six-stage privacy pipeline
4. **Privacy boundary** — ScenePayload diagram (what crosses, what never crosses)
5. **Architecture A** — Apple Foundation Models (always-on, Neural Engine)
6. **Architecture B** — Cloud Gemini (this repo) — quality benchmark
7. **Architecture C** — Gemma 3 fine-tuning pipeline (LoRA metrics, GGUF export)
8. **Evaluation design** — Latin square, N=20, Friedman test
9. **Results** — latency table, story quality Likert results, PII scrubbing statistics
10. **Privacy evidence** — `test_privacy.py` demo, rawDataTransmitted audit
11. **Limitations and future work**
12. **Conclusion** — what the results mean for edge AI privacy in children's applications

---

*Document generated: 2026-04-16*  
*Repo: github.com/j2damax/seesaw-cloud-agent*  
*Dissertation: "Privacy-Preserving Edge AI Co-Creative Story Companion"*
