# SeeSaw — System Architecture

**Last updated:** 2026-04-12  
**Version:** Sprint 3 (Gemma 4 integration)

---

## Three-Tier Overview

```
┌─────────────────────────────────────────────────────────────────────┐
│  TIER 1: seesaw-companion-ios  (iPhone — always on-device)          │
│                                                                     │
│  Camera/Mic → Six-Stage Privacy Pipeline → ScenePayload            │
│            → Story Engine (mode-selected) → AVSpeechSynthesizer    │
│                                                                     │
│  Story Engine modes:                                                │
│    onDevice       → Apple Foundation Models (3B, Neural Engine)    │
│    gemma4OnDevice → Gemma 4 1B GGUF via MediaPipe (~800MB DL)      │
│    cloud          → POST ScenePayload to Tier 2                    │
│    hybrid         → cloud → gemma4OnDevice → onDevice fallback     │
│                                                                     │
│  Privacy guarantee: raw pixels/audio NEVER leave the device        │
└────────────────────┬────────────────────────────────────────────────┘
                     │ ScenePayload only (labels + scrubbed text)
                     │ POST /story/generate
                     ▼
┌─────────────────────────────────────────────────────────────────────┐
│  TIER 2: seesaw-cloud-agent  (Cloud Run — THIS REPO)                │
│                                                                     │
│  FastAPI → API key check → Google ADK story_agent                  │
│         → Gemini 2.0 Flash → StoryBeat JSON response               │
│         → Firestore (session + beat persistence)                   │
│                                                                     │
│  Also serves: GET /model/latest (signed GCS URL for GGUF download) │
└────────────────────┬────────────────────────────────────────────────┘
                     │ training artifacts
                     ▼
┌─────────────────────────────────────────────────────────────────────┐
│  TIER 3: Training Pipeline  (Vertex AI + Colab)                     │
│                                                                     │
│  TinyStories + StoryBeatRecord exports → data_prep.ipynb           │
│  → finetune.ipynb (LoRA, Vertex AI T4, ~3h, ~$6)                  │
│  → export_gguf.ipynb (Q4_K_M GGUF, ~800 MB)                       │
│  → upload to gs://seesaw-models/                                   │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Six-Stage iOS Privacy Pipeline (Tier 1)

The pipeline runs entirely on-device. Each stage produces anonymous outputs only:

| Stage | Technology | Input | Output |
|-------|-----------|-------|--------|
| 1. Face Detection | `VNDetectFaceRectanglesRequest` | JPEG frame | Face bounding boxes |
| 2. Face Blur | `CIGaussianBlur` σ≥30 | JPEG + boxes | Blurred JPEG |
| 3. Object Detection | YOLO11n CoreML (44 classes) | Blurred JPEG | Label strings |
| 4. Scene Classification | `VNClassifyImageRequest` | Blurred JPEG | Scene categories |
| 5. Speech → Text | `SFSpeechRecognizer` (on-device only) | Audio buffer | Raw transcript |
| 6. PII Scrub | Regex patterns (`PIIScrubber`) | Raw transcript | Scrubbed text |

**Output:** `ScenePayload { objects:[String], scene:[String], transcript:String?, childAge:Int }`  
**Raw data fate:** allocated in-memory, processed, discarded. Never written to disk, never transmitted.

---

## iOS App Structure (Tier 1)

### Concurrency Model

All services are Swift actors. `@MainActor` used only where platform APIs require it:

| Component | Isolation | Purpose |
|-----------|-----------|---------|
| `PrivacyPipelineService` | actor | Six-stage pipeline |
| `OnDeviceStoryService` | actor | Apple Foundation Models |
| `Gemma4StoryService` | actor | Gemma 4 GGUF via MediaPipe |
| `AudioService` | actor | TTS (AVSpeechSynthesizer) |
| `AudioCaptureService` | actor | Mic capture |
| `SpeechRecognitionService` | actor | On-device STT |
| `CloudAgentService` | actor | HTTP client for this repo |
| `BLEService` | @MainActor | CoreBluetooth (platform req) |
| `CompanionViewModel` | @MainActor | UI state machine |

### Dependency Injection

`AppDependencyContainer` constructs all singletons at launch. `AppCoordinator` injects into ViewModels via factory methods. Views never construct services directly.

### Navigation State Machine

```
launch → terms → signIn → onboarding → home
```
Fast-paths: if `hasAcceptedTerms` and `hasCompletedOnboarding` are set, coordinator jumps to `home`.

### Session State Machine (`SessionState.swift`)

```
idle → scanning → connected → receivingImage → processingPrivacy
     → requestingStory → generatingStory → encodingAudio
     → sendingAudio → recordingAudio → listeningForAnswer → error(_)
