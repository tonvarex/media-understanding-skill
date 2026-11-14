# media-understanding-skill

Agent skill that gives LLMs native-like video, audio, and image understanding via OpenRouter.

Instead of forcing a single heavy pipeline on every file, the agent dynamically chooses between two complementary approaches:
- **Method A (Contact Sheets + Whisper):** Extracts timestamped frame grids (`ffmpeg` + `Pillow`) and word-level speech transcripts (`openai/whisper-large-v3`). Fast, cheap, and pixel-accurate for reading on-screen text, verifying exact quotes, or inspecting specific timestamps.
- **Method B (Native Multimodal Model):** Compresses and splits long videos automatically and sends video + audio together to `google/gemini-4-hydrogen` via OpenRouter. Captures motion, non-speech audio (music, SFX, tone), plot, and scene transitions.

Works in any project without polluting your working directory — all intermediate files are written to the system temp directory.

---

## Features

- **Smart Method Routing:** The agent selects Method A, Method B, or a hybrid workflow (broad overview via Gemini → exact verification via zoomed frames and Whisper) depending on the task and video length.
- **Automatic Compression & Splitting:** `ask_video.py` downscales and re-encodes large videos with `ffmpeg`, splits long footage on keyframes, and tracks part offsets so timestamps stay aligned.
- **Pause-Aware Audio Chunking:** `transcribe.py` detects silence intervals (`silencedetect`) to split long audio tracks without cutting words in half, outputting aligned timestamps and `.srt` / `.json` / `.txt` files.
- **Timestamped Contact Sheets:** `frames.py` generates `4x3` (or custom) image grids with `MM:SS.s` burned into each frame, supporting uniform sampling, scene-change detection (`--scene`), and high-res zoom ranges.
- **Zero-Leak API Key Handling:** Resolves your OpenRouter key from environment variables, macOS Keychain, Linux `libsecret`, or a `chmod 600` file without ever printing or logging the secret.

---

## Requirements

- **OS:** macOS or Linux
- **Python:** 3.9+ with [Pillow](https://python-pillow.org/)
- **System tools:** `ffmpeg` and `ffprobe`
- **API:** An [OpenRouter](https://openrouter.ai/) API key

### Install dependencies

**macOS:**
```bash
brew install ffmpeg
pip install pillow
```

**Linux (Debian/Ubuntu):**
```bash
sudo apt update && sudo apt install -y ffmpeg libsecret-tools
pip install pillow
```

---

## Installation

Clone the repository into your agent's skills directory (for example, `~/.claude/skills/`):

```bash
git clone https://github.com/tonvarex/media-understanding-skill.git ~/.claude/skills/video-understanding
```

*(Note: Ensure the directory structure places `SKILL.md` and the `scripts/` folder at `~/.claude/skills/video-understanding/`.)*

---

## API Key Setup

Never hardcode your OpenRouter key or paste it into agent chats. `openrouter_key.py` checks sources in the following order:

1. `OPENROUTER_API_KEY` environment variable
2. OS secret store (**macOS Keychain** or **Linux `secret-tool`**) — *recommended*
3. `~/.config/openrouter/api_key` (must have `600` permissions)

### Store in OS Keychain (Recommended)

**macOS:**
```bash
security add-generic-password -U -s openrouter-api-key -a "$(id -un)" -w
```

**Linux:**
```bash
secret-tool store --label="OpenRouter API key" service openrouter-api-key
```

---

## Standalone CLI Usage

While designed to be invoked automatically by an LLM agent, all scripts can be run directly from the terminal:

### 1. Ask a multimodal model (`ask_video.py`)
```bash
# General scene-by-scene breakdown
python3 scripts/ask_video.py video.mp4 "Describe what happens in the video with timestamps."

# Long video search using Gemini agentic processing
python3 scripts/ask_video.py lecture.mp4 "List every topic transition with timestamps." --processing agentic

# Preview compression and split plan without making API calls
python3 scripts/ask_video.py movie.mp4 "Summarize" --dry-run
```
**Key flags:** `--model` (default: `google/gemini-4-hydrogen`), `--processing` (`agentic` | `static`), `--height` (default: `480`), `--fps` (default: `8`), `--max-mb`, `--max-min`, `--no-compress`.

### 2. Generate timestamped frame sheets (`frames.py`)
```bash
# Auto-sampled contact sheets (12–48 frames)
python3 scripts/frames.py video.mp4

# Scene-change detection
python3 scripts/frames.py edited_clip.mp4 --scene 0.3

# High-resolution zoom on a specific time range (22s to 26s)
python3 scripts/frames.py video.mp4 --start 22 --end 26 --every 0.5 --width 1000 --cols 2 --rows 2
```

### 3. Transcribe speech (`transcribe.py`)
```bash
# Auto-detect language
python3 scripts/transcribe.py video.mp4

# Force language and save transcript files (.txt, .json, .srt) to a specific folder
python3 scripts/transcribe.py podcast.mp3 --lang ru --out ./transcript_out
```

---

## Repository Structure

```text
.
├── SKILL.md                  # Agent instructions, decision matrix, and safety rules
├── README.md                 # Documentation
└── scripts/
    ├── ask_video.py          # Video compression, splitting, and OpenRouter VLM client
    ├── frames.py             # ffmpeg frame extraction and Pillow contact-sheet builder
    ├── transcribe.py         # Silence-aware audio chunking and Whisper transcription
    └── openrouter_key.py     # Secure cross-platform API key resolver
```

---

## License

MIT
