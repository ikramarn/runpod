# Video Production Agent Instructions

You work only in `/workspace/youtube-automation`.

Use Ollama locally. Do not configure or use paid LLM providers, expose local
services publicly, or place credentials in source code, task comments, or logs.

For a video-production task:

1. Read the assigned task for the topic and constraints.
2. Inspect the generated script and source media before reporting success.
3. Run only the existing pipeline command: `python pipeline.py "<topic>"`.
4. Report the paths to `data/script.txt` and `output/draft.mp4`, along with any
   Pexels assets used and failures encountered.

Do not upload or publish a video. `upload_youtube.py` is disabled by design.
Treat each draft as awaiting human review for factual accuracy, media licensing,
attribution, audience setting, metadata, and publishing approval.