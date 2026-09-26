# Cyber Scribe (v1)

Voice notes → local transcript → structured lab journal entry, straight into
your own study-folder structure. Built by and for
[The-Art-of-Hacking/h4cker](https://github.com/The-Art-of-Hacking/h4cker)
roadmap study (`00-Inbox`, `01-Foundations`, ... `10-References` by
default) — **but the folder names are fully configurable, not hardcoded.**
Set your own via `SCRIBE_PHASES` in `scribe.env` if you're following a
different course, curriculum, or personal structure entirely. See
**Configuring your own phase folders** below.

Built for the "Document" step of your Study → Lab → Explain → Document →
Exit Check loop. The point is that nothing said out loud during a lab gets
lost, and nothing uncertain gets silently turned into a fact.

## How it behaves (the rules baked in)

- **Raw transcripts are never discarded or edited.** Every recording's
  transcript is saved as-is to `00-Inbox/raw_<timestamp>_<label>.txt`
  before anything else happens.
- **Transcription is fully local** (faster-whisper, runs on CPU). Nothing
  about your lab work leaves your machine at this step.
- **Structuring only states what you actually said.** The transcript gets
  sorted into your journal template (Objective, Scope, Environment,
  Actions, Commands, Finding, Root Cause, Evidence, Detection
  Opportunities, Mitigation, What I Learned, etc.) by an LLM. Anything the
  transcript doesn't clearly support is marked `NEEDS VERIFICATION`
  instead of guessed.
- **Backend priority: Ollama → Anthropic → manual template.** The tool
  tries your local Ollama server first (free, fully offline). If Ollama
  isn't running and you've set `ANTHROPIC_API_KEY`, it falls back to that.
  If neither is available, you get a clean Markdown template with the full
  raw transcript dropped in for manual sorting. The tool never blocks on
  having any key.

## Setup

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Make sure Ollama is running (it's what does the structuring, free & local):
ollama serve
# and that you've pulled a model — check with: ollama list
# If your model isn't llama3.1, tell scribe.py which one to use:
export OLLAMA_MODEL=mistral   # or whatever `ollama list` shows you

# Optional fallback if Ollama isn't reachable — not needed otherwise:
export ANTHROPIC_API_KEY=sk-ant-...

# Point the tool at your actual journal folder from Phase 0:
export SCRIBE_JOURNAL_ROOT=/path/to/your/journal
```

You'll also need `ffmpeg` on your system (faster-whisper uses it to decode
audio): `sudo pacman -S ffmpeg` on Arch/Omarchy.

`scribe.py` auto-detects whether Ollama is reachable at
`http://localhost:11434` (override with `OLLAMA_HOST` if you run it
elsewhere) — no toggle needed, it just uses whatever's available.

## Configuring your own phase folders

This tool doesn't assume the H4CKER roadmap, or any specific course —
the folder names are just a config value. In `scribe.env` (copy it from
`scribe.env.example` if you haven't yet):

```
SCRIBE_PHASES=Inbox,Networking,Web-Security,Pentesting,CTFs,Reports
```

Comma-separated, any names you want. These become:
- the actual subfolders created under `SCRIBE_JOURNAL_ROOT`
- the phase dropdown options in the web app
- the valid `--phase` values for the CLI

Leave `SCRIBE_PHASES` blank or unset to fall back to the default H4CKER
roadmap phases (`00-Inbox` through `10-References`).

## Recommended: the web app

No fixed recording length — start, talk through the whole lab session, stop
whenever you're done. This is the workflow built for daily use while
studying.

```bash
source venv/bin/activate
python app.py
```

Open `http://localhost:5000`. Flow:

1. Enter a **topic** and pick the **phase folder** for this session.
2. **Start Recording** — talk through what you did. No time limit; **Stop
   Recording** whenever you're finished.
3. The recording gets transcribed locally (faster-whisper). The transcript
   appears in an editable box — fix any misheard words here before
   structuring.
4. **Structure Entry** — sends the transcript to Claude (if
   `ANTHROPIC_API_KEY` is set) to sort into your journal template. You'll
   see it as a status line while it works, then the structured Markdown
   appears, editable.
5. **Save Entry** — writes the `.md` file into the phase folder you picked,
   and shows you the saved path.

Everything stays fully local when Ollama is running — nothing about your
lab work leaves your machine, transcription or structuring. The transcript
text only goes out over the network if Ollama isn't reachable and
`ANTHROPIC_API_KEY` is set as a fallback (step #4).

Note on "live" transcription: the browser records the full clip, then
faster-whisper transcribes it after you hit Stop — it's not word-by-word
captioning while you talk. True streaming ASR needs a different (less
accurate, more resource-hungry) setup; for lab notes, transcribing right
after you stop is close enough to instant and keeps accuracy high.

## Running it without opening an IDE

Once you've done the one-time `pip install -r requirements.txt` setup above:

1. **Edit `scribe.env`** with your actual journal path and Ollama model —
   you only need to do this once:
   ```
   SCRIBE_JOURNAL_ROOT=/path/to/your/journal
   OLLAMA_MODEL=qwen2.5:7b-instruct-q4_K_M
   ```
2. **Run `./run.sh`** from a terminal (any terminal — no IDE needed). It
   activates the venv, loads `scribe.env`, starts the app, and opens your
   browser automatically.
3. **Optional — launch from your app launcher instead of a terminal:**
   edit `cyber-scribe.desktop`, fixing the `Exec=` line to the actual path
   where you put this project, then:
   ```bash
   cp cyber-scribe.desktop ~/.local/share/applications/
   ```
   "Cyber Scribe" should now show up in rofi/wofi/walker (whatever
   launcher Omarchy has you on) like any other app.

## Alternative: the command-line tool

Same underlying logic as the web app, useful for scripting or quick tests.
This is the fixed-duration version (`--seconds`) from before the web app existed.

**Full pipeline — record, transcribe, structure, save:**

```bash
python scribe.py entry --topic "SQLi lab on DVWA" --phase 04-Offensive --seconds 300
```

Talk through what you did for up to 5 minutes (`--seconds`), then it
transcribes, structures, and saves the entry into `04-Offensive/`.

**Already have an audio file (e.g. recorded on your phone)?**

```bash
python scribe.py entry --audio ./notes.wav --topic "AD enumeration" --phase 05-Active-Directory
```

**Run steps separately** (useful for debugging or reviewing the raw
transcript before structuring it):

```bash
python scribe.py record --seconds 300 --out session1.wav
python scribe.py transcribe --audio session1.wav --model small
python scribe.py structure --transcript ./journal/00-Inbox/raw_....txt \
    --topic "SQLi lab on DVWA" --phase 04-Offensive
```

## Transcription accuracy on infosec jargon

Whisper's default vocabulary doesn't know words like `nmap`, `vsftpd`, or
`CVE` well, so it substitutes the closest everyday-sounding words instead
("and map", "VS FTPD", "CBEs"). Two things are built in to help:

- **A vocabulary hint** (`VOCAB_HINT` in `scribe.py`) is passed to Whisper
  on every transcription, biasing it toward common pentest/infosec terms.
  Add your own frequently-used tool or term names to that constant if you
  keep hitting the same mistranscription.
- **GPU acceleration**: transcription tries your RTX 4050 (CUDA) first,
  falling back to CPU automatically if that's unavailable. This lets you
  comfortably use a larger, more accurate model instead of trading
  accuracy for speed.

Even with both, expect to fix a few words per session in the editable
transcript box before hitting **Structure Entry** — that's exactly why
that field is editable rather than locked.

## Whisper model sizes

`--model` accepts `tiny`, `base`, `small`, `medium` (default), `large-v3`.
Bigger = more accurate, slower, more VRAM/RAM. `medium` is a good balance
on your GPU; try `large-v3` if accuracy still isn't good enough and you
don't mind the extra couple of seconds per transcription. Drop to `small`
if you ever run this on CPU-only hardware and it feels too slow.

## What v1 deliberately doesn't do yet

- No auto-phase-detection — you tell it `--phase` each time.
- No editing of past entries — regenerate or hand-edit the `.md` file.
- No CTF/Project template variants — same structured template for
  everything for now.

These are natural v2 additions once the core loop (talk → get a Markdown
file in the right folder) is working reliably for you.