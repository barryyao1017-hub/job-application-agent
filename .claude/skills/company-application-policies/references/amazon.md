# Amazon application policy

amazon.jobs refuses new applications while the account has ten active ones ("You've reached the maximum number of job applications", redirect to `summary?result=application_limit_reach`). Applications stay active until Amazon rejects them, fills the role, or the user withdraws them.

## Required actions

- Apply automatically, but only to roles with fit at or above `limited_company_minimum_fit_score` (90 by default): the ledger queues and claims nothing below it for a company with an application limit.
- A worker that hits the cap blocks with `blocker_category: "application_limit"`. Recording it with `block --category application_limit` keeps the job and Amazon's other jobs queued (deferred) and stops `claim` from handing out Amazon jobs until the limit is cleared.
- Ask the user to withdraw applications they no longer want in the amazon.jobs Application Dashboard. After they confirm, run `python3 -m job_agent clear-limit --company Amazon`.
- Report the deferred Amazon jobs in the run summary (`python3 -m job_agent limits`).
