from pathlib import Path
import os
import requests


def download_stock_clips(topic: str, output_dir: Path, count: int = 3) -> list[Path]:
    """Download up to three landscape videos from Pexels when an API key is configured."""
    api_key = os.environ.get("PEXELS_API_KEY")
    if not api_key:
        raise RuntimeError(
            "PEXELS_API_KEY is required. Set it before running, or place three MP4 files in media/."
        )

    output_dir.mkdir(parents=True, exist_ok=True)
    response = requests.get(
        "https://api.pexels.com/v1/videos/search",
        headers={"Authorization": api_key},
        params={"query": topic, "orientation": "landscape", "per_page": count},
        timeout=60,
    )
    response.raise_for_status()

    clips: list[Path] = []
    for index, video in enumerate(response.json().get("videos", [])[:count], start=1):
        files = [item for item in video.get("video_files", []) if item.get("width", 0) >= 1280]
        if not files:
            files = video.get("video_files", [])
        if not files:
            continue
        video_url = sorted(files, key=lambda item: item.get("width", 0), reverse=True)[0]["link"]
        destination = output_dir / f"clip_{index}.mp4"
        with requests.get(video_url, stream=True, timeout=120) as download:
            download.raise_for_status()
            with destination.open("wb") as target:
                for chunk in download.iter_content(chunk_size=1024 * 1024):
                    if chunk:
                        target.write(chunk)
        clips.append(destination)

    if len(clips) < count:
        raise RuntimeError(f"Pexels returned only {len(clips)} usable clips; need {count}.")
    return clips


def generate_clips_wan(prompts: list[str], output_dir: Path) -> list[Path]:
    """Generate video clips locally with Wan2.2 from a list of scene prompts.

    Falls back automatically when PEXELS_API_KEY is not set.  The model is
    loaded lazily on the first call so import cost is zero when Pexels is used.
    """
    from wan_generate import generate_clips  # local import — GPU deps optional
    return generate_clips(prompts, output_dir)


def get_clips(topic: str, scene_prompts: list[str], output_dir: Path) -> list[Path]:
    """Return three clips for *topic*, choosing the source automatically.

    - If PEXELS_API_KEY is set  → download from Pexels (original behaviour).
    - If PEXELS_API_KEY is absent → generate locally with Wan2.2 using
      *scene_prompts* (one prompt per clip, exactly three required).
    """
    if os.environ.get("PEXELS_API_KEY"):
        return download_stock_clips(topic, output_dir)

    if len(scene_prompts) != 3:
        raise ValueError(f"Wan2.2 mode requires exactly 3 scene prompts, got {len(scene_prompts)}.")
    print("[research] PEXELS_API_KEY not set — generating clips locally with Wan2.2.")
    return generate_clips_wan(scene_prompts, output_dir)
