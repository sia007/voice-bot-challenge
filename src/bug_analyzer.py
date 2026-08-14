"""
After the calls are made, run this to have an LLM do a first pass over every
transcript looking for concrete bugs/quality issues, formatted to match the
example in the challenge doc. This is a *starting point* -- skim its output
and edit BUG_REPORT.md by hand before submitting; don't ship raw model
output uncritically (the challenge explicitly says they're not looking for
one-shot copy-paste).
"""
import os
import glob
import json
from openai import OpenAI

from src.config import settings, TRANSCRIPTS_DIR, BUG_REPORT_PATH

client = OpenAI(api_key=settings.openai_api_key)

ANALYSIS_PROMPT = """You are a QA engineer reviewing a transcript of a phone call between a
simulated patient and an AI medical-office phone agent that is being evaluated for bugs.

Read the transcript below (scenario: {scenario_title}) and list any concrete bugs or quality
issues you can find.

Pay special attention to OUTCOME, not just phrasing: did the patient's actual request from this
call (the reason they called) get resolved by the end of the transcript? A call that ends in a
transfer, a dropped line, or a vague "someone will follow up" WITHOUT the original request being
completed is a serious bug (severity High or Critical) even if every individual line the agent
said was polite and well-formed. Don't undersell an unresolved call as a minor tone/phrasing
issue -- the outcome matters more than the wording.

Also look for: factual errors, failure to validate constraints (e.g. confirming an appointment on
a day/time without checking availability or office hours), ignoring what the caller said, unclear
or contradictory answers, inappropriate medical advice, failure to ask for necessary identifying
info, poor handling of interruptions, and overly robotic phrasing.

Only report things that are actually visible in the transcript -- do not invent issues. If you
find nothing notable, say so explicitly.

For each issue, respond in this exact format (one block per issue):

Bug: <one-line description>
Severity: <Low|Medium|High|Critical>
Quote: <short quote from the transcript, <15 words, showing the issue>
Details: <1-3 sentences explaining why it's a problem, and explicitly note whether the patient's
original request was ultimately resolved or not>

---

Transcript:
{transcript_text}
"""

CROSS_CALL_PROMPT = """You are a QA lead doing a final pass over a bug report that was drafted by
analyzing phone call transcripts one at a time. Because each transcript was reviewed in isolation,
the draft may have under-reported issues that are actually the SAME recurring bug showing up
across multiple calls -- e.g. several calls independently flagged as "abrupt ending" or "transfer
without resolution" might really be one systemic bug (like a broken escalation/transfer flow)
rather than several unrelated minor issues.

Read the full draft report below and identify any bug that appears to recur across 3 or more
different calls. For each recurring pattern you find, write ONE consolidated entry:

Bug: <one-line description of the systemic issue>
Severity: Critical (recurring, systemic issues that block the patient's core request are more
severe than any single instance)
Calls affected: <list the call/file names involved>
Details: <2-4 sentences describing the pattern and why its frequency makes it more serious than
the individual entries suggest>

If you find no genuinely recurring pattern (i.e. every issue really is a one-off), say so
explicitly rather than forcing a consolidation.

Draft report:
{draft_report}
"""


def analyze_transcript(scenario_id: str, scenario_title: str, transcript_text: str) -> str:
    resp = client.chat.completions.create(
        model=settings.openai_analysis_model,
        messages=[
            {"role": "user", "content": ANALYSIS_PROMPT.format(
                scenario_title=scenario_title,
                transcript_text=transcript_text,
            )},
        ],
        temperature=0.2,
    )
    return resp.choices[0].message.content


def analyze_cross_call_patterns(draft_report: str) -> str:
    resp = client.chat.completions.create(
        model=settings.openai_analysis_model,
        messages=[
            {"role": "user", "content": CROSS_CALL_PROMPT.format(draft_report=draft_report)},
        ],
        temperature=0.2,
    )
    return resp.choices[0].message.content


def run_analysis():
    from src.scenarios import get_scenario

    txt_files = sorted(glob.glob(os.path.join(TRANSCRIPTS_DIR, "*.txt")))
    if not txt_files:
        print("No transcripts found -- run call_runner.py first.")
        return

    per_call_sections = []

    for path in txt_files:
        filename = os.path.basename(path)
        # filenames are "{scenario_id}_{call_sid}.txt"; call SIDs always start with "CA",
        # and scenario_ids can themselves contain underscores, so strip the trailing CA... part.
        parts = filename[:-4].split("_")
        scenario_id = "_".join(parts[:-1]) if parts and parts[-1].startswith("CA") else "_".join(parts)

        try:
            scenario = get_scenario(scenario_id)
            title = scenario["title"]
        except KeyError:
            title = scenario_id

        with open(path) as f:
            transcript_text = f.read()

        print(f"Analyzing {filename}...")
        analysis = analyze_transcript(scenario_id, title, transcript_text)

        per_call_sections.append(f"\n## Scenario: {title} ({filename})\n{analysis}\n")

    draft_body = "\n".join(per_call_sections)

    print("Looking for patterns that recur across multiple calls...")
    cross_call_findings = analyze_cross_call_patterns(draft_body)

    report_sections = [
        "# Bug Report\n",
        "Auto-drafted from call transcripts. Review and edit before submitting.\n",
        "\n## Recurring / Systemic Issues (across multiple calls)\n",
        cross_call_findings,
        "\n\n## Per-Call Findings\n",
        draft_body,
    ]

    with open(BUG_REPORT_PATH, "w") as f:
        f.write("\n".join(report_sections))

    print(f"\nDraft bug report written to {BUG_REPORT_PATH}")
    print("Review it, remove noise, and add call/timestamp references before submitting.")


if __name__ == "__main__":
    run_analysis()
