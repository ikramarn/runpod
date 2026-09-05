"""
Wan2.2 TI2V-5B local text-to-video generation.

Generates short MP4 clips from text prompts using the Wan-AI/Wan2.2-T2V-A14B
model (the dense TI2V-5B variant is used by default for 24 GB VRAM).

Environment variables:
  WAN_MODEL_ID   Override the HuggingFace model repo
                 (default: Wan-AI/Wan2.2-T2V-A14B)
  WAN_CACHE_DIR  Override the local weights cache directory
                 (default: /workspace/wan-weights)

The model is loaded once and cached in module-level state so repeated calls
within the same process do not reload weights.
"""

from __future__ import annotations

import os
from pathlib import Path

import torch
import imageio
import numpy as np

# ---------------------------------------------------------------------------
# Lazy pipeline cache — loaded on first call to generate_clip()
# ---------------------------------------------------------------------------
_pipe = None


def _load_pipeline():
    global _pipe
    if _pipe is not None:
        return _pipe

    from diffusers import AutoencoderKLWan, WanPipeline
    from diffusers.schedulers.scheduling_unipc_multistep import UniPCMultistepScheduler

    model_id = os.environ.get("WAN_MODEL_ID", "Wan-AI/Wan2.2-T2V-A14B")
    cache_dir = os.environ.get("WAN_CACHE_DIR", "/workspace/wan-weights")

    print(f"[wan_generate] Loading {model_id} (this takes ~60 s on first run) …")

    # Mean/std values from the official Wan2.2 release
    vae = AutoencoderKLWan.from_pretrained(
        model_id,
        subfolder="vae",
        torch_dtype=torch.float32,
        cache_dir=cache_dir,
    )

    _pipe = WanPipeline.from_pretrained(
        model_id,
        vae=vae,
        torch_dtype=torch.bfloat16,
        cache_dir=cache_dir,
    )
    _pipe.scheduler = UniPCMultistepScheduler.from_config(_pipe.scheduler.config,
                                                          flow_shift=8.0)
    _pipe.to("cuda")
    _pipe.enable_model_cpu_offload()   # keeps peak VRAM ≈ 18–22 GB on 24 GB card
    print("[wan_generate] Pipeline ready.")
    return _pipe


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def generate_clip(
    prompt: str,
    output_path: Path,
    negative_prompt: str = "low quality, blurry, distorted, watermark, text",
    num_frames: int = 81,       # ~3.4 s at 24 fps; must be 4k+1 (e.g. 49, 81)
    fps: int = 24,
    width: int = 1280,
    height: int = 720,
    num_inference_steps: int = 50,
    guidance_scale: float = 5.0,
    seed: int | None = None,
) -> Path:
    """
    Generate a single video clip from *prompt* and write it to *output_path*.

    Returns the resolved output path.
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    pipe = _load_pipeline()

    generator = torch.Generator(device="cuda")
    if seed is not None:
        generator.manual_seed(seed)

    print(f"[wan_generate] Generating: {prompt[:80]} …")
    result = pipe(
        prompt=prompt,
        negative_prompt=negative_prompt,
        height=height,
        width=width,
        num_frames=num_frames,
        num_inference_steps=num_inference_steps,
        guidance_scale=guidance_scale,
        generator=generator,
    )

    # result.frames is a list-of-lists: [batch][frame] = PIL Image
    frames = result.frames[0]

    # Write to MP4 via imageio
    writer = imageio.get_writer(str(output_path), fps=fps, codec="libx264",
                                 quality=8, pixelformat="yuv420p")
    for frame in frames:
        writer.append_data(np.array(frame))
    writer.close()

    print(f"[wan_generate] Saved {len(frames)} frames → {output_path}")
    return output_path


def generate_clips(
    prompts: list[str],
    output_dir: Path,
    fps: int = 24,
    num_frames: int = 81,
    seed: int | None = None,
) -> list[Path]:
    """
    Generate one clip per prompt and return the list of output paths.
    Clips are named clip_1.mp4, clip_2.mp4, … to match the existing pipeline.
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    for index, prompt in enumerate(prompts, start=1):
        clip_seed = None if seed is None else seed + index
        path = generate_clip(
            prompt=prompt,
            output_path=output_dir / f"clip_{index}.mp4",
            fps=fps,
            num_frames=num_frames,
            seed=clip_seed,
        )
        paths.append(path)
    return paths
