from flask import Flask, request, Response, send_file
from twilio.twiml.voice_response import VoiceResponse, Gather
from twilio.rest import Client
from openai import OpenAI
from elevenlabs import ElevenLabs
import os
import tempfile
import uuid
import time

app = Flask(__name__)

# ----------------------
# CONFIGURATION
# ----------------------

# Environment API keys
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY")
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
TWILIO_PHONE_NUMBER = os.getenv("TWILIO_PHONE_NUMBER")
YOUR_PHONE_NUMBER = "+13234576314"  # Google Voice

# Initialize clients
client = OpenAI(api_key=OPENAI_API_KEY)
eleven_client = ElevenLabs(api_key=ELEVENLABS_API_KEY)
twilio_client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)

# Store temporary audio
temp_audio_files = {}

# Conversation memory
conversations = {}

# Scheduling
scheduled_days = {day: False for day in ["monday","tuesday","wednesday","thursday","friday","saturday","sunday"]}

# AI toggle
AI_ENABLED = True

# Base URL for serving audio
BASE_URL = os.getenv("RENDER_EXTERNAL_URL", "https://twilio-ai-receptionist.onrender.com")

# Pricing info
PRICING_INFO = """<PASTE YOUR PRICING INFO HERE>"""  # Keep your existing pricing text

# ----------------------
# ELEVENLABS HELPER
# ----------------------

def generate_speech_elevenlabs(text: str) -> str | None:
    try:
        audio = eleven_client.text_to_speech(
            text=text,
            voice="yM93hbw8Qtvdma2wCnJG",
            model="eleven_multilingual_v2"
        )
        audio_id = str(uuid.uuid4())
        temp_audio_files[audio_id] = {"data": audio, "timestamp": time.time()}
        return f"{BASE_URL}/audio/{audio_id}.mp3"
    except Exception as e:
        print(f"ElevenLabs error: {e}")
        return None

def cleanup_old_audio():
    now = time.time()
    to_remove = [k for k,v in temp_audio_files.items() if now - v['timestamp'] > 600]
    for k in to_remove: del temp_audio_files[k]

@app.route("/audio/<audio_id>.mp3")
def serve_audio(audio_id):
    cleanup_old_audio()
    if audio_id not in temp_audio_files:
        return "Audio not found", 404
    audio_data = temp_audio_files[audio_id]['data']
    tmp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".mp3")
    tmp_file.write(audio_data)
    tmp_file.close()
    return send_file(tmp_file.name, mimetype="audio/mpeg")


# ----------------------
# ROUTES
# ----------------------

@app.route("/voice", methods=["POST"])
def voice():
    resp = VoiceResponse()
    dial = resp.dial(
        timeout=6,
        action="/ai-pickup",
        method="POST",
        record="record-from-answer"
    )
    dial.number(YOUR_PHONE_NUMBER)
    return Response(str(resp), mimetype="text/xml")


@app.route("/ai-pickup", methods=["POST"])
def ai_pickup():
    resp = VoiceResponse()
    if not AI_ENABLED:
        resp.say("Sorry, the receptionist is unavailable. Please try again later.")
        resp.hangup()
        return Response(str(resp), mimetype="text/xml")
    
    status = request.form.get("DialCallStatus","")
    if status in ["no-answer","busy","failed"]:
        greeting = "Thank you for calling Mount Masters, this is Daniel, how can I help you today?"
        audio_url = generate_speech_elevenlabs(greeting)
        gather = resp.gather(input="speech", timeout=4, action="/process", speech_timeout="auto", enhanced=True)
        if audio_url: gather.play(audio_url)
        else: gather.say(greeting)
        resp.record(play_beep=False, recording_status_callback="/handle-recording")
        resp.hangup()
    else:
        resp.hangup()
    return Response(str(resp), mimetype="text/xml")


@app.route("/process", methods=["POST"])
def process():
    transcription = request.form.get("SpeechResult","")
    call_sid = request.form.get("CallSid","")
    resp = VoiceResponse()

    if call_sid not in conversations: conversations[call_sid] = {"messages": []}
    if transcription: conversations[call_sid]["messages"].append({"role":"user","content":transcription})

    try:
        messages = [
            {"role":"system","content":PRICING_INFO}
        ] + conversations[call_sid]["messages"][-6:]

        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=messages,
            max_tokens=120,
            temperature=0.7
        )

        answer = response.choices[0].message.content
        conversations[call_sid]["messages"].append({"role":"assistant","content":answer})

        audio_url = generate_speech_elevenlabs(answer)
        if audio_url: resp.play(audio_url)
        else: resp.say(answer)

        if not is_conversation_ending(answer):
            gather = resp.gather(input="speech", timeout=5, action="/process", speech_timeout="auto", enhanced=True)
            followup_text = "Anything else I can help you with?"
            followup_audio = generate_speech_elevenlabs(followup_text)
            if followup_audio: gather.play(followup_audio)
            else: gather.say(followup_text)

        resp.hangup()
    except Exception as e:
        print(f"OpenAI error: {e}")
        resp.say("Tech hiccup, recording your info.")
        resp.record(action="/handle-recording", max_length=60)
    return Response(str(resp), mimetype="text/xml")


@app.route("/handle-recording", methods=["POST"])
def handle_recording():
    recording_url = request.form.get("RecordingUrl")
    transcription = request.form.get("TranscriptionText")
    print(f"Recording saved: {recording_url}, transcription: {transcription}")
    resp = VoiceResponse()
    final_text = "Perfect, got it! Someone will call you back today to schedule your TV mounting. Thanks!"
    audio_url = generate_speech_elevenlabs(final_text)
    if audio_url: resp.play(audio_url)
    else: resp.say(final_text)
    resp.hangup()
    return Response(str(resp), mimetype="text/xml")


# ----------------------
# HELPERS
# ----------------------
def is_conversation_ending(resp_text):
    phrases = ["thanks for calling","have a great day","we'll be in touch","someone will call you","talk to you soon","goodbye","schedule your mounting"]
    return any(p in resp_text.lower() for p in phrases)


@app.before_request
def cleanup_conversations():
    if len(conversations) > 100:
        keys_to_remove = list(conversations.keys())[:-50]
        for k in keys_to_remove: del conversations[k]


@app.route("/")
def home():
    return "TV Mounting AI Receptionist is running! 📺📞", 200


@app.route("/health")
def health():
    return {
        "status": "healthy",
        "openai_key": "set" if OPENAI_API_KEY else "missing",
        "elevenlabs_key": "set" if ELEVENLABS_API_KEY else "missing",
        "twilio_configured": "yes" if TWILIO_ACCOUNT_SID else "no",
        "scheduled_days": scheduled_days
    }, 200


if __name__ == "__main__":
    port = int(os.environ.get("PORT",5000))
    app.run(host="0.0.0.0", port=port)

