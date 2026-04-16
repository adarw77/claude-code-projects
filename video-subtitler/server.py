import uuid
import shutil
import subprocess
import tempfile
import threading
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, File, Form, UploadFile, HTTPException
from fastapi.responses import FileResponse, HTMLResponse

app = FastAPI()

WORK_DIR = Path(tempfile.gettempdir()) / "video_subtitler"
WORK_DIR.mkdir(exist_ok=True)

FFMPEG  = r"C:\ffmpeg\ffmpeg-8.1-essentials_build\bin\ffmpeg.exe"
YT_DLP  = r"C:\Users\abbas\AppData\Local\Programs\Python\Python312\Scripts\yt-dlp.exe"

# Whisper model loaded once on first use, then reused for all jobs
_whisper_model = None
_whisper_lock = threading.Lock()

def get_whisper_model():
    global _whisper_model
    if _whisper_model is None:
        with _whisper_lock:
            if _whisper_model is None:
                import whisper
                _whisper_model = whisper.load_model("base")
    return _whisper_model

# job_id -> {"status": str, "progress": str, "output": str|None, "error": str|None}
jobs: dict[str, dict] = {}


def update_job(job_id: str, status: str, progress: str, output: str = None, error: str = None):
    jobs[job_id] = {"status": status, "progress": progress, "output": output, "error": error}


def srt_from_whisper_result(result: dict) -> str:
    """Convert whisper result segments to SRT format."""
    lines = []
    for i, seg in enumerate(result["segments"], 1):
        start = format_ts(seg["start"])
        end = format_ts(seg["end"])
        text = seg["text"].strip()
        lines.append(f"{i}\n{start} --> {end}\n{text}\n")
    return "\n".join(lines)


def format_ts(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = int((seconds % 1) * 1000)
    return f"{h:02}:{m:02}:{s:02},{ms:03}"


def translate_srt_to_language(srt_text: str, target_language: str, api_key: str) -> str:
    """Use OpenAI GPT to translate SRT subtitle text to target language."""
    from openai import OpenAI
    client = OpenAI(api_key=api_key)

    prompt = (
        f"Translate the following SRT subtitle file to {target_language}. "
        "Keep the SRT format exactly (numbers, timestamps, blank lines). "
        "Only translate the text lines, not the timestamps or indices.\n\n"
        f"{srt_text}"
    )

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.2,
    )
    return response.choices[0].message.content.strip()


