import os
import tempfile
import uuid
from flask import Flask, request, Response, send_file
from twilio.twiml.voice_response import VoiceResponse, Gather
from openai import OpenAI
from elevenlabs import set_api_key, generate_text_to_speech

app = Flask(__name__)

# ----------------------
# CONFIGURATION
# ----------------------
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
set_api_key(os.getenv("ELEVENLABS_API_KEY"))

YOUR_PHONE_NUMBER = "+13234576314"
TWILIO_PHONE_NUMBER = os.getenv("TWILIO_PHONE_NUMBER")
AI_ENABLED = True

# Conversation & scheduling storage
conversations = {}
scheduled_days = {day: False for day in ["monday","tuesday","wednesday","thursday","friday","saturday","sunday"]}

# Pricing info (your full flow)
PRICING_INFO = """
TV MOUNTING SERVICES - MOUNT MASTERS:
- 28-49": $99
- 50-76": $120
- 77-86": $139
Cord hiding options, scheduling, etc...
"""

# ----------------------
# HELPER: ElevenLabs TTS
# ----------------------
def generate_speech(text):
    try:
        audio = generate_text_to_speech(
            text=text,
            voice="yM93hbw8Qtvdma2wCnJG",
            model="eleven_multilingual_v2"
        )
        audio_id = str(uuid.uuid4())
        path = f"/tmp/{audio_id}.mp3"
        with open(path, "wb") as f:
            f.write(audio)
        base_url = os.getenv("RENDER_EXTERNAL_URL", "https://your-render-url.onrender.com")
        return f"{base_url}/audio/{audio_id}.mp3"
    except Exception as e:
        print("ElevenLabs error:", e)
        return None

@app.route("/audio/<audio_id>.mp3")
def serve_audio(audio_id):
    path = f"/tmp/{audio_id}.mp3"
    if not os.path.exists(path):
        return "Audio not found", 404
    return send_file(path, mimetype="audio/mpeg")

# ----------------------
# ROUTES
# ----------------------
@app.route("/voice", methods=["POST"])
def voice():
    resp = VoiceResponse()
    dial = resp.dial(timeout=6, action="/ai-pickup")
    dial.number(YOUR_PHONE_NUMBER)
    return Response(str(resp), mimetype="text/xml")

@app.route("/ai-pickup", methods=["POST"])
def ai_pickup():
    if not AI_ENABLED:
        resp = VoiceResponse()
        resp.say("Sorry, the receptionist is unavailable.", voice="Polly.Joanna-Neural")
        resp.hangup()
        return Response(str(resp), mimetype="text/xml")

    resp = VoiceResponse()
    greeting = "Thank you for calling Mount Masters, this is Daniel, how can I help you today?"
    audio_url = generate_speech(greeting)
    gather = resp.gather(input="speech", timeout=5, action="/process", speech_timeout="auto")
    if audio_url:
        gather.play(audio_url)
    else:
        gather.say(greeting, voice="Polly.Matthew-Neural")
    resp.record(play_beep=False, recording_status_callback="/handle-recording")
    return Response(str(resp), mimetype="text/xml")

@app.route("/process", methods=["POST"])
def process():
    transcription = request.form.get("SpeechResult", "")
    call_sid = request.form.get("CallSid", "")
    caller_number = request.form.get("From", "Unknown")
    resp = VoiceResponse()

    if call_sid not in conversations:
        conversations[call_sid] = {"messages": [], "caller": caller_number}
    conversations[call_sid]["messages"].append({"role": "user", "content": transcription})

    messages = [
        {"role": "system", "content": f"You are Daniel, professional TV mounting receptionist.\n{PRICING_INFO}"}
    ] + conversations[call_sid]["messages"][-6:]

    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=messages,
            max_tokens=120,
            temperature=0.7
        )
        answer = response.choices[0].message.content
        conversations[call_sid]["messages"].append({"role": "assistant", "content": answer})

        audio_url = generate_speech(answer)
        if audio_url:
            resp.play(audio_url)
        else:
            resp.say(answer, voice="Polly.Matthew-Neural")
        resp.hangup()
    except Exception as e:
        print("OpenAI error:", e)
        resp.say("Sorry, a tech hiccup occurred.", voice="Polly.Matthew-Neural")
        resp.hangup()

    return Response(str(resp), mimetype="text/xml")

@app.route("/handle-recording", methods=["POST"])
def handle_recording():
    resp = VoiceResponse()
    resp.say("Got it! We'll call you back today.", voice="Polly.Matthew-Neural")
    resp.hangup()
    return Response(str(resp), mimetype="text/xml")

@app.route("/")
def home():
    return "TV Mounting AI Receptionist is running!", 200

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
