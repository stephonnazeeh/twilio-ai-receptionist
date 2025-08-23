from flask import Flask, request, Response
from twilio.twiml.voice_response import VoiceResponse, Gather
import os
import openai

app = Flask(__name__)
from flask import Flask, request, Response
from twilio.twiml.voice_response import VoiceResponse

app = Flask(__name__)

@app.route("/voice", methods=["POST"])
def voice():
    resp = VoiceResponse()
    # Forward all calls to your cell for verification
    resp.dial("+12168822781")
    return Response(str(resp), mimetype="text/xml")

@app.route("/")
def home():
    return "Forwarding Test", 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)

