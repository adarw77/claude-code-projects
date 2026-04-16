# Video Subtitler

A local web app that adds burned-in subtitles to any video — with auto-transcription, translation, or your own SRT file.

## Features
- Upload a video file or paste a YouTube / direct video URL
- Auto-transcribe speech using OpenAI Whisper (runs locally, no API key needed)
- Translate subtitles to English (via Whisper) or Arabic/Spanish/French/German (via OpenAI API)
- Upload your own `.srt` file to burn in custom subtitles

## Prerequisites

### 1. Python 3.9+
Download from https://python.org

### 2. ffmpeg
Download from https://ffmpeg.org/download.html and add it to your PATH.
On Windows: download the zip, extract it, and add the `bin` folder to your system PATH.

### 3. Install Python packages
```
pip install -r requirements.txt
```
> Note: `openai-whisper` will also download the Whisper model (~140 MB) on first use.

## Running

```
cd video-subtitler
uvicorn server:app --reload
```

Then open http://localhost:8000 in your browser.

## Usage

1. **Drop a video file** or **paste a YouTube URL**
2. Choose **subtitle mode**:
   - *Auto-transcribe* — Whisper listens to the audio and generates subtitles
   - *Upload SRT* — provide your own subtitle file
3. If using auto-transcribe, choose the **subtitle language**:
   - *Original* — subtitles in whatever language is spoken
   - *English* — Whisper translates to English automatically
   - *Arabic / Spanish / French / German* — requires an OpenAI API key (GPT-4o mini)
4. Click **Process Video** and wait
5. Preview and **Download** the result

## Notes
- Processed files are stored in your system temp directory and are not persisted across server restarts.
- For large videos, transcription may take a few minutes depending on your hardware.
- Using a GPU significantly speeds up Whisper — install `torch` with CUDA support if available.
