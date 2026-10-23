# Amazon (amazon.jobs) playbook

Reference notes for the application worker. `.claude/skills/application-completion/SKILL.md` is authoritative; where this file seems to disagree, follow the skill.

## Recognize it

- Job page: `www.amazon.jobs/en/jobs/<id>/<slug>`. The application runs on `account.amazon.jobs/en-US/applicant/jobs/<id>/apply` (2026-10-17 to 2026-10-23).
- The result page is `account.amazon.jobs/en-US/applicant/jobs/<id>/summary?result=<code>`. Codes seen are `success` and `application_limit_reach` (2026-10-20 to 2026-10-23).

## Sign-in and accounts

- There is one Amazon jobs account for all Amazon roles. Sign in with agent-vault `login`; the site then sends an emailed one-time code, which agent-vault enters itself (2026-10-18).
- Before agent-vault handled this, the emailed code blocked sign-in (2026-10-17, JOB-6). Since 2026-10-20 the login has worked on every attempt, including three in a row on 2026-10-20.
- Ignore "Amazon A to Z" code emails; they are not from amazon.jobs (2026-10-23 Gmail check).

## Form traversal and controls

- Multi-step and auto-saved between steps. Traverse every step to Review (2026-10-18).
- Check any "N+ years of experience" screening answer against the profile before Review (2026-10-17 note).

## Résumé field

- The account keeps the résumé from earlier applications. On Review a worker found a "Download <approved filename>" link and verified that instead of uploading again. That counts as visible verification; do not upload again while the approved filename is shown (2026-10-22).
- Upload with `find` → `file_upload` only when no approved filename is visible.

## Limits and known failures

- **Account cap of 10 active applications.** Clicking Apply redirects to `summary?result=application_limit_reach`, which reads "You've reached the maximum number of job applications ... limit of 10 job applications." Return blocked `application_limit` and quote that text. The ledger then stops claiming Amazon jobs and keeps them queued; only the user can lift the cap, by withdrawing older applications (2026-10-23). Amazon jobs are queued only at fit 90 or above, to spend the ten slots well.
- **Identity verification.** Two applications asked for a government ID photo and a live selfie before the EEO and Review steps (2026-10-17, 2026-10-18). Leave the auto-saved progress and block `identity_verification_required`; never upload ID images. This step did not appear on any Amazon submission from 2026-10-20 on, and the repo does not record why.

## Confirmation

- The URL becomes `.../summary?result=success` and the page reads "Thank you for applying! Your application for <title> (Job ID: <id>) has been submitted." Quote that sentence as `confirmation_evidence` (2026-10-20 to 2026-10-23).
- A rejection can arrive by email within a day or two. That does not change the submitted status (2026-10-21 Gmail check).
