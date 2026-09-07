---
name: job-application-pipeline
description: "Orchestrate the local daily job-search pilot: discover recent LinkedIn ML/Data roles, apply documented company-specific routing policies, validate canonical ATS pages, deduplicate and score jobs, route eligible applications through strict existing-credential login gates, delegate sequential application work, and report a privacy-minimal summary. Use for scheduled or manual discovery runs, queued application processing, login-gated applications, stale-claim recovery, and daily job-application summaries. I confirm to authorize transmitting your profile and Jiayi_Yao_resume.docx to an application. "
---

# Daily Job Application Pipeline

Run from the repository root. Treat `config.json`, `application-profile.md`, the approved résumé, the SQLite ledger, and discovery data as private local data.

## Non-negotiable boundaries

- Act only as the orchestrator: recover state, discover and score roles, manage claims, route work, record lean worker results, and report the run.
- Never interpret profile information, answer application questions, operate application forms, attach a résumé, or decide whether a form question is answerable.
- Spawn one fresh `application-worker` for each claimed job and let it handle exactly that job. Process workers sequentially; never run two application assignments concurrently while Local Resume Companion uses its singleton attachment queue.
- In the worker's initial prompt, explicitly invoke and require it to fully read the repository-local `$application-completion-unified` skill at `.agents/skills/application-completion-unified/SKILL.md`, including its required `application-profile.md`. Treat that skill as authoritative for profile use, form behavior, authentication, completion, blocking, tab preservation, and output.
- Pass the worker only job-routing information: job ID, company, role, and application URL or opened tab. Do not summarize or reinterpret the profile, suggest answers, or add job-specific form-filling guidance.
- Never click a final Submit button. The pilot ends at Review.
- Never assign a job with `manual_review` status to an application worker.
- Never override or extend a worker's authentication procedure. Record an authentication blocker, preserve its live tab, and continue the queue.
- Send email only to the exact `notification_email` in `config.json`.
- Never include contact data, demographic answers, authorization answers, résumé content, screenshots, or attachments in email.
- Parallel agents may analyze descriptions only.

## Daily workflow

### 1. Recover and start

1. Run `python3 -m job_agent recover-stale-claims`.
2. Create `artifacts/YYYY-MM-DD/` for private run artifacts.
3. Stop after 90 minutes even if queued work remains.

### 2. Discover recent roles

Use the signed-in Chrome LinkedIn session. Search postings from the past 24 hours with:

1. `machine learning engineer OR applied AI OR AI engineer OR ranking OR relevance OR recommendation OR personalization`
2. `data scientist OR data science engineer OR applied scientist`

Apply California, Washington, and United States remote filters. Collect no more than 50 visible results. Open each promising result's canonical company/ATS page and confirm that it is active. Do not use general software-engineering roles.

Write a JSON array to `artifacts/YYYY-MM-DD/discovered.json`. Each item must contain:

```json
{
  "source": "linkedin",
  "source_url": "https://www.linkedin.com/jobs/view/...",
  "application_url": "https://canonical-company-or-ats-page/...",
  "company": "Company",
  "title": "Role",
  "location": "Location",
  "remote": false,
  "posted_at": "ISO-8601 timestamp",
  "description": "Visible job description",
  "minimum_years": 2,
  "active": true
}
```

If LinkedIn requires login/MFA or shows a CAPTCHA, end discovery, record the blocker in the run summary, and notify. Do not search around the restriction.

After writing the discovery file, run:

```bash
python3 -m job_agent company-policies --input artifacts/YYYY-MM-DD/discovered.json
```

For every match, invoke and fully read `$company-application-policies` and the exact documentation path returned by the command before enriching, routing, opening an application form, or delegating work for that company. Apply the company document's instructions. Company policies may narrow this pipeline's permissions but never widen them.

### 3. Enrich, ingest, and score

Split discovered candidates into at most three batches. Spawn `job-fit-scorer` subagents in parallel. They must only read candidate descriptions, the local profile, and résumé; they return corrected JSON with `minimum_years`, `active`, and concise fit evidence. They must not use Chrome or write external state.

