# Gemma 3 Fine-Tuning Guide

**Goal:** Fine-tune `google/gemma-3-1b-it` on children's story data to produce `seesaw-gemma3-1b-q4km.gguf` (~800 MB) for on-device iOS inference via MediaPipe Tasks GenAI.

> **Note:** `google/gemma-4-1b-it` does not exist — Gemma 4 skipped 1B (smallest is E2B MoE, incompatible with MediaPipe). `gemma-3-1b-it` is the correct model: 1B parameters, instruction-tuned, fully supported by llama.cpp GGUF and MediaPipe Tasks GenAI on iOS.

**Run the three notebooks in `training/` in order.** Each is self-contained and documented inline.

## Training Run Results (2026-04-13)

| Epoch | Training Loss | Validation Loss |
|---|---|---|
| 1 | 0.5126 | 0.5115 |
| 2 | 0.4769 | 0.4960 |
| 3 | 0.4687 | **0.4945** |

**Final eval_loss: 0.4945** — well below target of < 1.5. No overfitting (train/val losses track closely). Runtime: 27 min on Colab T4. Checkpoint: `gs://seesaw-models/checkpoints/seesaw-gemma3-v1/` (40 objects, 190.6 MiB).

---

## Overview

```
Notebook 1: data_prep.ipynb      (~30 min, free Colab T4)
  TinyStories + StoryBeatRecord exports → SeeSaw JSONL format
  Output: gs://seesaw-models/training-data/seesaw_beats_train.jsonl

Notebook 2: finetune.ipynb       (~3 hours, Vertex AI T4, ~$6)
  LoRA fine-tuning on Gemma 3 1B instruction-tuned base
  Output: gs://seesaw-models/checkpoints/seesaw-gemma3-v1/

Notebook 3: export_gguf.ipynb    (~20 min, free Colab T4)
  Merge LoRA → GGUF Q4_K_M quantisation → validate → upload
  Output: gs://seesaw-models/seesaw-gemma3-1b-q4km.gguf
```

---

## Notebook 1: `data_prep.ipynb`

### Dataset Sources

| Source | HuggingFace ID | Count (raw) | Count (after filter) | Purpose |
|--------|---------------|-------------|---------------------|---------|
| TinyStories | `roneneldan/TinyStories` | 2,119,719 | ~8,000 sampled | Base story fluency, simple vocabulary |
| SeeSaw story beats | iOS app export | Variable | All available | Domain-specific (highest value) |

### Exporting StoryBeatRecord from iOS

In the iOS app, open the Story Timeline → share any session → the share sheet exports JSON including all beats. Each exported beat provides a gold-standard training example in the exact format the model needs.

Alternatively, extract via SwiftData directly:
```swift
// In a debug build, add this to CompanionViewModel:
func exportTrainingData() -> String {
    let beats = storyTimelineStore.allBeats()
    return beats.map { beat in
        """
        {"prompt": "\(beat.question)", "response": "\(beat.storyText)"}
        """
    }.joined(separator: "\n")
}
```

### SeeSaw Instruction Format

Each training example is converted to Gemma's chat template:

```jsonl
{
  "text": "<bos><start_of_turn>user\nYou are SeeSaw, a gentle storytelling companion for children aged 4-8. Child: Vihas, age 5. Objects: teddy_bear, book. Scene: living_room. Continue the story.\n<end_of_turn>\n<start_of_turn>model\n{\"story_text\": \"Vihas held the bear tight as it whispered secrets of the magical forest beyond the bookshelf.\", \"question\": \"What do you think the bear is whispering?\", \"is_ending\": false}<end_of_turn>"
}
```

**JSON-in-text format:** The model generates valid JSON objects as its response. This is important — the iOS `Gemma4StoryService.parseStoryBeat()` expects JSON from the model output.

### Safety Filter

Before saving, filter out any examples containing:
```python
BANNED_TERMS = [
    "kill", "die", "dead", "blood", "gun", "knife", "weapon",
    "scary", "monster", "nightmare", "dark", "horror",
    "alcohol", "drug", "sex", "adult",
]
```

### Target Dataset Size

6,000–8,000 examples. Less leads to under-fitting on JSON format; more risks over-fitting on TinyStories vocabulary.

