"""
Wan2.2 TI2V-5B local text-to-video generation.

Uses the official Wan2.2 inference code (cloned from GitHub) rather than
diffusers, since diffusers integration is not yet complete for Wan2.2-T2V-A14B.

We use TI2V-5B (5B params) because:
  - Runs comfortably on 24 GB VRAM with offload_model=True
  - Supports text-to-video (no image required, just omit --image)
  - 720p @ 24fps native output
  - Task name: "ti2v-5B"

Environment variables (all optional):
  WAN_REPO_DIR   Path to the cloned Wan2.2 repo   (default: /workspace/Wan2.2)
  WAN_MODEL_DIR  Path to downloaded TI2V-5B weights (default: /workspace/wan-weights/Wan2.2-TI2V-5B)
  WAN_MODEL_ID   HuggingFace repo ID               (default: Wan-AI/Wan2.2-TI2V-5B)
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
WAN_MODEL_ID  = os.environ.get("WAN_MODEL_ID", "Wan-AI/Wan2.2-TI2V-5B")

# Task name as expected by generate.py --task
_TASK = "ti2v-5B"

# Size format expected by generate.py: width*height  (asterisk, not x)
_SIZE = "1280*720"


def _ensure_repo() -> None:
    """Clone the official Wan2.2 repo and install its deps if not present."""
    if WAN_REPO_DIR.exists() and (WAN_REPO_DIR / "generate.py").exists():
        return
    print(f"[wan_generate] Cloning Wan2.2 repo → {WAN_REPO_DIR} …")
    subprocess.run(
        ["git", "clone", "https://github.com/Wan-Video/Wan2.2.git", str(WAN_REPO_DIR)],
        check=True,
    )
    print("[wan_generate] Installing Wan2.2 dependencies …")

    # flash_attn requires torch already present in the build env to compile.
    # Install everything except flash_attn first, then install flash_attn
    # with --no-build-isolation so it can see the already-installed torch.
    req_file = WAN_REPO_DIR / "requirements.txt"
    reqs = req_file.read_text().splitlines()
    non_flash = [r for r in reqs if r.strip() and not r.strip().lower().startswith("flash_attn")]
    flash = [r for r in reqs if r.strip() and r.strip().lower().startswith("flash_attn")]

    if non_flash:
        subprocess.run(
            [sys.executable, "-m", "pip", "install", "-q"] + non_flash,
            check=True,
        )
    if flash:
        # --no-build-isolation lets the build see the venv's torch
        subprocess.run(
            [sys.executable, "-m", "pip", "install", "-q",
             "--no-build-isolation"] + flash,
            check=True,
        )


def _ensure_weights() -> None:
    """Download TI2V-5B weights via huggingface-cli if not already present."""
    # Consider present when the directory is non-empty
    if WAN_MODEL_DIR.exists() and any(WAN_MODEL_DIR.iterdir()):
        return
    WAN_MODEL_DIR.mkdir(parents=True, exist_ok=True)
    print(f"[wan_generate] Downloading {WAN_MODEL_ID} weights → {WAN_MODEL_DIR} (~15 GB) …")
    subprocess.run(
        [
            sys.executable, "-m", "huggingface_hub.commands.huggingface_cli",
            "download",
            WAN_MODEL_ID,
            "--local-dir", str(WAN_MODEL_DIR),
        ],
        check=True,
    )


def generate_clip(
    prompt: str,
    output_path: Path,
    num_frames: int = 81,           # must be 4k+1; 81 ≈ 3.4 s @ 24 fps
    num_inference_steps: int = 50,
    guidance_scale: float = 5.0,
    seed: int | None = None,
) -> Path:
    """
    Generate a single MP4 clip from *prompt* using generate.py and write it
    to *output_path*.  Returns the resolved output path.
    """
    _ensure_repo()
    _ensure_weights()

    output_path = Path(output_path).resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Use a temp file so generate.py's save_file path is absolute and unambiguous
    with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp:
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
            "--offload_model",      "true",   # keep peak VRAM ≤ 22 GB on 24 GB card
            "--t5_cpu",                       # offload T5 encoder to CPU
            "--prompt",             prompt,
        ]
        if seed is not None:
            cmd += ["--base_seed", str(seed)]

        env = os.environ.copy()
        # Ensure Wan2.2 package is importable
        env["PYTHONPATH"] = str(WAN_REPO_DIR) + os.pathsep + env.get("PYTHONPATH", "")

        print(f"[wan_generate] Generating clip: {prompt[:80]} …")
        result = subprocess.run(cmd, env=env, cwd=str(WAN_REPO_DIR))
        if result.returncode != 0:
            raise RuntimeError(
                f"Wan2.2 generate.py exited with code {result.returncode}. "
                "Check the output above for details."
            )

        if not tmp_mp4.exists():
            raise RuntimeError(
                f"generate.py succeeded but {tmp_mp4} was not created."
            )

        shutil.move(str(tmp_mp4), str(output_path))
    finally:
        # Clean up temp file if still present after an error
        if tmp_mp4.exists():
            tmp_mp4.unlink(missing_ok=True)

    print(f"[wan_generate] Saved → {output_path}")
    return output_path


def generate_clips(
    prompts: list[str],
    output_dir: Path,
    num_frames: int = 81,
    seed: int | None = None,
) -> list[Path]:
    """
    Generate one clip per prompt, named clip_1.mp4 … clip_N.mp4.
    Returns the list of output paths in order.
    """
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
