from flask import Flask, request, Response, send_file
from twilio.twiml.voice_response import VoiceResponse, Gather
import twilio.rest
import os
from openai import OpenAI
from elevenlabs import generate, set_api_key
import tempfile
import uuid
import time

app = Flask(__name__)

# ----------------------
# CONFIGURATION
# ----------------------

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
set_api_key(os.getenv("ELEVENLABS_API_KEY"))

twilio_client = twilio.rest.Client(
    os.getenv("TWILIO_ACCOUNT_SID"),
    os.getenv("TWILIO_AUTH_TOKEN")
)

temp_audio_files = {}
conversations = {}
scheduled_days = {
    "monday": False,
    "tuesday": False,
    "wednesday": False,
    "thursday": False,
    "friday": False,
    "saturday": False,
    "sunday": False
}

YOUR_PHONE_NUMBER = "+13234576314"  # Google Voice number
TWILIO_PHONE_NUMBER = os.getenv("TWILIO_PHONE_NUMBER")
AI_ENABLED = True

PRICING_INFO = """
TV MOUNTING SERVICES - MOUNT MASTERS:

TV MOUNTING PRICES:
- 28-49": $99 for mounting
- 50-76": $120 for mounting  
- 77-86": $139 for mounting
- Multiple TVs: Calculate each TV separately

TV MOUNTS (if customer needs one):
- Full Motion Mount: $65
- Standard Mount: $35
- No charge if customer has their own

CORD HIDING OPTIONS:
- Outlet behind TV: $175 per TV
- Plastic cord cover: available
- Leave cords hanging: free

OTHER SERVICES:
- TV takedown/removal: $70 per TV

SERVICE AREA:
- Los Angeles + 25 mile radius
- Outside 25 miles: callback required
- Over 50 miles/other states: politely decline

SCHEDULING:
- Same day mounting available
- Mon/Thu/Fri/Sat/Sun: 7:30 PM+
- Tue/Wed: Anytime after 12 PM
- One appointment per day

CONVERSATION FLOW:
1. Greet: "Thank you for calling Mount Masters, this is Daniel, how can I help you?"
2. Ask TV size and quantity
3. Ask what city they're in
4. Ask about cord hiding preferences  
5. Offer same day mounting
6. Schedule based on availability

IMPORTANT: We only do TV mounting — nothing else!
"""

# ----------------------
# ELEVENLABS HELPERS
# ----------------------

def generate_speech_elevenlabs(text):
    try:
        audio = generate(
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
        temp_audio_files[audio_id] = {'data': audio, 'timestamp': time.time()}
        base_url = os.getenv("RENDER_EXTERNAL_URL", "https://twilio-ai-receptionist.onrender.com")
        return f"{base_url}/audio/{audio_id}.mp3"
    except Exception as e:
        print(f"ElevenLabs error: {e}")
        return None

def cleanup_old_audio():
    now = time.time()
    for key in list(temp_audio_files.keys()):
        if now - temp_audio_files[key]['timestamp'] > 600:
            del temp_audio_files[key]

@app.route("/audio/<audio_id>.mp3")
def serve_audio(audio_id):
    cleanup_old_audio()
    if audio_id not in temp_audio_files:
        return "Audio not found", 404
    data = temp_audio_files[audio_id]['data']
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".mp3")
    tmp.write(data)
    tmp.close()
    return send_file(tmp.name, mimetype='audio/mpeg', as_attachment=False, download_name=f"{audio_id}.mp3")

# ----------------------
# TWILIO ROUTES
# ----------------------

@app.route("/voice", methods=["POST"])
def voice():
    resp = VoiceResponse()
    dial = resp.dial(timeout=6, action="/ai-pickup", method="POST", record="record-from-answer")
    dial.number(YOUR_PHONE_NUMBER)
    return Response(str(resp), mimetype="text/xml")

@app.route("/ai-pickup", methods=["POST"])
def ai_pickup():
    resp = VoiceResponse()
    if not AI_ENABLED:
        resp.say("Sorry, the receptionist is unavailable. Please try again later.")
        resp.hangup()
        return Response(str(resp), mimetype="text/xml")

    dial_status = request.form.get("DialCallStatus", "")
    if dial_status in ["no-answer", "busy", "failed"]:
        greeting = "Thank you for calling Mount Masters, this is Daniel, how can I help you today?"
        audio_url = generate_speech_elevenlabs(greeting)
        gather = resp.gather(input="speech", timeout=4, action="/process", speech_timeout="auto", enhanced=True)
        if audio_url:
            gather.play(audio_url)
        else:
            gather.say(greeting)
        resp.record(play_beep=False, recording_status_callback="/handle-recording")
        fallback_text = "I didn't catch that. Feel free to call Mount Masters back anytime!"
        fallback_audio = generate_speech_elevenlabs(fallback_text)
        if fallback_audio:
            resp.play(fallback_audio)
        else:
            resp.say(fallback_text)
        resp.hangup()
    else:
        resp.hangup()
    return Response(str(resp), mimetype="text/xml")

