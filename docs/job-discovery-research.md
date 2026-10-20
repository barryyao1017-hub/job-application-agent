# Job discovery: sources research (2026-10-20)

Question: the daily pipeline discovers roles by driving LinkedIn in Chrome. What would an efficient, comprehensive discovery step look like instead? Everything below was tested from this Mac on 2026-10-20 unless marked "not verified".

## Summary

1. Make **direct ATS feeds** the primary source: Greenhouse, Lever and Ashby publish official, unauthenticated JSON job boards; Workday and Amazon.jobs expose unofficial but stable JSON. All five answered in under 1.2 s, with full descriptions, timestamps and canonical apply URLs. This is what the 10-18 run did by hand (`source: ats-api`), and it produced 28 ledger rows with 19 reaching `ready_for_review`, versus 19 rows from LinkedIn across all runs and 0 on 10-19.
2. Add **one aggregator for breadth** (companies not in our registry). The best empirical result was the `python-jobspy` Indeed backend: 40 past-24h Bay Area MLE postings in 0.6 s, 38 of them with the employer's own apply URL and all with descriptions. The official Indeed MCP connector works but returns ~10 results per call, no date filter, Indeed click-tracking links instead of employer URLs, and hit a Cloudflare "Security Check" page on the second job opened.
3. Keep LinkedIn out of the daily path. Its User Agreement (section 8.2) forbids bots, scraping and automated access, the browser flow is the slowest and most fragile step, and it is the only step that can CAPTCHA the user's account.

## What runs today

`.claude/skills/job-application-pipeline/SKILL.md` step 2: a Claude session drives the signed-in LinkedIn tab, runs two keyword searches with past-24h and CA/WA/remote filters, opens each promising card, visits the canonical ATS page, and writes `artifacts/YYYY-MM-DD/discovered.json`.

Ledger evidence (`data/job-agent.sqlite3`):

| source | jobs | notes |
|---|---|---|
| linkedin | 19 | 4 runs; 10-19 run discovered 0 |
| ats-api | 28 | one manual run on 10-18 from a 60-company market-cap list |

Problems with the LinkedIn step: dozens of browser tool calls per run; depends on a logged-in session (CAPTCHA/MFA ends the run); LinkedIn's terms forbid it; postings carry no structured minimum-years or description, so the scorer agents reconstruct them; and cards link through LinkedIn's apply redirect, so the worker still has to find the ATS page.

## Sources evaluated

### A. Direct employer feeds (recommended primary)

| Source | Endpoint | Auth | Tested result | Fields |
|---|---|---|---|---|
| Greenhouse | `boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true` | none | Anthropic: 666 jobs, 0.19 s | `absolute_url`, `first_published`, `updated_at`, `location`, content |
| Lever | `api.lever.co/v0/postings/{company}?mode=json` | none | Palantir OK, 0.2 s | `hostedUrl`, `applyUrl`, `createdAt`, `descriptionPlain`, `workplaceType`, `country` |
| Ashby | `api.ashbyhq.com/posting-api/job-board/{board}` | none | OpenAI: 806 jobs, 0.29 s | `jobUrl`, `applyUrl`, `publishedAt`, `descriptionPlain`, `isRemote`, `location` |
| Workday (unofficial) | `POST {host}/wday/cxs/{tenant}/{site}/jobs` with `{"searchText","limit":20,"offset"}`; detail at `.../job/{externalPath}` | none | NVIDIA: 568 matches, 1.2 s; detail gives `jobDescription`, `jobReqId`, `postedOn` | `postedOn` is relative text ("Posted Today"); 20 per page |
| Amazon.jobs (unofficial) | `amazon.jobs/en/search.json?base_query=...&loc_query=USA&sort=recent` | none | 469 hits, 0.4 s | `posted_date`, `description`, `basic_qualifications`, `job_path`, `is_intern`, `is_manager` |
| SmartRecruiters | `api.smartrecruiters.com/v1/companies/{id}/postings` | none | endpoint answers; needs correct company ids | official, paginated |
| Google Careers | `google.com/about/careers/applications/jobs/results/?q=...&location=United States&sort_by=date` | none | HTML, 20 jobs/page, fetchable with curl | Google is `manual_review` anyway |
| Microsoft | `gcsservices.careers.microsoft.com/search/api/v1/search` | none | **not verified**: TLS connects, curl gets no response | needs a browser-like client |
| Apple | `jobs.apple.com/api/v1/search` | none | **not verified**: `serviceError` with my request body | applications need Apple ID + CAPTCHA regardless |
| Meta | metacareers.com | — | HTTP 400 to curl | needs browser |

Of the 60 companies in `artifacts/2026-10-18/companies-by-market-cap.md`, 8 are on Workday, 1 Lever, 1 Eightfold, 1 Oracle; the rest are unannotated. The feeds above cover the ATSes the worker already handles best (Greenhouse, Ashby, Lever, Workday with vault accounts).

Why this is the right primary source: zero browser time, no login, no rate limits observed, exact timestamps for the 24-hour window, full descriptions for the scorer, canonical URLs that already match `infer_source` and `extract_ats_job_id` in `job_agent/core.py`, and the pipeline becomes a deterministic Python step that can run headless.

