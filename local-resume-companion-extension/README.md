# Local Resume Companion

Local Chrome extension that attaches one user-configured approved résumé to a clearly labeled required Resume/CV input. It never submits an application or targets Cover Letter.

**Fallback only.** Since October 2026 the application worker attaches the résumé with Claude in Chrome's `file_upload` tool (see section 5 of `.claude/skills/application-completion/SKILL.md`; trial and timing in `../RESUME_FILE_UPLOAD_TRIAL.md`). The worker queues a request here only when no file input can be found or surfaced, or `file_upload` has errored twice.

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

## Concurrent workers

Each enqueue writes its own file to `attach-queue/` (write, then rename, so the host never reads half an entry). When a page asks for the résumé, the native host looks for an entry whose URL the page's URL contains and claims it by renaming it to a name unique to that host process; `rename` is atomic, so if two hosts race for one entry exactly one wins. The entry is deleted once the reply is built, or put back if it could not be. Entries older than 30 minutes are dropped. The host still honors the old single-slot `attach-target-url.txt`, so a checkout that predates the queue keeps working.

Several application workers can therefore use the fallback at once, as long as each queues its own page's exact URL. `tests/test_resume_queue.py` compiles the host and checks matching, the race, expiry and the legacy file.
