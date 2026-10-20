---
name: job-application-pipeline
description: "Orchestrate the local daily job-search pilot: discover recent ML/Data roles from the company registry's ATS job feeds, apply documented company-specific routing policies, validate canonical ATS pages, deduplicate and score jobs, route eligible applications through strict login gates (existing credentials or an account agent-vault creates), delegate sequential application work that submits when enabled, analyze blockers into to-dos, check Gmail for recruiter replies, and report a privacy-minimal summary. Use for scheduled or manual discovery runs, queued application processing, login-gated applications, stale-claim recovery, and daily job-application summaries."
---

# Daily Job Application Pipeline

Run from the repository root. Invoking this skill, including from the scheduled daily run, is the user's authorization to transmit `application-profile.md` facts and `Jiayi_Yao_resume.docx` to the application sites processed in the run and, while `submit_applications` is `true` in `config.json`, to submit those applications. Treat `config.json`, `application-profile.md`, the approved résumé, the SQLite ledger, and discovery data as private local data.

## Non-negotiable boundaries

- Act only as the orchestrator: recover state, discover and score roles, manage claims, route work, record lean worker results, and report the run.
- Never interpret profile information, answer application questions, operate application forms, attach a résumé, or decide whether a form question is answerable.
- Use the Agent tool with `subagent_type: "application-worker"` to start one fresh worker for each claimed job and let it handle exactly that job. Process workers sequentially; never run two application assignments concurrently while Local Resume Companion uses its singleton attachment queue.
- In the worker's initial prompt, require it to fully read and follow the repository-local `application-completion` skill at `.claude/skills/application-completion/SKILL.md`, including its required `application-profile.md`. Treat that skill as authoritative for profile use, form behavior, authentication, completion, blocking, tab preservation, and output.
- Pass the worker only job-routing information: job ID, company, role, and application URL or opened tab. Do not summarize or reinterpret the profile, suggest answers, or add job-specific form-filling guidance.
- Submission is the worker's job, never the orchestrator's. `claim` returns `submit: true` only while `config.json` has `submit_applications: true`; pass that value to the worker unchanged. With `submit: false`, workers stop at Review.
- Never assign a job with `manual_review` status to an application worker.
- Never override or extend a worker's authentication procedure. Record an authentication blocker, preserve its live tab, and continue the queue.
- Send email only with the Gmail `send_message` tool and only to the exact `notification_email` in `config.json`.
- Never include contact data, demographic answers, authorization answers, résumé content, screenshots, or attachments in email.
- Gmail is read-only apart from that one summary email: never reply to, label, archive, or forward a recruiter message.
- Parallel agents may analyze descriptions only.

## Daily workflow

### 1. Recover and start

1. Run `python3 -m job_agent recover-stale-claims`.
2. Create `artifacts/YYYY-MM-DD/` for private run artifacts.
3. Stop after 90 minutes even if queued work remains.

### 2. Discover recent roles

Discovery is a ledger command, not a browser task. Run:

```bash
python3 -m job_agent fetch-feeds --registry data/company-registry.json --out artifacts/YYYY-MM-DD/discovered.json
```

It pulls the Greenhouse, Lever, Ashby, Workday and Amazon job boards listed in `data/company-registry.json` (private, gitignored; template `company-registry.example.json` at the repo root), keeps ML/Data individual-contributor postings from the past `recency_hours` whose location is preferred or US-remote, and writes the discovery array. Each item has this shape:

```json
{
  "source": "ats-api",
  "source_url": "https://job-boards.greenhouse.io/company/jobs/123",
  "application_url": "https://job-boards.greenhouse.io/company/jobs/123",
  "company": "Company",
  "title": "Role",
  "location": "Location",
  "remote": false,
  "posted_at": "ISO-8601 timestamp",
  "description": "Job description text",
  "minimum_years": null,
  "active": true
}
```

Put the per-board stats it prints (`fetched`, `kept`, `errors`) in the run summary. A board that errors is a note in the summary, not a run blocker. If the command itself fails or the registry is missing, record that as the discovery blocker, skip steps 3 and 4, and continue with sections 5–7.

Do not browse LinkedIn or any job board in Chrome to discover roles: the registry feeds are the run's only discovery source. Companies missing from the registry are added by the user, one line each.

After writing the discovery file, run:

```bash
python3 -m job_agent company-policies --input artifacts/YYYY-MM-DD/discovered.json
```

For every match, invoke the `company-application-policies` skill, read it fully, and the exact documentation path returned by the command before enriching, routing, opening an application form, or delegating work for that company. Apply the company document's instructions. Company policies may narrow this pipeline's permissions but never widen them.

