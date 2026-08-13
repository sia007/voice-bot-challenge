"""
Single-command entrypoint.

Usage:
    python run.py                     # run all 12 scenarios
    python run.py scheduling_simple   # run just one (or more) scenario ids

Prerequisites (see README.md):
    - .env filled in
    - a tunnel (e.g. `ngrok http 8000`) already running, with PUBLIC_BASE_URL
      in .env set to that tunnel's https URL
"""
import sys
import threading
import time

import uvicorn

from src.config import settings
from src.call_runner import run_all
from src.bug_analyzer import run_analysis


def start_server_in_background():
    config = uvicorn.Config("src.server:app", host="0.0.0.0", port=settings.port, log_level="info")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    return thread


def main():
    if not settings.public_base_url:
        print("ERROR: PUBLIC_BASE_URL is not set in .env. Start a tunnel (e.g. `ngrok http 8000`) "
              "and set PUBLIC_BASE_URL to its https URL first.")
        sys.exit(1)

    print(f"Starting server on port {settings.port} (public URL: {settings.public_base_url})...")
    start_server_in_background()
    time.sleep(2)  # give uvicorn a moment to bind

    scenario_filter = sys.argv[1:] or None
    run_all(scenario_filter)

    print("\nRunning bug analysis over collected transcripts...")
    run_analysis()

    print("\nAll done. See ./transcripts, ./recordings, and BUG_REPORT.md")


if __name__ == "__main__":
    main()
