import os
from flask import Flask
from twilio.twiml.voice_response import VoiceResponse

app = Flask(__name__)

@app.route("/voice", methods=["POST"])
def voice():
    """Temporarily disabled AI — just play a simple message or hang up."""
    resp = VoiceResponse()
    # Option 1: Just hang up with no audio:
    # resp.hangup()

    # Option 2: Play a short unavailable message:
    resp.say("Hi! We're not accepting calls right now. Please try again later.", voice="alice")
    resp.hangup()
    return str(resp)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)

