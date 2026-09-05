from pathlib import Path
import subprocess


def render_video(clips: list[Path], narration: Path, output_path: Path) -> None:
    if len(clips) != 3:
        raise ValueError("Exactly three stock clips are required.")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    command = [
        "ffmpeg", "-y", "-stream_loop", "-1",
        "-i", str(clips[0]), "-stream_loop", "-1",
        "-i", str(clips[1]), "-stream_loop", "-1",
        "-i", str(clips[2]),
        "-i", str(narration),
        "-filter_complex",
        "[0:v]trim=duration=20,setpts=PTS-STARTPTS,scale=1920:1080:force_original_aspect_ratio=increase,crop=1920:1080,setsar=1[v0];"
        "[1:v]trim=duration=20,setpts=PTS-STARTPTS,scale=1920:1080:force_original_aspect_ratio=increase,crop=1920:1080,setsar=1[v1];"
        "[2:v]trim=duration=20,setpts=PTS-STARTPTS,scale=1920:1080:force_original_aspect_ratio=increase,crop=1920:1080,setsar=1[v2];"
        "[v0][v1][v2]concat=n=3:v=1:a=0[video]",
        "-map", "[video]", "-map", "3:a:0", "-shortest",
        "-c:v", "libx264", "-preset", "fast", "-crf", "22",
        "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k",
        str(output_path),
    ]
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError(f"FFmpeg failed: {result.stderr[-2000:]}")
