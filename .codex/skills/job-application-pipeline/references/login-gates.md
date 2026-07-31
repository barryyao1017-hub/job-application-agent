# Login gates

Use this procedure only for authentication needed to reach a job application. Passing a login gate does not authorize clicking the application's final Submit control.

## Configuration and secret boundary

Read `application_account_email` and `application_account_registry_path` from `config.json`.

- Use only the configured bot-owned email to create accounts. Do not infer or substitute another email.
- Keep passwords exclusively in Google Password Manager. Do not inspect browser password storage or copy, expose, log, return, or persist a password.
- Never store recovery answers, cookies, session tokens, MFA approvals, or one-time codes.
- Treat the configured registry as private local data.

If the bot email or registry path is missing, reuse an existing visible Chrome session or saved login when possible, but do not create an account.

## Authentication sequence

1. Identify the authentication origin, including any tenant-specific hostname. Use that origin—not only the employer name—as the account boundary.
2. Check the private account registry for the origin and configured bot email. Treat the registry as a routing hint, not proof that a password is available.
3. If the application is already signed in, continue and append an `observed_existing` event if no record exists.
4. Otherwise, use the ordinary login form and allow Chrome to offer saved credentials. Use a visible saved credential or autofill suggestion without attempting to reveal its secret.
5. Submit the login form once. If it succeeds, append a `login_succeeded` event and continue.
6. If the site reports that no account exists, or Chrome offers no usable credential and the site clearly supports self-service registration, open registration.
7. Enter the exact configured bot email as the username wherever an email address is accepted. If a separate arbitrary username is mandatory and the email is rejected as a username, return a blocker rather than inventing an identity.
8. Focus the new-password field and select Chrome's suggested strong password. Confirm that Chrome fills any confirmation field and accept its save prompt when presented. Do not generate or type an agent-created password.
9. Complete ordinary account creation. Accept only routine terms or privacy acknowledgements already authorized by the application profile.
10. Complete email verification only through an available, authorized inbox connection. Do not ask for or handle phone verification, inaccessible MFA, recovery questions, passkeys, identity documents, or unsupported one-time codes.
11. After registration succeeds, append an `account_created` event. Append `verification_completed` after verification succeeds, then continue the application.

If the site says the email is already registered but Chrome has no usable saved login, do not create a duplicate or repeatedly guess. Return `login_credentials_unavailable`.

## Human-handoff blockers

Return `blocked` promptly for:

- `captcha`
- `phone_verification`
- `mfa_unavailable`
- `email_verification_unavailable`
- `password_manager_unavailable`
- `login_credentials_unavailable`
- `account_creation_unsupported`
- `authentication_technical_failure`

Preserve the live tab and committed progress. The orchestrator must record the blocker and continue to the next eligible job instead of ending the daily run.

## Account registry

Use append-only JSON Lines so each authentication event is auditable and prior records are not overwritten. Before appending, ensure the parent directory exists. Write exactly one JSON object per line with:

```json
{
  "recorded_at": "ISO-8601 timestamp",
  "company": "Employer",
  "auth_origin": "https://tenant.example.com",
  "account_email": "configured bot-owned email",
  "username": "configured bot-owned email",
  "event": "observed_existing | login_succeeded | account_created | verification_completed | blocked",
  "status": "active | pending_verification | blocked",
  "password_provider": "google_password_manager",
  "blocker_category": null
}
```

Set `blocker_category` only for a `blocked` event. Never add a password or other secret field. Before creating an account, scan the registry for the same normalized `auth_origin` and `account_email`; if an active or pending account exists, attempt login or verification rather than registering again.
