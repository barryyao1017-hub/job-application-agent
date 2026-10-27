---
name: application-completion
description: "Complete exactly one current or supplied job application through its final pre-submit review state and, when the assignment says `submit: true`, submit it and confirm receipt, without running the full discovery pipeline. Use for an application-worker assignment, isolated worker-behavior check, recovery of one open application, or verification of a worker change against a current application tab or supplied application URL."
---

# Application Completion

Operate on exactly one application and finish at a confirmed submission (when the assignment says `submit: true`), at its final pre-submit review state (otherwise), or at an allowed hard blocker.

## Non-negotiable boundaries

- Click the final **Submit**, **Submit Application**, or equivalent control only when the assignment explicitly says `submit: true` and every check in section 6 passes, following section 7. Without `submit: true` (for example an isolated verification run), stop at the final pre-submit state. Never click Submit to trigger or refresh validation, and never click it a second time for the same application.
- When the user explicitly invokes this skill for a job application, that invocation is the user's standing advance authorization to enter and upload the user's approved application-profile information, contact and professional information, and approved résumé (or the résumé PDF tailored to this posting from it) to the specific application site being processed and, when the assignment says `submit: true`, to submit that one application. This authorization does not override any mandatory browser or platform action-time confirmation policy; comply with any confirmation the active browser runtime requires.
- Create an account only through agent-vault's `register` tool as described in section 2. Never invent, type, or solicit credentials or verification codes, open a verification email or link yourself, expose secrets, or extend the authentication procedure.
- Use only the résumé the assignment names (`resume_path`: a PDF tailored to this posting, or the approved résumé) and confirm its displayed filename before reporting the application ready.
- Preserve the live application tab and all committed progress as the review deliverable.
- Treat missing profile information as an inference task, not a blocker. Block only for authentication, CAPTCHA handoff failure, or an unavoidable technical barrier after supported recovery.

## 1. Load the source of truth

Before interacting with the browser, fully read [`../../../application-profile.md`](../../../application-profile.md). Treat it as authoritative for personal facts, approved answers, résumé location, education guidance, and review-stage inference defaults. Treat this skill as authoritative for application behavior, authentication, completion, blocking, and output.

Use the user's Chrome session through the Claude in Chrome tools (`mcp__claude-in-chrome__*`; load them with ToolSearch if they are deferred) and the current application tab or supplied application URL. Other application workers may be running in the same Chrome at the same time. Given a URL, open it in a new tab of your own with `tabs_create_mcp` and note that tab's `tabId`; given an opened tab, that tab is yours. Pass your own `tabId` in every browser call, and never read, navigate, or close a tab you did not open. Run shell commands from the repository root. Preserve a supplied `job_id` exactly; use `null` when an isolated run has no job ID.

Right after opening your tab, call `tabs_context_mcp` and note its tab group along with your `tabId`. Call it again before each step's actions (filling a page, uploading, clicking **Next**) and immediately before the final Submit, and check that your tab still shows your company's site; once you have set your `jobtab-` marker (section 2), check that the title still carries it, setting it again after a page load. If your `tabId` is gone, now sits in a different tab group, or shows another company's application, stop: do not refill the form in another tab and do not click anything, since with several workers in one Chrome a click could land in another worker's application. Return `blocked` with `blocker_category: "technical_failure"` and `blocker_message` "tab group changed", naming the old and new group in `blocker_evidence`.

Once you know which applicant tracking system the application runs on, read its playbook in [`references/`](references/) if one exists (`workday.md`, `greenhouse.md`, `ashby.md`, `lever.md`, `icims.md`, `smartrecruiters.md`, `successfactors.md`, `amazon.md`, `google.md`). Playbooks record what earlier runs observed on that ATS; where one disagrees with this skill, this skill wins.

## 2. Pass authentication gates

Use this procedure only when authentication is required to reach the application. Authentication never authorizes submission.

