# Local Resume Companion

Local Chrome extension that attaches one user-configured approved résumé to a clearly labeled required Resume/CV input. It never submits an application or targets Cover Letter.

## Quick Start (macOS)

1. Copy `config.example.json` to `config.json` in the repository root.
2. Set `approved_resume_path` to the absolute path of your local résumé. Do not commit this file or the résumé.
3. In Chrome, open `chrome://extensions`, enable **Developer mode**, then choose **Load unpacked** and select `local-resume-companion-extension`.
4. Copy the extension ID shown by Chrome.
5. Run `local-resume-companion-extension/native-host/install.command` and paste the extension ID. The installer validates your résumé path, builds the native host, and registers a manifest containing that ID.
6. Refresh any application page that was already open before the extension was installed or reloaded.

The native messaging manifest is generated from `native-host/com.local_resume_companion.json`; its `allowed_origins` is replaced with your extension ID and its host path is replaced with your local installation path.

## Other operating systems

The extension source is cross-platform, but the included installer currently supports macOS. Windows and Linux require an equivalent native-host registration script that uses the same generated manifest and points Chrome to the compiled native-host executable.

For autonomous use, the application bot queues one exact target page with `node enqueue-attach.js "APPLICATION_URL"`. When that page contains one clearly labeled Resume/CV upload field, the extension attaches the approved résumé automatically. The instruction is consumed after one use.
