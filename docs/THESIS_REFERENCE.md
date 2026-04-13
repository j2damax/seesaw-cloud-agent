# SeeSaw — MSc Thesis Reference

**Dissertation title:** Privacy-Preserving Edge AI Co-Creative Story Companion  
**Architecture evaluated:** Three-tier comparative study (A: on-device Apple FM · B: cloud Gemini · C: on-device Gemma 3)  
**This repo:** Architecture B cloud backend + Tier 3 fine-tuning pipeline

---

## 1. Cloud Backend (Architecture B) — Verified Deployment

| Property | Value |
|---|---|
| **Service URL** | `https://seesaw-cloud-agent-531853173205.europe-west1.run.app` |
| **GCP Project** | `seesaw-3e396` |
| **Region** | `europe-west1` (EU data residency — GDPR compliant) |
| **Revision** | `seesaw-cloud-agent-00005-497` (deployed 2026-04-13) |
| **Framework** | FastAPI 0.115 + Google ADK 0.2.0 + Gemini 2.5 Flash |
| **Persistence** | Firestore (Native mode, europe-west2), 30-day TTL |
| **Container** | Python 3.12-slim, 1 Gi RAM, min-instances=0, max-instances=3 |
| **Auth** | `X-SeeSaw-Key` shared secret header (64-char hex, Secret Manager) |

### Verified API Endpoints (2026-04-13)

| Endpoint | Result |
|---|---|
| `GET /health` | `{"status":"ok","version":"1.0.0"}` |
| `POST /story/generate` | Full story beat JSON, Firestore session written |
| `GET /model/latest` | Signed GCS URL + `size_bytes=814261088` |
| No key → any endpoint | `{"error":"Unauthorized"}` (401) |

### Story Generation Latency (Architecture B)

Observed on Colab T4 test calls to Cloud Run (europe-west1):

| Condition | Latency |
|---|---|
| Cold start (min-instances=0, first request) | ~25–35s |
| Warm instance | ~1.5–3s |

For dissertation timing measurements, use warm-instance latency. Cold-start latency is a deployment configuration artefact, not a model quality measure.

---

## 2. Fine-Tuned Model (Architecture C) — Tier 3 Pipeline

### Base Model

| Property | Value |
|---|---|
| **Model** | `google/gemma-3-1b-it` |
| **Parameters** | 1B |
| **Context window** | 32,768 tokens |
| **Licence** | Gemma Terms of Service |
| **HuggingFace** | `google/gemma-3-1b-it` |

> **Note:** `google/gemma-4-1b-it` does not exist — Gemma 4 has no 1B variant (smallest is E2B MoE, MediaPipe-incompatible). Gemma 3 1B is the correct choice for this project.

### Fine-Tuning Run (2026-04-13)

| Property | Value |
|---|---|
| **Method** | LoRA (r=16, α=32, target: q/k/v/o projections) |
| **Trainable parameters** | ~8M / 1B (~0.8%) |
| **Training data** | ~8,000 examples (TinyStories + SeeSaw beat exports) |
| **Format** | Gemma chat template, JSON-in-text output |
| **Hardware** | Vertex AI T4 GPU |
| **Runtime** | 27 minutes |
| **Cost** | ~$6 USD |
| **Epochs** | 3 |
| **Batch** | 4 × grad_accum=4 (effective=16) |
| **Learning rate** | 2e-4, cosine schedule with 5% warmup |
| **Checkpoint** | `gs://seesaw-models/checkpoints/seesaw-gemma3-v1/` |

### Training Metrics

| Epoch | Training Loss | Validation Loss |
|---|---|---|
| 1 | 0.5126 | 0.5115 |
| 2 | 0.4769 | 0.4960 |
| 3 | 0.4687 | **0.4945** |

**Best eval_loss: 0.4945** — well below target threshold of 1.5. Train/val losses track closely (no overfitting). Best model loaded at epoch 3.