```

### Story Generation Routing (`CompanionViewModel`)

```
runFullPipeline(jpegData:)
  ├── .onDevice       → runOnDevicePipeline (Apple Foundation Models)
  ├── .gemma4OnDevice → runGemma4Pipeline   (Gemma 4 GGUF, falls back to Apple FM)
  ├── .cloud          → runCloudPipeline    (POST to this repo)
  └── .hybrid         → runHybridPipeline  (cloud → Gemma4 → Apple FM)
```

---

## Cloud Agent Structure (Tier 2 — This Repo)

### Request Flow

```
iOS CloudAgentService
  POST /story/generate
  Header: X-SeeSaw-Key: {secret}
  Body: ScenePayload JSON
         ↓
  FastAPI main.py
    verify_api_key middleware
         ↓
  story.py router
    validates ScenePayload (Pydantic)
         ↓
  story_agent.py
    LlmAgent(model=Gemini 2.0 Flash)
    builds prompt from ScenePayload + history
         ↓
  returns StoryBeat JSON
         ↓
  firestore.py
    appends beat to session document
         ↓
  iOS receives { story_text, question, is_ending, session_id, beat_index }
```

### Agent Design (`story_agent.py`)

Uses Google ADK `LlmAgent` with `LiteLlm` backend:

```python
story_agent = LlmAgent(
    name="seesaw_story_agent",
    model=LiteLlm(model="gemini/gemini-2.0-flash"),
    instruction=STORY_SYSTEM_PROMPT   # children's storytelling persona
)
```

The system prompt enforces:
- Children-appropriate content (no violence, fear, adult themes)
- JSON-only output: `{ story_text, question, is_ending }`
- 2–3 sentence story text, 40–80 words
- Address child by name

---

## Training Pipeline (Tier 3)

### Dataset Composition

| Source | Count | Purpose |
|--------|-------|---------|
| `roneneldan/TinyStories` (HuggingFace) | ~8,000 sampled | Base story fluency |
| `StoryBeatRecord` exports from iOS app | Variable | Domain-specific (highest value) |
| **Total** | 6,000–8,000 | After safety filtering |

### Fine-Tuning Configuration

```
Base model:    google/gemma-4-1b-it  (instruction-tuned)
Method:        LoRA  (r=16, alpha=32, target: q/k/v/o projections)
Parameters:    ~0.8% trainable
Hardware:      Vertex AI T4 GPU
Duration:      ~3 hours
Cost:          ~$6 USD
Epochs:        3
Batch:         4 + grad_accum=4 (effective=16)
LR:            2e-4, cosine schedule
```

### Export Pipeline

```
Vertex AI checkpoint
  ↓ merge LoRA adapters
  ↓ convert_hf_to_gguf.py  (llama.cpp)
  ↓ llama-quantize Q4_K_M
  → seesaw-gemma4-1b-q4km.gguf (~800 MB)
  ↓ upload gs://seesaw-models/
  ↓ GET /model/latest returns signed URL
  ↓ iOS ModelDownloadManager downloads to Documents/
  ↓ Gemma4StoryService loads via MediaPipe LlmInference
```

---

## Comparative Research Design

Three architectures evaluated for the MSc dissertation:

| Architecture | Story Engine | Privacy Guarantee | Network Required |
|---|---|---|---|
| A — On-Device | Apple Foundation Models | Zero raw data transmitted | No |
| B — Cloud | Gemini 2.0 Flash (this repo) | ScenePayload labels only | Yes |
| C — Hybrid Gemma 4 | Fine-tuned Gemma 4 1B | Zero raw data transmitted | No |

**Null hypothesis H₀:** Architecture A (fully on-device) produces story beats rated statistically equivalent in quality to B (cloud) and C (Gemma 4), while transmitting zero PII.

**Evaluation:** 20 child participants, Likert-scale story quality ratings, paired t-test / Wilcoxon signed-rank. See `seesaw-companion-ios/SeeSaw-Project-Master.md` for full benchmark design.

---

## Infrastructure

| Service | Purpose | Region |
|---------|---------|--------|
| Cloud Run | FastAPI container | europe-west1 |
| Firestore | Session persistence | europe-west2 (Native mode) |
| Cloud Storage | GGUF model, story assets | europe-west2 |
| Secret Manager | API keys | europe-west1 |
| Vertex AI | Model fine-tuning | us-central1 (T4 available) |

**Cost profile (idle):** ~$0/month (Cloud Run scales to zero). Active: ~$0.002/request.
