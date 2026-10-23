# SmartRecruiters playbook

Reference notes for the application worker. `.claude/skills/application-completion/SKILL.md` is authoritative; where this file seems to disagree, follow the skill. Evidence: Arista and SAP (ready for review, 2026-10-18) and the ServiceNow `file_upload` trial (2026-10-18). Nothing has been submitted on SmartRecruiters yet.

## Recognize it

- Job page: `jobs.smartrecruiters.com/<Company>/<id>-<slug>` (2026-10-18).
- "I'm interested" opens the Easy Apply form at `jobs.smartrecruiters.com/oneclick-ui/company/<Company>/publication/<uuid>`. It has a later `/screening` step, which is where both observed applications stopped at Review (2026-10-18).

## Sign-in and accounts

- Neither the Arista nor the SAP application needed sign-in or an account (2026-10-18).

## Form traversal and controls

- Both applications reached Review in 2–3 minutes. Traverse past the screening questions; the first page is not the final step (2026-10-18).

## Résumé field

- The tools cannot see the real résumé input. The accessibility tree shows only a "Resume" heading, and `file_upload` on that heading fails with "Element is not a file input" (2026-10-18).
- The input sits inside the open shadow root of `spl-dropzone[data-test="resume-upload"]`. Use the skill's workaround (section 5 step 5; scripts in `RESUME_FILE_UPLOAD_TRIAL.md`):
  1. Move that input into the light DOM.
  2. Run `find` for "Resume file input (relocated)" and call `file_upload` on that ref.
  3. Move the input back and clear the attributes you added.

  The component keeps its change listener on the moved input (2026-10-18).
- Never use the `apply-with-resume-container` dropzone; it is an optional autofill (2026-10-18).
- The filename shows only inside the dropzone's shadow root, so `get_page_text` will not show it. Verify by reading the shadow root with `javascript_tool` or by taking a screenshot (2026-10-18).

## Limits and known failures

- None recorded beyond the hidden input. Per-account caps and already-applied warnings are unknown.

## Confirmation

- Unknown: no SmartRecruiters application has been submitted. Use the skill's generic confirmation rules (section 7).
