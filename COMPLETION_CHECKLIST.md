# Application Agent Completion Checklist

Use this checklist for every job application before reporting that it is complete or ready for review.

## Definition of complete

An application is complete only when the worker has traversed every application page or step and reached the final pre-submit state:

- The final **Submit**, **Submit Application**, or equivalent button is visible.
- Clicking that button would submit the application immediately.
- Every required field on every prior and current step has a committed value.
- The approved résumé is visibly attached.
- No visible validation errors remain.

Seeing a **Next**, **Continue**, **Save and Continue**, or step-navigation control is proof that the application is not complete. Do not return a ready result from an intermediate page. Never click the final Submit button without explicit user instruction.

## Multi-page traversal

1. Identify the current step and the total or visible remaining steps.
2. Fill and verify every required field on the current step.
3. Click **Next**, **Continue**, or the equivalent non-submitting navigation control.
4. Verify that the application advanced to a different step before continuing.
5. Repeat until the final Submit button is visible.
6. Revisit prior steps when the site exposes a review summary or when validation sends the form backward.

Do not assume a form is single-page because only one page is initially visible. On Workday, Cisco, and similar systems, continue through all steps until the final Submit control is present.

## Strict completion check

1. Identify every field marked required by the application.
2. Verify that every required field has a committed value, not merely text typed into a search box or dropdown.
   - For dropdowns, select an actual listed option and confirm the selected value is displayed after the menu closes.
   - Do not assume a value was saved because it is visible while the control is active.
3. Confirm the approved résumé is attached and that its displayed filename matches the approved local résumé.
4. Check that required acknowledgements, eligibility questions, and consent fields are selected.
5. Review the completed form once more for visible required-field errors or blank required fields.
6. Confirm the final Submit control is visible and enabled, but do not click it.

## Résumé attachment procedure

Use the Local Resume Companion Chrome extension for résumé uploads. Do not manually enter résumé content or attach a different file.

1. Queue the exact application document URL with the extension's attachment helper. For competing upload controls, use `enqueue-attach.js 'DOCUMENT_URL' --tab-id TAB_ID --frame-id FRAME_ID --selector 'CSS_SELECTOR'` after inspecting the intended field. Chrome frame 0 is the top-level document; use the companion popup for frame IDs and URLs. Optional `--shadow-hosts` takes a JSON array of open-shadow-host selectors from outermost to innermost.
2. Automatic mode identifies the Résumé/CV field and excludes Cover Letter. Explicit mode uses only the selected unique enabled file input in the specified tab/frame, with no fallback if the target fails.
3. On sites with more than one upload control, ensure the extension targets the explicitly required Résumé/CV field—not an optional autofill-from-résumé field.
4. Verify that the form visibly displays the approved résumé filename, `Jiayi_Yao_resume.docx`, after attachment.
5. If the filename is not displayed, do not report the application as complete. Diagnose the field labeling or page-frame context, then retry only after the extension can unambiguously target the required résumé field.

## Embedded forms and custom dropdowns

Some application forms are embedded in an iframe and use custom dropdowns. Treat the iframe as the form context for both the dropdown and its options.

1. Open the dropdown from the embedded form context.
2. Wait until the actual list of options is visible and inspect it before selecting anything.
3. Select one exact, visible option from that same embedded form context. Do not rely on typing text and pressing Enter unless the site visibly confirms that exact option.
4. After the menu closes, verify the control displays the committed selected value. Do not accept an active search term, a highlighted option, or a default value as a committed answer.
5. If the exact education discipline is absent, select the closest truthful listed discipline. For a Data Science degree, prefer Mathematics, Computer Science, Statistics/Decision Theory, or another truthful related discipline before choosing Other.
6. For years-of-experience dropdowns, never type a bare number and press Enter. Custom controls can match or retain an unintended default such as `0 years`. Instead, select the full visible range (for example, `1 - 2 year(s)`) and verify that exact range is displayed afterward.

### Greenhouse custom-dropdown safeguards

Greenhouse applications can render React-based dropdowns inside an embedded iframe while retaining hidden options from other controls in the DOM.

1. Never press **Enter** to commit a Greenhouse dropdown selection. The key event can bubble to the form and trigger premature validation, leaving stale required-field errors even when selected values are displayed.
2. Prefer clicking the exact visible option. If a reliable click is unavailable, use arrow keys only after confirming the focused option in the visible menu, then press **Tab** to commit it and close the menu.
3. Target only options with visible on-screen bounds. Ignore hidden or zero-size options, including cached phone-country choices from other dropdowns.
4. After the first required dropdown, immediately verify that the intended value is displayed, `aria-invalid` is not `true`, and no visible `This field is required` message appeared.
5. If premature validation errors appear, stop filling additional fields. Reload and complete a clean pass before proceeding; never click the final Submit control merely to refresh validation.

## Handling incomplete profile information

When the profile does not explicitly answer a question, use the review-stage inference defaults in `application-profile.md`. The user reviews all inferred values before submission, so a missing low-consequence detail is not itself a blocker.

- Choose the closest accurate option when the form’s choices do not exactly match the profile.
- Use the last calendar day when only a graduation month and year are known.
- Default prior employment, prior internship/contractor status, prior employee ID/email, and prior application questions for a named company to **No** when no affiliation appears in the profile or résumé.
- Use the profile’s approved start-date and compensation defaults when those fields are required.
- Answer U.S. citizenship **No**, government affiliation **No/None**, security clearance **No/None**, and criminal history **No**.
- Select **No/None/Not applicable** for government-identifier questions when available; never fabricate identifier digits.
- Complete required legal and privacy acknowledgements using the profile defaults. Do not block merely because the wording is legal.
- Do not create an exhaustive answer manifest. The user reviews inferred values directly in the preserved application before submission.
- Continue filling all later fields and pages. Do not stop at the first uncertain question.

Do not block on citizenship, government affiliation, security clearance, criminal history, or legal acknowledgements. At an authentication gate, follow `.agents/skills/job-application-pipeline/references/login-gates.md` exactly. It checks cached credentials and Chrome saved logins first, then permits account creation using the connected agent-specific mailbox when neither offers applicable credentials. Email verification is authorized for existing logins and new accounts; follow the reference for mailbox identification, secure passwords, and bounded verification attempts.

Block only for authentication or an unavoidable technical barrier:

- Authentication unavailable after the authorized saved-login and agent-mailbox procedure.
- CAPTCHA that cannot be completed through the supported user handoff.
- A technical failure that remains after the skill’s supported recovery steps.

If a site explicitly requires PDF, use an approved PDF derivative of the approved résumé only when the profile or local configuration provides one. Never certify that a PDF was uploaded while a DOCX is attached.

## Preserve the live application

The live browser tab is the review deliverable. Do not create a mandatory screenshot or answer manifest that duplicates it.

1. For a ready application, keep the completed tab open as a deliverable.
2. For an unresolved hard blocker, keep the tab open as a handoff with all committed progress intact.
3. Before returning, finalize browser tabs with the application tab explicitly kept. Omit discovery, duplicate, and intermediate tabs.
4. Return `review_tab_preserved: true` only after the tab has been kept successfully.
5. If interrupted or recovering from a browser failure, preserve or reclaim the application tab before returning.
6. Never close a completed or blocked application tab merely because the ledger result was recorded or the orchestrator is moving to another job.

## Submission rule

Never submit the application unless the user explicitly instructs you to submit it. Leave the final pre-submit page open. A ready result means the user can review the page and click Submit without completing another field or visiting another step.