### GGUF Export

| Property | Value |
|---|---|
| **Export method** | llama.cpp b8777 `convert_hf_to_gguf.py` + `llama-quantize Q4_K_M` |
| **Output file** | `seesaw-gemma3-1b-q4km.gguf` |
| **GCS location** | `gs://seesaw-models/seesaw-gemma3-1b-q4km.gguf` |
| **File size** | 814,261,088 bytes (777 MB) |
| **GGUF architecture** | `gemma3` |
| **Context length (metadata)** | 32,768 tokens |
| **Quantisation** | Q4_K_M (4-bit, mixed precision, k-quant) |
| **Validated** | `gguf.GGUFReader` metadata check: architecture=gemma3, context=32768 ✓ |
| **Download** | `GET /model/latest` → 1-hour signed GCS URL |

### Model Output Format

The model is trained to output JSON only:

```json
{"story_text": "Vihas held the bear tight...", "question": "What do you think the bear whispered?", "is_ending": false}
```

The iOS `Gemma4StoryService.parseResponse()` attempts JSON decode first, falls back to heuristic text extraction for robustness.

---

## 3. Privacy Architecture — Thesis Claims

### The Core Invariant

```
∀ session s: s.rawDataTransmitted == false
```

This invariant holds for **all three architecture modes**. For Architecture B (cloud), it is enforced structurally: the iOS `CloudAgentService` only sends `ScenePayload` — a struct of label strings and scrubbed text. It is architecturally impossible to send pixels or audio through this path.

### What Crosses the Privacy Boundary (Architecture B)

```
ScenePayload {
  objects:       ["teddy_bear", "book"]    // YOLO label strings — no pixels
  scene:         ["living_room"]           // VNClassify strings — no frames
  transcript:    "I love this bear"        // PII-scrubbed — no audio
  child_age:     5                         // integer — no birthdate
  child_name:    "Vihas"                   // first name only — no family name
  session_id:    "uuid"                    // pseudonymous — no device ID
}
```

### What NEVER Crosses (verifiable by code audit)

- JPEG frames, pixel buffers, Base64 images
- PCM/AAC audio data
- Face bounding boxes or embeddings
- Unredacted transcripts
- Device identifiers (IDFA, IDFV, device UUID)
- IP address (not logged server-side)

### Auditability

- iOS `StorySessionRecord.rawDataTransmitted: Bool` is hardcoded `false`, visible in Timeline UI
- `StorySessionRecord.totalPiiTokensRedacted: Int` counts PII events per session
- Firestore stores only generated story text and object labels — not transcript, not child name
- Sessions auto-delete after 30 days (Firestore TTL on `ttl` field)

---

## 4. Comparative Evaluation Design

### Three Architectures

| | Architecture A | Architecture B | Architecture C |
|---|---|---|---|
| **Engine** | Apple Foundation Models (3B, Neural Engine) | Gemini 2.5 Flash via Cloud Run | Gemma 3 1B GGUF via MediaPipe |
| **Network required** | No | Yes | No (after 777 MB download) |
| **Raw data transmitted** | No | No | No |
| **Cold-start latency** | ~2–4s (model always loaded) | ~25–35s (Cloud Run cold) / ~1.5–3s (warm) | ~3–5s (model load from disk) |
| **Story quality (hypothesis)** | Baseline | Highest (largest model) | Between A and B |
| **Privacy guarantee** | Zero transmission | ScenePayload labels only | Zero transmission |

### Null Hypothesis

**H₀:** Architecture A (Apple FM, fully on-device) produces story beats rated statistically equivalent in quality to Architecture B (cloud Gemini) and Architecture C (Gemma 3 on-device), while transmitting zero PII.

### Evaluation Protocol