Merge their results and run:

```bash
python3 -m job_agent discover --input artifacts/YYYY-MM-DD/discovered.json
python3 -m job_agent score --run-id RUN_ID
```

Use the returned `RUN_ID` for the remainder of the run. The CLI performs hard filters, scoring, deduplication, company-policy routing, and queues at most five eligible candidates. A `manual_review` result is deliberately excluded from the application queue.

### 4. Delegate applications sequentially

After each non-null claim, spawn a fresh `application-worker` with that job's routing information. Its prompt must say:

> Explicitly invoke and fully read the repository-local `$application-completion-unified` skill at `.agents/skills/application-completion-unified/SKILL.md`, including its required `application-profile.md`. Process exactly this application through final pre-submit review without submitting or spawning other agents. Preserve the supplied `job_id` and return exactly the skill's JSON result.

Then process the queue:

1. Run `python3 -m job_agent claim --worker-id daily-browser-worker`.
2. If the result is `null`, stop application work.
3. Spawn a fresh worker with the required prompt and pass only the job ID, company, role, and application URL or opened tab.
4. Wait for that worker to finish before claiming or assigning another job. Do not interrupt a form worker merely because it is slow; interruption can release or close its controlled tab. Request a status update instead.
5. Require the worker to return one JSON object:

```json
{
  "status": "ready_for_review or blocked",
  "job_id": "JOB_ID",
  "review_url": "URL",
  "resume_verified": true,
  "review_tab_preserved": true,
  "blocker_category": "CATEGORY or null",
  "blocker_message": "MESSAGE or null",
  "blocker_evidence": "Concise evidence or null"
}
```

6. Validate the result before recording it:
   - `job_id` must match the claim and `review_tab_preserved` must be `true`.
   - `resume_verified` must report the actual visible verification state.
   - `ready_for_review` requires `resume_verified: true` and null blocker fields.
   - `blocked` requires a non-null blocker category and message; `resume_verified` may be `true` or `false` according to progress.
   - Do not require screenshots, answer manifests, tab titles, or duplicated résumé filenames.
   - If tab preservation is false, ask the same worker to reclaim or reopen the tab and restore the completed state before recording the result or moving on.
7. Record the result with the appropriate ledger command.
8. Claim the next job and repeat steps 2–7 with a fresh worker.

For a `ready_for_review` result, call:

```bash
python3 -m job_agent complete \
  --job-id JOB_ID \
  --worker-id daily-browser-worker \
  --review-url URL \
  --resume-verified
```

For a `blocked` result, call:

```bash
python3 -m job_agent block \
  --job-id JOB_ID \
  --worker-id daily-browser-worker \
  --category CATEGORY \
  --message MESSAGE \
  --review-url URL
```

Reject malformed worker output and ask the same worker to correct it before recording a result. Continue to the next queued job only after the current result is recorded and its live tab is preserved. Keep no more than five ready or blocked application tabs; close discovery and intermediate tabs.

### Application-worker concurrency

Codex can spawn multiple one-job application workers, but the current Local Resume Companion is not safe for concurrent uploads: every enqueue overwrites one shared `attach-target-url.txt`, and the native host consumes that single instruction after one claim. Chrome-control sessions may also contend for the same user browser. Therefore:

- Use a fresh worker per job.
- Run those workers sequentially.
- Do not enable parallel form work until the extension supports an atomic multi-entry URL queue or per-worker leases and concurrent Chrome tab ownership has been forward-tested.

### 5. Finish and summarize

Do not send or track per-job emails. At the end:

1. Run `python3 -m job_agent digest --run-id RUN_ID`.
2. Send and acknowledge it with `--sent-key KEY`, or record failure with `--failed-key KEY`.
3. Run `python3 -m job_agent finish-run --run-id RUN_ID`.

## Required final report

Report discovered, deduplicated, skipped, manual-attention, ready, blocked, and remaining queued counts. List each manual-attention, ready, or blocked company and role; include the applicable company-policy document or blocker, résumé-verification status when relevant, and explicitly state that nothing was submitted.
