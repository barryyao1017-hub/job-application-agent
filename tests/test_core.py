from __future__ import annotations

import sqlite3
import tempfile
import unittest
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from job_agent.core import (
    active_limits,
    block_job,
    canonicalize_url,
    claim_next,
    clear_limits,
    complete_job,
    connect_db,
    create_run,
    deferred_jobs,
    digest_payload,
    extract_ats_job_id,
    infer_ats,
    ingest_candidates,
    load_company_policies,
    load_config,
    mark_notification,
    match_company_policy,
    outcome_report,
    record_discovery,
    recover_stale_claims,
    requeue_jobs,
    resume_text,
    score_candidate,
    score_jobs,
    submit_job,
    swap_plan,
    withdraw_job,
)


NOW = datetime(2026, 7, 30, 14, 0, tzinfo=timezone.utc)


def config(resume: Path) -> dict:
    return {
        "approved_resume_path": str(resume),
        "notification_email": "barryyao1017@gmail.com",
        "recency_hours": 24,
        "minimum_fit_score": 70,
        "submit_applications": True,
        "approved_resume_filename": "Jiayi_Yao_resume.docx",
        "role_keywords": ["machine learning engineer", "data scientist", "ranking"],
        "preferred_location_terms": ["california", "seattle", "remote"],
        "skill_keywords": ["python", "sql", "machine learning", "ranking", "pytorch"],
    }


def candidate(**overrides) -> dict:
    base = {
        "source_url": "https://www.linkedin.com/jobs/view/123456/?trackingId=abc",
        "application_url": "https://job-boards.greenhouse.io/acme/jobs/123456?gh_src=abc&utm_source=linkedin",
        "company": "Acme",
        "title": "Machine Learning Engineer, Ranking",
        "location": "California",
        "remote": False,
        "posted_at": (NOW - timedelta(hours=2)).isoformat(),
        "description": "Build ranking models using Python, SQL, PyTorch and machine learning. 2+ years of experience.",
        "minimum_years": 2,
        "active": True,
    }
    base.update(overrides)
    return base


class CoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.resume = self.root / "Jiayi_Yao_resume.docx"
        self.resume.write_bytes(b"resume")
        self.cfg = config(self.resume)
        self.policy_root = self.root / "company-policies"
        self.policy_root.mkdir()
        (self.policy_root / "google.md").write_text("# Google\n", encoding="utf-8")
        (self.policy_root / "policies.json").write_text(
            """{
  "policies": [
    {
      "id": "google",
      "company_names": ["Google", "Google LLC", "Google DeepMind"],
      "handling": "manual_review",
      "documentation": "google.md",
      "reason": "Preserve the user's limited application allowance."
    }
  ]
}
""",
            encoding="utf-8",
        )
        self.cfg["company_policies_path"] = str(self.policy_root / "policies.json")
        self.connection = connect_db(self.root / "jobs.sqlite3")
        self.run_id = create_run(self.connection, "run-1")

    def tearDown(self) -> None:
        self.connection.close()
        self.temp.cleanup()

    def test_canonicalize_removes_tracking_but_keeps_identity(self) -> None:
        url = canonicalize_url(
            "https://JOB-BOARDS.greenhouse.io/acme/jobs/123/?utm_source=x&gh_jid=123&source=LinkedIn"
        )
        self.assertEqual(url, "https://job-boards.greenhouse.io/acme/jobs/123?gh_jid=123")
        self.assertEqual(extract_ats_job_id(url), "123")

    def test_ingest_deduplicates_canonical_url(self) -> None:
        first = ingest_candidates(self.connection, [candidate()], self.run_id)
        second = ingest_candidates(self.connection, [candidate()], self.run_id)
        self.assertEqual(len(first["inserted"]), 1)
        self.assertEqual(len(second["duplicates"]), 1)

    def test_score_and_queue_good_fit(self) -> None:
        result = score_candidate(candidate(), self.cfg, now=NOW)
        self.assertGreaterEqual(result.score, 70)
        ingest_candidates(self.connection, [candidate()], self.run_id)
        scored = score_jobs(self.connection, self.cfg, self.run_id, now=NOW)
        self.assertEqual(len(scored["queued"]), 1)

    def test_every_job_at_threshold_is_queued_without_a_cap(self) -> None:
        jobs = [
            candidate(application_url=f"https://job-boards.greenhouse.io/acme/jobs/{900000 + n}")
            for n in range(8)
        ]
        ingest_candidates(self.connection, jobs, self.run_id)
        scored = score_jobs(self.connection, self.cfg, self.run_id, now=NOW)
        self.assertEqual(len(scored["queued"]), 8)

    def test_company_policy_alias_matches_exactly(self) -> None:
        policies = load_company_policies(self.cfg["company_policies_path"])
        self.assertEqual(match_company_policy("Google LLC", policies)["id"], "google")
        self.assertIsNone(match_company_policy("Google Fiber Vendor", policies))

    def test_manual_review_company_is_never_queued_or_claimed(self) -> None:
        ingest_candidates(
            self.connection,
            [
                candidate(
                    company="Google",
                    application_url="https://careers.google.com/jobs/results/123456",
                )
            ],
            self.run_id,
        )
        result = score_jobs(self.connection, self.cfg, self.run_id, now=NOW)
        self.assertEqual(len(result["manual_review"]), 1)
        self.assertEqual(result["queued"], [])
        self.assertIsNone(claim_next(self.connection, "worker-1"))
        row = self.connection.execute("SELECT * FROM jobs").fetchone()
        self.assertEqual(row["status"], "manual_review")
        self.assertEqual(row["company_policy_id"], "google")
        self.assertEqual(
            row["company_policy_document"],
            str((self.policy_root / "google.md").resolve()),
        )

    def test_claim_reroutes_preexisting_manual_review_company(self) -> None:
        ingested = ingest_candidates(
            self.connection,
            [
                candidate(
                    company="Google DeepMind",
                    application_url="https://careers.google.com/jobs/results/654321",
                )
            ],
            self.run_id,
        )
        self.connection.execute(
            "UPDATE jobs SET status='queued' WHERE id=?",
            (ingested["inserted"][0],),
        )
        claimed = claim_next(
            self.connection,
            "worker-1",
            self.cfg["company_policies_path"],
        )
        self.assertIsNone(claimed)
        status = self.connection.execute(
            "SELECT status FROM jobs WHERE id=?",
            (ingested["inserted"][0],),
        ).fetchone()["status"]
        self.assertEqual(status, "manual_review")

    def test_hard_filters(self) -> None:
        cases = (
            (candidate(title="Machine Learning Intern"), "internship"),
            (candidate(title="Director of Data Science"), "management"),
            (candidate(minimum_years=7), "minimum experience"),
            (candidate(location="London, UK"), "location"),
            (candidate(description="Machine learning role. U.S. citizen required."), "citizenship"),
        )
        for value, expected in cases:
            with self.subTest(expected=expected):
                result = score_candidate(value, self.cfg, now=NOW)
                self.assertIn(expected, result.skip_reason or "")

    def test_filters_use_word_boundaries(self) -> None:
        internal = candidate(title="AI/ML Engineer, Internal Platforms")
        self.assertIsNone(score_candidate(internal, self.cfg, now=NOW).skip_reason)

        ml_software = candidate(
            title="Software Engineer III, AI/ML, Google Cloud AI",
            description="Python or C++ and end-to-end ML model deployment.",
        )
        self.assertIsNone(score_candidate(ml_software, self.cfg, now=NOW).skip_reason)

        general = candidate(title="Software Engineer", description="Build email delivery services.")
        self.assertIn("outside the ML", score_candidate(general, self.cfg, now=NOW).skip_reason or "")

    def test_skill_points_come_from_the_fit_scorer(self) -> None:
        keyword = score_candidate(candidate(), self.cfg, now=NOW)
        self.assertIn("skills 16/25 (keyword fallback: machine learning, python, pytorch, ranking, sql)", keyword.rationale)

        scored = score_candidate(
            candidate(skill_score=12, skill_rationale="Trains ranking models; PyTorch."), self.cfg, now=NOW
        )
        self.assertIn("skills 12/25 (job-fit-scorer: Trains ranking models; PyTorch.)", scored.rationale)
        self.assertEqual(scored.score, keyword.score - 16 + 12)

        for raw, expected in ((40, 25), (-3, 0), ("18", 18), (0, 0)):
            with self.subTest(raw=raw):
                result = score_candidate(candidate(skill_score=raw), self.cfg, now=NOW)
                self.assertTrue(result.rationale[1].startswith(f"skills {expected}/25 (job-fit-scorer"))
        for raw in (None, "n/a", True):
            with self.subTest(raw=raw):
                result = score_candidate(candidate(skill_score=raw), self.cfg, now=NOW)
                self.assertIn("keyword fallback", result.rationale[1])

    def test_skill_score_is_stored_and_used_when_scoring(self) -> None:
        low = candidate(skill_score=3, skill_rationale="Dashboards only.")
        ingest_candidates(self.connection, [low], self.run_id)
        row = self.connection.execute("SELECT skill_score, skill_rationale FROM jobs").fetchone()
        self.assertEqual((row["skill_score"], row["skill_rationale"]), (3, "Dashboards only."))
        # 30 role + 3 skills + 20 experience + 15 location + 10 recency = 78.
        scored = score_jobs(self.connection, {**self.cfg, "minimum_fit_score": 80}, self.run_id, now=NOW)
        self.assertEqual(scored["queued"], [])
        fit = self.connection.execute("SELECT fit_score FROM jobs").fetchone()["fit_score"]
        self.assertEqual(fit, 78)

    def test_existing_ledger_gains_skill_columns(self) -> None:
        path = self.root / "legacy.sqlite3"
        connect_db(path).close()
        legacy = sqlite3.connect(path)
        legacy.execute("ALTER TABLE jobs DROP COLUMN skill_score")
        legacy.execute("ALTER TABLE jobs DROP COLUMN skill_rationale")
        legacy.commit()
        legacy.close()
        upgraded = connect_db(path)
        columns = {row["name"]: row["type"] for row in upgraded.execute("PRAGMA table_info(jobs)")}
        upgraded.close()
        self.assertEqual(columns["skill_score"], "INTEGER")
        self.assertEqual(columns["skill_rationale"], "TEXT")

    def test_resume_text_reads_docx_paragraphs(self) -> None:
        resume = self.root / "resume.docx"
        word = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
        with zipfile.ZipFile(resume, "w") as archive:
            archive.writestr(
                "word/document.xml",
                f"<w:document {word}><w:body>"
                "<w:p><w:r><w:t>Jane Doe</w:t></w:r></w:p>"
                "<w:p></w:p>"
                "<w:p><w:r><w:t>Python</w:t><w:tab/><w:t>SQL</w:t></w:r></w:p>"
                "</w:body></w:document>",
            )
        self.assertEqual(resume_text(resume), "Jane Doe\nPython\tSQL")
        with self.assertRaises(ValueError):
            resume_text(self.root / "resume.pdf")

    def test_state_abbreviation_location_terms(self) -> None:
        cfg = {**self.cfg, "preferred_location_terms": [", ca", ", wa"]}
        for location in ("San Mateo, CA", "Kirkland, WA"):
            with self.subTest(location=location):
                result = score_candidate(candidate(location=location), cfg, now=NOW)
                self.assertIsNone(result.skip_reason)
        for location in ("Toronto, Canada", "Vancouver, Washington DC area, Wakanda"):
            with self.subTest(location=location):
                result = score_candidate(candidate(location=location), cfg, now=NOW)
                self.assertIn("location", result.skip_reason or "")

    def test_atomic_claim_and_recovery(self) -> None:
        ingest_candidates(self.connection, [candidate()], self.run_id)
        score_jobs(self.connection, self.cfg, self.run_id, now=NOW)
        claimed = claim_next(self.connection, "worker-1")
        self.assertIsNotNone(claimed)
        self.assertIsNone(claim_next(self.connection, "worker-2"))
        self.connection.execute(
            "UPDATE jobs SET claimed_at=? WHERE id=?",
            ((NOW - timedelta(hours=3)).isoformat(), claimed["id"]),
        )
        recovered = recover_stale_claims(self.connection, 120, now=NOW)
        self.assertEqual(recovered, [claimed["id"]])

    def test_parallel_claims_skip_a_company_already_claimed(self) -> None:
        ingest_candidates(
            self.connection,
            [
                candidate(),
                candidate(
                    application_url="https://job-boards.greenhouse.io/acme/jobs/222",
                    source_url="https://acme.example/jobs/222",
                    company="ACME ",
                ),
                candidate(
                    application_url="https://jobs.ashbyhq.com/beta/333",
                    source_url="https://beta.example/jobs/333",
                    company="Beta",
                ),
            ],
            self.run_id,
        )
        score_jobs(self.connection, self.cfg, self.run_id, now=NOW)
        first = claim_next(self.connection, "worker-1")
        second = claim_next(self.connection, "worker-2")
        self.assertEqual({first["company"].strip().lower(), second["company"]}, {"acme", "Beta"})
        self.assertIsNone(claim_next(self.connection, "worker-3"))
        complete_job(
            self.connection,
            first["id"],
            "worker-1",
            review_url=first["application_url"],
            resume_verified=True,
        )
        third = claim_next(self.connection, "worker-1")
        self.assertEqual(third["company"].strip().lower(), "acme")
        self.assertNotEqual(third["id"], first["id"])

    def test_completion_requires_resume_verification(self) -> None:
        ingest_candidates(self.connection, [candidate()], self.run_id)
        score_jobs(self.connection, self.cfg, self.run_id, now=NOW)
        claimed = claim_next(self.connection, "worker-1")
        completed = complete_job(
            self.connection,
            claimed["id"],
            "worker-1",
            review_url=claimed["application_url"],
            resume_verified=True,
        )
        self.assertEqual(completed["status"], "ready_for_review")
        self.assertEqual(completed["resume_verified"], 1)

    def test_block_records_one_concise_message(self) -> None:
        ingest_candidates(self.connection, [candidate()], self.run_id)
        score_jobs(self.connection, self.cfg, self.run_id, now=NOW)
        claimed = claim_next(self.connection, "worker-1")
        blocked = block_job(
            self.connection,
            claimed["id"],
            "worker-1",
            "captcha",
            "CAPTCHA shown",
            claimed["application_url"],
        )
        self.assertEqual(blocked["status"], "blocked")
        self.assertEqual(blocked["blocker_category"], "captcha")
        self.assertEqual(blocked["blocker_message"], "CAPTCHA shown")

    def test_submit_requires_switch_resume_and_evidence(self) -> None:
        ingest_candidates(self.connection, [candidate()], self.run_id)
        score_jobs(self.connection, self.cfg, self.run_id, now=NOW)
        claimed = claim_next(self.connection, "worker-1")
        kwargs = dict(
            confirmation_url=claimed["application_url"],
            evidence="Thank you for applying",
            resume_verified=True,
            submit_applications=True,
        )
        for override in (
            {"submit_applications": False},
            {"resume_verified": False},
            {"evidence": "  "},
        ):
            with self.subTest(override=override):
                with self.assertRaises(ValueError):
                    submit_job(self.connection, claimed["id"], "worker-1", **{**kwargs, **override})
        submitted = submit_job(self.connection, claimed["id"], "worker-1", **kwargs)
        self.assertEqual(submitted["status"], "submitted")
        self.assertEqual(submitted["confirmation_evidence"], "Thank you for applying")
        self.assertIsNotNone(submitted["submitted_at"])

    def test_outcome_report_rate_and_blockers(self) -> None:
        ingest_candidates(
            self.connection,
            [
                candidate(),
                candidate(application_url="https://job-boards.greenhouse.io/acme/jobs/222222"),
            ],
            self.run_id,
        )
        score_jobs(self.connection, self.cfg, self.run_id, now=NOW)
        first = claim_next(self.connection, "w")
        submit_job(
            self.connection,
            first["id"],
            "w",
            confirmation_url=first["application_url"],
            evidence="Application received",
            resume_verified=True,
            submit_applications=True,
        )
        second = claim_next(self.connection, "w")
        block_job(self.connection, second["id"], "w", "captcha", "CAPTCHA shown")
        report = outcome_report(self.connection, run_id=self.run_id)
        self.assertEqual(report["attempts"], 2)
        self.assertEqual(report["submission_rate_percent"], 50.0)
        self.assertEqual(report["blockers"]["captcha"][0]["message"], "CAPTCHA shown")
        self.assertEqual(report["ready_for_review"], [])
        body = digest_payload(self.connection, self.cfg, self.run_id, now=NOW)["email"]["body"]
        self.assertIn("Submitted 1 of 2 application attempts (50.0%)", body)
        self.assertIn("Blocked — captcha: 1", body)
        self.assertNotIn("No applications were submitted", body)

    def test_rate_counts_each_attempt_including_retries_and_abandoned(self) -> None:
        ingest_candidates(self.connection, [candidate()], self.run_id)
        score_jobs(self.connection, self.cfg, self.run_id, now=NOW)
        job = claim_next(self.connection, "w")
        block_job(self.connection, job["id"], "w", "technical_failure", "Upload failed")
        # Retry in a later run: re-queue, abandon once, then submit.
        later = create_run(self.connection, "run-2")
        self.connection.execute("UPDATE jobs SET status='queued' WHERE id=?", (job["id"],))
        claim_next(self.connection, "w", run_id=later)
        recover_stale_claims(self.connection, 0, now=datetime.now(timezone.utc) + timedelta(minutes=1))
        retry = claim_next(self.connection, "w", run_id=later)
        submit_job(
            self.connection,
            retry["id"],
            "w",
            confirmation_url=retry["application_url"],
            evidence="Application received",
            resume_verified=True,
            submit_applications=True,
        )
        overall = outcome_report(self.connection)
        self.assertEqual(overall["attempts"], 3)
        self.assertEqual(
            overall["attempt_outcomes"],
            {"submitted": 1, "ready_for_review": 0, "blocked": 1, "abandoned": 1},
        )
        self.assertEqual(overall["submission_rate_percent"], 33.3)
        self.assertEqual(outcome_report(self.connection, run_id=later)["attempts"], 2)
        self.assertEqual(outcome_report(self.connection, run_id=self.run_id)["attempts"], 1)

    def test_claim_without_run_id_uses_latest_running_run(self) -> None:
        ingest_candidates(self.connection, [candidate()], self.run_id)
        score_jobs(self.connection, self.cfg, self.run_id, now=NOW)
        claim_next(self.connection, "w")
        run = self.connection.execute("SELECT run_id FROM attempts").fetchone()["run_id"]
        self.assertEqual(run, self.run_id)

    def test_discovery_stats_are_recorded_and_reported(self) -> None:
        boards = [
            {"company": "Acme", "ats": "greenhouse", "fetched": 120, "kept": 2, "errors": []},
            {"company": "Beta", "ats": "lever", "fetched": 30, "kept": 0, "errors": []},
            {"company": "Gamma", "ats": "workday", "fetched": 0, "kept": 0, "errors": ["HTTP 500"]},
        ]
        summary = record_discovery(self.connection, self.run_id, boards)
        self.assertEqual(summary["companies_checked"], 3)
        self.assertEqual(summary["postings_scanned"], 150)
        self.assertEqual(summary["companies_with_matches"], {"Acme": 2})
        self.assertEqual(summary["companies_with_errors"], ["Gamma"])
        # Recording again for the same run replaces, not appends.
        record_discovery(self.connection, self.run_id, boards[:2])
        report = outcome_report(self.connection)
        self.assertEqual(report["discovery"][0]["companies_checked"], 2)
        body = digest_payload(self.connection, self.cfg, self.run_id, now=NOW)["email"]["body"]
        self.assertIn("Companies checked: 2\n", body)
        self.assertIn("Postings scanned: 150", body)
        self.assertIn("Companies with new matching roles: Acme (2)", body)
        self.assertIn("Companies checked: Acme, Beta", body)

    def test_legacy_review_only_config_disables_submission(self) -> None:
        import json

        legacy = {k: v for k, v in self.cfg.items() if k != "submit_applications"}
        legacy["review_only"] = True
        path = self.root / "config.json"
        path.write_text(json.dumps(legacy), encoding="utf-8")
        self.assertFalse(load_config(path)["submit_applications"])

    def test_parallel_workers_default_and_bounds(self) -> None:
        import json

        path = self.root / "config.json"
        path.write_text(json.dumps(self.cfg), encoding="utf-8")
        self.assertEqual(load_config(path)["max_parallel_workers"], 2)
        for value in (0, 4, True, "2"):
            with self.subTest(value=value):
                path.write_text(json.dumps({**self.cfg, "max_parallel_workers": value}), encoding="utf-8")
                with self.assertRaises(ValueError):
                    load_config(path)

    def test_digest_is_idempotent(self) -> None:
        payload = digest_payload(self.connection, self.cfg, self.run_id, now=NOW)
        self.assertTrue(payload["eligible"])
        mark_notification(self.connection, payload["notification_key"], sent=True)
        again = digest_payload(self.connection, self.cfg, self.run_id, now=NOW)
        self.assertFalse(again["eligible"])

    def test_digest_surfaces_manual_attention_policy(self) -> None:
        ingest_candidates(
            self.connection,
            [
                candidate(
                    company="Google",
                    application_url="https://careers.google.com/jobs/results/789012",
                )
            ],
            self.run_id,
        )
        score_jobs(self.connection, self.cfg, self.run_id, now=NOW)
        payload = digest_payload(self.connection, self.cfg, self.run_id, now=NOW)
        self.assertEqual(payload["counts"]["manual_review"], 1)
        self.assertIn("Manual attention: 1", payload["email"]["body"])
        self.assertIn("policy: google", payload["email"]["body"])


    def test_europe_only_remote_postings_are_outside_the_location_filter(self) -> None:
        for location in ("Budapest, Hungary", "Sofia, Bulgaria", "Prague", "Remote - Ontario"):
            with self.subTest(location=location):
                result = score_candidate(candidate(location=location, remote=True), self.cfg, now=NOW)
                self.assertIn("location", result.skip_reason or "")
        for location in ("New York, NY", "Remote", "Remote - US", "Austin, Texas"):
            with self.subTest(location=location):
                result = score_candidate(candidate(location=location, remote=True), self.cfg, now=NOW)
                self.assertIsNone(result.skip_reason)
                self.assertIn("location 15/15", result.rationale[3])

    def test_ats_is_stored_and_backfilled(self) -> None:
        self.assertEqual(infer_ats("https://nvidia.wd5.myworkdayjobs.com/en-US/X/job/1"), "workday")
        self.assertEqual(infer_ats("https://careers.withwaymo.com/jobs?gh_jid=1"), "greenhouse")
        self.assertEqual(infer_ats("https://www.shopify.com/careers/ml_1", "ashby"), "ashby")
        self.assertEqual(infer_ats("https://www.example.com/careers/1"), "example.com")
        ingest_candidates(self.connection, [candidate()], self.run_id)
        self.assertEqual(self.connection.execute("SELECT ats FROM jobs").fetchone()["ats"], "greenhouse")

        path = self.root / "legacy-ats.sqlite3"
        legacy = connect_db(path)
        ingest_candidates(legacy, [candidate()], create_run(legacy, "r"))
        legacy.close()
        raw = sqlite3.connect(path)
        raw.execute("ALTER TABLE jobs DROP COLUMN ats")
        raw.commit()
        raw.close()
        upgraded = connect_db(path)
        self.assertEqual(upgraded.execute("SELECT ats FROM jobs").fetchone()["ats"], "greenhouse")
        upgraded.close()

    def test_report_breaks_attempts_down_by_ats(self) -> None:
        ingest_candidates(
            self.connection,
            [
                candidate(),
                candidate(
                    company="Beta",
                    application_url="https://beta.wd1.myworkdayjobs.com/External/job/X/ML-Engineer_R1",
                ),
            ],
            self.run_id,
        )
        score_jobs(self.connection, self.cfg, self.run_id, now=NOW)
        first = claim_next(self.connection, "w")
        submit_job(
            self.connection, first["id"], "w", confirmation_url=first["application_url"],
            evidence="Thanks", resume_verified=True, submit_applications=True,
        )
        second = claim_next(self.connection, "w")
        block_job(self.connection, second["id"], "w", "login_credentials_unavailable", "error")
        report = outcome_report(self.connection, run_id=self.run_id)
        by_ats = report["by_ats"]
        self.assertEqual(set(by_ats), {"greenhouse", "workday"})
        blocked_ats = "workday" if second["company"] == "Beta" else "greenhouse"
        self.assertEqual(by_ats[blocked_ats]["blockers"], {"login_credentials_unavailable": 1})
        self.assertEqual(by_ats[blocked_ats]["submission_rate_percent"], 0.0)
        self.assertEqual(report["by_company"][first["company"]]["outcomes"]["submitted"], 1)
        body = digest_payload(self.connection, self.cfg, self.run_id, now=NOW)["email"]["body"]
        self.assertIn("By ATS: greenhouse", body)

    def test_requeue_returns_blocked_jobs_to_the_queue(self) -> None:
        ingest_candidates(self.connection, [candidate()], self.run_id)
        score_jobs(self.connection, self.cfg, self.run_id, now=NOW)
        job = claim_next(self.connection, "w")
        block_job(self.connection, job["id"], "w", "technical_failure", "Upload failed")
        self.assertEqual(requeue_jobs(self.connection, [job["id"]]), [job["id"]])
        row = self.connection.execute("SELECT status, blocker_category FROM jobs").fetchone()
        self.assertEqual((row["status"], row["blocker_category"]), ("queued", None))
        with self.assertRaises(ValueError):
            requeue_jobs(self.connection, [job["id"]])


