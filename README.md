# seesaw-cloud-agent

Cloud backend for the **SeeSaw** privacy-first AI storytelling companion for children aged 3–8.

## What This Is

SeeSaw is an iOS app that transforms real-world objects (seen via the device camera) into interactive, personalised story beats. This service provides optional cloud-enhanced story generation via **Gemini 2.0 Flash** and hosts the **Gemma 4 1B GGUF model** for iOS download.

The iOS app sends only anonymous scene labels — never pixels, audio, or faces. Full privacy contract in [`docs/PRIVACY_CONTRACT.md`](docs/PRIVACY_CONTRACT.md).

## Quick Start

```bash
pip install -r requirements.txt
GEMINI_API_KEY=... SEESAW_API_KEY=... uvicorn app.main:app --reload --port 8080
curl http://localhost:8080/health
```

## Documentation

| Document | Purpose |
|----------|---------|
| [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | Full system architecture (3 tiers) |
| [`docs/PRIVACY_CONTRACT.md`](docs/PRIVACY_CONTRACT.md) | What the cloud receives and what it never receives |
| [`docs/API_REFERENCE.md`](docs/API_REFERENCE.md) | Endpoint schemas (fixed — must match iOS) |
| [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md) | GCP setup + Cloud Run deploy |
| [`docs/FINE_TUNING.md`](docs/FINE_TUNING.md) | Gemma 4 LoRA training pipeline |
| [`docs/iOS_Implementation_Guide.md`](docs/iOS_Implementation_Guide.md) | Master sprint document (Steps 4–6) |
| [`docs/VAD_Research.md`](docs/VAD_Research.md) | LLM-assisted semantic turn-taking detection |

## Stack

- **FastAPI** + Pydantic v2
- **Google ADK** (`LlmAgent` + Gemini 2.0 Flash)
- **Firebase Firestore** (session persistence)
- **Cloud Run** (europe-west1, min-instances=0)
- **Cloud Storage** (GGUF model hosting)
- **Vertex AI** (Gemma 4 fine-tuning pipeline)

## Related Repositories

- **iOS app:** `github.com/j2damax/seesaw-companion-ios` (branch: `gemma-4-integration`)
- **YOLO model:** `github.com/j2damax/seesaw-yolo-model`
- **Project board:** https://github.com/users/j2damax/projects/4/views/7

## Research Context

MSc dissertation — *"Privacy-Preserving Edge AI Co-Creative Story Companion"*  
Architecture comparison: on-device (Apple FM) vs. on-device (Gemma 4) vs. cloud (Gemini 2.0 Flash)  
Privacy invariant: `rawDataTransmitted == false` for all modes
