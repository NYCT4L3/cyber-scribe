#!/usr/bin/env python3
"""
Cyber Scribe — local web app.

Start/stop recording in the browser (no fixed time limit) -> transcript
appears once you stop -> a structured journal entry gets generated ->
review and save it into your journal folder structure.

Everything runs on your machine. Audio and transcripts never leave it
except the transcript text itself, which is sent to the Anthropic API
only if you've set ANTHROPIC_API_KEY (structuring step).

Run:
    python app.py
Then open:
    http://localhost:5000
"""

import os
import tempfile
from pathlib import Path

from flask import Flask, jsonify, render_template, request

import scribe  # reuses record/transcribe/structure/save logic from the CLI tool

app = Flask(__name__)

# Cap upload size generously (long lab sessions = big audio files)
app.config["MAX_CONTENT_LENGTH"] = 500 * 1024 * 1024  # 500 MB


@app.route("/")
def index():
    ollama_up = scribe._ollama_available()
    return render_template(
        "index.html",
        phases=scribe.VALID_PHASES,
        ollama_up=ollama_up,
        has_api_key=bool(os.environ.get("ANTHROPIC_API_KEY")),
        structuring_available=ollama_up or bool(os.environ.get("ANTHROPIC_API_KEY")),
    )


@app.route("/api/transcribe", methods=["POST"])
def api_transcribe():
    if "audio" not in request.files:
        return jsonify({"error": "No audio file received."}), 400

    audio_file = request.files["audio"]
    topic = request.form.get("topic", "session").strip() or "session"
    model_size = request.form.get("model", "medium")

    suffix = Path(audio_file.filename or "clip.webm").suffix or ".webm"
    tmp_path = Path(tempfile.mktemp(suffix=suffix))
    audio_file.save(tmp_path)

    try:
        transcript = scribe.transcribe_audio(tmp_path, model_size=model_size)
    except Exception as e:
        return jsonify({"error": f"Transcription failed: {e}"}), 500
    finally:
        tmp_path.unlink(missing_ok=True)

    if not transcript.strip():
        return jsonify({"error": "No speech detected in that recording. Try again."}), 422

    raw_path = scribe.save_raw_transcript(transcript, topic)
    return jsonify({"transcript": transcript, "raw_path": str(raw_path)})


@app.route("/api/structure", methods=["POST"])
def api_structure():
    data = request.get_json(force=True)
    transcript = data.get("transcript", "")
    topic = data.get("topic", "session")
    raw_path = Path(data.get("raw_path", "transcript.txt"))

    if not transcript.strip():
        return jsonify({"error": "No transcript to structure."}), 400

    fields, backend = scribe.structure_transcript(transcript, topic)
    markdown = scribe.build_markdown(topic, fields, transcript, raw_path)
    return jsonify({"markdown": markdown, "backend": backend, "fields": fields})


@app.route("/api/save", methods=["POST"])
def api_save():
    data = request.get_json(force=True)
    markdown = data.get("markdown", "")
    topic = data.get("topic", "entry")
    phase = data.get("phase", "00-Inbox")

    if phase not in scribe.VALID_PHASES:
        return jsonify({"error": f"Invalid phase: {phase}"}), 400
    if not markdown.strip():
        return jsonify({"error": "Nothing to save."}), 400

    path = scribe.save_structured_entry(markdown, topic, phase)
    return jsonify({"path": str(path)})


if __name__ == "__main__":
    print(f"Journal root: {scribe.JOURNAL_ROOT.resolve()}")
    print("Open http://localhost:5000 in your browser.")

    # Only open the browser in the actual running process, not Flask's
    # debug-mode reloader parent (which would otherwise open two tabs).
    if os.environ.get("WERKZEUG_RUN_MAIN") == "true" or not app.debug:
        import threading
        import webbrowser
        threading.Timer(1.0, lambda: webbrowser.open("http://localhost:5000")).start()

    app.run(debug=True, port=5000)