---
name: job-application-pipeline
description: "Orchestrate the local daily job-search pilot: discover recent ML/Data roles from the company registry's ATS job feeds, apply documented company-specific routing policies, validate canonical ATS pages, deduplicate and score jobs, route eligible applications through strict login gates (existing credentials or an account agent-vault creates), delegate application work to parallel workers that submit when enabled, analyze blockers into to-dos, check Gmail for recruiter replies, and report a privacy-minimal summary. Use for scheduled or manual discovery runs, queued application processing, login-gated applications, stale-claim recovery, and daily job-application summaries."
---

# Daily Job Application Pipeline

Run from the repository root. Invoking this skill, including from the scheduled daily run, is the user's authorization to transmit `application-profile.md` facts and `Jiayi_Yao_resume.docx` to the application sites processed in the run and, while `submit_applications` is `true` in `config.json`, to submit those applications. Treat `config.json`, `application-profile.md`, the approved résumé, the SQLite ledger, and discovery data as private local data.

## Non-negotiable boundaries

- Act only as the orchestrator: recover state, discover and score roles, manage claims, route work, record lean worker results, and report the run.
- Never interpret profile information, answer application questions, operate application forms, attach a résumé, or decide whether a form question is answerable.
- Use the Agent tool with `subagent_type: "application-worker"` to start one fresh worker for each claimed job and let it handle exactly that job. Run up to `max_parallel_workers` of them at once (see "Application-worker concurrency").
- In the worker's initial prompt, require it to fully read and follow the repository-local `application-completion` skill at `.claude/skills/application-completion/SKILL.md`, including its required `application-profile.md`. Treat that skill as authoritative for profile use, form behavior, authentication, completion, blocking, tab preservation, and output.
- Pass the worker only job-routing information: job ID, company, role, and application URL. Do not summarize or reinterpret the profile, suggest answers, or add job-specific form-filling guidance.
- Submission is the worker's job, never the orchestrator's. `claim` returns `submit: true` only while `config.json` has `submit_applications: true`; pass that value to the worker unchanged. With `submit: false`, workers stop at Review.
- Never assign a job with `manual_review` status to an application worker.
- Never override or extend a worker's authentication procedure. Record an authentication blocker, preserve its live tab, and continue the queue.
- Send email only with the Gmail `send_message` tool and only to the exact `notification_email` in `config.json`.
- Never include contact data, demographic answers, authorization answers, résumé content, screenshots, or attachments in email.
- Gmail is read-only apart from that one summary email: never reply to, label, archive, or forward a recruiter message.
- Apart from application workers, parallel agents may analyze descriptions only.

## Daily workflow

### 1. Recover and start

1. Run `python3 -m job_agent recover-stale-claims`.
2. Create `artifacts/YYYY-MM-DD/` for private run artifacts.
3. Stop after 90 minutes even if queued work remains. Jobs still `queued` stay queued and are claimed first by the next run.

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

It also starts the run and records in the ledger which companies were checked, how many postings each board returned, and how many it kept; it prints the `run_id` and `companies_checked`. Use that `RUN_ID` for the remainder of the run. Put the per-board stats it prints (`fetched`, `kept`, `errors`) in the run summary. A board that errors is a note in the summary, not a run blocker. If the command itself fails or the registry is missing, record that as the discovery blocker, skip steps 3 and 4, and continue with sections 5–7.

Do not browse LinkedIn or any job board in Chrome to discover roles: the registry feeds are the run's only discovery source. Companies missing from the registry are added by the user, one line each.

After writing the discovery file, run:

```bash
python3 -m job_agent company-policies --input artifacts/YYYY-MM-DD/discovered.json
```

For every match, invoke the `company-application-policies` skill, read it fully, and the exact documentation path returned by the command before enriching, routing, opening an application form, or delegating work for that company. Apply the company document's instructions. Company policies may narrow this pipeline's permissions but never widen them.

### 3. Enrich, ingest, and score

First write the résumé as text for the scorers to read:

```bash
python3 -m job_agent resume-text
```

Split discovered candidates into at most three batches. Start `job-fit-scorer` agents (Agent tool, `subagent_type: "job-fit-scorer"`) in parallel by sending the calls in one message. They must only read candidate descriptions, the local profile, and `data/resume.txt`; they return corrected JSON with `minimum_years`, `active`, concise fit evidence, and a `skill_score` (0–25) with its `skill_rationale`. Keep both fields on every candidate when merging, since `score` uses `skill_score` as the skills component. They must not use Chrome or write external state.

Merge their results and run:

```bash
python3 -m job_agent discover --input artifacts/YYYY-MM-DD/discovered.json --run-id RUN_ID
python3 -m job_agent score --run-id RUN_ID
```

Pass the `RUN_ID` from `fetch-feeds` to `discover`, so the jobs and the discovery stats share one run. If discovery failed and there is no `RUN_ID` yet, omit `--run-id` and use the one `discover` returns. The CLI performs hard filters, scoring, deduplication, company-policy routing, and queues every eligible candidate scoring at least `minimum_fit_score`; there is no daily cap. A `manual_review` result is deliberately excluded from the application queue.

### 4. Delegate applications to parallel workers

After each non-null claim, start a fresh `application-worker` with that job's routing information. Its prompt must say:

