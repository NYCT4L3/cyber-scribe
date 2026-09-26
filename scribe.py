#!/usr/bin/env python3
"""
Cyber Scribe — voice notes to structured lab journal entries.

Pipeline:
    record  -> raw .wav audio
    transcribe -> raw transcript (saved untouched to 00-Inbox/)
    structure  -> structured Markdown entry (saved to the chosen phase folder)

Design rules (from the roadmap):
    - The raw transcript is NEVER discarded or silently edited.
    - Anything the structuring step can't confidently fill is marked
      NEEDS VERIFICATION instead of being guessed.
    - Transcription runs fully offline (faster-whisper).
    - Structuring tries local Ollama first (fully offline, free), falls
      back to the Anthropic API if ANTHROPIC_API_KEY is set, and falls
      back further to a clean manual-fill template if neither is
      available — the tool never blocks on having any key.

Usage:
    python scribe.py entry --topic "SQL injection lab" --phase 04-Offensive
        (records from your mic, transcribes, structures, saves — full pipeline)

    python scribe.py entry --audio ./notes.wav --topic "..." --phase 05-Active-Directory
        (skip recording, use an existing audio file)

    python scribe.py record --seconds 300 --out raw_2026-09-26.wav
    python scribe.py transcribe --audio raw_2026-09-26.wav
    python scribe.py structure --transcript ./00-Inbox/raw_2026-09-26.txt \
        --topic "..." --phase 04-Offensive

Setup:
    pip install -r requirements.txt
    (optional, for AI-structured entries) export ANTHROPIC_API_KEY=sk-ant-...
"""

import argparse
import datetime
import os
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Config — adjust JOURNAL_ROOT to wherever your 00-Inbox / 01-Foundations /
# ... folder structure from Phase 0 actually lives.
# ---------------------------------------------------------------------------
JOURNAL_ROOT = Path(os.environ.get("SCRIBE_JOURNAL_ROOT", "./journal")).expanduser()
INBOX = JOURNAL_ROOT / "00-Inbox"

# Ollama is tried first for structuring (local, free). Override the model
# with `export OLLAMA_MODEL=mistral` etc. to match whatever you've pulled —
# check with `ollama list`.
OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "llama3.1")

_DEFAULT_PHASES = [
    "00-Inbox", "01-Foundations", "02-Networking", "03-Web", "04-Offensive",
    "05-Active-Directory", "06-Cloud", "07-Defensive", "08-Projects",
    "09-CTFs", "10-References",
]

# Override with a comma-separated list in SCRIBE_PHASES (or scribe.env) to
# match your own folder structure — this tool doesn't assume any one
# roadmap. Example: SCRIBE_PHASES=Inbox,Networking,Web,Pentesting,Reports
_phases_env = os.environ.get("SCRIBE_PHASES", "")
VALID_PHASES = (
    [p.strip() for p in _phases_env.split(",") if p.strip()]
    if _phases_env else _DEFAULT_PHASES
)

TEMPLATE_FIELDS = [
    "Objective", "Scope / Authorization", "Environment", "Initial State",
    "Actions Performed", "Commands / Requests Used", "Observed Output",
    "Finding", "Root Cause", "Security Impact", "Evidence",
    "Detection Opportunities", "Mitigation", "What I Learned",
    "Unverified Details / Follow-up",
]

NEEDS_VERIFICATION = "NEEDS VERIFICATION"


# ---------------------------------------------------------------------------
# Recording
# ---------------------------------------------------------------------------
def record_audio(out_path: Path, seconds: int, samplerate: int = 16000) -> Path:
    """Record from the default microphone. Requires sounddevice + numpy + soundfile."""
    try:
        import sounddevice as sd
        import soundfile as sf
    except ImportError:
        sys.exit(
            "Recording needs extra packages. Run:\n"
            "  pip install sounddevice soundfile numpy\n"
            "Or skip recording and pass --audio with an existing file."
        )

    print(f"Recording for {seconds}s... speak now (Ctrl+C to stop early).")
    try:
        audio = sd.rec(int(seconds * samplerate), samplerate=samplerate, channels=1)
        sd.wait()
    except KeyboardInterrupt:
        sd.stop()
        print("\nStopped early.")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(out_path), audio, samplerate)
    print(f"Saved audio -> {out_path}")
    return out_path


