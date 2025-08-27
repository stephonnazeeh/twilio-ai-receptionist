import os
import uuid
import tempfile
import time
import requests
from flask import Flask, request, Response, send_file
from twilio.twiml.voice_response import VoiceResponse

app = Flask(__name__)

# ----------------------
# CONFIG
# ----------------------

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY")
TWILIO_PHONE_NUMBER = os.getenv("TWILIO_PHONE_NUMBER")
YOUR_PHONE_NUMBER = "+13234576314"  # Your Google Voice number

# Temporary audio storage
temp_audio_files = {}

# ----------------------
# ElevenLabs via HTTP
# ----------------------

def generate_speech_elevenlabs(text):
    """Generate speech using ElevenLabs HTTP API and return URL for playback"""
    try:
        url = "https://api.elevenlabs.io/v1/text-to-speech/yM93hbw8Qtvdma2wCnJG"
        headers = {
            "xi-api-key": ELEVENLABS_API_KEY,
            "Content-Type": "application/json"
        }
        payload = {
            "text": text,
            "voice_settings": {
                "stability": 0.5,
                "similarity_boost": 0.8,
                "style": 0.2
            }
        }
        response = requests.post(url, json=payload)
        response.raise_for_status()
        audio_bytes = response.content

        # Save temporarily
        audio_id = str(uuid.uuid4())
        temp_audio_files[audio_id] = {
            "data": audio_bytes,
            "timestamp": time.time()
        }

        base_url = os.getenv("RENDER_EXTERNAL_URL", "https://your-app.onrender.com")
        return f"{base_url}/audio/{audio_id}.mp3"

    except Exception as e:
        print("ElevenLabs error:", e)
        return None

def cleanup_old_audio():
    """Remove old audio files > 10 min"""
    now = time.time()
    to_delete = [k for k, v in temp_audio_files.items() if now - v["timestamp"] > 600]
    for k in to_delete:
        del temp_audio_files[k]

@app.route("/audio/<audio_id>.mp3")
def serve_audio(audio_id):
    cleanup_old_audio()
    if audio_id not in temp_audio_files:
        return "Audio not found", 404

    data = temp_audio_files[audio_id]["data"]
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".mp3")
    tmp.write(data)
    tmp.close()
    return send_file(tmp.name, mimetype="audio/mpeg", as_attachment=False)

# ----------------------
# Twilio Call Routes
# ----------------------

@app.route("/voice", methods=["POST"])
def voice():
    resp = VoiceResponse()
    dial = resp.dial(timeout=6, action="/ai-pickup", method="POST")
    dial.number(YOUR_PHONE_NUMBER)
    return Response(str(resp), mimetype="text/xml")

@app.route("/ai-pickup", methods=["POST"])
def ai_pickup():
    resp = VoiceResponse()
    greeting = "Thank you for calling Mount Masters, this is Daniel, how can I help you today?"
    audio_url = generate_speech_elevenlabs(greeting)
    gather = resp.gather(input="speech", timeout=5, action="/process", speech_timeout="auto", enhanced=True)
    if audio_url:
        gather.play(audio_url)
    else:
        gather.say(greeting)
    resp.record(play_beep=False, recording_status_callback="/handle-recording")
    resp.hangup()
    return Response(str(resp), mimetype="text/xml")

@app.route("/process", methods=["POST"])
def process():
    transcription = request.form.get("SpeechResult", "")
    resp = VoiceResponse()
    if not transcription:
        resp.say("Sorry, I couldn't hear you.")
    else:
        # Here you could add OpenAI processing
        resp.say(f"You said: {transcription}")
    resp.hangup()
    return Response(str(resp), mimetype="text/xml")

@app.route("/handle-recording", methods=["POST"])
def handle_recording():
    recording_url = request.form.get("RecordingUrl")
    print("Recording saved:", recording_url)
    resp = VoiceResponse()
    resp.say("Thanks! Someone will call you back shortly.")
    resp.hangup()
    return Response(str(resp), mimetype="text/xml")

# ----------------------
# Health Check
# ----------------------
@app.route("/health")
def health():
    return {"status": "healthy"}, 200

# ----------------------
# Run
# ----------------------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
