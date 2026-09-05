import os
import requests


def write_script(topic: str, model: str = "qwen2.5-coder:14b") -> str:
    prompt = f"""Write a 60-second educational YouTube narration about: {topic}

Return only the spoken narration, with no title, stage directions, markdown, or quotation marks.
Use approximately 130 to 155 words. Be accurate, clear, and engaging."""
    response = requests.post(
        os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434") + "/api/generate",
        json={"model": model, "prompt": prompt, "stream": False},
        timeout=600,
    )
    response.raise_for_status()
    script = response.json().get("response", "").strip()
    if not script:
        raise RuntimeError("Ollama returned an empty script.")
    return script
