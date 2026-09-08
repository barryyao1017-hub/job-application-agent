# Local Resume Companion

Local Chrome extension that attaches one user-configured approved résumé to a clearly labeled required Resume/CV input. It never submits an application or targets Cover Letter.

## Quick Start (macOS)

1. Copy `config.example.json` to `config.json` in the repository root.
2. Set `approved_resume_path` to the absolute path of your local résumé. Do not commit this file or the résumé.
3. In Chrome, open `chrome://extensions`, enable **Developer mode**, then choose **Load unpacked** and select `local-resume-companion-extension`.
4. Copy the extension ID shown by Chrome.
5. Run `local-resume-companion-extension/native-host/install.command` and paste the extension ID. The installer validates your résumé path, builds and signs the native macOS host, and registers a manifest containing that ID.
6. Refresh any application page that was already open before the extension was installed or reloaded.

The native messaging manifest is generated from `native-host/com.local_resume_companion.json`; its `allowed_origins` is replaced with your extension ID and its host path is replaced with your local installation path.

## Other operating systems

The extension source is cross-platform, but the included installer currently supports macOS. Windows and Linux require an equivalent native-host registration script that uses the same generated manifest and points Chrome to the compiled native-host executable.

## Queue an attachment

The URL-only invocation remains the automatic default:

```sh
node local-resume-companion-extension/enqueue-attach.js 'https://example.com/application'
```

When automatic matching is ambiguous, inspect the live page and supply an explicit target:

```sh
node local-resume-companion-extension/enqueue-attach.js 'https://example.com/application' --tab-id 123 --frame-id 0 --selector 'input#resume-upload'
```

Use the real Chrome tab ID and frame ID, not a Playwright frame index. Frame 0 is the top-level document. The extension popup lists the active tab's document URLs, frame IDs, and most recent attachment status. For an iframe, use its exact document URL and frame ID. The selector is scoped to that document. For open shadow DOM, add `--shadow-hosts '["resume-widget", "upload-panel"]'`; each selector enters one uniquely matched shadow host in order, then the final selector selects the file input. Closed shadow roots are unsupported.

An explicit target bypasses label matching. It must resolve to exactly one connected, enabled file input. Hidden file inputs are permitted because custom upload buttons commonly hide them; the agent must inspect the associated visible control and current application step first. An invalid, missing, or ambiguous target never falls back to another field. A node replaced during the native request is rejected. Inspect the page again and enqueue a fresh request after any such error.

Requests contain a unique ID and are consumed once. The background worker checks the actual Chrome sender tab, frame, document, and URL before claiming bytes. The native host also checks the exact URL, request ID, and explicit tab/frame values. It reads only the configured approved résumé; the queue cannot select another local file. Queue updates and claims use the same short-lived lock directory. If interrupted while holding it, remove the `.lock` directory only after confirming no enqueue/native-host process is running.

The popup's `dispatched` status means the file-input events were delivered, **not** that the website accepted the upload. Verify the displayed résumé filename and any validation errors in the live application. `needs_target` means the agent should select an explicit field; `blocked` includes the reason to inspect before retrying.

## Updating an existing installation

Version 0.2 adds session storage for attachment status. On macOS, the installer builds an Objective-C native executable with an ad-hoc signature and stable identifier. This replaces the shell/Python launcher, which macOS can deny before it starts even when Chrome has Full Disk Access. Run `native-host/install.command` again with the existing extension ID, reload Local Resume Companion in Chrome's extensions page, then refresh the application page when its progress can safely be restored. Both native host and extension must be updated together. Enqueue a fresh request after updating. The retired C host does not understand explicit targets. If macOS denies file access, add the exact installed `resume-native-host` executable to System Settings → Privacy & Security → Full Disk Access with user authorization; a shell-script launcher may not appear in that list. The installer requires Apple command-line tools. Changing the installed extension ID also requires rerunning the installer with that ID.

## Concurrency limitation

There is still one queued request. New enqueue operations replace a pending request, so run application workers sequentially. The lock prevents overlapping queue writes/claims, but this is not a multi-job queue. A native claim consumes the request before dispatch; if the page changes or site rejects the upload afterward, verify the UI and enqueue again deliberately.

## Confirmed Chewy behavior

Chewy can show a blocking JavaScript alert reading “You have Uploaded Resume Successfully.” Dismiss it through the native Chrome UI if browser dialog inspection stalls, then verify the visible `Download Jiayi_Yao_resume.docx` link. The alert alone does not replace filename verification. This flow was verified on September 7, 2026.
