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

if ! command -v ffmpeg >/dev/null 2>&1; then
  apt-get update
  DEBIAN_FRONTEND=noninteractive apt-get install -y ffmpeg python3-venv curl
fi

if ! command -v ollama >/dev/null 2>&1; then
  printf 'installing Ollama\n'
  curl -fsSL "https://ollama.com/install.sh?cachebust=$(date +%s)" | sh
fi

if ! command -v paperclipai >/dev/null 2>&1; then
  printf 'installing Paperclip\n'
  if ! command -v node >/dev/null 2>&1 || ! command -v npx >/dev/null 2>&1; then
    curl -fsSL https://deb.nodesource.com/setup_22.x | bash -
    DEBIAN_FRONTEND=noninteractive apt-get install -y nodejs
  fi
  npx --yes paperclipai@latest install
fi

if ! command -v opencode >/dev/null 2>&1; then
  npm install --global opencode-ai
fi

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

if [ -f "$PROJECT/requirements.txt" ]; then
  if [ ! -d "$PROJECT/.venv" ]; then
    python3 -m venv "$PROJECT/.venv"
  fi
  "$PROJECT/.venv/bin/pip" install --upgrade pip

  # Install PyTorch 2.8 with CUDA 12.8 wheel first so the index is available
  # for the rest of the requirements (RunPod ships CUDA 12.x drivers even when
  # reporting CUDA 13 compatibility).
  "$PROJECT/.venv/bin/pip" install \
    torch==2.8.0 torchvision \
    --index-url https://download.pytorch.org/whl/cu128

  "$PROJECT/.venv/bin/pip" install -r "$PROJECT/requirements.txt"
  "$PROJECT/.venv/bin/pip" install piper-tts

  if [ ! -f "$PROJECT/en_US-lessac-medium.onnx" ] || [ ! -f "$PROJECT/en_US-lessac-medium.onnx.json" ]; then
    printf 'downloading Piper voice model\n'
    (cd "$PROJECT" && "$PROJECT/.venv/bin/python" -m piper.download_voices --data-dir "$PROJECT" en_US-lessac-medium)
  fi

  # Pre-download Wan2.2 weights so the first pipeline run does not time out.
  # Weights are stored in /workspace/wan-weights (~20 GB) which persists across
  # Pod stops but not Pod terminations.
  WAN_CACHE=/workspace/wan-weights
  WAN_MODEL="Wan-AI/Wan2.2-T2V-A14B"
  if [ ! -d "$WAN_CACHE/models--Wan-AI--Wan2.2-T2V-A14B" ]; then
    printf 'downloading Wan2.2 weights to %s (this is ~20 GB)\n' "$WAN_CACHE"
    mkdir -p "$WAN_CACHE"
    "$PROJECT/.venv/bin/python" - <<PYEOF
import os
os.environ["HF_HOME"] = "$WAN_CACHE"
from huggingface_hub import snapshot_download
snapshot_download(
    repo_id="$WAN_MODEL",
    cache_dir="$WAN_CACHE",
    ignore_patterns=["*.bin"],   # prefer safetensors
)
print("Wan2.2 weights downloaded.")
PYEOF
  else
    printf 'Wan2.2 weights already cached at %s\n' "$WAN_CACHE"
  fi
else
  printf 'waiting for project files at %s\n' "$PROJECT"
fi

export PATH="$HOME/.local/bin:$PATH"
printf 'onboarding Paperclip\n'
paperclipai onboard --yes

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
