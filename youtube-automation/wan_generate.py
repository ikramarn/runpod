"""
Wan2.2 local text-to-video generation.

Uses Wan2.2-T2V-A14B at 832*480 resolution — low enough VRAM to run on 24 GB.
The TI2V-5B model only supports 1280*704 which OOMs on 24 GB even with offloading.

Upgrade path: swap WAN_MODEL_ID / WAN_MODEL_DIR / _TASK / _SIZE env vars to use
a larger model on a higher-VRAM pod without changing any pipeline code.

Environment variables (all optional):
  WAN_REPO_DIR   Path to cloned Wan2.2 repo      (default: /workspace/Wan2.2)
  WAN_MODEL_DIR  Path to model weights            (default: /workspace/wan-weights/Wan2.2-T2V-A14B)
  WAN_MODEL_ID   HuggingFace repo ID              (default: Wan-AI/Wan2.2-T2V-A14B)
  WAN_TASK       generate.py --task value         (default: t2v-A14B)
  WAN_SIZE       generate.py --size value         (default: 832*480)
"""

from __future__ import annotations

import os
import sys
import shutil
import subprocess
import tempfile
from pathlib import Path

WAN_REPO_DIR  = Path(os.environ.get("WAN_REPO_DIR",  "/workspace/Wan2.2"))
WAN_MODEL_DIR = Path(os.environ.get("WAN_MODEL_DIR", "/workspace/wan-weights/Wan2.2-TI2V-5B"))
WAN_MODEL_ID  = os.environ.get("WAN_MODEL_ID",  "Wan-AI/Wan2.2-TI2V-5B")
_TASK         = os.environ.get("WAN_TASK",      "ti2v-5B")
_SIZE         = os.environ.get("WAN_SIZE",      "704*1280")  # portrait; lower res than 1280*704


def _ensure_repo() -> None:
    """Clone the official Wan2.2 repo and install extras if not present."""
    if WAN_REPO_DIR.exists() and (WAN_REPO_DIR / "generate.py").exists():
        return
    print(f"[wan_generate] Cloning Wan2.2 repo → {WAN_REPO_DIR} …")
    subprocess.run(
        ["git", "clone", "https://github.com/Wan-Video/Wan2.2.git", str(WAN_REPO_DIR)],
        check=True,
    )
    print("[wan_generate] Installing Wan2.2 extra dependencies …")
    # Skip Wan2.2's requirements.txt — it pins numpy<2 which breaks librosa/scipy.
    extras = ["decord", "librosa", "peft", "easydict", "ftfy",
              "dashscope", "opencv-python", "torchaudio"]
    subprocess.run([sys.executable, "-m", "pip", "install", "-q"] + extras, check=True)


def _ensure_weights() -> None:
    """Download model weights via huggingface-cli if not already present."""
    if WAN_MODEL_DIR.exists() and any(WAN_MODEL_DIR.iterdir()):
        return
    WAN_MODEL_DIR.mkdir(parents=True, exist_ok=True)
    print(f"[wan_generate] Downloading {WAN_MODEL_ID} → {WAN_MODEL_DIR} …")
    subprocess.run(
        ["huggingface-cli", "download", WAN_MODEL_ID,
         "--local-dir", str(WAN_MODEL_DIR)],
        check=True,
    )


def generate_clip(
    prompt: str,
    output_path: Path,
    num_frames: int = 9,           # 4k+1 minimum practical; 9 frames ≈ 0.4s, smallest VAE output
    num_inference_steps: int = 20,
    guidance_scale: float = 5.0,
    seed: int | None = None,
) -> Path:
    """Generate a single MP4 clip and write it to output_path."""
    _ensure_repo()
    _ensure_weights()

    output_path = Path(output_path).resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.NamedTemporaryFile(
        suffix=".mp4",
        delete=False,
        dir=output_path.parent,   # same filesystem as destination — avoids cross-device move
    ) as tmp:
        tmp_mp4 = Path(tmp.name)

    try:
        cmd = [
            sys.executable,
            str(WAN_REPO_DIR / "generate.py"),
            "--task",               _TASK,
            "--size",               _SIZE,
            "--ckpt_dir",           str(WAN_MODEL_DIR),
            "--sample_steps",       str(num_inference_steps),
            "--sample_guide_scale", str(guidance_scale),
            "--frame_num",          str(num_frames),
            "--save_file",          str(tmp_mp4),
            "--offload_model",      "true",
            "--convert_model_dtype",  # fp16 saves ~1.5 GB during VAE decode
            "--prompt",             prompt,
        ]
        if seed is not None:
            cmd += ["--base_seed", str(seed)]

        env = os.environ.copy()
        env["PYTHONPATH"] = str(WAN_REPO_DIR) + os.pathsep + env.get("PYTHONPATH", "")
        env["PYTORCH_CUDA_ALLOC_CONF"] = "expandable_segments:True"

        print(f"[wan_generate] Generating: {prompt[:80]} …")
        result = subprocess.run(cmd, env=env, cwd=str(WAN_REPO_DIR))
        if result.returncode != 0:
            raise RuntimeError(f"generate.py exited {result.returncode}")

        if not tmp_mp4.exists():
            raise RuntimeError(f"generate.py succeeded but {tmp_mp4} not created")

        shutil.move(str(tmp_mp4), str(output_path))
    finally:
        if tmp_mp4.exists():
            tmp_mp4.unlink(missing_ok=True)

    print(f"[wan_generate] Saved → {output_path}")
    return output_path


def generate_clips(
    prompts: list[str],
    output_dir: Path,
    num_frames: int = 9,
    seed: int | None = None,
) -> list[Path]:
    """Generate one clip per prompt, named clip_1.mp4 … clip_N.mp4."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    for index, prompt in enumerate(prompts, start=1):
        clip_seed = None if seed is None else seed + index
        path = generate_clip(
            prompt=prompt,
            output_path=output_dir / f"clip_{index}.mp4",
            num_frames=num_frames,
            seed=clip_seed,
        )
        paths.append(path)
    return paths
