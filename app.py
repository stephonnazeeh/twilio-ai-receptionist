import os
import tempfile
import requests
from flask import Flask, request, send_file
from twilio.twiml.voice_response import VoiceResponse
from openai import OpenAI
from elevenlabs import ElevenLabs

app = Flask(__name__)

# --- Load API keys ---
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY")

openai_client = OpenAI(api_key=OPENAI_API_KEY)
eleven_client = ElevenLabs(api_key=ELEVENLABS_API_KEY)

# Your ElevenLabs voice ID
VOICE_ID = "dXHKnmELyDS5HzlpW0VN"

@app.route("/voice", methods=["POST"])
def voice():
    """Handles incoming Twilio calls"""
    incoming_msg = request.values.get("SpeechResult", "Hello")
    
    # Step 1: Get AI response from OpenAI
    response = openai_client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": "You are a friendly AI receptionist for a TV mounting business."},
            {"role": "user", "content": incoming_msg}
        ]
    )
    ai_text = response.choices[0].message.content
    
    # Step 2: Get ElevenLabs audio
    audio = eleven_client.text_to_speech.convert(
        voice_id=VOICE_ID,
        model_id="eleven_monolingual_v1",
        text=ai_text
    )

    # Save to temp file
    with tempfile.NamedTemporaryFile(delete=False, suffix=".mp3") as f:
        f.write(audio)
        audio_url = request.url_root + "play_audio?file=" + f.name
    
    # Step 3: Build Twilio response
    resp = VoiceResponse()
    resp.play(audio_url)
    return str(resp)

@app.route("/play_audio")
def play_audio():
    """Serves generated ElevenLabs audio"""
    file = request.args.get("file")
    return send_file(file, mimetype="audio/mpeg")

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
