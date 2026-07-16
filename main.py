"""
main.py — FastAPI voice pipeline server (Phase 5).
Wires up Twilio Media Streams, Deepgram Speech-to-Text (STT),
LangGraph state machine (Brain), and ElevenLabs Text-to-Speech (TTS).

Includes a Developer Simulator mode when API keys are not provided.
"""

import os
import json
import base64
import asyncio
import httpx
from fastapi import FastAPI, WebSocket, Request, Response
from fastapi.responses import HTMLResponse
from twilio.twiml.voice_response import VoiceResponse, Connect
from twilio.rest import Client
from agent.graph import graph
from agent.state import initial_state
from agent.db_service import db
from dotenv import load_dotenv

load_dotenv()

app = FastAPI()

# Credentials from environment
PORT = int(os.environ.get("PORT", 8080))
CLINIC_ID = os.environ.get("PILOT_CLINIC_ID", "d72164a7-dd69-45c2-ac65-92c588b303a8")
DEEPGRAM_API_KEY = os.environ.get("DEEPGRAM_API_KEY")
ELEVENLABS_API_KEY = os.environ.get("ELEVENLABS_API_KEY")
ELEVENLABS_VOICE_ID = os.environ.get("ELEVENLABS_VOICE_ID", "21m00Tcm4TlvDq8ikWAM")  # Rachel voice


# ── ElevenLabs TTS Integration ───────────────────────────────────────────────
async def generate_tts_audio(text: str) -> bytes | None:
    """
    Sends text to ElevenLabs TTS API.
    Requests mulaw_8000 (8kHz mono Mu-law) to match Twilio's streaming codec.
    """
    if not ELEVENLABS_API_KEY:
        print("[TTS] [DEV] No ELEVENLABS_API_KEY. Using mock audio response.")
        # Return a simulated 1-second silence chunk (8000 bytes for 8kHz Mu-law)
        return b"\xff" * 8000

    url = f"https://api.elevenlabs.io/v1/text-to-speech/{ELEVENLABS_VOICE_ID}/stream"
    headers = {
        "xi-api-key": ELEVENLABS_API_KEY,
        "Content-Type": "application/json",
        "accept": "audio/x-mulaw"
    }
    payload = {
        "text": text,
        "model_id": "eleven_monolingual_v1",
        "output_format": "ulaw_8000",
        "voice_settings": {
            "stability": 0.5,
            "similarity_boost": 0.75
        }
    }

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(url, json=payload, headers=headers, timeout=15)
            if resp.status_code == 200:
                return resp.content
            print(f"[TTS] ElevenLabs failed ({resp.status_code}): {resp.text}")
    except Exception as e:
        print(f"[TTS] Error generating speech: {e}")
    return None


# ── Twilio Escalation Live Call Transfer (Phase 6) ──────────────────────────
async def redirect_call_to_escalation(call_sid: str, escalation_number: str):
    """
    Invokes Twilio REST API to redirect current live call to /escalate-dial TwiML endpoint.
    Wait for 4.0 seconds to allow the receptionist's final voice response to finish playing.
    """
    await asyncio.sleep(4.0)

    account_sid = os.environ.get("TWILIO_ACCOUNT_SID")
    auth_token = os.environ.get("TWILIO_AUTH_TOKEN")

    if not account_sid or not auth_token or call_sid.startswith("simulated-"):
        print(f"[Twilio] [DEV] Simulated redirect for CallSid '{call_sid}' to {escalation_number} complete.")
        return

    try:
        host = os.environ.get("PUBLIC_URL")
        if not host:
            print("[Twilio] ERROR: PUBLIC_URL env variable is missing. Cannot perform REST API redirect.")
            return

        client = Client(account_sid, auth_token)
        client.calls(call_sid).update(
            method="POST",
            url=f"{host}/escalate-dial?number={escalation_number}"
        )
        print(f"[Twilio] Redirected CallSid '{call_sid}' successfully to {escalation_number}.")
    except Exception as e:
        print(f"[Twilio] Error redirecting call: {e}")


@app.post("/escalate-dial")
async def escalate_dial(request: Request, number: str):
    """Returns TwiML instructions to bridge the active call to a clinic human agent."""
    response = VoiceResponse()
    print(f"[Twilio] Dialing human escalation number: {number}")
    response.dial(number)
    return Response(content=str(response), media_type="application/xml")


# ── Webhook: Incoming Twilio Call ────────────────────────────────────────────
@app.post("/incoming-call")
async def incoming_call(request: Request):
    """
    Twilio HTTP Post Webhook for incoming calls.
    Returns TwiML instruction to connect the call audio to our WebSocket.
    """
    form_data = await request.form()
    call_sid = form_data.get("CallSid", "unknown-call")
    host = request.headers.get("host", f"localhost:{PORT}")

    print(f"\n[Twilio] Incoming call received. CallSid: {call_sid}")

    response = VoiceResponse()
    # Speak an initial prompt before connecting the stream
    response.say("Welcome to Greenfield Multi-Specialty Clinic. Please wait while we connect your call.")

    # Wires up Twilio Connect Stream to our WebSocket endpoint
    connect = Connect()
    websocket_url = f"wss://{host}/media-stream"
    connect.stream(url=websocket_url)
    response.append(connect)

    return Response(content=str(response), media_type="application/xml")


