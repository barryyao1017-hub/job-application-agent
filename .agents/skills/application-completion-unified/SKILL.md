---
name: application-completion-unified
description: "Complete or verify exactly one current or supplied job application through its final pre-submit review state without submitting or running the full discovery pipeline. Use for an application-worker assignment, isolated worker-behavior check, recovery of one open application, or verification of a worker change against a current application tab or supplied application URL."
---

# Unified Application Completion

Operate on exactly one application and finish only at its final pre-submit review state or an allowed hard blocker.

## Non-negotiable boundaries

- Do not click the final **Submit**, **Submit Application**, or equivalent control during this workflow. Submission requires a separate explicit user instruction.
- Do not create an account, invent or solicit credentials or verification codes, expose secrets, or extend the authentication procedure.
- Use only the approved résumé and confirm its displayed filename before reporting the application ready.
- Preserve the live application tab and all committed progress as the review deliverable.
- Treat missing profile information as an inference task, not a blocker. Block only for authentication, CAPTCHA handoff failure, or an unavoidable technical barrier after supported recovery.

## 1. Load the source of truth

Before interacting with the browser, fully read [`../../../application-profile.md`](../../../application-profile.md). Treat it as authoritative for personal facts, approved answers, résumé location, education guidance, and review-stage inference defaults. Treat this skill as authoritative for application behavior, authentication, completion, blocking, and output.

Use the user's Chrome session and the current application tab or supplied application URL. Preserve a supplied `job_id` exactly; use `null` when an isolated run has no job ID.

## 2. Pass authentication gates

Use this procedure only when authentication is required to reach the application. Authentication never authorizes submission.

1. Check the company-login credentials cache available to the agent. Select at most one credential matching the employer or authentication origin, such as the matching Google credential when available, and attempt it once.
2. Only when no applicable cached credential exists, invoke Chrome's saved-login credential prompt. Use at most one matching saved login without revealing its secret, and attempt it once.

If an applicable cached credential fails, stop; do not continue to Chrome's prompt. If no applicable cached credential exists and Chrome's prompt is unavailable, offers no applicable credential, or fails, return `blocked` with `blocker_category: "login_credentials_unavailable"`.

Do not open registration, attempt account or credential recovery, inspect secrets, or try another authentication fallback. Preserve the tab and committed progress so a pipeline orchestrator can continue to the next application.

## 3. Traverse every application step

1. Identify the current step and the total or visible remaining steps.
2. Identify every required field on the step.
3. Fill each field from the profile or résumé. When neither supplies an answer, apply the profile's review-stage inference defaults and choose the closest accurate option.
4. Confirm every value is committed. Text present in an active search box, a highlighted option, or an open dropdown is not a committed answer.
5. Complete required acknowledgements, eligibility questions, and consent fields using the profile defaults.
6. Click **Next**, **Continue**, **Save and Continue**, or the equivalent non-submitting navigation control.
7. Verify that the application advanced to a different step, then repeat.
8. Revisit earlier steps when a review summary or validation sends the form backward.

Do not assume a form is single-page because only one page is initially visible. Workday, Cisco, and similar systems require traversal until the immediate final Submit control is visible. A visible step-navigation control proves the application is not ready.

Continue through later fields and pages when a low-consequence detail requires inference. Use the last calendar day when only a graduation month and year are known, choose the closest truthful listed option, and apply the profile's defaults for prior affiliation, start date, compensation, citizenship, government affiliation or identifiers, security clearance, criminal history, and legal or privacy acknowledgements. Never fabricate identifier digits. Legal wording alone is not a blocker.

## 4. Commit custom controls correctly

For embedded forms, operate on the dropdown and its options within the same iframe context:

1. Open the control and wait for the actual option list to become visible.
2. Inspect the visible options before selecting.
3. Select an exact visible option. Do not rely on typing and pressing Enter unless the site visibly confirms the intended value.
4. Close the menu and verify that the control displays the committed value.

If Data Science is absent from an education-discipline dropdown, select the closest truthful listed discipline, preferring Mathematics, Computer Science, Statistics/Decision Theory, or another related discipline before **Other**.

For years-of-experience dropdowns, select the complete visible range, such as `1 - 2 year(s)`, and verify that range afterward. Never type a bare number and press Enter; custom controls can retain an unintended default such as `0 years`.

### Greenhouse safeguards

Greenhouse can render React dropdowns inside an iframe while retaining hidden options from other controls:

1. Do not press **Enter** to commit a Greenhouse selection; it can trigger premature form validation.
2. Click the exact visible option. If a reliable click is unavailable, use arrow keys only after confirming the focused visible option, then press **Tab** to commit and close the menu.
3. Ignore hidden or zero-size options, including cached phone-country choices.
4. After the first required dropdown, verify the displayed value, confirm `aria-invalid` is not `true`, and check that no visible `This field is required` message appeared.
5. If premature validation appears, stop filling additional fields, reload, and complete a clean pass.

## 5. Attach and verify the résumé

Use Local Resume Companion; do not manually enter résumé content or attach a different file.

1. Queue the exact application-page URL with the extension's attachment helper.
2. Let the extension identify the required Résumé/CV upload field while excluding Cover Letter fields.
3. When multiple upload controls exist, target the explicitly required Résumé/CV field rather than an optional résumé-autofill field.
4. Verify that the form visibly displays the approved filename, `Jiayi_Yao_resume.docx`.
5. If the filename is absent, diagnose the field label or page-frame context and retry only when the extension can target the required field unambiguously.

If a site explicitly requires PDF, use an approved PDF derivative only when the profile or local configuration provides one. Never claim that a PDF was uploaded while a DOCX is attached.

## 6. Verify the final pre-submit state

Report `ready_for_review` only when all of the following are true:

- Every application page has been traversed.
- The final Submit control is visible and enabled, and clicking it would submit immediately.
- Every required field on every prior and current step has a committed value.
- Required acknowledgements, eligibility questions, and consent fields are selected.
- The approved résumé is visibly attached with the verified filename.
- No visible validation errors or blank required fields remain.

Review the completed form once more. Do not use the final Submit control to trigger or refresh validation.

## 7. Handle blockers and preserve the tab

The only allowed hard blockers are:

- Credentials unavailable after the strict two-step authentication procedure.
- A CAPTCHA that cannot be completed through the supported user handoff.
- A technical failure that remains after the supported recovery steps.

For either a ready application or a blocker:

1. Keep the application tab open with all committed progress intact.
2. Finalize browser tabs with the application tab explicitly kept; omit discovery, duplicate, and intermediate tabs.
3. Reclaim or reopen the application tab after an interruption or browser failure before returning.
4. Set `review_tab_preserved: true` only after the application tab has been kept successfully.

Do not close the application tab because a ledger result was recorded or an orchestrator is moving to another job. The live tab is the review deliverable.

## 8. Return the result

Return one lean JSON object and no screenshot or exhaustive answer manifest:

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

For a pipeline assignment, preserve the supplied `job_id` exactly. For an isolated run without a job ID, return `null`.
