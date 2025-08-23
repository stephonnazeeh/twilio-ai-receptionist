from flask import Flask, request, Response
from twilio.twiml.voice_response import VoiceResponse, Gather
import twilio.rest
import os
from openai import OpenAI

app = Flask(__name__)

# Initialize OpenAI client with new API
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# Initialize Twilio client for SMS (still here if you want SMS later)
twilio_client = twilio.rest.Client(
    os.getenv("TWILIO_ACCOUNT_SID"),
    os.getenv("TWILIO_AUTH_TOKEN")
)

# Store conversation states (in production, use Redis or database)
conversations = {}

# Your phone number to receive summaries
YOUR_PHONE_NUMBER = "+13234576314"  # Your Google Voice number
TWILIO_PHONE_NUMBER = os.getenv("TWILIO_PHONE_NUMBER")  # Your Twilio number

# PRICING INFO (unchanged)
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

@app.route("/voice", methods=["POST"])
def voice():
    resp = VoiceResponse()
    
    # Ring your cell via Google Voice for 6 seconds - NOW RECORDING
    dial = resp.dial(
        timeout=6,
        action="/ai-pickup", 
        method="POST",
        record="record-from-answer"   # <-- record when call is answered
    )
    dial.number(YOUR_PHONE_NUMBER)  # Your Google Voice number
    
    return Response(str(resp), mimetype="text/xml")

@app.route("/ai-pickup", methods=["POST"])
def ai_pickup():
    """This only runs if YOU don't answer within 6 seconds"""
    resp = VoiceResponse()
    dial_status = request.form.get("DialCallStatus", "")
    
    # Only proceed if the call wasn't answered
    if dial_status in ["no-answer", "busy", "failed"]:
        # Small pause before AI starts
        resp.pause(length=1)
        
        # Gather speech input from the caller - NOW RECORDING AI CONVERSATION
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
        
        # Also record the AI interaction
        resp.record(
            play_beep=False,
            recording_status_callback="/handle-recording"
        )
        
        # Fallback if no speech detected
        resp.say("Hmm, I didn't catch that. Feel free to call back when you're ready to chat!", voice="Polly.Joanna-Neural")
        resp.hangup()
    else:
        # If you answered, just hang up the AI side
        resp.hangup()
    
    return Response(str(resp), mimetype="text/xml")

@app.route("/process", methods=["POST"])
def process():
    transcription = request.form.get("SpeechResult", "")
    call_sid = request.form.get("CallSid", "")
    caller_number = request.form.get("From", "Unknown")
    
    resp = VoiceResponse()
    
    if not transcription:
        resp.say("Sorry, I couldn't quite catch that - maybe the connection cut out for a sec? What were you looking for help with?", 
                voice="Polly.Joanna-Neural")
        
        # Give them another chance
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
        # Get or create conversation history
        if call_sid not in conversations:
            conversations[call_sid] = {"messages": [], "caller": caller_number}
        
        conversations[call_sid]["messages"].append({"role": "user", "content": transcription})
        
        # Create messages with conversation history
        messages = [
            {
                "role": "system", 
                "content": f"""You are Sarah, a super friendly and conversational receptionist for a home services business. 
Talk like a real person - use casual language, contractions, and be genuinely helpful.

{PRICING_INFO}

AVAILABILITY:
- Monday-Friday: 8 AM - 6 PM
- Saturday: 9 AM - 4 PM  
- Sunday: Emergency only
- We can usually get someone out within 24-48 hours
- Emergency calls: same day or next morning

CONVERSATION STYLE:
- Sound like you're actually talking to someone, not reading a script
- Use "um," "you know," and natural speech patterns occasionally
- Keep responses under 30 words but be conversational
- Ask follow-up questions naturally
- Get their name early and use it
- If they want to schedule, get name, phone, service, and preferred timing
- Always mention we do free estimates

Remember: You're having a real conversation with someone who called for help!"""
            }
        ]
        
        # Add conversation history (keep last 6 messages for context)
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
        
        # Continue conversation unless it's clearly ending
        if not is_conversation_ending(answer):
            gather = resp.gather(
                input="speech", 
                timeout=5, 
                action="/process",
                speech_timeout="auto",
                enhanced=True
            )
            gather.say("Is there anything else I can help you with today?", voice="Polly.Joanna-Neural")
            
            # Fallback ending
            resp.say("Thanks for calling! Have a great day!", voice="Polly.Joanna-Neural")
        else:
            resp.say("Thanks so much for calling! We'll be in touch soon.", voice="Polly.Joanna-Neural")
        
        resp.hangup()
        
    except Exception as e:
        print(f"OpenAI error: {e}")
        resp.say("No worries, I'm having a little tech hiccup on my end. "
                 "Let me just grab your name and number real quick so someone can call you right back, okay?", 
                voice="Polly.Joanna-Neural")
        
        # Record their info as backup
        resp.record(
            action="/handle-recording",
            max_length=60,
            transcribe=True
        )
    
    return Response(str(resp), mimetype="text/xml")

@app.route("/handle-recording", methods=["POST"])
def handle_recording():
    """Handle voicemail/recording info"""
    recording_url = request.form.get("RecordingUrl")
    transcription = request.form.get("TranscriptionText")
    
    print(f"Recording saved: {recording_url}")
    if transcription:
        print(f"Transcription: {transcription}")
    
    resp = VoiceResponse()
    resp.say("Perfect, got it! Someone's definitely gonna call you back today. Thanks so much for calling!", 
            voice="Polly.Joanna-Neural")
    resp.hangup()
    
    return Response(str(resp), mimetype="text/xml")

def is_conversation_ending(response):
    """Check if the AI response indicates the conversation should end"""
    ending_phrases = [
        "thanks for calling",
        "have a great day",
        "we'll be in touch",
        "someone will call you",
        "talk to you soon",
        "goodbye",
        "we'll contact you"
    ]
    
    response_lower = response.lower()
    return any(phrase in response_lower for phrase in ending_phrases)

@app.route("/")
def home():
    return "Twilio AI Receptionist is running! 📞", 200

@app.route("/health")
def health():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "openai_key": "set" if os.getenv("OPENAI_API_KEY") else "missing",
        "twilio_configured": "yes" if os.getenv("TWILIO_ACCOUNT_SID") else "no"
    }, 200

# Clean up old conversations periodically (basic cleanup)
@app.before_request
def cleanup_conversations():
    if len(conversations) > 100:
        # Keep only the 50 most recent conversations
        keys_to_remove = list(conversations.keys())[:-50]
        for key in keys_to_remove:
            del conversations[key]

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
