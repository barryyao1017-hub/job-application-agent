# Lever playbook

Reference notes for the application worker. `.claude/skills/application-completion/SKILL.md` is authoritative; where this file seems to disagree, follow the skill. Evidence is thin: two applications, Palantir (ready for review, 2026-10-18) and Zoox (submitted, 2026-10-21).

## Recognize it

- `jobs.lever.co/<company>/<uuid>`; the form is at `.../<uuid>/apply` (2026-10-18).

## Sign-in and accounts

- Neither application needed sign-in or an account (2026-10-18, 2026-10-21).

## Form traversal and controls

- The Palantir form reached Review in about 1.3 minutes and 31 tool calls, which is consistent with a single page (2026-10-18). No Lever-specific control problems have been recorded.

## Résumé field

- No Lever-specific notes. Use the default `find` → `file_upload` on the required Résumé/CV input and confirm the filename. Both applications verified the résumé (2026-10-18, 2026-10-21).

## Limits and known failures

- None observed. Behaviour with per-company caps or already-applied warnings is unknown.

## Confirmation

- After Submit, Zoox redirected off Lever to the company's own domain (`zoox.com/confirmation?LeverAppId=...`), and the page read "Application Received!" (2026-10-21). Expect the confirmation page to be on a non-Lever host.
