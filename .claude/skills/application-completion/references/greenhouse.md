# Greenhouse playbook

Reference notes for the application worker. `.claude/skills/application-completion/SKILL.md` is authoritative; where this file seems to disagree, follow the skill.

## Recognize it

- Hosted board: `job-boards.greenhouse.io/<board>/jobs/<id>`, with the form on the same page (Anthropic, Reddit, Glean, Chime) (2026-10-17 to 2026-10-22).
- Embedded: a company careers page whose URL carries `?gh_jid=<id>` and holds `iframe#grnhse_iframe` (Databricks, Waymo on `careers.withwaymo.com`, Lyft on `app.careerpuck.com`) (2026-10-18, 2026-10-23). The iframe's document is `job-boards.greenhouse.io/embed/job_app?for=<board>&token=<id>` (Pinterest, Avathon) (2026-10-17).

## Sign-in and accounts

- No sign-in or account was needed on any observed Greenhouse application (2026-10-17 to 2026-10-23).

## Form traversal and controls

- Usually a single page, but still check for further steps before treating it as final.
- Follow the skill's Greenhouse safeguards (section 4): click the exact visible dropdown option, never press Enter to commit, ignore hidden cached options, and reload for a clean pass if validation fires early.
- The tools cannot see into an embedded form (the tree stops at the cross-origin iframe). Navigate your tab to the iframe's `src` with `javascript_tool` and do the whole application there. Never write that URL to results or logs: it carries a token (2026-10-18).
- `javascript_tool` has refused to run on a careers page whose URL had `?gh_jid=` ("[BLOCKED: Cookie/query string data]"). Read-only scripts still ran, but scripts that touched `location.href` or `iframe.src` did not (Databricks) (2026-10-18). If that happens, use the skill's Local Resume Companion fallback (section 5 step 6). The same navigation worked for Waymo and Lyft (2026-10-23).
- Workers run in parallel. Once, a worker's tab group changed mid-run, it filled the form again in a duplicate tab, and it may have clicked in another worker's tab (Waymo). Pass your own `tabId` on every call and follow the skill's tab-group check (section 1): block instead of refilling if your tab or its group changed (2026-10-23).

## Résumé field

- The required input is the "Attach" file input under "Resume/CV". Leave the separate Cover Letter input empty (2026-10-18).
- `find` → `file_upload` works on hosted and navigated-to embed forms. The upload itself takes about 0.5 s, but `find` takes about 7 s (2026-10-19).
- Once, a `find` ref went stale before `file_upload` ("Element is no longer in the document") because the page re-rendered. Issue the two calls back to back and retry once (2026-10-19).

## Limits and known failures

- None specific to Greenhouse. Discovery's location filter rejects Europe-only roles flagged remote (seen on Ashby, 2026-10-21).

## Confirmation

- Hosted board: the URL becomes `/jobs/<id>/confirmation` and the page reads "Thank you for applying! Your application has been received." or "Thank you for your interest in <Company>! Your application has been received." (2026-10-20 to 2026-10-22).
- Embed: either the form is replaced in place by a "Thank you" message (Waymo), or the page moves to `embed/job_app/confirmation?for=<board>` titled "Thank you for applying" (Lyft) (2026-10-23).
