# SeeSaw — Gemma 4 Integration: Master Implementation Prompt

**For use as a Claude Code session-opening context document.**
**Branch:** `gemma-4-integration` (seesaw-companion-ios) + new `seesaw-cloud-agent` repo
**Timeline:** 2 days · **Project board:** https://github.com/users/j2damax/projects/4/views/7
**Cloud repo:** github.com/j2damax/seesaw-cloud-agent
**Last updated:** 2026-04-12

---

## 1. What Has Already Been Built (Do Not Touch)

The `on-device-pipeline` branch of `seesaw-companion-ios` is feature-complete. It contains:

| Layer | Implementation | Status |
|-------|---------------|--------|
| Object detection | YOLO11n CoreML — 44 classes, `PrivacyPipelineService` Stage 3 | ✅ Complete |
| Privacy pipeline | 6-stage (face blur → YOLO → scene → STT → PII scrub) | ✅ Complete |
| Story generation | Apple Foundation Models `OnDeviceStoryService` | ✅ Complete |
| Story Timeline | SwiftData `StorySessionRecord` + `StoryBeatRecord`, Timeline + Detail views | ✅ Complete |
| Audio | `AudioService`, `AudioCaptureService`, `SpeechRecognitionService` | ✅ Complete |
| Tests | 129 tests, 0 failures | ✅ Complete |

**Do not modify any existing files from the above layers.** The Gemma 4 integration is purely additive. All existing modes (`onDevice` = Apple FM, `cloud` = existing Cloud Run endpoint) must continue to work identically.

---

## 2. What This Sprint Adds

### Mode 2: Gemma 4 1B On-Device (new `StoryGenerationMode` case)

A new story generation path using a fine-tuned Gemma 4 1B GGUF model running via MediaPipe Tasks GenAI on-device. The model is ~800 MB, downloaded once on first use, stored in the app's Documents directory. Runs entirely on-device — same absolute privacy guarantee as Apple Foundation Models mode.

### Mode 3: Cloud Enhanced via seesaw-cloud-agent (new cloud backend)

A new `FastAPI + Google ADK + Gemini 2.0 Flash` backend deployed on Cloud Run. Accepts the existing `ScenePayload` struct (labels + scrubbed transcript only — no raw media), returns `StoryBeat`-compatible JSON. The iOS `CloudAgentService` already handles this — only the backend URL in Settings changes. 

### Settings screen mode picker

A `Story Engine` section in `SettingsTabView` allowing parents to choose between the three modes. The `storyMode` UserDefaults key already exists; the Settings UI needs the `gemma4OnDevice` case added and a download progress card shown when needed.

---

## 3. Three-Mode Architecture

```swift
enum StoryGenerationMode: String, CaseIterable {
    case onDevice          // Apple Foundation Models (~3B, Neural Engine) — EXISTING
    case gemma4OnDevice    // Gemma 4 1B GGUF (MediaPipe, ~800 MB download) — NEW
    case cloud             // seesaw-cloud-agent (Gemini 2.0 Flash, FastAPI) — NEW backend
}
```

**Fallback chain (automatic, invisible to child):**
```
cloud (preferred when network available + URL configured)
  └── gemma4OnDevice (when model is downloaded)
       └── onDevice (always available, zero setup)
```

The `OnDeviceStoryOrchestrator` (new `@MainActor` actor) resolves which mode actually runs based on:
1. User preference (`UserDefaults.storyMode`)
2. Network reachability (for `cloud` mode)
3. GGUF file presence in Documents (for `gemma4OnDevice`)

---

## 4. iOS Implementation Plan (Branch: `gemma-4-integration`)

Create this branch from `on-device-pipeline` HEAD, not `main`.

### Step 4.1 — Extend `StoryGenerationMode`

File: `SeeSaw/Model/StoryGenerationMode.swift`

Add `case gemma4OnDevice` with:
- `rawValue`: `"gemma4OnDevice"`
- `displayName`: `"Gemma 4 (Enhanced On-Device)"`
- `description`: `"Fine-tuned open model · ~800 MB one-time download"`
- New computed properties: `var requiresDownload: Bool` and `var requiresNetwork: Bool`