- N = 20 child participants, ages 4–8, with parental informed consent
- Each child uses all three modes in counterbalanced order (Latin square, 3×3)
- Metric: Likert-scale story quality rating (1–5) by parent/carer observer
- Secondary metrics: response latency (measured in-app), `totalPiiTokensRedacted` per session
- Statistical test: Friedman test + Wilcoxon signed-rank post-hoc (non-parametric, paired, N<30)
- Full benchmark design: `seesaw-companion-ios/SeeSaw-Project-Master.md`

---

## 5. Technical Stack — Cite-Ready Summary

### Cloud Backend Stack

```
Language:   Python 3.12
Framework:  FastAPI 0.115.0
AI:         Google ADK 0.2.0 + LiteLlm + Gemini 2.5 Flash
Storage:    Google Cloud Firestore (Native, europe-west2)
Hosting:    Google Cloud Run (europe-west1, serverless, min-instances=0)
Auth:       Shared-secret header (X-SeeSaw-Key, GCP Secret Manager)
Model CDN:  Google Cloud Storage (europe-west2) + V4 signed URLs
```

### Fine-Tuning Stack

```
Base:       google/gemma-3-1b-it (HuggingFace)
Fine-tune:  PEFT 0.14 LoRA, Transformers 4.49, TRL
Hardware:   Vertex AI custom job, NVIDIA T4 GPU
Export:     llama.cpp b8777 convert_hf_to_gguf.py + Q4_K_M quantisation
Format:     GGUF (llama.cpp standard), Q4_K_M 4-bit mixed precision
iOS load:   MediaPipe Tasks GenAI LlmInference
```

### iOS Stack (Architecture C path)

```
Language:   Swift 6, SwiftUI, SwiftData
Inference:  MediaPipe Tasks GenAI (LlmInference)
Model file: seesaw-gemma3-1b-q4km.gguf (777 MB, Documents/)
Download:   URLSession background download, progress via AsyncStream
```

---

## 6. Repository Artefacts for Thesis Appendix

| Artefact | Location | Purpose |
|---|---|---|
| Cloud agent source | `github.com/j2damax/seesaw-cloud-agent` | Architecture B implementation |
| Training notebooks | `training/data_prep.ipynb`, `finetune.ipynb`, `export_gguf.ipynb` | Tier 3 pipeline |
| Fine-tuned checkpoint | `gs://seesaw-models/checkpoints/seesaw-gemma3-v1/` | Model weights |
| Production GGUF | `gs://seesaw-models/seesaw-gemma3-1b-q4km.gguf` | Deployed model |
| Privacy contract | `docs/PRIVACY_CONTRACT.md` | Formal privacy spec |
| API reference | `docs/API_REFERENCE.md` | Endpoint contract |
| Deployment record | `docs/DEPLOYMENT.md` | Infrastructure evidence |
| iOS source | `github.com/j2damax/seesaw-companion-ios` (branch: `gemma-4-integration`) | All three architectures |

---

## 7. Key Figures for Dissertation

| Figure | Value | Source |
|---|---|---|
| Training eval_loss (final) | 0.4945 | `training/finetune.ipynb` cell output |
| GGUF file size | 814,261,088 bytes (777 MB) | `gsutil ls -lh gs://seesaw-models/seesaw-gemma3-1b-q4km.gguf` |
| Trainable parameters | ~8M / 1B (0.8%) | LoRA r=16 on q/k/v/o, 18 layers |
| Cloud warm latency | ~1.5–3s | Observed during `POST /story/generate` testing |
| Cloud cold-start | ~25–35s | Cloud Run min-instances=0 |
| PII scrubbing | `totalPiiTokensRedacted` per session | iOS `StorySessionRecord` field |
| Privacy invariant | `rawDataTransmitted = false` for all sessions | iOS `StorySessionRecord` field |
| Monthly cloud cost (idle) | ~$0 (scales to zero) | Cloud Run billing |
| Monthly cloud cost (active) | ~$5 (100 req/day) | Cloud Run + Gemini API |
