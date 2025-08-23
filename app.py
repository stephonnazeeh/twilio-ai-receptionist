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

    # Ring your cell via Google Voice for 10 seconds
    dial = resp.dial(timeout=10)
    dial.number("+13234576314")  # Your Google Voice number forwarding to your cell
    resp.pause(length=1)  # small pause before AI starts

    # Gather speech input from the caller if you don't answer
    with resp.gather(input="speech", timeout=5, action="/process") as gather:
        gather.say(
            "Sorry we missed your call. Please tell me what service you need, and I’ll help you right away.",
            voice="Polly.Joanna.Neural"
        )

    return Response(str(resp), mimetype="text/xml")

@app.route("/process", methods=["POST"])
def process():
    transcription = request.form.get("SpeechResult", "")
    resp = VoiceResponse()

    if not transcription:
        resp.say("Sorry, I didn't catch that. Please try again.", voice="Polly.Joanna.Neural")
        return Response(str(resp), mimetype="text/xml")

    try:
        response = openai.ChatCompletion.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "You are a receptionist for a home services business. Answer naturally and politely. Collect name, service requested, and budget. Quote only accurate pricing. If you don’t know something, say so politely."},
                {"role": "user", "content": transcription}
            ]
        )
        answer = response.choices[0].message["content"]
        resp.say(answer, voice="Polly.Joanna.Neural")
    except Exception as e:
        print("OpenAI error:", e)
        resp.say("Sorry, something went wrong. I couldn't process that request.", voice="Polly.Joanna.Neural")

    resp.pause(length=2)
    resp.say("Thank you, goodbye.", voice="Polly.Joanna.Neural")
    return Response(str(resp), mimetype="text/xml")

@app.route("/")
def home():
    return "Twilio AI Receptionist is running!", 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)

