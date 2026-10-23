# ElevenLabs application policy

ElevenLabs' Ashby board accepts one application per candidate every 90 days. A second application is rejected after the form is filled ("you have applied for a position in this domain within the last 90 days").

## Required actions

- Apply automatically, but only to roles with fit at or above `limited_company_minimum_fit_score` (90 by default).
- The ledger enforces the window itself: `claim` skips ElevenLabs for 90 days after a submission recorded in the ledger, and its queued jobs stay queued (deferred) until then.
- If a worker still hits the limit (for example after an application the user sent by hand), it blocks with `blocker_category: "application_limit"`; record it with `block --category application_limit --until <date the 90 days end, if known>`.
