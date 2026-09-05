# YouTube automation case study

This creates a reviewable draft, not an automatic upload:

1. Enter a topic manually.
2. Ask local Ollama for a roughly 60-second narration.
3. Generate local speech with Piper.
4. Obtain three 720p video clips — either from Pexels **or** generated locally
   with **Wan2.2 TI2V-5B** (chosen automatically based on whether
   `PEXELS_API_KEY` is set).
5. Combine the clips and narration with FFmpeg.
6. Save `output/draft.mp4`.

## Run

Terraform installs the runtime on the Pod, but the local project files must be
copied into `/workspace/youtube-automation` before running this pipeline. The
Pod currently uses a local volume, so this directory survives Pod stops and
restarts but is deleted if the Pod is terminated. Back up final videos outside
the Pod.

### Wan2.2 mode (no Pexels key required)

```bash
cd /workspace/youtube-automation
source .venv/bin/activate
python pipeline.py "How local AI models work"
```

The pipeline detects that `PEXELS_API_KEY` is absent and falls back to Wan2.2
automatically. Three scene prompts are derived from the generated script and
written to `data/scene_prompts.txt` for review. Each clip takes roughly
4–8 minutes on an RTX PRO 4000 (24 GB VRAM).

For reproducible output pass `--seed`:

```bash
python pipeline.py "How local AI models work" --seed 42
```

### Pexels mode (stock footage)

```bash
cd /workspace/youtube-automation
source .venv/bin/activate
export PEXELS_API_KEY=your_key
python pipeline.py "How local AI models work"
```

### Skip clip generation (files already in media/)

```bash
python pipeline.py "How local AI models work" --skip-download
```

## Hardware requirements

| Component | Requirement |
|-----------|-------------|
| GPU VRAM  | 24 GB (RTX PRO 4000 / 4090 or equivalent) |
| Disk      | ~20 GB for Wan2.2 weights in `/workspace/wan-weights` |
| RAM       | 31 GB recommended (CPU offloading during generation) |

Wan2.2 weights are downloaded once by `bootstrap.sh` and cached at
`/workspace/wan-weights`. The cache survives Pod stops but **not** Pod
terminations — re-running bootstrap will re-download them.

## Environment variables

| Variable | Default | Purpose |
|----------|---------|---------|
| `PEXELS_API_KEY` | _(unset)_ | If set, use Pexels for clips instead of Wan2.2 |
| `WAN_MODEL_ID` | `Wan-AI/Wan2.2-T2V-A14B` | Override HuggingFace model repo |
| `WAN_CACHE_DIR` | `/workspace/wan-weights` | Override weights cache location |
| `OLLAMA_URL` | `http://127.0.0.1:11434` | Ollama API endpoint |
| `PIPER_MODEL` | `en_US-lessac-medium.onnx` | Piper voice model path |

## Output files

| Path | Contents |
|------|----------|
| `output/draft.mp4` | Final rendered video |
| `data/script.txt` | Generated narration text |
| `data/narration.wav` | Synthesised voice audio |
| `data/scene_prompts.txt` | Wan2.2 prompts used (Wan2.2 mode only) |
| `media/clip_1–3.mp4` | Source video clips |

## Paperclip agents

Paperclip manages tasks, schedules, and approvals. Its agents use the locally
installed OpenCode runtime, which is configured to call Ollama only. In
Paperclip, create agents using adapter type `opencode_local`, working directory
`/workspace/youtube-automation`, and model `ollama/qwen2.5-coder:14b`.

Use `AGENTS.md` as the instructions file for the Video Producer. Give only the
Video Producer the Pexels API key as a Paperclip secret reference (if using
Pexels mode). Keep YouTube OAuth credentials out of all agents until a
human-approved Publisher workflow has been designed.

Review the generated draft before publishing: verify factual accuracy, media
licensing/attribution, audience settings, metadata, and title. `upload_youtube.py`
is intentionally disabled.
