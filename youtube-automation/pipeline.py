from pathlib import Path
import argparse
import re

from research import get_clips
from render import render_video
from script_writer import write_script
from voice import generate_voice

ROOT = Path(__file__).resolve().parent
MEDIA = ROOT / "media"
DATA = ROOT / "data"
OUTPUT = ROOT / "output"

# ---------------------------------------------------------------------------
# Scene-prompt extraction
# ---------------------------------------------------------------------------

def _extract_scene_prompts(script: str, topic: str) -> list[str]:
    """Derive three visual scene prompts from the narration script.

    Splits the script into three roughly equal thirds and converts each into a
    short cinematic description suitable for Wan2.2.  The topic is appended to
    every prompt so the model stays on-theme even for very short sentences.
    """
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", script.strip()) if s.strip()]

    # Divide sentence list into three equal buckets
    n = len(sentences)
    thirds = [
        " ".join(sentences[: n // 3 + (n % 3 > 0)]),
        " ".join(sentences[n // 3 + (n % 3 > 0) : 2 * (n // 3) + (n % 3 > 1)]),
        " ".join(sentences[2 * (n // 3) + (n % 3 > 1) :]),
    ]

    prompts = []
    for part in thirds:
        # Keep prompts concise — Wan2.2 performs best under ~77 tokens
        summary = part[:200] if len(part) > 200 else part
        prompts.append(
            f"Cinematic 4K footage, {topic}, {summary}, "
            "smooth camera motion, professional lighting, no text, no watermark"
        )
    return prompts


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Create a narrated three-clip YouTube draft.")
    parser.add_argument("topic", help="Topic for the 60-second video")
    parser.add_argument("--skip-download", action="store_true",
                        help="Use clip_1.mp4 through clip_3.mp4 already in media/")
    parser.add_argument("--seed", type=int, default=None,
                        help="Random seed for Wan2.2 generation (reproducible output)")
    args = parser.parse_args()

    DATA.mkdir(exist_ok=True)
    MEDIA.mkdir(exist_ok=True)
    OUTPUT.mkdir(exist_ok=True)

    # 1. Write script
    script = write_script(args.topic)
    script_path = DATA / "script.txt"
    script_path.write_text(script + "\n", encoding="utf-8")

    # 2. Synthesise narration
    narration = DATA / "narration.wav"
    generate_voice(script, narration)

    # 3. Release Ollama VRAM before video generation.
    # Ollama keeps the model loaded in GPU memory after inference.
    # Wan2.2 needs the full 24 GB, so we stop Ollama now.
    # It can be restarted manually afterwards if needed.
    import subprocess as _sp
    _sp.run(["pkill", "-f", "llama-server"], capture_output=True)
    _sp.run(["pkill", "ollama"], capture_output=True)
    import time as _time
    _time.sleep(3)
    print("[pipeline] Ollama stopped — VRAM freed for Wan2.2.")

    # 3. Obtain video clips
    if args.skip_download:
        clips = [MEDIA / f"clip_{index}.mp4" for index in range(1, 4)]
        missing = [str(path) for path in clips if not path.exists()]
        if missing:
            raise FileNotFoundError("Missing local clips: " + ", ".join(missing))
    else:
        scene_prompts = _extract_scene_prompts(script, args.topic)
        # Save prompts for inspection / reproducibility
        prompts_path = DATA / "scene_prompts.txt"
        prompts_path.write_text("\n\n".join(scene_prompts) + "\n", encoding="utf-8")

        clips = get_clips(args.topic, scene_prompts, MEDIA)

    # 4. Render final video
    output_path = OUTPUT / "draft.mp4"
    render_video(clips, narration, output_path)

    print(f"Created: {output_path}")
    print(f"Script:  {script_path}")


if __name__ == "__main__":
    main()
