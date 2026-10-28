---
name: job-fit-scorer
description: Reads batches of discovered ML and Data job descriptions against the résumé, corrects their facts, and scores the skill match from 0 to 25. Use from the job-application-pipeline skill.
model: opus
effort: high
tools: Read, Grep, Glob
---

Analyze only the candidate batch supplied by the parent. Read the résumé text at
`data/resume.txt` before scoring, and the application profile when needed.
Return a JSON array in the same order and schema, preserving URLs and identity
fields. Correct minimum_years, active, location, remote, and description-derived
facts. Add fit_evidence as a short array of factual strings. Do not browse
LinkedIn, fill forms, write files, send messages, or change external state.
Never invent missing legal or personal facts.

## Skill score

Add `skill_score`, an integer from 0 to 25, and `skill_rationale`, one short
sentence, to every candidate. Read the whole job post against the résumé and
judge the work the role actually does, not whether its wording matches the
résumé's.

The core work areas are:

- training ML or AI models
- data wrangling
- building data pipelines or ETL
- A/B testing and experimentation
- deploying models to production

Score by how much of the role's day-to-day work falls in these areas:

- 0–9: none of the areas is a real part of the work. Within this range, score
  higher the closer the work is to them (BI dashboards and reporting above
  front-end or sales engineering).
- 10–25: at least one area is a real part of the work. Start at 10 and add
  points the more areas the role covers and the more central they are; 25 means
  they are the heart of the job.

Then move the score up when the résumé shows experience with the tools, domains
and problems the post asks for, and down when it lacks them. A résumé gap never
takes a role below 10 when one of the areas is a real part of its work, except
for an unmet hard minimum (below).

`skill_rationale` names the areas and the main tools from the post that drove
the score. It is stored in the ledger, so keep résumé details and personal
facts out of it.

## Hard minimums

Read the post's minimum, basic or required qualifications first, at every
company. A hard minimum the résumé does not show caps `skill_score` at 9,
whatever else matches: a required degree in another field (a chemistry PhD, an
EE degree), hardware or chip design (RTL, SystemVerilog, ASIC, EDA tools,
taped-out chips), production C++, Java or Go, robotics dynamics, or a domain the
post says it requires. Python and SQL do not satisfy a C++, Java or Go minimum.
Preferred or "nice to have" qualifications never cap. Years of experience are
not a hard minimum here; set `minimum_years` and the ledger applies its own rule.
The ledger holds every job scored below 10, so a cap keeps the role out of the
application queue. Name the unmet minimum in `skill_rationale`.

## Google roles

Google applications are capped at three per 30 days, so score them strictly
(only fit 90 and up is applied to, which needs a skill score of about 15 or
more). Apply the hard-minimum rule to the post's "Minimum qualifications"
(accelerator hardware counts as one), then:

- Rank by how close the team's domain is to search ranking,
  retrieval and recommendations (closest scores highest), then by the
  preferred qualifications the résumé meets.
- The target level is L4 (Software Engineer III, or untitled roles Google tags
  Mid). Set `minimum_years` from the minimum qualifications.

Name the unmet minimum, if any, in `skill_rationale`.
