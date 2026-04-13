# Gemma 3 Fine-Tuning Guide

**Goal:** Fine-tune `google/gemma-3-1b-it` on children's story data to produce `seesaw-gemma3-1b-q4km.gguf` (~800 MB) for on-device iOS inference via MediaPipe Tasks GenAI.

> **Note:** `google/gemma-4-1b-it` does not exist — Gemma 4 skipped 1B (smallest is E2B MoE, incompatible with MediaPipe). `gemma-3-1b-it` is the correct model: 1B parameters, instruction-tuned, fully supported by llama.cpp GGUF and MediaPipe Tasks GenAI on iOS.

**Run the three notebooks in `training/` in order.** Each is self-contained and documented inline.

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

### Step 1: Merge LoRA Adapters

```python
from peft import PeftModel
from transformers import AutoModelForCausalLM, AutoTokenizer

base_model = AutoModelForCausalLM.from_pretrained("google/gemma-3-1b-it", torch_dtype=torch.float16)
model = PeftModel.from_pretrained(base_model, "gs://seesaw-models/checkpoints/seesaw-gemma3-v1/")
merged = model.merge_and_unload()
merged.save_pretrained("/tmp/seesaw-gemma4-merged")
```

### Step 2: Convert to GGUF

Using `llama.cpp` (pre-built binary available on Colab):

```bash
# Clone llama.cpp (shallow)
git clone --depth 1 https://github.com/ggerganov/llama.cpp /tmp/llama.cpp
cd /tmp/llama.cpp && pip install -r requirements.txt

# Convert HuggingFace model to GGUF float16
python convert_hf_to_gguf.py /tmp/seesaw-gemma4-merged \
  --outfile /tmp/seesaw-gemma4-f16.gguf \
  --outtype f16

# Quantise to Q4_K_M
./llama-quantize /tmp/seesaw-gemma4-f16.gguf \
                 /tmp/seesaw-gemma3-1b-q4km.gguf \
                 Q4_K_M
```

**Expected output size:** ~800–850 MB

### Step 3: Validate

Run 3 sample inferences on the GGUF model before uploading:

```bash
./llama-cli \
  -m /tmp/seesaw-gemma3-1b-q4km.gguf \
  -p "<bos><start_of_turn>user\nChild: Vihas, age 5. Objects: teddy_bear, book. Continue the story.<end_of_turn>\n<start_of_turn>model\n" \
  -n 200
```

Check that:
1. Output is valid JSON with `story_text`, `question`, `is_ending` fields
2. Content is child-appropriate (no violence, fear, adult themes)
3. Story text is 40–80 words
4. `is_ending` is `false` for continuation prompts

### Step 4: Upload to GCS

```bash
gsutil cp /tmp/seesaw-gemma3-1b-q4km.gguf gs://seesaw-models/seesaw-gemma3-1b-q4km.gguf
gsutil acl ch -u AllUsers:R gs://seesaw-models/seesaw-gemma3-1b-q4km.gguf  # or use signed URLs
```

After upload, test the `/model/latest` endpoint returns the correct download URL and size.

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