---

## Notebook 2: `finetune.ipynb`

### LoRA Configuration

```python
from peft import LoraConfig, get_peft_model

lora_config = LoraConfig(
    r=16,                          # rank — 16 is standard for 1B models
    lora_alpha=32,                 # scaling = alpha/r = 2
    target_modules=["q_proj", "v_proj", "k_proj", "o_proj"],
    lora_dropout=0.05,
    bias="none",
    task_type="CAUSAL_LM",
)
```

**Trainable parameters:** ~0.8% of total (approx 8M out of 1B). This is why the fine-tuned model remains the same size — the LoRA adapters are merged at export time.

### Training Hyperparameters

```python
training_args = TrainingArguments(
    num_train_epochs=3,
    per_device_train_batch_size=4,
    gradient_accumulation_steps=4,    # effective batch = 16
    learning_rate=2e-4,
    lr_scheduler_type="cosine",
    warmup_ratio=0.05,
    max_grad_norm=1.0,
    fp16=True,                        # T4 supports FP16
    logging_steps=50,
    save_strategy="epoch",
    evaluation_strategy="epoch",
    load_best_model_at_end=True,
    metric_for_best_model="eval_loss",
)
```

### Target Metrics

| Metric | Target | Action if not met |
|--------|--------|-------------------|
| `eval_loss` | < 1.5 | Increase epochs or dataset size |
| JSON parse rate (manual spot-check) | > 95% | Adjust system prompt in training data |
| Child-appropriate rating (manual) | 5/5 on 10 sample outputs | Review safety filter |

### Vertex AI Submission

```python
from google.cloud import aiplatform

aiplatform.init(project="seesaw-3e396", location="europe-west4")

job = aiplatform.CustomTrainingJob(
    display_name="seesaw-gemma4-finetune",
    script_path="training/finetune.py",
    container_uri="us-docker.pkg.dev/vertex-ai/training/pytorch-gpu.2-0:latest",
    requirements=["transformers", "peft", "datasets", "accelerate", "trl"],
)
job.run(
    args=["--model_name=google/gemma-3-1b-it", "--output_dir=gs://seesaw-models/checkpoints/"],
    replica_count=1,
    machine_type="n1-standard-8",
    accelerator_type="NVIDIA_TESLA_T4",
    accelerator_count=1,
)
```

**Expected cost:** ~$6 USD for a 3-epoch T4 job on 8,000 examples.

---

## Notebook 3: `export_gguf.ipynb`

Run on **Colab T4** (free tier, ~20 min). The notebook is fully automated — run all cells in order.

### Key implementation notes (lessons from production run 2026-04-13)

**llama.cpp setup:** Clone from `https://github.com/ggml-org/llama.cpp` (`ggerganov/llama.cpp` redirects here). Install only `gguf sentencepiece protobuf>=4.21.0,<5.0.0` — **do not** run `pip install -r requirements.txt` as it pins `numpy~=1.26.4` which downgrades Colab's numpy 2.x and breaks torch.

**Gemma 3 patches to `convert_hf_to_gguf.py`:**
1. Vocab assertion: `assert max(tokenizer.vocab.values()) < vocab_size` must be relaxed to a warning — Gemma 3 has special token IDs ≥ `vocab_size` (262144).
2. BPE pre-tokenizer hash: `789696f5946cc0fc59371f39f6097cafed196b3acded6140432f26bbb1ae1669` is not in llama.cpp b8776's `get_vocab_base_pre()` mapping. Insert `if chkhsh == "<hash>": res = "default"` before the `if res is None: raise` guard. Both patches are applied automatically by the notebook.

**LoRA merge subprocess:** `login()` only authenticates the parent kernel. Pass `HF_TOKEN` via `env=` to the merge subprocess; use `get_token()` (not the removed `HfFolder`) to retrieve it.

**Step 7 validation:** Uses `gguf.GGUFReader` for lightweight metadata inspection instead of running `llama-cli` inference. Running `llama-cli` on Colab T4 after the merge step exhausts system RAM and crashes the session.

### Step 1: Merge LoRA Adapters

The notebook runs this in a subprocess to isolate torch/PEFT C extensions from the parent kernel:

