"""
The core of the voice bot.

Flow for one call:
  1. call_runner.py asks Twilio to dial TARGET_NUMBER, with the call's
     `url` pointing at POST /twiml/{scenario_id} on this server.
  2. Twilio hits /twiml/{scenario_id} as soon as the call connects; we
     respond with TwiML that opens a bidirectional Media Stream back to
     our own /media-stream/{scenario_id} websocket.
  3. Over that websocket we receive base64 mu-law audio frames from the
     practice's agent (the system under test) and forward them straight
     into an OpenAI Realtime API session that is playing the "patient"
     persona for this scenario. Realtime API audio output (also mu-law)
     is forwarded straight back to Twilio, which plays it into the call.
  4. Both sides' transcripts (from Realtime API transcription events) are
     written incrementally to disk via TranscriptWriter.

Why this architecture (see ARCHITECTURE.md for the full writeup):
  - Twilio Media Streams + a Realtime speech-to-speech model is the
    standard low-latency pattern for phone-call voice bots: no manual
    STT -> LLM -> TTS pipeline to hand-stitch, and Twilio + OpenAI both
    speak 8kHz mu-law natively so no resampling is needed.
"""
import asyncio
import json

import websockets
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request
from fastapi.responses import PlainTextResponse
from twilio.twiml.voice_response import VoiceResponse, Connect

from src.config import settings, AUDIO_FORMAT
from src.scenarios import get_scenario
from src.transcript_store import TranscriptWriter

app = FastAPI()

OPENAI_REALTIME_URL = "wss://api.openai.com/v1/realtime?model={model}"

# In-memory registry the call_runner polls to know when a call's transcript
# is "done" (populated when the Twilio stream closes).
CALL_TRANSCRIPTS: dict[str, TranscriptWriter] = {}
CALL_STATUS: dict[str, str] = {}  # call_sid -> "in_progress" | "completed"


@app.post("/twiml/{scenario_id}")
async def twiml(scenario_id: str, request: Request):
    """Twilio calls this once the outbound call is answered."""
    form = await request.form()
    call_sid = form.get("CallSid", "unknown")
    CALL_STATUS[call_sid] = "in_progress"

    vr = VoiceResponse()
    connect = Connect()
    stream_url = f"{settings.public_base_url.replace('https://', 'wss://').replace('http://', 'ws://')}/media-stream/{scenario_id}/{call_sid}"
    connect.stream(url=stream_url)
    vr.append(connect)
    return PlainTextResponse(str(vr), media_type="application/xml")


@app.websocket("/media-stream/{scenario_id}/{call_sid}")
async def media_stream(websocket: WebSocket, scenario_id: str, call_sid: str):
    await websocket.accept()
    scenario = get_scenario(scenario_id)
    transcript = TranscriptWriter(call_sid=call_sid, scenario_id=scenario_id)
    CALL_TRANSCRIPTS[call_sid] = transcript

    stream_sid = {"value": None}

    async with websockets.connect(
        OPENAI_REALTIME_URL.format(model=settings.openai_realtime_model),
        extra_headers={
            "Authorization": f"Bearer {settings.openai_api_key}",
        },
        max_size=None,
    ) as openai_ws:
        await _init_realtime_session(openai_ws, scenario)

        # Some test lines answer with their own automated greeting/IVR
        # before our persona ever gets a turn. If we force our bot to speak
        # immediately, it talks over that greeting and can get confused by
        # hearing only fragments of it. So: only force an opening line if
        # the other side stays silent for a bit; otherwise let normal
        # server-VAD turn-taking handle it once their greeting finishes.
        heard_speech = asyncio.Event()

        await asyncio.gather(
            _twilio_to_openai(websocket, openai_ws, stream_sid),
            _openai_to_twilio(openai_ws, websocket, stream_sid, transcript, heard_speech),
            _greet_if_silent(openai_ws, heard_speech),
        )

    CALL_STATUS[call_sid] = "completed"


