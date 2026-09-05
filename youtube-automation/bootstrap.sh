#!/usr/bin/env bash
set -euo pipefail

export HOME=/workspace/paperclip-home
export PATH="$HOME/.local/bin:$PATH"
export OLLAMA_MODELS=/workspace/ollama-models
PROJECT=/workspace/youtube-automation

mkdir -p "$HOME/.config/opencode" "$OLLAMA_MODELS" "$PROJECT" /workspace/logs
exec > >(tee -a /workspace/logs/bootstrap.log) 2>&1
trap 'status=$?; printf "bootstrap failed with status %s at line %s: %s\n" "$status" "$LINENO" "$BASH_COMMAND" >&2' ERR

printf 'bootstrap started at %s\n' "$(date -Is)"

# ── Clone / update project files into /workspace/youtube-automation ───────────
# Keep the project in /workspace so it persists across container restarts.
# The container-local clone at /runpod is ephemeral and unreliable.
PROJECT=/workspace/youtube-automation
REPO_URL="https://github.com/ikramarn/runpod.git"

if [ ! -d "$PROJECT/.git" ]; then
  printf 'setting up git in %s\n' "$PROJECT"
  git init "$PROJECT"
  git -C "$PROJECT" remote add origin "$REPO_URL"
  git -C "$PROJECT" fetch origin
  git -C "$PROJECT" checkout -b master --track origin/master 2>/dev/null || \
    git -C "$PROJECT" reset --hard origin/master
  # Move project files from subdirectory to workspace root if needed
  if [ -d "$PROJECT/youtube-automation" ]; then
    cp -r "$PROJECT/youtube-automation/." "$PROJECT/"
    rm -rf "$PROJECT/youtube-automation"
  fi
else
  printf 'updating project files\n'
  git -C "$PROJECT" fetch origin
  git -C "$PROJECT" reset --hard origin/master
fi

# ── System packages ──────────────────────────────────────────────────────────
if ! command -v ffmpeg >/dev/null 2>&1; then
  apt-get update
  DEBIAN_FRONTEND=noninteractive apt-get install -y ffmpeg python3-venv curl git
fi

# ── Ollama ───────────────────────────────────────────────────────────────────
if ! command -v ollama >/dev/null 2>&1; then
  printf 'installing Ollama\n'
  curl -fsSL "https://ollama.com/install.sh?cachebust=$(date +%s)" | sh
fi

# ── Node.js 24 + Paperclip ───────────────────────────────────────────────────
# Paperclip requires Node.js >= 24.11.0
if ! command -v paperclipai >/dev/null 2>&1; then
  printf 'installing Paperclip\n'
  NODE_MAJOR=$(node --version 2>/dev/null | sed 's/v\([0-9]*\).*/\1/' || true)
  if [ -z "$NODE_MAJOR" ] || [ "$NODE_MAJOR" -lt 24 ]; then
    printf 'installing Node.js 24\n'
    curl -fsSL https://deb.nodesource.com/setup_24.x | bash -
    DEBIAN_FRONTEND=noninteractive apt-get install -y nodejs
  fi
  npx --yes paperclipai@latest install
fi

# ── opencode ─────────────────────────────────────────────────────────────────
if ! command -v opencode >/dev/null 2>&1; then
  # Allow install scripts for opencode-ai to avoid ENOENT on package.json
  npm config set allow-scripts=opencode-ai --location=user
  npm install --global opencode-ai
fi

# ── opencode config ──────────────────────────────────────────────────────────
cat > "$HOME/.config/opencode/opencode.json" <<'EOF'
{
  "$schema": "https://opencode.ai/config.json",
  "model": "ollama/qwen2.5-coder:14b",
  "small_model": "ollama/qwen2.5-coder:14b",
  "share": "disabled",
  "enabled_providers": ["ollama"],
  "provider": {
    "ollama": {
      "npm": "@ai-sdk/openai-compatible",
      "name": "Ollama (local)",
      "options": { "baseURL": "http://127.0.0.1:11434/v1" },
      "models": {
        "qwen2.5-coder:14b": { "name": "Qwen 2.5 Coder 14B" }
      }
    }
  }
}
EOF

