# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repository layout

This is a collection of standalone mini-projects. Each project lives in its own directory (or as a single file at the root) and is fully self-contained.

| Path | What it is |
|---|---|
| `tictactoe.html` | Single-file browser game — no build step, open directly in a browser |
| `video-subtitler/` | FastAPI server + single-page frontend for burning subtitles into video |

## Video Subtitler — running locally

```bash
cd video-subtitler
pip install -r requirements.txt
uvicorn server:app --reload
# Open http://localhost:8000
```

**External dependencies that must be on PATH:** `ffmpeg`, `yt-dlp` (for URL downloads).  
Whisper downloads its model (~140 MB) on first transcription.

## Video Subtitler — architecture

The backend (`server.py`) is a single FastAPI app. Every job runs in a background `threading.Thread` (not an async task) so Whisper/ffmpeg calls don't block the event loop. Job state lives in a module-level `jobs` dict keyed by UUID — it is not persisted and is lost on server restart.

Processing pipeline per job:
1. **Acquire** — copy uploaded file to `WORK_DIR/<job_id>/` or download via `yt-dlp`
2. **Subtitles** — either copy uploaded SRT, or run `whisper.load_model("base").transcribe()`; if target language is not English/original, call OpenAI `gpt-4o-mini` for translation
3. **Burn** — run `ffmpeg` with `subtitles=` video filter; audio stream is copied without re-encoding

The frontend (`index.html`) is served directly by FastAPI from disk. It submits a `multipart/form-data` POST to `/process`, then polls `/status/<job_id>` every 1.5 s until `status == "done"` or `"error"`, then fetches `/download/<job_id>`.

## Git & GitHub workflow

All projects share one repository: [adarw77/claude-code-projects](https://github.com/adarw77/claude-code-projects).

- Commit after every meaningful change with a clean message: `<type>: <short summary>` followed by a bullet list of specifics.
- Types: `feat`, `fix`, `refactor`, `docs`, `chore`
- Always push to `origin master` after committing so GitHub stays in sync.