Gap: it only sees companies we list. That is also a feature (it is how the 10-18 run targeted big tech), but it needs a registry file (`company`, `ats`, `token`/`host`) and an aggregator for the long tail.

### B. Aggregators

| Source | How | Tested result | Verdict |
|---|---|---|---|
| Indeed MCP (official, connected) | `search_jobs(search, location, country_code, job_type)`, `get_job_details(job_id)` | 10 results per call; mixed in 5-month-old part-time "AI Trainer" posts and a Staff role; `Posted on` present; no date filter; no description in search; links are `to.indeed.com` → `indeed.com/viewjob` (Indeed Apply or employer redirect); rate limit hit immediately ("try again in 51 seconds"); second job page opened in Chrome showed a Cloudflare Security Check | Sanctioned and free, so keep it as a supplementary source for coverage spot-checks and `get_company_data`. Too thin and too redirect-heavy to be primary. |
| python-jobspy, Indeed backend | `scrape_jobs(site_name=["indeed"], hours_old=24, ...)` (uses Indeed's mobile GraphQL API) | 40 rows in 0.6 s, 40 descriptions, 38 direct employer URLs (e.g. `grnh.se/...`), `date_posted` | Best breadth per second. Unofficial API: Indeed could change or block it; no account involved. |
| python-jobspy, LinkedIn guest | unauthenticated `jobs-guest/.../seeMoreJobPostings/search?f_TPR=r86400` | 40 rows in 18 s; no description or direct URL unless fetched per job; raw endpoint also worked from curl, 10 cards per page | Same ToS problem as browser control, minus the account risk. Not recommended. |
| python-jobspy, ZipRecruiter | | 14 rows, 11 direct URLs, no descriptions | marginal |
| python-jobspy, Glassdoor | | 40 rows, no descriptions or direct URLs | low value |
| python-jobspy, Google Jobs | | 0 rows | unreliable |
| Dice MCP, ZipRecruiter MCP | in the Claude connector registry, not connected | not tested | tech-heavy boards; cheap to try via connectors |
| Crustdata MCP | `crustdata_job_search_live` | not tested; paid B2B product | skip |
| JSearch (RapidAPI), SerpApi `google_jobs`, Adzuna | paid or keyed HTTP APIs over Google for Jobs | not tested; Adzuna returns 400 without a key | fallback if Indeed access breaks |
| Apify ATS aggregators | hosted Greenhouse/Lever/Ashby/Workday crawlers, about $1–2 per 1,000 jobs | not tested | only worth it if maintaining feed code becomes a burden |
| hiring.cafe | internal search API | Cloudflare challenge | no |
| LinkedIn official Jobs API | partner-only | — | not available |

### C. Terms and risk

- LinkedIn User Agreement 8.2: no scraping or copying of the Services, no "bots or other unauthorized automated methods". Browser control and the guest endpoint both fall under this; the browser flow additionally risks the user's account.
- Indeed: the MCP connector is Indeed's sanctioned route. The jobspy backend uses an unpublished API; treat it as best-effort and make the pipeline degrade gracefully when it fails.
- Greenhouse, Lever, Ashby job-board APIs are documented for public use. Workday CXS and Amazon search.json are undocumented but have been stable for years and are read-only.

## Recommended design

1. **Registry file** `data/company-registry.json` (or under `.claude/skills/company-application-policies/references/`): one entry per target company with `ats` (`greenhouse|lever|ashby|workday|amazon|smartrecruiters`) and the board token or Workday host/tenant/site. Seed it from the 10-18 market-cap list plus the priority companies in the job-scout skill.
2. **New ledger subcommand** `python3 -m job_agent fetch-feeds --registry ... --out artifacts/YYYY-MM-DD/discovered.json`: pulls every feed, keeps postings whose title matches the ML/Data patterns and whose timestamp is inside `recency_hours` (Workday: accept "Posted Today"/"Yesterday"), applies `preferred_location_terms`, and emits the existing `discovered.json` schema with `source: "ats-api"`. Stdlib `urllib` only, so the project stays dependency-free; concurrent fetches with `ThreadPoolExecutor`.
3. **Breadth step** `python3 -m job_agent fetch-aggregators`: optional, calls jobspy's Indeed backend (installed in a venv outside the repo, or vendored as a subprocess) with `hours_old=24` for the two keyword queries and CA/WA/remote locations, and merges results whose `job_url_direct` is an ATS page. If jobspy is missing or errors, log and continue. The Indeed MCP stays available to the orchestrator as a manual cross-check.
4. **Pipeline skill**: step 2 becomes "run the two commands, then run `company-policies`"; the LinkedIn browser step is removed or demoted to a fallback the user enables explicitly. `job-fit-scorer` stays as is; it gets better input (full descriptions, exact dates).
5. **Scheduling**: because discovery no longer needs Chrome, `run-automation.sh job-pipeline` can run discovery headlessly; add the new subcommands to its allowlist.

Expected effect: discovery drops from tens of browser tool calls and several minutes to a few seconds of HTTP, with more candidates per run (hundreds of postings scanned across the registry) and higher-quality scorer input.

## Open questions for Barry

- Which companies belong in the registry beyond the 10-18 list? Each new company is one line once its ATS is known.
- Is the unofficial jobspy Indeed backend acceptable for breadth, or should breadth come only from the official Indeed MCP (fewer, noisier results, no automation outside a Claude session)?
