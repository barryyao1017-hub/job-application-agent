from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from .core import (
    DEFAULT_CONFIG_PATH,
    DEFAULT_DB_PATH,
    block_job,
    claim_next,
    complete_job,
    connect_db,
    create_run,
    digest_payload,
    finish_run,
    ingest_candidates,
    load_company_policies,
    load_config,
    mark_notification,
    match_company_policy,
    outcome_report,
    recover_stale_claims,
    score_jobs,
    submit_job,
)


def emit(value: Any) -> None:
    print(json.dumps(value, indent=2, sort_keys=True, default=str))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python3 -m job_agent")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB_PATH)
    subparsers = parser.add_subparsers(dest="command", required=True)

    discover = subparsers.add_parser("discover")
    discover.add_argument("--input", type=Path, required=True)
    discover.add_argument("--run-id")

    score = subparsers.add_parser("score")
    score.add_argument("--run-id")

    policies = subparsers.add_parser("company-policies")
    policy_source = policies.add_mutually_exclusive_group(required=True)
    policy_source.add_argument("--company")
    policy_source.add_argument("--input", type=Path)

    claim = subparsers.add_parser("claim")
    claim.add_argument("--worker-id", required=True)

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
        if args.command == "discover":
            candidates = json.loads(args.input.read_text(encoding="utf-8"))
            if not isinstance(candidates, list):
                raise ValueError("Discovery input must be a JSON array")
            run_id = create_run(connection, args.run_id)
            emit(ingest_candidates(connection, candidates, run_id))
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
            claimed = claim_next(connection, args.worker_id, config["company_policies_path"])
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
            emit(outcome_report(connection, run_id=args.run_id, since=args.since))
        elif args.command == "block":
            emit(
                block_job(
                    connection,
                    args.job_id,
                    args.worker_id,
                    args.category,
                    args.message,
                    args.review_url,
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