class ApplicationLimitTests(unittest.TestCase):
    """Companies whose site caps applications: higher fit bar, and claims stop while the cap is in force."""

    tearDown = CoreTests.tearDown

    def setUp(self) -> None:
        CoreTests.setUp(self)
        (self.policy_root / "amazon.md").write_text("# Amazon\n", encoding="utf-8")
        (self.policy_root / "elevenlabs.md").write_text("# ElevenLabs\n", encoding="utf-8")
        (self.policy_root / "policies.json").write_text(
            """{
  "policies": [
    {"id": "amazon", "company_names": ["Amazon", "AWS"], "handling": "auto_apply",
     "documentation": "amazon.md", "reason": "Ten active applications.",
     "application_limit": {"description": "Ten active applications per account."}},
    {"id": "elevenlabs", "company_names": ["ElevenLabs"], "handling": "auto_apply",
     "documentation": "elevenlabs.md", "reason": "One per 90 days.",
     "application_limit": {"description": "One application per 90 days.", "max_submissions": 1, "window_days": 90}}
  ]
}""",
            encoding="utf-8",
        )
        self.policies = load_company_policies(self.cfg["company_policies_path"])

    def claim(self, worker: str, now: datetime | None = None) -> dict | None:
        return claim_next(self.connection, worker, self.cfg["company_policies_path"], now=now)

    def job(self, company: str, number: int, skill: int) -> dict:
        # 30 role + skill + 20 experience + 15 location + 10 recency = 75 + skill.
        return candidate(
            company=company,
            application_url=f"https://job-boards.greenhouse.io/{company.lower()}/jobs/{number}",
            skill_score=skill,
        )

    def statuses(self) -> dict:
        return {
            (row["company"], row["fit_score"]): row["status"]
            for row in self.connection.execute("SELECT company, fit_score, status FROM jobs")
        }

    def test_limited_companies_need_a_fit_of_90(self) -> None:
        ingest_candidates(
            self.connection,
            [self.job("Amazon", 1, 10), self.job("AWS", 2, 17), self.job("Acme", 3, 10)],
            self.run_id,
        )
        result = score_jobs(self.connection, self.cfg, self.run_id, now=NOW)
        self.assertEqual(len(result["held_below_limited_threshold"]), 1)
        self.assertEqual(
            self.statuses(),
            {("Amazon", 85): "scored", ("AWS", 92): "queued", ("Acme", 85): "queued"},
        )

    def test_invalid_application_limit_is_rejected(self) -> None:
        (self.policy_root / "policies.json").write_text(
            '{"policies": [{"id": "x", "company_names": ["X"], "handling": "auto_apply", '
            '"documentation": "amazon.md", "application_limit": {"description": "d", "max_submissions": 1}}]}',
            encoding="utf-8",
        )
        with self.assertRaises(ValueError):
            load_company_policies(self.cfg["company_policies_path"])

    def test_reported_limit_defers_the_company_until_cleared(self) -> None:
        ingest_candidates(
            self.connection,
            [self.job("Amazon", 1, 20), self.job("Amazon", 2, 18), self.job("Acme", 3, 5)],
            self.run_id,
        )
        score_jobs(self.connection, self.cfg, self.run_id, now=NOW)
        first = self.claim("w")
        self.assertEqual(first["company"], "Amazon")
        capped = block_job(
            self.connection, first["id"], "w", "application_limit", "Limit of 10 reached",
            policies=self.policies,
        )
        self.assertEqual(capped["status"], "queued")
        self.assertIn("policy:amazon", active_limits(self.connection, self.policies))
        self.assertEqual({job["company"] for job in deferred_jobs(self.connection, self.policies)}, {"Amazon"})
        # Amazon is skipped while capped; Acme is claimed instead, then nothing is left.
        self.assertEqual(self.claim("w2")["company"], "Acme")
        self.assertIsNone(self.claim("w3"))
        body = digest_payload(self.connection, self.cfg, self.run_id, now=NOW)["email"]["body"]
        self.assertIn("Deferred by an application limit (still queued): Amazon (2)", body)
        report = outcome_report(self.connection, run_id=self.run_id, policies=self.policies)
        self.assertEqual(report["attempt_outcomes"]["blocked"], 1)
        self.assertEqual(len(report["deferred"]), 2)

        self.assertEqual(clear_limits(self.connection, "AWS", self.policies), 1)
        retry = self.claim("w4")
        self.assertEqual((retry["company"], retry["blocker_category"]), ("Amazon", None))

    def test_reported_limit_raises_the_bar_for_a_company_without_a_policy(self) -> None:
        ingest_candidates(self.connection, [self.job("Beta", 1, 20), self.job("Beta", 2, 8)], self.run_id)
        score_jobs(self.connection, self.cfg, self.run_id, now=NOW)
        first = self.claim("w")
        block_job(
            self.connection, first["id"], "w", "application_limit", "Cap", policies=self.policies,
            until=(NOW + timedelta(days=1)).isoformat(),
        )
        self.assertIsNone(self.claim("w", now=NOW))
        # The 83-fit Beta job drops back to scored; the 95 one waits for the cap to expire.
        self.assertEqual(self.statuses(), {("Beta", 95): "queued", ("Beta", 83): "scored"})
        self.assertEqual(self.claim("w", now=NOW + timedelta(days=2))["fit_score"], 95)

    def test_submission_window_is_enforced_from_the_ledger(self) -> None:
        ingest_candidates(
            self.connection, [self.job("ElevenLabs", 1, 20), self.job("ElevenLabs", 2, 19)], self.run_id
        )
        score_jobs(self.connection, self.cfg, self.run_id, now=NOW)
        job = self.claim("w")
        submit_job(
            self.connection, job["id"], "w", confirmation_url=job["application_url"],
            evidence="Thanks", resume_verified=True, submit_applications=True,
        )
        self.assertIsNone(self.claim("w"))
        limit = active_limits(self.connection, self.policies)["policy:elevenlabs"]
        self.assertEqual(limit["source"], "policy")
        later = datetime.now(timezone.utc) + timedelta(days=91)
        self.assertEqual(self.claim("w", now=later)["fit_score"], 94)