### Step 4.2 — Create `Gemma4StoryService`

New file: `SeeSaw/Services/AI/Gemma4StoryService.swift`

```swift
import MediaPipeTasksGenAI
import Foundation

actor Gemma4StoryService {

    static let modelFilename  = "seesaw-gemma4-1b-q4km"
    static let modelExtension = "gguf"
    static let modelCDNEndpoint = "/model/latest"   // appended to cloudAgentURL

    private var inference: LlmInference?

    private let systemPrompt = """
        You are SeeSaw, a gentle and imaginative storytelling companion for children aged 4-8.
        Each response must be a JSON object with exactly three fields:
        - "storyText": 2-3 sentences (40-80 words), simple vocabulary, second-person present tense
        - "question": one open-ended question (max 15 words) inviting the child to respond
        - "isEnding": boolean — true only if this is a natural story conclusion
        Never include violence, fear, or adult themes. Always address the child by name.
        Respond with valid JSON only, no markdown fences.
        """

    var isLoaded: Bool { inference != nil }

    func loadModel() async throws {
        let url = modelFileURL()
        guard FileManager.default.fileExists(atPath: url.path) else {
            throw Gemma4Error.modelNotDownloaded
        }
        var options = LlmInference.Options(modelPath: url.path)
        options.maxTokens = 200
        options.temperature = 0.8
        options.randomSeed = 42
        options.topK = 40
        inference = try LlmInference(options: options)
    }

    func generateBeat(
        context: SceneContext,
        profile: ChildProfile,
        history: [StoryTurn]
    ) async throws -> StoryBeat {
        guard let inference else { throw Gemma4Error.modelNotLoaded }
        let prompt = buildPrompt(context: context, profile: profile, history: history)
        let raw = try await inference.generateResponse(inputText: prompt)
        return try parseStoryBeat(raw)
    }

    func unload() { inference = nil }

    func modelFileURL() -> URL {
        FileManager.default.urls(for: .documentDirectory, in: .userDomainMask)[0]
            .appendingPathComponent("\(Self.modelFilename).\(Self.modelExtension)")
    }

    // MARK: - Private

    private func buildPrompt(context: SceneContext, profile: ChildProfile, history: [StoryTurn]) -> String {
        let objects = context.objects.isEmpty ? "some interesting things" : context.objects.joined(separator: ", ")
        let scene   = context.scene.isEmpty   ? "a cozy space"           : context.scene.joined(separator: ", ")
        let recent  = history.suffix(3).map { "\($0.role == .model ? "Story" : profile.name): \($0.text)" }
                               .joined(separator: "\n")
        let user = """
            Child's name: \(profile.name), age: \(profile.age)
            Objects visible: \(objects)
            Scene: \(scene)
            \(history.isEmpty ? "" : "Recent story:\n\(recent)\n")
            Continue the story. Respond with JSON only.
            """
        // Gemma 4 chat template
        return "<bos><start_of_turn>user\n\(systemPrompt)\n\n\(user)<end_of_turn>\n<start_of_turn>model\n"
    }

    private func parseStoryBeat(_ raw: String) throws -> StoryBeat {
        let clean = raw
            .trimmingCharacters(in: .whitespacesAndNewlines)
            .replacingOccurrences(of: "```json", with: "")
            .replacingOccurrences(of: "```", with: "")
            .trimmingCharacters(in: .whitespacesAndNewlines)
        guard let data = clean.data(using: .utf8),
              let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              let storyText = json["storyText"] as? String,
              let question  = json["question"]  as? String
        else { throw Gemma4Error.parseFailure(raw) }
        return StoryBeat(storyText: storyText, question: question, isEnding: json["isEnding"] as? Bool ?? false)
    }
}

