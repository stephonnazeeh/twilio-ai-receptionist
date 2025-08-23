from flask import Flask, request, Response
from twilio.twiml.voice_response import VoiceResponse, Gather
import os
import openai

app = Flask(__name__)

# Make sure you set OPENAI_API_KEY in Render environment variables
openai.api_key = os.getenv("OPENAI_API_KEY")

@app.route("/voice", methods=["POST"])
def voice():
    resp = VoiceResponse()

    # Ring your cell via Google Voice for 6 seconds
    dial = resp.dial(timeout=6)
    dial.number("+13234576314")  # Your Google Voice number forwarding to your cell

    # If not answered, AI takes over
    with resp.gather(input="speech", timeout=5, action="/process") as gather:
        gather.say("Sorry we missed your call. Please tell me what service you need, and I’ll help you right away.")

    return Response(str(resp), mimetype="text/xml")

@app.route("/process", methods=["POST"])
def process():
    transcription = request.form.get("SpeechResult", "")
    response = openai.ChatCompletion.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": "You are a receptionist for a home services business. Be polite, collect name, service, and budget, and close the job with pricing."},
            {"role": "user", "content": transcription}
        ]
    )
    answer = response.choices[0].message["content"]
    resp = VoiceResponse()
    resp.say(answer)
    resp.pause(length=2)
    resp.say("Thank you, goodbye.")
    return Response(str(resp), mimetype="text/xml")

@app.route("/")
def home():
    return "Twilio AI Receptionist is running!", 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