class SwapTests(unittest.TestCase):
    """Withdrawing a weaker active Amazon application to free a slot for a stronger queued one."""

    tearDown = CoreTests.tearDown
    job = ApplicationLimitTests.job

    def setUp(self) -> None:
        CoreTests.setUp(self)
        (self.policy_root / "amazon.md").write_text("# Amazon\n", encoding="utf-8")
        (self.policy_root / "policies.json").write_text(
            """{
  "policies": [
    {"id": "amazon", "company_names": ["Amazon", "AWS"], "handling": "auto_apply",
     "documentation": "amazon.md", "reason": "Ten active applications.",
     "application_limit": {"description": "Ten active applications per account.", "max_active": 3},
     "swap": {"min_fit_gain": 10, "max_withdrawals_per_run": 1}}
  ]
}""",
            encoding="utf-8",
        )
        self.policies = load_company_policies(self.cfg["company_policies_path"])
        # Submitted 76, 80, 95 (ATS ids 1-3); queued 93 and 92 (ids 4-5).
        ingest_candidates(
            self.connection,
            [self.job("Amazon", n, skill) for n, skill in ((1, 1), (2, 5), (3, 20), (4, 18), (5, 17))],
            self.run_id,
        )
        score_jobs(self.connection, self.cfg, self.run_id, now=NOW)
        for ats_id, fit in (("1", 76), ("2", 80), ("3", 95), ("4", 93), ("5", 92)):
            self.connection.execute("UPDATE jobs SET ats_job_id=? WHERE fit_score=?", (ats_id, fit))
        self.connection.execute(
            "UPDATE jobs SET status='submitted', submitted_at=? WHERE ats_job_id IN ('1', '2', '3')", (NOW.isoformat(),)
        )
        self.connection.execute("UPDATE jobs SET status='queued' WHERE ats_job_id IN ('4', '5')")
        self.ids = {
            row["ats_job_id"]: row["id"] for row in self.connection.execute("SELECT id, ats_job_id FROM jobs")
        }

    def active(self, *ids: str, status: str = "SUBMITTED") -> list[dict]:
        return [{"ats_job_id": job_id, "status": status} for job_id in ids]

    def plan(self, active: list[dict], **kwargs) -> dict:
        return swap_plan(self.connection, "Amazon", active, self.policies, run_id=self.run_id, **kwargs)

    def withdraw(self, ats_id: str, replacement_ats_id: str) -> dict:
        return withdraw_job(
            self.connection,
            self.ids[ats_id],
            replacement_job_id=self.ids[replacement_ats_id],
            evidence="Moved to Archived as Withdrawn",
            policies=self.policies,
            run_id=self.run_id,
            submit_applications=True,
        )

    def test_swap_needs_a_cap_on_active_applications(self) -> None:
        (self.policy_root / "policies.json").write_text(
            '{"policies": [{"id": "x", "company_names": ["X"], "handling": "auto_apply", '
            '"documentation": "amazon.md", "application_limit": {"description": "d"}, '
            '"swap": {"min_fit_gain": 10, "max_withdrawals_per_run": 1}}]}',
            encoding="utf-8",
        )
        with self.assertRaises(ValueError):
            load_company_policies(self.cfg["company_policies_path"])

    def test_plan_pairs_the_weakest_application_with_the_strongest_queued_job(self) -> None:
        plan = self.plan(self.active("1", "2", "3"))
        self.assertEqual(plan["free_slots"], 0)
        self.assertEqual(
            [(pair["withdraw"]["fit_score"], pair["replacement"]["fit_score"]) for pair in plan["pairs"]],
            [(76, 93)],
        )

    def test_plan_keeps_slots_it_must_not_touch(self) -> None:
        # Recruiter contact on 1; 2 has moved past plain submitted; an application the ledger never sent holds a slot.
        active = self.active("3", "unknown") + self.active("2", status="UNDER_REVIEW") + self.active("1")
        self.assertEqual(self.plan(active, keep=["1"])["pairs"], [])
        # A rejection archived 1: a slot is free, so nothing is withdrawn.
        plan = self.plan(self.active("2", "3"))
        self.assertEqual((plan["free_slots"], plan["pairs"]), (1, []))

    def test_withdraw_frees_the_slot_once_per_run(self) -> None:
        self.connection.execute(
            "INSERT INTO company_limits(company, company_key, reported_at, message) VALUES ('Amazon', 'policy:amazon', ?, 'cap')",
            (NOW.isoformat(),),
        )
        withdrawn = self.withdraw("1", "4")
        self.assertEqual((withdrawn["status"], withdrawn["limits_cleared"]), ("withdrawn", 1))
        self.assertEqual(active_limits(self.connection, self.policies), {})
        self.assertEqual(self.plan(self.active("2", "3", "x"))["withdrawals_left_this_run"], 0)
        with self.assertRaisesRegex(ValueError, "already withdrew"):
            self.withdraw("2", "5")
        report = outcome_report(self.connection, run_id=self.run_id, policies=self.policies)
        self.assertEqual(
            [(job["fit_score"], job["replacement_fit_score"]) for job in report["withdrawn"]], [(76, 93)]
        )
        body = digest_payload(self.connection, self.cfg, self.run_id, now=NOW)["email"]["body"]
        self.assertIn("(fit 76) for", body)

    def test_withdraw_refuses_a_small_gain_or_a_non_submitted_job(self) -> None:
        with self.assertRaisesRegex(ValueError, "not 10 above"):
            self.withdraw("3", "4")
        with self.assertRaisesRegex(ValueError, "only submitted"):
            self.withdraw("4", "5")


if __name__ == "__main__":
    unittest.main()
