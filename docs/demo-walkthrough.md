# Portfolio demonstration script

Allow roughly 8–10 minutes. Use fictional resumes and owned inbox/calendar accounts only.
Run the app and confirm provider mode before recording. Preview mode is useful offline, but label
it clearly; do not describe a simulated action as a delivered email or booked calendar event.

1. **Introduction (45 seconds):** Open the read-only public dashboard. Explain the goal: recruiters
   inspect job-relevant evidence and make the decisions. Point out the three sample roles.
2. **Job requirements (1 minute):** Sign in as recruiter. Create a job, draft/edit criteria, show that
   weights total 100, and confirm them. Mention that criteria/profile changes invalidate old results.
3. **Resume import (1 minute):** Upload a PDF and DOCX from `samples/resumes`, confirm they are
   synthetic, and watch processing progress. Inspect the parsed profile and correct a field if needed.
4. **Evidence review (2 minutes):** Start screening, open a source excerpt, compare candidates,
   and show an insufficient-evidence criterion. Review the result. Demonstrate that a high score
   alone has not moved the pipeline stage, then explicitly shortlist the candidate.
5. **Assessment (1.5 minutes):** Approve a short questionnaire and create an invitation. Open the
   link in a separate tab, answer the questions, and submit future availability. Show the submission
   receipt and that a second submission is refused. Back in the workspace, review the separate
   MCQ score and advisory feedback.
6. **Scheduling and outcome (1.5 minutes):** Select candidate availability, check Calendar, confirm
   the owned test attendee, and inspect the action receipt. With live configuration, show the actual
   test event/inbox. Add interview feedback and record a hiring outcome with a note.
7. **Engineering evidence (1 minute):** Show the role boundary with a manager account, the audit
   history, processing errors/retry, and the evaluation report. Explain the difference between term
   matching in demo mode and a separately evaluated Gemini run.

Useful failure demonstrations: upload a blank scanned PDF, change confirmed criteria then inspect
a stale screening, revisit a submitted invite, or attempt a busy calendar slot. For restart recovery,
pause a new screening at review, restart the API, and then approve it without repeating AI evaluation.

Close with the measured benchmark limitations and free-host sleeping behavior. Present the source,
tests, architecture, and deployment recipe together; do not claim real hiring validation or guaranteed
production availability from the synthetic demo.
