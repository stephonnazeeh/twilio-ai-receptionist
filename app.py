# app.py
from flask import Flask, request, Response, send_file
from twilio.twiml.voice_response import VoiceResponse, Gather
from openai import OpenAI
from elevenlabs import generate, set_api_key
import os, tempfile, uuid, time

app = Flask(__name__)

# ----------------------
# CONFIGURATION
# ----------------------
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
set_api_key(os.getenv("ELEVENLABS_API_KEY"))

YOUR_PHONE_NUMBER = "+13234576314"  # Your Google Voice
TWILIO_PHONE_NUMBER = os.getenv("TWILIO_PHONE_NUMBER")
AI_ENABLED = True

# Temp audio storage
temp_audio_files = {}

# ----------------------
# HELPER FUNCTIONS
# ----------------------
def generate_speech(text: str):
    """Return URL to temp MP3 file"""
    try:
        audio_bytes = generate(
            text=text,
            voice="yM93hbw8Qtvdma2wCnJG",
            model="eleven_multilingual_v2",
            voice_settings={
                "stability": 0.5,
                "similarity_boost": 0.8,
                "style": 0.2,
                "use_speaker_boost": True
            }
        )

        audio_id = str(uuid.uuid4())
        temp_audio_files[audio_id] = {"data": audio_bytes, "timestamp": time.time()}

        base_url = os.getenv("RENDER_EXTERNAL_URL", "http://localhost:5000")
        return f"{base_url}/audio/{audio_id}.mp3"
    except Exception as e:
        print("ElevenLabs error:", e)
        return None

def cleanup_old_audio():
    now = time.time()
    for k in list(temp_audio_files.keys()):
        if now - temp_audio_files[k]["timestamp"] > 600:
            del temp_audio_files[k]

# ----------------------
# ROUTES
# ----------------------
@app.route("/audio/<audio_id>.mp3")
def serve_audio(audio_id):
    cleanup_old_audio()
    if audio_id not in temp_audio_files:
        return "Audio not found", 404
    data = temp_audio_files[audio_id]["data"]

    temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".mp3")
    temp_file.write(data)
    temp_file.close()

    return send_file(temp_file.name, mimetype="audio/mpeg")

@app.route("/voice", methods=["POST"])
def voice():
    """Main webhook for incoming call"""
    resp = VoiceResponse()
    dial = resp.dial(timeout=6, action="/ai-pickup", method="POST")
    dial.number(YOUR_PHONE_NUMBER)
    return Response(str(resp), mimetype="text/xml")

@app.route("/ai-pickup", methods=["POST"])
def ai_pickup():
    """AI answers if no one picks up"""
    if not AI_ENABLED:
        resp = VoiceResponse()
        resp.say("Sorry, we're unavailable. Please try again later.")
        resp.hangup()
        return Response(str(resp), mimetype="text/xml")

    resp = VoiceResponse()
    greeting_text = "Thank you for calling Mount Masters, this is Daniel. How can I help you today?"
    audio_url = generate_speech(greeting_text)

    gather = resp.gather(input="speech", timeout=5, action="/process", speech_timeout="auto")
    if audio_url:
        gather.play(audio_url)
    else:
        gather.say(greeting_text)

    resp.hangup()
    return Response(str(resp), mimetype="text/xml")

@app.route("/process", methods=["POST"])
def process():
    transcription = request.form.get("SpeechResult", "")
    resp = VoiceResponse()

    if not transcription:
        resp.say("Sorry, I didn't catch that. Please call again.")
        resp.hangup()
        return Response(str(resp), mimetype="text/xml")

    # Generate AI response
    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "You are Daniel, a professional TV mounting receptionist."},
                {"role": "user", "content": transcription}
            ],
            max_tokens=100
        )
        answer = response.choices[0].message.content
    except Exception as e:
        print("OpenAI error:", e)
        answer = "Sorry, a technical error occurred. Please leave a message."

    audio_url = generate_speech(answer)
    if audio_url:
        resp.play(audio_url)
    else:
        resp.say(answer)

    resp.hangup()
    return Response(str(resp), mimetype="text/xml")

@app.route("/")
def home():
    return "AI Receptionist is running!"

@app.route("/health")
def health():
    return {"status": "healthy", "keys": {"openai": bool(os.getenv("OPENAI_API_KEY")), "elevenlabs": bool(os.getenv("ELEVENLABS_API_KEY"))}}

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)

