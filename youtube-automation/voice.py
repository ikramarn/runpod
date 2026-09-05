from pathlib import Path
import os
import subprocess


def generate_voice(script: str, output_path: Path) -> None:
    """Use Piper installed on PATH to synthesize narration locally."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    model = os.environ.get("PIPER_MODEL", str(Path(__file__).resolve().parent / "en_US-lessac-medium.onnx"))
    command = ["piper", "--model", model, "--output_file", str(output_path)]
    result = subprocess.run(command, input=script, text=True, capture_output=True)
    if result.returncode:
        raise RuntimeError(f"Piper failed: {result.stderr.strip()}")