# ── Python venv + dependencies ────────────────────────────────────────────────
if [ -f "$PROJECT/requirements.txt" ]; then
  if [ ! -d "$PROJECT/.venv" ]; then
    python3 -m venv "$PROJECT/.venv"
  fi
  "$PROJECT/.venv/bin/pip" install --upgrade pip

  # Install PyTorch 2.8 with CUDA 12.8 wheel first (RunPod CUDA 12.x drivers)
  "$PROJECT/.venv/bin/pip" install \
    torch==2.8.0 torchvision \
    --index-url https://download.pytorch.org/whl/cu128

  "$PROJECT/.venv/bin/pip" install -r "$PROJECT/requirements.txt"
  "$PROJECT/.venv/bin/pip" install piper-tts

  # ── Piper voice model ───────────────────────────────────────────────────────
  if [ ! -f "$PROJECT/en_US-lessac-medium.onnx" ] || \
     [ ! -f "$PROJECT/en_US-lessac-medium.onnx.json" ]; then
    printf 'downloading Piper voice model\n'
    (cd "$PROJECT" && \
     "$PROJECT/.venv/bin/python" -m piper.download_voices \
       --data-dir "$PROJECT" en_US-lessac-medium)
  fi

  # ── Wan2.2 repo + weights ───────────────────────────────────────────────────
  WAN_REPO=/workspace/Wan2.2
  WAN_WEIGHTS=/workspace/wan-weights/Wan2.2-T2V-A14B
  WAN_MODEL_ID="Wan-AI/Wan2.2-T2V-A14B"

  if [ ! -f "$WAN_REPO/generate.py" ]; then
    printf 'cloning Wan2.2 repo\n'
    git clone https://github.com/Wan-Video/Wan2.2.git "$WAN_REPO"
    # DO NOT install Wan2.2's requirements.txt — it pins numpy<2 which
    # conflicts with librosa/scipy (>=2). Install only the extras we need.
    "$PROJECT/.venv/bin/pip" install -q \
      decord librosa peft easydict ftfy dashscope opencv-python torchaudio \
      hf_transfer
    # flash_attn: download pre-built wheel to avoid cross-device link error
    # and the need to compile from source.
    "$PROJECT/.venv/bin/pip" install -q --cache-dir /workspace/.pip-cache \
      "https://github.com/Dao-AILab/flash-attention/releases/download/v2.8.3.post1/flash_attn-2.8.3.post1+cu12torch2.8cxx11abiTRUE-cp312-cp312-linux_x86_64.whl"
  fi

  if [ ! -d "$WAN_WEIGHTS" ] || [ -z "$(ls -A "$WAN_WEIGHTS" 2>/dev/null)" ]; then
    printf 'downloading Wan2.2 T2V-A14B weights to %s\n' "$WAN_WEIGHTS"
    mkdir -p "$WAN_WEIGHTS"
    HF_HUB_ENABLE_HF_TRANSFER=1 "$PROJECT/.venv/bin/huggingface-cli" download \
      "$WAN_MODEL_ID" \
      --local-dir "$WAN_WEIGHTS"
  else
    printf 'Wan2.2 weights already present at %s\n' "$WAN_WEIGHTS"
  fi

else
  printf 'waiting for project files at %s\n' "$PROJECT"
fi

# ── Paperclip onboard ─────────────────────────────────────────────────────────
export PATH="$HOME/.local/bin:$PATH"
printf 'onboarding Paperclip\n'
paperclipai onboard --yes

# Fix secrets directory permissions that Paperclip requires
chmod 700 "$HOME/.paperclip/instances/default/secrets" 2>/dev/null || true
chmod 600 "$HOME/.paperclip/instances/default/secrets/master.key" 2>/dev/null || true

# ── Start services ────────────────────────────────────────────────────────────
printf 'starting Ollama and Paperclip\n'
ollama serve > /workspace/logs/ollama.log 2>&1 &
ollama_pid=$!
paperclipai run > /workspace/logs/paperclip.log 2>&1 &
paperclip_pid=$!
trap 'kill "$ollama_pid" "$paperclip_pid" 2>/dev/null || true' EXIT

until curl -fsS http://127.0.0.1:11434/api/tags >/dev/null 2>&1; do sleep 2; done
printf 'pulling Ollama model\n'
ollama pull qwen2.5-coder:14b
printf 'bootstrap completed at %s\n' "$(date -Is)"
wait "$ollama_pid" "$paperclip_pid"