enum Gemma4Error: LocalizedError {
    case modelNotDownloaded
    case modelNotLoaded
    case parseFailure(String)
    var errorDescription: String? {
        switch self {
        case .modelNotDownloaded:   return "Gemma 4 model not downloaded. Go to Settings to download."
        case .modelNotLoaded:       return "Gemma 4 model is not loaded."
        case .parseFailure(let r):  return "Failed to parse Gemma 4 response: \(r.prefix(100))"
        }
    }
}
```

**Note:** No context window management needed. Gemma 4 1B has a 32K token context window. A full 8-turn session with rolling history is ~2K tokens. Use a simple `history.suffix(6)` window — no `restartWithSummary` equivalent required.

### Step 4.3 — Create `ModelDownloadManager`

New file: `SeeSaw/Services/AI/ModelDownloadManager.swift`

```swift
import Foundation

@MainActor
@Observable
final class ModelDownloadManager: NSObject {

    var progress: Double = 0
    var isDownloading: Bool = false
    var isModelReady: Bool = false
    var errorMessage: String?

    private var downloadTask: URLSessionDownloadTask?

    override init() {
        super.init()
        isModelReady = FileManager.default.fileExists(atPath: localModelURL.path)
    }

    var localModelURL: URL {
        FileManager.default.urls(for: .documentDirectory, in: .userDomainMask)[0]
            .appendingPathComponent("\(Gemma4StoryService.modelFilename).\(Gemma4StoryService.modelExtension)")
    }

    func downloadModel(cloudAgentBaseURL: String) async {
        guard !isModelReady, !isDownloading else { return }
        isDownloading = true; errorMessage = nil; progress = 0

        // Fetch signed download URL from cloud endpoint
        let metaURL = URL(string: "\(cloudAgentBaseURL)\(Gemma4StoryService.modelCDNEndpoint)")
                      ?? URL(string: "https://cdn.seesaw.app/model/latest")!
        var downloadURL = metaURL
        if let (data, _) = try? await URLSession.shared.data(from: metaURL),
           let json = try? JSONSerialization.jsonObject(with: data) as? [String: String],
           let urlStr = json["download_url"],
           let url = URL(string: urlStr) {
            downloadURL = url
        }

        let session = URLSession(configuration: .default, delegate: self, delegateQueue: nil)
        downloadTask = session.downloadTask(with: downloadURL)
        downloadTask?.resume()
    }

    func cancelDownload() {
        downloadTask?.cancel()
        isDownloading = false
    }
}

extension ModelDownloadManager: URLSessionDownloadDelegate {
    nonisolated func urlSession(_ session: URLSession, downloadTask: URLSessionDownloadTask,
                                 didFinishDownloadingTo location: URL) {
        do {
            let dest = localModelURL
            if FileManager.default.fileExists(atPath: dest.path) {
                try FileManager.default.removeItem(at: dest)
            }
            try FileManager.default.moveItem(at: location, to: dest)
            Task { @MainActor [weak self] in self?.isModelReady = true; self?.isDownloading = false; self?.progress = 1 }
        } catch {
            Task { @MainActor [weak self] in self?.isDownloading = false; self?.errorMessage = error.localizedDescription }
        }
    }

    nonisolated func urlSession(_ session: URLSession, downloadTask: URLSessionDownloadTask,
                                 didWriteData _: Int64, totalBytesWritten: Int64, totalBytesExpectedToWrite: Int64) {
        guard totalBytesExpectedToWrite > 0 else { return }
        let p = Double(totalBytesWritten) / Double(totalBytesExpectedToWrite)
        Task { @MainActor [weak self] in self?.progress = p }
    }

    nonisolated func urlSession(_ session: URLSession, task: URLSessionTask, didCompleteWithError error: Error?) {
        guard let error else { return }
        Task { @MainActor [weak self] in self?.isDownloading = false; self?.errorMessage = error.localizedDescription }
    }
}
```

### Step 4.4 — Wire into `AppDependencyContainer`

```swift
// Add to AppDependencyContainer properties:
let gemma4StoryService: Gemma4StoryService
let modelDownloadManager: ModelDownloadManager

// Add to init():
gemma4StoryService   = Gemma4StoryService()
modelDownloadManager = ModelDownloadManager()

