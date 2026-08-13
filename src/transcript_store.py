"""
Very small helper for writing a running transcript to disk as a call happens,
so that even if something crashes mid-call we still have partial evidence.
"""
import os
import json
import time
from src.config import TRANSCRIPTS_DIR

os.makedirs(TRANSCRIPTS_DIR, exist_ok=True)


class TranscriptWriter:
    def __init__(self, call_sid: str, scenario_id: str):
        self.call_sid = call_sid
        self.scenario_id = scenario_id
        self.path = os.path.join(TRANSCRIPTS_DIR, f"{scenario_id}_{call_sid}.txt")
        self.json_path = os.path.join(TRANSCRIPTS_DIR, f"{scenario_id}_{call_sid}.json")
        self.turns = []
        with open(self.path, "w") as f:
            f.write(f"# Scenario: {scenario_id}\n# Call SID: {call_sid}\n\n")

    def add_turn(self, speaker: str, text: str):
        """speaker is 'caller_bot' (our simulated patient) or 'agent_under_test'."""
        text = (text or "").strip()
        if not text:
            return
        entry = {"speaker": speaker, "text": text, "t": time.time()}
        self.turns.append(entry)
        label = "PATIENT (our bot)" if speaker == "caller_bot" else "PRACTICE AGENT"
        with open(self.path, "a") as f:
            f.write(f"[{label}] {text}\n")
        with open(self.json_path, "w") as f:
            json.dump(self.turns, f, indent=2)

    def full_text(self) -> str:
        lines = []
        for t in self.turns:
            label = "PATIENT" if t["speaker"] == "caller_bot" else "AGENT"
            lines.append(f"{label}: {t['text']}")
        return "\n".join(lines)
