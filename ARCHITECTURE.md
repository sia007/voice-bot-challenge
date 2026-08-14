# Architecture

## What I built

The bot is a Twilio-outbound call bridged, over a WebSocket **Media Stream**,
into an **OpenAI Realtime API** session that plays a specific "patient"
persona per scenario. Concretely: `call_runner.py` asks Twilio's REST API to
dial the test line; Twilio hits my FastAPI server's `/twiml/{scenario_id}`
endpoint as soon as the call connects, which responds with TwiML telling
Twilio to open a bidirectional audio stream back to
`/media-stream/{scenario_id}/{call_sid}`. From there it's a thin relay loop:
inbound base64 mu-law audio frames from the practice's agent are forwarded
into `input_audio_buffer.append` events on the Realtime session, and
`response.output_audio.delta` events coming back out are forwarded straight
into the Twilio stream as `media` events. Twilio's server-side VAD
(`server_vad` on the Realtime session) handles turn-taking, so the model
naturally waits for the agent to finish speaking before replying, and can be
interrupted mid-response for the barge-in scenario. Transcription events
(`response.output_audio_transcript.done` for our bot's own speech,
`conversation.item.input_audio_transcription.completed` for the agent under
test) are written incrementally to `transcripts/` as the call happens, so a
crash mid-call still leaves partial evidence. Twilio's own dual-channel call
recording is downloaded afterward as the `.mp3` deliverable, and a separate
`bug_analyzer.py` pass reads each finished transcript and drafts
`BUG_REPORT.md` using the same rubric as the example bug in the challenge doc
(bug / severity / quote / details), with a second pass afterward that
specifically looks for the same bug recurring across multiple calls (see
"Evidence of iteration" below for why that second pass exists).

One infrastructure wrinkle worth naming explicitly: OpenAI fully retired the
beta version of the Realtime API (the version documented in most tutorials
and blog posts as of when I started this) partway through this project, in
favor of a restructured GA API with different session config shape and
several renamed events. The code here targets the current GA API.

## Why this approach, and what I considered instead

The main design decision was **speech-to-speech (Realtime API) vs. a
hand-stitched STT → LLM → TTS pipeline**. I went with the Realtime API
because it collapses transcription, reasoning, and speech synthesis into one
low-latency, full-duplex session with built-in interruption handling — which
matters a lot for the "natural conversational voice interaction" and
"sensible turn-taking" requirements in the grading rubric. A hand-stitched
pipeline (e.g. Deepgram STT → GPT-4 → ElevenLabs TTS) gives more control over
each stage individually (useful if I wanted a specific voice provider, or
needed to inject custom logic between transcription and generation), but it
adds real end-to-end latency at every hop and makes barge-in handling my own
problem to solve (racing partial transcripts against still-playing TTS
audio). For a scripted test caller rather than a production customer-facing
bot, that extra complexity wasn't worth it. The other reason for this choice
is audio-format convenience: Twilio Media Streams and the Realtime API both
speak 8kHz mu-law (`g711_ulaw`) natively, so audio is relayed byte-for-byte
in both directions with zero resampling code — one less place for bugs to
hide in a 6-hour build.

For **infrastructure**, I chose Twilio's outbound-call + Media Streams model
over Twilio's newer "ConversationRelay" product mainly because Media Streams
gives direct control of the raw audio going to/from the Realtime API, which
made it easier to reason about exactly what's being sent when debugging
(and doesn't tie me to Twilio's own text-to-speech). The tradeoff is I own a
bit more plumbing (the WebSocket relay in `server.py`) than a fully managed
option would require — acceptable for a 6-hour take-home, less so for a
production system, where I'd lean more on a managed offering if it fit.

For **call orchestration**, I run scenarios sequentially with a short delay
between them (`call_runner.py`) rather than firing all 10+ calls in parallel.
Sequential calls are slower overall, but they mean I can watch server logs
per call while iterating, and they avoid hammering the test line / hitting
Twilio concurrency limits on a bare trial-tier setup.

For **frameworks**, the server is FastAPI + uvicorn. I picked FastAPI mainly
for its native `async`/`await` support and built-in WebSocket handling —
this project is fundamentally two concurrent audio streams (Twilio ↔ server,
server ↔ OpenAI) that need to run at the same time without blocking each
other, which is exactly what `asyncio.gather()` and an async framework are
for. A synchronous framework like Flask would need extra threading/worker
machinery bolted on to handle a live bidirectional audio relay reasonably;
FastAPI gives that concurrency model by default. The rest of the stack is
intentionally minimal — plain `requests` for one-off Twilio REST calls,
no ORM/database (call state just lives in memory for the duration of a run,
since nothing here needs to persist beyond one script execution).

For **bug detection**, I deliberately kept it as a second, separate LLM pass
over the finished transcript rather than trying to have the Realtime session
judge itself live mid-call. Judging quality issues (e.g. "did it check
office hours before confirming that appointment?") benefits from seeing the
whole conversation, and coupling it into the live call loop would add
latency and risk breaking character. The analyzer output is explicitly a
draft — the rubric asks for well-described bugs over a long list of
nitpicks, and that kind of judgment call needs a human pass, not raw model
output shipped as-is.

## Evidence of iteration

Two concrete things changed after reviewing real call output, not just
theoretical design choices:

1. **The caller-bot originally always spoke first.** Early transcripts
   showed it talking over the practice line's own automated greeting/IVR
   ("Para Español, oprima el 2"), which sometimes confused the model into
   briefly responding as if it were the receptionist rather than the
   patient. Fix: added a short listen-first window (`_greet_if_silent` in
   `server.py`) — the bot now only opens the call itself if the other side
   stays silent for ~3.5 seconds; if the line has its own greeting, our bot
   waits for it to finish and lets normal turn-taking take over.

2. **The bug analyzer's per-call prompt undersold a serious, recurring
   issue.** Reviewing transcripts by hand turned up a pattern the
   auto-generated report had scattered across six separate calls as minor,
   differently-labeled issues (e.g. "lack of empathy," "abrupt call
   termination") — when it was actually one systemic bug: the agent
   defaults to a fake "transferring you now" that immediately hangs up
   whenever it can't resolve a request in-line. The per-transcript prompt
   was rewritten to explicitly check whether the patient's original request
   was actually resolved by the end of the call (not just whether the
   phrasing sounded polite), and a second cross-call pass
   (`analyze_cross_call_patterns` in `bug_analyzer.py`) was added that reads
   every call's findings together specifically to catch this kind of
   pattern that's invisible when each transcript is judged in isolation.

## Data flow summary

```
call_runner.py --(Twilio REST: calls.create)--> Twilio --(dials)--> Test line
                                                     |
                                          (call answered, Twilio fetches TwiML)
                                                     v
                                    FastAPI /twiml/{scenario_id}
                                                     |
                                    TwiML: <Connect><Stream url=wss://.../media-stream/...>
                                                     v
                              FastAPI /media-stream websocket  <==>  OpenAI Realtime API
                                     |  writes turns incrementally
                                     v
                              transcripts/*.txt, *.json

(after call ends)
call_runner.py --(Twilio REST: recordings.list/download)--> recordings/*.mp3
bug_analyzer.py --(reads transcripts one at a time, calls OpenAI)--> per-call findings
bug_analyzer.py --(reads all findings together, calls OpenAI again)--> recurring-pattern findings
                                                     v
                                            BUG_REPORT.md
```
