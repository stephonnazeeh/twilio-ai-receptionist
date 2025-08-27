# app.py
from flask import Flask, request, send_file
from twilio.twiml.voice_response import VoiceResponse
from twilio.rest import Client as TwilioClient
from openai import OpenAI
from elevenlabs import ElevenLabs
import os

# Config
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
TWILIO_ACCOUNT_SID = os.environ.get("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.environ.get("TWILIO_AUTH_TOKEN")

app = Flask(__name__)

# OpenAI client
openai_client = OpenAI(api_key=OPENAI_API_KEY)

# ElevenLabs client
eleven_client = ElevenLabs(api_key=os.environ.get("ELEVENLABS_API_KEY"))

# Twilio client
twilio_client = TwilioClient(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)

@app.route("/voice", methods=["POST"])
def voice():
    # Get incoming speech/text or a default prompt
    incoming_text = request.form.get("SpeechResult") or "Hello! How can I help you today?"

    # Generate response from OpenAI
    response = openai_client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": incoming_text}]
    )
    answer = response.choices[0].message.content

    # Generate audio using ElevenLabs
    audio_bytes = eleven_client.text_to_speech(
        text=answer,
        voice="Rachel"  # Replace with any available voice
    )

    # Save audio temporarily
    audio_file = "/tmp/response.mp3"
    with open(audio_file, "wb") as f:
        f.write(audio_bytes)

    # Twilio response
    resp = VoiceResponse()
    resp.play(audio_file)
    return str(resp), 200, {"Content-Type": "application/xml"}

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
