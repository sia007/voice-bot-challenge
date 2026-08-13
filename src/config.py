"""
Central place for env vars + small shared constants.
Everything here is read once at import time so the rest of the codebase
can just do `from src.config import settings`.
"""
import os
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()


def _req(name: str, default: str = "") -> str:
    return os.getenv(name, default)


@dataclass
class Settings:
    twilio_account_sid: str = _req("TWILIO_ACCOUNT_SID")
    twilio_auth_token: str = _req("TWILIO_AUTH_TOKEN")
    twilio_from_number: str = _req("TWILIO_FROM_NUMBER")
    target_number: str = _req("TARGET_NUMBER", "+18054398008")

    openai_api_key: str = _req("OPENAI_API_KEY")
    openai_realtime_model: str = _req("OPENAI_REALTIME_MODEL", "gpt-4o-realtime-preview-2024-12-17")
    openai_analysis_model: str = _req("OPENAI_ANALYSIS_MODEL", "gpt-4o-mini")

    public_base_url: str = _req("PUBLIC_BASE_URL").rstrip("/")
    port: int = int(_req("PORT", "8000"))

    seconds_between_calls: int = int(_req("SECONDS_BETWEEN_CALLS", "10"))
    call_timeout_seconds: int = int(_req("CALL_TIMEOUT_SECONDS", "240"))


settings = Settings()

# Twilio Media Streams use 8kHz mu-law (G.711 u-law) audio. In the GA
# Realtime API this is expressed as a format *object* (not a flat string
# like the old beta API used) with type "audio/pcmu".
AUDIO_FORMAT = {"type": "audio/pcmu"}

TRANSCRIPTS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "transcripts")
RECORDINGS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "recordings")
BUG_REPORT_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "BUG_REPORT.md")