# ---------------------------------------------------------------------------
# Transcription (local, offline)
# ---------------------------------------------------------------------------
_MODEL_CACHE = {}

# Biases Whisper's decoder toward infosec/pentest vocabulary it wouldn't
# otherwise recognize well (nmap, vsftpd, CVE, etc.). Passed as initial_prompt
# — it doesn't get transcribed itself, it just primes recognition.
VOCAB_HINT = (
    "Cybersecurity lab notes. Tools and terms: nmap, vsftpd, Metasploitable, "
    "Kali Linux, CVE, backdoor, root shell, privilege escalation, SSH, FTP, "
    "SMB, Nmap -sV, enumeration, exploit, payload, Burp Suite, SQL injection, "
    "XSS, CSRF, SSRF, Active Directory, Kerberos, LDAP, Wireshark, Nikto, "
    "Metasploit, reverse shell, netcat, hash, IP address, subnet, firewall."
)


def get_whisper_model(model_size: str = "medium"):
    """Load (and cache) a faster-whisper model so repeated calls in the same
    process — e.g. from the web app — don't reload it from disk each time.
    Tries GPU (CUDA) first for speed/accuracy headroom, falls back to CPU
    automatically if no working CUDA setup is found."""
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        sys.exit(
            "Transcription needs faster-whisper. Run:\n"
            "  pip install faster-whisper"
        )
    if model_size in _MODEL_CACHE:
        return _MODEL_CACHE[model_size]

    print(f"Loading Whisper model ({model_size})... first run downloads it once.")
    try:
        model = WhisperModel(model_size, device="cuda", compute_type="float16")
        print("Using GPU (CUDA) for transcription.")
    except Exception:
        model = WhisperModel(model_size, device="cpu", compute_type="int8")
        print("GPU not available for Whisper — using CPU.")
    _MODEL_CACHE[model_size] = model
    return model


def transcribe_audio(audio_path: Path, model_size: str = "medium") -> str:
    """Transcribe with faster-whisper. Runs locally — nothing leaves the machine."""
    model = get_whisper_model(model_size)

    segments, info = model.transcribe(str(audio_path), beam_size=5, initial_prompt=VOCAB_HINT)
    print(f"Detected language: {info.language} (p={info.language_probability:.2f})")

    lines = []
    for seg in segments:
        lines.append(seg.text.strip())
    transcript = " ".join(lines).strip()
    return transcript


def save_raw_transcript(transcript: str, label: str) -> Path:
    """Raw transcripts always land in 00-Inbox, untouched, timestamped."""
    INBOX.mkdir(parents=True, exist_ok=True)
    ts = datetime.datetime.now().strftime("%Y-%m-%d_%H%M%S")
    safe_label = "".join(c if c.isalnum() or c in "-_" else "-" for c in label)[:40]
    path = INBOX / f"raw_{ts}_{safe_label}.txt"
    path.write_text(transcript, encoding="utf-8")
    print(f"Saved raw transcript -> {path}")
    return path


# ---------------------------------------------------------------------------
# Structuring
# ---------------------------------------------------------------------------
STRUCTURING_SYSTEM_PROMPT_TEMPLATE = (
    "You convert a raw, spoken lab-session transcript into a structured "
    "cybersecurity lab journal entry. Use ONLY what is stated or clearly "
    "implied in the transcript. For any field where the transcript gives "
    "no real information, or where a command, IP, version, or timestamp "
    "is ambiguous, write exactly \"{needs_verification}\" for that field "
    "or that detail — never invent specifics. Do not repeat the same "
    "sentence or fact across multiple fields just to fill space — if two "
    "fields would end up saying the same thing, put it in whichever field "
    "it actually belongs to and mark the other \"{needs_verification}\". "
    "A short or casual transcript with little real lab content should "
    "produce a mostly-\"{needs_verification}\" entry — that's correct, "
    "not a failure. Respond with ONLY a JSON object, no preamble, no "
    "markdown fences, with exactly these keys:\n"
    "{field_list}"
)


