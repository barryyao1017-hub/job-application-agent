# Login gates

Use this procedure only for authentication needed to reach a job application. Passing a login gate does not authorize clicking the application's final Submit control.

## Strict two-step policy

1. Check the company-login credentials cache available to the agent. Select at most one credential that matches the employer or authentication origin, such as the matching Google credential when available, and attempt login once.
2. Only when no applicable company credential is available, invoke the saved-login credential prompt provided by Google Chrome. Use at most one matching saved login without revealing its secret, and attempt login once.

If the applicable cached credential fails, stop the login attempt; do not continue to the Chrome prompt. If no applicable cached credential exists and the Chrome prompt is unavailable, offers no applicable credential, or fails, stop the login attempt.

Return `blocked` with `blocker_category: "login_credentials_unavailable"`, preserve the live tab and committed progress, and let the orchestrator move on to the next application.

Do not create accounts, open registration, solicit credentials or verification codes, invent credentials, inspect or expose secrets, attempt recovery, or add any other fallback path.