// Update makeCompanionViewModel():
CompanionViewModel(
    ...,                              // all existing params unchanged
    gemma4StoryService: gemma4StoryService
)
```

### Step 4.5 — Update `CompanionViewModel`

Add `private let gemma4StoryService: Gemma4StoryService` and update `runFullPipeline()`:

```swift
private func runFullPipeline(jpegData: Data) async {
    switch storyMode {
    case .onDevice:
        await runOnDevicePipeline(jpegData: jpegData)       // EXISTING — unchanged
    case .gemma4OnDevice:
        await runGemma4Pipeline(jpegData: jpegData)         // NEW
    case .cloud:
        await runCloudPipeline(jpegData: jpegData)          // EXISTING — unchanged
    }
}

// New method — mirrors runOnDevicePipeline structure but uses Gemma4StoryService
private func runGemma4Pipeline(jpegData: Data) async {
    do {
        // Load model if not already loaded
        if !await gemma4StoryService.isLoaded {
            try await gemma4StoryService.loadModel()
        }
        // Run same privacy pipeline as onDevice mode
        sessionState = .processingPrivacy
        let result = try await privacyPipeline.process(jpegData: jpegData, childAge: childAge)
        // ... same beginStorySession, recordBeat, speak, listen loop
        // ... using gemma4StoryService.generateBeat() instead of onDeviceStoryService
        // ... no context restart logic needed (32K window, use history.suffix(6))
    } catch is Gemma4Error {
        // Graceful fallback to Apple FM
        AppConfig.shared.log("Gemma4 unavailable, falling back to Apple FM", level: .warning)
        await runOnDevicePipeline(jpegData: jpegData)
    } catch {
        setError(error.localizedDescription)
    }
}
```

### Step 4.6 — Update `SettingsTabView`

Add a **Story Engine** section above the existing wearable section:

```
Story Engine
  Picker (segmented or radio):
    ○ Apple FM        Built-in, always available
    ● Gemma 4         Enhanced, 800 MB download
    ○ Cloud           Requires internet + server URL

  [Shown only when gemma4OnDevice is selected:]
  ┌─────────────────────────────────────────┐
  │  Gemma 4 Model                          │
  │  Fine-tuned for children's storytelling │
  │  ~800 MB · One-time download            │
  │                                         │
  │  [Not downloaded]                       │
  │  ProgressView(value: manager.progress)  │
  │  [Download Model]    [Cancel]           │
  │                                         │
  │  [Downloaded] ✓ Ready                   │
  └─────────────────────────────────────────┘
```

### Step 4.7 — Add MediaPipe dependency

In Xcode → Package Dependencies → Add:
```
https://github.com/google/mediapipe-swift-package-manager
Product: MediaPipeTasksGenAI
```
Or via CocoaPods: `pod 'MediaPipeTasksGenAI'`
Minimum iOS 16+ — compatible with project's iOS 26+ minimum.

---

## 5. Cloud Backend (`j2damax/seesaw-cloud-agent`)

### Repository Structure

```
seesaw-cloud-agent/
├── app/
│   ├── main.py
│   ├── routers/
│   │   ├── story.py          # POST /story/generate
│   │   ├── session.py        # GET/POST /session/{id}
│   │   ├── model.py          # GET /model/latest  (signed CDN URL)
│   │   └── health.py         # GET /health
│   ├── agents/
│   │   ├── story_agent.py    # Google ADK + Gemini 2.0 Flash
│   │   └── safety_agent.py   # ShieldGemma 4 classifier (T3-018)
│   ├── models/
│   │   ├── scene_payload.py  # Mirrors iOS ScenePayload struct
│   │   └── story_beat.py     # Mirrors iOS StoryBeat struct
│   ├── services/
│   │   ├── firestore.py      # Session persistence
│   │   └── model_cdn.py      # GCS signed URL generation
│   └── config.py
├── training/
│   ├── data_prep.ipynb       # Colab: dataset preparation
│   ├── finetune.ipynb        # Colab: LoRA fine-tuning on Vertex AI
│   └── export_gguf.ipynb     # Colab: GGUF export + INT4 quantisation
├── docs/
│   ├── ARCHITECTURE.md
│   ├── PRIVACY_CONTRACT.md
│   ├── API_REFERENCE.md
│   ├── DEPLOYMENT.md
│   └── FINE_TUNING.md
├── Dockerfile
├── cloudbuild.yaml
├── requirements.txt
└── README.md
```

### API Contract (Fixed — matches existing iOS `CloudAgentService`)

**POST /story/generate**

Request (what iOS already sends):
```json
{
  "objects": ["teddy_bear", "book", "sofa"],
  "scene": ["living_room"],
  "transcript": "I love this bear",
  "child_age": 5,
  "child_name": "Vihas",
  "story_history": [
    { "role": "model", "text": "Once upon a time..." },
    { "role": "user",  "text": "I love this bear" }
  ],
  "session_id": "uuid-string"
}
```

Response (what iOS `CloudAgentService` expects):
```json
{
  "story_text": "Vihas held the bear close as it whispered secrets...",
  "question": "What do you think the bear is dreaming about?",
  "is_ending": false,
  "session_id": "uuid-string",
  "beat_index": 1
}
```

**Do not change these field names** — they are hardcoded in the existing iOS `CloudAgentService.swift`.

**GET /model/latest**

Response:
```json
{
  "download_url": "https://storage.googleapis.com/seesaw-models/seesaw-gemma4-1b-q4km.gguf?X-Goog-Signature=...",
  "model_version": "1.0.0",
  "size_bytes": 850000000,
  "expires_at": "2026-04-12T19:00:00Z"
}
```

**GET /health**

Response: `{"status": "ok", "version": "1.0.0"}`

### Core Backend Code

**app/main.py**
```python
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from app.routers import story, session, model, health
from app.config import Settings

