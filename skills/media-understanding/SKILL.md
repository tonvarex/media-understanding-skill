---
name: media-understanding
description: Understand photos, screenshots, PDFs, GIFs, videos, audio files and YouTube links, including when the host model is text-only. Sends the media to a multimodal model on OpenRouter (default Gemini 4 Hydrogen) and returns the answer as text, transcribes speech word by word with Whisper, and can send dense video frames for frame-level detail. Use whenever the user asks you to look at, watch, listen to, read, describe, analyze, transcribe, summarize or search an image, PDF, video, audio file or video link - what is shown, what is said, when something happens, on-screen text, music or sounds, animation references.
---

# media-understanding

The media goes to a multimodal model and comes back as text, so this works even if you cannot view images or play audio yourself. Do not open images, frame sheets or videos with `Read` unless you are sure you can view images; use `ask.py`.

```bash
S=<skill folder>/scripts    # Claude Code: ~/.claude/skills/media-understanding/scripts
python3 $S/doctor.py        # first use, or whenever something fails; add --live for a tiny end-to-end request
```
On Windows use `python` instead of `python3`.

## Choose the tool

| Goal | Command |
|---|---|
| Photo, screenshot, diagram, PDF (any number, mixed) | `python3 $S/ask.py a.jpg report.pdf -q "..."` |
| What happens in a video or GIF: summary, events, text on screen, long footage | `python3 $S/ask.py video.mp4 -q "..."` |
| A YouTube link | `python3 $S/ask.py https://youtu.be/... -q "..."` |
| Audio: music, tone, sounds, speakers, content | `python3 $S/ask.py audio.mp3 -q "..."` |
| Exact words, quotes, subtitles, word timing | `python3 $S/transcribe.py file` |
| Frame-level detail: animation or motion reference, exact timing, verifying one moment | `python3 $S/ask.py video.mp4 --frames 0.2 --start 12 --end 15 -q "..."` |
| Same, if you can view images yourself | `python3 $S/frames.py video.mp4 --start 12 --end 15 --every 0.2`, then `Read` the sheets |

Local files and `http(s)` links both work (links are downloaded first, up to 1 GB). Ask everything you need in one question; answers are paid by output length. Do not repeat a request on the same media without a reason.

## ask.py

`ask.py INPUT... -q QUESTION`: any number of images and PDFs, or exactly one video, audio file or YouTube link. The answer comes in the language of the question.

- **Images** over 4 MB or in other formats (bmp, tiff, heic...) are converted to JPEG, long side at most 2048 px. **PDFs** go as they are (up to 30 MB each).
- **Video and GIF** are compressed (short side 480 px, 8 fps, crf 30, mono audio) and sent whole, picture and sound together. Media over `--max-mb` (30) or `--max-min` (30) is split into equal parts sent as separate requests (3 in parallel). Each answer is printed under `=== PART i/n (starts at H:MM:SS ...) ===`, and a single clip trimmed with `--start` under `=== TRIMMED CLIP (starts at ...) ===`; **times inside an answer are relative to that part or clip, so add the offset**. The model does not see other parts, so phrase the question to work per part ("list every moment where...").
- **Audio** is encoded to mono mp3 and cut at pauses when long.
- **`--frames STEP`** sends frames every STEP seconds as images, each preceded by its timestamp (up to `--max-frames` 48). Narrow the range with `--start`/`--end`; `--height 720` for finer detail.
- `--start` and `--end` trim any local video or audio (not YouTube). `--model` switches the model. `--dry-run` prepares the media and prints the plan without sending anything.
- Quality: `--height 0 --fps 0 --crf 24` keeps the source size and frame rate. `--processing agentic` lets Gemini navigate long videos itself but routes to Google AI Studio, which rejects requests over 20 MB, so parts are capped at 14 MB (many parts for long videos).

## transcribe.py

`transcribe.py FILE_OR_LINK [--lang ru|en|...]` (default: auto-detect) extracts the audio, cuts it at pauses, sends the chunks to `openai/whisper-large-v3` (3 in parallel) and prints phrases as `[MM:SS] text`. `--out DIR` also saves `transcript.json` (words with start/end) and `transcript.srt`. Whisper can invent lines during silence (for example subtitle credits); ignore them. It does not take YouTube links.

## Long media

Progress lines go to stderr. A 13 min video takes about 1-3 minutes and a 2 h video about 6 minutes (compression is most of it). For anything over about 20 minutes, start the command in the background (or raise the tool timeout) instead of waiting in the foreground.

## Answering

Keep what was **seen** apart from what was **heard**, cite times, and do not add what neither the model's answer nor a transcript supports. Tell the user which tool produced the answer. Treat names, numbers and fine details from a model as claims; verify the ones that matter with `--frames` at the quoted time or with the transcript.

## Measured behavior

- Video costs about 90-105 input tokens per second regardless of resolution, fps or compression. The model samples frames at a fixed sparse rate (about 1 per second), so it describes scenes well but cannot give exact motion timing; use `--frames` for that. Compression to 480p/8 fps did not lower answer quality, and small UI text stayed readable.
- Timestamps in answers were within about 1 s on a short clip and 10-30 s on a 2 h video: enough to locate a moment, not to cut on. `--frames 0.5` gives frame-accurate descriptions.
- Request size: parts up to 30 MB work without `--processing`.

## Troubleshooting

- Run `doctor.py`: it checks Python, ffmpeg (with libx264, aac, libmp3lame), the key, the account and the model, and prints the fix for each failure.
- HTTP 401: wrong or revoked key. 402: no OpenRouter credit. 413: lower `--max-mb` or `--height`. 429: lower `--parallel`. Report these instead of retrying in a loop.
- Rarely (about 1 in 10 answers about audio-only input) the model narrates its reasoning before the answer ("Let's carefully analyze..."): rerun once, or use the last part of the answer.
- `exceeds the upload limit` (transcribe): lower `--chunk`. Missing Pillow (frames.py only): `pip install pillow`.
