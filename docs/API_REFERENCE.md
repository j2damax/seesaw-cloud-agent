# SeeSaw Cloud Agent — API Reference

**Base URL:** `https://seesaw-cloud-agent-[hash]-ew.a.run.app`  
**Set in iOS:** Settings → Cloud Agent URL  
**Authentication:** `X-SeeSaw-Key: {SEESAW_API_KEY}` header on all requests except `/health`

---

## Endpoints

### POST /story/generate

Generates the next story beat from a scene payload. The primary endpoint consumed by the iOS `CloudAgentService`.

**Do not rename fields.** They are hardcoded in `CloudAgentService.swift` on the iOS side.

#### Request

```http
POST /story/generate
Content-Type: application/json
X-SeeSaw-Key: your-secret-key
```

```json
{
  "objects": ["teddy_bear", "book", "sofa"],
  "scene": ["living_room"],
  "transcript": "I love this bear",
  "child_age": 5,
  "child_name": "Vihas",
  "story_history": [
    { "role": "model", "text": "Vihas held the bear close as the adventure began." },
    { "role": "user",  "text": "I love this bear" }
  ],
  "session_id": "3f9a1b2c-4d5e-6f7g-8h9i-0j1k2l3m4n5o"
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `objects` | `[string]` | Yes | YOLO-detected object labels |
| `scene` | `[string]` | Yes | Scene classification labels |
| `transcript` | `string \| null` | No | PII-scrubbed child speech |
| `child_age` | `int` | Yes | Child's age (3–12) |
| `child_name` | `string` | Yes | Child's first name |
| `story_history` | `[StoryTurn]` | No | Previous turns (omit for first beat) |
| `session_id` | `string \| null` | No | UUID; omit to start a new session |

**StoryTurn:**
```json
{ "role": "model" | "user", "text": "..." }
```

#### Response (200 OK)

```json
{
  "story_text": "Vihas held the bear close as it whispered a secret about the magical forest beyond the sofa.",
  "question": "What do you think the bear whispered?",
  "is_ending": false,
  "session_id": "3f9a1b2c-4d5e-6f7g-8h9i-0j1k2l3m4n5o",
  "beat_index": 1
}
```

| Field | Type | Description |
|-------|------|-------------|
| `story_text` | `string` | 2–3 sentences, 40–80 words, child-appropriate |
| `question` | `string` | Open-ended question for child (max 15 words) |
| `is_ending` | `bool` | `true` only on final story beat |
| `session_id` | `string` | Echo of request session_id (or newly created UUID) |
| `beat_index` | `int` | 0-indexed beat count within this session |

#### Error Responses

| Status | Body | When |
|--------|------|------|
| `401` | `{"error": "Unauthorized"}` | Missing or wrong `X-SeeSaw-Key` |
| `422` | Pydantic validation detail | Required field missing or wrong type |
| `503` | `{"error": "Story generation failed", "detail": "..."}` | Gemini API error |
| `500` | `{"error": "Internal server error"}` | Unexpected exception |

#### iOS Handling

The iOS `CloudAgentService` decodes the response into `StoryResponse`:

```swift
struct StoryResponse: Codable {
    let storyText: String    // snake_case → camelCase via JSONDecoder keyDecodingStrategy
    let question: String
    let isEnding: Bool
}
```

The `session_id` and `beat_index` fields are decoded but not currently used on the iOS side (they exist for future parent dashboard features).

---

### GET /model/latest

Returns a signed GCS URL for downloading the Gemma 4 1B GGUF model. The iOS `ModelDownloadManager` calls this endpoint to resolve the download URL.

```http
GET /model/latest
X-SeeSaw-Key: your-secret-key
```

#### Response (200 OK)

```json
{
  "download_url": "https://storage.googleapis.com/seesaw-models/seesaw-gemma4-1b-q4km.gguf?X-Goog-Signature=...&expires=...",
  "model_version": "1.0.0",
  "size_bytes": 850000000,
  "expires_at": "2026-04-13T19:00:00Z"
}
```

| Field | Type | Description |
|-------|------|-------------|
| `download_url` | `string` | Signed GCS URL, valid for 1 hour |
| `model_version` | `string` | Semantic version of the GGUF model |
| `size_bytes` | `int` | File size for progress display (~850 MB) |
| `expires_at` | `string` | ISO 8601 UTC expiry of the signed URL |

The iOS `ModelDownloadManager` uses this URL directly with `URLSession.downloadTask`. If the endpoint is unreachable, iOS falls back to the hardcoded GCS URL in `UserDefaults.standard.gemma4ModelURL`.

---

### GET /session/{session_id}

Retrieves a stored session's beats for the parent dashboard (post-sprint feature).

```http
GET /session/3f9a1b2c-4d5e-6f7g-8h9i-0j1k2l3m4n5o
X-SeeSaw-Key: your-secret-key
```

#### Response (200 OK)

```json
{
  "session_id": "3f9a1b2c-...",
  "child_age": 5,
  "objects": ["teddy_bear", "book"],
  "beat_count": 4,
  "created_at": "2026-04-12T19:00:00Z",
  "beats": [
    {
      "beat_index": 0,
      "story_text": "...",
      "question": "...",
      "is_ending": false
    }
  ]
}
```

#### 404 Response

```json
{ "error": "Session not found" }
```

---

### DELETE /session/{session_id}

Deletes a session and all its beats (GDPR right to erasure). Called from the iOS app's Timeline delete action.

```http
DELETE /session/3f9a1b2c-...
X-SeeSaw-Key: your-secret-key
```

#### Response (200 OK)

```json
{ "deleted": true }
```

---

### GET /health

Health check. Does not require authentication. Used by Cloud Run health probes.

```http
GET /health
```

#### Response (200 OK)

```json
{
  "status": "ok",
  "version": "1.0.0"
}
```

---

## Rate Limits

Cloud Run default: 80 concurrent requests per instance. Story generation is I/O-bound (Gemini API call, ~1–3s). At 1 Gi memory and min-instances=0, cold start is ~2s.

Practical limit for MSc prototype: 10 concurrent sessions. No additional rate limiting implemented.

---

## Authentication Details

All endpoints except `/health` require the `X-SeeSaw-Key` header:

```python
# FastAPI middleware (app/main.py)
async def verify_api_key(request: Request, call_next):
    if request.url.path != "/health":
        key = request.headers.get("X-SeeSaw-Key", "")
        if key != settings.api_key:
            return JSONResponse({"error": "Unauthorized"}, status_code=401)
    return await call_next(request)
```

The `SEESAW_API_KEY` is stored in GCP Secret Manager and injected into Cloud Run at deploy time. The parent sets the same key in the iOS app under Settings → Cloud Agent Key (stored in `UserDefaults`).

---

## Changelog

| Version | Date | Change |
|---------|------|--------|
| 1.0.0 | 2026-04-12 | Initial API (Sprint 3) |
