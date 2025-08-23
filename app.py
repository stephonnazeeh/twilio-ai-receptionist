from flask import Flask, request, Response
from twilio.twiml.voice_response import VoiceResponse, Gather
import twilio.rest
import os
from openai import OpenAI

app = Flask(__name__)

# ----------------------
# CONFIGURATION
# ----------------------

# Initialize OpenAI client
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# Initialize Twilio client
twilio_client = twilio.rest.Client(
    os.getenv("TWILIO_ACCOUNT_SID"),
    os.getenv("TWILIO_AUTH_TOKEN")
)

# Store conversation states (in production, use Redis or DB)
conversations = {}

# Phone numbers
YOUR_PHONE_NUMBER = "+13234576314"  # Google Voice number
TWILIO_PHONE_NUMBER = os.getenv("TWILIO_PHONE_NUMBER")

# Toggle AI answering
AI_ENABLED = True  # Set False to stop AI from answering calls

# Business pricing info
PRICING_INFO = """
CURRENT PRICING (always mention free estimates available):

PLUMBING:
- Basic repairs (leaks, clogs): $150-250
- Toilet/faucet replacement: $200-400
- Water heater repair: $300-500
- Major plumbing (repiping): $1000-3000

ELECTRICAL:
- Outlet/switch work: $150-300
- Light fixture install: $100-250
- Panel upgrades: $1200-2500
- Whole house rewiring: $3000-8000

HVAC:
- AC tune-up: $150-200
- Repair calls: $200-400
- New AC unit: $3500-7000
- Ductwork: $1500-4000

HANDYMAN:
- $85/hour (2 hour minimum)
- Most small jobs: $200-500
- Drywall repair: $150-300
- Painting (per room): $300-800

CLEANING:
- Regular house cleaning: $120-250
- Deep cleaning: $200-400
- Move-in/out: $250-500

LANDSCAPING:
- Lawn maintenance: $50-100/visit
- Tree trimming: $300-800
- Landscape design: $800-2500
- Irrigation install: $1500-4000
"""

# ----------------------
# ROUTES
# ----------------------

@app.route("/voice", methods=["POST"])
def voice():
    resp = VoiceResponse()
    
    # Ring your Google Voice number for 6 seconds, now recording
    dial = resp.dial(
        timeout=6,
        action="/ai-pickup",
        method="POST",
        record="record-from-answer"  # Record from the moment call is answered
    )
    dial.number(YOUR_PHONE_NUMBER)
    
    return Response(str(resp), mimetype="text/xml")


@app.route("/ai-pickup", methods=["POST"])
def ai_pickup():
    """Runs if you don’t answer within 6 seconds."""
    if not AI_ENABLED:
        # AI is off — hang up politely
        resp = VoiceResponse()
        resp.say("Sorry, the receptionist is unavailable. Please try again later.", voice="Polly.Joanna-Neural")
        resp.hangup()
        return Response(str(resp), mimetype="text/xml")
    
    resp = VoiceResponse()
    dial_status = request.form.get("DialCallStatus", "")
    
    if dial_status in ["no-answer", "busy", "failed"]:
        resp.pause(length=1)
        
        # Gather speech input from caller
        gather = resp.gather(
            input="speech",
            timeout=4,
            action="/process",
            speech_timeout="auto",
            enhanced=True
        )
        gather.say(
            "Hey there! So sorry I missed your call - I was probably helping another customer. "
            "I'm here now though, and I'd love to help you out. What kind of home service are you looking for today?",
            voice="Polly.Joanna-Neural"
        )
        
        # Record AI interaction as backup
        resp.record(play_beep=False, recording_status_callback="/handle-recording")
        
        resp.say("Hmm, I didn't catch that. Feel free to call back when you're ready to chat!", voice="Polly.Joanna-Neural")
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
    
    if not transcription:
        resp.say("Sorry, I couldn't quite catch that. What were you looking for help with?", voice="Polly.Joanna-Neural")
        gather = resp.gather(
            input="speech",
            timeout=4,
            action="/process",
            speech_timeout="auto",
            enhanced=True
        )
        gather.say("I'm all ears...", voice="Polly.Joanna-Neural")
        return Response(str(resp), mimetype="text/xml")
    
    try:
        if call_sid not in conversations:
            conversations[call_sid] = {"messages": [], "caller": caller_number}
        
        conversations[call_sid]["messages"].append({"role": "user", "content": transcription})
        
        # Build conversation messages for OpenAI
        messages = [
            {
                "role": "system",
                "content": f"""You are Sarah, a super friendly receptionist for a home services business.
{PRICING_INFO}

AVAILABILITY:
- Mon-Fri: 8 AM - 6 PM
- Sat: 9 AM - 4 PM
- Sun: Emergency only

CONVERSATION STYLE:
- Casual, helpful, conversational
- Use contractions, ask follow-ups naturally
- Keep responses short (under 30 words)
- Always mention free estimates
"""
            }
        ]
        messages.extend(conversations[call_sid]["messages"][-6:])
        
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=messages,
            max_tokens=100,
            temperature=0.7
        )
        
        answer = response.choices[0].message.content
        conversations[call_sid]["messages"].append({"role": "assistant", "content": answer})
        
        resp.say(answer, voice="Polly.Joanna-Neural")
        
        if not is_conversation_ending(answer):
            gather = resp.gather(
                input="speech",
                timeout=5,
                action="/process",
                speech_timeout="auto",
                enhanced=True
            )
            gather.say("Is there anything else I can help you with today?", voice="Polly.Joanna-Neural")
            resp.say("Thanks for calling! Have a great day!", voice="Polly.Joanna-Neural")
        else:
            resp.say("Thanks so much for calling! We'll be in touch soon.", voice="Polly.Joanna-Neural")
        
        resp.hangup()
        
    except Exception as e:
        print(f"OpenAI error: {e}")
        resp.say("No worries, I'm having a little tech hiccup. Let me grab your name and number quickly.", voice="Polly.Joanna-Neural")
        resp.record(action="/handle-recording", max_length=60, transcribe=True)
    
    return Response(str(resp), mimetype="text/xml")


@app.route("/handle-recording", methods=["POST"])
def handle_recording():
    recording_url = request.form.get("RecordingUrl")
    transcription = request.form.get("TranscriptionText")
    
    print(f"Recording saved: {recording_url}")
    if transcription:
        print(f"Transcription: {transcription}")
    
    resp = VoiceResponse()
    resp.say("Perfect, got it! Someone will call you back today. Thanks for calling!", voice="Polly.Joanna-Neural")
    resp.hangup()
    
    return Response(str(resp), mimetype="text/xml")


# ----------------------
# HELPER FUNCTIONS
# ----------------------

def is_conversation_ending(response):
    ending_phrases = [
        "thanks for calling",
        "have a great day",
        "we'll be in touch",
        "someone will call you",
        "talk to you soon",
        "goodbye",
        "we'll contact you"
    ]
    return any(phrase in response.lower() for phrase in ending_phrases)


# ----------------------
# MISC
# ----------------------

@app.route("/")
def home():
    return "Twilio AI Receptionist is running! 📞", 200

@app.route("/health")
def health():
    return {
        "status": "healthy",
        "openai_key": "set" if os.getenv("OPENAI_API_KEY") else "missing",
        "twilio_configured": "yes" if os.getenv("TWILIO_ACCOUNT_SID") else "no"
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