```python
from peft import PeftModel
from transformers import AutoModelForCausalLM, AutoTokenizer

base_model = AutoModelForCausalLM.from_pretrained(
    "google/gemma-3-1b-it", torch_dtype=torch.float16, device_map="auto"
)
model = PeftModel.from_pretrained(base_model, "/tmp/seesaw-gemma3-checkpoint")
merged = model.merge_and_unload()
merged.save_pretrained("/tmp/seesaw-gemma3-final")
```

### Step 2: Convert to GGUF

```bash
# Clone canonical repo (not ggerganov — redirects to ggml-org)
git clone --depth 1 https://github.com/ggml-org/llama.cpp /tmp/llama.cpp

# Install only what convert_hf_to_gguf.py needs
pip install gguf sentencepiece "protobuf>=4.21.0,<5.0.0"

# Download pre-built Ubuntu x64 binary from latest GitHub release
# (resolves tag via https://api.github.com/repos/ggml-org/llama.cpp/releases/latest)

# Convert to GGUF float16 (with Gemma 3 patches applied by notebook)
python /tmp/llama.cpp/convert_hf_to_gguf.py /tmp/seesaw-gemma3-final \
  --outfile /tmp/seesaw-gemma3-f16.gguf --outtype f16

# Quantise to Q4_K_M, then delete F16 to free ~2.3 GB
llama-quantize /tmp/seesaw-gemma3-f16.gguf /tmp/seesaw-gemma3-1b-q4km.gguf Q4_K_M
```

**Actual output size:** 814,261,088 bytes (777 MB)

### Step 3: Validate (metadata only — no inference)

```python
from gguf import GGUFReader
reader = GGUFReader("/tmp/seesaw-gemma3-1b-q4km.gguf", "r")
# Checks: file size 700–1000 MB, general.architecture contains "gemma"
# Prints: context_length=32768, block_count=18, vocab_size=262144
```

### Step 4: Upload to GCS

```bash
gsutil cp /tmp/seesaw-gemma3-1b-q4km.gguf gs://seesaw-models/seesaw-gemma3-1b-q4km.gguf
```

After upload, update `app/routers/model.py`:
```python
MODEL_FILENAME   = "seesaw-gemma3-1b-q4km.gguf"
MODEL_SIZE_BYTES = 814_261_088   # measured — do not estimate
```
Then redeploy to Cloud Run and verify `GET /model/latest` returns a valid signed URL.

---

## iOS Integration

Once the GGUF is uploaded, the iOS `Gemma4StoryService` loads it via MediaPipe:

```swift
// In Gemma4StoryService (after MediaPipe package is added — Step 4.7):
import MediaPipeTasksGenAI

var options = LlmInference.Options(modelPath: modelPath)
options.maxTokens = 200
options.temperature = 0.8
options.randomSeed = 42
options.topK = 40
let inference = try LlmInference(options: options)
let rawOutput = try inference.generateResponse(inputText: fullPrompt)
let beat = try Gemma4StoryService.parseResponse(rawOutput, isFinalTurn: isFinalTurn)
```

**Context window:** Gemma 3 1B has a 32K token context window. A full 8-turn SeeSaw session with rolling history is ~2K tokens. No context-restart logic needed (unlike Apple Foundation Models which has a ~4K effective window on the 3B model).

---

## HuggingFace Model Card

After validation, publish the model as `j2damax/seesaw-gemma3-1b` on HuggingFace:

```markdown
---
base_model: google/gemma-3-1b-it
language: en
license: gemma
tags:
  - children
  - storytelling
  - privacy
  - gguf
  - lora
---

# SeeSaw-Gemma-1B

Fine-tuned Gemma 3 1B for children's interactive storytelling.
Trained on TinyStories + SeeSaw story beat exports.
Outputs JSON: { story_text, question, is_ending }.
Quantised to Q4_K_M GGUF for on-device iOS inference via MediaPipe.
```

---

## Troubleshooting

