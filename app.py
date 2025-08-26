from flask import Flask, request, Response, send_file
from twilio.twiml.voice_response import VoiceResponse, Gather
import twilio.rest
import os
from openai import OpenAI
from elevenlabs.client import ElevenLabs
from elevenlabs import VoiceSettings
import tempfile
import uuid
import threading
import time

app = Flask(__name__)

# ----------------------
# CONFIGURATION
# ----------------------

# Initialize OpenAI client
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# Initialize ElevenLabs client
elevenlabs_client = ElevenLabs(api_key=os.getenv("ELEVENLABS_API_KEY"))

# Store temporary audio files
temp_audio_files = {}

# Initialize Twilio client
twilio_client = twilio.rest.Client(
    os.getenv("TWILIO_ACCOUNT_SID"),
    os.getenv("TWILIO_AUTH_TOKEN")
)

# Store conversation states (in production, use Redis or DB)
conversations = {}

# Store scheduling (in production, use Redis or DB)
# Format: {"monday": False, "tuesday": False, "wednesday": False, "thursday": False, "friday": False, "saturday": False, "sunday": False}
scheduled_days = {
    "monday": False,
    "tuesday": False, 
    "wednesday": False,
    "thursday": False,
    "friday": False,
    "saturday": False,
    "sunday": False
}

# Phone numbers
YOUR_PHONE_NUMBER = "+13234576314"  # Google Voice number
TWILIO_PHONE_NUMBER = os.getenv("TWILIO_PHONE_NUMBER")

# Toggle AI answering
AI_ENABLED = True  # Set False to stop AI from answering calls

# Business pricing info
PRICING_INFO = """
TV MOUNTING SERVICES - MOUNT MASTERS:

TV MOUNTING PRICES:
- 28-49": $99 for mounting
- 50-76": $120 for mounting  
- 77-86": $139 for mounting
- Multiple TVs: Calculate each TV separately

TV MOUNTS (if customer needs one):
- Full Motion Mount: $65 (swivels, tilts, extends from wall - perfect for corner viewing or reducing glare)
- Standard Mount: $35 (fixed position, sits flat against wall)
- No charge for bracket if customer has their own

CORD HIDING OPTIONS:
- Hiding cords with outlet behind TV: $175 per TV (cleanest, most premium look)
- Plastic cord cover: Available option (mention as alternative)
- Leave cords hanging: Free option

OTHER SERVICES:
- TV takedown/removal: $70 per TV

SERVICE AREA:
- Los Angeles and within 25 mile radius
- Outside 25 miles: Owner callback required, collect number
- Over 50 miles/other states: Politely decline, don't service that area

SCHEDULING:
- Same day mounting available
- Mon/Thu/Fri/Sat/Sun: 7:30 PM or later (high demand during day)
- Tuesday/Wednesday: Anytime after 12 PM
- Track bookings: Only one appointment per day, schedule next available day

CONVERSATION FLOW:
1. Greet: "Thank you for calling Mount Masters, this is Daniel, how can I help you?"
2. Ask TV size and quantity
3. Ask what city they're in (check service area)
4. Ask about cord hiding preferences  
5. Offer same day mounting
6. Schedule based on availability

IMPORTANT: We specialize in TV mounting only - no other services!
"""

# ----------------------
# ELEVENLABS HELPER
# ----------------------

def generate_speech_elevenlabs(text):
    """Generate speech using ElevenLabs and create temporary URL"""
    try:
        # Generate audio with ElevenLabs
        audio_generator = elevenlabs_client.generate(
            text=text,
            voice="yM93hbw8Qtvdma2wCnJG",
            model="eleven_multilingual_v2",
            voice_settings=VoiceSettings(
                stability=0.5,
                similarity_boost=0.8,
                style=0.2,
                use_speaker_boost=True
            )
        )
        
        # Convert generator to bytes
        audio_bytes = b"".join(chunk for chunk in audio_generator)
        
        # Create unique filename
        audio_id = str(uuid.uuid4())
        
        # Store audio in memory temporarily
        temp_audio_files[audio_id] = {
            'data': audio_bytes,
            'timestamp': time.time()
        }
        
        # Return URL that our app can serve
        base_url = os.getenv("RENDER_EXTERNAL_URL", "https://twilio-ai-receptionist.onrender.com")
        return f"{base_url}/audio/{audio_id}.mp3"
        
    except Exception as e:
        print(f"ElevenLabs error: {e}")
        return None

