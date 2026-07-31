---
name: application-completion
description: "Complete or verify exactly one job application through its final pre-submit review state without submitting and without running the full discovery or application pipeline. Use for an application-worker assignment, an isolated worker-behavior check, recovery of one open application, or quick verification of a worker tweak against a current application tab or supplied application URL."
---

# Application Completion

Operate on exactly one current or supplied job application.

## Required sources

Before interacting with the browser, fully read:

- [`../../../application-profile.md`](../../../application-profile.md) for approved answers and review-stage inference defaults.
- [`../../../COMPLETION_CHECKLIST.md`](../../../COMPLETION_CHECKLIST.md) for form traversal, résumé verification, completion criteria, tab preservation, and submission boundaries.
- [`../../../.codex/skills/job-application-pipeline/references/login-gates.md`](../../../.codex/skills/job-application-pipeline/references/login-gates.md) for the strict authentication policy.

Treat those files as authoritative. The login-gate reference controls authentication; the profile and completion checklist control application answers and completion.

## Workflow

1. Use the user's Chrome session and the current application tab or supplied application URL.
2. Apply the profile defaults and traverse every page described by the completion checklist.
3. Use Local Resume Companion for the approved résumé and visibly verify its filename.
4. At a login gate, follow the required two-step login reference exactly. Do not create an account or add a fallback.
5. Stop only at the final pre-submit state or an allowed hard blocker. Never click the final Submit control.
6. Preserve the live application tab before returning.

## Result

Return one lean JSON object:

```json
{
  "status": "ready_for_review or blocked",
  "job_id": "supplied job ID or null",
  "review_url": "URL",
  "resume_verified": true,
  "review_tab_preserved": true,
  "blocker_category": "CATEGORY or null",
  "blocker_message": "MESSAGE or null",
  "blocker_evidence": "Concise evidence or null"
}
```

For a pipeline assignment, preserve the supplied `job_id` exactly. For an isolated run without a job ID, return `null`. Do not produce a screenshot or exhaustive answer manifest.