settings = Settings()
app = FastAPI(title="SeeSaw Cloud Agent", version="1.0.0")

app.add_middleware(CORSMiddleware, allow_origins=["*"],
                   allow_methods=["POST", "GET"], allow_headers=["*"])

@app.middleware("http")
async def verify_api_key(request: Request, call_next):
    if request.url.path != "/health":
        key = request.headers.get("X-SeeSaw-Key", "")
        if key != settings.api_key:
            from fastapi.responses import JSONResponse
            return JSONResponse({"error": "Unauthorized"}, status_code=401)
    return await call_next(request)

app.include_router(health.router)
app.include_router(story.router,   prefix="/story")
app.include_router(session.router, prefix="/session")
app.include_router(model.router,   prefix="/model")
```

**app/agents/story_agent.py**
```python
from google.adk.agents import LlmAgent
from google.adk.models.lite_llm import LiteLlm

STORY_SYSTEM_PROMPT = """
You are SeeSaw, a gentle AI storytelling companion for children aged 3-8.
You receive: a scene (detected objects + child speech) and a story history.
Generate the next story beat: 2-3 sentences (40-80 words), simple vocabulary,
second-person present tense, always ending with an open question for the child.
Never include violence, fear, darkness, or adult themes.
Always address the child by their name.
Respond with JSON only:
{"story_text": "...", "question": "...", "is_ending": false}
"""

story_agent = LlmAgent(
    name="seesaw_story_agent",
    model=LiteLlm(model="gemini/gemini-2.0-flash"),
    instruction=STORY_SYSTEM_PROMPT
)
```

**Dockerfile**
```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app/ ./app/
EXPOSE 8080
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
```

**requirements.txt**
```
fastapi==0.115.0
uvicorn==0.30.0
google-adk==0.2.0
google-cloud-firestore==2.19.0
google-cloud-storage==2.18.0
pydantic==2.7.0
pydantic-settings==2.3.0
```

**Cloud Run deploy command:**
```bash
gcloud run deploy seesaw-cloud-agent \
  --source . \
  --region europe-west1 \
  --platform managed \
  --allow-unauthenticated \
  --set-secrets GEMINI_API_KEY=GEMINI_API_KEY:latest,SEESAW_API_KEY=SEESAW_API_KEY:latest \
  --memory 1Gi \
  --min-instances 0 \
  --max-instances 3
