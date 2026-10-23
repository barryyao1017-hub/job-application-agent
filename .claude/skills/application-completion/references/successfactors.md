# SAP SuccessFactors playbook

Reference notes for the application worker. `.claude/skills/application-completion/SKILL.md` is authoritative. This repo has no observed SuccessFactors application yet: no run, retro, ledger row or commit records one. Everything below comes from the skill; the rest is unknown.

## Recognize it

- Host contains `successfactors.com` (named in skill section 2 as a multi-company platform). Specific URL shapes have not been observed.
- Do not confuse it with SAP's own job postings: those were applied to on SmartRecruiters (`jobs.smartrecruiters.com/SAPITBusinessSysteme/...`) (2026-10-18). See smartrecruiters.md.

## Sign-in and accounts

- Every company has its own account. In `list_accounts`, only an exact `site_host` match counts (skill section 2).
- With no matching account, follow the skill's `register()` procedure. How agent-vault copes with SuccessFactors' sign-up form is untested.

## Form traversal and controls

- Unknown. Apply skill sections 3 and 4: traverse every step and commit every custom control.

## Résumé field

- Unknown. Use the default `find` → `file_upload` on the required Résumé/CV input and never a Cover Letter input.

## Limits and known failures

- None recorded. After the first run, record what you see in the retro so this playbook can be filled in.

## Confirmation

- Unknown. Use the skill's generic confirmation rules (section 7).
