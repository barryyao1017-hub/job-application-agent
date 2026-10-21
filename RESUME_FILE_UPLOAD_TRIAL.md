# Trial: replacing Local Resume Companion with Claude in Chrome `file_upload`

Date: 2026-10-18. Browser: the agent's Chrome (debug port 9222, confirmed with the `?browser-check` tab). Tool: `mcp__claude-in-chrome__file_upload` (`ref`, `tabId`, `paths`). File: the approved résumé `Jiayi_Yao_resume.docx`. No other field was filled and nothing was submitted; all trial tabs were closed afterwards.

Verdict: **not a drop-in replacement.** Ashby and hosted Greenhouse boards work with a plain `find` → `file_upload`. SmartRecruiters and embedded Greenhouse do not, because the accessibility tree that `find`/`read_page` expose never includes the file input (open shadow root, cross-origin iframe). Both have a verified workaround, so the extension can be retired once the skill prescribes those two extra steps. The skills were left unchanged by the trial itself; the user then decided to make `file_upload` the default with the extension as fallback, and section 5 of the completion skill now encodes the ladder below.

## Per-ATS results

| ATS | Page tried | Input findable by `find`/`read_page`? | Filename visible after `file_upload`? | Blocking alert |
|---|---|---|---|---|
| Ashby | `jobs.ashbyhq.com/maintainx/d2c51648-…/application` | Yes. `find` returned three file inputs: "(Autofill from resume)", "Resume", "Cover Letter". | Yes. The file landed on `input#_systemfield_resume` (checked by script); the autofill and `#cover_letter` inputs stayed empty; the page rendered "Jiayi_Yao_resume.docx". | None |
| SmartRecruiters | `jobs.smartrecruiters.com/oneclick-ui/company/ServiceNow/publication/427b47e6-…` (Easy apply form reached via "I'm interested") | **No.** The tree shows only a generic "Resume" heading; the real `input[type=file]` lives in the open shadow root of `spl-dropzone[data-test="resume-upload"]`. `file_upload` on the heading ref fails with "Element is not a file input". | **Yes, with a workaround** (below): after moving the shadow input into the light DOM it appeared as a file button, `file_upload` set it, and the dropzone listed "Jiayi_Yao_resume.docx". The `apply-with-resume-container` dropzone stayed empty. | None |
| Greenhouse, embedded | `databricks.com/company/careers/…?gh_jid=8401114002` (form inside `iframe#grnhse_iframe` from `job-boards.greenhouse.io/embed/job_app`) | **No.** The tree stops at the cross-origin iframe; `find` reports no form at all. | **Yes, with a workaround** (below): after navigating the tab to the iframe's own URL, `find` returned the "Attach" file input under "Resume/CV", distinct from "Cover Letter"; the page rendered "Jiayi_Yao_resume.docx" and `#cover_letter` stayed empty. | None |
| Greenhouse, hosted board | `job-boards.greenhouse.io/cognitiv/jobs/4327598009` | Yes. "Attach" file input under "Resume/CV". | Yes. | None |

## Other findings

- **Résumé path must be readable by the session.** `file_upload` refused `/Users/jiayiyao/Documents/Jiayi_Yao_resume.docx` ("only files this session is allowed to read can be uploaded"). It accepted a copy at `data/Jiayi_Yao_resume.docx` inside the repository (`data/` and `*.docx` are gitignored). Before switching, either point `approved_resume_path` at a copy inside the repo or start workers with `--add-dir ~/Documents`. The scheduled run in `scripts/run-automation.sh` would need the same.
- **`javascript_tool` is refused on pages whose URL carries tokens** ("[BLOCKED: Cookie/query string data]"), which hit the Databricks careers page (`?gh_jid=`). Scripts that only read iframe ids still ran; scripts that touched `location.href` or `iframe.src` did not. The skill should not depend on reading those values back.
- **No concurrency hazard.** `file_upload` reads the file per call and targets one `ref` in one `tabId`; nothing is shared between workers, so the single-slot `attach-target-url.txt` queue is no longer the reason workers must be sequential. Workers still need distinct tabIds in the same Chrome.
- The extension's field-selection rules carry over unchanged: required Résumé/CV only, never Cover Letter, never the optional Ashby "Autofill from resume" input or the SmartRecruiters `apply-with-resume-container` dropzone.

