import os
import tempfile
from flask import Flask, request, send_file, abort
from twilio.twiml.voice_response import VoiceResponse
from openai import OpenAI
from elevenlabs import generate, set_api_key

app = Flask(__name__)

# --- Load API keys ---
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY")
VOICE_ID = "dXHKnmELyDS5HzlpW0VN"

if not OPENAI_API_KEY or not ELEVENLABS_API_KEY:
    raise ValueError("OPENAI_API_KEY and ELEVENLABS_API_KEY must be set as environment variables")

# init clients
openai_client = OpenAI(api_key=OPENAI_API_KEY)
set_api_key(ELEVENLABS_API_KEY)

# Keep track of temp files to clean up
TEMP_FILES = set()


@app.route("/voice", methods=["POST"])
def voice():
    """Handles incoming Twilio calls"""
    incoming_msg = request.values.get("SpeechResult", "Hello")

    # Step 1: OpenAI generates receptionist response
    try:
        response = openai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "You are a friendly AI receptionist for a TV mounting business."},
                {"role": "user", "content": incoming_msg}
            ]
        )
        ai_text = response.choices[0].message.content
    except Exception as e:
        ai_text = "Sorry, I am having trouble responding right now."
        print(f"OpenAI error: {e}")

    # Step 2: ElevenLabs generates audio
    try:
        audio_bytes = generate(
            text=ai_text,
            voice=VOICE_ID,
            model="eleven_monolingual_v1"
        )
    except Exception as e:
        print(f"ElevenLabs error: {e}")
        abort(500, "Error generating audio")

    # Save audio to temporary file
    with tempfile.NamedTemporaryFile(delete=False, suffix=".mp3") as f:
        f.write(audio_bytes)
        temp_path = f.name
        TEMP_FILES.add(temp_path)

    # Build URL for Twilio to fetch the audio
    audio_url = request.url_root + "play_audio?file=" + os.path.basename(temp_path)

    # Step 3: Tell Twilio to play the audio
    resp = VoiceResponse()
    resp.play(audio_url)
    return str(resp)


@app.route("/play_audio")
def play_audio():
    """Serves the generated ElevenLabs audio"""
    file_name = request.args.get("file")
    if not file_name:
        abort(400, "Missing file parameter")

    # Construct full path
    full_path = os.path.join(tempfile.gettempdir(), file_name)
    if not os.path.exists(full_path):
        abort(404, "File not found")

    return send_file(full_path, mimetype="audio/mpeg")


if __name__ == "__main__":
    # Optional: cleanup old temp files at startup
    for f in TEMP_FILES:
        if os.path.exists(f):
            os.remove(f)
    app.run(host="0.0.0.0", port=5000)
