# media-understanding

Agent skill that gives any LLM native-like understanding of **images, PDFs, GIFs, videos, audio and YouTube links** through [OpenRouter](https://openrouter.ai), even when the model itself is text-only.

The agent runs one command, the media goes to a multimodal model (Gemini 4 Hydrogen by default), and the answer comes back as text. Exact speech comes from Whisper, word by word.

## Quick Start

**1. Install ffmpeg** (Python 3.9+ is the only other requirement)

macOS:

```bash
brew install ffmpeg
```

Linux (Debian/Ubuntu):

```bash
sudo apt install ffmpeg
```

Windows (PowerShell):

```powershell
winget install ffmpeg
```

**2. Get a key at [openrouter.ai/keys](https://openrouter.ai/keys) and set it**

macOS / Linux: add this line to `~/.zshrc` or `~/.bashrc`:

```bash
export MUS_OPENROUTER_API_KEY="sk-or-..."
```

Windows (PowerShell):

```powershell
setx MUS_OPENROUTER_API_KEY "sk-or-..."
```

**3. Install the skill**

```bash
npx skills add tonvarex/media-understanding-skill
```

**4. Restart your agent and check the setup**

macOS / Linux:

```bash
python3 <skill folder>/scripts/doctor.py --live
```

Windows (PowerShell):

```powershell
python <skill folder>\scripts\doctor.py --live
```

`<skill folder>` is the `media-understanding` folder inside your agent's skills directory.

Then just ask your agent: "what's in this screenshot?", "summarize this video", "what did the speaker say at 12:40?".

## Features

- **Everything in one skill**: photos, screenshots, PDFs, GIFs, videos, audio, YouTube links and plain URLs
- **Picture and sound together**: a video is understood as a whole, with its audio track, not as a silent slideshow
- **Works with text-only models**: the agent never has to view an image itself
- **Long media just works**: big files are compressed, cut into parts, processed in parallel, and the timestamps are shifted back for you (a 2 hour video takes about 6 minutes)
- **Frame-level mode**: `--frames 0.2` sends dense timestamped frames of a short range, for animation references, exact timing and verifying a single moment
- **Word-level transcription**: Whisper with per-word timing, long audio cut at pauses, saves `transcript.json` and `transcript.srt`
- **Zero Python dependencies**: standard library plus ffmpeg, no SDKs, no `pip install`
- **One key, one variable**: `MUS_OPENROUTER_API_KEY`, nothing is written to disk
- **Built-in `doctor.py`**: checks Python, ffmpeg, the key, the account balance and the model, and tells you how to fix what is wrong
- **Clear errors and progress**: bad key, no credit, wrong file type, rate limits all say what to do

## Why not just one video API call?

| | media-understanding |
|---|---|
| Local video over the request size limit | Compressed to 480p / 8 fps, split automatically |
| Timestamps of the second part of a long video | Each part is labeled with its offset |
| Exact motion timing | `--frames` mode (the model samples video only about once per second) |
| iPhone photos (HEIC), BMP, TIFF, huge images | Converted to JPEG automatically |
| Animated GIF / WebP | Treated as video, not as one frame |
| Voice notes and music | Understood by the model, or transcribed word by word |

## Installation

### With the skills CLI (recommended)

```bash
npx skills add tonvarex/media-understanding-skill
```

The CLI asks which agents to install for and whether to install globally or into the current project.

### Manual

Clone the repository and copy `skills/media-understanding` into your agent's skills directory.

```bash
git clone https://github.com/tonvarex/media-understanding-skill.git
```

Restart the agent after setting the variable: a running session keeps its old environment, and apps started from the Dock, Finder or Start menu do not read shell profiles (start the agent from a terminal, or set the variable system-wide).

## Usage

```bash
S=<skill folder>/scripts

# Images and PDFs, any number
python3 $S/ask.py before.png after.png -q "List every visual difference"
python3 $S/ask.py report.pdf -q "Summarize the key numbers"

# Video, GIF, YouTube
python3 $S/ask.py talk.mp4 -q "List the main points with timestamps"
python3 $S/ask.py https://youtu.be/VIDEO_ID -q "What is this video about?"

# Audio: music, tone, speakers
python3 $S/ask.py voice.ogg -q "What do I need to do?"

# Frame-level detail of a short range
python3 $S/ask.py demo.mp4 --frames 0.25 --start 12 --end 15 -q "How does the menu animate?"

# Exact words with timing
python3 $S/transcribe.py interview.mp3 --lang en --out ./transcript
```

On Windows use `python` instead of `python3`.

## Tools

| Script | What it does |
|---|---|
| `ask.py` | Ask a question about images, PDFs, a video, GIF, audio file or YouTube link |
| `transcribe.py` | Word-level transcription with Whisper, optional `.json` and `.srt` |
| `frames.py` | Contact sheets of timestamped frames, for agents that can view images (needs Pillow) |
| `doctor.py` | Checks the installation, `--live` sends one tiny test request |

Useful options of `ask.py`: `--start` / `--end` trim a local file, `--frames STEP` sends dense frames, `--model` picks another model, `--dry-run` shows the plan without sending anything. Run `--help` for the rest.

## Configuration

| Variable | Purpose |
|---|---|
| `MUS_OPENROUTER_API_KEY` | OpenRouter API key (required) |
| `MUS_MODEL` | Default model instead of `google/gemini-4-hydrogen` |

## Cost and privacy

You pay OpenRouter per request: about half a cent for an image or a 2-page PDF, 3 cents for a 45-second video, about $1.3 for a 2-hour video. The media is uploaded to OpenRouter and the model provider, so do not use it on files you would not send to a third-party API.

## Platforms

Tested on macOS (Python 3.9 and 3.12). Linux and Windows have not been run yet, issues and fixes are welcome.

## License

MIT