async def _init_realtime_session(openai_ws, scenario: dict):
    """Configure the Realtime session: persona instructions, audio formats,
    voice, and server-side VAD so turn-taking feels natural.

    NOTE: as of the GA Realtime API (the beta interface -- including the
    old flat `modalities` / `input_audio_format` / `output_audio_format`
    keys and the `OpenAI-Beta` header -- was fully retired May 2026), audio
    config lives under nested `session.audio.input` / `session.audio.output`
    objects instead of flat top-level keys.
    """
    session_update = {
        "type": "session.update",
        "session": {
            "type": "realtime",
            "model": settings.openai_realtime_model,
            "output_modalities": ["audio"],
            "instructions": scenario["instructions"],
            "audio": {
                "input": {
                    "format": AUDIO_FORMAT,
                    "transcription": {"model": "whisper-1"},
                    "turn_detection": {
                        "type": "server_vad",
                        "threshold": 0.5,
                        "prefix_padding_ms": 300,
                        "silence_duration_ms": 500,
                    },
                },
                "output": {
                    "format": AUDIO_FORMAT,
                    "voice": "alloy",
                },
            },
        },
    }
    await openai_ws.send(json.dumps(session_update))


async def _greet_if_silent(openai_ws, heard_speech: asyncio.Event, timeout_s: float = 3.5):
    """If the other side hasn't started talking within a few seconds of
    connecting (no automated greeting/IVR), have our persona open the call
    itself. If they *do* speak first (e.g. an IVR menu), stand down and let
    normal turn-taking handle it once they finish."""
    try:
        await asyncio.wait_for(heard_speech.wait(), timeout=timeout_s)
        # They spoke first -- do nothing, server VAD will prompt our model
        # to respond once their turn ends.
    except asyncio.TimeoutError:
        await openai_ws.send(json.dumps({
            "type": "response.create",
            "response": {"instructions": "Greet the person who answered and briefly state why you're calling, per your persona."},
        }))


async def _twilio_to_openai(twilio_ws: WebSocket, openai_ws, stream_sid: dict):
    """Forward inbound audio from the practice's agent (via Twilio) into
    the Realtime session."""
    try:
        while True:
            raw = await twilio_ws.receive_text()
            data = json.loads(raw)
            event = data.get("event")

            if event == "start":
                stream_sid["value"] = data["start"]["streamSid"]

            elif event == "media":
                audio_payload = data["media"]["payload"]  # base64 mu-law
                await openai_ws.send(json.dumps({
                    "type": "input_audio_buffer.append",
                    "audio": audio_payload,
                }))

            elif event == "stop":
                break
    except WebSocketDisconnect:
        pass
    finally:
        try:
            await openai_ws.close()
        except Exception:
            pass


async def _openai_to_twilio(openai_ws, twilio_ws: WebSocket, stream_sid: dict, transcript: TranscriptWriter, heard_speech: asyncio.Event):
    """Forward Realtime API audio output back into the Twilio call, and log
    transcript events from both sides as they arrive."""
    try:
        async for raw in openai_ws:
            event = json.loads(raw)
            etype = event.get("type")

            if etype == "input_audio_buffer.speech_started":
                heard_speech.set()

            elif etype == "response.output_audio.delta" and stream_sid["value"]:
                await twilio_ws.send_text(json.dumps({
                    "event": "media",
                    "streamSid": stream_sid["value"],
                    "media": {"payload": event["delta"]},
                }))

            # Our simulated patient's own speech, transcribed by the model.
            elif etype == "response.output_audio_transcript.done":
                transcript.add_turn("caller_bot", event.get("transcript", ""))

            # The practice agent's speech, transcribed via Whisper on the
            # input audio buffer. (This event name is unchanged from the
            # beta API in the GA release.)
            elif etype == "conversation.item.input_audio_transcription.completed":
                transcript.add_turn("agent_under_test", event.get("transcript", ""))

            elif etype == "error":
                print(f"[OpenAI Realtime error] {event}")

    except (websockets.exceptions.ConnectionClosed, WebSocketDisconnect):
        pass