def _structuring_system_prompt() -> str:
    field_list = "\n".join(f"- {f}" for f in TEMPLATE_FIELDS)
    return STRUCTURING_SYSTEM_PROMPT_TEMPLATE.format(
        needs_verification=NEEDS_VERIFICATION, field_list=field_list
    )


def _parse_json_fields(text: str) -> dict:
    import json
    text = text.strip()
    text = text.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {}


def _ollama_available() -> bool:
    try:
        import requests
        r = requests.get(f"{OLLAMA_HOST}/api/tags", timeout=1.5)
        return r.status_code == 200
    except Exception:
        return False


def structure_with_ollama(transcript: str, topic: str, model: str = None) -> dict:
    """Ask a local Ollama model to draft the structured fields. Fully offline —
    nothing about your lab work leaves the machine for this step."""
    import requests

    model = model or OLLAMA_MODEL
    system = _structuring_system_prompt()
    user = f"Topic: {topic}\n\nRaw transcript:\n{transcript}"

    resp = requests.post(
        f"{OLLAMA_HOST}/api/chat",
        json={
            "model": model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "format": "json",
            "stream": False,
            "options": {"num_ctx": 8192},  # avoid silently truncating long lab sessions
        },
        timeout=300,  # generous — first call on a large/CPU-bound model can be slow
    )
    resp.raise_for_status()
    content = resp.json().get("message", {}).get("content", "")
    fields = _parse_json_fields(content)
    if not fields:
        print("Warning: could not parse structured JSON from Ollama; trying next backend.")
    return fields


def structure_transcript(transcript: str, topic: str) -> tuple[dict, str]:
    """Try structuring backends in order: local Ollama -> Anthropic API ->
    none (manual-fill template). Returns (fields, backend_used)."""
    if _ollama_available():
        try:
            fields = structure_with_ollama(transcript, topic)
            if fields:
                return fields, "ollama"
        except Exception as e:
            print(f"Warning: Ollama structuring failed ({e}); trying next backend.")
    else:
        print(f"Ollama not reachable at {OLLAMA_HOST} — is `ollama serve` running?")

    if os.environ.get("ANTHROPIC_API_KEY"):
        try:
            fields = structure_with_anthropic(transcript, topic)
            if fields:
                return fields, "anthropic"
        except Exception as e:
            print(f"Warning: Anthropic structuring failed ({e}).")

    print("No structuring backend available — saving raw-transcript template for manual fill.")
    return {}, "none"


def structure_with_anthropic(transcript: str, topic: str) -> dict:
    """Ask Claude to draft the structured fields from the raw transcript.
    Only used as a fallback if Ollama isn't reachable and ANTHROPIC_API_KEY
    is set. Anything not clearly stated in the transcript is left for the
    model to flag as NEEDS VERIFICATION rather than invented.
    """
    from anthropic import Anthropic

    client = Anthropic()  # reads ANTHROPIC_API_KEY from env
    system = _structuring_system_prompt()
    user = f"Topic: {topic}\n\nRaw transcript:\n{transcript}"

    resp = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=2000,
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    text = "".join(b.text for b in resp.content if b.type == "text").strip()
    fields = _parse_json_fields(text)
    if not fields:
        print("Warning: could not parse structured JSON from the model; falling back to raw template.")
    return fields


def build_markdown(topic: str, fields: dict, transcript: str, raw_transcript_path: Path) -> str:
    date = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    lines = [f"# {topic}", "", f"*Logged {date} — raw transcript: `{raw_transcript_path.name}`*", ""]
    for field in TEMPLATE_FIELDS:
        value = fields.get(field, "").strip() if fields else ""
        if not value:
            value = NEEDS_VERIFICATION
        lines.append(f"## {field}")
        lines.append(value)
        lines.append("")

    if not fields:
        # No AI structuring available — keep the full raw transcript visible
        # instead of hiding it, so nothing is lost.
        lines.append("## Raw Transcript (unstructured — fill sections above manually)")
        lines.append(transcript)
        lines.append("")

    return "\n".join(lines)