## Verified workarounds

### SmartRecruiters (open shadow root)

Run once with `javascript_tool`, then `find` "file input Resume file input (relocated)" and call `file_upload` on that ref; finally move the input back:

```js
// before file_upload
const dz = document.querySelector('spl-dropzone[data-test="resume-upload"]');
const input = dz.shadowRoot.querySelector('input[type="file"]');
window.__resumeInput = input; window.__resumeParent = input.parentNode;
input.setAttribute('aria-label', 'Resume file input (relocated)');
input.style.cssText = 'position:fixed;left:0;top:0;width:200px;height:30px;opacity:0.01;z-index:99999';
document.body.appendChild(input);
```

```js
// after file_upload
const i = window.__resumeInput; window.__resumeParent.appendChild(i);
i.style.cssText = ''; i.removeAttribute('aria-label');
document.querySelector('spl-dropzone[data-test="resume-upload"]').shadowRoot.textContent.includes('Jiayi_Yao_resume.docx');
```

The component kept its `change` listener on the moved node and displayed the file. The displayed filename lives inside the shadow root, so `get_page_text`/`innerText` do not show it; verify with the script above or a screenshot.

### Greenhouse embedded in a company site (cross-origin iframe)

Navigate the worker's tab to the iframe's own document instead of filling through the embed:

```js
location.href = document.getElementById('grnhse_iframe').src;  // job-boards.greenhouse.io/embed/job_app?for=…&token=…
```

The standalone page is the same form (same `token`), `find` sees the "Resume/CV" Attach input, and the rest of the application proceeds there. This matches what the extension-era skill already required ("queue the iframe's exact URL"). Do not echo the URL into logs; it carries a validity token.

## Proposed section 5 for `.claude/skills/application-completion/SKILL.md`

Written so it can be dropped in once the path question above is settled:

> ## 5. Attach and verify the résumé
>
> Attach the approved résumé with `mcp__claude-in-chrome__file_upload`, passing this worker's own `tabId`, the `ref` of the required Résumé/CV file input, and `paths: ["<approved_resume_path from config.json>"]`. The path must be one the session can read (inside the repository or a directory added with `--add-dir`). Do not manually enter résumé content or attach a different file.
>
> 1. Suppress page-generated informational alerts first with `javascript_tool` (`window.alert = (m) => console.log('[suppressed alert]', m)`); do not override `confirm` or `prompt`.
> 2. Locate the input with `find` ("Resume/CV file input"). Choose only the required Résumé/CV input: never a Cover Letter input, never Ashby's "(Autofill from resume)" input (the required one is `input#_systemfield_resume`), never SmartRecruiters' `apply-with-resume-container` dropzone.
> 3. If `find` returns no file input, the control is hidden from the accessibility tree:
>    - SmartRecruiters (`jobs.smartrecruiters.com`): the input is in the open shadow root of `spl-dropzone[data-test="resume-upload"]`. Move it into the light DOM with `javascript_tool`, upload to its ref, then move it back (scripts in `RESUME_FILE_UPLOAD_TRIAL.md`).
>    - Greenhouse embedded in a company careers page (`iframe#grnhse_iframe`): navigate the same tab to the iframe's `src` and continue the application on `job-boards.greenhouse.io/embed/job_app`.
> 4. Treat the upload as asynchronous: wait briefly, then read the page; never wait indefinitely.
> 5. Verify that the form visibly shows `Jiayi_Yao_resume.docx` (for SmartRecruiters, read the dropzone's shadow text or take a screenshot). Report `resume_verified: true` only then.
> 6. If the filename is absent, re-run `find`, confirm the ref is still the required input, and upload once more. Do not re-upload while the filename is visible.
>
> Local Resume Companion (`node local-resume-companion-extension/enqueue-attach.js URL`) remains available as a fallback; its single-slot queue means only one worker may use it at a time.

## Timing

Date: 2026-10-19, same agent Chrome (port 9222, `?browser-check` confirmed), same two pages as the trial above. Local Resume Companion was loaded in that Chrome (unpacked from the main checkout, extension id `mmljpimppaapdbpbnhgdhgfcmjdpicom`, native host registered for it), so both methods were timed. Wall-clock seconds, all clocks on the same machine.

- **Method A (`file_upload`):** `t0` = `Date.now()` via `javascript_tool` immediately before `find`; then `find` for the required Résumé/CV input; then `file_upload` with `data/Jiayi_Yao_resume.docx` (a copy inside the worktree, since the tool refuses `~/Documents`); then a 250 ms in-page poll until `document.body.innerText` contains `Jiayi_Yao_resume.docx`. `t1` was recorded just before `file_upload`, so "find phase" = `t1 − t0` (the `find` call plus one model round trip) and "upload phase" = end − `t1`. The tab was reloaded between runs.
- **Method B (extension):** a 250 ms poller was armed in the page first, then `Date.now()` was taken in the shell right before `node local-resume-companion-extension/enqueue-attach.js "<page URL>"` (the main checkout's copy, which is the one the loaded extension and native host read); end = the poller's first detection of the filename. Fresh tab per run. Cap 60 s; no run timed out.
- On Ashby, the form is fetched after page load; both methods' clocks started only once `input#_systemfield_resume` existed.

| Page | Method | Run | Seconds | Find phase | Upload phase |
|---|---|---|---|---|---|
| Greenhouse hosted (`cognitiv/jobs/4327598009`) | A `file_upload` | 1 | 6.585 | – | – |
| Greenhouse hosted | A `file_upload` | 2 | 7.191 | 6.666 | 0.525 |
| Greenhouse hosted | A `file_upload` | 3 | 7.844 | 7.311 | 0.533 |
| Greenhouse hosted | B extension | 1 | 1.335 | | |
| Greenhouse hosted | B extension | 2 | 0.705 | | |
| Greenhouse hosted | B extension | 3 | 2.020 | | |
| Ashby (`maintainx/…/application`) | A `file_upload` | 1 | 8.449 | 8.171 | 0.278 |
| Ashby | A `file_upload` | 2 | 10.619 | 10.287 | 0.332 |
| Ashby | A `file_upload` | 3 | 8.275 | 8.006 | 0.269 |
| Ashby | B extension | 1 | 0.961 | | |
| Ashby | B extension | 2 | 1.035 | | |
| Ashby | B extension | 3 | 0.322 | | |

| Page | Method | Median (s) | Mean (s) |
|---|---|---|---|
| Greenhouse hosted | A `file_upload` | 7.19 | 7.21 |
| Greenhouse hosted | B extension | 1.34 | 1.35 |
| Ashby | A `file_upload` | 8.45 | 9.11 |
| Ashby | B extension | 0.96 | 0.77 |

Discarded attempts (not in the table): one Greenhouse Method A attempt failed at `file_upload` with "Element is no longer in the document" because the ref from `find` went stale during the ~6 s round trip (the page re-rendered); the run was restarted from a reload. One Ashby Method A attempt was lost to a "connection lost" error from the browser tool before any action ran; also restarted.

Interpretation: the extension attaches the file 5–9× sooner than `file_upload` on these pages, but almost none of that gap is upload work. `file_upload` itself takes 0.3–0.5 s from call to visible filename; the remaining 6–10 s per run is the `find` call (the accessibility-tree query against the whole form, slower on Ashby's longer form) plus the model round trip between `find` and `file_upload`. The extension skips both because its content script already knows the selector and polls every 1.5 s, so its cost is one poll interval plus the native-host read (0.3–2.0 s, median about 1 s). In a real worker the `find` is usually not an extra step, since the worker has to locate the field anyway to choose the required input over Cover Letter and Ashby's autofill input, so the practical penalty of switching is closer to the ~0.5 s upload phase plus one tool call, not the full 7–8 s. The stale-ref failure is the more important cost: a ref obtained seconds earlier can expire on pages that re-render, so the skill should `find` and `file_upload` back to back (ideally in one `browser_batch`) and retry once on "no longer in the document".