### 3. Enrich, ingest, and score

Split discovered candidates into at most three batches. Start `job-fit-scorer` agents (Agent tool, `subagent_type: "job-fit-scorer"`) in parallel by sending the calls in one message. They must only read candidate descriptions, the local profile, and résumé; they return corrected JSON with `minimum_years`, `active`, and concise fit evidence. They must not use Chrome or write external state.

Merge their results and run:

```bash
python3 -m job_agent discover --input artifacts/YYYY-MM-DD/discovered.json
python3 -m job_agent score --run-id RUN_ID
```

Use the returned `RUN_ID` for the remainder of the run. The CLI performs hard filters, scoring, deduplication, company-policy routing, and queues at most five eligible candidates. A `manual_review` result is deliberately excluded from the application queue.

### 4. Delegate applications sequentially

After each non-null claim, start a fresh `application-worker` with that job's routing information. Its prompt must say:

> Fully read and follow the repository-local `application-completion` skill at `.claude/skills/application-completion/SKILL.md`, including its required `application-profile.md`. Process exactly this application without spawning other agents. `submit: SUBMIT` — with `true`, submit it after the final pre-submit checks pass and confirm receipt as the skill's submit-and-confirm section describes; with `false`, stop at final pre-submit review. Preserve the supplied `job_id` and return exactly the skill's JSON result.

Replace `SUBMIT` with the claim's `submit` value.

Then process the queue:

1. Run `python3 -m job_agent claim --worker-id daily-browser-worker`.
2. If the result is `null`, stop application work.
3. Start a fresh worker with the required prompt and pass only the job ID, company, role, application URL or opened tab, and the claim's `submit` value.
4. Run the worker in the foreground and wait for it to finish before claiming or assigning another job. Do not stop a form worker merely because it is slow; stopping it can release or close its controlled tab.
5. Require the worker to return one JSON object:

```json
{
  "status": "submitted, ready_for_review, or blocked",
  "job_id": "JOB_ID",
  "review_url": "URL",
  "resume_verified": true,
  "review_tab_preserved": true,
  "confirmation_evidence": "On-page confirmation quote or null",
  "blocker_category": "CATEGORY or null",
  "blocker_message": "MESSAGE or null",
  "blocker_evidence": "Concise evidence or null"
}
```

6. Validate the result before recording it:
   - `job_id` must match the claim and `review_tab_preserved` must be `true`.
   - `resume_verified` must report the actual visible verification state.
   - `submitted` requires the claim's `submit: true`, `resume_verified: true`, non-null `confirmation_evidence`, and null blocker fields.
   - `ready_for_review` requires `resume_verified: true` and null blocker fields. With `submit: true`, it also needs a reason in `blocker_evidence` or the worker's message (the skill's pre-submit stop conditions); ask the worker with SendMessage if none is given, and record that reason in the run report.
   - `blocked` requires a non-null blocker category and message; `resume_verified` may be `true` or `false` according to progress.
   - Do not require screenshots, answer manifests, tab titles, or duplicated résumé filenames.
   - If tab preservation is false, use SendMessage to ask the same worker to reclaim or reopen the tab and restore the completed state before recording the result or moving on.
7. Record the result with the appropriate ledger command.
8. Claim the next job and repeat steps 2–7 with a fresh worker.

For a `submitted` result, call:

```bash
python3 -m job_agent submit --job-id JOB_ID --worker-id daily-browser-worker --confirmation-url URL --evidence "CONFIRMATION_EVIDENCE" --resume-verified
```

For a `ready_for_review` result, call:

```bash
python3 -m job_agent complete --job-id JOB_ID --worker-id daily-browser-worker --review-url URL --resume-verified
```

For a `blocked` result, call:

```bash
python3 -m job_agent block --job-id JOB_ID --worker-id daily-browser-worker --category CATEGORY --message MESSAGE --review-url URL
```

Reject malformed worker output and use SendMessage to ask the same worker to correct it before recording a result. Continue to the next queued job only after the current result is recorded and its live tab is preserved. Close a submitted application's tab once its result is recorded, since nothing is left to review there. Keep no more than five ready or blocked application tabs; close discovery and intermediate tabs.

### Application-worker concurrency

Claude can run multiple one-job application workers, but the current Local Resume Companion is not safe for concurrent uploads: every enqueue overwrites one shared `attach-target-url.txt`, and the native host consumes that single instruction after one claim. Chrome-control sessions may also contend for the same user browser. Therefore:

- Use a fresh worker per job.
- Run those workers sequentially.
- Do not enable parallel form work until the extension supports an atomic multi-entry URL queue or per-worker leases and concurrent Chrome tab ownership has been forward-tested.

### 5. Analyze blockers and file to-dos

Run `python3 -m job_agent report --since TODAY` (TODAY as `YYYY-MM-DD`, UTC) for this run's attempts and `python3 -m job_agent report` for the all-time rate. For every blocked job today, and for every `ready_for_review` that should have been submitted, decide the root cause from the worker's blocker message and evidence: authentication (which ATS or identity provider, which agent-vault status), ATS control or navigation, résumé upload, CAPTCHA or identity verification, submission rejected or unconfirmed, or infrastructure (Chrome, extension, agent-vault). Write the analysis to `artifacts/YYYY-MM-DD/retro.md`.

Then decide whether each fix is a generalization improvement: a change to the worker skill, agent-vault, Local Resume Companion, or the pipeline that would also unblock other companies on the same ATS or the same kind of gate (for example "agent-vault register misses the iCIMS Email field", "Workday Network Error on upload needs a retry"). One-off causes are not: the posting closed, one company needs an account only the user can create, or identity verification the user must do in person.

The project's to-do list is the "Job Application Agent To-Dos" artifact, https://claude.ai/artifact/WSphNhTrrHRRg3DVgEKDhi (load `ArtifactData` with ToolSearch if deferred):

1. `list` the `todos` collection and `get` `meta/seq`.
2. For each generalization fix, skip it if an open to-do already covers it (append today's company to that row's `note` with a pinned `update` instead). Otherwise add a row `JOB-<num>` with `num`, `title` (the fix, imperative), `note` (root cause, affected companies and ATS, evidence), `owner: "claude"`, `status: "open"`, `priority` (`high` when it blocked two or more jobs or a whole ATS), `created_at: TODAY`.
3. For one-off blockers that need the user (an account, in-person verification), add an `owner: "barry"` row unless one exists.
4. Write all rows and the bumped `meta/seq` (`{next: last + 1}`, pinned with `if_version`) in one `batch`.

If the artifact tools are unavailable, put the proposed to-dos in the run report and the summary email instead.

### 6. Check Gmail for recruiter replies

Read the companies from `python3 -m job_agent report` (all time): the `submitted` list, plus the `ready_for_review` list, since the user submits some of those by hand. Search Gmail (the claude.ai Gmail connector's `search_threads`, read-only) for threads from the last 14 days whose sender or subject names one of those companies, excluding the user's own sent mail, for example `newer_than:14d -from:me (Company1 OR Company2 ...)`. Classify each relevant thread by its subject and snippet only:

- `recruiter_outreach`: a person asks to talk, schedule a call, or answer questions.
- `interview_or_assessment`: an interview invitation, scheduling link, or online assessment.
- `rejection`: the application is closed.
- `confirmation`: an automated "we received your application". For a `ready_for_review` job, this means the user submitted it; say so in the report.

Ignore job alerts, newsletters, and agent-vault verification emails. Do not open links, reply, or download attachments. In the report and the email, list each recruiter, interview, or rejection thread as company, role if known, category, and date: no sender names, addresses, or message text. Recruiter outreach and interviews go first, since they need the user. Add an `owner: "barry"`, `priority: "high"` to-do for each new recruiter outreach or interview thread (same batch rules as section 5).

### 7. Finish and summarize

Do not send or track per-job emails. At the end:

1. Run `python3 -m job_agent digest --run-id RUN_ID`. The body already includes the submission rate and blocker counts for this run. Append, as plain lines: the all-time submission rate from section 5, the root cause of each blocker and whether a to-do was filed (by ID), and the Gmail findings from section 6.
2. If the payload is `eligible`, send `email.subject` and `email.body` to exactly `email.to` with the Gmail `send_message` tool. Then acknowledge with `python3 -m job_agent digest --run-id RUN_ID --sent-key KEY`, or record failure with `--failed-key KEY`.
3. Run `python3 -m job_agent finish-run --run-id RUN_ID`.

## Required final report

Report discovered, deduplicated, skipped, manual-attention, submitted, ready, blocked, and remaining queued counts, plus the percentage of attempted applications submitted today and all time. List each manual-attention, submitted, ready, or blocked company and role; include the applicable company-policy document, the confirmation evidence for submissions, or the blocker and its root cause. List the to-dos filed (by ID) and the recruiter, interview, and rejection emails found. If `submit` was `false`, state that nothing was submitted.