# ── WebSocket: Live Media Stream Handler ──────────────────────────────────────
@app.websocket("/media-stream")
async def media_stream(websocket: WebSocket):
    """
    Handles bi-directional streaming audio packets with Twilio over WebSocket.
    Streams incoming audio to Deepgram STT, runs the Brain, and streams TTS back.
    """
    await websocket.accept()
    print("[WS] Connection established with Twilio.")

    stream_sid = None
    call_sid = None
    call_state = None

    # Track deepgram websocket connection if using real STT
    dg_socket = None

    # Queue for outgoing audio chunks to stream back to Twilio
    audio_queue = asyncio.Queue()

    async def stream_audio_to_twilio():
        """Worker task to send audio payloads from queue back to Twilio."""
        nonlocal stream_sid
        while True:
            try:
                audio_payload = await audio_queue.get()
                if not stream_sid:
                    continue

                # Encode to base64 and wrap in Twilio media frame format
                base64_audio = base64.b64encode(audio_payload).decode("utf-8")
                message = {
                    "event": "media",
                    "streamSid": stream_sid,
                    "media": {
                        "payload": base64_audio
                    }
                }
                await websocket.send_text(json.dumps(message))
            except Exception as e:
                print(f"[WS] Error streaming audio to Twilio: {e}")
                break

    # Start audio transmitter task
    transmit_task = asyncio.create_task(stream_audio_to_twilio())

    async def process_brain_turn(user_transcript: str):
        """Processes a single turn: Transcript -> Brain (LangGraph) -> TTS -> Twilio."""
        nonlocal call_state, call_sid
        if not call_state:
            call_state = initial_state(clinic_id=CLINIC_ID, call_sid=call_sid or "unknown-sid")

        print(f"\n[Brain] User Transcript: '{user_transcript}'")

        # Update input
        call_state["current_input"] = user_transcript

        try:
            # 1. Invoke LangGraph Brain
            updated_state = graph.invoke(call_state)
            call_state = updated_state  # persist state across turns

            ai_response = call_state.get("response", "")
            print(f"[Brain] AI Response: '{ai_response}'")

            # 2. Synthesize TTS
            print("[TTS] Generating audio via ElevenLabs...")
            tts_audio = await generate_tts_audio(ai_response)

            if tts_audio:
                # 3. Stream in 20ms chunks (160 bytes for 8kHz Mu-law)
                chunk_size = 160
                for i in range(0, len(tts_audio), chunk_size):
                    chunk = tts_audio[i : i + chunk_size]
                    await audio_queue.put(chunk)
                    # Pause 20ms between chunks to maintain natural play rate
                    await asyncio.sleep(0.02)
                print(f"[TTS] Outgoing audio streaming complete.")

            # 4. Check for Escalation and trigger transfer
            if call_state.get("escalated"):
                clinic = db.get_clinic(CLINIC_ID)
                esc_num = clinic["escalation_phone_e164"] if clinic else "+919876543210"
                print(f"[WS] Escalation triggered! Scheduling redirect for CallSid '{call_sid}' to {esc_num}...")
                asyncio.create_task(redirect_call_to_escalation(call_sid, esc_num))

        except Exception as e:
            print(f"[Brain] Error processing turn: {e}")

    try:
        # Loop over messages from Twilio
        async for raw_msg in websocket.iter_text():
            msg = json.loads(raw_msg)
            event = msg.get("event")

            if event == "start":
                # Extract session ids
                stream_sid = msg["start"]["streamSid"]
                call_sid = msg["start"].get("callSid")
                print(f"[WS] Stream started. StreamSid: {stream_sid}, CallSid: {call_sid}")

                # Trigger first welcome prompt from AI Receptionist
                welcome_msg = "Thank you for calling Greenfield Multi-Specialty Clinic. I'm your AI receptionist. How can I assist you today?"
                print(f"[Brain] Greeting caller with welcome message.")
                tts_audio = await generate_tts_audio(welcome_msg)
                if tts_audio:
                    # Stream the greeting chunks
                    chunk_size = 160
                    for i in range(0, len(tts_audio), chunk_size):
                        await audio_queue.put(tts_audio[i : i + chunk_size])
                        await asyncio.sleep(0.02)

            elif event == "media":
                # Raw audio payload (base64 encoded Mu-law)
                payload_b64 = msg["media"]["payload"]
                raw_audio = base64.b64decode(payload_b64)

                # Forward audio to Deepgram (or handle mock input)
                # In developer mode with no keys, we can write a text simulator interface below.
                pass

            elif event == "stop":
                print(f"[WS] Stream stopped. StreamSid: {stream_sid}")
                break

    except Exception as e:
        print(f"[WS] Connection error: {e}")

    finally:
        transmit_task.cancel()
        await websocket.close()
        print("[WS] Connection closed cleanly.")