def cleanup_old_audio():
    """Remove audio files older than 10 minutes"""
    current_time = time.time()
    to_remove = []
    for audio_id, data in temp_audio_files.items():
        if current_time - data['timestamp'] > 600:  # 10 minutes
            to_remove.append(audio_id)
    
    for audio_id in to_remove:
        del temp_audio_files[audio_id]

@app.route("/audio/<audio_id>.mp3")
def serve_audio(audio_id):
    """Serve temporary audio files"""
    cleanup_old_audio()
    
    if audio_id not in temp_audio_files:
        return "Audio not found", 404
    
    audio_data = temp_audio_files[audio_id]['data']
    
    # Create temporary file
    temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.mp3')
    temp_file.write(audio_data)
    temp_file.close()
    
    return send_file(temp_file.name, 
                     mimetype='audio/mpeg',
                     as_attachment=False,
                     download_name=f"{audio_id}.mp3")

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
    """Runs if you don't answer within 6 seconds."""
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
        
        # Try ElevenLabs first, fallback to Twilio TTS
        greeting_text = "Thank you for calling Mount Masters, this is Daniel, how can I help you today?"
        
        audio_url = generate_speech_elevenlabs(greeting_text)
        
        # Gather speech input from caller
        gather = resp.gather(
            input="speech",
            timeout=4,
            action="/process",
            speech_timeout="auto",
            enhanced=True
        )
        
        if audio_url:
            gather.play(audio_url)
        else:
            gather.say(greeting_text, voice="Polly.Matthew-Neural")
        
        # Record AI interaction as backup
        resp.record(play_beep=False, recording_status_callback="/handle-recording")
        
        fallback_text = "I didn't catch that. Feel free to call Mount Masters back anytime!"
        fallback_audio = generate_speech_elevenlabs(fallback_text)
        
        if fallback_audio:
            resp.play(fallback_audio)
        else:
            resp.say(fallback_text, voice="Polly.Matthew-Neural")
            
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
        clarify_text = "Sorry, I couldn't quite catch that. How can I help you today?"
        clarify_audio = generate_speech_elevenlabs(clarify_text)
        
        if clarify_audio:
            resp.play(clarify_audio)
        else:
            resp.say(clarify_text, voice="Polly.Matthew-Neural")
            
        gather = resp.gather(
            input="speech",
            timeout=4,
            action="/process",
            speech_timeout="auto",
            enhanced=True
        )
        
        prompt_text = "I'm all ears..."
        prompt_audio = generate_speech_elevenlabs(prompt_text)
        
        if prompt_audio:
            gather.play(prompt_audio)
        else:
            gather.say(prompt_text, voice="Polly.Matthew-Neural")
            
        return Response(str(resp), mimetype="text/xml")
    
    try:
        if call_sid not in conversations:
            conversations[call_sid] = {"messages": [], "caller": caller_number}
        
        conversations[call_sid]["messages"].append({"role": "user", "content": transcription})
        
        # Build conversation messages for OpenAI
        messages = [
            {
                "role": "system",
                "content": f"""You are Daniel, a professional TV mounting receptionist for Mount Masters. Follow this EXACT conversation flow:

{PRICING_INFO}

CONVERSATION FLOW (FOLLOW IN ORDER):
1. If they inquire about TV mounting, ask: "What size TV and how many TVs are you looking to mount?"
2. Next ask: "What city are you in?" 
   - Los Angeles/within 25 miles: Continue
   - Outside 25 miles: "You'll need a callback from our owner. Can I get your number?"  
   - Over 50 miles/other states: "Sorry, we don't service that area, but feel free to chat if you'd like."
3. Ask about cord hiding: "How would you like the cords handled - hidden behind the wall with an outlet, cord covers, or left hanging?"
4. Offer same day: "We do same day TV mounting. Would you like your TV mounted today?"
5. Schedule based on availability - check what days are booked

CURRENT SCHEDULE STATUS:
Monday: {"Booked" if scheduled_days["monday"] else "Available 7:30 PM+"}
Tuesday: {"Booked" if scheduled_days["tuesday"] else "Available after 12 PM"}  
Wednesday: {"Booked" if scheduled_days["wednesday"] else "Available after 12 PM"}
Thursday: {"Booked" if scheduled_days["thursday"] else "Available 7:30 PM+"}
Friday: {"Booked" if scheduled_days["friday"] else "Available 7:30 PM+"}
Saturday: {"Booked" if scheduled_days["saturday"] else "Available 7:30 PM+"}
Sunday: {"Booked" if scheduled_days["sunday"] else "Available 7:30 PM+"}

STYLE: Professional, helpful, follow the flow step by step. Calculate totals when appropriate.
"""
            }
        ]
        messages.extend(conversations[call_sid]["messages"][-6:])
        
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=messages,
            max_tokens=120,
            temperature=0.7
        )
        
        answer = response.choices[0].message.content
        conversations[call_sid]["messages"].append({"role": "assistant", "content": answer})
        
        # Check if we need to update scheduling based on the response
        if "7:30" in answer.lower() and any(day in answer.lower() for day in ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]):
            for day in ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]:
                if day in answer.lower():
                    scheduled_days[day] = True
                    print(f"Scheduled appointment for {day}")
                    break
        
        # Generate speech with ElevenLabs
        answer_audio = generate_speech_elevenlabs(answer)
        
        if answer_audio:
            resp.play(answer_audio)
        else:
            resp.say(answer, voice="Polly.Matthew-Neural")
        
        if not is_conversation_ending(answer):
            gather = resp.gather(
                input="speech",
                timeout=5,
                action="/process",
                speech_timeout="auto",
                enhanced=True
            )
            
            followup_text = "Anything else I can help you with?"
            followup_audio = generate_speech_elevenlabs(followup_text)
            
            if followup_audio:
                gather.play(followup_audio)
            else:
                gather.say(followup_text, voice="Polly.Matthew-Neural")
                
            closing_text = "Thanks for calling! Have a great day!"
            closing_audio = generate_speech_elevenlabs(closing_text)
            
            if closing_audio:
                resp.play(closing_audio)
            else:
                resp.say(closing_text, voice="Polly.Matthew-Neural")
        else:
            final_text = "Thanks so much for calling! We'll be in touch soon to schedule your mounting."
            final_audio = generate_speech_elevenlabs(final_text)
            
            if final_audio:
                resp.play(final_audio)
            else:
                resp.say(final_text, voice="Polly.Matthew-Neural")
        
        resp.hangup()
        
    except Exception as e:
        print(f"OpenAI error: {e}")
        error_text = "No worries, I'm having a little tech hiccup. Let me grab your name and number quickly."
        error_audio = generate_speech_elevenlabs(error_text)
        
        if error_audio:
            resp.play(error_audio)
        else:
            resp.say(error_text, voice="Polly.Matthew-Neural")
            
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
    
    final_text = "Perfect, got it! Someone will call you back today to schedule your TV mounting. Thanks!"
    final_audio = generate_speech_elevenlabs(final_text)
    
    if final_audio:
        resp.play(final_audio)
    else:
        resp.say(final_text, voice="Polly.Matthew-Neural")
        
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
        "we'll contact you",
        "schedule your mounting"
    ]
    return any(phrase in response.lower() for phrase in ending_phrases)


# ----------------------
# MISC
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
