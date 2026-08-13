"""
Orchestrator: for each scenario, place an outbound call from our Twilio
number to the target test line, wait for it to finish, then pull down the
recording. Run this while `uvicorn src.server:app` (or `python run.py`) is
already up and reachable at PUBLIC_BASE_URL.
"""
from __future__ import annotations

import os
import sys
import time
import requests
from twilio.rest import Client

from src.config import settings, RECORDINGS_DIR
from src.scenarios import SCENARIOS

os.makedirs(RECORDINGS_DIR, exist_ok=True)


def place_call(client: Client, scenario_id: str) -> str:
    call = client.calls.create(
        to=settings.target_number,
        from_=settings.twilio_from_number,
        url=f"{settings.public_base_url}/twiml/{scenario_id}",
        record=True,
        recording_channels="dual",
        machine_detection="Enable",
        timeout=30,
    )
    return call.sid


def wait_for_call_completion(client: Client, call_sid: str, timeout_s: int) -> str:
    start = time.time()
    while time.time() - start < timeout_s:
        call = client.calls(call_sid).fetch()
        if call.status in ("completed", "busy", "failed", "no-answer", "canceled"):
            return call.status
        time.sleep(3)
    return "timeout"


def download_recording(client: Client, call_sid: str, scenario_id: str, max_wait_s: int = 60) -> str | None:
    """Twilio finishes processing the recording a few seconds *after* the
    call itself is marked completed, so poll until it's actually ready
    (status == 'completed') instead of grabbing it immediately."""
    start = time.time()
    recording = None
    while time.time() - start < max_wait_s:
        recordings = client.recordings.list(call_sid=call_sid)
        if recordings:
            candidate = recordings[0]
            if candidate.status == "completed":
                recording = candidate
                break
            print(f"  [info] recording status={candidate.status}, waiting...")
        else:
            print("  [info] recording not yet visible via API, waiting...")
        time.sleep(3)

    if recording is None:
        print(f"  [warn] no completed recording found for {call_sid} after {max_wait_s}s")
        return None

    # Twilio serves recordings as .mp3 or .wav via this URL pattern.
    media_url = f"https://api.twilio.com{recording.uri.replace('.json', '.mp3')}"
    for attempt in range(3):
        resp = requests.get(media_url, auth=(settings.twilio_account_sid, settings.twilio_auth_token))
        if resp.status_code == 200:
            out_path = os.path.join(RECORDINGS_DIR, f"{scenario_id}_{call_sid}.mp3")
            with open(out_path, "wb") as f:
                f.write(resp.content)
            return out_path
        print(f"  [info] recording media not ready yet (HTTP {resp.status_code}), retrying...")
        time.sleep(3)

    print(f"  [warn] gave up downloading recording media for {call_sid}")
    return None


def run_all(scenario_filter: list[str] | None = None):
    client = Client(settings.twilio_account_sid, settings.twilio_auth_token)
    scenarios = SCENARIOS if not scenario_filter else [s for s in SCENARIOS if s["id"] in scenario_filter]

    results = []
    for i, scenario in enumerate(scenarios):
        print(f"\n[{i+1}/{len(scenarios)}] Calling for scenario '{scenario['id']}' ({scenario['title']})...")
        call_sid = place_call(client, scenario["id"])
        print(f"  call_sid={call_sid} -- waiting for completion...")
        status = wait_for_call_completion(client, call_sid, settings.call_timeout_seconds)
        print(f"  call finished with status={status}")

        recording_path = download_recording(client, call_sid, scenario["id"])
        if recording_path:
            print(f"  recording saved -> {recording_path}")

        results.append({
            "scenario_id": scenario["id"],
            "call_sid": call_sid,
            "status": status,
            "recording_path": recording_path,
        })

        if i < len(scenarios) - 1:
            time.sleep(settings.seconds_between_calls)

    print("\nDone. Summary:")
    for r in results:
        print(f"  {r['scenario_id']:<28} status={r['status']:<10} sid={r['call_sid']}")
    return results


if __name__ == "__main__":
    only = sys.argv[1:] or None
    run_all(only)
