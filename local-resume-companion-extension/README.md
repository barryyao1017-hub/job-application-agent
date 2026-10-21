# Local Resume Companion

Local Chrome extension that attaches one user-configured approved résumé to a clearly labeled required Resume/CV input. It never submits an application or targets Cover Letter.

**Fallback only.** Since October 2026 the application worker attaches the résumé with Claude in Chrome's `file_upload` tool (see section 5 of `.claude/skills/application-completion/SKILL.md`; trial and timing in `../RESUME_FILE_UPLOAD_TRIAL.md`). The worker queues a request here only when no file input can be found or surfaced, or `file_upload` has errored twice. The single-slot queue below is one reason workers still run one at a time.

## Quick Start (macOS)

1. Copy `config.example.json` to `config.json` in the repository root.
2. Set `approved_resume_path` to the absolute path of your local résumé, kept inside the repository at `data/Jiayi_Yao_resume.docx` (`data/` is gitignored) so the default `file_upload` path can read it too. Do not commit this file or the résumé.
3. In Chrome, open `chrome://extensions`, enable **Developer mode**, then choose **Load unpacked** and select `local-resume-companion-extension`.
4. Copy the extension ID shown by Chrome.
5. Run `local-resume-companion-extension/native-host/install.command` and paste the extension ID. The installer validates your résumé path, builds the native host, and registers a manifest containing that ID.
6. Refresh any application page that was already open before the extension was installed or reloaded.

The native messaging manifest is generated from `native-host/com.local_resume_companion.json`; its `allowed_origins` is replaced with your extension ID and its host path is replaced with your local installation path.

## Other operating systems

The extension source is cross-platform, but the included installer currently supports macOS. Windows and Linux require an equivalent native-host registration script that uses the same generated manifest and points Chrome to the compiled native-host executable.

For autonomous use, the application bot queues one exact target page with `node enqueue-attach.js "APPLICATION_URL"`. When that page contains one clearly labeled Resume/CV upload field, the extension attaches the approved résumé automatically. The instruction is consumed after one use.

## Concurrency limitation

The current attachment queue is a single file containing one URL. Each enqueue replaces the prior URL, and the native host consumes that instruction after one successful attachment.

- Multiple one-job application workers are supported when they run sequentially.
- Concurrent application workers are not safe: their enqueue operations can overwrite one another, attach to the wrong worker's timing window, or leave one form without a résumé.
- Keep application-form workers sequential until the queue is redesigned as an atomic multi-entry queue or uses per-worker leases.
