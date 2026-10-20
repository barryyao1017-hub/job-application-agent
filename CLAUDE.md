# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

# Job application agent

Local daily pipeline: discover recent ML/Data roles from employer ATS job feeds (Greenhouse, Lever, Ashby, Workday, Amazon), score and dedupe them in a SQLite ledger, and fill and submit up to five applications in the agent's Chrome. Workers submit only while `config.json` has `submit_applications: true` (the ledger refuses `submit` otherwise); with it `false` they stop at the final Review page.

## Commands

- All tests: `python3 -m unittest` (stdlib only; no dependencies, build step, or linter).
- One test: `python3 -m unittest tests.test_core.CoreTests.test_hard_filters`.
- Ledger CLI: `python3 -m job_agent --help`. Every subcommand prints JSON; errors print `{"error", "type"}` and exit 1. `--config` / `--db` override the defaults (`config.json`, `data/job-agent.sqlite3`) — point them at temp paths when experimenting so the real ledger is untouched.
- Feed discovery: `python3 -m job_agent fetch-feeds --registry data/company-registry.json --out artifacts/YYYY-MM-DD/discovered.json` pulls the Greenhouse, Lever, Ashby, Workday and Amazon boards listed in the registry concurrently (stdlib `urllib` only), keeps recent ML/Data postings in the preferred locations, and writes the `discovered.json` array that `discover` ingests (`source: "ats-api"`). It prints per-board stats (`fetched`, `kept`, `skipped`, `errors`); a failing board is reported, not fatal. `--queries` only matter for Amazon's search API; `--max-pages` bounds the newest-first walk per Workday board and Amazon query. Workday and Amazon only give day-level dates, so those rows get `posted_at` at the end of that day (config `timezone`) and `posted_at_precision: "day"`. The registry is `data/company-registry.json` (gitignored with the rest of `data/`; copy `company-registry.example.json` from the repo root, one entry per company with `ats` and the board `token`, or `host`/`tenant`/`site` for Workday). Parsers live in `job_agent/feeds.py`; `tests/test_feeds.py` covers each ATS with canned fixtures in `tests/fixtures/feeds/`.
- Scheduled runs: `scripts/install-schedules.sh` (re-run after editing schedules; `--uninstall` removes them). Run one by hand with `scripts/run-automation.sh job-pipeline`.

## Architecture

The work is split between a deterministic Python ledger and LLM instructions:

- `job_agent/core.py` holds all state and rules: URL canonicalization (tracking params stripped, identity params kept), dedupe by canonical URL and by `(company, ats_job_id)`, rule-based scoring with hard filters (internship, management, citizenship/clearance, >5 years, recency, non-ML role, location), company-policy matching, atomic claims, and the idempotent email digest. `cli.py` is a thin argparse wrapper.
- Job status flow: `discovered` → `scored` | `skipped` | `manual_review` → `queued` (fit ≥ `minimum_fit_score`, capped by `daily_limit`) → `claimed` → `submitted` | `ready_for_review` | `blocked`. `report` gives the submission rate and blockers by category. `recover-stale-claims` returns old claims to `queued`. `complete` and `submit` require `--resume-verified`; `submit` also needs `--evidence` (the on-page confirmation). Policy companies are re-checked at claim time, so a `manual_review` company is never claimed even if queued earlier.
- `.claude/skills/job-application-pipeline` drives a run: `fetch-feeds` discovery → `job-fit-scorer` enriches candidates → `discover`/`score` → loop of `claim` → one `application-worker` (foreground, one at a time) → `submit`/`complete`/`block` → blocker retro + to-dos → Gmail recruiter-reply check → `digest` → Gmail send → `finish-run`.
- Schema changes go in `SCHEMA` plus the `ALTER TABLE` migration in `connect_db`, since existing ledgers are reused.

## Layout

- `job_agent/` — ledger CLI: discover, score, company-policies, claim, submit, complete, block, report, digest, recover-stale-claims, finish-run. Ledger at `data/job-agent.sqlite3`; run artifacts in `artifacts/YYYY-MM-DD/` (both gitignored).
- `.claude/skills/job-application-pipeline` — orchestrator for a full run.
- `.claude/skills/application-completion` — one-application worker procedure (authoritative for form behavior, auth, résumé, output). `COMPLETION_CHECKLIST.md` defines "complete" (final Submit visible, every step traversed, résumé attached, no validation errors); the skill's submit-and-confirm section defines "submitted".
- `.claude/skills/company-application-policies` — per-company routing; registry in `references/policies.json` (Google is `manual_review`).
- `.claude/agents/` — `application-worker` (Opus, one job, Chrome) and `job-fit-scorer` (Sonnet, read-only).
- `application-profile.md` — source of truth for personal answers. `config.json` — private local config (gitignored; template in `config.example.json`).
- `local-resume-companion-extension/` — Chrome extension + native host that attaches the approved résumé; queue with `node local-resume-companion-extension/enqueue-attach.js URL`. Its queue holds one URL, so application workers must run sequentially. Debugging guide: `RESUME_EXTENSION_DEVELOPMENT.md`.
- Repo lives at `~/code/job-application-agent` (`~/Desktop/job-application-agent` is a symlink kept so Chrome's unpacked-extension path and ID stay valid; macOS blocks launchd jobs from Desktop/Documents).
- Daily job pipeline: Claude desktop scheduled task `job-application-pipeline-daily` (07:00 every day; stored in `~/.claude/scheduled-tasks/`), since it needs Chrome, Gmail and the to-do artifact. It runs only while the desktop app is open (a missed run fires on next launch). It runs from `~/code/job-application-agent-main`, a detached worktree that `scripts/sync-main-checkout.sh` resets to `origin/main` at the start of each run, so feature branches checked out here never reach the daily run; only what is pushed to `main` does. Don't edit or commit there (the sync refuses to overwrite tracked edits). Its `config.json`, `data/`, `artifacts/` and résumé queue file are links back to this checkout. The Chrome extension's code still loads from this checkout.
- `automations/` + `scripts/run-automation.sh` + `scripts/install-schedules.sh` — launchd-scheduled headless runs (Google L4 monitor 09:00/17:00; weekly AI stock report Sat 09:00; `run-automation.sh job-pipeline` still runs the pipeline headlessly by hand). `run-automation.sh` sets each run's model, timeout watchdog, and `--allowedTools` allowlist — a new CLI command or tool a scheduled run needs must be added there. It unsets `ANTHROPIC_API_KEY` so the claude.ai Gmail connector works. Logs in `~/Library/Logs/claude-automations/`; non-repo state in `~/.claude-automations/`.
- `.agents/` and `.codex/` — legacy Codex configuration, kept for reference only; do not edit or rely on them.

## Rules

- Only application workers click a final Submit control, only with `submit: true` from `claim`, at most once per application. Never type passwords. Accounts are created only through agent-vault's `register` tool, which generates the password and saves it to Bitwarden; see the completion skill's auth section.
- Email only `notification_email` from `config.json`, and never include contact, demographic, authorization or résumé content.
- `tests/test_agent_instructions.py` pins key phrases in the skills and agents; update it alongside instruction changes.
