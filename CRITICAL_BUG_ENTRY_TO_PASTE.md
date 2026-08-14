## CRITICAL: Agent silently drops calls it can't resolve, via a fake "transfer"

**Severity:** Critical
**Calls affected:** at least 6 of 12 —
`cancel_appointment_CA44cc490c18bee85216022323decb38d3.txt`,
`scheduling_specific_time_CA3232b9fd15676e6a04d9b2ca4cbcd3c4.txt`,
`reschedule_existing_CAdc26177aac315ecbb4c11a271ba48c11.txt`,
`interruption_barge_in_CA1e7d4d7afbe432762648cd0675e445de.txt`,
`unclear_garbled_request_CAd11083e4acf80aff92b4aeb6e13eca64.txt`,
`angry_frustrated_patient_CAdeebe8e43b8db7b91bb757aeaec0c70e.txt`

**Details:** Across the majority of test calls, whenever the agent hits a
situation it can't resolve inline (can't find a record, needs to cancel,
needs to reschedule, or in one case after fully and correctly verifying the
patient's identity), it follows an identical script: offer to "connect you
to our patient support team," say "Transferring you now. Thank you," then
immediately play "Hello, you've reached the Pretty Good AI test line.
Goodbye" and hang up. No real transfer happens. No follow-up is logged. The
patient's original request is never completed.

This is not a one-off glitch in a single flow — it's the agent's default
fallback behavior for an entire class of situations (cancellations,
reschedules, interruptions, and general escalation), meaning most callers
who hit any obstacle end up talking to a dead line instead of a human.

The most damning instance: in `cancel_appointment_CA44cc490c18bee85216022323decb38d3.txt`,
the agent successfully collects and confirms the patient's full name (spelled
letter-by-letter), date of birth, and a corrected phone number over several
turns of real identity verification — then says "I can't proceed further
right now," offers the fake transfer, and hangs up anyway even after the
patient explicitly says "Actually, I need to cancel the appointment right
now" and, after being cut off, "Wait, I think there's been a
misunderstanding. I'm still here." The agent did the hard part (verification)
correctly and then abandoned the actual task the patient called for.

**Why this is severity Critical, not just High:** every other bug in this
report affects call quality. This one means the patient's underlying
request — the entire reason they called — silently fails, with no recovery
path, no error message admitting failure, and language ("transferring you
now") that actively implies help is coming when it isn't.

---

