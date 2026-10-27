# Amazon application policy

amazon.jobs refuses new applications while the account has ten active ones ("You've reached the maximum number of job applications", redirect to `summary?result=application_limit_reach`). Applications stay active until Amazon rejects them (they move to the dashboard's Archived tab as "No longer under consideration", often within a few days), fills the role, or they are withdrawn. Archived applications do not count toward the ten.

## Required actions

- Apply automatically, but only to roles with fit at or above `limited_company_minimum_fit_score` (90 by default): the ledger queues and claims nothing below it for a company with an application limit.
- A worker that hits the cap blocks with `blocker_category: "application_limit"`. Recording it with `block --category application_limit` keeps the job and Amazon's other jobs queued (deferred) and stops `claim` from handing out Amazon jobs until the limit is cleared.
- The policy's `swap` lets the orchestrator withdraw a weaker active application for a queued job at least `min_fit_gain` (10) fit points better, at most `max_withdrawals_per_run` (2) per run. Follow "Swap procedure" below; never withdraw anything outside it.
- Report the deferred Amazon jobs in the run summary (`python3 -m job_agent limits`).

## Swap procedure

The orchestrator runs this before the claim loop when `submit_applications` is true and Amazon has queued jobs. Withdrawal is permanent: Amazon notifies the recruiting team, and an applicant reportedly cannot reapply to the same job afterwards (forum reports, not confirmed by Amazon). So every step below errs toward keeping an application.

1. In the agent's Chrome, open `https://account.amazon.jobs/en-US/applicant/dashboard/applications` and sign in with agent-vault if asked (account site `amazon.com`; it works on `passport.amazon.jobs`).
2. Read the active list from the page's own API with the browser's JavaScript tool, and save it as `artifacts/YYYY-MM-DD/amazon-active.json`:
   `(await (await fetch('/api/apply/applications/query_applications?application_group=ACTIVE')).json()).applications.map(a => ({ats_job_id: a.job_id, status: a.status, title: a.job.title}))`
   Every active application read `SUBMITTED` on 2026-10-27; rejected ones read `NO_LONGER_UNDER_CONSIDERATION` under `ARCHIVED`. Any status other than `SUBMITTED` means Amazon is acting on it, and the ledger never withdraws it.
3. Recruiter check: search Gmail (read-only, metadata) for `newer_than:60d (amazon OR aws) -subject:"thank you for applying"`. For each thread that is an interview, assessment, scheduling or recruiter message about one of the active applications (by job ID or title), pass that job ID to `--keep`. If Gmail is unavailable, skip the swap this run.
4. `python3 -m job_agent swap-plan --company Amazon --active-file artifacts/YYYY-MM-DD/amazon-active.json --keep IDS --run-id RUN_ID`. Applications the ledger did not submit hold their slots.
   - `free_slots` above 0: rejections have freed room. Run `python3 -m job_agent clear-limit --company Amazon` and withdraw nothing.
   - Empty `pairs`: nothing is worth swapping. Leave the cap in place.
5. Take only the first pair. Open the replacement's job page, `https://www.amazon.jobs/en/jobs/<replacement ats_job_id>`, and confirm it still takes applications (an Apply button, no "not taking new applications" notice). If not, stop the swap for this run.
6. On the dashboard, click the Withdraw link whose label ends `and ID <withdraw ats_job_id>`, check the dialog names that same title and ID, then click its "Withdraw application" button. Read the ACTIVE list again: the ID must be gone. Record it with `python3 -m job_agent withdraw --job-id <withdraw job id> --replacement-job-id <replacement job id> --evidence "<ID> left the Active list after Withdraw" --run-id RUN_ID`, which also lifts the reported cap.
7. Claim as usual. `claim` hands out the highest-fit queued job, which is the replacement. Start the second pair only after the replacement comes back `submitted`, repeating steps 2 to 6 (the active list has changed). If the replacement is blocked, stop swapping for this run and add a to-do with the blocker.
