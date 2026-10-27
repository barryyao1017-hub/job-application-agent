---
name: company-application-policies
description: Apply documented company-specific safeguards and routing instructions during job discovery, scoring, application preparation, or application review. Use whenever a discovered or user-selected employer matches the company policy registry, before opening or delegating an application for that employer.
---

# Company Application Policies

Use the registry at `references/policies.json` to match normalized company names. Treat aliases as exact normalized names; do not use substring or speculative matching.

For every match:

1. Read the matched documentation file fully before taking company-specific action.
2. Follow its routing instruction before opening a form or assigning an application worker.
3. Keep the job in the discovery ledger even when automation is prohibited.
4. Treat company instructions as additional restrictions. Never use them to override the pipeline's privacy, truthfulness, résumé-verification, review-only, or no-submit boundaries.
5. Surface the policy match and the required user action in the run summary.

`manual_review` means: analyze and rank the role, preserve its canonical URL, and present it to the user. Never claim it for, or pass it to, an application worker.

`application_limit` means the company's site caps how many applications one account may send. The ledger queues and claims that company's jobs only at fit at or above `limited_company_minimum_fit_score` (config, default 90), so the cap goes to the best fits. A `max_submissions` within `window_days` is enforced from the ledger's own submissions; any other cap takes effect when a worker reports it (`block --category application_limit`), after which `claim` skips the company and its jobs stay queued until the limit expires or `clear-limit` lifts it. A company without a policy that reports a cap gets the same treatment.

`swap` (needs `application_limit.max_active`) lets the orchestrator free a slot itself: withdraw the weakest active application the ledger submitted for a queued job at least `min_fit_gain` fit points better, at most `max_withdrawals_per_run` a run. The policy document holds the site's swap procedure; nothing is ever withdrawn outside it.

To add a company, create one concise Markdown file in `references/` and add its exact company-name aliases, handling mode, document filename, reason, and any `application_limit` (`description`, optionally `max_submissions` and `window_days`) to `references/policies.json`.
