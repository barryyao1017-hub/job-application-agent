# Résumé Extension Development Guide

This guide is for maintaining and debugging the Local Resume Companion Chrome extension when a job application does not receive the approved résumé correctly.

**The extension is now the fallback.** The default attach method is Claude in Chrome's `file_upload` (`find` → `file_upload` back to back, pinned to the worker's tab), described in section 5 of `.claude/skills/application-completion/SKILL.md`, with the per-ATS trial, workarounds, and timing in `RESUME_FILE_UPLOAD_TRIAL.md`. Use this guide when a worker had to fall back to the extension.

## Purpose and safety boundaries

The extension attaches only the approved local résumé to a required Résumé/CV field on one explicitly queued application page.

- Never attach a résumé to a Cover Letter field.
- Never enter résumé content manually.
- Never submit an application.
- Always verify that the application visibly displays `Jiayi_Yao_resume.docx` after attachment.
- If the intended résumé field cannot be identified unambiguously, stop and report the exact reason rather than guessing.

## Components

| Component | Responsibility |
| --- | --- |
| `manifest.json` | Declares extension permissions and injects the content script into all page frames. |
| `content.js` | Finds the required upload control, receives the approved file bytes, assigns the file, and dispatches normal upload events. |
| `background.js` | Relays a page-frame request to the native messaging host. |
| `enqueue-attach.js` | Queues one exact application URL for autonomous attachment. |
| `native-host/resume_native_host.c` | Provides the approved local file only when the queued URL matches. |
| `native-host/install.command` | Registers the native messaging host for the locally installed Chrome extension. |

## Trigger flow

1. The application agent identifies the exact URL of the application page or embedded application frame.
2. The agent runs `enqueue-attach.js` with that exact URL.
3. The content script on the matching page/frame locates the required résumé field.
4. The content script asks `background.js` for the approved file.
5. The background worker asks the native host to claim the queued URL.
6. The native host returns the approved résumé bytes once, then consumes the queued instruction.
7. The content script assigns the file to the input, dispatches `input` and `change`, and checks the filename.
8. The application agent confirms that `Jiayi_Yao_resume.docx` is displayed in the form.

## Parallel-worker feasibility

Codex can create multiple one-job workers, but the extension's current queue cannot safely serve concurrent workers:

- `enqueue-attach.js` overwrites one shared `attach-target-url.txt`.
- The native host reads one target and deletes the file after a successful claim.
- Separate native-host processes have no lock or lease coordinating simultaneous claims.
- Multiple workers also share the user's Chrome instance, so tab ownership and recovery can contend even when URLs differ.

Use fresh workers sequentially today. Before enabling concurrent application workers:

1. Replace the singleton file with an atomic queue keyed by normalized application URL and a unique request or worker ID.
2. Claim and remove only the matching entry under a file lock or transactional store.
3. Return the request ID with the attachment response so the content script can reject mismatched claims.
4. Forward-test simultaneous uploads in distinct tabs, including embedded iframes.
5. Verify each tab shows the approved filename and that Cover Letter remains untouched.
6. Verify independent browser sessions can retain their final Review or blocked handoff tabs.

## Field-identification rules

`content.js` must choose only one required résumé input.

1. Prefer a known explicit required field when a site exposes a stable identifier.
   - Ashby required résumé field: `input[type="file"]#_systemfield_resume`.
2. Otherwise inspect nearby visible text for `resume`, `résumé`, or `CV`.
3. Reject any candidate whose nearby text contains `cover letter`.
4. If zero or multiple candidates remain, do not upload.

Ashby commonly renders two file inputs: an optional “Autofill from resume” input and the actual required résumé input. The explicit `_systemfield_resume` rule exists to prevent attachment to the optional autofill control.

## Common failures and fixes

### “A single clearly labeled Resume/CV field was not found”

The form has no unambiguous matching input, or more than one candidate matched.

- Inspect all `input[type="file"]` controls and their nearby visible labels.
- Add a narrow, site-specific explicit selector only when it clearly represents the required résumé field.
- Do not broaden matching rules in a way that could target Cover Letter.

### Ashby attachment goes to the optional autofill control

Ensure `content.js` checks for `#_systemfield_resume` before the general label-based search. That selector must return immediately rather than merely adding one candidate to the general match list.

### Native messaging host not found

The extension is installed, but the native host is not registered for its current extension ID.

- Run `native-host/install.command` again.
- Paste the current extension ID from `chrome://extensions`.
- Reload the extension after making source changes.

### Extension changed, but page behavior is unchanged

Chrome does not replace an already-injected content script merely because the extension was reloaded.

1. Reload the extension on `chrome://extensions`.
2. Refresh the application page or embedded application frame.
3. Requeue the exact URL.
4. Verify the displayed filename.

### Embedded Greenhouse applications

The application may be inside an iframe. The extension is configured with `all_frames: true`, so queue the iframe's exact URL, not only the outer careers-page URL.

### Filename does not appear after a successful-looking attach

The site may require its normal event flow or the extension may have targeted the wrong field.

- Confirm `input` and `change` events are dispatched after assigning `input.files`.
- Inspect the form after a short wait.
- Treat a missing displayed filename as failure; do not mark the application complete.

## Development workflow

1. Reproduce on an open application without submitting it.
2. Inspect only visible upload controls and their labels.
3. Make the smallest possible selector change in `content.js`.
4. Reload the extension.
5. Refresh the affected application page.
6. Queue the exact URL and verify the filename appears in the required field.
7. Test that Cover Letter remains untouched.
8. Update this guide with any stable, site-specific rule and its rationale.

## Configuration to keep local

Do not commit the approved résumé itself, generated queue files, or compiled native-host binaries. Keep local absolute paths and the installed Chrome extension ID out of shared source where possible.