```

---

## 6. Gemma 4 Fine-Tuning (Google Colab)

Run the notebooks in `training/` in order. Each notebook is self-contained and can run on a free Colab T4 instance except finetune.ipynb which requires Vertex AI.

### Notebook 1: `data_prep.ipynb`
- Load `roneneldan/TinyStories` from HuggingFace (2M stories)
- Sample 10,000 examples
- Convert to SeeSaw instruction format (system/user/assistant chat template)
- Apply safety filter (block violence/fear terms)
- Add any `StoryBeatRecord` exports from the iOS app (highest value — domain-specific)
- Target: 6,000–8,000 clean training examples
- Save to `gs://seesaw-models/training-data/seesaw_beats_train.jsonl`

### Notebook 2: `finetune.ipynb`
- Load Gemma 4 1B instruction-tuned base (`google/gemma-4-1b-it`) in 4-bit
- LoRA config: `r=16, alpha=32, target_modules=["q_proj","v_proj","k_proj","o_proj"]`
- 3 epochs, batch=4, grad_accum=4, lr=2e-4, cosine schedule
- Submit as Vertex AI custom training job (T4 GPU, ~3h, ~$6)
- Save best checkpoint to `gs://seesaw-models/checkpoints/`

### Notebook 3: `export_gguf.ipynb`
- Merge LoRA adapters into base model
- Convert to GGUF via llama.cpp `convert_hf_to_gguf.py`
- Quantise to Q4_K_M: `./llama-quantize model-f16.gguf model-q4km.gguf Q4_K_M`
- Validate: run 3 sample inferences on desktop, check JSON output parses correctly
- Upload to `gs://seesaw-models/seesaw-gemma4-1b-q4km.gguf`
- Expected size: ~800 MB

---

## 7. Documentation to Write First in `seesaw-cloud-agent`

Write these docs before any code. They carry forward all context from the iOS repo.

### `docs/ARCHITECTURE.md`
- Three-tier architecture diagram (on-device → Gemma 4 → cloud)
- Privacy boundary: `ScenePayload` only crosses to LLM
- Six-stage privacy pipeline description
- iOS app structure: actors, DI container, coordinator
- Three `StoryGenerationMode` cases and their fallback chain
- Reference to `seesaw-companion-ios/on-device-pipeline` branch

### `docs/PRIVACY_CONTRACT.md`
- What the cloud endpoint receives: object labels + scrubbed transcript only
- What it **never** receives: pixels, raw audio, face data, bounding boxes, raw names
- `rawDataTransmitted = false` invariant — enforced in iOS, auditable in `StorySessionRecord`
- GDPR/COPPA compliance note for cloud path
- Firestore data retention: sessions auto-deleted after 30 days
- Parent dashboard data: pseudonymised session IDs only

### `docs/API_REFERENCE.md`
- Full schemas for all endpoints with examples
- Authentication: `X-SeeSaw-Key` header (set in iOS Settings → Cloud Agent Key)
- Error codes and their iOS handling behaviour
- Rate limit: 10 req/min per IP (Cloud Run default)

### `docs/FINE_TUNING.md`
- Dataset sources, counts, and safety filtering approach
- LoRA configuration rationale
- Vertex AI job setup steps
- Expected training metrics (target eval_loss < 1.5)
- GGUF export and validation steps
- HuggingFace model card template for publishing SeeSaw-Gemma-1B open-weight

---

## 8. GitHub Project Board Task List

**Board:** https://github.com/users/j2damax/projects/4/views/7
**Repo:** j2damax/seesaw-cloud-agent

Archive any existing tasks that pre-date this plan. Create these:

### Day 1 — Cloud Foundation
| ID | Title | Label | Day |
|----|-------|-------|-----|
| T3-001 | GCP project setup — APIs, service account, IAM | `setup` | D1 AM |
| T3-002 | Firebase Firestore provisioned (Native mode, europe-west2) | `setup` | D1 AM |
| T3-003 | Secret Manager: GEMINI_API_KEY + SEESAW_API_KEY | `setup` | D1 AM |
| T3-004 | Repo structure bootstrapped — all dirs + placeholder files | `setup` | D1 AM |
| T3-005 | docs/: ARCHITECTURE + PRIVACY_CONTRACT + API_REFERENCE written | `docs` | D1 AM |
| T3-006 | FastAPI skeleton + /health deployed to Cloud Run | `backend` | D1 PM |
| T3-007 | POST /story/generate — Google ADK + Gemini 2.0 Flash | `backend` | D1 PM |
| T3-008 | iOS end-to-end test: Cloud mode → Cloud Run → StoryBeat response | `integration` | D1 PM |
| T3-009 | Firestore: session create/read/append beats | `backend` | D1 PM |

