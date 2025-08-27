import os
import tempfile
from flask import Flask, request, send_file
from twilio.twiml.voice_response import VoiceResponse
from openai import OpenAI
from elevenlabs import generate, set_api_key

app = Flask(__name__)

# --- Load API keys ---
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY")
VOICE_ID = "dXHKnmELyDS5HzlpW0VN"

# init clients
openai_client = OpenAI(api_key=OPENAI_API_KEY)
set_api_key(ELEVENLABS_API_KEY)


@app.route("/voice", methods=["POST"])
def voice():
    """Handles incoming Twilio calls"""
    incoming_msg = request.values.get("SpeechResult", "Hello")

    # Step 1: OpenAI generates receptionist response
    response = openai_client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": "You are a friendly AI receptionist for a TV mounting business."},
            {"role": "user", "content": incoming_msg}
        ]
    )
    ai_text = response.choices[0].message.content

    # Step 2: ElevenLabs generates audio
    audio = generate(
        text=ai_text,
        voice=VOICE_ID,
        model="eleven_monolingual_v1"
    )

    # Save audio to temporary file
    with tempfile.NamedTemporaryFile(delete=False, suffix=".mp3") as f:
        f.write(audio)
        temp_path = f.name
        audio_url = request.url_root + "play_audio?file=" + temp_path

    # Step 3: Tell Twilio to play the audio
    resp = VoiceResponse()
    resp.play(audio_url)
    return str(resp)


@app.route("/play_audio")
def play_audio():
    """Serves the generated ElevenLabs audio"""
    file = request.args.get("file")
    return send_file(file, mimetype="audio/mpeg")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
