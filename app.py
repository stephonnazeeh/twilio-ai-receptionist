from flask import Flask, request, Response
from twilio.twiml.voice_response import VoiceResponse, Gather
import os
from openai import OpenAI

app = Flask(__name__)

# Initialize OpenAI client with new API
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# Store conversation states (in production, use Redis or database)
conversations = {}

@app.route("/voice", methods=["POST"])
def voice():
    resp = VoiceResponse()
    
    # Ring your cell via Google Voice for 6 seconds
    dial = resp.dial(timeout=6)
    dial.number("+13234576314")  # Your Google Voice number forwarding to your cell
    
    # Small pause before AI starts
    resp.pause(length=1)
    
    # Gather speech input from the caller if you don't answer
    gather = resp.gather(
        input="speech", 
        timeout=4, 
        action="/process",
        speech_timeout="auto",
        enhanced=True
    )
    
    gather.say(
        "Hi there! Sorry I missed your call. I'm here to help you with any home services you need. What can I assist you with today?",
        voice="Polly.Joanna-Neural"
    )
    
    # Fallback if no speech detected
    resp.say("I didn't catch that. Please call back when you're ready to chat!", voice="Polly.Joanna-Neural")
    resp.hangup()
    
    return Response(str(resp), mimetype="text/xml")

@app.route("/process", methods=["POST"])
def process():
    transcription = request.form.get("SpeechResult", "")
    call_sid = request.form.get("CallSid", "")
    
    resp = VoiceResponse()
    
    if not transcription:
        resp.say("Sorry, I didn't catch that. Could you repeat what you need help with?", 
                voice="Polly.Joanna-Neural")
        
        # Give them another chance
        gather = resp.gather(
            input="speech", 
            timeout=4, 
            action="/process",
            speech_timeout="auto",
            enhanced=True
        )
        gather.say("I'm listening...", voice="Polly.Joanna-Neural")
        
        return Response(str(resp), mimetype="text/xml")
    
    try:
        # Get or create conversation history
        if call_sid not in conversations:
            conversations[call_sid] = []
        
        conversations[call_sid].append({"role": "user", "content": transcription})
        
        # Create messages with conversation history
        messages = [
            {
                "role": "system", 
                "content": """You are Sarah, a friendly receptionist for a home services business. 

Key guidelines:
- Be conversational and warm, not robotic
- Keep responses under 25 words for phone calls
- Collect: name, service needed, preferred timing, budget if relevant
- Services include: plumbing, electrical, HVAC, handyman, cleaning, landscaping
- For pricing, give general ranges and mention we provide free estimates
- If you need more info, ask one question at a time
- Be helpful but don't make promises about availability
- If they want to schedule, get their contact info and preferred times

Remember: This is a phone conversation, so be natural and conversational!"""
            }
        ]
        
        # Add conversation history (keep last 6 messages for context)
        messages.extend(conversations[call_sid][-6:])
        
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=messages,
            max_tokens=100,
            temperature=0.7
        )
        
        answer = response.choices[0].message.content
        conversations[call_sid].append({"role": "assistant", "content": answer})
        
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
            gather.say("Anything else I can help you with?", voice="Polly.Joanna-Neural")
            
            # Fallback ending
            resp.say("Thanks for calling! Have a great day!", voice="Polly.Joanna-Neural")
        else:
            resp.say("Thanks so much for calling! We'll be in touch soon.", voice="Polly.Joanna-Neural")
        
        resp.hangup()
        
    except Exception as e:
        print(f"OpenAI error: {e}")
        resp.say("I'm having a bit of trouble right now. Let me take your name and number so someone can call you back.", 
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
    """Handle voicemail recordings as backup"""
    recording_url = request.form.get("RecordingUrl")
    transcription = request.form.get("TranscriptionText")
    
    # Log the recording info (you can add database storage here)
    print(f"Backup recording: {recording_url}")
    print(f"Transcription: {transcription}")
    
    resp = VoiceResponse()
    resp.say("Got it! Someone will call you back shortly. Thanks for calling!", 
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
        "openai_key": "set" if os.getenv("OPENAI_API_KEY") else "missing"
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