### Day 2 — Gemma 4 + iOS Mode 2
| ID | Title | Label | Day |
|----|-------|-------|-----|
| T3-010 | Colab data_prep.ipynb: TinyStories → SeeSaw format | `ml` | D2 AM |
| T3-011 | Colab finetune.ipynb: Vertex AI LoRA training job launched | `ml` | D2 AM |
| T3-012 | Colab export_gguf.ipynb: GGUF Q4_K_M export + validation | `ml` | D2 PM |
| T3-013 | GCS bucket + model upload + GET /model/latest endpoint | `backend` | D2 AM |
| T3-014 | iOS: Gemma4StoryService + ModelDownloadManager (Step 4.2–4.3) | `ios` | D2 AM |
| T3-015 | iOS: AppDependencyContainer + CompanionViewModel wired (Step 4.4–4.5) | `ios` | D2 AM |
| T3-016 | iOS: SettingsTabView Story Engine section (Step 4.6) | `ios` | D2 PM |
| T3-017 | iOS: MediaPipe dependency added + build green | `ios` | D2 PM |
| T3-018 | iOS: Mode 2 end-to-end test — download → generate → Timeline stores | `integration` | D2 PM |
| T3-019 | docs/FINE_TUNING.md complete with actual training metrics | `docs` | D2 PM |

### Post-Sprint (Nice to Have)
| ID | Title | Label |
|----|-------|-------|
| T3-020 | ShieldGemma 4 safety classifier replacing regex filter in cloud path | `ml` |
| T3-021 | HuggingFace model card: publish SeeSaw-Gemma-1B | `ml` |
| T3-022 | Firestore model version tracking + iOS update notification | `backend` |
| T3-023 | Parent dashboard API (story history, like counts, session export) | `backend` |

---

## 9. 2-Day Schedule

### Day 1 (Cloud live by end of day)

| Time | Action | Done When |
|------|--------|-----------|
| 09:00 | GCP project, APIs, Firebase, Secret Manager (T3-001–003) | Console shows all green |
| 10:00 | Clone `seesaw-cloud-agent`, create repo structure (T3-004) | `git push` succeeds |
| 11:00 | Write docs/ (T3-005) — use Claude with this prompt as context | 4 .md files committed |
| 12:00 | FastAPI skeleton + health endpoint (T3-006) | `/health` returns `{"status":"ok"}` |
| 13:00 | POST /story/generate with ADK story_agent (T3-007) | Local `curl` test passes |
| 14:00 | `gcloud run deploy` — Cloud Run URL obtained | URL in browser shows /health |
| 15:00 | iOS: set cloudAgentURL in Settings → Run story in Cloud mode (T3-008) | Story plays from Cloud Run |
| 16:00 | Firestore session persistence (T3-009) | Firestore console shows session doc |
| 17:00 | Launch `data_prep.ipynb` on Colab (runs ~2h unattended) | Colab cell running |

### Day 2 (Gemma 4 on-device by end of day)

| Time | Action | Done When |
|------|--------|-----------|
| 09:00 | Check Colab output → launch `finetune.ipynb` Vertex AI job (T3-011) | Vertex AI job running |
| 09:30 | GET /model/latest endpoint + GCS bucket setup (T3-013) | Signed URL returned |
| 10:00 | iOS: Gemma4StoryService + ModelDownloadManager (T3-014) | Files compile |
| 11:00 | iOS: DI container + CompanionViewModel + Settings UI (T3-015–016) | App builds, mode picker visible |
| 12:00 | iOS: MediaPipe SPM dependency (T3-017) | BUILD SUCCEEDED |
| 13:00 | Vertex AI job completes → run `export_gguf.ipynb` (T3-012) | GGUF validated on desktop |
| 14:00 | Upload GGUF to GCS (T3-013 complete) | `/model/latest` returns GGUF URL |
| 15:00 | iOS: trigger model download in Settings, wait, run story in Gemma 4 mode (T3-018) | Story beat generated on-device |
| 16:00 | Verify Timeline stores session with storyMode="gemma4OnDevice" | SwiftData record visible |
| 17:00 | Update project board, commit to both repos | Sprint complete |

