# app.py
from flask import Flask, Response, request, send_file
from twilio.twiml.voice_response import VoiceResponse
from elevenlabs import generate, set_api_key
import os, uuid, tempfile, time

app = Flask(__name__)

# ----------------------
# CONFIGURATION
# ----------------------
set_api_key(os.getenv("ELEVENLABS_API_KEY"))

# Temporary audio storage
temp_audio_files = {}

def generate_speech_elevenlabs(text):
    """Generate speech using ElevenLabs and return temporary URL"""
    try:
        audio = generate(
            text=text,
            voice="yM93hbw8Qtvdma2wCnJG",  # Replace with your ElevenLabs voice ID
            model="eleven_multilingual_v2"
        )
        audio_id = str(uuid.uuid4())
        temp_audio_files[audio_id] = {
            'data': audio,
            'timestamp': time.time()
        }
        base_url = os.getenv("RENDER_EXTERNAL_URL", "http://localhost:5000")
        return f"{base_url}/audio/{audio_id}.mp3"
    except Exception as e:
        print(f"ElevenLabs error: {e}")
        return None

@app.route("/audio/<audio_id>.mp3")
def serve_audio(audio_id):
    if audio_id not in temp_audio_files:
        return "Audio not found", 404

    audio_data = temp_audio_files[audio_id]['data']
    temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".mp3")
    temp_file.write(audio_data)
    temp_file.close()
