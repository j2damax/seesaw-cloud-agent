# seesaw-cloud-agent

Cloud backend for **SeeSaw** — a privacy-first AI storytelling companion for children aged 3–8.

**Tier 2 of 3** in the MSc dissertation comparative evaluation:  
*"Privacy-Preserving Edge AI Co-Creative Story Companion"*

```
Tier 1: seesaw-companion-ios   iPhone — on-device privacy pipeline
Tier 2: seesaw-cloud-agent     Cloud Run — this repo (Architecture B)
Tier 3: Gemma fine-tuning      Vertex AI — LoRA training pipeline
```

**Live:** `https://seesaw-cloud-agent-531853173205.europe-west1.run.app`

---

## What It Does

Receives anonymous scene labels from iOS, generates personalised story beats via Gemini 2.5 Flash, persists sessions in Firestore, and serves a fine-tuned Gemma 3 1B GGUF for on-device download (Architecture C).

**Privacy invariant:** `rawDataTransmitted == false` for all sessions.  
The iOS app sends only YOLO label strings and PII-scrubbed speech — never pixels, audio, or faces.

---

## Stack

| Layer | Technology |
|---|---|
| API | FastAPI 0.115 + Pydantic v2 |
| AI agent | Google ADK 0.2.0 + LiteLlm → Gemini 2.5 Flash |
| Persistence | Firestore Native (europe-west2), 30-day TTL |
| Model hosting | Cloud Storage (europe-west2), V4 signed URLs |
| Hosting | Cloud Run (europe-west1), min-instances=0, 1Gi |
| Auth | `X-SeeSaw-Key` shared secret via Secret Manager |
| Fine-tuning | Vertex AI T4, LoRA r=16, Gemma 3 1B, eval_loss 0.4945 |

---

## API

All endpoints require `X-SeeSaw-Key` header except `/health`.

| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/story/generate` | Generate next story beat from ScenePayload |
| `GET` | `/model/latest` | Signed GCS URL for Gemma 3 GGUF download |
| `GET` | `/session/{id}` | Retrieve session + beat history |
| `DELETE` | `/session/{id}` | GDPR right-to-erasure delete |
| `GET` | `/health` | Liveness probe (unauthenticated) |

**Request → Response:**
```json
POST /story/generate
{
  "objects": ["teddy_bear", "book"],
  "scene": ["living_room"],
  "transcript": "I love this bear",
  "child_age": 5,
  "child_name": "Vihas",
  "story_history": [],
  "session_id": null
}

→ {
  "story_text": "You find your soft teddy bear nestled in the corner...",
  "question": "What do you think the bear has been dreaming about?",
  "is_ending": false,
  "session_id": "7f33b5bd-b6d7-48e6-afcc-f44ac36cd6c3",
  "beat_index": 0
}
```

---

## Quick Start

```bash
git clone https://github.com/j2damax/seesaw-cloud-agent.git
cd seesaw-cloud-agent
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# Configure
cat > .env << 'EOF'
GEMINI_API_KEY=your-key
SEESAW_API_KEY=your-key
GCS_BUCKET_NAME=seesaw-models
FIRESTORE_PROJECT=seesaw-3e396
EOF

# Run
uvicorn app.main:app --reload --port 8080

# Test
curl http://localhost:8080/health
curl -X POST http://localhost:8080/story/generate \
  -H "Content-Type: application/json" \
  -H "X-SeeSaw-Key: your-key" \
  -d '{"objects":["teddy_bear","book"],"scene":["living_room"],"child_age":5,"child_name":"Vihas"}'
```

---

## Tests

```bash
pip install -r requirements-test.txt
pytest tests/ -m "not live" -v
# 38 passed, 0 failed
```

Modules: `test_health`, `test_story`, `test_session`, `test_auth`, `test_model`, `test_privacy`  
`test_privacy.py` structurally verifies the privacy contract — transcript and child name are never logged or stored.

---

## Deploy

```bash
gcloud run deploy seesaw-cloud-agent \
  --source . \
  --region europe-west1 \
  --platform managed \
  --allow-unauthenticated \
  --service-account seesaw-cloud-agent@seesaw-3e396.iam.gserviceaccount.com \
  --set-secrets GEMINI_API_KEY=GEMINI_API_KEY:latest,SEESAW_API_KEY=SEESAW_API_KEY:latest \
  --set-env-vars GCS_BUCKET_NAME=seesaw-models,FIRESTORE_PROJECT=seesaw-3e396 \
  --memory 1Gi --min-instances 0 --max-instances 3 --timeout 60
```

See [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md) for full GCP setup (Firestore, GCS, Secret Manager, IAM).

---

## Fine-Tuned Model (Architecture C)

| Property | Value |
|---|---|
| Base | `google/gemma-3-1b-it` |
| Method | LoRA r=16, α=32, q/k/v/o, ~0.8% trainable |
| Data | 8,000 examples (TinyStories + iOS beat exports) |
| Training | 3 epochs, Vertex AI T4, 27 min, ~$6 |
| eval_loss | 0.4945 (epoch 3) |
| Export | Q8_0 GGUF, 1,028 MB — Q4_K_M unsupported by MediaPipe |
| Location | `gs://seesaw-models/seesaw-gemma3-1b-q8_0.gguf` |
| iOS load | MediaPipe Tasks GenAI `LlmInference` |

Training notebooks: [`training/`](training/)

---

## Project Structure

```
app/
  main.py              FastAPI app + API key middleware
  config.py            Pydantic Settings
  routers/             story.py · session.py · model.py · health.py
  agents/story_agent.py  Google ADK LlmAgent + Gemini 2.5 Flash
  models/              ScenePayload · StoryBeatResponse
  services/            firestore.py · model_cdn.py
tests/                 38 tests — unit + privacy + live smoke
training/              data_prep · finetune · export_gguf (Colab notebooks)
docs/                  ARCHITECTURE · API_REFERENCE · PRIVACY_CONTRACT
                       DEPLOYMENT · FINE_TUNING · DEVELOPER_REFERENCE
```

---

## Documentation

| Doc | Purpose |
|---|---|
| [`docs/DEVELOPER_REFERENCE.md`](docs/DEVELOPER_REFERENCE.md) | Complete reference — architecture, implementation, deployment, learnings, thesis guide |
| [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | Three-tier system overview |
| [`docs/PRIVACY_CONTRACT.md`](docs/PRIVACY_CONTRACT.md) | What the cloud receives and what it never receives |
| [`docs/API_REFERENCE.md`](docs/API_REFERENCE.md) | Endpoint schemas (fixed — must match iOS) |
| [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md) | GCP setup + Cloud Run deploy |
| [`docs/FINE_TUNING.md`](docs/FINE_TUNING.md) | Gemma 3 LoRA training pipeline |
| [`docs/THESIS_REFERENCE.md`](docs/THESIS_REFERENCE.md) | Key figures and data for MSc dissertation |

---

## Related

- **iOS app:** [`github.com/j2damax/seesaw-companion-ios`](https://github.com/j2damax/seesaw-companion-ios) (branch: `gemma-4-integration`)
- **YOLO model:** [`github.com/j2damax/seesaw-yolo-model`](https://github.com/j2damax/seesaw-yolo-model)
- **Project board:** [github.com/users/j2damax/projects/4](https://github.com/users/j2damax/projects/4/views/7)

---

*MSc dissertation — "Privacy-Preserving Edge AI Co-Creative Story Companion"*  
*GCP project: `seesaw-3e396` · Deployed: 2026-04-13*
