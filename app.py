import os
import uuid
import tempfile
from flask import Flask, request, Response, send_file
from twilio.twiml.voice_response import VoiceResponse, Gather
from openai import OpenAI
from elevenlabs import set_api_key, generate

app = Flask(__name__)

# ----------------------
# CONFIG
# ----------------------
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
set_api_key(os.getenv("ELEVENLABS_API_KEY"))

YOUR_PHONE_NUMBER = "+13234576314"  # Google Voice
AI_ENABLED = True

temp_audio_files = {}

# ----------------------
# ELEVENLABS HELPER
# ----------------------
def generate_speech(text):
    """Generate speech with ElevenLabs and store temporarily"""
    try:
        audio_bytes = generate(
            text=text,
            voice="Rachel",
            model="eleven_multilingual_v2"
        )
        audio_id = str(uuid.uuid4())
        temp_audio_files[audio_id] = audio_bytes
        base_url = os.getenv("RENDER_EXTERNAL_URL", "https://your-app.onrender.com")
        return f"{base_url}/audio/{audio_id}.mp3"
    except Exception as e:
        print("ElevenLabs error:", e)
        return None

@app.route("/audio/<audio_id>.mp3")
def serve_audio(audio_id):
    if audio_id not in temp_audio_files:
        return "Audio not found", 404
    temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".mp3")
    temp_file.write(temp_audio_files[audio_id])
    temp_file.close()
    return send_file(temp_file.name, mimetype="audio/mpeg")

# ----------------------
# ROUTES
# ----------------------
@app.route("/voice", methods=["POST"])
def voice():
    """Forward call to your number for 6s, then AI pickup"""
    resp = VoiceResponse()
    dial = resp.dial(timeout=6, action="/ai-pickup", method="POST")
    dial.number(YOUR_PHONE_NUMBER)
    return Response(str(resp), mimetype="text/xml")

@app.route("/ai-pickup", methods=["POST"])
def ai_pickup():
    """AI answers if no human pickup"""
    resp = VoiceResponse()
    if not AI_ENABLED:
        resp.say("Sorry, no one is available. Please try again later.", voice="Polly.Joanna-Neural")
        resp.hangup()
        return Response(str(resp), mimetype="text/xml")

    greeting = "Thank you for calling Mount Masters, this is Daniel. How can I help you today?"
    audio_url = generate_speech(greeting)

    gather = resp.gather(input="speech", timeout=5, action="/process", speech_timeout="auto")
    if audio_url:
        gather.play(audio_url)
    else:
        gather.say(greeting, voice="Polly.Matthew-Neural")

    resp.record(play_beep=False, recording_status_callback="/handle-recording")
    resp.hangup()
    return Response(str(resp), mimetype="text/xml")

@app.route("/process", methods=["POST"])
def process():
    transcription = request.form.get("SpeechResult", "")
    resp = VoiceResponse()
    if transcription:
        answer = f"You said: {transcription}. We'll call you shortly."
    else:
        answer = "Sorry, I didn't catch that. Please call again later."
    audio_url = generate_speech(answer)
    if audio_url:
        resp.play(audio_url)
    else:
        resp.say(answer, voice="Polly.Matthew-Neural")
    resp.hangup()
    return Response(str(resp), mimetype="text/xml")

@app.route("/handle-recording", methods=["POST"])
def handle_recording():
    recording_url = request.form.get("RecordingUrl")
    print("Recording saved:", recording_url)
    resp = VoiceResponse()
    resp.say("Thank you! We received your message.", voice="Polly.Matthew-Neural")
    resp.hangup()
    return Response(str(resp), mimetype="text/xml")

@app.route("/")
def home():
    return "AI Receptionist Running! ✅", 200

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
