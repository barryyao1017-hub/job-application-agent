from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from .core import (
    DEFAULT_CONFIG_PATH,
    DEFAULT_DB_PATH,
    DEFAULT_RESUME_TEXT_PATH,
    APPLICATION_LIMIT_CATEGORY,
    active_limits,
    block_job,
    claim_next,
    clear_limits,
    complete_job,
    connect_db,
    create_run,
    deferred_jobs,
    digest_payload,
    finish_run,
    ingest_candidates,
    latest_running_run,
    load_company_policies,
    load_config,
    mark_notification,
    match_company_policy,
    outcome_report,
    record_discovery,
    recover_stale_claims,
    requeue_jobs,
    resume_text,
    score_jobs,
    submit_job,
    swap_plan,
    withdraw_job,
)
from .feeds import DEFAULT_QUERIES, DEFAULT_REGISTRY_PATH, run_fetch_feeds


def emit(value: Any) -> None:
    print(json.dumps(value, indent=2, sort_keys=True, default=str))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python3 -m job_agent")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB_PATH)
    subparsers = parser.add_subparsers(dest="command", required=True)

    fetch_feeds = subparsers.add_parser(
        "fetch-feeds",
        help="Pull the ATS job boards in the company registry into a discovered.json file",
    )
    fetch_feeds.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY_PATH)
    fetch_feeds.add_argument("--out", type=Path, required=True)
    fetch_feeds.add_argument(
        "--queries",
        nargs="+",
        default=list(DEFAULT_QUERIES),
        help="Search terms for boards that only expose a search API (Amazon); "
        "the other boards list every open job and are filtered by title locally",
    )
    fetch_feeds.add_argument(
        "--max-pages",
        type=int,
        default=10,
        help="Pages to walk per Workday board and per Amazon query (newest first)",
    )
    fetch_feeds.add_argument(
        "--run-id",
        help="Run to record the per-company stats under (default: a new run); "
        "pass the printed run_id to discover",
    )

    discover = subparsers.add_parser("discover")
    discover.add_argument("--input", type=Path, required=True)
    discover.add_argument("--run-id")

    resume = subparsers.add_parser(
        "resume-text",
        help="Write the approved résumé as plain text for job-fit-scorer to read",
    )
    resume.add_argument("--out", type=Path, default=DEFAULT_RESUME_TEXT_PATH)

    score = subparsers.add_parser("score")
    score.add_argument("--run-id")

    policies = subparsers.add_parser("company-policies")
    policy_source = policies.add_mutually_exclusive_group(required=True)
    policy_source.add_argument("--company")
    policy_source.add_argument("--input", type=Path)

    claim = subparsers.add_parser("claim")
    claim.add_argument("--worker-id", required=True)
    claim.add_argument("--run-id", help="Run the attempt counts toward (default: latest running run)")

    complete = subparsers.add_parser("complete")
    complete.add_argument("--job-id", required=True)
    complete.add_argument("--worker-id", required=True)
    complete.add_argument("--review-url", required=True)
    complete.add_argument("--resume-verified", action="store_true", required=True)

    submit = subparsers.add_parser("submit")
    submit.add_argument("--job-id", required=True)
    submit.add_argument("--worker-id", required=True)
    submit.add_argument("--confirmation-url", required=True)
    submit.add_argument("--evidence", required=True)
    submit.add_argument("--resume-verified", action="store_true", required=True)

    report = subparsers.add_parser("report")
    report.add_argument("--run-id")
    report.add_argument("--since", help="ISO date or timestamp (UTC) on last update")

    block = subparsers.add_parser("block")
    block.add_argument("--job-id", required=True)
    block.add_argument("--worker-id", required=True)
    block.add_argument("--category", required=True)
    block.add_argument("--message", required=True)
    block.add_argument("--review-url")
    block.add_argument(
        "--until",
        help=f"With --category {APPLICATION_LIMIT_CATEGORY}: ISO date the cap lifts "
        "(default: until clear-limit)",
    )

    requeue = subparsers.add_parser(
        "requeue", help="Put blocked or ready_for_review jobs back in the queue for a fresh attempt"
    )
    requeue.add_argument("--job-id", required=True, nargs="+")

    subparsers.add_parser(
        "limits", help="Companies whose application cap is in force and the queued jobs it defers"
    )

    clear_limit = subparsers.add_parser(
        "clear-limit", help="Lift a reported application cap, e.g. after withdrawing applications"
    )
    clear_limit.add_argument("--company", required=True)

    plan = subparsers.add_parser(
        "swap-plan", help="Active applications to withdraw for stronger queued jobs (companies with a swap policy)"
    )
    plan.add_argument("--company", required=True)
    plan.add_argument(
        "--active-file",
        type=Path,
        required=True,
        help="JSON array of the site's active applications: {ats_job_id, status}",
    )
    plan.add_argument("--keep", nargs="*", default=[], help="ATS job ids never to withdraw (recruiter contact)")
    plan.add_argument("--run-id", help="Run the withdrawals count toward (default: latest running run)")

    withdraw = subparsers.add_parser("withdraw", help="Record an application withdrawn on the site for a swap")
    withdraw.add_argument("--job-id", required=True)
    withdraw.add_argument("--replacement-job-id", required=True)
    withdraw.add_argument("--evidence", required=True)
    withdraw.add_argument("--run-id", help="Run the withdrawal counts toward (default: latest running run)")

    digest = subparsers.add_parser("digest")
    digest.add_argument("--run-id", required=True)
    digest.add_argument("--sent-key")
    digest.add_argument("--failed-key")

    recover = subparsers.add_parser("recover-stale-claims")
    recover.add_argument("--timeout-minutes", type=int)

    finish = subparsers.add_parser("finish-run")
    finish.add_argument("--run-id", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        config = load_config(args.config)
        connection = connect_db(args.db)
        if args.command == "fetch-feeds":
            result = run_fetch_feeds(
                config,
                registry_path=args.registry,
                out_path=args.out,
                queries=args.queries,
                max_pages=args.max_pages,
            )
            run_id = create_run(connection, args.run_id)
            summary = record_discovery(connection, run_id, result["boards"])
            result["run_id"] = run_id
            result["companies_checked"] = summary["companies_checked"]
            emit(result)
        elif args.command == "discover":
            candidates = json.loads(args.input.read_text(encoding="utf-8"))
            if not isinstance(candidates, list):
                raise ValueError("Discovery input must be a JSON array")
            run_id = create_run(connection, args.run_id)
            emit(ingest_candidates(connection, candidates, run_id))
        elif args.command == "resume-text":
            text = resume_text(config["approved_resume_path"])
            if not text:
                raise ValueError("The approved résumé has no extractable text")
            args.out.parent.mkdir(parents=True, exist_ok=True)
            args.out.write_text(text + "\n", encoding="utf-8")
            emit({"path": str(args.out), "characters": len(text)})
        elif args.command == "score":
            emit(score_jobs(connection, config, args.run_id))
        elif args.command == "company-policies":
            registry = load_company_policies(config["company_policies_path"])
            if args.company:
                companies = [args.company]
            else:
                candidates = json.loads(args.input.read_text(encoding="utf-8"))
                if not isinstance(candidates, list):
                    raise ValueError("Discovery input must be a JSON array")
                companies = sorted(
                    {
                        str(candidate.get("company") or "").strip()
                        for candidate in candidates
                        if isinstance(candidate, dict) and candidate.get("company")
                    }
                )
            matches = []
            for company in companies:
                match = match_company_policy(company, registry)
                if match:
                    matches.append({"company": company, **match})
            emit({"matches": matches})
        elif args.command == "claim":
            claimed = claim_next(
                connection,
                args.worker_id,
                config["company_policies_path"],
                run_id=args.run_id,
                limited_minimum_fit_score=int(config["limited_company_minimum_fit_score"]),
            )
            if claimed is not None:
                claimed["submit"] = config["submit_applications"]
            emit(claimed)
        elif args.command == "complete":
            emit(
                complete_job(
                    connection,
                    args.job_id,
                    args.worker_id,
                    review_url=args.review_url,
                    resume_verified=args.resume_verified,
                )
            )
        elif args.command == "submit":
            emit(
                submit_job(
                    connection,
                    args.job_id,
                    args.worker_id,
                    confirmation_url=args.confirmation_url,
                    evidence=args.evidence,
                    resume_verified=args.resume_verified,
                    submit_applications=config["submit_applications"],
                )
            )
        elif args.command == "report":
            policies = load_company_policies(config["company_policies_path"])
            emit(outcome_report(connection, run_id=args.run_id, since=args.since, policies=policies))
        elif args.command == "block":
            emit(
                block_job(
                    connection,
                    args.job_id,
                    args.worker_id,
                    args.category,
                    args.message,
                    args.review_url,
                    policies=load_company_policies(config["company_policies_path"]),
                    until=args.until,
                )
            )
        elif args.command == "requeue":
            emit({"requeued": requeue_jobs(connection, args.job_id)})
        elif args.command == "limits":
            policies = load_company_policies(config["company_policies_path"])
            emit(
                {
                    "active": list(active_limits(connection, policies).values()),
                    "deferred": deferred_jobs(connection, policies),
                }
            )
        elif args.command == "clear-limit":
            policies = load_company_policies(config["company_policies_path"])
            emit({"company": args.company, "cleared": clear_limits(connection, args.company, policies)})
        elif args.command == "swap-plan":
            active = json.loads(args.active_file.read_text(encoding="utf-8"))
            if not isinstance(active, list) or not all(isinstance(item, dict) and item.get("ats_job_id") for item in active):
                raise ValueError("Active applications must be a JSON array of objects with ats_job_id")
            emit(
                swap_plan(
                    connection,
                    args.company,
                    active,
                    load_company_policies(config["company_policies_path"]),
                    run_id=args.run_id or latest_running_run(connection),
                    keep=args.keep,
                )
            )
        elif args.command == "withdraw":
            emit(
                withdraw_job(
                    connection,
                    args.job_id,
                    replacement_job_id=args.replacement_job_id,
                    evidence=args.evidence,
                    policies=load_company_policies(config["company_policies_path"]),
                    run_id=args.run_id or latest_running_run(connection),
                    submit_applications=config["submit_applications"],
                )
            )
        elif args.command == "digest":
            if args.sent_key or args.failed_key:
                key = args.sent_key or args.failed_key
                mark_notification(connection, key, sent=bool(args.sent_key), error=args.failed_key)
                emit({"notification_key": key, "sent": bool(args.sent_key)})
            else:
                emit(digest_payload(connection, config, args.run_id))
        elif args.command == "recover-stale-claims":
            timeout = args.timeout_minutes or int(config.get("claim_timeout_minutes", 120))
            emit({"recovered": recover_stale_claims(connection, timeout)})
        elif args.command == "finish-run":
            finish_run(connection, args.run_id)
            emit({"run_id": args.run_id, "status": "completed"})
        return 0
    except Exception as exc:
        emit({"error": str(exc), "type": type(exc).__name__})
        return 1


if __name__ == "__main__":
    sys.exit(main())