@app.route("/process", methods=["POST"])
def process():
    transcription = request.form.get("SpeechResult", "")
    call_sid = request.form.get("CallSid", "")
    caller_number = request.form.get("From", "Unknown")
    resp = VoiceResponse()

    if call_sid not in conversations:
        conversations[call_sid] = {"messages": [], "caller": caller_number}

    if transcription:
        conversations[call_sid]["messages"].append({"role": "user", "content": transcription})
        messages = [{"role": "system", "content": f"You are Daniel, a TV mounting receptionist.\n{PRICING_INFO}"}]
        messages.extend(conversations[call_sid]["messages"][-6:])
        try:
            response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=messages,
                max_tokens=120,
                temperature=0.7
            )
            answer = response.choices[0].message.content
            conversations[call_sid]["messages"].append({"role": "assistant", "content": answer})
            audio_url = generate_speech_elevenlabs(answer)
            if audio_url:
                resp.play(audio_url)
            else:
                resp.say(answer)
            if not any(phrase in answer.lower() for phrase in [
                "thanks for calling", "have a great day", "we'll be in touch",
                "someone will call you", "talk to you soon", "goodbye",
                "we'll contact you", "schedule your mounting"
            ]):
                gather = resp.gather(input="speech", timeout=5, action="/process",
                                     speech_timeout="auto", enhanced=True)
                followup_text = "Anything else I can help you with?"
                followup_audio = generate_speech_elevenlabs(followup_text)
                if followup_audio:
                    gather.play(followup_audio)
                else:
                    gather.say(followup_text)
                closing_text = "Thanks for calling! Have a great day!"
                closing_audio = generate_speech_elevenlabs(closing_text)
                if closing_audio:
                    resp.play(closing_audio)
                else:
                    resp.say(closing_text)
            else:
                final_text = "Thanks so much for calling! We'll be in touch soon to schedule your mounting."
                final_audio = generate_speech_elevenlabs(final_text)
                if final_audio:
                    resp.play(final_audio)
                else:
                    resp.say(final_text)
        except Exception as e:
            print(f"OpenAI error: {e}")
            error_text = "No worries, I'm having a little tech hiccup. Let me grab your name and number quickly."
            error_audio = generate_speech_elevenlabs(error_text)
            if error_audio:
                resp.play(error_audio)
            else:
                resp.say(error_text)
            resp.record(action="/handle-recording", max_length=60, transcribe=True)
    else:
        clarify_text = "Sorry, I couldn't catch that. How can I help you today?"
        clarify_audio = generate_speech_elevenlabs(clarify_text)
        if clarify_audio:
            resp.play(clarify_audio)
        else:
            resp.say(clarify_text)
    resp.hangup()
    return Response(str(resp), mimetype="text/xml")

@app.route("/handle-recording", methods=["POST"])
def handle_recording():
    recording_url = request.form.get("RecordingUrl")
    transcription = request.form.get("TranscriptionText")
    print(f"Recording saved: {recording_url}")
    if transcription:
        print(f"Transcription: {transcription}")
    resp = VoiceResponse()
    final_text = "Perfect, got it! Someone will call you back today to schedule your TV mounting. Thanks!"
    final_audio = generate_speech_elevenlabs(final_text)
    if final_audio:
        resp.play(final_audio)
    else:
        resp.say(final_text)
    resp.hangup()
    return Response(str(resp), mimetype="text/xml")

# ----------------------
# HEALTH & HOME
# ----------------------

@app.route("/")
def home():
    return "TV Mounting AI Receptionist is running! 📺📞", 200

@app.route("/health")
def health():
    return {
        "status": "healthy",
        "openai_key": "set" if os.getenv("OPENAI_API_KEY") else "missing",
        "elevenlabs_key": "set" if os.getenv("ELEVENLABS_API_KEY") else "missing", 
        "twilio_configured": "yes" if os.getenv("TWILIO_ACCOUNT_SID") else "no",
        "scheduled_days": scheduled_days
    }, 200

@app.before_request
def cleanup_conversations():
    if len(conversations) > 100:
        keys_to_remove = list(conversations.keys())[:-50]
        for key in keys_to_remove:
            del conversations[key]

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)