> Fully read and follow the repository-local `application-completion` skill at `.claude/skills/application-completion/SKILL.md`, including its required `application-profile.md`. Process exactly this application without spawning other agents. `submit: SUBMIT` — with `true`, submit it after the final pre-submit checks pass and confirm receipt as the skill's submit-and-confirm section describes; with `false`, stop at final pre-submit review. Preserve the supplied `job_id` and return exactly the skill's JSON result.

Replace `SUBMIT` with the claim's `submit` value.

Then process the queue with up to `SLOTS` workers at a time, where `SLOTS` is `max_parallel_workers` from `config.json` (default 2, at most 3). Slot `N` uses worker id `daily-browser-worker-N` for its claims and for recording its results.

1. For each free slot, run `python3 -m job_agent claim --worker-id daily-browser-worker-N --run-id RUN_ID`. Each claim is logged as one application attempt for this run. `claim` never hands out a job from a company that already has a claimed job, so parallel workers never sign in to or create the same company's account at once.
2. If a claim returns `null`, leave that slot empty. When every slot is empty, stop application work. A `null` can also mean the remaining queued jobs belong to companies in progress, so claim again for empty slots each time a worker finishes.
3. For each non-null claim, start a fresh worker with the required prompt and pass only the job ID, company, role, application URL, and the claim's `submit` value. Pass the URL, never an already opened tab: each worker opens and owns its own tab. Start the workers for all newly filled slots in one message, one Agent call each, so they run at the same time.
4. When a worker finishes, handle its result (steps 5–7), then claim for its slot again (step 1) and start the next worker, so at most `SLOTS` run at once. Do not stop a form worker merely because it is slow; stopping it can release or close its controlled tab. Do not touch a running worker's tab.
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
8. Claim the next job for the freed slot and repeat with a fresh worker.

For a `submitted` result, call:

```bash
python3 -m job_agent submit --job-id JOB_ID --worker-id daily-browser-worker-N --confirmation-url URL --evidence "CONFIRMATION_EVIDENCE" --resume-verified
```

For a `ready_for_review` result, call:

```bash
python3 -m job_agent complete --job-id JOB_ID --worker-id daily-browser-worker-N --review-url URL --resume-verified
```

For a `blocked` result, call:

```bash
python3 -m job_agent block --job-id JOB_ID --worker-id daily-browser-worker-N --category CATEGORY --message MESSAGE --review-url URL
```

Use the worker id of the slot that claimed the job. Reject malformed worker output and use SendMessage to ask the same worker to correct it before recording a result. Refill a slot only after its result is recorded and its live tab is preserved. Close a submitted application's tab once its result is recorded, since nothing is left to review there. Keep no more than five ready or blocked application tabs; close discovery and intermediate tabs.

### Application-worker concurrency

Application workers share one Chrome but nothing else they could clobber:

- Each worker opens its own tab and pins that `tabId` in every browser call, and passes a marker it puts in its own tab's title as agent-vault's `tab_hint`, so logins and sign-ups fill only its own tab.
- The résumé is attached with `file_upload`, which reads the file per call and targets one ref in one tab. The Local Resume Companion fallback keeps one queue entry per request under `attach-queue/` and hands each to the page whose URL matches it, so concurrent fallbacks do not overwrite each other.
- `claim` is atomic and skips companies that already have a claimed job, so two workers never share one company's account.

Keep `max_parallel_workers` small (2 by default, at most 3): every worker drives the same Chrome window, and a page's blocking alert or a slow site can stall the browser for all of them. If a run shows browser-tool timeouts or `connection lost` errors from two or more workers at once, set `max_parallel_workers` to 1 for the next run, which restores one-at-a-time processing, and add a to-do.

### 5. Analyze blockers and file to-dos

Run `python3 -m job_agent report --run-id RUN_ID` for this run's attempts and `python3 -m job_agent report` for the all-time rate. The submission rate is submitted attempts divided by all finished application attempts: every claim counts once, so a retried job counts as two attempts, and a ready_for_review, blocked or abandoned (stale-claim) attempt counts as not submitted. The all-time rate counts from `rate_counted_since` (the rate was reset on 2026-10-20). For every blocked job today, and for every `ready_for_review` that should have been submitted, decide the root cause from the worker's blocker message and evidence: authentication (which ATS or identity provider, which agent-vault status), ATS control or navigation, résumé upload, CAPTCHA or identity verification, submission rejected or unconfirmed, or infrastructure (Chrome, extension, agent-vault). Write the analysis to `artifacts/YYYY-MM-DD/retro.md`.

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

1. Run `python3 -m job_agent digest --run-id RUN_ID`. The body already includes the companies checked, postings scanned, the submission rate and blocker counts for this run. Append, as plain lines: the all-time submission rate from section 5, the root cause of each blocker and whether a to-do was filed (by ID), and the Gmail findings from section 6.
2. If the payload is `eligible`, send `email.subject` and `email.body` to exactly `email.to` with the Gmail `send_message` tool. Then acknowledge with `python3 -m job_agent digest --run-id RUN_ID --sent-key KEY`, or record failure with `--failed-key KEY`.
3. Run `python3 -m job_agent finish-run --run-id RUN_ID`.

## Required final report

Report companies checked, postings scanned, discovered, deduplicated, skipped, manual-attention, submitted, ready, blocked, and remaining queued counts, plus the submission rate (submitted attempts / application attempts) for this run and all time. List each manual-attention, submitted, ready, or blocked company and role; include the applicable company-policy document, the confirmation evidence for submissions, or the blocker and its root cause. List the to-dos filed (by ID) and the recruiter, interview, and rejection emails found. If `submit` was `false`, state that nothing was submitted.
