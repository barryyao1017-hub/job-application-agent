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

To add a company, create one concise Markdown file in `references/` and add its exact company-name aliases, handling mode, document filename, and reason to `references/policies.json`.
