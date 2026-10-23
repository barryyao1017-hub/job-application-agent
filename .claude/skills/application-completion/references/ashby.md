# Ashby playbook

Reference notes for the application worker. `.claude/skills/application-completion/SKILL.md` is authoritative; where this file seems to disagree, follow the skill.

## Recognize it

- `jobs.ashbyhq.com/<board>/<uuid>`, with the form at `.../<uuid>/application` (OpenAI, Wayve, ElevenLabs, Rillet, Plaud, Speak, MaintainX) (2026-10-17 to 2026-10-23).
- Also seen embedded in a company careers page (Shopify), where it needed no sign-in (2026-10-18).

## Sign-in and accounts

- No sign-in or account was needed on any observed Ashby application (2026-10-17 to 2026-10-23).

## Form traversal and controls

- Single application page. The form loads after the page itself, so wait until `input#_systemfield_resume` exists before you `find` anything (2026-10-19).
- Ashby marks required fields with an asterisk. Run the skill's required-field scan (section 6) before the first Submit click and fill every one, including free-text fields such as a GitHub URL. A submission was rejected once because the worker left a required GitHub field empty, which cost a second Submit click (ElevenLabs) (2026-10-23).

## Résumé field

- `find` returns three file inputs: "(Autofill from resume)", "Resume" and "Cover Letter". Upload only to the required one, `input#_systemfield_resume`. Never use the autofill input or `#cover_letter` (2026-10-18).
- On Ashby's long form, `find` takes 8–10 s, so a ref can go stale. Issue `find` and `file_upload` back to back and retry once on "Element is no longer in the document". One trial run was also lost to a "connection lost" error from the browser tool (2026-10-19).
- Confirm the page renders the approved filename after the upload (2026-10-18).

## Limits and known failures

- Some companies cap applications per candidate, and Ashby rejects the Submit click even when the form is complete:
  - "I'm sorry we are limiting applications to give everyone a chance." This came on a second ElevenLabs application two minutes after the first (2026-10-21).
  - "you have applied for a position in this domain within the last 90 days" (ElevenLabs, two days after an earlier submission) (2026-10-23).
  
  Both mean the application will not go in. Return blocked `application_limit` with the quoted text and do not retry; the ledger then skips the company until the limit ends. ElevenLabs' one-per-90-days window is in the company policy registry, so the ledger no longer claims it inside the window.
- Ashby flags some Europe-only roles as remote, and discovery queued them (ElevenLabs) (2026-10-21). The location filter now rejects them; if one still reaches you, check the posting's location before applying.

## Confirmation

- The URL stays at `.../application`; the page text changes to "Your application was successfully submitted. We'll contact you if there are next steps." (OpenAI) or "Thank you for applying to <Company>!" (Wayve, ElevenLabs) (2026-10-21, 2026-10-22).
