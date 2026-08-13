# Pretty Good AI — Voice Bot Challenge

A voice bot that calls Pretty Good AI's test line (`+1-805-439-8008`), plays a
set of realistic patient personas, has a natural spoken conversation with
their agent, records and transcribes every call, and drafts a bug report
from what it finds.

Quick version of how it works: Twilio dials the test line and opens a live
audio connection back to a small local server, which pipes that audio
straight into an OpenAI Realtime API session playing a specific patient
persona. See `ARCHITECTURE.md` for the full reasoning behind that choice.

## Before you start

You'll need:
- Python 3.9+ (3.10+ preferred, but 3.9 works — see note below)
- A **paid/upgraded** Twilio account (not the free trial — trial accounts
  block several call parameters this project uses, and can't call arbitrary
  numbers), with a **Trust Hub Primary Business/Individual profile approved**
  (a KYC step Twilio requires before placing outbound calls; can take up to
  48 hours, so do this first if you haven't already)
- A Twilio phone number capable of outbound calling
- An OpenAI API key with billing/credits added, with access to the
  Realtime API
- [ngrok](https://ngrok.com/) installed, with a free account and your
  authtoken configured (`ngrok config add-authtoken <token>`) — Twilio needs
  a public URL to reach your laptop over

## Setup

```bash
git clone <this-repo>
cd voice-bot-challenge
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
```

Open `.env` and fill in:
- `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN` — from the Twilio console dashboard
- `TWILIO_FROM_NUMBER` — the Twilio number you bought (E.164 format, e.g. `+13334445555`)
- `OPENAI_API_KEY` — from platform.openai.com
- Leave `TARGET_NUMBER` as the provided test line

Leave `PUBLIC_BASE_URL` for the next step.

**Note on Python 3.9:** if `python3 --version` shows 3.9.x, that's fine —
the code's written to work on it. Just make sure you're actually using the
venv's Python (`source .venv/bin/activate` first) so the pinned dependency
versions in `requirements.txt` are respected; a couple of them are pinned
specifically to avoid version-mismatch errors between `openai`/`httpx` and
`websockets`.

## Start a tunnel (keep this running the whole time)

In its own terminal:
```bash
ngrok http 8000
```
Copy the `https://xxxx.ngrok-free.app` (or `.dev`) URL it prints, and paste
it into `.env` as `PUBLIC_BASE_URL` (no trailing slash). **This URL changes
every time you restart ngrok on the free tier** — if you restart it, update
`.env` again before your next run.

## Run

In a second terminal (venv activated):

```bash
python run.py
```

This starts the local server, calls all 12 scenarios in `src/scenarios.py`
one after another, downloads each recording, and finishes by drafting
`BUG_REPORT.md` from the transcripts. Expect it to take roughly 25-40
minutes end to end (a few minutes per call, small gaps between calls) — this
is intentionally sequential rather than parallel so you can watch each call
happen in the logs.

To run just one or a few scenarios while testing (much cheaper than the full
set):
```bash
python run.py scheduling_simple
python run.py scheduling_simple medication_refill
```

**`run.py` is not a persistent server** — it starts the server, does its
job, and exits. You can't `curl` against it after it finishes; if you want
to poke at the server directly, do it while a `run.py` process is actively
running.

Outputs land in:
- `transcripts/` — a `.txt` (readable) and `.json` (structured) per call
- `recordings/` — a `.mp3` per call
- `BUG_REPORT.md` — an LLM-drafted first pass. **Read and edit this by
  hand** before submitting — it's a starting point, not the final artifact.

## Repo layout

```
run.py                   # single entrypoint (server + call runner + analysis)
src/
  config.py               # env var loading
  scenarios.py             # patient personas
  server.py                 # FastAPI: TwiML endpoint + media-stream <-> Realtime bridge
  call_runner.py             # places calls via Twilio, downloads recordings
  transcript_store.py         # incremental transcript writer
  bug_analyzer.py               # LLM pass over transcripts -> BUG_REPORT.md draft
transcripts/                     # output: call transcripts
recordings/                       # output: call audio (.mp3)
BUG_REPORT.md                      # output: bug findings
ARCHITECTURE.md
```

## If something breaks

A few real issues I hit while building this, in case you hit them too:
- **`connection refused` on ngrok** → the local server isn't running; both
  ngrok and `python run.py` need to be up at the same time.
- **Twilio "Invalid or disallowed parameters"** → trial account, needs upgrading.
- **Twilio "compliance profile not approved"** → Trust Hub KYC step above,
  wait for approval.
- **`beta_api_shape_disabled` from OpenAI** → OpenAI retired the old beta
  Realtime API; this repo is already updated for the GA API, but if you're
  troubleshooting further, don't reintroduce the `OpenAI-Beta` header or the
  old flat `input_audio_format`/`modalities` session keys.
- **`insufficient_quota` from OpenAI** → add billing credits.
