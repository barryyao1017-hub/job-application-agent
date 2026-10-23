# iCIMS playbook

Reference notes for the application worker. `.claude/skills/application-completion/SKILL.md` is authoritative; where this file seems to disagree, follow the skill. Evidence: AMD (ready for review, 2026-10-18) and Arm (blocked, 2026-10-18 and 2026-10-19). Nothing has been submitted on iCIMS yet.

## Recognize it

- Per-company subdomains of `icims.com`: `careers-<company>.icims.com/jobs/<id>/...` (AMD) and `experienced-<company>.icims.com/jobs/<id>/<slug>/candidate` (Arm). The company's own careers site (such as `careers.arm.com`) links out to them (2026-10-18, 2026-10-19).
- The sign-in page is `.../jobs/<id>/login`. Later steps carry `step=` in the URL; on AMD the last step before Review was the voluntary self-identification form at `step=6` (2026-10-18).

## Sign-in and accounts

- Every company has its own account. Only an exact `site_host` match counts (skill section 2).
- `register()` created the AMD account (2026-10-18).
- The iCIMS sign-up form has both a "Login Name" and an "Email" field. agent-vault originally left Email blank (Arm, 2026-10-18); after a fix it filled both (2026-10-19). Check both fields hold a value after `register` before going on.
- Once, iCIMS rejected a new profile with "Invalid Data Error", saying the phone number was already linked to an existing account. agent-vault did not notice the rejection and kept a vault item for an account that did not exist (Arm) (2026-10-19). Treat this as the site saying you are already registered: stop with `login_credentials_unavailable`, and say in `blocker_message` that agent-vault may have saved an item for the rejected account.

## Form traversal and controls

- Long multi-step flow: the AMD application took about 8 minutes and 151 tool calls (2026-10-18). Traverse every step through the voluntary self-identification forms to Review.

## Résumé field

- The required input is "Upload CV", `input[type="file"][id="PortalProfileFields.Resume_File"]`. An optional "Supporting Documents" input has help text that also mentions the CV; never upload there (2026-10-19, commit d98c663).
- When `find` returns both, pick by the "Upload CV" label and check that the ref is that file input.

## Limits and known failures

- One phone number or email may already belong to an existing candidate account for that company (Arm). There is no recovery path; stop as described above (2026-10-19).
- Per-account application caps and already-applied warnings are unknown.

## Confirmation

- Unknown: no iCIMS application has been submitted. Use the skill's generic confirmation rules (section 7).