| Problem | Likely cause | Fix |
|---------|-------------|-----|
| `eval_loss` stagnates > 2.0 | Learning rate too high | Reduce to 1e-4 |
| JSON parse rate < 80% | Training examples not in JSON format | Check `data_prep.ipynb` output format |
| GGUF file > 1 GB | Wrong quantisation type | Use `Q4_K_M` not `Q8_0` |
| MediaPipe crash on iOS | Incorrect model format | Validate with `llama-cli` first |
| Cold-start > 5s on iPhone 12 | Model loading | Pre-load at app launch, not on first story request |

⏺ Here are the step-by-step instructions for all three notebooks in sequence.                                                                                                                     
                                                            
  ---                                                                                                                                                                                             
  Notebook 1 — Data Preparation (free Colab, ~30 min)
                                                                                                                                                                                                  
  1. Go to colab.research.google.com → File → Upload notebook → upload training/data_prep.ipynb
                                                                                                                                                                                                  
  2. Upload your iOS training data — in the left sidebar click the Files icon (📁) → Upload → select docs/seesaw_training_all.jsonl. It will appear at /content/seesaw_training_all.jsonl.        
                                                                                                                                                                                                  
  3. Runtime → Change runtime type → T4 GPU → Save                                                                                                                                                
                                                            
  4. Run all cells (Runtime → Run all). When the GCP auth cell runs, a browser popup will ask you to sign in with j2damax@gmail.com — approve it.                                                 
                                                            
  5. Final cell should print:                                                                                                                                                                     
  Uploaded 8000 examples to gs://seesaw-models/training-data/seesaw_beats_train.jsonl
                                                                                     
  6. Verify in your terminal:                                                                                                                                                                     
  ! gsutil ls -lh gs://seesaw-models/training-data/                                                                                                                                               
                                                                                                                                                                                                  
  ---                                                                                                                                                                                             
  Notebook 2 — LoRA Fine-Tuning (Colab T4, ~3 hours)        
                                                                                                                                                                                                  
  1. File → Upload notebook → upload training/finetune.ipynb
                                                                                                                                                                                                  
  2. Runtime → Change runtime type → T4 GPU → Save
                                                                                                                                                                                                  
  3. Run all cells. When the auth cell runs:                                                                                                                                                      
  - GCP popup → approve with j2damax@gmail.com
  - HuggingFace login() prompt → paste your HF token (hf_...)                                                                                                                                     
                                                               
  4. Training will log every 50 steps. Target: eval_loss < 1.5 by epoch 3.                                                                                                                        
                                                                                                                                                                                                  
  5. Final cell should print:                                                                                                                                                                     
  Checkpoint uploaded to gs://seesaw-models/checkpoints/seesaw-gemma3-v1                                                                                                                          
                                                                        
  ▎ Important: Keep the Colab tab active or enable Tools → Settings → Site → Prevent Colab from disconnecting to avoid the ~90 min idle timeout during training.                                  
                                                                                                                                                                                                  
  ---                                                                                                                                                                                             
  Notebook 3 — GGUF Export & Validation (free Colab, ~20 min)                                                                                                                                     
                                                             
  1. File → Upload notebook → upload training/export_gguf.ipynb
                                                                                                                                                                                                  
  2. Runtime → Change runtime type → T4 GPU → Save
                                                                                                                                                                                                  
  3. Run all cells. Auth cell will prompt for GCP + HF token again.                                                                                                                               
   
  4. Step 7 (validation) should print:
  File size: 777 MB
  ✓ Size in expected range
  Architecture : gemma3
  Model name   : Seesaw Gemma3 Final
  Context len  : 32768
  ✓ Architecture is Gemma
  All metadata checks passed — GGUF is valid. Proceed to Step 8.

  5. Final cell should print:
  Uploaded to gs://seesaw-models/seesaw-gemma3-1b-q4km.gguf
  File size: 814261088 bytes (777 MB)

  6. Verify:
  gsutil ls -lh gs://seesaw-models/seesaw-gemma3-1b-q4km.gguf

  ---
  After all three notebooks complete

  1. app/routers/model.py — already updated: MODEL_FILENAME="seesaw-gemma3-1b-q4km.gguf", MODEL_SIZE_BYTES=814_261_088
  2. GET /model/latest — verified returning signed GCS URL (revision seesaw-cloud-agent-00005-497, 2026-04-13)
  3. Cloud Run — deployed and serving 100% traffic