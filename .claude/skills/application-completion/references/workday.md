# Workday playbook

Reference notes for the application worker. `.claude/skills/application-completion/SKILL.md` is authoritative; where this file seems to disagree, follow the skill.

## Recognize it

- Job pages on `<tenant>.wd<N>.myworkdayjobs.com/en-US/<site>/job/...` (NVIDIA wd5, Salesforce wd12, Intel/KLA/Broadcom/Applied Materials wd1, CrowdStrike/Cisco/Palo Alto Networks wd5) (2026-10-18).
- Some tenants use `wd1.myworkdaysite.com/recruiting/<company>/...` instead (Snap) (2026-10-17).
- The application path observed every time is `.../apply/applyManually` (Apply Manually) (2026-10-17, 2026-10-18).

## Sign-in and accounts

- Every tenant has its own account. Use only the `list_accounts` entry whose `site_host` equals the tab's hostname; on `myworkdaysite.com` add `/recruiting/<company>`. A login stored for one tenant was rejected on another (Capital One) (2026-10-17).
- When no account matches, create one with `register()` on the tenant's Create Account page. This worked for Intel, CrowdStrike, Cisco, Palo Alto Networks, KLA, Applied Materials and Broadcom (2026-10-18).
- The verification email can come from a company-specific sender such as `Workday@<company>.com` that agent-vault does not yet trust; `verify_email` then fails. Stop and name the sender in `blocker_message` so the user can have agent-vault trust it (2026-10-18).
- `login` used to return `error` "Still on a login form after submitting" although the sign-in had worked (CrowdStrike wd5, Salesforce wd12) (2026-10-21). agent-vault now waits for the outcome and quotes the page's own error, and three Workday logins on 2026-10-23 had no such error. An empty password field afterwards means nothing: agent-vault always clears it. Doctor's "BW_SESSION not set" line is about your shell, not a locked vault.
- Do not reload mid-application: a reload dropped the Workday session on a retry, and the next `login` then hit a CDP connect timeout (2026-10-18). Before the first form step there is nothing to lose, so the skill's check after `login` returns `ok` does navigate to the apply URL again.
- `login` returned `ok` twice while the apply page kept showing Sign In, step 1 of 6 (NVIDIA JR2023503, 2026-10-24), and CrowdStrike's Sign In modal stayed up with `error` "Still on a login form after submitting" (2026-10-25). Follow the skill's check after `ok`: confirm Candidate Home or the first form step, reopen the apply URL, retry `login` once, then block.
- agent-vault timed out connecting to Chrome once about 25 tabs were open. Close your own intermediate tabs as you go, and on a connection timeout follow the skill's close-tabs-and-retry-once rule (2026-10-18).

## Form traversal and controls

- Workday is multi-step: keep clicking Save and Continue until the Review step shows the final Submit. A visible step bar means you are not done (skill section 3; spot-checked on Intel, 2026-10-18).
- Progress is saved server-side step by step, so a resumed tab may open on a later step (2026-10-18).
- Check the work-authorization answer and any optional Education section against the profile before Review (2026-10-17 note on an NVIDIA application).

## Résumé field

- The upload section can be labelled "Resume/CV ... you can include a cover letter as well". That is the résumé input; the cover-letter wording does not disqualify it (2026-10-18; Local Resume Companion fix f299334).
- Use `find` → `file_upload` back to back, then confirm the approved filename shows in the section.
- Workday has answered an upload with "Network Error" (Salesforce) (2026-10-18). Re-run `find` and upload once more per skill section 5 step 9; if it repeats, block `technical_failure` with the error text.

## Limits and known failures

- "You've already applied for this job" can appear right after sign-in. Do not start another application; quote the warning in your result. The 2026-10-21 case (Salesforce) was recorded as blocked `already_applied` and may have been a false positive caused by a parallel test session on the same account (JOB-33).
- Read the posting for eligibility limits: a Salesforce role open only to former Salesforce interns was submitted anyway (2026-10-23).

## Confirmation

- After Submit, the page reads "Application Submitted - Your application has been successfully submitted." and the URL ends `/jobTasks/completed/application` (NVIDIA, Salesforce) (2026-10-20, 2026-10-23).
- Candidate Home lists the requisition with a status and date: "Application Received" on NVIDIA, "In Consideration" on Salesforce. Use it to confirm an ambiguous result (2026-10-20, 2026-10-23).
