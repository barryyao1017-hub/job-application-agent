# Google Careers playbook

Reference notes for the application worker. `.claude/skills/application-completion/SKILL.md` is authoritative; where this file seems to disagree, follow the skill.

Observed by the weekly Google bot (scheduled task `google-ml-application-cycle`, Oct 2026) before Google moved into this pipeline.

## Account and sign-in

- Apply through the Google account barrryyao@gmail.com (three r's). The agent's Chrome is normally already signed in to it: check the account shown on the careers page before anything else.
- If it is signed out, sign in only through agent-vault (`list_accounts`, the google.com account, then `login`). A passkey prompt, a phone prompt, or a failed login is `login_credentials_unavailable`: block, do not work around it.
- The résumé's contact email (from `application-profile.md`) differs from the sign-in account. Where a form asks for a contact email, give the profile's.
- Leave drafts for other postings on the account alone.

## Applying

- Open the posting URL from the assignment and use its Apply button; the apply link carries a per-session token, so never record it.
- Google keeps one résumé on the Careers profile for every draft. Upload the assignment's `resume_path` (the PDF tailored to this posting) right before this posting's Apply, replacing whatever the profile holds.
- The upload control can open only a native file picker. When `find` shows no file input, inject a hidden `<input type=file>` with `javascript_tool`, `file_upload` into it, then dispatch the file to the page's drop target with a `DataTransfer` drag-and-drop. Verify the filename shows before moving on.
- Role information step: preferred location from the posting; answer each minimum-qualification question Yes only where the résumé shows it; legal eligibility and sponsorship from the profile.
- Voluntary self-identification step: answer from `application-profile.md` on every draft, since answers do not carry over between drafts. Read the race checkboxes' current state on screen before clicking: a click toggles.
- Save each step with Next. With `submit: true`, submit on the final step and wait for Google's confirmation; the dashboard (https://www.google.com/about/careers/applications/dashboard) then lists it as submitted. That is the confirmation evidence.
- A CAPTCHA or bot check is `captcha`: block and leave the tab for the user.
- Google refuses a second application to the same job within 90 days and the user's own limit is three per 30 days. A refusal for either is `application_limit`, with the date it lifts if the page gives one.