1. If the site already recognizes an existing signed-in session in the user's Chrome, such as an active Google account offered through **Continue with Google**, use that session once. This is not a credential entry; do not type a password.
2. Otherwise, use the agent-vault MCP server (`mcp__agent-vault__*`; load with ToolSearch if deferred). It fills the login form and any authenticator or emailed one-time code itself; you never see or type a secret. Pass `tab_hint` on every `login`, `register`, `verify_email`, and `add_site_domain` call, set to a marker only your tab carries: `jobtab-` plus the first 8 characters of the `job_id` (or of a random UUID for an isolated run). Right before each call, put the marker in your tab's title with `javascript_tool` on your `tabId`: `if (!document.title.includes('MARKER')) document.title = 'MARKER ' + document.title`, since a page load or redirect resets the title. agent-vault picks the first tab whose URL or title contains the hint. Without one it acts on whichever tab is visible in any window, and a hostname or URL can also match another worker's tab or a tab preserved from an earlier attempt at the same job; either way it can fill another tab's form or return misleading `account_exists` or `no_login_form` results. If the status message says no tab matched, set the title again and retry once.
   1. Call `list_accounts` and pick the account whose `site_host` is the login page's hostname (on `myworkdaysite.com`, hostname plus `/recruiting/<company>` from the URL, such as `wd1.myworkdaysite.com/recruiting/snapchat`). On multi-company platforms (`myworkdayjobs.com`, `icims.com`, `taleo.net`, `oraclecloud.com`, `successfactors.com`) only an exact `site_host` match counts, because each company has its own account: an `nvidia.wd5.myworkdayjobs.com` login does not work on `amazon.wd5.myworkdayjobs.com`. Elsewhere, a matching `site_domain` is enough. If none matches, go to step 3.
   2. With the login page (username/password form, choosing **Sign in with email** or equivalent if the site offers several methods) open in the application tab, call `login(account_id)` once and act on its status:
      - `ok`: confirm the page is signed in before continuing: the application step or the candidate home shows, not a **Sign In** form or button. If it still shows sign-in, the single-page app may not have picked up the session: navigate your tab to the application URL again (no form progress exists yet to lose), wait for it to settle, and check again. If it is still signed out, call `login` once more, then reload once more. Only then block with `login_credentials_unavailable`, putting "login returned ok but the page stayed signed out" in `blocker_message`.
      - `origin_mismatch` while on the company's real login page on another domain: call `add_site_domain(account_id)` once, then retry `login` once if it returns `ok`.
      - `no_login_form`: navigate to the site's sign-in form and retry once.
      - `error` "Still on a login form after submitting" on Workday: treat it like an `ok` that stayed signed out (the steps above), once, before blocking.
      - `needs_approval`, `denied`, `2fa_unsupported`, or `error`: stop and block with `blocker_category: "login_credentials_unavailable"`, putting the status and message in `blocker_message`. For `error`, also run `uv --directory /Users/jiayiyao/Desktop/agent-vault run agent-vault doctor` and include its summary; its "BW_SESSION not set in this shell" line is about the worker's shell, not the MCP server, so don't report it as a locked vault. Exception: when the `error` says agent-vault could not connect to Chrome or the connection timed out, a frozen background tab or too many open tabs is the usual cause. First run `node scripts/wake-frozen-tabs.mjs`, which activates tabs Chrome froze without reloading them. Then close the intermediate, duplicate, and verification tabs you opened yourself (never your application tab or another worker's), count the remaining tabs with `curl -s localhost:9222/json/list`, and retry the same call once. If it fails again, block with `technical_failure` and put the tab count in `blocker_evidence`.
3. Otherwise, use Chrome's saved-login autofill for the authentication origin. Use at most one matching saved login without revealing its secret, and attempt it once.
4. Otherwise, if the site offers account creation (**Create Account**, **Sign Up**, **Register**), create the account with agent-vault. It fills the configured email and a generated password, saves the login to Bitwarden before submitting, and opens verification links itself.

   An account that the careers site's own sign-in or **Create Account** link leads to counts as the site's account, even when it lives on the employer's identity domain and is valid across the employer's other services: an IBMid (`login.ibm.com`), an Oracle account, an SAP ID, and the like. Create it with `register` exactly as below; do not decline it for being a general company account. This does not extend to third-party sign-in (**Continue with Google**, LinkedIn, or any OAuth consent screen): never grant a consent screen, and use such a button only for an already signed-in session as in step 1. An Apple Account (`idmsa.apple.com`) is the exception: signing up needs an image CAPTCHA, so block with `login_credentials_unavailable` and name `idmsa.apple.com` instead of calling `register`.
   1. Open the site's create-account page in the application tab.
   2. Fill every field that is neither the email nor a password from the profile, such as first and last name, country, phone, and the terms or privacy consent box. Leave the email and password fields empty for agent-vault.
   3. Call `register()` once and act on its status:
      - `ok`: if the site now shows a sign-in form, call `login(account_id)` once with the account id from the message, handling its status as in step 2. Then continue the application.
      - `verify_email`: call `verify_email(account_id)` once. It waits for the email, opens the link in a separate tab, and leaves the application tab alone. On `ok`, return to the application tab, open the sign-in page if the site asks, and call `login(account_id)` once as in step 2.
      - `account_exists` naming a vault account: sign in with that account as in step 2.
      - `account_exists` because the site says the email is already registered: stop. agent-vault does not know that password.
      - `no_signup_form`: open the create-account page, not the sign-in page, and retry once.
      - `signup_rejected`: fix the fields the message names, then call `register()` once more.
      - `needs_approval`, `denied`, `origin_mismatch`, or `error`: stop, as in step 2.
   4. `verify_email` returning `not_found` or `error` also stops.

If no path is available or the attempts fail, stop and return `blocked` with `blocker_category: "login_credentials_unavailable"`, putting the last agent-vault status and message in `blocker_message`. When the site offers no account creation (for example, sign-in only through a company SSO), name the exact login domain in `blocker_message` so the user can add a login for it to the Bitwarden folder "agent". Never type a password or code yourself; agent-vault is the only credential source.

Do not attempt account or credential recovery, read verification emails, inspect secrets, or try another authentication fallback. Preserve the tab and committed progress so a pipeline orchestrator can continue to the next application.

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
5. Confirm the committed value from the DOM, never from a screenshot alone: read the control with `read_page`, `find`, or `javascript_tool` (the input's `value`, the selected option, `aria-checked`, or the control's displayed text). Screenshots can lag the page by several seconds, especially while other workers share the browser, and a lagging screenshot has shown the wrong option as selected. If the DOM disagrees with what you intended, fix it before moving on.

Step 5 applies to every dropdown, radio group, checkbox, and yes/no question, including demographic, attestation, and work-authorization answers.

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

Attach the approved résumé with `mcp__claude-in-chrome__file_upload`; do not manually enter résumé content or attach a different file. Local Resume Companion is the fallback, used only after the steps below fail.

The assignment's `resume_path` names the file: a PDF tailored to this posting (under `artifacts/`) for strong fits and Google, otherwise the approved résumé. Without a `resume_path`, Read `approved_resume_path` from `config.json`. Pass that path as `paths`. `file_upload` reads only paths this session may read, so the file must live inside the repository (the configured default is `<repo>/data/Jiayi_Yao_resume.docx`; `data/` is gitignored) or in a directory added with `--add-dir`. The fallback's native host reads the same path.

1. Suppress page-generated informational alerts in the application tab with `mcp__claude-in-chrome__javascript_tool`, for example `window.alert = (m) => console.log('[suppressed alert]', m)`. A native JavaScript dialog blocks the Claude in Chrome extension until a person dismisses it, so prevention matters more than recovery. Do not override `confirm` or `prompt`.
2. Locate and upload back to back: run `find` ("required Résumé/CV file input"), then `file_upload` with that ref, this worker's own `tabId`, and `paths: ["<resume_path>"]`, in one `browser_batch` where possible. A ref from `find` can go stale within seconds on pages that re-render, so put no other action or reasoning step between the two calls. Every call in this section pins the worker's own `tabId`; never act on another tab.
3. Choose only the required Résumé/CV input, keeping the extension's field-selection rules: never a Cover Letter input; on Ashby never the "(Autofill from resume)" input, the required one is `input#_systemfield_resume`; on SmartRecruiters never the `apply-with-resume-container` dropzone. When `find` returns several file inputs, pick by the visible label and confirm the chosen ref is a file input before uploading.
4. If `file_upload` fails with "Element is no longer in the document", re-run `find` and `file_upload` once, back to back.
5. If `find` returns no file input, the control is hidden from the accessibility tree. Surface it, then return to step 2:
   - SmartRecruiters (`jobs.smartrecruiters.com`): the input is inside the open shadow root of `spl-dropzone[data-test="resume-upload"]`. With `javascript_tool`, move that input into the light DOM (scripts in `RESUME_FILE_UPLOAD_TRIAL.md`: give it `aria-label` "Resume file input (relocated)" and append it to `document.body` with a fixed, near-transparent style), `find` it by that label, upload, then move it back and clear the attributes.
   - Greenhouse embedded in a company careers page (`iframe#grnhse_iframe`): the form is a cross-origin iframe the tools cannot see into. With `javascript_tool`, set `location.href` to that iframe's `src` so the same tab shows the standalone `job-boards.greenhouse.io/embed/job_app` form, and continue the whole application there. Never write that URL into results, logs, or the ledger; it carries a token.
6. Fall back to Local Resume Companion only when no file input is findable or surfaceable, or `file_upload` has errored twice: queue the exact page or frame document URL with `node local-resume-companion-extension/enqueue-attach.js "APPLICATION_URL"` and let the extension identify the required Résumé/CV field, excluding Cover Letter and optional autofill fields. Each enqueue adds its own entry to `attach-queue/`, and the native host hands the approved résumé (never a tailored PDF) only to a page whose URL contains a queued URL, consuming that one entry; entries expire after 30 minutes. So other workers' fallbacks cannot overwrite yours, but queue your own tab's exact URL, never a shorter prefix another worker's page could also match. Verify the filename immediately; if you give up while your entry may still be queued, say so in `blocker_evidence`.
7. Treat upload completion as an asynchronous page transition. Wait briefly, then read the page state; never wait indefinitely.
8. Verify that the form visibly displays the attached file's name (`Jiayi_Yao_resume.docx` for the approved résumé, `Jiayi_Yao_resume.pdf` for a tailored one) after handling any dialog. If the fallback attached the approved résumé in place of a tailored PDF, say so in `blocker_evidence`. On SmartRecruiters the filename is rendered inside the dropzone's shadow root, so read that shadow root's text with `javascript_tool` or take a screenshot; `get_page_text` does not show it. Report `resume_verified: true` only then.
9. If the filename is absent, re-run `find`, confirm the ref is still the required input, and upload once more. Do not upload again while the filename is visible; this avoids duplicate uploads.

Some sites, including Adobe's observed application flow, can display a delayed blocking success alert after the file input receives the file and change events. The page creates this alert; neither `file_upload` nor Local Resume Companion does. A prior controlled tab can still appear stalled if the alert opens while another browser operation is pending. This timing explanation is a suspected failure mode, not a proven root cause.

If a browser operation stalls immediately after attachment despite the suppression, assume a native dialog is open. In an unattended run nobody can dismiss it: wait up to two minutes, retry once, and if the browser tools still do not respond return `blocked` with `blocker_category: "technical_failure"` and evidence `suspected blocking dialog`. When the browser responds again, reclaim or reopen the same application tab, verify the filename and committed form state, and continue. Do not upload or queue the résumé again unless the verified filename is absent.

If the résumé input accepts only PDF (its `accept` attribute leaves out `.docx`, or the page rejects the DOCX with an "only pdf" message) and `resume_path` is the DOCX, upload the assignment's `resume_pdf_path` instead, following the same steps, and verify its filename. `resume_pdf_path` is a PDF of the approved résumé the user approved; when it is `null`, block with `technical_failure` and "PDF-only résumé field" in `blocker_message`. Never claim that a PDF was uploaded while a DOCX is attached.

## 6. Verify the final pre-submit state

Report `ready_for_review` only when all of the following are true:

- Every application page has been traversed.
- The final Submit control is visible and enabled, and clicking it would submit immediately.
- Every required field on every prior and current step has a committed value.
- Required acknowledgements, eligibility questions, and consent fields are selected.
- The assigned résumé (`resume_path`) is visibly attached with the verified filename.
- No visible validation errors or blank required fields remain.

Before relying on that last check, scan the current step for required fields programmatically, not only by eye. With `javascript_tool` on your `tabId` (inside the form's frame), list the inputs, selects, and textareas that are `required`, `aria-required="true"`, or whose label carries a required marker (a trailing `*`, "(required)", Ashby's and Greenhouse's asterisks, Workday's `*` and `data-automation-id` required labels), and report which are empty or unchecked. Fill each empty one from the profile or résumé, or with its inference defaults; a required free-text field the profile does not cover (for example a GitHub or portfolio URL) gets the profile's value if it has one, otherwise a truthful "N/A". Repeat the scan until it reports nothing empty.

Some required fields need something only the user can make: a shared link to a thread or document they create, a take-home or exercise submission, a work sample, or a URL the page validates and rejects "N/A" for. Never invent one. Leave the rest of the form filled, keep the tab, and return `blocked` with `blocker_category: "unanswerable_required_field"`, the field's label in `blocker_message`, and what it asks for in `blocker_evidence`.

Review the completed form once more. Do not use the final Submit control to trigger or refresh validation.

## 7. Submit and confirm (only with `submit: true`)

Skip this section unless the assignment says `submit: true`. Before clicking Submit, review the completed answers once more and stop at `ready_for_review` instead of submitting when any of these is true:

- An answer contradicts `application-profile.md` or the résumé.
- The form asks for a government identifier number, payment, a background-check authorization beyond a standard acknowledgement, or identity verification such as an ID photo or selfie.
- The site warns that you have already applied to this role.

If the site refuses because the account reached an application cap (for example amazon.jobs's "You've reached the maximum number of job applications" or an Ashby board's "applied ... within the last 90 days" or "limiting applications"), whether before the form or after Submit, return `blocked` with `blocker_category: "application_limit"`, the site's wording in `blocker_message`, and, when the page says when the limit ends, that date in `blocker_evidence`. Do not try another role at the same company.

Otherwise, run the required-field scan from section 6 one last time, then:

1. Click the immediate final Submit control exactly once.
2. Wait for the page to settle, then read it. A confirmation is visible on-page text or a status such as "Thank you for applying", "Application submitted", "We received your application", or the role listed as Submitted/Under review in the candidate portal. Record a short quote of it as `confirmation_evidence`.
3. If Submit instead reveals validation errors, fix the named fields and click Submit once more only after every error is cleared; this counts as the same submission attempt because the first click was rejected. Stop after that second rejection.
4. If a post-submit page asks optional questions (voluntary surveys, talent-community sign-up), leave them; the application is already in.
5. If the result is ambiguous (a spinner, a generic page, a crash), do not click Submit again. Check the candidate portal or the role's page for an "Applied" state; if it still cannot be confirmed, block with `submission_unconfirmed`.

Return `submitted` only with visible confirmation evidence. A rejected submission that could not be fixed returns `blocked` with `blocker_category: "submission_rejected"` and the site's error text in `blocker_evidence`.

## 8. Handle blockers and preserve the tab

The only allowed hard blockers are:

- Credentials unavailable after the authentication procedure (existing session, agent-vault login, saved login, agent-vault account creation).
- A CAPTCHA that cannot be completed through the supported user handoff.
- A technical failure that remains after the supported recovery steps.
- Identity verification (ID photo, selfie) the user must complete in person: `identity_verification_required`.
- A submission that was rejected or cannot be confirmed (section 7): `submission_rejected` or `submission_unconfirmed`.
- The account reached the site's application cap (section 7): `application_limit`.
- The tab group changed under you (section 1): `technical_failure`.
- A required field needs something only the user can create (section 6): `unanswerable_required_field`.

For a submitted or ready application, or a blocker:

1. Keep the application tab open with all committed progress intact.
2. Finalize browser tabs with the application tab explicitly kept; close only discovery, duplicate, and intermediate tabs you opened yourself.
3. Reclaim or reopen the application tab after an interruption or browser failure before returning.
4. Set `review_tab_preserved: true` only after the application tab has been kept successfully.

Do not close the application tab because a ledger result was recorded or an orchestrator is moving to another job. The live tab is the review deliverable.

## 9. Return the result

Return one lean JSON object and no screenshot or exhaustive answer manifest:

```json
{
  "status": "submitted, ready_for_review, or blocked",
  "job_id": "supplied job ID or null",
  "review_url": "URL",
  "resume_verified": true,
  "review_tab_preserved": true,
  "confirmation_evidence": "Short quote of the on-page confirmation, or null",
  "blocker_category": "CATEGORY or null",
  "blocker_message": "MESSAGE or null",
  "blocker_evidence": "Concise evidence or null"
}
```

Set `resume_verified` from the actual visible state. A `submitted` result requires `resume_verified: true`, non-null `confirmation_evidence`, and null blocker fields; `review_url` is the confirmation page URL. A `ready_for_review` result requires `resume_verified: true` and null blocker fields. A `blocked` result may report `true` or `false` according to progress and must include a non-null blocker category and message.

For a pipeline assignment, preserve the supplied `job_id` exactly. For an isolated run without a job ID, return `null`.
