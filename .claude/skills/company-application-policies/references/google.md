# Google application policy

Google Careers (google.com/about/careers) is discovered by `fetch-feeds` (`ats: google`) and applied to automatically, like any other company. The user allows at most three Google applications in a rolling 30-day window, and Google refuses a second application to the same job within 90 days.

## Required actions

- Apply automatically, but only to roles with fit at or above `limited_company_minimum_fit_score` (90 by default). The target is L4: Software Engineer III, or an untitled role Google tags Mid. Discovery already drops Senior, Staff, Principal, PhD and early-career titles.
- Every Google job gets a résumé tailored to the posting and a résumé-vs-posting screenshot before it is claimed (`tailor_resume` in the policy; the pipeline skill's tailoring step).
- The ledger enforces the window: `claim` skips Google once three submissions in the last 30 days are on record, and its queued jobs stay queued (deferred) until the oldest one ages out. The ledger never re-applies to a job it submitted.
- The user also applies by hand. Before claiming a Google job in a run, the orchestrator opens the applications dashboard (https://www.google.com/about/careers/applications/dashboard) in the agent's Chrome, signed in as barrryyao@gmail.com (three r's), and records every submitted application from the last 30 days that the ledger lacks with `record-applied --url <posting URL> --company Google --title <title> --submitted-at <date> --evidence "Google Careers dashboard"`. Drafts do not count. If the dashboard cannot be read, say so in the report and rely on the ledger.
- If a worker still hits the limit, it blocks with `blocker_category: "application_limit"`; record it with `block --category application_limit --until <date the oldest application in the window plus 30 days>`.
- Form procedure: `application-completion/references/google.md`.
