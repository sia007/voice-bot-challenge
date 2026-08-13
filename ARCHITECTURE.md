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
`response.audio.delta` events coming back out are forwarded straight into the
Twilio stream as `media` events. Twilio's server-side VAD (`server_vad` on
the Realtime session) handles turn-taking, so the model naturally waits for
the agent to finish speaking before replying, and can be interrupted
mid-response for the barge-in scenario. Transcription events
(`response.audio_transcript.done` for our bot's own speech,
`conversation.item.input_audio_transcription.completed` for the agent under
test) are written incrementally to `transcripts/` as the call happens, so a
crash mid-call still leaves partial evidence. Twilio's own dual-channel call
recording is downloaded afterward as the `.mp3` deliverable, and a separate
`bug_analyzer.py` pass reads each finished transcript and drafts
`BUG_REPORT.md` using the same rubric as the example bug in the challenge doc
(bug / severity / quote / details).

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

For **bug detection**, I deliberately kept it as a second, separate LLM pass
over the finished transcript rather than trying to have the Realtime session
judge itself live mid-call. Judging quality issues (e.g. "did it check
office hours before confirming that appointment?") benefits from seeing the
whole conversation, and coupling it into the live call loop would add
latency and risk breaking character. The analyzer output is explicitly a
draft — the rubric asks for well-described bugs over a long list of
nitpicks, and that kind of judgment call needs a human pass, not raw model
output shipped as-is.

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
bug_analyzer.py --(reads transcripts, calls OpenAI chat completions)--> BUG_REPORT.md
```