def save_structured_entry(markdown: str, topic: str, phase: str) -> Path:
    if phase not in VALID_PHASES:
        sys.exit(f"--phase must be one of: {', '.join(VALID_PHASES)}")
    folder = JOURNAL_ROOT / phase
    folder.mkdir(parents=True, exist_ok=True)
    ts = datetime.datetime.now().strftime("%Y-%m-%d")
    safe_topic = "".join(c if c.isalnum() or c in "-_ " else "" for c in topic).strip().replace(" ", "-")[:60]
    path = folder / f"{ts}_{safe_topic or 'entry'}.md"
    path.write_text(markdown, encoding="utf-8")
    print(f"Saved structured entry -> {path}")
    return path


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def cmd_record(args):
    record_audio(Path(args.out), args.seconds)


def cmd_transcribe(args):
    transcript = transcribe_audio(Path(args.audio), args.model)
    save_raw_transcript(transcript, Path(args.audio).stem)
    print("\n--- Transcript ---\n")
    print(transcript)


def cmd_structure(args):
    transcript = Path(args.transcript).read_text(encoding="utf-8")
    fields, backend = structure_transcript(transcript, args.topic)
    print(f"Structuring backend used: {backend}")
    md = build_markdown(args.topic, fields, transcript, Path(args.transcript))
    save_structured_entry(md, args.topic, args.phase)


def cmd_entry(args):
    # Full pipeline: record (or use --audio) -> transcribe -> structure -> save
    if args.audio:
        audio_path = Path(args.audio)
    else:
        ts = datetime.datetime.now().strftime("%Y-%m-%d_%H%M%S")
        audio_path = Path(f"/tmp/scribe_{ts}.wav")
        record_audio(audio_path, args.seconds)

    transcript = transcribe_audio(audio_path, args.model)
    raw_path = save_raw_transcript(transcript, args.topic)

    fields, backend = structure_transcript(transcript, args.topic)
    print(f"Structuring backend used: {backend}")

    md = build_markdown(args.topic, fields, transcript, raw_path)
    save_structured_entry(md, args.topic, args.phase)


def main():
    parser = argparse.ArgumentParser(description="Cyber Scribe: voice -> transcript -> structured journal entry")
    sub = parser.add_subparsers(dest="command", required=True)

    p_record = sub.add_parser("record", help="Record audio from the mic")
    p_record.add_argument("--seconds", type=int, default=180)
    p_record.add_argument("--out", default="/tmp/scribe_recording.wav")
    p_record.set_defaults(func=cmd_record)

    p_trans = sub.add_parser("transcribe", help="Transcribe an existing audio file")
    p_trans.add_argument("--audio", required=True)
    p_trans.add_argument("--model", default="medium", help="tiny/base/small/medium/large-v3")
    p_trans.set_defaults(func=cmd_transcribe)

    p_struct = sub.add_parser("structure", help="Turn a saved transcript into a structured entry")
    p_struct.add_argument("--transcript", required=True)
    p_struct.add_argument("--topic", required=True)
    p_struct.add_argument("--phase", required=True, choices=VALID_PHASES)
    p_struct.set_defaults(func=cmd_structure)

    p_entry = sub.add_parser("entry", help="Full pipeline: record/audio -> transcribe -> structure -> save")
    p_entry.add_argument("--audio", help="Use an existing audio file instead of recording")
    p_entry.add_argument("--seconds", type=int, default=180, help="Recording length if no --audio given")
    p_entry.add_argument("--model", default="medium")
    p_entry.add_argument("--topic", required=True)
    p_entry.add_argument("--phase", required=True, choices=VALID_PHASES)
    p_entry.set_defaults(func=cmd_entry)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()