# JPMorgan Chase application guidance

Handling: `auto_apply` means preparation through final pre-submit review, not permission to submit.

## Known starting-screen privacy acknowledgment

On the official JPMorgan Chase Oracle careers site (`https://jpmc.fa.oraclecloud.com/hcmUI/CandidateExperience/`), the application email-entry screen has an “I agree with the terms and conditions” checkbox. The observed “Terms and Conditions” dialog acknowledges the applicable candidate recruitment privacy policies and global employment/workforce privacy notice, and gives consent where required for processing personal data for the purposes described there. This routine privacy acknowledgment was reviewed in this task on September 7, 2026.

The user explicitly authorizes selecting this known starting-screen acknowledgment and clicking Agree/Next on subsequent JPMorgan Chase applications without asking again. Do not treat its heading alone as evidence of a binding contract. No need to reopen and reread the linked privacy policies on each application. Recognize the documented official site and starting screen; this is not blanket authorization for every agreement shown by this employer. If the visible screen instead introduces materially different obligations, such as arbitration, a waiver, or a contract, apply the browser's applicable confirmation rules. Company guidance cannot override mandatory action-time browser confirmation.

## Email verification and submission

Use the connected agent mailbox under the completion skill's authentication procedure, unless the user explicitly authorizes another connected mailbox for the current application.

Determine the purpose of verification from where it occurs in the workflow, not from the Verify label or generic “complete your job application” wording alone.

- **Initial identity verification:** Immediately after entering an email address at `/apply/email`, before filling the application, the “Confirm Your Identity” screen can say that verification will “complete your job application.” This wording does not mean it submits the application. On September 7, 2026, for job 210779432, the email subject was “Take action to confirm your identity”; completing Verify opened Personal Info, step 1 of 4, at `/apply/section/1`. Complete this authentication step and continue filling without requesting final-submission approval.
- **Final application verification:** A verification challenge after completing the form and initiating submission may be the final submission action. The previously observed final email was titled “Final step to complete your job application” and identified the job number. Stop before completing that final verification in review-only work unless the user separately authorizes submission.

Do not assume every application requires final email verification. For job 210779432, clicking Submit after the user's explicit authorization led directly to “Thank you for your job application” and an active application with status “Under Review.” Authorization to submit one application does not authorize future submissions.

## Résumé attachment

Oracle can retain a hidden initial résumé-import input alongside the final Upload Resume field. Inspect the current step and, when automatic targeting is ambiguous, use the companion's explicit tab/frame/selector target for the actual résumé attachment control. Never guess a stable input ID from a previous application. Verify the displayed filename after upload.