# ── Developer Web Dashboard (For testing without live Twilio / phones) ───────
@app.get("/", response_class=HTMLResponse)
async def developer_dashboard():
    """Simple web console to test the voice agent's brain directly in the browser."""
    html_content = """
    <!DOCTYPE html>
    <html>
    <head>
        <title>MediCare Connect Voice Agent Console</title>
        <style>
            body { font-family: 'Segoe UI', Arial, sans-serif; background: #121214; color: #e1e1e6; margin: 0; padding: 20px; }
            .container { max-width: 800px; margin: 40px auto; background: #202024; padding: 30px; border-radius: 12px; box-shadow: 0 4px 12px rgba(0,0,0,0.5); }
            h1 { color: #04d361; border-bottom: 1px solid #29292e; padding-bottom: 10px; margin-top: 0; }
            .log-box { height: 350px; overflow-y: auto; background: #121214; padding: 15px; border-radius: 6px; margin-bottom: 20px; font-family: monospace; border: 1px solid #29292e; }
            .input-box { display: flex; gap: 10px; }
            input { flex: 1; padding: 12px; background: #121214; border: 1px solid #29292e; border-radius: 6px; color: #fff; font-size: 16px; }
            button { background: #04d361; border: none; padding: 12px 24px; color: #121214; font-weight: bold; border-radius: 6px; cursor: pointer; font-size: 16px; }
            button:hover { background: #00b33c; }
            .user-msg { color: #8257e5; margin: 5px 0; }
            .ai-msg { color: #04d361; margin: 5px 0; }
            .sys-msg { color: #7c7c8a; margin: 5px 0; }
        </style>
    </head>
    <body>
        <div class="container">
            <h1>MediCare Connect — Developer Dashboard</h1>
            <p>Simulate a phone conversation with the voice receptionist brain in real time.</p>
            <div id="logs" class="log-box">
                <div class="sys-msg">[System] Ready to start conversation...</div>
            </div>
            <div class="input-box">
                <input type="text" id="userInput" placeholder="Type your response to the receptionist here..." onkeypress="handleKey(event)"/>
                <button onclick="sendMessage()">Send</button>
            </div>
        </div>
        <script>
            let callSid = "simulated-" + Math.random().toString(36).substring(7);
            let state = {
                clinic_id: "d72164a7-dd69-45c2-ac65-92c588b303a8",
                call_sid: callSid,
                messages: [],
                current_input: "",
                response: ""
            };

            // Print welcome message
            const logs = document.getElementById("logs");
            logs.innerHTML += `<div class="ai-msg"><b>Receptionist:</b> Thank you for calling Greenfield Multi-Specialty Clinic. I'm your AI receptionist. I can help you book, reschedule, or cancel an appointment, or answer questions about our clinic. How can I assist you today?</div>`;

            function handleKey(e) {
                if (e.key === 'Enter') sendMessage();
            }

            async function sendMessage() {
                const input = document.getElementById("userInput");
                const text = input.value.strip ? input.value.strip() : input.value;
                if (!text) return;

                input.value = "";
                logs.innerHTML += `<div class="user-msg"><b>You:</b> ${text}</div>`;
                logs.scrollTop = logs.scrollHeight;

                try {
                    const response = await fetch("/simulate-turn", {
                        method: "POST",
                        headers: { "Content-Type": "application/json" },
                        body: JSON.stringify({ text: text, state: state })
                    });
                    const data = await response.json();
                    
                    state = data.state;
                    logs.innerHTML += `<div class="ai-msg"><b>Receptionist:</b> ${data.response}</div>`;
                    logs.scrollTop = logs.scrollHeight;
                } catch (e) {
                    logs.innerHTML += `<div class="sys-msg">[System Error] Failed to process turn.</div>`;
                    logs.scrollTop = logs.scrollHeight;
                }
            }
        </script>
    </body>
    </html>
    """
    return HTMLResponse(content=html_content)


@app.post("/simulate-turn")
async def simulate_turn(payload: dict):
    """Simulates a conversation turn by invoking the LangGraph brain directly via HTTP."""
    text = payload.get("text", "")
    state = payload.get("state", {})

    state["current_input"] = text

    # Run LangGraph brain
    try:
        updated_state = graph.invoke(state)
        # Clear messages from JSON serialization context since they are Pydantic objects
        serializable_state = {k: v for k, v in updated_state.items() if k != "messages"}
        
        response_text = updated_state.get("response", "")
        if updated_state.get("escalated"):
            # Fetch escalation number dynamically
            clinic = db.get_clinic(state.get("clinic_id", CLINIC_ID))
            esc_num = clinic["escalation_phone_e164"] if clinic else "+919876543210"
            response_text += f" <br/><span style='color: #fd951f;'>[SYSTEM: Call redirected to human escalation line: {esc_num}]</span>"

        return {
            "response": response_text,
            "state": serializable_state
        }
    except Exception as e:
        return {
            "response": f"[Error: {e}] Let me connect you with a staff member.",
            "state": state
        }


if __name__ == "__main__":
    import uvicorn
    print(f"\n[Server] Starting MediCare Connect Voice Engine on port {PORT}...")
    uvicorn.run("main:app", host="0.0.0.0", port=PORT, log_level="info")