def process_video(
    job_id: str,
    video_source: str,         # file path or URL
    is_url: bool,
    subtitle_mode: str,        # "auto" or "srt"
    subtitle_lang: str,        # "original", "english", "arabic", "spanish", "french", "german"
    srt_path: Optional[str],   # path to uploaded SRT (if subtitle_mode == "srt")
    openai_api_key: Optional[str],
):
    job_dir = WORK_DIR / job_id
    job_dir.mkdir(exist_ok=True)

    try:
        # ── Step 1: Acquire video ──────────────────────────────────────────
        update_job(job_id, "running", "Acquiring video...")

        if is_url:
            video_path = job_dir / "input.mp4"
            result = subprocess.run(
                [YT_DLP, "-f", "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
                 "--merge-output-format", "mp4",
                 "-o", str(video_path), video_source],
                capture_output=True, text=True
            )
            if result.returncode != 0:
                raise RuntimeError(f"yt-dlp failed.\nCommand: {YT_DLP}\nError: {result.stderr[-1000:]}")
        else:
            video_path = Path(video_source)

        # ── Step 2: Get subtitles ──────────────────────────────────────────
        final_srt = job_dir / "subtitles.srt"

        if subtitle_mode == "srt":
            shutil.copy(srt_path, final_srt)

        else:  # auto transcribe
            update_job(job_id, "running", "Transcribing audio with Whisper...")
            model = get_whisper_model()

            if subtitle_lang == "english":
                # Whisper can directly translate to English
                result = model.transcribe(str(video_path), task="translate", language=None)
            else:
                # Transcribe in original language first
                result = model.transcribe(str(video_path), task="transcribe")

            srt_text = srt_from_whisper_result(result)

            # If target language is not English and not original, translate via GPT
            if subtitle_lang not in ("original", "english"):
                if not openai_api_key:
                    raise RuntimeError("An OpenAI API key is required for non-English translation.")
                update_job(job_id, "running", f"Translating subtitles to {subtitle_lang}...")
                lang_names = {
                    "arabic": "Arabic",
                    "spanish": "Spanish",
                    "french": "French",
                    "german": "German",
                }
                srt_text = translate_srt_to_language(srt_text, lang_names[subtitle_lang], openai_api_key)

            final_srt.write_text(srt_text, encoding="utf-8")

        # ── Step 3: Burn subtitles with ffmpeg ─────────────────────────────
        update_job(job_id, "running", "Burning subtitles into video...")
        output_path = job_dir / "output.mp4"

        # ffmpeg subtitles filter requires forward slashes and escaped colons on Windows
        srt_str = str(final_srt).replace("\\", "/").replace(":", "\\:")

        ffmpeg_result = subprocess.run(
            [
                FFMPEG, "-y",
                "-i", str(video_path),
                "-vf", f"subtitles='{srt_str}'",
                "-c:a", "copy",
                str(output_path),
            ],
            capture_output=True, text=True
        )
        if ffmpeg_result.returncode != 0:
            raise RuntimeError(f"ffmpeg failed.\nCommand: {FFMPEG}\nError: {ffmpeg_result.stderr[-2000:]}")

        update_job(job_id, "done", "Done!", output=str(output_path))

    except FileNotFoundError as e:
        update_job(job_id, "error", "Failed.", error=f"Executable not found: {e.filename}\nFull error: {e}")
    except Exception as e:
        update_job(job_id, "error", "Failed.", error=str(e))


# ── Routes ─────────────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
def serve_frontend():
    html_path = Path(__file__).parent / "index.html"
    return HTMLResponse(html_path.read_text(encoding="utf-8"))


@app.post("/process")
async def start_process(
    video_file: Optional[UploadFile] = File(None),
    video_url: Optional[str] = Form(None),
    subtitle_mode: str = Form("auto"),
    subtitle_lang: str = Form("original"),
    srt_file: Optional[UploadFile] = File(None),
    openai_api_key: Optional[str] = Form(None),
):
    if not video_file and not video_url:
        raise HTTPException(400, "Provide either a video file or a URL.")
    if subtitle_mode == "srt" and not srt_file:
        raise HTTPException(400, "SRT mode requires an SRT file.")

    job_id = str(uuid.uuid4())
    job_dir = WORK_DIR / job_id
    job_dir.mkdir(exist_ok=True)

    # Save uploaded video
    video_source = None
    is_url = False
    if video_file:
        safe_name = "input" + Path(video_file.filename).suffix
        video_source = str(job_dir / safe_name)
        with open(video_source, "wb") as f:
            shutil.copyfileobj(video_file.file, f)
    else:
        video_source = video_url.strip()
        is_url = True

    # Save uploaded SRT
    srt_path = None
    if srt_file:
        srt_path = str(job_dir / "uploaded.srt")
        with open(srt_path, "wb") as f:
            shutil.copyfileobj(srt_file.file, f)

    update_job(job_id, "queued", "Queued...")

    thread = threading.Thread(
        target=process_video,
        args=(job_id, video_source, is_url, subtitle_mode, subtitle_lang, srt_path, openai_api_key),
        daemon=True,
    )
    thread.start()

    return {"job_id": job_id}


@app.get("/status/{job_id}")
def get_status(job_id: str):
    if job_id not in jobs:
        raise HTTPException(404, "Job not found.")
    return jobs[job_id]


@app.get("/download/{job_id}")
def download(job_id: str):
    job = jobs.get(job_id)
    if not job or job["status"] != "done":
        raise HTTPException(400, "Job not ready.")
    return FileResponse(job["output"], media_type="video/mp4", filename="subtitled_video.mp4")