---

## 10. Key Constraints

1. **`gemma-4-integration` branch starts from `on-device-pipeline` HEAD** — never from `main`.

2. **Additive only.** No existing file outside `StoryGenerationMode.swift`, `AppDependencyContainer.swift`, `CompanionViewModel.swift`, and `SettingsTabView.swift` should be modified. Add new files; extend existing ones minimally.

3. **Privacy boundary is unchanged for cloud mode.** The cloud endpoint receives `ScenePayload` labels + scrubbed transcript only. No pixels, no audio, no faces. Document this in `PRIVACY_CONTRACT.md` before writing any cloud code.

4. **`StoryBeat` struct is immutable.** `Gemma4StoryService` parses its JSON response into the existing `StoryBeat` type. Do not add new fields to `StoryBeat`.

5. **`StoryTimelineStore` records every mode.** `StorySessionRecord.storyMode` stores `"gemma4OnDevice"` or `"cloud"` as appropriate. No other Timeline code changes.

6. **Graceful degradation is mandatory.** If Gemma 4 model not downloaded, or cloud endpoint unreachable, silently fall back to Apple FM. No child-visible error. Parent sees status in Settings only.

7. **GGUF file in Documents, not bundle.** ~800 MB cannot go in the app bundle. `Gemma4StoryService.modelFileURL()` always points to `FileManager.documentDirectory`.

8. **Cloud Run authentication.** `--allow-unauthenticated` on Cloud Run is acceptable for the MSc prototype. Add `X-SeeSaw-Key` middleware in FastAPI as first-line abuse prevention.

9. **iOS `cloudAgentURL` key already exists.** `UserDefaults.standard.cloudAgentURL` is already wired in `CloudAgentService`. The parent sets this URL in Settings after deploying Cloud Run. No new UserDefaults keys needed for the cloud endpoint.

10. **129 tests must still pass after iOS changes.** Run `xcodebuild test -scheme SeeSaw -destination 'platform=iOS Simulator,name=iPhone 17'` before committing any iOS changes.

---

## 11. How to Start Each Work Session

### Cloud backend session (in `seesaw-cloud-agent` repo)
```
Open Claude Code in the seesaw-cloud-agent directory.
Paste this document as the first message or reference as CLAUDE.md context.
Say: "Implement Task T3-[ID] as specified in the Enhanced Claude Agent Prompt.
      The API contract in Section 5 is fixed — do not change field names."
```

### iOS session (in `seesaw-companion-ios` on `gemma-4-integration` branch)
```
Open Claude Code in seesaw-companion-ios.
Paste this document + CLAUDE.md as context.
Say: "Implement iOS Step 4.[X] from the Enhanced Claude Agent Prompt.
      Do not modify any files from the on-device-pipeline feature.
      Only touch: StoryGenerationMode.swift, AppDependencyContainer.swift,
      CompanionViewModel.swift, SettingsTabView.swift.
      Create new files: Gemma4StoryService.swift, ModelDownloadManager.swift."
```

### Colab notebook session
```
Open a new Colab notebook.
Say to Claude: "Generate the complete content for training/[notebook].ipynb
                using the dataset sources and code patterns in Section 6
                of the Enhanced Claude Agent Prompt."
Copy the generated cells into Colab and run.
```

---

*This document is the single source of truth for the Gemma 4 integration sprint.
All implementation decisions should be validated against Section 10 constraints before proceeding.
Reference: Gemma 4 & On-Device Tier 3: Analysis and Revised Blueprint.md for model specs.*
